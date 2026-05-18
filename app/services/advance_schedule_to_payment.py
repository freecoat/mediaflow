"""Materializzazione QuoteAdvanceSchedule → AdvancePayment (v3.5.0-alpha.144).

Hook chiamato al converti quote→job: per ogni QuoteAdvanceSchedule della quote
crea un AdvancePayment(status=pending) + AdvancePaymentAllocation (mappa
quote_line_id → JCL.id via JCL.quote_line_id).

Compute scheduled_due_date da anchor + offset_days:
- quote_approved: today + offset
- project_start: job.start_date + offset (None se job non ha start_date)
- specific_date: schedule.due_date (offset ignorato)
- milestone: None (futuro, ProjectMilestone resolution)

Emette Notification kind="advance_pending" a tutti gli utenti del tenant con
permesso edit_invoices (admin/manager/accounting).

Idempotenza: skip schedule se esiste già un AP con quote_advance_schedule_id
== schedule.id (evita duplicati su re-converti).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import (
    AdvanceDueAnchor,
    AdvancePayment,
    AdvancePaymentAllocation,
    AdvancePaymentStatus,
    Job,
    JobCostLine,
    QuoteAdvanceAllocation,
    QuoteAdvanceSchedule,
    User,
)
from app.services.notifications import notify

import logging
log = logging.getLogger(__name__)


def _compute_due_date(schedule: QuoteAdvanceSchedule, job: Job, today: date) -> Optional[date]:
    anchor = schedule.due_anchor
    offset = schedule.due_offset_days or 0
    if anchor == AdvanceDueAnchor.quote_approved:
        return today + timedelta(days=offset)
    if anchor == AdvanceDueAnchor.project_start:
        if job.start_date:
            return job.start_date + timedelta(days=offset)
        return today + timedelta(days=offset)  # fallback
    if anchor == AdvanceDueAnchor.specific_date:
        return schedule.due_date
    if anchor == AdvanceDueAnchor.milestone:
        return None  # futuro: ProjectMilestone resolution
    return None


def _compute_amount(schedule: QuoteAdvanceSchedule, quote_total: float) -> float:
    """amount_fixed prevale su pct. amount_fixed→cifra esplicita.
    pct → pct × quote_total_after_discount (imponibile)."""
    if schedule.amount_fixed and schedule.amount_fixed > 0:
        return round(schedule.amount_fixed, 2)
    if schedule.pct and schedule.pct > 0:
        return round((quote_total or 0) * schedule.pct, 2)
    return 0.0


def _resolve_jcl_for_quote_line(db: Session, job_id: int, quote_line_id: int) -> Optional[JobCostLine]:
    return db.query(JobCostLine).filter(
        JobCostLine.job_id == job_id,
        JobCostLine.quote_line_id == quote_line_id,
    ).first()


def _admin_user_ids(db: Session, tenant_id: int) -> list[int]:
    """Utenti tenant con ruolo admin/manager/accounting (destinatari notifica
    advance_pending). Filtra is_active."""
    from app.models import UserRole
    rows = db.query(User.id).filter(
        User.tenant_id == tenant_id,
        User.is_active == True,  # noqa: E712
        User.role.in_([UserRole.admin, UserRole.manager]),
    ).all()
    return [r[0] for r in rows]


def materialize_schedules(
    db: Session,
    quote,
    job: Job,
    user_id: Optional[int],
    tenant_id: int,
) -> dict:
    """Per ogni QuoteAdvanceSchedule della quote:
    - skip se già materializzato (idempotente)
    - crea AdvancePayment(status=pending, no invoice yet)
    - crea AdvancePaymentAllocation per ogni QuoteAdvanceAllocation della schedule
    - emette Notification advance_pending a admin/manager/accounting

    Ritorna: {created: [ap_dicts], skipped: N, notified: N_users}.
    """
    schedules = db.query(QuoteAdvanceSchedule).filter(
        QuoteAdvanceSchedule.quote_id == quote.id,
        QuoteAdvanceSchedule.tenant_id == tenant_id,
    ).order_by(QuoteAdvanceSchedule.sort_order.asc()).all()
    if not schedules:
        return {"created": [], "skipped": 0, "notified": 0}

    today = date.today()
    quote_total = quote.total_after_discount or 0
    created: list[dict] = []
    skipped = 0
    new_ap_ids: list[int] = []

    for sched in schedules:
        # Idempotenza
        existing = db.query(AdvancePayment).filter(
            AdvancePayment.tenant_id == tenant_id,
            AdvancePayment.quote_advance_schedule_id == sched.id,
        ).first()
        if existing:
            skipped += 1
            continue

        amount = _compute_amount(sched, quote_total)
        if amount <= 0:
            log.warning(f"[materialize_schedules] schedule #{sched.id} amount=0, skip")
            skipped += 1
            continue

        due = _compute_due_date(sched, job, today)
        ap = AdvancePayment(
            tenant_id=tenant_id,
            project_id=job.project_id,
            invoice_id=None,
            amount=amount,
            balance_remaining=amount,
            status=AdvancePaymentStatus.pending,
            quote_advance_schedule_id=sched.id,
            scheduled_due_date=due,
            label=sched.label,
            notes=sched.notes,
            created_by_user_id=user_id,
        )
        db.add(ap)
        db.flush()
        new_ap_ids.append(ap.id)

        # v3.5.0-alpha.166 — Materialize con preset "fill_sequential":
        # alloc.amount = min(JCL.total_quoted, remaining), itera in ordine di
        # qa.id (= ordine inserimento UI / quote_line_id ASC), ultima parziale.
        # `pct` su QuoteAdvanceAllocation viene IGNORATO (semantica chiarita
        # post-α.166: vince l'amount calcolato dal preset). Per acconti con
        # copertura specifica per riga, utente edita post-materialize via UI.
        q_allocs = db.query(QuoteAdvanceAllocation).filter(
            QuoteAdvanceAllocation.schedule_id == sched.id,
        ).order_by(QuoteAdvanceAllocation.id.asc()).all()
        remaining = amount
        for idx, qa in enumerate(q_allocs):
            jcl = _resolve_jcl_for_quote_line(db, job.id, qa.quote_line_id)
            if not jcl:
                log.warning(f"[materialize_schedules] no JCL for QuoteLine #{qa.quote_line_id} in job #{job.id}")
                continue
            jcl_q = jcl.total_quoted or 0.0
            take = round(min(jcl_q, remaining), 2)
            if take < 0:
                take = 0.0
            ap_alloc = AdvancePaymentAllocation(
                advance_payment_id=ap.id,
                job_cost_line_id=jcl.id,
                amount=take,
                sort_order=idx,
                # pct ricalcolato auto da listener pre-insert
            )
            db.add(ap_alloc)
            remaining = round(remaining - take, 2)
            if remaining <= 0:
                remaining = 0.0
        if remaining > 0.01:
            log.warning(
                f"[materialize_schedules] AP #{ap.id} residuo non allocato: "
                f"{remaining} (AP.amount={amount} > Σ JCL quoted coperte)"
            )

        created.append({
            "advance_payment_id": ap.id,
            "schedule_id": sched.id,
            "label": sched.label,
            "amount": amount,
            "due_date": due.isoformat() if due else None,
            "allocations": len(q_allocs),
        })

    # Notifica admin/manager/accounting
    notified = 0
    if new_ap_ids:
        admin_ids = _admin_user_ids(db, tenant_id)
        if admin_ids:
            body_parts = [
                f"Quote {quote.number} approvata su progetto {job.code}.",
                f"{len(new_ap_ids)} acconto/i in attesa di emissione fattura:",
            ]
            for c in created:
                due_lbl = f" scad. {c['due_date']}" if c["due_date"] else ""
                body_parts.append(f"  • {c['label'] or '(senza label)'}: €{c['amount']:.2f}{due_lbl}")
            body_parts.append("\nApri /finance per emettere le fatture acconto.")
            notify(
                db,
                user_ids=admin_ids,
                kind="advance_pending",
                title=f"Acconti da emettere — {job.code}",
                body="\n".join(body_parts),
                severity="action_required",
                link="/finance#section-invoices",
                actor_user_id=user_id,
                tenant_id=tenant_id,
                commit=False,  # commit gestito dal caller
            )
            notified = len(admin_ids)

    return {
        "created": created,
        "skipped": skipped,
        "notified": notified,
    }
