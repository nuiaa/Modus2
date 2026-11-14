import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from market_trends import MarketTrendStore, _months_before


def point(day, value):
    return (datetime.combine(day, datetime.min.time(), timezone.utc).timestamp(), value)


class Feed:
    def __init__(self, points):
        self.points = points
        self.calls = []

    def observations(self, symbol, range_str):
        self.calls.append((symbol, range_str))
        return self.points


class TrendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.feed = Feed([])
        self.store = MarketTrendStore(os.path.join(self.temp.name, 'trends.db'), self.feed)

    def tearDown(self):
        self.temp.cleanup()

    def test_incremental_revision_and_failed_refresh(self):
        today = date.today()
        self.feed.points = [point(today, 100)]
        self.assertEqual(self.store.sync('A')['range'], '2y')
        self.feed.points = [point(today, 110)]
        self.assertEqual(self.store.sync('A')['range'], '1mo')
        self.feed.points = []
        self.assertFalse(self.store.sync('A')['ok'])
        summary = self.store.summary('A')
        self.assertEqual(summary['latest_close'], 110)
        self.assertEqual(summary['observation_count'], 1)
        self.assertIsNone(summary['returns']['1y']['value_pct'])
        self.assertIsNone(summary['sma']['20']['value'])
        self.assertFalse(summary['range_52w']['full_window'])
        json.dumps(summary, allow_nan=False)

    def test_exact_returns_sma_and_drawdown(self):
        today = date.today()
        self.feed.points = [point(today - timedelta(days=i), 100) for i in range(400)]
        self.feed.points += [point(today - timedelta(days=2), 200), point(today, 120)]
        self.store.sync('A')
        result = self.store.summary('A')
        for item in result['returns'].values():
            self.assertAlmostEqual(item['value_pct'], 20)
            self.assertEqual(item['gap_days'], 0)
        self.assertAlmostEqual(result['sma']['20']['value'], 106)
        self.assertGreater(result['volatility_20d_pct'], 0)
        self.assertEqual(result['range_52w']['high'], 200)
        self.assertAlmostEqual(result['range_52w']['drawdown_from_high_pct'], -40)
        self.assertAlmostEqual(result['range_52w']['max_drawdown_pct'], -50)
        self.assertTrue(result['range_52w']['full_window'])

    def test_flat_history_has_zero_realized_volatility(self):
        today = date.today()
        self.feed.points = [point(today - timedelta(days=i), 100) for i in range(30)]
        self.store.sync('A')
        self.assertEqual(self.store.summary('A')['volatility_20d_pct'], 0)

    def test_baseline_gap_and_no_future_baseline(self):
        today = date.today()
        target = _months_before(today, 1)
        self.feed.points = [point(target - timedelta(days=8), 80), point(target + timedelta(days=1), 90), point(today, 100)]
        self.store.sync('A')
        self.assertIsNone(self.store.summary('A')['returns']['1m']['value_pct'])
        self.feed.points = [point(target - timedelta(days=7), 80)]
        self.store.sync('A')
        item = self.store.summary('A')['returns']['1m']
        self.assertEqual(item['value_pct'], 25)
        self.assertEqual(item['gap_days'], 7)

    def test_invalid_values_and_parameterized_symbol(self):
        today = date.today()
        self.feed.points = [point(today, float('nan')), point(today, -1), point(today, 0), point(today + timedelta(days=1), 50)]
        self.assertFalse(self.store.sync('A')['ok'])
        self.feed.points = [point(today, 10)]
        symbol = "A'); DROP TABLE daily_closes;--"
        self.store.sync(symbol)
        self.assertEqual(self.store.summary(symbol)['latest_close'], 10)
        self.assertIsNone(self.store.summary('A')['latest_close'])

    def test_calendar_month_end_and_leap_year(self):
        self.assertEqual(_months_before(date(2024, 3, 31), 1), date(2024, 2, 29))
        self.assertEqual(_months_before(date(2024, 2, 29), 12), date(2023, 2, 28))

    def test_long_offline_interval_requests_backfill(self):
        self.feed.points = [point(date.today() - timedelta(days=80), 100)]
        self.store.sync('A')
        self.assertEqual(self.store.sync('A')['range'], '2y')
        self.assertTrue(self.store.summary('A')['stale'])


if __name__ == '__main__':
    unittest.main()
