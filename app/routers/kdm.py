"""Router richieste KDM/DKDM (v3.5.0-alpha.172.226). Tracking-only.
Vedi docs/superpowers/specs/2026-06-19-kdm-dkdm-request-design.md
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.context import current_tenant_id
from app.models import KdmRequest, DcpCpl, CinemaFacility, CinemaServer
from app.services.rbac import has_permission, current_user_optional

router = APIRouter(prefix="/kdm", tags=["kdm"])


def _tpl():
    from app.main import templates
    return templates


def _require_kdm(request: Request, db: Session):
    user = current_user_optional(request)
    if not has_permission(user, "manage_kdm"):
        raise HTTPException(status_code=403, detail="Permesso manage_kdm richiesto")
    return user


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def kdm_page(request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse("pages/kdm.html", {"request": request})


@router.get("/api/requests")
async def list_requests(
    request: Request,
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    type: Optional[str] = None,
):
    _require_kdm(request, db)
    q = (
        db.query(KdmRequest)
        .filter(
            KdmRequest.tenant_id == current_tenant_id(),
            KdmRequest.deleted_at.is_(None),
        )
    )
    if status:
        q = q.filter(KdmRequest.status == status)
    if type:
        q = q.filter(KdmRequest.request_type == type)
    rows = q.order_by(KdmRequest.requested_at.desc()).all()
    return JSONResponse([
        {
            "id": r.id,
            "request_type": r.request_type,
            "status": r.status,
            "client_id": r.client_id,
            "project_id": r.project_id,
            "requested_title": r.requested_title,
            "valid_from": r.valid_from.isoformat() if r.valid_from else None,
            "valid_to": r.valid_to.isoformat() if r.valid_to else None,
            "matched_confidence": r.matched_confidence,
            "dcp_cpl_id": r.dcp_cpl_id,
            "job_deliverable_id": r.job_deliverable_id,
        }
        for r in rows
    ])
