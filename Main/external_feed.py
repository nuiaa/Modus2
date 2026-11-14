"""Small, cached official feeds; no credentials or auction-tail estimates."""
import csv
import io
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

import extra_feeds

GPR_URL = "https://www.matteoiacoviello.com/ai_gpr_files/ai_gpr_data_monthly.csv"
GPR_CLASSIC_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
AUCTION_URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json"
# Daily Treasury Statement: since 2022 the TGA closing balance row carries its value in
# ``open_today_bal`` (``close_today_bal`` is "null"); amounts are millions of USD.
TGA_URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/"
           "operating_cash_balance?filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Closing%20Balance"
           "&fields=record_date,account_type,open_today_bal,close_today_bal&sort=-record_date&page%5Bsize%5D=15")
# Japanese Ministry of Finance constant-maturity JGB yields for the current month.
JGB_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"


def _date(value):
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m", "%Y%m", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite observation")
    return number


def _metric(key, name, value, unit, date, source, notes):
    return dict(id=key, name=name, value=value, unit=unit, date=date,
                source=source, notes=notes, stale=False, sync_error=None)


def parse_gpr(text):
    rows = []
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not {"Date", "GPR_AI", "GPR_OIL"}.issubset(reader.fieldnames or []):
        raise ValueError("AI-GPR CSV schema changed")
    for row in reader:
        try:
            rows.append((_date(row["Date"]), row))
        except (ValueError, TypeError):
            continue
    result = []
    for column, name in (("GPR_AI", "AI Jeopolitik Risk Endeksi"), ("GPR_OIL", "AI Petrol Jeopolitik Risk Endeksi")):
        for date, row in sorted(rows, key=lambda item: item[0], reverse=True):
            try:
                value = _number(row[column])
            except (ValueError, TypeError):
                continue
            result.append(_metric(column, name, value, "endeks", date, GPR_URL,
                "Iacoviello–Tong AI-GPR (2026), monthly; distinct from the classic Caldara–Iacoviello GPR. CC BY; observations may be revised."))
            break
        else:
            raise ValueError("No valid observation for " + column)
    return result


def parse_classic_gpr(content):
    """Read the publisher's binary XLS; never substitute the AI-based index."""
    try:
        import xlrd
    except ImportError as exc:
        raise ValueError("Classic GPR requires xlrd") from exc
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
    except (xlrd.XLRDError, OSError, TypeError) as exc:
        raise ValueError("Invalid classic GPR XLS: " + str(exc)) from exc
    try:
        sheet = book.sheet_by_name("Sheet1")
        headers = [str(cell).strip() for cell in sheet.row_values(0)]
        if not {"month", "GPR"}.issubset(headers):
            raise ValueError("Classic GPR XLS schema changed")
        month_col, value_col = headers.index("month"), headers.index("GPR")
        observations = {}
        for row_index in range(1, sheet.nrows):
            try:
                date = xlrd.xldate_as_datetime(sheet.cell_value(row_index, month_col), book.datemode).date()
                value = _number(sheet.cell_value(row_index, value_col))
                observations[date] = value
            except (ValueError, TypeError, OverflowError):
                continue
        if not observations:
            raise ValueError("No valid classic GPR observation")
        date = max(observations)
        value = observations[date]
        notes = ("Classic Caldara–Iacoviello GPR, monthly; Caldara and Iacoviello (2022), "
                 "Measuring Geopolitical Risk, American Economic Review 112(4), 1194–1225. "
                 "https://www.matteoiacoviello.com/gpr.htm; CC BY; observations may be revised.")
        previous_month = date.replace(day=1).toordinal() - 1
        previous_date = date.fromordinal(previous_month).replace(day=1)
        if previous_date in observations:
            notes += " 1-month change: {:+.2f} index points.".format(value - observations[previous_date])
        return [_metric("GPR_CLASSIC", "Klasik Jeopolitik Risk Endeksi (Caldara–Iacoviello)",
                        value, "endeks", date.isoformat(), GPR_CLASSIC_URL, notes)]
    except (xlrd.XLRDError, IndexError) as exc:
        raise ValueError("Classic GPR XLS schema changed") from exc
    finally:
        book.release_resources()


def parse_auctions(data):
    if not isinstance(data, list):
        raise ValueError("Treasury auction schema changed")
    result = []
    for term in ("10-Year", "30-Year"):
        eligible = []
        for row in data:
            if row.get("originalSecurityTerm") != term:
                continue
            # Require an explicit negative flag, avoiding accidental TIPS inclusion.
            if str(row.get("inflationProtected", "")).lower() not in ("no", "false", "n"):
                continue
            try:
                date = _date(row["competitiveAuctionCloseDate"])
                cover = _number(row["bidToCoverRatio"])
                high_yield = _number(row["highYield"])
                if cover <= 0:
                    continue
                eligible.append((date, cover, high_yield))
            except (ValueError, TypeError, KeyError):
                continue
        if not eligible:
            raise ValueError("No valid nominal " + term + " auction")
        date, cover, high_yield = max(eligible, key=lambda item: item[0])
        key = term.split("-")[0]
        notes = "Latest nominal original " + term + " Treasury auction; includes reopenings, excludes TIPS. High yield is the auction stop-out yield, not an auction tail."
        result.extend([
            _metric("AUCTION_BTC_" + key + "Y", key + "Y Hazine ihalesi bid-to-cover", cover, "oran", date, AUCTION_URL, notes),
            _metric("UST_" + key + "Y_HIGH_YIELD", key + "Y Hazine ihalesi en yüksek kabul faizi", high_yield, "%", date, AUCTION_URL, notes),
        ])
    return result


def parse_tga(data):
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Treasury DTS schema changed")
    balances = {}
    for row in rows:
        if "Closing Balance" not in str(row.get("account_type", "")):
            continue
        raw = row.get("close_today_bal")
        if raw in (None, "", "null"):
            raw = row.get("open_today_bal")
        try:
            balances[_date(row["record_date"])] = _number(raw) / 1000
        except (ValueError, TypeError, KeyError):
            continue
    if not balances:
        raise ValueError("No valid TGA closing balance")
    days = sorted(balances)
    latest = days[-1]
    notes = ("Daily Treasury Statement kapanış bakiyesi (milyar USD); "
             "FRED WTREGEN haftalık ortalamasının günlük karşılığı.")
    if len(days) > 1:
        notes += f" Önceki iş günü ({days[-2]}) farkı {balances[latest] - balances[days[-2]]:+,.1f} milyar USD."
    week = [day for day in days
            if (datetime.fromisoformat(latest) - datetime.fromisoformat(day)).days >= 7]
    if week:
        notes += f" {week[-1]} tarihine göre fark {balances[latest] - balances[week[-1]]:+,.1f} milyar USD."
    notes += " TGA artışı piyasadan likidite çeker."
    return [_metric("TGA_DAILY", "Hazine Genel Hesabı (günlük kapanış)", balances[latest],
                    "milyar USD", latest, "https://fiscaldata.treasury.gov (DTS)", notes)]


def parse_jgb(text):
    lines = text.splitlines()
    header_index = next((i for i, line in enumerate(lines) if line.startswith("Date,")), None)
    if header_index is None:
        raise ValueError("MOF JGB CSV schema changed")
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    if not {"2Y", "10Y", "30Y"}.issubset(reader.fieldnames or []):
        raise ValueError("MOF JGB CSV schema changed")
    rows = []
    for item in reader:
        try:
            day = datetime.strptime((item.get("Date") or "").strip(), "%Y/%m/%d").date().isoformat()
            rows.append((day, {tenor: _number(item[tenor]) for tenor in ("2Y", "10Y", "30Y")}))
        except (ValueError, TypeError, KeyError):
            continue
    if not rows:
        raise ValueError("No valid JGB observation this month")
    rows.sort()
    day, latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    result = []
    for tenor in ("2Y", "10Y", "30Y"):
        notes = "Japonya Maliye Bakanlığı sabit vadeli JGB getirisi (günlük)."
        if previous:
            notes += f" {previous[0]} gününe göre {(latest[tenor] - previous[1][tenor]) * 100:+.1f} baz puan."
        result.append(_metric("JGB_" + tenor, f"Japonya {tenor} Tahvil Faizi (günlük, MOF)",
                              latest[tenor], "%", day, JGB_URL, notes))
    return result


def cross_metrics(fred_metrics, external_metrics, today=None):
    """Daily combinations of FRED series with the daily TGA and JGB feeds."""
    today = today or datetime.now(timezone.utc).date()
    fred = {item.get("id"): item for item in fred_metrics or [] if item.get("value") is not None}
    external = {item.get("id"): item for item in external_metrics or [] if item.get("value") is not None}

    def build(key, name, unit, parts, formula, notes, max_age=7):
        if not all(part in source for source, part in parts):
            metric = _metric(key, name, None, unit, None, "Türetilmiş", "Bileşenlerden en az biri alınamadı.")
            metric["stale"] = True
            return metric
        items = [source[part] for source, part in parts]
        dates = [datetime.fromisoformat(item["date"]).date() for item in items]
        value = formula(*(item["value"] for item in items))
        component_dates = ", ".join(f"{part}: {item['date']}" for (_, part), item in zip(parts, items))
        metric = _metric(key, name, value, unit, max(dates).isoformat(), "Türetilmiş",
                         notes + " Bileşen tarihleri: " + component_dates + ".")
        metric["stale"] = (any(item.get("stale") or item.get("sync_error") for item in items)
                           or (today - min(dates)).days > max_age)
        return metric

    rows = [
        (GROUP_TREASURY, build("NET_LIQ_DAILY_TGA", "Net Likidite (günlük TGA ile)", "milyar USD",
                               ((fred, "WALCL"), (external, "TGA_DAILY"), (fred, "RRPONTSYD")),
                               lambda walcl, tga, rrp: walcl - tga - rrp,
                               "Fed bilançosu (haftalık) − günlük TGA kapanışı − ters repo.", max_age=10)),
        (GROUP_JAPAN, build("US_JP_10Y_DAILY", "ABD-Japonya 10Y Faiz Farkı (günlük)", "yüzde puan",
                            ((fred, "DGS10"), (external, "JGB_10Y")),
                            lambda us, jp: us - jp,
                            "DGS10 eksi MOF JGB 10Y; daralma yen carry pozisyonlarına baskı demektir.")),
    ]
    for months in ("3", "6"):
        rows.append((GROUP_FED, build(
            f"FED_PRICED_{months}M", f"Piyasanın Fiyatladığı Faiz Değişimi ({months} ay)", "baz puan",
            ((external, f"ZQ_{months}M"), (fred, "EFFR")),
            lambda implied, effr: (implied - effr) * 100,
            "Fed funds vadeli ima faizi eksi bugünkü efektif fed faizi; −25 ≈ bir indirim fiyatlanmış.")))
    for group, metric in rows:
        metric["group"] = group
        metric["focus"] = None
    return [metric for _, metric in rows]


def _url_feed(url, parser):
    def fetch(session, now):
        response = session.get(url, timeout=(10, 30), headers={"User-Agent": "MacroDashboard/1.0"})
        response.raise_for_status()
        return parser(response)
    return fetch


def _load_feed(path, ttl, fetch, session, now, max_age):
    cached = None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(cached.get("metrics"), list) or not cached["metrics"]
                or not all(isinstance(item, dict) and {"id", "name", "value", "unit", "date", "source", "notes"}.issubset(item)
                           for item in cached["metrics"])):
            cached = None
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    error = None
    try:
        fresh = cached and 0 <= now.timestamp() - float(cached["fetched_at"]) < ttl
    except (KeyError, ValueError, TypeError):
        fresh = False
    if fresh:
        metrics = cached["metrics"]
    else:
        try:
            metrics = fetch(session, now)
        except Exception as exc:  # any network, schema or parser failure falls back to the cache
            error = type(exc).__name__ + ": " + str(exc)[:180]
            if not cached:
                return [], error
            metrics = cached["metrics"]
        else:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"fetched_at": now.timestamp(), "metrics": metrics}), encoding="utf-8")
                temporary.replace(path)
            except OSError:
                # A read-only cache must not discard a successfully retrieved feed.
                pass
    output = []
    for item in metrics:
        metric = dict(item)
        try:
            age = (now.date() - datetime.fromisoformat(metric["date"]).date()).days
            metric["stale"] = bool(error) or age > max_age or age < 0
        except (KeyError, ValueError, TypeError):
            continue
        metric["sync_error"] = error
        output.append(metric)
    return output, error


GROUP_GEO = "Jeopolitik risk"
GROUP_TREASURY = "Hazine ve likidite"
GROUP_JAPAN = "Japonya tahvilleri"
GROUP_COT = "Pozisyonlanma (CFTC COT)"
GROUP_OIL = "Petrol stokları ve vadeli eğri"
GROUP_COMEX = "COMEX depo stokları"
GROUP_ETF = "Fiziki metal ETF stokları"
GROUP_OPTIONS = "Opsiyon duyarlılığı (CBOE)"
GROUP_FED = "Fed takvimi ve faiz beklentisi"
GROUP_CRYPTO = "Kripto türevleri ve likidite"
# Display order of the external metric cards.
GROUP_ORDER = (GROUP_FED, GROUP_TREASURY, GROUP_COT, GROUP_OPTIONS, GROUP_OIL, GROUP_COMEX, GROUP_ETF,
               GROUP_JAPAN, GROUP_CRYPTO, GROUP_GEO)

# Metric id -> assets whose AI context should include it (None: every asset).
METRIC_FOCUS = dict(extra_feeds.COT_FOCUS)
METRIC_FOCUS.update({key: ("oil", "brent") for _, key, _ in extra_feeds.EIA_SERIES})
METRIC_FOCUS.update(WTI_M1_M7=("oil", "brent"), GPR_OIL=("oil", "brent"),
                    COMEX_GOLD=("gold",), COMEX_SILVER=("silver",),
                    GLD_TONNES=("gold",), SLV_TONNES=("silver",), COMEX_COPPER=("gold", "silver"),
                    PCR_TOTAL=("spx",), PCR_EQUITY=("spx",), PCR_INDEX=("spx",), PCR_SPX=("spx",),
                    BTC_FUNDING=("btc",), BTC_OI=("btc",), STABLE_SUPPLY=("btc",))


def _feeds():
    """(name, ttl seconds, source, fetch(session, now), max age days, placeholders, group)."""
    def today(fetch):
        return lambda session, now: fetch(session, now.date())

    return [
        ("ai_gpr", 86400, GPR_URL, _url_feed(GPR_URL, lambda r: parse_gpr(r.text)), 75,
         [("GPR_AI", "AI Jeopolitik Risk Endeksi", "endeks"), ("GPR_OIL", "AI Petrol Jeopolitik Risk Endeksi", "endeks")],
         GROUP_GEO),
        ("auctions", 21600, AUCTION_URL, _url_feed(AUCTION_URL, lambda r: parse_auctions(r.json())), 60,
         [(("AUCTION_BTC_" + term + "Y") if suffix == "BTC" else ("UST_" + term + "Y_" + suffix), term + "Y Hazine ihalesi " + label, unit)
          for term in ("10", "30") for suffix, label, unit in (("BTC", "bid-to-cover", "oran"), ("HIGH_YIELD", "en yüksek kabul faizi", "%"))],
         GROUP_TREASURY),
        ("classic_gpr", 86400, GPR_CLASSIC_URL, _url_feed(GPR_CLASSIC_URL, lambda r: parse_classic_gpr(r.content)), 75,
         [("GPR_CLASSIC", "Klasik Jeopolitik Risk Endeksi (Caldara–Iacoviello)", "endeks")], GROUP_GEO),
        ("tga_daily", 43200, TGA_URL, _url_feed(TGA_URL, lambda r: parse_tga(r.json())), 7,
         [("TGA_DAILY", "Hazine Genel Hesabı (günlük kapanış)", "milyar USD")], GROUP_TREASURY),
        # The MOF file is not UTF-8 (Japanese footnote); only ASCII fields are read.
        ("jgb_daily", 43200, JGB_URL, _url_feed(JGB_URL, lambda r: parse_jgb(r.content.decode("latin-1"))), 7,
         [("JGB_" + tenor, f"Japonya {tenor} Tahvil Faizi (günlük, MOF)", "%") for tenor in ("2Y", "10Y", "30Y")],
         GROUP_JAPAN),
        ("cot", 43200, extra_feeds.COT_SOURCE, today(extra_feeds.fetch_cot), 14,
         [(key, f"{market} – {group} COT Endeksi (3Y)", "endeks (0-100)")
          for markets in (extra_feeds.COT_DISAGG, extra_feeds.COT_TFF) for key, market, group in markets.values()],
         GROUP_COT),
        ("eia", 43200, "https://www.eia.gov (WPSR)", lambda session, now: extra_feeds.fetch_eia(session), 10,
         [(key, name, "milyon varil") for _, key, name in extra_feeds.EIA_SERIES], GROUP_OIL),
        ("oil_curve", 21600, "Yahoo Finance", today(extra_feeds.fetch_oil_curve), 5,
         [("WTI_M1_M7", "WTI Vadeli Eğri: 1. − 7. Ay Farkı", "USD/varil")], GROUP_OIL),
        ("cme_stocks", 43200, "https://www.cmegroup.com", lambda session, now: extra_feeds.fetch_cme_stocks(session), 5,
         [(key, f"COMEX {metal} Registered Stoku", unit) for _, key, metal, unit, _ in extra_feeds.CME_FILES],
         GROUP_COMEX),
        ("gld_holdings", 43200, extra_feeds.GLD_URL, lambda session, now: extra_feeds.fetch_gld(session), 7,
         [("GLD_TONNES", "GLD Altın Stoku", "ton")], GROUP_ETF),
        ("slv_holdings", 43200, extra_feeds.SLV_URL, lambda session, now: extra_feeds.fetch_slv(session), 7,
         [("SLV_TONNES", "SLV Gümüş Stoku", "ton")], GROUP_ETF),
        ("cboe_pcr", 21600, "https://www.cboe.com", today(extra_feeds.fetch_cboe), 5,
         [(key, label, "oran") for _, key, label in extra_feeds.CBOE_RATIOS], GROUP_OPTIONS),
        ("fomc", 21600, extra_feeds.FOMC_URL, today(extra_feeds.fetch_fomc), 1,
         [("FOMC_NEXT", "Sonraki FOMC Kararına Kalan Gün", "gün")], GROUP_FED),
        ("fed_funds_futures", 21600, "Yahoo Finance", today(extra_feeds.fetch_fed_funds_futures), 5,
         [("ZQ_3M", "Fed Funds Vadeli İma Faizi (3 ay sonrası)", "%"),
          ("ZQ_6M", "Fed Funds Vadeli İma Faizi (6 ay sonrası)", "%")], GROUP_FED),
        ("btc_derivatives", 1800, "Bybit / Binance", today(extra_feeds.fetch_btc_derivatives), 1,
         [("BTC_FUNDING", "BTC Perpetual Funding (yıllıklandırılmış)", "%")], GROUP_CRYPTO),
        ("stablecoins", 21600, extra_feeds.STABLECOIN_URL, today(extra_feeds.fetch_stablecoins), 2,
         [("STABLE_SUPPLY", "USD Stablecoin Toplam Arzı", "milyar USD")], GROUP_CRYPTO),
    ]


def load_external_metrics(cache_dir=None, session=None, now=None, only=None):
    """Return metric dictionaries for every feed. Missing feeds have null-valued error rows.

    Pass the application's existing private cache directory when integrating.
    ``session`` and timezone-aware ``now`` are injectable for deterministic tests;
    ``only`` restricts loading to the named feeds.
    """
    root = Path(cache_dir) if cache_dir is not None else Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))) / "MacroDashboard" / "external"
    now = now or datetime.now(timezone.utc)
    session = session or requests
    metrics = []
    for name, ttl, source, fetch, max_age, placeholders, group in _feeds():
        if only is not None and name not in only:
            continue
        values, error = _load_feed(root / (name + ".json"), ttl, fetch, session, now, max_age)
        if not values:
            for key, label, unit in placeholders:
                item = _metric(key, label, None, unit, None, source, "Doğrulanmış gözlem alınamadı.")
                item.update(stale=True, sync_error=error)
                values.append(item)
        for item in values:
            item["group"] = group
            item["focus"] = METRIC_FOCUS.get(item["id"])
        metrics.extend(values)
    return metrics


class ExternalMacroFeed:
    """``cache_path`` is a private directory containing separate feed cache files."""

    def __init__(self, cache_path=None, session=None):
        self.cache_path = cache_path
        self.session = session

    def fetch_metrics(self):
        return load_external_metrics(self.cache_path, self.session)
