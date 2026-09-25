# Copyright (c) 2026, Adimyra Systems Private Limited
# For license information, please see license.txt

from frappe.model.document import Document


class ERPBackupJob(Document):
	"""A backup or restore run from the adiERP Backup page. Created and updated only by the app."""
