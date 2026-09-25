# Copyright (c) 2026, Adimyra Systems Private Limited
# For license information, please see license.txt

from frappe.model.document import Document


class SiteCareJob(Document):
	"""A backup or restore run from adiSiteCare. Created and updated only by the app."""
