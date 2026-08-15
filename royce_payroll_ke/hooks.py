app_name = "royce_payroll_ke"
app_title = "Royce Payroll Ke"
app_publisher = "Royce Technologies LTD"
app_description = "Kenya PAYE, NSSF, SHIF and Housing Levy payroll compliance engine for ERPNext"
app_email = "developer@roycetechnologies.co.ke"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "royce_payroll_ke",
# 		"logo": "/assets/royce_payroll_ke/logo.png",
# 		"title": "Royce Payroll Ke",
# 		"route": "/royce_payroll_ke",
# 		"has_permission": "royce_payroll_ke.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/royce_payroll_ke/css/royce_payroll_ke.css"
# app_include_js = "/assets/royce_payroll_ke/js/royce_payroll_ke.js"

# include js, css files in header of web template
# web_include_css = "/assets/royce_payroll_ke/css/royce_payroll_ke.css"
# web_include_js = "/assets/royce_payroll_ke/js/royce_payroll_ke.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "royce_payroll_ke/public/scss/website"

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
# app_include_icons = "royce_payroll_ke/public/icons.svg"

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
# 	"methods": "royce_payroll_ke.utils.jinja_methods",
# 	"filters": "royce_payroll_ke.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "royce_payroll_ke.install.before_install"
# after_install = "royce_payroll_ke.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "royce_payroll_ke.uninstall.before_uninstall"
# after_uninstall = "royce_payroll_ke.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "royce_payroll_ke.utils.before_app_install"
# after_app_install = "royce_payroll_ke.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "royce_payroll_ke.utils.before_app_uninstall"
# after_app_uninstall = "royce_payroll_ke.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "royce_payroll_ke.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "royce_payroll_ke.notifications.get_notification_config"

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
# 		"royce_payroll_ke.tasks.all"
# 	],
# 	"daily": [
# 		"royce_payroll_ke.tasks.daily"
# 	],
# 	"hourly": [
# 		"royce_payroll_ke.tasks.hourly"
# 	],
# 	"weekly": [
# 		"royce_payroll_ke.tasks.weekly"
# 	],
# 	"monthly": [
# 		"royce_payroll_ke.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "royce_payroll_ke.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "royce_payroll_ke.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "royce_payroll_ke.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "royce_payroll_ke.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["royce_payroll_ke.utils.before_request"]
# after_request = ["royce_payroll_ke.utils.after_request"]

# Job Events
# ----------
# before_job = ["royce_payroll_ke.utils.before_job"]
# after_job = ["royce_payroll_ke.utils.after_job"]

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
# 	"royce_payroll_ke.auth.validate"
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

