"""The work itself: backups and restores run as background jobs that call the same
bench/frappe commands you would type in a terminal, stream their output, and keep
their progress in a JSON file.

Progress lives in files, not the database, because a restore replaces the database
(and maintenance mode blocks every request to the site while it runs):
  sites/<site>/private/adi_erp_backup/jobs/<job>.json   full state + log (System Manager only)
  sites/<site>/public/files/adierp-status/<token>.json  progress mirror the page can read
                                                         while the site is in maintenance
Works on Frappe v15 and v16.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

import frappe
from frappe.utils import get_bench_path, now_datetime

APP = "adi_erp_backup"
DB_EXTS = (".sql.gz", ".sql")
FILE_EXTS = (".tar", ".tar.gz", ".tgz")


# ---------------------------------------------------------------- paths & state


def work_dir(*parts):
	path = frappe.get_site_path("private", APP, *parts)
	os.makedirs(path if not os.path.splitext(path)[1] else os.path.dirname(path), exist_ok=True)
	return path


def state_path(job):
	return os.path.join(work_dir("jobs"), f"{job}.json")


def public_status_path(token):
	d = frappe.get_site_path("public", "files", "adierp-status")
	os.makedirs(d, exist_ok=True)
	return os.path.join(d, f"{token}.json")


def read_state(job):
	try:
		with open(state_path(job)) as f:
			return json.load(f)
	except Exception:
		return None


def write_state(state):
	state["updated"] = str(now_datetime())
	tmp = state_path(state["job"]) + ".tmp"
	with open(tmp, "w") as f:
		json.dump(state, f, indent=1, default=str)
	os.replace(tmp, state_path(state["job"]))
	if state.get("token"):  # mirror without anything sensitive
		mirror = {k: state.get(k) for k in ("job", "type", "status", "stage", "progress", "error", "updated", "finished", "outputs", "restarted")}
		mirror["log"] = "\n".join((state.get("log") or "").splitlines()[-150:])
		pub = public_status_path(state["token"])
		with open(pub + ".tmp", "w") as f:
			json.dump(mirror, f, default=str)
		os.replace(pub + ".tmp", pub)


def new_state(job, kind, token=None, **extra):
	state = {"job": job, "type": kind, "status": "Queued", "stage": "Queued", "progress": 0, "log": "", "error": "",
		"started": None, "finished": None, "outputs": {}, "token": token, **extra}
	write_state(state)
	return state


# ---------------------------------------------------------------- running commands

SECRET = re.compile(r"(--db-root-password\s+)(\S+)")


def _frappe_cmd(*args):
	"""`bench --site <site> <args>` without needing the bench CLI on PATH (works under supervisor too)."""
	return [os.path.join(get_bench_path(), "env", "bin", "python"), "-m", "frappe.utils.bench_helper", "frappe", "--site", frappe.local.site, *args]


def run(state, cmd, stage, start, end, expect_seconds=60):
	"""Run one command, stream its output into the log, move progress from start→end. Raises on failure."""
	state.update(stage=stage, progress=start)
	shown = f"bench --site {frappe.local.site} " + " ".join(cmd[6:]) if "frappe.utils.bench_helper" in cmd else " ".join(cmd)
	log(state, "\n$ " + SECRET.sub(r"\1********", shown))
	proc = subprocess.Popen(cmd, cwd=os.path.join(get_bench_path(), "sites"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
		stdin=subprocess.DEVNULL, text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"})
	t0 = time.time()
	last_write = 0
	for line in proc.stdout:
		state["log"] += SECRET.sub(r"\1********", line)
		elapsed = time.time() - t0
		state["progress"] = min(end - 1, start + int((end - start) * min(0.95, elapsed / max(expect_seconds, 1))))
		if time.time() - last_write > 1:
			write_state(state)
			last_write = time.time()
	code = proc.wait()
	state["progress"] = end
	write_state(state)
	if code != 0:
		raise RuntimeError(f"“{stage}” failed (exit code {code}) — see the log above.")


def log(state, text):
	state["log"] += text.rstrip("\n") + "\n"
	write_state(state)


def parse_backup_output(text):
	"""Frappe prints e.g.  Database: ./site/private/backups/2026...-database.sql.gz 2.4MiB"""
	out = {}
	for key, label in (("config", "Config"), ("db", "Database"), ("public", "Public"), ("private", "Private")):
		m = None
		for m in re.finditer(rf"^\s*{label}\s*:\s*(\S+)", text, re.M):
			pass
		if m:
			out[key] = os.path.basename(m.group(1))
	return out


def site_config():
	with open(frappe.get_site_path("site_config.json")) as f:
		return json.load(f)


# ---------------------------------------------------------------- DB record (best effort — the DB may be mid-restore)


def save_record(state, fields=None):
	try:
		frappe.db.rollback()
		if not frappe.db.table_exists("ERP Backup Job"):
			return
		values = {
			"status": state["status"], "stage": state["stage"], "progress": state["progress"], "log": state["log"][-60000:],
			"error": state.get("error") or None, "finished_on": state.get("finished"), **(fields or {}),
		}
		if frappe.db.exists("ERP Backup Job", state["job"]):
			frappe.db.set_value("ERP Backup Job", state["job"], values, update_modified=True)
		else:  # the job's own record went away with the restored database — put it back
			doc = frappe.get_doc({"doctype": "ERP Backup Job", "job_type": state["type"], "requested_by": state.get("user"),
				"with_files": state.get("with_files", 0), "restart_after": state.get("restart", 0), "started_on": state.get("started"),
				"status_token": state.get("token"), **values})
			doc.name = state["job"]
			doc.flags.name_set = True
			doc.db_insert()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()


def _reconnect():
	"""After a restore the old database connection is gone — open a fresh one."""
	try:
		frappe.db.close()
	except Exception:
		pass
	frappe.local.db = None
	frappe.connect(frappe.local.site)


# ---------------------------------------------------------------- backup


def run_backup(job):
	state = read_state(job) or new_state(job, "Backup")
	state.update(status="Running", started=str(now_datetime()))
	save_record(state, {"started_on": state["started"]})
	try:
		args = ["backup"] + (["--with-files"] if state.get("with_files") else [])
		run(state, _frappe_cmd(*args), "Taking backup", 5, 95, expect_seconds=240 if state.get("with_files") else 60)
		outputs = parse_backup_output(state["log"])
		if not outputs.get("db"):
			raise RuntimeError("The backup finished but no database file was reported.")
		state.update(outputs=outputs, status="Success", stage="Backup complete", progress=100, finished=str(now_datetime()))
		write_state(state)
		save_record(state, {"db_file": outputs.get("db"), "public_file": outputs.get("public"), "private_file": outputs.get("private"), "config_file": outputs.get("config")})
	except Exception as e:
		state.update(status="Failed", stage="Backup failed", error=str(e), finished=str(now_datetime()))
		write_state(state)
		save_record(state)
	_notify(state)


# ---------------------------------------------------------------- restore


def run_restore(job):
	state = read_state(job)
	if not state:
		return
	state.update(status="Running", started=str(now_datetime()))
	save_record(state, {"started_on": state["started"]})
	src = state["sources"]
	maintenance_on = restored = False
	root_pwd = frappe.cache().get_value(f"{APP}:rootpwd:{job}")
	frappe.cache().delete_value(f"{APP}:rootpwd:{job}")
	try:
		# 1. pre-flight: the files are there and look right
		state.update(stage="Checking the backup files", progress=3)
		log(state, "Checking the backup files…")
		from frappe.installer import is_downgrade, is_partial, validate_database_sql

		db = src["db"]
		if not os.path.isfile(db):
			raise RuntimeError("The database backup file is missing.")
		if db.endswith(".gz") and subprocess.run(["gzip", "-t", db], capture_output=True).returncode != 0:
			raise RuntimeError("The database backup is not a valid .gz file (corrupt or incomplete upload).")
		if is_partial(db):
			raise RuntimeError("This is a partial backup — it can't restore a whole site.")
		if is_downgrade(db):
			log(state, "⚠ This backup is from an older Frappe version — migrate will upgrade it.")
		validate_database_sql(db, _raise=True)
		for key in ("public", "private"):
			if src.get(key) and not os.path.isfile(src[key]):
				raise RuntimeError(f"The {key} files backup is missing.")
		log(state, "✓ Backup files look good.")

		# 2. safety backup of the site as it is now — the undo point
		run(state, _frappe_cmd("backup", *(["--with-files"] if (src.get("public") or src.get("private")) else [])),
			"Safety backup of the current site", 5, 25, expect_seconds=120)
		safety = parse_backup_output(state["log"])
		state["outputs"]["safety"] = safety
		log(state, f"✓ Safety backup: {safety.get('db')}")

		# 3. maintenance mode ON (and make sure it really is), scheduler paused
		run(state, _frappe_cmd("set-maintenance-mode", "on"), "Maintenance mode on", 26, 30, 10)
		maintenance_on = True
		if not int(site_config().get("maintenance_mode") or 0):
			raise RuntimeError("Maintenance mode did not switch on — stopping before touching the database.")
		log(state, "✓ Maintenance mode is ON — users see the maintenance page.")
		run(state, _frappe_cmd("set-config", "pause_scheduler", "1"), "Pausing the scheduler", 30, 33, 10)

		# 4. restore
		args = ["restore", db, "--force"]
		if src.get("public"):
			args += ["--with-public-files", src["public"]]
		if src.get("private"):
			args += ["--with-private-files", src["private"]]
		if root_pwd:
			args += ["--db-root-password", root_pwd]
		run(state, _frappe_cmd(*args), "Restoring the database" + (" and files" if (src.get("public") or src.get("private")) else ""), 34, 70, expect_seconds=300)
		restored = True

		# 5. keep this tool on the site even if the backup is from before it was installed
		apps = subprocess.run(_frappe_cmd("list-apps"), cwd=os.path.join(get_bench_path(), "sites"), capture_output=True, text=True).stdout
		if APP not in apps:
			run(state, _frappe_cmd("install-app", APP), "Re-installing adiERP Backup", 70, 74, 60)

		# 6. migrate + caches
		run(state, _frappe_cmd("migrate"), "Migrating", 74, 92, expect_seconds=300)
		run(state, _frappe_cmd("clear-cache"), "Clearing cache", 92, 94, 20)
		run(state, _frappe_cmd("clear-website-cache"), "Clearing website cache", 94, 95, 20)

		# 7. back online
		run(state, _frappe_cmd("set-config", "pause_scheduler", "0"), "Resuming the scheduler", 95, 96, 10)
		run(state, _frappe_cmd("set-maintenance-mode", "off"), "Maintenance mode off", 96, 98, 10)
		maintenance_on = False
		log(state, "✓ Site is back online. Everyone needs to sign in again.")

		state.update(status="Success", stage="Restore complete", progress=100, finished=str(now_datetime()))
		write_state(state)
		_reconnect()
		save_record(state, {"safety_backup": json.dumps(safety), "restore_db": os.path.basename(db),
			"restore_public": os.path.basename(src.get("public") or "") or None, "restore_private": os.path.basename(src.get("private") or "") or None})

		# 8. optional restart — last, detached, so it can't cut this job short
		if state.get("restart"):
			bench = shutil.which("bench") or os.path.expanduser("~/.local/bin/bench")
			try:
				subprocess.Popen([bench, "restart"], cwd=get_bench_path(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
				state["restarted"] = True
				log(state, "↻ Restart requested (bench restart).")
			except Exception as e:
				log(state, f"⚠ Couldn't run bench restart ({e}) — restart the services yourself if needed.")
	except Exception as e:
		recovery = ""
		if maintenance_on and not restored:
			# nothing was changed yet — put the site back online
			for args in (("set-config", "pause_scheduler", "0"), ("set-maintenance-mode", "off")):
				subprocess.run(_frappe_cmd(*args), cwd=os.path.join(get_bench_path(), "sites"), capture_output=True)
			recovery = "Nothing was changed — the site is back online."
		elif maintenance_on:
			safety = (state["outputs"].get("safety") or {}).get("db")
			recovery = ("The site is still in MAINTENANCE MODE so nobody works on a half-restored database. "
				f"To go back to how it was, restore the safety backup: bench --site {frappe.local.site} restore "
				f"sites/{frappe.local.site}/private/backups/{safety} --force, then migrate and set-maintenance-mode off.")
		state.update(status="Failed", stage="Restore failed", error=f"{e} {recovery}".strip(), finished=str(now_datetime()))
		log(state, f"✗ {state['error']}")
		write_state(state)
		try:
			_reconnect()
		except Exception:
			pass
		save_record(state)
	_notify(state)


def _notify(state):
	try:
		user = state.get("user")
		if not user or user == "Guest" or not frappe.db.table_exists("Notification Log"):
			return
		ok = state["status"] == "Success"
		frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "document_type": "ERP Backup Job",
			"document_name": state["job"], "subject": f"{state['type']} {'completed' if ok else 'FAILED'} · {state['job']}" + ("" if ok else f" — {state.get('error', '')[:120]}")}).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
