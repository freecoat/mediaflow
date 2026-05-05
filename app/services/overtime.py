"""Engine straordinari (v3.4.21).

Dato un set di TimePunch + WorkingHoursPolicy, ritorna un breakdown
delle ore lavorate diviso per categoria di maggiorazione:

  - regular_hours           ore "normali" entro soglia giornaliera
  - overtime_daily_hours    ore oltre daily_hours_threshold nello stesso giorno
  - overtime_weekly_hours   ore oltre weekly_hours_threshold nella settimana
                            (al netto già di overtime_daily, evita doppi conteggi)
  - night_hours             ore che cadono nella fascia notturna
  - sunday_hours            ore lavorate di domenica
  - holiday_hours           ore lavorate in festività (holidays_country)
  - weighted_factor         "ore equivalenti" applicando il MAX dei moltiplicatori
                            applicabili a ciascun minuto (no cumulo). Serve come
                            fattore per moltiplicare il rate orario al cost report.

Solo punch con kind in (shift, overtime) contano. Ferie/malattia/pausa/idle
sono fuori dal conteggio (sono trattati altrove come ResourceUnavailability
o come kind separato nel summary).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, time, timedelta
from typing import Iterable, List, Optional, Set, Dict

from app.models import TimePunch, PunchKind, WorkingHoursPolicy
from app.services.working_hours import get_holidays


COUNTABLE_KINDS = (PunchKind.shift, PunchKind.overtime)


@dataclass
class OvertimeBreakdown:
    regular_hours: float = 0.0
    overtime_daily_hours: float = 0.0
    overtime_weekly_hours: float = 0.0
    night_hours: float = 0.0
    sunday_hours: float = 0.0
    holiday_hours: float = 0.0
    weighted_factor: float = 0.0
    total_hours: float = 0.0
    # Dettaglio per giorno (utile per UI tabellare)
    daily: Dict[str, "DayBreakdown"] = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {
            "regular_hours": round(self.regular_hours, 2),
            "overtime_daily_hours": round(self.overtime_daily_hours, 2),
            "overtime_weekly_hours": round(self.overtime_weekly_hours, 2),
            "night_hours": round(self.night_hours, 2),
            "sunday_hours": round(self.sunday_hours, 2),
            "holiday_hours": round(self.holiday_hours, 2),
            "weighted_factor": round(self.weighted_factor, 4),
            "total_hours": round(self.total_hours, 2),
            "daily": {k: v.as_dict() for k, v in self.daily.items()},
        }
        return out


@dataclass
class DayBreakdown:
    date: date
    total_hours: float = 0.0
    night_hours: float = 0.0
    is_sunday: bool = False
    is_holiday: bool = False

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "total_hours": round(self.total_hours, 2),
            "night_hours": round(self.night_hours, 2),
            "is_sunday": self.is_sunday,
            "is_holiday": self.is_holiday,
        }


def _hours(td: timedelta) -> float:
    return td.total_seconds() / 3600.0


def _split_at_midnight(start: datetime, end: datetime) -> List[tuple[datetime, datetime]]:
    """Spezza un intervallo che attraversa mezzanotte in segmenti per-giorno."""
    out = []
    cur = start
    while cur.date() < end.date():
        next_midnight = datetime.combine(cur.date() + timedelta(days=1), time(0, 0))
        out.append((cur, next_midnight))
        cur = next_midnight
    if cur < end:
        out.append((cur, end))
    return out


def _night_overlap_hours(
    seg_start: datetime, seg_end: datetime,
    night_start: time, night_end: time,
) -> float:
    """Quante ore del segmento (tutto in un solo giorno) cadono in fascia notturna.

    Fascia notturna è night_start..night_end, ma tipicamente night_end < night_start
    (es. 22:00..06:00 del giorno dopo). Per semplicità calcoliamo le due porzioni:
      - dalla mezzanotte a night_end (mattino presto)
      - da night_start alla mezzanotte successiva (sera/notte)
    """
    if not night_start or not night_end:
        return 0.0
    d = seg_start.date()
    day_start = datetime.combine(d, time(0, 0))
    day_end = day_start + timedelta(days=1)
    s = max(seg_start, day_start)
    e = min(seg_end, day_end)
    if e <= s:
        return 0.0

    total = 0.0
    if night_end > time(0, 0):
        # fascia mattutina: 00:00 .. night_end
        ne = datetime.combine(d, night_end)
        ov = (min(e, ne) - max(s, day_start)).total_seconds()
        if ov > 0:
            total += ov / 3600.0
    if night_start < time(23, 59):
        # fascia serale: night_start .. 24:00
        ns = datetime.combine(d, night_start)
        ov = (min(e, day_end) - max(s, ns)).total_seconds()
        if ov > 0:
            total += ov / 3600.0
    return total


def _iso_week_key(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def compute_overtime(
    punches: Iterable[TimePunch],
    policy: WorkingHoursPolicy,
    holidays_set: Optional[Set[date]] = None,
) -> OvertimeBreakdown:
    """Calcola il breakdown straordinari per un set di TimePunch.

    `holidays_set` opzionale: se non passato viene calcolato dalla policy
    sull'intervallo coperto dai punch (chiamata cached possibile dall'esterno).
    """
    out = OvertimeBreakdown()
    closed = [p for p in punches if p.end_datetime and p.kind in COUNTABLE_KINDS]
    if not closed:
        return out

    if holidays_set is None:
        y_min = min(p.start_datetime.year for p in closed)
        y_max = max(p.end_datetime.year for p in closed)
        holidays_set = get_holidays(policy, y_min, y_max)

    # 1. Splitta per-giorno e accumula per data
    daily: Dict[date, DayBreakdown] = {}
    for p in closed:
        for seg_s, seg_e in _split_at_midnight(p.start_datetime, p.end_datetime):
            d = seg_s.date()
            db = daily.setdefault(d, DayBreakdown(date=d))
            db.total_hours += _hours(seg_e - seg_s)
            db.night_hours += _night_overlap_hours(
                seg_s, seg_e, policy.night_start, policy.night_end,
            )

    # 2. Marca domenica/festività + accumula totali per categoria
    weekly_totals: Dict[tuple, float] = {}
    weekly_overtime_daily: Dict[tuple, float] = {}
    for d, db in daily.items():
        db.is_sunday = (d.weekday() == 6)
        db.is_holiday = (d in holidays_set)
        out.total_hours += db.total_hours
        out.night_hours += db.night_hours
        if db.is_sunday:
            out.sunday_hours += db.total_hours
        if db.is_holiday:
            out.holiday_hours += db.total_hours

        # Overtime giornaliero: ore oltre daily_hours_threshold
        excess = max(0.0, db.total_hours - policy.daily_hours_threshold)
        out.overtime_daily_hours += excess

        # Aggrega per settimana ISO
        wk = _iso_week_key(d)
        weekly_totals[wk] = weekly_totals.get(wk, 0.0) + db.total_hours
        weekly_overtime_daily[wk] = weekly_overtime_daily.get(wk, 0.0) + excess

    # 3. Overtime settimanale: ore oltre weekly_threshold *che non siano già*
    #    considerate overtime giornaliero (per evitare doppi conteggi).
    for wk, total_w in weekly_totals.items():
        excess_w = max(0.0, total_w - policy.weekly_hours_threshold)
        # già contate come daily-overtime in questa settimana
        already = weekly_overtime_daily.get(wk, 0.0)
        out.overtime_weekly_hours += max(0.0, excess_w - already)

    out.regular_hours = max(
        0.0,
        out.total_hours - out.overtime_daily_hours - out.overtime_weekly_hours,
    )

    # 4. Weighted factor: applica MAX moltiplicatore per ogni "quota" di ore.
    #    Approssimazione: trattiamo holiday > sunday > overtime > night > regular.
    #    Le ore notturne ricevono night_multiplier solo se non già coperte da
    #    una categoria con moltiplicatore maggiore.
    h_mult = policy.holiday_multiplier or 1.0
    s_mult = policy.sunday_multiplier or 1.0
    o_mult = policy.overtime_multiplier or 1.0
    n_mult = policy.night_multiplier or 1.0

    # somma pesata: usiamo una stima sequenziale per evitare cumuli
    weighted = 0.0
    # ore con moltiplicatore "festivo"
    weighted += out.holiday_hours * h_mult
    # ore domenicali NON in festività
    sunday_non_holiday = max(0.0, out.sunday_hours - out.holiday_hours)
    weighted += sunday_non_holiday * s_mult
    # overtime totale (daily+weekly), escludendo già festivo+domenica
    overtime_total = out.overtime_daily_hours + out.overtime_weekly_hours
    overtime_remaining = max(0.0, overtime_total - out.holiday_hours - sunday_non_holiday)
    weighted += overtime_remaining * o_mult
    # ore notturne residue (non già festivo/domenica/overtime)
    night_residual = max(
        0.0,
        out.night_hours - out.holiday_hours - sunday_non_holiday - overtime_remaining,
    )
    weighted += night_residual * n_mult
    # ore regolari residue
    regular_residual = max(
        0.0,
        out.total_hours - out.holiday_hours - sunday_non_holiday - overtime_remaining - night_residual,
    )
    weighted += regular_residual * 1.0

    out.weighted_factor = weighted
    out.daily = {d.isoformat(): db for d, db in sorted(daily.items())}
    return out


# ── Breakdown per-punch (v3.5.0-alpha.16) ────────────────────────────
@dataclass
class PunchBreakdown:
    """Distribuzione di un singolo TimePunch sulle categorie di maggiorazione.

    Le ore "extra" del giorno (overtime giornaliero) sono attribuite alle ore
    finali della giornata (last-in-first-out): se ho due punch da 4h+5h con
    threshold 8, il primo è 4h reg, il secondo è 4h reg + 1h ot. Questa
    convenzione riflette il modo standard in cui vengono firmate le buste paga.
    """
    punch_id: int
    duration_h: float = 0.0
    regular_h: float = 0.0
    overtime_h: float = 0.0
    night_h: float = 0.0
    sunday_h: float = 0.0
    holiday_h: float = 0.0
    is_sunday: bool = False
    is_holiday: bool = False

    def as_dict(self) -> dict:
        return {
            "punch_id": self.punch_id,
            "duration_h": round(self.duration_h, 2),
            "regular_h": round(self.regular_h, 2),
            "overtime_h": round(self.overtime_h, 2),
            "night_h": round(self.night_h, 2),
            "sunday_h": round(self.sunday_h, 2),
            "holiday_h": round(self.holiday_h, 2),
            "is_sunday": self.is_sunday,
            "is_holiday": self.is_holiday,
        }


def compute_punch_breakdown(
    punches: Iterable[TimePunch],
    policy: WorkingHoursPolicy,
    holidays_set: Optional[Set[date]] = None,
) -> Dict[int, PunchBreakdown]:
    """Per ogni punch, calcola il breakdown distribuendo le ore di maggiorazione.

    L'overtime è attribuito alle ore "in coda" alla giornata (per giornata di
    calendario, non per settimana ISO che è gestita separatamente nel weighted_factor).
    Le ore notturne sono calcolate puntualmente dal segmento. Sunday/holiday
    flaggano l'intero punch quando il suo giorno cade in tali categorie.

    Restituisce dict {punch_id: PunchBreakdown}. Punch in corso (no end) sono
    saltati. Punch break/leave/sick/idle vengono ritornati con duration=0 ma
    senza categorie (sono fuori dalla rendicontazione).
    """
    out: Dict[int, PunchBreakdown] = {}
    closed_countable = [p for p in punches if p.end_datetime and p.kind in COUNTABLE_KINDS]
    if not closed_countable:
        return out

    if holidays_set is None:
        y_min = min(p.start_datetime.year for p in closed_countable)
        y_max = max(p.end_datetime.year for p in closed_countable)
        holidays_set = get_holidays(policy, y_min, y_max)

    threshold = policy.daily_hours_threshold or 8.0
    night_start = policy.night_start
    night_end = policy.night_end

    # Raggruppa per giorno di calendario (basato su start_datetime.date())
    from collections import defaultdict
    by_day: Dict[date, List[TimePunch]] = defaultdict(list)
    for p in closed_countable:
        by_day[p.start_datetime.date()].append(p)

    for day, day_punches in by_day.items():
        is_sunday = (day.weekday() == 6)
        is_holiday = (day in holidays_set)
        # Ordino per start_datetime per attribuire l'overtime alle ULTIME ore
        day_punches_sorted = sorted(day_punches, key=lambda p: p.start_datetime)
        # Calcolo ore di ogni punch (sommando segmenti che cadono in questo
        # giorno — un punch che attraversa mezzanotte conta solo la parte di
        # questo giorno).
        durations: List[float] = []
        nights: List[float] = []
        for p in day_punches_sorted:
            day_h = 0.0
            day_n = 0.0
            for seg_s, seg_e in _split_at_midnight(p.start_datetime, p.end_datetime):
                if seg_s.date() != day:
                    continue
                day_h += _hours(seg_e - seg_s)
                day_n += _night_overlap_hours(seg_s, seg_e, night_start, night_end)
            durations.append(day_h)
            nights.append(day_n)
        total_day = sum(durations)
        ot_total_day = max(0.0, total_day - threshold)
        # Distribuzione last-in-first-out: scorro i punch dal più recente,
        # tolgo `ot_total_day` finché esaurisce.
        ot_share: List[float] = [0.0] * len(durations)
        remaining = ot_total_day
        for i in range(len(durations) - 1, -1, -1):
            if remaining <= 0:
                break
            take = min(remaining, durations[i])
            ot_share[i] = take
            remaining -= take

        for idx, p in enumerate(day_punches_sorted):
            d_h = durations[idx]
            ot_h = ot_share[idx]
            reg_h = max(0.0, d_h - ot_h)
            out[p.id] = PunchBreakdown(
                punch_id=p.id,
                duration_h=d_h,
                regular_h=reg_h,
                overtime_h=ot_h,
                night_h=nights[idx],
                sunday_h=d_h if is_sunday else 0.0,
                holiday_h=d_h if is_holiday else 0.0,
                is_sunday=is_sunday,
                is_holiday=is_holiday,
            )
    return out
