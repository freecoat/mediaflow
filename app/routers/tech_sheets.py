"""Router scheda tecnica progetto (v3.4.31, edit link α.172.28).

Workflow sheet di un progetto: catena di lavorazione (camere, audio, look,
storage, dailies, crew, process). Schema flessibile JSON.

- `GET    /projects/api/{pid}/tech-sheet` — JSON (auto-crea draft se manca)
- `PUT    /projects/api/{pid}/tech-sheet` — sostituisce data + campi metadata
- `POST   /projects/api/{pid}/tech-sheet/publish` — genera/rigenera token readonly
- `DELETE /projects/api/{pid}/tech-sheet/public` — disattiva link readonly
- `POST   /projects/api/{pid}/tech-sheet/publish-edit` — genera/rigenera token EDIT
- `DELETE /projects/api/{pid}/tech-sheet/public-edit` — disattiva link EDIT
- `GET    /projects/api/{pid}/tech-sheet/edit-logs` — audit modifiche pubbliche
- `GET    /public/tech-sheet/{token}` — vista pubblica readonly (no auth)
- `GET    /public/tech-sheet/{edit_token}/edit` — editor pubblico (no auth)
- `PUT    /public/tech-sheet/{edit_token}` — save granulare con identità editor
- `GET    /public/tech-sheet/{edit_token}/state` — polling updated_at + recent logs
"""
from __future__ import annotations
from datetime import datetime, timedelta
import secrets
import re
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Body
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    Project, ProjectTechSheet, DeliveryTemplate, Resource, User,
    TechSheetEditLog,
)
from app.services.rbac import current_user_optional, can_view_finance, has_permission
from app.context import current_tenant_id

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

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
        "is_public_edit_enabled": ts.is_public_edit_enabled,
        "edit_token": ts.edit_token if ts.is_public_edit_enabled else None,
        "edit_expires_at": ts.edit_expires_at.isoformat() if ts.edit_expires_at else None,
        "edit_published_at": ts.edit_published_at.isoformat() if ts.edit_published_at else None,
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


def _is_edit_token_alive(ts: ProjectTechSheet) -> bool:
    if not ts.is_public_edit_enabled or not ts.edit_token:
        return False
    if ts.edit_expires_at and ts.edit_expires_at < datetime.utcnow():
        return False
    return True


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("cf-connecting-ip")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host[:64]
    return None


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


@router.post("/projects/api/{project_id}/tech-sheet/publish-edit")
async def publish_tech_sheet_edit(
    project_id: int,
    request: Request,
    expires_days: Optional[int] = Form(30),
    rotate_token: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Abilita link pubblico EDITABILE (α.172.28).

    - `expires_days=0` o vuoto → senza scadenza.
    - `rotate_token=true` → rigenera (link vecchio invalidato).
    - Default scadenza 30gg (vs 90gg readonly): più stretta per sicurezza.
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

    if rotate_token or not ts.edit_token:
        ts.edit_token = secrets.token_urlsafe(32)
    ts.is_public_edit_enabled = True
    ts.edit_published_at = datetime.utcnow()
    if expires_days and int(expires_days) > 0:
        ts.edit_expires_at = datetime.utcnow() + timedelta(days=int(expires_days))
    else:
        ts.edit_expires_at = None
    db.commit(); db.refresh(ts)
    return {
        "edit_token": ts.edit_token,
        "is_public_edit_enabled": ts.is_public_edit_enabled,
        "edit_expires_at": ts.edit_expires_at.isoformat() if ts.edit_expires_at else None,
        "edit_published_at": ts.edit_published_at.isoformat() if ts.edit_published_at else None,
    }


@router.delete("/projects/api/{project_id}/tech-sheet/public-edit")
async def unpublish_tech_sheet_edit(
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
    ts.is_public_edit_enabled = False
    ts.edit_expires_at = None
    db.commit()
    return {"ok": True}


@router.get("/projects/api/{project_id}/tech-sheet/edit-logs")
async def tech_sheet_edit_logs(
    project_id: int,
    request: Request,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not has_permission(user, "view_projects") and not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Permesso negato")
    p = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    ts = db.query(ProjectTechSheet).filter(ProjectTechSheet.project_id == project_id).first()
    if not ts:
        return {"logs": []}
    logs = db.query(TechSheetEditLog).filter(
        TechSheetEditLog.tech_sheet_id == ts.id,
    ).order_by(TechSheetEditLog.edited_at.desc()).limit(min(max(limit, 1), 500)).all()
    return {
        "logs": [{
            "id": l.id,
            "editor_name": l.editor_name,
            "editor_email": l.editor_email,
            "ip_address": l.ip_address,
            "section_keys": l.section_keys,
            "summary": l.summary,
            "edited_at": l.edited_at.isoformat() if l.edited_at else None,
        } for l in logs]
    }


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


# ── Editor pubblico (no auth) — α.172.28 ──────────────────────
@router.get("/public/tech-sheet/{edit_token}/edit", response_class=HTMLResponse)
async def public_tech_sheet_edit(
    edit_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    ts = db.query(ProjectTechSheet).options(
        joinedload(ProjectTechSheet.project).joinedload(Project.client),
        joinedload(ProjectTechSheet.delivery_template),
    ).filter(ProjectTechSheet.edit_token == edit_token).first()
    if not ts or not _is_edit_token_alive(ts):
        reason = "expired" if (ts and ts.edit_expires_at and ts.edit_expires_at < datetime.utcnow()) else "not_found"
        return _tpl().TemplateResponse(
            "pages/tech_sheet_public_error.html",
            {"request": request, "reason": reason},
            status_code=410 if ts else 404,
        )
    project = ts.project
    return _tpl().TemplateResponse(
        "pages/tech_sheet_public_edit.html",
        {
            "request": request,
            "ts": _serialize(ts, project),
            "project": project,
            "delivery_template": ts.delivery_template,
            "edit_token": edit_token,
        },
    )


@router.put("/public/tech-sheet/{edit_token}")
async def public_tech_sheet_save(
    edit_token: str,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Save granulare da editor pubblico.

    Payload: `{editor_name, editor_email, sections: {key: value, ...}}`.
    Merge top-level: solo sezioni in `sections` sovrascrivono. Le altre
    restano come sono (concorrenza last-write-wins per-sezione, vedi memo
    `project_session_22mag2026` per design).
    """
    ts = db.query(ProjectTechSheet).filter(
        ProjectTechSheet.edit_token == edit_token,
    ).first()
    if not ts or not _is_edit_token_alive(ts):
        raise HTTPException(410 if ts else 404, "Link non valido o scaduto")

    editor_name = (payload.get("editor_name") or "").strip()[:200]
    editor_email = (payload.get("editor_email") or "").strip().lower()[:200]
    sections = payload.get("sections") or {}
    if not editor_name or len(editor_name) < 2:
        raise HTTPException(422, "Nome obbligatorio")
    if not editor_email or not _EMAIL_RE.match(editor_email):
        raise HTTPException(422, "Email non valida")
    if not isinstance(sections, dict) or not sections:
        raise HTTPException(422, "Nessuna sezione da salvare")

    # Merge top-level: solo chiavi note in DEFAULT_DATA
    new_data = dict(ts.data or {})
    accepted: list[str] = []
    for key, val in sections.items():
        if key in DEFAULT_DATA:
            new_data[key] = val
            accepted.append(key)
    if not accepted:
        raise HTTPException(422, "Nessuna sezione valida")
    ts.data = new_data

    log = TechSheetEditLog(
        tech_sheet_id=ts.id,
        editor_name=editor_name,
        editor_email=editor_email,
        ip_address=_client_ip(request),
        section_keys=",".join(accepted)[:500],
        summary=(payload.get("summary") or None),
    )
    db.add(log)
    db.commit(); db.refresh(ts); db.refresh(log)
    return {
        "ok": True,
        "saved_sections": accepted,
        "updated_at": ts.updated_at.isoformat() if ts.updated_at else None,
        "log_id": log.id,
    }


@router.get("/public/tech-sheet/{edit_token}/field-options")
async def public_tech_sheet_field_options(
    edit_token: str, db: Session = Depends(get_db),
):
    """α.172.34 — Opzioni dropdown per editor pubblico (no-auth, gated da token).
    Ritorna mappa field_path → [{value, label}, ...]."""
    ts = db.query(ProjectTechSheet).filter(
        ProjectTechSheet.edit_token == edit_token,
    ).first()
    if not ts or not _is_edit_token_alive(ts):
        raise HTTPException(410 if ts else 404, "Link non valido o scaduto")
    from app.models import TechSheetFieldOption
    rows = db.query(TechSheetFieldOption).filter(
        TechSheetFieldOption.tenant_id == ts.tenant_id,
        TechSheetFieldOption.is_active == True,  # noqa: E712
    ).order_by(
        TechSheetFieldOption.field_path, TechSheetFieldOption.sort_order, TechSheetFieldOption.value,
    ).all()
    out: dict[str, list] = {}
    for o in rows:
        out.setdefault(o.field_path, []).append({"value": o.value, "label": o.label or o.value})
    return out


@router.get("/public/tech-sheet/{edit_token}/state")
async def public_tech_sheet_state(
    edit_token: str,
    request: Request,
    since: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Polling concorrenza: ritorna updated_at + log nuovi dopo `since` (ISO).

    Frontend chiama ogni 30s. Se `updated_at_server > last_known` E
    log nuovi presenti → mostra banner con autore + sezioni cambiate.
    """
    ts = db.query(ProjectTechSheet).filter(
        ProjectTechSheet.edit_token == edit_token,
    ).first()
    if not ts or not _is_edit_token_alive(ts):
        raise HTTPException(410 if ts else 404, "Link non valido o scaduto")

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", ""))
        except Exception:
            since_dt = None

    q = db.query(TechSheetEditLog).filter(TechSheetEditLog.tech_sheet_id == ts.id)
    if since_dt:
        q = q.filter(TechSheetEditLog.edited_at > since_dt)
    logs = q.order_by(TechSheetEditLog.edited_at.desc()).limit(20).all()
    return {
        "updated_at": ts.updated_at.isoformat() if ts.updated_at else None,
        "logs": [{
            "editor_name": l.editor_name,
            "editor_email": l.editor_email,
            "section_keys": l.section_keys,
            "edited_at": l.edited_at.isoformat() if l.edited_at else None,
        } for l in logs],
    }
