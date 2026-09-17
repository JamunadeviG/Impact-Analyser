# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

"""
Orchestrator - background job that drives the full analysis pipeline.

Stages
------
1. Interpreting  : AI Interpreter extracts structured target from a free-text prompt.
                   (Skipped on Direct Target / Full Scan paths.)
2. Scanning      : File Scanner (Task 5) + DB Scanner (Task 6) build the ScanReport.
3. Drafting      : AI Drafter (Task 7) proposes a structured change plan.
4. Formatting    : AI Formatter (Task 8) scores, validates and writes the final report.
5. Complete      : Run is submitted (docstatus=1) - immutable audit record.

On any unhandled exception the run is set to Failed (stays draft, docstatus=0).
"""

import json
import frappe
from frappe import _


# Stage progress percentages (for UI progress bar)
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
		frappe.log_error(f"Impact Analysis Run {run_id} not found", "Orchestrator")
		return

	try:
		_run_pipeline_inner(run)
	except Exception as exc:
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

	run.reload()
	run.scan_report = json.dumps(scan_report, indent=2, default=str)
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep

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
	run.reload()
	run.status = "Complete"
	run.save(ignore_permissions=True)
	run.submit()
	frappe.db.commit()  # nosemgrep

	_publish(run.name, "Complete", "Analysis complete - report ready!")


# Helpers
def _set_status(run, status: str, message: str = "") -> None:
	"""Update run status in DB and publish realtime event."""
	run.reload()
	run.status = status
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
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
	frappe.publish_realtime(
		"impact_analyzer_progress",
		{"run_id": run_id, "status": status, "message": message},
		after_commit=False,
	)


def _build_target(run, extraction_result) -> dict:
	"""Build a unified target dict from the run + optional interpreter output."""
	target = {
		"app": run.app or "",
		"doctype": run.doctype_target or "",
		"filenames": [f.strip() for f in (run.filenames or "").split(",") if f.strip()],
		"functions": [f.strip() for f in (run.functions or "").split(",") if f.strip()],
	}
	if extraction_result and isinstance(extraction_result, dict):
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
