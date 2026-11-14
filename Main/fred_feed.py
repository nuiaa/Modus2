"""Incremental, keyless FRED CSV storage and macroeconomic calculations.

Observation dates are FRED dates, not publication or revision timestamps. A
45-day overlap updates recent revisions; older revisions need a full refresh.
"""
import csv
import io
import math
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import requests


FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# id: (Turkish display name, unit, observation frequency, display scale)
FRED_SERIES = {
    "DFII10": ("ABD 10Y Reel Faiz (DFII10)", "%", "günlük", 1),
    "T10YIE": ("10Y Başabaş Enflasyon (T10YIE)", "%", "günlük", 1),
    "T5YIE": ("5Y Başabaş Enflasyon (T5YIE)", "%", "günlük", 1),
    "T5YIFR": ("5Y5Y İleri Enflasyon (T5YIFR)", "%", "günlük", 1),
    "T10Y2Y": ("10Y-2Y Faiz Farkı (T10Y2Y)", "yüzde puan", "günlük", 1),
    "T10Y3M": ("10Y-3A Faiz Farkı (T10Y3M)", "yüzde puan", "günlük", 1),
    "DGS10": ("ABD 10Y Sabit Vadeli Faiz (DGS10)", "%", "günlük", 1),
    "DGS2": ("ABD 2Y Sabit Vadeli Faiz (DGS2)", "%", "günlük", 1),
    "DGS3MO": ("ABD 3A Sabit Vadeli Faiz (DGS3MO)", "%", "günlük", 1),
    "WALCL": ("Fed Bilançosu (WALCL)", "milyar USD", "haftalık", 0.001),
    "WTREGEN": ("Hazine Genel Hesabı, Hafta Ort. (WTREGEN)", "milyar USD", "haftalık", 0.001),
    "RRPONTSYD": ("Ters Repo (RRPONTSYD)", "milyar USD", "günlük", 1),
    "M2SL": ("ABD M2 Para Arzı (M2SL)", "milyar USD", "aylık", 1),
    "BAMLH0A0HYM2": ("Yüksek Getirili Tahvil Spread'i (OAS)", "yüzde puan", "günlük", 1),
    "THREEFYTP10": ("10Y Vade Primi (THREEFYTP10)", "yüzde puan", "günlük", 1),
    "A091RC1Q027SBEA": ("Federal Faiz Ödemesi, Yıllıklandırılmış", "milyar USD/yıl", "çeyreklik", 1),
    "W006RC1Q027SBEA": ("Federal Vergi Gelirleri, Yıllıklandırılmış", "milyar USD/yıl", "çeyreklik", 1),
    "FDHBFIN": ("Yabancı ve Uluslararası Yatırımcı Tahvilleri", "milyar USD", "çeyreklik", 1),
    "PCEPILFE": ("Çekirdek PCE Fiyat Endeksi", "endeks", "aylık", 1),
    "CPILFESL": ("Çekirdek TÜFE Endeksi", "endeks", "aylık", 1),
    "PPIACO": ("Üretici Fiyat Endeksi", "endeks", "aylık", 1),
    "CES0500000003": ("Ortalama Saatlik Kazanç", "USD/saat", "aylık", 1),
    "PAYEMS": ("Tarım Dışı İstihdam Düzeyi", "bin kişi", "aylık", 1),
    "UNRATE": ("İşsizlik Oranı", "%", "aylık", 1),
    "JTSJOL": ("Açık İş Pozisyonları", "bin kişi", "aylık", 1),
    "GDPC1": ("Reel GSYH Düzeyi", "milyar zincirlenmiş USD", "çeyreklik", 1),
    "GDP": ("Nominal GSYH Düzeyi", "milyar USD/yıl", "çeyreklik", 1),
    "RSAFS": ("Perakende Satışlar", "milyon USD", "aylık", 1),
    "NFCI": ("Chicago Fed Finansal Koşullar Endeksi", "endeks", "haftalık", 1),
    "SOFR": ("SOFR", "%", "günlük", 1),
    "EFFR": ("Efektif Fed Faizi (EFFR)", "%", "günlük", 1),
    "DRCCLACBS": ("Kredi Kartı Temerrüt Oranı", "%", "çeyreklik", 1),
    "DRTSCILM": ("Ticari Kredi Standartları (SLOOS)", "% net yanıt", "çeyreklik", 1),
    "GDPNOW": ("Atlanta Fed GDPNow", "yıllıklandırılmış %", "çeyreklik", 1),
    "IRLTLT01JPM156N": ("Japonya 10Y Tahvil Faizi", "%", "aylık", 1),
    "IRLTLT01USM156N": ("ABD 10Y Tahvil Faizi (OECD aylık)", "%", "aylık", 1),
}

DERIVED_DEPS = {
    "Net Likidite (yaklaşık)": ("WALCL", "WTREGEN", "RRPONTSYD"),
    "SOFR - EFFR Farkı": ("SOFR", "EFFR"),
    "Çekirdek PCE Yıllık Değişim": ("PCEPILFE",),
    "Çekirdek TÜFE Yıllık Değişim": ("CPILFESL",),
    "ÜFE Yıllık Değişim": ("PPIACO",),
    "Saatlik Kazanç Yıllık Değişim": ("CES0500000003",),
    "Tarım Dışı İstihdam Aylık Fark": ("PAYEMS",),
    "Reel GSYH Çeyreklik Yıllıklandırılmış Büyüme": ("GDPC1",),
    "Reel GSYH Yıllık Büyüme": ("GDPC1",),
    "Nominal GSYH Yıllık Büyüme": ("GDP",),
    "Faiz Ödemesi / Vergi Geliri": ("A091RC1Q027SBEA", "W006RC1Q027SBEA"),
    "ABD 10Y Faiz - Nominal Büyüme (r-g vekili)": ("DGS10", "GDP"),
    "ABD-Japonya 10Y Faiz Farkı (aylık)": ("IRLTLT01USM156N", "IRLTLT01JPM156N"),
}

FRED_GROUPS = (
    ("Reel Faiz ve Enflasyon Beklentisi", ("DFII10", "T10YIE", "T5YIE", "T5YIFR")),
    ("Getiri Eğrisi", ("T10Y2Y", "T10Y3M", "DGS10", "DGS2", "DGS3MO")),
    ("Fed ve Net Likidite", ("WALCL", "WTREGEN", "RRPONTSYD", "M2SL", "Net Likidite (yaklaşık)")),
    ("Kredi ve Mali Baskı", ("BAMLH0A0HYM2", "THREEFYTP10", "A091RC1Q027SBEA",
                              "W006RC1Q027SBEA", "Faiz Ödemesi / Vergi Geliri",
                              "ABD 10Y Faiz - Nominal Büyüme (r-g vekili)", "FDHBFIN")),
    ("Enflasyon ve İstihdam", ("PCEPILFE", "Çekirdek PCE Yıllık Değişim",
                                "CPILFESL", "Çekirdek TÜFE Yıllık Değişim",
                                "PPIACO", "ÜFE Yıllık Değişim",
                                "CES0500000003", "Saatlik Kazanç Yıllık Değişim",
                                "PAYEMS", "Tarım Dışı İstihdam Aylık Fark", "UNRATE", "JTSJOL")),
    ("Büyüme ve Finansal Koşullar", ("GDPC1", "Reel GSYH Çeyreklik Yıllıklandırılmış Büyüme",
                                      "Reel GSYH Yıllık Büyüme", "GDP", "Nominal GSYH Yıllık Büyüme",
                                      "RSAFS", "NFCI", "SOFR", "EFFR",
                                      "SOFR - EFFR Farkı", "DRCCLACBS", "DRTSCILM", "GDPNOW")),
    ("Japonya ve Offshore Yuan", ("IRLTLT01JPM156N", "IRLTLT01USM156N",
                                    "ABD-Japonya 10Y Faiz Farkı (aylık)", "CNH=X")),
)

SERIES_NOTES = {
    "WALCL": "Çarşamba günkü Fed bilanço düzeyi; milyon USD olarak saklanır, milyar USD gösterilir.",
    "WTREGEN": "Çarşamba biten haftanın Hazine Genel Hesabı ortalaması; anlık bakiye değildir.",
    "GDPNOW": "FRED gözlem tarihi ilgili çeyreğin başlangıcıdır; günlük tahmin revizyon tarihi değildir.",
    "A091RC1Q027SBEA": "BEA federal cari faiz harcaması; yıllıklandırılmış düzey, bütçedeki net faiz gideri değildir.",
    "W006RC1Q027SBEA": "BEA federal cari vergi gelirleri; yıllıklandırılmış çeyreklik düzey.",
    "GDP": "Nominal GSYH; yıllıklandırılmış çeyreklik düzey.",
    "FDHBFIN": "Yabancı ve uluslararası yatırımcıların toplamı; yalnızca merkez bankaları değil.",
}


def default_database_path():
    """Use the same private files directory in the Android activity and service."""
    if sys.platform == "android" or os.environ.get("ANDROID_ARGUMENT"):
        try:
            from jnius import autoclass
        except Exception:
            autoclass = None
        if autoclass:
            for class_name, attribute in (("org.kivy.android.PythonActivity", "mActivity"),
                                          ("org.kivy.android.PythonService", "mService")):
                try:
                    context = getattr(autoclass(class_name), attribute)
                    if context:
                        return os.path.join(str(context.getFilesDir().getAbsolutePath()), "fred_cache.sqlite3")
                except Exception:
                    pass
        private = os.environ.get("ANDROID_PRIVATE")
        if private:
            return os.path.join(private, "fred_cache.sqlite3")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fred_cache.sqlite3")


class FredStore:
    def __init__(self, db_path=None, http_get=None):
        self.db_path = db_path or default_database_path()
        self.http_get = http_get or requests.get
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                series_id TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL,
                PRIMARY KEY (series_id, date))""")
            db.execute("""CREATE TABLE IF NOT EXISTS sync_status (
                series_id TEXT PRIMARY KEY, last_success_utc TEXT NOT NULL)""")

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def max_date(self, series_id):
        with closing(self._connect()) as db:
            row = db.execute("SELECT MAX(date) FROM observations WHERE series_id=?", (series_id,)).fetchone()
        return row[0] if row else None

    def sync_series(self, series_id):
        if series_id not in FRED_SERIES:
            raise ValueError("Bilinmeyen FRED serisi: " + str(series_id))
        last = self.max_date(series_id)
        start = (date.fromisoformat(last) - timedelta(days=45)).isoformat() if last else None
        params = {"id": series_id}
        if start:
            params["cosd"] = start
        response = self.http_get(FRED_CSV_URL, params=params, timeout=25)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
        if reader.fieldnames not in (["observation_date", series_id], ["DATE", series_id]):
            raise ValueError("Beklenmeyen FRED CSV başlığı: " + str(reader.fieldnames))
        date_field = reader.fieldnames[0]
        rows = []
        missing_dates = []
        for item in reader:
            raw = (item.get(series_id) or "").strip()
            obs_date = date.fromisoformat(item[date_field]).isoformat()
            if not raw or raw == ".":
                missing_dates.append((series_id, obs_date))
                continue
            value = float(raw)
            if math.isfinite(value):
                rows.append((series_id, obs_date, value))
        with closing(self._connect()) as db, db:
            db.executemany("DELETE FROM observations WHERE series_id=? AND date=?", missing_dates)
            db.executemany("INSERT OR REPLACE INTO observations(series_id,date,value) VALUES(?,?,?)", rows)
            db.execute("INSERT OR REPLACE INTO sync_status(series_id,last_success_utc) VALUES(?,?)",
                       (series_id, datetime.now(timezone.utc).isoformat()))
        return {"series_id": series_id, "start": start, "received": len(rows)}

    def sync_many(self, series_ids=None, workers=4):
        ids = list(dict.fromkeys(series_ids or FRED_SERIES.keys()))
        results, errors = {}, {}
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(ids)))) as pool:
            futures = {series_id: pool.submit(self.sync_series, series_id) for series_id in ids}
            for series_id, future in futures.items():
                try:
                    results[series_id] = future.result()
                except Exception as exc:
                    errors[series_id] = str(exc)[:160]
        return {"results": results, "errors": errors}

    def recent(self, series_id, count=13):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT date,value FROM observations WHERE series_id=? "
                              "ORDER BY date DESC LIMIT ?", (series_id, count)).fetchall()
        return list(reversed(rows))

    def daily_forward_fill(self, series_ids, days=60):
        """Calendar-day equivalent of pandas resample('D').ffill().

        Each stream is seeded from its last observation before the window.
        Missing data before a stream begins remain missing, never zero.
        """
        latest_dates = [self.max_date(code) for code in series_ids]
        if any(item is None for item in latest_dates):
            return []
        end = max(date.fromisoformat(item) for item in latest_dates)
        start = end - timedelta(days=days)
        streams = {}
        with closing(self._connect()) as db:
            for code in series_ids:
                seed = db.execute("SELECT date,value FROM observations WHERE series_id=? AND date<? "
                                  "ORDER BY date DESC LIMIT 1", (code, start.isoformat())).fetchone()
                rows = db.execute("SELECT date,value FROM observations WHERE series_id=? AND date>=? AND date<=? "
                                  "ORDER BY date", (code, start.isoformat(), end.isoformat())).fetchall()
                streams[code] = ([seed] if seed else []) + rows
        positions = {code: 0 for code in series_ids}
        current = {code: None for code in series_ids}
        aligned = []
        day = start
        while day <= end:
            day_string = day.isoformat()
            for code in series_ids:
                rows = streams[code]
                while positions[code] < len(rows) and rows[positions[code]][0] <= day_string:
                    current[code] = rows[positions[code]]
                    positions[code] += 1
            if all(current.values()):
                aligned.append((day_string, {code: current[code] for code in series_ids}))
            day += timedelta(days=1)
        return aligned

    def metrics(self):
        metrics = []
        histories = {}
        # FRED dates are period starts: monthly/quarterly data are published 1-2 months after
        # the period ends, so ages are measured against that publication lag, not the date.
        max_age_days = {"günlük": 10, "haftalık": 21, "aylık": 100, "çeyreklik": 230}

        def stale(obs_date, frequency):
            return bool(obs_date and (date.today() - date.fromisoformat(obs_date)).days > max_age_days[frequency])

        for code, (label, unit, frequency, scale) in FRED_SERIES.items():
            history = self.recent(code, 13)
            histories[code] = history
            latest = history[-1] if history else None
            metrics.append({"id": code, "name": label, "value": latest[1] * scale if latest else None,
                            "date": latest[0] if latest else None, "unit": unit,
                            "frequency": frequency, "source": "FRED",
                            "notes": SERIES_NOTES.get(code, ""),
                            "stale": stale(latest[0], frequency) if latest else False})

        def add(name, value=None, obs_date=None, unit="%", notes="", is_stale=False):
            metrics.append({"id": name, "name": name, "value": value,
                            "date": obs_date, "unit": unit, "frequency": "hesaplanan",
                            "source": "FRED türevi", "notes": notes, "stale": is_stale})

        def month_key(obs_date):
            d = date.fromisoformat(obs_date)
            return d.year * 12 + d.month

        def quarter_key(obs_date):
            d = date.fromisoformat(obs_date)
            return d.year * 4 + (d.month - 1) // 3

        aligned = self.daily_forward_fill(("WALCL", "WTREGEN", "RRPONTSYD"))
        if aligned:
            day, values = aligned[-1]
            dates = ", ".join(f"{code}: {values[code][0]}" for code in values)
            old = any(stale(values[code][0], FRED_SERIES[code][2]) for code in values)
            value = (values["WALCL"][1] - values["WTREGEN"][1]) / 1000 - values["RRPONTSYD"][1]
            add("Net Likidite (yaklaşık)", value, day, "milyar USD", dates, old)
        else:
            add("Net Likidite (yaklaşık)", unit="milyar USD")

        aligned = self.daily_forward_fill(("SOFR", "EFFR"))
        if aligned:
            day, values = aligned[-1]
            old = any(stale(values[code][0], "günlük") for code in values)
            add("SOFR - EFFR Farkı", (values["SOFR"][1] - values["EFFR"][1]) * 100,
                day, "baz puan", ", ".join(f"{code}: {values[code][0]}" for code in values), old)
        else:
            add("SOFR - EFFR Farkı", unit="baz puan")

        for code, name in (("PCEPILFE", "Çekirdek PCE Yıllık Değişim"),
                           ("CPILFESL", "Çekirdek TÜFE Yıllık Değişim"),
                           ("PPIACO", "ÜFE Yıllık Değişim"),
                           ("CES0500000003", "Saatlik Kazanç Yıllık Değişim")):
            values = histories[code]
            by_month = {month_key(obs_date): amount for obs_date, amount in values}
            baseline = by_month.get(month_key(values[-1][0]) - 12) if values else None
            value = (values[-1][1] / baseline - 1) * 100 if baseline else None
            add(name, value, values[-1][0] if value is not None else None,
                is_stale=stale(values[-1][0], "aylık") if values else False)

        payroll = histories["PAYEMS"]
        payroll_months = {month_key(obs_date): amount for obs_date, amount in payroll}
        prior_payroll = payroll_months.get(month_key(payroll[-1][0]) - 1) if payroll else None
        payroll_change = payroll[-1][1] - prior_payroll if prior_payroll is not None else None
        add("Tarım Dışı İstihdam Aylık Fark", payroll_change,
            payroll[-1][0] if payroll_change is not None else None, "bin kişi",
            is_stale=stale(payroll[-1][0], "aylık") if payroll else False)

        gdp = histories["GDPC1"]
        gdp_quarters = {quarter_key(obs_date): amount for obs_date, amount in gdp}
        prior_quarter = gdp_quarters.get(quarter_key(gdp[-1][0]) - 1) if gdp else None
        prior_year = gdp_quarters.get(quarter_key(gdp[-1][0]) - 4) if gdp else None
        qoq = 100 * ((gdp[-1][1] / prior_quarter) ** 4 - 1) if prior_quarter else None
        yoy = 100 * (gdp[-1][1] / prior_year - 1) if prior_year else None
        add("Reel GSYH Çeyreklik Yıllıklandırılmış Büyüme", qoq,
            gdp[-1][0] if qoq is not None else None, "yıllıklandırılmış %",
            is_stale=stale(gdp[-1][0], "çeyreklik") if gdp else False)
        add("Reel GSYH Yıllık Büyüme", yoy,
            gdp[-1][0] if yoy is not None else None,
            is_stale=stale(gdp[-1][0], "çeyreklik") if gdp else False)

        nominal = histories["GDP"]
        nominal_quarters = {quarter_key(obs_date): (obs_date, amount) for obs_date, amount in nominal}
        nominal_prior = nominal_quarters.get(quarter_key(nominal[-1][0]) - 4) if nominal else None
        nominal_yoy = (nominal[-1][1] / nominal_prior[1] - 1) * 100 if nominal_prior and nominal_prior[1] > 0 else None
        add("Nominal GSYH Yıllık Büyüme", nominal_yoy,
            nominal[-1][0] if nominal_yoy is not None else None, "%",
            f"Baz çeyrek {nominal_prior[0]}" if nominal_prior else "Aynı çeyrek geçen yıl yok",
            stale(nominal[-1][0], "çeyreklik") if nominal else False)

        interest_by_quarter = {quarter_key(obs_date): (obs_date, amount) for obs_date, amount in histories["A091RC1Q027SBEA"]}
        tax_by_quarter = {quarter_key(obs_date): (obs_date, amount) for obs_date, amount in histories["W006RC1Q027SBEA"]}
        common_quarters = interest_by_quarter.keys() & tax_by_quarter.keys()
        latest_common = max(common_quarters) if common_quarters else None
        if latest_common is not None and tax_by_quarter[latest_common][1] > 0:
            interest_date, interest_value = interest_by_quarter[latest_common]
            tax_date, tax_value = tax_by_quarter[latest_common]
            add("Faiz Ödemesi / Vergi Geliri", 100 * interest_value / tax_value,
                interest_date, "%", f"Aynı çeyrek SAAR: faiz {interest_date}; vergi {tax_date}",
                stale(interest_date, "çeyreklik"))
        else:
            add("Faiz Ödemesi / Vergi Geliri", notes="Eşleşen çeyreklik veri yok")

        dgs10 = histories["DGS10"]
        if dgs10 and nominal_yoy is not None:
            add("ABD 10Y Faiz - Nominal Büyüme (r-g vekili)", dgs10[-1][1] - nominal_yoy,
                dgs10[-1][0], "yüzde puan",
                f"DGS10 {dgs10[-1][0]} eksi nominal GSYH YoY {nominal[-1][0]}; borç stokunun ortalama faizi değildir",
                stale(dgs10[-1][0], "günlük") or stale(nominal[-1][0], "çeyreklik"))
        else:
            add("ABD 10Y Faiz - Nominal Büyüme (r-g vekili)", unit="yüzde puan")

        us_months = {month_key(obs_date): (obs_date, amount) for obs_date, amount in histories["IRLTLT01USM156N"]}
        jp_months = {month_key(obs_date): (obs_date, amount) for obs_date, amount in histories["IRLTLT01JPM156N"]}
        common_months = us_months.keys() & jp_months.keys()
        latest_month = max(common_months) if common_months else None
        if latest_month is not None:
            us_date, us_value = us_months[latest_month]
            jp_date, jp_value = jp_months[latest_month]
            add("ABD-Japonya 10Y Faiz Farkı (aylık)", us_value - jp_value, us_date,
                "yüzde puan", f"ABD {us_date} eksi Japonya {jp_date}; OECD aylık ortalamaları",
                stale(us_date, "aylık") or stale(jp_date, "aylık"))
        else:
            add("ABD-Japonya 10Y Faiz Farkı (aylık)", unit="yüzde puan")
        return metrics

    def trend_changes(self, series_ids, horizons=None):
        """Compare dated observations without treating a missing period as a valid baseline."""
        horizons = horizons or {"1m": 30, "1y": 365}
        max_gap = {"günlük": 7, "haftalık": 14, "aylık": 45, "çeyreklik": 100}
        rate_ids = {"DFII10", "T10YIE", "T5YIE", "T5YIFR", "T10Y2Y", "T10Y3M",
                    "DGS10", "DGS2", "DGS3MO", "SOFR", "EFFR", "IRLTLT01JPM156N", "IRLTLT01USM156N"}
        rate_ids.update({"BAMLH0A0HYM2", "THREEFYTP10"})
        output = []
        for code in series_ids:
            if code not in FRED_SERIES:
                continue
            name, unit, frequency, scale = FRED_SERIES[code]
            rows = self.recent(code, 500)
            if not rows:
                continue
            latest_day = date.fromisoformat(rows[-1][0])
            latest_value = rows[-1][1] * scale
            comparisons = {}
            for label, days in horizons.items():
                if frequency == "çeyreklik" and days < 80:
                    comparisons[label] = None
                    continue
                target = latest_day - timedelta(days=days)
                prior = next(((obs_date, amount * scale) for obs_date, amount in reversed(rows)
                              if date.fromisoformat(obs_date) <= target), None)
                if not prior or (target - date.fromisoformat(prior[0])).days > max_gap[frequency]:
                    comparisons[label] = None
                    continue
                if code in rate_ids:
                    change, change_unit = (latest_value - prior[1]) * 100, "baz puan"
                elif "%" in unit or unit == "yüzde puan":
                    # Includes GDPNOW and DRTSCILM: change of a rate is in percentage points.
                    change, change_unit = latest_value - prior[1], "yüzde puan"
                elif unit == "endeks":
                    change, change_unit = latest_value - prior[1], "endeks puanı"
                elif prior[1] > 0:
                    change, change_unit = (latest_value / prior[1] - 1) * 100, "%"
                else:
                    comparisons[label] = None
                    continue
                comparisons[label] = {"value": change, "unit": change_unit,
                                      "baseline_date": prior[0], "baseline_value": prior[1]}
            output.append({"id": code, "name": name, "date": rows[-1][0],
                           "value": latest_value, "unit": unit,
                           "frequency": frequency, "comparisons": comparisons})
        return output

    def derived_trend_changes(self, horizons=None):
        """Dated changes in aligned liquidity/funding proxies, retaining component dates."""
        horizons = horizons or {"1m": 30, "1y": 365}
        specs = (
            ("Net Likidite (yaklaşık)", ("WALCL", "WTREGEN", "RRPONTSYD"),
             lambda v: (v["WALCL"][1] - v["WTREGEN"][1]) / 1000 - v["RRPONTSYD"][1], "milyar USD"),
            ("SOFR - EFFR Farkı", ("SOFR", "EFFR"),
             lambda v: (v["SOFR"][1] - v["EFFR"][1]) * 100, "baz puan"),
        )
        output = []
        for name, codes, formula, unit in specs:
            aligned = self.daily_forward_fill(codes, days=400)
            if not aligned:
                continue
            latest_day, latest_values = aligned[-1]
            latest_number = formula(latest_values)
            by_day = {obs_day: formula(values) for obs_day, values in aligned}
            comparisons = {}
            for label, days in horizons.items():
                target = (date.fromisoformat(latest_day) - timedelta(days=days)).isoformat()
                baseline = by_day.get(target)
                comparisons[label] = ({"value": latest_number - baseline, "unit": unit,
                                       "baseline_date": target, "baseline_value": baseline}
                                      if baseline is not None else None)
            max_age = {"günlük": 10, "haftalık": 21}
            outdated = any((date.today() - date.fromisoformat(latest_values[code][0])).days >
                           max_age[FRED_SERIES[code][2]] for code in codes)
            output.append({"id": name, "name": name, "value": latest_number,
                           "date": latest_day, "unit": unit, "frequency": "hesaplanan",
                           "stale": outdated, "notes": ", ".join(f"{code}: {latest_values[code][0]}" for code in codes),
                           "comparisons": comparisons})
        return output


def required_series_for_names(names):
    names = set(names or [])
    ids = {code for code, spec in FRED_SERIES.items() if code in names or spec[0] in names}
    for name, deps in DERIVED_DEPS.items():
        if name in names:
            ids.update(deps)
    return ids


def mark_sync_errors(metrics, errors):
    """Annotate cached observations whose latest source refresh failed."""
    for item in metrics:
        dependencies = DERIVED_DEPS.get(item['id'], (item['id'],))
        failed = [code for code in dependencies if code in errors]
        if failed:
            item['sync_error'] = ', '.join(failed)
    return metrics


def fetch_cnh_quote():
    """Prefer yfinance when installed; retain a lightweight Yahoo chart fallback on Android."""
    try:
        import yfinance as yf
        frame = yf.Ticker("CNH=X").history(period="5d", interval="1d", auto_adjust=False)
        closes = frame["Close"].dropna()
        if not closes.empty:
            value = float(closes.iloc[-1])
            if math.isfinite(value) and value > 0:
                return {"value": value, "date": closes.index[-1].date().isoformat(),
                        "source": "Yahoo Finance (yfinance)"}
    except Exception:
        pass
    from market_feed import YahooFeed
    item = YahooFeed().latest("CNH=X")
    if item:
        return {"value": item["value"],
                "date": datetime.fromtimestamp(item["timestamp"], timezone.utc).date().isoformat(),
                "source": "Yahoo Finance chart"}
    return None
