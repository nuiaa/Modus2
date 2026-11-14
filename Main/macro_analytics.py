"""Dated cross-market descriptive calculations; correlation is not causation."""
import calendar
import math
from datetime import date, timedelta


def _daily_changes(rows, relative=True):
    points = sorted({day: float(value) for day, value in rows
                     if isinstance(day, str) and value is not None and math.isfinite(float(value))}.items())
    result = {}
    for (prior_day, prior), (day, current) in zip(points, points[1:]):
        gap = (date.fromisoformat(day) - date.fromisoformat(prior_day)).days
        if gap > 7 or (relative and prior <= 0):
            continue
        result[day] = math.log(current / prior) if relative and current > 0 else current - prior
    return result


def dated_correlation(first_rows, second_rows, days=90, min_pairs=25, second_relative=True):
    """Pearson correlation on exact shared dates of daily changes in a recent window."""
    if not first_rows or not second_rows:
        return None
    end = min(date.fromisoformat(first_rows[-1][0]), date.fromisoformat(second_rows[-1][0]))
    if (date.today() - end).days > 10:
        return None
    start = (end - timedelta(days=days)).isoformat()
    first = _daily_changes(first_rows, True)
    second = _daily_changes(second_rows, second_relative)
    shared = [day for day in first.keys() & second.keys() if start <= day <= end.isoformat()]
    shared.sort()
    if len(shared) < min_pairs:
        return None
    x = [first[day] for day in shared]
    y = [second[day] for day in shared]
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    xx = sum((a - mean_x) ** 2 for a in x)
    yy = sum((b - mean_y) ** 2 for b in y)
    if xx <= 0 or yy <= 0:
        return None
    return {"r": numerator / math.sqrt(xx * yy), "pairs": len(shared),
            "start_date": shared[0], "end_date": shared[-1],
            "first_measure": "daily_log_return",
            "second_measure": "daily_log_return" if second_relative else "daily_level_change"}


def _months_before(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def matched_ratio(first_rows, second_rows):
    """Latest common-date ratio and calendar-horizon changes; raw units are retained."""
    second = dict(second_rows)
    common = sorted((day, first / second[day]) for day, first in first_rows
                    if day in second and first > 0 and second[day] > 0)
    if not common:
        return None
    latest_day, latest_ratio = common[-1]
    output = {"date": latest_day, "value": latest_ratio, "comparisons": {}, "matched_days": len(common)}
    for label, months in (("1m", 1), ("3m", 3), ("1y", 12)):
        target = _months_before(date.fromisoformat(latest_day), months)
        prior = next(((day, value) for day, value in reversed(common) if day <= target.isoformat()), None)
        gap = (target - date.fromisoformat(prior[0])).days if prior else None
        output["comparisons"][label] = (
            {"value_pct": (latest_ratio / prior[1] - 1) * 100, "baseline_date": prior[0]}
            if prior and gap <= 7 else None
        )
    return output
