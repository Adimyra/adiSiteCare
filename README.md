<div align="center">

<img src="adisitecare/public/images/adiSiteCare_logo.png" alt="adiSiteCare" width="140">

# adiSiteCare

**Backup, restore and site care for Frappe / ERPNext — right from Desk.**

No SSH. No MariaDB root password. No sudo. Just a safe, guided page with a live terminal.

[![License: MIT](https://img.shields.io/badge/License-MIT-4D6443.svg)](license.txt)
[![Frappe](https://img.shields.io/badge/Frappe-v15%20%7C%20v16-112921.svg)](https://frappeframework.com)
[![ERPNext](https://img.shields.io/badge/ERPNext-v15%20%7C%20v16-4D6443.svg)](https://erpnext.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-112921.svg)](https://www.python.org)
[![Made by Adimyra](https://img.shields.io/badge/made%20by-Adimyra-4D6443.svg)](https://adimyra.com)

</div>

---

## Why adiSiteCare?

Restoring a Frappe site usually means SSH access, typing `bench` commands, knowing the MariaDB root
password and remembering every step: backup first, maintenance mode on, restore, migrate, clear cache,
maintenance off, restart. adiSiteCare turns that into one guided page on Desk — with the same commands
running underneath, shown live in a terminal window, and safety checks at every step.

**Typical use:** take a backup on *production*, download it, upload it on *staging* and restore — or roll
a site back to an earlier backup on the same server.

## Features

### 🗄️ Backup
- One click `bench --site <site> backup` — database only, or **with files** (public + private)
- Runs in the background with a live terminal, progress bar and step checklist
- Every backup file is checked after it's written; byte-exact downloads (database, files, site config)
- All backups on the server listed with size, download and **Restore** buttons

### ♻️ Restore
- **Upload** a backup (large files are uploaded in chunks) or **pick one already on the server**
- Optional public / private files and site config (for the encryption key of another site)
- Guided, safe order — each step verified before the next:
  1. Check the backup files — gzip integrity, partial backup, Frappe version, SQL validation
  2. **Safety backup** of the site as it is now — your undo point
  3. **Maintenance mode on** — confirmed in `site_config.json` before touching anything — scheduler paused
  4. Restore database and files
  5. `migrate`, `clear-cache`, `clear-website-cache`
  6. Back online — maintenance off, scheduler resumed
  7. Optional `bench restart`
- **Staging mode** — keeps outgoing emails muted and the scheduler paused, so production data on a
  staging site never emails real customers
- Progress keeps updating even while the site is in maintenance mode

### 🛠️ Tools
- **Site switches** — one click from the health bar or the Tools tab:
  - **Emails** — mute / unmute; when unmuting, emails waiting in the queue can be discarded first
  - **Scheduler** — pause / resume (also re-enables it if it was disabled in System Settings)
  - **Maintenance mode** — on for 5 / 15 / 30 / 60 minutes with a live countdown, then off automatically
    (Frappe blocks every request during maintenance — this page too — so it always switches itself off)
- **After-restore tasks** — migrate → clear cache → clear website cache → restart, in one click
- **Migrate**, **Clear cache**, **Restart bench** — each with the live terminal

### 📊 Dashboard & workspace
- Health bar: maintenance, scheduler, emails, background workers, disk space — *All good* or *Needs attention*
- Last backup, backups on server, last restore, jobs in the last 30 days
- **adiSiteCare** workspace with shortcuts and number cards; every run is kept as a **SiteCare Job** with its full log

## No server passwords needed

| | `bench restore` | adiSiteCare |
|---|---|---|
| MariaDB root password | required — it drops and re-creates the database | **not needed** — clears and re-imports the site's own database with the site's own database user |
| Server / sudo password | needed for `bench restart` | **not needed** — restart only runs where supervisor is reachable without a password, otherwise it is skipped |
| Secrets in code or config | — | **none** |

The same password-free restore is available on the command line:

```bash
bench --site <site> sitecare-restore-db path/to/backup.sql.gz [--public-files files.tar] [--private-files private-files.tar]
```

> **Restart without a password (optional):** run once on the server — `sudo bench setup production <user>`
> (or `sudo bench setup sudoers <user>`). A restart is not required after a restore.

## Safety

- **System Manager only.** A restore also asks for the site name (typed exactly) and the user's own login password.
- **One job at a time**, and free disk space is checked before starting.
- **Maintenance mode is verified** before the database is touched.
- If a restore fails **before** the database changes, the site is put back online automatically.
  If it fails **after**, the site stays in maintenance mode and the log shows exactly how to recover from the safety backup.
- Damaged uploads (for example a `.sql.gz` that a browser unpacked while downloading) are rejected immediately with a clear message.
- Files stay in `sites/<site>/private/backups` — the same folder `bench backup` uses. No extra folders.

## Installation

```bash
cd frappe-bench
bench get-app https://github.com/Adimyra/adiSiteCare
bench --site <your-site> install-app adisitecare
```

Open **adiSiteCare** from the apps screen, or go to `/app/sitecare`.

### Requirements
- Frappe / ERPNext **v15 or v16**, MariaDB
- A background worker for the `long` queue — `bench worker` in development, supervisor in production
- Enough free disk space for the backup, a safety backup and the restored database

## Credits

Designed and built by **[Md Faiyaz Ansari](https://github.com/itsfaiyaz)** ([@itsfaiyaz](https://github.com/itsfaiyaz))
at **[Adimyra Systems Private Limited](https://adimyra.com)**.

### Contributors

<a href="https://github.com/itsfaiyaz"><img src="https://github.com/itsfaiyaz.png" width="64" height="64" alt="itsfaiyaz" style="border-radius:50%"></a>

**Md Faiyaz Ansari** — [@itsfaiyaz](https://github.com/itsfaiyaz) · author & maintainer

Contributions are welcome — open an issue or a pull request.

## License

[MIT](license.txt) © 2026 Md Faiyaz Ansari, Adimyra Systems Private Limited
