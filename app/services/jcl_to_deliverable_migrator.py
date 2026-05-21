"""v3.5.0-alpha.172.9 (Sprint 5 T1+T2) — Runtime tool migrate JCL non-time → JobDeliverable.

Lo script `scripts/migrate_restructure_phase1.py` fa backfill one-shot al boot
post-pull. Questo modulo espone le stesse semantiche come SERVICE callabile
runtime, per casi:
- Quote storiche non migrate al primo run
- Voci aggiunte manualmente con unit non-time-based (regression)
- Admin che vede notifica `legacy_jcl_non_time` e clicca "Migra ora"

API:
- `scan_legacy_jcl(db)` → lista JCL non-time-based attive (tenant-scoped)
- `migrate_jcl_to_deliverable(db, jcl_id)` → migra UNA JCL (idempotente)
- `migrate_all_legacy(db)` → migra tutte le JCL legacy nel tenant
- `notify_admins_if_legacy(db)` → emette notifica `legacy_jcl_non_time`
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.models import (
    JobCostLine, JobDeliverable, Booking, BookingDeliverable,
    DeliverableUnitNature, DeliverableBillingStatus, DeliverableNature,
    DeliverableStatus, NotificationKind, NotificationSeverity,
)
from app.services.cost_line_sync import unit_nature_for, is_time_based_unit
from app.context import current_tenant_id

log = logging.getLogger(__name__)


def scan_legacy_jcl(db: Session, tenant_id: Optional[int] = None) -> list[dict]:
    """Lista JCL con unit NON time-based (= candidate per migrazione).

    Esclude JCL il cui JobDeliverable autospawnato esiste già (idempotenza).
    """
    tid = tenant_id or current_tenant_id()
    rows = (
        db.query(JobCostLine)
        .filter(JobCostLine.tenant_id == tid)
        .all()
    )
    out: list[dict] = []
    for jcl in rows:
        unit = (jcl.unit or "").strip().lower()
        if is_time_based_unit(unit):
            continue
        # Skip se autospawn JobDeliverable esiste già
        already = db.query(JobDeliverable).filter(
            JobDeliverable.job_cost_line_id == jcl.id
        ).first()
        if already:
            continue
        out.append({
            "jcl_id": jcl.id,
            "job_id": jcl.job_id,
            "description": jcl.description,
            "unit": unit,
            "quantity_quoted": jcl.quantity_quoted,
            "unit_price": jcl.unit_price,
            "total_quoted": jcl.total_quoted,
            "external_outsourced": bool(getattr(jcl, "external_outsourced", False)),
        })
    return out


def migrate_jcl_to_deliverable(db: Session, jcl_id: int) -> dict:
    """Migra una JCL non-time-based a 1+ JobDeliverable.

    Idempotente: se esiste già JobDeliverable linkato a questa JCL, ritorna
    `{"migrated": False, "reason": "already_migrated"}`.

    Ritorna `{"migrated": True, "deliverable_ids": [...], "bookings_linked": N}`.
    """
    jcl = db.query(JobCostLine).filter(JobCostLine.id == jcl_id).first()
    if not jcl:
        return {"migrated": False, "reason": "not_found"}
    unit = (jcl.unit or "").strip().lower()
    if is_time_based_unit(unit):
        return {"migrated": False, "reason": "is_time_based"}
    existing = db.query(JobDeliverable).filter(
        JobDeliverable.job_cost_line_id == jcl.id
    ).first()
    if existing:
        return {"migrated": False, "reason": "already_migrated",
                "existing_deliverable_id": existing.id}

    external = bool(getattr(jcl, "external_outsourced", False))
    nature_str = "manual_allow" if external else unit_nature_for(unit)
    unit_eff = "lump" if external else unit
    qty_raw = float(jcl.quantity_quoted or 0.0)
    # v3.5.0-alpha.172.14 — Spawn rule:
    # external/manual_allow/deliverable_volume → 1 row aggregato.
    # deliverable_qty (pc/lot/shot/version) → N row, 1 per unità.
    if external or nature_str in ("manual_allow", "deliverable_volume"):
        n_rows = 1
        per_row_qty = qty_raw if qty_raw > 0 else 1.0
    else:
        # deliverable_qty
        n_rows = max(1, int(round(qty_raw)))
        per_row_qty = 1.0

    new_ids: list[int] = []
    up = float(jcl.unit_price or 0.0)
    qa_total = float(jcl.quantity_actual or 0.0)
    qa_int = round(qa_total)
    aggregated = (n_rows == 1)  # external O volume O manual_allow
    for idx in range(n_rows):
        if aggregated:
            # 1 row → tutto il qty_actual va qui (cap a per_row_qty)
            qty_done = min(qa_total, per_row_qty) if per_row_qty > 0 else qa_total
        else:
            # N row deliverable_qty → 1 per unità completata
            qty_done = 1.0 if idx < qa_int else 0.0
        d = JobDeliverable(
            tenant_id=jcl.tenant_id,
            job_id=jcl.job_id,
            job_cost_line_id=jcl.id,
            quote_line_id=jcl.quote_line_id,
            price_item_id=jcl.price_item_id,
            name=jcl.description or f"Deliverable {idx + 1}",
            unit=unit_eff,
            unit_price=up,
            unit_nature=DeliverableUnitNature(nature_str),
            quantity_planned=per_row_qty,
            quantity_delivered=qty_done,
            total_quoted=round(per_row_qty * up, 2),
            total_accrued=round(qty_done * up, 2),
            total_cost_accrued=0.0,
            nature=DeliverableNature.digital,
            status=DeliverableStatus.delivered if qty_done > 0 else DeliverableStatus.planned,
            billing_status=DeliverableBillingStatus.not_billed,
        )
        db.add(d)
        db.flush()
        new_ids.append(d.id)

    # Cascade booking.job_cost_line_id → booking_deliverables pivot (primary).
    bookings_linked = 0
    if new_ids:
        primary_did = new_ids[0]
        bks = db.query(Booking).filter(Booking.job_cost_line_id == jcl.id).all()
        for b in bks:
            already_link = db.query(BookingDeliverable).filter(
                BookingDeliverable.booking_id == b.id,
                BookingDeliverable.job_deliverable_id == primary_did,
            ).first()
            if already_link:
                continue
            db.add(BookingDeliverable(
                booking_id=b.id,
                job_deliverable_id=primary_did,
                sort_order=0,
            ))
            bookings_linked += 1

    # Azzera maturato JCL: cost_line_sync sprint 2 lo fa di default per non-time,
    # ma qui esplicito per essere safe se chiamato fuori dal sync.
    jcl.quantity_actual = 0.0
    jcl.total_accrued = 0.0
    jcl.total_expected = 0.0
    jcl.total_cost_accrued = 0.0
    db.flush()

    log.info(
        "[jcl_to_deliverable] JCL #%d (unit=%s, qty=%s) → %d JobDeliverable, %d booking linked",
        jcl.id, unit, jcl.quantity_quoted, len(new_ids), bookings_linked,
    )
    return {
        "migrated": True,
        "jcl_id": jcl.id,
        "deliverable_ids": new_ids,
        "bookings_linked": bookings_linked,
        "external_outsourced": external,
    }


def migrate_all_legacy(db: Session, tenant_id: Optional[int] = None) -> dict:
    """Migra TUTTE le JCL legacy non-time del tenant.

    Wrap di `migrate_jcl_to_deliverable` su `scan_legacy_jcl`. Ritorna summary
    aggregato `{migrated, skipped, deliverables_spawned, bookings_linked}`.
    """
    candidates = scan_legacy_jcl(db, tenant_id=tenant_id)
    summary = {
        "candidates": len(candidates),
        "migrated": 0,
        "skipped": 0,
        "deliverables_spawned": 0,
        "bookings_linked": 0,
        "errors": [],
    }
    for c in candidates:
        try:
            res = migrate_jcl_to_deliverable(db, c["jcl_id"])
            if res.get("migrated"):
                summary["migrated"] += 1
                summary["deliverables_spawned"] += len(res.get("deliverable_ids", []))
                summary["bookings_linked"] += res.get("bookings_linked", 0)
            else:
                summary["skipped"] += 1
        except Exception as e:
            summary["errors"].append({"jcl_id": c["jcl_id"], "error": str(e)})
            log.exception("migrate_jcl_to_deliverable failed for #%d", c["jcl_id"])
    return summary


def notify_admins_if_legacy(db: Session, tenant_id: Optional[int] = None) -> dict:
    """Scan + se trova JCL legacy, emette notifica `legacy_jcl_non_time`.

    Idempotenza: non rilancia notifica se esiste già una unread con stesso kind
    nel tenant (evita spam). Usata da cron `cr_eom_review` pattern o post-boot.
    """
    from app.services.notifications import notify_permission
    from app.models import Notification
    candidates = scan_legacy_jcl(db, tenant_id=tenant_id)
    if not candidates:
        return {"notified": False, "reason": "no_legacy_jcl", "count": 0}
    # Idempotenza: già notificato e unread?
    tid = tenant_id or current_tenant_id()
    existing = db.query(Notification).filter(
        Notification.tenant_id == tid,
        Notification.kind == NotificationKind.legacy_jcl_non_time.value,
        Notification.read_at.is_(None),
    ).first()
    if existing:
        return {"notified": False, "reason": "already_pending", "count": len(candidates)}
    n_jobs = len({c["job_id"] for c in candidates})
    notify_permission(
        db,
        permission="hard_delete_project",  # admin-only key (proxy for admin role)
        kind=NotificationKind.legacy_jcl_non_time.value,
        severity=NotificationSeverity.action_required.value,
        title=f"{len(candidates)} JCL residuali da migrare a Deliverable",
        body=(
            f"Trovate {len(candidates)} JobCostLine con unit non time-based "
            f"(es. pc/TB/lump/allow) su {n_jobs} job. Queste voci dovrebbero "
            f"essere JobDeliverable per il workflow restructure 2026-05-20. "
            f"Apri /admin/restructure-migration per migrarle in batch o singolarmente."
        ),
        link="/admin/restructure-migration",
        payload={"candidates_count": len(candidates), "jobs_count": n_jobs},
    )
    return {"notified": True, "count": len(candidates), "jobs": n_jobs}
