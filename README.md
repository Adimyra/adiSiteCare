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
[![Release](https://img.shields.io/github/v/release/Adimyra/adiSiteCare?color=4D6443&label=stable)](https://github.com/Adimyra/adiSiteCare/releases)

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
- **Upload** a backup (large files are uploaded in resumable pieces), **pick one already on the server**, or
  **paste a Google Drive link** — the server downloads it with `gdown`, restores it, and deletes the downloaded
  copy when done (share the file as *Anyone with the link*)
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
  staging site never emails real customers — and shows the **staging banner** on the website
- **Knows when the backup was taken** — read from the dump itself (`Dump completed on …`), not the file or upload time
- Progress keeps updating even while the site is in maintenance mode

### 🛠️ Tools
- **Site switches** — one click from the health bar or the Tools tab:
  - **Emails** — mute / unmute; when unmuting, emails waiting in the queue can be discarded first
  - **Scheduler** — pause / resume (also re-enables it if it was disabled in System Settings)
  - **Maintenance mode** — on for 5 / 15 / 30 / 60 minutes with a live countdown, then off automatically
    (Frappe blocks every request during maintenance — this page too — so it always switches itself off)
- **Staging banner** — a thin **STAGING** strip above the website navbar: *"Test site — please don't place orders
  or make payments"* with **Database backup · date · time** of the restored data. Turned on automatically by a
  staging restore, or from the dashboard with a live desktop preview. Uses *Website Settings → Banner HTML* and
  keeps any other banner content
- **Restart bench** — detected automatically: restarts `bench start` on development, runs `bench restart` on
  production (asks the system user password when supervisor needs sudo — used once, never saved)
- **After-restore tasks** — migrate → clear cache → clear website cache → restart, in one click
- **Migrate**, **Clear cache**, **Restart bench** — each with the live terminal

### 📊 Dashboard & workspace
- Health bar: maintenance, scheduler, emails, background workers, disk space — *All good* or *Needs attention*
- Last backup, backups on server, last restore, jobs in the last 30 days
- **adiSiteCare** workspace with shortcuts and number cards

### 🧾 Job history
- Every backup, restore and action is kept as a **SiteCare Job** — **when** (date & time), **who**, **how**
  (files created or restored from, safety backup) and the **full terminal log**
- The history **survives restores**: records newer than the restored backup are put back automatically
- Backup *files* are cleaned up by Frappe (see below) — the history record always stays

## What runs behind each switch

Nothing custom — adiSiteCare uses the same Frappe functions as these `bench` commands:

| Switch | What changes | Same as |
|---|---|---|
| Emails · **Mute** / **Unmute** | `mute_emails` = 1 / 0 in `site_config.json` | `bench --site <site> set-config mute_emails 1` / `0` |
| Emails · discard waiting | `Email Queue` rows *Not Sent* → *Error* (never sent) | — |
| Scheduler · **Pause** / **Resume** | `pause_scheduler` = 1 / 0 in `site_config.json` | `bench --site <site> scheduler pause` / `resume` |
| Scheduler · Resume (when disabled) | System Settings → *Enable Scheduler* = 1 | `bench --site <site> scheduler enable` |
| Maintenance · on for N min | `maintenance_mode` = 1, then 0 after N minutes | `bench --site <site> set-maintenance-mode on` / `off` |

While emails are muted, Frappe still creates them — they wait in the **Email Queue** and are sent once you unmute.
Settings in `common_site_config.json` apply to the whole bench; adiSiteCare shows them but leaves them to you.

## Backup files are short-term

adiSiteCare keeps backups where `bench backup` puts them (`sites/<site>/private/backups`), and Frappe cleans that folder:

- **Every backup** first deletes files older than ~23 hours (`keep_backups_for_hours` in site config)
- **Every hour** the scheduler keeps only the newest **3** backup sets (*System Settings → Number of Backups*)

Download the backups you want to keep, or pair adiSiteCare with an off-site backup app. The **job history** is never deleted.

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

## ✅ Compatibility & releases

> **adiSiteCare v1.0.0 is stable on both Frappe / ERPNext v15 and v16.**

| Frappe / ERPNext | Branch | Python | Status |
|---|---|---|---|
| **v16** | **`version-16`** | 3.14 | ✅ **Stable** |
| **v15** | **`version-15`** | 3.10 – 3.12 | ✅ **Stable** |
| latest | **`main`** | 3.10+ | ✅ **Stable** — same code as both version branches |

**One codebase, both versions:** features that exist only in v16 (workspace sidebar, desktop icons) are picked up
automatically on v16 and simply skipped on v15. Every release is published on **all three branches** —
see [Releases](https://github.com/Adimyra/adiSiteCare/releases).

## Installation

**Frappe / ERPNext v16**

```bash
bench get-app https://github.com/Adimyra/adiSiteCare --branch version-16
bench --site <your-site> install-app adisitecare
```

**Frappe / ERPNext v15**

```bash
bench get-app https://github.com/Adimyra/adiSiteCare --branch version-15
bench --site <your-site> install-app adisitecare
```

Then open **adiSiteCare** from the apps screen, or go to **`/app/sitecare`**.

### Updating

```bash
bench update --apps adisitecare
```

or, for this app only:

```bash
cd apps/adisitecare && git pull && cd ../.. && bench --site <your-site> migrate
```

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
