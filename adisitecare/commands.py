"""bench --site <site> sitecare-restore-db <backup.sql.gz> [--public-files x.tar] [--private-files y.tar]

Restores a full backup INTO the site's existing database using the site's own database
user (from site_config.json) — so, unlike `bench restore`, it needs no MariaDB root
password. The site keeps its own database name, user and password.
Works on Frappe v15 and v16 (MariaDB).
"""

import inspect
import json
import os
import subprocess

import click
import frappe
from frappe.commands import get_site, pass_context


def _drop_all_tables():
	db_name = frappe.conf.db_name
	rows = frappe.db.sql(
		"select table_name, table_type from information_schema.tables where table_schema = %s", db_name
	)
	frappe.db.sql("SET FOREIGN_KEY_CHECKS = 0")
	for name, kind in rows:
		frappe.db.sql_ddl(f"DROP {'VIEW' if kind == 'VIEW' else 'TABLE'} IF EXISTS `{name}`")
	frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
	print(f"Cleared {len(rows)} tables from {db_name}")


def _import(sql_file):
	from frappe.database.db_manager import DbManager
	from frappe.database.mariadb.setup_db import import_db_from_sql

	# older Frappe can't read .gz directly — unpack next to it for the import, then remove
	tmp = None
	if sql_file.endswith(".gz") and "gzip" not in inspect.getsource(DbManager.restore_database):
		tmp = sql_file[:-3] + ".sitecare-tmp.sql"
		with open(tmp, "wb") as out:
			subprocess.run(["gzip", "-cd", sql_file], stdout=out, check=True)
		sql_file = tmp
	try:
		import_db_from_sql(source_sql=sql_file, verbose=True)
	finally:
		if tmp and os.path.exists(tmp):
			os.remove(tmp)


LEGACY = {"adi_erp_backup": "adisitecare"}  # renamed apps: old name → new name


def _fix_installed_apps():
	"""A backup lists the apps its site had. Apps that aren't on this bench would break migrate,
	so take them off the site's installed list (like `bench remove-from-installed-apps`) and say so."""
	row = frappe.db.sql("select defvalue from `tabDefaultValue` where defkey='installed_apps' and parent='__global'")
	installed = json.loads(row[0][0]) if row and row[0][0] else []
	on_bench = set(frappe.get_all_apps())
	missing = [a for a in installed if a not in on_bench]
	if not missing:
		return
	keep = []
	for app in installed:
		if app not in missing:
			keep.append(app)
		elif LEGACY.get(app) in on_bench:
			_move_legacy(app)
			keep.append(LEGACY[app])
			print(f"✓ {app} was renamed to {LEGACY[app]} — moved its records")
		else:
			print(f"⚠ App {app} is in the backup but not on this bench — removed from installed apps "
				f"(install it and migrate again if you need it)")
	keep = list(dict.fromkeys(keep))  # no duplicates, same order
	frappe.db.sql("update `tabDefaultValue` set defvalue=%s where defkey='installed_apps' and parent='__global'", json.dumps(keep))
	frappe.db.sql("delete from `tabInstalled Application` where app_name in %s", (tuple(missing),))
	frappe.db.commit()
	frappe.cache.delete_keys("")  # installed apps are cached in Redis too


def _move_legacy(app):
	if app == "adi_erp_backup":
		if frappe.db.sql("show tables like 'tabERP Backup Job'") and not frappe.db.sql("show tables like 'tabSiteCare Job'"):
			frappe.db.sql_ddl("RENAME TABLE `tabERP Backup Job` TO `tabSiteCare Job`")
		for dt in ("DocField", "DocPerm", "DocType Action", "DocType Link", "DocType State"):
			frappe.db.sql(f"delete from `tab{dt}` where parent='ERP Backup Job'")
		frappe.db.sql("delete from `tabDocType` where name='ERP Backup Job'")
		frappe.db.sql("delete from `tabHas Role` where parenttype='Page' and parent='adierp-backup'")
		frappe.db.sql("delete from `tabPage` where name='adierp-backup'")
		frappe.db.sql("delete from `tabModule Def` where name='adiERP Backup'")


@click.command("sitecare-restore-db")
@click.argument("sql_file")
@click.option("--public-files", help="Public files backup (.tar / .tgz)")
@click.option("--private-files", help="Private files backup (.tar / .tgz)")
@pass_context
def restore_db(context, sql_file, public_files=None, private_files=None):
	"Restore a backup into this site's database without the MariaDB root password"
	from frappe.installer import extract_files, validate_database_sql

	site = get_site(context)
	sql_file = os.path.abspath(sql_file)
	for path in (sql_file, public_files, private_files):
		if path and not os.path.isfile(path):
			raise click.ClickException(f"File not found: {path}")

	frappe.init(site)
	frappe.connect()
	try:
		if (frappe.conf.db_type or "mariadb") != "mariadb":
			raise click.ClickException("Only MariaDB sites are supported")
		validate_database_sql(sql_file, _raise=True)
		_drop_all_tables()
		frappe.db.commit()
		print(f"Importing {os.path.basename(sql_file)} …")
		_import(sql_file)
		print("Database restored")
		_fix_installed_apps()
	finally:
		frappe.destroy()

	for label, path in (("public", public_files), ("private", private_files)):
		if path:
			print(f"Extracting {label} files from {os.path.basename(path)} …")
			tar = extract_files(site, os.path.abspath(path))
			if os.path.abspath(tar) != os.path.abspath(path) and os.path.exists(tar):
				os.remove(tar)  # extract_files leaves a copy of the archive in the site folder
			print(f"{label.capitalize()} files restored")


commands = [restore_db]
