"""
MediaFlow — Numbering service unificato (v3.5.0-alpha.66.14.8)

Sostituisce le 3 funzioni ad-hoc `_next_quote_number_progressive`,
`_next_batch_code`, `_next_job_code` (e in futuro `_next_invoice_number`)
con un singolo entry-point.

PROBLEMA RISOLTO N.1 — Soft-delete bypass: i record cestinati conservano
il campo UNIQUE (Quote.number, BillingBatch.code, Job.code). Pre-check
sul `db.query(Model).filter(...).first()` senza `execution_options(
include_deleted=True)` non vede i cestinati → genera codice già occupato →
IntegrityError 500 al INSERT successivo. Documentato in
`feedback_soft_delete_unique_bypass.md` (v3.5.0-alpha.7.3) come pattern da
applicare ovunque.

PROBLEMA RISOLTO N.2 — Race condition (parziale): SELECT max + INSERT non
è atomico. 2 utenti → stesso numero → IntegrityError sul secondo INSERT.
Soluzione completa richiede sequence DB / SELECT FOR UPDATE (PostgreSQL)
o BEGIN IMMEDIATE (SQLite). Qui implementiamo retry-on-IntegrityError che
copre il singolo workflow ma non garantisce assenza di errore visibile
all'utente. Sarà migrato a transazione pessimistica nello sprint R4
"Booking mutation gate".

DESIGN:
- `next_progressive_code(db, model, prefix, *, code_field, include_deleted)`
  - Ritorna il prossimo `f"{prefix}{N:03d}"` non ancora usato.
  - `code_field` può essere "code" o "number".
  - `include_deleted=True` di default → bypass soft-delete listener.
  - Considera tail "vNN" per versioning quote (skip).
- `with_retry_on_unique(callable, *, retries=3)` — wrapper che riesegue
  un INSERT su IntegrityError (UNIQUE violato) ricomputando il number.
  Per race condition.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Optional, Callable, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


def next_progressive_code(
    db: Session,
    model: type,
    prefix: str,
    *,
    code_field: str = "code",
    include_deleted: bool = True,
    extra_filter: Optional[Any] = None,
) -> str:
    """Genera prossimo codice progressivo `f"{prefix}{N:03d}"` non occupato.

    Args:
        db: Session SQLAlchemy.
        model: Classe ORM (Quote, BillingBatch, Job, Invoice, ecc.).
        prefix: Prefisso fisso es. "Q-2026-", "BB-2026-", "{PROJECT_CODE}-J".
        code_field: Nome del campo UNIQUE da sondare. Default "code"; per
            Quote usare "number".
        include_deleted: Se True, bypass del soft-delete filter event-listener
            (default). Se l'entità non supporta soft-delete è no-op.
        extra_filter: Clausola SQL aggiuntiva (es. tenant scope) opzionale.

    Returns:
        Stringa `f"{prefix}{N:03d}"` libera al momento della query.

    NB: Non garantisce thread-safety. Tra ritorno e INSERT del caller può
    interporsi un altro utente che usa lo stesso N → IntegrityError.
    Wrappare l'INSERT in `with_retry_on_unique`.
    """
    col = getattr(model, code_field)
    q = db.query(model).filter(col.like(f"{prefix}%"))
    if include_deleted:
        # SQLAlchemy 2.0 do_orm_execute event listener (vedi soft_delete.py)
        q = q.execution_options(include_deleted=True)
    if extra_filter is not None:
        q = q.filter(extra_filter)
    last = q.order_by(model.id.desc()).first()
    n = 1
    if last is not None:
        try:
            tail = getattr(last, code_field).rsplit("-", 1)[1]
            # Skip tail "vNN" (es. quote versioning Q-2026-001-v2):
            # in tal caso ricaviamo il base "Q-2026-001" e prendiamo il suo N.
            if tail.startswith("v") and tail[1:].isdigit():
                base = getattr(last, code_field).rsplit("-", 1)[0]
                tail = base.rsplit("-", 1)[1]
            n = int(tail) + 1
        except (ValueError, IndexError, AttributeError):
            n = 1
    return f"{prefix}{n:03d}"


def next_year_progressive(
    db: Session,
    model: type,
    prefix_template: str = "{base}-{year}-",
    *,
    base: str,
    code_field: str = "code",
    include_deleted: bool = True,
    extra_filter: Optional[Any] = None,
) -> str:
    """Variante per pattern `{BASE}-{YEAR}-{NNN}` (Q-2026-001, BB-2026-007).

    Helper sopra `next_progressive_code` che costruisce il prefix con anno
    corrente. Args identici escluso `prefix_template` e `base`.
    """
    year = _date.today().year
    prefix = prefix_template.format(base=base, year=year)
    return next_progressive_code(
        db, model, prefix,
        code_field=code_field,
        include_deleted=include_deleted,
        extra_filter=extra_filter,
    )


def with_retry_on_unique(
    fn: Callable[[], Any],
    *,
    retries: int = 3,
) -> Any:
    """Esegui `fn()` (es. INSERT + commit). Se IntegrityError per UNIQUE
    violato, retry fino a `retries` volte. Tra retry il caller è
    responsabile di ricomputare il codice (rilegge da DB).

    Pattern di uso:

        def _do():
            number = next_progressive_code(db, Quote, "Q-2026-",
                                           code_field="number")
            q = Quote(number=number, ...)
            db.add(q)
            db.commit()
            return q

        q = with_retry_on_unique(_do, retries=3)

    Sui retries esauriti, rilancia l'ultimo IntegrityError.
    """
    last_err: Optional[IntegrityError] = None
    for attempt in range(retries):
        try:
            return fn()
        except IntegrityError as e:
            last_err = e
            logger.warning(
                f"numbering retry {attempt+1}/{retries} on UNIQUE: {e.orig if hasattr(e, 'orig') else e}"
            )
    if last_err is not None:
        raise last_err
    return None  # unreachable
