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
	Walk app filesystem and scan Python, JS, JSON, HTML, Jinja, and hooks files
	for references to target DocTypes, fields, functions, or files.
	Scoped to target fields/functions/files when specified, rather than
	indiscriminately matching the entire DocType.

	Parameters
	----------
	app_name : str
		Name of the Frappe bench app (e.g. "frappe", "airplane_mode", "impact_analyser").
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
				"usage_type": "Python Field Attribute",
				"source": "File"
			}
		]
	"""
	doctype = (target.get("doctype") or "").strip()
	app_path = _resolve_app_path(app_name, doctype)
	search_targets = _prepare_search_targets(target, app_path)

	if not search_targets["primary_tokens"] and not search_targets["filenames"]:
		return []

	hits_dict = {}

	for root, dirs, files in os.walk(app_path):
		# Exclude virtualenvs, node_modules, git directories
		dirs[:] = [
			d for d in dirs
			if d not in (".git", "node_modules", "__pycache__", ".venv", ".bench")
			and not (d == "dist" and "public" in root)
		]

		for filename in files:
			rel_path = os.path.relpath(os.path.join(root, filename), app_path)
			full_path = os.path.join(root, filename)

			# Skip binary/large media files
			ext = os.path.splitext(filename)[1].lower()
			if ext in (
				".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
				".woff", ".woff2", ".ttf", ".eot", ".pdf", ".pyc",
				".tar", ".gz", ".zip", ".lock", ".map",
			):
				continue

			try:
				_scan_single_file(full_path, rel_path, ext, filename, search_targets, hits_dict)
			except Exception as exc:
				frappe.log_error(f"Error scanning file {rel_path}: {exc}", "Impact Analyzer File Scanner")

	# Sort hits by severity (High -> Medium -> Low), then file, then line
	order = {"High": 0, "Medium": 1, "Low": 2}
	results = list(hits_dict.values())
	results.sort(key=lambda h: (order.get(h.get("severity", "Low"), 3), h.get("file", ""), h.get("line", 0)))
	return results


# ── Path Resolution ───────────────────────────────────────────────────────────

def _resolve_app_path(app_name: str, doctype: str = "") -> str:
	"""Find the filesystem root path of the target app."""
	app_name = (app_name or "").strip()

	if app_name:
		try:
			return frappe.get_app_path(app_name)
		except Exception:
			pass

	# Try resolving app from DocType module if app_name not found or not given
	if doctype:
		try:
			module = frappe.db.get_value("DocType", doctype, "module")
			if module:
				inferred_app = frappe.db.get_value("Module Def", module, "app_name")
				if inferred_app:
					return frappe.get_app_path(inferred_app)
		except Exception:
			pass

	# Check frappe-bench/apps directory directly
	if app_name:
		try:
			bench_dir = os.path.abspath(os.path.join(frappe.get_app_path("frappe"), "..", ".."))
			candidate = os.path.join(bench_dir, "apps", app_name)
			if os.path.isdir(candidate):
				return candidate
		except Exception:
			pass

	try:
		return frappe.get_app_path("impact_analyser")
	except Exception:
		return os.getcwd()


# ── Target Preparation ────────────────────────────────────────────────────────

def _prepare_search_targets(target: dict, app_path: str = "") -> dict:
	"""Normalize, discover fields, and build tokens from the target specification."""
	doctype = (target.get("doctype") or "").strip()
	fields = [f.strip() for f in target.get("fields", []) if f and f.strip()]
	functions = [f.strip() for f in target.get("functions", []) if f and f.strip()]
	filenames = [f.strip() for f in target.get("filenames", []) if f and f.strip()]

	# Discover DocType fields automatically if doctype given but no fields specified
	if doctype and not fields:
		fields = _discover_doctype_fields(doctype, app_path)

	dt_scrubbed = frappe.scrub(doctype) if doctype else ""
	dt_sql = f"tab{doctype}" if doctype else ""
	dt_camel = doctype.replace(" ", "") if doctype else ""

	# Build the universal token set for DocType-level references
	all_tokens: set = set()
	if doctype:
		all_tokens.add(doctype)
		if dt_scrubbed:
			all_tokens.add(dt_scrubbed)
		if dt_sql:
			all_tokens.add(dt_sql)
		if dt_camel and dt_camel != doctype:
			all_tokens.add(dt_camel)

	# Determine if this is a narrowly scoped scan (field/function/file level) or broad (doctype-level)
	has_narrow_targets = bool(fields or functions or filenames)

	primary_tokens: set = set()
	for f in fields:
		primary_tokens.add(f)
	for fn in functions:
		primary_tokens.add(fn)

	# If no specific fields or functions were targeted, fall back to DocType tokens
	if not has_narrow_targets:
		primary_tokens = all_tokens.copy()

	# ── REFINEMENT 1: Controller function scanning only when DocType is specified ──
	# When no doctype context exists, controller function scanning is meaningless —
	# a function name like "validate" could exist in thousands of files.
	# We track this flag so _scan_python_file can skip controller-specific logic.
	has_doctype_context = bool(doctype)

	return {
		"doctype": doctype,
		"dt_scrubbed": dt_scrubbed,
		"dt_sql": dt_sql,
		"dt_camel": dt_camel,
		"fields": set(fields),
		"functions": set(functions),
		"filenames": set(filenames),
		"has_narrow_targets": has_narrow_targets,
		"has_doctype_context": has_doctype_context,
		"primary_tokens": primary_tokens,
		"all_tokens": all_tokens,
	}


def _discover_doctype_fields(doctype: str, app_path: str = "") -> list:
	"""Query DocType metadata or inspect DocType JSON on disk to find fields."""
	discovered = []
	try:
		meta = frappe.get_meta(doctype)
		if meta:
			for df in meta.fields:
				if df.fieldname:
					discovered.append(df.fieldname)
			if discovered:
				return discovered
	except Exception:
		pass

	try:
		fields_from_db = frappe.db.get_all(
			"DocField",
			filters={"parent": doctype},
			pluck="fieldname",
		)
		if fields_from_db:
			return [f for f in fields_from_db if f]
	except Exception:
		pass

	# Search on disk for DocType JSON
	if app_path and os.path.isdir(app_path):
		dt_scrubbed = frappe.scrub(doctype)
		for root, _dirs, files in os.walk(app_path):
			if f"{dt_scrubbed}.json" in files:
				try:
					with open(os.path.join(root, f"{dt_scrubbed}.json"), "r", encoding="utf-8") as fh:
						data = json.load(fh)
						for fld in data.get("fields", []):
							fname = fld.get("fieldname")
							if fname:
								discovered.append(fname)
						if discovered:
							return discovered
				except Exception:
					pass

	return discovered


# ── Hit Recording ─────────────────────────────────────────────────────────────

def _record_hit(hits_dict: dict, rel_path: str, line_no: int, snippet: str, usage_type: str, severity: str) -> None:
	"""Deduplicate hits on (rel_path, line_no) preserving the highest severity."""
	key = (rel_path, line_no)
	order = {"High": 3, "Medium": 2, "Low": 1}
	new_rank = order.get(severity, 1)

	if key in hits_dict:
		existing = hits_dict[key]
		existing_rank = order.get(existing.get("severity", "Low"), 1)
		if new_rank > existing_rank:
			hits_dict[key] = {
				"file": rel_path,
				"line": line_no,
				"snippet": snippet,
				"usage_type": usage_type,
				"severity": severity,
				"impact": severity,
				"source": "File",
			}
	else:
		hits_dict[key] = {
			"file": rel_path,
			"line": line_no,
			"snippet": snippet,
			"usage_type": usage_type,
			"severity": severity,
			"impact": severity,
			"source": "File",
		}


# ── Single File Dispatcher ────────────────────────────────────────────────────

def _scan_single_file(full_path: str, rel_path: str, ext: str, filename: str, targets: dict, hits_dict: dict) -> None:
	"""Route file scanning based on extension and filename."""

	# ── REFINEMENT 3: Match ALL files whose basename matches target filenames ──
	# We do NOT break after the first match — every file whose path contains a
	# target filename gets a hit recorded. os.walk visits every file in the tree,
	# so there is no early-exit issue here; the fix is to NOT use break/return
	# after the first match below.
	if targets["filenames"]:
		for fn_target in targets["filenames"]:
			# Match by basename so "api.py" matches any "api.py" anywhere in the tree
			target_basename = os.path.basename(fn_target)
			if target_basename.lower() == filename.lower() or fn_target.lower() in rel_path.lower():
				_record_hit(
					hits_dict, rel_path, 1,
					f"File path matches target: {rel_path}",
					"Target File Match",
					"Medium",
				)
				# Do NOT break — record ALL matching paths; then continue scanning content

	# Read content
	try:
		with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
			content = fh.read()
	except Exception:
		return

	# Fast filter: if none of the primary tokens appear anywhere in content, skip
	if targets["primary_tokens"] and not any(token in content for token in targets["primary_tokens"]):
		# Still scan if no primary tokens (e.g. pure filename-based target)
		if not targets["filenames"]:
			return

	lines = content.splitlines()

	if ext == ".py":
		_scan_python_file(content, lines, rel_path, filename, targets, hits_dict)
	elif ext == ".js":
		_scan_js_file(lines, rel_path, targets, hits_dict)
	elif ext == ".json":
		_scan_json_file(content, lines, rel_path, targets, hits_dict)
	elif ext in (".html", ".jinja", ".md"):
		_scan_template_file(lines, rel_path, targets, hits_dict)
	elif filename == "hooks.py":
		_scan_hooks_file(lines, rel_path, targets, hits_dict)
	elif filename == "patches.txt" or "patches" in rel_path:
		_scan_text_lines(lines, rel_path, targets, hits_dict, usage_type="Patch Reference", severity="Low")
	else:
		_scan_text_lines(lines, rel_path, targets, hits_dict, usage_type="General Reference", severity="Low")


# ── File Type Handlers ────────────────────────────────────────────────────────

def _scan_python_file(content: str, lines: list, rel_path: str, filename: str, targets: dict, hits_dict: dict) -> None:
	"""Scan Python file with AST and regex analysis for mutations (High), reads (Medium), and refs (Low)."""
	ast_lines_handled: set = set()

	# 1. AST Pass
	try:
		tree = ast.parse(content)
		for node in ast.walk(tree):
			# Field assignment/write: doc.field = value (High)
			if (
				isinstance(node, ast.Assign)
				and isinstance(node.targets[0], ast.Attribute)
				and node.targets[0].attr in targets["fields"]
			):
				line_no = getattr(node, "lineno", 1)
				if line_no not in ast_lines_handled:
					snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
					ast_lines_handled.add(line_no)
					_record_hit(hits_dict, rel_path, line_no, snippet, "Python Field Write (Assignment)", "High")

			# ── REFINEMENT 1: Controller function def scanning only with DocType context ──
			# Only scan for function definitions inside files when we have a DocType.
			# Without a DocType, matching a function name like "validate" is meaningless.
			if targets["has_doctype_context"] and targets["functions"]:
				# Function definition in controller: def validate(self):
				if isinstance(node, ast.FunctionDef) and node.name in targets["functions"]:
					line_no = getattr(node, "lineno", 1)
					if line_no not in ast_lines_handled:
						snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
						ast_lines_handled.add(line_no)
						_record_hit(hits_dict, rel_path, line_no, snippet, "Python Function Definition", "High")

				# Function call
				if (
					isinstance(node, ast.Call)
					and isinstance(getattr(node, "func", None), ast.Attribute)
					and node.func.attr in targets["functions"]
				):
					line_no = getattr(node, "lineno", 1)
					if line_no not in ast_lines_handled:
						snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
						ast_lines_handled.add(line_no)
						_record_hit(hits_dict, rel_path, line_no, snippet, "Python Function Call", "Medium")

			# Field attribute access (e.g. doc.fieldname)
			if isinstance(node, ast.Attribute) and node.attr in targets["fields"]:
				line_no = getattr(node, "lineno", 1)
				if line_no not in ast_lines_handled:
					snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
					ast_lines_handled.add(line_no)
					_record_hit(hits_dict, rel_path, line_no, snippet, "Python Field Attribute Access", "Medium")

	except SyntaxError:
		pass

	# 2. Raw SQL scan
	sql_keywords = ("select", "update", "insert", "delete", "frappe.db.sql", "from", "where")
	for idx, line in enumerate(lines, start=1):
		if idx in ast_lines_handled:
			continue
		lower = line.lower()
		if any(kw in lower for kw in sql_keywords):
			for token in targets["primary_tokens"]:
				if re.search(r"\b" + re.escape(token) + r"\b", line):
					ast_lines_handled.add(idx)
					_record_hit(hits_dict, rel_path, idx, line.strip(), "Raw SQL Reference", "High")
					break

	# 3. Direct token line match (dict access or assignments)
	for idx, line in enumerate(lines, start=1):
		if idx in ast_lines_handled:
			continue
		for token in targets["primary_tokens"]:
			pattern = r"['\"]" + re.escape(token) + r"['\"]|\b" + re.escape(token) + r"\b"
			if re.search(pattern, line):
				ast_lines_handled.add(idx)
				_record_hit(hits_dict, rel_path, idx, line.strip(), "Python Code Reference", "Low")
				break


def _scan_js_file(lines: list, rel_path: str, targets: dict, hits_dict: dict) -> None:
	"""Scan JavaScript files for frm.doc, field triggers, and frappe calls."""
	seen_lines: set = set()
	for idx, line in enumerate(lines, start=1):
		snippet = line.strip()

		# Scoped to fields
		for field in targets["fields"]:
			if re.search(r"\b" + re.escape(field) + r"\b", line):
				if "frm.doc." in line or "cur_frm" in line:
					usage = "JS Field Access (frm.doc)"
				elif snippet.startswith(f"{field}:") or snippet.startswith(f"'{field}':") or snippet.startswith(f'"{field}":'):
					usage = "JS Field Event Trigger"
				else:
					usage = "JS Field Reference"
				seen_lines.add(idx)
				_record_hit(hits_dict, rel_path, idx, snippet, usage, "Medium")
				break

		# Scoped to functions (only when DocType context exists)
		if targets["has_doctype_context"]:
			for fn in targets["functions"]:
				if idx not in seen_lines and re.search(r"\b" + re.escape(fn) + r"\b", line):
					seen_lines.add(idx)
					_record_hit(hits_dict, rel_path, idx, snippet, "JS Function Reference", "Medium")
					break

		# If broad DocType scan
		if not targets["has_narrow_targets"] and targets["doctype"]:
			if idx not in seen_lines and re.search(r"\b" + re.escape(targets["doctype"]) + r"\b", line):
				seen_lines.add(idx)
				_record_hit(hits_dict, rel_path, idx, snippet, "JS DocType Reference", "Low")


def _scan_json_file(content: str, lines: list, rel_path: str, targets: dict, hits_dict: dict) -> None:
	"""Scan JSON file for DocType schema definitions, link fields, and depends_on."""
	try:
		data = json.loads(content)
		if isinstance(data, dict) and data.get("doctype") == "DocType":
			# Root DocType match
			if targets["doctype"] and data.get("name") == targets["doctype"]:
				_record_hit(
					hits_dict, rel_path, 1,
					f"DocType JSON schema for '{targets['doctype']}'",
					"DocType JSON Schema Definition", "Low",
				)

			# Field schema
			last_line_idx = 0
			for fld in data.get("fields", []):
				fname = fld.get("fieldname", "")
				foptions = fld.get("options", "")
				fdepends = fld.get("depends_on", "") or ""

				# Find real line number for this field in JSON
				field_line = 1
				if fname:
					target_pattern = f'"fieldname": "{fname}"'
					for l_idx in range(last_line_idx, len(lines)):
						if target_pattern in lines[l_idx]:
							field_line = l_idx + 1
							last_line_idx = l_idx + 1
							break
					else:
						# Fallback if not found searching forward: search from start of file
						for l_idx in range(len(lines)):
							if target_pattern in lines[l_idx]:
								field_line = l_idx + 1
								break

				# Link field pointing to target doctype (High severity schema coupling)
				if targets["doctype"] and foptions == targets["doctype"]:
					_record_hit(
						hits_dict, rel_path, field_line,
						f"Link Field '{fname}' points to target DocType '{targets['doctype']}'",
						"DocType Link Schema", "High",
					)

				# Target field definition
				if fname in targets["fields"]:
					_record_hit(
						hits_dict, rel_path, field_line,
						f"Field '{fname}' ({fld.get('fieldtype')}) in {data.get('name')}",
						"DocType Field Schema", "Medium",
					)

				# depends_on expression
				if targets["fields"] and any(f in fdepends for f in targets["fields"]):
					_record_hit(
						hits_dict, rel_path, field_line,
						f"Field '{fname}' depends_on expression: {fdepends}",
						"DocType Depends On Schema", "Medium",
					)

			return
	except Exception:
		pass

	# Generic JSON fallback
	_scan_text_lines(lines, rel_path, targets, hits_dict, usage_type="JSON Reference", severity="Low")


def _scan_template_file(lines: list, rel_path: str, targets: dict, hits_dict: dict) -> None:
	"""Scan Jinja, HTML, and Markdown templates for token references."""
	for idx, line in enumerate(lines, start=1):
		for token in targets["primary_tokens"]:
			if re.search(r"\b" + re.escape(token) + r"\b", line):
				_record_hit(
					hits_dict, rel_path, idx, line.strip(),
					"Template Field / DocType Reference", "Low",
				)
				break


def _scan_hooks_file(lines: list, rel_path: str, targets: dict, hits_dict: dict) -> None:
	"""Scan hooks.py for doc_events or method overrides."""
	for idx, line in enumerate(lines, start=1):
		for token in targets["primary_tokens"]:
			if token in line:
				_record_hit(
					hits_dict, rel_path, idx, line.strip(),
					"App Hooks Registration", "Low",
				)
				break


def _scan_text_lines(lines: list, rel_path: str, targets: dict, hits_dict: dict, usage_type: str, severity: str) -> None:
	"""Generic line-by-line fallback scanner."""
	for idx, line in enumerate(lines, start=1):
		for token in targets["primary_tokens"]:
			if token in line:
				_record_hit(hits_dict, rel_path, idx, line.strip(), usage_type, severity)
				break
