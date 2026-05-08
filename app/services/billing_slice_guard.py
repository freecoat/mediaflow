"""v3.5.0-alpha.59 — Guard sui Booking dentro periodo già fatturato.

Una `JCLBilledSlice` (introdotta in α.58) registra che la JCL è stata
fatturata per un periodo specifico. Modificare un Booking il cui intervallo
ricade *anche parzialmente* in quel periodo corromperebbe la fattura
emessa: il maturato tornerebbe a divergere dallo snapshot, ma la fattura
resta inalterata. Questa è una situazione che richiede una rettifica
formale (nota di credito, fattura supplementare), non un edit silente.

Il guard centralizza la verifica e ritorna lo slice "colpevole" (per
errori dettagliati con period + invoice number). Viene applicato in:
  - router planning: tutti gli endpoint che modificano booking esistenti
  - service ai_assistant: handler tool_use propose_move/resize/delete

Invariante: se un booking è coperto da N slice diverse, ne ritorniamo
una qualsiasi (la prima trovata) — basta una per dichiarare il blocco.

Differenza rispetto ad α.51.1 fix A2 (`_assert_jcl_not_locked`): quello
blocca su `JCLBillingStatus in (in_batch, billed, paid)` indipendentemente
dal periodo. Lo slice-guard è più granulare: una JCL già `billed` può
avere nuovo lavoro in periodi successivi, e quel lavoro deve restare
editabile fino a che non viene anch'esso slice-ato. Il check
JCLBillingStatus resta utile per il caso `in_batch` (batch in approvazione,
nessuno slice esiste ancora).
"""
from __future__ import annotations

from typing import Optional, Tuple
from datetime import date

from sqlalchemy.orm import Session

from app.models import Booking, JCLBilledSlice


def find_blocking_slice(db: Session, booking: Booking) -> Optional[JCLBilledSlice]:
    """Ritorna la prima `JCLBilledSlice` il cui [period_start, period_end]
    si sovrappone all'intervallo `[booking.start_datetime.date(),
    booking.end_datetime.date()]`. None se nessuna sovrapposizione.

    Se il booking non ha `job_cost_line_id`, ritorna None (non vincolato
    a fatturazione).
    """
    if not booking.job_cost_line_id:
        return None
    if not booking.start_datetime or not booking.end_datetime:
        return None
    b_start = booking.start_datetime.date()
    b_end = booking.end_datetime.date()
    return _find_slice_for_jcl_period(db, booking.job_cost_line_id, b_start, b_end)


def find_blocking_slice_for_dates(
    db: Session,
    job_cost_line_id: Optional[int],
    start: date,
    end: date,
) -> Optional[JCLBilledSlice]:
    """Variante per controlli pre-save (booking ancora non persistito o
    nuove date proposte da un move). `start`/`end` sono le date risultanti
    DOPO l'edit. Se non c'è JCL, niente lock."""
    if not job_cost_line_id:
        return None
    return _find_slice_for_jcl_period(db, job_cost_line_id, start, end)


def _find_slice_for_jcl_period(
    db: Session, jcl_id: int, start: date, end: date,
) -> Optional[JCLBilledSlice]:
    return (
        db.query(JCLBilledSlice)
        .filter(
            JCLBilledSlice.job_cost_line_id == jcl_id,
            JCLBilledSlice.period_start <= end,
            JCLBilledSlice.period_end >= start,
        )
        .order_by(JCLBilledSlice.period_start.asc())
        .first()
    )


def slice_lock_message(slice_: JCLBilledSlice) -> str:
    """Messaggio standard per HTTPException(409) o ValueError."""
    invoice_label = ""
    if slice_.invoice and slice_.invoice.number:
        invoice_label = f" (fattura {slice_.invoice.number})"
    return (
        f"Booking dentro periodo già fatturato "
        f"[{slice_.period_start.isoformat()} → {slice_.period_end.isoformat()}]"
        f"{invoice_label}. Per correzioni formali usa l'endpoint di rettifica "
        f"o cancella la fattura."
    )


def slice_lock_payload(slice_: JCLBilledSlice) -> dict:
    """Payload JSON per response 409 — UI lo usa per popolare la modale di
    rettifica."""
    return {
        "slice_id": slice_.id,
        "period_start": slice_.period_start.isoformat(),
        "period_end": slice_.period_end.isoformat(),
        "invoice_id": slice_.invoice_id,
        "invoice_number": (
            slice_.invoice.number if slice_.invoice else None
        ),
        "billed_amount": slice_.billed_amount,
    }


# v3.5.0-alpha.60 — aggregati slice per il cost report 3 colonne ────────

def billed_locked_for_jcl(db: Session, jcl_id: int) -> float:
    """Σ `billed_amount` di tutte le slice della JCL. È l'importo
    "chiuso in fattura": immutabile, non più variabile per backedit."""
    if not jcl_id:
        return 0.0
    rows = (
        db.query(JCLBilledSlice.billed_amount)
        .filter(JCLBilledSlice.job_cost_line_id == jcl_id)
        .all()
    )
    return round(sum((r[0] or 0.0) for r in rows), 2)


def billed_locked_bulk(db: Session, jcl_ids) -> dict:
    """Variante bulk: ritorna dict {jcl_id: Σ billed_amount}.
    Singola query per evitare N+1 nel cost report (tipicamente 10-50 JCL
    per job)."""
    jcl_ids = list(set(jcl_ids or []))
    if not jcl_ids:
        return {}
    from sqlalchemy import func as _f
    rows = (
        db.query(
            JCLBilledSlice.job_cost_line_id,
            _f.coalesce(_f.sum(JCLBilledSlice.billed_amount), 0.0),
        )
        .filter(JCLBilledSlice.job_cost_line_id.in_(jcl_ids))
        .group_by(JCLBilledSlice.job_cost_line_id)
        .all()
    )
    return {row[0]: round(row[1] or 0.0, 2) for row in rows}


def three_column_view(jcl, billed_locked: float) -> dict:
    """Calcola le 3 colonne cost report per una JobCostLine:

    - **billed_locked**: Σ slice.billed_amount (chiuso in fattura,
      immutabile). Passato come parametro per evitare N+1 (chiamante
      pre-fetcha via `billed_locked_bulk`).
    - **accrued_post_period**: maturato eccedente il già fatturato.
      = max(0, total_accrued − billed_locked). Rappresenta le ore done
      ancora non slice-ate, prossima candidata alla fatturazione.
    - **forecast_future**: stima ulteriori ore ancora da lavorare.
      = max(0, total_expected − total_accrued).

    Note di consistenza:
    - Σ delle 3 = total_expected (quando forecast > accrued).
    - billed_locked + accrued_post_period = total_accrued (= over_under_now).
    - billed_locked + accrued_post_period + forecast_future = total_expected.
    """
    accrued = jcl.total_accrued or 0.0
    expected = jcl.total_expected or 0.0
    accrued_post_period = max(0.0, round(accrued - billed_locked, 2))
    forecast_future = max(0.0, round(expected - accrued, 2))
    return {
        "billed_locked": round(billed_locked, 2),
        "accrued_post_period": accrued_post_period,
        "forecast_future": forecast_future,
    }
