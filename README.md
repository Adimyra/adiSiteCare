### adiERP Backup

Backup and restore a Frappe / ERPNext site from Desk — safely, with maintenance mode and live progress.
Works on Frappe **v15** and **v16**. Page: **/app/adierp-backup** (System Manager only).

#### Backup
- Runs `bench --site <site> backup` (optionally `--with-files`) in the background (long queue).
- Live progress + terminal log; download links for database, public files, private files and site config when done.
- Lists all backups in `sites/<site>/private/backups` with download and "Restore this".

#### Restore
Upload a database backup (`.sql.gz` / `.sql`) and optionally public / private files (`.tar`, `.tar.gz`, `.tgz`) —
uploads are chunked, so large files work — or pick an existing backup. Then **Start restore** runs, in order:

1. Pre-flight checks — gzip integrity, partial backup, downgrade warning, SQL validation
2. **Safety backup** of the current site (your undo point)
3. **Maintenance mode ON** — verified in `site_config.json` before continuing — and scheduler paused
4. `bench --site <site> restore <db> [--with-public-files] [--with-private-files] --force`
5. Re-installs adiERP Backup if the backup predates it
6. `migrate`, `clear-cache`, `clear-website-cache`
7. Scheduler resumed, **maintenance mode OFF**
8. Optional `bench restart`

Safety:
- System Manager only; restore also needs the site name typed exactly and the user's password.
- Only one job at a time; disk space is checked first.
- The MariaDB root password is taken from `common_site_config.json` (`root_password`) or entered once —
  it is kept in cache for the job only and masked in every log. It is never saved.
- Progress during restore is read from a static status file, so it keeps working while the site is in maintenance mode.
- If the restore fails **before** the database is touched, maintenance mode is switched off again.
  If it fails **after**, the site stays in maintenance mode and the log shows how to recover from the safety backup.

#### Requirements
- A running background worker for the `long` queue (`bench worker` / supervisor in production).
- Enough free disk space for the backup files, a safety backup and the restored database.

#### Install
```bash
bench get-app https://github.com/Adimyra/adiERPBackup
bench --site <site> install-app adi_erp_backup
```

#### License
MIT
