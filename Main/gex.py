"""Black-Scholes gamma exposure helpers (naive dealer convention: long calls, short puts)."""
import math
from datetime import date, datetime, timedelta, timezone


def norm_pdf(x):
    return math.exp(-x ** 2 / 2.0) / math.sqrt(2.0 * math.pi)


def compute_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_pdf(d1) / (S * sigma * math.sqrt(T))


def _nth_sunday(year, month, n):
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def us_market_close_utc(day):
    """16:00 New York time on ``day`` in UTC, without needing tzdata on Android."""
    dst = _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)
    return datetime(day.year, day.month, day.day, 20 if dst else 21, tzinfo=timezone.utc)


def expiry_date(exp_ts):
    """Yahoo lists expirations at 00:00 UTC of the expiration day."""
    return datetime.fromtimestamp(exp_ts, timezone.utc).date()


def years_to_expiry(exp_ts, now=None, minimum_seconds=3600):
    now = now or datetime.now(timezone.utc)
    seconds = (us_market_close_utc(expiry_date(exp_ts)) - now).total_seconds()
    return max(seconds, minimum_seconds) / (365.25 * 86400)


def dollar_gamma(spot, strike, T, r, iv, oi, mult):
    """Dollar gamma per 1% move."""
    return compute_gamma(spot, strike, T, r, iv) * oi * mult * spot ** 2 * 0.01


def net_gex(positions, spot, T, r, mult):
    """positions: iterable of (strike, iv, open_interest, sign) with sign +1 call / -1 put."""
    return sum(sign * dollar_gamma(spot, k, T, r, iv, oi, mult) for k, iv, oi, sign in positions)


def gamma_flip(positions, spot, T, r, mult, band, steps=80):
    """Hypothetical spot where net GEX changes sign, nearest to the current spot."""
    positions = list(positions)
    if not positions or spot <= 0:
        return None
    low, high = spot * (1.0 - band), spot * (1.0 + band)
    grid = [low + (high - low) * i / steps for i in range(steps + 1)]
    values = [net_gex(positions, s, T, r, mult) for s in grid]
    crossings = []
    for (s0, v0), (s1, v1) in zip(zip(grid, values), zip(grid[1:], values[1:])):
        if v0 == 0:
            crossings.append(s0)
        elif v0 * v1 < 0:
            crossings.append(s0 + (s1 - s0) * v0 / (v0 - v1))
    return min(crossings, key=lambda s: abs(s - spot)) if crossings else None
