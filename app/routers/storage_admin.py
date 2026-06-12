"""F1 (spec 2026-06-10) — Admin storage facility: volumi, agent, coda, proposte.
F4 (spec 2026-06-11) — Ticket archivio/restore LTO.
F5 (spec 2026-06-12) — Ordini di transfer digitale (TransferOrder).
F6 (spec 2026-06-12) — Distruzioni doppia-conferma + asset-map + storage-report.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    AgentJob, AgentJobType, AgentNode,
    ArchiveTicket, Asset, AssetContentState, AssetMembership,
    AssetProposedState, DestructionRequest, JobDeliverable, PhysicalAsset,
    PhysicalAssetKind, StorageVolume, TransferOrder, User,
)
from app.services.agent_installer import build_installer_zip
from app.services.agent_queue import enqueue_job, generate_agent_token, enqueue_scan_if_absent
from app.services.asset_registry import confirm_proposal, discard_proposal
from app.services.deliverable_match import rank_candidates, link_deliverable_on_confirm
from app.services.rbac import (
    current_user_optional, has_permission, requires_permission,
)

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


# ── F4 — Ticket archivio/restore LTO ────────────────────────────────


def _build_ticket_lookups(
    tickets: list[ArchiveTicket],
    db: Session,
) -> tuple[dict, dict, dict, dict]:
    """Batch-fetch tutti gli oggetti collegati ai ticket e restituisce 4 lookup dict.

    Ritorna: (asset_map, deliverable_map, physical_asset_map, user_map)
    Ogni map: {id: oggetto_orm} oppure {id: full_name} per gli utenti.
    """
    asset_ids = {t.asset_id for t in tickets if t.asset_id}
    deliv_ids = {t.job_deliverable_id for t in tickets if t.job_deliverable_id}
    pa_ids = {t.physical_asset_id for t in tickets if t.physical_asset_id}
    user_ids = set()
    for t in tickets:
        if t.requested_by_user_id:
            user_ids.add(t.requested_by_user_id)
        if t.assigned_to_user_id:
            user_ids.add(t.assigned_to_user_id)

    asset_map: dict[int, Asset] = (
        {a.id: a for a in db.execute(select(Asset).where(
            Asset.id.in_(asset_ids), Asset.tenant_id == CURRENT_TENANT)).scalars().all()}
        if asset_ids else {}
    )
    deliverable_map: dict[int, JobDeliverable] = (
        {d.id: d for d in db.execute(select(JobDeliverable).where(
            JobDeliverable.id.in_(deliv_ids),
            JobDeliverable.tenant_id == CURRENT_TENANT)).scalars().all()}
        if deliv_ids else {}
    )
    physical_asset_map: dict[int, PhysicalAsset] = (
        {pa.id: pa for pa in db.execute(select(PhysicalAsset).where(
            PhysicalAsset.id.in_(pa_ids),
            PhysicalAsset.tenant_id == CURRENT_TENANT)).scalars().all()}
        if pa_ids else {}
    )
    user_map: dict[int, str] = (
        {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()}
        if user_ids else {}
    )
    return asset_map, deliverable_map, physical_asset_map, user_map


def _serialize_ticket(
    t: ArchiveTicket,
    asset_map: dict,
    deliverable_map: dict,
    physical_asset_map: dict,
    user_map: dict,
) -> dict:
    """Serializza un ArchiveTicket usando lookup dict pre-caricati (no N+1)."""
    # Asset digitale
    asset_info = None
    if t.asset_id:
        a = asset_map.get(t.asset_id)
        if a:
            asset_info = {"id": a.id, "filename": a.original_name or a.filename}

    # Deliverable
    deliv_info = None
    if t.job_deliverable_id:
        d = deliverable_map.get(t.job_deliverable_id)
        if d:
            deliv_info = {"id": d.id, "name": d.name}

    # Tape (PhysicalAsset) — usa campo `label`
    tape_info = None
    if t.physical_asset_id:
        pa = physical_asset_map.get(t.physical_asset_id)
        if pa:
            tape_info = {"id": pa.id, "name": pa.label}

    return {
        "id": t.id,
        "kind": t.kind,
        "status": t.status,
        "note": t.note,
        "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
        "closed_at": t.closed_at.isoformat() + "Z" if t.closed_at else None,
        "asset": asset_info,
        "deliverable": deliv_info,
        "tape": tape_info,
        "requested_by": user_map.get(t.requested_by_user_id) if t.requested_by_user_id else None,
        "assigned_to": user_map.get(t.assigned_to_user_id) if t.assigned_to_user_id else None,
    }


@router.get("/api/tickets", dependencies=[RequireStorage])
def list_tickets(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """F4 — Lista ticket archivio/restore. Filtri: kind, status. Max 200, desc id."""
    q = (
        select(ArchiveTicket)
        .where(ArchiveTicket.tenant_id == CURRENT_TENANT)
        .order_by(ArchiveTicket.id.desc())
        .limit(200)
    )
    if kind:
        q = q.where(ArchiveTicket.kind == kind)
    if status:
        q = q.where(ArchiveTicket.status == status)
    tickets = db.execute(q).scalars().all()
    if not tickets:
        return []
    asset_map, deliverable_map, physical_asset_map, user_map = _build_ticket_lookups(tickets, db)
    return [
        _serialize_ticket(t, asset_map, deliverable_map, physical_asset_map, user_map)
        for t in tickets
    ]


@router.post("/api/tickets", dependencies=[RequireStorage])
def create_ticket(
    request: Request,
    kind: str = Form(...),
    asset_id: Optional[int] = Form(None),
    deliverable_id: Optional[int] = Form(None),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """F4 — Crea un ticket archivio/restore.

    Form fields:
    - kind: 'archive' o 'restore'
    - asset_id: id Asset digitale (opzionale, tenant check)
    - deliverable_id: id JobDeliverable (opzionale, tenant check)
    - note: testo libero opzionale

    Ritorna: {"ok": True, "id": <ticket_id>}.
    """
    from app.services.archive_tickets import create_ticket as svc_create

    user = current_user_optional(request)
    user_id = getattr(user, "id", None)

    # Risolvi asset con tenant check
    asset: Optional[Asset] = None
    if asset_id:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.tenant_id != CURRENT_TENANT:
            raise HTTPException(404, f"Asset #{asset_id} non trovato")

    # Risolvi deliverable con tenant check
    deliverable: Optional[JobDeliverable] = None
    if deliverable_id:
        deliverable = db.get(JobDeliverable, deliverable_id)
        if deliverable is None or deliverable.tenant_id != CURRENT_TENANT:
            raise HTTPException(404, f"Deliverable #{deliverable_id} non trovato")

    try:
        ticket = svc_create(
            db,
            kind=kind,
            asset=asset,
            deliverable=deliverable,
            note=(note or "").strip() or None,
            user_id=user_id,
            tenant_id=CURRENT_TENANT,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "id": ticket.id}


@router.post("/api/tickets/{ticket_id}/transition", dependencies=[RequireStorage])
def transition_ticket(
    ticket_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    """F4 — Avanza lo stato di un ticket.

    Form fields:
    - status: nuovo stato ('in_progress', 'done', 'cancelled')

    Ritorna: {"ok": True, "status": <nuovo_stato>}.
    """
    from app.services.archive_tickets import transition as svc_transition

    ticket = db.get(ArchiveTicket, ticket_id)
    if ticket is None or ticket.tenant_id != CURRENT_TENANT:
        raise HTTPException(404, "Ticket non trovato")

    user = current_user_optional(request)
    user_id = getattr(user, "id", None)

    try:
        ticket = svc_transition(db, ticket, status, user_id=user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "status": ticket.status}


# ── F5 — Ordini di transfer digitale ─────────────────────────────────


def _build_transfer_lookups(
    orders: list[TransferOrder],
    db: Session,
) -> tuple[dict, dict]:
    """Batch-fetch asset e utenti collegati agli ordini (no N+1).

    Ritorna: (asset_map {id: Asset}, user_map {id: full_name}).
    """
    asset_ids: set[int] = set()
    user_ids: set[int] = set()
    for o in orders:
        for aid in (o.asset_ids or []):
            asset_ids.add(aid)
        if o.requested_by_user_id:
            user_ids.add(o.requested_by_user_id)

    asset_map: dict[int, Asset] = (
        {a.id: a for a in db.execute(select(Asset).where(
            Asset.id.in_(asset_ids), Asset.tenant_id == CURRENT_TENANT)).scalars().all()}
        if asset_ids else {}
    )
    user_map: dict[int, str] = (
        {u.id: u.full_name for u in db.execute(
            select(User).where(User.id.in_(user_ids))).scalars().all()}
        if user_ids else {}
    )
    return asset_map, user_map


def _serialize_transfer(o: TransferOrder, asset_map: dict, user_map: dict) -> dict:
    """Serializza un TransferOrder usando lookup dict pre-caricati."""
    assets = []
    for aid in (o.asset_ids or []):
        a = asset_map.get(aid)
        assets.append({
            "id": aid,
            "filename": (a.original_name or a.filename) if a else None,
        })
    return {
        "id": o.id,
        "tool": o.tool,
        "status": o.status,
        "destination": o.destination,
        "recipient_email": o.recipient_email,
        "note": o.note,
        "assets": assets,
        "link_url": o.link_url,
        "link_expires_at": o.link_expires_at.isoformat() + "Z" if o.link_expires_at else None,
        "verification": o.verification,
        "requested_by": user_map.get(o.requested_by_user_id) if o.requested_by_user_id else None,
        "created_at": o.created_at.isoformat() + "Z" if o.created_at else None,
        "closed_at": o.closed_at.isoformat() + "Z" if o.closed_at else None,
    }


@router.get("/api/transfer-tools", dependencies=[RequireStorage])
def list_transfer_tools():
    """F5 — Driver di transfer disponibili dal registry ADAPTERS."""
    from app.services.transfer_adapters import ADAPTERS

    return [
        {"key": a.key, "label": a.label, "mode": a.mode}
        for a in ADAPTERS.values()
    ]


@router.get("/api/transfers", dependencies=[RequireStorage])
def list_transfers(
    tool: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """F5 — Lista ordini di transfer. Filtri: tool, status. Max 200, desc id."""
    q = (
        select(TransferOrder)
        .where(TransferOrder.tenant_id == CURRENT_TENANT)
        .order_by(TransferOrder.id.desc())
        .limit(200)
    )
    if tool:
        q = q.where(TransferOrder.tool == tool)
    if status:
        q = q.where(TransferOrder.status == status)
    orders = db.execute(q).scalars().all()
    if not orders:
        return []
    asset_map, user_map = _build_transfer_lookups(orders, db)
    return [_serialize_transfer(o, asset_map, user_map) for o in orders]


@router.post("/api/transfers", dependencies=[RequireStorage])
def create_transfer(
    request: Request,
    tool: str = Form(...),
    asset_ids: str = Form(...),
    destination: str = Form(...),
    recipient_email: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """F5 — Crea un ordine di transfer.

    Form fields:
    - tool: chiave driver dal registry ('manual', 'aspera')
    - asset_ids: CSV di ID asset, es. "1,2" (parse tollerante)
    - destination: destinazione (formato ascp per aspera)
    - recipient_email / note: opzionali

    Ritorna: {"ok": True, "id": <order_id>}.
    """
    from app.services.transfer_orders import create_order

    # Parse CSV tollerante: split, strip, int, scarta vuoti
    ids: list[int] = []
    for part in asset_ids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise HTTPException(400, f"asset_ids non valido: {part!r} non è un intero")
    if not ids:
        raise HTTPException(400, "asset_ids vuoto: indicare almeno 1 ID asset (CSV).")

    user = current_user_optional(request)
    try:
        order = create_order(
            db,
            tool=tool,
            asset_ids=ids,
            destination=destination,
            recipient_email=(recipient_email or "").strip() or None,
            note=(note or "").strip() or None,
            user_id=getattr(user, "id", None),
            tenant_id=CURRENT_TENANT,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "id": order.id}


@router.post("/api/transfers/{order_id}/close", dependencies=[RequireStorage])
def close_transfer(
    order_id: int,
    request: Request,
    ok: bool = Form(...),
    method: str = Form(...),
    details: Optional[str] = Form(None),
    link_url: Optional[str] = Form(None),
    link_expires_at: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """F5 — Chiude un ordine con esito (done/failed) + link opzionale.

    Form fields:
    - ok: esito (true=done, false=failed)
    - method: metodo verifica ('manual', 'checksum', 'size')
    - details / link_url: opzionali
    - link_expires_at: scadenza link "YYYY-MM-DD" → datetime a fine giornata

    Ritorna: {"ok": True, "status": <nuovo_stato>}.
    """
    from app.services.transfer_orders import close_order

    order = db.get(TransferOrder, order_id)
    if order is None or order.tenant_id != CURRENT_TENANT:
        raise HTTPException(404, "Ordine non trovato")

    expires_dt = None
    if link_expires_at and link_expires_at.strip():
        try:
            d = datetime.strptime(link_expires_at.strip(), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "link_expires_at non valida (atteso YYYY-MM-DD)")
        expires_dt = d.replace(hour=23, minute=59, second=59)

    user = current_user_optional(request)
    try:
        order = close_order(
            db,
            order,
            ok=ok,
            method=method,
            details=(details or "").strip() or None,
            link_url=(link_url or "").strip() or None,
            link_expires_at=expires_dt,
            user_id=getattr(user, "id", None),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "status": order.status}


@router.post("/api/transfers/{order_id}/transition", dependencies=[RequireStorage])
def transition_transfer(
    order_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    """F5 — Avanza lo stato di un ordine (es. cancelled / in_progress).

    Ritorna: {"ok": True, "status": <nuovo_stato>}.
    """
    from app.services.transfer_orders import transition as svc_transition

    order = db.get(TransferOrder, order_id)
    if order is None or order.tenant_id != CURRENT_TENANT:
        raise HTTPException(404, "Ordine non trovato")

    user = current_user_optional(request)
    try:
        order = svc_transition(db, order, status, user_id=getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "status": order.status}


# ── F6 — Distruzioni doppia-conferma ─────────────────────────────────


def _fetch_destruction(rid: int, db: Session) -> DestructionRequest:
    """Carica una DestructionRequest con tenant check (404 se assente)."""
    req = db.get(DestructionRequest, rid)
    if req is None or req.tenant_id != CURRENT_TENANT:
        raise HTTPException(404, "Richiesta di distruzione non trovata")
    return req


def _serialize_destructions(reqs: list[DestructionRequest], db: Session) -> list[dict]:
    """Serializza le richieste con lookup batch asset/utenti (no N+1)."""
    asset_ids = {r.asset_id for r in reqs}
    user_ids: set[int] = set()
    for r in reqs:
        for uid in (r.requested_by_user_id, r.approved_by_user_id,
                    r.closed_by_user_id):
            if uid:
                user_ids.add(uid)

    asset_map: dict[int, Asset] = (
        {a.id: a for a in db.execute(select(Asset).where(
            Asset.id.in_(asset_ids), Asset.tenant_id == CURRENT_TENANT)).scalars().all()}
        if asset_ids else {}
    )
    user_map: dict[int, str] = (
        {u.id: u.full_name for u in db.execute(
            select(User).where(User.id.in_(user_ids))).scalars().all()}
        if user_ids else {}
    )

    out = []
    for r in reqs:
        a = asset_map.get(r.asset_id)
        out.append({
            "id": r.id,
            "status": r.status,
            "reason": r.reason,
            "executed_method": r.executed_method,
            "agent_job_id": r.agent_job_id,
            "asset": ({"id": a.id, "filename": a.original_name or a.filename}
                      if a else {"id": r.asset_id, "filename": None}),
            "requested_by": user_map.get(r.requested_by_user_id)
                            if r.requested_by_user_id else None,
            "approved_by": user_map.get(r.approved_by_user_id)
                           if r.approved_by_user_id else None,
            "closed_by": user_map.get(r.closed_by_user_id)
                         if r.closed_by_user_id else None,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            "closed_at": r.closed_at.isoformat() + "Z" if r.closed_at else None,
        })
    return out


@router.post("/api/destructions", dependencies=[RequireStorage])
def create_destruction(
    request: Request,
    asset_id: int = Form(...),
    reason: str = Form(...),
    db: Session = Depends(get_db),
):
    """F6 — Richiesta di distruzione documentata (TPN).

    Form fields:
    - asset_id: id Asset digitale (tenant check)
    - reason: motivazione obbligatoria (audit)

    Ritorna: {"ok": True, "id": <request_id>}.
    """
    from app.services.destruction import request_destruction

    asset = db.get(Asset, asset_id)
    if asset is None or asset.tenant_id != CURRENT_TENANT:
        raise HTTPException(404, f"Asset #{asset_id} non trovato")

    user = current_user_optional(request)
    try:
        req = request_destruction(
            db, asset=asset, reason=reason,
            user_id=getattr(user, "id", None), tenant_id=CURRENT_TENANT,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "id": req.id}


@router.get("/api/destructions", dependencies=[RequireStorage])
def list_destructions(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """F6 — Lista richieste di distruzione. Filtro: status. Max 200, desc id."""
    q = (
        select(DestructionRequest)
        .where(DestructionRequest.tenant_id == CURRENT_TENANT)
        .order_by(DestructionRequest.id.desc())
        .limit(200)
    )
    if status:
        q = q.where(DestructionRequest.status == status)
    reqs = db.execute(q).scalars().all()
    if not reqs:
        return []
    return _serialize_destructions(reqs, db)


@router.post("/api/destructions/{rid}/approve")
def approve_destruction(
    rid: int,
    user: User = Depends(requires_permission("approve_destruction")),
    db: Session = Depends(get_db),
):
    """F6 — Approva (doppia conferma). UNICO endpoint con gate RBAC
    `approve_destruction`; l'invariante approvatore≠richiedente sta nel service."""
    from app.services.destruction import approve as svc_approve

    req = _fetch_destruction(rid, db)
    try:
        req = svc_approve(db, req, user_id=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "status": req.status}


@router.post("/api/destructions/{rid}/reject", dependencies=[RequireStorage])
def reject_destruction(
    rid: int,
    request: Request,
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """F6 — Rifiuta la richiesta (solo da requested). Notifica il richiedente."""
    from app.services.destruction import reject as svc_reject

    req = _fetch_destruction(rid, db)
    user = current_user_optional(request)
    try:
        req = svc_reject(db, req, user_id=getattr(user, "id", None),
                         reason=(reason or "").strip() or None)
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "status": req.status}


@router.post("/api/destructions/{rid}/execute-manual", dependencies=[RequireStorage])
def execute_destruction_manual(
    rid: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """F6 — Chiude come eseguita a mano (solo da approved): movimento
    destroyed + content_state deleted/archived_only."""
    from app.services.destruction import execute_manual as svc_execute

    req = _fetch_destruction(rid, db)
    user = current_user_optional(request)
    try:
        req = svc_execute(db, req, user_id=getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "status": req.status}


@router.post("/api/destructions/{rid}/enqueue-verify", dependencies=[RequireStorage])
def enqueue_destruction_verify(
    rid: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """F6 — Accoda il job agent delete_verify (solo da approved, asset
    registrato su volume). L'agent verifica soltanto, non cancella mai."""
    from app.services.destruction import enqueue_verify as svc_enqueue

    req = _fetch_destruction(rid, db)
    user = current_user_optional(request)
    try:
        job = svc_enqueue(db, req, user_id=getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "job_id": job.id}


@router.post("/api/destructions/{rid}/transition", dependencies=[RequireStorage])
def transition_destruction(
    rid: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    """F6 — Transizione generica (solo 'cancelled'): richiedente originale
    o admin (is_admin = chi ha il permesso approve_destruction)."""
    from app.services.destruction import transition as svc_transition

    req = _fetch_destruction(rid, db)
    user = current_user_optional(request)
    try:
        req = svc_transition(
            db, req, status,
            user_id=getattr(user, "id", None),
            is_admin=has_permission(user, "approve_destruction"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    db.commit()
    return {"ok": True, "status": req.status}


# ── F6 — Asset map + storage report ──────────────────────────────────

_ASSET_MAP_LIMIT = 500

# Stati FSM "aperti" per i conteggi pending del report
_TICKETS_OPEN = ("requested", "in_progress")
_TRANSFERS_OPEN = ("requested", "in_progress")
_DESTRUCTIONS_OPEN = ("requested", "approved")


@router.get("/api/asset-map", dependencies=[RequireStorage])
def asset_map(
    content_state: Optional[str] = None,
    volume_id: Optional[int] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """F6 — Mappa "dove vive ogni asset" (solo registry confermato).

    Filtri: content_state (online|archived_only|deleted), volume_id, q
    (substring su filename). Limit 500 + flag truncated.
    Ritorna: {"items": [...], "truncated": bool}. Tutto batch, no N+1.
    """
    query = (
        select(Asset)
        .where(
            Asset.tenant_id == CURRENT_TENANT,
            Asset.proposed_state == AssetProposedState.confirmed,
        )
        .order_by(Asset.id.desc())
    )
    if content_state:
        try:
            query = query.where(
                Asset.content_state == AssetContentState(content_state))
        except ValueError:
            raise HTTPException(400, f"content_state non valido: {content_state!r}")
    if volume_id:
        query = query.where(Asset.storage_volume_id == volume_id)
    if q and q.strip():
        query = query.where(Asset.filename.ilike(f"%{q.strip()}%"))

    rows = db.execute(query.limit(_ASSET_MAP_LIMIT + 1)).scalars().all()
    truncated = len(rows) > _ASSET_MAP_LIMIT
    rows = rows[:_ASSET_MAP_LIMIT]
    if not rows:
        return {"items": [], "truncated": False}

    asset_ids = [a.id for a in rows]

    # Volumi (batch)
    vol_ids = {a.storage_volume_id for a in rows if a.storage_volume_id}
    vol_map: dict[int, StorageVolume] = (
        {v.id: v for v in db.execute(select(StorageVolume).where(
            StorageVolume.id.in_(vol_ids),
            StorageVolume.tenant_id == CURRENT_TENANT)).scalars().all()}
        if vol_ids else {}
    )

    # Tape membership ATTIVE su LTO (batch join)
    tapes_by_asset: dict[int, list[dict]] = {}
    for m, pa in db.execute(
        select(AssetMembership, PhysicalAsset)
        .join(PhysicalAsset, PhysicalAsset.id == AssetMembership.physical_asset_id)
        .where(
            AssetMembership.asset_id.in_(asset_ids),
            AssetMembership.tenant_id == CURRENT_TENANT,
            AssetMembership.removed_at.is_(None),
            PhysicalAsset.tenant_id == CURRENT_TENANT,
            PhysicalAsset.kind == PhysicalAssetKind.lto,
        )
        .order_by(AssetMembership.added_at.desc())
    ).all():
        entry = {"id": pa.id, "label": pa.label}
        bucket = tapes_by_asset.setdefault(m.asset_id, [])
        if entry not in bucket:  # dedup: più membership sullo stesso tape
            bucket.append(entry)

    # Deliverable reverse link (batch)
    deliv_by_asset: dict[int, dict] = {
        d.digital_asset_id: {"id": d.id, "name": d.name}
        for d in db.execute(select(JobDeliverable).where(
            JobDeliverable.digital_asset_id.in_(asset_ids),
            JobDeliverable.tenant_id == CURRENT_TENANT)).scalars().all()
    }

    # Distruzioni attive (batch)
    destruction_pending: set[int] = {
        r.asset_id for r in db.execute(select(DestructionRequest).where(
            DestructionRequest.asset_id.in_(asset_ids),
            DestructionRequest.tenant_id == CURRENT_TENANT,
            DestructionRequest.status.in_(_DESTRUCTIONS_OPEN))).scalars().all()
    }

    # Transfer count: ordini done del tenant caricati UNA volta,
    # conteggio in Python sugli asset_ids JSON
    transfer_count: dict[int, int] = {}
    done_orders = db.execute(select(TransferOrder).where(
        TransferOrder.tenant_id == CURRENT_TENANT,
        TransferOrder.status == "done")).scalars().all()
    wanted = set(asset_ids)
    for o in done_orders:
        for aid in (o.asset_ids or []):
            if aid in wanted:
                transfer_count[aid] = transfer_count.get(aid, 0) + 1

    items = []
    for a in rows:
        vol = vol_map.get(a.storage_volume_id) if a.storage_volume_id else None
        items.append({
            "id": a.id,
            "filename": a.filename,
            "content_state": a.content_state.value,
            "volume": {"id": vol.id, "name": vol.name} if vol else None,
            "tapes": tapes_by_asset.get(a.id, []),
            "preview_status": a.preview_status,
            "transfer_count": transfer_count.get(a.id, 0),
            "deliverable": deliv_by_asset.get(a.id),
            "destruction_pending": a.id in destruction_pending,
        })
    return {"items": items, "truncated": truncated}


@router.get("/api/storage-report", dependencies=[RequireStorage])
def storage_report(db: Session = Depends(get_db)):
    """F6 — Report aggregato storage: volumi, tape, stati contenuto,
    membership orfane, preview locali, code pendenti."""
    import os

    # Registry confermato del tenant, caricato una volta
    assets = db.execute(select(Asset).where(
        Asset.tenant_id == CURRENT_TENANT,
        Asset.proposed_state == AssetProposedState.confirmed,
    )).scalars().all()

    # Volumi: conteggi su asset con contenuto ancora presente (no deleted)
    by_volume: dict[int, dict] = {}
    content_states: dict[str, int] = {}
    for a in assets:
        content_states[a.content_state.value] = (
            content_states.get(a.content_state.value, 0) + 1)
        if a.storage_volume_id and a.content_state != AssetContentState.deleted:
            agg = by_volume.setdefault(
                a.storage_volume_id, {"asset_count": 0, "bytes_total": 0})
            agg["asset_count"] += 1
            agg["bytes_total"] += a.file_size or 0

    volumes = []
    for v in db.execute(select(StorageVolume).where(
            StorageVolume.tenant_id == CURRENT_TENANT)
            .order_by(StorageVolume.name)).scalars().all():
        agg = by_volume.get(v.id, {"asset_count": 0, "bytes_total": 0})
        volumes.append({
            "id": v.id,
            "name": v.name,
            "asset_count": agg["asset_count"],
            "bytes_total": agg["bytes_total"],
            "free_gb": v.free_gb,
            "total_gb": v.total_gb,
        })

    # Tape LTO: membership attive aggregate per tape
    tape_rows = db.execute(
        select(PhysicalAsset, AssetMembership)
        .join(AssetMembership,
              AssetMembership.physical_asset_id == PhysicalAsset.id,
              isouter=True)
        .where(
            PhysicalAsset.tenant_id == CURRENT_TENANT,
            PhysicalAsset.kind == PhysicalAssetKind.lto,
        )
    ).all()
    by_tape: dict[int, dict] = {}
    for pa, m in tape_rows:
        agg = by_tape.setdefault(pa.id, {
            "id": pa.id, "label": pa.label, "file_count": 0, "bytes_total": 0})
        if m is not None and m.removed_at is None:
            agg["file_count"] += 1
            agg["bytes_total"] += m.file_size or 0
    tapes = sorted(by_tape.values(), key=lambda t: t["label"] or "")

    # Membership orfane (asset_id NULL, ancora attive)
    orphan_memberships = len(db.execute(select(AssetMembership.id).where(
        AssetMembership.tenant_id == CURRENT_TENANT,
        AssetMembership.asset_id.is_(None),
        AssetMembership.removed_at.is_(None))).all())

    # Preview locali ready: somma size dai file su disco (tollerante)
    preview_count = 0
    preview_bytes = 0
    for a in assets:
        if a.preview_status != "ready" or a.preview_storage != "local":
            continue
        preview_count += 1
        if a.preview_path:
            try:
                preview_bytes += os.path.getsize(a.preview_path)
            except OSError:
                pass  # file mancante/inaccessibile: conta 0 byte

    # Code pendenti
    pending = {
        "proposals": len(db.execute(select(Asset.id).where(
            Asset.tenant_id == CURRENT_TENANT,
            Asset.proposed_state == AssetProposedState.pending_review)).all()),
        "tickets_open": len(db.execute(select(ArchiveTicket.id).where(
            ArchiveTicket.tenant_id == CURRENT_TENANT,
            ArchiveTicket.status.in_(_TICKETS_OPEN))).all()),
        "transfers_open": len(db.execute(select(TransferOrder.id).where(
            TransferOrder.tenant_id == CURRENT_TENANT,
            TransferOrder.status.in_(_TRANSFERS_OPEN))).all()),
        "destructions_open": len(db.execute(select(DestructionRequest.id).where(
            DestructionRequest.tenant_id == CURRENT_TENANT,
            DestructionRequest.status.in_(_DESTRUCTIONS_OPEN))).all()),
    }

    return {
        "volumes": volumes,
        "tapes": tapes,
        "content_states": content_states,
        "orphan_memberships": orphan_memberships,
        "previews": {"count": preview_count, "bytes_total": preview_bytes},
        "pending": pending,
    }
