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


	@frappe.whitelist(allow_guest=False)
	def create_and_run_scan(
		self,
		target_app,
		app_path=None,
		scan_custom_controller_methods=1,
		scan_standalone_helpers=1,
	):
		"""
		Whitelisted method callable from the web UI to create a new Dead Code
		Eliminator document (with the user-supplied options) and immediately
		run the full analysis.  Returns the scan name and summary statistics
		so the browser can redirect straight to the results view.
		"""
		if frappe.session.user == "Guest":
			frappe.throw(frappe._("You must be logged in to run a scan."), frappe.PermissionError)

		doc = frappe.new_doc("Dead Code Eliminator")
		doc.target_app = (target_app or "").strip()
		if not doc.target_app:
			frappe.throw(frappe._("Target Frappe App is required."))
		doc.app_path = (app_path or "").strip() or None
		doc.scan_custom_controller_methods = int(scan_custom_controller_methods)
		doc.scan_standalone_helpers = int(scan_standalone_helpers)
		doc.status = "Draft"

		# insert first so the doc has a name before running analysis
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		result = doc.run_analysis()

		return {
			"scan_name": doc.name,
			"result": result,
		}
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
		dynamic_dispatch_symbols = self._extract_dynamic_dispatch_symbols(ast_cache)

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
				ast_cache=ast_cache,
				dynamic_dispatch_symbols=dynamic_dispatch_symbols
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

	def _analyze_python_file(self, fpath, rel_path, content, file_contents, hooks_symbols, json_symbols, ast_cache, dynamic_dispatch_symbols=None):
		candidates = []
		dynamic_dispatch_symbols = dynamic_dispatch_symbols or set()
		is_test = "test" in rel_path.lower()
		is_patch = "patches" in rel_path.lower()
		is_report_script = self._is_report_script(rel_path)

		# Report scripts, Workspaces, and Print Formats are all dispatched
		# by Frappe purely through directory/name convention or dynamic
		# getattr/hook lookups (report execute(), workspace onboarding
		# content, print format Jinja context) - never through a literal
		# Python reference. Rather than chase every dispatch shape
		# individually, these folders are excluded from scanning outright.
		path_parts = {p.lower() for p in rel_path.split("/")}
		is_excluded_module = bool(path_parts & {"report", "workspace", "print_format"})
		if is_test or is_excluded_module:
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
					if (occurrences == 0 and node.name not in hooks_symbols
						and node.name not in local_json_symbols
						and node.name not in dynamic_dispatch_symbols):
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
							if self._is_property(subnode):
								continue
							if mname in dynamic_dispatch_symbols:
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
				if is_report_script and fname_str == "execute":
					continue
				if self._is_whitelisted(node):
					continue
				if fname_str in hooks_symbols or fname_str in local_json_symbols:
					continue
				if fname_str in dynamic_dispatch_symbols:
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

	def _is_report_script(self, rel_path):
		"""
		Report script files (<module>/report/<name>/<name>.py) follow the
		same directory-based Frappe convention as DocType controllers:
		the file's `execute(filters)` function is looked up and invoked
		dynamically by the report engine via
		`frappe.get_attr(dotted_path + ".execute")` — never referenced by
		a literal Python call anywhere in the app. A "0 occurrences"
		result on `execute` in one of these files is therefore a
		guaranteed false positive, the same structural category as
		DocType controllers, hooks.py entries, and @property methods.
		"""
		parts = rel_path.split("/")
		if len(parts) >= 3:
			grandparent, folder, filename = parts[-3], parts[-2], parts[-1]
			if grandparent == "report" and filename == f"{folder}.py":
				return True
		return False

	def _extract_dynamic_dispatch_symbols(self, ast_cache):
		"""
		Finds dynamic-by-name call sites across the whole app and protects
		the target name from the dead-code check. Covers two shapes:

		  1. getattr(obj, "literal_name") — the builtin two-arg form.
		  2. frappe.get_attr(dotted_path) — Frappe's own report/hook
		     dispatch mechanism (this is literally how the report engine
		     calls a report's `execute`: `frappe.get_attr(dotted_path +
		     ".execute")`; app-specific dispatch, e.g. an alternate report
		     entry point toggled by a checkbox, commonly mirrors this same
		     convention). The dotted path is frequently *built* rather
		     than a single literal — `prefix + ".execute_variant"` or
		     f"{prefix}.execute_variant" — so simple '+' concatenation and
		     f-string literal segments are resolved too; only the trailing
		     dotted segment is taken as the symbol name.

		Either way, the target is a string, not an attribute/name
		reference, so it's invisible to `_count_symbol_references` for the
		same structural reason DocType controllers, hooks.py entries, and
		@property methods are: the app graph calls it, but no code spells
		its name as a direct Python reference. A name assembled from a
		non-literal part at runtime (e.g. a variable holding the whole
		suffix) still can't be resolved statically — known limitation.
		"""
		symbols = set()

		def add_from_string(s):
			if not isinstance(s, str) or not s:
				return
			tail = s.rsplit(".", 1)[-1].strip(". ")
			if tail:
				symbols.add(tail)

		def literal_fragments(node):
			"""Pull out literal string pieces from a plain string, simple
			'+' concatenation, or an f-string — enough to resolve the
			trailing dotted segment even when the prefix is dynamic."""
			frags = []
			if isinstance(node, ast.Constant) and isinstance(node.value, str):
				frags.append(node.value)
			elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
				frags.extend(literal_fragments(node.left))
				frags.extend(literal_fragments(node.right))
			elif isinstance(node, ast.JoinedStr):
				for value in node.values:
					if isinstance(value, ast.Constant) and isinstance(value.value, str):
						frags.append(value.value)
			return frags

		for tree in ast_cache.values():
			for node in ast.walk(tree):
				if not isinstance(node, ast.Call):
					continue
				func = node.func
				is_getattr = (
					(isinstance(func, ast.Name) and func.id == "getattr")
					or (isinstance(func, ast.Attribute) and func.attr == "getattr")
				)
				is_frappe_get_attr = isinstance(func, ast.Attribute) and func.attr == "get_attr"

				if is_getattr and len(node.args) >= 2:
					for frag in literal_fragments(node.args[1]):
						add_from_string(frag)
				elif is_frappe_get_attr and len(node.args) >= 1:
					for frag in literal_fragments(node.args[0]):
						add_from_string(frag)

		return symbols

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

	def _is_property(self, node):
		"""
		Excludes @property (and @cached_property, and the matching
		@X.setter/@X.deleter/@X.getter re-definitions) from the
		controller-method dead-code check.

		These methods are invoked via attribute access (`doc.full_address`),
		never via a `()` call, so:
		  - Jinja/print-format template access (`{{ doc.full_address }}`)
		    leaves no Python AST trace at all.
		  - If the property backs a DocType `is_virtual` field, Frappe
		    calls it internally via `getattr(doc, fieldname)` — again
		    invisible to a Python reference scan.
		A "0 occurrences" result on one of these is therefore a
		guaranteed false positive, the same structural category as
		DocType controller classes and hooks.py entries — not something
		a reference count can ever resolve.
		"""
		for dec in node.decorator_list:
			if isinstance(dec, ast.Name) and dec.id in ("property", "cached_property"):
				return True
			if isinstance(dec, ast.Attribute) and dec.attr in ("setter", "deleter", "getter", "cached_property"):
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


@frappe.whitelist()
def create_and_run_scan_api(target_app, app_path=None, scan_custom_controller_methods=1, scan_standalone_helpers=1):
	"""
	Module-level whitelisted function callable from the web UI via frappe.call().
	Creates a new Dead Code Eliminator document with the supplied options and
	immediately runs the full analysis.  Returns the scan name so the browser
	can redirect straight to the results view.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("You must be logged in to run a scan."), frappe.PermissionError)

	doc = frappe.new_doc("Dead Code Eliminator")
	doc.target_app = (target_app or "").strip()
	if not doc.target_app:
		frappe.throw(frappe._("Target Frappe App is required."))
	doc.app_path = (app_path or "").strip() or None
	doc.scan_custom_controller_methods = int(scan_custom_controller_methods)
	doc.scan_standalone_helpers = int(scan_standalone_helpers)
	doc.status = "Draft"

	# Insert first so the doc has a name before running analysis
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	result = doc.run_analysis()

	return {
		"scan_name": doc.name,
		"result": result,
	}
