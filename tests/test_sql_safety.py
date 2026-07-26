from datetime import date
import unittest

from tests import load_app


class SqlSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()
        cls.report_date = date(2026, 7, 25)

    def test_read_only_catalog_query_with_report_date_is_allowed(self):
        sql = "SELECT title FROM catalog WHERE date_added <= DATE '2026-07-25' LIMIT 5"
        self.assertEqual(self.app["is_safe_catalog_sql"](sql, self.report_date), (True, ""))

    def test_mutating_or_multi_statement_sql_is_rejected(self):
        sql = "SELECT title FROM catalog WHERE date_added <= DATE '2026-07-25'; DELETE FROM catalog"
        safe, reason = self.app["is_safe_catalog_sql"](sql, self.report_date)
        self.assertFalse(safe)
        self.assertIn("unsupported", reason.lower())

    def test_query_without_report_date_is_rejected(self):
        safe, reason = self.app["is_safe_catalog_sql"]("SELECT title FROM catalog", self.report_date)
        self.assertFalse(safe)
        self.assertIn("report date", reason.lower())
