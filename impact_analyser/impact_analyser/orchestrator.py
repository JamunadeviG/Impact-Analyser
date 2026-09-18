<<<<<<< HEAD
﻿# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

"""
Orchestrator - background job that drives the full analysis pipeline.
=======
# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

"""
Orchestrator — background job that drives the full analysis pipeline.
>>>>>>> 3871c81 (latest ui process and ai update)

Stages
------
1. Interpreting  : AI Interpreter extracts structured target from a free-text prompt.
                   (Skipped on Direct Target / Full Scan paths.)
<<<<<<< HEAD
2. Scanning      : File Scanner (Task 5) + DB Scanner (Task 6) build the ScanReport.
3. Drafting      : AI Drafter (Task 7) proposes a structured change plan.
4. Formatting    : AI Formatter (Task 8) scores, validates and writes the final report.
5. Complete      : Run is submitted (docstatus=1) - immutable audit record.

On any unhandled exception the run is set to Failed (stays draft, docstatus=0).
=======
                   Branches if query is informational (intent: "list_fields").
2. Scanning      : File Scanner (Task 5) + DB Scanner (Task 6) build the ScanReport.
3. Drafting      : AI Drafter (Task 7) proposes a structured change plan.
4. Formatting    : AI Formatter (Task 8) scores, validates and writes the final report.
5. Complete      : Run is submitted (docstatus=1) — immutable audit record.

On any unhandled exception the run is set to Failed (stays draft, docstatus=0)
with full traceback and error message logged and recorded in the run document.
>>>>>>> 3871c81 (latest ui process and ai update)
"""

import json
import frappe
from frappe import _


<<<<<<< HEAD
# Stage progress percentages (for UI progress bar)
=======
>>>>>>> 3871c81 (latest ui process and ai update)
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
<<<<<<< HEAD
		frappe.log_error(f"Impact Analysis Run {run_id} not found", "Orchestrator")
=======
		frappe.log_error(f"Impact Analysis Run {run_id} not found", "Impact Analyzer")
		return

	# Idempotency guard: skip if already in a terminal state
	if run.docstatus == 1 or run.status in ("Complete", "Failed"):
		frappe.logger("impact_analyser").info(
			f"run_pipeline skipped for {run_id}: already terminal "
			f"(status={run.status}, docstatus={run.docstatus})"
		)
>>>>>>> 3871c81 (latest ui process and ai update)
		return

	try:
		_run_pipeline_inner(run)
	except Exception as exc:
<<<<<<< HEAD
		_fail(run, str(exc))
		frappe.log_error(frappe.get_traceback(), f"Impact Analyzer Pipeline Failed - {run_id}")


# Inner pipeline (raises on error so the outer try/except catches it)
def _run_pipeline_inner(run) -> None:
	path = run.path_used  # "AI Interpretation" | "Direct Target" | "Full Scan"

	# Stage 1: Interpret (only on AI Interpretation path)
	extraction_result = None
	if path == "AI Interpretation":
		_set_status(run, "Interpreting", "Interpreting your prompt...")
		try:
			from impact_analyser.ai.interpreter import interpret
			extraction_result = interpret(run)
		except Exception:
			extraction_result = _mock_extraction(run)

	# Stage 2: Scan
	_set_status(run, "Scanning", "Scanning codebase and database customizations...")
	target = _build_target(run, extraction_result)

	try:
		try:
			from impact_analyser.scanner.file_scanner import scan_files
			from impact_analyser.scanner.db_scanner import find_db_usages
		except ImportError:
			from impact_analyser.impact_analyser.scanner.file_scanner import scan_files
			from impact_analyser.impact_analyser.scanner.db_scanner import find_db_usages

		file_hits = scan_files(run.app or "frappe", target)
		db_hits = find_db_usages(target)
		scan_report = {"file_hits": file_hits, "db_hits": db_hits, "target": target}
	except Exception as exc:
		frappe.log_error(f"Error during impact scan: {exc}\n{frappe.get_traceback()}", "Impact Analyzer Scanner")
		scan_report = {"file_hits": [], "db_hits": [], "target": target}
=======
		tb = frappe.get_traceback()
		_fail(run, str(exc), tb)
		frappe.log_error(tb, f"Impact Analyzer Pipeline Failed — {run_id}")


def _run_pipeline_inner(run) -> None:
	path = run.path_used  # "AI Interpretation" | "Direct Target" | "Full Scan"

	# ── Stage 1: Interpret (only on AI Interpretation path) ───────────────────
	extraction_result = None
	if path == "AI Interpretation":
		_set_status(run, "Interpreting", "🤖 Interpreting your prompt with AI…")
		from impact_analyser.ai.interpreter import interpret
		extraction_result = interpret(run)

		# Informational schema query branching (list_fields)
		if extraction_result and extraction_result.get("intent") == "list_fields":
			_handle_list_fields(run, extraction_result)
			return

	# ── Stage 2: Scan ─────────────────────────────────────────────────────────
	_set_status(run, "Scanning", "🔍 Scanning codebase and database customizations…")
	from impact_analyser.scanner.file_scanner import scan_files
	from impact_analyser.scanner.db_scanner import find_db_usages

	target = _build_target(run, extraction_result)
	scan_app = run.app or target.get("app") or "frappe"
	file_hits = scan_files(scan_app, target)
	db_hits = find_db_usages(target)
	scan_report = {"file_hits": file_hits, "db_hits": db_hits, "target": target}
>>>>>>> 3871c81 (latest ui process and ai update)

	run.reload()
	run.scan_report = json.dumps(scan_report, indent=2, default=str)
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep

<<<<<<< HEAD
	# Stage 3: Draft
	_set_status(run, "Drafting", "Drafting change analysis...")
	try:
		from impact_analyser.ai.drafter import draft
		from impact_analyser.scanner.validator import validate

		change_plan = draft(run, scan_report)
		verified_changes = validate(change_plan)
	except Exception:
		# Drafter/Validator fallback - convert scanner hits directly
		verified_changes = _mock_verified_changes(scan_report)

	# Stage 4: Format
	_set_status(run, "Formatting", "Formatting impact report...")
	try:
		from impact_analyser.ai.formatter import format_report
		format_report(run, verified_changes)
	except Exception:
		_write_placeholder_report(run, verified_changes)

	# Stage 5: Complete
=======
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
>>>>>>> 3871c81 (latest ui process and ai update)
	run.reload()
	run.status = "Complete"
	run.save(ignore_permissions=True)
	run.submit()
	frappe.db.commit()  # nosemgrep

<<<<<<< HEAD
	_publish(run.name, "Complete", "Analysis complete - report ready!")


# Helpers
=======
	_publish(run, "Complete", "✅ Analysis complete — report ready!")


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
		"<th style='padding:8px 12px; border:1px solid rgba(255,255,255,0.15);'>Fieldtype</th>",
		"<th style='padding:8px 12px; border:1px solid rgba(255,255,255,0.15);'>Mandatory</th>",
		"</tr></thead><tbody>",
	]

	for fld in doctype_fields:
		reqd_badge = "<span style='color:#f87171; font-weight:600;'>Yes</span>" if fld["reqd"] else "<span style='opacity:0.5;'>No</span>"
		html_lines.append(
			f"<tr>"
			f"<td style='padding:8px 12px; border:1px solid rgba(255,255,255,0.1); font-weight:500;'>{fld['label']}</td>"
			f"<td style='padding:8px 12px; border:1px solid rgba(255,255,255,0.1); font-family:monospace; color:#60a5fa;'>{fld['fieldname']}</td>"
			f"<td style='padding:8px 12px; border:1px solid rgba(255,255,255,0.1);'>{fld['fieldtype']}</td>"
			f"<td style='padding:8px 12px; border:1px solid rgba(255,255,255,0.1);'>{reqd_badge}</td>"
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

>>>>>>> 3871c81 (latest ui process and ai update)
def _set_status(run, status: str, message: str = "") -> None:
	"""Update run status in DB and publish realtime event."""
	run.reload()
	run.status = status
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
<<<<<<< HEAD
	_publish(run.name, status, message)


def _fail(run, error_msg: str) -> None:
	"""Mark run as Failed (stays Draft, docstatus=0)."""
	try:
		run.reload()
		run.status = "Failed"
		run.save(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
	except Exception:
		pass
	_publish(run.name, "Failed", f"Error: {error_msg}")


def _publish(run_id: str, status: str, message: str = "") -> None:
	"""Publish realtime progress event."""
=======
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
>>>>>>> 3871c81 (latest ui process and ai update)
	frappe.publish_realtime(
		"impact_analyzer_progress",
		{"run_id": run_id, "status": status, "message": message},
		after_commit=False,
	)

<<<<<<< HEAD
=======
	frappe.logger("impact_analyser").info(f"Published realtime [{status}] for {run_id}: {message}")

>>>>>>> 3871c81 (latest ui process and ai update)

def _build_target(run, extraction_result) -> dict:
	"""Build a unified target dict from the run + optional interpreter output."""
	target = {
		"app": run.app or "",
		"doctype": run.doctype_target or "",
<<<<<<< HEAD
=======
		"fields": [],
>>>>>>> 3871c81 (latest ui process and ai update)
		"filenames": [f.strip() for f in (run.filenames or "").split(",") if f.strip()],
		"functions": [f.strip() for f in (run.functions or "").split(",") if f.strip()],
	}
	if extraction_result and isinstance(extraction_result, dict):
<<<<<<< HEAD
		target["doctype"] = target["doctype"] or extraction_result.get("doctype", "")
		target["filenames"] = target["filenames"] or extraction_result.get("files", [])
		target["functions"] = target["functions"] or extraction_result.get("functions", [])
	return target


def _mock_extraction(run) -> dict:
	"""Minimal extraction when AI Interpreter is not yet available."""
	return {
		"app": run.app or "",
		"doctype": run.doctype_target or "",
		"fields": [],
		"functions": [],
		"files": [],
		"confidence": 0.0,
		"clarification_needed": "AI Interpreter module not yet installed.",
	}


def _mock_verified_changes(scan_report: dict) -> list:
	"""Return hits from scan_report as pre-verified change stubs with their computed severity."""
	changes = []
	for hit in scan_report.get("file_hits", []):
		impact = hit.get("severity") or hit.get("impact") or "Medium"
		changes.append({
			"file": hit.get("file", ""),
			"line": hit.get("line", 0) or 0,
			"source": "File",
			"impact": impact,
			"reason": hit.get("snippet", ""),
			"suggested_action": "Review this usage before making the change.",
			"snippet": hit.get("snippet", ""),
			"usage_type": hit.get("usage_type", ""),
		})
	for hit in scan_report.get("db_hits", []):
		impact = hit.get("severity") or hit.get("impact") or "High"
		changes.append({
			"file": hit.get("file") or (hit.get("doctype", "") + ": " + hit.get("name", "")),
			"line": hit.get("line", 0) or 0,
			"source": "Database",
			"impact": impact,
			"reason": hit.get("snippet", ""),
			"suggested_action": "Update or migrate this customization.",
			"snippet": hit.get("snippet", ""),
			"usage_type": hit.get("usage_type", ""),
		})
	return changes


def _write_placeholder_report(run, verified_changes: list) -> None:
	"""Write a formatted summary and populate child table from verified changes."""
	high = sum(1 for c in verified_changes if c.get("impact") == "High")
	med  = sum(1 for c in verified_changes if c.get("impact") == "Medium")
	low  = sum(1 for c in verified_changes if c.get("impact") == "Low")
	total = len(verified_changes)

	file_count = sum(1 for c in verified_changes if c.get("source") == "File")
	db_count = sum(1 for c in verified_changes if c.get("source") == "Database")

	if total > 0:
		run.summary = (
			f"<p><strong>Scan complete.</strong> "
			f"Found <strong>{total}</strong> potential impact points "
			f"({file_count} in files, {db_count} in database customizations): "
			f"<span style='color:#f87171;'><strong>{high} High</strong></span>, "
			f"<span style='color:#fb923c;'><strong>{med} Medium</strong></span>, "
			f"<span style='color:#60a5fa;'><strong>{low} Low</strong></span>.</p>"
		)
	else:
		run.summary = "<p><strong>Scan complete.</strong> Found <strong>0</strong> potential impact points. No direct references detected.</p>"

	# Write child table rows
	run.set("changes", [])
	for c in verified_changes:
		run.append(
			"changes",
			{
				"file": c.get("file", "")[:255],
				"line": c.get("line", 0) or 0,
				"source": c.get("source", "File"),
				"impact": c.get("impact", "Low"),
				"reason": c.get("reason", "")[:140] if c.get("reason") else "",
				"suggested_action": c.get("suggested_action", ""),
				"snippet": c.get("snippet", ""),
				"usage_type": c.get("usage_type", "")[:140] if c.get("usage_type") else "",
			},
		)

	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
=======
		target["app"] = target["app"] or extraction_result.get("app", "")
		target["doctype"] = target["doctype"] or extraction_result.get("doctype", "")
		extracted_files = extraction_result.get("files") or []
		extracted_functions = extraction_result.get("functions") or []
		extracted_fields = extraction_result.get("fields") or []

		target["filenames"] = list(set(target["filenames"] + [f for f in extracted_files if f]))
		target["functions"] = list(set(target["functions"] + [f for f in extracted_functions if f]))
		target["fields"] = [f.strip() for f in extracted_fields if f and f.strip()]
	return target
>>>>>>> 3871c81 (latest ui process and ai update)
