"""Positioning, inventory, sentiment, calendar and crypto-derivative feeds.

Every ``fetch_*`` function takes a requests-like ``session`` (and ``today`` where the
URL depends on the date) and returns metric dictionaries in the external_feed format.
Parsers raise ValueError on schema changes so the caller can fall back to its cache.
"""
import html
import math
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}


def _metric(key, name, value, unit, day, source, notes):
    return dict(id=key, name=name, value=value, unit=unit, date=day,
                source=source, notes=notes, stale=False, sync_error=None)


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite observation")
    return number


def _get(session, url, headers=None, timeout=(10, 40)):
    response = session.get(url, timeout=timeout, headers=headers or BROWSER_HEADERS)
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# CFTC Commitments of Traders
# ---------------------------------------------------------------------------
COT_SOURCE = "https://publicreporting.cftc.gov (CFTC COT)"
COT_DISAGG_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
COT_TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
# code: (key, Turkish market name, trader group label, long field, short field)
COT_DISAGG = {
    "088691": ("COT_GOLD", "Altın", "Managed Money"),
    "084691": ("COT_SILVER", "Gümüş", "Managed Money"),
    "085692": ("COT_COPPER", "Bakır", "Managed Money"),
    "067651": ("COT_WTI", "WTI Petrol", "Managed Money"),
}
COT_TFF = {
    "13874A": ("COT_ES", "E-mini S&P 500", "Leveraged Funds"),
    "209742": ("COT_NQ", "Nasdaq 100 Mini", "Leveraged Funds"),
    "098662": ("COT_DXY", "Dolar Endeksi", "Leveraged Funds"),
    "097741": ("COT_JPY", "Japon Yeni", "Leveraged Funds"),
    "133741": ("COT_BTC", "CME Bitcoin", "Leveraged Funds"),
    "043602": ("COT_UST10", "ABD 10Y Tahvil Vadelisi", "Leveraged Funds"),
}
COT_FIELDS = {
    "disagg": ("m_money_positions_long_all", "m_money_positions_short_all"),
    "tff": ("lev_money_positions_long", "lev_money_positions_short"),
}
COT_LOOKBACK_WEEKS = 156


def cot_url(base, codes, today):
    start = (today - timedelta(weeks=COT_LOOKBACK_WEEKS + 2)).isoformat()
    long_field, short_field = COT_FIELDS["disagg" if base == COT_DISAGG_URL else "tff"]
    code_list = ",".join("'" + code + "'" for code in codes)
    query = {
        "$select": f"cftc_contract_market_code,report_date_as_yyyy_mm_dd,open_interest_all,{long_field},{short_field}",
        "$where": f"cftc_contract_market_code in({code_list}) AND report_date_as_yyyy_mm_dd >= '{start}T00:00:00.000'",
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": "5000",
    }
    return base + "?" + urlencode(query)


def parse_cot(rows, markets, kind):
    if not isinstance(rows, list):
        raise ValueError("CFTC COT schema changed")
    long_field, short_field = COT_FIELDS[kind]
    series = {}
    for row in rows:
        try:
            code = row["cftc_contract_market_code"].strip()
            day = row["report_date_as_yyyy_mm_dd"][:10]
            net = _number(row[long_field]) - _number(row[short_field])
            open_interest = _number(row["open_interest_all"])
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        if code in markets:
            series.setdefault(code, {})[day] = (net, open_interest)
    result = []
    for code, (key, market, group) in markets.items():
        history = sorted(series.get(code, {}).items())
        if len(history) < 2:
            continue
        day, (net, open_interest) = history[-1]
        previous = history[-2][1][0]
        window = [value[0] for _, value in history[-COT_LOOKBACK_WEEKS:]]
        low, high = min(window), max(window)
        index = 100 * (net - low) / (high - low) if high > low else 50.0
        share = 100 * net / open_interest if open_interest else 0.0
        notes = (f"{group} net pozisyonu {net:+,.0f} kontrat (açık pozisyonun %{share:+.1f}'i); "
                 f"haftalık değişim {net - previous:+,.0f}. COT endeksi son {len(window)} haftalık aralıkta "
                 f"netin yeri: 0 = en kısa, 100 = en uzun; 80 üstü kalabalık long, 20 altı kalabalık short. "
                 f"Rapor salı günkü pozisyonu gösterir, cuma yayımlanır.")
        result.append(_metric(key, f"{market} – {group} COT Endeksi (3Y)", index, "endeks (0-100)",
                              day, COT_SOURCE, notes))
    if not result:
        raise ValueError("No valid COT market")
    return result


def fetch_cot(session, today):
    disagg = _get(session, cot_url(COT_DISAGG_URL, COT_DISAGG, today)).json()
    tff = _get(session, cot_url(COT_TFF_URL, COT_TFF, today)).json()
    return parse_cot(disagg, COT_DISAGG, "disagg") + parse_cot(tff, COT_TFF, "tff")


COT_FOCUS = {"COT_GOLD": ("gold",), "COT_SILVER": ("silver",), "COT_COPPER": ("gold", "silver"),
             "COT_WTI": ("oil", "brent"), "COT_ES": ("spx",), "COT_NQ": ("spx",),
             "COT_DXY": ("dollar", "gold"), "COT_JPY": ("dollar",), "COT_BTC": ("btc",),
             "COT_UST10": ("spx", "gold", "dollar")}


# ---------------------------------------------------------------------------
# EIA weekly petroleum inventories (public XLS, no API key)
# ---------------------------------------------------------------------------
EIA_URL = "https://www.eia.gov/dnav/pet/hist_xls/{}w.xls"
EIA_SERIES = (
    ("WCESTUS1", "EIA_CRUDE", "ABD Ham Petrol Stokları (SPR hariç)"),
    ("WGTSTUS1", "EIA_GASOLINE", "ABD Benzin Stokları"),
    ("WDISTUS1", "EIA_DISTILLATE", "ABD Distilat Stokları"),
    ("W_EPC0_SAX_YCUOK_MBBL", "EIA_CUSHING", "Cushing Ham Petrol Stokları"),
    ("WCSSTUS1", "EIA_SPR", "Stratejik Petrol Rezervi (SPR)"),
)


def parse_eia(content, key, name, series_id):
    import xlrd
    book = xlrd.open_workbook(file_contents=content, on_demand=True)
    try:
        sheet = book.sheet_by_name("Data 1")
        if str(sheet.cell_value(1, 1)).strip() != series_id:
            raise ValueError("EIA XLS schema changed")
        rows = []
        for index in range(3, sheet.nrows):
            stamp, value = sheet.cell_value(index, 0), sheet.cell_value(index, 1)
            if isinstance(stamp, float) and isinstance(value, float) and math.isfinite(value):
                rows.append((xlrd.xldate_as_datetime(stamp, book.datemode).date(), value / 1000))
    except (xlrd.XLRDError, IndexError) as exc:
        raise ValueError("EIA XLS schema changed") from exc
    finally:
        book.release_resources()
    if len(rows) < 2:
        raise ValueError("No EIA observations")
    day, value = rows[-1]
    change = value - rows[-2][1]
    # Same calendar week in each of the previous five years (±3 days).
    seasonal = []
    for years in range(1, 6):
        target = day - timedelta(weeks=52 * years)
        match = min(rows, key=lambda row: abs((row[0] - target).days))
        if abs((match[0] - target).days) <= 3:
            seasonal.append(match[1])
    notes = f"Haftalık değişim {change:+.2f} milyon varil."
    if len(seasonal) == 5:
        average = sum(seasonal) / 5
        notes += f" Aynı haftanın 5 yıllık ortalaması {average:.1f}; fark %{(value / average - 1) * 100:+.1f}."
    notes += " EIA çarşamba yayımlar; stok düşüşü fiyat için genelde destekleyicidir."
    return _metric(key, name, value, "milyon varil", day.isoformat(), "https://www.eia.gov (WPSR)", notes)


def fetch_eia(session):
    result = []
    for series_id, key, name in EIA_SERIES:
        result.append(parse_eia(_get(session, EIA_URL.format(series_id)).content, key, name, series_id))
    return result


# ---------------------------------------------------------------------------
# COMEX depository stocks (CME public XLS, browser user agent required)
# ---------------------------------------------------------------------------
CME_URL = "https://www.cmegroup.com/delivery_reports/{}.xls"
CME_FILES = (
    ("Gold_Stocks", "COMEX_GOLD", "Altın", "milyon ons", 1e6),
    ("Silver_stocks", "COMEX_SILVER", "Gümüş", "milyon ons", 1e6),
    ("Copper_Stocks", "COMEX_COPPER", "Bakır", "bin kısa ton", 1e3),
)


def parse_cme_stocks(content, key, metal, unit, scale):
    import xlrd
    book = xlrd.open_workbook(file_contents=content, on_demand=True)
    try:
        sheet = book.sheet_by_index(0)
        totals, activity = {}, None
        for index in range(sheet.nrows):
            row = sheet.row_values(index)
            label = str(row[0]).upper()
            for cell in row:
                found = re.search(r"Activity Date:\s*(\d{1,2}/\d{1,2}/\d{4})", str(cell))
                if found:
                    activity = datetime.strptime(found.group(1), "%m/%d/%Y").date()
            for name in ("REGISTERED", "ELIGIBLE", "PLEDGED"):
                if label.startswith("TOTAL " + name) and len(row) > 7:
                    totals[name] = (_number(row[2]), _number(row[7]))
            if label.startswith("COMBINED TOTAL") and len(row) > 7:
                totals["COMBINED"] = (_number(row[2]), _number(row[7]))
    except (xlrd.XLRDError, IndexError) as exc:
        raise ValueError("CME stocks XLS schema changed") from exc
    finally:
        book.release_resources()
    if "REGISTERED" not in totals or "ELIGIBLE" not in totals or activity is None:
        raise ValueError("CME stocks XLS schema changed")
    registered_prev, registered = totals["REGISTERED"]
    eligible = totals["ELIGIBLE"][1]
    combined = totals.get("COMBINED", (None, registered + eligible + totals.get("PLEDGED", (0, 0))[1]))[1]
    notes = (f"Registered (teslimata hazır) günlük değişim {(registered - registered_prev) / scale:+.3f} {unit}; "
             f"eligible {eligible / scale:,.2f}, toplam {combined / scale:,.2f} {unit}; "
             f"registered/toplam %{100 * registered / combined:.1f}. "
             "Registered düşüşü teslimat için fiziksel arzın daraldığını gösterebilir.")
    return _metric(key, f"COMEX {metal} Registered Stoku", registered / scale, unit,
                   activity.isoformat(), "https://www.cmegroup.com (depo raporu)", notes)


def fetch_cme_stocks(session):
    return [parse_cme_stocks(_get(session, CME_URL.format(name)).content, key, metal, unit, scale)
            for name, key, metal, unit, scale in CME_FILES]


# ---------------------------------------------------------------------------
# Physical metal ETF holdings
# ---------------------------------------------------------------------------
GLD_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en"
SLV_URL = "https://www.ishares.com/us/products/239855/ishares-silver-trust-fund"
_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_rows(content):
    """Yield {column letter: text} rows of every worksheet; stdlib only (no openpyxl on Android)."""
    import io
    import zipfile
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("Not an xlsx file") from exc
    shared = []
    if "xl/sharedStrings.xml" in archive.namelist():
        for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).iter(_XLSX_NS + "si"):
            shared.append("".join(node.text or "" for node in item.iter(_XLSX_NS + "t")))
    for name in sorted(n for n in archive.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")):
        rows = []
        for row in ET.fromstring(archive.read(name)).iter(_XLSX_NS + "row"):
            cells = {}
            for cell in row.iter(_XLSX_NS + "c"):
                value = cell.find(_XLSX_NS + "v")
                text = value.text if value is not None else ""
                if cell.get("t") == "s" and text:
                    text = shared[int(text)]
                cells[re.sub(r"\d", "", cell.get("r", ""))] = (text or "").strip()
            rows.append(cells)
        yield rows


def parse_gld(content):
    for rows in _xlsx_rows(content):
        header = next((row for row in rows[:5] if "Date" in row.values()), None)
        if not header:
            continue
        columns = {text: letter for letter, text in header.items()}
        date_col = columns.get("Date")
        tonnes_col = next((letter for text, letter in columns.items() if text.startswith("Tonnes of Gold")), None)
        if not date_col or not tonnes_col:
            continue
        history = []
        for row in rows:
            try:
                day = datetime.strptime(row.get(date_col, ""), "%d-%b-%Y").date()
                history.append((day, _number(row.get(tonnes_col))))
            except (ValueError, TypeError):
                continue
        if len(history) >= 2:
            history.sort()
            day, tonnes = history[-1]

            def change(days):
                base = next((value for when, value in reversed(history) if when <= day - timedelta(days=days)), None)
                return f"{tonnes - base:+.1f}" if base is not None else "yok"

            year = [value for when, value in history if when >= day - timedelta(days=365)]
            notes = (f"Günlük {tonnes - history[-2][1]:+.1f} ton, 1 hafta {change(7)}, 1 ay {change(30)}, "
                     f"1 yıl {change(365)} ton; 52 haftalık aralık {min(year):,.1f}–{max(year):,.1f} ton. "
                     "Artış ETF'e fiziksel altın girişi (yatırımcı talebi), azalış çıkış demektir.")
            return [_metric("GLD_TONNES", "GLD Altın Stoku", tonnes, "ton", day.isoformat(),
                            "https://www.spdrgoldshares.com (tarihsel veri)", notes)]
    raise ValueError("GLD archive schema changed")


def fetch_gld(session):
    return parse_gld(_get(session, GLD_URL, timeout=(10, 60)).content)


def parse_slv(text):
    page = html.unescape(text)
    found = re.search(r'"tonnes"\s*:\s*\{([^{}]*)\}', page)
    if not found:
        raise ValueError("iShares SLV page schema changed")
    block = found.group(1)
    value = re.search(r'"formattedValue"\s*:\s*"([\d,.]+)"', block)
    as_of = re.search(r'"formattedAsOfDate"\s*:\s*"([A-Za-z]{3} \d{1,2}, \d{4})"', block)
    if not value or not as_of:
        raise ValueError("iShares SLV page schema changed")
    tonnes = _number(value.group(1).replace(",", ""))
    day = datetime.strptime(as_of.group(1), "%b %d, %Y").date()
    return [_metric("SLV_TONNES", "SLV Gümüş Stoku", tonnes, "ton", day.isoformat(), SLV_URL,
                    "iShares sayfasındaki güncel değer; sağlayıcı geçmiş seri yayımlamıyor, değişim hesaplanmaz. "
                    "Artış ETF'e fiziksel gümüş girişi demektir.")]


def fetch_slv(session):
    return parse_slv(_get(session, SLV_URL, timeout=(10, 40)).text)


# ---------------------------------------------------------------------------
# CBOE daily put/call ratios
# ---------------------------------------------------------------------------
CBOE_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{}_daily_options"
CBOE_RATIOS = (
    ("TOTAL PUT/CALL RATIO", "PCR_TOTAL", "CBOE Toplam Put/Call Oranı"),
    ("EQUITY PUT/CALL RATIO", "PCR_EQUITY", "CBOE Hisse Put/Call Oranı"),
    ("INDEX PUT/CALL RATIO", "PCR_INDEX", "CBOE Endeks Put/Call Oranı"),
    ("SPX + SPXW + SPXO PUT/CALL RATIO", "PCR_SPX", "SPX Put/Call Oranı"),
)


def parse_cboe(data, day):
    ratios = {item.get("name", "").strip().upper(): item.get("value")
              for item in (data or {}).get("ratios", []) if isinstance(item, dict)}
    result = []
    for name, key, label in CBOE_RATIOS:
        try:
            value = _number(ratios[name])
        except (KeyError, ValueError, TypeError):
            continue
        if value <= 0:
            continue
        result.append(_metric(key, label, value, "oran", day.isoformat(), "https://www.cboe.com",
                              "Günlük hacim bazlı. Hisse P/C 0,5 altı aşırı iyimserlik, 0,8-1 üstü korku/hedge "
                              "sinyali olarak okunur; kontrarian gösterge."))
    if not result:
        raise ValueError("CBOE ratios schema changed")
    return result


def fetch_cboe(session, today):
    last_error = None
    for back in range(0, 8):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        try:
            return parse_cboe(_get(session, CBOE_URL.format(day.isoformat())).json(), day)
        except Exception as exc:  # missing day files return 403/404
            last_error = exc
    raise ValueError("No CBOE daily file in the last week: " + str(last_error)[:80])


# ---------------------------------------------------------------------------
# FOMC calendar and fed funds futures
# ---------------------------------------------------------------------------
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}


def parse_fomc(text):
    meetings = []
    sections = re.split(r"(\d{4}) FOMC Meetings", text)
    for year_text, body in zip(sections[1::2], sections[2::2]):
        year = int(year_text)
        months = re.findall(r'fomc-meeting__month[^>]*>\s*(?:<strong>)?\s*([A-Za-z/]+)', body)
        days = re.findall(r'fomc-meeting__date[^>]*>\s*([0-9]+(?:-[0-9]+)?)(\*?)', body)
        for month_text, (day_text, sep) in zip(months, days):
            month_name = month_text.split("/")[-1].lower()
            month = next((value for name, value in MONTHS.items() if name.startswith(month_name[:3])), None)
            if month is None:
                continue
            end_day = int(day_text.split("-")[-1])
            try:
                meetings.append((date(year, month, end_day), bool(sep)))
            except ValueError:
                continue
    if not meetings:
        raise ValueError("FOMC calendar schema changed")
    return sorted(set(meetings))


def fomc_metric(meetings, today):
    upcoming = [item for item in meetings if item[0] >= today]
    if not upcoming:
        raise ValueError("No upcoming FOMC meeting listed")
    day, sep = upcoming[0]
    notes = f"Karar günü {day.isoformat()}" + (" (ekonomik projeksiyonlar/SEP açıklanır)" if sep else "") + "."
    if len(upcoming) > 1:
        notes += f" Sonraki: {upcoming[1][0].isoformat()}."
    return _metric("FOMC_NEXT", "Sonraki FOMC Kararına Kalan Gün", (day - today).days, "gün",
                   today.isoformat(), FOMC_URL, notes)


def fetch_fomc(session, today):
    return [fomc_metric(parse_fomc(_get(session, FOMC_URL).text), today)]


FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"


def contract_symbol(root, year, month, suffix):
    return f"{root}{FUTURES_MONTH_CODES[month - 1]}{year % 100:02d}.{suffix}"


def add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    return index // 12, index % 12 + 1


def yahoo_last_close(session, symbol):
    response = _get(session, "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol
                    + "?range=5d&interval=1d", timeout=(8, 15))
    result = response.json()["chart"]["result"][0]
    pairs = [(stamp, close) for stamp, close in zip(result.get("timestamp") or [],
                                                    result["indicators"]["quote"][0].get("close") or [])
             if stamp and close]
    if not pairs:
        raise ValueError("No Yahoo close for " + symbol)
    stamp, close = pairs[-1]
    return datetime.fromtimestamp(stamp, timezone.utc).date(), _number(close)


def fetch_fed_funds_futures(session, today):
    result = []
    for months, key, label in ((3, "ZQ_3M", "3 ay sonrası"), (6, "ZQ_6M", "6 ay sonrası")):
        year, month = add_months(today, months)
        symbol = contract_symbol("ZQ", year, month, "CBT")
        day, price = yahoo_last_close(session, symbol)
        result.append(_metric(key, f"Fed Funds Vadeli İma Faizi ({label})", 100 - price, "%", day.isoformat(),
                              "Yahoo Finance " + symbol,
                              f"{symbol} kontratı: 100 − fiyat = o ayın ortalama efektif fed faizi beklentisi."))
    return result


def fetch_oil_curve(session, today):
    # WTI stops trading around the 20th of the month before delivery.
    first = add_months(today, 1 if today.day < 19 else 2)
    later = add_months(date(first[0], first[1], 1), 6)
    near_symbol = contract_symbol("CL", first[0], first[1], "NYM")
    far_symbol = contract_symbol("CL", later[0], later[1], "NYM")
    near_day, near = yahoo_last_close(session, near_symbol)
    _, far = yahoo_last_close(session, far_symbol)
    return [_metric("WTI_M1_M7", "WTI Vadeli Eğri: 1. − 7. Ay Farkı", near - far, "USD/varil", near_day.isoformat(),
                    "Yahoo Finance " + near_symbol + ", " + far_symbol,
                    f"{near_symbol} {near:.2f} − {far_symbol} {far:.2f}. Pozitif = backwardation "
                    "(yakın arz sıkı); negatif = contango (arz bol, depolama primi).")]


# ---------------------------------------------------------------------------
# Crypto derivatives and stablecoin liquidity
# ---------------------------------------------------------------------------
BYBIT_URL = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
STABLECOIN_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=false"


def parse_bybit(data, today):
    try:
        ticker = data["result"]["list"][0]
        funding = _number(ticker["fundingRate"])
        interval = _number(ticker.get("fundingIntervalHour") or 8)
        open_interest = _number(ticker["openInterestValue"]) / 1e9
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("Bybit ticker schema changed") from exc
    annual = funding * (24 / interval) * 365 * 100
    return [
        _metric("BTC_FUNDING", "BTC Perpetual Funding (yıllıklandırılmış)", annual, "%", today.isoformat(),
                "Bybit BTCUSDT", f"Son funding {funding * 100:+.4f}% / {interval:.0f} saat. Yüksek pozitif: "
                "kaldıraçlı long kalabalık; negatif: short kalabalık."),
        _metric("BTC_OI", "BTC Perpetual Açık Pozisyon (Bybit)", open_interest, "milyar USD", today.isoformat(),
                "Bybit BTCUSDT", "Tek borsa; fiyatla birlikte yükselen OI yeni kaldıraç girişi demektir."),
    ]


def fetch_btc_derivatives(session, today):
    try:
        return parse_bybit(_get(session, BYBIT_URL).json(), today)
    except Exception:
        data = _get(session, BINANCE_FUNDING_URL).json()
        funding = _number(data["lastFundingRate"])
        return [_metric("BTC_FUNDING", "BTC Perpetual Funding (yıllıklandırılmış)", funding * 3 * 365 * 100, "%",
                        today.isoformat(), "Binance BTCUSDT",
                        f"Son funding {funding * 100:+.4f}% / 8 saat (Bybit alınamadı)." )]


def parse_stablecoins(data, today):
    assets = (data or {}).get("peggedAssets") if isinstance(data, dict) else None
    if not isinstance(assets, list):
        raise ValueError("DefiLlama schema changed")

    def total(field):
        amount = 0.0
        for asset in assets:
            if asset.get("pegType") != "peggedUSD":
                continue
            value = (asset.get(field) or {}).get("peggedUSD")
            if isinstance(value, (int, float)) and math.isfinite(value):
                amount += value
        return amount / 1e9

    now, week = total("circulating"), total("circulatingPrevWeek")
    month = total("circulatingPrevMonth")
    if now <= 0:
        raise ValueError("No stablecoin supply")
    notes = f"Haftalık değişim {now - week:+.1f}, aylık {now - month:+.1f} milyar USD. Arz artışı kriptoya giren likiditeyi gösterir."
    return [_metric("STABLE_SUPPLY", "USD Stablecoin Toplam Arzı", now, "milyar USD", today.isoformat(),
                    "https://defillama.com/stablecoins", notes)]


def fetch_stablecoins(session, today):
    return parse_stablecoins(_get(session, STABLECOIN_URL, timeout=(10, 60)).json(), today)


# ---------------------------------------------------------------------------
# Text context: headlines and this week's calendar
# ---------------------------------------------------------------------------
HEADLINE_FEEDS = (
    ("Fed", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
)


def parse_rss(content, source, now, hours=48, limit=6):
    root = ET.fromstring(content)
    items = []
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        published = item.findtext("pubDate")
        try:
            stamp = parsedate_to_datetime(published)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if title and timedelta(0) <= now - stamp <= timedelta(hours=hours):
            items.append({"source": source, "title": title[:180], "time": stamp.astimezone(timezone.utc)})
    return sorted(items, key=lambda entry: entry["time"], reverse=True)[:limit]


def fetch_headlines(session, now=None):
    now = now or datetime.now(timezone.utc)
    headlines = []
    for source, url in HEADLINE_FEEDS:
        try:
            headlines.extend(parse_rss(_get(session, url, timeout=(5, 10)).content, source, now))
        except Exception:
            continue
    return [{"source": item["source"], "title": item["title"],
             "time": item["time"].strftime("%Y-%m-%d %H:%M UTC")}
            for item in sorted(headlines, key=lambda entry: entry["time"], reverse=True)]


def parse_week_calendar(content, today):
    """High-impact USD events from today to the end of the calendar week."""
    root = ET.fromstring(content)
    events = []
    for event in root.findall("event"):
        if (event.findtext("country") or "") != "USD" or (event.findtext("impact") or "") != "High":
            continue
        try:
            day = datetime.strptime((event.findtext("date") or "").strip(), "%m-%d-%Y").date()
        except ValueError:
            continue
        if day < today:
            continue
        parts = [f"{day.isoformat()} {(event.findtext('time') or '').strip()} {event.findtext('title') or ''}".strip()]
        if event.findtext("forecast"):
            parts.append("beklenti " + event.findtext("forecast"))
        if event.findtext("previous"):
            parts.append("önceki " + event.findtext("previous"))
        events.append(", ".join(parts))
    return events
