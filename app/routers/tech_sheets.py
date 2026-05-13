"""Router scheda tecnica progetto (v3.4.31).

Workflow sheet di un progetto: catena di lavorazione (camere, audio, look,
storage, dailies, crew, process). Schema flessibile JSON.

- `GET    /projects/api/{pid}/tech-sheet` — JSON (auto-crea draft se manca)
- `PUT    /projects/api/{pid}/tech-sheet` — sostituisce data + campi metadata
- `POST   /projects/api/{pid}/tech-sheet/publish` — genera/rigenera token + scadenza
- `DELETE /projects/api/{pid}/tech-sheet/public` — disattiva link pubblico
- `GET    /public/tech-sheet/{token}` — vista pubblica readonly (no auth)
"""
from __future__ import annotations
from datetime import datetime, timedelta
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Body
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Project, ProjectTechSheet, DeliveryTemplate, Resource, User
from app.services.rbac import current_user_optional, can_view_finance, has_permission
from app.context import current_tenant_id

router = APIRouter(tags=["tech_sheets"])



def _tpl():
    from app.main import templates
    return templates


# Sezioni con default vuoto. Mantenere allineato con UI editor.
DEFAULT_DATA = {
    "general": {
        "production_company": "", "shoot_days": None, "num_cameras": None,
    },
    "cameras": [],   # [{id_letter, model, codec, sensor_res, format_aspect, framing_aspect, fps, hi_speed_max_fps, shutter, color_space_in, working_color_space, odt, squeeze, safety_pct, lenses[], mag_type, min_per_mag, datarate_mbs}]
    "audio": {
        "recorder": "", "file_format": "", "sample_rate": "", "bit_depth": "",
        "tc_fps": "", "sync_method": "", "track_layout": "",
    },
    "looks": [],     # [{name, scope, lut_file, size_3d, type, range_transform}]
    "storage": {
        "master": "", "backup": "", "shuttle": "",
        "checksum_onset": "", "checksum_lab": "",
        "lto_count": None, "lto_type": "", "shuttle_freq": "",
        "mags_reusable": False, "total_tb_estimated": None,
    },
    "dailies": {
        "editorial_format": "", "editorial_container": "",
        "online_format": "", "online_bitrate": "",
        "naming_convention": "", "burnins": [],
        "nle": "", "review_platform": "", "exchange_format": "",
    },
    "folder_struct": {"volume_naming": "", "daily_template": ""},
    "contacts": [],  # [{role, resource_id, name_text, email, phone}]
    "process": {
        "qc_onset": "", "qc_lab": "", "clearance_sla": "",
        "report_recipients": [], "notify_emails": [],
    },
    "notes": "",
}


def _get_or_create(db: Session, project: Project) -> ProjectTechSheet:
    ts = db.query(ProjectTechSheet).filter(ProjectTechSheet.project_id == project.id).first()
    if not ts:
        ts = ProjectTechSheet(
            project_id=project.id,
            tenant_id=project.tenant_id or current_tenant_id(),
            data=dict(DEFAULT_DATA),
            version="0.1",
            status="draft",
        )
        db.add(ts); db.commit(); db.refresh(ts)
    return ts


def _serialize(ts: ProjectTechSheet, project: Optional[Project] = None) -> dict:
    data = ts.data or {}
    # Fill missing sections with defaults (forward-compat)
    merged = dict(DEFAULT_DATA)
    merged.update(data)
    out = {
        "id": ts.id,
        "project_id": ts.project_id,
        "version": ts.version,
        "status": ts.status,
        "approved_by_user_id": ts.approved_by_user_id,
        "approved_at": ts.approved_at.isoformat() if ts.approved_at else None,
        "is_public_enabled": ts.is_public_enabled,
        "public_token": ts.public_token if ts.is_public_enabled else None,
        "expires_at": ts.expires_at.isoformat() if ts.expires_at else None,
        "published_at": ts.published_at.isoformat() if ts.published_at else None,
        "delivery_template_id": ts.delivery_template_id,
        "created_at": ts.created_at.isoformat() if ts.created_at else None,
        "updated_at": ts.updated_at.isoformat() if ts.updated_at else None,
        "data": merged,
    }
    if project:
        out["project"] = {
            "id": project.id, "code": project.code, "title": project.title,
            "client_id": project.client_id,
            "client_name": project.client.name if project.client else None,
            "project_type": project.project_type,
            "director": project.director, "producer": project.producer, "dop": project.dop,
            "shoot_start": project.shoot_start.isoformat() if project.shoot_start else None,
            "shoot_end": project.shoot_end.isoformat() if project.shoot_end else None,
            "delivery_deadline": project.delivery_deadline.isoformat() if project.delivery_deadline else None,
            "length_minutes": project.length_minutes,
            "fps": project.fps,
            "shooting_format": project.shooting_format,
            "delivery_format": project.delivery_format,
            "description": project.description,
        }
    return out


def _is_token_alive(ts: ProjectTechSheet) -> bool:
    if not ts.is_public_enabled or not ts.public_token:
        return False
    if ts.expires_at and ts.expires_at < datetime.utcnow():
        return False
    return True


# ── API authenticated ──────────────────────────────────────────
@router.get("/projects/api/{project_id}/tech-sheet")
async def get_tech_sheet(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not has_permission(user, "view_projects") and not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Permesso negato")
    p = db.query(Project).options(joinedload(Project.client)).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    ts = _get_or_create(db, p)
    return _serialize(ts, p)


@router.put("/projects/api/{project_id}/tech-sheet")
async def update_tech_sheet(
    project_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Serve permesso edit_projects")
    p = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    ts = _get_or_create(db, p)

    # Aggiorna metadata se presenti
    if "version" in payload and payload["version"] is not None:
        ts.version = str(payload["version"])[:50]
    if "status" in payload and payload["status"] in ("draft", "preview", "approved"):
        new_status = payload["status"]
        if new_status == "approved" and ts.status != "approved":
            ts.approved_by_user_id = user.id if user else None
            ts.approved_at = datetime.utcnow()
        elif new_status != "approved":
            ts.approved_by_user_id = None
            ts.approved_at = None
        ts.status = new_status
    if "delivery_template_id" in payload:
        dt_id = payload["delivery_template_id"]
        if dt_id:
            dt = db.query(DeliveryTemplate).filter(DeliveryTemplate.id == int(dt_id)).first()
            if not dt:
                raise HTTPException(404, "DeliveryTemplate non trovato")
            ts.delivery_template_id = dt.id
        else:
            ts.delivery_template_id = None

    # Aggiorna data (merge top-level su sezioni note)
    if "data" in payload and isinstance(payload["data"], dict):
        new_data = dict(ts.data or {})
        for key, val in payload["data"].items():
            if key in DEFAULT_DATA:
                new_data[key] = val
        ts.data = new_data

    db.commit(); db.refresh(ts)
    return _serialize(ts, p)


@router.post("/projects/api/{project_id}/tech-sheet/publish")
async def publish_tech_sheet(
    project_id: int,
    request: Request,
    expires_days: Optional[int] = Form(90),
    rotate_token: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Abilita link pubblico.

    - `expires_days=0` o vuoto → senza scadenza (`expires_at=NULL`).
    - `rotate_token=true` → rigenera token (vecchio link invalidato).
    """
    user = current_user_optional(request)
    if not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Serve permesso edit_projects")
    p = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    ts = _get_or_create(db, p)

    if rotate_token or not ts.public_token:
        ts.public_token = secrets.token_urlsafe(32)
    ts.is_public_enabled = True
    ts.published_at = datetime.utcnow()
    if expires_days and int(expires_days) > 0:
        ts.expires_at = datetime.utcnow() + timedelta(days=int(expires_days))
    else:
        ts.expires_at = None
    db.commit(); db.refresh(ts)
    return {
        "public_token": ts.public_token,
        "is_public_enabled": ts.is_public_enabled,
        "expires_at": ts.expires_at.isoformat() if ts.expires_at else None,
        "published_at": ts.published_at.isoformat() if ts.published_at else None,
    }


@router.delete("/projects/api/{project_id}/tech-sheet/public")
async def unpublish_tech_sheet(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Serve permesso edit_projects")
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    ts = db.query(ProjectTechSheet).filter(ProjectTechSheet.project_id == project_id).first()
    if not ts:
        return {"ok": True}
    ts.is_public_enabled = False
    ts.expires_at = None
    db.commit()
    return {"ok": True}


# ── Vista pubblica (no auth) ──────────────────────────────────
@router.get("/public/tech-sheet/{token}", response_class=HTMLResponse)
async def public_tech_sheet(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    ts = db.query(ProjectTechSheet).options(
        joinedload(ProjectTechSheet.project).joinedload(Project.client),
        joinedload(ProjectTechSheet.delivery_template),
    ).filter(ProjectTechSheet.public_token == token).first()
    if not ts or not _is_token_alive(ts):
        return _tpl().TemplateResponse(
            "pages/tech_sheet_public_error.html",
            {"request": request, "reason": "expired" if (ts and ts.expires_at and ts.expires_at < datetime.utcnow()) else "not_found"},
            status_code=410 if ts else 404,
        )
    project = ts.project
    return _tpl().TemplateResponse(
        "pages/tech_sheet_public.html",
        {
            "request": request,
            "ts": _serialize(ts, project),
            "project": project,
            "delivery_template": ts.delivery_template,
        },
    )
