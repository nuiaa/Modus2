import os
import tempfile
import time
import unittest
from datetime import date, datetime, timezone

from alarm_logic import evaluate_alarm, next_notification_id, observe, read_alarms, save_changes, write_alarms
from gex import gamma_flip, net_gex, us_market_close_utc, years_to_expiry


class AlarmRuleTests(unittest.TestCase):
    def test_zero_target_crossing_triggers(self):
        alarm = {'symbol': '10Y-2Y', 'cond_type': 'crossing', 'target_value': 0.0, 'last_seen_value': -0.05}
        self.assertTrue(evaluate_alarm(alarm, 0.02)[0])

    def test_first_check_near_negative_target(self):
        alarm = {'symbol': 'VIX Eğrisi', 'cond_type': 'crossing', 'target_value': -2.0}
        self.assertTrue(evaluate_alarm(alarm, -2.005)[0])
        self.assertFalse(evaluate_alarm(alarm, -1.0)[0])

    def test_gamma_flip_uses_live_or_recent_stored_levels(self):
        alarm = {'symbol': 'SPX', 'cond_type': 'gamma_flip', 'last_seen_value': 5010}
        self.assertTrue(evaluate_alarm(alarm, 4990, {'flip': 5000})[0])
        alarm['gex_levels'] = {'flip': 5000, 'updated_at': time.time() - 3600}
        self.assertTrue(evaluate_alarm(alarm, 4990)[0])
        alarm['gex_levels']['updated_at'] = time.time() - 3 * 86400
        self.assertFalse(evaluate_alarm(alarm, 4990)[0])

    def test_wall_does_not_repeat_while_inside_zone(self):
        alarm = {'symbol': 'SPX', 'cond_type': 'put_wall', 'last_seen_value': 4980, 'trigger_mode': 'every'}
        self.assertFalse(evaluate_alarm(alarm, 4970, {'put_wall': 5000})[0])

    def test_once_alarm_deactivates(self):
        alarm = {'trigger_mode': 'once', 'is_active': True}
        observe(alarm, 1.0, True)
        self.assertTrue(alarm['triggered'])
        self.assertFalse(alarm['is_active'])

    def test_notification_ids_are_distinct(self):
        self.assertEqual(len({next_notification_id() for _ in range(50)}), 50)


class AlarmFileTests(unittest.TestCase):
    def test_service_save_keeps_alarm_added_by_app(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'alarms.json')
            write_alarms(path, [{'id': 'a', 'last_price': 1}])
            service_copy = read_alarms(path)
            write_alarms(path, read_alarms(path) + [{'id': 'b'}])  # app adds an alarm meanwhile
            service_copy[0]['last_price'] = 2
            save_changes(path, service_copy, {'a': {'last_price': 2}})
            saved = read_alarms(path)
        self.assertEqual([a['id'] for a in saved], ['a', 'b'])
        self.assertEqual(saved[0]['last_price'], 2)


class GexTests(unittest.TestCase):
    def test_market_close_respects_us_dst(self):
        self.assertEqual(us_market_close_utc(date(2026, 7, 17)).hour, 20)
        self.assertEqual(us_market_close_utc(date(2026, 12, 18)).hour, 21)

    def test_expiry_counts_to_close_not_midnight(self):
        expiry = datetime(2026, 7, 17, tzinfo=timezone.utc).timestamp()
        now = datetime(2026, 7, 17, 14, tzinfo=timezone.utc)
        self.assertAlmostEqual(years_to_expiry(expiry, now) * 365.25 * 24, 6.0)

    def test_flip_between_put_and_call_gamma(self):
        positions = [(95.0, 0.2, 1000, -1), (105.0, 0.2, 1000, 1)]
        flip = gamma_flip(positions, 100.0, 30 / 365, 0.04, 100, 0.06)
        self.assertIsNotNone(flip)
        self.assertLess(net_gex(positions, flip - 1, 30 / 365, 0.04, 100), 0)
        self.assertGreater(net_gex(positions, flip + 1, 30 / 365, 0.04, 100), 0)


if __name__ == '__main__':
    unittest.main()
