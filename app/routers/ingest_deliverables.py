"""
MediaFlow — Ingest endpoint per auto-fill quantity_delivered da MHL/CSV LTO.

v3.5.0-alpha.172.3 Restructure Sprint 3.

Workflow:
- POST /ingest/yoyotta-mhl: upload .mhl + job_id + deliverable_id (opzionale)
  Parser estrae elenco file -> crea 1 PhysicalAsset (kind=LTO) per il
  contenuto della cassetta + auto-link a deliverable + quantity_delivered++.
- POST /ingest/csv-lto: equivalente con CSV format.

Permission: edit_deliverables (manager/producer/operator possono caricare).

NOTA: Implementazione MVP. Featurizzazioni avanzate (multi-tape, AssetMembership
auto-popolato file-by-file, AI matching deliverable per filename) rinviate
a sprint successivo.
"""
from app.services.clock import now_utc
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, JobDeliverable, PhysicalAsset, PhysicalAssetKind,
    DeliverableStatus, AssetOwnerType,
    Job, Project,
)
from app.services.rbac import current_user_optional, has_permission
from app.context import current_tenant_id
from app.services.mhl_parser import parse_mhl_bytes, parse_csv_lto_bytes
from app.services.deliverable_cost_sync import recompute_deliverable_cost

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _require_edit_deliverables(request: Request) -> User:
    user = current_user_optional(request)
    if not has_permission(user, "edit_deliverables"):
        raise HTTPException(403, "Permesso insufficiente per ingest deliverable")
    return user


def _spawn_physical_asset_from_parsed(
    db: Session, *,
    parsed: dict,
    project: Project,
    job: Optional[Job],
    deliverable: Optional[JobDeliverable],
    tape_label: Optional[str],
    user: Optional[User],
) -> PhysicalAsset:
    """Crea 1 PhysicalAsset (kind=LTO) che rappresenta la cassetta scritta.
    Total size + n_files mostrati in descrizione."""
    n_files = parsed["n_files"]
    total_bytes = parsed["total_size_bytes"]
    label = tape_label or f"LTO {project.code} — {now_utc().strftime('%Y%m%d-%H%M')}"
    desc = (
        f"Ingest da {parsed['creator'] or 'MHL/CSV'} (v{parsed['version']}). "
        f"{n_files} file, {total_bytes / 1e12:.2f} TB totali."
    )
    pa = PhysicalAsset(
        tenant_id=current_tenant_id(),
        project_id=project.id,
        job_id=job.id if job else None,
        job_deliverable_id=deliverable.id if deliverable else None,
        kind=PhysicalAssetKind.lto,
        label=label[:255],
        description=desc,
        capacity_gb=12500.0,  # LTO-9 default; user può aggiornare
        used_gb=round(total_bytes / 1e9, 2) if total_bytes else None,
        is_internal_archive=True,
        is_delivered_external=False,
        owner_type=AssetOwnerType.internal,
        custodian_user_id=user.id if user else None,
        condition="verified",
        logistics_status="in_storage",
        notes=f"Auto-ingested {parsed['n_files']} file checksum-verified.",
    )
    db.add(pa); db.flush()
    return pa


def _process_ingest(
    db: Session,
    *,
    parsed: dict,
    job_id: Optional[int],
    deliverable_id: Optional[int],
    tape_label: Optional[str],
    source: str,
    user: User,
) -> dict:
    """Common logic: trova/valida deliverable + job + project, spawn
    PhysicalAsset, link, recompute."""
    deliverable: Optional[JobDeliverable] = None
    if deliverable_id:
        deliverable = db.query(JobDeliverable).filter(
            JobDeliverable.id == deliverable_id,
            JobDeliverable.tenant_id == current_tenant_id(),
        ).first()
        if not deliverable:
            raise HTTPException(404, f"Deliverable #{deliverable_id} non trovato")

    job: Optional[Job] = None
    if deliverable:
        job = db.query(Job).filter(Job.id == deliverable.job_id).first()
    elif job_id:
        job = db.query(Job).filter(
            Job.id == job_id, Job.tenant_id == current_tenant_id(),
        ).first()
        if not job:
            raise HTTPException(404, f"Job #{job_id} non trovato")
    else:
        raise HTTPException(400, "Specificare job_id o deliverable_id")

    project = db.query(Project).filter(Project.id == job.project_id).first()
    if not project:
        raise HTTPException(404, "Project del job non trovato")

    # Spawn PhysicalAsset
    pa = _spawn_physical_asset_from_parsed(
        db,
        parsed=parsed, project=project, job=job, deliverable=deliverable,
        tape_label=tape_label, user=user,
    )

    confirmed_qty = 0
    if deliverable:
        # Link verifica — via service (nodo B): crea pivot + risync FK cache.
        from app.services.deliverable_assets import link_asset
        link_asset(
            db, deliverable,
            physical_asset_id=pa.id,
            source=source,
            user_id=user.id if user else None,
            notes=f"Auto-ingest {parsed['n_files']} file da {source}",
        )
        # Auto-confirm 1 unità (la "cassetta" = 1 piece consegnata)
        # Idempotente: solo se quantity_delivered < quantity_planned
        if (deliverable.quantity_delivered or 0) < (deliverable.quantity_planned or 0):
            deliverable.quantity_delivered = (deliverable.quantity_delivered or 0) + 1.0
            if deliverable.confirmed_at is None:
                deliverable.confirmed_at = now_utc()
                deliverable.confirmed_by_user_id = user.id if user else None
            if (deliverable.quantity_delivered or 0) >= (deliverable.quantity_planned or 0):
                deliverable.status = DeliverableStatus.delivered
                deliverable.delivered_date = now_utc().date()
            else:
                deliverable.status = DeliverableStatus.in_progress
            # FK cache physical_asset_id già risincronizzato da link_asset sopra.
            confirmed_qty = 1
            recompute_deliverable_cost(db, deliverable)

    db.commit()
    db.refresh(pa)
    if deliverable:
        db.refresh(deliverable)

    return {
        "ok": True,
        "physical_asset_id": pa.id,
        "physical_asset_label": pa.label,
        "n_files": parsed["n_files"],
        "total_size_tb": round((parsed["total_size_bytes"] or 0) / 1e12, 3),
        "deliverable_id": deliverable.id if deliverable else None,
        "quantity_delivered_increment": confirmed_qty,
        "deliverable_quantity_delivered": deliverable.quantity_delivered if deliverable else None,
        "deliverable_quantity_planned": deliverable.quantity_planned if deliverable else None,
        "deliverable_status": deliverable.status.value if deliverable else None,
    }


@router.post("/yoyotta-mhl")
async def ingest_yoyotta_mhl(
    request: Request,
    file: UploadFile = File(...),
    job_id: Optional[int] = Form(None),
    deliverable_id: Optional[int] = Form(None),
    tape_label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload Yoyotta MHL file -> spawn PhysicalAsset (kind=LTO) +
    auto-link deliverable + quantity_delivered++.

    Form fields:
    - file: .mhl content (XML)
    - job_id: target job (richiesto se deliverable_id non fornito)
    - deliverable_id: target deliverable (opzionale, fa anche confirm)
    - tape_label: nome cassetta (es. "LTO042"). Default auto-generato.
    """
    user = _require_edit_deliverables(request)
    if not file.filename:
        raise HTTPException(400, "File richiesto")
    data = await file.read()
    if not data:
        raise HTTPException(400, "File vuoto")
    try:
        parsed = parse_mhl_bytes(data)
    except ValueError as e:
        raise HTTPException(400, f"MHL parse error: {e}")
    return _process_ingest(
        db, parsed=parsed, job_id=job_id, deliverable_id=deliverable_id,
        tape_label=tape_label, source="mhl_yoyotta", user=user,
    )


@router.post("/csv-lto")
async def ingest_csv_lto(
    request: Request,
    file: UploadFile = File(...),
    job_id: Optional[int] = Form(None),
    deliverable_id: Optional[int] = Form(None),
    tape_label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload CSV LTO report -> spawn PhysicalAsset + link.
    Header atteso: filename,size_bytes,checksum[,checksum_type]."""
    user = _require_edit_deliverables(request)
    data = await file.read()
    if not data:
        raise HTTPException(400, "File vuoto")
    try:
        parsed = parse_csv_lto_bytes(data)
    except Exception as e:
        raise HTTPException(400, f"CSV parse error: {e}")
    return _process_ingest(
        db, parsed=parsed, job_id=job_id, deliverable_id=deliverable_id,
        tape_label=tape_label, source="csv_lto", user=user,
    )
