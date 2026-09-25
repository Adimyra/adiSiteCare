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
			if not m:
				continue
			kind = ("db" if fn.endswith((".sql.gz", ".sql")) else "private" if fn.endswith(("private-files.tar", "private-files.tgz", "private-files.tar.gz"))
				else "public" if fn.endswith(("files.tar", "files.tgz", "files.tar.gz")) else "config" if fn.endswith(".json") else None)
			if not kind:
				continue
			g = groups.setdefault(m.group(1), {"stamp": m.group(1), "files": {}})
			size = os.path.getsize(os.path.join(d, fn))
			g["files"][kind] = {"name": fn, "size": _human(size), "bytes": size, "url": f"/backups/{fn}"}
	backups = sorted(groups.values(), key=lambda g: g["stamp"], reverse=True)
	for g in backups:
		s = g["stamp"]
		g["when"] = f"{s[6:8]}-{s[4:6]}-{s[0:4]} {s[9:11]}:{s[11:13]}"
	total, used, free = shutil.disk_usage(get_bench_path())
	jobs = frappe.get_all("ERP Backup Job", fields=["name", "job_type", "status", "stage", "progress", "with_files", "requested_by", "creation", "finished_on",
		"db_file", "public_file", "private_file", "error", "status_token"], order_by="creation desc", limit=15)
	for j in jobs:
		j["by"] = frappe.utils.get_fullname(j.requested_by) if j.requested_by else ""
	conf = frappe.get_conf()
	return {
		"site": frappe.local.site,
		"frappe": frappe.__version__,
		"apps": frappe.get_installed_apps(),
		"backups": backups[:30],
		"jobs": jobs,
		"busy": _busy_job(),
		"disk": {"free": _human(free), "free_bytes": free, "total": _human(total), "pct_used": round(used * 100 / total)},
		"root_password_set": bool(conf.get("root_password")),
		"db_size": _human(frappe.db.sql("select sum(data_length + index_length) from information_schema.tables where table_schema=%s", frappe.conf.db_name)[0][0] or 0),
	}


@frappe.whitelist()
def job_status(job: str) -> dict:
	_require()
	return runner.read_state(job) or {}


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


# ---------------------------------------------------------------- uploads (chunked, straight to disk)


def _check_ext(filename, kind):
	name = (filename or "").lower()
	allowed = runner.DB_EXTS if kind == "db" else runner.FILE_EXTS
	if not name.endswith(allowed):
		frappe.throw(_("{0} must be one of: {1}").format(_("Database backup") if kind == "db" else _("Files backup"), ", ".join(allowed)))
	if "/" in filename or "\\" in filename or filename.startswith("."):
		frappe.throw(_("Invalid file name"))


@frappe.whitelist(methods=["POST"])
def upload_chunk(upload_id: str, kind: str, filename: str, index: int | str, total: int | str) -> dict:
	"""Receive one piece of a backup file. Pieces arrive in order and are appended."""
	_require()
	if kind not in ("db", "public", "private") or not re.fullmatch(r"[a-z0-9]{8,40}", upload_id or ""):
		frappe.throw(_("Invalid upload"))
	_check_ext(filename, kind)
	chunk = frappe.request.files.get("chunk") if frappe.request and frappe.request.files else None
	if not chunk:
		frappe.throw(_("No data received"))
	data = chunk.stream.read(CHUNK_LIMIT + 1)
	if len(data) > CHUNK_LIMIT:
		frappe.throw(_("Chunk too large"))
	path = os.path.join(runner.work_dir("uploads", upload_id), filename)
	index = cint(index)
	with open(path, "wb" if index == 0 else "ab") as f:
		f.write(data)
	done = index + 1 >= cint(total)
	return {"ref": f"upload:{upload_id}/{filename}" if done else None, "size": os.path.getsize(path), "done": done}


def _resolve(ref, kind):
	"""upload:<id>/<file> (uploaded here) or backup:<file> (already in private/backups) → absolute path."""
	if not ref:
		return None
	if ref.startswith("upload:"):
		upload_id, _sep, filename = ref[7:].partition("/")
		_check_ext(filename, kind)
		path = os.path.join(runner.work_dir("uploads", upload_id), filename)
	elif ref.startswith("backup:"):
		filename = ref[7:]
		_check_ext(filename, kind)
		path = os.path.join(_backups_dir(), filename)
	else:
		frappe.throw(_("Invalid source"))
	real = os.path.realpath(path)
	if not real.startswith(os.path.realpath(frappe.get_site_path("private"))) or not os.path.isfile(real):
		frappe.throw(_("File not found: {0}").format(os.path.basename(path)))
	return real


# ---------------------------------------------------------------- restore


@frappe.whitelist(methods=["POST"])
def start_restore(db: str, confirm_site: str, password: str, public: str | None = None, private: str | None = None,
		restart: int | str = 0, db_root_password: str | None = None) -> dict:
	_require()
	from frappe.utils.password import check_password

	if (confirm_site or "").strip() != frappe.local.site:
		frappe.throw(_("Type the site name exactly ({0}) to confirm.").format(frappe.local.site))
	try:
		check_password(frappe.session.user, password)
	except frappe.AuthenticationError:
		frappe.throw(_("Your password is incorrect."))
	if _busy_job():
		frappe.throw(_("Another backup or restore is already running — wait for it to finish."))
	if not db_root_password and not frappe.get_conf().get("root_password"):
		frappe.throw(_("Enter the MariaDB root password — restore needs it to recreate the database (it is not saved)."))

	sources = {"db": _resolve(db, "db"), "public": _resolve(public, "public"), "private": _resolve(private, "private")}
	if not sources["db"]:
		frappe.throw(_("Choose the database backup to restore."))
	need = sum(os.path.getsize(p) for p in sources.values() if p) * 3 + 200 * 1024 * 1024
	free = shutil.disk_usage(get_bench_path()).free
	if free < need:
		frappe.throw(_("Not enough disk space: {0} free, about {1} needed (restore + safety backup). Free some space first.").format(_human(free), _human(need)))

	doc = frappe.get_doc({"doctype": "ERP Backup Job", "job_type": "Restore", "status": "Queued", "stage": "Queued",
		"with_files": 1 if (sources["public"] or sources["private"]) else 0, "restart_after": cint(restart),
		"requested_by": frappe.session.user, "started_on": now_datetime(), "status_token": frappe.generate_hash(length=32),
		"restore_db": os.path.basename(sources["db"]), "restore_public": os.path.basename(sources["public"] or "") or None,
		"restore_private": os.path.basename(sources["private"] or "") or None})
	doc.insert(ignore_permissions=True)

	# copy the sources next to the job — they must survive the restore (which replaces private/files)
	job_dir = runner.work_dir("restore", doc.name)
	copied = {}
	for key, path in sources.items():
		if path:
			dest = os.path.join(job_dir, os.path.basename(path))
			shutil.copy2(path, dest)
			copied[key] = dest
	runner.new_state(doc.name, "Restore", token=doc.status_token, sources=copied, restart=cint(restart), user=frappe.session.user,
		with_files=doc.with_files)
	if db_root_password:
		frappe.cache().set_value(f"{runner.APP}:rootpwd:{doc.name}", db_root_password, expires_in_sec=3 * 3600)
	frappe.db.commit()
	frappe.enqueue("adi_erp_backup.runner.run_restore", queue="long", timeout=6 * 3600, job=doc.name, enqueue_after_commit=True)
	return {"job": doc.name, "token": doc.status_token}


def has_app_permission():
	return "System Manager" in frappe.get_roles()
