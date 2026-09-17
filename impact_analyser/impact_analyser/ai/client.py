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
		try:
			key = settings.get_password("gemini_api_key", raise_exception=False) or ""
		except Exception:
			key = ""
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
		raise


def _log_api_call(run_id: str, stage: str, model: str, request_payload: str, response_payload: str) -> None:
	"""Write an audit entry to Impact Analyzer Log."""
	try:
		log = frappe.get_doc(
			{
				"doctype": "Impact Analyzer Log",
				"run_id": run_id or "Direct API Call",
				"stage": stage,
				"model": model,
				"request_payload": request_payload,
				"response_payload": response_payload,
			}
		)
		log.insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
	except Exception as exc:
		# Logging failure should never break the analysis pipeline
		frappe.log_error(f"Failed to log Gemini API call: {exc}", "Impact Analyzer Logger")


def _generate_mock_response(prompt: str, stage: str) -> str:
	"""Produce a plausible mock response for local dev and automated testing."""
	if stage == "Interpretation":
		return json.dumps({
			"app": "frappe",
			"doctype": "User",
			"fields": ["email", "first_name"],
			"functions": [],
			"files": [],
			"confidence": 0.95,
			"clarification_needed": None,
		})
	elif stage == "Drafting":
		return json.dumps([
			{
				"file": "frappe/core/doctype/user/user.py",
				"line": 10,
				"source": "File",
				"impact": "Medium",
				"reason": "Referenced in controller logic",
				"suggested_action": "Verify field access",
				"snippet": "self.email = email",
				"usage_type": "Python Field Write (Assignment)",
			}
		])
	elif stage == "Formatting":
		return (
			"<p><strong>Executive Summary (Mock):</strong> Analysis completed successfully. "
			"Review the verified changes below before applying modifications.</p>"
		)
	return ""
