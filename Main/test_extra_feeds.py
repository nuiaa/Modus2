import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

import extra_feeds as feeds


def cot_row(code, day, long, short, oi=1000):
    return {"cftc_contract_market_code": code, "report_date_as_yyyy_mm_dd": day + "T00:00:00.000",
            "m_money_positions_long_all": str(long), "m_money_positions_short_all": str(short),
            "open_interest_all": str(oi)}


class CotTests(unittest.TestCase):
    def test_index_position_and_weekly_change(self):
        rows = [cot_row("088691", "2026-10-13", 100, 50),   # net 50 (low)
                cot_row("088691", "2026-10-20", 300, 50),   # net 250 (high)
                cot_row("088691", "2026-10-27", 200, 50),   # net 150
                cot_row("088691", "2026-11-03", 250, 50)]   # net 200
        result = feeds.parse_cot(rows, {"088691": ("COT_GOLD", "Altın", "Managed Money")}, "disagg")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["value"], 75.0)
        self.assertEqual(result[0]["date"], "2026-11-03")
        self.assertIn("+200 kontrat", result[0]["notes"])
        self.assertIn("haftalık değişim +50", result[0]["notes"])

    def test_bad_rows_skipped_and_empty_raises(self):
        rows = [cot_row("088691", "2026-11-03", "x", 1)]
        with self.assertRaises(ValueError):
            feeds.parse_cot(rows, {"088691": ("COT_GOLD", "Altın", "MM")}, "disagg")
        with self.assertRaises(ValueError):
            feeds.parse_cot({"error": 1}, {}, "disagg")

    def test_url_filters_codes_and_window(self):
        url = feeds.cot_url(feeds.COT_TFF_URL, {"13874A": None}, date(2026, 11, 14))
        self.assertIn("lev_money_positions_long", url)
        self.assertIn("13874A", url)
        self.assertIn("2023-", url)


class CboeTests(unittest.TestCase):
    def test_ratios(self):
        data = {"ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": "0.85"},
                           {"name": "EQUITY PUT/CALL RATIO", "value": "0.63"},
                           {"name": "MXEA PUT/CALL RATIO", "value": "0.00"}]}
        rows = {row["id"]: row for row in feeds.parse_cboe(data, date(2026, 11, 13))}
        self.assertEqual(set(rows), {"PCR_TOTAL", "PCR_EQUITY"})
        self.assertEqual(rows["PCR_EQUITY"]["value"], 0.63)

    def test_falls_back_to_previous_trading_day(self):
        good = Mock()
        good.json.return_value = {"ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": "0.9"}]}
        missing = Mock()
        missing.raise_for_status.side_effect = Exception("403")
        session = Mock()
        session.get.side_effect = lambda url, **kw: good if "2026-11-13" in url else missing
        rows = feeds.fetch_cboe(session, date(2026, 11, 15))  # Sunday
        self.assertEqual(rows[0]["date"], "2026-11-13")


FOMC_HTML = """
<h4>2026 FOMC Meetings</h4>
<div class="fomc-meeting__month col-xs-5"><strong>October</strong></div>
<div class="fomc-meeting__date col-xs-4">27-28</div>
<div class="fomc-meeting__month col-xs-5"><strong>December</strong></div>
<div class="fomc-meeting__date col-xs-4">8-9*</div>
<h4>2027 FOMC Meetings</h4>
<div class="fomc-meeting__month col-xs-5"><strong>January</strong></div>
<div class="fomc-meeting__date col-xs-4">26-27</div>
<div class="fomc-meeting__month col-xs-5"><strong>Apr/May</strong></div>
<div class="fomc-meeting__date col-xs-4">30-1</div>
"""


class FomcAndFuturesTests(unittest.TestCase):
    def test_next_meeting_and_sep_flag(self):
        meetings = feeds.parse_fomc(FOMC_HTML)
        self.assertIn((date(2027, 5, 1), False), meetings)
        metric = feeds.fomc_metric(meetings, date(2026, 11, 14))
        self.assertEqual(metric["value"], 25)
        self.assertIn("SEP", metric["notes"])
        self.assertIn("2027-01-27", metric["notes"])

    def test_schema_change(self):
        with self.assertRaises(ValueError):
            feeds.parse_fomc("<html></html>")

    def test_contract_symbols(self):
        self.assertEqual(feeds.add_months(date(2026, 11, 14), 3), (2027, 2))
        self.assertEqual(feeds.contract_symbol("ZQ", 2027, 2, "CBT"), "ZQG27.CBT")
        self.assertEqual(feeds.contract_symbol("CL", 2026, 12, "NYM"), "CLZ26.NYM")

    def test_oil_curve_rolls_after_expiry_window(self):
        requested = []

        def fake_close(session, symbol):
            requested.append(symbol)
            return date(2026, 11, 13), 80.0 if len(requested) == 1 else 75.0

        with patch.object(feeds, "yahoo_last_close", fake_close):
            row = feeds.fetch_oil_curve(None, date(2026, 11, 20))[0]
        self.assertEqual(requested, ["CLF27.NYM", "CLN27.NYM"])
        self.assertEqual(row["value"], 5.0)


class CryptoTests(unittest.TestCase):
    def test_bybit_funding_annualized(self):
        data = {"result": {"list": [{"fundingRate": "0.0001", "fundingIntervalHour": "8",
                                     "openInterestValue": "4755152422.98"}]}}
        rows = {row["id"]: row for row in feeds.parse_bybit(data, date(2026, 11, 14))}
        self.assertAlmostEqual(rows["BTC_FUNDING"]["value"], 0.0001 * 3 * 365 * 100)
        self.assertAlmostEqual(rows["BTC_OI"]["value"], 4.75515242298)

    def test_bybit_failure_falls_back_to_binance(self):
        bybit = Mock()
        bybit.json.return_value = {"retCode": 10001}
        binance = Mock()
        binance.json.return_value = {"lastFundingRate": "0.0002"}
        session = Mock()
        session.get.side_effect = lambda url, **kw: bybit if "bybit" in url else binance
        rows = feeds.fetch_btc_derivatives(session, date(2026, 11, 14))
        self.assertEqual(rows[0]["source"], "Binance BTCUSDT")

    def test_stablecoin_supply_sums_usd_pegs_only(self):
        data = {"peggedAssets": [
            {"pegType": "peggedUSD", "circulating": {"peggedUSD": 100e9},
             "circulatingPrevWeek": {"peggedUSD": 98e9}, "circulatingPrevMonth": {"peggedUSD": 90e9}},
            {"pegType": "peggedEUR", "circulating": {"peggedEUR": 5e9}},
        ]}
        row = feeds.parse_stablecoins(data, date(2026, 11, 14))[0]
        self.assertAlmostEqual(row["value"], 100)
        self.assertIn("+2.0", row["notes"])


class TextFeedTests(unittest.TestCase):
    def test_rss_keeps_recent_items_only(self):
        rss = b"""<rss><channel>
            <item><title>Fed holds rates &amp; signals patience</title><pubDate>Fri, 13 Nov 2026 19:00:00 GMT</pubDate></item>
            <item><title>Old story</title><pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        items = feeds.parse_rss(rss, "Fed", datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
        self.assertEqual([item["title"] for item in items], ["Fed holds rates & signals patience"])

    def test_week_calendar_high_impact_usd_from_today(self):
        xml = b"""<weeklyevents>
            <event><title>CPI m/m</title><country>USD</country><date>11-10-2026</date><time>1:30pm</time>
                   <impact>High</impact><forecast>0.3%</forecast><previous>0.6%</previous></event>
            <event><title>PPI m/m</title><country>USD</country><date>11-13-2026</date><time>1:30pm</time>
                   <impact>High</impact><forecast /><previous>1.3%</previous></event>
            <event><title>GDP</title><country>EUR</country><date>11-13-2026</date><time>10:00am</time>
                   <impact>High</impact></event>
        </weeklyevents>"""
        events = feeds.parse_week_calendar(xml, date(2026, 11, 12))
        self.assertEqual(events, ["2026-11-13 1:30pm PPI m/m, önceki 1.3%"])


def xlsx(rows):
    """Minimal xlsx: a disclaimer sheet and a data sheet using shared strings."""
    import io
    import zipfile
    strings, sheet_rows = [], []
    for index, row in enumerate(rows, 1):
        cells = []
        for column, value in zip("ABCDEFGHIJ", row):
            if isinstance(value, str):
                strings.append(value)
                cells.append(f'<c r="{column}{index}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                cells.append(f'<c r="{column}{index}"><v>{value}</v></c>')
        sheet_rows.append(f'<row r="{index}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(
            f"<si><t>{text}</t></si>" for text in strings) + "</sst>")
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData><row r="1"/></sheetData></worksheet>')
        archive.writestr("xl/worksheets/sheet2.xml", f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return buffer.getvalue()


class EtfHoldingTests(unittest.TestCase):
    def test_gld_tonnes_and_changes(self):
        content = xlsx([["Date", "Closing Price", "Tonnes of Gold in the Trust"],
                        ["12-Oct-2026", 350, 1054.2],
                        ["05-Nov-2026", 360, 1040.5],
                        ["11-Nov-2026", 365, 1041.1],
                        ["12-Nov-2026", 354.9, 1040.7]])
        row = feeds.parse_gld(content)[0]
        self.assertEqual(row["id"], "GLD_TONNES")
        self.assertEqual(row["value"], 1040.7)
        self.assertEqual(row["date"], "2026-11-12")
        self.assertIn("Günlük -0.4 ton, 1 hafta +0.2, 1 ay -13.5", row["notes"])

    def test_gld_schema_and_non_xlsx(self):
        with self.assertRaises(ValueError):
            feeds.parse_gld(xlsx([["Tarih", "Fiyat"], ["12-Nov-2026", 1]]))
        with self.assertRaises(ValueError):
            feeds.parse_gld(b"%PDF-1.5")

    def test_slv_from_escaped_page_json(self):
        page = ('<div data="{&quot;tonnes&quot;:{&quot;visible&quot;:true,&quot;label&quot;:&quot;Tonnes in Trust&quot;,'
                '&quot;formattedValue&quot;:&quot;15,684.52&quot;,&quot;formattedAsOfDate&quot;:&quot;Nov 13, 2026&quot;,'
                '&quot;name&quot;:&quot;tonnes&quot;}}"></div>')
        row = feeds.parse_slv(page)[0]
        self.assertEqual(row["value"], 15684.52)
        self.assertEqual(row["date"], "2026-11-13")
        with self.assertRaises(ValueError):
            feeds.parse_slv("<html>no data</html>")


class XlsParserTests(unittest.TestCase):
    def workbook(self, rows):
        sheet = Mock(nrows=len(rows))
        sheet.row_values.side_effect = lambda index: rows[index]
        sheet.cell_value.side_effect = lambda row, col: rows[row][col]
        book = Mock(datemode=0)
        book.sheet_by_name.return_value = sheet
        book.sheet_by_index.return_value = sheet
        return book

    def test_cme_registered_and_activity_date(self):
        rows = [["GOLD", "", "", "", "", "", "Report Date: 11/13/2026", "", ""],
                ["Troy Ounce", "", "", "", "", "", "Activity Date: 11/12/2026", "", ""],
                ["TOTAL REGISTERED", "", 14241501.0, 0, 0, 0, 0, 14220956.0, ""],
                ["TOTAL PLEDGED", "", 1676023.0, "", "", "", "", 1676023.0, ""],
                ["TOTAL ELIGIBLE", "", 8688689.0, 0, 0, 0, 0, 8683384.0, ""],
                ["COMBINED TOTAL", "", 22930190.0, 0, 0, 0, 0, 22904341.0, ""]]
        with patch("xlrd.open_workbook", return_value=self.workbook(rows)):
            row = feeds.parse_cme_stocks(b"x", "COMEX_GOLD", "Altın", "milyon ons", 1e6)
        self.assertAlmostEqual(row["value"], 14.220956)
        self.assertEqual(row["date"], "2026-11-12")
        self.assertIn("-0.021", row["notes"])
        self.assertIn("%62.1", row["notes"])

    def test_eia_weekly_change_and_seasonal_average(self):
        import xlrd
        start = xlrd.xldate.xldate_from_date_tuple((2021, 11, 12), 0)
        rows = [["Back", ""], ["Sourcekey", "WCESTUS1"], ["Date", "Stocks"]]
        # One observation per week for five years, constant 400 million barrels.
        rows += [[start + 7 * week, 400000.0] for week in range(0, 52 * 5 + 1)]
        rows[-1][1] = 420000.0
        with patch("xlrd.open_workbook", return_value=self.workbook(rows)):
            row = feeds.parse_eia(b"x", "EIA_CRUDE", "Ham petrol", "WCESTUS1")
        self.assertEqual(row["value"], 420.0)
        self.assertIn("+20.00", row["notes"])
        self.assertIn("ortalaması 400.0", row["notes"])


if __name__ == "__main__":
    unittest.main()
