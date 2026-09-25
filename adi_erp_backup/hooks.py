app_name = "adi_erp_backup"
app_title = "adiERP Backup"
app_publisher = "Adimyra Systems Private Limited"
app_description = "Backup and restore this Frappe/ERPNext site from Desk - safely, with maintenance mode and live progress"
app_email = "admin@adimyra.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "adi_erp_backup",
# 		"logo": "/assets/adi_erp_backup/logo.png",
# 		"title": "adiERP Backup",
# 		"route": "/adi_erp_backup",
# 		"has_permission": "adi_erp_backup.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/adi_erp_backup/css/adi_erp_backup.css"
# app_include_js = "/assets/adi_erp_backup/js/adi_erp_backup.js"

# include js, css files in header of web template
# web_include_css = "/assets/adi_erp_backup/css/adi_erp_backup.css"
# web_include_js = "/assets/adi_erp_backup/js/adi_erp_backup.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "adi_erp_backup/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "adi_erp_backup/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "adi_erp_backup.utils.jinja_methods",
# 	"filters": "adi_erp_backup.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "adi_erp_backup.install.before_install"
# after_install = "adi_erp_backup.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "adi_erp_backup.uninstall.before_uninstall"
# after_uninstall = "adi_erp_backup.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "adi_erp_backup.utils.before_app_install"
# after_app_install = "adi_erp_backup.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "adi_erp_backup.utils.before_app_uninstall"
# after_app_uninstall = "adi_erp_backup.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "adi_erp_backup.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "adi_erp_backup.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"adi_erp_backup.tasks.all"
# 	],
# 	"daily": [
# 		"adi_erp_backup.tasks.daily"
# 	],
# 	"hourly": [
# 		"adi_erp_backup.tasks.hourly"
# 	],
# 	"weekly": [
# 		"adi_erp_backup.tasks.weekly"
# 	],
# 	"monthly": [
# 		"adi_erp_backup.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "adi_erp_backup.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "adi_erp_backup.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "adi_erp_backup.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "adi_erp_backup.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["adi_erp_backup.utils.before_request"]
# after_request = ["adi_erp_backup.utils.after_request"]

# Job Events
# ----------
# before_job = ["adi_erp_backup.utils.before_job"]
# after_job = ["adi_erp_backup.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"adi_erp_backup.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


required_apps = ["frappe"]

add_to_apps_screen = [
	{
		"name": "adi_erp_backup",
		"logo": "/assets/frappe/images/frappe-framework-logo.svg",
		"title": "adiERP Backup",
		"route": "/app/adierp-backup",
		"has_permission": "adi_erp_backup.api.has_app_permission",
	}
]
