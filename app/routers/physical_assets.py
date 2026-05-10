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
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import (
    PhysicalAsset, PhysicalAssetKind, JobDeliverable, Job, Project, Client, User,
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
    label: str = Form(...),
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
    db: Session = Depends(get_db),
):
    _require_perm(request)
    try:
        kind_enum = PhysicalAssetKind(kind)
    except ValueError:
        raise HTTPException(400, f"kind invalido: {kind}")
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
