"""Router Portale Cliente — v3.5.0-alpha.97 (#10 fase A).

Auth separata dal sistema admin. Il cliente accede via magic link (token
random 64-hex). Cookie `portal_token` (httponly, 7gg default). Vede solo
progetti del SUO `client_id`.

Endpoint:
- POST /portal/api/access — admin crea accesso per cliente (genera token,
  ritorna link da inviare via email/manualmente)
- GET /portal/login?token=X — valida token + setta cookie + redirect
- POST /portal/logout — pulisce cookie
- GET /portal/ — dashboard (lista progetti del cliente)
- GET /portal/project/{id} — scheda progetto read-only
- GET /portal/api/me — info accesso corrente (debug/UI)

Niente endpoint mutator: il cliente è SOLO lettore.
"""
from __future__ import annotations
from app.services.clock import now_utc
from app.config import settings
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    ClientPortalAccess, Client, Project, Asset, Invoice,
)
from app.services.rbac import requires_permission
from app.context import current_tenant_id

router = APIRouter(prefix="/portal", tags=["portal"])

PORTAL_COOKIE = "portal_token"
PORTAL_TOKEN_DAYS = 7

RequireAdminLink = Depends(requires_permission("manage_settings_global"))


# ── Helpers ───────────────────────────────────────────────────────


def _tpl():
    from app.main import templates
    return templates


def _resolve_portal_access(token: Optional[str], db: Session) -> Optional[ClientPortalAccess]:
    if not token:
        return None
    a = db.query(ClientPortalAccess).filter(
        ClientPortalAccess.token == token,
        ClientPortalAccess.tenant_id == current_tenant_id(),
        ClientPortalAccess.is_active == True,  # noqa: E712
        ClientPortalAccess.revoked_at.is_(None),
    ).first()
    if not a:
        return None
    if a.expires_at and a.expires_at < now_utc():
        return None
    return a


def _require_portal(request: Request, db: Session) -> ClientPortalAccess:
    token = request.cookies.get(PORTAL_COOKIE)
    a = _resolve_portal_access(token, db)
    if not a:
        raise HTTPException(401, "Accesso portale non valido o scaduto")
    return a


def _accessible_project_ids(access: ClientPortalAccess, db: Session) -> list[int]:
    if access.project_scope:
        return [int(x) for x in access.project_scope]
    rows = db.query(Project.id).filter(
        Project.tenant_id == current_tenant_id(),
        Project.client_id == access.client_id,
    ).all()
    return [r[0] for r in rows]


# ── Admin: crea accesso (link da inviare al cliente) ─────────────


@router.post("/api/access", dependencies=[RequireAdminLink])
async def create_access(
    request: Request,
    client_id: int = Form(...),
    email: str = Form(...),
    full_name: Optional[str] = Form(None),
    project_scope_json: Optional[str] = Form(None),  # JSON array project_id
    expires_days: int = Form(PORTAL_TOKEN_DAYS),
    db: Session = Depends(get_db),
):
    """Admin crea accesso portale per un cliente. Ritorna URL completo
    da inviare al cliente (per ora via email manuale)."""
    import json as _json
    c = db.query(Client).filter(
        Client.id == client_id, Client.tenant_id == current_tenant_id(),
    ).first()
    if not c:
        raise HTTPException(404, "Cliente non trovato")
    scope = None
    if project_scope_json:
        try:
            scope = _json.loads(project_scope_json)
        except _json.JSONDecodeError:
            raise HTTPException(400, "project_scope_json malformato")
        if not isinstance(scope, list):
            raise HTTPException(400, "project_scope_json deve essere array")
    token = secrets.token_hex(32)  # 64 hex chars
    expires = now_utc() + timedelta(days=max(1, min(expires_days, 365)))
    user = getattr(request.state, "current_user", None)
    a = ClientPortalAccess(
        tenant_id=current_tenant_id(),
        client_id=c.id,
        email=email.strip().lower()[:255],
        full_name=(full_name or "").strip() or None,
        token=token,
        project_scope=scope,
        expires_at=expires,
        created_by_user_id=user.id if user else None,
    )
    db.add(a); db.commit(); db.refresh(a)
    # Build URL (base_url dalla request)
    base = str(request.base_url).rstrip("/")
    link = f"{base}/portal/login?token={token}"
    return {
        "id": a.id,
        "client_id": c.id,
        "client_name": c.name,
        "email": a.email,
        "token": token,
        "magic_link": link,
        "expires_at": a.expires_at.isoformat(),
        "project_scope": scope,
    }


@router.get("/api/access")
async def list_access(
    client_id: Optional[int] = None,
    include_revoked: int = 0,
    db: Session = Depends(get_db),
):
    """Lista accessi portale (admin view)."""
    q = db.query(ClientPortalAccess).filter(
        ClientPortalAccess.tenant_id == current_tenant_id(),
    )
    if client_id:
        q = q.filter(ClientPortalAccess.client_id == client_id)
    if not include_revoked:
        q = q.filter(ClientPortalAccess.revoked_at.is_(None))
    rows = q.order_by(ClientPortalAccess.created_at.desc()).all()
    cli_map = {c.id: c for c in db.query(Client).filter(
        Client.id.in_([r.client_id for r in rows])
    ).all()} if rows else {}
    return [{
        "id": r.id,
        "client_id": r.client_id,
        "client_name": cli_map.get(r.client_id).name if cli_map.get(r.client_id) else None,
        "email": r.email,
        "full_name": r.full_name,
        "is_active": r.is_active,
        "created_at": str(r.created_at)[:19] if r.created_at else None,
        "expires_at": str(r.expires_at)[:19] if r.expires_at else None,
        "last_seen_at": str(r.last_seen_at)[:19] if r.last_seen_at else None,
        "project_scope": r.project_scope,
        "revoked_at": str(r.revoked_at)[:19] if r.revoked_at else None,
    } for r in rows]


@router.post("/api/access/{access_id}/revoke", dependencies=[RequireAdminLink])
async def revoke_access(access_id: int, db: Session = Depends(get_db)):
    a = db.query(ClientPortalAccess).filter(
        ClientPortalAccess.id == access_id,
        ClientPortalAccess.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404)
    a.is_active = False
    a.revoked_at = now_utc()
    db.commit()
    return {"ok": True}


# ── Login flow ────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def portal_login(
    request: Request,
    token: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Valida token + setta cookie + redirect a /portal/. Se token mancante
    o invalido, mostra pagina di errore (senza esporre dettagli)."""
    if not token:
        return _tpl().TemplateResponse(
            "pages/portal_login.html",
            {"request": request, "error": "Token mancante"},
            status_code=400,
        )
    a = _resolve_portal_access(token, db)
    if not a:
        return _tpl().TemplateResponse(
            "pages/portal_login.html",
            {"request": request, "error": "Link non valido o scaduto. Contatta il tuo referente."},
            status_code=401,
        )
    a.last_seen_at = now_utc()
    db.commit()
    resp = RedirectResponse(url="/portal/", status_code=303)
    max_age = int((a.expires_at - now_utc()).total_seconds()) if a.expires_at else 7 * 86400
    resp.set_cookie(
        key=PORTAL_COOKIE,
        value=token,
        httponly=True,
        max_age=max(60, max_age),
        samesite="lax",
        secure=(settings.app_env == "production"),  # α.172.172 — HTTPS-only in prod
    )
    return resp


@router.post("/logout")
async def portal_logout():
    resp = RedirectResponse(url="/portal/login", status_code=303)
    resp.delete_cookie(PORTAL_COOKIE)
    return resp


# ── Portale: dashboard cliente ───────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def portal_home(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(PORTAL_COOKIE)
    a = _resolve_portal_access(token, db)
    if not a:
        return RedirectResponse(url="/portal/login", status_code=303)
    a.last_seen_at = now_utc()
    db.commit()
    project_ids = _accessible_project_ids(a, db)
    projects = db.query(Project).filter(
        Project.id.in_(project_ids),
    ).order_by(Project.created_at.desc()).all() if project_ids else []
    client = db.query(Client).filter(Client.id == a.client_id).first()
    return _tpl().TemplateResponse(
        "pages/portal_home.html",
        {
            "request": request,
            "access": a, "client": client,
            "projects": projects,
        },
    )


@router.get("/project/{project_id}", response_class=HTMLResponse)
async def portal_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    a = _require_portal(request, db)
    ids = _accessible_project_ids(a, db)
    if project_id not in ids:
        raise HTTPException(403, "Progetto non accessibile dal tuo profilo portale")
    p = db.query(Project).options(
        joinedload(Project.client),
        joinedload(Project.milestones),
    ).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404)
    # Assets visibili: project_id = p.id, NO internal queue
    assets = db.query(Asset).filter(
        Asset.tenant_id == current_tenant_id(),
        Asset.project_id == project_id,
        Asset.parent_asset_id.is_(None),
    ).order_by(Asset.created_at.desc()).limit(200).all()
    return _tpl().TemplateResponse(
        "pages/portal_project.html",
        {
            "request": request,
            "access": a,
            "project": p,
            "assets": assets,
        },
    )


@router.get("/api/me")
async def portal_me(request: Request, db: Session = Depends(get_db)):
    a = _require_portal(request, db)
    c = db.query(Client).filter(Client.id == a.client_id).first()
    return {
        "access_id": a.id,
        "email": a.email,
        "full_name": a.full_name,
        "client_id": a.client_id,
        "client_name": c.name if c else None,
        "expires_at": str(a.expires_at)[:19] if a.expires_at else None,
        "project_scope_count": len(a.project_scope) if a.project_scope else None,
    }
