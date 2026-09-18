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
<<<<<<< HEAD
	Walk app filesystem and scan Python, JS, JSON, HTML, Jinja, and hooks files
	for references to target DocTypes, fields, functions, or files.
=======
	Walk app filesystem and scan 9 file types for references to target DocTypes, fields, functions, or files.
	Scoped to target fields/functions/files when specified, rather than indiscriminately matching the entire DocType.
>>>>>>> 3871c81 (latest ui process and ai update)

	Parameters
	----------
	app_name : str
<<<<<<< HEAD
		Name of the Frappe bench app (e.g. "student_management", "frappe", "impact_analyser").
=======
		Name of the Frappe bench app (e.g. "frappe", "airplane_mode", "impact_analyser").
>>>>>>> 3871c81 (latest ui process and ai update)
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
		List of FileHit dicts with line number, snippet, and severity:
		[
			{
				"file": "relative/path/to/file.py",
				"line": 42,
<<<<<<< HEAD
				"snippet": "self.seat = seat",
				"usage_type": "Python Field Write (Assignment)",
				"severity": "High",
=======
				"snippet": "code snippet",
				"usage_type": "Python Field Attribute",
>>>>>>> 3871c81 (latest ui process and ai update)
				"source": "File"
			}
		]
	"""
	doctype = (target.get("doctype") or "").strip()
	app_path = _resolve_app_path(app_name, doctype)
	search_targets = _prepare_search_targets(target, app_path)

<<<<<<< HEAD
	if not search_targets["all_tokens"] and not search_targets["filenames"]:
		return []

	hits_dict = {}
=======
	hits = []
	targets = _prepare_search_targets(target)

	if not targets["primary_tokens"] and not targets["filenames"]:
		return hits
>>>>>>> 3871c81 (latest ui process and ai update)

	for root, dirs, files in os.walk(app_path):
		# Exclude virtualenvs, node_modules, git directories
		dirs[:] = [
			d for d in dirs
			if d not in (".git", "node_modules", "__pycache__", ".venv", ".bench", "public/dist")
		]

		for filename in files:
			rel_path = os.path.relpath(os.path.join(root, filename), app_path)
			full_path = os.path.join(root, filename)

			# Skip binary/large media files
			ext = os.path.splitext(filename)[1].lower()
			if ext in (
				".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
				".woff", ".woff2", ".ttf", ".eot", ".pdf", ".pyc",
				".tar", ".gz", ".zip", ".lock",
			):
				continue

			try:
<<<<<<< HEAD
				_scan_single_file(full_path, rel_path, ext, search_targets, hits_dict)
=======
				_scan_single_file(full_path, rel_path, ext, targets, hits)
>>>>>>> 3871c81 (latest ui process and ai update)
			except Exception as exc:
				frappe.log_error(f"Error scanning file {rel_path}: {exc}", "Impact Analyzer File Scanner")

	# Sort hits by severity (High -> Medium -> Low), then file, then line
	order = {"High": 0, "Medium": 1, "Low": 2}
	results = list(hits_dict.values())
	results.sort(key=lambda h: (order.get(h.get("severity", "Low"), 3), h.get("file", ""), h.get("line", 0)))
	return results


<<<<<<< HEAD
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


def _prepare_search_targets(target: dict, app_path: str = "") -> dict:
	"""Normalize, discover fields, and build tokens from the target specification."""
=======
def _prepare_search_targets(target: dict) -> dict:
	"""
	Normalize target specification.
	If fields, functions, or filenames are specified, scoping ensures that the scan
	focuses on references to those specific elements rather than matching every
	appearance of the DocType name across the codebase.
	"""
>>>>>>> 3871c81 (latest ui process and ai update)
	doctype = (target.get("doctype") or "").strip()
	fields = [f.strip() for f in target.get("fields", []) if f and f.strip()]
	functions = [f.strip() for f in target.get("functions", []) if f and f.strip()]
	filenames = [f.strip() for f in target.get("filenames", []) if f and f.strip()]

	# Discover DocType fields automatically if none were explicitly provided
	if doctype and not fields:
		fields = _discover_doctype_fields(doctype, app_path)

	dt_scrubbed = frappe.scrub(doctype) if doctype else ""
	dt_sql = f"tab{doctype}" if doctype else ""
	dt_camel = doctype.replace(" ", "") if doctype else ""

<<<<<<< HEAD
	all_tokens = set()
	if doctype:
		all_tokens.add(doctype)
		if dt_scrubbed:
			all_tokens.add(dt_scrubbed)
		if dt_sql:
			all_tokens.add(dt_sql)
		if dt_camel and dt_camel != doctype:
			all_tokens.add(dt_camel)

=======
	# Determine if this is a narrowly scoped scan (field/function/file level) or broad (doctype-level)
	has_narrow_targets = bool(fields or functions or filenames)

	primary_tokens = set()
>>>>>>> 3871c81 (latest ui process and ai update)
	for f in fields:
		primary_tokens.add(f)
	for fn in functions:
		primary_tokens.add(fn)

	# If no specific fields or functions were targeted, then the doctype is the primary target
	if not has_narrow_targets and doctype:
		primary_tokens.add(doctype)
		if dt_scrubbed:
			primary_tokens.add(dt_scrubbed)
		if dt_sql:
			primary_tokens.add(dt_sql)

	return {
		"doctype": doctype,
		"dt_scrubbed": dt_scrubbed,
		"dt_sql": dt_sql,
		"dt_camel": dt_camel,
		"fields": set(fields),
		"functions": set(functions),
		"filenames": set(filenames),
		"has_narrow_targets": has_narrow_targets,
		"primary_tokens": primary_tokens,
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
					with open(os.path.join(root, f"{dt_scrubbed}.json"), "r", encoding="utf-8") as f:
						data = json.load(f)
						for fld in data.get("fields", []):
							fname = fld.get("fieldname")
							if fname:
								discovered.append(fname)
						if discovered:
							return discovered
				except Exception:
					pass

	return discovered


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


def _scan_single_file(full_path: str, rel_path: str, ext: str, targets: dict, hits_dict: dict) -> None:
	"""Route file scanning based on extension and filename."""
	filename = os.path.basename(rel_path)

	# 1. Target file name match
	if targets["filenames"]:
		for fn_target in targets["filenames"]:
			if fn_target.lower() in rel_path.lower():
				_record_hit(
					hits_dict, rel_path, 1,
					f"File path matches target: {rel_path}",
					"Target File Match",
					"Medium",
				)

	# Read content
	try:
		with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
			content = f.read()
	except Exception:
		return

	# Fast filter check: if none of the primary tokens appear in content, skip line scanning
	if not any(token in content for token in targets["primary_tokens"]):
		return

	lines = content.splitlines()

	if ext == ".py":
		_scan_python_file(content, lines, rel_path, targets, hits_dict)
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


<<<<<<< HEAD
def _scan_python_file(content: str, lines: list, rel_path: str, targets: dict, hits_dict: dict) -> None:
	"""Scan Python file with AST and regex analysis for mutations (High), reads (Medium), and refs (Low)."""
	ast_lines_handled = set()

=======
# ── File Type Handlers ────────────────────────────────────────────────────────

def _scan_python_file(content: str, lines: list, rel_path: str, targets: dict, hits: list) -> None:
	"""1. AST Pass + 2. Raw SQL + 3. Line References for Python files."""
	seen_lines = set()

>>>>>>> 3871c81 (latest ui process and ai update)
	# 1. AST Pass
	try:
		tree = ast.parse(content, filename=rel_path)
		for node in ast.walk(tree):
			# Function definition matching target
			if isinstance(node, ast.FunctionDef) and node.name in targets["functions"]:
				line_no = getattr(node, "lineno", 1)
				snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
<<<<<<< HEAD
				_record_hit(
					hits_dict, rel_path, line_no, snippet,
					"Python Function Definition", "High",
				)
				ast_lines_handled.add(line_no)

			# Field assignments / writes: doc.fieldname = ...
			elif isinstance(node, ast.Assign):
				for target_node in node.targets:
					if isinstance(target_node, ast.Attribute) and target_node.attr in targets["fields"]:
						line_no = getattr(node, "lineno", 1)
						snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
						_record_hit(
							hits_dict, rel_path, line_no, snippet,
							"Python Field Write (Assignment)", "High",
						)
						ast_lines_handled.add(line_no)

			# Attribute reads: doc.fieldname
			elif isinstance(node, ast.Attribute) and node.attr in targets["fields"]:
				line_no = getattr(node, "lineno", 1)
				if line_no not in ast_lines_handled:
					snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
					_record_hit(
						hits_dict, rel_path, line_no, snippet,
						"Python Field Access", "Medium",
					)
					ast_lines_handled.add(line_no)

	except SyntaxError:
		pass

	# 2. Line-by-line inspection for Frappe API calls & SQL
	for idx, line in enumerate(lines, start=1):
		stripped = line.strip()
		lower = line.lower()

		# Frappe mutations (High)
		mutation_keywords = (
			"frappe.db.set_value", "frappe.delete_doc", "frappe.new_doc",
			".insert(", ".save(", ".delete(", ".submit(", ".cancel(",
			"update tab", "delete from tab", "insert into tab",
		)
		if any(kw in lower for kw in mutation_keywords):
			if targets["doctype"] and (targets["doctype"].lower() in lower or targets["dt_scrubbed"] in lower):
				_record_hit(
					hits_dict, rel_path, idx, stripped,
					"Python DocType Mutation", "High",
				)
				continue
			if any(f in line for f in targets["fields"]):
				_record_hit(
					hits_dict, rel_path, idx, stripped,
					"Python Field Mutation", "High",
				)
				continue

		# Frappe reads / queries (Medium)
		read_keywords = (
			"frappe.get_doc", "frappe.get_all", "frappe.get_list",
			"frappe.db.get_value", "frappe.db.count", "frappe.db.exists",
			"frappe.db.sql", "select ",
		)
		if any(kw in lower for kw in read_keywords):
			if targets["dt_sql"] and targets["dt_sql"].lower() in lower:
				_record_hit(
					hits_dict, rel_path, idx, stripped,
					"Raw SQL DocType Query", "Medium",
				)
				continue
			elif targets["doctype"] and (targets["doctype"].lower() in lower or targets["dt_scrubbed"] in lower):
				_record_hit(
					hits_dict, rel_path, idx, stripped,
					"Python DocType Query / Read", "Medium",
				)
				continue

		# Generic tokens match (Comments, docstrings, imports -> Low)
		if idx not in ast_lines_handled:
			for token in targets["all_tokens"]:
				if token in line:
					is_comment = stripped.startswith("#") or '"""' in stripped or "'''" in stripped
					sev = "Low" if is_comment else "Medium"
					utype = "Python DocType Reference" if token in (targets["doctype"], targets["dt_scrubbed"]) else "Python Field Reference"
					_record_hit(hits_dict, rel_path, idx, stripped, utype, sev)
					break


def _scan_js_file(lines: list, rel_path: str, targets: dict, hits_dict: dict) -> None:
	"""Scan JavaScript file for frm.set_value (High), event handlers & reads (Medium), refs (Low)."""
	for idx, line in enumerate(lines, start=1):
		stripped = line.strip()
		lower = line.lower()

		# Field writes via frm.set_value or cur_frm.set_value (High)
		if "set_value" in line and any(f in line for f in targets["fields"]):
			_record_hit(
				hits_dict, rel_path, idx, stripped,
				"JS Field Write (set_value)", "High",
			)
			continue

		# Direct assignment frm.doc.fieldname = ... (High)
		for field in targets["fields"]:
			if re.search(r"(?:frm\.doc|cur_frm\.doc)\." + re.escape(field) + r"\s*=", line):
				_record_hit(
					hits_dict, rel_path, idx, stripped,
					"JS Field Write (Assignment)", "High",
				)
				break

		# Event handlers & triggers (Medium)
		for field in targets["fields"]:
			if re.search(r"\b" + re.escape(field) + r"\b", line):
				if stripped.startswith(f"{field}:") or stripped.startswith(f"'{field}':") or stripped.startswith(f'"{field}":'):
					_record_hit(
						hits_dict, rel_path, idx, stripped,
						"JS Field Event Handler", "Medium",
					)
				elif "frm.doc." in line or "cur_frm.doc." in line:
					_record_hit(
						hits_dict, rel_path, idx, stripped,
						"JS Field Access (frm.doc)", "Medium",
					)
				else:
					_record_hit(
						hits_dict, rel_path, idx, stripped,
						"JS Field Reference", "Low",
					)

		# DocType checks (Medium / Low)
		if targets["doctype"] and re.search(r"\b" + re.escape(targets["doctype"]) + r"\b", line):
			if "frappe.ui.form.on" in line or "frappe.call" in line:
				_record_hit(
					hits_dict, rel_path, idx, stripped,
					"JS DocType Form Trigger / Call", "Medium",
				)
			else:
				_record_hit(
					hits_dict, rel_path, idx, stripped,
					"JS DocType Reference", "Low",
				)
=======
				seen_lines.add(line_no)
				hits.append({
					"file": rel_path,
					"line": line_no,
					"snippet": snippet,
					"usage_type": "Python Function Definition",
					"source": "File",
				})

			# Function calls
			elif isinstance(node, ast.Call):
				func_name = ""
				if isinstance(node.func, ast.Name):
					func_name = node.func.id
				elif isinstance(node.func, ast.Attribute):
					func_name = node.func.attr
				if func_name and func_name in targets["functions"]:
					line_no = getattr(node, "lineno", 1)
					if line_no not in seen_lines:
						snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
						seen_lines.add(line_no)
						hits.append({
							"file": rel_path,
							"line": line_no,
							"snippet": snippet,
							"usage_type": "Python Function Call",
							"source": "File",
						})

			# Field attribute access (e.g. doc.fieldname)
			elif isinstance(node, ast.Attribute) and node.attr in targets["fields"]:
				line_no = getattr(node, "lineno", 1)
				if line_no not in seen_lines:
					snippet = lines[line_no - 1].strip() if line_no <= len(lines) else ""
					seen_lines.add(line_no)
					hits.append({
						"file": rel_path,
						"line": line_no,
						"snippet": snippet,
						"usage_type": "Python Field Attribute Access",
						"source": "File",
					})
	except SyntaxError:
		pass

	# 2. Raw SQL scan
	sql_keywords = ("select", "update", "insert", "delete", "frappe.db.sql", "from", "where")
	for idx, line in enumerate(lines, start=1):
		if idx in seen_lines:
			continue
		lower = line.lower()
		if any(kw in lower for kw in sql_keywords):
			for token in targets["primary_tokens"]:
				if re.search(r"\b" + re.escape(token) + r"\b", line):
					seen_lines.add(idx)
					hits.append({
						"file": rel_path,
						"line": idx,
						"snippet": line.strip(),
						"usage_type": "Raw SQL Reference",
						"source": "File",
					})
					break

	# 3. Direct token line match (dict access or assignments)
	for idx, line in enumerate(lines, start=1):
		if idx in seen_lines:
			continue
		for token in targets["primary_tokens"]:
			# Match word boundary or quoted token
			pattern = r"['\"]" + re.escape(token) + r"['\"]|\b" + re.escape(token) + r"\b"
			if re.search(pattern, line):
				seen_lines.add(idx)
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": line.strip(),
					"usage_type": "Python Code Reference",
					"source": "File",
				})
				break


def _scan_js_file(lines: list, rel_path: str, targets: dict, hits: list) -> None:
	"""3. Scan JavaScript files for frm.doc, field triggers, and frappe calls."""
	seen_lines = set()
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
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": snippet,
					"usage_type": usage,
					"source": "File",
				})
				break

		# Scoped to functions
		for fn in targets["functions"]:
			if idx not in seen_lines and re.search(r"\b" + re.escape(fn) + r"\b", line):
				seen_lines.add(idx)
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": snippet,
					"usage_type": "JS Function Reference",
					"source": "File",
				})
				break

		# If broad DocType scan
		if not targets["has_narrow_targets"] and targets["doctype"]:
			if idx not in seen_lines and re.search(r"\b" + re.escape(targets["doctype"]) + r"\b", line):
				seen_lines.add(idx)
				hits.append({
					"file": rel_path,
					"line": idx,
					"snippet": snippet,
					"usage_type": "JS DocType Reference",
					"source": "File",
				})
>>>>>>> 3871c81 (latest ui process and ai update)


def _scan_json_file(content: str, lines: list, rel_path: str, targets: dict, hits_dict: dict) -> None:
	"""Scan JSON file for DocType schema definitions, link fields, and depends_on."""
	try:
		data = json.loads(content)
		if isinstance(data, dict) and data.get("doctype") == "DocType":
<<<<<<< HEAD
			# Root DocType match
			if targets["doctype"] and data.get("name") == targets["doctype"]:
				_record_hit(
					hits_dict, rel_path, 1,
					f"DocType JSON schema for '{targets['doctype']}'",
					"DocType JSON Schema Definition", "Low",
				)
=======
			dt_name = data.get("name", "")

			# If broad doctype scan
			if not targets["has_narrow_targets"] and targets["doctype"] and dt_name == targets["doctype"]:
				hits.append({
					"file": rel_path,
					"line": 1,
					"snippet": f"DocType JSON schema definition for {targets['doctype']}",
					"usage_type": "DocType Schema Definition",
					"source": "File",
				})
>>>>>>> 3871c81 (latest ui process and ai update)

			# Field schema
			for idx, fld in enumerate(data.get("fields", []), start=1):
				fname = fld.get("fieldname", "")
				foptions = fld.get("options", "")
				fdepends = fld.get("depends_on", "")

<<<<<<< HEAD
				# Link field pointing to target doctype (High severity schema coupling)
				if targets["doctype"] and foptions == targets["doctype"]:
					_record_hit(
						hits_dict, rel_path, idx,
						f"Link Field '{fname}' points to target DocType '{targets['doctype']}'",
						"DocType Link Schema", "High",
					)

				# Target field definition
				if fname in targets["fields"]:
					_record_hit(
						hits_dict, rel_path, idx,
						f"Field '{fname}' ({fld.get('fieldtype')}) in {data.get('name')}",
						"DocType Field Schema", "Medium",
					)

				# depends_on expression
				if targets["fields"] and any(f in fdepends for f in targets["fields"]):
					_record_hit(
						hits_dict, rel_path, idx,
						f"Field '{fname}' depends_on expression: {fdepends}",
						"DocType Depends On Schema", "Medium",
					)
=======
				if targets["fields"] and fname in targets["fields"]:
					hits.append({
						"file": rel_path,
						"line": idx,
						"snippet": f"Field '{fname}' ({fld.get('fieldtype')}) defined in {dt_name}",
						"usage_type": "DocType Field Schema",
						"source": "File",
					})
				if targets["fields"] and any(f in (fdepends or "") for f in targets["fields"]):
					hits.append({
						"file": rel_path,
						"line": idx,
						"snippet": f"Field '{fname}' depends_on expression mentions target: {fdepends}",
						"usage_type": "DocType Depends On Expression",
						"source": "File",
					})
				if not targets["has_narrow_targets"] and targets["doctype"] and foptions == targets["doctype"]:
					hits.append({
						"file": rel_path,
						"line": idx,
						"snippet": f"Link Field '{fname}' points to target DocType '{targets['doctype']}'",
						"usage_type": "DocType Link Schema",
						"source": "File",
					})
>>>>>>> 3871c81 (latest ui process and ai update)
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


<<<<<<< HEAD
def _scan_text_lines(lines: list, rel_path: str, targets: dict, hits_dict: dict, usage_type: str, severity: str) -> None:
	"""Generic line-by-line fallback scanner."""
	for idx, line in enumerate(lines, start=1):
		for token in targets["all_tokens"]:
			if token in line:
				_record_hit(hits_dict, rel_path, idx, line.strip(), usage_type, severity)
				break
=======
def _scan_text_lines(lines: list, rel_path: str, targets: dict, hits: list, usage_type: str = "Reference") -> None:
	"""Generic line-by-line fallback scanner."""
	seen_lines = set()
	for idx, line in enumerate(lines, start=1):
		for token in targets["primary_tokens"]:
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
>>>>>>> 3871c81 (latest ui process and ai update)
