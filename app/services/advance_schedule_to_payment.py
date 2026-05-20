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


def _resolve_deliverables_for_quote_line(db: Session, job_id: int, quote_line_id: int) -> list:
    """v3.5.0-alpha.172.3 Restructure — Restituisce TUTTI i JobDeliverable
    spawnati da una QuoteLine (1 row per qty unitaria, decisione restructure)."""
    from app.models import JobDeliverable
    return db.query(JobDeliverable).filter(
        JobDeliverable.job_id == job_id,
        JobDeliverable.quote_line_id == quote_line_id,
        JobDeliverable.deleted_at.is_(None),
    ).order_by(JobDeliverable.id.asc()).all()


def rebuild_ap_allocations_from_schedule(db: Session, ap, schedule) -> dict:
    """v3.5.0-alpha.172.3 — Re-materialize delle AP_allocation per un AP
    a partire dalle QuoteAdvanceAllocation correnti della schedule.

    Cancella allocations vecchie del AP (precondizione: il caller le ha gia
    droppate) e ricostruisce fill_sequential su JCL + Deliverable parallel.

    Per ogni QuoteAdvanceAllocation:
    - se la QuoteLine matcha una JCL (unit time-based) -> AdvancePaymentAllocation
    - se matcha N Deliverable (unit non-time, 1 row per qty) -> N
      AdvancePaymentDeliverableAllocation con amount pro-quota su total_quoted

    Caller è responsabile del commit e di chiamare con AP in stato editabile
    (pending/draft/confirmed). AP invoiced/paid/consumed non rallocabili
    (servirebbe nota credito).
    """
    from app.models import (
        AdvancePaymentAllocation, AdvancePaymentDeliverableAllocation,
        QuoteAdvanceAllocation,
    )

    job = db.query(Job).filter(Job.id == ap.project_id).first()  # placeholder
    # Job vero deriva da: AP.project_id -> Project.jobs[0] (può essere multi).
    # Recupera tramite quote_advance_schedule_id -> quote_id -> Quote.job.
    from app.models import Quote as _Q
    q = db.query(_Q).filter(_Q.id == schedule.quote_id).first()
    if q and q.job:
        job = q.job
    if not job:
        log.warning(f"[rebuild_ap_allocations] AP #{ap.id} no job linked, skip")
        return {"jcl_allocs": 0, "deliverable_allocs": 0}

    q_allocs = db.query(QuoteAdvanceAllocation).filter(
        QuoteAdvanceAllocation.schedule_id == schedule.id,
    ).order_by(QuoteAdvanceAllocation.id.asc()).all()
    if not q_allocs:
        return {"jcl_allocs": 0, "deliverable_allocs": 0}

    remaining = float(ap.amount or 0.0)
    jcl_allocs = 0
    deliv_allocs = 0
    sort_idx = 0

    for qa in q_allocs:
        if remaining <= 0:
            break
        # Time-based ramo: JCL singolo
        jcl = _resolve_jcl_for_quote_line(db, job.id, qa.quote_line_id)
        if jcl is not None:
            jcl_q = float(jcl.total_quoted or 0.0)
            take = round(min(jcl_q, remaining), 2)
            if take <= 0:
                continue
            db.add(AdvancePaymentAllocation(
                advance_payment_id=ap.id,
                job_cost_line_id=jcl.id,
                amount=take,
                sort_order=sort_idx,
            ))
            jcl_allocs += 1
            sort_idx += 1
            remaining = round(remaining - take, 2)
            continue
        # Non-time ramo: N Deliverable per QuoteLine
        delivs = _resolve_deliverables_for_quote_line(db, job.id, qa.quote_line_id)
        for d in delivs:
            if remaining <= 0:
                break
            d_q = float(d.total_quoted or 0.0)
            take = round(min(d_q, remaining), 2)
            if take <= 0:
                continue
            db.add(AdvancePaymentDeliverableAllocation(
                advance_payment_id=ap.id,
                job_deliverable_id=d.id,
                amount=take,
                sort_order=sort_idx,
            ))
            deliv_allocs += 1
            sort_idx += 1
            remaining = round(remaining - take, 2)

    if remaining > 0.01:
        log.warning(
            f"[rebuild_ap_allocations] AP #{ap.id} residuo non allocato: {remaining} "
            f"(AP.amount={ap.amount}, Sigma coperture < amount)"
        )

    return {"jcl_allocs": jcl_allocs, "deliverable_allocs": deliv_allocs}


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
        # v3.5.0-alpha.172.3 Restructure — Branching JCL/Deliverable.
        from app.models import AdvancePaymentDeliverableAllocation
        q_allocs = db.query(QuoteAdvanceAllocation).filter(
            QuoteAdvanceAllocation.schedule_id == sched.id,
        ).order_by(QuoteAdvanceAllocation.id.asc()).all()
        remaining = amount
        sort_idx = 0
        for qa in q_allocs:
            if remaining <= 0:
                break
            # Time-based ramo: JCL singolo
            jcl = _resolve_jcl_for_quote_line(db, job.id, qa.quote_line_id)
            if jcl is not None:
                jcl_q = jcl.total_quoted or 0.0
                take = round(min(jcl_q, remaining), 2)
                if take <= 0:
                    continue
                db.add(AdvancePaymentAllocation(
                    advance_payment_id=ap.id,
                    job_cost_line_id=jcl.id,
                    amount=take,
                    sort_order=sort_idx,
                ))
                sort_idx += 1
                remaining = round(remaining - take, 2)
                continue
            # Non-time ramo: N Deliverable per QuoteLine (1 row per qty)
            delivs = _resolve_deliverables_for_quote_line(db, job.id, qa.quote_line_id)
            if not delivs:
                log.warning(
                    f"[materialize_schedules] no JCL/Deliverable for QuoteLine "
                    f"#{qa.quote_line_id} in job #{job.id}"
                )
                continue
            for d in delivs:
                if remaining <= 0:
                    break
                d_q = float(d.total_quoted or 0.0)
                take = round(min(d_q, remaining), 2)
                if take <= 0:
                    continue
                db.add(AdvancePaymentDeliverableAllocation(
                    advance_payment_id=ap.id,
                    job_deliverable_id=d.id,
                    amount=take,
                    sort_order=sort_idx,
                ))
                sort_idx += 1
                remaining = round(remaining - take, 2)
        if remaining > 0.01:
            log.warning(
                f"[materialize_schedules] AP #{ap.id} residuo non allocato: "
                f"{remaining} (AP.amount={amount} > Sigma coperture)"
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
