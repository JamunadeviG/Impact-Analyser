# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from impact_analyser.ai.client import call_gemini, get_settings


FORMATTER_SYSTEM_PROMPT = """You are an expert Frappe Framework technical writer and software architect.
Your task is to write a concise, professional Executive Summary for an Impact Analysis Report.
You will be given the total number of changes, their impact ratings (High, Medium, Low), and a list of the most critical verified changes.

Output ONLY a rich HTML string (no markdown, no ```html code blocks) containing the executive summary.
Use <p>, <strong>, <ul>, and <li> tags for formatting.
Do NOT include <html> or <body> tags.

The summary should:
1. State the overall risk level (High, Medium, or Low).
2. Summarize the most critical impact points (e.g., "Changes to X will affect Y Workflow and Z Server Script").
3. Provide a clear recommendation on whether the change is safe to proceed or requires significant refactoring/testing.
"""


def format_report(run, verified_changes: list) -> None:
	"""
	Formatter stage: Generate HTML executive summary and write changes to the DB document.

	Parameters
	----------
	run : Impact Analysis Run document
	verified_changes : list[dict]
		List of validated change objects from Validator.
	"""
	high_impact = [c for c in verified_changes if c.get("impact") == "High"]
	med_impact = [c for c in verified_changes if c.get("impact") == "Medium"]
	low_impact = [c for c in verified_changes if c.get("impact") == "Low"]

	# Prepare prompt for Claude to generate the summary
	prompt_payload = {
		"target": {
			"app": run.app,
			"doctype": run.doctype_target,
			"filenames": run.filenames,
			"functions": run.functions,
		},
		"stats": {
			"total": len(verified_changes),
			"high": len(high_impact),
			"medium": len(med_impact),
			"low": len(low_impact),
		},
		"critical_changes_sample": high_impact[:10] if high_impact else med_impact[:5],
	}

	prompt = json.dumps(prompt_payload, indent=2, default=str)
	settings = get_settings()
	model = settings.report_model or "gemini-1.5-pro"

	# Generate summary narrative
	if verified_changes:
		raw_summary = call_gemini(
			prompt=prompt,
			system_prompt=FORMATTER_SYSTEM_PROMPT,
			model=model,
			run_id=run.name,
			stage="Formatting",
		)
		# Clean markdown if Claude included it accidentally
		summary = raw_summary.strip()
		if summary.startswith("```html"):
			summary = summary.replace("```html", "", 1)
		if summary.endswith("```"):
			summary = summary[:-3]
		summary = summary.strip()
	else:
		summary = "<p><strong>No Impact Found:</strong> The target was not found in the scanned files or database customizations. This change appears to be safe.</p>"

	run.reload()
	run.summary = summary

	# Populate child table
	run.set("changes", [])
	for c in verified_changes:
		run.append(
			"changes",
			{
				"file": c.get("file", "")[:255],
				"line": c.get("line", 0) or 0,
				"source": c.get("source", "File"),
				"impact": c.get("impact", "Low"),
				"reason": c.get("reason", ""),
				"suggested_action": c.get("suggested_action", ""),
				"snippet": c.get("snippet", ""),
				"usage_type": c.get("usage_type", "")[:140],
			},
		)

	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep
