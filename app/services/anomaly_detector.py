"""Anomaly detector — v3.5.0-alpha.89 sprint S4.

Scanner idempotente che popola la tabella `anomaly_entries` dai dati
esistenti (JCL, Invoice, JCLBilledSlice). Riusa la logica già presente
nei vecchi endpoint `/finance/api/anomalies/*` ma li rende stateful:
ogni anomalia rilevata diventa un record gestibile (open/handled/dismissed).

Idempotenza: `dedup_key = "{type}:{source_kind}:{source_id}"` UNIQUE per
tenant. Re-scan aggiorna `last_seen_at` e `amount` se cambiati, ma non
duplica. Anomalie già chiuse (handled/dismissed) non vengono riaperte
automaticamente — l'operatore può forzare reopen via endpoint dedicato.

Trigger detect: chiamata manuale via `POST /finance/api/anomalies/detect`,
oppure invocato da hook (es. dopo emit invoice → rileva extra_after_billed).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models import (
    AnomalyAction,  # noqa: F401 (re-exported)
    AnomalyEntry,
    AnomalySourceKind,
    AnomalyStatus,
    AnomalyType,
    Invoice,
    InvoiceStatus,
    JCLBilledSlice,
    Job,
    JobCostLine,
    JobStatus,
)

CURRENT_TENANT = 1


def _upsert(
    db: Session,
    *,
    anomaly_type: AnomalyType,
    source_kind: AnomalySourceKind,
    source_id: int,
    description: str,
    amount: float,
    project_id: Optional[int] = None,
    job_id: Optional[int] = None,
    client_id: Optional[int] = None,
) -> AnomalyEntry:
    """Upsert idempotente per (tipo, source). Crea se nuovo, aggiorna
    last_seen_at + amount + description se esistente. Status non viene
    mai toccato (rispetta le decisioni operatore)."""
    dedup_key = f"{anomaly_type.value}:{source_kind.value}:{source_id}"
    existing = (
        db.query(AnomalyEntry)
        .filter(
            AnomalyEntry.tenant_id == CURRENT_TENANT,
            AnomalyEntry.dedup_key == dedup_key,
        )
        .first()
    )
    now = datetime.utcnow()
    if existing:
        existing.last_seen_at = now
        existing.amount = amount
        existing.description = description
        existing.project_id = project_id
        existing.job_id = job_id
        existing.client_id = client_id
        return existing
    entry = AnomalyEntry(
        tenant_id=CURRENT_TENANT,
        anomaly_type=anomaly_type,
        source_kind=source_kind,
        source_id=source_id,
        dedup_key=dedup_key,
        project_id=project_id,
        job_id=job_id,
        client_id=client_id,
        amount=amount,
        description=description,
        detected_at=now,
        last_seen_at=now,
        status=AnomalyStatus.open,
    )
    db.add(entry)
    return entry


def detect_extra_after_billed(db: Session) -> int:
    """JobCostLine con quantity_actual > slice billed_quantity (Σ slice) +
    extra recente: indica done emerso DOPO che la slice è stata fatturata.
    Già notificato da event 'extra_after_billed' in billing flow; qui lo
    persistiamo come anomalia gestibile."""
    n = 0
    # Subquery: somma quantity billata per JCL
    from sqlalchemy import func
    billed_by_jcl = (
        db.query(
            JCLBilledSlice.job_cost_line_id.label("jcl_id"),
            func.sum(JCLBilledSlice.billed_quantity).label("billed_qty"),
        )
        .filter(JCLBilledSlice.tenant_id == CURRENT_TENANT)
        .group_by(JCLBilledSlice.job_cost_line_id)
        .subquery()
    )
    rows = (
        db.query(JobCostLine, billed_by_jcl.c.billed_qty)
        .options(joinedload(JobCostLine.job).joinedload(Job.project))
        .join(billed_by_jcl, JobCostLine.id == billed_by_jcl.c.jcl_id)
        .filter(JobCostLine.tenant_id == CURRENT_TENANT)
        .filter(JobCostLine.quantity_actual > billed_by_jcl.c.billed_qty)
        .all()
    )
    for jcl, billed_qty in rows:
        delta_qty = (jcl.quantity_actual or 0) - (billed_qty or 0)
        delta_val = round(delta_qty * (jcl.unit_price or 0), 2)
        if delta_val <= 0:
            continue
        _upsert(
            db,
            anomaly_type=AnomalyType.extra_after_billed,
            source_kind=AnomalySourceKind.jcl,
            source_id=jcl.id,
            description=(
                f"JCL #{jcl.id} «{jcl.description[:60] if jcl.description else ''}»: "
                f"{delta_qty:.2f} {jcl.unit or ''} done dopo fatturazione (≈ €{delta_val:.2f})"
            ),
            amount=delta_val,
            project_id=jcl.job.project_id if jcl.job else None,
            job_id=jcl.job_id,
            client_id=jcl.job.client_id if jcl.job else None,
        )
        n += 1
    return n


def detect_sforamento(db: Session) -> int:
    """JobCostLine non-extra con quantity_actual > quantity_quoted."""
    n = 0
    rows = (
        db.query(JobCostLine)
        .options(joinedload(JobCostLine.job).joinedload(Job.project))
        .filter(JobCostLine.tenant_id == CURRENT_TENANT)
        .filter(JobCostLine.job_id.isnot(None))
        .filter(JobCostLine.is_extra == False)  # noqa: E712
        .filter(JobCostLine.quantity_actual > JobCostLine.quantity_quoted)
        .all()
    )
    for jcl in rows:
        delta_qty = (jcl.quantity_actual or 0) - (jcl.quantity_quoted or 0)
        delta_val = round(delta_qty * (jcl.unit_price or 0), 2)
        if delta_val <= 0:
            continue
        _upsert(
            db,
            anomaly_type=AnomalyType.sforamento_monte_ore,
            source_kind=AnomalySourceKind.jcl,
            source_id=jcl.id,
            description=(
                f"Sforamento JCL #{jcl.id}: +{delta_qty:.2f} {jcl.unit or ''} "
                f"({jcl.quantity_actual:.2f} vs {jcl.quantity_quoted:.2f} preventivati)"
            ),
            amount=delta_val,
            project_id=jcl.job.project_id if jcl.job else None,
            job_id=jcl.job_id,
            client_id=jcl.job.client_id if jcl.job else None,
        )
        n += 1
    return n


def detect_over_budget(db: Session) -> int:
    """JobCostLine extra puro (is_extra=True, no quote_line_id)."""
    n = 0
    rows = (
        db.query(JobCostLine)
        .options(joinedload(JobCostLine.job).joinedload(Job.project))
        .filter(JobCostLine.tenant_id == CURRENT_TENANT)
        .filter(JobCostLine.job_id.isnot(None))
        .filter(JobCostLine.is_extra == True)  # noqa: E712
        .all()
    )
    for jcl in rows:
        total = round(
            (jcl.quantity_actual or jcl.quantity_quoted or 0) * (jcl.unit_price or 0), 2
        )
        if total <= 0:
            continue
        _upsert(
            db,
            anomaly_type=AnomalyType.over_budget,
            source_kind=AnomalySourceKind.jcl,
            source_id=jcl.id,
            description=(
                f"Extra JCL #{jcl.id} «{jcl.description[:60] if jcl.description else ''}» "
                f"({jcl.quantity_actual or jcl.quantity_quoted} {jcl.unit or ''})"
            ),
            amount=total,
            project_id=jcl.job.project_id if jcl.job else None,
            job_id=jcl.job_id,
            client_id=jcl.job.client_id if jcl.job else None,
        )
        n += 1
    return n


def detect_mancato_recupero(db: Session) -> int:
    """Fatture attive scadute (due_date < oggi, status NOT IN paid/cancelled).
    Indica mancato recupero credito.

    v3.5.0-alpha.91 audit fix P1: deriva project_id da inv.job.project_id
    quando disponibile. Era sempre NULL → handle write_off_loss falliva con
    400 "write-off richiede project_id"."""
    n = 0
    today = date.today()
    rows = (
        db.query(Invoice)
        .options(
            joinedload(Invoice.client),
            joinedload(Invoice.job).joinedload(Job.project),
        )
        .filter(Invoice.tenant_id == CURRENT_TENANT)
        .filter(Invoice.due_date.isnot(None))
        .filter(Invoice.due_date < today)
        .filter(Invoice.status.notin_([InvoiceStatus.paid, InvoiceStatus.cancelled]))
        .all()
    )
    for inv in rows:
        amt = float(inv.total or 0)
        if amt <= 0:
            continue
        days_overdue = (today - inv.due_date).days
        _upsert(
            db,
            anomaly_type=AnomalyType.mancato_recupero,
            source_kind=AnomalySourceKind.invoice,
            source_id=inv.id,
            description=(
                f"Fattura {inv.number} scaduta da {days_overdue}gg "
                f"({inv.client.name if inv.client else 'cliente'})"
            ),
            amount=amt,
            project_id=(inv.job.project_id if inv.job else None),
            job_id=inv.job_id,
            client_id=inv.client_id,
        )
        n += 1
    return n


def detect_quote_discrepancy(db: Session, threshold_pct: float = 15.0) -> int:
    """Job con consuntivo (total_accrued) che divergeq dal budget quotato
    oltre soglia (default 15%). Indica errore di quotazione iniziale o
    scope creep significativo da segnalare al commerciale."""
    n = 0
    rows = (
        db.query(Job)
        .options(joinedload(Job.project), joinedload(Job.cost_lines))
        .filter(Job.tenant_id == CURRENT_TENANT)
        .filter(Job.status.in_([JobStatus.in_progress, JobStatus.completed]))
        .filter(Job.quote_id.isnot(None))
        .all()
    )
    for job in rows:
        budget = float(job.budget_quoted or 0)
        if budget <= 0:
            continue
        accrued = sum(
            (jcl.quantity_actual or 0) * (jcl.unit_price or 0)
            for jcl in (job.cost_lines or [])
        )
        if accrued <= 0:
            continue
        pct_diff = (accrued - budget) / budget * 100.0
        if abs(pct_diff) < threshold_pct:
            continue
        _upsert(
            db,
            anomaly_type=AnomalyType.quote_discrepancy,
            source_kind=AnomalySourceKind.job,
            source_id=job.id,
            description=(
                f"Job {job.code}: consuntivo €{accrued:.2f} vs quotato €{budget:.2f} "
                f"({pct_diff:+.1f}% — soglia ±{threshold_pct:.0f}%)"
            ),
            amount=abs(accrued - budget),
            project_id=job.project_id,
            job_id=job.id,
            client_id=job.client_id,
        )
        n += 1
    return n


def detect_all(db: Session) -> dict:
    """Esegue tutti i detector in sequenza. Ritorna conteggi per tipo.
    Idempotente: re-run su stesso dataset non duplica. Esegue commit unico
    a fine ciclo."""
    counts = {
        "extra_after_billed": detect_extra_after_billed(db),
        "sforamento_monte_ore": detect_sforamento(db),
        "over_budget": detect_over_budget(db),
        "mancato_recupero": detect_mancato_recupero(db),
        "quote_discrepancy": detect_quote_discrepancy(db),
    }
    db.commit()
    counts["total"] = sum(counts.values())
    return counts
