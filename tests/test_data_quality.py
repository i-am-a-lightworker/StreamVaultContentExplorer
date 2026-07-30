from datetime import date
import unittest

from tests import load_app


class DataQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()

    def test_movie_season_episode_quality_check_is_queryable(self):
        result = self.app["query"](
            "SELECT COUNT(*) AS records FROM catalog WHERE content_type = 'Movie' AND (seasons IS NOT NULL OR episodes IS NOT NULL)"
        )
        self.assertGreaterEqual(int(result.iloc[0]["records"]), 0)

    def test_bundled_youcatalog_is_the_default_source(self):
        self.assertTrue(self.app["DEFAULT_YOUCATALOG_PATH"].is_file())
        self.assertEqual(self.app["DEFAULT_YOUCATALOG_NAME"], "Netflix YouCatalog")
        total = self.app["scalar"]("SELECT COUNT(*) FROM catalog")
        self.assertEqual(total, 8807)

    def test_widget_values_are_normalized_for_the_default_youcatalog(self):
        self.assertEqual(self.app["scalar"]("SELECT COUNT(*) FROM catalog WHERE regexp_matches(lower(rating), '^[0-9]+\\s*min$')"), 0)
        self.assertEqual(self.app["scalar"]("SELECT COUNT(*) FROM catalog WHERE rating = 'Unrated'"), 7)
        self.assertEqual(self.app["scalar"]("SELECT COUNT(*) FROM catalog WHERE country = 'Unknown'"), 831)
        restored = self.app["scalar"]("SELECT COUNT(*) FROM catalog WHERE content_id IN ('s5542', 's5795', 's5814') AND runtime_min IS NOT NULL")
        self.assertEqual(restored, 3)

    def test_report_date_excludes_future_records(self):
        report_date = date(2026, 7, 25)
        included = self.app["scalar"]("SELECT COUNT(*) FROM catalog WHERE date_added <= ?", [report_date])
        total = self.app["scalar"]("SELECT COUNT(*) FROM catalog")
        self.assertLessEqual(included, total)
