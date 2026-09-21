import frappe

no_cache = 1

def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/impact-analyzer"
		raise frappe.Redirect

	csrf_token = ""
	if hasattr(frappe.local, "session") and getattr(frappe.local.session, "data", None):
		csrf_token = getattr(frappe.local.session.data, "csrf_token", "")
	context.csrf_token = csrf_token
