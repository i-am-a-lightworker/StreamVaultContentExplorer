from datetime import date
import time
import unittest

from tests import load_app


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()

    def test_simple_question_completes_within_reasonable_budget(self):
        started = time.perf_counter()
        _, result, _ = self.app["ask_streamvault"](
            "Show the 10 licenses expiring in the next 30 days with the highest viewing hours.",
            date(2026, 7, 25),
        )
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 5.0)
        self.assertLessEqual(len(result), 10)
