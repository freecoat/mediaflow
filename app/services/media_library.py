"""Media Library — serializer unificato Asset (digitale) + PhysicalAsset (fisico).
Read-only (Fase A). Tenant-scoped + visibilità TPN. Righe omogenee per il browser.

Task 2: asset digitali (Asset).
Task 3: PhysicalAsset (fisico) fuso nello stesso elenco, ordinato per
created_at DESC, con paginazione best-effort cross-natura. department/
delivery_status/linked_to_delivery arrivano in Task 4 (join deliverable)."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.models import (
    Asset, AssetProposedState, PhysicalAsset, Project, Client,
)
from app.context import current_tenant_id
from app.services.rbac import is_admin
from app.services.project_access import accessible_project_ids


# Filtri validi solo per una natura: se presenti restringono l'elenco a quella
# natura (una riga fisica non ha asset_type/proposed_state/tech; una digitale
# non ha physical_kind).
_DIGITAL_ONLY_FILTERS = ("asset_type", "proposed_state",
                         "tech_resolution", "tech_codec", "tech_hdr", "tech_frame_rate")
_PHYSICAL_ONLY_FILTERS = ("physical_kind",)


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


def row_from_physical(pa: PhysicalAsset, *, project=None, client=None) -> dict:
    return {
        "nature": "physical", "id": pa.id,
        "name": pa.label or pa.serial_number or f"physical-{pa.id}",
        "asset_type": None,
        "physical_kind": getattr(pa.kind, "value", None) or (pa.kind and str(pa.kind)),
        "project": {"id": project.id, "code": project.code, "title": project.title} if project else None,
        "client": {"id": client.id, "name": client.name} if client else None,
        "department": None,          # Task 4
        "delivery_status": None,     # Task 4
        "linked_to_delivery": False, # Task 4
        "proposed_state": None,
        "flags": {"internal_archive": bool(pa.is_internal_archive),
                  "delivered_external": bool(pa.is_delivered_external)},
        "storage": {"volume_id": None, "volume_name": None, "path": pa.location},
        "checksum": pa.checksum_xxhash or pa.checksum_md5,
        "size_bytes": int(pa.capacity_gb * (1024 ** 3)) if pa.capacity_gb else None,
        "tech": None,
        "created_at": pa.created_at.isoformat() if pa.created_at else None,
    }


def _physical_query(db, user, f: dict):
    q = db.query(PhysicalAsset).filter(
        PhysicalAsset.tenant_id == current_tenant_id(),
        PhysicalAsset.deleted_at.is_(None),
    )
    if f.get("project_id"):
        q = q.filter(PhysicalAsset.project_id == int(f["project_id"]))
    if f.get("job_id"):
        q = q.filter(PhysicalAsset.job_id == int(f["job_id"]))
    if f.get("physical_kind"):
        q = q.filter(PhysicalAsset.kind == f["physical_kind"])
    if f.get("internal_archive") in ("1", "true", True):
        q = q.filter(PhysicalAsset.is_internal_archive.is_(True))
    if f.get("delivered_external") in ("1", "true", True):
        q = q.filter(PhysicalAsset.is_delivered_external.is_(True))
    if f.get("checksum"):
        q = q.filter(or_(PhysicalAsset.checksum_xxhash.like(f["checksum"] + "%"),
                         PhysicalAsset.checksum_md5.like(f["checksum"] + "%")))
    if f.get("q"):
        like = f"%{f['q']}%"
        q = q.filter(or_(PhysicalAsset.label.like(like),
                         PhysicalAsset.serial_number.like(like),
                         PhysicalAsset.location.like(like)))
    # visibilità TPN: admin tutto; altrimenti solo progetti accessibili.
    if not is_admin(user):
        proj_ids = accessible_project_ids(user, db)
        q = (q.filter(PhysicalAsset.project_id.in_(proj_ids))
             if proj_ids else q.filter(PhysicalAsset.id < 0))
    return q


def list_assets(db: Session, user, filters: dict, *, offset: int = 0, limit: int = 50) -> dict:
    """Fonde asset digitali (Asset) e fisici (PhysicalAsset) in un unico elenco
    ordinato per created_at DESC. Paginazione best-effort cross-natura: si
    materializzano fino a offset+limit righe per natura, poi si fonde e si
    taglia la finestra. `total` = conteggio combinato reale delle due nature."""
    f = filters or {}
    limit = max(1, min(200, int(limit)))
    nature = f.get("nature")
    total = 0
    built: list[tuple] = []

    # Un filtro esclusivo di una natura restringe l'elenco a quella natura,
    # anche senza `nature` esplicito (es. asset_type è solo digitale).
    digital_only = any(f.get(k) for k in _DIGITAL_ONLY_FILTERS)
    physical_only = any(f.get(k) for k in _PHYSICAL_ONLY_FILTERS)
    want_digital = nature in (None, "", "digital") and not physical_only
    want_physical = nature in (None, "", "physical") and not digital_only

    if want_digital:
        dq = _digital_query(db, user, f)
        total += dq.count()
        for a in dq.order_by(Asset.created_at.desc()).limit(offset + limit).all():
            project = db.get(Project, a.project_id) if a.project_id else None
            client = db.get(Client, project.client_id) if (project and project.client_id) else None
            built.append((a.created_at, row_from_asset(a, project=project, client=client)))

    if want_physical:
        pq = _physical_query(db, user, f)
        total += pq.count()
        for pa in pq.order_by(PhysicalAsset.created_at.desc()).limit(offset + limit).all():
            project = db.get(Project, pa.project_id) if pa.project_id else None
            client = db.get(Client, project.client_id) if (project and project.client_id) else None
            built.append((pa.created_at, row_from_physical(pa, project=project, client=client)))

    built.sort(key=lambda t: (t[0] or datetime.min), reverse=True)
    page = [r for _, r in built[offset:offset + limit]]
    next_offset = offset + limit if (offset + limit) < len(built) else None
    return {"rows": page, "total": total, "next_offset": next_offset}
