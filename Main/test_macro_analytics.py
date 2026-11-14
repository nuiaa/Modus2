import unittest
from datetime import date, timedelta
from macro_analytics import dated_correlation, matched_ratio


class MacroAnalyticsTests(unittest.TestCase):
    def test_correlation_uses_dated_changes_not_levels(self):
        today = date.today()
        first, second = [], []
        a, b = 100.0, 100.0
        for i in range(92):
            day = (today - timedelta(days=91-i)).isoformat()
            step = 0.01 if i % 3 else -0.005
            a *= 1 + step
            b *= 1 - step
            first.append((day, a))
            second.append((day, b))
        result = dated_correlation(first, second)
        self.assertGreater(result["pairs"], 60)
        self.assertLess(result["r"], -0.99)
        self.assertIsNone(dated_correlation(first[:5], second[:5]))

    def test_copper_gold_ratio_has_matching_dates(self):
        today = date.today()
        copper = [((today - timedelta(days=i)).isoformat(), 4.0 if i else 5.0) for i in range(400)]
        gold = [((today - timedelta(days=i)).isoformat(), 2000.0) for i in range(400)]
        result = matched_ratio(copper, gold)
        self.assertAlmostEqual(result["value"], 0.0025)
        self.assertAlmostEqual(result["comparisons"]["1m"]["value_pct"], 25)
        self.assertAlmostEqual(result["comparisons"]["1y"]["value_pct"], 25)


if __name__ == "__main__":
    unittest.main()
