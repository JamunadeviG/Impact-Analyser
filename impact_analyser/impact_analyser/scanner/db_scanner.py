# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import json
import re
import frappe
from frappe import _


def find_db_usages(target: dict) -> list:
	"""
<<<<<<< HEAD
	Query Frappe database customizations and schema tables for references to
	the target DocType, fields, or functions.

	Scans:
	1. Linked DocTypes (DocField and Custom Field Link/Table targets)
	2. Property Setters
	3. Custom Fields
	4. Client Scripts
	5. Server Scripts
	6. Workflows & Workflow Transitions
	7. Reports
	8. Print Formats
	9. Notifications
	10. Dashboard Items (Dashboard Chart, Number Card)
=======
	Query 7 Frappe database customization DocTypes for references to the target DocType, fields, or functions.
	Properly scoped: when specific fields/functions are targeted, filters customizations to those elements
	rather than pulling all records attached to the parent DocType.
>>>>>>> 3871c81 (latest ui process and ai update)

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
		List of DbHit dicts tagged source="Database" with severity:
		[
			{
				"doctype": "DocField",
				"name": "Airplane Ticket-flight",
				"reference_type": "Linked DocType via Link Field",
				"usage_type": "Linked DocType",
				"file": "DocType: Airplane Ticket",
				"line": 1,
				"snippet": "DocType 'Airplane Ticket' links to 'Airplane Flight' via 'flight'",
				"severity": "High",
				"source": "Database"
			}
		]
	"""
	doctype_target = (target.get("doctype") or "").strip()
	fields_target = [f.strip() for f in target.get("fields", []) if f and f.strip()]
	functions_target = [f.strip() for f in target.get("functions", []) if f and f.strip()]

<<<<<<< HEAD
	all_tokens = set()
	if doctype_target:
		all_tokens.add(doctype_target)
		scrubbed = frappe.scrub(doctype_target)
		if scrubbed:
			all_tokens.add(scrubbed)
	for f in fields_target:
		all_tokens.add(f)
	for fn in functions_target:
		all_tokens.add(fn)

	if not all_tokens and not doctype_target:
=======
	has_narrow_targets = bool(fields_target or functions_target)

	primary_tokens = set(fields_target + functions_target)
	if not has_narrow_targets and doctype_target:
		primary_tokens.add(doctype_target)

	if not primary_tokens and not doctype_target:
>>>>>>> 3871c81 (latest ui process and ai update)
		return []

	hits = []

<<<<<<< HEAD
	# 1. Linked DocTypes via Link / Table fields
	_scan_linked_doctypes(doctype_target, hits)

	# 2. Property Setters
	_scan_property_setters(doctype_target, fields_target, all_tokens, hits)

	# 3. Custom Fields
	_scan_custom_fields(doctype_target, fields_target, all_tokens, hits)

	# 4. Client Scripts
	_scan_client_scripts(doctype_target, all_tokens, hits)

	# 5. Server Scripts
	_scan_server_scripts(doctype_target, all_tokens, hits)

	# 6. Workflows & Transitions
	_scan_workflows(doctype_target, all_tokens, hits)

	# 7. Reports
	_scan_reports(doctype_target, all_tokens, hits)

	# 8. Print Formats
	_scan_print_formats(doctype_target, all_tokens, hits)

	# 9. Notifications
	_scan_notifications(doctype_target, all_tokens, hits)

	# 10. Dashboard Items (Charts & Number Cards)
	_scan_dashboard_items(doctype_target, all_tokens, hits)
=======
	# 1. Client Script
	_scan_client_scripts(doctype_target, fields_target, primary_tokens, has_narrow_targets, hits)

	# 2. Server Script
	_scan_server_scripts(doctype_target, fields_target, primary_tokens, has_narrow_targets, hits)

	# 3. Workflows (Workflow, Workflow Transition)
	_scan_workflows(doctype_target, primary_tokens, has_narrow_targets, hits)

	# 4. Custom Field
	_scan_custom_fields(doctype_target, fields_target, primary_tokens, has_narrow_targets, hits)

	# 5. Property Setter
	_scan_property_setters(doctype_target, fields_target, has_narrow_targets, hits)

	# 6. Notification
	_scan_notifications(doctype_target, primary_tokens, has_narrow_targets, hits)

	# 7. Dashboard Chart / Number Card
	_scan_dashboard_items(doctype_target, fields_target, primary_tokens, has_narrow_targets, hits)
>>>>>>> 3871c81 (latest ui process and ai update)

	# Sort: High -> Medium -> Low
	order = {"High": 0, "Medium": 1, "Low": 2}
	hits.sort(key=lambda h: (order.get(h.get("severity", "Low"), 3), h.get("doctype", ""), h.get("name", "")))
	return hits


<<<<<<< HEAD
def _scan_linked_doctypes(dt_target: str, hits: list) -> None:
	"""Scan DocField and Custom Field for Link/Table fields pointing to target DocType."""
	if not dt_target or not frappe.db.exists("DocType", "DocField"):
		return
	try:
		# Standard DocField links
		links = frappe.db.sql(
			"""
			SELECT parent, fieldname, label, fieldtype, options
			FROM `tabDocField`
			WHERE fieldtype IN ('Link', 'Table', 'Table MultiSelect')
			  AND options = %(dt)s
			  AND parent != %(dt)s
			""",
			{"dt": dt_target},
			as_dict=True,
		)
		for lk in links:
			hits.append({
				"doctype": "DocType",
				"name": lk.parent,
				"reference_type": f"Linked DocType ({lk.parent} -> {dt_target} via '{lk.fieldname}')",
				"usage_type": "Linked DocType",
				"file": f"DocType: {lk.parent}",
				"line": 1,
				"snippet": f"DocType '{lk.parent}' has {lk.fieldtype} field '{lk.fieldname}' pointing to '{dt_target}'",
				"severity": "High",
				"impact": "High",
				"source": "Database",
			})
	except Exception as exc:
		frappe.log_error(f"Error scanning DocField links: {exc}", "DB Scanner")

	# Custom Field links pointing to dt_target
	if frappe.db.exists("DocType", "Custom Field"):
		try:
			clinks = frappe.db.sql(
				"""
				SELECT name, dt, fieldname, label, fieldtype, options
				FROM `tabCustom Field`
				WHERE fieldtype IN ('Link', 'Table', 'Table MultiSelect')
				  AND options = %(dt)s
				  AND dt != %(dt)s
				""",
				{"dt": dt_target},
				as_dict=True,
			)
			for clk in clinks:
				hits.append({
					"doctype": "Custom Field",
					"name": clk.name,
					"reference_type": f"Linked DocType via Custom Field '{clk.fieldname}' on '{clk.dt}'",
					"usage_type": "Custom Field Link",
					"file": f"Custom Field: {clk.name}",
					"line": 1,
					"snippet": f"Custom Field '{clk.fieldname}' ({clk.fieldtype}) on '{clk.dt}' points to '{dt_target}'",
					"severity": "High",
					"impact": "High",
					"source": "Database",
				})
		except Exception as exc:
			frappe.log_error(f"Error scanning Custom Field links: {exc}", "DB Scanner")


def _scan_property_setters(dt_target: str, fields_target: list, tokens: set, hits: list) -> None:
	"""Scan Property Setter documents for modifications to target DocType or fields."""
	if not frappe.db.exists("DocType", "Property Setter"):
		return
	try:
		setters = frappe.get_all(
			"Property Setter",
			fields=["name", "doc_type", "field_name", "property", "value"],
		)
		for ps in setters:
			is_match = False
			snippet = ""
			sev = "Medium"

			if dt_target and ps.doc_type == dt_target:
				is_match = True
				snippet = f"Property Setter modifies '{ps.property}' on DocType '{ps.doc_type}'"
				if ps.field_name:
					snippet += f", field '{ps.field_name}'"
			elif fields_target and ps.field_name in fields_target:
				is_match = True
				snippet = f"Property Setter modifies target field '{ps.field_name}' on '{ps.doc_type}' ({ps.property})"

			if is_match:
				if ps.property in ("reqd", "read_only", "hidden", "options", "fieldtype"):
					sev = "High"
				hits.append({
					"doctype": "Property Setter",
					"name": ps.name,
					"reference_type": f"Property Setter on {ps.doc_type}.{ps.field_name or '*'}",
					"usage_type": "Property Setter",
					"file": f"Property Setter: {ps.name}",
					"line": 1,
					"snippet": snippet,
					"severity": sev,
					"impact": sev,
					"source": "Database",
				})
	except Exception as exc:
		frappe.log_error(f"Error scanning Property Setters: {exc}", "DB Scanner")


def _scan_custom_fields(dt_target: str, fields_target: list, tokens: set, hits: list) -> None:
	"""Scan Custom Field documents."""
	if not frappe.db.exists("DocType", "Custom Field"):
		return
	try:
		cfields = frappe.get_all(
			"Custom Field",
			fields=["name", "dt", "fieldname", "label", "fieldtype", "options", "depends_on"],
		)
		for cf in cfields:
			if dt_target and cf.dt == dt_target:
				hits.append({
					"doctype": "Custom Field",
					"name": cf.name,
					"reference_type": f"Custom Field on target DocType '{cf.dt}'",
					"usage_type": "Custom Field Definition",
					"file": f"Custom Field: {cf.name}",
					"line": 1,
					"snippet": f"Custom field '{cf.fieldname}' ({cf.label or cf.fieldtype}) on DocType '{cf.dt}'",
					"severity": "High",
					"impact": "High",
					"source": "Database",
				})
			elif fields_target and cf.fieldname in fields_target:
				hits.append({
					"doctype": "Custom Field",
					"name": cf.name,
					"reference_type": f"Target Custom Field name '{cf.fieldname}'",
					"usage_type": "Custom Field Definition",
					"file": f"Custom Field: {cf.name}",
					"line": 1,
					"snippet": f"Custom field name match '{cf.fieldname}' on '{cf.dt}'",
					"severity": "High",
					"impact": "High",
					"source": "Database",
				})
			# depends_on expressions
			dep = cf.depends_on or ""
			for token in tokens:
				if token in dep:
					hits.append({
						"doctype": "Custom Field",
						"name": cf.name,
						"reference_type": f"Custom Field depends_on on '{cf.dt}'",
						"usage_type": "Custom Field Condition",
						"file": f"Custom Field: {cf.name}",
						"line": 1,
						"snippet": f"Custom field '{cf.fieldname}' depends_on expression: {dep}",
						"severity": "Medium",
						"impact": "Medium",
						"source": "Database",
					})
					break
	except Exception as exc:
		frappe.log_error(f"Error scanning Custom Fields: {exc}", "DB Scanner")


def _scan_client_scripts(dt_target: str, tokens: set, hits: list) -> None:
	"""Scan Client Script documents."""
=======
def _scan_client_scripts(dt_target: str, fields_target: list, tokens: set, has_narrow_targets: bool, hits: list) -> None:
	"""1. Scan Client Script documents."""
>>>>>>> 3871c81 (latest ui process and ai update)
	if not frappe.db.exists("DocType", "Client Script"):
		return
	try:
		scripts = frappe.get_all("Client Script", fields=["name", "dt", "script", "enabled"])
		for s in scripts:
			if not s.enabled:
				continue
			script_text = s.script or ""
<<<<<<< HEAD
			if dt_target and s.dt == dt_target:
				hits.append({
					"doctype": "Client Script",
					"name": s.name,
					"reference_type": f"Client Script for DocType '{s.dt}'",
					"usage_type": "Client Script DocType Binding",
					"file": f"Client Script: {s.name}",
					"line": 1,
					"snippet": f"Active Client Script bound to DocType '{s.dt}'",
					"severity": "High",
					"impact": "High",
					"source": "Database",
				})
				continue

			for line_no, line in enumerate(script_text.splitlines(), start=1):
				for token in tokens:
					if token in line:
						hits.append({
							"doctype": "Client Script",
							"name": s.name,
							"reference_type": f"Client Script Content Mention on '{s.dt}'",
							"usage_type": "Client Script Content",
							"file": f"Client Script: {s.name}",
							"line": line_no,
							"snippet": line.strip(),
							"severity": "Medium",
							"impact": "Medium",
							"source": "Database",
						})
						break
=======

			# If narrow targets (fields/functions), must match script text token AND dt (if specified)
			if has_narrow_targets:
				if dt_target and s.dt != dt_target:
					continue
				for line_no, line in enumerate(script_text.splitlines(), start=1):
					for token in tokens:
						if re.search(r"\b" + re.escape(token) + r"\b", line):
							hits.append({
								"file": f"Client Script: {s.name}",
								"line": line_no,
								"snippet": line.strip(),
								"usage_type": f"Client Script mentions '{token}'",
								"source": "Database",
								"doctype": "Client Script",
								"name": s.name,
							})
							break
			else:
				# Broad DocType scan
				if dt_target and s.dt == dt_target:
					hits.append({
						"file": f"Client Script: {s.name}",
						"line": 1,
						"snippet": f"Client Script attached to DocType '{s.dt}'",
						"usage_type": "Client Script DocType Binding",
						"source": "Database",
						"doctype": "Client Script",
						"name": s.name,
					})
>>>>>>> 3871c81 (latest ui process and ai update)
	except Exception as exc:
		frappe.log_error(f"Error scanning Client Script: {exc}", "Impact Analyzer DB Scanner")


<<<<<<< HEAD
def _scan_server_scripts(dt_target: str, tokens: set, hits: list) -> None:
	"""Scan Server Script documents."""
=======
def _scan_server_scripts(dt_target: str, fields_target: list, tokens: set, has_narrow_targets: bool, hits: list) -> None:
	"""2. Scan Server Script documents."""
>>>>>>> 3871c81 (latest ui process and ai update)
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
<<<<<<< HEAD
			if dt_target and s.reference_doctype == dt_target:
				hits.append({
					"doctype": "Server Script",
					"name": s.name,
					"reference_type": f"Server Script ({s.script_type}) attached to '{s.reference_doctype}'",
					"usage_type": "Server Script DocType Binding",
					"file": f"Server Script: {s.name}",
					"line": 1,
					"snippet": f"Server Script ({s.script_type}) attached to DocType '{s.reference_doctype}'",
					"severity": "High",
					"impact": "High",
					"source": "Database",
				})
				continue

			for line_no, line in enumerate(script_text.splitlines(), start=1):
				for token in tokens:
					if token in line:
						hits.append({
							"doctype": "Server Script",
							"name": s.name,
							"reference_type": f"Server Script Content Mention on '{s.reference_doctype or s.script_type}'",
							"usage_type": "Server Script Content",
							"file": f"Server Script: {s.name}",
							"line": line_no,
							"snippet": line.strip(),
							"severity": "High",
							"impact": "High",
							"source": "Database",
						})
						break
=======

			if has_narrow_targets:
				if dt_target and s.reference_doctype != dt_target:
					continue
				for line_no, line in enumerate(script_text.splitlines(), start=1):
					for token in tokens:
						if re.search(r"\b" + re.escape(token) + r"\b", line):
							hits.append({
								"file": f"Server Script: {s.name}",
								"line": line_no,
								"snippet": line.strip(),
								"usage_type": f"Server Script mentions '{token}'",
								"source": "Database",
								"doctype": "Server Script",
								"name": s.name,
							})
							break
			else:
				if dt_target and s.reference_doctype == dt_target:
					hits.append({
						"file": f"Server Script: {s.name}",
						"line": 1,
						"snippet": f"Server Script ({s.script_type}) attached to '{s.reference_doctype}'",
						"usage_type": "Server Script DocType Binding",
						"source": "Database",
						"doctype": "Server Script",
						"name": s.name,
					})
>>>>>>> 3871c81 (latest ui process and ai update)
	except Exception as exc:
		frappe.log_error(f"Error scanning Server Script: {exc}", "Impact Analyzer DB Scanner")


<<<<<<< HEAD
def _scan_workflows(dt_target: str, tokens: set, hits: list) -> None:
	"""Scan Workflow & Workflow Transition documents."""
=======
def _scan_workflows(dt_target: str, tokens: set, has_narrow_targets: bool, hits: list) -> None:
	"""3. Scan Workflow & Workflow Transition documents."""
>>>>>>> 3871c81 (latest ui process and ai update)
	if not frappe.db.exists("DocType", "Workflow"):
		return
	try:
		workflows = frappe.get_all("Workflow", fields=["name", "document_type", "is_active"])
		for wf in workflows:
			if not wf.is_active:
				continue
			if dt_target and wf.document_type != dt_target:
				continue

			if not has_narrow_targets:
				hits.append({
<<<<<<< HEAD
=======
					"file": f"Workflow: {wf.name}",
					"line": 1,
					"snippet": f"Active Workflow bound to DocType '{wf.document_type}'",
					"usage_type": "Workflow DocType Binding",
					"source": "Database",
>>>>>>> 3871c81 (latest ui process and ai update)
					"doctype": "Workflow",
					"name": wf.name,
					"reference_type": f"Active Workflow for DocType '{wf.document_type}'",
					"usage_type": "Workflow Binding",
					"file": f"Workflow: {wf.name}",
					"line": 1,
					"snippet": f"Active Workflow '{wf.name}' bound to DocType '{wf.document_type}'",
					"severity": "High",
					"impact": "High",
					"source": "Database",
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
						if re.search(r"\b" + re.escape(token) + r"\b", cond):
							hits.append({
<<<<<<< HEAD
=======
								"file": f"Workflow: {wf.name} (Transition {t.action})",
								"line": 1,
								"snippet": f"Transition condition references '{token}': {cond}",
								"usage_type": "Workflow Transition Condition",
								"source": "Database",
>>>>>>> 3871c81 (latest ui process and ai update)
								"doctype": "Workflow Transition",
								"name": t.name,
								"reference_type": f"Workflow Transition Condition ({wf.name} -> {t.action})",
								"usage_type": "Workflow Transition Condition",
								"file": f"Workflow: {wf.name}",
								"line": 1,
								"snippet": f"Transition '{t.action}' condition mentions '{token}': {cond}",
								"severity": "High",
								"impact": "High",
								"source": "Database",
							})
							break
	except Exception as exc:
		frappe.log_error(f"Error scanning Workflows: {exc}", "Impact Analyzer DB Scanner")


<<<<<<< HEAD
def _scan_reports(dt_target: str, tokens: set, hits: list) -> None:
	"""Scan Report documents."""
	if not frappe.db.exists("DocType", "Report"):
		return
	try:
		reports = frappe.get_all(
			"Report",
			fields=["name", "ref_doctype", "report_type", "query", "json", "disabled"],
		)
		for r in reports:
			if getattr(r, "disabled", 0):
				continue
			if dt_target and r.ref_doctype == dt_target:
				hits.append({
					"doctype": "Report",
					"name": r.name,
					"reference_type": f"Report based on '{r.ref_doctype}'",
					"usage_type": "Report DocType Reference",
					"file": f"Report: {r.name}",
					"line": 1,
					"snippet": f"Report '{r.name}' ({r.report_type}) is based on target DocType '{r.ref_doctype}'",
					"severity": "Medium",
					"impact": "Medium",
					"source": "Database",
				})
				continue

			# Check report query or json for token mentions
			query_text = (r.query or "") + " " + (r.json or "")
			for token in tokens:
				if token in query_text:
=======
def _scan_custom_fields(dt_target: str, fields_target: list, tokens: set, has_narrow_targets: bool, hits: list) -> None:
	"""4. Scan Custom Field documents."""
	if not frappe.db.exists("DocType", "Custom Field"):
		return
	try:
		cfields = frappe.get_all(
			"Custom Field",
			fields=["name", "dt", "fieldname", "label", "options", "depends_on"],
		)
		for cf in cfields:
			if has_narrow_targets:
				if dt_target and cf.dt != dt_target:
					continue
				if cf.fieldname in fields_target:
>>>>>>> 3871c81 (latest ui process and ai update)
					hits.append({
						"doctype": "Report",
						"name": r.name,
						"reference_type": f"Report Content Reference in '{r.name}'",
						"usage_type": "Report Content Reference",
						"file": f"Report: {r.name}",
						"line": 1,
<<<<<<< HEAD
						"snippet": f"Report '{r.name}' ({r.report_type}) query/definition references '{token}'",
						"severity": "Medium",
						"impact": "Medium",
=======
						"snippet": f"Target field '{cf.fieldname}' ({cf.label}) is a Custom Field on '{cf.dt}'",
						"usage_type": "Custom Field Definition",
						"source": "Database",
						"doctype": "Custom Field",
						"name": cf.name,
					})
				dep = cf.depends_on or ""
				for token in tokens:
					if re.search(r"\b" + re.escape(token) + r"\b", dep):
						hits.append({
							"file": f"Custom Field: {cf.name}",
							"line": 1,
							"snippet": f"Custom Field '{cf.fieldname}' depends_on references '{token}': {dep}",
							"usage_type": "Custom Field Expression",
							"source": "Database",
							"doctype": "Custom Field",
							"name": cf.name,
						})
						break
			else:
				if dt_target and (cf.dt == dt_target or cf.options == dt_target):
					hits.append({
						"file": f"Custom Field: {cf.name}",
						"line": 1,
						"snippet": f"Custom Field '{cf.fieldname}' on '{cf.dt}' (Options: {cf.options})",
						"usage_type": "Custom Field DocType Reference",
>>>>>>> 3871c81 (latest ui process and ai update)
						"source": "Database",
					})
	except Exception as exc:
<<<<<<< HEAD
		frappe.log_error(f"Error scanning Reports: {exc}", "DB Scanner")


def _scan_print_formats(dt_target: str, tokens: set, hits: list) -> None:
	"""Scan Print Format documents."""
	if not frappe.db.exists("DocType", "Print Format"):
=======
		frappe.log_error(f"Error scanning Custom Fields: {exc}", "Impact Analyzer DB Scanner")


def _scan_property_setters(dt_target: str, fields_target: list, has_narrow_targets: bool, hits: list) -> None:
	"""5. Scan Property Setter documents."""
	if not frappe.db.exists("DocType", "Property Setter"):
>>>>>>> 3871c81 (latest ui process and ai update)
		return
	try:
		pfs = frappe.get_all(
			"Print Format",
			fields=["name", "doc_type", "html", "disabled"],
		)
<<<<<<< HEAD
		for pf in pfs:
			if getattr(pf, "disabled", 0):
				continue
			if dt_target and pf.doc_type == dt_target:
				hits.append({
					"doctype": "Print Format",
					"name": pf.name,
					"reference_type": f"Print Format attached to '{pf.doc_type}'",
					"usage_type": "Print Format DocType Reference",
					"file": f"Print Format: {pf.name}",
					"line": 1,
					"snippet": f"Print Format '{pf.name}' attached to DocType '{pf.doc_type}'",
					"severity": "Medium",
					"impact": "Medium",
					"source": "Database",
				})
				continue

			html_text = pf.html or ""
			for token in tokens:
				if token in html_text:
					hits.append({
						"doctype": "Print Format",
						"name": pf.name,
						"reference_type": f"Print Format Template Reference in '{pf.name}'",
						"usage_type": "Print Format Content Reference",
						"file": f"Print Format: {pf.name}",
						"line": 1,
						"snippet": f"Print Format '{pf.name}' template HTML references '{token}'",
						"severity": "Medium",
						"impact": "Medium",
						"source": "Database",
					})
					break
	except Exception as exc:
		frappe.log_error(f"Error scanning Print Formats: {exc}", "DB Scanner")


def _scan_notifications(dt_target: str, tokens: set, hits: list) -> None:
	"""Scan Notification documents."""
=======
		for ps in setters:
			if has_narrow_targets:
				if dt_target and ps.doc_type != dt_target:
					continue
				if ps.field_name in fields_target:
					hits.append({
						"file": f"Property Setter: {ps.name}",
						"line": 1,
						"snippet": f"Property Setter overrides '{ps.property}' for target field '{ps.field_name}' on '{ps.doc_type}'",
						"usage_type": "Property Setter Field Override",
						"source": "Database",
						"doctype": "Property Setter",
						"name": ps.name,
					})
			else:
				if dt_target and ps.doc_type == dt_target:
					hits.append({
						"file": f"Property Setter: {ps.name}",
						"line": 1,
						"snippet": f"Property Setter on '{ps.doc_type}' (Field: {ps.field_name}, Property: {ps.property})",
						"usage_type": "Property Setter DocType Override",
						"source": "Database",
						"doctype": "Property Setter",
						"name": ps.name,
					})
	except Exception as exc:
		frappe.log_error(f"Error scanning Property Setters: {exc}", "Impact Analyzer DB Scanner")


def _scan_notifications(dt_target: str, tokens: set, has_narrow_targets: bool, hits: list) -> None:
	"""6. Scan Notification documents."""
>>>>>>> 3871c81 (latest ui process and ai update)
	if not frappe.db.exists("DocType", "Notification"):
		return
	try:
		notifications = frappe.get_all(
			"Notification",
			fields=["name", "document_type", "condition", "message", "enabled"],
		)
		for n in notifications:
			if not n.enabled:
				continue
			if dt_target and n.document_type != dt_target:
				continue

			if has_narrow_targets:
				cond = (n.condition or "") + " " + (n.message or "")
				for token in tokens:
					if re.search(r"\b" + re.escape(token) + r"\b", cond):
						hits.append({
							"file": f"Notification: {n.name}",
							"line": 1,
							"snippet": f"Notification on '{n.document_type}' references '{token}'",
							"usage_type": "Notification Condition / Message Reference",
							"source": "Database",
							"doctype": "Notification",
							"name": n.name,
						})
						break
			else:
				hits.append({
<<<<<<< HEAD
=======
					"file": f"Notification: {n.name}",
					"line": 1,
					"snippet": f"Active Notification on DocType '{n.document_type}'",
					"usage_type": "Notification DocType Binding",
					"source": "Database",
>>>>>>> 3871c81 (latest ui process and ai update)
					"doctype": "Notification",
					"name": n.name,
					"reference_type": f"Enabled Notification for DocType '{n.document_type}'",
					"usage_type": "Notification Binding",
					"file": f"Notification: {n.name}",
					"line": 1,
					"snippet": f"Enabled Notification '{n.name}' attached to DocType '{n.document_type}'",
					"severity": "Medium",
					"impact": "Medium",
					"source": "Database",
				})
<<<<<<< HEAD
				continue

			cond = n.condition or ""
			for token in tokens:
				if token in cond:
					hits.append({
						"doctype": "Notification",
						"name": n.name,
						"reference_type": f"Notification Condition Reference in '{n.name}'",
						"usage_type": "Notification Condition",
						"file": f"Notification: {n.name}",
						"line": 1,
						"snippet": f"Notification '{n.name}' condition mentions '{token}': {cond}",
						"severity": "Medium",
						"impact": "Medium",
						"source": "Database",
					})
					break
=======
>>>>>>> 3871c81 (latest ui process and ai update)
	except Exception as exc:
		frappe.log_error(f"Error scanning Notifications: {exc}", "Impact Analyzer DB Scanner")


<<<<<<< HEAD
def _scan_dashboard_items(dt_target: str, tokens: set, hits: list) -> None:
	"""Scan Dashboard Chart & Number Card documents."""
=======
def _scan_dashboard_items(dt_target: str, fields_target: list, tokens: set, has_narrow_targets: bool, hits: list) -> None:
	"""7. Scan Dashboard Chart & Number Card documents."""
>>>>>>> 3871c81 (latest ui process and ai update)
	for dt_name in ("Dashboard Chart", "Number Card"):
		if not frappe.db.exists("DocType", dt_name):
			continue
		try:
			items = frappe.get_all(dt_name, fields=["name", "document_type", "filters_json"])
			for item in items:
				if dt_target and item.document_type != dt_target:
					continue

				if has_narrow_targets:
					filters = item.filters_json or ""
					for token in tokens:
						if token in filters:
							hits.append({
								"file": f"{dt_name}: {item.name}",
								"line": 1,
								"snippet": f"{dt_name} filters mention target field '{token}'",
								"usage_type": f"{dt_name} Filter Reference",
								"source": "Database",
								"doctype": dt_name,
								"name": item.name,
							})
							break
				else:
					hits.append({
						"doctype": dt_name,
						"name": item.name,
						"reference_type": f"{dt_name} based on '{item.document_type}'",
						"usage_type": f"{dt_name} DocType Binding",
						"file": f"{dt_name}: {item.name}",
						"line": 1,
						"snippet": f"{dt_name} '{item.name}' is based on '{item.document_type}'",
						"severity": "Low",
						"impact": "Low",
						"source": "Database",
					})
<<<<<<< HEAD
					continue

				filters = item.filters_json or ""
				for token in tokens:
					if token in filters:
						hits.append({
							"doctype": dt_name,
							"name": item.name,
							"reference_type": f"{dt_name} Filters Reference in '{item.name}'",
							"usage_type": f"{dt_name} Filter Reference",
							"file": f"{dt_name}: {item.name}",
							"line": 1,
							"snippet": f"{dt_name} '{item.name}' filters mention '{token}'",
							"severity": "Low",
							"impact": "Low",
							"source": "Database",
						})
						break
		except Exception as exc:
			frappe.log_error(f"Error scanning {dt_name}: {exc}", "DB Scanner")
=======
		except Exception as exc:
			frappe.log_error(f"Error scanning {dt_name}: {exc}", "Impact Analyzer DB Scanner")
>>>>>>> 3871c81 (latest ui process and ai update)
