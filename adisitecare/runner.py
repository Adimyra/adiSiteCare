"""The work itself: backups and restores run as background jobs that call the same
bench/frappe commands you would type in a terminal, stream their output, and keep
their progress in a JSON file.

Backup files stay in sites/<site>/private/backups (same place as `bench backup`).
A restore uses the site's own database user — no MariaDB root password is needed.
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

APP = "adisitecare"
DB_EXTS = (".sql.gz", ".sql")
FILE_EXTS = (".tar", ".tgz")


# ---------------------------------------------------------------- paths & state
#
# Backup files live only where `bench backup` puts them: sites/<site>/private/backups.
# Job progress lives in Redis (it survives the database being replaced), and for a
# restore also in one small file the page can read while the site is in maintenance:
#   sites/<site>/public/files/sitecare-status-<random token>.json


def backups_dir():
	return frappe.get_site_path("private", "backups")


def public_status_path(token):
	return frappe.get_site_path("public", "files", f"sitecare-status-{token}.json")


def _cache():
	return frappe.cache() if callable(frappe.cache) else frappe.cache


def _key(job):
	return f"{APP}:job:{job}"


def read_state(job):
	try:
		return _cache().get_value(_key(job))
	except Exception:
		return None


def write_state(state):
	state["updated"] = str(now_datetime())
	state["now_ts"] = time.time()
	try:
		_cache().set_value(_key(state["job"]), state, expires_in_sec=3 * 24 * 3600)
	except Exception:
		pass  # Redis busy/flushed for a moment — the next write puts it back
	if state.get("token"):  # mirror without anything sensitive
		mirror = {k: state.get(k) for k in ("job", "type", "action", "title", "status", "stage", "progress", "error", "updated", "finished", "outputs", "restarted", "steps", "now_ts")}
		mirror["log"] = "\n".join((state.get("log") or "").splitlines()[-150:])
		pub = public_status_path(state["token"])
		with open(pub + ".tmp", "w") as f:
			json.dump(mirror, f, default=str)
		os.replace(pub + ".tmp", pub)


def cleanup_status_files(days=7):
	d = frappe.get_site_path("public", "files")
	for fn in os.listdir(d) if os.path.isdir(d) else []:
		if fn.startswith("sitecare-status-"):
			path = os.path.join(d, fn)
			if time.time() - os.path.getmtime(path) > days * 86400:
				try:
					os.remove(path)
				except OSError:
					pass


def new_state(job, kind, token=None, **extra):
	state = {"job": job, "type": kind, "status": "Queued", "stage": "Queued", "progress": 0, "log": "", "error": "",
		"started": None, "finished": None, "outputs": {}, "token": token, **extra}
	write_state(state)
	return state


# ---------------------------------------------------------------- steps (the checklist next to the terminal)

RESTORE_STEPS = [("check", "Check the backup files"), ("safety", "Safety backup"), ("maintenance", "Maintenance mode on"),
	("restore", "Restore database & files"), ("migrate", "Migrate & clear cache"), ("online", "Back online")]
BACKUP_STEPS = [("backup", "Take the backup"), ("verify", "Check the backup files")]
MIGRATE = ("migrate", "Migrate", ("migrate",), 300)
CACHE = ("cache", "Clear cache", ("clear-cache",), 20)
WEBCACHE = ("webcache", "Clear website cache", ("clear-website-cache",), 20)
RESTART = ("restart", "Restart bench", None, 0)
ACTIONS = {
	"post_restore": ("After-restore tasks", [MIGRATE, CACHE, WEBCACHE, RESTART]),
	"migrate": ("Migrate", [MIGRATE, CACHE, WEBCACHE]),
	"clear_cache": ("Clear cache", [CACHE, WEBCACHE]),
	"restart": ("Restart bench", [RESTART]),
}


def make_steps(pairs):
	return [{"key": k, "label": label, "status": "pending", "started": None, "ended": None} for k, label in pairs]


def set_step(state, key, status="running"):
	now = time.time()
	for st in state.get("steps") or []:
		if st["key"] == key:
			if status == "running" and st["status"] != "running":
				st["started"] = now
			if status != "running":
				st["started"] = st["started"] or now
				st["ended"] = now
			st["status"] = status
		elif status == "running" and st["status"] == "running":
			st.update(status="done", ended=now)
	write_state(state)


def finish_steps(state, ok):
	now = time.time()
	for st in state.get("steps") or []:
		if st["status"] == "running":
			st.update(status="done" if ok else "failed", ended=now)
		elif not ok and st["status"] == "pending":
			st["status"] = "skipped"


# ---------------------------------------------------------------- running commands

SECRET = re.compile(r"(--db-root-password\s+|encryption_key\W+)(\S+)")


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
		if not frappe.db.table_exists("SiteCare Job"):
			return
		values = {
			"status": state["status"], "stage": state["stage"], "progress": state["progress"], "log": state["log"][-60000:],
			"error": state.get("error") or None, "finished_on": state.get("finished"), **(fields or {}),
		}
		if frappe.db.exists("SiteCare Job", state["job"]):
			frappe.db.set_value("SiteCare Job", state["job"], values, update_modified=True)
		else:  # the job's own record went away with the restored database — put it back
			doc = frappe.get_doc({"doctype": "SiteCare Job", "job_type": state["type"], "requested_by": state.get("user"),
				"with_files": state.get("with_files", 0), "restart_after": state.get("restart", 0), "started_on": state.get("started"),
				"status_token": state.get("token"), **values})
			doc.name = state["job"]
			doc.flags.name_set = True
			doc.db_insert()
			fix_series(state["job"])
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()


def fix_series(name):
	"""The restored database has the naming counter from backup time — move it past a job we put back."""
	prefix, _sep, num = name.rpartition("-")
	if not num.isdigit():
		return
	prefix, num = prefix + "-", int(num)
	current = frappe.db.sql("select current from `tabSeries` where name=%s", prefix)
	if not current:
		frappe.db.sql("insert into `tabSeries` (name, current) values (%s, %s)", (prefix, num))
	elif (current[0][0] or 0) < num:
		frappe.db.sql("update `tabSeries` set current=%s where name=%s", (num, prefix))


def _reconnect():
	"""After a restore the old database connection is gone — open a fresh one."""
	try:
		frappe.db.close()
	except Exception:
		pass
	frappe.local.db = None
	frappe.connect(frappe.local.site)


def _snapshot_history():
	"""The job history lives in the database a restore replaces — keep a copy in memory to put back afterwards."""
	try:
		return frappe.get_all("SiteCare Job", fields=["*"], order_by="creation asc")
	except Exception:
		return []
	finally:
		# end the read transaction — an open one holds a metadata lock on the table and the
		# restore's DROP TABLE would wait for it forever
		frappe.db.rollback()


def _next_name(name):
	"""Next free job name with the same prefix (SC-2026-00007 …), counter moved past it."""
	prefix = name.rpartition("-")[0] + "-"
	names = frappe.db.sql("select name from `tabSiteCare Job` where name like %s", prefix + "%", pluck=True)
	top = max([int(n.rpartition("-")[2]) for n in names if n.rpartition("-")[2].isdigit()] + [0])
	new = f"{prefix}{top + 1:05d}"
	fix_series(new)
	return new


def _same_job(name, created):
	row = frappe.db.get_value("SiteCare Job", name, "creation")
	return row is None or str(row)[:19] == str(created or "")[:19]


def _claim_name(state):
	"""The restored backup may already hold a different job with this job's name (another site's
	history, or an older one) — then save this job under the next free name instead of overwriting it."""
	name = state["job"]
	if _same_job(name, state.get("created")):
		return
	state["job"] = _next_name(name)
	log(state, f"↻ The restored backup already has a job {name} — this restore is recorded as {state['job']}.")


def _restore_history(rows):
	"""Put back history records the restored backup didn't have (e.g. jobs run after that backup was taken)."""
	added = 0
	try:
		if not rows or not frappe.db.table_exists("SiteCare Job"):
			return 0
		columns = set(frappe.db.get_table_columns("SiteCare Job"))
		for row in rows:
			if frappe.db.exists("SiteCare Job", row["name"]):
				if _same_job(row["name"], row.get("creation")):
					continue
				row["name"] = _next_name(row["name"])  # a different job has this name in the restored backup
			doc = frappe.get_doc({"doctype": "SiteCare Job", **{k: v for k, v in row.items() if k in columns}})
			doc.name = row["name"]
			doc.flags.name_set = True
			doc.db_insert()
			fix_series(row["name"])
			added += 1
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
	return added


def _reconcile(job):
	"""A restored database brings back job records as they were at backup time — close the ones still 'running'."""
	try:
		frappe.db.sql("""update `tabSiteCare Job` set status='Interrupted', stage='Closed — this record came back with a restored backup'
			where status in ('Queued', 'Running') and name != %s""", job)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()


def restart_available():
	return _supervisor_ok()


def _do_restart(state):
	"""Last step, detached — a restart also restarts the worker running this job."""
	set_step(state, "restart")
	if not _supervisor_ok():
		log(state, "↻ Restart skipped — this server needs a one-time setup so the app can restart without a password: "
			"`sudo bench setup production <user>` (or `sudo bench setup sudoers <user>`). "
			"Without it, restart from the terminal: bench restart")
		set_step(state, "restart", "skipped")
		return False
	bench = shutil.which("bench") or os.path.expanduser("~/.local/bin/bench")
	log(state, "\n$ bench restart")
	try:
		subprocess.Popen([bench, "restart"], cwd=get_bench_path(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL, start_new_session=True)
		state["restarted"] = True
		log(state, "↻ Restart started — web and workers come back in a few seconds.")
		set_step(state, "restart", "done")
		return True
	except Exception as e:
		log(state, f"⚠ Couldn't run bench restart ({e}) — run it from the terminal.")
		set_step(state, "restart", "failed")
		return False


# ---------------------------------------------------------------- actions (migrate / clear cache / restart)


def run_action(job):
	state = read_state(job)
	if not state:
		return
	title, steps = ACTIONS[state["action"]]
	state.update(status="Running", started=str(now_datetime()))
	save_record(state, {"started_on": state["started"]})
	wants_restart = any(k == "restart" for k, *_ in steps)
	work = [x for x in steps if x[0] != "restart"]
	try:
		for i, (key, label, args, expect) in enumerate(work):
			set_step(state, key)
			a = 5 + int(90 * i / max(len(work), 1))
			b = 5 + int(90 * (i + 1) / max(len(work), 1))
			run(state, _frappe_cmd(*args), label, a, b, expect)
			set_step(state, key, "done")
		state.update(status="Success", stage=f"{title} complete", progress=100, finished=str(now_datetime()))
		log(state, f"✓ {title} complete.")
		write_state(state)
		save_record(state)
		if wants_restart:
			_do_restart(state)
			save_record(state)
	except Exception as e:
		finish_steps(state, False)
		state.update(status="Failed", stage=f"{title} failed", error=str(e), finished=str(now_datetime()))
		log(state, f"✗ {e}")
		write_state(state)
		save_record(state)
	_notify(state)


def run_maintenance(job):
	"""Maintenance mode on for N minutes, then off again — always off at the end, even on errors."""
	state = read_state(job)
	if not state:
		return
	minutes = int(state.get("minutes") or 15)
	state.update(status="Running", started=str(now_datetime()))
	save_record(state, {"started_on": state["started"]})
	switched_on = False
	try:
		set_step(state, "on")
		run(state, _frappe_cmd("set-maintenance-mode", "on"), "Maintenance mode on", 2, 5, 10)
		switched_on = True
		if not int(site_config().get("maintenance_mode") or 0):
			raise RuntimeError("Maintenance mode did not switch on.")
		log(state, f"✓ Maintenance mode is ON — users see the maintenance page for {minutes} minutes.")
		set_step(state, "window")
		end = time.time() + minutes * 60
		while time.time() < end:
			if not int(site_config().get("maintenance_mode") or 0):
				log(state, "↻ Maintenance mode was switched off on the server — ending early.")
				break
			left = int(end - time.time())
			state.update(stage=f"Back online in {left // 60}:{left % 60:02d}", progress=5 + int(90 * (1 - left / (minutes * 60))),
				ends_at=end)
			write_state(state)
			time.sleep(5)
		set_step(state, "off")
	except Exception as e:
		state["error"] = str(e)
		log(state, f"✗ {e}")
	finally:
		if switched_on or int(site_config().get("maintenance_mode") or 0):
			subprocess.run(_frappe_cmd("set-maintenance-mode", "off"), cwd=os.path.join(get_bench_path(), "sites"), capture_output=True)
			log(state, "\n$ bench --site {0} set-maintenance-mode off".format(frappe.local.site))
		back = not int(site_config().get("maintenance_mode") or 0)
		if back:
			log(state, "✓ Maintenance mode is OFF — the site is back online.")
		finish_steps(state, back and not state.get("error"))
		state.update(status="Success" if back and not state.get("error") else "Failed", progress=100 if back else state["progress"],
			stage="Site back online" if back else "Maintenance mode still ON", finished=str(now_datetime()))
		if not back:
			state["error"] = (state.get("error") or "") + f" Run on the server: bench --site {frappe.local.site} set-maintenance-mode off"
		write_state(state)
		save_record(state)
		_notify(state)


# ---------------------------------------------------------------- backup


def run_backup(job):
	state = read_state(job) or new_state(job, "Backup")
	state.update(status="Running", started=str(now_datetime()))
	save_record(state, {"started_on": state["started"]})
	try:
		args = ["backup"] + (["--with-files"] if state.get("with_files") else [])
		set_step(state, "backup")
		run(state, _frappe_cmd(*args), "Taking backup", 5, 95, expect_seconds=240 if state.get("with_files") else 60)
		set_step(state, "verify")
		outputs = parse_backup_output(state["log"])
		if not outputs.get("db"):
			raise RuntimeError("The backup finished but no database file was reported.")
		for key, fn in outputs.items():
			path = os.path.join(backups_dir(), fn)
			if not os.path.isfile(path) or (fn.endswith(".gz") and subprocess.run(["gzip", "-t", path], capture_output=True).returncode != 0):
				raise RuntimeError(f"Backup file {fn} is missing or damaged.")
		log(state, "✓ Backup files checked — " + ", ".join(outputs.values()))
		finish_steps(state, True)
		state.update(outputs=outputs, status="Success", stage="Backup complete", progress=100, finished=str(now_datetime()))
		write_state(state)
		save_record(state, {"db_file": outputs.get("db"), "public_file": outputs.get("public"), "private_file": outputs.get("private"), "config_file": outputs.get("config")})
	except Exception as e:
		finish_steps(state, False)
		state.update(status="Failed", stage="Backup failed", error=str(e), finished=str(now_datetime()))
		log(state, f"✗ {e}")
		write_state(state)
		save_record(state)
	_notify(state)


# ---------------------------------------------------------------- restore


def _supervisor_ok():
	"""bench restart works without a password only when this user can talk to supervisor
	directly (bench setup production) or has passwordless sudo (bench setup sudoers)."""
	try:
		r = subprocess.run(["supervisorctl", "status"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
		if r.returncode in (0, 3) and "Permission denied" not in (r.stdout + r.stderr) and r.stdout.strip():
			return True
	except Exception:
		pass
	try:
		return subprocess.run(["sudo", "-n", "supervisorctl", "status"], capture_output=True, timeout=15, stdin=subprocess.DEVNULL).returncode in (0, 3)
	except Exception:
		return False


def run_restore(job):
	state = read_state(job)
	if not state:
		return
	state.update(status="Running", started=str(now_datetime()))
	save_record(state, {"started_on": state["started"]})
	src = state["sources"]
	staging = state.get("staging")
	maintenance_on = restored = False
	with_files = bool(src.get("public") or src.get("private"))
	try:
		# 1. pre-flight: the files are there and look right
		set_step(state, "check")
		state.update(stage="Checking the backup files", progress=3)
		log(state, "Checking the backup files…")
		from frappe.installer import is_downgrade, is_partial, validate_database_sql

		if (frappe.conf.db_type or "mariadb") != "mariadb":
			raise RuntimeError("Only MariaDB sites are supported.")
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
		for key in ("public", "private", "config"):
			if src.get(key) and not os.path.isfile(src[key]):
				raise RuntimeError(f"The {key} backup file is missing.")
		key_from_backup = None
		if src.get("config"):
			with open(src["config"]) as f:
				key_from_backup = (json.load(f) or {}).get("encryption_key")
		# `bench backup` removes files older than a day — keep the ones we are about to use
		for path in src.values():
			if path:
				os.utime(path)
		log(state, "✓ Backup files look good.")
		from adisitecare import banner

		taken = banner.backup_time(db)
		state["backup_taken_on"] = str(taken) if taken else None
		if taken:
			log(state, f"✓ This backup was taken on {banner.label(taken)}")

		set_step(state, "safety")
		# 2. safety backup of the site as it is now — the undo point (lands in private/backups too)
		run(state, _frappe_cmd("backup", *(["--with-files"] if with_files else [])), "Safety backup of the current site", 5, 25, expect_seconds=120)
		safety = parse_backup_output(state["log"])
		state["outputs"]["safety"] = safety
		log(state, f"✓ Safety backup: {safety.get('db')}")

		set_step(state, "maintenance")
		# 3. maintenance mode ON (and make sure it really is), scheduler paused
		run(state, _frappe_cmd("set-maintenance-mode", "on"), "Maintenance mode on", 26, 30, 10)
		maintenance_on = True
		if not int(site_config().get("maintenance_mode") or 0):
			raise RuntimeError("Maintenance mode did not switch on — stopping before touching the database.")
		log(state, "✓ Maintenance mode is ON — users see the maintenance page.")
		run(state, _frappe_cmd("set-config", "pause_scheduler", "1"), "Pausing the scheduler", 30, 32, 10)
		if staging:
			run(state, _frappe_cmd("set-config", "mute_emails", "1"), "Muting outgoing emails (staging copy)", 32, 33, 10)

		set_step(state, "restore")
		history = _snapshot_history()
		# 4. restore — with the site's own database user, so no MariaDB root password is needed
		args = ["sitecare-restore-db", db]
		if src.get("public"):
			args += ["--public-files", src["public"]]
		if src.get("private"):
			args += ["--private-files", src["private"]]
		frappe.db.commit()  # hold no transaction (and no table locks) while the database is replaced
		restored = True  # from here on the database may already be changed
		run(state, _frappe_cmd(*args), "Restoring the database" + (" and files" if with_files else ""), 34, 70, expect_seconds=300)
		if key_from_backup and key_from_backup != site_config().get("encryption_key"):
			from frappe.installer import update_site_config

			update_site_config("encryption_key", key_from_backup, site_config_path=frappe.get_site_path("site_config.json"))
			log(state, "✓ Encryption key taken from the backup's site config (saved passwords in the backup keep working).")

		# 5. keep this tool on the site even if the backup is from before it was installed
		apps = subprocess.run(_frappe_cmd("list-apps"), cwd=os.path.join(get_bench_path(), "sites"), capture_output=True, text=True).stdout
		if APP not in apps:
			run(state, _frappe_cmd("install-app", APP), "Re-installing adiSiteCare", 70, 74, 60)

		set_step(state, "migrate")
		# 6. migrate + caches
		run(state, _frappe_cmd("migrate"), "Migrating", 74, 92, expect_seconds=300)
		run(state, _frappe_cmd("clear-cache"), "Clearing cache", 92, 94, 20)
		run(state, _frappe_cmd("clear-website-cache"), "Clearing website cache", 94, 95, 20)

		set_step(state, "online")
		# 7. back online
		if staging:
			log(state, "Staging copy: the scheduler stays PAUSED and emails stay MUTED "
				"(turn them on with: bench --site {0} set-config pause_scheduler 0 / mute_emails 0).".format(frappe.local.site))
		else:
			run(state, _frappe_cmd("set-config", "pause_scheduler", "0"), "Resuming the scheduler", 95, 96, 10)
		run(state, _frappe_cmd("set-maintenance-mode", "off"), "Maintenance mode off", 96, 98, 10)
		maintenance_on = False
		log(state, "✓ Site is back online.")
		set_step(state, "online", "done")

		state.update(status="Success", stage="Restore complete", progress=100, finished=str(now_datetime()))
		write_state(state)
		_reconnect()
		_claim_name(state)
		kept = _restore_history([r for r in history if r["name"] != job])
		_reconcile(state["job"])
		if kept:
			log(state, f"✓ Job history kept — {kept} record(s) newer than the backup put back.")
		if staging:
			try:
				banner.apply(state.get("backup_taken_on") or now_datetime())
				log(state, "✓ Staging banner shown on the website (Website Settings → Banner HTML).")
			except Exception as e:
				log(state, f"⚠ Couldn't set the staging banner ({e}) — set it from Tools.")
		save_record(state, {"backup_taken_on": state.get("backup_taken_on"), "safety_backup": json.dumps(safety), "restore_db": os.path.basename(db),
			"restore_public": os.path.basename(src.get("public") or "") or None, "restore_private": os.path.basename(src.get("private") or "") or None})

		# 8. optional restart — last and detached; skipped (never asks a password) when the server isn't set up for it
		if state.get("restart"):
			_do_restart(state)
			save_record(state)
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
				f"To go back to how it was, restore the safety backup {safety} (it is in the backups list), "
				f"or on the server: bench --site {frappe.local.site} sitecare-restore-db sites/{frappe.local.site}/private/backups/{safety}, "
				"then migrate and set-maintenance-mode off.")
		finish_steps(state, False)
		state.update(status="Failed", stage="Restore failed", error=f"{e} {recovery}".strip(), finished=str(now_datetime()))
		log(state, f"✗ {state['error']}")
		write_state(state)
		try:
			_reconnect()
			if restored:
				_claim_name(state)
			_restore_history([r for r in (locals().get("history") or []) if r["name"] != job])
			_reconcile(state["job"])
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
		frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "document_type": "SiteCare Job",
			"document_name": state["job"], "subject": f"{state['type']} {'completed' if ok else 'FAILED'} · {state['job']}" + ("" if ok else f" — {state.get('error', '')[:120]}")}).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
