# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import json
import os
import requests
import frappe
from frappe import _


def get_settings():
	"""Fetch Impact Analyzer Settings single document."""
	return frappe.get_single("Impact Analyzer Settings")


def get_api_key(settings=None):
	"""
	Get Gemini API key from Impact Analyzer Settings or GEMINI_API_KEY environment variable.
	"""
	if not settings:
		settings = get_settings()
	key = ""
	if hasattr(settings, "get_password"):
		key = settings.get_password("gemini_api_key") or ""
	if not key and hasattr(settings, "gemini_api_key"):
		key = settings.gemini_api_key or ""
	if not key:
		key = os.environ.get("GEMINI_API_KEY", "").strip()
	return key


def call_gemini(
	prompt: str,
	system_prompt: str,
	model: str = None,
	run_id: str = None,
	stage: str = "AI Stage",
) -> str:
	"""
	Send a prompt to the Google Gemini generateContent API.

	Falls back to mock mode if API key is absent and enable_mock_fallback is 1 or in test mode.
	Logs request and response to Impact Analyzer Log.
	"""
	settings = get_settings()
	api_key = get_api_key(settings)
	selected_model = model or settings.interpreter_model or "gemini-1.5-flash"
	enable_mock = bool(settings.enable_mock_fallback or getattr(frappe.flags, "in_test", False))

	if not api_key:
		if not enable_mock:
			frappe.throw(
				_(
					"Gemini API Key is not configured in Impact Analyzer Settings "
					"or GEMINI_API_KEY environment variable, and Mock Fallback is disabled."
				),
				frappe.ValidationError,
			)
		# Return mock response
		mock_text = _generate_mock_response(prompt, stage)
		_log_api_call(
			run_id, stage,
			f"{selected_model} (Mock)",
			json.dumps({"system": system_prompt, "prompt": prompt}, indent=2),
			mock_text,
		)
		return mock_text

	# Gemini REST endpoint
	url = (
		f"https://generativelanguage.googleapis.com/v1beta/models/"
		f"{selected_model}:generateContent?key={api_key}"
	)
	headers = {"Content-Type": "application/json"}
	payload = {
		"system_instruction": {
			"parts": {"text": system_prompt}
		},
		"contents": [
			{
				"role": "user",
				"parts": [{"text": prompt}],
			}
		],
		"generationConfig": {
			"temperature": 0.2,
			"maxOutputTokens": 4096,
		},
	}

	try:
		res = requests.post(url, headers=headers, json=payload, timeout=120)
		res.raise_for_status()
		data = res.json()

		# Extract text from Gemini response structure
		response_text = ""
		candidates = data.get("candidates", [])
		if candidates:
			parts = candidates[0].get("content", {}).get("parts", [])
			for part in parts:
				response_text += part.get("text", "")

		_log_api_call(
			run_id, stage, selected_model,
			json.dumps({"system": system_prompt, "prompt": prompt}, indent=2),
			response_text,
		)
		return response_text

	except Exception as exc:
		if enable_mock:
			frappe.log_error(
				f"Gemini API request failed: {exc}. Using mock fallback.",
				"Impact Analyzer Client",
			)
			mock_text = _generate_mock_response(prompt, stage)
			_log_api_call(
				run_id, stage,
				f"{selected_model} (Mock Fallback)",
				json.dumps({"system": system_prompt, "prompt": prompt}, indent=2),
				mock_text,
			)
			return mock_text
		raise frappe.ValidationError(_("Gemini API request failed: {0}").format(str(exc)))


# Keep backward-compatible alias so orchestrator ImportError fallbacks still work
call_claude = call_gemini


def _log_api_call(run_id, stage, model, prompt_sent, response_received):
	"""Save audit log record in Impact Analyzer Log."""
	try:
		log = frappe.get_doc({
			"doctype": "Impact Analyzer Log",
			"run": run_id,
			"stage": stage,
			"model": model,
			"timestamp": frappe.utils.now_datetime(),
			"prompt_sent": prompt_sent,
			"response_received": response_received,
		})
		log.insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
	except Exception:
		pass


def _generate_mock_response(prompt: str, stage: str) -> str:
	"""Generate appropriate mock response JSON/text based on the pipeline stage."""
	if "Interpreting" in stage or "Interpreter" in stage:
		return json.dumps(
			{
				"app": "frappe",
				"doctype": "User",
				"fields": ["first_name", "last_name", "email"],
				"functions": ["validate_email"],
				"files": ["frappe/core/doctype/user/user.py"],
				"confidence": 0.9,
				"clarification_needed": "",
			},
			indent=2,
		)
	elif "Drafting" in stage or "Drafter" in stage:
		return json.dumps(
			[
				{
					"file": "frappe/core/doctype/user/user.py",
					"line": 42,
					"source": "File",
					"impact": "High",
					"reason": "Function validate_email is called during document validation.",
					"suggested_action": "Ensure parameter compatibility after renaming.",
					"snippet": "def validate_email(self):",
					"usage_type": "Python Function Def",
				}
			],
			indent=2,
		)
	elif "Formatting" in stage or "Formatter" in stage:
		return (
			"<p><strong>Impact Analysis Report (Mock):</strong> "
			"Changing the target field/function will affect validation hooks and UI logic. "
			"Recommend thorough testing before deploying this change.</p>"
		)
	return "Mock response for prompt."
