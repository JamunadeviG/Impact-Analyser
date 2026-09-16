# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist()
def get_apps_list():
	"""Return list of installed app names for the App selector in the Desk Page."""
	return frappe.get_installed_apps()


@frappe.whitelist()
def analyze(app=None, doctype=None, filenames=None, functions=None, prompt=None):
	"""
	Entry point called from the Desk Page.

	Determines the scan path (AI Interpretation / Direct Target / Full Scan),
	creates an Impact Analysis Run document, enqueues the background pipeline,
	and returns the run_id so the frontend can subscribe to realtime events.

	Scan paths
	----------
	Path 1 – AI Interpretation : ``prompt`` is non-empty
	Path 2 – Direct Target     : ``doctype``, ``filenames``, or ``functions`` given (no prompt)
	Path 3 – Full Scan         : nothing specific — scans the whole app
	"""
	# ── Determine scan path ────────────────────────────────────────────────────
	prompt = (prompt or "").strip()
	doctype = (doctype or "").strip()
	filenames = (filenames or "").strip()
	functions = (functions or "").strip()
	app = (app or "").strip()

	if not app and not doctype and not filenames and not functions and not prompt:
		frappe.throw(_("Please specify an app, a target (DocType / files / functions), or a prompt."))

	user = frappe.session.user
	if user != "Administrator":
		active_runs = frappe.db.count(
			"Impact Analysis Run",
			filters={
				"triggered_by": user,
				"status": ("in", ["Queued", "Interpreting", "Scanning", "Drafting", "Formatting"]),
			},
		)
		if active_runs >= 5:
			frappe.throw(_("You have reached the maximum limit of 5 concurrent analysis runs. Please wait for them to complete."))

	if prompt:
		path_used = "AI Interpretation"
	elif doctype or filenames or functions:
		path_used = "Direct Target"
	else:
		path_used = "Full Scan"

	# ── Create Impact Analysis Run ─────────────────────────────────────────────
	run = frappe.get_doc(
		{
			"doctype": "Impact Analysis Run",
			"app": app,
			"doctype_target": doctype or None,
			"filenames": filenames or None,
			"functions": functions or None,
			"prompt": prompt or None,
			"path_used": path_used,
			"status": "Queued",
			"triggered_by": frappe.session.user,
		}
	)
	run.insert(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep

	# ── Publish initial realtime event ─────────────────────────────────────────
	_publish(run.name, "Queued", "Queued — waiting for background worker…")

	# ── Enqueue background pipeline ────────────────────────────────────────────
	frappe.enqueue(
		"impact_analyser.orchestrator.run_pipeline",
		queue="default",
		timeout=600,
		run_id=run.name,
		now=False,
	)

	return {"status": "Queued", "run_id": run.name}


@frappe.whitelist()
def get_run(run_id):
	"""Fetch a single Impact Analysis Run document (used after Complete event)."""
	if not frappe.has_permission("Impact Analysis Run", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_doc("Impact Analysis Run", run_id).as_dict()


def _publish(run_id, status, message=""):
	"""Publish a realtime progress event for the given run."""
	frappe.publish_realtime(
		"impact_analyzer_progress",
		{"run_id": run_id, "status": status, "message": message},
		after_commit=False,
	)
