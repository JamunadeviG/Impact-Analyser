import frappe
from frappe import _


def get_context(context):
	# This page shows scan results, which can reveal internal file paths
	# and code structure — require login, same as the desk form would.
	if frappe.session.user == 'Guest':
		frappe.throw(_('You need to be logged in to view this page'), frappe.PermissionError)

	context.no_cache = 1
	context.title = 'Dead Code Eliminator'

	scan_name = frappe.form_dict.get('scan')

	# List of recent scans, for the landing/list state of the page.
	context.scans = frappe.get_all(
		'Dead Code Eliminator',
		fields=[
			'name', 'target_app', 'status',
			'total_files_scanned', 'total_dead_items',
			'low_risk_count', 'medium_risk_count', 'high_risk_count',
			'modified',
		],
		order_by='modified desc',
		limit_page_length=50,
	)

	context.doc = None
	context.inventory = []

	if scan_name:
		if not frappe.db.exists('Dead Code Eliminator', scan_name):
			frappe.throw(_('Scan not found'), frappe.DoesNotExistError)
		if not frappe.has_permission('Dead Code Eliminator', 'read', doc=scan_name):
			frappe.throw(_('Not permitted to view this scan'), frappe.PermissionError)

		doc = frappe.get_doc('Dead Code Eliminator', scan_name)
		context.doc = doc
		context.inventory = doc.get('inventory') or []

	return context
