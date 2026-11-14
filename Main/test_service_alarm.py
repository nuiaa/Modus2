import unittest
from unittest.mock import patch

import service


class ServiceAlarmTests(unittest.TestCase):
    def test_crossing_state_persists_without_notification(self):
        alarm = {'symbol': 'VIX Endeksi', 'cond_type': 'crossing_up',
                 'target_value': 20, 'last_seen_value': 15,
                 'is_active': True, 'triggered': False}

        class Fetcher:
            def fetch_current_metrics(self, required_names=None):
                return {'VIX Endeksi': 18}

        with patch.object(service, 'load_alarms', return_value=([alarm], 'alarms.json')), \
             patch.object(service, 'ServiceMarketFetcher', return_value=Fetcher()), \
             patch.object(service, 'save_alarms') as save, \
             patch.object(service.ServiceNotificationEngine, 'send_notification') as notify:
            service.check_and_trigger_alarms()

        self.assertEqual(alarm['last_seen_value'], 18)
        self.assertEqual(alarm['last_price'], 18)
        save.assert_called_once()
        notify.assert_not_called()

    def test_missing_observation_does_not_trigger(self):
        alarm = {'symbol': 'VIX Endeksi', 'cond_type': 'crossing_up',
                 'target_value': 20, 'last_seen_value': 15,
                 'is_active': True, 'triggered': False}

        class Fetcher:
            def fetch_current_metrics(self, required_names=None):
                return {}

        with patch.object(service, 'load_alarms', return_value=([alarm], 'alarms.json')), \
             patch.object(service, 'ServiceMarketFetcher', return_value=Fetcher()), \
             patch.object(service, 'save_alarms') as save, \
             patch.object(service.ServiceNotificationEngine, 'send_notification') as notify:
            service.check_and_trigger_alarms()

        self.assertEqual(alarm['last_seen_value'], 15)
        save.assert_not_called()
        notify.assert_not_called()

    def test_repeat_alarm_remains_active_after_prior_trigger(self):
        alarm = {'symbol': 'VIX Endeksi', 'cond_type': 'crossing_up',
                 'target_value': 20, 'last_seen_value': 19,
                 'trigger_mode': 'repeat', 'is_active': True, 'triggered': True}

        class Fetcher:
            def fetch_current_metrics(self, required_names=None):
                return {'VIX Endeksi': 21}

        with patch.object(service, 'load_alarms', return_value=([alarm], 'alarms.json')), \
             patch.object(service, 'ServiceMarketFetcher', return_value=Fetcher()), \
             patch.object(service, 'save_alarms') as save, \
             patch.object(service.ServiceNotificationEngine, 'send_notification') as notify:
            service.check_and_trigger_alarms()

        self.assertFalse(alarm['triggered'])
        self.assertTrue(alarm['is_active'])
        save.assert_called_once()
        notify.assert_called_once()


if __name__ == '__main__':
    unittest.main()
