# Copyright (c) 2026, Team Thendral and contributors
# For license information, please see license.txt

import ast
import json
import os
import re
import frappe
from frappe import _


def scan_files(app_name: str, target: dict) -> list:
	"""
	Walk app filesystem and scan 9 file types for references to target DocTypes, fields, functions, or files.

	Parameters
	----------
	app_name : str
		Name of the Frappe bench app (e.g. "frappe", "erpnext", "impact_analyser").
	target : dict
		{
			"doctype": str,
			"fields": list[str],
			"functions": list[str],
			"filenames": list[str]
		}

	Returns
	-------
	list[dict]
		List of FileHit dicts:
		[
			{
				"file": "relative/path/to/file.py",
				"line": 42,
				"snippet": "code snippet",
				"usage_type": "Python Function Definition",
				"source": "File"
			}
		]
	"""
	app_name = app_name or "impact_analyser"
	try:
		app_path = frappe.get_app_path(app_name)
	except Exception:
		app_path = frappe.get_app_path("impact_analyser")

	hits = []
	search_targets = _prepare_search_targets(target)

	if not search_targets["all_tokens"]:
		return hits

	for root, dirs, files in os.walk(app_path):
		# Exclude virtualenvs, node_modules, git directories
		dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", ".bench", "public/dist")]

		for filename in files:
			rel_path = os.path.relpath(os.path.join(root, filename), app_path)
			full_path = os.path.join(root, filename)

			# Skip binary/large media files
			ext = os.path.splitext(filename)[1].lower()
			if ext in (".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".pyc", ".tar", ".gz", ".zip"):
				continue

			try:
				_scan_single_file(full_path, rel_path, ext, search_targets, hits)
			except Exception as exc:
				frappe.log_error(f"Error scanning file {rel_path}: {exc}", "File Scanner")

	return hits


def _prepare_search_targets(target: dict) -> dict:
	"""Normalize and build regex patterns from the target specification."""
	doctype = (target.get("doctype") or "").strip()
	fields = [f.strip() for f in target.get("fields", []) if f and f.strip()]
	functions = [f.strip() for f in target.get("functions", []) if f and f.strip()]
	filenames = [f.strip() for f in target.get("filenames", []) if f and f.strip()]

	dt_scrubbed = frappe.scrub(doctype) if doctype else ""
	dt_sql = f"tab{doctype}" if doctype else ""

	all_tokens = set()
	if doctype:
		all_tokens.add(doctype)
		if dt_scrubbed:
			all_tokens.add(dt_scrubbed)
		if dt_sql:
			all_tokens.add(dt_sql)
	for f in fields:
		all_tokens.add(f)
	for fn in functions:
		all_tokens.add(fn)

	return {
		"doctype": doctype,
		"dt_scrubbed": dt_scrubbed,
		"dt_sql": dt_sql,
		"fields": set(fields),
		"functions": set(functions),
		"filenames": set(filenames),
		"all_tokens": all_tokens,
	}


def _scan_single_file(full_path: str, rel_path: str, ext: str, targets: dict, hits: list) -> None:
	"""Route file scanning based on extension and filename."""
	filename = os.path.basename(rel_path)

	# File name target check
	if targets["filenames"]:
		for fn_target in targets["filenames"]:
			if fn_target.lower() in rel_path.lower():
				hits.append({
					"file": rel_path,
					"line": 1,
					"snippet": f"File path matches target: {rel_path}",
					"usage_type": "Target File Reference",
					"source": "File",
				})

	# Read content
	try:
		with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
			content = f.read()
	except Exception:
		return

	# Quick fast filter check: if none of all_tokens are in content, skip line scanning
	if not any(token in content for token in targets["all_tokens"]):
		return

	lines = content.splitlines()

	if ext == ".py":
		_scan_python_file(content, lines, rel_path, targets, hits)
	elif ext == ".js":
		_scan_js_file(lines, rel_path, targets, hits)
	elif ext == ".json":
		_scan_json_file(content, lines, rel_path, targets, hits)
	elif ext in (".html", ".jinja", ".md"):
		_scan_template_file(lines, rel_path, targets, hits)
	elif filename == "hooks.py":
		_scan_hooks_file(lines, rel_path, targets, hits)
	elif filename == "patches.txt" or "patches" in rel_path:
		_scan_text_lines(lines, rel_path, targets, hits, usage_type="Patch Reference")
	else:
		_scan_text_lines(lines, rel_path, targets, hits, usage_type="General Reference")


# ── File Type Scanner Handlers ────────────────────────────────────────────────

def _scan_python_file(content: str, lines: list, rel_path: str, targets: dict, hits: list) -> None:
	"""1. AST Pass + 2. Raw SQL scan for Python files."""
	# 1. AST Pass
	try:
		tree = ast.parse(content, filename=rel_path)
		for node in ast.walk(tree):
			# Function definitions
			if isinstance(node, ast.FunctionDef) and node.name in targets["functions"]:
				line_no = getattr(node, "lineno", 1)
				snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
				hits.append({
					"file": rel_path,
					"line": line_no,
					"snippet": snippet,
					"usage_type": "Python Function Def",
					"source": "File",
				})

			# Attribute access (e.g. doc.fieldname)
			elif isinstance(node, ast.Attribute) and node.attr in targets["fields"]:
				line_no = getattr(node, "lineno", 1)
				snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
				hits.append({
					"file": rel_path,
					"line": line_no,
					"snippet": snippet,
					"usage_type": "Python Field Attribute",
					"source": "File",
				})
	except SyntaxError:
		# Fallback to line scanning if AST parse fails
		pass

	# 2. Raw SQL & String Literal Scan
	sql_keywords = ("select", "update", "insert", "delete", "frappe.db.sql", "tab")
	for idx, line in enumerate(lines, start=1):
		lower = line.lower()
		if any(kw in lower for kw in sql_keywords):
			if targets["dt_sql"] and targets["dt_sql"].lower() in lower:
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": line.strip(),
					"usage_type": "Raw SQL DocType Query",
					"source": "File",
				})
			elif targets["doctype"] and targets["doctype"].lower() in lower and "tab" in lower:
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": line.strip(),
					"usage_type": "Raw SQL DocType Reference",
					"source": "File",
				})

	# 3. Direct token line match (catch calls / hooks / decorators)
	_scan_text_lines(lines, rel_path, targets, hits, usage_type="Python Reference")


def _scan_js_file(lines: list, rel_path: str, targets: dict, hits: list) -> None:
	"""3. Scan JavaScript files for frm.doc, field triggers, and frappe calls."""
	for idx, line in enumerate(lines, start=1):
		snippet = line.strip()
		# Field access / trigger check
		for field in targets["fields"]:
			if re.search(r"\b" + re.escape(field) + r"\b", line):
				if "frm.doc." in line or "cur_frm" in line:
					usage = "JS Field Access (frm.doc)"
				elif snippet.startswith(f"{field}:") or snippet.startswith(f"'{field}':") or snippet.startswith(f'"{field}":'):
					usage = "JS Field Event Handler"
				else:
					usage = "JS Field Reference"
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": snippet,
					"usage_type": usage,
					"source": "File",
				})

		# DocType check
		if targets["doctype"] and re.search(r"\b" + re.escape(targets["doctype"]) + r"\b", line):
			hits.append({
				"file": rel_path,
				"line": idx,
				"snippet": snippet,
				"usage_type": "JS DocType Reference",
				"source": "File",
			})


def _scan_json_file(content: str, lines: list, rel_path: str, targets: dict, hits: list) -> None:
	"""4. Scan JSON files (DocType definitions, Fixtures, Reports)."""
	try:
		data = json.loads(content)
		if isinstance(data, dict) and data.get("doctype") == "DocType":
			# DocType JSON file
			if targets["doctype"] and data.get("name") == targets["doctype"]:
				hits.append({
					"file": rel_path,
					"line": 1,
					"snippet": f"DocType JSON definition for {targets['doctype']}",
					"usage_type": "DocType JSON Schema",
					"source": "File",
				})

			# Fields in DocType JSON
			for idx, fld in enumerate(data.get("fields", []), start=1):
				fname = fld.get("fieldname", "")
				foptions = fld.get("options", "")
				fdepends = fld.get("depends_on", "")

				if fname in targets["fields"]:
					hits.append({
						"file": rel_path,
						"line": idx,
						"snippet": f"Field '{fname}' ({fld.get('fieldtype')}) in {data.get('name')}",
						"usage_type": "DocType Field Schema",
						"source": "File",
					})
				if targets["doctype"] and foptions == targets["doctype"]:
					hits.append({
						"file": rel_path,
						"line": idx,
						"snippet": f"Link Field '{fname}' points to target DocType '{targets['doctype']}'",
						"usage_type": "DocType Link Schema",
						"source": "File",
					})
				if targets["fields"] and any(f in fdepends for f in targets["fields"]):
					hits.append({
						"file": rel_path,
						"line": idx,
						"snippet": f"Field '{fname}' depends_on expression: {fdepends}",
						"usage_type": "DocType Depends On Schema",
						"source": "File",
					})
			return
	except Exception:
		pass

	# Generic JSON / Fixture fallback
	usage = "Fixture / JSON Reference" if "fixtures" in rel_path else "JSON Reference"
	_scan_text_lines(lines, rel_path, targets, hits, usage_type=usage)


def _scan_template_file(lines: list, rel_path: str, targets: dict, hits: list) -> None:
	"""6. Scan Jinja and HTML template files."""
	for idx, line in enumerate(lines, start=1):
		for token in targets["all_tokens"]:
			if re.search(r"\b" + re.escape(token) + r"\b", line):
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": line.strip(),
					"usage_type": "Jinja/HTML Template Reference",
					"source": "File",
				})
				break


def _scan_hooks_file(lines: list, rel_path: str, targets: dict, hits: list) -> None:
	"""5. Scan hooks.py for target doc_events, override_whitelisted_methods, etc."""
	for idx, line in enumerate(lines, start=1):
		for token in targets["all_tokens"]:
			if token in line:
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": line.strip(),
					"usage_type": "App Hooks Registration",
					"source": "File",
				})
				break


def _scan_text_lines(lines: list, rel_path: str, targets: dict, hits: list, usage_type: str = "Reference") -> None:
	"""Generic line-by-line fallback scanner using deduplicated line matching."""
	seen_lines = set()
	for idx, line in enumerate(lines, start=1):
		for token in targets["all_tokens"]:
			if token in line and idx not in seen_lines:
				seen_lines.add(idx)
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": line.strip(),
					"usage_type": usage_type,
					"source": "File",
				})
				break
