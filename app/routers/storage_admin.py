"""F1 (spec 2026-06-10) — Admin storage facility: volumi, agent, coda, proposte."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    AgentJob, AgentJobType, AgentNode,
    Asset, AssetProposedState, StorageVolume,
)
from app.services.agent_installer import build_installer_zip
from app.services.agent_queue import enqueue_job, generate_agent_token, enqueue_scan_if_absent
from app.services.asset_registry import confirm_proposal, discard_proposal
from app.services.deliverable_match import rank_candidates, link_deliverable_on_confirm
from app.services.rbac import current_user_optional, requires_permission

CURRENT_TENANT = 1

router = APIRouter(prefix="/storage", tags=["storage"])

RequireStorage = Depends(requires_permission("edit_planning_all"))


def _tpl():
    from app.main import templates
    return templates


# ── Pagina HTML ──────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def storage_page(request: Request):
    user = current_user_optional(request)
    return _tpl().TemplateResponse("pages/storage.html",
                                   {"request": request, "user": user})


# ── Volumi ───────────────────────────────────────────────────────────

@router.get("/api/volumes", dependencies=[RequireStorage])
def list_volumes(db: Session = Depends(get_db)):
    vols = db.execute(
        select(StorageVolume)
        .where(StorageVolume.tenant_id == CURRENT_TENANT)
        .order_by(StorageVolume.name)
    ).scalars().all()
    return [
        {
            "id": v.id,
            "name": v.name,
            "mount_path": v.mount_path,
            "watch_dirs": v.watch_dirs or [],
            "read_only": v.read_only,
            "total_gb": v.total_gb,
            "free_gb": v.free_gb,
            "is_active": v.is_active,
            "auto_preview": v.auto_preview,
        }
        for v in vols
    ]


@router.post("/api/volumes", dependencies=[RequireStorage])
def create_volume(
    name: str = Form(...),
    mount_path: str = Form(...),
    watch_dirs: str = Form(""),
    read_only: bool = Form(True),
    auto_preview: bool = Form(False),
    db: Session = Depends(get_db),
):
    dirs = [d.strip() for d in watch_dirs.split(",") if d.strip()]
    v = StorageVolume(
        tenant_id=CURRENT_TENANT,
        name=name,
        mount_path=mount_path,
        watch_dirs=dirs,
        read_only=read_only,
        auto_preview=auto_preview,
    )
    db.add(v)
    db.commit()
    return {"ok": True, "id": v.id}


@router.put("/api/volumes/{vol_id}", dependencies=[RequireStorage])
def update_volume(
    vol_id: int,
    name: str = Form(...),
    mount_path: str = Form(...),
    watch_dirs: str = Form(""),
    read_only: bool = Form(True),
    is_active: bool = Form(True),
    auto_preview: bool = Form(False),
    db: Session = Depends(get_db),
):
    v = db.get(StorageVolume, vol_id)
    if v is None or v.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    v.name = name
    v.mount_path = mount_path
    v.watch_dirs = [d.strip() for d in watch_dirs.split(",") if d.strip()]
    v.read_only = read_only
    v.is_active = is_active
    v.auto_preview = auto_preview
    db.commit()
    return {"ok": True}


@router.post("/api/volumes/{vol_id}/scan-now", dependencies=[RequireStorage])
def scan_now(vol_id: int, request: Request, db: Session = Depends(get_db)):
    v = db.get(StorageVolume, vol_id)
    if v is None or v.tenant_id != CURRENT_TENANT or not v.is_active:
        raise HTTPException(404)
    user = current_user_optional(request)
    job = enqueue_scan_if_absent(db, tenant_id=CURRENT_TENANT, volume_id=vol_id,
                                 requested_by_user_id=getattr(user, "id", None))
    db.commit()
    return {"ok": True, "job_id": job.id}


@router.post("/api/volumes/{vol_id}/browse", dependencies=[RequireStorage])
def browse_volume(vol_id: int, request: Request, rel_path: str = Form(""),
                  db: Session = Depends(get_db)):
    """Accoda un job browse (listing dir via agent). La UI polla il job."""
    v = db.get(StorageVolume, vol_id)
    if v is None or v.tenant_id != CURRENT_TENANT or not v.is_active:
        raise HTTPException(404)
    user = current_user_optional(request)
    job = enqueue_job(
        db, tenant_id=CURRENT_TENANT, type=AgentJobType.browse,
        payload={"volume_id": vol_id,
                 "rel_path": rel_path.strip().strip("/\\")},
        requested_by_user_id=getattr(user, "id", None),
    )
    db.commit()
    return {"ok": True, "job_id": job.id}


# ── Agent ────────────────────────────────────────────────────────────

@router.get("/api/agents", dependencies=[RequireStorage])
def list_agents(db: Session = Depends(get_db)):
    ags = db.execute(
        select(AgentNode)
        .where(AgentNode.tenant_id == CURRENT_TENANT)
        .order_by(AgentNode.name)
    ).scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "version": a.version,
            "capabilities": a.capabilities or [],
            "last_heartbeat_at": (
                a.last_heartbeat_at.isoformat() if a.last_heartbeat_at else None
            ),
            "is_active": a.is_active,
        }
        for a in ags
    ]


@router.post("/api/agents", dependencies=[RequireStorage])
def create_agent(name: str = Form(...), db: Session = Depends(get_db)):
    plain, token_hash = generate_agent_token()
    a = AgentNode(tenant_id=CURRENT_TENANT, name=name, auth_token_hash=token_hash)
    db.add(a)
    db.commit()
    return {"ok": True, "id": a.id, "token": plain}


@router.post("/api/agents/{agent_id}/installer", dependencies=[RequireStorage])
def download_installer(agent_id: int, request: Request,
                       server_url: Optional[str] = Form(None),
                       db: Session = Depends(get_db)):
    """ZIP pronto-all'uso. RIGENERA il token dell'agent (il vecchio smette
    di funzionare): il plain vive solo dentro lo zip scaricato.
    POST (non GET): la rotazione del token è una mutazione — su GET sarebbe
    CSRF-abile via navigazione cross-site (cookie SameSite=Lax)."""
    a = db.get(AgentNode, agent_id)
    if a is None or a.tenant_id != CURRENT_TENANT or not a.is_active:
        raise HTTPException(404)
    if server_url:
        from urllib.parse import urlparse
        p = urlparse(server_url)
        if p.scheme not in ("http", "https") or not p.netloc:
            raise HTTPException(400, "server_url non valido (atteso http(s)://host)")
    plain, token_hash = generate_agent_token()
    a.auth_token_hash = token_hash
    db.commit()
    base = (server_url or str(request.base_url)).rstrip("/")
    data = build_installer_zip(server_url=base, token_plain=plain,
                               agent_name=a.name)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in a.name)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="claqo-agent-{safe_name}.zip"'},
    )


@router.delete("/api/agents/{agent_id}", dependencies=[RequireStorage])
def revoke_agent(agent_id: int, db: Session = Depends(get_db)):
    a = db.get(AgentNode, agent_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    a.is_active = False
    db.commit()
    return {"ok": True}


# ── Job queue ────────────────────────────────────────────────────────

@router.get("/api/jobs", dependencies=[RequireStorage])
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    jobs = db.execute(
        select(AgentJob)
        .where(AgentJob.tenant_id == CURRENT_TENANT)
        .order_by(AgentJob.id.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": j.id,
            "type": j.type.value,
            "status": j.status.value,
            "payload": j.payload,
            "error": j.error,
            "progress": j.progress,
            "created_at": j.created_at.isoformat(),
            "asset_id": j.asset_id,
        }
        for j in jobs
    ]


@router.get("/api/jobs/{job_id}", dependencies=[RequireStorage])
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(AgentJob, job_id)
    if j is None or j.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    return {
        "id": j.id,
        "type": j.type.value,
        "status": j.status.value,
        "payload": j.payload,
        "result": j.result,
        "error": j.error,
    }


@router.post("/api/register-path", dependencies=[RequireStorage])
def register_path(
    request: Request,
    volume_id: int = Form(...),
    rel_path: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    v = db.get(StorageVolume, volume_id)
    if v is None or v.tenant_id != CURRENT_TENANT or not v.is_active:
        raise HTTPException(404, "volume non trovato")
    job = enqueue_job(
        db,
        tenant_id=CURRENT_TENANT,
        type=AgentJobType.probe,
        payload={"volume_id": volume_id, "rel_path": rel_path.strip().lstrip("/")},
        requested_by_user_id=getattr(user, "id", None),
    )
    db.commit()
    return {"ok": True, "job_id": job.id}


# ── Proposte ─────────────────────────────────────────────────────────

@router.get("/api/proposals", dependencies=[RequireStorage])
def list_proposals(db: Session = Depends(get_db)):
    rows = db.execute(
        select(Asset)
        .where(
            Asset.tenant_id == CURRENT_TENANT,
            Asset.proposed_state == AssetProposedState.pending_review,
        )
        .order_by(Asset.id.desc())
    ).scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "rel_path": a.rel_path,
            "file_size": a.file_size,
            "mime_type": a.mime_type,
            "checksum_xxhash": a.checksum_xxhash,
            "tech_specs": a.tech_specs_json,
            "volume_id": a.storage_volume_id,
            "matched_deliverable_id": a.matched_deliverable_id,
        }
        for a in rows
    ]


@router.get("/api/proposals/{asset_id}/candidates", dependencies=[RequireStorage])
def proposal_candidates(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    return rank_candidates(db, a)


@router.post("/api/proposals/{asset_id}/confirm", dependencies=[RequireStorage])
def confirm(
    asset_id: int,
    request: Request,
    deliverable_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    user = current_user_optional(request)
    confirm_proposal(db, a, user_id=getattr(user, "id", None))
    target = deliverable_id or a.matched_deliverable_id
    if target:
        link_deliverable_on_confirm(db, a, deliverable_id=int(target),
                                    user_id=getattr(user, "id", None))
    # Auto-preview: se il volume ha il flag attivo, accoda un job preview
    vol = db.get(StorageVolume, a.storage_volume_id) if a.storage_volume_id else None
    if vol is not None and vol.auto_preview:
        from app.services.asset_preview import enqueue_preview
        try:
            enqueue_preview(db, a, requested_by_user_id=getattr(user, "id", None))
        except ValueError:
            pass  # asset senza rel_path (upload manuale): nessun preview possibile
    db.commit()
    return {"ok": True}


@router.post("/api/proposals/{asset_id}/discard", dependencies=[RequireStorage])
def discard(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    discard_proposal(db, a)
    db.commit()
    return {"ok": True}
