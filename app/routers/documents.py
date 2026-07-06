# app/routers/documents.py
"""Router documenti collegati — Fase D (v3.5.0-alpha.172.243).

Collega file Google Drive a progetti/acquisitions via incolla-link o Picker,
salvando solo un riferimento (metadata + link). Tenant-scoped, soft-delete,
RBAC runtime per linked_type. Best-effort: metadata assenti → fallback name."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.context import current_tenant_id
from app.models.models import DocumentLink, Project, Acquisition
from app.services.rbac import has_permission, current_user, current_user_optional
from app.services.tenant_guard import scoped, fetch_or_404
from app.services import google_drive
from app.services.oauth_providers import get_valid_access_token

router = APIRouter(tags=["documents"])

# NB: tenant dal contesto (current_tenant_id()), come calendar.py/acquisitions.py.
# scoped()/fetch_or_404() applicano il filtro tenant internamente — NON passare
# un tenant_id come kwarg (fetch_or_404 non lo accetta).

# linked_type → (modello, perm_view, perm_manage)
_ENTITY = {
    "project": (Project, "view_projects", "edit_projects"),
    "acquisition": (Acquisition, "view_acquisitions", "manage_acquisitions"),
}


def _serialize_doc(d: DocumentLink) -> dict:
    return {
        "id": d.id, "provider": d.provider, "external_file_id": d.external_file_id,
        "name": d.name, "mime_type": d.mime_type, "web_url": d.web_url,
        "icon_url": d.icon_url, "owner_email": d.owner_email,
        "project_id": d.project_id, "acquisition_id": d.acquisition_id,
    }


def _resolve_entity(linked_type: str):
    ent = _ENTITY.get(linked_type)
    if not ent:
        raise HTTPException(400, f"linked_type non valido: {linked_type}")
    return ent


def _safe_url(u: Optional[str]) -> str:
    u = (u or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else ""


@router.post("/documents/api/link")
async def link_document(request: Request, db: Session = Depends(get_db),
                        linked_type: str = Form(...), linked_id: int = Form(...),
                        url: Optional[str] = Form(None),
                        file_id: Optional[str] = Form(None),
                        name: Optional[str] = Form(None),
                        mime_type: Optional[str] = Form(None),
                        web_url: Optional[str] = Form(None),
                        icon_url: Optional[str] = Form(None)):
    user = current_user(request)
    model, _pv, perm_manage = _resolve_entity(linked_type)
    if not has_permission(user, perm_manage):
        raise HTTPException(403, "Permesso negato")
    # entità esiste + tenant-scoped (fetch_or_404 usa current_tenant_id() internamente)
    fetch_or_404(db, model, linked_id)

    fid = (file_id or "").strip()
    d_name = (name or "").strip()
    d_web = _safe_url(web_url)
    d_mime = mime_type
    d_icon = icon_url
    d_owner = None

    if not fid:  # modo incolla-link
        parsed = google_drive.parse_drive_file_id(url or "")
        if not parsed:
            raise HTTPException(400, "URL Drive non riconosciuto")
        fid = parsed
        md = google_drive.fetch_file_metadata(db, user.id, fid)
        if md:
            d_name = md["name"] or d_name
            d_mime = md["mime_type"]
            d_web = _safe_url(md["web_url"]) or _safe_url(url)
            d_icon = md["icon_url"]
            d_owner = md["owner_email"]
        else:  # fallback: file non accessibile via drive.file
            d_web = _safe_url(url)
            d_name = d_name or "Documento Drive"
    if not d_name:
        d_name = "Documento Drive"
    if not d_web:
        d_web = "https://drive.google.com/file/d/" + fid + "/view"

    doc = DocumentLink(tenant_id=current_tenant_id(), provider="google", external_file_id=fid,
                       name=d_name, mime_type=d_mime, web_url=d_web, icon_url=d_icon,
                       owner_email=d_owner, added_by=user.id)
    setattr(doc, f"{linked_type}_id", linked_id)
    db.add(doc); db.commit(); db.refresh(doc)
    return _serialize_doc(doc)


@router.get("/documents/api/list")
async def list_documents(request: Request, linked_type: str, linked_id: int,
                         db: Session = Depends(get_db)):
    user = current_user(request)
    _model, perm_view, _pm = _resolve_entity(linked_type)
    if not has_permission(user, perm_view):
        raise HTTPException(403, "Permesso negato")
    q = scoped(db.query(DocumentLink), DocumentLink).filter(
        getattr(DocumentLink, f"{linked_type}_id") == linked_id,
        DocumentLink.is_active == True,  # noqa: E712
    ).order_by(DocumentLink.created_at.desc())
    return {"documents": [_serialize_doc(d) for d in q.all()]}


@router.delete("/documents/api/link/{doc_id}")
async def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    doc = fetch_or_404(db, DocumentLink, doc_id)
    linked_type = ("project" if doc.project_id else "acquisition" if doc.acquisition_id
                   else "project")
    _model, _pv, perm_manage = _resolve_entity(linked_type)
    if not has_permission(user, perm_manage):
        raise HTTPException(403, "Permesso negato")
    doc.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/documents/api/picker-config")
async def picker_config(request: Request, db: Session = Depends(get_db)):
    user = current_user_optional(request)
    api_key = os.getenv("GOOGLE_PICKER_API_KEY", "").strip()
    if not user or not api_key:
        return {"enabled": False}
    token = get_valid_access_token(db, user.id, "google")
    if not token:
        return {"enabled": False}
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    app_id = client_id.split("-", 1)[0] if "-" in client_id else client_id
    return {"enabled": True, "api_key": api_key, "app_id": app_id, "oauth_token": token}
