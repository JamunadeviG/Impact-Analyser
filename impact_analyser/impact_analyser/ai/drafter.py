# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import json
import re
import frappe
from frappe import _
from impact_analyser.ai.client import call_gemini, get_settings


DRAFTER_SYSTEM_PROMPT = """You are an expert Frappe Framework software architect.
You are given a ScanReport containing raw file and database hits found during codebase analysis.

Your task is to convert these raw scan hits into a structured Change Plan list.
Assign an impact severity ("High", "Medium", or "Low") to each hit based on these rules:
- High: Validation hooks, API endpoints, Server Scripts, Workflows, core field schema changes, >5 usages.
- Medium: Reports, Print Formats, Client Scripts, Notifications, Dashboard Charts, depends_on expressions.
- Low: Comments, unused imports, docstrings, generic string mentions.

Output ONLY a JSON array of change objects matching this schema:
[
  {
    "file": "relative/filepath or DB doc name",
    "line": line_number_int,
    "source": "File" or "Database",
    "impact": "High" or "Medium" or "Low",
    "reason": "Clear explanation of why this point is impacted and what might break",
    "suggested_action": "Specific refactoring or migration steps required",
    "snippet": "exact line snippet",
    "usage_type": "usage type description"
  }
]

Do NOT output any markdown text outside the JSON array block.
"""


def draft(run, scan_report: dict) -> list:
	"""
	AI Drafter stage entry point.

	Parameters
	----------
	run : Impact Analysis Run document
	scan_report : dict containing 'file_hits', 'db_hits', and 'target'

	Returns
	-------
	list[dict] : Change plan proposed by Claude.
	"""
	file_hits = scan_report.get("file_hits", [])
	db_hits = scan_report.get("db_hits", [])
	target = scan_report.get("target", {})

	if not file_hits and not db_hits:
		return []

	# Truncate scan hits if extremely large to fit in prompt token budget
	combined_hits = file_hits[:100] + db_hits[:50]

	prompt_payload = {
		"target": target,
		"total_file_hits": len(file_hits),
		"total_db_hits": len(db_hits),
		"hits": combined_hits,
	}

	prompt = json.dumps(prompt_payload, indent=2, default=str)
	settings = get_settings()
	model = settings.report_model or "gemini-1.5-pro"

	raw_response = call_gemini(
		prompt=prompt,
		system_prompt=DRAFTER_SYSTEM_PROMPT,
		model=model,
		run_id=run.name,
		stage="Drafting",
	)

	change_plan = _parse_change_plan_json(raw_response, combined_hits)
	return change_plan


def _parse_change_plan_json(raw_text: str, fallback_hits: list) -> list:
	"""Parse AI JSON response array into a list of change objects."""
	cleaned = raw_text.strip()
	if "```json" in cleaned:
		cleaned = cleaned.split("```json")[1].split("```")[0].strip()
	elif "```" in cleaned:
		cleaned = cleaned.split("```")[1].split("```")[0].strip()

	try:
		data = json.loads(cleaned)
		if isinstance(data, list):
			return data
	except Exception:
		match = re.search(r"\[.*\]", cleaned, re.DOTALL)
		if match:
			try:
				return json.loads(match.group(0))
			except Exception:
				pass

	# Fallback if AI JSON formatting failed
	changes = []
	for hit in fallback_hits:
		source = hit.get("source", "File")
		changes.append({
			"file": hit.get("file", ""),
			"line": hit.get("line", 0),
			"source": source,
			"impact": "High" if source == "Database" else "Medium",
			"reason": f"Usage detected in {hit.get('usage_type', 'code')}",
			"suggested_action": "Review and verify usage before applying change.",
			"snippet": hit.get("snippet", ""),
			"usage_type": hit.get("usage_type", ""),
		})
	return changes
