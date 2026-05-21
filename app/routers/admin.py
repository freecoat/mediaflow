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
from app.context import current_tenant_id


router = APIRouter(prefix="/admin", tags=["admin"])



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


# ── Cestino (v3.5.0-alpha.7) ───────────────────────────────────

@router.get("/cestino", response_class=HTMLResponse)
async def admin_trash_page(request: Request,
                           _: User = Depends(requires_permission("view_trash"))):
    return _tpl().TemplateResponse("pages/admin_trash.html", {"request": request})


@router.get("/api/trash")
async def list_trash(
    request: Request, db: Session = Depends(get_db),
    _: User = Depends(requires_permission("view_trash")),
):
    """Lista record nel cestino, raggruppati per entity_type."""
    from app.models.models import Quote, Project, JobCostLine, Booking, BookingStatus
    out: dict[str, list[dict]] = {"quote": [], "project": []}

    # ── Quote ──
    deleted_quotes = (db.query(Quote)
                        .execution_options(include_deleted=True)
                        .filter(Quote.deleted_at.isnot(None))
                        .order_by(Quote.deleted_at.desc())
                        .all())
    for q in deleted_quotes:
        deleter = (db.query(User).filter(User.id == q.deleted_by_user_id).first()
                   if q.deleted_by_user_id else None)
        active_bookings = 0
        if q.job:
            active_bookings = (db.query(Booking)
                                 .join(JobCostLine, Booking.job_cost_line_id == JobCostLine.id)
                                 .filter(JobCostLine.job_id == q.job.id,
                                         Booking.status != BookingStatus.cancelled)
                                 .count())
        out["quote"].append({
            "id":            q.id,
            "label":         f"{q.number} — {q.title}",
            "project_code":  q.project.code if q.project else None,
            "project_id":    q.project_id,
            "client_name":   q.client.name if q.client else None,
            "deleted_at":    q.deleted_at.isoformat() if q.deleted_at else None,
            "deleted_by":    deleter.full_name if deleter else (deleter.email if deleter else None),
            "lines_count":   len(q.lines),
            "had_job":       bool(q.job),
            "active_bookings_on_job": active_bookings,
            "status":        q.status.value if hasattr(q.status, "value") else str(q.status),
        })

    # ── Project ──
    deleted_projects = (db.query(Project)
                          .execution_options(include_deleted=True)
                          .filter(Project.deleted_at.isnot(None))
                          .order_by(Project.deleted_at.desc())
                          .all())
    for p in deleted_projects:
        deleter = (db.query(User).filter(User.id == p.deleted_by_user_id).first()
                   if p.deleted_by_user_id else None)
        # quote totali (anche cestinate)
        all_quotes = (db.query(Quote)
                        .execution_options(include_deleted=True)
                        .filter(Quote.project_id == p.id).count())
        out["project"].append({
            "id":           p.id,
            "label":        f"{p.code} — {p.title}",
            "client_name":  p.client.name if p.client else None,
            "deleted_at":   p.deleted_at.isoformat() if p.deleted_at else None,
            "deleted_by":   deleter.full_name if deleter else (deleter.email if deleter else None),
            "quotes_count": all_quotes,
            "status":       p.status.value if hasattr(p.status, "value") else str(p.status),
        })
    return out


@router.post("/api/trash/{entity_type}/{entity_id}/restore")
async def trash_restore(
    entity_type: str, entity_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("restore_trash")),
):
    if entity_type == "quote":
        from app.services.soft_delete import fetch_quote_including_trash, restore_quote
        q = fetch_quote_including_trash(db, entity_id)
        if not q:
            raise HTTPException(404)
        result = restore_quote(db, q)
        db.commit()
        return result
    if entity_type == "project":
        from app.services.soft_delete import fetch_project_including_trash, restore_project
        p = fetch_project_including_trash(db, entity_id)
        if not p:
            raise HTTPException(404)
        result = restore_project(db, p)
        db.commit()
        return result
    raise HTTPException(400, f"entity_type sconosciuto: {entity_type}")


@router.get("/api/trash/expiry-info")
async def trash_expiry_info(
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("view_trash")),
):
    """Ritorna (a) retention_days configurato; (b) preview dry-run dei
    record che verrebbero purgati ora. Usato dalla UI per il banner header
    e il dialog di conferma del bottone 'Purga scaduti'."""
    from app.services.soft_delete import purge_expired_trash
    from app.config import settings as cfg
    info = purge_expired_trash(db, dry_run=True)
    info["retention_days_configured"] = int(getattr(cfg, "trash_retention_days", 30) or 0)
    return info


@router.post("/api/trash/purge-expired")
async def trash_purge_expired(
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("purge_total")),
):
    """Esegue purge cascade dei record con `deleted_at < now - retention_days`.

    Idempotente: se nessun record scaduto, ritorna `{quotes_purged: 0, ...}`.
    Se `retention_days=0` (cestino infinito) skippa tutto.
    """
    from app.services.soft_delete import purge_expired_trash
    result = purge_expired_trash(db, dry_run=False)
    db.commit()
    return result


@router.delete("/api/trash/{entity_type}/{entity_id}")
async def trash_purge(
    entity_type: str, entity_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("purge_total")),
):
    """Hard-delete definitivo dal cestino. Riusa lo stesso engine
    `soft_delete_*(force=True)` con cascade completo.
    """
    from app.services.rbac import current_user_optional
    user = current_user_optional(request)

    if entity_type == "quote":
        from app.services.soft_delete import (
            fetch_quote_including_trash, soft_delete_quote,
        )
        q = fetch_quote_including_trash(db, entity_id)
        if not q:
            raise HTTPException(404)
        result = soft_delete_quote(db, q, user=user, force=True)
        db.commit()
        return result
    if entity_type == "project":
        from app.services.soft_delete import (
            fetch_project_including_trash, soft_delete_project,
        )
        p = fetch_project_including_trash(db, entity_id)
        if not p:
            raise HTTPException(404)
        result = soft_delete_project(db, p, user=user, force=True)
        db.commit()
        return result
    raise HTTPException(400, f"entity_type sconosciuto: {entity_type}")


# ── API system maintenance ─────────────────────────────────────
@router.post("/api/check-deadlines")
async def trigger_deadline_check(
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_settings_global")),
):
    """Trigger on-demand del check job_deadline_approaching.

    Idempotente: se le notifiche per i job in scadenza sono già state emesse
    nelle ultime DEDUP_WINDOW_DAYS, ritorna 0.
    """
    from app.services.job_deadline_check import check_job_deadlines
    n = check_job_deadlines(db)
    return {"emitted": n, "checked_at": datetime.utcnow().isoformat()}


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
        "extra_permissions": u.extra_permissions or [],
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


@router.put("/api/users/{user_id}/permissions")
async def update_user_extra_permissions(
    user_id: int, request: Request,
    extra_permissions: str = Form(""),  # CSV
    db: Session = Depends(get_db),
    _: User = Depends(requires_permission("manage_users")),
):
    """Aggiorna i permessi extra (additivi) per un utente specifico.

    I permessi base sono dati dal ruolo. Questa lista è ADDITIVA: chiavi
    qui presenti vengono concesse al singolo utente in aggiunta a quelle
    del ruolo. Non è possibile sottrarre permessi del ruolo da qui.
    """
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Utente non trovato")
    perms = [p.strip() for p in extra_permissions.split(",") if p.strip()]
    invalid = [p for p in perms if p not in ALL_PERMISSION_KEYS]
    if invalid:
        raise HTTPException(400, f"Permessi non validi: {', '.join(invalid)}")
    # Pulizia: scarta quelli già presenti nel ruolo (ridondanti)
    role_perms: set = set()
    if u.role_obj and u.role_obj.permissions:
        role_perms = set(u.role_obj.permissions)
    cleaned = sorted(set(perms) - role_perms)
    u.extra_permissions = cleaned if cleaned else None
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
    roles = db.query(Role).filter(Role.tenant_id == current_tenant_id()).order_by(Role.is_system.desc(), Role.id).all()
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
        tenant_id=current_tenant_id(), code=code, name=name, description=description,
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


# ── Audit log TPN (v3.5.0-alpha.70.1) ──────────────────────────


@router.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(
    request: Request,
    _: User = Depends(requires_permission("manage_users")),
):
    """Pagina HTML audit log accessi asset DAM."""
    return _tpl().TemplateResponse(
        "pages/admin_audit_log.html", {"request": request}
    )


@router.get("/api/audit-log")
async def list_audit_log(
    request: Request,
    db: Session = Depends(get_db),
    asset_id: Optional[int] = None,
    project_id: Optional[int] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    _: User = Depends(requires_permission("manage_users")),
):
    from app.models import AssetAccessLog, AssetAccessAction, Asset
    q = db.query(AssetAccessLog).order_by(AssetAccessLog.ts.desc())
    if asset_id: q = q.filter(AssetAccessLog.asset_id == asset_id)
    if project_id: q = q.filter(AssetAccessLog.project_id == project_id)
    if user_id: q = q.filter(AssetAccessLog.user_id == user_id)
    if action:
        try:
            act = AssetAccessAction(action)
            q = q.filter(AssetAccessLog.action == act)
        except ValueError:
            raise HTTPException(400, f"Action non valida: {action}")
    rows = q.limit(min(limit, 500)).offset(offset).all()
    # Hydrate user + asset names
    user_ids = list({r.user_id for r in rows if r.user_id})
    asset_ids = list({r.asset_id for r in rows if r.asset_id})
    proj_ids = list({r.project_id for r in rows if r.project_id})
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids)).all()} if asset_ids else {}
    from app.models import Project as _P
    projects = {p.id: p for p in db.query(_P).filter(_P.id.in_(proj_ids)).all()} if proj_ids else {}
    return {
        "rows": [
            {
                "id": r.id,
                "ts": str(r.ts)[:19] if r.ts else None,
                "user_id": r.user_id,
                "user_email": (users.get(r.user_id).email if users.get(r.user_id) else None),
                "action": r.action.value if r.action else None,
                "asset_id": r.asset_id,
                "asset_name": (assets.get(r.asset_id).original_name if assets.get(r.asset_id) else None),
                "project_id": r.project_id,
                "project_code": (projects.get(r.project_id).code if projects.get(r.project_id) else None),
                "ip_address": r.ip_address,
                "user_agent": (r.user_agent or "")[:80],
                "extra": r.extra,
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
        "count": len(rows),
    }


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


# ─────────────────────────────────────────────────────────────────
# v3.5.0-alpha.172.3 Restructure Sprint 3 — Hard-delete project cascade
# Workflow ADMIN-ONLY, irreversibile. Spec docs/RESTRUCTURE_2026_05_20.md
# sezione 6.
# ─────────────────────────────────────────────────────────────────

@router.delete("/projects/{project_id}/hard-delete")
async def hard_delete_project_endpoint(
    project_id: int,
    confirm_token: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    user: User = Depends(requires_permission("hard_delete_project")),
):
    """Hard-delete cascade FULL di un progetto + tutto l'albero correlato
    (Quote, Job, JCL, Booking, Invoice, Asset, Deliverable, ...).

    Pensato SOLO per workflow test/cleanup admin. Per produzione standard
    usa soft-delete (cestino).

    Anti-misclick: il body deve contenere `confirm_token` = `"DELETE-{code}"`.
    Esempio: project.code='TEST-001' -> confirm_token='DELETE-TEST-001'.

    Returns: counters per tabella + project_code.
    """
    from app.models import Project
    from app.services.project_purge import hard_delete_project

    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project non trovato")

    expected = f"DELETE-{proj.code}"
    if confirm_token != expected:
        raise HTTPException(
            400,
            f"confirm_token non valido. Atteso esattamente '{expected}'."
        )

    try:
        report = hard_delete_project(db, project_id, actor_user_id=user.id)
        db.commit()
        return report
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Hard-delete fallito: {e}")


# ─────────────────────────────────────────────────────────────────
# v3.5.0-alpha.172.9 (Sprint 5 T1+T2) — Restructure migration tools
# Migra JCL legacy non-time-based → JobDeliverable runtime (vs script CLI).
# ADMIN-only (proxy: permesso `hard_delete_project`).
# ─────────────────────────────────────────────────────────────────

@router.get("/restructure-migration", response_class=HTMLResponse)
async def restructure_migration_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(requires_permission("hard_delete_project")),
):
    """UI admin per migrare JCL residuali → JobDeliverable singolarmente o batch."""
    return _tpl().TemplateResponse(
        "pages/admin_restructure_migration.html",
        {"request": request},
    )


@router.get("/api/restructure/legacy-jcl-scan")
async def restructure_legacy_jcl_scan(
    db: Session = Depends(get_db),
    user: User = Depends(requires_permission("hard_delete_project")),
):
    """Ritorna lista JCL non-time candidate per migrazione."""
    from app.services.jcl_to_deliverable_migrator import scan_legacy_jcl
    candidates = scan_legacy_jcl(db)
    return {
        "count": len(candidates),
        "candidates": candidates,
    }


@router.post("/api/restructure/migrate-jcl/{jcl_id}")
async def restructure_migrate_jcl(
    jcl_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(requires_permission("hard_delete_project")),
):
    """Migra UNA JCL legacy → JobDeliverable. Idempotente."""
    from app.services.jcl_to_deliverable_migrator import migrate_jcl_to_deliverable
    try:
        result = migrate_jcl_to_deliverable(db, jcl_id)
        if result.get("migrated"):
            db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Migrazione fallita: {e}")


@router.post("/api/restructure/migrate-all")
async def restructure_migrate_all(
    db: Session = Depends(get_db),
    user: User = Depends(requires_permission("hard_delete_project")),
):
    """Batch: migra TUTTE le JCL legacy non-time del tenant."""
    from app.services.jcl_to_deliverable_migrator import migrate_all_legacy
    try:
        summary = migrate_all_legacy(db)
        db.commit()
        return summary
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Migrazione batch fallita: {e}")


@router.post("/api/restructure/notify-admins")
async def restructure_notify_admins(
    db: Session = Depends(get_db),
    user: User = Depends(requires_permission("hard_delete_project")),
):
    """Trigger manuale notifica admin se trova JCL legacy residuali.
    Idempotente: skip se notifica unread già pending."""
    from app.services.jcl_to_deliverable_migrator import notify_admins_if_legacy
    try:
        result = notify_admins_if_legacy(db)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Notifica fallita: {e}")

