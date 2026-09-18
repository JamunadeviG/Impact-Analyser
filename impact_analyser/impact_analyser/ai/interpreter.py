
import json
import re
import frappe
from frappe import _
from impact_analyser.ai.client import call_gemini, get_settings


INTERPRETER_SYSTEM_PROMPT = """You are an expert Frappe Framework codebase analyzer.
Your task is to analyze user queries asking about changing code, DocTypes, fields, or functions in a Frappe/ERPNext application.
You must extract the exact technical targets mentioned or implied in the prompt into a structured JSON object.

Output ONLY a valid JSON object matching this schema:
{
  "app": "app_name or empty string",
  "doctype": "DocType Name or empty string",
  "fields": ["list", "of", "fieldnames"],
  "functions": ["list", "of", "function_names"],
  "files": ["list", "of", "filepaths"],
  "confidence": float_between_0_and_1,
  "clarification_needed": "clarification text if ambiguous, else empty string"
}

Do NOT wrap the JSON in extra text outside the JSON block.

Here are examples of correct extractions:

Example 1:
User: "What breaks if I rename total_amount to grand_total in Sales Invoice in erpnext?"
JSON:
{
  "app": "erpnext",
  "doctype": "Sales Invoice",
  "fields": ["total_amount", "grand_total"],
  "functions": [],
  "files": [],
  "confidence": 0.95,
  "clarification_needed": ""
}

Example 2:
User: "We are updating validate_items function and rate field in Delivery Note in frappe"
JSON:
{
  "app": "frappe",
  "doctype": "Delivery Note",
  "fields": ["rate"],
  "functions": ["validate_items"],
  "files": [],
  "confidence": 0.9,
  "clarification_needed": ""
}

Example 3:
User: "What happens if I change customer status handling?"
JSON:
{
  "app": "",
  "doctype": "Customer",
  "fields": ["status"],
  "functions": [],
  "files": [],
  "confidence": 0.6,
  "clarification_needed": "Please specify if you are changing Customer DocType status field or Workflow transitions."
}
"""


def interpret(run) -> dict:
	"""
	AI Interpreter stage entry point.

	Parameters
	----------
	run : Impact Analysis Run document

	Returns
	-------
	dict : Extracted targets ({ app, doctype, fields, functions, files, confidence, clarification_needed })
	"""
	prompt = (run.prompt or "").strip()
	if not prompt:
		return _empty_extraction(run)

	settings = get_settings()
	model = settings.interpreter_model or "gemini-1.5-flash"

	# Call Gemini
	raw_response = call_gemini(
		prompt=prompt,
		system_prompt=INTERPRETER_SYSTEM_PROMPT,
		model=model,
		run_id=run.name,
		stage="Interpreting",
	)

	# Clean JSON response
	extraction_result = _parse_json_response(raw_response)

	# Overwrite app if user manually provided app in form
	if run.app:
		extraction_result["app"] = run.app
	if run.doctype_target and not extraction_result.get("doctype"):
		extraction_result["doctype"] = run.doctype_target

	# Save extraction_result to run document
	run.reload()
	run.extraction_result = json.dumps(extraction_result, indent=2)
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep

	return extraction_result


def _parse_json_response(text: str) -> dict:
	"""Extract JSON from raw AI response text."""
	cleaned = text.strip()

	# Remove markdown code blocks if present
	if "```json" in cleaned:
		cleaned = cleaned.split("```json")[1].split("```")[0].strip()
	elif "```" in cleaned:
		cleaned = cleaned.split("```")[1].split("```")[0].strip()

	try:
		return json.loads(cleaned)
	except Exception:
		# Fallback regex extraction for json object
		match = re.search(r"\{.*\}", cleaned, re.DOTALL)
		if match:
			try:
				return json.loads(match.group(0))
			except Exception:
				pass

	return {
		"app": "",
		"doctype": "",
		"fields": [],
		"functions": [],
		"files": [],
		"confidence": 0.0,
		"clarification_needed": "Failed to parse AI response into JSON format.",
	}


def _empty_extraction(run) -> dict:
	"""Return empty extraction dict when no prompt is provided."""
	return {
		"app": run.app or "",
		"doctype": run.doctype_target or "",
		"fields": [],
		"functions": [f.strip() for f in (run.functions or "").split(",") if f.strip()],
		"files": [f.strip() for f in (run.filenames or "").split(",") if f.strip()],
		"confidence": 1.0,
		"clarification_needed": "",
	}
>>>>>>> main
=======
# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import json
import re
import frappe
from frappe import _
from impact_analyser.ai.client import call_gemini, get_settings


INTERPRETER_SYSTEM_PROMPT = """You are an expert Frappe Framework codebase analyzer.
Your task is to analyze user queries regarding Frappe/ERPNext applications and classify the intent:
1. "list_fields": The user wants to discover, inspect, or list the available schema fields of a DocType (e.g. "i want to know available fields", "show me all fields for Customer", "what fields exist in Airplane Ticket?").
2. "impact_analysis": The user is proposing or asking about changing, renaming, refactoring, or deleting code, DocTypes, fields, or functions (e.g. "What breaks if I rename flight to flight_code?", "We are updating validate_items in Delivery Note").

Extract the exact technical targets into a structured JSON object matching this schema:
{
  "intent": "list_fields" or "impact_analysis",
  "app": "app_name or empty string",
  "doctype": "DocType Name or empty string",
  "fields": ["list", "of", "fieldnames"],
  "functions": ["list", "of", "function_names"],
  "files": ["list", "of", "filepaths"],
  "confidence": float_between_0_and_1,
  "clarification_needed": "clarification text if ambiguous, else empty string"
}

Output ONLY valid JSON. Do NOT wrap the JSON in extra text outside the JSON block.

Here are examples of correct extractions:

Example 1 (Informational field query):
User: "i want to know available fields"
DocType context: "Airplane Ticket"
JSON:
{
  "intent": "list_fields",
  "app": "airplane_mode",
  "doctype": "Airplane Ticket",
  "fields": [],
  "functions": [],
  "files": [],
  "confidence": 0.95,
  "clarification_needed": ""
}

Example 2 (Informational field query with DocType in prompt):
User: "What are the available fields in Sales Invoice?"
JSON:
{
  "intent": "list_fields",
  "app": "erpnext",
  "doctype": "Sales Invoice",
  "fields": [],
  "functions": [],
  "files": [],
  "confidence": 0.98,
  "clarification_needed": ""
}

Example 3 (Impact analysis - field rename):
User: "What breaks if I rename total_amount to grand_total in Sales Invoice in erpnext?"
JSON:
{
  "intent": "impact_analysis",
  "app": "erpnext",
  "doctype": "Sales Invoice",
  "fields": ["total_amount", "grand_total"],
  "functions": [],
  "files": [],
  "confidence": 0.95,
  "clarification_needed": ""
}

Example 4 (Impact analysis - function & field change):
User: "We are updating validate_items function and rate field in Delivery Note in frappe"
JSON:
{
  "intent": "impact_analysis",
  "app": "frappe",
  "doctype": "Delivery Note",
  "fields": ["rate"],
  "functions": ["validate_items"],
  "files": [],
  "confidence": 0.9,
  "clarification_needed": ""
}

Example 5 (Ambiguous prompt):
User: "What happens if I change customer status handling?"
JSON:
{
  "intent": "impact_analysis",
  "app": "",
  "doctype": "Customer",
  "fields": ["status"],
  "functions": [],
  "files": [],
  "confidence": 0.6,
  "clarification_needed": "Please specify if you are changing Customer DocType status field or Workflow transitions."
}
"""


def interpret(run) -> dict:
	"""
	AI Interpreter stage entry point.

	Parameters
	----------
	run : Impact Analysis Run document

	Returns
	-------
	dict : Extracted targets ({ intent, app, doctype, fields, functions, files, confidence, clarification_needed })
	"""
	prompt = (run.prompt or "").strip()
	doctype_target = (run.doctype_target or "").strip()

	if not prompt:
		return _empty_extraction(run)

	settings = get_settings()
	model = settings.interpreter_model or "gemini-1.5-flash"

	augmented_prompt = prompt
	if doctype_target:
		augmented_prompt += f"\n(Target DocType context: {doctype_target})"
	if run.app:
		augmented_prompt += f"\n(Target App context: {run.app})"

	# Call Gemini
	raw_response = call_gemini(
		prompt=augmented_prompt,
		system_prompt=INTERPRETER_SYSTEM_PROMPT,
		model=model,
		run_id=run.name,
		stage="Interpreting",
	)

	# Clean and parse JSON response
	extraction_result = _parse_json_response(raw_response)

	# Heuristic verification for intent if prompt is clearly a read-only field query
	lower_prompt = prompt.lower()
	if any(phrase in lower_prompt for phrase in ("available field", "available fields", "list fields", "show fields", "what fields")):
		extraction_result["intent"] = "list_fields"

	# Overwrite app and doctype if user explicitly specified them in form
	if run.app:
		extraction_result["app"] = run.app
	if doctype_target and not extraction_result.get("doctype"):
		extraction_result["doctype"] = doctype_target

	# Infer app from doctype if app is still empty
	resolved_dt = extraction_result.get("doctype") or doctype_target
	if not extraction_result.get("app") and resolved_dt and frappe.db.exists("DocType", resolved_dt):
		try:
			mod = frappe.db.get_value("DocType", resolved_dt, "module")
			if mod:
				extraction_result["app"] = frappe.local.module_app.get(frappe.scrub(mod)) or ""
		except Exception:
			pass

	# Default intent to impact_analysis if omitted
	if "intent" not in extraction_result:
		extraction_result["intent"] = "impact_analysis"

	# Save extraction_result to run document
	run.reload()
	run.extraction_result = json.dumps(extraction_result, indent=2)
	run.save(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep

	return extraction_result


def _parse_json_response(text: str) -> dict:
	"""Extract JSON from raw AI response text."""
	cleaned = text.strip()

	if "```json" in cleaned:
		cleaned = cleaned.split("```json")[1].split("```")[0].strip()
	elif "```" in cleaned:
		cleaned = cleaned.split("```")[1].split("```")[0].strip()

	try:
		return json.loads(cleaned)
	except Exception:
		match = re.search(r"\{.*\}", cleaned, re.DOTALL)
		if match:
			try:
				return json.loads(match.group(0))
			except Exception:
				pass

	return {
		"intent": "impact_analysis",
		"app": "",
		"doctype": "",
		"fields": [],
		"functions": [],
		"files": [],
		"confidence": 0.0,
		"clarification_needed": "Failed to parse AI response into JSON format.",
	}


def _empty_extraction(run) -> dict:
	"""Return empty extraction dict when no prompt is provided."""
	return {
		"intent": "impact_analysis",
		"app": run.app or "",
		"doctype": run.doctype_target or "",
		"fields": [],
		"functions": [f.strip() for f in (run.functions or "").split(",") if f.strip()],
		"files": [f.strip() for f in (run.filenames or "").split(",") if f.strip()],
		"confidence": 1.0,
		"clarification_needed": "",
	}
