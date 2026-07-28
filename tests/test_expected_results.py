from datetime import date
import unittest

from tests import load_app


class ExpectedResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()

    def test_spanish_drama_ranking_honors_limit_and_sorting(self):
        _, result, _ = self.app["ask_streamvault"](
            "Show the 15 Spanish-language dramas with the highest viewing hours.",
            date(2026, 7, 25),
        )
        self.assertEqual(len(result), 15)
        self.assertTrue((result["Language"] == "Spanish").all())
        self.assertTrue((result["Genre"] == "Drama").all())
        self.assertTrue(result["Viewing Hours"].is_monotonic_decreasing)

    def test_automated_regression_suite_contains_questions_8_to_36(self):
        suite = self.app["DEBUG_QUESTIONS"]
        self.assertEqual(len(suite), 30)
        self.assertEqual(suite[0]["id"], 8)
        self.assertEqual(suite[-1]["id"], 36)

    def test_ready_made_report_templates_include_eight_reports(self):
        templates = self.app["REPORT_TEMPLATES"]
        self.assertEqual(len(templates), 8)
        self.assertEqual(len({template["id"] for template in templates}), 8)
