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
    # v3.5.0-alpha.172.97 — scan ALL matching codes and compute max(N).
    # ORDER BY id.desc() era fragile: con versioning (Q-2026-004-v2) il
    # "piu' recente" puntava a un base N piu' basso, restituendo un N gia'
    # occupato da un altro doc → UNIQUE collision. Fix: max progressive
    # tra tutti i match, ignorando suffix -vNN.
    max_n = 0
    for row in q.all():
        code = getattr(row, code_field)
        if not code:
            continue
        try:
            tail = code.rsplit("-", 1)[1]
            if tail.startswith("v") and tail[1:].isdigit():
                base = code.rsplit("-", 1)[0]
                tail = base.rsplit("-", 1)[1]
            cur_n = int(tail)
        except (ValueError, IndexError, AttributeError):
            continue
        if cur_n > max_n:
            max_n = cur_n
    return f"{prefix}{max_n + 1:03d}"


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


# v3.5.0-alpha.115 — NumberingConfig cabling.
# Variabili supportate per ogni doc_type. UI greys-out quelle non in lista.
_DOC_VARS_SUPPORTED: dict[str, set[str]] = {
    "quote":               {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","PROJECT_CODE","CLIENT_CODE"},
    "billing_batch":       {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","PROJECT_CODE","CLIENT_CODE"},
    "invoice":             {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","CLIENT_CODE","PROJECT_CODE"},
    "invoice_closing":     {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","PROJECT_CODE","CLIENT_CODE"},
    "invoice_credit_note": {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","CLIENT_CODE"},
    "job":                 {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","PROJECT_CODE"},
    "cost_report_export":  {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","PROJECT_CODE"},
    "supplier_invoice":    {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN"},
    "overhead_cost":       {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN"},
    # v3.5.0-alpha.116 — Ingest batch + DDT (logistica fisica)
    "ingest_batch":        {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","PROJECT_CODE"},
    "ddt":                 {"YYYY","YY","MM","DD","YYYYMMDD","NNN","NN","NNNN","PROJECT_CODE"},
}

_DOC_DEFAULTS: dict[str, str] = {
    "quote":               "Q-{YYYY}-{NNN}",
    "billing_batch":       "BB-{YYYY}-{NNN}",
    "invoice":             "{NNN}/{YYYY}",
    "invoice_closing":     "CL-{PROJECT_CODE}-{YYYY}",
    "invoice_credit_note": "NC-{YYYY}-{NNN}",
    "job":                 "{PROJECT_CODE}-J{NNN}",
    "cost_report_export":  "CR-{PROJECT_CODE}-{YYYYMMDD}",
    "supplier_invoice":    "FP-{YYYY}-{NNN}",
    "overhead_cost":       "OH-{YYYY}-{NNNN}",
    "ingest_batch":        "BATCH-{YYYY}-{NNN}",
    "ddt":                 "DDT-{YYYY}-{NNN}",
}


def supported_vars(doc_type: str) -> set[str]:
    """Variabili lecite nel format_pattern di un doc_type."""
    return _DOC_VARS_SUPPORTED.get(doc_type, set())


def default_pattern(doc_type: str) -> str:
    """Pattern default per back-compat se NumberingConfig non personalizzato."""
    return _DOC_DEFAULTS.get(doc_type, "{NNN}")


def validate_pattern(doc_type: str, pattern: str) -> Optional[str]:
    """Verifica che il pattern contenga solo variabili supportate per il doc_type.
    Ritorna None se valido, altrimenti il nome della variabile non supportata."""
    import re
    allowed = _DOC_VARS_SUPPORTED.get(doc_type, set())
    if not allowed:
        return None
    for var in re.findall(r"\{([A-Z_]+)\}", pattern):
        if var not in allowed:
            return var
    return None


def expand_pattern(
    fmt: str,
    seq: int,
    *,
    project_code: Optional[str] = None,
    client_code: Optional[str] = None,
    today: Optional[_date] = None,
) -> str:
    """Sostituisci tutte le variabili del format_pattern.
    Variabili date e seq sono sempre disponibili. PROJECT_CODE/CLIENT_CODE
    fallback a "" se non passati (eviting placeholder fake)."""
    if today is None:
        today = _date.today()
    return (
        fmt
        .replace("{YYYY}", f"{today.year:04d}")
        .replace("{YY}",   f"{today.year % 100:02d}")
        .replace("{MM}",   f"{today.month:02d}")
        .replace("{DD}",   f"{today.day:02d}")
        .replace("{YYYYMMDD}", today.strftime("%Y%m%d"))
        .replace("{NNNN}", f"{seq:04d}")
        .replace("{NNN}",  f"{seq:03d}")
        .replace("{NN}",   f"{seq:02d}")
        .replace("{PROJECT_CODE}", (project_code or ""))
        .replace("{CLIENT_CODE}",  (client_code or ""))
    )


def gen_doc_code(
    db: Session,
    doc_type: str,
    *,
    tenant_id: int,
    project_code: Optional[str] = None,
    client_code: Optional[str] = None,
    today: Optional[_date] = None,
) -> tuple[str, int]:
    """Generatore unificato che legge NumberingConfig + incrementa seq atomico.

    Ritorna (code_generato, seq_usata).

    Algoritmo:
    1. Cerca NumberingConfig(tenant_id, doc_type). Se assente: usa default.
    2. Se reset_yearly e current_year != today.year: reset seq=0.
    3. seq = current_seq + 1.
    4. Espande variabili + ritorna codice.
    5. Aggiorna current_seq + current_year nel record (caller commit).
    6. NB: caller deve gestire UNIQUE collision via with_retry_on_unique.
    """
    if today is None:
        today = _date.today()
    from app.models.models import NumberingConfig
    rec = db.query(NumberingConfig).filter(
        NumberingConfig.tenant_id == tenant_id,
        NumberingConfig.doc_type == doc_type,
    ).first()
    if rec is None:
        fmt = default_pattern(doc_type)
        reset_yearly = True
        last_seq = 0
    else:
        fmt = rec.format_pattern or default_pattern(doc_type)
        reset_yearly = bool(rec.reset_yearly)
        last_seq = rec.current_seq or 0
        if reset_yearly and (rec.current_year or 0) != today.year:
            last_seq = 0
    seq = last_seq + 1
    code = expand_pattern(fmt, seq, project_code=project_code,
                          client_code=client_code, today=today)
    # Atomically update record (or create if missing)
    if rec is None:
        rec = NumberingConfig(
            tenant_id=tenant_id, doc_type=doc_type,
            format_pattern=fmt, reset_yearly=reset_yearly,
            current_year=today.year, current_seq=seq,
        )
        db.add(rec)
    else:
        rec.current_year = today.year
        rec.current_seq = seq
    return code, seq


# v3.5.0-alpha.172.97 — Helper versioning per Quote.number
# Tutte le Quote nascono con suffix -v1. new-version aggiunge -v(N+1).
# Folder-view UI raggruppa per base_code = strip -vN suffix.
import re as _re

_VERSION_SUFFIX_RE = _re.compile(r"-v(\d+)$")


def split_version_suffix(code: str) -> tuple[str, int]:
    """Spezza un Quote.number in (base, version_number).

    Esempi:
        "Q-2026-001-v2" -> ("Q-2026-001", 2)
        "Q-2026-001"    -> ("Q-2026-001", 1)   # legacy fallback
        ""              -> ("", 1)
    """
    if not code:
        return "", 1
    m = _VERSION_SUFFIX_RE.search(code)
    if m:
        return code[:m.start()], int(m.group(1))
    return code, 1


def with_v1_suffix(code: str) -> str:
    """Aggiunge `-v1` a un base code se non ha già un suffix -vN.

    Idempotente. Usato dai generatori quote-number per produrre sempre
    codici versionati uniformi (Q-2026-001-v1).
    """
    if not code:
        return code
    return code if _VERSION_SUFFIX_RE.search(code) else f"{code}-v1"


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
