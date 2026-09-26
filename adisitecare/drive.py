"""Upload backups to Google Drive through the Cloud Backup app (if it's installed and connected),
then share them as "anyone with the link" so another server can restore from the link.

adiSiteCare never stores Google credentials itself — it borrows Cloud Backup's authorized
Google Drive provider. Without Cloud Backup, this whole feature simply isn't offered.
"""

import os

import frappe

APP = "cloud_backup"


def status():
	"""Is a Google Drive provider from Cloud Backup ready to use? Cheap: no Google call."""
	if APP not in frappe.get_installed_apps():
		return {"installed": False, "ready": False}
	try:
		from cloud_backup.services.backup_service import is_provider_ready

		settings = frappe.get_cached_doc("Cloud Backup Settings")
		for name in (settings.default_provider, settings.fallback_provider):
			if not name or not frappe.db.exists("Cloud Backup Provider", name):
				continue
			doc = frappe.get_cached_doc("Cloud Backup Provider", name)
			if doc.provider_type == "google_drive" and is_provider_ready(doc):
				return {"installed": True, "ready": True, "provider": name,
					"folder": doc.get("folder_name_display") or doc.get("destination_folder") or ""}
		return {"installed": True, "ready": False,
			"reason": "Connect a Google Drive provider in Cloud Backup (Provider → authorize) to use this."}
	except Exception as e:
		return {"installed": True, "ready": False, "reason": f"Cloud Backup isn't set up yet ({e})."}


def upload(path, share):
	"""Upload one file to the Cloud Backup Drive folder. Returns {id, name, size, link, shared}."""
	from cloud_backup.services.provider_service import get_provider

	st = status()
	if not st.get("ready"):
		raise RuntimeError(st.get("reason") or "Google Drive (Cloud Backup) isn't connected.")
	doc = frappe.get_doc("Cloud Backup Provider", st["provider"])
	provider = get_provider(doc)  # refreshes the token if needed
	result = provider.upload_file(path, doc.destination_folder or doc.root_folder, os.path.basename(path))
	svc = provider.service
	if share:
		svc.permissions().create(fileId=result["id"], body={"type": "anyone", "role": "reader"}, fields="id").execute()
	link = svc.files().get(fileId=result["id"], fields="webViewLink").execute().get("webViewLink")
	try:
		from cloud_backup.services import log_service

		log_service.write_log("external_upload", f"adiSiteCare uploaded {result.get('name')}", source="adisitecare",
			details={"file_id": result["id"], "provider": st["provider"], "shared": bool(share)})
	except Exception:
		pass
	return {"id": result["id"], "name": result.get("name"), "size": result.get("size"), "link": link, "shared": bool(share)}
