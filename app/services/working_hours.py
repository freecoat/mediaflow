"""Engine orario lavorativo: split smart di un range in slot rispettando policy.

E3 v3.4.17 — Dato un range start/end e una WorkingHoursPolicy, ritorna
una lista di intervalli (start, end) ritagliati su:
  - giorni lavorativi (working_days bitmask)
  - orario mattina + pomeriggio (con pausa pranzo)
  - festività nazionali (holidays_country)
  - ferie/malattia (ResourceUnavailability)
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Set, Iterable

from app.models import WorkingHoursPolicy, ResourceUnavailability


@dataclass
class TimeSlot:
    start: datetime
    end: datetime


def _bit_for_weekday(d: date) -> int:
    """Bit per giorno: lun=0..dom=6."""
    return 1 << d.weekday()


def _is_working_day(policy: WorkingHoursPolicy, d: date,
                    holidays_set: Set[date], unav_set: Set[date]) -> bool:
    if d in unav_set:
        return False
    if d in holidays_set:
        return False
    return bool(policy.working_days & _bit_for_weekday(d))


def _intersect(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> Optional[TimeSlot]:
    s = max(s1, s2)
    e = min(e1, e2)
    if e <= s:
        return None
    return TimeSlot(s, e)


def _day_intervals(policy: WorkingHoursPolicy, d: date) -> List[TimeSlot]:
    """Intervalli di lavoro nel giorno: mattina + (eventuale) pomeriggio."""
    out = [TimeSlot(
        datetime.combine(d, policy.morning_start),
        datetime.combine(d, policy.morning_end),
    )]
    if policy.afternoon_start and policy.afternoon_end:
        out.append(TimeSlot(
            datetime.combine(d, policy.afternoon_start),
            datetime.combine(d, policy.afternoon_end),
        ))
    return out


def get_holidays(policy: WorkingHoursPolicy, year_from: int, year_to: int) -> Set[date]:
    """Festività nazionali per gli anni richiesti, o set vuoto se policy disabilita."""
    if not policy.holidays_country:
        return set()
    try:
        import holidays as _hol
        years = list(range(year_from, year_to + 1))
        country = policy.holidays_country.upper()
        # Es. holidays.IT(years=[2026])
        country_class = getattr(_hol, country, None)
        if not country_class:
            return set()
        return set(country_class(years=years).keys())
    except Exception:
        return set()


def _unavailability_dates(unavailabilities: Iterable[ResourceUnavailability]) -> Set[date]:
    """Espande gli intervalli ferie/malattia in set di date."""
    out: Set[date] = set()
    for u in unavailabilities:
        d = u.start_date
        while d <= u.end_date:
            out.add(d)
            d += timedelta(days=1)
    return out


def split_booking_smart(
    start: datetime,
    end: datetime,
    policy: WorkingHoursPolicy,
    unavailabilities: Optional[Iterable[ResourceUnavailability]] = None,
) -> List[TimeSlot]:
    """Splitta un range richiesto in N slot rispettando la policy.

    Se policy.afternoon_* è valorizzato → ogni giorno produce 2 slot
    (mattina + pomeriggio) separati dalla pausa pranzo.
    Salta weekend (in base a working_days), festività, e date in unavailabilities.
    """
    if end <= start:
        return []
    holidays_set = get_holidays(policy, start.year, end.year)
    unav_set = _unavailability_dates(unavailabilities or [])

    out: List[TimeSlot] = []
    cur = start.date()
    last = end.date()
    while cur <= last:
        if _is_working_day(policy, cur, holidays_set, unav_set):
            for interval in _day_intervals(policy, cur):
                clipped = _intersect(start, end, interval.start, interval.end)
                if clipped:
                    out.append(clipped)
        cur += timedelta(days=1)
    return out


def is_working_at(
    dt: datetime,
    policy: WorkingHoursPolicy,
    unavailabilities: Optional[Iterable[ResourceUnavailability]] = None,
) -> bool:
    """True se `dt` cade in un orario lavorativo (no weekend/festività/ferie/pausa)."""
    holidays_set = get_holidays(policy, dt.year, dt.year)
    unav_set = _unavailability_dates(unavailabilities or [])
    if not _is_working_day(policy, dt.date(), holidays_set, unav_set):
        return False
    for interval in _day_intervals(policy, dt.date()):
        if interval.start <= dt < interval.end:
            return True
    return False
