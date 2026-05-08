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
    """Ore-uomo del booking = somma delle durate degli assignment (man-hours).

    v3.4.55 fix: prima usavamo shell-duration (start→end del booking),
    sottostimando il maturato per booking multi-risorsa. Es: 2 colorist su
    8h → shell 8h → maturato 1 giornata; ma il costo cost-report è 2
    giornate-colorist (ognuno conta come unità di lavoro). Allineato con
    `reverse_quote.compute_quantity_from_hours` che già usa man-hours.
    """
    if not getattr(b, "assignments", None):
        # Fallback: nessun assignment caricato → usa shell-duration
        if not b.start_datetime or not b.end_datetime:
            return 0.0
        return max(0.0, (b.end_datetime - b.start_datetime).total_seconds() / 3600.0)
    total = 0.0
    for a in b.assignments:
        if a.start_datetime and a.end_datetime:
            total += max(0.0, (a.end_datetime - a.start_datetime).total_seconds() / 3600.0)
    return total


def _qty_from_hours(unit: str, total_hours: float, n_bookings: int) -> float:
    """Conversione ore → quantità nell'unit della cost line.

    v3.5.0-alpha.13: per unità non temporali (pc/lump/fix/lot/shot/version/
    allow/TB/GB) usiamo il count dei booking, non le ore.
    """
    u = (unit or "").strip().lower()
    if u in TIME_UNITS_HOUR:
        return round(total_hours, 2)
    if u in TIME_UNITS_DAY:
        return round(total_hours / HOURS_PER_DAY, 4)
    return float(n_bookings)


def recompute_cost_line_actual(db: Session, jcl) -> dict:
    """Ricomputa `quantity_actual`, `total_accrued`, `total_expected`
    per una JobCostLine aggregando i booking associati.

    v3.5.0-alpha.55: oltre al maturato (booking done) ora calcoliamo anche
    la **stima** = tutti i booking non cancellati × prezzo. Va a popolare
    `total_expected` (prima riempito solo da edit manuale, lasciava il
    cost report con Over/Under sempre 0). Semantica:

    - `quantity_actual` = booking done (lavoro fatto)
    - `total_accrued`   = quantity_actual × unit_price (maturato certo)
    - `total_expected`  = qty pianificata × unit_price (forecast: tutti i
       booking confermati o done, esclusi solo cancelled)

    L'over/under nel cost report è poi calcolato lato API in due viste:
    Now (accrued − quoted) e Forecast (expected − quoted).
    """
    from app.models import Booking, BookingExecutionStatus, BookingStatus
    if jcl is None:
        return {"updated": False, "reason": "no_jcl"}

    # Tutti i booking non cancellati associati alla cost line
    all_bookings = db.query(Booking).filter(
        Booking.job_cost_line_id == jcl.id,
        Booking.status != BookingStatus.cancelled,
    ).all()
    done_bookings = [b for b in all_bookings if b.execution_status == BookingExecutionStatus.done]

    unit = (jcl.unit or "").strip().lower()
    done_hours = sum(_booking_hours(b) for b in done_bookings)
    planned_hours = sum(_booking_hours(b) for b in all_bookings)
    new_qty_actual = _qty_from_hours(unit, done_hours, len(done_bookings))
    new_qty_planned = _qty_from_hours(unit, planned_hours, len(all_bookings))

    new_accrued = round(new_qty_actual * (jcl.unit_price or 0.0), 2)
    # Stima = quantità pianificata × prezzo. Se non ci sono booking
    # ancora pianificati, default al quotato (non a 0): la lavorazione
    # esiste a preventivo ma non è stata ancora schedulata. Quando arriva
    # il primo booking, la stima passa a qty_planned (può andare sotto
    # o sopra il quotato → genera under o over).
    expected_qty = new_qty_planned if all_bookings else (jcl.quantity_quoted or 0.0)
    new_expected = round(expected_qty * (jcl.unit_price or 0.0), 2)

    new_work_date = max(
        (b.start_datetime.date() for b in done_bookings if b.start_datetime),
        default=None,
    )

    changed = (
        abs((jcl.quantity_actual or 0) - new_qty_actual) > 1e-6
        or abs((jcl.total_accrued or 0) - new_accrued) > 1e-2
        or abs((jcl.total_expected or 0) - new_expected) > 1e-2
        or jcl.work_date != new_work_date
    )
    jcl.quantity_actual = new_qty_actual
    jcl.total_accrued = new_accrued
    jcl.total_expected = new_expected
    jcl.work_date = new_work_date
    return {
        "updated": changed,
        "jcl_id": jcl.id,
        "unit": unit,
        "bookings_done": len(done_bookings),
        "bookings_planned": len(all_bookings),
        "total_hours": round(done_hours, 2),
        "planned_hours": round(planned_hours, 2),
        "quantity_actual": new_qty_actual,
        "quantity_planned": new_qty_planned,
        "total_accrued": new_accrued,
        "total_expected": new_expected,
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
