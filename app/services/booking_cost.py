"""Engine costo booking (v3.4.32).

Dato un BookingAssignment (intervallo per una specifica risorsa) + WorkingHoursPolicy,
ritorna un breakdown delle ore divise per fascia con i moltiplicatori applicati.

A differenza di `overtime.py` (che opera sui TimePunch HR, basato sulla soglia
giornaliera), qui l'overtime è **basato sulla fascia oraria** della policy:
ore fuori da `morning_start..morning_end` + `afternoon_start..afternoon_end`
sono considerate overtime indipendentemente dal totale giornaliero.

Questo è più adatto al booking: l'operatore sa subito se sta lavorando in
straordinario in base all'orario, senza dover sapere quanto avrà accumulato
nella giornata.

Cost report cliente: parte dal Booking, NON dai TimePunch. Le timbrature
sono altro binario (HR / consulente del lavoro). Vedi memoria
`project_costreport_vs_timesheet.md`.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import Iterable, List, Optional, Set, Tuple

from app.models import (
    Booking, BookingAssignment, WorkingHoursPolicy,
    BookingExecutionStatus, BookingOvertimeStatus,
)


@dataclass
class BookingBreakdown:
    """Ore di un booking_assignment spezzate per categoria.

    overtime_hours include tutto quanto cade fuori dalle fasce regolari della
    policy (prima di morning_start, fra morning_end e afternoon_start,
    dopo afternoon_end). night_hours è la sotto-quota dell'overtime caduta
    in fascia notturna (riceve night_multiplier al posto di overtime_multiplier).

    sunday_hours / holiday_hours sono mutually exclusive con regular/overtime:
    se il giorno è festivo o domenica, l'intero booking di quel giorno conta
    nelle ore "speciali" e si applica il moltiplicatore corrispondente
    (regular/overtime non vengono sommati per quel giorno).
    """
    total_hours: float = 0.0
    regular_hours: float = 0.0
    overtime_hours: float = 0.0
    night_hours: float = 0.0
    sunday_hours: float = 0.0
    holiday_hours: float = 0.0
    # Ore overtime "in attesa di approvazione" (booking.overtime_status=pending)
    # Mostrate ma NON conteggiate nel weighted_factor finché approved.
    pending_overtime_hours: float = 0.0
    # Fattore moltiplicativo cumulato applicato al rate base. Se il booking
    # ha overtime_status=pending, le ore overtime non sono ancora pesate
    # (ma si vedono in pending_overtime_hours).
    weighted_factor: float = 0.0
    # Ore booking in pool not_done (count_in_costs=False) → escluse dal weighted
    # ma riportate per UI.
    not_done_pool_hours: float = 0.0

    def as_dict(self) -> dict:
        return {
            "total_hours": round(self.total_hours, 2),
            "regular_hours": round(self.regular_hours, 2),
            "overtime_hours": round(self.overtime_hours, 2),
            "night_hours": round(self.night_hours, 2),
            "sunday_hours": round(self.sunday_hours, 2),
            "holiday_hours": round(self.holiday_hours, 2),
            "pending_overtime_hours": round(self.pending_overtime_hours, 2),
            "not_done_pool_hours": round(self.not_done_pool_hours, 2),
            "weighted_factor": round(self.weighted_factor, 4),
        }

    def add(self, other: "BookingBreakdown") -> None:
        for fld in (
            "total_hours", "regular_hours", "overtime_hours", "night_hours",
            "sunday_hours", "holiday_hours", "pending_overtime_hours",
            "not_done_pool_hours", "weighted_factor",
        ):
            setattr(self, fld, getattr(self, fld) + getattr(other, fld))


def _hours(td: timedelta) -> float:
    return td.total_seconds() / 3600.0


def _split_at_midnight(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    out = []
    cur = start
    while cur.date() < end.date():
        next_midnight = datetime.combine(cur.date() + timedelta(days=1), time(0, 0))
        out.append((cur, next_midnight))
        cur = next_midnight
    if cur < end:
        out.append((cur, end))
    return out


def _overlap_hours(a_start: datetime, a_end: datetime,
                   b_start: datetime, b_end: datetime) -> float:
    s = max(a_start, b_start)
    e = min(a_end, b_end)
    if e <= s:
        return 0.0
    return _hours(e - s)


def _regular_window(d: date, policy: WorkingHoursPolicy) -> List[Tuple[datetime, datetime]]:
    """Fasce regolari della policy applicate al giorno `d`."""
    out: List[Tuple[datetime, datetime]] = []
    if policy.morning_start and policy.morning_end:
        out.append((datetime.combine(d, policy.morning_start),
                    datetime.combine(d, policy.morning_end)))
    if policy.afternoon_start and policy.afternoon_end:
        out.append((datetime.combine(d, policy.afternoon_start),
                    datetime.combine(d, policy.afternoon_end)))
    return out


def _night_overlap(seg_start: datetime, seg_end: datetime,
                   policy: WorkingHoursPolicy) -> float:
    """Quante ore del segmento (intra-day) cadono in fascia notturna."""
    ns, ne = policy.night_start, policy.night_end
    if not ns or not ne:
        return 0.0
    d = seg_start.date()
    day_start = datetime.combine(d, time(0, 0))
    day_end = day_start + timedelta(days=1)
    total = 0.0
    if ne > time(0, 0):
        # Mattina presto: 00:00..ne
        ne_dt = datetime.combine(d, ne)
        total += _overlap_hours(seg_start, seg_end, day_start, ne_dt)
    if ns < time(23, 59):
        # Sera/notte: ns..24:00
        ns_dt = datetime.combine(d, ns)
        total += _overlap_hours(seg_start, seg_end, ns_dt, day_end)
    return total


def compute_assignment_breakdown(
    assignment: BookingAssignment,
    policy: WorkingHoursPolicy,
    holidays_set: Optional[Set[date]] = None,
    booking: Optional[Booking] = None,
) -> BookingBreakdown:
    """Breakdown ore per un singolo BookingAssignment.

    `booking` opzionale: se passato, condiziona l'attribuzione delle ore in
    base a `execution_status`/`overtime_status`/`count_in_costs`:
      - not_done + count_in_costs=False: tutte le ore vanno in not_done_pool
      - overtime_status=pending: ore overtime calcolate ma in pending_overtime
      - overtime_status=rejected: equivalente a none (di solito non arriva
        qui perché il booking è stato split su rifiuto, vedi cascade)
    """
    out = BookingBreakdown()
    s, e = assignment.start_datetime, assignment.end_datetime
    if not s or not e or e <= s:
        return out

    book = booking or assignment.booking
    is_pool = (
        book is not None
        and book.execution_status == BookingExecutionStatus.not_done
        and not book.count_in_costs
    )
    is_pending = (
        book is not None
        and book.overtime_status == BookingOvertimeStatus.pending
    )

    if holidays_set is None:
        holidays_set = set()

    # Splitta per-giorno
    for seg_s, seg_e in _split_at_midnight(s, e):
        seg_hours = _hours(seg_e - seg_s)
        d = seg_s.date()
        out.total_hours += seg_hours

        if is_pool:
            out.not_done_pool_hours += seg_hours
            continue

        is_sun = (d.weekday() == 6)
        is_hol = (d in holidays_set)
        if is_hol:
            out.holiday_hours += seg_hours
            continue
        if is_sun:
            out.sunday_hours += seg_hours
            continue

        # Giorno normale: separa regular vs overtime in base a fasce policy
        windows = _regular_window(d, policy)
        regular_in_seg = 0.0
        for ws, we in windows:
            regular_in_seg += _overlap_hours(seg_s, seg_e, ws, we)
        overtime_in_seg = max(0.0, seg_hours - regular_in_seg)
        night_in_seg = _night_overlap(seg_s, seg_e, policy)
        # night è sotto-quota di overtime (l'overlap notte è sempre fuori
        # dalle fasce regolari diurne)
        if is_pending:
            out.pending_overtime_hours += overtime_in_seg
        else:
            out.overtime_hours += overtime_in_seg
        out.regular_hours += regular_in_seg
        # night va contato solo come componente overtime (non additivo a totale)
        if is_pending:
            # Tracciato comunque per UI ma non pesato
            pass
        else:
            out.night_hours += night_in_seg

    # Weighted factor (=ore equivalenti dopo moltiplicatori)
    h_mult = policy.holiday_multiplier or 1.0
    s_mult = policy.sunday_multiplier or 1.0
    o_mult = policy.overtime_multiplier or 1.0
    n_mult = policy.night_multiplier or 1.0

    weighted = 0.0
    weighted += out.holiday_hours * h_mult
    weighted += out.sunday_hours * s_mult
    # v3.4.32.2: scaglioni overtime se policy.overtime_brackets è valorizzato
    # (es. CCNL Cinema Doppiaggio: prime 2h +30%, poi +60%). Le ore notturne
    # mantengono comunque il night_multiplier, sostituendolo a quello dello
    # scaglione: night = "fuori orario notte profonda", non sub-overtime.
    overtime_non_night = max(0.0, out.overtime_hours - out.night_hours)
    if policy.overtime_brackets:
        weighted += _weighted_overtime_with_brackets(
            overtime_non_night, policy.overtime_brackets, o_mult,
        )
    else:
        weighted += overtime_non_night * o_mult
    weighted += out.night_hours * n_mult
    weighted += out.regular_hours * 1.0
    out.weighted_factor = weighted
    return out


def _weighted_overtime_with_brackets(
    hours: float, brackets: list, fallback_mult: float,
) -> float:
    """Distribuisce `hours` di overtime sui scaglioni e somma il weighted.

    `brackets` = [{"from_hour": float, "multiplier": float}, ...] ordinato.
    Le ore vengono distribuite in ordine: scaglione 0..from_hour_1 con
    multiplier_0, scaglione from_hour_1..from_hour_2 con multiplier_1, ecc.
    L'ultimo scaglione assorbe tutte le ore residue.

    Se `brackets` è malformato o vuoto, usa `fallback_mult` su tutte le ore.
    """
    if not brackets or not isinstance(brackets, list):
        return hours * fallback_mult
    try:
        sorted_b = sorted(
            [{"from_hour": float(b.get("from_hour", 0)), "multiplier": float(b.get("multiplier", 1.0))}
             for b in brackets],
            key=lambda x: x["from_hour"],
        )
    except (TypeError, ValueError):
        return hours * fallback_mult
    if not sorted_b:
        return hours * fallback_mult

    weighted = 0.0
    remaining = hours
    for i, bk in enumerate(sorted_b):
        if remaining <= 0:
            break
        next_from = sorted_b[i + 1]["from_hour"] if i + 1 < len(sorted_b) else None
        if next_from is None:
            # Ultimo scaglione assorbe tutto
            weighted += remaining * bk["multiplier"]
            remaining = 0.0
        else:
            slot_hours = max(0.0, next_from - bk["from_hour"])
            take = min(remaining, slot_hours)
            weighted += take * bk["multiplier"]
            remaining -= take
    return weighted


def has_overtime_window(
    start: datetime, end: datetime,
    policy: WorkingHoursPolicy,
    holidays_set: Optional[Set[date]] = None,
) -> bool:
    """True se l'intervallo cade (anche solo in parte) fuori dalle fasce
    regolari della policy in un giorno feriale-non-festivo. Domenica e
    festività sono giorni interi "speciali" e non scattano overtime
    (ricevono già il loro moltiplicatore).
    """
    if end <= start:
        return False
    holidays_set = holidays_set or set()
    for seg_s, seg_e in _split_at_midnight(start, end):
        d = seg_s.date()
        if d.weekday() == 6 or d in holidays_set:
            continue
        seg_hours = _hours(seg_e - seg_s)
        windows = _regular_window(d, policy)
        regular_in_seg = sum(_overlap_hours(seg_s, seg_e, ws, we)
                             for ws, we in windows)
        if seg_hours - regular_in_seg > 1e-6:
            return True
    return False


def working_day_end(d: date, policy: WorkingHoursPolicy) -> Optional[datetime]:
    """Fine della fascia regolare per il giorno `d` secondo la policy.
    = afternoon_end se presente, altrimenti morning_end."""
    if policy.afternoon_end:
        return datetime.combine(d, policy.afternoon_end)
    if policy.morning_end:
        return datetime.combine(d, policy.morning_end)
    return None


def absolute_day_limit(d: date, policy: WorkingHoursPolicy) -> datetime:
    """Limite assoluto oltre il quale neanche overtime è permesso (D2=c).

    Usa night_end del giorno successivo: copre i turni notturni veri delle
    case di post-prod (default 06:00 del giorno dopo). Se policy.night_end
    è None, fallback a 23:59 dello stesso giorno.
    """
    if policy.night_end:
        return datetime.combine(d + timedelta(days=1), policy.night_end)
    return datetime.combine(d, time(23, 59, 59))
