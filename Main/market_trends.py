"""Dated raw Yahoo close history and deterministic, non-predictive summaries."""
import calendar
import math
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone


def default_database_path():
    # Reuse the activity/service-safe directory without sharing the FRED schema.
    from fred_feed import default_database_path as fred_path
    return os.path.join(os.path.dirname(fred_path()), "market_trends.sqlite3")


def _months_before(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class MarketTrendStore:
    def __init__(self, db_path=None, feed=None):
        self.db_path = db_path or default_database_path()
        if feed is None:
            from market_feed import YahooFeed
            feed = YahooFeed()
        self.feed = feed
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS daily_closes (symbol TEXT NOT NULL, date TEXT NOT NULL, close REAL NOT NULL CHECK(close > 0), PRIMARY KEY(symbol,date))")
            db.execute("CREATE TABLE IF NOT EXISTS trend_sync_status (symbol TEXT PRIMARY KEY, last_success_utc TEXT NOT NULL)")

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def history(self, symbol, days=400):
        """Dated raw closes for cross-market calculations."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        with closing(self._connect()) as db:
            return db.execute("SELECT date,close FROM daily_closes WHERE symbol=? AND date>=? ORDER BY date",
                              (symbol, cutoff)).fetchall()

    def sync(self, symbol):
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("A nonempty symbol is required")
        with closing(self._connect()) as db:
            latest = db.execute("SELECT MAX(date) FROM daily_closes WHERE symbol=?", (symbol,)).fetchone()[0]
        # Catch up long offline intervals instead of leaving an undetected hole.
        range_str = "1mo" if latest and (date.today() - date.fromisoformat(latest)).days <= 25 else "2y"
        points = self.feed.observations(symbol, range_str=range_str)
        rows = {}
        for stamp, close in points:
            try:
                value = float(close)
                day = datetime.fromtimestamp(stamp, timezone.utc).date()
                if math.isfinite(value) and value > 0 and day <= date.today():
                    rows[day.isoformat()] = value
            except (ValueError, TypeError, OverflowError, OSError):
                continue
        if not rows:
            return {"symbol": symbol, "ok": False, "received": 0, "range": range_str,
                    "error": "No valid observations returned; existing history retained"}
        with closing(self._connect()) as db, db:
            db.executemany("INSERT OR REPLACE INTO daily_closes(symbol,date,close) VALUES(?,?,?)",
                           [(symbol, day, value) for day, value in sorted(rows.items())])
            db.execute("INSERT OR REPLACE INTO trend_sync_status VALUES(?,?)",
                       (symbol, datetime.now(timezone.utc).isoformat()))
        return {"symbol": symbol, "ok": True, "received": len(rows), "range": range_str}

    def summary(self, symbol):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT date,close FROM daily_closes WHERE symbol=? ORDER BY date", (symbol,)).fetchall()
            status = db.execute("SELECT last_success_utc FROM trend_sync_status WHERE symbol=?", (symbol,)).fetchone()
        notes = ["Raw unadjusted closes: splits, dividends and futures rolls can distort returns.",
                 "Dates use Yahoo timestamps converted to UTC; latest daily bar may be incomplete."]
        result = {"symbol": symbol, "basis": "raw_close", "observation_count": len(rows),
                  "observation_date": rows[-1][0] if rows else None,
                  "latest_close": rows[-1][1] if rows else None,
                  "last_success_utc": status[0] if status else None,
                  "returns": {}, "sma": {}, "range_52w": None,
                  "volatility_20d_pct": None, "quality_notes": notes}
        if not rows:
            notes.append("No observations available.")
            return result
        latest_day = date.fromisoformat(rows[-1][0])
        latest_close = rows[-1][1]
        age = (date.today() - latest_day).days
        result["age_days"] = age
        result["stale"] = age > 7
        if age > 7:
            notes.append("Latest observation is more than seven calendar days old.")
        for name, months in (("1m", 1), ("3m", 3), ("1y", 12)):
            target = _months_before(latest_day, months)
            prior = next((row for row in reversed(rows) if row[0] <= target.isoformat()), None)
            gap = (target - date.fromisoformat(prior[0])).days if prior else None
            valid = prior is not None and gap <= 7
            result["returns"][name] = {"value_pct": (latest_close / prior[1] - 1) * 100 if valid else None,
                                       "target_date": target.isoformat(), "baseline_date": prior[0] if prior else None,
                                       "end_date": latest_day.isoformat(), "gap_days": gap}
            if not valid:
                notes.append(name + " return unavailable: no baseline within seven days before target.")
        gaps = [(date.fromisoformat(b[0]) - date.fromisoformat(a[0])).days for a, b in zip(rows, rows[1:])]
        if any(gap > 7 for gap in gaps):
            notes.append("History contains gaps longer than seven calendar days; moving averages use observed bars only.")
        for window in (20, 50, 200):
            sample = rows[-window:]
            result["sma"][str(window)] = {"value": sum(row[1] for row in sample) / window if len(sample) == window else None,
                                          "count": len(sample), "start_date": sample[0][0], "end_date": rows[-1][0]}
        recent = rows[-21:]
        if len(recent) == 21 and all((date.fromisoformat(b[0]) - date.fromisoformat(a[0])).days <= 7
                                      for a, b in zip(recent, recent[1:])):
            log_returns = [math.log(b[1] / a[1]) for a, b in zip(recent, recent[1:])]
            average = sum(log_returns) / len(log_returns)
            variance = sum((value - average) ** 2 for value in log_returns) / (len(log_returns) - 1)
            sessions_per_year = 365 if symbol == "BTC-USD" else 252
            result["volatility_20d_pct"] = math.sqrt(variance * sessions_per_year) * 100
        start = latest_day - timedelta(weeks=52)
        sample = [row for row in rows if row[0] >= start.isoformat()]
        peak, worst = sample[0][1], 0.0
        for _, value in sample:
            peak = max(peak, value)
            worst = min(worst, (value / peak - 1) * 100)
        high, low = max(row[1] for row in sample), min(row[1] for row in sample)
        full = date.fromisoformat(rows[0][0]) <= start + timedelta(days=7)
        result["range_52w"] = {"low": low, "high": high, "drawdown_from_high_pct": (latest_close / high - 1) * 100,
                                "max_drawdown_pct": worst, "start_date": sample[0][0], "end_date": sample[-1][0],
                                "count": len(sample), "full_window": full}
        if not full:
            notes.append("52-week range covers only the available partial history.")
        return result
