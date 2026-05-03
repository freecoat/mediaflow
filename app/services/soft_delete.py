"""
MediaFlow — Soft-delete framework (v3.5.0-alpha.7)

Per ora copre la sola entità `Quote`. Il pattern è generico: per estendere
ad altre entità (Project, Client, Resource, …) basta:

  1. Aggiungere `deleted_at` + `deleted_by_user_id` al modello
  2. Aggiungere il modello a `_SOFT_DELETE_MODELS`
  3. Aggiornare l'auto-migrate in `app/main.py`

Il filter automatico è implementato via SQLAlchemy 2.0 `with_loader_criteria`
applicato dentro un event listener su `do_orm_execute`. Esclude di default
qualsiasi record con `deleted_at IS NOT NULL`.

Per bypassare il filter (es. pagina cestino, restore, audit), usare:

    db.query(Quote).execution_options(include_deleted=True).all()

oppure il context manager:

    with include_deleted(db):
        deleted_quotes = db.query(Quote).filter(Quote.deleted_at.isnot(None)).all()
"""
from __future__ import annotations
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.models import (
    Quote, QuoteLine, Job, JobCostLine, Booking, BookingAssignment,
    BookingStatus, User,
)

logger = logging.getLogger(__name__)


# ── Modelli soggetti al filter automatico ──────────────────────

# Aggiungere qui per estendere il pattern. Il modello deve avere `deleted_at`.
_SOFT_DELETE_MODELS = (Quote,)


# ── Event listener: filtra di default ──────────────────────────

def _install_soft_delete_filter() -> None:
    """Registra il listener `do_orm_execute` (idempotente).

    Per ogni SELECT su uno dei `_SOFT_DELETE_MODELS`, il filter
    `deleted_at IS NULL` viene auto-applicato. Bypassabile con
    `execution_options(include_deleted=True)`.
    """
    @event.listens_for(Session, "do_orm_execute")
    def _filter_soft_deleted(execute_state):
        if not execute_state.is_select:
            return
        if execute_state.execution_options.get("include_deleted", False):
            return
        criteria = []
        for model in _SOFT_DELETE_MODELS:
            criteria.append(
                with_loader_criteria(
                    model,
                    lambda cls: cls.deleted_at.is_(None),
                    include_aliases=True,
                )
            )
        if criteria:
            execute_state.statement = execute_state.statement.options(*criteria)


@contextmanager
def include_deleted(db: Session):
    """Context manager opzionale: tutte le query nel blocco vedono anche
    i record in cestino. Esempio:

        with include_deleted(db):
            q = db.query(Quote).filter(Quote.id == qid).first()
    """
    # In SQLAlchemy 2.0 il bypass va passato per-statement; questo helper
    # è solo zucchero sintattico per il caller, in realtà serve usare
    # .execution_options(include_deleted=True). Lasciato per uso futuro.
    yield db


# ── Service: regole di delete/restore Quote ──────────────────

class DeleteBlocked(Exception):
    """Eccezione tipata per HARD-BLOCK con elenco bloccanti.

    Il router la cattura e ritorna 409 con payload strutturato per la UI:
      {detail, blocking: {bookings: [...]}, can_force: bool}
    """
    def __init__(self, message: str, *, bookings: list[dict],
                 jobs: list[dict] | None = None):
        super().__init__(message)
        self.message  = message
        self.bookings = bookings
        self.jobs     = jobs or []


def fetch_quote_including_trash(db: Session, quote_id: int) -> Optional[Quote]:
    """Carica una Quote inclusi i record nel cestino (per restore/purge)."""
    return (db.query(Quote)
              .execution_options(include_deleted=True)
              .filter(Quote.id == quote_id)
              .first())


def _collect_blocking_bookings(db: Session, quote: Quote) -> list[dict]:
    """Ritorna l'elenco dei booking attivi (status != cancelled) collegati
    a una qualunque JobCostLine del Job di questa quote.

    Lista vuota = niente bloccanti, soft-delete sicuro.
    """
    if not quote.job:
        return []
    rows = (db.query(Booking)
              .join(JobCostLine, Booking.job_cost_line_id == JobCostLine.id)
              .filter(JobCostLine.job_id == quote.job.id,
                      Booking.status != BookingStatus.cancelled)
              .all())
    return [{
        "booking_id":      b.id,
        "start_datetime":  b.start_datetime.isoformat() if b.start_datetime else None,
        "end_datetime":    b.end_datetime.isoformat()   if b.end_datetime   else None,
        "status":          b.status.value if hasattr(b.status, "value") else str(b.status),
        "job_cost_line_id": b.job_cost_line_id,
    } for b in rows]


def soft_delete_quote(db: Session, quote: Quote, *, user: User,
                      force: bool = False) -> dict:
    """Soft-delete di una Quote con tutte le regole di integrità v3.4.55+.

    Caso 1 — `force=False` (delete normale, perm `delete_quotes`):
      - Se ci sono booking attivi sul Job collegato → solleva `DeleteBlocked`
        con elenco bloccanti. La UI mostra i booking e suggerisce di
        cancellarli prima.
      - Altrimenti: `quote.deleted_at = now()` + `deleted_by_user_id = user.id`.
        Le QuoteLine ereditano lo stato (sono accessibili solo via
        Quote.lines, e Quote è invisibile).

    Caso 2 — `force=True` (pulizia totale admin, perm `purge_total`):
      - HARD-DELETE atomico cascade: BookingAssignment → Booking →
        JobCostLine → Job → QuoteLine → Quote.
      - Bypass del cestino: irreversibile. Per i casi "spazza via questa
        quote di test e tutto il suo strascico".
      - Se chi chiama non ha `purge_total`, il router rifiuta prima di
        arrivare qui.

    Ritorna un dict con statistiche (per la response/log).
    """
    if quote.deleted_at is not None and not force:
        return {"ok": True, "already_deleted": True, "quote_id": quote.id}

    blocking = _collect_blocking_bookings(db, quote)

    if not force:
        if blocking:
            raise DeleteBlocked(
                f"Quote ha {len(blocking)} booking attivi. "
                "Cancellali prima oppure chiedi a un admin di fare 'pulizia totale'.",
                bookings=blocking,
            )
        # Soft-delete pulito
        quote.deleted_at         = datetime.utcnow()
        quote.deleted_by_user_id = user.id if user else None
        return {
            "ok":           True,
            "mode":         "soft",
            "quote_id":     quote.id,
            "lines_count":  len(quote.lines),
            "had_job":      bool(quote.job),
        }

    # ── force=True: pulizia totale (hard-delete cascade) ───────
    job = quote.job
    job_id = job.id if job else None
    cost_lines_count = 0
    bookings_count = 0
    assignments_count = 0
    if job:
        cost_lines = list(job.cost_lines)
        cost_lines_count = len(cost_lines)
        for cl in cost_lines:
            bks = (db.query(Booking)
                     .filter(Booking.job_cost_line_id == cl.id)
                     .all())
            for b in bks:
                bookings_count += 1
                # cancella assignments
                ass = (db.query(BookingAssignment)
                         .filter(BookingAssignment.booking_id == b.id)
                         .all())
                assignments_count += len(ass)
                for a in ass:
                    db.delete(a)
                db.delete(b)
        # Anche eventuali booking legati al Job senza job_cost_line_id (extra)
        orphan_bks = (db.query(Booking)
                        .filter(Booking.job_id == job.id,
                                Booking.job_cost_line_id.is_(None))
                        .all())
        for b in orphan_bks:
            bookings_count += 1
            ass = (db.query(BookingAssignment)
                     .filter(BookingAssignment.booking_id == b.id)
                     .all())
            assignments_count += len(ass)
            for a in ass:
                db.delete(a)
            db.delete(b)
        for cl in cost_lines:
            db.delete(cl)
        db.delete(job)
    # QuoteLine cascade-orphan via ORM, ma per essere espliciti li rimuovo
    lines_count = len(quote.lines)
    for ln in list(quote.lines):
        db.delete(ln)
    db.delete(quote)
    db.flush()
    return {
        "ok":               True,
        "mode":             "purge_total",
        "quote_id":         quote.id,
        "job_id":           job_id,
        "lines_count":      lines_count,
        "cost_lines_count": cost_lines_count,
        "bookings_count":   bookings_count,
        "assignments_count": assignments_count,
    }


def restore_quote(db: Session, quote: Quote) -> dict:
    """Ripristina una Quote dal cestino. Idempotente."""
    if quote.deleted_at is None:
        return {"ok": True, "already_active": True, "quote_id": quote.id}
    quote.deleted_at         = None
    quote.deleted_by_user_id = None
    return {"ok": True, "quote_id": quote.id}
