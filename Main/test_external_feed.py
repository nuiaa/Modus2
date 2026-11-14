import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import requests
from external_feed import (AUCTION_URL, GPR_URL, JGB_URL, TGA_URL, ExternalMacroFeed, cross_metrics,
                           load_external_metrics, parse_auctions, parse_classic_gpr, parse_gpr, parse_jgb,
                           parse_tga)


NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
# The original five feeds; newer feeds have their own parser tests in test_extra_feeds.
CORE = {"ai_gpr", "auctions", "classic_gpr", "tga_daily", "jgb_daily"}
CSV = "Date,GPR_AI,GPR_OIL\n2026-09-01,90,30\n2026-10-01,100,40\n"


def auction(term, date, cover="2.5", tips="No"):
    return dict(originalSecurityTerm=term, competitiveAuctionCloseDate=date,
                bidToCoverRatio=cover, highYield="4.2", inflationProtected=tips)


AUCTIONS = [auction("10-Year", "2026-11-10T13:00:00"), auction("30-Year", "2026-11-12")]


TGA = {"data": [
    {"record_date": "2026-11-12", "account_type": "Treasury General Account (TGA) Closing Balance",
     "open_today_bal": "933127", "close_today_bal": "null"},
    {"record_date": "2026-11-10", "account_type": "Treasury General Account (TGA) Closing Balance",
     "open_today_bal": "912134", "close_today_bal": "null"},
    {"record_date": "2026-11-04", "account_type": "Treasury General Account (TGA) Closing Balance",
     "open_today_bal": "950000", "close_today_bal": "null"},
]}
JGB = ("Interest Rate (November 2026),,,,,(Unit : %)\n"
       "Date,1Y,2Y,10Y,30Y\n"
       "2026/11/11,1.6,1.861,2.840,3.990\n"
       "2026/11/12,1.6,1.857,2.841,3.974\n"
       ",,,,\n"
       "\"If you cannot download the latest csv data\",,,,\n")


def session():
    client = Mock()
    ust = Mock()
    ust.json.return_value = AUCTIONS
    tga = Mock()
    tga.json.return_value = TGA
    responses = {GPR_URL: Mock(text=CSV), AUCTION_URL: ust, TGA_URL: tga,
                 JGB_URL: Mock(content=JGB.encode("latin-1"))}
    client.get.side_effect = lambda url, **kwargs: responses.get(url, Mock(content=b"mock-xls"))
    return client


class ExternalFeedTests(unittest.TestCase):
    def setUp(self):
        # Mock binary workbook decoding, retaining xlrd's real Excel-date conversion.
        self.sheet = Mock(nrows=3)
        self.sheet.row_values.return_value = ["month", "GPR", "GPRT", "GPRA"]
        values = [["month", "GPR"], [46266.0, 100.0], [46296.0, 110.0]]
        self.sheet.cell_value.side_effect = lambda row, col: values[row][col]
        self.book = Mock(datemode=0)
        self.book.sheet_by_name.return_value = self.sheet
        self.workbook_patch = patch("xlrd.open_workbook", return_value=self.book)
        self.workbook_patch.start()
        self.addCleanup(self.workbook_patch.stop)

    def test_classic_xls_dates_and_change(self):
        rows = parse_classic_gpr(b"mock-xls")
        self.assertEqual(rows[0]["id"], "GPR_CLASSIC")
        self.assertEqual(rows[0]["date"], "2026-10-01")
        self.assertEqual(rows[0]["value"], 110)
        self.assertIn("+10.00", rows[0]["notes"])
        self.book.release_resources.assert_called()

    def test_classic_schema_error(self):
        self.sheet.row_values.return_value = ["month", "GPR_AI"]
        with self.assertRaisesRegex(ValueError, "schema"):
            parse_classic_gpr(b"mock-xls")

    def test_public_class_api(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = ExternalMacroFeed(directory, session()).fetch_metrics()
            self.assertTrue({"GPR_AI", "GPR_OIL", "AUCTION_BTC_10Y", "AUCTION_BTC_30Y"}.issubset({r["id"] for r in rows}))
            self.assertTrue(all({"id", "name", "value", "unit", "date", "source", "notes", "stale", "sync_error"}.issubset(r) for r in rows))

    def test_latest_valid_and_bom(self):
        rows = parse_gpr("\ufeff" + CSV + "2026-11-01,NaN,\n")
        self.assertEqual([row["value"] for row in rows], [100, 40])
        self.assertIn("distinct", rows[0]["notes"])

    def test_auctions_sort_exclude_tips_and_missing_results(self):
        data = AUCTIONS + [auction("10-Year", "2026-11-13", "9", "Yes"),
                           auction("10-Year", "2026-11-14", ""),
                           auction("10-Year", "2026-10-10", "3")]
        rows = parse_auctions(data)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["date"], "2026-11-10")
        self.assertEqual(rows[0]["value"], 2.5)

    def test_cache_ttl_and_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            client = session()
            rows = load_external_metrics(directory, client, NOW, only=CORE)
            self.assertEqual(len(rows), 11)
            self.assertFalse(any(row["stale"] for row in rows))
            cached_client = Mock()
            load_external_metrics(directory, cached_client, NOW + timedelta(hours=5), only=CORE)
            cached_client.get.assert_not_called()
            # Auctions expire at six hours while AI-GPR remains cached.
            failing = Mock()
            failing.get.side_effect = requests.Timeout("test timeout")
            rows = load_external_metrics(directory, failing, NOW + timedelta(hours=7), only=CORE)
            self.assertEqual(failing.get.call_count, 1)
            self.assertFalse(rows[0]["stale"])
            self.assertTrue(rows[2]["stale"])
            self.assertIn("Timeout", rows[2]["sync_error"])
            self.assertEqual(rows[2]["value"], 2.5)
            rows = load_external_metrics(directory, failing, NOW + timedelta(hours=25), only=CORE)
            self.assertTrue(all(row["stale"] for row in rows))

    def test_cold_failure_visible_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            client.get.side_effect = requests.ConnectionError("offline")
            rows = load_external_metrics(directory, client, NOW, only=CORE)
            self.assertEqual(len(rows), 11)
            self.assertTrue(all(row["value"] is None and row["stale"] and row["sync_error"] for row in rows))

    def test_schema_failure_uses_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            load_external_metrics(directory, session(), NOW, only=CORE)
            client = session()
            broken = Mock(text="Unexpected,Columns\n1,2")
            broken.json.return_value = {"error": "schema"}
            self.sheet.row_values.return_value = ["unexpected"]
            client.get.side_effect = lambda url, **kwargs: broken
            rows = load_external_metrics(directory, client, NOW + timedelta(days=1), only=CORE)
            self.assertTrue(all(row["sync_error"] for row in rows))
            self.assertEqual(rows[0]["value"], 100)


    def test_tga_reads_closing_balance_in_billions(self):
        rows = parse_tga(TGA)
        self.assertEqual(rows[0]["id"], "TGA_DAILY")
        self.assertEqual(rows[0]["date"], "2026-11-12")
        self.assertAlmostEqual(rows[0]["value"], 933.127)
        self.assertIn("+21.0", rows[0]["notes"])
        self.assertIn("2026-11-04", rows[0]["notes"])

    def test_tga_schema_error(self):
        with self.assertRaisesRegex(ValueError, "schema"):
            parse_tga({"error": "x"})
        with self.assertRaises(ValueError):
            parse_tga({"data": []})

    def test_jgb_latest_day_and_change(self):
        rows = {row["id"]: row for row in parse_jgb(JGB)}
        self.assertEqual(set(rows), {"JGB_2Y", "JGB_10Y", "JGB_30Y"})
        self.assertEqual(rows["JGB_10Y"]["value"], 2.841)
        self.assertEqual(rows["JGB_10Y"]["date"], "2026-11-12")
        self.assertIn("-1.6 baz puan", rows["JGB_30Y"]["notes"])

    def test_jgb_empty_month_raises_for_cache_fallback(self):
        with self.assertRaises(ValueError):
            parse_jgb("Interest Rate,,\nDate,2Y,10Y,30Y\n,,,\n")

    def test_cross_metrics_combine_daily_sources(self):
        fred = [{"id": "WALCL", "value": 6600.0, "date": "2026-11-11"},
                {"id": "RRPONTSYD", "value": 20.0, "date": "2026-11-12"},
                {"id": "DGS10", "value": 4.1, "date": "2026-11-12"}]
        external = parse_tga(TGA) + parse_jgb(JGB)
        rows = {row["id"]: row for row in cross_metrics(fred, external, NOW.date())}
        self.assertAlmostEqual(rows["NET_LIQ_DAILY_TGA"]["value"], 6600 - 933.127 - 20)
        self.assertAlmostEqual(rows["US_JP_10Y_DAILY"]["value"], 4.1 - 2.841)
        self.assertFalse(rows["US_JP_10Y_DAILY"]["stale"])
        self.assertIn("WALCL: 2026-11-11", rows["NET_LIQ_DAILY_TGA"]["notes"])
        self.assertEqual(rows["NET_LIQ_DAILY_TGA"]["group"], "Hazine ve likidite")

    def test_fed_pricing_from_futures_minus_effr(self):
        fred = [{"id": "EFFR", "value": 3.88, "date": "2026-11-12"}]
        external = [{"id": "ZQ_3M", "value": 3.63, "date": "2026-11-13"},
                    {"id": "ZQ_6M", "value": 3.38, "date": "2026-11-13"}]
        rows = {row["id"]: row for row in cross_metrics(fred, external, NOW.date())}
        self.assertAlmostEqual(rows["FED_PRICED_3M"]["value"], -25)
        self.assertAlmostEqual(rows["FED_PRICED_6M"]["value"], -50)
        self.assertEqual(rows["FED_PRICED_3M"]["unit"], "baz puan")

    def test_all_feeds_fail_safely_with_group_and_focus(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            client.get.side_effect = requests.ConnectionError("offline")
            rows = load_external_metrics(directory, client, NOW)
        ids = {row["id"] for row in rows}
        self.assertTrue({"COT_GOLD", "EIA_CRUDE", "COMEX_SILVER", "PCR_EQUITY", "FOMC_NEXT",
                         "ZQ_3M", "BTC_FUNDING", "STABLE_SUPPLY", "WTI_M1_M7"}.issubset(ids))
        self.assertTrue(all(row["value"] is None and row["group"] for row in rows))
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id["COT_GOLD"]["focus"], ("gold",))
        self.assertIsNone(by_id["FOMC_NEXT"]["focus"])

    def test_cross_metrics_missing_or_old_component(self):
        fred = [{"id": "DGS10", "value": 4.1, "date": "2026-10-01"}]
        rows = {row["id"]: row for row in cross_metrics(fred, parse_jgb(JGB), NOW.date())}
        self.assertIsNone(rows["NET_LIQ_DAILY_TGA"]["value"])
        self.assertTrue(rows["NET_LIQ_DAILY_TGA"]["stale"])
        self.assertTrue(rows["US_JP_10Y_DAILY"]["stale"])


if __name__ == "__main__":
    unittest.main()
