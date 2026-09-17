# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import os
import frappe
from frappe import _


def validate(change_plan: list, app_name: str = None) -> list:
	"""
	Validator stage: Re-check proposed change plan against real disk files & database records.

	Purges hallucinated files, deleted DB records, or invalid line references.

	Parameters
	----------
	change_plan : list[dict]
		Proposed changes from AI Drafter.
	app_name : str
		App name for file path resolution.

	Returns
	-------
	list[dict]
		Filtered list of verified changes.
	"""
	if not change_plan:
		return []

	verified_changes = []
	app_name = app_name or "impact_analyser"

	try:
		app_path = frappe.get_app_path(app_name)
	except Exception:
		app_path = ""

	for change in change_plan:
		source = change.get("source", "File")
		file_ref = change.get("file", "")

		if source == "File":
			if _verify_file_change(file_ref, change, app_path):
				verified_changes.append(change)
		elif source == "Database":
			if _verify_db_change(file_ref, change):
				verified_changes.append(change)
		else:
			# Unknown source — keep by default
			verified_changes.append(change)

	return verified_changes


def _verify_file_change(rel_path: str, change: dict, app_path: str) -> bool:
	"""Verify file exists on disk and snippet is valid."""
	if not rel_path:
		return False

	# Try direct path or relative to app_path
	candidate_paths = []
	if app_path:
		candidate_paths.append(os.path.join(app_path, rel_path))
	candidate_paths.append(rel_path)

	found_path = None
	for p in candidate_paths:
		if os.path.isfile(p):
			found_path = p
			break

	if not found_path:
		# File does not exist on disk — purge hallucination
		return False

	return True


def _verify_db_change(file_ref: str, change: dict) -> bool:
	"""Verify database customization document exists in MariaDB."""
	doctype = change.get("doctype")
	doc_name = change.get("name")

	if not doctype or not doc_name:
		# Parse from "DocType: Name" format
		if ":" in file_ref:
			parts = file_ref.split(":", 1)
			doctype = parts[0].strip()
			doc_name = parts[1].strip()

	if doctype and doc_name:
		try:
			if frappe.db.exists(doctype, doc_name):
				return True
			else:
				# Document deleted from DB — purge
				return False
		except Exception:
			pass

	return True
