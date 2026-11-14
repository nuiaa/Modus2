import unittest
from urllib.parse import unquote

from market_feed import YahooFeed, compute_dynamics


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status != 200:
            raise __import__('requests').HTTPError(str(self.status))

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.headers = {}

    def get(self, url, **kwargs):
        return self.responses[unquote(url.rsplit('/', 1)[-1])]


def chart(stamps, closes):
    return {'chart': {'result': [{'timestamp': stamps,
                                  'indicators': {'quote': [{'close': closes}]}}],
                      'error': None}}


class YahooFeedTests(unittest.TestCase):
    def test_null_and_invalid_closes_keep_timestamps_aligned(self):
        session = FakeSession({'A': FakeResponse(chart([10, 20, 30], [1, None, 3]))})
        self.assertEqual(YahooFeed(session).observations('A'), [(10, 1.0), (30, 3.0)])

    def test_ratio_uses_common_dates(self):
        day = 86400
        session = FakeSession({
            'A': FakeResponse(chart([day, 2 * day, 3 * day], [10, 100, 30])),
            'B': FakeResponse(chart([day, 3 * day], [2, 3])),
        })
        result = YahooFeed(session).ratio_change('A', 'B')
        self.assertEqual(result['value'], 10)
        self.assertEqual(result['change_pct'], 100)

    def test_combined_uses_common_dates(self):
        day = 86400
        session = FakeSession({
            'A': FakeResponse(chart([day, 2 * day, 3 * day], [10, 100, 30])),
            'B': FakeResponse(chart([day, 3 * day], [2, 3])),
        })
        result = YahooFeed(session).combined(('A', 'B'), lambda v: v['A'] - v['B'])
        self.assertEqual(result['value'], 27)
        self.assertEqual(result['previous'], 8)
        self.assertEqual(result['timestamp'], 3 * day)

    def test_combined_missing_leg_is_unavailable(self):
        session = FakeSession({'A': FakeResponse(chart([86400], [1])), 'B': FakeResponse({}, 429)})
        self.assertIsNone(YahooFeed(session).combined(('A', 'B'), lambda v: v['A'] / v['B']))

    def test_dynamics_crack_spread_and_breadth(self):
        day = 86400
        session = FakeSession({
            'CL=F': FakeResponse(chart([day, 2 * day], [80, 90])),
            'RB=F': FakeResponse(chart([day, 2 * day], [2.5, 2.5])),
            'HO=F': FakeResponse(chart([day, 2 * day], [3.0, 3.0])),
            'RSP': FakeResponse(chart([day, 2 * day], [100, 110])),
            'SPY': FakeResponse(chart([day, 2 * day], [400, 400])),
        })
        result = compute_dynamics(YahooFeed(session), {'crack_321', 'breadth_rsp_spy'})
        # (2*2.5*42 + 3.0*42 - 3*90) / 3 = 22.0; previous day 32.0
        self.assertAlmostEqual(result['crack_321']['value'], 22.0)
        self.assertIn("-10.00 günlük", result['crack_321']['display'])
        self.assertAlmostEqual(result['breadth_rsp_spy']['value'], 10.0)
        self.assertEqual(result['breadth_rsp_spy']['tone'], 1)

    def test_dynamics_vix_ratio_tone(self):
        day = 86400
        session = FakeSession({
            '^VIX9D': FakeResponse(chart([day], [30])),
            '^VIX': FakeResponse(chart([day], [20])),
        })
        result = compute_dynamics(YahooFeed(session), {'vix_short_term'})['vix_short_term']
        self.assertAlmostEqual(result['value'], 1.5)
        self.assertEqual(result['tone'], -1)
        self.assertEqual(result['display'], "1.500")

    def test_rejected_chart_is_unavailable(self):
        session = FakeSession({'A': FakeResponse({}, 429)})
        self.assertIsNone(YahooFeed(session).latest('A'))


if __name__ == '__main__':
    unittest.main()
