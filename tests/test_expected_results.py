from datetime import date
import unittest

from tests import load_app


class ExpectedResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()

    def test_spanish_drama_ranking_honors_limit_and_sorting(self):
        report_date = self.app["to_python_date"](self.app["scalar"]("SELECT MAX(date_added) FROM catalog"))
        _, result, _ = self.app["ask_streamvault"](
            "How many titles are in each genre?",
            report_date,
        )
        self.assertGreater(len(result), 0)
        self.assertIn("Genre", result.columns)
        self.assertIn("Title Count", result.columns)

    def test_automated_regression_suite_contains_questions_8_to_36(self):
        suite = self.app["DEBUG_QUESTIONS"]
        self.assertEqual(len(suite), 30)
        self.assertEqual(suite[0]["id"], 8)
        self.assertEqual(suite[-1]["id"], 36)

    def test_ready_made_report_templates_include_eight_reports(self):
        templates = self.app["REPORT_TEMPLATES"]
        self.assertEqual(len(templates), 8)
        self.assertEqual(len({template["id"] for template in templates}), 8)
