"""Endpoints for the adiERP Backup page — System Manager only. Restore also asks for the
user's password and the site name, like any destructive operation should."""

import os
import re
import shutil

import frappe
from frappe import _
from frappe.utils import cint, get_bench_path, now_datetime

from adi_erp_backup import runner

CHUNK_LIMIT = 8 * 1024 * 1024  # per upload request


def _require():
	frappe.only_for("System Manager")


def _backups_dir():
	return frappe.get_site_path("private", "backups")


def _human(n):
	n = float(n or 0)
	for unit in ("B", "KB", "MB", "GB", "TB"):
		if n < 1024:
			return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
		n /= 1024
	return f"{n:.1f} PB"


def _busy_job():
	return frappe.db.get_value("ERP Backup Job", {"status": ["in", ["Queued", "Running"]]}, "name")


# ---------------------------------------------------------------- overview


@frappe.whitelist()
def overview() -> dict:
	_require()
	d = _backups_dir()
	groups = {}
	if os.path.isdir(d):
		for fn in os.listdir(d):
			m = re.match(r"^(\d{8}_\d{6})-", fn)
			if not m or "adierp-tmp" in fn:
				continue
			kind = ("db" if fn.endswith((".sql.gz", ".sql")) else "private" if fn.endswith(("private-files.tar", "private-files.tgz", "private-files.tar.gz"))
				else "public" if fn.endswith(("files.tar", "files.tgz", "files.tar.gz")) else "config" if fn.endswith(".json") else None)
			if not kind:
				continue
			g = groups.setdefault(m.group(1), {"stamp": m.group(1), "files": {}})
			size = os.path.getsize(os.path.join(d, fn))
			g["files"][kind] = {"name": fn, "size": _human(size), "bytes": size, "url": download_url(fn)}
	backups = sorted(groups.values(), key=lambda g: g["stamp"], reverse=True)
	for g in backups:
		s = g["stamp"]
		g["when"] = f"{s[6:8]}-{s[4:6]}-{s[0:4]} {s[9:11]}:{s[11:13]}"
	total, used, free = shutil.disk_usage(get_bench_path())
	jobs = frappe.get_all("ERP Backup Job", fields=["name", "job_type", "status", "stage", "progress", "with_files", "requested_by", "creation", "finished_on",
		"db_file", "public_file", "private_file", "error", "status_token"], order_by="creation desc", limit=15)
	for j in jobs:
		j["by"] = frappe.utils.get_fullname(j.requested_by) if j.requested_by else ""
	return {
		"site": frappe.local.site,
		"frappe": frappe.__version__,
		"apps": frappe.get_installed_apps(),
		"backups": backups[:30],
		"jobs": jobs,
		"busy": _busy_job(),
		"disk": {"free": _human(free), "free_bytes": free, "total": _human(total), "pct_used": round(used * 100 / total)},
		"db_size": _human(frappe.db.sql("select sum(data_length + index_length) from information_schema.tables where table_schema=%s", frappe.conf.db_name)[0][0] or 0),
	}


@frappe.whitelist()
def job_status(job: str) -> dict:
	_require()
	state = runner.read_state(job)
	if state:
		return state
	d = frappe.db.get_value("ERP Backup Job", job, ["name", "job_type", "status", "stage", "progress", "error", "log",
		"db_file", "public_file", "private_file", "config_file"], as_dict=True) or {}
	return {"job": d.get("name"), "type": d.get("job_type"), "status": d.get("status"), "stage": d.get("stage"), "progress": d.get("progress"),
		"error": d.get("error"), "log": d.get("log"), "outputs": {k: d.get(k + "_file") for k in ("db", "public", "private", "config")}} if d else {}


@frappe.whitelist(methods=["GET"])
def download(file: str):
	"""Byte-exact download of a backup file (as an attachment, never re-encoded by the browser).
	Behind nginx the file is handed to nginx (X-Accel-Redirect), so big files don't tie up a worker."""
	_require()
	from urllib.parse import quote

	from werkzeug.utils import send_file
	from werkzeug.wrappers import Response

	path = None
	for kind in ("db", "public", "config"):
		try:
			path = _resolve(file, kind)
			break
		except frappe.ValidationError:
			continue
	if not path:
		frappe.throw(_("File not found: {0}").format(file))
	name = os.path.basename(path)
	if frappe.request.headers.get("X-Use-X-Accel-Redirect"):
		response = Response()
		response.headers["X-Accel-Redirect"] = quote(f"/protected/private/backups/{name}")
		response.headers["Content-Type"] = "application/octet-stream"
	else:
		response = send_file(path, environ=frappe.request.environ, mimetype="application/octet-stream", as_attachment=True, download_name=name)
	response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
	response.headers["Cache-Control"] = "no-store"
	return response


def download_url(name):
	return f"/api/method/adi_erp_backup.api.download?file={name}"


# ---------------------------------------------------------------- backup


@frappe.whitelist(methods=["POST"])
def start_backup(with_files: int | str = 0) -> dict:
	_require()
	if _busy_job():
		frappe.throw(_("Another backup or restore is already running — wait for it to finish."))
	doc = frappe.get_doc({"doctype": "ERP Backup Job", "job_type": "Backup", "status": "Queued", "stage": "Queued",
		"with_files": cint(with_files), "requested_by": frappe.session.user, "started_on": now_datetime()})
	doc.insert(ignore_permissions=True)
	runner.new_state(doc.name, "Backup", with_files=cint(with_files), user=frappe.session.user)
	frappe.db.commit()
	frappe.enqueue("adi_erp_backup.runner.run_backup", queue="long", timeout=4 * 3600, job=doc.name, enqueue_after_commit=True)
	return {"job": doc.name}


# ---------------------------------------------------------------- uploads (chunked, straight into private/backups)

KIND_SUFFIX = {"db": "database", "public": "files", "private": "private-files", "config": "site_config_backup"}
STAMPED = re.compile(r"^\d{8}_\d{6}-")


def _check_ext(filename, kind):
	name = (filename or "").lower()
	allowed = runner.DB_EXTS if kind == "db" else (".json",) if kind == "config" else runner.FILE_EXTS
	if not name.endswith(allowed):
		label = {"db": _("Database backup"), "config": _("Site config backup")}.get(kind, _("Files backup"))
		frappe.throw(_("{0} must be one of: {1}").format(label, ", ".join(allowed)))
	if "/" in filename or "\\" in filename or filename.startswith(".") or ".." in filename:
		frappe.throw(_("Invalid file name"))


def _upload_name(filename, kind, stamp):
	"""Keep a Frappe backup's own name (so its database/files/config stay together in the list);
	anything else gets the usual <timestamp>-<site>-<kind> name."""
	if STAMPED.match(filename) and (kind != "public" or not filename.endswith(("private-files.tar", "private-files.tgz"))):
		return filename
	ext = next(e for e in (".sql.gz", ".sql", ".tgz", ".tar", ".json") if filename.lower().endswith(e))
	return f"{stamp}-{frappe.local.site.replace('.', '_')}-uploaded-{KIND_SUFFIX[kind]}{ext}"


def _check_start(data, filename, kind, total):
	"""Catch a wrong or damaged file on its first piece, before uploading the rest."""
	name = filename.lower()
	if name.endswith((".gz", ".tgz")) and data[:2] != b"\x1f\x8b":
		if data.lstrip().startswith(b"-- begin frappe metadata") or data.lstrip().startswith(b"--"):
			frappe.throw(_("This file is not really gzip — it was damaged when it was downloaded (the browser unpacked it and "
				"kept only the first lines). Download the backup again with the adiERP Backup download button, then upload that file."),
				title=_("Damaged backup file"))
		frappe.throw(_("{0} is not a valid gzip file.").format(filename), title=_("Damaged backup file"))
	if kind == "db" and total == 1 and len(data) < 1024:
		frappe.throw(_("{0} is only {1} bytes — far too small to be a database backup.").format(filename, len(data)), title=_("Damaged backup file"))


@frappe.whitelist(methods=["POST"])
def upload_chunk(upload_id: str, kind: str, filename: str, index: int | str, total: int | str, stamp: str) -> dict:
	"""Receive one piece of a backup file. Pieces arrive in order and are appended to a
	hidden .part file in private/backups, renamed to the final name after the last piece."""
	_require()
	if kind not in KIND_SUFFIX or not re.fullmatch(r"[a-z0-9]{8,40}", upload_id or "") or not re.fullmatch(r"\d{8}_\d{6}", stamp or ""):
		frappe.throw(_("Invalid upload"))
	_check_ext(filename, kind)
	chunk = frappe.request.files.get("chunk") if frappe.request and frappe.request.files else None
	if not chunk:
		frappe.throw(_("No data received"))
	data = chunk.stream.read(CHUNK_LIMIT + 1)
	if len(data) > CHUNK_LIMIT:
		frappe.throw(_("Chunk too large"))
	if cint(index) == 0:
		_check_start(data, filename, kind, cint(total))
	d = _backups_dir()
	os.makedirs(d, exist_ok=True)
	part = os.path.join(d, f".upload-{upload_id}.part")
	index = cint(index)
	with open(part, "wb" if index == 0 else "ab") as f:
		f.write(data)
	if index + 1 < cint(total):
		return {"ref": None, "done": False}
	final = _upload_name(filename, kind, stamp)
	dest = os.path.join(d, final)
	if os.path.exists(dest):
		if os.path.getsize(dest) == os.path.getsize(part):
			os.remove(part)  # same file uploaded again — use the one that's there
		else:
			os.remove(part)
			frappe.throw(_("A different file named {0} is already in the backups folder.").format(final))
	else:
		os.replace(part, dest)
	return {"ref": final, "done": True, "size": _human(os.path.getsize(dest))}


def _resolve(ref, kind):
	"""A file name in private/backups → absolute path (never outside that folder)."""
	if not ref:
		return None
	filename = ref.split(":", 1)[-1]
	_check_ext(filename, kind)
	path = os.path.realpath(os.path.join(_backups_dir(), filename))
	if os.path.dirname(path) != os.path.realpath(_backups_dir()) or not os.path.isfile(path):
		frappe.throw(_("File not found: {0}").format(filename))
	return path


# ---------------------------------------------------------------- restore


@frappe.whitelist(methods=["POST"])
def start_restore(db: str, confirm_site: str, password: str, public: str | None = None, private: str | None = None,
		config: str | None = None, restart: int | str = 0, staging: int | str = 0) -> dict:
	_require()
	from frappe.utils.password import check_password

	if (confirm_site or "").strip() != frappe.local.site:
		frappe.throw(_("Type the site name exactly ({0}) to confirm.").format(frappe.local.site))
	try:
		check_password(frappe.session.user, password)
	except frappe.AuthenticationError:
		frappe.throw(_("Your login password is incorrect."))
	if _busy_job():
		frappe.throw(_("Another backup or restore is already running — wait for it to finish."))

	sources = {"db": _resolve(db, "db"), "public": _resolve(public, "public"), "private": _resolve(private, "private"),
		"config": _resolve(config, "config")}
	if not sources["db"]:
		frappe.throw(_("Choose the database backup to restore."))
	need = sum(os.path.getsize(sources[k]) for k in ("db", "public", "private") if sources[k]) * 3 + 200 * 1024 * 1024
	free = shutil.disk_usage(get_bench_path()).free
	if free < need:
		frappe.throw(_("Not enough disk space: {0} free, about {1} needed (restore + safety backup). Free some space first.").format(_human(free), _human(need)))

	doc = frappe.get_doc({"doctype": "ERP Backup Job", "job_type": "Restore", "status": "Queued", "stage": "Queued",
		"with_files": 1 if (sources["public"] or sources["private"]) else 0, "restart_after": cint(restart),
		"requested_by": frappe.session.user, "started_on": now_datetime(), "status_token": frappe.generate_hash(length=32),
		"restore_db": os.path.basename(sources["db"]), "restore_public": os.path.basename(sources["public"] or "") or None,
		"restore_private": os.path.basename(sources["private"] or "") or None})
	doc.insert(ignore_permissions=True)
	runner.cleanup_status_files()
	runner.new_state(doc.name, "Restore", token=doc.status_token, sources=sources, restart=cint(restart), staging=cint(staging),
		user=frappe.session.user, with_files=doc.with_files)
	frappe.db.commit()
	frappe.enqueue("adi_erp_backup.runner.run_restore", queue="long", timeout=6 * 3600, job=doc.name, enqueue_after_commit=True)
	return {"job": doc.name, "token": doc.status_token}


def has_app_permission():
	return "System Manager" in frappe.get_roles()
