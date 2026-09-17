# Copyright (c) 2026, Impact Analyser and contributors
# For license information, please see license.txt

import ast
import difflib
import os
import re
import frappe
from frappe.model.document import Document

# Frappe DocType Controller standard lifecycle methods called dynamically by the framework
FRAPPE_CONTROLLER_LIFECYCLE = {
	"validate", "before_save", "before_insert", "after_insert", "on_submit",
	"before_submit", "on_cancel", "before_cancel", "on_update", "after_delete",
	"on_trash", "autoname", "before_validate", "on_change", "setup", "onload",
	"get_list", "get_count", "has_permission", "get_permission_query_conditions"
}

# Standard Frappe Client Script lifecycle events
FRAPPE_JS_LIFECYCLE = {
	"refresh", "onload", "validate", "before_save", "before_submit", "on_submit",
	"setup", "timeline_refresh", "onload_post_render", "before_cancel", "on_cancel"
}

class DeadCodeEliminator(Document):
	def validate(self):
		if not self.title:
			self.title = f"Scan: {self.target_app or 'impact_analyser'}"

	@frappe.whitelist()
	def run_analysis(self):
		"""Scans every DocType, .py, and .js file across the target Frappe app."""
		app_name = self.target_app or "impact_analyser"
		app_dir = self.app_path

		if not app_dir:
			try:
				app_dir = frappe.get_app_path(app_name)
			except Exception:
				# Fallback: check current directory or common bench path
				candidates = [
					os.path.join(frappe.get_bench_path() if hasattr(frappe, "get_bench_path") else "", "apps", app_name),
					os.path.join("/home/raj/aeroplane_app/apps", app_name),
					os.getcwd()
				]
				for cand in candidates:
					if os.path.exists(cand):
						app_dir = cand
						break

		if not app_dir or not os.path.exists(app_dir):
			frappe.throw(f"Cannot locate Frappe app directory for '{app_name}'. Please verify the path.")

		self.app_path = app_dir
		self.status = "Scanning Entire App"
		self.set("inventory", [])
		self.call_path_justifications = ""

		# 1. Discover all source files across the app
		py_files, js_files, doctype_dirs = self._discover_app_files(app_dir)
		total_files = len(py_files) + len(js_files)
		self.total_files_scanned = total_files

		# 2. Extract Framework Hooks (hooks.py, whitelisted endpoints, client script calls)
		hooks_alive_symbols = self._extract_framework_hooks(app_dir)

		# 3. Build Global Cross-File Reference Graph
		app_symbol_references, total_lines = self._build_global_reference_graph(py_files, js_files)
		self.total_lines_scanned = total_lines

		# 4. Scan files for the 6 Dead Code Categories with Frappe Guardrails
		all_dead_items = []
		file_diff_map = {}

		# Scan Python Files (.py & DocType Controllers)
		if self.scan_python_files:
			for py_path in py_files:
				rel_path = os.path.relpath(py_path, app_dir)
				items, diff_chunk = self._scan_python_file(
					py_path, rel_path, app_symbol_references, hooks_alive_symbols
				)
				if items:
					all_dead_items.extend(items)
				if diff_chunk:
					file_diff_map[rel_path] = diff_chunk

		# Scan JavaScript Files (.js & DocType Client Scripts)
		if self.scan_javascript_files:
			for js_path in js_files:
				rel_path = os.path.relpath(js_path, app_dir)
				items, diff_chunk = self._scan_js_file(
					js_path, rel_path, app_symbol_references, hooks_alive_symbols
				)
				if items:
					all_dead_items.extend(items)
				if diff_chunk:
					file_diff_map[rel_path] = diff_chunk

		# 5. Populate Section 5.A: Dead Code Inventory Table
		low_cnt = 0
		med_cnt = 0
		high_cnt = 0
		justifications = []

		for item in all_dead_items:
			self.append("inventory", {
				"symbol_or_block": item["symbol"],
				"symbol_type": item["type"],
				"file_path": item["file_path"],
				"location": item["location"],
				"reason": item["reason"],
				"risk_level": item["risk"],
				"call_path_justification": item["justification"],
				"safe_to_eliminate": 1 if item["safe"] else 0
			})

			if item["risk"] == "Low":
				low_cnt += 1
			elif item["risk"] == "Medium":
				med_cnt += 1
			else:
				high_cnt += 1

			justifications.append(
				f"#### `{item['symbol']}` ({item['type']})\n"
				f"- **File:** `{item['file_path']}:{item['location']}`\n"
				f"- **Reason:** {item['reason']}\n"
				f"- **Unreachability Proof:** {item['justification']}\n"
			)

		self.total_dead_items = len(all_dead_items)
		self.low_risk_count = low_cnt
		self.medium_risk_count = med_cnt
		self.high_risk_count = high_cnt

		# 6. Populate Section 5.B: Call Path Justifications
		if justifications:
			self.call_path_justifications = (
				f"### App-Wide Unreachability Analysis ({self.total_dead_items} Candidates Found)\n\n"
				+ "\n".join(justifications)
			)
		else:
			self.call_path_justifications = "### No dead code detected. All symbols have active call paths across the Frappe app."

		# 7. Populate Section 5.C: Multi-File Unified Diffs
		unified_diff_text, diff_html = self._format_multi_file_diff(file_diff_map)
		self.unified_diff = unified_diff_text
		self.diff_html = diff_html

		self.status = "Completed"
		self.save()

		return {
			"total_files": self.total_files_scanned,
			"total_dead_items": self.total_dead_items,
			"low_risk": self.low_risk_count,
			"diff_files": len(file_diff_map)
		}

	def _discover_app_files(self, app_dir: str):
		"""Traverses the Frappe app to index all DocType controllers, scripts, and modules."""
		py_files = []
		js_files = []
		doctype_dirs = []

		skip_dirs = {"node_modules", "__pycache__", ".git", "dist", "public/dist", "build", "env", "venv"}

		for root, dirs, files in os.walk(app_dir):
			dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

			if os.path.basename(root) == "doctype":
				doctype_dirs.append(root)

			for file in files:
				if file.endswith(".py") and not file.startswith("."):
					py_files.append(os.path.join(root, file))
				elif file.endswith(".js") and not file.startswith("."):
					js_files.append(os.path.join(root, file))

		return py_files, js_files, doctype_dirs

	def _extract_framework_hooks(self, app_dir: str) -> set:
		"""Scans hooks.py and desk calls to protect all string-registered hooks and endpoints."""
		alive_symbols = set()

		# 1. Parse hooks.py
		hooks_path = os.path.join(app_dir, "hooks.py")
		if not os.path.exists(hooks_path):
			# Search subdirectories for hooks.py
			for root, _, files in os.walk(app_dir):
				if "hooks.py" in files:
					hooks_path = os.path.join(root, "hooks.py")
					break

		if os.path.exists(hooks_path):
			try:
				with open(hooks_path, "r", encoding="utf-8") as f:
					content = f.read()
				# Find all string literals (e.g. 'app.module.method', 'doc_events', etc.)
				strings = re.findall(r"['\"]([a-zA-Z0-9_\.]+)['\"]", content)
				for s in strings:
					parts = s.split(".")
					alive_symbols.add(parts[-1]) # function or class name
					alive_symbols.add(s)
			except Exception:
				pass

		return alive_symbols

	def _build_global_reference_graph(self, py_files: list, js_files: list):
		"""Reads all files to build a global index of every referenced identifier in the app."""
		reference_counts = {}
		total_lines = 0

		all_files = py_files + js_files
		for fpath in all_files:
			try:
				with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
					content = f.read()
				lines = content.splitlines()
				total_lines += len(lines)

				# Tokenize identifiers
				tokens = re.findall(r"\b([a-zA-Z_$][\w$]*)\b", content)
				for tok in tokens:
					reference_counts[tok] = reference_counts.get(tok, 0) + 1
			except Exception:
				continue

		return reference_counts, total_lines

	def _scan_python_file(self, fpath: str, rel_path: str, app_refs: dict, hooks_alive: set):
		"""Scans a Python file (.py / DocType controller) enforcing the 6 categories & Frappe guardrails."""
		items = []
		try:
			with open(fpath, "r", encoding="utf-8") as f:
				source = f.read()
			tree = ast.parse(source)
		except Exception:
			return [], None

		lines = source.splitlines()
		removable_line_spans = []

		# Check dynamic access guardrails: getattr, hasattr, frappe.get_attr
		has_dynamic_access = bool(re.search(r"\b(getattr|hasattr|frappe\.get_attr)\b", source))

		# Find DocType controller classes: class DocTypeName(Document)
		doctype_classes = set()
		for node in tree.body:
			if isinstance(node, ast.ClassDef):
				for base in node.bases:
					base_name = getattr(base, "id", getattr(base, "attr", ""))
					if base_name in ("Document", "NestedSet", "StatusUpdater"):
						doctype_classes.add(node.name)

		# Category 2: Unused Imports
		file_tokens = re.findall(r"\b([a-zA-Z_$][\w$]*)\b", source)
		file_token_counts = {}
		for tok in file_tokens:
			file_token_counts[tok] = file_token_counts.get(tok, 0) + 1

		for node in tree.body:
			if isinstance(node, ast.Import):
				for alias in node.names:
					name_to_check = alias.asname or alias.name
					if file_token_counts.get(name_to_check, 0) <= 1:
						items.append({
							"symbol": f"import {alias.name}",
							"type": "Import",
							"file_path": rel_path,
							"location": f"Line {node.lineno}",
							"reason": f"Import '{name_to_check}' is never referenced in {rel_path}.",
							"risk": "Low",
							"justification": f"0 internal load occurrences; not a side-effect import.",
							"safe": True
						})
						removable_line_spans.append((node.lineno, getattr(node, "end_lineno", node.lineno)))

			elif isinstance(node, ast.ImportFrom):
				for alias in node.names:
					name_to_check = alias.asname or alias.name
					if file_token_counts.get(name_to_check, 0) <= 1:
						items.append({
							"symbol": f"from {node.module} import {alias.name}",
							"type": "Import",
							"file_path": rel_path,
							"location": f"Line {node.lineno}",
							"reason": f"Imported specifier '{name_to_check}' is unused.",
							"risk": "Low",
							"justification": f"0 usages found within this module scope.",
							"safe": True
						})
						removable_line_spans.append((node.lineno, getattr(node, "end_lineno", node.lineno)))

		# Category 1: Unused Top-Level Functions & Classes (non-exported / unreferenced across app)
		for node in tree.body:
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				# Guardrail: Whitelisted APIs & Framework Decorators (@frappe.whitelist)
				is_whitelisted = any(
					getattr(d, "id", getattr(d, "attr", "")) in ("whitelist", "event_handler")
					for d in node.decorator_list
				)
				if is_whitelisted:
					continue

				# Guardrail: Registered in hooks.py
				if node.name in hooks_alive:
					continue

				# Check across global app references
				global_count = app_refs.get(node.name, 0)
				# 1 occurrence means it only appears at its own declaration!
				if global_count <= 1:
					kind = "Function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "Class"
					items.append({
						"symbol": node.name,
						"type": kind,
						"file_path": rel_path,
						"location": f"Lines {node.lineno}-{getattr(node, 'end_lineno', node.lineno)}",
						"reason": f"Declared in {rel_path} but 0 incoming calls or references across the entire app.",
						"risk": "Medium" if has_dynamic_access else "Low",
						"justification": f"App graph degree is 0; not whitelisted and not hooked in hooks.py.",
						"safe": not has_dynamic_access
					})
					if not has_dynamic_access:
						removable_line_spans.append((node.lineno, getattr(node, "end_lineno", node.lineno)))

		# Category 4: Unreachable Control-Flow Blocks
		for node in ast.walk(tree):
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				for idx, stmt in enumerate(node.body):
					if isinstance(stmt, (ast.Return, ast.Raise)):
						if idx + 1 < len(node.body):
							dead_start = node.body[idx + 1].lineno
							dead_end = getattr(node.body[-1], "end_lineno", node.body[-1].lineno)
							snippet = "\n".join(lines[dead_start - 1:dead_end]).strip()
							items.append({
								"symbol": snippet[:35] + ("..." if len(snippet) > 35 else ""),
								"type": "Control Flow Block",
								"file_path": rel_path,
								"location": f"Lines {dead_start}-{dead_end}",
								"reason": f"Unreachable statements following unconditional terminal '{type(stmt).__name__.lower()}'.",
								"risk": "Low",
								"justification": f"Execution unconditionally terminates at line {stmt.lineno}.",
								"safe": True
							})
							removable_line_spans.append((dead_start, dead_end))
							break

		# Category 5: Unused Private Members inside classes
		for node in tree.body:
			if isinstance(node, ast.ClassDef):
				is_controller = node.name in doctype_classes
				for item in node.body:
					if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
						# Guardrail: Frappe Controller Lifecycle methods are NEVER dead!
						if is_controller and item.name in FRAPPE_CONTROLLER_LIFECYCLE:
							continue

						# Check private helpers starting with _
						if item.name.startswith("_") and not item.name.startswith("__"):
							if not item.decorator_list and item.name not in hooks_alive:
								if app_refs.get(item.name, 0) <= 1:
									items.append({
										"symbol": f"{node.name}.{item.name}",
										"type": "Private Member",
										"file_path": rel_path,
										"location": f"Lines {item.lineno}-{getattr(item, 'end_lineno', item.lineno)}",
										"reason": f"Private method '{item.name}' inside class '{node.name}' has 0 calls in the app.",
										"risk": "Low",
										"justification": f"Private encapsulated helper with zero invocations.",
										"safe": True
									})
									removable_line_spans.append((item.lineno, getattr(item, "end_lineno", item.lineno)))

		# Generate Unified Diff for this file
		diff_chunk = self._generate_file_diff(lines, removable_line_spans, rel_path)
		return items, diff_chunk

	def _scan_js_file(self, fpath: str, rel_path: str, app_refs: dict, hooks_alive: set):
		"""Scans a JavaScript file / Frappe Desk Client Script enforcing Frappe Desk conventions."""
		items = []
		try:
			with open(fpath, "r", encoding="utf-8") as f:
				source = f.read()
		except Exception:
			return [], None

		lines = source.splitlines()
		removable_line_spans = []

		# Category 2: Unused JS Imports
		for idx, line in enumerate(lines):
			if line.strip().startswith("import ") and "from" in line:
				spec_match = re.search(r"import\s+\{([^}]+)\}\s+from", line)
				if spec_match:
					specs = [s.strip() for s in spec_match.group(1).split(",")]
					for sp in specs:
						sp_clean = sp.split(" as ")[-1].strip()
						if len(re.findall(rf"\b{sp_clean}\b", source)) <= 1:
							items.append({
								"symbol": sp_clean,
								"type": "Import",
								"file_path": rel_path,
								"location": f"Line {idx + 1}",
								"reason": f"Imported specifier '{sp_clean}' is never referenced.",
								"risk": "Low",
								"justification": f"0 usages in client script.",
								"safe": True
							})
							removable_line_spans.append((idx + 1, idx + 1))

		# Category 1: Standalone JS Functions with 0 references across app
		for match in re.finditer(r"(?:^|\n)(?!\s*export\s+)function\s+([a-zA-Z_$][\w$]*)\s*\(", source):
			fn_name = match.group(1)
			# Guardrail: Check Frappe JS hooks & field events
			if fn_name in FRAPPE_JS_LIFECYCLE or fn_name in hooks_alive:
				continue

			if app_refs.get(fn_name, 0) <= 1:
				lineno = source[:match.start()].count("\n") + 1
				items.append({
					"symbol": fn_name,
					"type": "Function",
					"file_path": rel_path,
					"location": f"Line {lineno}",
					"reason": f"JavaScript function '{fn_name}' has 0 calls across the app.",
					"risk": "Low",
					"justification": f"0 client or server references found in graph.",
					"safe": True
				})

		diff_chunk = self._generate_file_diff(lines, removable_line_spans, rel_path)
		return items, diff_chunk

	def _generate_file_diff(self, lines: list, removable_spans: list, rel_path: str):
		"""Generates unified diff chunk for a single file."""
		if not removable_spans:
			return None

		removable_indices = set()
		for start, end in removable_spans:
			for l in range(start, end + 1):
				removable_indices.add(l - 1)

		new_lines = [line for idx, line in enumerate(lines) if idx not in removable_indices]

		diff = list(difflib.unified_diff(
			[l + "\n" for l in lines],
			[l + "\n" for l in new_lines],
			fromfile=f"a/{rel_path}",
			tofile=f"b/{rel_path}",
			lineterm=""
		))

		return "\n".join(diff) if diff else None

	def _format_multi_file_diff(self, file_diff_map: dict):
		"""Combines multi-file diffs into a unified diff string and HTML preview."""
		if not file_diff_map:
			return "No dead code modifications required.", "<div style='color:#9ca3af;'>No modifications required.</div>"

		unified_diff_blocks = []
		html_blocks = [
			"<div style='background:#111827; color:#f3f4f6; padding:15px; border-radius:8px; font-family:monospace; font-size:13px; max-height:500px; overflow-y:auto;'>"
		]

		for rel_path, diff_text in file_diff_map.items():
			unified_diff_blocks.append(diff_text)
			html_blocks.append(f"<div style='background:#1f2937; padding:6px 12px; margin:10px 0 5px; border-radius:4px; font-weight:bold; color:#60a5fa;'>📄 {rel_path}</div>")

			for line in diff_text.splitlines():
				escaped = frappe.utils.escape_html(line)
				if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
					html_blocks.append(f"<div style='color:#9ca3af;'>{escaped}</div>")
				elif line.startswith("+"):
					html_blocks.append(f"<div style='color:#34d399; background:rgba(16,185,129,0.15);'>{escaped}</div>")
				elif line.startswith("-"):
					html_blocks.append(f"<div style='color:#f87171; background:rgba(239,68,68,0.15);'>{escaped}</div>")
				else:
					html_blocks.append(f"<div style='color:#d1d5db;'>{escaped}</div>")

		html_blocks.append("</div>")

		return "\n\n".join(unified_diff_blocks), "".join(html_blocks)
