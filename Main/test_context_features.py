import unittest
from datetime import date, timedelta

from context_features import (distance_pct, format_gex_position, format_history_position,
                              format_sma_position, gex_position, history_position, sma_position)


def _rows(values, end=date(2026, 1, 30)):
    return [((end - timedelta(days=len(values) - 1 - i)).isoformat(), value) for i, value in enumerate(values)]


class ContextFeatureTests(unittest.TestCase):
    def test_distance_pct(self):
        self.assertAlmostEqual(distance_pct(110, 100), 10.0)
        self.assertAlmostEqual(distance_pct(90, 100), -10.0)
        self.assertIsNone(distance_pct(100, 0))
        self.assertIsNone(distance_pct("-", 100))
        self.assertIsNone(distance_pct(None, 100))

    def test_history_position_top_of_window(self):
        position = history_position(_rows(list(range(1, 101))), years=1, min_count=50)
        self.assertEqual(position["count"], 100)
        self.assertAlmostEqual(position["percentile"], 99.5)
        self.assertGreater(position["zscore"], 1.5)
        self.assertEqual(position["low"], 1)
        self.assertEqual(position["high"], 100)
        self.assertIn("en üst %10", format_history_position("VIX", position))

    def test_history_position_uses_only_trailing_window(self):
        old = [1000.0] * 200
        recent = [float(v) for v in range(1, 101)]
        rows = _rows(old + recent, end=date(2026, 1, 30))
        position = history_position(rows, years=0.2, min_count=50)
        self.assertLess(position["high"], 1000)

    def test_history_position_requires_minimum_count_and_ignores_bad_rows(self):
        self.assertIsNone(history_position(_rows([1.0] * 10), min_count=50))
        self.assertIsNone(history_position([]))
        rows = _rows([5.0] * 60) + [("bad", 1.0), ("2026-02-01", None)]
        position = history_position(rows, min_count=50)
        self.assertAlmostEqual(position["percentile"], 50.0)
        self.assertIsNone(position["zscore"])

    def test_sma_position(self):
        sma = {"20": {"value": 100}, "50": {"value": 95}, "200": {"value": 105}}
        position = sma_position(102, sma)
        self.assertAlmostEqual(position["distances"]["20"], 2.0)
        self.assertEqual(position["order"], "SMA50 < SMA200")
        text = format_sma_position(position)
        self.assertIn("SMA200'ün -2.86% altında", text)
        self.assertIsNone(format_sma_position(sma_position(102, {"200": {"value": None}})))

    def test_gex_position(self):
        position = gex_position(100, put_wall=95, call_wall=110, flip=102)
        self.assertAlmostEqual(position["put_wall"], -5.0)
        self.assertEqual(position["side_of_flip"], "below")
        self.assertTrue(position["inside_walls"])
        text = format_gex_position(position)
        self.assertIn("flip spota göre +2.00%", text)
        self.assertIn("spot flip'in altında", text)
        missing = gex_position(100, None, None, None)
        self.assertIsNone(format_gex_position(missing))


if __name__ == "__main__":
    unittest.main()
