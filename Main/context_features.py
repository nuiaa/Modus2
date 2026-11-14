"""Deterministic relative features for the AI context.

LLMs compare raw numbers unreliably, so levels are expressed here relative to
their own history (percentile, z-score), to moving averages and to spot.
Every label is descriptive; none is a trading signal.
"""
import math
from datetime import date, timedelta


def _clean(rows):
    points = {}
    for day, value in rows or ():
        try:
            number = float(value)
            date.fromisoformat(day)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            points[day] = number
    return sorted(points.items())


def parse_level(text):
    """Parse a display level such as '2,650.00'; '-' or 'Veri yok' give None."""
    try:
        value = float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def distance_pct(value, reference):
    """Percent by which value sits above (+) or below (-) reference."""
    try:
        value, reference = float(value), float(reference)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(value) and math.isfinite(reference)) or reference <= 0:
        return None
    return (value / reference - 1) * 100


def history_position(rows, years=1, min_count=50):
    """Where the latest observation sits within its own trailing window.

    Percentile is the mid-rank share of window observations below the latest
    value (ties count half), so a value equal to every other point gives 50.
    """
    points = _clean(rows)
    if not points:
        return None
    end_day, latest = points[-1]
    start = (date.fromisoformat(end_day) - timedelta(days=round(365.25 * years))).isoformat()
    window = [value for day, value in points if day >= start]
    if len(window) < min_count:
        return None
    below = sum(1 for value in window if value < latest)
    equal = sum(1 for value in window if value == latest)
    mean = sum(window) / len(window)
    variance = sum((value - mean) ** 2 for value in window) / (len(window) - 1)
    deviation = math.sqrt(variance)
    return {"value": latest, "end_date": end_day, "start_date": next(day for day, _ in points if day >= start),
            "count": len(window), "percentile": (below + 0.5 * equal) / len(window) * 100,
            "zscore": (latest - mean) / deviation if deviation > 0 else None,
            "low": min(window), "high": max(window), "years": years}


def percentile_label(percentile):
    if percentile is None:
        return None
    if percentile >= 90:
        return "pencerenin en üst %10'unda"
    if percentile >= 70:
        return "pencere ortalamasının belirgin üstünde"
    if percentile > 30:
        return "pencerenin orta bölgesinde"
    if percentile > 10:
        return "pencere ortalamasının belirgin altında"
    return "pencerenin en alt %10'unda"


def format_history_position(name, position, unit=""):
    if not position:
        return None
    unit = f" {unit}" if unit else ""
    span = f"{position['years']:g}y"
    z = f", z={position['zscore']:+.2f}" if position.get('zscore') is not None else ""
    return (f"{name} {position['value']:.3f}{unit}: son {span} içinde persentil %{position['percentile']:.0f}{z} "
            f"({percentile_label(position['percentile'])}; aralık {position['low']:.3f}–{position['high']:.3f}, "
            f"{position['count']} gözlem, {position['start_date']}–{position['end_date']})")


def sma_position(latest_close, sma):
    """Distance of the latest close to each available SMA and the 50/200 order."""
    result = {"distances": {}, "order": None}
    values = {}
    for window in ("20", "50", "200"):
        value = ((sma or {}).get(window) or {}).get("value")
        distance = distance_pct(latest_close, value)
        if distance is not None:
            result["distances"][window] = distance
            values[window] = value
    if "50" in values and "200" in values:
        result["order"] = "SMA50 > SMA200" if values["50"] > values["200"] else "SMA50 < SMA200"
    return result


def format_sma_position(position):
    if not position or not position["distances"]:
        return None
    parts = [f"SMA{window}'ün {distance:+.2f}% {'üstünde' if distance >= 0 else 'altında'}"
             for window, distance in position["distances"].items()]
    text = "fiyat " + ", ".join(parts)
    if position["order"]:
        text += f"; {position['order']}"
    return text


def gex_position(spot, put_wall=None, call_wall=None, flip=None):
    """Percent distances of option levels to spot and spot's side of the flip."""
    result = {"put_wall": distance_pct(put_wall, spot), "call_wall": distance_pct(call_wall, spot),
              "flip": distance_pct(flip, spot), "side_of_flip": None, "inside_walls": None}
    if result["flip"] is not None:
        result["side_of_flip"] = "below" if result["flip"] > 0 else "above"
    if result["put_wall"] is not None and result["call_wall"] is not None:
        result["inside_walls"] = result["put_wall"] <= 0 <= result["call_wall"]
    return result


def format_gex_position(position):
    if not position:
        return None
    parts = []
    for key, label in (("put_wall", "put duvarı"), ("flip", "flip"), ("call_wall", "call duvarı")):
        if position[key] is not None:
            parts.append(f"{label} spota göre {position[key]:+.2f}%")
    if position["side_of_flip"]:
        parts.append("spot flip'in " + ("altında" if position["side_of_flip"] == "below" else "üstünde"))
    if position["inside_walls"] is not None:
        parts.append("spot put–call duvarları arasında" if position["inside_walls"] else "spot put–call duvar aralığının dışında")
    return "; ".join(parts) if parts else None
