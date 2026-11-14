"""Alarm rules and alarms.json persistence shared by the app and the background service.

Both processes read-modify-write the same file, so every write re-reads the file
first and applies only the fields the writer actually changed.
"""
import itertools
import json
import os
import time
from datetime import datetime, timezone

from i18n import tr, trd

GEX_CONDITIONS = ('put_wall', 'call_wall', 'gamma_flip')
GEX_LEVEL_MAX_AGE_SECONDS = 24 * 3600

_notification_counter = itertools.count()


def next_notification_id():
    """Distinct Android notification ids even for alarms fired in the same second."""
    return (int(time.time() * 1000) + next(_notification_counter)) % 2_000_000_000


def _crossed(last, target, current):
    return last is not None and ((last < target <= current) or (last > target >= current))


def _gex_level(alarm, gex_info, now=None):
    """Live levels from the app scan, else the copy stored on the alarm if recent."""
    key = {'put_wall': 'put_wall', 'call_wall': 'call_wall', 'gamma_flip': 'flip'}[alarm.get('cond_type')]
    info = gex_info
    if info is None:
        stored = alarm.get('gex_levels') or {}
        try:
            age = (now or time.time()) - float(stored.get('updated_at'))
        except (TypeError, ValueError):
            return None
        if not 0 <= age <= GEX_LEVEL_MAX_AGE_SECONDS:
            return None
        info = stored
    level = info.get(key)
    return float(level) if isinstance(level, (int, float)) and level > 0 else None


def evaluate_alarm(alarm, current, gex_info=None, now=None):
    """Return (triggered, title, message) for one observation; does not mutate the alarm."""
    sym = alarm.get('symbol', '')
    cond = alarm.get('cond_type', 'crossing')
    try:
        target = float(alarm.get('target_value', 0.0) or 0.0)
    except (TypeError, ValueError):
        target = 0.0
    last = alarm.get('last_seen_value', alarm.get('last_price'))
    last = float(last) if isinstance(last, (int, float)) else None
    current = float(current)
    # Notification text follows the interface language; the alarm keeps its source name.
    values = {"sym": trd(sym), "target": f"{target:,.2f}", "current": f"{current:,.2f}"}

    if cond == 'crossing':
        if last is not None:
            hit = _crossed(last, target, current)
        else:
            hit = abs(current - target) <= max(abs(target), 1e-4) * 0.005
        return hit, tr("ALARM: {sym} KESISME ({target})", **values), \
            tr("{sym} degeri {target} seviyesini kesti! (Guncel: {current})", **values)
    if cond in ('crossing_up', 'above'):
        hit = current >= target and (cond == 'above' or last is None or last < target)
        return hit, "ALARM: {sym} >= {target}".format(**values), \
            tr("{sym} degeri {target} seviyesinin uzerine cikti! (Guncel: {current})", **values)
    if cond in ('crossing_down', 'below'):
        hit = current <= target and (cond == 'below' or last is None or last > target)
        return hit, "ALARM: {sym} <= {target}".format(**values), \
            tr("{sym} degeri {target} seviyesinin altina indi! (Guncel: {current})", **values)
    if cond in GEX_CONDITIONS:
        level = _gex_level(alarm, gex_info, now)
        if level is None:
            return False, "", ""
        values["level"] = f"{level:,.2f}"
        if cond == 'call_wall':
            hit = current >= level and (last is None or last < level)
            return hit, tr("ALARM: {sym} CALL WALL DIRENCINDE!", **values), \
                tr("{sym} ({current}) ana Call Wall direncine ({level}) ulasti!", **values)
        hit = current <= level and (last is None or last > level)
        if cond == 'put_wall':
            return hit, tr("ALARM: {sym} PUT WALL DESTEGINDE!", **values), \
                tr("{sym} ({current}) ana Put Wall destegine ({level}) temas etti!", **values)
        return hit, tr("ALARM: {sym} GAMMA FLIP ASILDI!", **values), \
            tr("{sym} ({current}) Gamma Flip seviyesinin ({level}) altina indi!", **values)
    return False, "", ""


def is_checkable(alarm):
    return alarm.get('is_active', True) and not (
        alarm.get('triggered', False) and alarm.get('trigger_mode', 'once') == 'once')


def observe(alarm, current, triggered):
    """Apply one observation to the alarm in place; return only the changed fields."""
    changes = {'last_price': current, 'last_seen_value': current}
    if triggered:
        once = alarm.get('trigger_mode', 'once') == 'once'
        changes.update(triggered=once, is_active=not once,
                       triggered_at=datetime.now(timezone.utc).isoformat())
    alarm.update(changes)
    return changes


def read_alarms(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else None
    except (OSError, ValueError):
        return None


def write_alarms(path, alarms):
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(alarms, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _key(alarm):
    return alarm.get('id') or (alarm.get('symbol'), alarm.get('cond_type'), alarm.get('target_value'))


def save_changes(path, fallback_alarms, changes_by_key):
    """Re-read the file and apply only the given field changes to matching alarms.

    Alarms added or deleted by the other process since our read are preserved.
    """
    alarms = read_alarms(path)
    if alarms is None:
        alarms = fallback_alarms
    else:
        for alarm in alarms:
            changes = changes_by_key.get(_key(alarm))
            if changes:
                alarm.update(changes)
    write_alarms(path, alarms)
    return alarms


alarm_key = _key
