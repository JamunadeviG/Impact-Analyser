import frappe
from frappe import _
import os

# Core Frappe ecosystem apps - maintained by Frappe team, not project developers.
# Only apps NOT in this set will be shown to the developer.
FRAMEWORK_APPS = {
	"frappe", "erpnext", "hrms", "payments", "ecommerce_integrations",
	"erpnext_shipping", "frappe_whatsapp", "lms", "gameplan", "drive",
	"builder", "print_designer", "wiki", "crm", "raven", "helpdesk",
	"insights", "lending", "health", "agriculture", "education",
	"manufacturing", "non_profit", "hospitality", "erpnext_com",
	"frappe_io", "press", "posawesome", "erpnext_france","impact_analyser"
}


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(_("You need to be logged in to view this page"), frappe.PermissionError)

	context.no_cache = 1
	context.title = "Dead Code Eliminator"

	scan_name = frappe.form_dict.get("scan")

	context.scans = frappe.get_all(
		"Dead Code Eliminator",
		fields=[
			"name", "target_app", "status",
			"total_files_scanned", "total_dead_items",
			"low_risk_count", "medium_risk_count", "high_risk_count",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=50,
	)

	# Fetch only apps installed on the current running site,
	# then exclude framework/ecosystem apps to show only developer-created apps.
	available_apps = []
	try:
		installed = list(frappe.get_installed_apps())
		available_apps = [app for app in installed if app not in FRAMEWORK_APPS]
	except Exception:
		pass

	context.available_apps = sorted(available_apps)

	context.doc = None
	context.inventory = []

	if scan_name:
		if not frappe.db.exists("Dead Code Eliminator", scan_name):
			frappe.throw(_("Scan not found"), frappe.DoesNotExistError)
		if not frappe.has_permission("Dead Code Eliminator", "read", doc=scan_name):
			frappe.throw(_("Not permitted to view this scan"), frappe.PermissionError)

		doc = frappe.get_doc("Dead Code Eliminator", scan_name)
		context.doc = doc
		context.inventory = doc.get("inventory") or []

	return context
