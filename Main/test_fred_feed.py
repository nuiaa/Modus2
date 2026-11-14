import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta

from fred_feed import FredStore, required_series_for_names, mark_sync_errors


class Response:
    def __init__(self, body):
        self.content = body.encode('utf-8')

    def raise_for_status(self):
        pass


class FredFeedTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, 'macro.sqlite3')

    def tearDown(self):
        self.folder.cleanup()

    def test_initial_full_download_then_45_day_overlap_and_revision(self):
        calls = []
        bodies = [
            'observation_date,DFII10\n2026-11-01,2.10\n2026-11-10,2.20\n',
            'observation_date,DFII10\n2026-11-01,2.15\n2026-11-10,2.25\n2026-11-11,.\n',
        ]

        def get(url, params, timeout):
            calls.append((url, dict(params)))
            return Response(bodies.pop(0))

        store = FredStore(self.db_path, http_get=get)
        first = store.sync_series('DFII10')
        second = store.sync_series('DFII10')
        self.assertIsNone(first['start'])
        self.assertEqual(second['start'], '2026-09-26')
        self.assertNotIn('cosd', calls[0][1])
        self.assertEqual(calls[1][1]['cosd'], '2026-09-26')
        self.assertEqual(store.recent('DFII10')[-1], ('2026-11-10', 2.25))
        self.assertEqual(len(store.recent('DFII10')), 2)

    def test_revision_to_missing_removes_obsolete_value(self):
        bodies = ['observation_date,DFII10\n2026-11-01,2.10\n2026-11-10,2.20\n',
                  'observation_date,DFII10\n2026-11-01,.\n2026-11-10,2.25\n']
        store = FredStore(self.db_path, http_get=lambda url, params, timeout: Response(bodies.pop(0)))
        store.sync_series('DFII10')
        store.sync_series('DFII10')
        self.assertEqual(store.recent('DFII10'), [('2026-11-10', 2.25)])

    def test_daily_forward_fill_and_units(self):
        today = date.today()
        wednesday = (today - timedelta(days=2)).isoformat()
        yesterday = (today - timedelta(days=1)).isoformat()
        store = FredStore(self.db_path)
        rows = [
            ('WALCL', wednesday, 8_000_000),
            ('WTREGEN', wednesday, 700_000),
            ('RRPONTSYD', yesterday, 200),
            ('SOFR', yesterday, 4.10),
            ('EFFR', yesterday, 4.00),
        ]
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executemany('INSERT INTO observations VALUES (?,?,?)', rows)
        aligned = store.daily_forward_fill(('WALCL', 'WTREGEN', 'RRPONTSYD'))
        self.assertEqual(aligned[-1][0], yesterday)
        self.assertEqual(aligned[-1][1]['WALCL'][0], wednesday)
        metrics = {row['name']: row for row in store.metrics()}
        self.assertEqual(metrics['Net Likidite (yaklaşık)']['value'], 7100)
        self.assertAlmostEqual(metrics['SOFR - EFFR Farkı']['value'], 10)
        self.assertEqual(metrics['Fed Bilançosu (WALCL)']['value'], 8000)

    def test_monthly_and_quarterly_transforms(self):
        store = FredStore(self.db_path)
        rows = []
        for month in range(1, 13):
            rows.append(('PCEPILFE', f'2025-{month:02d}-01', 100 + month))
        rows.append(('PCEPILFE', '2026-01-01', 114))
        rows += [('PAYEMS', '2026-01-01', 160000), ('PAYEMS', '2026-02-01', 160125)]
        rows += [('GDPC1', '2025-01-01', 20000), ('GDPC1', '2025-04-01', 20200),
                 ('GDPC1', '2025-07-01', 20400), ('GDPC1', '2025-10-01', 20600),
                 ('GDPC1', '2026-01-01', 20800)]
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executemany('INSERT INTO observations VALUES (?,?,?)', rows)
        metrics = {row['name']: row for row in store.metrics()}
        self.assertAlmostEqual(metrics['Çekirdek PCE Yıllık Değişim']['value'],
                               (114 / 101 - 1) * 100)
        self.assertEqual(metrics['Tarım Dışı İstihdam Aylık Fark']['value'], 125)
        self.assertAlmostEqual(metrics['Reel GSYH Çeyreklik Yıllıklandırılmış Büyüme']['value'],
                               100 * ((20800 / 20600) ** 4 - 1))
        self.assertAlmostEqual(metrics['Reel GSYH Yıllık Büyüme']['value'], 4)

    def test_derived_alarm_dependencies(self):
        self.assertEqual(required_series_for_names({'Net Likidite (yaklaşık)'}),
                         {'WALCL', 'WTREGEN', 'RRPONTSYD'})
        metrics = [{'id': 'Net Likidite (yaklaşık)'}, {'id': 'DFII10'}]
        marked = mark_sync_errors(metrics, {'RRPONTSYD': 'HTTP 429'})
        self.assertEqual(marked[0]['sync_error'], 'RRPONTSYD')
        self.assertNotIn('sync_error', marked[1])

    def test_missing_calendar_period_does_not_use_older_row(self):
        store = FredStore(self.db_path)
        rows = [('PCEPILFE', '2025-01-01', 100), ('PCEPILFE', '2026-02-01', 110),
                ('PAYEMS', '2026-01-01', 160000), ('PAYEMS', '2026-03-01', 160300),
                ('GDPC1', '2025-01-01', 20000), ('GDPC1', '2025-07-01', 20300),
                ('GDPC1', '2026-01-01', 20600)]
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executemany('INSERT INTO observations VALUES (?,?,?)', rows)
        metrics = {row['name']: row for row in store.metrics()}
        self.assertIsNone(metrics['Çekirdek PCE Yıllık Değişim']['value'])
        self.assertIsNone(metrics['Tarım Dışı İstihdam Aylık Fark']['value'])
        self.assertIsNone(metrics['Reel GSYH Çeyreklik Yıllıklandırılmış Büyüme']['value'])
        self.assertAlmostEqual(metrics['Reel GSYH Yıllık Büyüme']['value'], 3)

    def test_rate_trend_uses_basis_points_and_dated_baseline(self):
        store = FredStore(self.db_path)
        rows = [('DFII10', '2026-09-30', 2.50), ('DFII10', '2026-10-01', 2.45),
                ('DFII10', '2026-10-30', 2.20), ('DFII10', '2026-11-01', 2.25)]
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executemany('INSERT INTO observations VALUES (?,?,?)', rows)
        comparison = store.trend_changes(['DFII10'])[0]['comparisons']['1m']
        self.assertEqual(comparison['baseline_date'], '2026-10-01')
        self.assertAlmostEqual(comparison['value'], -20)
        self.assertEqual(comparison['unit'], 'baz puan')

    def test_fiscal_and_japan_spreads_match_periods_and_units(self):
        store = FredStore(self.db_path)
        rows = [
            ('A091RC1Q027SBEA', '2026-04-01', 1200),
            ('A091RC1Q027SBEA', '2026-07-01', 1300),
            ('W006RC1Q027SBEA', '2026-04-01', 4000),
            ('GDP', '2025-07-01', 30000), ('GDP', '2026-07-01', 31500),
            ('DGS10', '2026-11-10', 4.25),
            ('IRLTLT01USM156N', '2026-09-01', 4.10),
            ('IRLTLT01USM156N', '2026-10-01', 4.20),
            ('IRLTLT01JPM156N', '2026-09-01', 1.80),
        ]
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executemany('INSERT INTO observations VALUES (?,?,?)', rows)
        metrics = {row['id']: row for row in store.metrics()}
        self.assertEqual(metrics['Faiz Ödemesi / Vergi Geliri']['date'], '2026-04-01')
        self.assertAlmostEqual(metrics['Faiz Ödemesi / Vergi Geliri']['value'], 30)
        self.assertAlmostEqual(metrics['Nominal GSYH Yıllık Büyüme']['value'], 5)
        self.assertAlmostEqual(metrics['ABD 10Y Faiz - Nominal Büyüme (r-g vekili)']['value'], -0.75)
        self.assertAlmostEqual(metrics['ABD-Japonya 10Y Faiz Farkı (aylık)']['value'], 2.30)
        self.assertEqual(metrics['ABD-Japonya 10Y Faiz Farkı (aylık)']['date'], '2026-09-01')

    def test_derived_liquidity_trend_retains_billion_dollar_units(self):
        store = FredStore(self.db_path)
        end = date.today() - timedelta(days=1)
        prior = end - timedelta(days=365)
        rows = [
            ('WALCL', prior.isoformat(), 8_000_000),
            ('WTREGEN', prior.isoformat(), 700_000),
            ('RRPONTSYD', prior.isoformat(), 200),
            ('WALCL', end.isoformat(), 8_100_000),
            ('WTREGEN', end.isoformat(), 650_000),
            ('RRPONTSYD', end.isoformat(), 150),
        ]
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executemany('INSERT INTO observations VALUES (?,?,?)', rows)
        metric = next(item for item in store.derived_trend_changes() if item['id'] == 'Net Likidite (yaklaşık)')
        self.assertEqual(metric['unit'], 'milyar USD')
        self.assertAlmostEqual(metric['value'], 7300)
        self.assertAlmostEqual(metric['comparisons']['1y']['value'], 200)


if __name__ == '__main__':
    unittest.main()
