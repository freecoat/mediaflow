"""
MediaFlow — deliverable_cost_sync (v3.5.0-alpha.172.2)

Calcolo di `JobDeliverable.total_cost_accrued` come quota equa dei costi
booking che linkano il deliverable via `booking_deliverables` (M:N).

Maturato (revenue) NON è gestito qui: è confermato MANUALMENTE dal
producer via `JobDeliverable.quantity_delivered`. Vedi spec
docs/RESTRUCTURE_2026_05_20.md sezione 3.1.

Regola cost split (decisione restructure):
  per ogni booking con N deliverable linkati:
      booking_total_cost = Σ (assignment_hours × cost_rate_snap)
      per ogni deliverable D nel link:
          D.total_cost_accrued += booking_total_cost / N

Idempotente: ricomputa SEMPRE da zero per il deliverable in input
(azzera + ricalcola). Pattern coerente con `cost_line_sync.recompute_cost_line_actual`.

NOTA: Un booking può essere linkato SIA a una JCL (`job_cost_line_id`,
back-compat) SIA a 1+ Deliverable via pivot. Il costo va a ENTRAMBI:
- Cost-side JCL: gestito da `cost_line_sync` (full booking cost)
- Cost-side Deliverable: quota da questo modulo

Non c'è double-count revenue perché:
- JCL.total_accrued = ore_done × unit_price (revenue lavorazione)
- Deliverable.total_accrued = quantity_delivered × unit_price (revenue consegna)
sono entità diverse che il cliente paga separatamente nella quote split
(subtotal_gross_jcl + subtotal_gross_deliverable).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def _booking_cost(booking) -> float:
    """Costo del booking = Σ (assignment_hours × cost_rate_snap).
    Fallback a Resource.internal_cost_hourly se snap NULL (pre-α.167 booking).
    """
    total = 0.0
    for a in (booking.assignments or []):
        if not a.start_datetime or not a.end_datetime:
            continue
        rate = getattr(a, "cost_rate_snap", None)
        if rate is None or rate <= 0:
            res = getattr(a, "resource", None)
            if res is None:
                continue
            rate = res.internal_cost_hourly
            if rate is None or rate <= 0:
                continue
        hours = max(0.0, (a.end_datetime - a.start_datetime).total_seconds() / 3600.0)
        total += hours * rate
    return round(total, 2)


def recompute_deliverable_cost(db: Session, deliverable) -> dict:
    """Ricomputa `Deliverable.total_cost_accrued` come quota equa dei booking
    linkati via `booking_deliverables`.

    Per ogni booking:
      n_links = COUNT(booking_deliverables WHERE booking_id = b.id)
      D.total_cost_accrued += booking_cost(b) / n_links

    Considera SOLO booking con state ∈ {done, in_progress} (esclude
    tentative/cancelled/confirmed-non-iniziato). Coerenza con cost_line_sync
    che pesa solo `done`. Qui includiamo anche `in_progress` perché il
    deliverable comincia ad accumulare costo appena la produzione parte.
    """
    from app.models import (
        Booking, BookingDeliverable, BookingState, BookingStatus,
    )
    from sqlalchemy import func

    if deliverable is None:
        return {"updated": False, "reason": "no_deliverable"}

    # Trova tutti i booking linkati a questo deliverable
    link_rows = (
        db.query(Booking)
        .join(BookingDeliverable, BookingDeliverable.booking_id == Booking.id)
        .filter(
            BookingDeliverable.job_deliverable_id == deliverable.id,
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )

    new_cost = 0.0
    n_bookings_done = 0
    for b in link_rows:
        # Solo done/in_progress contribuiscono ai costi maturati
        state = getattr(b, "state", None)
        if state not in (BookingState.done, BookingState.in_progress):
            continue
        n_bookings_done += 1
        # Conta deliverable linkati a questo booking (per split equa)
        n_links = db.query(func.count(BookingDeliverable.id)).filter(
            BookingDeliverable.booking_id == b.id
        ).scalar() or 1
        booking_cost = _booking_cost(b)
        new_cost += booking_cost / n_links

    new_cost = round(new_cost, 2)

    # Revenue: maturato è manuale (quantity_delivered × unit_price).
    # Aggiornato solo per coerenza display + dirty flag clear.
    quantity_delivered = float(deliverable.quantity_delivered or 0.0)
    quantity_planned = float(deliverable.quantity_planned or 0.0)
    unit_price = float(deliverable.unit_price or 0.0)
    new_accrued = round(quantity_delivered * unit_price, 2)
    new_quoted = round(quantity_planned * unit_price, 2)

    changed = (
        abs((deliverable.total_cost_accrued or 0) - new_cost) > 1e-2
        or abs((deliverable.total_accrued or 0) - new_accrued) > 1e-2
        or abs((deliverable.total_quoted or 0) - new_quoted) > 1e-2
    )
    deliverable.total_cost_accrued = new_cost
    deliverable.total_accrued = new_accrued
    deliverable.total_quoted = new_quoted
    deliverable.accrued_stale = False

    return {
        "updated": changed,
        "deliverable_id": deliverable.id,
        "n_linked_bookings": len(link_rows),
        "n_active_bookings": n_bookings_done,
        "total_cost_accrued": new_cost,
        "total_accrued": new_accrued,
        "total_quoted": new_quoted,
    }


def recompute_for_booking(db: Session, booking) -> dict:
    """Hook chiamato dopo mutazione booking (create/update/delete). Ricalcola
    tutti i deliverable linkati a questo booking. Idempotente.
    """
    from app.models import BookingDeliverable, JobDeliverable
    if booking is None:
        return {"updated": [], "skipped": 0}
    links = db.query(BookingDeliverable).filter(
        BookingDeliverable.booking_id == booking.id
    ).all()
    results = []
    for link in links:
        d = db.query(JobDeliverable).filter(
            JobDeliverable.id == link.job_deliverable_id
        ).first()
        if d is None:
            continue
        r = recompute_deliverable_cost(db, d)
        results.append(r)
    return {"updated": results, "n_links": len(links)}


def recompute_for_job(db: Session, job_id: int) -> dict:
    """Ricalcola tutti i Deliverable di un job. Utile per riconciliazione
    bulk (es. post-import, post-batch).
    """
    from app.models import JobDeliverable
    deliverables = db.query(JobDeliverable).filter(
        JobDeliverable.job_id == job_id,
        JobDeliverable.deleted_at.is_(None),
    ).all()
    results = []
    for d in deliverables:
        results.append(recompute_deliverable_cost(db, d))
    return {"job_id": job_id, "n_deliverables": len(deliverables), "results": results}


def mark_deliverable_stale(db: Session, deliverable_ids) -> int:
    """Dirty flag pattern: marca uno o più deliverable come stale
    (recompute lazy). Coerente con `cost_line_sync.mark_jcl_stale`.
    """
    from app.models import JobDeliverable
    if not deliverable_ids:
        return 0
    if isinstance(deliverable_ids, int):
        deliverable_ids = [deliverable_ids]
    ids = [i for i in deliverable_ids if i]
    if not ids:
        return 0
    db.query(JobDeliverable).filter(JobDeliverable.id.in_(ids)).update(
        {JobDeliverable.accrued_stale: True}, synchronize_session=False
    )
    return len(ids)


def mark_booking_deliverables_stale(db: Session, booking) -> int:
    """Helper: marca tutti i deliverable linkati a un booking come stale."""
    from app.models import BookingDeliverable
    if booking is None:
        return 0
    ids = [r.job_deliverable_id for r in db.query(BookingDeliverable).filter(
        BookingDeliverable.booking_id == booking.id
    ).all()]
    return mark_deliverable_stale(db, ids)
