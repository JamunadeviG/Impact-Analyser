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
	Get AI API key from Impact Analyzer Settings or environment variables.
	Supports Groq (gsk_...), Anthropic (sk-ant-...), or Google Gemini (AIza...).
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
		key = (
			os.environ.get("GEMINI_API_KEY", "").strip()
			or os.environ.get("ANTHROPIC_API_KEY", "").strip()
			or os.environ.get("GROQ_API_KEY", "").strip()
		)
	return key


def call_gemini(
	prompt: str,
	system_prompt: str,
	model: str = None,
	run_id: str = None,
	stage: str = "AI Stage",
) -> str:
	"""
	Send a prompt to the configured AI API (Groq, Anthropic Claude, or Google Gemini).
	Automatically routes based on API key format and configuration.
	"""
	settings = get_settings()
	api_key = get_api_key(settings)
	selected_model = model or settings.interpreter_model or "gemini-1.5-flash"
	enable_mock = bool(settings.enable_mock_fallback or getattr(frappe.flags, "in_test", False))

	if not api_key:
		if not enable_mock:
			frappe.throw(
				_(
					"AI API Key is not configured in Impact Analyzer Settings "
					"or environment variables, and Mock Fallback is disabled."
				),
				frappe.ValidationError,
			)
		mock_text = _generate_mock_response(prompt, stage)
		_log_api_call(
			run_id, stage,
			f"{selected_model} (Mock)",
			json.dumps({"system": system_prompt, "prompt": prompt}, indent=2),
			mock_text,
		)
		return mock_text

	try:
		# ── Provider 1: Groq (starts with gsk_) ───────────────────────────────
		if api_key.startswith("gsk_"):
			if model and not model.startswith(("gemini", "claude")):
				groq_model = model
			elif stage in ("Drafting", "Formatting") and getattr(settings, "report_model", None) and not settings.report_model.startswith(("gemini", "claude")):
				groq_model = settings.report_model
			elif getattr(settings, "interpreter_model", None) and not settings.interpreter_model.startswith(("gemini", "claude")):
				groq_model = settings.interpreter_model
			else:
				groq_model = "openai/gpt-oss-120b"
			url = "https://api.groq.com/openai/v1/chat/completions"
			headers = {
				"Content-Type": "application/json",
				"Authorization": f"Bearer {api_key}",
			}
			payload = {
				"model": groq_model,
				"messages": [
					{"role": "system", "content": system_prompt},
					{"role": "user", "content": prompt},
				],
				"temperature": 0.2,
			}
			res = requests.post(url, headers=headers, json=payload, timeout=60)
			res.raise_for_status()
			data = res.json()
			response_text = data["choices"][0]["message"]["content"]
			_log_api_call(
				run_id, stage, f"Groq ({groq_model})",
				json.dumps({"system": system_prompt, "prompt": prompt}, indent=2),
				response_text,
			)
			return response_text

		# ── Provider 2: Anthropic Claude (starts with sk-ant-) ─────────────────
		elif api_key.startswith("sk-ant-"):
			claude_model = model if model and "claude" in model else "claude-3-5-sonnet-20241022"
			url = "https://api.anthropic.com/v1/messages"
			headers = {
				"Content-Type": "application/json",
				"x-api-key": api_key,
				"anthropic-version": "2023-06-01",
			}
			payload = {
				"model": claude_model,
				"system": system_prompt,
				"messages": [{"role": "user", "content": prompt}],
				"max_tokens": 4096,
				"temperature": 0.2,
			}
			res = requests.post(url, headers=headers, json=payload, timeout=60)
			res.raise_for_status()
			data = res.json()
			response_text = "".join([c.get("text", "") for c in data.get("content", [])])
			_log_api_call(
				run_id, stage, f"Anthropic ({claude_model})",
				json.dumps({"system": system_prompt, "prompt": prompt}, indent=2),
				response_text,
			)
			return response_text

		# ── Provider 3: Google Gemini (default) ───────────────────────────────
		else:
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
			res = requests.post(url, headers=headers, json=payload, timeout=60)
			res.raise_for_status()
			data = res.json()
			response_text = ""
			candidates = data.get("candidates", [])
			if candidates:
				parts = candidates[0].get("content", {}).get("parts", [])
				for part in parts:
					response_text += part.get("text", "")

			_log_api_call(
				run_id, stage, f"Gemini ({selected_model})",
				json.dumps({"system": system_prompt, "prompt": prompt}, indent=2),
				response_text,
			)
			return response_text

	except Exception as exc:
		if enable_mock:
			frappe.log_error(
				f"AI API request failed: {exc}. Using mock fallback.",
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
<<<<<<< HEAD
		raise


def _log_api_call(run_id: str, stage: str, model: str, request_payload: str, response_payload: str) -> None:
	"""Write an audit entry to Impact Analyzer Log."""
=======
		raise frappe.ValidationError(_("AI API request failed: {0}").format(str(exc)))


# Backward-compatible alias
call_claude = call_gemini


def _log_api_call(run_id, stage, model, prompt_sent, response_received):
	"""Save audit log record in Impact Analyzer Log."""
>>>>>>> 3871c81 (latest ui process and ai update)
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
<<<<<<< HEAD
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
=======
				"intent": "impact_analysis",
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
>>>>>>> 3871c81 (latest ui process and ai update)
		return (
			"<p><strong>Executive Summary (Mock):</strong> Analysis completed successfully. "
			"Review the verified changes below before applying modifications.</p>"
		)
	return ""
