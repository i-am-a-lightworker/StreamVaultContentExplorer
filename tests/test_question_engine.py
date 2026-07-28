from datetime import date
import unittest

from tests import load_app


class QuestionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()
        cls.report_date = cls.app["to_python_date"](cls.app["scalar"]("SELECT MAX(date_added) FROM catalog"))

    def test_country_filter_is_applied_to_default_youcatalog(self):
        _, result, plan = self.app["ask_streamvault"](
            "How many titles are from the United States?",
            self.report_date,
        )
        self.assertIn("lower(country) IN (?)", plan["sql"])
        self.assertTrue((result["Country"] == "United States").all())

    def test_country_runtime_comparison_uses_populated_default_fields(self):
        _, result, _ = self.app["ask_streamvault"](
            "Compare average runtime by country.",
            self.report_date,
        )
        self.assertIn("Country", result.columns)
        self.assertIn("Average Runtime (min)", result.columns)
        self.assertGreater(len(result), 0)

    def test_completion_rate_for_named_title_returns_only_that_title(self):
        title = self.app["query"](
            """
            SELECT title FROM catalog
            WHERE date_added <= ? AND length(title) > 10
            GROUP BY title HAVING COUNT(*) = 1
            ORDER BY title LIMIT 1
            """,
            [self.report_date],
        ).iloc[0, 0]
        answer, result, plan = self.app["ask_streamvault"](
            f"What's the completion rate for {title}?",
            self.report_date,
        )
        self.assertEqual(plan["interpretation"], "Exact catalog title match")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["Title"], title)
        self.assertIn("Completion Rate", result.columns)
        self.assertNotIn("semantic search", answer.lower())
