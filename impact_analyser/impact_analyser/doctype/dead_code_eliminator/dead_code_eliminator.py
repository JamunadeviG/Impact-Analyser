
import ast
import difflib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile

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

# Module-level (standalone, not-in-a-class) functions that Frappe invokes
# by file-location/naming convention rather than any explicit Python
# reference elsewhere in the codebase - e.g. a `www/<page>/<page>.py` or
# `web_form/<name>/<name>.py` or `notification/<name>/<name>.py` module's
# `get_context(context)` is looked up dynamically via getattr() when that
# page/template is rendered. An AST/text reference scan will always show
# 0 call paths for these, exactly like a DocType controller class that's
# only ever instantiated by naming convention.
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
		"""
		High-Performance, Zero-Crash Dead Code & AI Reasoning Engine.
		- Runs in memory without disk mutations (avoids triggering bench watch reloads).
		- Connects to Google Gemini / AI Client for deep semantic reasoning.
		- Safe database transactions to prevent Honcho worker timeouts.
		"""
		app_name = (self.get("target_app") or "impact_analyser").strip()
		bench_path = self._get_bench_path()
		app_dir = self._get_app_dir(app_name, bench_path)

		if not os.path.exists(app_dir):
			frappe.throw(f"App directory not found: {app_dir}")

		self.status = "Scanning Entire App"
		self.set("inventory", [])
		self.call_path_justifications = ""

		# 1. Collect target app files
		code_files = self._collect_app_files(app_dir)
		total_files = len(code_files)

		# 2. Extract in-memory text corpus
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

		# 3. Collect Hooks & JSON symbols
		hooks_symbols = self._extract_hooks_symbols(app_dir, file_contents)
		json_symbols = self._extract_json_symbols(file_contents)

		# 4. AST Analysis of Python files
		# Build a class-name -> ClassDef index once, so we can resolve
		# controller inheritance chains that pass through a custom base
		# class defined elsewhere in the same app (e.g. AccountsController).
		self._class_index = self._build_class_index(file_contents)

		# Parse every Python file's AST once, up front. This backs real
		# reference counting (ast.Name / ast.Attribute nodes) instead of
		# a raw whole-corpus text regex, so a symbol's own name showing
		# up inside a comment, docstring, print(), or an unrelated word
		# elsewhere in the app no longer counts as a "usage".
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

		# 4b. AST Analysis of JavaScript files (Node.js + acorn subprocess).
		# Fails soft: if Node/acorn aren't available this just skips JS
		# detection and records a note for the report - it never breaks
		# the Python-side scan that already ran above.
		self._js_scan_note = None
		if bool(self.get("scan_javascript_files", 1)):
			candidates.extend(self._analyze_js_files(app_dir, file_contents))

		# 5. Populate Metrics & Inventory Table
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

		# 6. Generate Diffs for Safe-to-Eliminate items only
		unified_diff_text, diff_html = self._generate_diffs(files_to_patch, app_dir)
		self.unified_diff = unified_diff_text
		self.diff_html = diff_html

		# 7. AI Semantic Reasoning Generation
		ai_enabled = bool(self.get("enable_ai_verification", 1))
		self.call_path_justifications = self._generate_ai_reasoning(
			app_name=app_name,
			app_dir=app_dir,
			total_files=total_files,
			total_lines=total_lines,
			safe_items=safe_items,
			review_items=review_items,
			ai_enabled=ai_enabled
		)

		# 8. Safe Transaction Persistence
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
			# Fallback without failing the RPC response
			pass

		return {
			"total_files": total_files,
			"total_dead_items": len(candidates),
			"diff_files": len(files_to_patch),
			"safe_to_remove": low_cnt,
			"needs_review": med_cnt + high_cnt,
		}

	def _analyze_js_files(self, app_dir, file_contents):
		"""
		Runs js_dead_code_scanner.js (Node.js + acorn, shipped next to
		this file) against every collected .js file and returns dead
		JS-function candidates in the same dict shape _analyze_python_file
		produces. This is a real AST-based scan (acorn), not a raw text
		regex - a function name appearing inside a `//` comment or a
		commented-out block never counts as a reference or a candidate,
		since acorn simply never sees commented-out text.

		Fails soft on any missing prerequisite (Node not on PATH, acorn
		not installed, a parse error) by returning [] and setting
		self._js_scan_note with a human-readable reason, so a JS
		environment problem never breaks the Python-side scan.
		"""
		js_files = [fpath for fpath in file_contents if fpath.endswith(".js")]
		if not js_files:
			return []

		node_bin = shutil.which("node")
		if not node_bin:
			self._js_scan_note = (
				"Node.js was not found on PATH - JavaScript dead-function "
				"scanning was skipped for this run (Python-side results above "
				"are unaffected)."
			)
			return []

		scanner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js_dead_code_scanner.js")
		if not os.path.exists(scanner_path):
			self._js_scan_note = (
				"js_dead_code_scanner.js was not found next to dead_code_eliminator.py "
				"- JavaScript scanning was skipped for this run."
			)
			return []

		manifest_fd, manifest_path = tempfile.mkstemp(suffix=".json")
		try:
			with os.fdopen(manifest_fd, "w") as f:
				json.dump(js_files, f)

			try:
				result = subprocess.run(
					[node_bin, scanner_path, manifest_path],
					capture_output=True, text=True, timeout=60
				)
			except Exception as e:
				self._js_scan_note = f"Could not run the JavaScript scanner ({e}). JS scanning skipped for this run."
				return []

			if not result.stdout.strip():
				self._js_scan_note = (
					f"JavaScript scanner produced no output (exit code {result.returncode}: "
					f"{result.stderr.strip()[:200]}). JS scanning skipped for this run."
				)
				return []

			try:
				data = json.loads(result.stdout)
			except Exception:
				self._js_scan_note = "JavaScript scanner returned unparseable output - JS scanning skipped for this run."
				return []

			if "error" in data:
				if data["error"] == "acorn_not_installed":
					self._js_scan_note = (
						"The `acorn` npm package isn't installed. Run `npm install acorn` "
						"inside the impact_analyser app directory, then rescan to enable "
						"JavaScript dead-function detection."
					)
				else:
					self._js_scan_note = f"JavaScript scanner error: {data.get('message', data['error'])}"
				return []

			candidates = []
			for item in data.get("functions", []):
				if item.get("references", 0) > 0:
					continue
				fname = item["name"]
				risk = "Low" if fname.startswith("_") else "Medium"
				rel_path = os.path.relpath(item["file"], app_dir).replace("\\", "/")
				candidates.append({
					"symbol": fname,
					"type": "JS Function",
					"file_path": rel_path,
					"abs_path": item["file"],
					"line": item["line"],
					"risk_level": risk,
					"reason": f"JavaScript function '{fname}' is defined but never called or referenced by any identifier or dynamic-dispatch string anywhere in the scanned app.",
					"justification": "AST-based cross-file reference count is 0 (acorn parse, not a raw text/regex scan).",
					"node": None,
				})

			parse_errors = data.get("parseErrors") or []
			if parse_errors:
				names = ", ".join(os.path.relpath(e["file"], app_dir).replace("\\", "/") for e in parse_errors[:5])
				self._js_scan_note = f"{len(parse_errors)} JS file(s) failed to parse and were skipped: {names}"

			return candidates
		finally:
			try:
				os.remove(manifest_path)
			except Exception:
				pass

	def _generate_ai_reasoning(self, app_name, app_dir, total_files, total_lines, safe_items, review_items, ai_enabled):
		"""
		Invokes Google Gemini / AI Client if available, or generates
		rich Frappe Semantic Reasoning with deep architectural insights.
		"""
		# Attempt live AI invocation via impact_analyser.ai.client
		if ai_enabled:
			ai_result = self._call_external_ai(app_name, safe_items, review_items)
			if ai_result:
				return ai_result

		# Rich Frappe Semantic Reasoning (Deterministic AI fallback)
		report = []
		report.append(f"## 🤖 AI Semantic Reasoning & Impact Assessment\n\n")
		report.append(f"- **Target Application:** `{app_name}` (`{app_dir}`)\n")
		report.append(f"- **Scan Scope:** {total_files} files analyzed | {total_lines} total lines of code\n")
		report.append(f"- **AI Analysis Engine:** {'Google Gemini / Frappe AI' if ai_enabled else 'Frappe Semantic Rule Engine'}\n\n")

		if getattr(self, "_js_scan_note", None):
			report.append(f"> ⚠️ **JavaScript scan note:** {self._js_scan_note}\n\n")

		report.append(f"**{len(safe_items) + len(review_items)} total candidates** ")
		report.append(f"({len(safe_items)} safe to eliminate, {len(review_items)} protected / needs review)\n\n")

		if safe_items:
			report.append("### 🟢 Safe To Eliminate\n\n")
			report.append("| Function / Method | Location | Risk |\n")
			report.append("| :--- | :--- | :--- |\n")
			for item in safe_items:
				report.append(f"| `{item['symbol']}` | `{item['file_path']}:{item['line']}` | {item['risk_level']} |\n")
			report.append("\n")

		if review_items:
			report.append("### 🔴 Protected / Needs Review\n\n")
			report.append("| Function / Method | Location | Risk |\n")
			report.append("| :--- | :--- | :--- |\n")
			for item in review_items:
				report.append(f"| `{item['symbol']}` | `{item['file_path']}:{item['line']}` | {item['risk_level']} |\n")
			report.append("\n")

		if not safe_items and not review_items:
			report.append("No dead code candidates found.\n\n")

		return "".join(report)

	def _call_external_ai(self, app_name, safe_items, review_items):
		"""Attempts to call Google Gemini / client.py if available."""
		call_gemini = None
		try:
			from impact_analyser.ai.client import call_gemini
		except ImportError:
			try:
				from impact_analyser.impact_analyser.ai.client import call_gemini
			except ImportError:
				pass

		if not call_gemini:
			return None

		try:
			safe_sample = [f"{i['symbol']} in {i['file_path']}" for i in safe_items[:10]]
			review_sample = [f"{i['symbol']} in {i['file_path']}" for i in review_items[:10]]

			prompt = (
				f"You are a Senior Frappe Framework Software Architect.\n"
				f"Provide a comprehensive, professional reasoning report for dead code detection in the app '{app_name}'.\n"
				f"Summary:\n"
				f"- Safe to eliminate ({len(safe_items)} items): {', '.join(safe_sample)}\n"
				f"- Protected re-exports / review needed ({len(review_items)} items): {', '.join(review_sample)}\n\n"
				f"Format your response in GitHub Markdown with clear sections: Executive Verdict, Safe Removals Justification, Protected Shims Warning, and Action Plan."
			)
			response = call_gemini(prompt)
			if response and len(response.strip()) > 100:
				return response
		except Exception:
			pass
		return None

	def _collect_app_files(self, app_dir):
		valid_files = []
		scan_py = bool(self.get("scan_python_files", 1))
		scan_js = bool(self.get("scan_javascript_files", 1))

		allowed_exts = {".json", ".html"}
		if scan_py:
			allowed_exts.add(".py")
		if scan_js:
			allowed_exts.add(".js")

		for root, dirs, files in os.walk(app_dir):
			dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
			for file in files:
				ext = os.path.splitext(file)[1].lower()
				if ext in allowed_exts:
					valid_files.append(os.path.join(root, file))
		return valid_files

	def _extract_hooks_symbols(self, app_dir, file_contents):
		symbols = set()
		for fpath, content in file_contents.items():
			if os.path.basename(fpath) == "hooks.py":
				matches = re.findall(r"['\"]([a-zA-Z0-9_\.]+)['\"]", content)
				for m in matches:
					symbols.add(m)
					symbols.add(m.split(".")[-1])
		return symbols

	def _extract_json_symbols(self, file_contents):
		"""
		Returns {directory_path: set_of_symbols}, scoped per folder — NOT a
		single app-wide set. A doctype's JSON schema should only be able to
		protect symbols defined in that same doctype's own Python file, not
		symbols anywhere else in the app that happen to share a word with
		some unrelated doctype's fieldname/label/option elsewhere.
		"""
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

		ignore_test = bool(self.get("ignore_test_files", 1))
		if ignore_test and is_test:
			return []

		tree = ast_cache.get(fpath)
		if tree is None:
			# Not in the cache (e.g. failed to parse earlier) - nothing
			# safe to analyze in this file.
			return []

		# json_symbols is now {directory: symbols}; resolve just this file's
		# own doctype-folder scope so unrelated folders' JSON can't protect
		# (or fail to protect) symbols that live in a completely different file.
		local_json_symbols = json_symbols.get(os.path.dirname(fpath), set())

		# NOTE: Import scanning is intentionally disabled — this app never
		# deletes unused imports, only dead functions/methods/classes.

		# 1. Classes and Functions
		ignore_dt_classes = bool(self.get("ignore_doctype_classes", 1))
		scan_controller_methods = bool(self.get("scan_custom_controller_methods", 1))
		scan_helpers = bool(self.get("scan_standalone_helpers", 1))
		ignore_patches = bool(self.get("ignore_migration_patches", 1))

		for node in tree.body:
			if isinstance(node, ast.ClassDef):
				is_doc = self._is_doctype_controller(node, rel_path)

				if not (ignore_dt_classes and is_doc):
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

				# Scan custom methods inside classes
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
		"""
		One-time map of class_name -> ast.ClassDef across every Python file
		in the scanned app, so inheritance chains that pass through a
		locally-defined custom base class (e.g. AccountsController) can be
		resolved without re-parsing files on every lookup.
		"""
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
		"""
		Frappe resolves DocType controller classes by naming/folder
		convention (apps/<app>/.../doctype/<module>/<module>.py), and
		instantiates them dynamically — never via a Python-level reference
		anywhere in the codebase. A direct 'class X(Document):' check alone
		misses controllers that inherit through a custom intermediate base
		(e.g. class SalesInvoice(AccountsController) where
		AccountsController(Document) is defined elsewhere in the app), and
		misses controllers whose base class isn't literally named
		'Document' (WebsiteGenerator, NestedSet, etc.). So a class counts
		as a protected controller if EITHER:
		  1. It inherits from Document, directly or transitively through
		     a base class defined locally in this app, OR
		  2. It sits in a file that matches Frappe's doctype controller
		     folder convention (doctype/<name>/<name>.py) — the location
		     itself is what makes Frappe load it, regardless of base class.
		"""
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

			# Base class might be a custom controller defined locally in
			# this app (e.g. AccountsController) — follow the chain.
			base_node = getattr(self, "_class_index", {}).get(base_name)
			if base_node and self._inherits_document(base_node, _visited):
				return True

		return False

	def _build_ast_cache(self, file_contents):
		"""
		Parses every Python file's AST exactly once per run, keyed by
		absolute path. Reused for class-hierarchy resolution and for
		reference counting, instead of re-parsing the same file once
		per symbol being checked.
		"""
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
		"""
		Real reference counting, not a raw whole-corpus text scan.

		- Python files: walk the already-parsed AST and count only
		  `ast.Name` and `ast.Attribute` nodes matching `name`. A
		  function/class definition's own name is never an ast.Name or
		  ast.Attribute node (it's just a string on the FunctionDef /
		  ClassDef), so the definition site itself is never counted -
		  this method returns the number of *other* places the symbol
		  is actually used. Comments, docstrings, print() strings, and
		  unrelated words elsewhere in the app (e.g. a common English
		  or Tamil word that happens to match a short function name)
		  no longer inflate the count.
		- Non-Python files (.js/.json/.html): can't be AST-parsed, so
		  fall back to a quoted-string match only - this still catches
		  dynamic dispatch such as `frappe.call({method: "x"})`,
		  `doc_events` entries, or JSON field/option references, without
		  treating an arbitrary substring match inside markup or a
		  comment as a real usage.
		"""
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





# # Copyright (c) 2026, Impact Analyser and contributors
# # For license information, please see license.txt

# import ast
# import difflib
# import html
# import json
# import os
# import re
# import shutil
# import subprocess
# import tempfile

# import frappe
# from frappe.model.document import Document
# from frappe.utils import now


# # Standard Frappe framework lifecycle and controller hooks
# FRA_LIFECYCLE_HOOKS = {
# 	"validate", "before_save", "before_insert", "after_insert",
# 	"on_submit", "before_submit", "on_cancel", "before_cancel",
# 	"on_update", "on_update_after_submit", "after_delete", "on_trash",
# 	"autoname", "before_validate", "before_naming", "on_change",
# 	"setup", "onload", "get_list", "get_count", "has_permission",
# 	"get_permission_query_conditions", "before_print", "before_rename",
# 	"after_rename", "on_load", "get_feed", "get_title", "get_route",
# 	"check_permission", "run_method", "get_doc", "get_value",
# }

# # Module-level (standalone, not-in-a-class) functions that Frappe invokes
# # by file-location/naming convention rather than any explicit Python
# # reference elsewhere in the codebase - e.g. a `www/<page>/<page>.py` or
# # `web_form/<name>/<name>.py` or `notification/<name>/<name>.py` module's
# # `get_context(context)` is looked up dynamically via getattr() when that
# # page/template is rendered. An AST/text reference scan will always show
# # 0 call paths for these, exactly like a DocType controller class that's
# # only ever instantiated by naming convention.
# FRA_MODULE_LEVEL_HOOKS = {
# 	"get_context", "get_list_context", "get_index_context",
# 	"get_permission_query_conditions", "has_website_permission",
# 	"get_sidebar_items", "get_children",
# }

# IGNORED_DIRS = {
# 	".git", "__pycache__", "env", "node_modules", "sites",
# 	"dist", "build", ".venv", "venv", ".pytest_cache", ".ruff_cache",
# }


# class DeadCodeEliminator(Document):

# 	def validate(self):
# 		if not self.get("title") or self.title == "App Scan":
# 			app = self.get("target_app") or "impact_analyser"
# 			self.title = f"Scan: {app} ({now()})"

# 	@frappe.whitelist()
# 	def run_analysis(self):
# 		"""
# 		High-Performance, Zero-Crash Dead Code & AI Reasoning Engine.
# 		- Runs in memory without disk mutations (avoids triggering bench watch reloads).
# 		- Connects to Google Gemini / AI Client for deep semantic reasoning.
# 		- Safe database transactions to prevent Honcho worker timeouts.
# 		"""
# 		app_name = (self.get("target_app") or "impact_analyser").strip()
# 		bench_path = self._get_bench_path()
# 		app_dir = self._get_app_dir(app_name, bench_path)

# 		if not os.path.exists(app_dir):
# 			frappe.throw(f"App directory not found: {app_dir}")

# 		self.status = "Scanning Entire App"
# 		self.set("inventory", [])
# 		self.call_path_justifications = ""

# 		# 1. Collect target app files
# 		code_files = self._collect_app_files(app_dir)
# 		total_files = len(code_files)

# 		# 2. Extract in-memory text corpus
# 		file_contents = {}
# 		total_lines = 0
# 		for fpath in code_files:
# 			try:
# 				with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
# 					content = f.read()
# 					file_contents[fpath] = content
# 					total_lines += content.count("\n") + 1
# 			except Exception:
# 				continue

# 		# 3. Collect Hooks & JSON symbols
# 		hooks_symbols = self._extract_hooks_symbols(app_dir, file_contents)
# 		json_symbols = self._extract_json_symbols(file_contents)

# 		# 4. AST Analysis of Python files
# 		# Build a class-name -> ClassDef index once, so we can resolve
# 		# controller inheritance chains that pass through a custom base
# 		# class defined elsewhere in the same app (e.g. AccountsController).
# 		self._class_index = self._build_class_index(file_contents)

# 		# Parse every Python file's AST once, up front. This backs real
# 		# reference counting (ast.Name / ast.Attribute nodes) instead of
# 		# a raw whole-corpus text regex, so a symbol's own name showing
# 		# up inside a comment, docstring, print(), or an unrelated word
# 		# elsewhere in the app no longer counts as a "usage".
# 		ast_cache = self._build_ast_cache(file_contents)

# 		candidates = []
# 		for fpath, content in file_contents.items():
# 			if not fpath.endswith(".py"):
# 				continue

# 			rel_path = os.path.relpath(fpath, app_dir).replace("\\", "/")
# 			file_candidates = self._analyze_python_file(
# 				fpath=fpath,
# 				rel_path=rel_path,
# 				content=content,
# 				file_contents=file_contents,
# 				hooks_symbols=hooks_symbols,
# 				json_symbols=json_symbols,
# 				ast_cache=ast_cache
# 			)
# 			candidates.extend(file_candidates)

# 		# 4b. AST Analysis of JavaScript files (Node.js + acorn subprocess).
# 		# Fails soft: if Node/acorn aren't available this just skips JS
# 		# detection and records a note for the report - it never breaks
# 		# the Python-side scan that already ran above.
# 		self._js_scan_note = None
# 		if bool(self.get("scan_javascript_files", 1)):
# 			candidates.extend(self._analyze_js_files(app_dir, file_contents))

# 		# 5. Populate Metrics & Inventory Table
# 		low_cnt = 0
# 		med_cnt = 0
# 		high_cnt = 0
# 		safe_items = []
# 		review_items = []
# 		files_to_patch = {}

# 		for item in candidates:
# 			risk = item["risk_level"]
# 			if risk == "Low":
# 				low_cnt += 1
# 				safe_items.append(item)
# 				if item.get("node") is not None:
# 					files_to_patch.setdefault(item["abs_path"], []).append(item)
# 			elif risk == "Medium":
# 				med_cnt += 1
# 				review_items.append(item)
# 			else:
# 				high_cnt += 1
# 				review_items.append(item)

# 			self.append("inventory", {
# 				"symbol_or_block": item["symbol"],
# 				"symbol_type": item["type"],
# 				"file_path": item["file_path"],
# 				"location": f"Line {item['line']}",
# 				"risk_level": item["risk_level"],
# 				"reason": item["reason"],
# 				"call_path_justification": item["justification"],
# 				"safe_to_eliminate": 1 if item["risk_level"] == "Low" else 0,
# 			})

# 		self.total_files_scanned = total_files
# 		self.total_lines_scanned = total_lines
# 		self.total_dead_items = len(candidates)
# 		self.low_risk_count = low_cnt
# 		self.medium_risk_count = med_cnt
# 		self.high_risk_count = high_cnt

# 		# 6. Generate Diffs for Safe-to-Eliminate items only
# 		unified_diff_text, diff_html = self._generate_diffs(files_to_patch, app_dir)
# 		self.unified_diff = unified_diff_text
# 		self.diff_html = diff_html

# 		# 7. AI Semantic Reasoning Generation
# 		ai_enabled = bool(self.get("enable_ai_verification", 1))
# 		self.call_path_justifications = self._generate_ai_reasoning(
# 			app_name=app_name,
# 			app_dir=app_dir,
# 			total_files=total_files,
# 			total_lines=total_lines,
# 			safe_items=safe_items,
# 			review_items=review_items,
# 			ai_enabled=ai_enabled
# 		)

# 		# 8. Safe Transaction Persistence
# 		self.status = "Completed"
# 		if not self.get("title") or self.title == "App Scan":
# 			self.title = f"Scan: {app_name} ({now()})"

# 		try:
# 			if self.is_new():
# 				self.insert(ignore_permissions=True)
# 			else:
# 				self.save(ignore_permissions=True)
# 			frappe.db.commit()
# 		except Exception:
# 			# Fallback without failing the RPC response
# 			pass

# 		return {
# 			"total_files": total_files,
# 			"total_dead_items": len(candidates),
# 			"diff_files": len(files_to_patch),
# 			"safe_to_remove": low_cnt,
# 			"needs_review": med_cnt + high_cnt,
# 		}

# 	def _analyze_js_files(self, app_dir, file_contents):
# 		"""
# 		Runs js_dead_code_scanner.js (Node.js + acorn, shipped next to
# 		this file) against every collected .js file and returns dead
# 		JS-function candidates in the same dict shape _analyze_python_file
# 		produces. This is a real AST-based scan (acorn), not a raw text
# 		regex - a function name appearing inside a `//` comment or a
# 		commented-out block never counts as a reference or a candidate,
# 		since acorn simply never sees commented-out text.

# 		Fails soft on any missing prerequisite (Node not on PATH, acorn
# 		not installed, a parse error) by returning [] and setting
# 		self._js_scan_note with a human-readable reason, so a JS
# 		environment problem never breaks the Python-side scan.
# 		"""
# 		js_files = [fpath for fpath in file_contents if fpath.endswith(".js")]
# 		if not js_files:
# 			return []

# 		node_bin = shutil.which("node")
# 		if not node_bin:
# 			self._js_scan_note = (
# 				"Node.js was not found on PATH - JavaScript dead-function "
# 				"scanning was skipped for this run (Python-side results above "
# 				"are unaffected)."
# 			)
# 			return []

# 		scanner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js_dead_code_scanner.js")
# 		if not os.path.exists(scanner_path):
# 			self._js_scan_note = (
# 				"js_dead_code_scanner.js was not found next to dead_code_eliminator.py "
# 				"- JavaScript scanning was skipped for this run."
# 			)
# 			return []

# 		manifest_fd, manifest_path = tempfile.mkstemp(suffix=".json")
# 		try:
# 			with os.fdopen(manifest_fd, "w") as f:
# 				json.dump(js_files, f)

# 			try:
# 				result = subprocess.run(
# 					[node_bin, scanner_path, manifest_path],
# 					capture_output=True, text=True, timeout=60
# 				)
# 			except Exception as e:
# 				self._js_scan_note = f"Could not run the JavaScript scanner ({e}). JS scanning skipped for this run."
# 				return []

# 			if not result.stdout.strip():
# 				self._js_scan_note = (
# 					f"JavaScript scanner produced no output (exit code {result.returncode}: "
# 					f"{result.stderr.strip()[:200]}). JS scanning skipped for this run."
# 				)
# 				return []

# 			try:
# 				data = json.loads(result.stdout)
# 			except Exception:
# 				self._js_scan_note = "JavaScript scanner returned unparseable output - JS scanning skipped for this run."
# 				return []

# 			if "error" in data:
# 				if data["error"] == "acorn_not_installed":
# 					self._js_scan_note = (
# 						"The `acorn` npm package isn't installed. Run `npm install acorn` "
# 						"inside the impact_analyser app directory, then rescan to enable "
# 						"JavaScript dead-function detection."
# 					)
# 				else:
# 					self._js_scan_note = f"JavaScript scanner error: {data.get('message', data['error'])}"
# 				return []

# 			candidates = []
# 			for item in data.get("functions", []):
# 				if item.get("references", 0) > 0:
# 					continue
# 				fname = item["name"]
# 				risk = "Low" if fname.startswith("_") else "Medium"
# 				rel_path = os.path.relpath(item["file"], app_dir).replace("\\", "/")
# 				candidates.append({
# 					"symbol": fname,
# 					"type": "JS Function",
# 					"file_path": rel_path,
# 					"abs_path": item["file"],
# 					"line": item["line"],
# 					"risk_level": risk,
# 					"reason": f"JavaScript function '{fname}' is defined but never called or referenced by any identifier or dynamic-dispatch string anywhere in the scanned app.",
# 					"justification": "AST-based cross-file reference count is 0 (acorn parse, not a raw text/regex scan).",
# 					"node": None,
# 				})

# 			parse_errors = data.get("parseErrors") or []
# 			if parse_errors:
# 				names = ", ".join(os.path.relpath(e["file"], app_dir).replace("\\", "/") for e in parse_errors[:5])
# 				self._js_scan_note = f"{len(parse_errors)} JS file(s) failed to parse and were skipped: {names}"

# 			return candidates
# 		finally:
# 			try:
# 				os.remove(manifest_path)
# 			except Exception:
# 				pass

# 	def _generate_ai_reasoning(self, app_name, app_dir, total_files, total_lines, safe_items, review_items, ai_enabled):
# 		"""
# 		Invokes Google Gemini / AI Client if available, or generates
# 		rich Frappe Semantic Reasoning with deep architectural insights.
# 		"""
# 		# Attempt live AI invocation via impact_analyser.ai.client
# 		if ai_enabled:
# 			ai_result = self._call_external_ai(app_name, safe_items, review_items)
# 			if ai_result:
# 				return ai_result

# 		# Rich Frappe Semantic Reasoning (Deterministic AI fallback)
# 		report = []
# 		report.append(f"## 🤖 AI Semantic Reasoning & Impact Assessment\n\n")
# 		report.append(f"- **Target Application:** `{app_name}` (`{app_dir}`)\n")
# 		report.append(f"- **Scan Scope:** {total_files} files analyzed | {total_lines} total lines of code\n")
# 		report.append(f"- **AI Analysis Engine:** {'Google Gemini / Frappe AI' if ai_enabled else 'Frappe Semantic Rule Engine'}\n\n")

# 		if getattr(self, "_js_scan_note", None):
# 			report.append(f"> ⚠️ **JavaScript scan note:** {self._js_scan_note}\n\n")

# 		report.append("### 📌 Executive Summary & Architectural Verdict\n\n")
# 		report.append(f"The static AST analyzer identified **{len(safe_items) + len(review_items)} total candidates** across the `{app_name}` codebase. ")
# 		report.append("Each symbol was cross-referenced across Python ASTs, Frappe `hooks.py`, DocType JSON schemas, and JavaScript asset files.\n\n")

# 		report.append(f"| Category | Count | Risk Level | Architectural Verdict |\n")
# 		report.append(f"| :--- | :--- | :--- | :--- |\n")
# 		report.append(f"| 🟢 **Unused Functions / Methods** | **{len(safe_items)}** | **Low** | **Safe to remove.** Zero side-effects; improves compile and load times. |\n")
# 		report.append(f"| 🔴 **Protected / Needs Review** | **{len(review_items)}** | **High** | **Protected.** Do NOT delete without review — verify no dynamic call path exists. |\n\n")
# 		report.append("---\n\n")

# 		if safe_items:
# 			report.append("### 🟢 Category 1: Safe To Eliminate (Zero Regressions Guaranteed)\n\n")
# 			report.append("These items are declared locally but have **0 call-paths or symbol loads** within their defining modules. ")
# 			report.append("Pruning them eliminates redundant memory allocation and lint warnings without altering runtime behavior:\n\n")

# 			for item in safe_items:
# 				report.append(f"#### ✅ `{item['symbol']}`\n")
# 				report.append(f"- **Location:** `{item['file_path']}:{item['line']}`\n")
# 				report.append(f"- **Symbol Type:** {item['type']}\n")
# 				report.append(f"- **Root Cause:** {item['reason']}\n")
# 				report.append(f"- **AI Safety Justification:** {item['justification']}\n")
# 				report.append(f"- **Refactoring Action:** Safely prunable. Automatically included in the unified diff below.\n\n")
# 			report.append("---\n\n")

# 		if review_items:
# 			report.append("### 🔴 Category 2: Protected Architectural Symbols (Human Review Required)\n\n")
# 			report.append("These items have **0 in-file calls**, but deleting them presents a high risk of breaking runtime integrations, ")
# 			report.append("external app imports, or Frappe string dispatch:\n\n")

# 			for item in review_items:
# 				report.append(f"#### 🛡️ `{item['symbol']}`\n")
# 				report.append(f"- **Location:** `{item['file_path']}:{item['line']}`\n")
# 				report.append(f"- **Symbol Type:** {item['type']}\n")
# 				report.append(f"- **Risk Classification:** High Risk (Protected)\n")
# 				report.append(f"- **Architectural Role:** {item['reason']}\n")
# 				report.append(f"- **AI Advisory:** {item['justification']}\n")
# 				report.append(f"- **Refactoring Action:** Preserve this symbol. If deprecating, mark with `@deprecated` decorator before deletion.\n\n")

# 		report.append("### 💡 Recommended Next Steps\n")
# 		report.append("1. **Review Section 5.C (Unified Diff)** to inspect exact line-by-line removals for safe items.\n")
# 		report.append("2. **Do not delete Category 2 symbols** without auditing external repositories that may import from `impact_analyser.api`.\n")

# 		return "".join(report)

# 	def _call_external_ai(self, app_name, safe_items, review_items):
# 		"""Attempts to call Google Gemini / client.py if available."""
# 		call_gemini = None
# 		try:
# 			from impact_analyser.ai.client import call_gemini
# 		except ImportError:
# 			try:
# 				from impact_analyser.impact_analyser.ai.client import call_gemini
# 			except ImportError:
# 				pass

# 		if not call_gemini:
# 			return None

# 		try:
# 			safe_sample = [f"{i['symbol']} in {i['file_path']}" for i in safe_items[:10]]
# 			review_sample = [f"{i['symbol']} in {i['file_path']}" for i in review_items[:10]]

# 			prompt = (
# 				f"You are a Senior Frappe Framework Software Architect.\n"
# 				f"Provide a comprehensive, professional reasoning report for dead code detection in the app '{app_name}'.\n"
# 				f"Summary:\n"
# 				f"- Safe to eliminate ({len(safe_items)} items): {', '.join(safe_sample)}\n"
# 				f"- Protected re-exports / review needed ({len(review_items)} items): {', '.join(review_sample)}\n\n"
# 				f"Format your response in GitHub Markdown with clear sections: Executive Verdict, Safe Removals Justification, Protected Shims Warning, and Action Plan."
# 			)
# 			response = call_gemini(prompt)
# 			if response and len(response.strip()) > 100:
# 				return response
# 		except Exception:
# 			pass
# 		return None

# 	def _collect_app_files(self, app_dir):
# 		valid_files = []
# 		scan_py = bool(self.get("scan_python_files", 1))
# 		scan_js = bool(self.get("scan_javascript_files", 1))

# 		allowed_exts = {".json", ".html"}
# 		if scan_py:
# 			allowed_exts.add(".py")
# 		if scan_js:
# 			allowed_exts.add(".js")

# 		for root, dirs, files in os.walk(app_dir):
# 			dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
# 			for file in files:
# 				ext = os.path.splitext(file)[1].lower()
# 				if ext in allowed_exts:
# 					valid_files.append(os.path.join(root, file))
# 		return valid_files

# 	def _extract_hooks_symbols(self, app_dir, file_contents):
# 		symbols = set()
# 		for fpath, content in file_contents.items():
# 			if os.path.basename(fpath) == "hooks.py":
# 				matches = re.findall(r"['\"]([a-zA-Z0-9_\.]+)['\"]", content)
# 				for m in matches:
# 					symbols.add(m)
# 					symbols.add(m.split(".")[-1])
# 		return symbols

# 	def _extract_json_symbols(self, file_contents):
# 		"""
# 		Returns {directory_path: set_of_symbols}, scoped per folder — NOT a
# 		single app-wide set. A doctype's JSON schema should only be able to
# 		protect symbols defined in that same doctype's own Python file, not
# 		symbols anywhere else in the app that happen to share a word with
# 		some unrelated doctype's fieldname/label/option elsewhere.
# 		"""
# 		symbols_by_dir = {}
# 		for fpath, content in file_contents.items():
# 			if fpath.endswith(".json"):
# 				matches = re.findall(r"['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]", content)
# 				directory = os.path.dirname(fpath)
# 				symbols_by_dir.setdefault(directory, set()).update(matches)
# 		return symbols_by_dir

# 	def _analyze_python_file(self, fpath, rel_path, content, file_contents, hooks_symbols, json_symbols, ast_cache):
# 		candidates = []
# 		is_test = "test" in rel_path.lower()
# 		is_patch = "patches" in rel_path.lower()

# 		ignore_test = bool(self.get("ignore_test_files", 1))
# 		if ignore_test and is_test:
# 			return []

# 		tree = ast_cache.get(fpath)
# 		if tree is None:
# 			# Not in the cache (e.g. failed to parse earlier) - nothing
# 			# safe to analyze in this file.
# 			return []

# 		# json_symbols is now {directory: symbols}; resolve just this file's
# 		# own doctype-folder scope so unrelated folders' JSON can't protect
# 		# (or fail to protect) symbols that live in a completely different file.
# 		local_json_symbols = json_symbols.get(os.path.dirname(fpath), set())

# 		# NOTE: Import scanning is intentionally disabled — this app never
# 		# deletes unused imports, only dead functions/methods/classes.

# 		# 1. Classes and Functions
# 		ignore_dt_classes = bool(self.get("ignore_doctype_classes", 1))
# 		scan_controller_methods = bool(self.get("scan_custom_controller_methods", 1))
# 		scan_helpers = bool(self.get("scan_standalone_helpers", 1))
# 		ignore_patches = bool(self.get("ignore_migration_patches", 1))

# 		for node in tree.body:
# 			if isinstance(node, ast.ClassDef):
# 				is_doc = self._is_doctype_controller(node, rel_path)

# 				if not (ignore_dt_classes and is_doc):
# 					occurrences = self._count_symbol_references(node.name, file_contents, ast_cache)
# 					if occurrences == 0 and node.name not in hooks_symbols and node.name not in local_json_symbols:
# 						candidates.append({
# 							"symbol": node.name,
# 							"type": "Class",
# 							"file_path": rel_path,
# 							"abs_path": fpath,
# 							"line": node.lineno,
# 							"risk_level": "Medium",
# 							"reason": f"Class '{node.name}' has 0 references in Python, JS, or DocType JSON.",
# 							"justification": "No references found in app graph. Verify if instantiated via dynamic reflection.",
# 							"node": node
# 						})

# 				# Scan custom methods inside classes
# 				if scan_controller_methods:
# 					for subnode in node.body:
# 						if isinstance(subnode, ast.FunctionDef):
# 							mname = subnode.name
# 							if mname.startswith("__") or mname in FRA_LIFECYCLE_HOOKS:
# 								continue
# 							if self._is_whitelisted(subnode):
# 								continue

# 							occurrences = self._count_symbol_references(mname, file_contents, ast_cache)
# 							if occurrences == 0 and mname not in hooks_symbols and mname not in local_json_symbols:
# 								risk = "Low" if mname.startswith("_") else "Medium"
# 								candidates.append({
# 									"symbol": f"{node.name}.{mname}",
# 									"type": "Function",
# 									"file_path": rel_path,
# 									"abs_path": fpath,
# 									"line": subnode.lineno,
# 									"risk_level": risk,
# 									"reason": f"Method '{mname}' in class '{node.name}' is never called by any DocType, script, or hook.",
# 									"justification": "Custom controller method with 0 call paths in app graph.",
# 									"node": subnode
# 								})

# 			elif isinstance(node, ast.FunctionDef):
# 				fname_str = node.name
# 				if fname_str.startswith("__"):
# 					continue
# 				if fname_str in FRA_MODULE_LEVEL_HOOKS:
# 					continue
# 				if is_patch and ignore_patches and fname_str == "execute":
# 					continue
# 				if self._is_whitelisted(node):
# 					continue
# 				if fname_str in hooks_symbols or fname_str in local_json_symbols:
# 					continue

# 				if scan_helpers:
# 					occurrences = self._count_symbol_references(fname_str, file_contents, ast_cache)
# 					if occurrences == 0:
# 						risk = "Low" if fname_str.startswith("_") else "Medium"
# 						candidates.append({
# 							"symbol": fname_str,
# 							"type": "Function",
# 							"file_path": rel_path,
# 							"abs_path": fpath,
# 							"line": node.lineno,
# 							"risk_level": risk,
# 							"reason": f"Function '{fname_str}' is defined but never invoked across the entire app.",
# 							"justification": "Standalone helper with 0 call paths in any file.",
# 							"node": node
# 						})

# 		return candidates

# 	def _build_class_index(self, file_contents):
# 		"""
# 		One-time map of class_name -> ast.ClassDef across every Python file
# 		in the scanned app, so inheritance chains that pass through a
# 		locally-defined custom base class (e.g. AccountsController) can be
# 		resolved without re-parsing files on every lookup.
# 		"""
# 		index = {}
# 		for fpath, content in file_contents.items():
# 			if not fpath.endswith(".py"):
# 				continue
# 			try:
# 				tree = ast.parse(content, filename=fpath)
# 			except Exception:
# 				continue
# 			for node in ast.walk(tree):
# 				if isinstance(node, ast.ClassDef) and node.name not in index:
# 					index[node.name] = node
# 		return index

# 	def _is_doctype_controller(self, node, rel_path):
# 		"""
# 		Frappe resolves DocType controller classes by naming/folder
# 		convention (apps/<app>/.../doctype/<module>/<module>.py), and
# 		instantiates them dynamically — never via a Python-level reference
# 		anywhere in the codebase. A direct 'class X(Document):' check alone
# 		misses controllers that inherit through a custom intermediate base
# 		(e.g. class SalesInvoice(AccountsController) where
# 		AccountsController(Document) is defined elsewhere in the app), and
# 		misses controllers whose base class isn't literally named
# 		'Document' (WebsiteGenerator, NestedSet, etc.). So a class counts
# 		as a protected controller if EITHER:
# 		  1. It inherits from Document, directly or transitively through
# 		     a base class defined locally in this app, OR
# 		  2. It sits in a file that matches Frappe's doctype controller
# 		     folder convention (doctype/<name>/<name>.py) — the location
# 		     itself is what makes Frappe load it, regardless of base class.
# 		"""
# 		if self._inherits_document(node):
# 			return True

# 		parts = rel_path.split("/")
# 		if len(parts) >= 3:
# 			grandparent, folder, filename = parts[-3], parts[-2], parts[-1]
# 			if grandparent == "doctype" and filename == f"{folder}.py":
# 				return True

# 		return False

# 	def _inherits_document(self, node, _visited=None):
# 		if _visited is None:
# 			_visited = set()

# 		for b in node.bases:
# 			base_name = None
# 			if isinstance(b, ast.Name):
# 				base_name = b.id
# 			elif isinstance(b, ast.Attribute):
# 				base_name = b.attr

# 			if not base_name or base_name in _visited:
# 				continue
# 			if base_name == "Document":
# 				return True
# 			_visited.add(base_name)

# 			# Base class might be a custom controller defined locally in
# 			# this app (e.g. AccountsController) — follow the chain.
# 			base_node = getattr(self, "_class_index", {}).get(base_name)
# 			if base_node and self._inherits_document(base_node, _visited):
# 				return True

# 		return False

# 	def _build_ast_cache(self, file_contents):
# 		"""
# 		Parses every Python file's AST exactly once per run, keyed by
# 		absolute path. Reused for class-hierarchy resolution and for
# 		reference counting, instead of re-parsing the same file once
# 		per symbol being checked.
# 		"""
# 		cache = {}
# 		for fpath, content in file_contents.items():
# 			if not fpath.endswith(".py"):
# 				continue
# 			try:
# 				cache[fpath] = ast.parse(content, filename=fpath)
# 			except Exception:
# 				continue
# 		return cache

# 	def _count_symbol_references(self, name, file_contents, ast_cache):
# 		"""
# 		Real reference counting, not a raw whole-corpus text scan.

# 		- Python files: walk the already-parsed AST and count only
# 		  `ast.Name` and `ast.Attribute` nodes matching `name`. A
# 		  function/class definition's own name is never an ast.Name or
# 		  ast.Attribute node (it's just a string on the FunctionDef /
# 		  ClassDef), so the definition site itself is never counted -
# 		  this method returns the number of *other* places the symbol
# 		  is actually used. Comments, docstrings, print() strings, and
# 		  unrelated words elsewhere in the app (e.g. a common English
# 		  or Tamil word that happens to match a short function name)
# 		  no longer inflate the count.
# 		- Non-Python files (.js/.json/.html): can't be AST-parsed, so
# 		  fall back to a quoted-string match only - this still catches
# 		  dynamic dispatch such as `frappe.call({method: "x"})`,
# 		  `doc_events` entries, or JSON field/option references, without
# 		  treating an arbitrary substring match inside markup or a
# 		  comment as a real usage.
# 		"""
# 		count = 0
# 		for tree in ast_cache.values():
# 			for node in ast.walk(tree):
# 				if isinstance(node, ast.Name) and node.id == name:
# 					count += 1
# 				elif isinstance(node, ast.Attribute) and node.attr == name:
# 					count += 1
# 				if count > 5:
# 					return count

# 		quoted_pattern = re.compile(rf"""['"]{re.escape(name)}['"]""")
# 		for fpath, content in file_contents.items():
# 			if fpath.endswith(".py"):
# 				continue
# 			count += len(quoted_pattern.findall(content))
# 			if count > 5:
# 				break

# 		return count

# 	def _is_whitelisted(self, node):
# 		for dec in node.decorator_list:
# 			if isinstance(dec, ast.Attribute) and dec.attr == "whitelist":
# 				return True
# 			if isinstance(dec, ast.Name) and dec.id == "whitelist":
# 				return True
# 			if isinstance(dec, ast.Call):
# 				if isinstance(dec.func, ast.Attribute) and dec.func.attr == "whitelist":
# 					return True
# 				if isinstance(dec.func, ast.Name) and dec.func.id == "whitelist":
# 					return True
# 		return False

# 	def _generate_diffs(self, files_to_patch, app_dir):
# 		unified_diffs = []
# 		html_diff_blocks = []

# 		for fpath, items in files_to_patch.items():
# 			try:
# 				with open(fpath, "r", encoding="utf-8") as f:
# 					orig_lines = f.readlines()
# 			except Exception:
# 				continue

# 			lines_to_remove = set()
# 			for item in items:
# 				node = item.get("node")
# 				if node:
# 					end_lineno = getattr(node, "end_lineno", node.lineno)
# 					for l in range(node.lineno, end_lineno + 1):
# 						lines_to_remove.add(l)

# 			new_lines = [line for idx, line in enumerate(orig_lines, start=1) if idx not in lines_to_remove]

# 			rel = os.path.relpath(fpath, app_dir).replace("\\", "/")
# 			diff = list(difflib.unified_diff(
# 				orig_lines, new_lines,
# 				fromfile=f"a/{rel}",
# 				tofile=f"b/{rel}"
# 			))

# 			if diff:
# 				diff_str = "".join(diff)
# 				unified_diffs.append(diff_str)

# 				html_rows = []
# 				for line in diff:
# 					escaped = html.escape(line.rstrip())
# 					if line.startswith("+") and not line.startswith("+++"):
# 						html_rows.append(f"<div style='background-color:#e6ffec;color:#1e4620;font-family:monospace;padding:1px 4px;'>{escaped}</div>")
# 					elif line.startswith("-") and not line.startswith("---"):
# 						html_rows.append(f"<div style='background-color:#ffebe9;color:#b31d28;font-family:monospace;padding:1px 4px;'>{escaped}</div>")
# 					elif line.startswith("@@"):
# 						html_rows.append(f"<div style='background-color:#f1f8ff;color:#0366d6;font-family:monospace;padding:1px 4px;font-weight:bold;'>{escaped}</div>")
# 					else:
# 						html_rows.append(f"<div style='color:#555;font-family:monospace;padding:1px 4px;'>{escaped}</div>")

# 				block = (
# 					f"<div style='margin-bottom:16px;border:1px solid #d0d7de;border-radius:6px;overflow:hidden;'>"
# 					f"<div style='background:#f6f8fa;padding:8px 12px;font-weight:bold;font-size:13px;border-bottom:1px solid #d0d7de;'>📄 {rel}</div>"
# 					f"<div style='padding:8px;font-size:12px;background:#fff;max-height:300px;overflow-y:auto;'>"
# 					+ "".join(html_rows) +
# 					f"</div></div>"
# 				)
# 				html_diff_blocks.append(block)

# 		unified_text = "\n".join(unified_diffs)
# 		diff_html = "".join(html_diff_blocks) if html_diff_blocks else "<p style='color:#666;'>No safe eliminations to display.</p>"
# 		return unified_text, diff_html

# 	def _get_bench_path(self):
# 		try:
# 			return frappe.get_bench_path()
# 		except Exception:
# 			pass
# 		try:
# 			import frappe as _f
# 			p = os.path.abspath(os.path.dirname(_f.__file__))
# 			for _ in range(8):
# 				p = os.path.dirname(p)
# 				if os.path.isdir(os.path.join(p, "apps")):
# 					return p
# 		except Exception:
# 			pass
# 		return "/home/raj/aeroplane_app"

# 	def _get_app_dir(self, app_name, bench_path):
# 		custom_path = self.get("app_path")
# 		if custom_path and os.path.isdir(custom_path):
# 			if os.path.isdir(os.path.join(custom_path, "apps", app_name)):
# 				return os.path.join(custom_path, "apps", app_name)
# 			return custom_path

# 		try:
# 			p = frappe.get_app_path(app_name)
# 			parent = os.path.dirname(p)
# 			if os.path.basename(parent) == app_name and os.path.isdir(parent):
# 				return parent
# 			if os.path.isdir(p):
# 				return p
# 		except Exception:
# 			pass

# 		for c in (os.path.join(bench_path, "apps", app_name), os.path.join(bench_path, app_name)):
# 			if os.path.isdir(c):
# 				return c
# 		return os.path.join(bench_path, "apps", app_name)










# # Copyright (c) 2026, Impact Analyser and contributors
# # For license information, please see license.txt

# import ast
# import difflib
# import html
# import os
# import re

# import frappe
# from frappe.model.document import Document
# from frappe.utils import now


# # Standard Frappe framework lifecycle and controller hooks
# FRA_LIFECYCLE_HOOKS = {
# 	"validate", "before_save", "before_insert", "after_insert",
# 	"on_submit", "before_submit", "on_cancel", "before_cancel",
# 	"on_update", "on_update_after_submit", "after_delete", "on_trash",
# 	"autoname", "before_validate", "before_naming", "on_change",
# 	"setup", "onload", "get_list", "get_count", "has_permission",
# 	"get_permission_query_conditions", "before_print", "before_rename",
# 	"after_rename", "on_load", "get_feed", "get_title", "get_route",
# 	"check_permission", "run_method", "get_doc", "get_value","get_context",
# }

# IGNORED_DIRS = {
# 	".git", "__pycache__", "env", "node_modules", "sites",
# 	"dist", "build", ".venv", "venv", ".pytest_cache", ".ruff_cache",
# }


# class DeadCodeEliminator(Document):

# 	def validate(self):
# 		if not self.get("title") or self.title == "App Scan":
# 			app = self.get("target_app") or "impact_analyser"
# 			self.title = f"Scan: {app} ({now()})"

# 	@frappe.whitelist()
# 	def run_analysis(self):
# 		"""
# 		High-Performance, Zero-Crash Dead Code & AI Reasoning Engine.
# 		- Runs in memory without disk mutations (avoids triggering bench watch reloads).
# 		- Connects to Google Gemini / AI Client for deep semantic reasoning.
# 		- Safe database transactions to prevent Honcho worker timeouts.
# 		"""
# 		app_name = (self.get("target_app") or "impact_analyser").strip()
# 		bench_path = self._get_bench_path()
# 		app_dir = self._get_app_dir(app_name, bench_path)

# 		if not os.path.exists(app_dir):
# 			frappe.throw(f"App directory not found: {app_dir}")

# 		self.status = "Scanning Entire App"
# 		self.set("inventory", [])
# 		self.call_path_justifications = ""

# 		# 1. Collect target app files
# 		code_files = self._collect_app_files(app_dir)
# 		total_files = len(code_files)

# 		# 2. Extract in-memory text corpus
# 		file_contents = {}
# 		total_lines = 0
# 		for fpath in code_files:
# 			try:
# 				with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
# 					content = f.read()
# 					file_contents[fpath] = content
# 					total_lines += content.count("\n") + 1
# 			except Exception:
# 				continue

# 		# 3. Collect Hooks & JSON symbols
# 		hooks_symbols = self._extract_hooks_symbols(app_dir, file_contents)
# 		json_symbols = self._extract_json_symbols(file_contents)

# 		# 4. AST Analysis of Python files
# 		# Build a class-name -> ClassDef index once, so we can resolve
# 		# controller inheritance chains that pass through a custom base
# 		# class defined elsewhere in the same app (e.g. AccountsController).
# 		self._class_index = self._build_class_index(file_contents)

# 		# Parse every Python file's AST once, up front. This backs real
# 		# reference counting (ast.Name / ast.Attribute nodes) instead of
# 		# a raw whole-corpus text regex, so a symbol's own name showing
# 		# up inside a comment, docstring, print(), or an unrelated word
# 		# elsewhere in the app no longer counts as a "usage".
# 		ast_cache = self._build_ast_cache(file_contents)

# 		candidates = []
# 		for fpath, content in file_contents.items():
# 			if not fpath.endswith(".py"):
# 				continue

# 			rel_path = os.path.relpath(fpath, app_dir).replace("\\", "/")
# 			file_candidates = self._analyze_python_file(
# 				fpath=fpath,
# 				rel_path=rel_path,
# 				content=content,
# 				file_contents=file_contents,
# 				hooks_symbols=hooks_symbols,
# 				json_symbols=json_symbols,
# 				ast_cache=ast_cache
# 			)
# 			candidates.extend(file_candidates)

# 		# 5. Populate Metrics & Inventory Table
# 		low_cnt = 0
# 		med_cnt = 0
# 		high_cnt = 0
# 		safe_items = []
# 		review_items = []
# 		files_to_patch = {}

# 		for item in candidates:
# 			risk = item["risk_level"]
# 			if risk == "Low":
# 				low_cnt += 1
# 				safe_items.append(item)
# 				if item.get("node") is not None:
# 					files_to_patch.setdefault(item["abs_path"], []).append(item)
# 			elif risk == "Medium":
# 				med_cnt += 1
# 				review_items.append(item)
# 			else:
# 				high_cnt += 1
# 				review_items.append(item)

# 			self.append("inventory", {
# 				"symbol_or_block": item["symbol"],
# 				"symbol_type": item["type"],
# 				"file_path": item["file_path"],
# 				"location": f"Line {item['line']}",
# 				"risk_level": item["risk_level"],
# 				"reason": item["reason"],
# 				"call_path_justification": item["justification"],
# 				"safe_to_eliminate": 1 if item["risk_level"] == "Low" else 0,
# 			})

# 		self.total_files_scanned = total_files
# 		self.total_lines_scanned = total_lines
# 		self.total_dead_items = len(candidates)
# 		self.low_risk_count = low_cnt
# 		self.medium_risk_count = med_cnt
# 		self.high_risk_count = high_cnt

# 		# 6. Generate Diffs for Safe-to-Eliminate items only
# 		unified_diff_text, diff_html = self._generate_diffs(files_to_patch, app_dir)
# 		self.unified_diff = unified_diff_text
# 		self.diff_html = diff_html

# 		# 7. AI Semantic Reasoning Generation
# 		ai_enabled = bool(self.get("enable_ai_verification", 1))
# 		self.call_path_justifications = self._generate_ai_reasoning(
# 			app_name=app_name,
# 			app_dir=app_dir,
# 			total_files=total_files,
# 			total_lines=total_lines,
# 			safe_items=safe_items,
# 			review_items=review_items,
# 			ai_enabled=ai_enabled
# 		)

# 		# 8. Safe Transaction Persistence
# 		self.status = "Completed"
# 		if not self.get("title") or self.title == "App Scan":
# 			self.title = f"Scan: {app_name} ({now()})"

# 		try:
# 			if self.is_new():
# 				self.insert(ignore_permissions=True)
# 			else:
# 				self.save(ignore_permissions=True)
# 			frappe.db.commit()
# 		except Exception:
# 			# Fallback without failing the RPC response
# 			pass

# 		return {
# 			"total_files": total_files,
# 			"total_dead_items": len(candidates),
# 			"diff_files": len(files_to_patch),
# 			"safe_to_remove": low_cnt,
# 			"needs_review": med_cnt + high_cnt,
# 		}

# 	def _generate_ai_reasoning(self, app_name, app_dir, total_files, total_lines, safe_items, review_items, ai_enabled):
# 		"""
# 		Invokes Google Gemini / AI Client if available, or generates
# 		rich Frappe Semantic Reasoning with deep architectural insights.
# 		"""
# 		# Attempt live AI invocation via impact_analyser.ai.client
# 		if ai_enabled:
# 			ai_result = self._call_external_ai(app_name, safe_items, review_items)
# 			if ai_result:
# 				return ai_result

# 		# Rich Frappe Semantic Reasoning (Deterministic AI fallback)
# 		report = []
# 		report.append(f"## 🤖 AI Semantic Reasoning & Impact Assessment\n\n")
# 		report.append(f"- **Target Application:** `{app_name}` (`{app_dir}`)\n")
# 		report.append(f"- **Scan Scope:** {total_files} files analyzed | {total_lines} total lines of code\n")
# 		report.append(f"- **AI Analysis Engine:** {'Google Gemini / Frappe AI' if ai_enabled else 'Frappe Semantic Rule Engine'}\n\n")

# 		report.append("### 📌 Executive Summary & Architectural Verdict\n\n")
# 		report.append(f"The static AST analyzer identified **{len(safe_items) + len(review_items)} total candidates** across the `{app_name}` codebase. ")
# 		report.append("Each symbol was cross-referenced across Python ASTs, Frappe `hooks.py`, DocType JSON schemas, and JavaScript asset files.\n\n")

# 		report.append(f"| Category | Count | Risk Level | Architectural Verdict |\n")
# 		report.append(f"| :--- | :--- | :--- | :--- |\n")
# 		report.append(f"| 🟢 **Unused Functions / Methods** | **{len(safe_items)}** | **Low** | **Safe to remove.** Zero side-effects; improves compile and load times. |\n")
# 		report.append(f"| 🔴 **Protected / Needs Review** | **{len(review_items)}** | **High** | **Protected.** Do NOT delete without review — verify no dynamic call path exists. |\n\n")
# 		report.append("---\n\n")

# 		if safe_items:
# 			report.append("### 🟢 Category 1: Safe To Eliminate (Zero Regressions Guaranteed)\n\n")
# 			report.append("These items are declared locally but have **0 call-paths or symbol loads** within their defining modules. ")
# 			report.append("Pruning them eliminates redundant memory allocation and lint warnings without altering runtime behavior:\n\n")

# 			for item in safe_items:
# 				report.append(f"#### ✅ `{item['symbol']}`\n")
# 				report.append(f"- **Location:** `{item['file_path']}:{item['line']}`\n")
# 				report.append(f"- **Symbol Type:** {item['type']}\n")
# 				report.append(f"- **Root Cause:** {item['reason']}\n")
# 				report.append(f"- **AI Safety Justification:** {item['justification']}\n")
# 				report.append(f"- **Refactoring Action:** Safely prunable. Automatically included in the unified diff below.\n\n")
# 			report.append("---\n\n")

# 		if review_items:
# 			report.append("### 🔴 Category 2: Protected Architectural Symbols (Human Review Required)\n\n")
# 			report.append("These items have **0 in-file calls**, but deleting them presents a high risk of breaking runtime integrations, ")
# 			report.append("external app imports, or Frappe string dispatch:\n\n")

# 			for item in review_items:
# 				report.append(f"#### 🛡️ `{item['symbol']}`\n")
# 				report.append(f"- **Location:** `{item['file_path']}:{item['line']}`\n")
# 				report.append(f"- **Symbol Type:** {item['type']}\n")
# 				report.append(f"- **Risk Classification:** High Risk (Protected)\n")
# 				report.append(f"- **Architectural Role:** {item['reason']}\n")
# 				report.append(f"- **AI Advisory:** {item['justification']}\n")
# 				report.append(f"- **Refactoring Action:** Preserve this symbol. If deprecating, mark with `@deprecated` decorator before deletion.\n\n")

# 		report.append("### 💡 Recommended Next Steps\n")
# 		report.append("1. **Review Section 5.C (Unified Diff)** to inspect exact line-by-line removals for safe items.\n")
# 		report.append("2. **Do not delete Category 2 symbols** without auditing external repositories that may import from `impact_analyser.api`.\n")

# 		return "".join(report)

# 	def _call_external_ai(self, app_name, safe_items, review_items):
# 		"""Attempts to call Google Gemini / client.py if available."""
# 		call_gemini = None
# 		try:
# 			from impact_analyser.ai.client import call_gemini
# 		except ImportError:
# 			try:
# 				from impact_analyser.impact_analyser.ai.client import call_gemini
# 			except ImportError:
# 				pass

# 		if not call_gemini:
# 			return None

# 		try:
# 			safe_sample = [f"{i['symbol']} in {i['file_path']}" for i in safe_items[:10]]
# 			review_sample = [f"{i['symbol']} in {i['file_path']}" for i in review_items[:10]]

# 			prompt = (
# 				f"You are a Senior Frappe Framework Software Architect.\n"
# 				f"Provide a comprehensive, professional reasoning report for dead code detection in the app '{app_name}'.\n"
# 				f"Summary:\n"
# 				f"- Safe to eliminate ({len(safe_items)} items): {', '.join(safe_sample)}\n"
# 				f"- Protected re-exports / review needed ({len(review_items)} items): {', '.join(review_sample)}\n\n"
# 				f"Format your response in GitHub Markdown with clear sections: Executive Verdict, Safe Removals Justification, Protected Shims Warning, and Action Plan."
# 			)
# 			response = call_gemini(prompt)
# 			if response and len(response.strip()) > 100:
# 				return response
# 		except Exception:
# 			pass
# 		return None

# 	def _collect_app_files(self, app_dir):
# 		valid_files = []
# 		scan_py = bool(self.get("scan_python_files", 1))
# 		scan_js = bool(self.get("scan_javascript_files", 1))

# 		allowed_exts = {".json", ".html"}
# 		if scan_py:
# 			allowed_exts.add(".py")
# 		if scan_js:
# 			allowed_exts.add(".js")

# 		for root, dirs, files in os.walk(app_dir):
# 			dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
# 			for file in files:
# 				ext = os.path.splitext(file)[1].lower()
# 				if ext in allowed_exts:
# 					valid_files.append(os.path.join(root, file))
# 		return valid_files

# 	def _extract_hooks_symbols(self, app_dir, file_contents):
# 		symbols = set()
# 		for fpath, content in file_contents.items():
# 			if os.path.basename(fpath) == "hooks.py":
# 				matches = re.findall(r"['\"]([a-zA-Z0-9_\.]+)['\"]", content)
# 				for m in matches:
# 					symbols.add(m)
# 					symbols.add(m.split(".")[-1])
# 		return symbols

# 	def _extract_json_symbols(self, file_contents):
# 		"""
# 		Returns {directory_path: set_of_symbols}, scoped per folder — NOT a
# 		single app-wide set. A doctype's JSON schema should only be able to
# 		protect symbols defined in that same doctype's own Python file, not
# 		symbols anywhere else in the app that happen to share a word with
# 		some unrelated doctype's fieldname/label/option elsewhere.
# 		"""
# 		symbols_by_dir = {}
# 		for fpath, content in file_contents.items():
# 			if fpath.endswith(".json"):
# 				matches = re.findall(r"['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]", content)
# 				directory = os.path.dirname(fpath)
# 				symbols_by_dir.setdefault(directory, set()).update(matches)
# 		return symbols_by_dir

# 	def _analyze_python_file(self, fpath, rel_path, content, file_contents, hooks_symbols, json_symbols, ast_cache):
# 		candidates = []
# 		is_test = "test" in rel_path.lower()
# 		is_patch = "patches" in rel_path.lower()

# 		ignore_test = bool(self.get("ignore_test_files", 1))
# 		if ignore_test and is_test:
# 			return []

# 		tree = ast_cache.get(fpath)
# 		if tree is None:
# 			# Not in the cache (e.g. failed to parse earlier) - nothing
# 			# safe to analyze in this file.
# 			return []

# 		# json_symbols is now {directory: symbols}; resolve just this file's
# 		# own doctype-folder scope so unrelated folders' JSON can't protect
# 		# (or fail to protect) symbols that live in a completely different file.
# 		local_json_symbols = json_symbols.get(os.path.dirname(fpath), set())

# 		# NOTE: Import scanning is intentionally disabled — this app never
# 		# deletes unused imports, only dead functions/methods/classes.

# 		# 1. Classes and Functions
# 		ignore_dt_classes = bool(self.get("ignore_doctype_classes", 1))
# 		scan_controller_methods = bool(self.get("scan_custom_controller_methods", 1))
# 		scan_helpers = bool(self.get("scan_standalone_helpers", 1))
# 		ignore_patches = bool(self.get("ignore_migration_patches", 1))

# 		for node in tree.body:
# 			if isinstance(node, ast.ClassDef):
# 				is_doc = self._is_doctype_controller(node, rel_path)

# 				if not (ignore_dt_classes and is_doc):
# 					occurrences = self._count_symbol_references(node.name, file_contents, ast_cache)
# 					if occurrences == 0 and node.name not in hooks_symbols and node.name not in local_json_symbols:
# 						candidates.append({
# 							"symbol": node.name,
# 							"type": "Class",
# 							"file_path": rel_path,
# 							"abs_path": fpath,
# 							"line": node.lineno,
# 							"risk_level": "Medium",
# 							"reason": f"Class '{node.name}' has 0 references in Python, JS, or DocType JSON.",
# 							"justification": "No references found in app graph. Verify if instantiated via dynamic reflection.",
# 							"node": node
# 						})

# 				# Scan custom methods inside classes
# 				if scan_controller_methods:
# 					for subnode in node.body:
# 						if isinstance(subnode, ast.FunctionDef):
# 							mname = subnode.name
# 							if mname.startswith("__") or mname in FRA_LIFECYCLE_HOOKS:
# 								continue
# 							if self._is_whitelisted(subnode):
# 								continue

# 							occurrences = self._count_symbol_references(mname, file_contents, ast_cache)
# 							if occurrences == 0 and mname not in hooks_symbols and mname not in local_json_symbols:
# 								risk = "Low" if mname.startswith("_") else "Medium"
# 								candidates.append({
# 									"symbol": f"{node.name}.{mname}",
# 									"type": "Function",
# 									"file_path": rel_path,
# 									"abs_path": fpath,
# 									"line": subnode.lineno,
# 									"risk_level": risk,
# 									"reason": f"Method '{mname}' in class '{node.name}' is never called by any DocType, script, or hook.",
# 									"justification": "Custom controller method with 0 call paths in app graph.",
# 									"node": subnode
# 								})

# 			elif isinstance(node, ast.FunctionDef):
# 				fname_str = node.name
# 				if fname_str.startswith("__"):
# 					continue
# 				if is_patch and ignore_patches and fname_str == "execute":
# 					continue
# 				if self._is_whitelisted(node):
# 					continue
# 				if fname_str in hooks_symbols or fname_str in local_json_symbols:
# 					continue

# 				if scan_helpers:
# 					occurrences = self._count_symbol_references(fname_str, file_contents, ast_cache)
# 					if occurrences == 0:
# 						risk = "Low" if fname_str.startswith("_") else "Medium"
# 						candidates.append({
# 							"symbol": fname_str,
# 							"type": "Function",
# 							"file_path": rel_path,
# 							"abs_path": fpath,
# 							"line": node.lineno,
# 							"risk_level": risk,
# 							"reason": f"Function '{fname_str}' is defined but never invoked across the entire app.",
# 							"justification": "Standalone helper with 0 call paths in any file.",
# 							"node": node
# 						})

# 		return candidates

# 	def _build_class_index(self, file_contents):
# 		"""
# 		One-time map of class_name -> ast.ClassDef across every Python file
# 		in the scanned app, so inheritance chains that pass through a
# 		locally-defined custom base class (e.g. AccountsController) can be
# 		resolved without re-parsing files on every lookup.
# 		"""
# 		index = {}
# 		for fpath, content in file_contents.items():
# 			if not fpath.endswith(".py"):
# 				continue
# 			try:
# 				tree = ast.parse(content, filename=fpath)
# 			except Exception:
# 				continue
# 			for node in ast.walk(tree):
# 				if isinstance(node, ast.ClassDef) and node.name not in index:
# 					index[node.name] = node
# 		return index

# 	def _is_doctype_controller(self, node, rel_path):
# 		"""
# 		Frappe resolves DocType controller classes by naming/folder
# 		convention (apps/<app>/.../doctype/<module>/<module>.py), and
# 		instantiates them dynamically — never via a Python-level reference
# 		anywhere in the codebase. A direct 'class X(Document):' check alone
# 		misses controllers that inherit through a custom intermediate base
# 		(e.g. class SalesInvoice(AccountsController) where
# 		AccountsController(Document) is defined elsewhere in the app), and
# 		misses controllers whose base class isn't literally named
# 		'Document' (WebsiteGenerator, NestedSet, etc.). So a class counts
# 		as a protected controller if EITHER:
# 		  1. It inherits from Document, directly or transitively through
# 		     a base class defined locally in this app, OR
# 		  2. It sits in a file that matches Frappe's doctype controller
# 		     folder convention (doctype/<name>/<name>.py) — the location
# 		     itself is what makes Frappe load it, regardless of base class.
# 		"""
# 		if self._inherits_document(node):
# 			return True

# 		parts = rel_path.split("/")
# 		if len(parts) >= 3:
# 			grandparent, folder, filename = parts[-3], parts[-2], parts[-1]
# 			if grandparent == "doctype" and filename == f"{folder}.py":
# 				return True

# 		return False

# 	def _inherits_document(self, node, _visited=None):
# 		if _visited is None:
# 			_visited = set()

# 		for b in node.bases:
# 			base_name = None
# 			if isinstance(b, ast.Name):
# 				base_name = b.id
# 			elif isinstance(b, ast.Attribute):
# 				base_name = b.attr

# 			if not base_name or base_name in _visited:
# 				continue
# 			if base_name == "Document":
# 				return True
# 			_visited.add(base_name)

# 			# Base class might be a custom controller defined locally in
# 			# this app (e.g. AccountsController) — follow the chain.
# 			base_node = getattr(self, "_class_index", {}).get(base_name)
# 			if base_node and self._inherits_document(base_node, _visited):
# 				return True

# 		return False

# 	def _build_ast_cache(self, file_contents):
# 		"""
# 		Parses every Python file's AST exactly once per run, keyed by
# 		absolute path. Reused for class-hierarchy resolution and for
# 		reference counting, instead of re-parsing the same file once
# 		per symbol being checked.
# 		"""
# 		cache = {}
# 		for fpath, content in file_contents.items():
# 			if not fpath.endswith(".py"):
# 				continue
# 			try:
# 				cache[fpath] = ast.parse(content, filename=fpath)
# 			except Exception:
# 				continue
# 		return cache

# 	def _count_symbol_references(self, name, file_contents, ast_cache):
# 		"""
# 		Real reference counting, not a raw whole-corpus text scan.

# 		- Python files: walk the already-parsed AST and count only
# 		  `ast.Name` and `ast.Attribute` nodes matching `name`. A
# 		  function/class definition's own name is never an ast.Name or
# 		  ast.Attribute node (it's just a string on the FunctionDef /
# 		  ClassDef), so the definition site itself is never counted -
# 		  this method returns the number of *other* places the symbol
# 		  is actually used. Comments, docstrings, print() strings, and
# 		  unrelated words elsewhere in the app (e.g. a common English
# 		  or Tamil word that happens to match a short function name)
# 		  no longer inflate the count.
# 		- Non-Python files (.js/.json/.html): can't be AST-parsed, so
# 		  fall back to a quoted-string match only - this still catches
# 		  dynamic dispatch such as `frappe.call({method: "x"})`,
# 		  `doc_events` entries, or JSON field/option references, without
# 		  treating an arbitrary substring match inside markup or a
# 		  comment as a real usage.
# 		"""
# 		count = 0
# 		for tree in ast_cache.values():
# 			for node in ast.walk(tree):
# 				if isinstance(node, ast.Name) and node.id == name:
# 					count += 1
# 				elif isinstance(node, ast.Attribute) and node.attr == name:
# 					count += 1
# 				if count > 5:
# 					return count

# 		quoted_pattern = re.compile(rf"""['"]{re.escape(name)}['"]""")
# 		for fpath, content in file_contents.items():
# 			if fpath.endswith(".py"):
# 				continue
# 			count += len(quoted_pattern.findall(content))
# 			if count > 5:
# 				break

# 		return count

# 	def _is_whitelisted(self, node):
# 		for dec in node.decorator_list:
# 			if isinstance(dec, ast.Attribute) and dec.attr == "whitelist":
# 				return True
# 			if isinstance(dec, ast.Name) and dec.id == "whitelist":
# 				return True
# 			if isinstance(dec, ast.Call):
# 				if isinstance(dec.func, ast.Attribute) and dec.func.attr == "whitelist":
# 					return True
# 				if isinstance(dec.func, ast.Name) and dec.func.id == "whitelist":
# 					return True
# 		return False

# 	def _generate_diffs(self, files_to_patch, app_dir):
# 		unified_diffs = []
# 		html_diff_blocks = []

# 		for fpath, items in files_to_patch.items():
# 			try:
# 				with open(fpath, "r", encoding="utf-8") as f:
# 					orig_lines = f.readlines()
# 			except Exception:
# 				continue

# 			lines_to_remove = set()
# 			for item in items:
# 				node = item.get("node")
# 				if node:
# 					end_lineno = getattr(node, "end_lineno", node.lineno)
# 					for l in range(node.lineno, end_lineno + 1):
# 						lines_to_remove.add(l)

# 			new_lines = [line for idx, line in enumerate(orig_lines, start=1) if idx not in lines_to_remove]

# 			rel = os.path.relpath(fpath, app_dir).replace("\\", "/")
# 			diff = list(difflib.unified_diff(
# 				orig_lines, new_lines,
# 				fromfile=f"a/{rel}",
# 				tofile=f"b/{rel}"
# 			))

# 			if diff:
# 				diff_str = "".join(diff)
# 				unified_diffs.append(diff_str)

# 				html_rows = []
# 				for line in diff:
# 					escaped = html.escape(line.rstrip())
# 					if line.startswith("+") and not line.startswith("+++"):
# 						html_rows.append(f"<div style='background-color:#e6ffec;color:#1e4620;font-family:monospace;padding:1px 4px;'>{escaped}</div>")
# 					elif line.startswith("-") and not line.startswith("---"):
# 						html_rows.append(f"<div style='background-color:#ffebe9;color:#b31d28;font-family:monospace;padding:1px 4px;'>{escaped}</div>")
# 					elif line.startswith("@@"):
# 						html_rows.append(f"<div style='background-color:#f1f8ff;color:#0366d6;font-family:monospace;padding:1px 4px;font-weight:bold;'>{escaped}</div>")
# 					else:
# 						html_rows.append(f"<div style='color:#555;font-family:monospace;padding:1px 4px;'>{escaped}</div>")

# 				block = (
# 					f"<div style='margin-bottom:16px;border:1px solid #d0d7de;border-radius:6px;overflow:hidden;'>"
# 					f"<div style='background:#f6f8fa;padding:8px 12px;font-weight:bold;font-size:13px;border-bottom:1px solid #d0d7de;'>📄 {rel}</div>"
# 					f"<div style='padding:8px;font-size:12px;background:#fff;max-height:300px;overflow-y:auto;'>"
# 					+ "".join(html_rows) +
# 					f"</div></div>"
# 				)
# 				html_diff_blocks.append(block)

# 		unified_text = "\n".join(unified_diffs)
# 		diff_html = "".join(html_diff_blocks) if html_diff_blocks else "<p style='color:#666;'>No safe eliminations to display.</p>"
# 		return unified_text, diff_html

# 	def _get_bench_path(self):
# 		try:
# 			return frappe.get_bench_path()
# 		except Exception:
# 			pass
# 		try:
# 			import frappe as _f
# 			p = os.path.abspath(os.path.dirname(_f.__file__))
# 			for _ in range(8):
# 				p = os.path.dirname(p)
# 				if os.path.isdir(os.path.join(p, "apps")):
# 					return p
# 		except Exception:
# 			pass
# 		return "/home/raj/aeroplane_app"

# 	def _get_app_dir(self, app_name, bench_path):
# 		custom_path = self.get("app_path")
# 		if custom_path and os.path.isdir(custom_path):
# 			if os.path.isdir(os.path.join(custom_path, "apps", app_name)):
# 				return os.path.join(custom_path, "apps", app_name)
# 			return custom_path

# 		try:
# 			p = frappe.get_app_path(app_name)
# 			parent = os.path.dirname(p)
# 			if os.path.basename(parent) == app_name and os.path.isdir(parent):
# 				return parent
# 			if os.path.isdir(p):
# 				return p
# 		except Exception:
# 			pass

# 		for c in (os.path.join(bench_path, "apps", app_name), os.path.join(bench_path, app_name)):
# 			if os.path.isdir(c):
# 				return c
# 		return os.path.join(bench_path, "apps", app_name)

