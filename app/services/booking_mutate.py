"""
MediaFlow — Booking mutation gate (v3.5.0-alpha.66.16.1)

Sprint R4 dell'audit: chiude pattern systemico O ("invarianti enforcati a
livello di handler, non a livello di modello"). SLICE_LOCK era validato in
7+ punti diversi (router planning + AI handlers move/resize/delete) con
copie inline divergenti. Una nuova mutator-route dimentica facilmente.

Questo modulo offre 3 helper unificati che TUTTI i call site di mutazione
booking devono usare:

1. `assert_slice_lock_safe(db, b, *, new_dates=None, force_unlock=False)`
   Solleva `SliceLocked` se il booking è dentro periodo billed:
   - se `new_dates` è None → check sulla posizione CORRENTE del booking
   - se `new_dates=(start,end)` → check sulla NUOVA posizione (move/resize)
   - `force_unlock=True` bypassa il check (slice-lock confirm dell'UI)

2. `assert_no_overlap_after(db, b, proposed_assignments)`
   Solleva `BookingConflict` se i NUOVI start/end/resource_id degli
   assignment causano overlap su altri booking della stessa risorsa.
   `proposed_assignments` = list[(BookingAssignment, new_start, new_end, new_resource_id)]
   (gli assignment del booking corrente sono auto-esclusi).

3. `audit_booking_mutation(db, b, *, kind, summary, payload, user_id=None)`
   Crea una `BookingChange` audit row con metadata standard. Idempotente:
   chiama `db.add()` ma non commit (lascia al caller la transazione).

Tipiche eccezioni:
- `SliceLocked`: booking dentro periodo già fatturato. Caller traduce in
  HTTP 409 con `code=SLICE_LOCK_CONFIRM_REQUIRED` (pattern α.66.3).
- `BookingConflict`: overlap su risorsa. Caller traduce in HTTP 409 / ValueError.

NB: questi helper NON committano. La transazione resta del caller, in
linea con il pattern "service flusha, router committa" (audit pattern E).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Booking, BookingAssignment, BookingChange, BookingStatus
from app.models.models import JCLBilledSlice
from app.services.billing_slice_guard import (
    find_blocking_slice,
    find_blocking_slice_for_dates,
    slice_lock_message,
    slice_lock_payload,
)

logger = logging.getLogger(__name__)


# ── Eccezioni tipate ──────────────────────────────────────────


class SliceLocked(Exception):
    """Booking dentro periodo già fatturato. Il caller (router) deve
    rispondere 409 con `code=SLICE_LOCK_CONFIRM_REQUIRED` + payload
    dettaglio (vedi `slice_lock_payload`).

    L'attributo `slice` è la `JCLBilledSlice` colpevole; `payload` è il
    dict pronto per response.
    """

    def __init__(self, slice_: JCLBilledSlice):
        super().__init__(slice_lock_message(slice_))
        self.slice = slice_
        self.payload = slice_lock_payload(slice_)
        self.message = slice_lock_message(slice_)


class BookingConflict(Exception):
    """Overlap su una risorsa. `conflict_assignment_id` indica con quale
    altro assignment c'è sovrapposizione."""

    def __init__(self, message: str, *, conflict_assignment_id: Optional[int] = None,
                 own_assignment_id: Optional[int] = None,
                 resource_id: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.conflict_assignment_id = conflict_assignment_id
        self.own_assignment_id = own_assignment_id
        self.resource_id = resource_id


# ── Helper #1: slice-lock unificato ───────────────────────────


def assert_slice_lock_safe(
    db: Session,
    b: Booking,
    *,
    new_dates: Optional[Tuple[date, date]] = None,
    force_unlock: bool = False,
) -> None:
    """Verifica unica per tutti i mutator. Si comporta in 3 modi a seconda
    dei parametri:

    - `new_dates=None`, `force_unlock=False` → check posizione CORRENTE
      del booking (per delete, state change, edit non-temporale).
    - `new_dates=(start,end)`, `force_unlock=False` → check NUOVA posizione
      (per move/resize). `start`/`end` sono date envelope risultanti.
    - `force_unlock=True` → bypass (lo richiede l'utente da UI 409).

    Solleva `SliceLocked` se il booking ricade in slice billed.
    Ritorna `None` se è safe.
    """
    if force_unlock:
        return
    if not b.job_cost_line_id:
        return  # niente JCL, niente fattura, niente lock
    if new_dates is None:
        s = find_blocking_slice(db, b)
    else:
        new_start, new_end = new_dates
        s = find_blocking_slice_for_dates(db, b.job_cost_line_id, new_start, new_end)
    if s is not None:
        raise SliceLocked(s)


# ── Helper #2: overlap check ──────────────────────────────────


def assert_no_overlap_after(
    db: Session,
    b: Booking,
    proposed_assignments: list[Tuple[BookingAssignment, datetime, datetime, int]],
) -> None:
    """Verifica che i NUOVI orari/risorse degli assignment non causino
    overlap su altri assignment esistenti (esclusi quelli del booking
    corrente). `proposed_assignments` = list di (orig_assignment, new_start,
    new_end, new_resource_id).

    Solleva `BookingConflict` al primo overlap trovato.
    """
    if not proposed_assignments:
        return
    own_ids = {a.id for a, *_ in proposed_assignments}
    for orig, ns, ne, nrid in proposed_assignments:
        c = (
            db.query(BookingAssignment)
            .join(Booking)
            .filter(
                Booking.status != BookingStatus.cancelled,
                BookingAssignment.id.notin_(own_ids),
                BookingAssignment.resource_id == nrid,
                BookingAssignment.start_datetime < ne,
                BookingAssignment.end_datetime > ns,
            )
            .first()
        )
        if c is not None:
            raise BookingConflict(
                f"Conflitto: assignment #{orig.id} su risorsa #{nrid} "
                f"({ns.strftime('%d/%m %H:%M')}→{ne.strftime('%H:%M')}) "
                f"overlap con assignment #{c.id}",
                conflict_assignment_id=c.id,
                own_assignment_id=orig.id,
                resource_id=nrid,
            )


# ── Helper #3: audit log ──────────────────────────────────────


def audit_booking_mutation(
    db: Session,
    b: Booking,
    *,
    kind: str,
    summary: str = "",
    payload: Optional[dict] = None,
    user_id: Optional[int] = None,
) -> BookingChange:
    """Crea (e `db.add()`) una `BookingChange` row. NON committa: la
    transazione resta del caller (pattern service-flusha-router-committa).

    Args:
        kind: tag della mutazione, es. "ai_move", "user_resize", "bulk_state",
              "delete", "restore". Convenzione open: usato per filtri
              dashboard audit.
        summary: testo umano breve (riepilogo per UI).
        payload: dict serializzabile JSON con dettagli (delta_minutes,
                 from_resource_id → to_resource_id, ecc).
        user_id: chi ha fatto la modifica (None se sistema/AI).
    """
    bc = BookingChange(
        booking_id=b.id,
        kind=kind,
        summary=summary or kind,
        payload=payload or {},
    )
    # Best-effort: alcuni vecchi schemi BookingChange non hanno user_id
    if user_id is not None and hasattr(BookingChange, "user_id"):
        bc.user_id = user_id
    db.add(bc)
    return bc


# ── Helper combinato (coverage piena slice + overlap) ─────────


def assert_mutation_safe(
    db: Session,
    b: Booking,
    proposed_assignments: list[Tuple[BookingAssignment, datetime, datetime, int]],
    *,
    force_unlock: bool = False,
) -> None:
    """Pre-flight check completo per move/resize/multi-move:

    1. Slice-lock CORRENTE (no current-position dentro fattura)
    2. Overlap check NEW (no conflitti orari)
    3. Slice-lock NUOVO (no new-position dentro fattura)

    Args identici a `assert_no_overlap_after`. Solleva `SliceLocked` o
    `BookingConflict`. Niente cambio sul DB.

    Use case: AI move/resize, multi-move, bulk-edit. Il caller fa solo
    il try/except + traduzione HTTP.
    """
    assert_slice_lock_safe(db, b, force_unlock=force_unlock)
    assert_no_overlap_after(db, b, proposed_assignments)
    if proposed_assignments:
        new_min = min(ns for _a, ns, _ne, _nrid in proposed_assignments).date()
        new_max = max(ne for _a, _ns, ne, _nrid in proposed_assignments).date()
        assert_slice_lock_safe(
            db, b, new_dates=(new_min, new_max), force_unlock=force_unlock,
        )
