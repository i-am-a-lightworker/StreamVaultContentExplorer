from datetime import date
import unittest

from tests import load_app


REPORT_DATE = date(2026, 7, 25)


class QuestionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()

    def test_country_genre_and_score_filters_are_all_applied(self):
        _, result, plan = self.app["ask_streamvault"](
            "How many South Korean thriller titles have an audience score of at least 85?",
            REPORT_DATE,
        )
        self.assertIn("lower(country) IN (?)", plan["sql"])
        self.assertIn("lower(genre) IN (?)", plan["sql"])
        self.assertIn("audience_score >= ?", plan["sql"])
        self.assertTrue((result["Country"] == "South Korea").all())
        self.assertTrue((result["Genre"] == "Thriller").all())
        self.assertTrue((result["Audience Score"] >= 85).all())

    def test_acquisition_comparison_includes_only_requested_types(self):
        _, result, _ = self.app["ask_streamvault"](
            "Compare licensed, original, and exclusive content by average cost, audience score, critic score, and viewing hours.",
            REPORT_DATE,
        )
        self.assertEqual(set(result["Acquisition Type"]), {"Licensed", "Original", "Exclusive"})
        self.assertEqual(len(result), 3)
