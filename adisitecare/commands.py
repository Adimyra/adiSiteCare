"""bench --site <site> sitecare-restore-db <backup.sql.gz> [--public-files x.tar] [--private-files y.tar]

Restores a full backup INTO the site's existing database using the site's own database
user (from site_config.json) — so, unlike `bench restore`, it needs no MariaDB root
password. The site keeps its own database name, user and password.
Works on Frappe v15 and v16 (MariaDB).
"""

import inspect
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
