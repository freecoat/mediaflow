"""Media Library — azioni mutanti (Fase B). Read-write, tenant-scoped.
Riusa deliverable_assets.link_asset/unlink_asset come fonte di verità dei
link. Nessuna funzione committa (commit gestito dal router)."""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from app.models.models import (
    Asset, PhysicalAsset, JobDeliverable, DeliverableAsset,
    DeliverableStatus, now_utc,
)
from app.context import current_tenant_id
from app.services.rbac import is_admin
from app.services.project_access import accessible_project_ids
from app.services.deliverable_assets import link_asset, unlink_asset

# Stati consegna "avanzati" da cui un supersede fa tornare indietro a in_progress.
_REOPEN_FROM = {DeliverableStatus.qc, DeliverableStatus.delivered, DeliverableStatus.closed}


class MediaActionError(Exception):
    """Errore applicativo (entità mancante / non accessibile / input invalido)."""


def _get_deliverable(db: Session, user, deliverable_id: int) -> JobDeliverable:
    jd = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
        JobDeliverable.deleted_at.is_(None),
    ).first()
    if not jd:
        raise MediaActionError("Consegna non trovata")
    if not is_admin(user) and jd.job_id is not None:
        # visibilità: la consegna appartiene a un job del progetto accessibile
        from app.models.models import Job
        job = db.get(Job, jd.job_id)
        if job and job.project_id and job.project_id not in accessible_project_ids(user, db):
            raise MediaActionError("Consegna non accessibile")
    return jd


def _active_link_same_nature(db: Session, jd: JobDeliverable, nature: str) -> Optional[DeliverableAsset]:
    q = db.query(DeliverableAsset).filter(
        DeliverableAsset.job_deliverable_id == jd.id,
        DeliverableAsset.superseded_at.is_(None),
    )
    if nature == "digital":
        q = q.filter(DeliverableAsset.asset_id.isnot(None))
    else:
        q = q.filter(DeliverableAsset.physical_asset_id.isnot(None))
    return q.order_by(DeliverableAsset.confirmed_at.desc(), DeliverableAsset.id.desc()).first()


def associate(db: Session, user, *, deliverable_id: int, items: list, reason: Optional[str] = None) -> dict:
    jd = _get_deliverable(db, user, deliverable_id)
    linked = superseded = 0
    for it in items or []:
        nature = it.get("nature")
        aid = int(it.get("id"))
        if nature not in ("digital", "physical"):
            continue
        prev = _active_link_same_nature(db, jd, nature)
        if nature == "digital":
            new_link = link_asset(db, jd, asset_id=aid, source="manual", user_id=user.id, notes=reason)
        else:
            new_link = link_asset(db, jd, physical_asset_id=aid, source="manual", user_id=user.id, notes=reason)
        linked += 1
        # supersede: c'era un attivo DIVERSO della stessa natura
        if prev is not None and prev.id != new_link.id:
            prev.superseded_at = now_utc()
            prev.superseded_by_id = new_link.id
            prev.supersede_reason = reason
            superseded += 1
    status_reset = False
    if superseded and jd.status in _REOPEN_FROM:
        jd.status = DeliverableStatus.in_progress
        jd.qc_substatus = None
        status_reset = True
        _notify_reopen(db, jd, user, reason)
    db.flush()
    return {"linked": linked, "superseded": superseded, "status_reset": status_reset}


def _notify_reopen(db, jd, user, reason):
    try:
        from app.services.notifications import notify_permission
        body = f"Consegna '{jd.name}' riaperta: asset superseduto in Media Library."
        if reason:
            body += f"\n\nMotivo: {reason}"
        notify_permission(
            db, permission="view_finance",
            kind="deliverable_reopened_supersede", severity="action_required",
            title=f"Consegna riaperta — {jd.name[:60]}", body=body,
            link=f"/cost-report#job-{jd.job_id}",
            payload={"deliverable_id": jd.id, "job_id": jd.job_id},
            actor_user_id=user.id, tenant_id=jd.tenant_id, commit=False,
        )
    except Exception as e:
        print(f"[media_actions] notify reopen failed (non bloccante): {e}")
