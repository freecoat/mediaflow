"""
Sincronizzazione JobCostLine.quantity_actual + total_accrued con i Booking.

v3.4.41 — bug fix: le ore booking marcate `done` non comparivano come
"maturate" nel cost report perché `JobCostLine.quantity_actual` non veniva
aggiornato dal flusso execution_status. La fonte canonica delle ore è il
Booking (decisione architetturale di v3.4.33), ma il cost report continua
ad esporre `total_accrued` per back-compat e per il drilldown per riga.

Conversione unit→ore:
- "hr" / "ore" / "hour": qty in ore = sum(hours_done)
- "day" / "giorno": qty in giorni = sum(hours_done) / 8
- altri unit (fix, lot, ...): non aggiornare automaticamente — quel tipo
  di lavorazione non si misura in ore di booking. Lasciato a edit manuale.

Idempotente: la ricomputazione legge tutti i booking `done` della cost
line, sostituisce quantity_actual + total_accrued. Si auto-rigenera ad
ogni hook (no drift incrementale).
"""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

HOURS_PER_DAY = 8.0
TIME_UNITS_HOUR = {"hr", "ore", "hour", "h"}
TIME_UNITS_DAY = {"day", "giorno", "giornate", "giornata", "d"}


def _booking_hours(b) -> float:
    """Durata booking in ore. Se ha assignments multi-risorsa, considera
    la durata della shell (start_datetime → end_datetime) — il costo è
    moltiplicato per ogni risorsa, ma le ore "lavoro" della cost line
    sono le ore-lavorazione, non le ore-uomo. Se serve cambiare in
    ore-uomo, sommare le durate degli assignment."""
    if not b.start_datetime or not b.end_datetime:
        return 0.0
    delta = (b.end_datetime - b.start_datetime).total_seconds() / 3600.0
    return max(0.0, delta)


def recompute_cost_line_actual(db: Session, jcl) -> dict:
    """Ricomputa `quantity_actual` e `total_accrued` per una JobCostLine
    aggregando i booking con execution_status=done associati."""
    from app.models import Booking, BookingExecutionStatus, BookingStatus
    if jcl is None:
        return {"updated": False, "reason": "no_jcl"}

    bookings = db.query(Booking).filter(
        Booking.job_cost_line_id == jcl.id,
        Booking.execution_status == BookingExecutionStatus.done,
        Booking.status != BookingStatus.cancelled,
    ).all()
    total_hours = sum(_booking_hours(b) for b in bookings)

    unit = (jcl.unit or "").strip().lower()
    if unit in TIME_UNITS_HOUR:
        new_qty = round(total_hours, 2)
    elif unit in TIME_UNITS_DAY:
        new_qty = round(total_hours / HOURS_PER_DAY, 4)
    else:
        # Unità non temporale: non aggiorniamo automaticamente.
        return {
            "updated": False,
            "reason": "non_time_unit",
            "unit": unit,
            "bookings_done": len(bookings),
            "total_hours": round(total_hours, 2),
        }

    new_accrued = round(new_qty * (jcl.unit_price or 0.0), 2)
    changed = (
        abs((jcl.quantity_actual or 0) - new_qty) > 1e-6
        or abs((jcl.total_accrued or 0) - new_accrued) > 1e-2
    )
    jcl.quantity_actual = new_qty
    jcl.total_accrued = new_accrued
    return {
        "updated": changed,
        "jcl_id": jcl.id,
        "unit": unit,
        "bookings_done": len(bookings),
        "total_hours": round(total_hours, 2),
        "quantity_actual": new_qty,
        "total_accrued": new_accrued,
    }


def recompute_for_booking(db: Session, booking) -> Optional[dict]:
    """Helper per gli hook negli endpoint planning. Se il booking ha
    una cost line associata, ricomputa la sua actual e ritorna il
    risultato. Altrimenti None."""
    if booking is None or not booking.job_cost_line_id:
        return None
    from app.models import JobCostLine
    jcl = db.query(JobCostLine).filter(JobCostLine.id == booking.job_cost_line_id).first()
    if not jcl:
        return None
    return recompute_cost_line_actual(db, jcl)


def recompute_for_job(db: Session, job_id: int) -> dict:
    """Ricalcola tutte le JobCostLine di un job. Utile come azione di
    riconciliazione (fix one-shot per DB esistenti dove i booking sono
    stati marcati done senza generare il sync)."""
    from app.models import JobCostLine
    jcls = db.query(JobCostLine).filter(JobCostLine.job_id == job_id).all()
    results = []
    for jcl in jcls:
        r = recompute_cost_line_actual(db, jcl)
        if r.get("updated"):
            results.append(r)
    return {
        "job_id": job_id,
        "lines_total": len(jcls),
        "lines_updated": len(results),
        "details": results,
    }
