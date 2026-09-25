"""Endpoints for the adiSiteCare page — System Manager only. Restore also asks for the
user's password and the site name, like any destructive operation should."""

import os
import re
import shutil
import subprocess
import time

import frappe
from frappe import _
from frappe.utils import cint, get_bench_path, now_datetime

from adisitecare import runner

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
	"""A job counts as busy only while it is really alive (its live state says so and it moved recently)."""
	for name in frappe.get_all("SiteCare Job", {"status": ["in", ["Queued", "Running"]]}, pluck="name", order_by="creation desc"):
		state = runner.read_state(name)
		if state and state.get("status") in ("Queued", "Running") and time.time() - (state.get("now_ts") or 0) < 2 * 3600:
			return name
	return None


def _stats(backups):
	since = frappe.utils.add_days(now_datetime(), -30)
	last = frappe.get_all("SiteCare Job", fields=["status"], order_by="creation desc", limit=1)
	return {
		"backup_bytes": sum(f["bytes"] for g in backups for f in g["files"].values()),
		"last_restore": frappe.db.get_value("SiteCare Job", {"job_type": "Restore", "status": "Success"}, "creation", order_by="creation desc"),
		"ok_30": frappe.db.count("SiteCare Job", {"status": "Success", "creation": [">=", since]}),
		"failed_30": frappe.db.count("SiteCare Job", {"status": "Failed", "creation": [">=", since]}),
		"last_failed": bool(last and last[0].status == "Failed"),
	}


def _scheduler_disabled():
	"""Scheduler switched off in System Settings (bench scheduler disable) or by disable_scheduler in config."""
	return bool(cint(frappe.get_conf().get("disable_scheduler")) or not cint(frappe.get_system_settings("enable_scheduler")))


def _health():
	conf = runner.site_config()
	common = frappe.get_conf()
	pending = frappe.db.count("Email Queue", {"status": "Not Sent"}) if frappe.db.table_exists("Email Queue") else 0
	workers = None
	try:
		from frappe.utils.background_jobs import get_workers

		workers = len(get_workers())
	except Exception:
		pass
	cache = runner._cache()
	restart = cache.get_value(f"{runner.APP}:restart_ok")
	if restart is None:
		restart = bool(runner.restart_available())
		cache.set_value(f"{runner.APP}:restart_ok", restart, expires_in_sec=600)
	return {
		"maintenance": bool(cint(conf.get("maintenance_mode"))),
		"scheduler_paused": bool(cint(conf.get("pause_scheduler")) or cint(common.get("pause_scheduler")) or _scheduler_disabled()),
		"scheduler_disabled": _scheduler_disabled(),
		"scheduler_paused_bench": bool(cint(common.get("pause_scheduler")) and not cint(conf.get("pause_scheduler"))),
		"emails_muted": bool(cint(conf.get("mute_emails"))),
		"emails_muted_bench": bool(cint(common.get("mute_emails")) and not cint(conf.get("mute_emails"))),
		"pending_emails": pending,
		"workers": workers,
		"restart_available": restart,
		"dev_mode": bool(cint(frappe.get_conf().get("developer_mode"))),
		"supervisor": bool(shutil.which("supervisorctl")),
		"bench_start": bool(_honcho_pid()),
		"os_user": _os_user(),
	}


# ---------------------------------------------------------------- overview


@frappe.whitelist()
def overview() -> dict:
	_require()
	d = _backups_dir()
	groups = {}
	if os.path.isdir(d):
		for fn in os.listdir(d):
			m = re.match(r"^(\d{8}_\d{6})-", fn)
			if not m or "sitecare-tmp" in fn:
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
	jobs = frappe.get_all("SiteCare Job", fields=["name", "job_type", "action", "status", "stage", "progress", "with_files", "requested_by", "creation", "finished_on",
		"db_file", "public_file", "private_file", "error", "status_token", "restore_db", "restore_public", "restore_private", "started_on"], order_by="creation desc", limit=15)
	for j in jobs:
		j["by"] = frappe.utils.get_fullname(j.requested_by) if j.requested_by else ""
	return {
		"site": frappe.local.site,
		"frappe": frappe.__version__,
		"apps": frappe.get_installed_apps(),
		"backups": backups[:30],
		"jobs": jobs,
		"busy": _busy_job(),
		"stats": _stats(backups),
		"health": _health(),
		"disk": {"free": _human(free), "free_bytes": free, "total": _human(total), "pct_used": round(used * 100 / total)},
		"db_size": _human(frappe.db.sql("select sum(data_length + index_length) from information_schema.tables where table_schema=%s", frappe.conf.db_name)[0][0] or 0),
	}


@frappe.whitelist()
def job_status(job: str) -> dict:
	_require()
	state = runner.read_state(job)
	if state:
		return state
	d = frappe.db.get_value("SiteCare Job", job, ["name", "job_type", "status", "stage", "progress", "error", "log",
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
	return f"/api/method/adisitecare.api.download?file={name}"


# ---------------------------------------------------------------- backup


@frappe.whitelist(methods=["POST"])
def start_backup(with_files: int | str = 0) -> dict:
	_require()
	if _busy_job():
		frappe.throw(_("Another backup or restore is already running — wait for it to finish."))
	doc = frappe.get_doc({"doctype": "SiteCare Job", "job_type": "Backup", "status": "Queued", "stage": "Queued",
		"with_files": cint(with_files), "requested_by": frappe.session.user, "started_on": now_datetime()})
	doc.insert(ignore_permissions=True)
	runner.new_state(doc.name, "Backup", with_files=cint(with_files), user=frappe.session.user,
		title=_("Backup with files") if cint(with_files) else _("Database backup"), steps=runner.make_steps(runner.BACKUP_STEPS))
	frappe.db.commit()
	frappe.enqueue("adisitecare.runner.run_backup", queue="long", timeout=4 * 3600, job=doc.name, enqueue_after_commit=True)
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
				"kept only the first lines). Download the backup again with the adiSiteCare download button, then upload that file."),
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

	doc = frappe.get_doc({"doctype": "SiteCare Job", "job_type": "Restore", "status": "Queued", "stage": "Queued",
		"with_files": 1 if (sources["public"] or sources["private"]) else 0, "restart_after": cint(restart),
		"requested_by": frappe.session.user, "started_on": now_datetime(), "status_token": frappe.generate_hash(length=32),
		"restore_db": os.path.basename(sources["db"]), "restore_public": os.path.basename(sources["public"] or "") or None,
		"restore_private": os.path.basename(sources["private"] or "") or None})
	doc.insert(ignore_permissions=True)
	runner.cleanup_status_files()
	steps = runner.RESTORE_STEPS + ([("restart", "Restart bench")] if cint(restart) else [])
	runner.new_state(doc.name, "Restore", token=doc.status_token, sources=sources, restart=cint(restart), staging=cint(staging), created=str(doc.creation),
		user=frappe.session.user, with_files=doc.with_files, title=_("Restore {0}").format(os.path.basename(sources["db"])),
		steps=runner.make_steps(steps))
	frappe.db.commit()
	frappe.enqueue("adisitecare.runner.run_restore", queue="long", timeout=6 * 3600, job=doc.name, enqueue_after_commit=True)
	return {"job": doc.name, "token": doc.status_token}


# ---------------------------------------------------------------- tools


@frappe.whitelist(methods=["POST"])
def start_action(action: str) -> dict:
	"""Migrate / clear cache / restart / all after-restore tasks — as a job with the live terminal."""
	_require()
	if action not in runner.ACTIONS:
		frappe.throw(_("Unknown action"))
	if _busy_job():
		frappe.throw(_("Another job is already running — wait for it to finish."))
	title, steps = runner.ACTIONS[action]
	doc = frappe.get_doc({"doctype": "SiteCare Job", "job_type": "Action", "action": title, "status": "Queued", "stage": "Queued",
		"requested_by": frappe.session.user, "started_on": now_datetime()})
	doc.insert(ignore_permissions=True)
	runner.new_state(doc.name, "Action", action=action, title=title, user=frappe.session.user,
		steps=runner.make_steps([(k, label) for k, label, *_ in steps]))
	frappe.db.commit()
	frappe.enqueue("adisitecare.runner.run_action", queue="long", timeout=2 * 3600, job=doc.name, enqueue_after_commit=True)
	return {"job": doc.name}


@frappe.whitelist(methods=["POST"])
def set_emails(muted: int | str, discard_pending: int | str = 0) -> dict:
	"""Mute / unmute outgoing email for this site (site_config: mute_emails).
	While muted, emails wait in the Email Queue; unmuting sends them — unless they are discarded first."""
	_require()
	from frappe.installer import update_site_config

	discarded = 0
	if not cint(muted) and cint(discard_pending):
		discarded = frappe.db.count("Email Queue", {"status": "Not Sent"})
		frappe.db.sql("""update `tabEmail Queue` set status='Error', error='Discarded by adiSiteCare before unmuting (staging copy)'
			where status='Not Sent'""")
		frappe.db.commit()
	update_site_config("mute_emails", 1 if cint(muted) else 0)
	return {"health": _health(), "discarded": discarded}


@frappe.whitelist(methods=["POST"])
def set_scheduler(paused: int | str) -> dict:
	"""Pause / resume scheduled jobs for this site (site_config: pause_scheduler)."""
	_require()
	from frappe.installer import update_site_config

	update_site_config("pause_scheduler", 1 if cint(paused) else 0)
	if not cint(paused) and not cint(frappe.get_system_settings("enable_scheduler")):
		from frappe.utils.scheduler import enable_scheduler

		enable_scheduler()  # also switched off in System Settings — switch it on there too
		frappe.db.commit()
	return {"health": _health()}


@frappe.whitelist(methods=["POST"])
def start_maintenance(minutes: int | str) -> dict:
	"""Maintenance mode for a fixed time. While it's on, Frappe blocks every request (this page too),
	so it can't be switched off from here — a background job switches it off when the time is up."""
	_require()
	minutes = cint(minutes)
	if minutes not in (5, 15, 30, 60):
		frappe.throw(_("Choose 5, 15, 30 or 60 minutes."))
	if _busy_job():
		frappe.throw(_("Another job is already running — wait for it to finish."))
	doc = frappe.get_doc({"doctype": "SiteCare Job", "job_type": "Action", "action": _("Maintenance window"), "status": "Queued",
		"stage": "Queued", "requested_by": frappe.session.user, "started_on": now_datetime(), "status_token": frappe.generate_hash(length=32)})
	doc.insert(ignore_permissions=True)
	runner.cleanup_status_files()
	runner.new_state(doc.name, "Action", action="maintenance", title=_("Maintenance mode · {0} min").format(minutes), minutes=minutes,
		token=doc.status_token, user=frappe.session.user,
		steps=runner.make_steps([("on", "Maintenance mode on"), ("window", f"Maintenance window · {minutes} min"), ("off", "Maintenance mode off")]))
	frappe.db.commit()
	frappe.enqueue("adisitecare.runner.run_maintenance", queue="long", timeout=minutes * 60 + 900, job=doc.name, enqueue_after_commit=True)
	return {"job": doc.name, "token": doc.status_token}


def _os_user():
	import getpass

	try:
		return getpass.getuser()
	except Exception:
		return ""


def _honcho_pid():
	"""PID of `bench start` (honcho) if this web process runs under it — i.e. a development bench."""
	pid = os.getpid()
	for _ in range(8):
		out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
		if not out.isdigit() or int(out) <= 1:
			return None
		pid = int(out)
		cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
		if "honcho" in cmd:
			return pid
	return None


@frappe.whitelist(methods=["POST"])
def restart_dev() -> dict:
	"""Development bench: stop `bench start` and start it again in the background (log: logs/bench-start.log)."""
	_require()
	import shlex

	pid = _honcho_pid()
	if not pid:
		frappe.throw(_("This site isn't running under bench start, so it can't be restarted from here."))
	if _busy_job():
		frappe.throw(_("Another job is running — wait for it to finish."))
	bench_path = get_bench_path()
	bench_cli = shutil.which("bench") or os.path.expanduser("~/.local/bin/bench")
	doc = frappe.get_doc({"doctype": "SiteCare Job", "job_type": "Action", "action": _("Restart bench"), "status": "Success",
		"stage": _("Restart started"), "progress": 100, "requested_by": frappe.session.user, "started_on": now_datetime(),
		"finished_on": now_datetime(), "log": f"$ bench start   (stopped PID {pid}, started again in the background)\n"
		"↻ Output: logs/bench-start.log"})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	script = (f"kill -INT {pid}; for i in $(seq 1 60); do kill -0 {pid} 2>/dev/null || break; sleep 1; done; sleep 2; "
		f"cd {shlex.quote(bench_path)} && echo \"--- restarted by adiSiteCare $(date) ---\" >> logs/bench-start.log && "
		f"exec {shlex.quote(bench_cli)} start >> logs/bench-start.log 2>&1")
	subprocess.Popen(["/bin/sh", "-c", script], cwd=bench_path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL, start_new_session=True)
	return {"job": doc.name, "log": "logs/bench-start.log"}


def _sudo(cmd, password, timeout=40):
	"""Run one command with sudo, the password fed on stdin (-S) — never on the command line, never stored."""
	return subprocess.run(["sudo", "-S", "-k", "-p", "", *cmd], input=password + "\n", capture_output=True, text=True, timeout=timeout)


@frappe.whitelist(methods=["POST"])
def restart_with_password(sudo_password: str) -> dict:
	"""bench restart for servers where supervisor needs sudo: restart this bench's web + worker programs
	with `sudo supervisorctl restart`. The password is used for this request only — not saved, not logged."""
	_require()
	password = sudo_password
	frappe.form_dict.pop("sudo_password", None)  # keep it out of any error log / request dump
	if not shutil.which("supervisorctl"):
		frappe.throw(_("Supervisor isn't installed on this server (a development bench with bench start?). "
			"Stop bench start with Ctrl+C and run bench start again."))
	if _busy_job():
		frappe.throw(_("Another job is running — wait for it to finish."))
	try:
		status = _sudo(["supervisorctl", "status"], password)
	except subprocess.TimeoutExpired:
		frappe.throw(_("sudo didn't answer — check that this user can use sudo."))
	err = (status.stderr or "").lower()
	if status.returncode not in (0, 3) or "incorrect password" in err or "sorry" in err:
		if "incorrect password" in err or "sorry" in err or "password" in err:
			frappe.throw(_("Wrong password, or this user ({0}) may not use sudo.").format(_os_user()), title=_("Restart failed"))
		frappe.throw(_("supervisorctl failed: {0}").format(frappe.utils.escape_html((status.stderr or status.stdout)[:300])), title=_("Restart failed"))
	bench = os.path.basename(get_bench_path())
	groups = sorted({line.split()[0].split(":")[0] for line in status.stdout.splitlines()
		if line.strip() and line.split()[0].startswith(bench)})
	groups = [g for g in groups if "redis" not in g]  # like bench restart: web + workers, not redis
	if not groups:
		frappe.throw(_("No supervisor programs found for this bench ({0}).").format(bench))
	doc = frappe.get_doc({"doctype": "SiteCare Job", "job_type": "Action", "action": _("Restart bench"), "status": "Success",
		"stage": _("Restart started"), "progress": 100, "requested_by": frappe.session.user, "started_on": now_datetime(),
		"finished_on": now_datetime(), "log": "$ sudo supervisorctl restart " + " ".join(g + ":" for g in groups) + "\n↻ Restart started."})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	# detached, last — it restarts this very web process too
	proc = subprocess.Popen(["sudo", "-S", "-k", "-p", "", "supervisorctl", "restart", *[g + ":" for g in groups]],
		stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, text=True)
	proc.stdin.write(password + "\n")
	proc.stdin.close()
	del password
	return {"groups": groups, "job": doc.name}


def has_app_permission():
	return "System Manager" in frappe.get_roles()
