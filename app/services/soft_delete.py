"""
MediaFlow — Soft-delete framework (v3.5.0-alpha.7, esteso α.66.15.3)

Estensione α.66.15.3 (sprint R2): copre ora 5 entità: Quote, Project,
PricelistSnapshot, PhysicalAsset, JobDeliverable. Tutte hanno colonna
`deleted_at` e vengono auto-filtrate dalle SELECT salvo bypass esplicito.

Pattern generico: per estendere ad altre entità basta:

  1. Aggiungere `deleted_at` + `deleted_by_user_id` al modello
  2. Aggiungere il modello a `_SOFT_DELETE_MODELS`
  3. Aggiornare l'auto-migrate in `app/main.py` (se nuova colonna su tabella esistente)

Il filter automatico è implementato via SQLAlchemy 2.0 `with_loader_criteria`
applicato dentro un event listener su `do_orm_execute`. Esclude di default
qualsiasi record con `deleted_at IS NOT NULL`.

Per bypassare il filter (es. pagina cestino, restore, audit, pre-check
unicità di un campo che il record cestinato occupa ancora), usare:

    db.query(Quote).execution_options(include_deleted=True).all()

oppure il context manager:

    with include_deleted(db):
        deleted_quotes = db.query(Quote).filter(Quote.deleted_at.isnot(None)).all()

Per le pre-check di unicità su rename/INSERT, usare il helper
`is_unique_or_deleted_aware` (v3.5.0-alpha.66.15.4) che fa il bypass
automaticamente.
"""
from __future__ import annotations
from app.services.clock import now_utc
import logging
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.models import (
    Quote, QuoteLine, Job, JobCostLine, Booking, BookingAssignment,
    BookingStatus, JobResourceAssignment, Project, User,
    PricelistSnapshot, PhysicalAsset, JobDeliverable,
)

logger = logging.getLogger(__name__)


# ── Modelli soggetti al filter automatico ──────────────────────

# Aggiungere qui per estendere il pattern. Il modello deve avere `deleted_at`.
# v3.5.0-alpha.66.15.3 (R2.0): aggiunti i 3 modelli che avevano deleted_at
# come colonna ma non erano nel filter auto (audit pattern systemico B).
_SOFT_DELETE_MODELS = (
    Quote, Project,
    PricelistSnapshot,   # introdotta α.66.6
    PhysicalAsset,       # introdotta α.66.9
    JobDeliverable,      # introdotta α.66.9
)


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


def is_unique_or_deleted_aware(
    db: Session,
    model: type,
    field: str,
    value: Any,
    *,
    exclude_id: Optional[int] = None,
    extra_filter: Optional[Any] = None,
) -> bool:
    """v3.5.0-alpha.66.15.4 — Pre-check unicità SOFT-DELETE-AWARE.

    Risolve l'audit HIGH #2: i pre-check di unicità sui campi `Project.code`,
    `Quote.number`, `Job.code`, ecc NON bypassano automaticamente il filter
    soft-delete. Risultato: l'utente cancella un Project con code "X", ne
    crea uno nuovo con code "X" → la pre-check passa (vede 0 record perché
    cestinato è filtrato), ma INSERT viola UNIQUE → 500.

    Questo helper bypassa il filter via `execution_options(include_deleted=True)`
    e ritorna True se il valore è davvero unico (anche includendo il cestino),
    False altrimenti.

    Args:
        db: Session SQLAlchemy.
        model: Classe ORM (Project, Quote, Job, BillingBatch, ecc.).
        field: Nome del campo da controllare (es. "code", "number").
        value: Valore proposto.
        exclude_id: PK da escludere (per UPDATE/rename: non comparare con se stesso).
        extra_filter: Clausola SQL aggiuntiva (es. tenant scope).

    Returns:
        True se `value` è disponibile (non occupato neanche in cestino).
        False se è occupato.

    Esempio uso:

        # CREATE Project
        if not is_unique_or_deleted_aware(db, Project, "code", code):
            raise HTTPException(400, f"Codice '{code}' già usato (anche in cestino)")

        # UPDATE Project rename
        if not is_unique_or_deleted_aware(db, Project, "code", new_code, exclude_id=p.id):
            raise HTTPException(400, f"Codice '{new_code}' già usato")
    """
    col = getattr(model, field)
    q = db.query(model).execution_options(include_deleted=True).filter(col == value)
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    if extra_filter is not None:
        q = q.filter(extra_filter)
    return q.first() is None


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


# v3.5.0-alpha.172.97 — Prefisso "bin" sul `number` di Quote in cestino.
# La UNIQUE constraint a livello DB su `quotes.number` non distingue tra
# attive e soft-deleted. Senza prefisso, dopo cestino di Q-2026-004-v2,
# una nuova versione con lo stesso nome falliva con IntegrityError.
# Soluzione: rinominare a `~B<id>~<original>` al delete, strip al restore.
_BIN_PREFIX_RE = re.compile(r"^~B(\d+)~")


def _bin_number(quote_id: int, original: str) -> str:
    """Genera number cestinato. Massimo 50 char (vedi Quote.number)."""
    prefix = f"~B{quote_id}~"
    # Tronca l'originale se complessivamente eccede 50 char
    max_orig = 50 - len(prefix)
    return prefix + (original[:max_orig] if original else "")


def _strip_bin_prefix(number: str) -> Optional[str]:
    """Se il numero ha il prefisso bin, ritorna l'originale. Altrimenti None."""
    if not number:
        return None
    m = _BIN_PREFIX_RE.match(number)
    if not m:
        return None
    return number[m.end():]


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
        # v3.5.0-alpha.172.97 — rinomina number con prefisso bin per liberare
        # il number originale per nuove quote/versioni (UNIQUE constraint DB
        # non distingue tra attive e soft-deleted).
        if quote.number and not _BIN_PREFIX_RE.match(quote.number):
            quote.number = _bin_number(quote.id, quote.number)
        quote.deleted_at         = now_utc()
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
    """Ripristina una Quote dal cestino. Idempotente.

    v3.5.0-alpha.172.97 — strip prefisso bin sul number. Se il number originale
    e' nel frattempo occupato da un'altra quote attiva, ritorna `renamed=True`
    con un nuovo number progressivo (`<orig>_R<id>`) e segnala il caller.
    """
    if quote.deleted_at is None:
        return {"ok": True, "already_active": True, "quote_id": quote.id}
    original = _strip_bin_prefix(quote.number) if quote.number else None
    renamed_to: Optional[str] = None
    if original:
        # Collision check: number originale occupato da altra quote attiva
        collision = (
            db.query(Quote)
            .filter(Quote.number == original, Quote.id != quote.id)
            .first()
        )
        if collision is None:
            quote.number = original
        else:
            # Mantiene number con suffisso di emergenza per non rompere UNIQUE
            quote.number = f"{original}_R{quote.id}"
            renamed_to = quote.number
    quote.deleted_at         = None
    quote.deleted_by_user_id = None
    return {
        "ok": True,
        "quote_id": quote.id,
        "renamed_to": renamed_to,
        "restored_number": quote.number,
    }


# ── Service: regole di delete/restore Project (v3.5.0-alpha.8) ─

def fetch_project_including_trash(db: Session, project_id: int) -> Optional[Project]:
    return (db.query(Project)
              .execution_options(include_deleted=True)
              .filter(Project.id == project_id)
              .first())


def _collect_active_quotes_on_project(db: Session, project: Project) -> list[dict]:
    """Quote ATTIVE (non in cestino) sul progetto. Lista vuota = niente
    bloccanti, soft-delete progetto sicuro.

    Le quote già in cestino non sono bloccanti: il progetto può essere
    cestinato sopra di esse, le ritrovi entrambe in /admin/cestino e
    decidi cosa ripristinare/purgare.
    """
    rows = (db.query(Quote)
              .filter(Quote.project_id == project.id, Quote.deleted_at.is_(None))
              .all())
    return [{
        "quote_id":  q.id,
        "number":    q.number,
        "title":     q.title,
        "status":    q.status.value if hasattr(q.status, "value") else str(q.status),
    } for q in rows]


def soft_delete_project(db: Session, project: Project, *, user: User,
                        force: bool = False) -> dict:
    """Soft-delete di un Project. Regole:

    Caso 1 — `force=False` (delete normale, perm `delete_projects`):
      - Quote attive sul progetto → `DeleteBlocked` con elenco. L'utente
        deve cestinarle prima (oppure chiede pulizia totale a un admin).
      - Altrimenti: `project.deleted_at = now()`. Le quote già nel cestino
        rimangono nel cestino, le job/resource_assignment rimangono in DB
        accessibili tramite la relationship Project.jobs (filtrate solo se
        avranno il proprio soft-delete in slice future).

    Caso 2 — `force=True` (purge_total, solo admin):
      - HARD-DELETE atomico cascade: assignments + bookings + cost_lines +
        jobs + quote_lines + quotes + project. Bypassa il cestino,
        irreversibile.

    Ritorna dict statistiche per response/log.
    """
    if project.deleted_at is not None and not force:
        return {"ok": True, "already_deleted": True, "project_id": project.id}

    blocking_quotes = _collect_active_quotes_on_project(db, project)

    if not force:
        if blocking_quotes:
            raise DeleteBlocked(
                f"Progetto ha {len(blocking_quotes)} quotazion"
                + ("e attiva" if len(blocking_quotes) == 1 else "i attive") + ". "
                "Cestinale prima oppure chiedi a un admin di fare 'pulizia totale'.",
                bookings=[],
                jobs=[{"label": f"{q['number']} — {q['title']}",
                        "id":    q["quote_id"]} for q in blocking_quotes],
            )
        project.deleted_at         = now_utc()
        project.deleted_by_user_id = user.id if user else None
        return {
            "ok":         True,
            "mode":       "soft",
            "project_id": project.id,
            "code":       project.code,
        }

    # ── force=True: hard-delete cascade ────────────────────────
    # Prendi anche quote in cestino (bypass filter)
    quotes_all = (db.query(Quote)
                    .execution_options(include_deleted=True)
                    .filter(Quote.project_id == project.id)
                    .all())
    quotes_count = 0
    jobs_count = 0
    cost_lines_count = 0
    bookings_count = 0
    assignments_count = 0
    job_assignments_count = 0
    for q in quotes_all:
        quotes_count += 1
        job = q.job
        if job:
            jobs_count += 1
            cost_lines = list(job.cost_lines)
            cost_lines_count += len(cost_lines)
            for cl in cost_lines:
                bks = (db.query(Booking)
                         .filter(Booking.job_cost_line_id == cl.id)
                         .all())
                for b in bks:
                    bookings_count += 1
                    ass = (db.query(BookingAssignment)
                             .filter(BookingAssignment.booking_id == b.id).all())
                    assignments_count += len(ass)
                    for a in ass:
                        db.delete(a)
                    db.delete(b)
            # Booking orfani senza cost_line
            orphan_bks = (db.query(Booking)
                            .filter(Booking.job_id == job.id,
                                    Booking.job_cost_line_id.is_(None))
                            .all())
            for b in orphan_bks:
                bookings_count += 1
                ass = (db.query(BookingAssignment)
                         .filter(BookingAssignment.booking_id == b.id).all())
                assignments_count += len(ass)
                for a in ass:
                    db.delete(a)
                db.delete(b)
            # Resource assignments del job
            jra = (db.query(JobResourceAssignment)
                     .filter(JobResourceAssignment.job_id == job.id).all())
            job_assignments_count += len(jra)
            for x in jra:
                db.delete(x)
            for cl in cost_lines:
                db.delete(cl)
            db.delete(job)
        for ln in list(q.lines):
            db.delete(ln)
        db.delete(q)
    db.delete(project)
    db.flush()
    return {
        "ok":                    True,
        "mode":                  "purge_total",
        "project_id":            project.id,
        "quotes_count":          quotes_count,
        "jobs_count":            jobs_count,
        "cost_lines_count":      cost_lines_count,
        "bookings_count":        bookings_count,
        "assignments_count":     assignments_count,
        "job_assignments_count": job_assignments_count,
    }


def restore_project(db: Session, project: Project) -> dict:
    """Ripristina un Project dal cestino. Idempotente."""
    if project.deleted_at is None:
        return {"ok": True, "already_active": True, "project_id": project.id}
    project.deleted_at         = None
    project.deleted_by_user_id = None
    return {"ok": True, "project_id": project.id}


# ── Retention: purge automatico (v3.5.0-alpha.8) ───────────────

def purge_expired_trash(db: Session, *, retention_days: Optional[int] = None,
                        dry_run: bool = False) -> dict:
    """Cancella definitivamente i record nel cestino più vecchi di
    `retention_days` giorni.

    - `retention_days=None` legge da `settings.trash_retention_days` (default 30).
    - `retention_days=0` = mai (no-op): l'utente vuole gestire il cestino
      manualmente, niente auto-purge.
    - `dry_run=True` ritorna solo il conto senza cancellare.

    Ritorna `{quotes_purged, projects_purged, retention_days, cutoff}`.
    Per ogni record cancellato applica la stessa logica cascade di
    `soft_delete_*(force=True)` (hard-delete totale di quote+job+booking
    o project+quote+job+booking).
    """
    from datetime import timedelta
    from app.config import settings

    if retention_days is None:
        retention_days = int(getattr(settings, "trash_retention_days", 30) or 0)
    if retention_days <= 0:
        return {"skipped": True, "reason": "retention_days_zero",
                "retention_days": retention_days}

    cutoff = now_utc() - timedelta(days=retention_days)

    # Quote scadute
    expired_quotes = (db.query(Quote)
                        .execution_options(include_deleted=True)
                        .filter(Quote.deleted_at.isnot(None),
                                Quote.deleted_at < cutoff)
                        .all())
    quotes_to_purge = [(q.id, q.number, q.title) for q in expired_quotes]

    # Project scaduti
    expired_projects = (db.query(Project)
                          .execution_options(include_deleted=True)
                          .filter(Project.deleted_at.isnot(None),
                                  Project.deleted_at < cutoff)
                          .all())
    projects_to_purge = [(p.id, p.code, p.title) for p in expired_projects]

    if dry_run:
        return {
            "dry_run":         True,
            "retention_days":  retention_days,
            "cutoff":          cutoff.isoformat(),
            "quotes_to_purge":   [{"id": qid, "number": n, "title": t}
                                  for qid, n, t in quotes_to_purge],
            "projects_to_purge": [{"id": pid, "code": c, "title": t}
                                  for pid, c, t in projects_to_purge],
        }

    # Eseguo purge in due passate. Project per primo (cascade pulisce le
    # quote sue), poi le quote rimaste (potrebbe avercene di "nude" senza
    # progetto cestinato).
    for p in expired_projects:
        soft_delete_project(db, p, user=None, force=True)
    # Ricarica le quote scadute rimaste (alcune potrebbero essere già state
    # cancellate dal cascade del project sopra).
    expired_quotes = (db.query(Quote)
                        .execution_options(include_deleted=True)
                        .filter(Quote.deleted_at.isnot(None),
                                Quote.deleted_at < cutoff)
                        .all())
    for q in expired_quotes:
        soft_delete_quote(db, q, user=None, force=True)
    db.flush()

    return {
        "ok":              True,
        "retention_days":  retention_days,
        "cutoff":          cutoff.isoformat(),
        "quotes_purged":   len(quotes_to_purge),
        "projects_purged": len(projects_to_purge),
    }
