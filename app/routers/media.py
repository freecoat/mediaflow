"""Router Media Library (Fase A) — browser unificato read-only asset
digitali (Asset) + fisici (PhysicalAsset). Nessuna azione mutante: le
associazioni/azioni bulk arrivano nelle fasi B/C/D.

Gate RBAC: manage_assets (retrocompat edit_planning_all) via media_gate.
Tenant-scope + visibilità TPN sono applicati dentro media_library."""
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.media_gate import requires_manage_assets
from app.services import media_library
from app.services import media_actions

router = APIRouter(prefix="/media", tags=["media"])
_Gate = Depends(requires_manage_assets())

# Chiavi filtro accettate dalla API assets (whitelist: ignora il resto).
_FILTER_KEYS = ("nature", "project_id", "client_id", "job_id", "department_id",
                "asset_type", "physical_kind", "delivery_status", "proposed_state",
                "internal_archive", "delivered_external", "linked_to_delivery",
                "volume_id", "q", "checksum",
                "tech_resolution", "tech_codec", "tech_hdr", "tech_frame_rate")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def media_page(request: Request, user=_Gate):
    from app.main import templates
    return templates.TemplateResponse(
        "pages/media_library.html",
        {"request": request, "active_page": "media"},
    )


@router.get("/api/assets")
async def media_assets(request: Request, user=_Gate, db: Session = Depends(get_db),
                       offset: int = 0, limit: int = 50):
    filters = {k: v for k, v in request.query_params.items() if k in _FILTER_KEYS and v}
    return media_library.list_assets(db, user, filters, offset=offset, limit=limit)


@router.get("/api/filters")
async def media_filters(user=_Gate, db: Session = Depends(get_db)):
    return media_library.filter_options(db, user)


@router.get("/api/asset/{nature}/{asset_id}")
async def media_asset_detail(nature: str, asset_id: int, user=_Gate,
                             db: Session = Depends(get_db)):
    if nature not in ("digital", "physical"):
        raise HTTPException(404, "natura non valida")
    d = media_library.asset_detail(db, user, nature, asset_id)
    if d is None:
        raise HTTPException(404, "Asset non trovato o non accessibile")
    return d


def _parse_items(raw: str):
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        raise HTTPException(400, "items malformato (atteso JSON)")
    if not isinstance(data, list):
        raise HTTPException(400, "items deve essere una lista")
    return data


def _bool_or_none(v):
    if v in (None, ""):
        return None
    return v in ("1", "true", "True", "on", True)


@router.post("/api/associate")
async def media_associate(user=_Gate, db: Session = Depends(get_db),
                          deliverable_id: int = Form(...), items: str = Form(...),
                          reason: str = Form(None)):
    parsed = _parse_items(items)
    try:
        out = media_actions.associate(db, user, deliverable_id=deliverable_id,
                                      items=parsed, reason=reason or None)
        db.commit()
    except media_actions.MediaActionError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    except Exception:
        db.rollback()
        raise
    return out


@router.post("/api/flags")
async def media_flags(user=_Gate, db: Session = Depends(get_db),
                      items: str = Form(...), internal_archive: str = Form(None),
                      delivered_external: str = Form(None)):
    parsed = _parse_items(items)
    try:
        out = media_actions.set_flags(db, user, parsed,
                                      internal_archive=_bool_or_none(internal_archive),
                                      delivered_external=_bool_or_none(delivered_external))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return out


@router.post("/api/unlink")
async def media_unlink(user=_Gate, db: Session = Depends(get_db),
                       deliverable_id: int = Form(...), items: str = Form(...)):
    parsed = _parse_items(items)
    try:
        out = media_actions.unlink(db, user, deliverable_id=deliverable_id, items=parsed)
        db.commit()
    except media_actions.MediaActionError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    except Exception:
        db.rollback()
        raise
    return out


@router.get("/api/export")
async def media_export(request: Request, user=_Gate, db: Session = Depends(get_db),
                       items: str = None):
    if items:
        parsed = _parse_items(items)
        csv_text = media_actions.export_manifest_csv(db, user, items=parsed)
    else:
        filters = {k: v for k, v in request.query_params.items() if k in _FILTER_KEYS and v}
        csv_text = media_actions.export_manifest_csv(db, user, filters=filters)
    return PlainTextResponse(csv_text, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=media_export.csv"})


@router.get("/api/deliverables")
async def media_deliverables(user=_Gate, db: Session = Depends(get_db),
                             project_id: int = None, job_id: int = None, q: str = None):
    from app.models.models import JobDeliverable, Job, Project
    from app.context import current_tenant_id
    query = db.query(JobDeliverable).filter(
        JobDeliverable.tenant_id == current_tenant_id(),
        JobDeliverable.deleted_at.is_(None))
    if job_id:
        query = query.filter(JobDeliverable.job_id == job_id)
    if q:
        query = query.filter(JobDeliverable.name.like(f"%{q}%"))
    out = []
    for jd in query.order_by(JobDeliverable.id.desc()).limit(200).all():
        job = db.get(Job, jd.job_id) if jd.job_id else None
        if project_id and (not job or job.project_id != project_id):
            continue
        proj = db.get(Project, job.project_id) if (job and job.project_id) else None
        out.append({"id": jd.id, "name": jd.name,
                    "job": {"id": job.id, "code": job.code} if job else None,
                    "project": {"id": proj.id, "code": proj.code} if proj else None,
                    "status": getattr(jd.status, "value", None) or str(jd.status)})
    return out
