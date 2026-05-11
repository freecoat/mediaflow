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
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import (
    PhysicalAsset, PhysicalAssetKind, JobDeliverable, Job, Project, Client, User,
    AssetMovement, AssetMovementType, AssetOwnerType, Supplier,
)

router = APIRouter(prefix="/physical-assets", tags=["physical_assets"])

CURRENT_TENANT = 1


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
    only_internal_archive: bool = False,
    only_delivered_external: bool = False,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(PhysicalAsset).filter(PhysicalAsset.tenant_id == CURRENT_TENANT)
    if not include_deleted:
        q = q.filter(PhysicalAsset.deleted_at.is_(None))
    if kind:
        try:
            q = q.filter(PhysicalAsset.kind == PhysicalAssetKind(kind))
        except ValueError:
            raise HTTPException(400, f"kind invalido: {kind}")
    if project_id:
        q = q.filter(PhysicalAsset.project_id == project_id)
    if job_id:
        q = q.filter(PhysicalAsset.job_id == job_id)
    if only_internal_archive:
        q = q.filter(PhysicalAsset.is_internal_archive == True)  # noqa: E712
    if only_delivered_external:
        q = q.filter(PhysicalAsset.is_delivered_external == True)  # noqa: E712
    items = q.order_by(PhysicalAsset.created_at.desc()).all()
    return [_serialize(a) for a in items]


@router.get("/api/{asset_id}")
async def get_physical_asset(asset_id: int, db: Session = Depends(get_db)):
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.id == asset_id,
        PhysicalAsset.tenant_id == CURRENT_TENANT,
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
        auto = next_label(db, kind, tenant_id=CURRENT_TENANT)
        label = auto or "(no label)"
    a = PhysicalAsset(
        tenant_id=CURRENT_TENANT,
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
        PhysicalAsset.tenant_id == CURRENT_TENANT,
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
        PhysicalAsset.tenant_id == CURRENT_TENANT,
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
        PhysicalAsset.tenant_id == CURRENT_TENANT,
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
    return get_config(db, tenant_id=CURRENT_TENANT)


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
    saved = save_config(db, new, tenant_id=CURRENT_TENANT)
    db.commit()
    return saved


@router.get("/api/numbering/peek")
async def peek_numbering(kind: str, offset: int = 0, db: Session = Depends(get_db)):
    from app.services.asset_numbering import peek_label
    return {"kind": kind, "next_label": peek_label(db, kind, offset, tenant_id=CURRENT_TENANT)}


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
        lbl = next_label(db, kind, tenant_id=CURRENT_TENANT) or "(no label)"
        a = PhysicalAsset(
            tenant_id=CURRENT_TENANT,
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


@router.get("/api/{asset_id}/movements")
async def list_movements(asset_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(AssetMovement)
        .filter(
            AssetMovement.physical_asset_id == asset_id,
            AssetMovement.tenant_id == CURRENT_TENANT,
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
            AssetMovement.tenant_id == CURRENT_TENANT,
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
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == CURRENT_TENANT,
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
        tenant_id=CURRENT_TENANT,
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
    db.add(m)
    # Update logistics_status su asset
    status_map = {
        AssetMovementType.ingest: "in_storage",
        AssetMovementType.outgest: "transit_out",
        AssetMovementType.transfer: "in_storage",
        AssetMovementType.return_to_client: "transit_out",
        AssetMovementType.return_from_client: "in_storage",
    }
    a.logistics_status = status_map.get(mt, a.logistics_status)
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
        AssetMovement.tenant_id == CURRENT_TENANT,
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
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == CURRENT_TENANT,
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
        PhysicalAsset.id == asset_id, PhysicalAsset.tenant_id == CURRENT_TENANT,
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
        AssetMovement.tenant_id == CURRENT_TENANT,
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


# ── Scan QR (mobile-friendly lookup) ─────────────────────────


@router.get("/scan/{token}", response_class=HTMLResponse)
async def scan_asset(token: str, request: Request, db: Session = Depends(get_db)):
    """Mobile-friendly page raggiunta da QR scan. Mostra dettaglio asset
    + ultimo movimento. NO access control duro per scope corrente (QR è
    in possesso fisico del supporto). Future: integrare access check TPN."""
    a = db.query(PhysicalAsset).filter(
        PhysicalAsset.qr_code_token == token,
        PhysicalAsset.tenant_id == CURRENT_TENANT,
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
