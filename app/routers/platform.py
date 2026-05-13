"""Router Platform Super-Admin (v3.5.0-alpha.104).

Gestione cross-tenant: lista/crea/edit/revoca Tenant, gestione admin user
per tenant. Accesso riservato a `User.is_platform_admin=True` (super-admin
della piattaforma, tipicamente residente su tenant=1 Default).

Bypass tenant filter: gli endpoint qui usano query DIRETTE su Tenant/User
senza il filtro `tenant_id == current_tenant_id()`. Il super-admin vede
tutti i tenant.

Path: `/platform/*`. Separato dall'admin del tenant (`/admin/*` o
`/settings/*` che restano scoped al tenant corrente).
"""
from __future__ import annotations
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.config import settings
from app.models import Tenant, User, Department, UserRole
from app.services.auth import hash_password
from app.services.rbac import current_user_optional

router = APIRouter(prefix="/platform", tags=["platform"])


def _require_platform_admin(request: Request) -> User:
    user = current_user_optional(request)
    if not user or not getattr(user, "is_platform_admin", False):
        raise HTTPException(403, "Accesso riservato al super-admin platform")
    return user


def _tpl():
    from app.main import templates
    return templates


# ── HTML pagina ──────────────────────────────────────────────────


@router.get("/tenants", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def platform_home(request: Request, db: Session = Depends(get_db)):
    _require_platform_admin(request)
    return _tpl().TemplateResponse(
        "pages/platform_tenants.html",
        {"request": request, "active_page": "platform"},
    )


# ── API ───────────────────────────────────────────────────────────


@router.get("/api/tenants")
async def list_tenants(request: Request, db: Session = Depends(get_db)):
    """Lista tutti i tenant + counters (users, projects, clients)."""
    _require_platform_admin(request)
    from app.models import Project, Client
    rows = db.query(Tenant).order_by(Tenant.id.asc()).all()
    # Counters via group_by (singolo round-trip per metrica)
    user_counts = dict(db.query(User.tenant_id, func.count(User.id)).group_by(User.tenant_id).all())
    proj_counts = dict(db.query(Project.tenant_id, func.count(Project.id)).group_by(Project.tenant_id).all())
    cli_counts = dict(db.query(Client.tenant_id, func.count(Client.id)).group_by(Client.tenant_id).all())
    return [{
        "id": t.id, "slug": t.slug, "name": t.name,
        "legal_name": t.legal_name, "email": t.email,
        "is_active": t.is_active,
        "onboarding_completed": t.onboarding_completed,
        "created_at": str(t.created_at)[:19] if t.created_at else None,
        "users_count": user_counts.get(t.id, 0),
        "projects_count": proj_counts.get(t.id, 0),
        "clients_count": cli_counts.get(t.id, 0),
    } for t in rows]


@router.post("/api/tenants")
async def create_tenant(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    admin_email: str = Form(...),
    admin_name: str = Form(...),
    admin_password: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea Tenant + admin User + Department defaults + cartella uploads/t{id}/.
    Stessa logica di scripts/create_tenant.py."""
    _require_platform_admin(request)
    slug = slug.strip().lower()
    if not slug or not name.strip() or not admin_email.strip():
        raise HTTPException(400, "slug, name, admin_email obbligatori")
    if db.query(Tenant).filter(Tenant.slug == slug).first():
        raise HTTPException(409, f"Slug '{slug}' già esistente")
    # Crea Tenant
    t = Tenant(
        name=name.strip(), slug=slug,
        is_active=True, onboarding_completed=False,
    )
    db.add(t); db.flush()
    # Departments default
    DEFAULT_DEPARTMENTS = [
        ("DI", "Digital Intermediate", "#6272f5"),
        ("VFX", "Visual Effects", "#a78bfa"),
        ("AUDIO", "Audio Post", "#10b981"),
        ("COMM", "Commercial", "#fb923c"),
    ]
    for code, dname, color in DEFAULT_DEPARTMENTS:
        d = Department(
            tenant_id=t.id, code=code, name=dname, color=color, is_active=True,
        )
        db.add(d)
    # Admin user
    pwd = admin_password.strip() if admin_password else secrets.token_urlsafe(12)
    u = User(
        tenant_id=t.id,
        email=admin_email.strip().lower(),
        full_name=admin_name.strip(),
        hashed_password=hash_password(pwd),
        role=UserRole.admin,
        is_active=True,
    )
    db.add(u)
    # Cartella uploads
    upload_dir = Path(settings.upload_dir) / f"t{t.id}"
    (upload_dir / "assets").mkdir(parents=True, exist_ok=True)
    (upload_dir / "thumbnails").mkdir(parents=True, exist_ok=True)
    db.commit(); db.refresh(t)
    return {
        "id": t.id, "slug": t.slug, "name": t.name,
        "admin_email": u.email, "admin_password": pwd,
        "login_url_dev": f"http://{slug}.lvh.me:8000/auth/login",
        "login_url_fallback": f"http://localhost:8000/auth/login?tenant={slug}",
    }


@router.patch("/api/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: int,
    request: Request,
    name: Optional[str] = Form(None),
    slug: Optional[str] = Form(None),
    legal_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
):
    _require_platform_admin(request)
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        raise HTTPException(404, "Tenant non trovato")
    if slug is not None:
        slug = slug.strip().lower()
        if slug and slug != t.slug:
            if db.query(Tenant).filter(Tenant.slug == slug, Tenant.id != tenant_id).first():
                raise HTTPException(409, f"Slug '{slug}' già usato")
            t.slug = slug
    if name is not None and name.strip():
        t.name = name.strip()
    if legal_name is not None:
        t.legal_name = legal_name.strip() or None
    if email is not None:
        t.email = email.strip() or None
    if is_active is not None:
        t.is_active = bool(is_active)
    db.commit(); db.refresh(t)
    return {"id": t.id, "slug": t.slug, "name": t.name, "is_active": t.is_active}


@router.post("/api/tenants/{tenant_id}/revoke")
async def revoke_tenant(tenant_id: int, request: Request, db: Session = Depends(get_db)):
    """Disattiva (NON elimina). Dati restano in DB ma login bloccato +
    tenant_resolver fallback al Default se slug non più risolve."""
    _require_platform_admin(request)
    if tenant_id == 1:
        raise HTTPException(400, "Tenant Default non revocabile")
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        raise HTTPException(404)
    t.is_active = False
    db.commit()
    return {"ok": True, "tenant_id": t.id, "is_active": False}


@router.post("/api/tenants/{tenant_id}/reactivate")
async def reactivate_tenant(tenant_id: int, request: Request, db: Session = Depends(get_db)):
    _require_platform_admin(request)
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        raise HTTPException(404)
    t.is_active = True
    db.commit()
    return {"ok": True, "tenant_id": t.id, "is_active": True}


@router.get("/api/tenants/{tenant_id}/users")
async def list_tenant_users(tenant_id: int, request: Request, db: Session = Depends(get_db)):
    _require_platform_admin(request)
    users = db.query(User).filter(User.tenant_id == tenant_id).order_by(User.created_at.desc()).all()
    return [{
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "role": u.role.value if hasattr(u.role, "value") else str(u.role),
        "is_active": u.is_active,
        "is_platform_admin": getattr(u, "is_platform_admin", False),
        "created_at": str(u.created_at)[:19] if u.created_at else None,
        "last_login": str(u.last_login)[:19] if u.last_login else None,
    } for u in users]


@router.post("/api/tenants/{tenant_id}/admin-user")
async def create_admin_user(
    tenant_id: int,
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    password: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Aggiungi admin user a un tenant esistente."""
    _require_platform_admin(request)
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        raise HTTPException(404, "Tenant non trovato")
    email_norm = email.strip().lower()
    if db.query(User).filter(User.tenant_id == tenant_id, User.email == email_norm).first():
        raise HTTPException(409, f"User {email_norm} già esistente su tenant {t.slug}")
    pwd = password.strip() if password else secrets.token_urlsafe(12)
    u = User(
        tenant_id=tenant_id,
        email=email_norm,
        full_name=full_name.strip(),
        hashed_password=hash_password(pwd),
        role=UserRole.admin,
        is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return {
        "id": u.id, "email": u.email, "tenant_id": tenant_id,
        "password": pwd,
    }
