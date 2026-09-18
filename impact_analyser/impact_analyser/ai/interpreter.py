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
3. "invalid": The prompt is a greeting, noise, test, or anything unrelated to schema inspection or impact analysis (e.g. "hello", "hi", "test", "what's up", "how are you", "good morning", "lol", "ok", single nonsense words).

Extract the exact technical targets into a structured JSON object matching this schema:
{
  "intent": "list_fields" or "impact_analysis" or "invalid",
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

Example 6 (Invalid - greeting):
User: "hello"
JSON:
{
  "intent": "invalid",
  "app": "",
  "doctype": "",
  "fields": [],
  "functions": [],
  "files": [],
  "confidence": 0.99,
  "clarification_needed": ""
}

Example 7 (Invalid - noise/test):
User: "hi there"
JSON:
{
  "intent": "invalid",
  "app": "",
  "doctype": "",
  "fields": [],
  "functions": [],
  "files": [],
  "confidence": 0.99,
  "clarification_needed": ""
}

Example 8 (Invalid - nonsense with DocType context):
User: "what's up"
DocType context: "Airplane Ticket"
JSON:
{
  "intent": "invalid",
  "app": "",
  "doctype": "",
  "fields": [],
  "functions": [],
  "files": [],
  "confidence": 0.99,
  "clarification_needed": ""
}
"""

# Heuristic keyword sets for local intent overrides (do not call AI for these)
_INVALID_PROMPT_PATTERNS = (
	"hello", "hi", "hey", "sup", "what's up", "whats up", "how are you",
	"good morning", "good evening", "good afternoon", "good night",
	"lol", "lmao", "ok", "okay", "test", "testing", "ping", "yo",
	"thanks", "thank you", "bye", "goodbye", "help me",
)

_LIST_FIELDS_PHRASES = (
	"available field", "available fields", "list fields", "list field",
	"show fields", "show field", "what fields", "which fields", "all fields",
)


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

	lower_prompt = prompt.lower().strip()

	# ── Fast local heuristic: detect invalid prompts without an API call ──────
	if _is_obviously_invalid(lower_prompt):
		result = {
			"intent": "invalid",
			"app": "",
			"doctype": "",
			"fields": [],
			"functions": [],
			"files": [],
			"confidence": 0.99,
			"clarification_needed": "",
		}
		_save_extraction(run, result)
		return result

	settings = get_settings()
	model = settings.interpreter_model or "gemini-1.5-flash"

	augmented_prompt = prompt
	if doctype_target:
		augmented_prompt += f"\n(Target DocType context: {doctype_target})"
	if run.app:
		augmented_prompt += f"\n(Target App context: {run.app})"

	# Call AI
	raw_response = call_gemini(
		prompt=augmented_prompt,
		system_prompt=INTERPRETER_SYSTEM_PROMPT,
		model=model,
		run_id=run.name,
		stage="Interpreting",
	)

	# Clean and parse JSON response
	extraction_result = _parse_json_response(raw_response)

	# ── Local overrides ───────────────────────────────────────────────────────
	# Force list_fields if phrasing is unambiguous
	if any(phrase in lower_prompt for phrase in _LIST_FIELDS_PHRASES):
		extraction_result["intent"] = "list_fields"

	# Overwrite app and doctype from form if user explicitly specified them
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

	# Default intent to impact_analysis if omitted or unrecognised
	if extraction_result.get("intent") not in ("list_fields", "impact_analysis", "invalid"):
		extraction_result["intent"] = "impact_analysis"

	_save_extraction(run, extraction_result)
	return extraction_result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_obviously_invalid(lower_prompt: str) -> bool:
	"""Return True if the prompt is clearly a greeting or noise."""
	stripped = lower_prompt.strip("!?.,:;'\" ")
	# Exact match against known invalid phrases
	if stripped in _INVALID_PROMPT_PATTERNS:
		return True
	# Very short prompt with no technical keywords
	if len(stripped) <= 3:
		return True
	# Starts with any known invalid opener
	for pat in _INVALID_PROMPT_PATTERNS:
		if lower_prompt.startswith(pat):
			return True
	return False


def _save_extraction(run, extraction_result: dict) -> None:
	"""Persist extraction_result JSON to the run document."""
	try:
		run.reload()
		run.extraction_result = json.dumps(extraction_result, indent=2)
		run.save(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
	except Exception:
		pass


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
