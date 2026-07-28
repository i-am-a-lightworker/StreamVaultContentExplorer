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

    def test_completion_rate_for_named_title_returns_only_that_title(self):
        title = self.app["query"](
            "SELECT title FROM catalog WHERE date_added <= ? ORDER BY title LIMIT 1",
            [REPORT_DATE],
        ).iloc[0, 0]
        answer, result, plan = self.app["ask_streamvault"](
            f"What's the completion rate for {title}?",
            REPORT_DATE,
        )
        self.assertEqual(plan["interpretation"], "Exact catalog title match")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["Title"], title)
        self.assertIn("Completion Rate", result.columns)
        self.assertNotIn("semantic search", answer.lower())
