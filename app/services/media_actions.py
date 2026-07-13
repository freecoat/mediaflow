"""Media Library — azioni mutanti (Fase B). Read-write, tenant-scoped.
Riusa deliverable_assets.link_asset/unlink_asset come fonte di verità dei
link. Nessuna funzione committa (commit gestito dal router)."""
from __future__ import annotations
import csv as _csv
import io
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


def _lookup_asset(db: Session, nature: str, aid: int):
    """Asset (digital) o PhysicalAsset del tenant corrente, o None. Evita link
    cross-tenant: link_asset di per sé non valida l'ownership dell'asset."""
    model = Asset if nature == "digital" else PhysicalAsset
    return db.query(model).filter(
        model.id == aid, model.tenant_id == current_tenant_id()
    ).first()


def associate(db: Session, user, *, deliverable_id: int, items: list, reason: Optional[str] = None) -> dict:
    jd = _get_deliverable(db, user, deliverable_id)
    # Snapshot dei link attivi pre-esistenti per natura: vengono superseduti UNA
    # sola volta, e i nuovi link creati in QUESTA stessa call non si superseduno
    # a vicenda (senza snapshot, un secondo item della stessa natura troverebbe
    # il link appena creato dal primo e lo marcherebbe superseded).
    prev_by_nature = {
        "digital": _active_link_same_nature(db, jd, "digital"),
        "physical": _active_link_same_nature(db, jd, "physical"),
    }
    linked = superseded = 0
    for it in items or []:
        nature = it.get("nature")
        if nature not in ("digital", "physical"):
            continue
        try:
            aid = int(it.get("id"))
        except (TypeError, ValueError):
            continue  # item malformato: salta invece di 500
        # Validazione tenant/esistenza PRIMA di creare il link.
        if _lookup_asset(db, nature, aid) is None:
            raise MediaActionError(f"Asset {nature}:{aid} non trovato")
        if nature == "digital":
            new_link = link_asset(db, jd, asset_id=aid, source="manual", user_id=user.id, notes=reason)
        else:
            new_link = link_asset(db, jd, physical_asset_id=aid, source="manual", user_id=user.id, notes=reason)
        linked += 1
        # supersede: c'era un attivo pre-esistente DIVERSO della stessa natura.
        prev = prev_by_nature.get(nature)
        if prev is not None and prev.id != new_link.id:
            prev.superseded_at = now_utc()
            prev.superseded_by_id = new_link.id
            prev.supersede_reason = reason
            superseded += 1
            prev_by_nature[nature] = None  # consumato: supersede una sola volta
    status_reset = False
    if superseded and jd.status in _REOPEN_FROM:
        jd.status = DeliverableStatus.in_progress
        jd.qc_substatus = None
        status_reset = True
        _notify_reopen(db, jd, user, reason)
    db.flush()
    return {"linked": linked, "superseded": superseded, "status_reset": status_reset}


def set_flags(db: Session, user, items: list, *, internal_archive=None, delivered_external=None) -> dict:
    tid = current_tenant_id()
    updated = 0
    for it in items or []:
        nature = it.get("nature")
        model = Asset if nature == "digital" else PhysicalAsset if nature == "physical" else None
        if model is None:
            continue
        try:
            aid = int(it.get("id"))
        except (TypeError, ValueError):
            continue  # item malformato: salta invece di 500
        obj = db.query(model).filter(model.id == aid, model.tenant_id == tid).first()
        if not obj:
            continue
        if not is_admin(user):
            if obj.project_id is None or obj.project_id not in accessible_project_ids(user, db):
                continue
        if internal_archive is not None:
            obj.is_internal_archive = bool(internal_archive)
        if delivered_external is not None:
            obj.is_delivered_external = bool(delivered_external)
        updated += 1
    db.flush()
    return {"updated": updated}


def unlink(db: Session, user, *, deliverable_id: int, items: list) -> dict:
    jd = _get_deliverable(db, user, deliverable_id)
    removed = 0
    for it in items or []:
        nature = it.get("nature")
        if nature not in ("digital", "physical"):
            continue
        try:
            aid = int(it.get("id"))
        except (TypeError, ValueError):
            continue  # item malformato: salta invece di 500
        if nature == "digital":
            removed += unlink_asset(db, jd, asset_id=aid)
        else:
            removed += unlink_asset(db, jd, physical_asset_id=aid)
    db.flush()
    return {"removed": removed}


_CSV_COLUMNS = ["nature", "name", "type", "project_code", "client", "department",
                "delivery_status", "linked_to_delivery", "checksum", "size_bytes",
                "storage_path", "created_at"]


def _row_to_csv_dict(r: dict) -> dict:
    return {
        "nature": r.get("nature"),
        "name": r.get("name"),
        "type": r.get("asset_type") or r.get("physical_kind") or "",
        "project_code": (r.get("project") or {}).get("code") if r.get("project") else "",
        "client": (r.get("client") or {}).get("name") if r.get("client") else "",
        "department": (r.get("department") or {}).get("name") if r.get("department") else "",
        "delivery_status": r.get("delivery_status") or "",
        "linked_to_delivery": "yes" if r.get("linked_to_delivery") else "no",
        "checksum": r.get("checksum") or "",
        "size_bytes": r.get("size_bytes") or "",
        "storage_path": (r.get("storage") or {}).get("path") if r.get("storage") else "",
        "created_at": r.get("created_at") or "",
    }


def export_manifest_csv(db: Session, user, *, items=None, filters=None, cap: int = 5000) -> str:
    from app.services import media_library
    rows = []
    if items:
        for it in items:
            d = media_library.asset_detail(db, user, it.get("nature"), int(it.get("id")))
            if d:
                rows.append(d)
    else:
        out = media_library.list_assets(db, user, filters or {}, offset=0, limit=cap)
        rows = out["rows"]
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(_row_to_csv_dict(r))
    return buf.getvalue()


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
