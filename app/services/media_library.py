"""Media Library — serializer unificato Asset (digitale) + PhysicalAsset (fisico).
Read-only (Fase A). Tenant-scoped + visibilità TPN. Righe omogenee per il browser.

Task 2: SOLO asset digitali (Asset). PhysicalAsset arriva in Task 3 (merge
delle due nature nello stesso elenco). department/delivery_status/
linked_to_delivery arrivano in Task 4 (join capitolato/deliverable)."""
from __future__ import annotations
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.models import (
    Asset, AssetProposedState, PhysicalAsset, Project, Client,
)
from app.context import current_tenant_id
from app.services.rbac import is_admin
from app.services.project_access import accessible_project_ids


def _tech_from_json(tech_specs_json) -> Optional[dict]:
    """Adatta lo shape reale prodotto da app/services/tech_specs_extractor
    (ffprobe_extractor.py / pillow_extractor.py):
        {"tool", "extracted_at", "container": {...}|None,
         "video": {"width","height","framerate","codec","pixel_format",...}|None,
         "audio": [{"codec","channels","sample_rate",...}, ...], "errors": [...]}
    Niente campo HDR/color_transfer estratto oggi -> "hdr" resta sempre None."""
    if not isinstance(tech_specs_json, dict):
        return None
    video = tech_specs_json.get("video") or {}
    audio_list = tech_specs_json.get("audio") or []
    width = video.get("width")
    height = video.get("height")
    resolution = f"{width}x{height}" if width and height else None
    codec = video.get("codec") or (audio_list[0].get("codec") if audio_list else None)
    frame_rate = video.get("framerate")
    if resolution is None and codec is None and frame_rate is None and not audio_list:
        return None
    return {"resolution": resolution, "codec": codec, "hdr": None, "frame_rate": frame_rate}


def row_from_asset(a: Asset, *, project=None, client=None) -> dict:
    return {
        "nature": "digital", "id": a.id,
        "name": a.original_name or a.filename or f"asset-{a.id}",
        "asset_type": getattr(a.asset_type, "value", None) or (a.asset_type and str(a.asset_type)),
        "physical_kind": None,
        "project": {"id": project.id, "code": project.code, "title": project.title} if project else None,
        "client": {"id": client.id, "name": client.name} if client else None,
        "department": None,          # Task 4
        "delivery_status": None,     # Task 4
        "linked_to_delivery": False, # Task 4
        "proposed_state": getattr(a.proposed_state, "value", None),
        "flags": {"internal_archive": bool(a.is_internal_archive),
                  "delivered_external": bool(a.is_delivered_external)},
        "storage": {"volume_id": a.storage_volume_id,
                    "volume_name": None,  # opzionale (join volume) — rinviabile
                    "path": a.rel_path or a.file_path},
        "checksum": a.checksum_xxhash,
        "size_bytes": a.file_size,
        "tech": _tech_from_json(a.tech_specs_json),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _visible_project_filter(q, user, db):
    """Applica la visibilità TPN come dam.py: admin vede tutto; altrimenti
    progetti accessibili + coda interna (project_id NULL) solo propria."""
    if is_admin(user):
        return q
    proj_ids = accessible_project_ids(user, db)
    filters = []
    if proj_ids:
        filters.append(Asset.project_id.in_(proj_ids))
    if user:
        filters.append((Asset.project_id.is_(None)) & (Asset.uploaded_by == user.id))
    return q.filter(or_(*filters)) if filters else q.filter(Asset.id < 0)


def _digital_query(db, user, f: dict):
    q = db.query(Asset).filter(
        Asset.tenant_id == current_tenant_id(),
        Asset.parent_asset_id.is_(None),
    )
    # proposte agent: default solo confirmed
    ps = f.get("proposed_state")
    if ps:
        q = q.filter(Asset.proposed_state == AssetProposedState(ps))
    else:
        q = q.filter(Asset.proposed_state == AssetProposedState.confirmed)
    if f.get("project_id"):
        q = q.filter(Asset.project_id == int(f["project_id"]))
    if f.get("job_id"):
        q = q.filter(Asset.job_id == int(f["job_id"]))
    if f.get("asset_type"):
        q = q.filter(Asset.asset_type == f["asset_type"])
    if f.get("internal_archive") in ("1", "true", True):
        q = q.filter(Asset.is_internal_archive.is_(True))
    if f.get("delivered_external") in ("1", "true", True):
        q = q.filter(Asset.is_delivered_external.is_(True))
    if f.get("checksum"):
        q = q.filter(Asset.checksum_xxhash.like(f["checksum"] + "%"))
    if f.get("q"):
        like = f"%{f['q']}%"
        q = q.filter(or_(Asset.original_name.like(like), Asset.filename.like(like),
                         Asset.rel_path.like(like), Asset.file_path.like(like)))
    q = _visible_project_filter(q, user, db)
    return q


def list_assets(db: Session, user, filters: dict, *, offset: int = 0, limit: int = 50) -> dict:
    limit = max(1, min(200, int(limit)))
    nature = (filters or {}).get("nature")
    rows = []
    total = 0
    if nature in (None, "", "digital"):
        dq = _digital_query(db, user, filters or {})
        total += dq.count()
        for a in dq.order_by(Asset.created_at.desc()).offset(offset).limit(limit).all():
            project = db.get(Project, a.project_id) if a.project_id else None
            client = db.get(Client, project.client_id) if (project and project.client_id) else None
            rows.append(row_from_asset(a, project=project, client=client))
    # physical: Task 3 — stub, non ancora implementato in Task 2. `nature`
    # "physical"/"all" non produce righe fisiche finché Task 3 non aggiunge
    # la query PhysicalAsset + merge. `total` riflette solo il conteggio
    # digitale finché resta così.
    next_offset = offset + limit if len(rows) == limit else None
    return {"rows": rows, "total": total, "next_offset": next_offset}
