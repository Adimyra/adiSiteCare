### adiERP Backup

Backup and restore a Frappe / ERPNext site from Desk — safely, with maintenance mode and live progress.
Works on Frappe **v15** and **v16**. Page: **/app/adierp-backup** (System Manager only).

#### Backup
- Runs `bench --site <site> backup` (optionally `--with-files`) in the background (long queue).
- Live progress + terminal log; download links for database, public files, private files and site config when done.
- Lists all backups in `sites/<site>/private/backups` with download and "Restore this".

#### Restore
Typical use: take a backup on **production**, download it, upload it on **staging** and restore.
Or restore an older backup that is already on the same server.

Upload the database backup (`.sql.gz` / `.sql`), optionally the public / private files (`.tar` / `.tgz`) and the
site config backup (`.json`) — uploads are chunked (large files work) and saved straight into
`sites/<site>/private/backups`, next to the backups `bench backup` makes. No other folders are used.
Then **Start restore** runs, in order:

1. Pre-flight checks — gzip integrity, partial backup, downgrade warning, SQL validation
2. **Safety backup** of the current site (your undo point, also in `private/backups`)
3. **Maintenance mode ON** — verified in `site_config.json` before continuing — and scheduler paused
4. `bench --site <site> adierp-restore-db <db> [--public-files …] [--private-files …]`
5. Re-installs adiERP Backup if the backup predates it
6. `migrate`, `clear-cache`, `clear-website-cache`
7. Scheduler resumed, **maintenance mode OFF**
8. Optional `bench restart`

#### No server passwords needed
- **No MariaDB root password.** `bench restore` needs root because it drops and re-creates the database.
  adiERP Backup instead clears and re-imports the site's *existing* database with the site's own database
  user from `site_config.json` — the same user the site already runs with. Nothing to type, nothing in code.
  The same command works from a terminal: `bench --site <site> adierp-restore-db <file.sql.gz>`.
- **No sudo password.** A restart is not needed after a restore (code doesn't change, caches are cleared).
  "Restart bench" only runs when this user can control supervisor without a password — true on servers set up
  with `sudo bench setup production <user>` (or `sudo bench setup sudoers <user>`); otherwise it is skipped.
- **Restoring another site's backup** (production → staging): add its site config backup — only its
  `encryption_key` is copied, so saved passwords (email accounts, integrations) keep working.
- **Staging copy** option keeps `mute_emails` on and the scheduler paused, so production data on staging never
  emails real customers.

#### Safety
- System Manager only; restore also needs the site name typed exactly and the user's password.
- Only one job at a time; disk space is checked first.
- Progress during restore is read from a small status file (`public/files/adierp-status-<random>.json`),
  so it keeps working while the site is in maintenance mode.
- If the restore fails **before** the database is touched, maintenance mode is switched off again.
  If it fails **after**, the site stays in maintenance mode and the log shows how to recover from the safety backup.
- Downloads are sent byte-exact as attachments (Frappe's `/backups/` link can be re-encoded by the browser on
  servers without nginx).

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
