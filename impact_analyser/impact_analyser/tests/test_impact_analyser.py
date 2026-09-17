# Copyright (c) 2026, Team Thendral and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from impact_analyser.ai.interpreter import _parse_json_response
from impact_analyser.scanner.file_scanner import _prepare_search_targets, scan_files
from impact_analyser.scanner.db_scanner import find_db_usages
from impact_analyser.scanner.validator import _verify_db_change
from impact_analyser.impact_analyser.orchestrator import _mock_verified_changes


class TestImpactAnalyser(FrappeTestCase):
	def test_interpreter_json_parsing(self):
		"""Test robust JSON extraction from AI responses."""
		res1 = _parse_json_response('{"app": "frappe"}')
		self.assertEqual(res1.get("app"), "frappe")

		raw = "Here is the result:\n```json\n{\"app\": \"erpnext\", \"doctype\": \"Sales Invoice\"}\n```\nDone."
		res2 = _parse_json_response(raw)
		self.assertEqual(res2.get("app"), "erpnext")
		self.assertEqual(res2.get("doctype"), "Sales Invoice")

	def test_scanner_target_preparation(self):
		"""Test search targets token generation."""
		target = {
			"doctype": "Sales Invoice",
			"fields": ["grand_total", "total_taxes"],
			"functions": ["validate_taxes"],
		}
		search_targets = _prepare_search_targets(target)

		self.assertIn("Sales Invoice", search_targets["all_tokens"])
		self.assertIn("sales_invoice", search_targets["all_tokens"])
		self.assertIn("tabSales Invoice", search_targets["all_tokens"])
		self.assertIn("grand_total", search_targets["all_tokens"])
		self.assertIn("validate_taxes", search_targets["all_tokens"])

	def test_file_scanner_returns_hits_with_severity(self):
		"""Test file scanner returns non-empty hits with High/Medium/Low severity ratings."""
		target = {
			"doctype": "Impact Analysis Run",
			"fields": ["status", "scan_report"],
			"functions": [],
		}
		hits = scan_files("impact_analyser", target)
		self.assertTrue(len(hits) > 0, "File scanner should find hits for Impact Analysis Run")

		for hit in hits:
			self.assertIn("file", hit)
			self.assertIn("line", hit)
			self.assertIn("snippet", hit)
			self.assertIn("severity", hit)
			self.assertIn(hit["severity"], ("High", "Medium", "Low"))
			self.assertEqual(hit["source"], "File")

	def test_db_scanner_returns_hits_with_metadata(self):
		"""Test DB scanner queries customizations and returns structured hits."""
		target = {
			"doctype": "Airplane Flight",
			"fields": ["status"],
			"functions": [],
		}
		hits = find_db_usages(target)
		linked_hits = [h for h in hits if h.get("usage_type") == "Linked DocType"]
		self.assertTrue(len(linked_hits) > 0, "DB scanner should find Airplane Ticket linking to Airplane Flight")

		for hit in hits:
			self.assertIn("doctype", hit)
			self.assertIn("name", hit)
			self.assertIn("reference_type", hit)
			self.assertIn("severity", hit)
			self.assertEqual(hit["source"], "Database")

	def test_mock_verified_changes_preserves_severity(self):
		"""Test _mock_verified_changes preserves severity from scan report."""
		scan_report = {
			"file_hits": [
				{"file": "test.py", "line": 10, "snippet": "x = 1", "severity": "High", "usage_type": "Test"},
				{"file": "read.py", "line": 5, "snippet": "print(x)", "severity": "Low", "usage_type": "Read"},
			],
			"db_hits": [
				{"doctype": "Server Script", "name": "SS1", "snippet": "val", "severity": "High", "usage_type": "Script"},
			],
		}
		changes = _mock_verified_changes(scan_report)
		self.assertEqual(len(changes), 3)
		self.assertEqual(changes[0]["impact"], "High")
		self.assertEqual(changes[1]["impact"], "Low")
		self.assertEqual(changes[2]["impact"], "High")

	def test_validator_db_check(self):
		"""Test DB existence check for change validation."""
		change_valid = {"doctype": "DocType", "name": "User"}
		self.assertTrue(_verify_db_change("DocType: User", change_valid))

		change_invalid = {"doctype": "DocType", "name": "ThisDoesNotExist12345"}
		self.assertFalse(_verify_db_change("DocType: ThisDoesNotExist12345", change_invalid))
