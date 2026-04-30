"""Router pannello amministrazione (v3.4.23).

Due aree, accessibili solo a chi ha rispettivamente:
  - /admin/users  : permission `manage_users`
  - /admin/roles  : permission `manage_roles`

Nessun altro vincolo di tenant qui (siamo single-tenant soft).
"""
from datetime import datetime
import secrets
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Form, Body
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import User, Role, Resource, UserRole
from app.services.auth import hash_password
from app.services.rbac import (
    PERMISSIONS, ALL_PERMISSION_KEYS, PRESET_PERMISSIONS, PRESET_DESCRIPTIONS,
    has_permission, current_user_optional, requires_permission,
)


router = APIRouter(prefix="/admin", tags=["admin"])

CURRENT_TENANT = 1


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ────────────────────────────────────────────────
@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, db: Session = Depends(get_db),
                           _: User = Depends(requires_permission("manage_users"))):
    return _tpl().TemplateResponse("pages/admin_users.html", {
        "request": request,
        "permissions_catalog": PERMISSIONS,
    })


@router.get("/roles", response_class=HTMLResponse)
async def admin_roles_page(request: Request, db: Session = Depends(get_db),
                           _: User = Depends(requires_permission("manage_roles"))):
    return _tpl().TemplateResponse("pages/admin_roles.html", {
        "request": request,
        "permissions_catalog": PERMISSIONS,
    })


# ── API utenti ─────────────────────────────────────────────────
def _user_dict(u: User) -> dict:
    role_obj = u.role_obj
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "is_active": u.is_active,
        "role_id": u.role_id,
        "role_code": role_obj.code if role_obj else (u.role.value if hasattr(u.role, "value") else None),
        "role_name": role_obj.name if role_obj else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "linked_resource_id": next((r.id for r in u.resources), None) if u.resources else None,
        "linked_resource_name": next((r.name for r in u.resources), None) if u.resources else None,
    }


@router.get("/api/users")
async def list_users(
    request: Request, db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_users")),
):
    users = db.query(User).options(joinedload(User.role_obj), joinedload(User.resources)).order_by(User.id).all()
    return [_user_dict(u) for u in users]


@router.post("/api/users")
async def create_user(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    role_id: int = Form(...),
    password: Optional[str] = Form(None),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_users")),
):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, f"Email già registrata: {email}")
    role = db.query(Role).filter(Role.id == role_id, Role.is_active == True).first()  # noqa: E712
    if not role:
        raise HTTPException(404, "Ruolo non trovato")
    pwd = password or _gen_temp_password()
    u = User(
        email=email, full_name=full_name, hashed_password=hash_password(pwd),
        role_id=role.id, is_active=is_active,
        # legacy enum: tenta il mapping inverso
        role=_role_code_to_enum(role.code),
    )
    db.add(u); db.commit(); db.refresh(u)
    return {**_user_dict(u), "temp_password": pwd if not password else None}


@router.put("/api/users/{user_id}")
async def update_user(
    user_id: int, request: Request,
    full_name: Optional[str] = Form(None),
    role_id: Optional[int] = Form(None),
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_users")),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Utente non trovato")
    if full_name is not None:
        u.full_name = full_name
    if role_id is not None:
        role = db.query(Role).filter(Role.id == role_id, Role.is_active == True).first()  # noqa: E712
        if not role:
            raise HTTPException(404, "Ruolo non trovato")
        u.role_id = role.id
        u.role = _role_code_to_enum(role.code)
    if is_active is not None:
        u.is_active = is_active
    db.commit(); db.refresh(u)
    return _user_dict(u)


@router.post("/api/users/{user_id}/reset-password")
async def reset_password(
    user_id: int, request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_users")),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Utente non trovato")
    new_pwd = _gen_temp_password()
    u.hashed_password = hash_password(new_pwd)
    db.commit()
    return {"ok": True, "temp_password": new_pwd, "email": u.email}


@router.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int, request: Request,
    db: Session = Depends(get_db),
    me: User = Depends(requires_permission("manage_users")),
):
    if user_id == me.id:
        raise HTTPException(400, "Non puoi eliminare te stesso")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Utente non trovato")
    # Soft delete preferito
    u.is_active = False
    db.commit()
    return {"ok": True}


# ── API ruoli ──────────────────────────────────────────────────
def _role_dict(r: Role, user_count: int = 0) -> dict:
    return {
        "id": r.id, "code": r.code, "name": r.name, "description": r.description,
        "permissions": r.permissions or [],
        "is_system": r.is_system, "is_active": r.is_active,
        "user_count": user_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/api/roles")
async def list_roles(
    request: Request, db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_roles")),
):
    roles = db.query(Role).filter(Role.tenant_id == CURRENT_TENANT).order_by(Role.is_system.desc(), Role.id).all()
    counts = dict(
        (rid, n) for rid, n in db.query(User.role_id, db.func.count(User.id) if hasattr(db, 'func') else None)
        .filter(User.role_id.isnot(None)).group_by(User.role_id).all()
    ) if False else {}
    # Workaround: count manuale
    from sqlalchemy import func
    rows = db.query(User.role_id, func.count(User.id)).filter(User.role_id.isnot(None), User.is_active == True).group_by(User.role_id).all()  # noqa: E712
    counts = {rid: n for rid, n in rows}
    return [_role_dict(r, counts.get(r.id, 0)) for r in roles]


@router.post("/api/roles")
async def create_role(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    permissions: str = Form(""),  # CSV
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_roles")),
):
    code = code.strip().lower()
    if not code or " " in code:
        raise HTTPException(400, "code deve essere lowercase senza spazi")
    if db.query(Role).filter(Role.code == code).first():
        raise HTTPException(400, f"Codice ruolo già esistente: {code}")
    perms = [p.strip() for p in permissions.split(",") if p.strip()]
    invalid = [p for p in perms if p not in ALL_PERMISSION_KEYS]
    if invalid:
        raise HTTPException(400, f"Permessi non validi: {', '.join(invalid)}")
    r = Role(
        tenant_id=CURRENT_TENANT, code=code, name=name, description=description,
        permissions=perms, is_system=False, is_active=True,
    )
    db.add(r); db.commit(); db.refresh(r)
    return _role_dict(r)


@router.put("/api/roles/{role_id}")
async def update_role(
    role_id: int, request: Request,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    permissions: Optional[str] = Form(None),  # CSV
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_roles")),
):
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(404, "Ruolo non trovato")
    # Admin role: permessi non modificabili (resta sempre full)
    if r.code == "admin" and permissions is not None:
        raise HTTPException(400, "I permessi del ruolo admin non sono modificabili")
    if name is not None: r.name = name
    if description is not None: r.description = description
    if permissions is not None:
        perms = [p.strip() for p in permissions.split(",") if p.strip()]
        invalid = [p for p in perms if p not in ALL_PERMISSION_KEYS]
        if invalid:
            raise HTTPException(400, f"Permessi non validi: {', '.join(invalid)}")
        r.permissions = perms
    if is_active is not None and not r.is_system:
        r.is_active = is_active
    db.commit(); db.refresh(r)
    return _role_dict(r)


@router.delete("/api/roles/{role_id}")
async def delete_role(
    role_id: int, request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_roles")),
):
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(404, "Ruolo non trovato")
    if r.is_system:
        raise HTTPException(400, "I ruoli built-in non possono essere eliminati (puoi disattivarli)")
    n_users = db.query(User).filter(User.role_id == role_id).count()
    if n_users > 0:
        raise HTTPException(400, f"Ruolo in uso da {n_users} utenti — riassegnali prima di eliminare")
    db.delete(r); db.commit()
    return {"ok": True}


# ── Helpers ────────────────────────────────────────────────────
def _gen_temp_password(length: int = 12) -> str:
    """Password temporanea sicura, alfanumerica readable."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _role_code_to_enum(code: str) -> UserRole:
    mapping = {
        "admin": UserRole.admin,
        "manager": UserRole.manager,
        "producer": UserRole.producer,
        "operator": UserRole.staff,  # back-compat enum
        "staff": UserRole.staff,
        "viewer": UserRole.viewer,
    }
    return mapping.get(code, UserRole.staff)
