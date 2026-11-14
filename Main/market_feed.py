"""Yahoo chart observations shared by the UI and the alarm service.

Yahoo's chart endpoint is a market quote source, not a source for FRED series.
Missing or rejected responses deliberately produce no observation.
"""
import math
from datetime import datetime, timezone
from urllib.parse import quote

import requests


YAHOO_MACROS = (
    ("ABD 13 Haftalık Bono Faizi (%)", "^IRX"),
    ("ABD 5 Yıllık Tahvil Faizi (%)", "^FVX"),
    ("ABD 10 Yıllık Tahvil Faizi (%)", "^TNX"),
    ("ABD 30 Yıllık Tahvil Faizi (%)", "^TYX"),
    ("VIX Endeksi", "^VIX"),
    ("VIX 9 Günlük (^VIX9D)", "^VIX9D"),
    ("VIX 3 Aylık (^VIX3M)", "^VIX3M"),
    ("VVIX (VIX'in Oynaklığı)", "^VVIX"),
    ("CBOE SKEW Endeksi (Kuyruk Riski)", "^SKEW"),
    ("MOVE Endeksi (Tahvil Oynaklığı)", "^MOVE"),
    ("Altın Oynaklık Endeksi (GVZ)", "^GVZ"),
    ("Petrol Oynaklık Endeksi (OVX)", "^OVX"),
    ("Dolar Endeksi (DXY)", "DX-Y.NYB"),
    ("USD/JPY (JPY / USD)", "JPY=X"),
    ("EUR/USD (USD / EUR)", "EURUSD=X"),
    ("USD/CNY (Onshore, CNY / USD)", "CNY=X"),
    ("WTI Petrol Vadeli (USD/varil)", "CL=F"),
    ("Brent Petrol Vadeli (USD/varil)", "BZ=F"),
    ("RBOB Benzin Vadeli (USD/galon)", "RB=F"),
    ("Isıtma Yağı Vadeli (USD/galon)", "HO=F"),
    ("Bakır Vadeli (USD/libre)", "HG=F"),
    ("Altın Vadeli (USD/ons)", "GC=F"),
    ("TIP ETF Fiyatı (Reel Faiz Değil)", "TIP"),
    ("EEM ETF Fiyatı", "EEM"),
    ("HYG ETF Fiyatı (Yüksek Getirili Tahvil)", "HYG"),
    ("LQD ETF Fiyatı (Yatırım Yapılabilir Tahvil)", "LQD"),
    ("RSP ETF Fiyatı (Eşit Ağırlıklı S&P 500)", "RSP"),
    ("SPY ETF Fiyatı", "SPY"),
)

# Spreads and ratios computed from same-day Yahoo closes.
# kind "ratio_change": primary number is the daily % change of a/b (alarms read it first).
# kind "level": primary number is the level; the daily change follows in brackets.
GALLON_PER_BARREL = 42.0
MARKET_DYNAMICS = (
    ("vix_short_term", "VIX9D/VIX Oranı (Kısa Vade Stres)", ("^VIX9D", "^VIX"),
     lambda v: v["^VIX9D"] / v["^VIX"], "level", "oran",
     "1'in üzeri: yakın vadeli korku 1 aylıktan yüksek (olay/panik riski); altı: sakin yakın vade."),
    ("breadth_rsp_spy", "RSP/SPY Oranı Günlük Değişimi (Piyasa Genişliği)", ("RSP", "SPY"),
     lambda v: v["RSP"] / v["SPY"], "ratio_change", "oran",
     "Pozitif: eşit ağırlıklı endeks önde, yükseliş geniş tabanlı; negatif: endeksi büyük hisseler taşıyor."),
    ("credit_hyg_lqd", "HYG/LQD Oranı Günlük Değişimi (Kredi Riski İştahı)", ("HYG", "LQD"),
     lambda v: v["HYG"] / v["LQD"], "ratio_change", "oran",
     "Negatif: yüksek getirili tahvil yatırım yapılabilir tahvile göre zayıf, kredi riski iştahı düşüyor."),
    ("brent_wti", "Brent-WTI Farkı (USD/varil)", ("BZ=F", "CL=F"),
     lambda v: v["BZ=F"] - v["CL=F"], "level", "USD/varil",
     "Ön ay vadeli kontratlar; vade ayları farklı olabilir. Genişleme: ABD dışı arz sıkılığı veya ABD stok fazlası."),
    ("crack_321", "3-2-1 Crack Spread (USD/varil)", ("CL=F", "RB=F", "HO=F"),
     lambda v: (2 * v["RB=F"] * GALLON_PER_BARREL + v["HO=F"] * GALLON_PER_BARREL - 3 * v["CL=F"]) / 3,
     "level", "USD/varil",
     "Rafineri marjı vekili: (2×benzin + 1×dizel − 3×ham petrol)/3, ön ay vadelileri. Yüksek: ürün talebi güçlü."),
)


class YahooFeed:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        })

    def observations(self, symbol, range_str="5d", interval="1d"):
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="")
        try:
            response = self.session.get(
                url, params={"range": range_str, "interval": interval}, timeout=8
            )
            response.raise_for_status()
            chart = response.json().get("chart") or {}
            if chart.get("error") or not chart.get("result"):
                return []
            result = chart["result"][0]
            timestamps = result.get("timestamp") or []
            quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
            closes = quotes.get("close") or []
            values = []
            for stamp, close in zip(timestamps, closes):
                if stamp is None or close is None:
                    continue
                value = float(close)
                if math.isfinite(value) and value > 0:
                    values.append((int(stamp), value))
            return sorted(values)
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
            return []

    def latest(self, symbol, range_str="5d"):
        points = self.observations(symbol, range_str)
        if not points:
            return None
        stamp, value = points[-1]
        previous = points[-2][1] if len(points) > 1 else None
        return {"value": value, "previous": previous, "timestamp": stamp}

    def combined(self, symbols, formula):
        """Apply ``formula`` to same-UTC-day closes; return latest and previous combined value."""
        by_symbol = {}
        for symbol in symbols:
            by_day = {datetime.fromtimestamp(t, timezone.utc).date(): (t, v)
                      for t, v in self.observations(symbol)}
            if not by_day:
                return None
            by_symbol[symbol] = by_day
        days = sorted(set.intersection(*(set(item) for item in by_symbol.values())))
        values = []
        for day in days:
            try:
                value = formula({symbol: by_symbol[symbol][day][1] for symbol in symbols})
            except ZeroDivisionError:
                continue
            if math.isfinite(value):
                stamp = max(by_symbol[symbol][day][0] for symbol in symbols)
                values.append((stamp, value))
        if not values:
            return None
        return {"value": values[-1][1], "previous": values[-2][1] if len(values) > 1 else None,
                "timestamp": values[-1][0]}

    def ratio_change(self, numerator, denominator):
        first = self.observations(numerator)
        second = self.observations(denominator)
        by_day = {datetime.fromtimestamp(t, timezone.utc).date(): v for t, v in second}
        ratios = [(t, value / by_day[datetime.fromtimestamp(t, timezone.utc).date()])
                  for t, value in first
                  if datetime.fromtimestamp(t, timezone.utc).date() in by_day
                  and by_day[datetime.fromtimestamp(t, timezone.utc).date()] > 0]
        if len(ratios) < 2 or ratios[-2][1] == 0:
            return None
        return {"value": ratios[-1][1],
                "change_pct": (ratios[-1][1] / ratios[-2][1] - 1) * 100,
                "timestamp": ratios[-1][0]}


def compute_dynamics(feed, keys=None):
    """Return {key: {label, value, display, tone, notes}} for MARKET_DYNAMICS.

    ``value`` is the number alarms compare against; ``tone`` is +1, -1 or 0.
    """
    output = {}
    for key, label, symbols, formula, kind, unit, notes in MARKET_DYNAMICS:
        if keys is not None and key not in keys:
            continue
        try:
            item = feed.combined(symbols, formula)
        except Exception:
            item = None
        if not item:
            continue
        value, previous = item["value"], item["previous"]
        if kind == "ratio_change":
            if not previous:
                continue
            pct = (value / previous - 1) * 100
            output[key] = {"label": label, "value": pct, "tone": (pct > 0) - (pct < 0),
                           "display": f"{pct:+.2f}% günlük (oran {value:.4f})", "notes": notes}
        else:
            change = value - previous if previous is not None else None
            display = f"{value:.3f}" if unit == "oran" else f"{value:.2f} {unit}"
            if change is not None:
                display += f" ({change:+.3f} günlük)" if unit == "oran" else f" ({change:+.2f} günlük)"
            # Only the VIX ratio has a direction: above 1 is stress.
            tone = ((value < 1) - (value > 1)) if key == "vix_short_term" else 0
            output[key] = {"label": label, "value": value, "tone": tone,
                           "display": display, "notes": notes}
    return output
