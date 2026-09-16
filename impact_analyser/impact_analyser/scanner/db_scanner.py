# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import json
import re
import frappe
from frappe import _


def find_db_usages(target: dict) -> list:
	"""
	Query 7 Frappe database customization DocTypes for references to the target DocType, fields, or functions.

	Parameters
	----------
	target : dict
		{
			"doctype": str,
			"fields": list[str],
			"functions": list[str]
		}

	Returns
	-------
	list[dict]
		List of DbHit dicts tagged source="Database".
	"""
	doctype_target = (target.get("doctype") or "").strip()
	fields_target = [f.strip() for f in target.get("fields", []) if f and f.strip()]
	functions_target = [f.strip() for f in target.get("functions", []) if f and f.strip()]

	all_tokens = set()
	if doctype_target:
		all_tokens.add(doctype_target)
	for f in fields_target:
		all_tokens.add(f)
	for fn in functions_target:
		all_tokens.add(fn)

	if not all_tokens:
		return []

	hits = []

	# 1. Client Script
	_scan_client_scripts(doctype_target, all_tokens, hits)

	# 2. Server Script
	_scan_server_scripts(doctype_target, all_tokens, hits)

	# 3. Workflows (Workflow, Workflow Transition)
	_scan_workflows(doctype_target, all_tokens, hits)

	# 4. Custom Field
	_scan_custom_fields(doctype_target, fields_target, all_tokens, hits)

	# 5. Property Setter
	_scan_property_setters(doctype_target, fields_target, all_tokens, hits)

	# 6. Notification
	_scan_notifications(doctype_target, all_tokens, hits)

	# 7. Dashboard Chart / Number Card
	_scan_dashboard_items(doctype_target, all_tokens, hits)

	return hits


def _scan_client_scripts(dt_target: str, tokens: set, hits: list) -> None:
	"""1. Scan Client Script documents."""
	if not frappe.db.exists("DocType", "Client Script"):
		return
	try:
		scripts = frappe.get_all("Client Script", fields=["name", "dt", "script", "enabled"])
		for s in scripts:
			if not s.enabled:
				continue
			script_text = s.script or ""
			# Match DocType
			if dt_target and s.dt == dt_target:
				hits.append({
					"file": f"Client Script: {s.name}",
					"line": 1,
					"snippet": f"Client Script for DocType '{s.dt}'",
					"usage_type": "Client Script DocType Binding",
					"source": "Database",
					"doctype": "Client Script",
					"name": s.name,
				})
			# Match script text tokens
			for line_no, line in enumerate(script_text.splitlines(), start=1):
				for token in tokens:
					if token in line:
						hits.append({
							"file": f"Client Script: {s.name}",
							"line": line_no,
							"snippet": line.strip(),
							"usage_type": "Client Script Content",
							"source": "Database",
							"doctype": "Client Script",
							"name": s.name,
						})
						break
	except Exception as exc:
		frappe.log_error(f"Error scanning Client Script: {exc}", "DB Scanner")


def _scan_server_scripts(dt_target: str, tokens: set, hits: list) -> None:
	"""2. Scan Server Script documents."""
	if not frappe.db.exists("DocType", "Server Script"):
		return
	try:
		scripts = frappe.get_all(
			"Server Script",
			fields=["name", "reference_doctype", "script", "script_type", "disabled"],
		)
		for s in scripts:
			if s.disabled:
				continue
			script_text = s.script or ""
			if dt_target and s.reference_doctype == dt_target:
				hits.append({
					"file": f"Server Script: {s.name}",
					"line": 1,
					"snippet": f"Server Script ({s.script_type}) attached to '{s.reference_doctype}'",
					"usage_type": "Server Script Reference Doctype",
					"source": "Database",
					"doctype": "Server Script",
					"name": s.name,
				})
			for line_no, line in enumerate(script_text.splitlines(), start=1):
				for token in tokens:
					if token in line:
						hits.append({
							"file": f"Server Script: {s.name}",
							"line": line_no,
							"snippet": line.strip(),
							"usage_type": "Server Script Content",
							"source": "Database",
							"doctype": "Server Script",
							"name": s.name,
						})
						break
	except Exception as exc:
		frappe.log_error(f"Error scanning Server Script: {exc}", "DB Scanner")


def _scan_workflows(dt_target: str, tokens: set, hits: list) -> None:
	"""3. Scan Workflow & Workflow Transition documents."""
	if not frappe.db.exists("DocType", "Workflow"):
		return
	try:
		workflows = frappe.get_all("Workflow", fields=["name", "document_type", "is_active"])
		for wf in workflows:
			if not wf.is_active:
				continue
			if dt_target and wf.document_type == dt_target:
				hits.append({
					"file": f"Workflow: {wf.name}",
					"line": 1,
					"snippet": f"Active Workflow bound to DocType '{wf.document_type}'",
					"usage_type": "Workflow Binding",
					"source": "Database",
					"doctype": "Workflow",
					"name": wf.name,
				})

			# Transitions condition check
			if frappe.db.exists("DocType", "Workflow Transition"):
				transitions = frappe.get_all(
					"Workflow Transition",
					filters={"parent": wf.name},
					fields=["name", "state", "action", "next_state", "condition"],
				)
				for t in transitions:
					cond = t.condition or ""
					for token in tokens:
						if token in cond:
							hits.append({
								"file": f"Workflow: {wf.name} (Transition {t.action})",
								"line": 1,
								"snippet": f"Transition condition: {cond}",
								"usage_type": "Workflow Transition Condition",
								"source": "Database",
								"doctype": "Workflow Transition",
								"name": t.name,
							})
							break
	except Exception as exc:
		frappe.log_error(f"Error scanning Workflows: {exc}", "DB Scanner")


def _scan_custom_fields(dt_target: str, fields_target: list, tokens: set, hits: list) -> None:
	"""4. Scan Custom Field documents."""
	if not frappe.db.exists("DocType", "Custom Field"):
		return
	try:
		cfields = frappe.get_all(
			"Custom Field",
			fields=["name", "dt", "fieldname", "label", "options", "depends_on", "mandatory_depends_on", "read_only_depends_on"],
		)
		for cf in cfields:
			if dt_target and cf.dt == dt_target:
				hits.append({
					"file": f"Custom Field: {cf.name}",
					"line": 1,
					"snippet": f"Custom field '{cf.fieldname}' ({cf.label}) on DocType '{cf.dt}'",
					"usage_type": "Custom Field Definition",
					"source": "Database",
					"doctype": "Custom Field",
					"name": cf.name,
				})
			if cf.fieldname in fields_target:
				hits.append({
					"file": f"Custom Field: {cf.name}",
					"line": 1,
					"snippet": f"Target custom field name match: '{cf.fieldname}' on {cf.dt}",
					"usage_type": "Custom Field Name",
					"source": "Database",
					"doctype": "Custom Field",
					"name": cf.name,
				})
			if dt_target and cf.options == dt_target:
				hits.append({
					"file": f"Custom Field: {cf.name}",
					"line": 1,
					"snippet": f"Link Custom Field '{cf.fieldname}' on '{cf.dt}' points to '{dt_target}'",
					"usage_type": "Custom Field Link Target",
					"source": "Database",
					"doctype": "Custom Field",
					"name": cf.name,
				})
			# depends_on
			dep = cf.depends_on or ""
			for token in tokens:
				if token in dep:
					hits.append({
						"file": f"Custom Field: {cf.name}",
						"line": 1,
						"snippet": f"Custom Field '{cf.fieldname}' depends_on: {dep}",
						"usage_type": "Custom Field Expression",
						"source": "Database",
						"doctype": "Custom Field",
						"name": cf.name,
					})
					break
	except Exception as exc:
		frappe.log_error(f"Error scanning Custom Fields: {exc}", "DB Scanner")


def _scan_property_setters(dt_target: str, fields_target: list, tokens: set, hits: list) -> None:
	"""5. Scan Property Setter documents."""
	if not frappe.db.exists("DocType", "Property Setter"):
		return
	try:
		setters = frappe.get_all(
			"Property Setter",
			fields=["name", "doc_type", "field_name", "property", "value"],
		)
		for ps in setters:
			if dt_target and ps.doc_type == dt_target:
				hits.append({
					"file": f"Property Setter: {ps.name}",
					"line": 1,
					"snippet": f"Property Setter for '{ps.doc_type}' - field: {ps.field_name}, property: {ps.property}",
					"usage_type": "Property Setter DocType",
					"source": "Database",
					"doctype": "Property Setter",
					"name": ps.name,
				})
			elif ps.field_name in fields_target:
				hits.append({
					"file": f"Property Setter: {ps.name}",
					"line": 1,
					"snippet": f"Property Setter modifies field '{ps.field_name}' on '{ps.doc_type}'",
					"usage_type": "Property Setter Field",
					"source": "Database",
					"doctype": "Property Setter",
					"name": ps.name,
				})
	except Exception as exc:
		frappe.log_error(f"Error scanning Property Setters: {exc}", "DB Scanner")


def _scan_notifications(dt_target: str, tokens: set, hits: list) -> None:
	"""6. Scan Notification documents."""
	if not frappe.db.exists("DocType", "Notification"):
		return
	try:
		notifications = frappe.get_all(
			"Notification",
			fields=["name", "document_type", "condition", "enabled"],
		)
		for n in notifications:
			if not n.enabled:
				continue
			if dt_target and n.document_type == dt_target:
				hits.append({
					"file": f"Notification: {n.name}",
					"line": 1,
					"snippet": f"Enabled Notification attached to DocType '{n.document_type}'",
					"usage_type": "Notification Binding",
					"source": "Database",
					"doctype": "Notification",
					"name": n.name,
				})
			cond = n.condition or ""
			for token in tokens:
				if token in cond:
					hits.append({
						"file": f"Notification: {n.name}",
						"line": 1,
						"snippet": f"Notification condition: {cond}",
						"usage_type": "Notification Condition",
						"source": "Database",
						"doctype": "Notification",
						"name": n.name,
					})
					break
	except Exception as exc:
		frappe.log_error(f"Error scanning Notifications: {exc}", "DB Scanner")


def _scan_dashboard_items(dt_target: str, tokens: set, hits: list) -> None:
	"""7. Scan Dashboard Chart & Number Card documents."""
	for dt_name in ("Dashboard Chart", "Number Card"):
		if not frappe.db.exists("DocType", dt_name):
			continue
		try:
			items = frappe.get_all(dt_name, fields=["name", "document_type", "filters_json"])
			for item in items:
				if dt_target and item.document_type == dt_target:
					hits.append({
						"file": f"{dt_name}: {item.name}",
						"line": 1,
						"snippet": f"{dt_name} based on '{item.document_type}'",
						"usage_type": f"{dt_name} DocType Binding",
						"source": "Database",
						"doctype": dt_name,
						"name": item.name,
					})
				filters = item.filters_json or ""
				for token in tokens:
					if token in filters:
						hits.append({
							"file": f"{dt_name}: {item.name}",
							"line": 1,
							"snippet": f"{dt_name} filters mention '{token}'",
							"usage_type": f"{dt_name} Filter Reference",
							"source": "Database",
							"doctype": dt_name,
							"name": item.name,
						})
						break
		except Exception as exc:
			frappe.log_error(f"Error scanning {dt_name}: {exc}", "DB Scanner")
