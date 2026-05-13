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
            # v3.5.0-alpha.111 — slice stornate (TD04) non bloccano più
            JCLBilledSlice.voided_at.is_(None),
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
        .filter(
            JCLBilledSlice.job_cost_line_id == jcl_id,
            JCLBilledSlice.voided_at.is_(None),
        )
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
        .filter(
            JCLBilledSlice.job_cost_line_id.in_(jcl_ids),
            JCLBilledSlice.voided_at.is_(None),
        )
        .group_by(JCLBilledSlice.job_cost_line_id)
        .all()
    )
    return {row[0]: round(row[1] or 0.0, 2) for row in rows}


def maybe_notify_extra_after_billed(db: Session, jcl) -> bool:
    """v3.5.0-alpha.61 — Se la JCL ha almeno una slice E un maturato
    eccedente il già fatturato, emette notifica `extra_after_billed`.

    Idempotente in modo conservativo: non rinotifica se esiste già una
    notifica `extra_after_billed` non archiviata per la stessa JCL. La
    nuova notifica viene emessa solo dopo che quella precedente è stata
    archiviata (o passata `cleanup_old` 90gg).

    Destinatari: ruoli `admin`, `manager`, `producer`, `accounting` —
    chi gestisce billing e chi pianifica il lavoro vedono insieme
    l'allerta in tempo reale.

    Ritorna True se ha emesso, False se nessuna azione (no slice, no
    extra, già notificato).
    """
    if jcl is None or not jcl.id:
        return False
    accrued = jcl.total_accrued or 0.0
    billed = billed_locked_for_jcl(db, jcl.id)
    extra = round(accrued - billed, 2)
    if extra <= 0.001:
        return False
    # Verifica esistenza slice (extra esiste solo se c'è anche solo una
    # slice già emessa — altrimenti è semplice maturato non ancora
    # trasmesso, niente di anomalo).
    has_slice = (
        db.query(JCLBilledSlice)
        .filter(JCLBilledSlice.job_cost_line_id == jcl.id)
        .first()
        is not None
    )
    if not has_slice:
        return False
    # Dedup: cerca notifiche extra_after_billed non archiviate per questa JCL.
    from app.models import Notification, NotificationKind, NotificationSeverity
    from sqlalchemy import cast
    from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
    existing = (
        db.query(Notification.id)
        .filter(
            Notification.kind == NotificationKind.extra_after_billed.value,
            Notification.is_archived == False,  # noqa: E712
        )
        .all()
    )
    # Filtraggio in-memory perché payload è JSON e SQLAlchemy/SQLite non offre
    # operatori JSON portabili. Lista corta (qualche decina al massimo).
    if existing:
        ids = [e[0] for e in existing]
        rows = db.query(Notification).filter(Notification.id.in_(ids)).all()
        for r in rows:
            try:
                if (r.payload or {}).get("jcl_id") == jcl.id:
                    return False  # già notificato, skip
            except Exception:
                pass

    # Risali a project / job per il link
    from app.models import JobCostLine, Job
    full = (
        db.query(JobCostLine).filter(JobCostLine.id == jcl.id).first()
    )
    job = full.job if full else None
    project = job.project if (job and job.project_id) else None
    project_label = (project.title if project else (job.title if job else "?"))
    link = f"/cost-report#job-{job.id}" if job else "/cost-report"
    title = f"⚠ Extra emerso su progetto fatturato: {project_label}"
    body = (
        f"Riga `{full.description}` ha {extra:.2f}€ di lavoro maturato "
        f"oltre il già fatturato (€{billed:.2f}). Considera trasmissione "
        f"a fatturazione o coordinamento col commerciale."
    )
    payload = {
        "jcl_id": jcl.id,
        "job_id": job.id if job else None,
        "project_id": project.id if project else None,
        "billed_locked": billed,
        "extra_amount": extra,
    }
    from app.services import notifications as notif_svc
    notif_svc.notify_role(
        db,
        role_codes=["admin", "manager", "producer", "accounting"],
        kind=NotificationKind.extra_after_billed.value,
        severity=NotificationSeverity.action_required.value,
        title=title,
        body=body,
        link=link,
        payload=payload,
    )
    return True


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
