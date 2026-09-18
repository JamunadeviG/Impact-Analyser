# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

"""
Orchestrator — background job that drives the full analysis pipeline.

Stages
------
1. Interpreting  : AI Interpreter extracts structured target from a free-text prompt.
                   (Skipped on Direct Target / Full Scan paths.)
                   Branches if query is informational (intent: "list_fields").
                   Terminates early with user warning if intent is "invalid".
2. Scanning      : File Scanner + DB Scanner build the ScanReport.
3. Drafting      : AI Drafter proposes a structured change plan.
4. Formatting    : AI Formatter scores, validates and writes the final report.
5. Complete      : Run is submitted (docstatus=1) — immutable audit record.

On any unhandled exception the run is set to Failed (stays draft, docstatus=0)
with full traceback and error message logged and recorded in the run document.
"""

import json
import traceback
import frappe
from frappe import _


STAGE_PROGRESS = {
	"Queued": 5,
	"Interpreting": 20,
	"Scanning": 45,
	"Drafting": 70,
	"Formatting": 90,
	"Complete": 100,
	"Failed": 100,
}


def run_pipeline(run_id: str) -> None:
	"""
	Main background job entry point.

	Parameters
	----------
	run_id : str
		Name of the Impact Analysis Run document (e.g. IAR-00001).
	"""
	try:
		run = frappe.get_doc("Impact Analysis Run", run_id)
	except frappe.DoesNotExistError:
		frappe.log_error(f"Impact Analysis Run {run_id} not found", "Impact Analyzer")
		return

	# Idempotency guard: skip if already in a terminal state
	if run.docstatus == 1 or run.status in ("Complete", "Failed"):
		frappe.logger("impact_analyser").info(
			f"run_pipeline skipped for {run_id}: already terminal "
			f"(status={run.status}, docstatus={run.docstatus})"
		)
		return

	try:
		_run_pipeline_inner(run)
	except Exception as exc:
		tb = traceback.format_exc()
		frappe.log_error(f"Impact Analyzer pipeline failed for {run_id}: {exc}\n{tb}", "Impact Analyzer")
		_fail(run, str(exc), tb)


def _run_pipeline_inner(run) -> None:
	"""Execute the pipeline stages sequentially."""

	# ── Stage 1: Interpret ────────────────────────────────────────────────────
	extraction_result = None
	if run.path_used == "AI Interpretation" and run.prompt:
		_set_status(run, "Interpreting", "🔍 Interpreting your prompt with AI…")
		from impact_analyser.ai.interpreter import interpret
		extraction_result = interpret(run)

		# ── REFINEMENT 2: Reject invalid prompts immediately ──────────────────
		# If the intent is "invalid" (greeting, noise, nonsense), stop the
		# pipeline immediately. Do NOT scan, draft, or format. Show the user a
		# clear warning in the summary instead.
		if extraction_result and extraction_result.get("intent") == "invalid":
			_handle_invalid_prompt(run)
			return

		# Informational schema query branching (list_fields)
		if extraction_result and extraction_result.get("intent") == "list_fields":
			_handle_list_fields(run, extraction_result)
			return

	# ── Stage 2: Scan ─────────────────────────────────────────────────────────
	_set_status(run, "Scanning", "🔍 Scanning codebase and database customizations…")
	from impact_analyser.scanner.file_scanner import scan_files
	from impact_analyser.scanner.db_scanner import find_db_usages

	target = _build_target(run, extraction_result)
	if target.get("doctype") and not frappe.db.exists("DocType", target["doctype"]):
		frappe.throw(_("DocType '{0}' does not exist.").format(target["doctype"]))
	scan_app = run.app or target.get("app") or "frappe"
	file_hits = scan_files(scan_app, target)
	db_hits = find_db_usages(target)
	scan_report = {"file_hits": file_hits, "db_hits": db_hits, "target": target}

	run.reload()
	run.scan_report = json.dumps(scan_report, indent=2, default=str)
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep

	# ── Stage 3: Draft ────────────────────────────────────────────────────────
	_set_status(run, "Drafting", "📝 Drafting change analysis with AI…")
	from impact_analyser.ai.drafter import draft
	from impact_analyser.scanner.validator import validate

	change_plan = draft(run, scan_report)
	verified_changes = validate(change_plan, app_name=scan_app)

	# ── Stage 4: Format ───────────────────────────────────────────────────────
	_set_status(run, "Formatting", "✨ Formatting impact report…")
	from impact_analyser.ai.formatter import format_report
	format_report(run, verified_changes)

	# ── Stage 5: Complete ─────────────────────────────────────────────────────
	run.reload()
	run.status = "Complete"
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
	run.submit()
	frappe.db.commit()  # nosemgrep

	_publish(run, "Complete", "✅ Impact analysis complete.")


# ── Special Branch Handlers ───────────────────────────────────────────────────

def _handle_invalid_prompt(run) -> None:
	"""
	Terminate the pipeline immediately for invalid/nonsense prompts.
	Sets status to Failed with a user-friendly warning summary.
	"""
	warning_summary = (
		"<div class='ia-error-summary' style='color:#fb923c; padding: 16px;'>"
		"<p><strong>⚠️ Your prompt doesn't look like a valid analysis request.</strong></p>"
		"<p>Please describe what you want to check. For example:</p>"
		"<ul>"
		"<li><em>\"What fields are available in Airplane Ticket?\"</em></li>"
		"<li><em>\"What breaks if I rename the flight field in Airplane Ticket?\"</em></li>"
		"<li><em>\"Which files use the validate_items function in Delivery Note?\"</em></li>"
		"</ul>"
		"</div>"
	)
	try:
		run.reload()
		if run.docstatus != 1:
			run.status = "Failed"
			run.summary = warning_summary
			run.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep
	except Exception:
		pass
	_publish(run, "Failed", "⚠️ Invalid prompt — please describe a field listing or impact analysis request.")


def _handle_list_fields(run, extraction_result: dict) -> None:
	"""
	Directly retrieve and format the schema/fields of the target DocType.
	Bypasses expensive codebase/DB scanners for read-only schema queries.
	"""
	doctype = (
		extraction_result.get("doctype")
		or run.doctype_target
		or ""
	).strip()

	if not doctype:
		frappe.throw(_("No DocType specified for listing fields."))

	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType '{0}' does not exist.").format(doctype))

	meta = frappe.get_meta(doctype)

	doctype_fields = []
	for df in meta.fields:
		if df.fieldtype in ("Section Break", "Column Break", "Tab Break"):
			continue
		opt_str = f" ({df.options})" if df.options and df.fieldtype in ("Link", "Select", "Table") else ""
		doctype_fields.append({
			"fieldname": df.fieldname,
			"label": df.label or df.fieldname,
			"fieldtype": f"{df.fieldtype}{opt_str}",
			"reqd": df.reqd or 0,
		})

	# Build rich HTML summary table
	html_lines = [
		f"<h3>Available Fields for DocType: <code>{doctype}</code></h3>",
		f"<p>Found <strong>{len(doctype_fields)}</strong> fields defined in DocType <em>{doctype}</em> (Module: {meta.module}).</p>",
		"<div style='overflow-x:auto; margin-top:16px;'>",
		"<table class='table table-bordered' style='width:100%; border-collapse:collapse; font-size:13px;'>",
		"<thead><tr style='background:rgba(255,255,255,0.08); text-align:left;'>",
		"<th style='padding:8px 12px; border:1px solid rgba(255,255,255,0.15);'>Label</th>",
		"<th style='padding:8px 12px; border:1px solid rgba(255,255,255,0.15);'>Fieldname</th>",
		"<th style='padding:8px 12px; border:1px solid rgba(255,255,255,0.15);'>Type</th>",
		"<th style='padding:8px 12px; border:1px solid rgba(255,255,255,0.15);'>Mandatory</th>",
		"</tr></thead><tbody>",
	]
	for i, fld in enumerate(doctype_fields):
		row_bg = "background:rgba(255,255,255,0.03)" if i % 2 else ""
		reqd_cell = (
			"<span style='color:#4ade80; font-weight:600;'>Yes</span>"
			if fld["reqd"]
			else "<span style='opacity:0.5'>No</span>"
		)
		html_lines.append(
			f"<tr style='{row_bg}'>"
			f"<td style='padding:8px 12px;border:1px solid rgba(255,255,255,0.1);font-weight:500'>{fld['label']}</td>"
			f"<td style='padding:8px 12px;border:1px solid rgba(255,255,255,0.1);font-family:monospace;color:#60a5fa'>{fld['fieldname']}</td>"
			f"<td style='padding:8px 12px;border:1px solid rgba(255,255,255,0.1)'>{fld['fieldtype']}</td>"
			f"<td style='padding:8px 12px;border:1px solid rgba(255,255,255,0.1)'>{reqd_cell}</td>"
			f"</tr>"
		)

	html_lines.append("</tbody></table></div>")

	scan_report = {
		"intent": "list_fields",
		"doctype": doctype,
		"total_fields": len(doctype_fields),
		"fields": doctype_fields,
		"file_hits": [],
		"db_hits": [],
	}

	run.reload()
	run.scan_report = json.dumps(scan_report, indent=2, default=str)
	run.summary = "".join(html_lines)
	run.status = "Complete"
	# Save all data first, commit, then submit to make doc immutable
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
	run.submit()
	frappe.db.commit()  # nosemgrep

	_publish(run, "Complete", f"✅ Available fields for '{doctype}' retrieved successfully.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_status(run, status: str, message: str = "") -> None:
	"""Update run status in DB and publish realtime event."""
	run.reload()
	run.status = status
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
	_publish(run, status, message)


def _fail(run, error_msg: str, traceback_str: str = "") -> None:
	"""Mark run as Failed with detailed message and traceback recorded in run doc."""
	try:
		run.reload()
		if run.docstatus == 1:
			# Doc already submitted -- cannot write, just log the error
			frappe.logger("impact_analyser").error(
				f"Cannot mark submitted run {run.name} as Failed: {error_msg}"
			)
		else:
			run.status = "Failed"
			tb_escaped = frappe.utils.escape_html(traceback_str) if traceback_str else ""
			err_escaped = frappe.utils.escape_html(error_msg)
			tb_block = f"<pre style='background:rgba(0,0,0,0.5); padding:10px; border-radius:6px; font-size:11px; overflow-x:auto;'><code>{tb_escaped}</code></pre>" if tb_escaped else ""
			run.summary = (
				f"<div class='ia-error-summary' style='color:#f87171;'>"
				f"<p><strong>❌ Pipeline Execution Failed:</strong> {err_escaped}</p>"
				f"{tb_block}"
				f"</div>"
			)
			run.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep
	except Exception:
		pass
	_publish(run, "Failed", f"❌ {error_msg}")


def _publish(run, status: str, message: str = "") -> None:
	"""Publish realtime progress event to user room and site broadcast with server logging."""
	run_id = run.name if hasattr(run, "name") else str(run)
	user = getattr(run, "triggered_by", None)

	# 1. Publish to user room if triggered_by user exists
	if user:
		frappe.publish_realtime(
			"impact_analyzer_progress",
			{"run_id": run_id, "status": status, "message": message},
			user=user,
			after_commit=False,
		)

	# 2. Publish to site room for general listeners
	frappe.publish_realtime(
		"impact_analyzer_progress",
		{"run_id": run_id, "status": status, "message": message},
		after_commit=False,
	)

	frappe.logger("impact_analyser").info(f"Published realtime [{status}] for {run_id}: {message}")


def _build_target(run, extraction_result) -> dict:
	"""Build a unified target dict from the run + optional interpreter output."""
	target = {
		"app": run.app or "",
		"doctype": run.doctype_target or "",
		"fields": [],
		"filenames": [f.strip() for f in (run.filenames or "").split(",") if f.strip()],
		"functions": [f.strip() for f in (run.functions or "").split(",") if f.strip()],
	}
	if extraction_result and isinstance(extraction_result, dict):
		target["app"] = target["app"] or extraction_result.get("app", "")
		target["doctype"] = target["doctype"] or extraction_result.get("doctype", "")
		extracted_files = extraction_result.get("files") or []
		extracted_functions = extraction_result.get("functions") or []
		extracted_fields = extraction_result.get("fields") or []

		target["filenames"] = list(set(target["filenames"] + [f for f in extracted_files if f]))
		target["functions"] = list(set(target["functions"] + [f for f in extracted_functions if f]))
		target["fields"] = [f.strip() for f in extracted_fields if f and f.strip()]
	return target
