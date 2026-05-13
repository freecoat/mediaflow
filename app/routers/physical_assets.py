"""
Router PhysicalAsset (v3.5.0-alpha.66.12).

Gestione asset FISICI: LTO tape, HDD USB/EXT, CRU drive, Blu-Ray, DVD,
cases/packaging. Modello separato da Asset (digitale) — vedi memoria
`project_dam_physical_assets`.

Pattern d'uso:
- Archivio interno: LTO con materiale (camera original, DPX graded, ecc.).
- Consegna esterna: drive USB / CRU / Blu-Ray spediti al cliente.
- Un asset può essere SIA archivio interno SIA aver generato una copia
  consegnata esternamente (flag ortogonali).
- Lega a JobDeliverable quando rappresenta "il file/supporto finale".
"""
from datetime import datetime, date, time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from app.database import get_db
from app.models import (
    PhysicalAsset, PhysicalAssetKind, JobDeliverable, Job, Project, Client, User,
    AssetMovement, AssetMovementType, AssetOwnerType, Supplier,
    AssetMembership, Asset,
)
from app.context import current_tenant_id

router = APIRouter(prefix="/physical-assets", tags=["physical_assets"])



def _tpl():
    from app.main import templates
    return templates


# ── Pagina HTML ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def physical_assets_page(request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse(
        "pages/physical_assets.html",
        {"request": request, "kinds": [k.value for k in PhysicalAssetKind]},
    )


# ── API JSON ─────────────────────────────────────────────────

def _serialize(a: PhysicalAsset) -> dict:
    return {
        "id": a.id,
        "tenant_id": a.tenant_id,
        "project_id": a.project_id,
        "job_id": a.job_id,
        "job_deliverable_id": a.job_deliverable_id,
        "kind": a.kind.value if a.kind else None,
        "label": a.label,
        "description": a.description,
        "serial_number": a.serial_number,
        "manufacturer": a.manufacturer,
        "barcode": a.barcode,
        "capacity_gb": a.capacity_gb,
        "used_gb": a.used_gb,
        "condition": a.condition,
        "location": a.location,
        "custodian_user_id": a.custodian_user_id,
        "is_internal_archive": a.is_internal_archive,
        "is_delivered_external": a.is_delivered_external,
        "delivered_at": a.delivered_at.isoformat() + "Z" if a.delivered_at else None,
        "delivered_to": a.delivered_to,
        "courier": a.courier,
        "tracking_number": a.tracking_number,
        "unit_cost": a.unit_cost,
        "checksum_md5": a.checksum_md5,
        "checksum_xxhash": a.checksum_xxhash,
        "last_verified_at": a.last_verified_at.isoformat() + "Z" if a.last_verified_at else None,
        "next_verification_due": a.next_verification_due.isoformat() if a.next_verification_due else None,
        "notes": a.notes,
        "created_at": a.created_at.isoformat() + "Z" if a.created_at else None,
        "deleted_at": a.deleted_at.isoformat() + "Z" if a.deleted_at else None,
        # v3.5.0-alpha.72 — Ownership + QR + logistics
        "owner_type": a.owner_type.value if a.owner_type else "internal",
        "owner_client_id": a.owner_client_id,
        "owner_supplier_id": a.owner_supplier_id,
        "owner_label": a.owner_label,
        "qr_code_token": a.qr_code_token,
        "qr_url": f"/physical-assets/api/{a.id}/qr.png" if a.qr_code_token else None,
        "label_url": f"/physical-assets/api/{a.id}/label.png" if a.qr_code_token else None,
        "logistics_status": a.logistics_status,
    }


@router.get("/api")
async def list_physical_assets(
    kind: Optional[str] = None,
    project_id: Optional[int] = None,
    job_id: Optional[int] = None,
    client_id: Optional[int] = None,
    q: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    only_internal_archive: bool = False,
    only_delivered_external: bool = False,
    include_deleted: bool = False,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.88 — Filtri estesi: client_id (via owner_client_id OR
    project.client_id), q (search su label/serial/barcode), period."""
    query = db.query(PhysicalAsset).filter(PhysicalAsset.tenant_id == current_tenant_id())
    if not include_deleted:
        query = query.filter(PhysicalAsset.deleted_at.is_(None))
    if kind:
        try:
            query = query.filter(PhysicalAsset.kind == PhysicalAssetKind(kind))
        except ValueError:
            raise HTTPException(400, f"kind invalido: {kind}")
    if project_id:
        query = query.filter(PhysicalAsset.project_id == project_id)
    if job_id:
        query = query.filter(PhysicalAsset.job_id == job_id)
    if client_id:
        from app.models import Project as _Project
        query = query.outerjoin(_Project, PhysicalAsset.project_id == _Project.id).filter(
            or_(
                PhysicalAsset.owner_client_id == client_id,
                _Project.client_id == client_id,
            )
        )
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                PhysicalAsset.label.ilike(like),
                PhysicalAsset.serial_number.ilike(like),
                PhysicalAsset.barcode.ilike(like),
            )
        )
    if from_date:
        query = query.filter(PhysicalAsset.created_at >= datetime.combine(from_date, time.min))
    if to_date:
        query = query.filter(PhysicalAsset.created_at <= datetime.combine(to_date, time.max))
    if only_internal_archive:
        query = query.filter(PhysicalAsset.is_internal_archive == True)  # noqa: E712
    if only_delivered_external:
        query = query.filter(PhysicalAsset.is_delivered_external == True)  # noqa: E712
    query = query.order_by(PhysicalAsset.created_at.desc())
    # v3.5.0-alpha.93 — limit per UI compatte (modal Shipment selector).
    if limit and limit > 0:
        query = query.limit(min(limit, 1000))
    items = query.all()
    return [_serialize(a) for a in items]


@router.get("/api/ingest-batches")
async def list_ingest_batches(
    direction: Optional[str] = None,
    shipping_payer: Optional[str] = None,
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    has_cost: Optional[int] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.94 — Lista IngestBatch (= "spedizioni") con totali costi.
    Tab Spedizioni nella pagina /assets/inout. Filtri per payer e periodo.

    v3.5.0-alpha.94 fix: posizionata sopra `/api/{asset_id}` perché altrimenti
    il segmento "ingest-batches" veniva matchato come asset_id e Pydantic
    tornava 422 (int_parsing). Stesso bug di α.92 T3 su billing.py.
    """
    from app.models import IngestBatch, Client, Project as _P
    q = db.query(IngestBatch).filter(IngestBatch.tenant_id == current_tenant_id())
    if direction:
        q = q.filter(IngestBatch.direction == direction)
    if shipping_payer:
        q = q.filter(IngestBatch.shipping_payer == shipping_payer)
    if project_id:
        q = q.filter(IngestBatch.project_id == project_id)
    if client_id:
        q = q.filter(IngestBatch.client_id == client_id)
    if from_date:
        q = q.filter(IngestBatch.batch_date >= datetime.combine(from_date, time.min))
    if to_date:
        q = q.filter(IngestBatch.batch_date <= datetime.combine(to_date, time.max))
    if has_cost:
        q = q.filter(IngestBatch.shipping_cost.is_not(None), IngestBatch.shipping_cost > 0)
    batches = q.order_by(IngestBatch.batch_date.desc()).limit(min(limit, 500)).all()
    proj_ids = list({b.project_id for b in batches if b.project_id})
    cli_ids = list({b.client_id for b in batches if b.client_id})
    proj_map = {p.id: p for p in db.query(_P).filter(_P.id.in_(proj_ids)).all()} if proj_ids else {}
    cli_map = {c.id: c for c in db.query(Client).filter(Client.id.in_(cli_ids)).all()} if cli_ids else {}
    if batches:
        from sqlalchemy import func as _f
        counts = dict(db.query(
            AssetMovement.ingest_batch_id, _f.count(AssetMovement.id)
        ).filter(
            AssetMovement.ingest_batch_id.in_([b.id for b in batches])
        ).group_by(AssetMovement.ingest_batch_id).all())
    else:
        counts = {}
    out = []
    total_cost = 0.0
    total_charged = 0.0
    for b in batches:
        cost = b.shipping_cost or 0.0
        total_cost += cost
        if b.shipping_payer == "charged_to_client" and b.project_id:
            p = proj_map.get(b.project_id)
            mk = float(getattr(p, "shipping_markup_pct", 15.0) or 0.0) if p else 15.0
            total_charged += cost * (1 + mk / 100.0)
        out.append({
            "id": b.id,
            "code": b.code,
            "direction": b.direction,
            "batch_date": str(b.batch_date)[:19] if b.batch_date else None,
            "delivery_note_number": b.delivery_note_number,
            "carrier": b.carrier,
            "tracking_number": b.tracking_number,
            "shipping_cost": cost,
            "shipping_payer": b.shipping_payer,
            "pickup_mode": b.pickup_mode,
            "billable_to_project_id": b.billable_to_project_id,
            "auto_billed_jcl_id": b.auto_billed_jcl_id,
            "project_id": b.project_id,
            "project_code": proj_map[b.project_id].code if b.project_id and b.project_id in proj_map else None,
            "client_id": b.client_id,
            "client_name": cli_map[b.client_id].name if b.client_id and b.client_id in cli_map else None,
            "movements_count": counts.get(b.id, 0),
            "notes": b.notes,
        })
    return {
        "items": out,
        "total_cost": round(total_cost, 2),
        "total_charged_to_client": round(total_charged, 2),
        "count": len(out),
    }


@router.get("/api/{asset_id}")
async def get_physical_asset(asset_id: int, db: Session = Depends(get_db)):
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id,
        PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Asset fisico non trovato")
    return _serialize(a)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"Data {s!r} non valida (atteso YYYY-MM-DD)")


def _parse_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"Datetime {s!r} non valido")


def _require_perm(request: Request, perm: str = "edit_planning_all"):
    """Riusa permessi esistenti — chi può creare booking/assegnare risorse
    può anche gestire asset fisici (sono parte del workflow di consegna).
    """
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, perm) and not has_permission(user, "assign_resources"):
        raise HTTPException(403, f"Permesso '{perm}' o 'assign_resources' richiesto")
    return user


@router.post("/api")
async def create_physical_asset(
    request: Request,
    kind: str = Form(...),
    label: Optional[str] = Form(None),  # v3.5.0-alpha.72.1: auto se vuoto
    description: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    job_deliverable_id: Optional[int] = Form(None),
    serial_number: Optional[str] = Form(None),
    manufacturer: Optional[str] = Form(None),
    barcode: Optional[str] = Form(None),
    capacity_gb: Optional[float] = Form(None),
    used_gb: Optional[float] = Form(None),
    condition: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    custodian_user_id: Optional[int] = Form(None),
    is_internal_archive: bool = Form(True),
    is_delivered_external: bool = Form(False),
    delivered_at: Optional[str] = Form(None),
    delivered_to: Optional[str] = Form(None),
    courier: Optional[str] = Form(None),
    tracking_number: Optional[str] = Form(None),
    unit_cost: Optional[float] = Form(None),
    checksum_md5: Optional[str] = Form(None),
    checksum_xxhash: Optional[str] = Form(None),
    last_verified_at: Optional[str] = Form(None),
    next_verification_due: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    owner_type: Optional[str] = Form("internal"),
    owner_client_id: Optional[int] = Form(None),
    owner_supplier_id: Optional[int] = Form(None),
    owner_label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _require_perm(request)
    try:
        kind_enum = PhysicalAssetKind(kind)
    except ValueError:
        raise HTTPException(400, f"kind invalido: {kind}")
    try:
        owner_enum = AssetOwnerType(owner_type or "internal")
    except ValueError:
        owner_enum = AssetOwnerType.internal
    from app.services.asset_qr import new_token
    # v3.5.0-alpha.72.1 — auto-numerazione se label vuoto
    from app.services.asset_numbering import next_label
    if not (label or "").strip():
        auto = next_label(db, kind, tenant_id=current_tenant_id())
        label = auto or "(no label)"
    a = PhysicalAsset(
        tenant_id=current_tenant_id(),
        kind=kind_enum,
        label=label.strip()[:255],
        description=(description or "").strip() or None,
        project_id=project_id or None,
        job_id=job_id or None,
        job_deliverable_id=job_deliverable_id or None,
        serial_number=(serial_number or "").strip()[:120] or None,
        manufacturer=(manufacturer or "").strip()[:120] or None,
        barcode=(barcode or "").strip()[:120] or None,
        capacity_gb=capacity_gb,
        used_gb=used_gb,
        condition=(condition or "").strip()[:40] or None,
        location=(location or "").strip()[:255] or None,
        custodian_user_id=custodian_user_id or None,
        is_internal_archive=is_internal_archive,
        is_delivered_external=is_delivered_external,
        delivered_at=_parse_datetime(delivered_at),
        delivered_to=(delivered_to or "").strip()[:255] or None,
        courier=(courier or "").strip()[:80] or None,
        tracking_number=(tracking_number or "").strip()[:120] or None,
        unit_cost=unit_cost,
        checksum_md5=(checksum_md5 or "").strip()[:64] or None,
        checksum_xxhash=(checksum_xxhash or "").strip()[:64] or None,
        last_verified_at=_parse_datetime(last_verified_at),
        next_verification_due=_parse_date(next_verification_due),
        notes=(notes or "").strip() or None,
        owner_type=owner_enum,
        owner_client_id=owner_client_id,
        owner_supplier_id=owner_supplier_id,
        owner_label=(owner_label or "").strip() or None,
        qr_code_token=new_token(),
        logistics_status="in_storage",
    )
    db.add(a); db.commit(); db.refresh(a)
    return _serialize(a)


@router.put("/api/{asset_id}")
async def update_physical_asset(
    asset_id: int,
    request: Request,
    kind: Optional[str] = Form(None),
    label: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    job_deliverable_id: Optional[int] = Form(None),
    serial_number: Optional[str] = Form(None),
    manufacturer: Optional[str] = Form(None),
    barcode: Optional[str] = Form(None),
    capacity_gb: Optional[float] = Form(None),
    used_gb: Optional[float] = Form(None),
    condition: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    custodian_user_id: Optional[int] = Form(None),
    is_internal_archive: Optional[bool] = Form(None),
    is_delivered_external: Optional[bool] = Form(None),
    delivered_at: Optional[str] = Form(None),
    delivered_to: Optional[str] = Form(None),
    courier: Optional[str] = Form(None),
    tracking_number: Optional[str] = Form(None),
    unit_cost: Optional[float] = Form(None),
    checksum_md5: Optional[str] = Form(None),
    checksum_xxhash: Optional[str] = Form(None),
    last_verified_at: Optional[str] = Form(None),
    next_verification_due: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _require_perm(request)
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id,
        PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Asset fisico non trovato")

    if kind is not None:
        try: a.kind = PhysicalAssetKind(kind)
        except ValueError: raise HTTPException(400, f"kind invalido: {kind}")
    if label is not None: a.label = label.strip()[:255] or a.label
    if description is not None: a.description = description.strip() or None
    if project_id is not None: a.project_id = project_id or None
    if job_id is not None: a.job_id = job_id or None
    if job_deliverable_id is not None: a.job_deliverable_id = job_deliverable_id or None
    if serial_number is not None: a.serial_number = serial_number.strip()[:120] or None
    if manufacturer is not None: a.manufacturer = manufacturer.strip()[:120] or None
    if barcode is not None: a.barcode = barcode.strip()[:120] or None
    if capacity_gb is not None: a.capacity_gb = capacity_gb
    if used_gb is not None: a.used_gb = used_gb
    if condition is not None: a.condition = condition.strip()[:40] or None
    if location is not None: a.location = location.strip()[:255] or None
    if custodian_user_id is not None: a.custodian_user_id = custodian_user_id or None
    if is_internal_archive is not None: a.is_internal_archive = is_internal_archive
    if is_delivered_external is not None: a.is_delivered_external = is_delivered_external
    if delivered_at is not None: a.delivered_at = _parse_datetime(delivered_at)
    if delivered_to is not None: a.delivered_to = delivered_to.strip()[:255] or None
    if courier is not None: a.courier = courier.strip()[:80] or None
    if tracking_number is not None: a.tracking_number = tracking_number.strip()[:120] or None
    if unit_cost is not None: a.unit_cost = unit_cost
    if checksum_md5 is not None: a.checksum_md5 = checksum_md5.strip()[:64] or None
    if checksum_xxhash is not None: a.checksum_xxhash = checksum_xxhash.strip()[:64] or None
    if last_verified_at is not None: a.last_verified_at = _parse_datetime(last_verified_at)
    if next_verification_due is not None: a.next_verification_due = _parse_date(next_verification_due)
    if notes is not None: a.notes = notes.strip() or None

    db.commit()
    return _serialize(a)


@router.delete("/api/{asset_id}")
async def delete_physical_asset(
    asset_id: int,
    request: Request,
    hard: bool = False,
    db: Session = Depends(get_db),
):
    _require_perm(request)
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id,
        PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Asset fisico non trovato")
    if hard:
        db.delete(a)
    else:
        a.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": asset_id, "hard": hard}


@router.post("/api/{asset_id}/restore")
async def restore_physical_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_perm(request)
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id,
        PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Asset fisico non trovato")
    a.deleted_at = None
    db.commit()
    return _serialize(a)


# ── Numerazione automatica (v3.5.0-alpha.72.1) ────────────────


@router.get("/api/numbering/config")
async def get_numbering_config(request: Request, db: Session = Depends(get_db)):
    from app.services.asset_numbering import get_config
    return get_config(db, tenant_id=current_tenant_id())


@router.put("/api/numbering/config")
async def update_numbering_config(
    request: Request,
    config: str = Form(...),
    db: Session = Depends(get_db),
):
    """PUT JSON string config (es. {"LTO":{"prefix":"LTO-","counter":1,"pad":3}})."""
    _require_perm(request, "edit_settings")
    import json as _json
    try:
        new = _json.loads(config)
    except _json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON malformato: {e}")
    from app.services.asset_numbering import save_config
    saved = save_config(db, new, tenant_id=current_tenant_id())
    db.commit()
    return saved


@router.get("/api/numbering/peek")
async def peek_numbering(kind: str, offset: int = 0, db: Session = Depends(get_db)):
    from app.services.asset_numbering import peek_label
    return {"kind": kind, "next_label": peek_label(db, kind, offset, tenant_id=current_tenant_id())}


# ── Batch import (v3.5.0-alpha.72.1) ──────────────────────────


@router.post("/api/batch-import")
async def batch_import_physical_assets(
    request: Request,
    kind: str = Form(...),
    count: int = Form(...),
    description: Optional[str] = Form(None),
    manufacturer: Optional[str] = Form(None),
    capacity_gb: Optional[float] = Form(None),
    location: Optional[str] = Form(None),
    owner_type: str = Form("internal"),
    unit_cost: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea N PhysicalAsset stesso kind con numerazione progressiva
    dalla config tenant. Use case: acquisto batch LTO (es. 20 LTO-9
    in un colpo).
    """
    _require_perm(request)
    if count <= 0 or count > 500:
        raise HTTPException(400, "count deve essere 1..500")
    try:
        kind_enum = PhysicalAssetKind(kind)
    except ValueError:
        raise HTTPException(400, f"kind invalido: {kind}")
    try:
        owner_enum = AssetOwnerType(owner_type or "internal")
    except ValueError:
        owner_enum = AssetOwnerType.internal
    from app.services.asset_numbering import next_label
    from app.services.asset_qr import new_token
    created = []
    for _ in range(count):
        lbl = next_label(db, kind, tenant_id=current_tenant_id()) or "(no label)"
        a = PhysicalAsset(
            tenant_id=current_tenant_id(),
            kind=kind_enum,
            label=lbl,
            description=(description or "").strip() or None,
            manufacturer=(manufacturer or "").strip()[:120] or None,
            capacity_gb=capacity_gb,
            location=(location or "").strip()[:255] or None,
            unit_cost=unit_cost,
            owner_type=owner_enum,
            qr_code_token=new_token(),
            logistics_status="in_storage",
            notes=(notes or "").strip() or None,
            is_internal_archive=True,
        )
        db.add(a)
        db.flush()
        created.append({"id": a.id, "label": a.label, "kind": a.kind.value})
    db.commit()
    return {"ok": True, "count": len(created), "assets": created}


# ── Movimenti / Logistics (v3.5.0-alpha.72) ──────────────────


def _movement_dict(m: AssetMovement) -> dict:
    return {
        "id": m.id,
        "physical_asset_id": m.physical_asset_id,
        "asset_id": m.asset_id,
        "movement_type": m.movement_type.value if m.movement_type else None,
        "delivery_note_number": m.delivery_note_number,
        "movement_date": str(m.movement_date)[:19] if m.movement_date else None,
        "expected_date": str(m.expected_date) if m.expected_date else None,
        "expected_return_date": str(m.expected_return_date) if m.expected_return_date else None,
        "from_party": m.from_party, "from_address": m.from_address, "from_contact": m.from_contact,
        "to_party": m.to_party, "to_address": m.to_address, "to_contact": m.to_contact,
        "client_id": m.client_id, "supplier_id": m.supplier_id,
        "package_count": m.package_count,
        "total_weight_kg": m.total_weight_kg,
        "dimensions_lwh_cm": m.dimensions_lwh_cm,
        "contents_description": m.contents_description,
        "carrier": m.carrier, "tracking_number": m.tracking_number,
        "shipping_cost": m.shipping_cost,
        "confirmed_at": str(m.confirmed_at)[:19] if m.confirmed_at else None,
        "confirmed_by_user_id": m.confirmed_by_user_id,
        "confirmed_by_name": m.confirmed_by_name,
        "attachment_path": m.attachment_path,
        "notes": m.notes,
        "created_at": str(m.created_at)[:19] if m.created_at else None,
    }


@router.get("/api/movements/all")
async def list_all_movements(
    direction: Optional[str] = None,
    movement_type: Optional[str] = None,
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    only_pending: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.73 — Vista unificata movimenti (physical + digital).
    Filtri: direction (ingest/outgest derivato da movement_type),
    movement_type, client, supplier, only_pending (no conferma).
    v3.5.0-alpha.86 (S3.5) — Filtri estesi: project_id + period.
    project_id filtra via IngestBatch + via FK su Asset/PhysicalAsset."""
    from app.models import Asset
    q = db.query(AssetMovement).filter(
        AssetMovement.tenant_id == current_tenant_id(),
    )
    if movement_type:
        try:
            q = q.filter(AssetMovement.movement_type == AssetMovementType(movement_type))
        except ValueError:
            raise HTTPException(400, f"movement_type invalido: {movement_type}")
    if direction:
        if direction == "ingest":
            q = q.filter(AssetMovement.movement_type.in_([
                AssetMovementType.ingest, AssetMovementType.return_from_client,
            ]))
        elif direction == "outgest":
            q = q.filter(AssetMovementType.outgest == AssetMovement.movement_type)
            q = q.union_all(
                db.query(AssetMovement).filter(
                    AssetMovement.tenant_id == current_tenant_id(),
                    AssetMovement.movement_type == AssetMovementType.return_to_client,
                )
            ) if False else q.filter(AssetMovement.movement_type.in_([
                AssetMovementType.outgest, AssetMovementType.return_to_client,
            ]))
    if client_id: q = q.filter(AssetMovement.client_id == client_id)
    if supplier_id: q = q.filter(AssetMovement.supplier_id == supplier_id)
    if only_pending: q = q.filter(AssetMovement.confirmed_at.is_(None))
    # v3.5.0-alpha.86 (S3.5) — project + period
    if project_id:
        # AssetMovement non ha project_id diretto; usiamo IngestBatch.project_id
        from app.models import IngestBatch as _IB
        q = q.join(_IB, AssetMovement.ingest_batch_id == _IB.id).filter(_IB.project_id == project_id)
    if from_date:
        q = q.filter(AssetMovement.movement_date >= datetime.combine(from_date, time.min))
    if to_date:
        q = q.filter(AssetMovement.movement_date <= datetime.combine(to_date, time.max))
    rows = q.order_by(AssetMovement.movement_date.desc()).limit(min(limit, 500)).all()
    pa_ids = [m.physical_asset_id for m in rows if m.physical_asset_id]
    a_ids = [m.asset_id for m in rows if m.asset_id]
    pa_map = {p.id: p for p in db.query(PhysicalAsset).filter(PhysicalAsset.id.in_(pa_ids)).all()} if pa_ids else {}
    a_map = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(a_ids)).all()} if a_ids else {}
    out = []
    for m in rows:
        d = _movement_dict(m)
        if m.physical_asset_id and m.physical_asset_id in pa_map:
            pa = pa_map[m.physical_asset_id]
            d["asset_label"] = pa.label
            d["asset_kind"] = pa.kind.value if pa.kind else None
            d["asset_nature"] = "physical"
        elif m.asset_id and m.asset_id in a_map:
            a = a_map[m.asset_id]
            d["asset_label"] = a.original_name
            d["asset_kind"] = a.asset_type.value if hasattr(a.asset_type, 'value') else str(a.asset_type)
            d["asset_nature"] = "digital"
            d["asset_file_size"] = a.file_size
        else:
            d["asset_nature"] = "unknown"
        out.append(d)
    return out


@router.get("/api/movements/by-asset")
async def list_movements_by_asset(
    physical_asset_id: Optional[int] = None,
    asset_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.92 — Storico In/Out completo di un asset (physical o digital).
    Usato dal drawer "Storico" nella pagina /assets/inout: click su row
    apre cronologia di QUEL specifico asset, senza limite 200 della lista globale.
    """
    from app.models import Asset
    if not physical_asset_id and not asset_id:
        raise HTTPException(400, "Specifica physical_asset_id o asset_id")
    q = db.query(AssetMovement).filter(AssetMovement.tenant_id == current_tenant_id())
    asset_label, asset_kind, asset_nature = None, None, None
    if physical_asset_id:
        q = q.filter(AssetMovement.physical_asset_id == physical_asset_id)
        pa = db.query(PhysicalAsset).filter(
            PhysicalAsset.id == physical_asset_id,
            PhysicalAsset.tenant_id == current_tenant_id(),
        ).first()
        if pa:
            asset_label = pa.label
            asset_kind = pa.kind.value if pa.kind else None
            asset_nature = "physical"
    elif asset_id:
        q = q.filter(AssetMovement.asset_id == asset_id)
        a = db.query(Asset).filter(
            Asset.id == asset_id, Asset.tenant_id == current_tenant_id(),
        ).first()
        if a:
            asset_label = a.original_name
            asset_kind = a.asset_type.value if hasattr(a.asset_type, "value") else str(a.asset_type)
            asset_nature = "digital"
    rows = q.order_by(AssetMovement.movement_date.desc()).all()
    return {
        "asset_label": asset_label,
        "asset_kind": asset_kind,
        "asset_nature": asset_nature,
        "physical_asset_id": physical_asset_id,
        "asset_id": asset_id,
        "movements": [_movement_dict(m) for m in rows],
    }


@router.get("/api/{asset_id}/movements")
async def list_movements(asset_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(AssetMovement)
        .filter(
            AssetMovement.physical_asset_id == asset_id,
            AssetMovement.tenant_id == current_tenant_id(),
        )
        .order_by(AssetMovement.movement_date.desc())
        .all()
    )
    return [_movement_dict(m) for m in rows]


def _next_ddt_number(db: Session) -> str:
    """Auto-incrementale 'DDT-YYYY-NNN' per tenant."""
    year = datetime.utcnow().year
    last = (
        db.query(AssetMovement)
        .filter(
            AssetMovement.tenant_id == current_tenant_id(),
            AssetMovement.delivery_note_number.like(f"DDT-{year}-%"),
        )
        .order_by(AssetMovement.id.desc())
        .first()
    )
    n = 1
    if last and last.delivery_note_number:
        try:
            n = int(last.delivery_note_number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"DDT-{year}-{n:03d}"


@router.post("/api/{asset_id}/movements")
async def create_movement(
    asset_id: int,
    request: Request,
    movement_type: str = Form(...),
    delivery_note_number: Optional[str] = Form(None),
    movement_date: Optional[datetime] = Form(None),
    expected_return_date: Optional[date] = Form(None),
    from_party: Optional[str] = Form(None),
    from_address: Optional[str] = Form(None),
    from_contact: Optional[str] = Form(None),
    to_party: Optional[str] = Form(None),
    to_address: Optional[str] = Form(None),
    to_contact: Optional[str] = Form(None),
    client_id: Optional[int] = Form(None),
    supplier_id: Optional[int] = Form(None),
    package_count: int = Form(1),
    total_weight_kg: Optional[float] = Form(None),
    dimensions_lwh_cm: Optional[str] = Form(None),
    contents_description: Optional[str] = Form(None),
    carrier: Optional[str] = Form(None),
    tracking_number: Optional[str] = Form(None),
    shipping_cost: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _require_perm(request)
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Asset fisico non trovato")
    try:
        mt = AssetMovementType(movement_type)
    except ValueError:
        raise HTTPException(400, f"movement_type non valido: {movement_type}")
    user = getattr(request.state, "current_user", None)
    if not delivery_note_number:
        delivery_note_number = _next_ddt_number(db)
    m = AssetMovement(
        tenant_id=current_tenant_id(),
        physical_asset_id=asset_id,
        movement_type=mt,
        delivery_note_number=delivery_note_number,
        movement_date=movement_date or datetime.utcnow(),
        expected_return_date=expected_return_date,
        from_party=(from_party or "").strip() or None,
        from_address=(from_address or "").strip() or None,
        from_contact=(from_contact or "").strip() or None,
        to_party=(to_party or "").strip() or None,
        to_address=(to_address or "").strip() or None,
        to_contact=(to_contact or "").strip() or None,
        client_id=client_id, supplier_id=supplier_id,
        package_count=package_count,
        total_weight_kg=total_weight_kg,
        dimensions_lwh_cm=(dimensions_lwh_cm or "").strip() or None,
        contents_description=(contents_description or "").strip() or None,
        carrier=(carrier or "").strip() or None,
        tracking_number=(tracking_number or "").strip() or None,
        shipping_cost=shipping_cost,
        notes=(notes or "").strip() or None,
        created_by_user_id=user.id if user else None,
    )
    db.add(m); db.flush()
    # Update logistics_status su asset
    status_map = {
        AssetMovementType.ingest: "in_storage",
        AssetMovementType.outgest: "transit_out",
        AssetMovementType.transfer: "in_storage",
        AssetMovementType.return_to_client: "transit_out",
        AssetMovementType.return_from_client: "in_storage",
    }
    a.logistics_status = status_map.get(mt, a.logistics_status)
    # v3.5.0-alpha.78.1 — TPN audit log per movimento fisico
    from app.services.project_access import log_asset_access
    from app.models import AssetAccessAction
    log_asset_access(db, user=user, action=AssetAccessAction.update,
                     project_id=a.project_id, request=request,
                     extra=f"physical movement DDT={delivery_note_number} mt={mt.value} physical_asset_id={a.id}",
                     commit=False)
    db.commit()
    db.refresh(m)
    return _movement_dict(m)


@router.post("/api/movements/{movement_id}/confirm")
async def confirm_movement(
    movement_id: int,
    request: Request,
    confirmed_by_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Conferma consegna/ritiro. Aggiorna logistics_status finale."""
    _require_perm(request)
    m = db.query(AssetMovement).filter(
        AssetMovement.id == movement_id,
        AssetMovement.tenant_id == current_tenant_id(),
    ).first()
    if not m:
        raise HTTPException(404, "Movimento non trovato")
    if m.confirmed_at:
        return {"ok": True, "already_confirmed": True, "at": str(m.confirmed_at)[:19]}
    user = getattr(request.state, "current_user", None)
    m.confirmed_at = datetime.utcnow()
    m.confirmed_by_user_id = user.id if user else None
    m.confirmed_by_name = (confirmed_by_name or "").strip() or None
    # Aggiorna logistics_status finale
    final_map = {
        AssetMovementType.outgest: "delivered_external",
        AssetMovementType.return_to_client: "delivered_external",
        AssetMovementType.return_from_client: "in_storage",
        AssetMovementType.ingest: "in_storage",
        AssetMovementType.transfer: "in_storage",
    }
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == m.physical_asset_id
    ).first()
    if a:
        a.logistics_status = final_map.get(m.movement_type, a.logistics_status)
    db.commit()
    return {"ok": True, "confirmed_at": str(m.confirmed_at)[:19]}


# ── QR + Label + DDT PDF ─────────────────────────────────────


@router.get("/api/{asset_id}/qr.png")
async def asset_qr_png(asset_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404)
    from app.services.asset_qr import generate_qr_png, new_token
    if not a.qr_code_token:
        a.qr_code_token = new_token()
        db.commit()
    base = str(request.base_url).rstrip("/")
    scan_url = f"{base}/physical-assets/scan/{a.qr_code_token}"
    png = generate_qr_png(scan_url, size_px=300)
    return Response(content=png, media_type="image/png")


@router.get("/api/{asset_id}/label.png")
async def asset_label_png(
    asset_id: int,
    request: Request,
    width_mm: float = 60,
    height_mm: float = 40,
    db: Session = Depends(get_db),
):
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404)
    from app.services.asset_qr import generate_label_png, new_token
    if not a.qr_code_token:
        a.qr_code_token = new_token()
        db.commit()
    base = str(request.base_url).rstrip("/")
    scan_url = f"{base}/physical-assets/scan/{a.qr_code_token}"
    owner_lbl = a.owner_label or None
    if not owner_lbl and a.owner_client_id:
        c = db.query(Client).filter(Client.id == a.owner_client_id).first()
        owner_lbl = f"Cliente: {c.name}" if c else None
    png = generate_label_png(
        scan_url=scan_url,
        asset_label=a.label,
        asset_kind=a.kind.value if a.kind else "",
        serial_number=a.serial_number,
        owner_label=owner_lbl,
        barcode_value=str(a.id),
        width_mm=width_mm, height_mm=height_mm,
    )
    return Response(content=png, media_type="image/png")


@router.get("/api/movements/{movement_id}/ddt.pdf")
async def movement_ddt_pdf(
    movement_id: int, request: Request, db: Session = Depends(get_db),
):
    m = db.query(AssetMovement).filter(
        AssetMovement.id == movement_id,
        AssetMovement.tenant_id == current_tenant_id(),
    ).first()
    if not m:
        raise HTTPException(404)
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == m.physical_asset_id
    ).first()
    if not a:
        raise HTTPException(404)
    from app.services.asset_qr import generate_delivery_note_pdf
    base = str(request.base_url).rstrip("/")
    scan_url = (
        f"{base}/physical-assets/scan/{a.qr_code_token}"
        if a.qr_code_token else None
    )
    title_map = {
        AssetMovementType.ingest: "Bolla di Ingresso (Carico)",
        AssetMovementType.outgest: "Bolla di Uscita (Scarico)",
        AssetMovementType.transfer: "Bolla di Trasferimento Interno",
        AssetMovementType.return_to_client: "Bolla di Restituzione al Cliente",
        AssetMovementType.return_from_client: "Bolla di Restituzione dal Cliente",
    }
    pdf = generate_delivery_note_pdf(
        title=title_map.get(m.movement_type, "Bolla di Consegna"),
        movement_type=m.movement_type.value if m.movement_type else "",
        delivery_note_number=m.delivery_note_number,
        movement_date=str(m.movement_date)[:19] if m.movement_date else "—",
        from_party=m.from_party, from_address=m.from_address,
        to_party=m.to_party, to_address=m.to_address,
        asset_label=a.label,
        asset_kind=a.kind.value if a.kind else "",
        serial_number=a.serial_number,
        package_count=m.package_count or 1,
        total_weight_kg=m.total_weight_kg,
        dimensions_lwh_cm=m.dimensions_lwh_cm,
        contents_description=m.contents_description,
        carrier=m.carrier, tracking_number=m.tracking_number,
        notes=m.notes,
        scan_url=scan_url,
    )
    fname = f"ddt_{m.delivery_note_number or m.id}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


# ── Contenuti digital ↔ physical (v3.5.0-alpha.74) ───────────


def _membership_dict(m: AssetMembership, asset: Optional[Asset] = None) -> dict:
    return {
        "id": m.id,
        "physical_asset_id": m.physical_asset_id,
        "asset_id": m.asset_id,
        "asset_name": asset.original_name if asset else None,
        "asset_mime": asset.mime_type if asset else None,
        "path_on_media": m.path_on_media,
        "checksum": m.checksum,
        "file_size": m.file_size or (asset.file_size if asset else None),
        "notes": m.notes,
        "added_at": str(m.added_at)[:19] if m.added_at else None,
        "removed_at": str(m.removed_at)[:19] if m.removed_at else None,
        "is_present": m.removed_at is None,
    }


@router.get("/api/{asset_id}/contents")
async def list_contents(
    asset_id: int,
    include_removed: int = 0,
    db: Session = Depends(get_db),
):
    """Lista digital Asset contenuti nel PhysicalAsset (storico + presente)."""
    q = db.query(AssetMembership).filter(
        AssetMembership.physical_asset_id == asset_id,
        AssetMembership.tenant_id == current_tenant_id(),
    )
    if not include_removed:
        q = q.filter(AssetMembership.removed_at.is_(None))
    rows = q.order_by(AssetMembership.added_at.desc()).all()
    a_ids = list({r.asset_id for r in rows})
    a_map = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(a_ids)).all()} if a_ids else {}
    return [_membership_dict(m, a_map.get(m.asset_id)) for m in rows]


@router.post("/api/{asset_id}/contents/add")
async def add_content(
    asset_id: int,
    request: Request,
    digital_asset_id: int = Form(...),
    path_on_media: Optional[str] = Form(None),
    checksum: Optional[str] = Form(None),
    file_size: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Aggiunge digital Asset esistente al physical (es. user lo mette
    fisicamente sul disco e lo registra qui)."""
    _require_perm(request)
    pa = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not pa: raise HTTPException(404, "Physical asset non trovato")
    da = db.query(Asset).filter(
        Asset.id == digital_asset_id, Asset.tenant_id == current_tenant_id(),
    ).first()
    if not da: raise HTTPException(404, "Digital asset non trovato")
    user = getattr(request.state, "current_user", None)
    m = AssetMembership(
        tenant_id=current_tenant_id(),
        physical_asset_id=asset_id,
        asset_id=digital_asset_id,
        path_on_media=(path_on_media or "").strip() or None,
        checksum=(checksum or "").strip() or None,
        file_size=file_size,
        notes=(notes or "").strip() or None,
        added_by_user_id=user.id if user else None,
    )
    db.add(m); db.commit(); db.refresh(m)
    return _membership_dict(m, da)


@router.post("/api/{asset_id}/contents/{membership_id}/remove")
async def remove_content(
    asset_id: int, membership_id: int, request: Request,
    db: Session = Depends(get_db),
):
    """Marca asset come rimosso dal supporto (mantiene storico)."""
    _require_perm(request)
    m = db.query(AssetMembership).filter(
        AssetMembership.id == membership_id,
        AssetMembership.physical_asset_id == asset_id,
        AssetMembership.tenant_id == current_tenant_id(),
    ).first()
    if not m: raise HTTPException(404)
    if m.removed_at: return {"ok": True, "already_removed": True}
    user = getattr(request.state, "current_user", None)
    m.removed_at = datetime.utcnow()
    m.removed_by_user_id = user.id if user else None
    db.commit()
    return {"ok": True, "removed_at": str(m.removed_at)[:19]}


@router.post("/api/{asset_id}/scan-content")
async def scan_filesystem_content(
    asset_id: int,
    request: Request,
    path: str = Form(...),
    compute_checksum: int = Form(0),
    auto_register: int = Form(0),
    max_files: int = Form(2000),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.75 — Scansiona filesystem path (es. HDD montato),
    walk + opt checksum + opt auto-register come Asset+Membership.

    SECURITY: path validato server-side (deve essere assoluto + accessible).
    NO arbitrary fs access: amministratore configura mount path; user
    inserisce path within whitelist.

    Output: lista file con metadata. Se auto_register=1, crea anche
    Asset placeholder + AssetMembership.
    """
    _require_perm(request)
    pa = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not pa: raise HTTPException(404)
    from app.services.fs_scan import walk_filesystem
    result = walk_filesystem(
        path, compute_checksum=bool(compute_checksum), max_files=max_files,
    )
    if "error" in result and not result.get("files"):
        raise HTTPException(400, result["error"])
    if auto_register:
        from app.models import AssetType
        user = getattr(request.state, "current_user", None)
        created = 0
        linked = 0
        for entry in result["files"]:
            # Skip se file system_type non determinabile come asset (placeholder)
            mime = entry.get("mime") or "application/octet-stream"
            a_type = AssetType.other
            if mime.startswith("video"): a_type = AssetType.video
            elif mime.startswith("audio"): a_type = AssetType.audio
            elif mime.startswith("image"): a_type = AssetType.image
            elif mime == "application/pdf": a_type = AssetType.document
            da = Asset(
                tenant_id=current_tenant_id(),
                filename=entry["hash"] or entry["filename"],
                original_name=entry["filename"],
                file_path="",  # placeholder, file NON copiato
                asset_type=a_type,
                mime_type=mime,
                file_size=entry["size"],
                project_id=pa.project_id,
                uploaded_by=user.id if user else 1,
                description=f"FS scan da {pa.label} ({result['root']})",
            )
            db.add(da); db.flush()
            created += 1
            m = AssetMembership(
                tenant_id=current_tenant_id(),
                physical_asset_id=asset_id,
                asset_id=da.id,
                path_on_media=entry["rel_path"],
                checksum=entry["hash"],
                file_size=entry["size"],
                added_by_user_id=user.id if user else None,
            )
            db.add(m); linked += 1
        db.commit()
        result["registered"] = {"created": created, "linked": linked}
    return result


@router.post("/api/{asset_id}/contents/manifest-import")
async def import_manifest(
    asset_id: int,
    request: Request,
    manifest: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.74 — Bulk import contenuto da manifest CSV/JSON.

    CSV: header `filename,path,checksum,size,notes` (size+checksum opt).
    JSON: lista `[{filename, path, checksum, size, notes}, ...]`.

    Per ogni riga:
      1. Cerca Asset DAM esistente per checksum (priorità) o filename.
      2. Se non trovato, crea Asset placeholder (file_path vuoto, is_internal).
      3. Crea AssetMembership con metadata.
    """
    _require_perm(request)
    pa = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not pa: raise HTTPException(404)
    raw = await manifest.read()
    if not raw: raise HTTPException(400, "Manifest vuoto")
    fname = (manifest.filename or "").lower()
    entries = []
    try:
        if fname.endswith(".json"):
            import json as _json
            data = _json.loads(raw.decode("utf-8", errors="ignore"))
            if not isinstance(data, list):
                raise HTTPException(400, "JSON deve essere lista di entry")
            entries = data
        else:
            # CSV (default)
            import csv as _csv
            import io as _io
            txt = raw.decode("utf-8", errors="ignore")
            reader = _csv.DictReader(_io.StringIO(txt))
            entries = list(reader)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Parse manifest: {e}")
    user = getattr(request.state, "current_user", None)
    from app.models import AssetType
    created = 0
    linked = 0
    skipped = 0
    for row in entries:
        if not isinstance(row, dict): skipped += 1; continue
        fn = (row.get("filename") or row.get("name") or "").strip()
        if not fn: skipped += 1; continue
        cs = (row.get("checksum") or "").strip() or None
        path = (row.get("path") or "").strip() or None
        try: size = int(row.get("size") or 0) or None
        except (ValueError, TypeError): size = None
        notes = (row.get("notes") or "").strip() or None
        # Lookup esistente
        da = None
        if cs:
            da = db.query(Asset).filter(
                Asset.tenant_id == current_tenant_id(),
                or_(Asset.filename == cs,
                    Asset.original_name == fn)
            ).first()
        if not da:
            # Crea placeholder
            da = Asset(
                tenant_id=current_tenant_id(),
                filename=cs or fn,
                original_name=fn,
                file_path="",
                asset_type=AssetType.other,
                mime_type="application/octet-stream",
                file_size=size or 0,
                project_id=pa.project_id,
                uploaded_by=user.id if user else 1,
                description=f"Manifest import da {pa.label}",
            )
            db.add(da); db.flush()
            created += 1
        m = AssetMembership(
            tenant_id=current_tenant_id(),
            physical_asset_id=asset_id,
            asset_id=da.id,
            path_on_media=path,
            checksum=cs,
            file_size=size,
            notes=notes,
            added_by_user_id=user.id if user else None,
        )
        db.add(m); linked += 1
    db.commit()
    return {
        "ok": True,
        "linked": linked,
        "created_placeholders": created,
        "skipped": skipped,
        "total": len(entries),
    }


# ── Digital ingest + IngestBatch (v3.5.0-alpha.73) ───────────


def _next_batch_code(db: Session) -> str:
    year = datetime.utcnow().year
    from app.models import IngestBatch
    last = (
        db.query(IngestBatch)
        .filter(
            IngestBatch.tenant_id == current_tenant_id(),
            IngestBatch.code.like(f"BATCH-{year}-%"),
        )
        .order_by(IngestBatch.id.desc())
        .first()
    )
    n = 1
    if last and last.code:
        try:
            n = int(last.code.split("-")[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"BATCH-{year}-{n:03d}"


@router.post("/api/ingest-batches")
async def create_ingest_batch(
    request: Request,
    direction: str = Form("ingest"),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    client_id: Optional[int] = Form(None),
    supplier_id: Optional[int] = Form(None),
    delivery_note_number: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.73 — Crea IngestBatch (raggruppa N movimenti)."""
    _require_perm(request)
    from app.models import IngestBatch
    user = getattr(request.state, "current_user", None)
    code = _next_batch_code(db)
    b = IngestBatch(
        tenant_id=current_tenant_id(),
        code=code, direction=direction,
        title=(title or "").strip() or None,
        description=(description or "").strip() or None,
        project_id=project_id, client_id=client_id, supplier_id=supplier_id,
        delivery_note_number=(delivery_note_number or "").strip() or None,
        notes=(notes or "").strip() or None,
        created_by_user_id=user.id if user else None,
    )
    db.add(b); db.commit(); db.refresh(b)
    return {"id": b.id, "code": b.code, "direction": b.direction}


def _get_or_create_shipping_price_item(db: Session):
    """v3.5.0-alpha.94 — Auto-crea PriceItem "Spedizione standard" se
    mancante. Idempotente per tenant. Categoria "Spedizioni" (auto-creata
    a sua volta).

    La JCL auto-generata dal flusso Shipment.charged_to_client linka a
    questo price_item. In questo modo:
      - Cost report raggruppa righe "Spedizioni" in una categoria dedicata
      - BillingBatch eredita name/category al transmit
      - Fattura SDI ha riga semantica "Spedizione" invece di free-form
    """
    from app.models import PriceItem, PriceCategory
    item = db.query(PriceItem).filter(
        PriceItem.tenant_id == current_tenant_id(),
        PriceItem.name == "Spedizione standard",
        PriceItem.is_active == True,  # noqa: E712
    ).first()
    if item:
        return item
    # Cerca/crea categoria
    cat = db.query(PriceCategory).filter(
        PriceCategory.tenant_id == current_tenant_id(),
        PriceCategory.name == "Spedizioni",
    ).first()
    if not cat:
        cat = PriceCategory(tenant_id=current_tenant_id(), name="Spedizioni", sort_order=999)
        db.add(cat); db.flush()
    item = PriceItem(
        tenant_id=current_tenant_id(),
        category_id=cat.id,
        name="Spedizione standard",
        description="Voce auto-generata per spedizioni riaddebitate (vettore + markup).",
        unit_pre="costo",
        unit="lump",
        price_list=0.0,
        price_average=0.0,
        price_low=0.0,
        is_active=True,
    )
    db.add(item); db.flush()
    return item


@router.post("/api/shipments")
async def create_shipment(
    request: Request,
    direction: str = Form(...),                 # ingest | outgest
    carrier: Optional[str] = Form(None),
    tracking_number: Optional[str] = Form(None),
    shipping_cost: Optional[float] = Form(None),
    shipping_payer: str = Form("internal"),     # internal | client_direct | charged_to_client
    pickup_mode: str = Form("we_ship"),         # we_ship | client_carrier_pickup | client_in_person
    billable_to_project_id: Optional[int] = Form(None),
    project_id: Optional[int] = Form(None),
    client_id: Optional[int] = Form(None),
    supplier_id: Optional[int] = Form(None),
    delivery_note_number: Optional[str] = Form(None),
    from_party: Optional[str] = Form(None),
    to_party: Optional[str] = Form(None),
    physical_asset_ids: Optional[str] = Form(None),   # CSV
    digital_asset_ids: Optional[str] = Form(None),    # CSV
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.93 — Spedizione raggruppata (1+ asset, 1 vettore, 1 costo).

    Crea 1 IngestBatch + N AssetMovement (uno per asset selezionato, fisico
    o digitale) con stesso DDT, carrier, tracking. Se shipping_payer =
    `charged_to_client` AND billable_to_project_id valorizzato → genera
    automaticamente JobCostLine nella categoria "Spedizioni" del Job attivo
    di quel project (per riaddebito al cliente nel ciclo fatturazione).

    Tutto in transazione singola: se la JCL fallisce, ribalta il batch.
    """
    _require_perm(request)
    from app.models import IngestBatch, Asset, Job, JobCostLine, JCLBillingStatus
    user = getattr(request.state, "current_user", None)

    # Validazione enum string fields
    if direction not in ("ingest", "outgest"):
        raise HTTPException(400, f"direction invalido: {direction}")
    if shipping_payer not in ("internal", "client_direct", "charged_to_client"):
        raise HTTPException(400, f"shipping_payer invalido: {shipping_payer}")
    if pickup_mode not in ("we_ship", "client_carrier_pickup", "client_in_person"):
        raise HTTPException(400, f"pickup_mode invalido: {pickup_mode}")
    if shipping_payer == "charged_to_client":
        if not billable_to_project_id:
            raise HTTPException(400, "charged_to_client richiede billable_to_project_id")
        if not shipping_cost or shipping_cost <= 0:
            raise HTTPException(400, "charged_to_client richiede shipping_cost > 0")

    # Parse asset ids
    def _parse_ids(csv: Optional[str]) -> list[int]:
        if not csv:
            return []
        try:
            return [int(x.strip()) for x in csv.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, f"ID asset non validi: {csv}")
    pa_ids = _parse_ids(physical_asset_ids)
    da_ids = _parse_ids(digital_asset_ids)
    if not pa_ids and not da_ids:
        raise HTTPException(400, "Specifica almeno un asset (physical_asset_ids o digital_asset_ids)")

    # Verifica esistenza asset (tenant scope)
    if pa_ids:
        found = db.query(PhysicalAsset.id).filter(
            PhysicalAsset.id.in_(pa_ids),
            PhysicalAsset.tenant_id == current_tenant_id(),
            PhysicalAsset.deleted_at.is_(None),
        ).all()
        if len(found) != len(pa_ids):
            raise HTTPException(404, f"Alcuni physical asset non trovati nel tenant")
    if da_ids:
        found = db.query(Asset.id).filter(
            Asset.id.in_(da_ids),
            Asset.tenant_id == current_tenant_id(),
        ).all()
        if len(found) != len(da_ids):
            raise HTTPException(404, f"Alcuni digital asset non trovati nel tenant")

    # DDT shared
    ddt = (delivery_note_number or "").strip() or _next_ddt_number(db)

    # 1. Crea IngestBatch
    code = _next_batch_code(db)
    batch = IngestBatch(
        tenant_id=current_tenant_id(),
        code=code, direction=direction,
        title=None,
        description=(notes or "").strip() or None,
        project_id=project_id, client_id=client_id, supplier_id=supplier_id,
        delivery_note_number=ddt,
        carrier=(carrier or "").strip() or None,
        tracking_number=(tracking_number or "").strip() or None,
        shipping_cost=shipping_cost,
        shipping_payer=shipping_payer,
        pickup_mode=pickup_mode,
        billable_to_project_id=billable_to_project_id,
        notes=(notes or "").strip() or None,
        created_by_user_id=user.id if user else None,
    )
    db.add(batch); db.flush()

    # 2. Crea N AssetMovement
    try:
        mt = AssetMovementType(direction)
    except ValueError:
        raise HTTPException(400, f"direction non mappabile a movement_type: {direction}")

    movements_created = 0
    for pid in pa_ids:
        m = AssetMovement(
            tenant_id=current_tenant_id(),
            physical_asset_id=pid,
            asset_id=None,
            ingest_batch_id=batch.id,
            movement_type=mt,
            delivery_note_number=ddt,
            movement_date=datetime.utcnow(),
            from_party=(from_party or "").strip() or None,
            to_party=(to_party or "").strip() or None,
            client_id=client_id, supplier_id=supplier_id,
            package_count=1,
            carrier=batch.carrier, tracking_number=batch.tracking_number,
            created_by_user_id=user.id if user else None,
        )
        db.add(m); movements_created += 1
    for aid in da_ids:
        m = AssetMovement(
            tenant_id=current_tenant_id(),
            physical_asset_id=None,
            asset_id=aid,
            ingest_batch_id=batch.id,
            movement_type=mt,
            delivery_note_number=ddt,
            movement_date=datetime.utcnow(),
            from_party=(from_party or "").strip() or None,
            to_party=(to_party or "").strip() or None,
            client_id=client_id, supplier_id=supplier_id,
            package_count=1,
            carrier=batch.carrier, tracking_number=batch.tracking_number,
            created_by_user_id=user.id if user else None,
        )
        db.add(m); movements_created += 1

    # 3. Auto-JCL se charged_to_client
    auto_jcl_id = None
    if shipping_payer == "charged_to_client":
        # Trova il primo Job attivo del project_id specificato
        job = db.query(Job).filter(
            Job.project_id == billable_to_project_id,
            Job.tenant_id == current_tenant_id(),
        ).order_by(Job.created_at.desc()).first()
        if not job:
            db.rollback()
            raise HTTPException(
                400,
                f"Nessun Job trovato per project_id={billable_to_project_id}; "
                "impossibile generare JCL Spedizioni. Crea prima un Job o usa "
                "shipping_payer=internal."
            )
        # v3.5.0-alpha.94 — Markup % configurabile per progetto (default 15%).
        # Applicato sul costo vettore prima di scrivere la JCL: il cliente
        # vede l'importo finale che riaddebita la copertura del nostro tempo
        # di gestione spedizione.
        project_obj = db.query(Project).filter(
            Project.id == billable_to_project_id,
        ).first()
        markup = float(getattr(project_obj, "shipping_markup_pct", 15.0) or 0.0)
        billed_unit_price = round(shipping_cost * (1 + markup / 100.0), 2)
        # v3.5.0-alpha.94 — PriceItem dedicato "Spedizione standard" (auto-creato
        # se mancante). Linka JCL → price_item per:
        #   1. Cost report raggruppa per categoria "Spedizioni"
        #   2. BillingBatch usa price_item.name come descrizione fattura
        ship_price_item = _get_or_create_shipping_price_item(db)
        desc_parts = [f"[Spedizione] {code}"]
        if batch.carrier: desc_parts.append(batch.carrier)
        if batch.tracking_number: desc_parts.append(batch.tracking_number)
        if markup > 0:
            desc_parts.append(f"+{markup:g}% ricarico")
        # JCL "extra" (riga aggiunta dopo la quote): quantity_quoted=0,
        # total_quoted=0; il maturato (total_accrued/expected) è il costo
        # spedizione (con markup) che viene riaddebitato al cliente.
        jcl = JobCostLine(
            tenant_id=current_tenant_id(),
            job_id=job.id,
            price_item_id=ship_price_item.id if ship_price_item else None,
            description=" — ".join(desc_parts)[:255],
            quantity_quoted=0.0,
            quantity_actual=1.0,
            unit="lump",
            unit_price=billed_unit_price,
            total_quoted=0.0,
            total_accrued=billed_unit_price,
            total_expected=billed_unit_price,
            is_billable=True,
            is_extra=True,
            billing_status=JCLBillingStatus.not_billed,
            notes=(
                f"Auto-generata da Shipment {code}. "
                f"Costo vettore: €{shipping_cost:.2f}; markup {markup:g}% "
                f"(Project.shipping_markup_pct) → riaddebito €{billed_unit_price:.2f}."
            ),
        )
        db.add(jcl); db.flush()
        batch.auto_billed_jcl_id = jcl.id
        auto_jcl_id = jcl.id

    db.commit()
    return {
        "batch_id": batch.id,
        "batch_code": batch.code,
        "delivery_note_number": ddt,
        "movements_created": movements_created,
        "shipping_cost": shipping_cost,
        "shipping_payer": shipping_payer,
        "auto_billed_jcl_id": auto_jcl_id,
    }


@router.post("/api/movements/digital")
async def create_digital_ingest(
    request: Request,
    file: UploadFile = File(...),
    movement_type: str = Form("ingest"),
    delivery_note_number: Optional[str] = Form(None),
    ingest_batch_id: Optional[int] = Form(None),
    project_id: Optional[int] = Form(None),
    client_id: Optional[int] = Form(None),
    from_party: Optional[str] = Form(None),
    to_party: Optional[str] = Form(None),
    contents_description: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.73 — Ingest digital: upload file + crea Asset (DAM)
    + crea AssetMovement digital. Esempio cliente consegna DCP/mix.
    Mutex con physical_asset_id (qui null)."""
    _require_perm(request)
    from app.models import Asset
    from app.services.dam import save_upload, generate_thumbnail, resolve_asset_type
    try:
        mt = AssetMovementType(movement_type)
    except ValueError:
        raise HTTPException(400, f"movement_type invalido: {movement_type}")
    file_bytes = await file.read()
    filename, file_path, mime_type = save_upload(file_bytes, file.filename)
    thumbnail_path = generate_thumbnail(file_path, mime_type)
    asset_type = resolve_asset_type(mime_type)
    user = getattr(request.state, "current_user", None)
    asset = Asset(
        tenant_id=current_tenant_id(),
        filename=filename, original_name=file.filename,
        file_path=file_path, thumbnail_path=thumbnail_path,
        asset_type=asset_type, mime_type=mime_type,
        file_size=len(file_bytes),
        project_id=project_id,
        uploaded_by=user.id if user else 1,
        description=contents_description or None,
    )
    db.add(asset); db.flush()
    if not delivery_note_number:
        delivery_note_number = _next_ddt_number(db)
    m = AssetMovement(
        tenant_id=current_tenant_id(),
        asset_id=asset.id,
        physical_asset_id=None,
        ingest_batch_id=ingest_batch_id,
        movement_type=mt,
        delivery_note_number=delivery_note_number,
        movement_date=datetime.utcnow(),
        from_party=(from_party or "").strip() or None,
        to_party=(to_party or "").strip() or None,
        client_id=client_id,
        contents_description=(contents_description or "").strip() or None,
        notes=(notes or "").strip() or None,
        created_by_user_id=user.id if user else None,
    )
    db.add(m); db.flush()
    # v3.5.0-alpha.78.1 — TPN audit log anche per digital ingest
    from app.services.project_access import log_asset_access
    from app.models import AssetAccessAction
    log_asset_access(db, user=user, action=AssetAccessAction.upload,
                     asset_id=asset.id, project_id=asset.project_id,
                     request=request,
                     extra=f"digital ingest DDT={delivery_note_number} mt={movement_type}",
                     commit=False)
    db.commit(); db.refresh(asset); db.refresh(m)
    return {
        "ok": True,
        "movement_id": m.id,
        "asset_id": asset.id,
        "asset_name": asset.original_name,
        "delivery_note_number": delivery_note_number,
    }


# ── Pagina vista unificata In/Out (v3.5.0-alpha.73) ──────────


@router.get("/inout", response_class=HTMLResponse)
async def assets_inout_page(request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse(
        "pages/assets_inout.html", {"request": request},
    )


# ── Scan QR (mobile-friendly lookup) ─────────────────────────


@router.get("/scan/{token}", response_class=HTMLResponse)
async def scan_asset(token: str, request: Request, db: Session = Depends(get_db)):
    """Mobile-friendly page raggiunta da QR scan. Mostra dettaglio asset
    + ultimo movimento. NO access control duro per scope corrente (QR è
    in possesso fisico del supporto). Future: integrare access check TPN."""
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.qr_code_token == token,
        PhysicalAsset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        return _tpl().TemplateResponse(
            "pages/physical_asset_scan.html",
            {"request": request, "not_found": True, "token": token},
            status_code=404,
        )
    last_mov = (
        db.query(AssetMovement)
        .filter(AssetMovement.physical_asset_id == a.id)
        .order_by(AssetMovement.movement_date.desc())
        .first()
    )
    return _tpl().TemplateResponse(
        "pages/physical_asset_scan.html",
        {
            "request": request, "asset": a, "last_movement": last_mov,
            "owner_client": (
                db.query(Client).filter(Client.id == a.owner_client_id).first()
                if a.owner_client_id else None
            ),
        },
    )
