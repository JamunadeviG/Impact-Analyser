import ast
import difflib
import html
import os
import re


import frappe
from frappe.model.document import Document
from frappe.utils import now


# Standard Frappe framework lifecycle and controller hooks
FRA_LIFECYCLE_HOOKS = {
	"validate", "before_save", "before_insert", "after_insert",
	"on_submit", "before_submit", "on_cancel", "before_cancel",
	"on_update", "on_update_after_submit", "after_delete", "on_trash",
	"autoname", "before_validate", "before_naming", "on_change",
	"setup", "onload", "get_list", "get_count", "has_permission",
	"get_permission_query_conditions", "before_print", "before_rename",
	"after_rename", "on_load", "get_feed", "get_title", "get_route",
	"check_permission", "run_method", "get_doc", "get_value",
}

FRA_MODULE_LEVEL_HOOKS = {
	"get_context", "get_list_context", "get_index_context",
	"get_permission_query_conditions", "has_website_permission",
	"get_sidebar_items", "get_children",
}

IGNORED_DIRS = {
	".git", "__pycache__", "env", "node_modules", "sites",
	"dist", "build", ".venv", "venv", ".pytest_cache", ".ruff_cache",
}


class DeadCodeEliminator(Document):

	def validate(self):
		if not self.get("title") or self.title == "App Scan":
			app = self.get("target_app") or "impact_analyser"
			self.title = f"Scan: {app} ({now()})"

	@frappe.whitelist()
	def run_analysis(self):
		app_name = (self.get("target_app") or "impact_analyser").strip()
		bench_path = self._get_bench_path()
		app_dir = self._get_app_dir(app_name, bench_path)

		if not os.path.exists(app_dir):
			frappe.throw(f"App directory not found: {app_dir}")

		self.status = "Scanning Entire App"
		self.set("inventory", [])
		self.call_path_justifications = ""

		code_files = self._collect_app_files(app_dir)
		total_files = len(code_files)

		file_contents = {}
		total_lines = 0
		for fpath in code_files:
			try:
				with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
					content = f.read()
					file_contents[fpath] = content
					total_lines += content.count("\n") + 1
			except Exception:
				continue

		hooks_symbols = self._extract_hooks_symbols(app_dir, file_contents)
		json_symbols = self._extract_json_symbols(file_contents)

		self._class_index = self._build_class_index(file_contents)
		ast_cache = self._build_ast_cache(file_contents)

		candidates = []
		for fpath, content in file_contents.items():
			if not fpath.endswith(".py"):
				continue

			rel_path = os.path.relpath(fpath, app_dir).replace("\\", "/")
			file_candidates = self._analyze_python_file(
				fpath=fpath,
				rel_path=rel_path,
				content=content,
				file_contents=file_contents,
				hooks_symbols=hooks_symbols,
				json_symbols=json_symbols,
				ast_cache=ast_cache
			)
			candidates.extend(file_candidates)

		# NOTE: JavaScript scanning intentionally removed — this app only
		# scans .py and .json files now.

		low_cnt = 0
		med_cnt = 0
		high_cnt = 0
		safe_items = []
		review_items = []
		files_to_patch = {}

		for item in candidates:
			risk = item["risk_level"]
			if risk == "Low":
				low_cnt += 1
				safe_items.append(item)
				if item.get("node") is not None:
					files_to_patch.setdefault(item["abs_path"], []).append(item)
			elif risk == "Medium":
				med_cnt += 1
				review_items.append(item)
			else:
				high_cnt += 1
				review_items.append(item)

			self.append("inventory", {
				"symbol_or_block": item["symbol"],
				"symbol_type": item["type"],
				"file_path": item["file_path"],
				"location": f"Line {item['line']}",
				"risk_level": item["risk_level"],
				"reason": item["reason"],
				"call_path_justification": item["justification"],
				"safe_to_eliminate": 1 if item["risk_level"] == "Low" else 0,
			})

		self.total_files_scanned = total_files
		self.total_lines_scanned = total_lines
		self.total_dead_items = len(candidates)
		self.low_risk_count = low_cnt
		self.medium_risk_count = med_cnt
		self.high_risk_count = high_cnt

		unified_diff_text, diff_html = self._generate_diffs(files_to_patch, app_dir)
		self.unified_diff = unified_diff_text
		self.diff_html = diff_html

		self.call_path_justifications = self._generate_report(
			app_name=app_name,
			app_dir=app_dir,
			total_files=total_files,
			total_lines=total_lines,
			safe_items=safe_items,
			review_items=review_items,
		)

		self.status = "Completed"
		if not self.get("title") or self.title == "App Scan":
			self.title = f"Scan: {app_name} ({now()})"

		try:
			if self.is_new():
				self.insert(ignore_permissions=True)
			else:
				self.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			pass

		return {
			"total_files": total_files,
			"total_dead_items": len(candidates),
			"diff_files": len(files_to_patch),
			"safe_to_remove": low_cnt,
			"needs_review": med_cnt + high_cnt,
		}

	def _generate_report(self, app_name, app_dir, total_files, total_lines, safe_items, review_items):
		"""
		Plain, deterministic scan report - grouped by file rather than one
		long flat table, so results for the same file sit together. No AI
		branding: detection is 100% rule-based (AST + naming-convention
		checks), so labelling this as an "AI" report was never accurate.
		"""
		total = len(safe_items) + len(review_items)
		report = []
		report.append(f"# Dead Code Scan — {app_name}\n\n")
		report.append(f"{total_files} files scanned · {total_lines} lines · {total} item(s) found\n\n")

		if total == 0:
			report.append("No dead code candidates found. ✅\n")
			return "".join(report)

		report.append(f"**{len(safe_items)}** safe to remove · **{len(review_items)}** need review\n\n")

		if safe_items:
			report.append(f"## ✅ Safe to Remove ({len(safe_items)})\n\n")
			report.extend(self._render_items_grouped_by_file(safe_items))

		if review_items:
			report.append(f"## ⚠️ Needs Review ({len(review_items)})\n\n")
			report.extend(self._render_items_grouped_by_file(review_items))

		return "".join(report)

	def _render_items_grouped_by_file(self, items):
		lines = []
		by_file = {}
		for item in items:
			by_file.setdefault(item["file_path"], []).append(item)

		for file_path in sorted(by_file):
			lines.append(f"**`{file_path}`**\n\n")
			for item in sorted(by_file[file_path], key=lambda i: i["line"]):
				lines.append(f"- Line {item['line']} — `{item['symbol']}` ({item['type']}, {item['risk_level']} risk)\n")
			lines.append("\n")

		return lines

	def _collect_app_files(self, app_dir):
		# Only .py and .json are scanned. JavaScript and HTML scanning
		# were removed — Python controller/helper dead-code and DocType
		# JSON symbol cross-referencing are the supported scope now.
		valid_files = []
		allowed_exts = {".py", ".json"}

		for root, dirs, files in os.walk(app_dir):
			dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
			for file in files:
				ext = os.path.splitext(file)[1].lower()
				if ext in allowed_exts:
					valid_files.append(os.path.join(root, file))
		return valid_files

	def _extract_hooks_symbols(self, app_dir, file_contents):
		"""
		Parses hooks.py via AST rather than raw-text regex.

		The previous regex approach (`re.findall` over the whole file
		text) matched every quoted string regardless of whether the line
		was commented out — so commenting out a doc_events/scheduler_events
		entry in hooks.py never removed its protection, and the function
		it used to point to stayed hidden from dead-code detection forever.
		ast.parse() never sees comment text at all (comments aren't part
		of the AST), so a commented-out reference now correctly stops
		counting, and the function becomes flaggable again on the next scan.
		"""
		symbols = set()
		for fpath, content in file_contents.items():
			if os.path.basename(fpath) != "hooks.py":
				continue
			try:
				tree = ast.parse(content, filename=fpath)
			except Exception:
				# Fall back to the old regex only if hooks.py fails to
				# parse (e.g. a syntax error mid-edit) - better to over-
				# protect briefly than crash the whole scan.
				matches = re.findall(r"['\"]([a-zA-Z0-9_\.]+)['\"]", content)
				for m in matches:
					symbols.add(m)
					symbols.add(m.split(".")[-1])
				continue

			for node in ast.walk(tree):
				if isinstance(node, ast.Constant) and isinstance(node.value, str):
					symbols.add(node.value)
					symbols.add(node.value.split(".")[-1])
		return symbols

	def _extract_json_symbols(self, file_contents):
		symbols_by_dir = {}
		for fpath, content in file_contents.items():
			if fpath.endswith(".json"):
				matches = re.findall(r"['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]", content)
				directory = os.path.dirname(fpath)
				symbols_by_dir.setdefault(directory, set()).update(matches)
		return symbols_by_dir

	def _analyze_python_file(self, fpath, rel_path, content, file_contents, hooks_symbols, json_symbols, ast_cache):
		candidates = []
		is_test = "test" in rel_path.lower()
		is_patch = "patches" in rel_path.lower()

		# Test files (test_*.py, IntegrationTest classes, etc.) are always
		# skipped entirely — Frappe/pytest discover their contents purely
		# by naming convention, so a reference-count check there can never
		# produce a meaningful result, only guaranteed noise. No toggle for
		# this; it's a structural exclusion, not a preference.
		if is_test:
			return []

		tree = ast_cache.get(fpath)
		if tree is None:
			return []

		local_json_symbols = json_symbols.get(os.path.dirname(fpath), set())

		scan_controller_methods = bool(self.get("scan_custom_controller_methods", 1))
		scan_helpers = bool(self.get("scan_standalone_helpers", 1))
		ignore_patches = bool(self.get("ignore_migration_patches", 1))

		for node in tree.body:
			if isinstance(node, ast.ClassDef):
				is_doc = self._is_doctype_controller(node, rel_path)

				# Doctype controller classes are loaded by Frappe purely
				# by file-naming convention - never by a literal Python
				# reference anywhere in the app. A reference-count check
				# on the class name itself is therefore a guaranteed
				# false positive, 100% of the time, regardless of any
				# checkbox - this isn't a preference, it's structural.
				if not is_doc:
					occurrences = self._count_symbol_references(node.name, file_contents, ast_cache)
					if occurrences == 0 and node.name not in hooks_symbols and node.name not in local_json_symbols:
						candidates.append({
							"symbol": node.name,
							"type": "Class",
							"file_path": rel_path,
							"abs_path": fpath,
							"line": node.lineno,
							"risk_level": "Medium",
							"reason": f"Class '{node.name}' has 0 references in Python, JS, or DocType JSON.",
							"justification": "No references found in app graph. Verify if instantiated via dynamic reflection.",
							"node": node
						})

				if scan_controller_methods:
					for subnode in node.body:
						if isinstance(subnode, ast.FunctionDef):
							mname = subnode.name
							if mname.startswith("__") or mname in FRA_LIFECYCLE_HOOKS:
								continue
							if self._is_whitelisted(subnode):
								continue

							occurrences = self._count_symbol_references(mname, file_contents, ast_cache)
							if occurrences == 0 and mname not in hooks_symbols and mname not in local_json_symbols:
								risk = "Low" if mname.startswith("_") else "Medium"
								candidates.append({
									"symbol": f"{node.name}.{mname}",
									"type": "Function",
									"file_path": rel_path,
									"abs_path": fpath,
									"line": subnode.lineno,
									"risk_level": risk,
									"reason": f"Method '{mname}' in class '{node.name}' is never called by any DocType, script, or hook.",
									"justification": "Custom controller method with 0 call paths in app graph.",
									"node": subnode
								})

			elif isinstance(node, ast.FunctionDef):
				fname_str = node.name
				if fname_str.startswith("__"):
					continue
				if fname_str in FRA_MODULE_LEVEL_HOOKS:
					continue
				if is_patch and ignore_patches and fname_str == "execute":
					continue
				if self._is_whitelisted(node):
					continue
				if fname_str in hooks_symbols or fname_str in local_json_symbols:
					continue

				if scan_helpers:
					occurrences = self._count_symbol_references(fname_str, file_contents, ast_cache)
					if occurrences == 0:
						risk = "Low" if fname_str.startswith("_") else "Medium"
						candidates.append({
							"symbol": fname_str,
							"type": "Function",
							"file_path": rel_path,
							"abs_path": fpath,
							"line": node.lineno,
							"risk_level": risk,
							"reason": f"Function '{fname_str}' is defined but never invoked across the entire app.",
							"justification": "Standalone helper with 0 call paths in any file.",
							"node": node
						})

		return candidates

	def _build_class_index(self, file_contents):
		index = {}
		for fpath, content in file_contents.items():
			if not fpath.endswith(".py"):
				continue
			try:
				tree = ast.parse(content, filename=fpath)
			except Exception:
				continue
			for node in ast.walk(tree):
				if isinstance(node, ast.ClassDef) and node.name not in index:
					index[node.name] = node
		return index

	def _is_doctype_controller(self, node, rel_path):
		if self._inherits_document(node):
			return True

		parts = rel_path.split("/")
		if len(parts) >= 3:
			grandparent, folder, filename = parts[-3], parts[-2], parts[-1]
			if grandparent == "doctype" and filename == f"{folder}.py":
				return True

		return False

	def _inherits_document(self, node, _visited=None):
		if _visited is None:
			_visited = set()

		for b in node.bases:
			base_name = None
			if isinstance(b, ast.Name):
				base_name = b.id
			elif isinstance(b, ast.Attribute):
				base_name = b.attr

			if not base_name or base_name in _visited:
				continue
			if base_name == "Document":
				return True
			_visited.add(base_name)

			base_node = getattr(self, "_class_index", {}).get(base_name)
			if base_node and self._inherits_document(base_node, _visited):
				return True

		return False

	def _build_ast_cache(self, file_contents):
		cache = {}
		for fpath, content in file_contents.items():
			if not fpath.endswith(".py"):
				continue
			try:
				cache[fpath] = ast.parse(content, filename=fpath)
			except Exception:
				continue
		return cache

	def _count_symbol_references(self, name, file_contents, ast_cache):
		count = 0
		for tree in ast_cache.values():
			for node in ast.walk(tree):
				if isinstance(node, ast.Name) and node.id == name:
					count += 1
				elif isinstance(node, ast.Attribute) and node.attr == name:
					count += 1
				if count > 5:
					return count

		quoted_pattern = re.compile(rf"""['"]{re.escape(name)}['"]""")
		for fpath, content in file_contents.items():
			if fpath.endswith(".py"):
				continue
			count += len(quoted_pattern.findall(content))
			if count > 5:
				break

		return count

	def _is_whitelisted(self, node):
		for dec in node.decorator_list:
			if isinstance(dec, ast.Attribute) and dec.attr == "whitelist":
				return True
			if isinstance(dec, ast.Name) and dec.id == "whitelist":
				return True
			if isinstance(dec, ast.Call):
				if isinstance(dec.func, ast.Attribute) and dec.func.attr == "whitelist":
					return True
				if isinstance(dec.func, ast.Name) and dec.func.id == "whitelist":
					return True
		return False

	def _generate_diffs(self, files_to_patch, app_dir):
		unified_diffs = []
		html_diff_blocks = []

		for fpath, items in files_to_patch.items():
			try:
				with open(fpath, "r", encoding="utf-8") as f:
					orig_lines = f.readlines()
			except Exception:
				continue

			lines_to_remove = set()
			for item in items:
				node = item.get("node")
				if node:
					end_lineno = getattr(node, "end_lineno", node.lineno)
					for l in range(node.lineno, end_lineno + 1):
						lines_to_remove.add(l)

			new_lines = [line for idx, line in enumerate(orig_lines, start=1) if idx not in lines_to_remove]

			rel = os.path.relpath(fpath, app_dir).replace("\\", "/")
			diff = list(difflib.unified_diff(
				orig_lines, new_lines,
				fromfile=f"a/{rel}",
				tofile=f"b/{rel}"
			))

			if diff:
				diff_str = "".join(diff)
				unified_diffs.append(diff_str)

				html_rows = []
				for line in diff:
					escaped = html.escape(line.rstrip())
					if line.startswith("+") and not line.startswith("+++"):
						html_rows.append(f"<div style='background-color:#e6ffec;color:#1e4620;font-family:monospace;padding:1px 4px;'>{escaped}</div>")
					elif line.startswith("-") and not line.startswith("---"):
						html_rows.append(f"<div style='background-color:#ffebe9;color:#b31d28;font-family:monospace;padding:1px 4px;'>{escaped}</div>")
					elif line.startswith("@@"):
						html_rows.append(f"<div style='background-color:#f1f8ff;color:#0366d6;font-family:monospace;padding:1px 4px;font-weight:bold;'>{escaped}</div>")
					else:
						html_rows.append(f"<div style='color:#555;font-family:monospace;padding:1px 4px;'>{escaped}</div>")

				block = (
					f"<div style='margin-bottom:16px;border:1px solid #d0d7de;border-radius:6px;overflow:hidden;'>"
					f"<div style='background:#f6f8fa;padding:8px 12px;font-weight:bold;font-size:13px;border-bottom:1px solid #d0d7de;'>📄 {rel}</div>"
					f"<div style='padding:8px;font-size:12px;background:#fff;max-height:300px;overflow-y:auto;'>"
					+ "".join(html_rows) +
					f"</div></div>"
				)
				html_diff_blocks.append(block)

		unified_text = "\n".join(unified_diffs)
		diff_html = "".join(html_diff_blocks) if html_diff_blocks else "<p style='color:#666;'>No safe eliminations to display.</p>"
		return unified_text, diff_html

	def _get_bench_path(self):
		try:
			return frappe.get_bench_path()
		except Exception:
			pass
		try:
			import frappe as _f
			p = os.path.abspath(os.path.dirname(_f.__file__))
			for _ in range(8):
				p = os.path.dirname(p)
				if os.path.isdir(os.path.join(p, "apps")):
					return p
		except Exception:
			pass
		return "/home/raj/aeroplane_app"

	def _get_app_dir(self, app_name, bench_path):
		custom_path = self.get("app_path")
		if custom_path and os.path.isdir(custom_path):
			if os.path.isdir(os.path.join(custom_path, "apps", app_name)):
				return os.path.join(custom_path, "apps", app_name)
			return custom_path

		try:
			p = frappe.get_app_path(app_name)
			parent = os.path.dirname(p)
			if os.path.basename(parent) == app_name and os.path.isdir(parent):
				return parent
			if os.path.isdir(p):
				return p
		except Exception:
			pass

		for c in (os.path.join(bench_path, "apps", app_name), os.path.join(bench_path, app_name)):
			if os.path.isdir(c):
				return c
		return os.path.join(bench_path, "apps", app_name)
