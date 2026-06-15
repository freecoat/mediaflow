"""SAL — Stato Avanzamento Lavori: metriche ore quotate/pianificate/lavorate.

Single source of truth per la vista SAL (`/finance/sal`). Read-only, aggrega
Job / JobCostLine / Booking esistenti. Nessun modello/migrazione.

Definizioni (decisioni Matteo, design 2026-06-12):
- **ore quotate(job)**: Σ su JobCostLine a unit-tempo. Unit-ora
  (hr/hour/h/ore/ora) → `quantity_quoted` as-is; unit-giorno
  (day/days/gg/giorno/giorni) → `quantity_quoted × daily_hours`. Voci a corpo
  (pc/TB/forfait…) ESCLUSE (0).
- **ore pianificate(job)**: Σ `_booking_billable_hours(b)` (override umana,
  no double-count sala+persona) sui Booking NON cancellati del job.
- **ore lavorate(job)**: idem ma solo `execution_status == done`.
- **per reparto**: quotato attribuito a `PriceItem.department_id` della JCL,
  pianificato/lavorato alla `Resource.department_id` della prima risorsa con
  reparto fra gli assignment del booking. Senza reparto → chiave 0 ("Altro").
- **allarme job**: lavorate>quotate o pianificate>quotate → "red";
  quotate>0 e max(lav,pian) ≥ 0.9×quotate → "amber"; altrimenti "none".

Le funzioni pure prendono `daily_hours` come parametro (default 8.0). La
risoluzione della WorkingHoursPolicy avviene in `project_metrics` via
`_daily_hours_for_job(db, job)`.
"""
from typing import Optional

from app.services.cost_line_sync import _booking_billable_hours

# Unit temporali per il monte ore quotate (lower/strip).
_HOUR_UNITS = {"hr", "hour", "h", "ore", "ora"}
_DAY_UNITS = {"day", "days", "gg", "giorno", "giorni"}
_TIME_UNITS = _HOUR_UNITS | _DAY_UNITS

DEFAULT_DAILY_HOURS = 8.0


def _norm_unit(unit: Optional[str]) -> str:
    return (unit or "").strip().lower()


def _jcl_quoted_hours(jcl, daily_hours: float) -> float:
    """Ore quotate di una singola JobCostLine. 0 se unit non temporale."""
    u = _norm_unit(getattr(jcl, "unit", None))
    qty = getattr(jcl, "quantity_quoted", 0.0) or 0.0
    if u in _HOUR_UNITS:
        return float(qty)
    if u in _DAY_UNITS:
        return float(qty) * float(daily_hours)
    return 0.0


def quoted_hours(job, *, daily_hours: float = DEFAULT_DAILY_HOURS) -> float:
    """Σ ore quotate sulle JobCostLine a unit-tempo del job."""
    total = 0.0
    for jcl in (getattr(job, "cost_lines", None) or []):
        total += _jcl_quoted_hours(jcl, daily_hours)
    return total


def quoted_amount(job) -> float:
    """Σ JobCostLine.total_quoted (euro quotati) del job."""
    return sum(
        float(getattr(j, "total_quoted", 0.0) or 0.0)
        for j in (getattr(job, "cost_lines", None) or [])
    )


def accrued_amount(job) -> float:
    """Σ JobCostLine.total_accrued (euro maturati) del job."""
    return sum(
        float(getattr(j, "total_accrued", 0.0) or 0.0)
        for j in (getattr(job, "cost_lines", None) or [])
    )


def blended_rate(quoted_eur: float, quoted_hours: float) -> float:
    """€/ora medio del progetto/job (per stimare €-anno dalle ore). 0 se 0 ore."""
    return (quoted_eur / quoted_hours) if quoted_hours and quoted_hours > 0 else 0.0


def _non_cancelled_bookings(job):
    """Booking del job con status != cancelled. Usa la relationship `bookings`."""
    from app.models import BookingStatus
    out = []
    for b in (getattr(job, "bookings", None) or []):
        if b.status != BookingStatus.cancelled:
            out.append(b)
    return out


def planned_hours(job) -> float:
    """Σ ore fatturabili sui Booking non-cancelled del job."""
    return sum(_booking_billable_hours(b) for b in _non_cancelled_bookings(job))


def worked_hours(job) -> float:
    """Σ ore fatturabili sui Booking non-cancelled e execution_status==done."""
    from app.models import BookingExecutionStatus
    return sum(
        _booking_billable_hours(b)
        for b in _non_cancelled_bookings(job)
        if b.execution_status == BookingExecutionStatus.done
    )


def _booking_year(b):
    sd = getattr(b, "start_datetime", None)
    return sd.year if sd is not None else None


def worked_hours_in_year(job, year: int) -> float:
    """Σ ore lavorate (done) dei booking non-cancelled con start_datetime in year."""
    from app.models import BookingExecutionStatus
    return sum(
        _booking_billable_hours(b)
        for b in _non_cancelled_bookings(job)
        if b.execution_status == BookingExecutionStatus.done
        and _booking_year(b) == year
    )


def planned_hours_in_year(job, year: int) -> float:
    """Σ ore pianificate (tutti i booking non-cancelled) con start_datetime in year."""
    return sum(
        _booking_billable_hours(b)
        for b in _non_cancelled_bookings(job)
        if _booking_year(b) == year
    )


def _booking_department_id(b) -> int:
    """Reparto del booking = department_id della prima risorsa (con reparto)
    fra gli assignment. Fallback 0 ("Altro")."""
    for a in (getattr(b, "assignments", None) or []):
        res = getattr(a, "resource", None)
        if res is not None and getattr(res, "department_id", None):
            return res.department_id
    return 0


def by_department(job, *, daily_hours: float = DEFAULT_DAILY_HOURS) -> dict:
    """dict department_id(int, 0=Altro) → {quoted, planned, worked}.

    Quotato attribuito al reparto del PriceItem della JCL; pianificato/lavorato
    al reparto della risorsa primaria del booking.
    """
    from app.models import BookingExecutionStatus

    out: dict = {}

    def _bucket(dep_id: int) -> dict:
        return out.setdefault(dep_id, {
            "quoted": 0.0, "planned": 0.0, "worked": 0.0,
            "quoted_eur": 0.0, "accrued_eur": 0.0,
        })

    # Quotato per reparto (da PriceItem.department_id della JCL)
    for jcl in (getattr(job, "cost_lines", None) or []):
        h = _jcl_quoted_hours(jcl, daily_hours)
        if h <= 0:
            continue
        pi = getattr(jcl, "price_item", None)
        dep_id = getattr(pi, "department_id", None) if pi is not None else None
        _bucket(dep_id or 0)["quoted"] += h

    # Euro per reparto: total_quoted/total_accrued della JCL attribuiti al
    # reparto del suo PriceItem (anche per voci non a tempo).
    for jcl in (getattr(job, "cost_lines", None) or []):
        pi = getattr(jcl, "price_item", None)
        dep_id = getattr(pi, "department_id", None) if pi is not None else None
        b = _bucket(dep_id or 0)
        b["quoted_eur"] += float(getattr(jcl, "total_quoted", 0.0) or 0.0)
        b["accrued_eur"] += float(getattr(jcl, "total_accrued", 0.0) or 0.0)

    # Pianificato / lavorato per reparto (da Resource.department_id del booking)
    for b in _non_cancelled_bookings(job):
        h = _booking_billable_hours(b)
        if h <= 0:
            continue
        dep_id = _booking_department_id(b)
        bucket = _bucket(dep_id)
        bucket["planned"] += h
        if b.execution_status == BookingExecutionStatus.done:
            bucket["worked"] += h

    return out


def job_alarm(job, *, daily_hours: float = DEFAULT_DAILY_HOURS) -> str:
    """"red" se lav/pian > quotate; "amber" se quotate>0 e max ≥ 0.9×quotate;
    altrimenti "none". quotate=0 → "none"."""
    quoted = quoted_hours(job, daily_hours=daily_hours)
    planned = planned_hours(job)
    worked = worked_hours(job)
    return _alarm_from(quoted, planned, worked)


def _alarm_from(quoted: float, planned: float, worked: float) -> str:
    if quoted <= 0:
        return "none"
    if worked > quoted or planned > quoted:
        return "red"
    if max(worked, planned) >= 0.9 * quoted:
        return "amber"
    return "none"


def job_metrics(job, *, daily_hours: float = DEFAULT_DAILY_HOURS) -> dict:
    """{quoted, planned, worked, pct, alarm, quoted_eur, accrued_eur, pct_eur}.

    pct = worked/quoted ore (0 se 0); pct_eur = accrued/quoted euro (0 se 0).
    """
    quoted = quoted_hours(job, daily_hours=daily_hours)
    planned = planned_hours(job)
    worked = worked_hours(job)
    pct = (worked / quoted) if quoted > 0 else 0.0
    q_eur = quoted_amount(job)
    a_eur = accrued_amount(job)
    return {
        "quoted": quoted,
        "planned": planned,
        "worked": worked,
        "pct": pct,
        "alarm": _alarm_from(quoted, planned, worked),
        "quoted_eur": q_eur,
        "accrued_eur": a_eur,
        "pct_eur": (a_eur / q_eur) if q_eur > 0 else 0.0,
    }


def _daily_hours_for_job(db, job) -> float:
    """Risolve daily_hours per il job: WorkingHoursPolicy del job se esiste,
    altrimenti WorkingHoursPolicy.is_default del tenant, altrimenti 8.0.

    Nota: Job non ha (ad oggi) una relationship `working_hours_policy`; il
    getattr difensivo permette di agganciarla in futuro senza toccare questo
    codice.
    """
    pol = getattr(job, "working_hours_policy", None)
    if pol is not None and getattr(pol, "daily_hours_threshold", None):
        return float(pol.daily_hours_threshold)
    from app.models import WorkingHoursPolicy
    q = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.is_default == True  # noqa: E712
    )
    tid = getattr(job, "tenant_id", None)
    if tid is not None:
        q = q.filter(WorkingHoursPolicy.tenant_id == tid)
    default_pol = q.first()
    if default_pol is not None and getattr(default_pol, "daily_hours_threshold", None):
        return float(default_pol.daily_hours_threshold)
    return DEFAULT_DAILY_HOURS


def project_metrics(db, project) -> dict:
    """Aggrega i job del progetto (già tenant-scoped dal chiamante).

    Ritorna {quoted, planned, worked, pct, alarm, job_count}. daily_hours
    risolto per ciascun job via `_daily_hours_for_job`. alarm = peggiore fra i
    job (red > amber > none).
    """
    quoted = planned = worked = 0.0
    quoted_eur = accrued_eur = 0.0
    job_count = 0
    has_red = has_amber = False
    for job in (getattr(project, "jobs", None) or []):
        job_count += 1
        daily = _daily_hours_for_job(db, job)
        m = job_metrics(job, daily_hours=daily)
        quoted += m["quoted"]
        planned += m["planned"]
        worked += m["worked"]
        quoted_eur += m["quoted_eur"]
        accrued_eur += m["accrued_eur"]
        if m["alarm"] == "red":
            has_red = True
        elif m["alarm"] == "amber":
            has_amber = True
    pct = (worked / quoted) if quoted > 0 else 0.0
    alarm = "red" if has_red else ("amber" if has_amber else "none")
    return {
        "quoted": quoted,
        "planned": planned,
        "worked": worked,
        "pct": pct,
        "alarm": alarm,
        "job_count": job_count,
        "quoted_eur": quoted_eur,
        "accrued_eur": accrued_eur,
        "pct_eur": (accrued_eur / quoted_eur) if quoted_eur > 0 else 0.0,
    }


# ── Vista temporale (tab 2) ──────────────────────────────────────────


def timeline_metrics(db, *, year: int, granularity: str = "month") -> dict:
    """Aggregato temporale tenant-scoped per la tab Temporale del SAL.

    - **pianificate/lavorate**: Σ `_booking_billable_hours` sui Booking del
      tenant (non-cancelled = pianificate; non-cancelled + done = lavorate),
      attribuiti al mese/trimestre del loro `start_datetime`.
    - **fatturato**: Σ `Invoice.subtotal` (no draft/cancelled, doc_type=="TD04"
      → segno -1) del mese di `issue_date`, mappato al periodo.
    - **pct** = lavorate / pianificate (0 se pianificate 0).

    granularity="month" → 12 periodi (label "2026-01"…"2026-12");
    "quarter" → 4 periodi (label "Q1"…"Q4", aggrega 3 mesi). Ritorna
    {"year", "granularity", "periods": [...], "total": {...}}.
    """
    from app.models import (
        Booking, BookingStatus, BookingExecutionStatus, Invoice, InvoiceStatus,
    )
    from app.context import current_tenant_id

    tid = current_tenant_id()
    gran = "quarter" if str(granularity).lower().startswith("q") else "month"

    # Accumulatori per mese 1..12.
    planned_by_month = {m: 0.0 for m in range(1, 13)}
    worked_by_month = {m: 0.0 for m in range(1, 13)}
    invoiced_by_month = {m: 0.0 for m in range(1, 13)}

    # Booking del tenant nell'anno (start_datetime), non-cancelled.
    # Filtro anno in SQL: evita di scansionare tutti gli anni del tenant.
    from sqlalchemy import extract
    bookings = (
        db.query(Booking)
        .filter(
            Booking.tenant_id == tid,
            Booking.status != BookingStatus.cancelled,
            extract("year", Booking.start_datetime) == year,
        )
        .all()
    )
    for b in bookings:
        sd = getattr(b, "start_datetime", None)
        if sd is None or sd.year != year:
            continue
        h = _booking_billable_hours(b)
        if h <= 0:
            continue
        planned_by_month[sd.month] += h
        if b.execution_status == BookingExecutionStatus.done:
            worked_by_month[sd.month] += h

    # Fatturato: Σ Invoice.subtotal (no draft/cancelled, TD04 = -1) per mese di
    # issue_date. Tenant-scope via Invoice.tenant_id denormalizzato.
    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.tenant_id == tid,
            Invoice.status != InvoiceStatus.draft,
            Invoice.status != InvoiceStatus.cancelled,
            extract("year", Invoice.issue_date) == year,
        )
        .all()
    )
    for inv in invoices:
        idate = getattr(inv, "issue_date", None)
        if idate is None or idate.year != year:
            continue
        sign = -1.0 if (getattr(inv, "doc_type", None) == "TD04") else 1.0
        invoiced_by_month[idate.month] += sign * float(inv.subtotal or 0.0)

    def _period_row(label, months):
        planned = sum(planned_by_month[m] for m in months)
        worked = sum(worked_by_month[m] for m in months)
        invoiced = sum(invoiced_by_month[m] for m in months)
        pct = (worked / planned) if planned > 0 else 0.0
        return {
            "label": label,
            "planned": planned,
            "worked": worked,
            "invoiced": invoiced,
            "pct": pct,
        }

    periods = []
    if gran == "quarter":
        for q in range(4):
            months = [q * 3 + 1, q * 3 + 2, q * 3 + 3]
            periods.append(_period_row(f"Q{q + 1}", months))
    else:
        for m in range(1, 13):
            periods.append(_period_row(f"{year:04d}-{m:02d}", [m]))

    tot_planned = sum(planned_by_month.values())
    tot_worked = sum(worked_by_month.values())
    tot_invoiced = sum(invoiced_by_month.values())
    total = {
        "planned": tot_planned,
        "worked": tot_worked,
        "invoiced": tot_invoiced,
        "pct": (tot_worked / tot_planned) if tot_planned > 0 else 0.0,
    }

    return {
        "year": year,
        "granularity": gran,
        "periods": periods,
        "total": total,
    }


def matrix_metrics(db, *, year: int, granularity: str = "month") -> dict:
    """Calendario SAL: righe = progetti, colonne = mesi/trimestri dell'anno,
    cella = % CUMULATIVA a fine periodo (ore cumulate, anni precedenti inclusi,
    / ore quotate totali del progetto).

    Base della cella (`basis`): periodi interamente passati → ore **lavorate**
    (done); mese corrente e futuri → ore **pianificate** (tutti i booking
    non-cancelled). Permette di vedere consuntivo nel passato e previsione avanti.

    Include i progetti del tenant non cestinati con ore quotate > 0 oppure con
    cumulato > 0 a fine anno. Riga "total" = Σ sui progetti inclusi.
    """
    from datetime import datetime as _dt
    from sqlalchemy.orm import joinedload
    from app.models import (
        Project, Job, JobCostLine, Booking, BookingAssignment,
        BookingStatus, BookingExecutionStatus,
    )
    from app.context import current_tenant_id

    tid = current_tenant_id()
    gran = (granularity or "month").strip().lower()
    if gran not in ("month", "quarter"):
        gran = "month"

    # Cutoff di fine periodo: primo istante del periodo successivo.
    if gran == "quarter":
        labels = ["Q1", "Q2", "Q3", "Q4"]
        cutoffs = [_dt(year, 4, 1), _dt(year, 7, 1), _dt(year, 10, 1),
                   _dt(year + 1, 1, 1)]
    else:
        labels = [f"{year:04d}-{m:02d}" for m in range(1, 13)]
        cutoffs = [(_dt(year, m + 1, 1) if m < 12 else _dt(year + 1, 1, 1))
                   for m in range(1, 13)]

    from datetime import date as _date
    today = _date.today()
    cur_first = _dt(today.year, today.month, 1)

    def _basis_for(cutoff):
        # periodo interamente passato (cutoff ≤ primo giorno del mese corrente)
        # → lavorato; altrimenti (mese corrente + futuri) → pianificato.
        return "worked" if cutoff <= cur_first else "planned"

    projects = (
        db.query(Project)
        .options(
            joinedload(Project.client),
            joinedload(Project.jobs).joinedload(Job.cost_lines),
            joinedload(Project.jobs).joinedload(Job.bookings)
            .joinedload(Booking.assignments)
            .joinedload(BookingAssignment.resource),
        )
        .filter(Project.tenant_id == tid, Project.deleted_at.is_(None))
        .order_by(Project.title)
        .all()
    )

    rows = []
    total_quoted = 0.0
    total_cum = [0.0] * len(cutoffs)
    total_prev = 0.0
    total_next = 0.0
    for prj in projects:
        quoted = 0.0
        # (booking_start, ore) — done per i periodi passati, tutti i non-cancelled
        # per i periodi correnti/futuri (pianificato). Tutti gli anni.
        done_events: list[tuple] = []
        planned_events: list[tuple] = []
        for job in (prj.jobs or []):
            dh = _daily_hours_for_job(db, job)
            quoted += quoted_hours(job, daily_hours=dh)
            for b in _non_cancelled_bookings(job):
                sd = getattr(b, "start_datetime", None)
                if sd is None:
                    continue
                h = _booking_billable_hours(b)
                if h <= 0:
                    continue
                planned_events.append((sd, h))
                if b.execution_status == BookingExecutionStatus.done:
                    done_events.append((sd, h))

        cum_cells = []
        for i, cutoff in enumerate(cutoffs):
            basis = _basis_for(cutoff)
            events = done_events if basis == "worked" else planned_events
            cum = sum(h for sd, h in events if sd < cutoff)
            pct = (cum / quoted) if quoted > 0 else 0.0
            cum_cells.append({"label": labels[i], "worked_cum": round(cum, 2),
                              "pct": pct, "basis": basis})

        final_cum = cum_cells[-1]["worked_cum"] if cum_cells else 0.0
        if quoted <= 0 and final_cum <= 0:
            continue  # progetto senza quotato né lavorato: fuori dal calendario

        # Colonne ai lati del calendario: Anno prec = ore lavorate (done) in N-1,
        # Anno succ = ore pianificate (non-cancelled) in N+1. Riuso degli eventi
        # già raccolti, nessun loop aggiuntivo sui job.
        prev_hours = round(sum(h for sd, h in done_events if sd.year == year - 1), 2)
        next_hours = round(sum(h for sd, h in planned_events if sd.year == year + 1), 2)

        rows.append({
            "id": prj.id,
            "code": prj.code,
            "title": prj.title,
            "client": prj.client.name if prj.client else None,
            "quoted": round(quoted, 2),
            "cells": cum_cells,
            "prev_year_hours": prev_hours,
            "next_year_hours": next_hours,
        })
        total_quoted += quoted
        total_prev += prev_hours
        total_next += next_hours
        for i, c in enumerate(cum_cells):
            total_cum[i] += c["worked_cum"]

    total_cells = [
        {"label": labels[i], "worked_cum": round(total_cum[i], 2),
         "pct": (total_cum[i] / total_quoted) if total_quoted > 0 else 0.0,
         "basis": _basis_for(cutoffs[i])}
        for i in range(len(cutoffs))
    ]

    return {
        "year": year,
        "granularity": gran,
        "prev_year": year - 1,
        "next_year": year + 1,
        "labels": labels,
        "projects": rows,
        "total": {
            "quoted": round(total_quoted, 2),
            "cells": total_cells,
            "prev_year_hours": round(total_prev, 2),
            "next_year_hours": round(total_next, 2),
        },
    }
