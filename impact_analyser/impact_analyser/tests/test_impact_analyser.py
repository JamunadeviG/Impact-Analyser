# Copyright (c) 2026, Team Thendral and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from impact_analyser.ai.interpreter import _parse_json_response
from impact_analyser.scanner.file_scanner import _prepare_search_targets
from impact_analyser.scanner.validator import _verify_db_change


class TestImpactAnalyser(FrappeTestCase):
	def test_interpreter_json_parsing(self):
		"""Test robust JSON extraction from AI responses."""
		# Clean JSON
		res1 = _parse_json_response('{"app": "frappe"}')
		self.assertEqual(res1.get("app"), "frappe")

		# Wrapped in markdown
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

	def test_validator_db_check(self):
		"""Test DB existence check for change validation."""
		change_valid = {"doctype": "DocType", "name": "User"}
		self.assertTrue(_verify_db_change("DocType: User", change_valid))

		change_invalid = {"doctype": "DocType", "name": "ThisDoesNotExist12345"}
		self.assertFalse(_verify_db_change("DocType: ThisDoesNotExist12345", change_invalid))
