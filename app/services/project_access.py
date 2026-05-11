"""v3.5.0-alpha.70 — Access control per progetto (TPN compliance).

Helper centralizzati per determinare se uno user può vedere o modificare
asset/dati di un progetto. Principio: need-to-know (compartimentalizzazione).

3 livelli di accesso (ordine di valutazione):
  1. Admin / manager → bypass (vedono tutto, action loggata).
  2. ProjectAccessGrant esplicito attivo (revoked_at IS NULL) → True.
  3. JobResourceAssignment per un job del project, via Resource.user_id
     legato all'user → True (auto-grant da pianificazione).
  4. Default → False.

Uso:
    from app.services.project_access import (
        user_can_access_project, accessible_project_ids,
        log_asset_access,
    )

    if not user_can_access_project(user, asset.project_id, db):
        raise HTTPException(403, "Accesso non autorizzato")
"""
from __future__ import annotations
from typing import Optional, Set
from datetime import datetime
from sqlalchemy.orm import Session

import ipaddress
from app.models import (
    User, Project, ProjectAccessGrant, JobResourceAssignment,
    Job, Resource, AssetAccessLog, AssetAccessAction,
)
from app.services.rbac import is_admin, is_manager
from app.context import current_tenant_id


CURRENT_TENANT = current_tenant_id()


def _client_ip(request) -> Optional[str]:
    """Estrae IP client dal request. Rispetta X-Forwarded-For per proxy."""
    if request is None:
        return None
    try:
        xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if xff:
            return xff
        return request.client.host if request.client else None
    except Exception:
        return None


def _ip_in_allowlist(ip: Optional[str], allowlist: Optional[list]) -> bool:
    """True se ip matcha almeno un CIDR/IP della allowlist.
    Allowlist None o vuoto → True (no restrizione)."""
    if not allowlist:
        return True
    if not ip:
        return False
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if "/" in str(entry):
                if ip_obj in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if ip_obj == ipaddress.ip_address(str(entry)):
                    return True
        except (ValueError, TypeError):
            continue
    return False


def check_project_ip_allowlist(
    project_id: Optional[int],
    request,
    db: Session,
) -> bool:
    """v3.5.0-alpha.70.3 — Verifica IP request contro project.ip_allowlist.
    True se OK o nessun progetto / no restrizione. False se ip NON matcha."""
    if not project_id:
        return True
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p or not p.ip_allowlist:
        return True
    ip = _client_ip(request)
    return _ip_in_allowlist(ip, p.ip_allowlist)


def _is_elevated(user: Optional[User]) -> bool:
    """Admin/manager hanno bypass globale (rivedono tutto, ma audit trail
    li traccia comunque). Configurabile in futuro via setting tenant."""
    return is_admin(user) or is_manager(user)


def user_can_access_project(
    user: Optional[User],
    project_id: Optional[int],
    db: Session,
) -> bool:
    """Determina se user ha access al progetto. project_id=None → False
    (asset internal queue → solo admin + uploader, gestito a parte)."""
    if not user or not project_id:
        return False
    if _is_elevated(user):
        return True
    # Grant esplicito attivo
    grant = db.query(ProjectAccessGrant).filter(
        ProjectAccessGrant.project_id == project_id,
        ProjectAccessGrant.user_id == user.id,
        ProjectAccessGrant.revoked_at.is_(None),
        ProjectAccessGrant.tenant_id == CURRENT_TENANT,
    ).first()
    if grant:
        return True
    # Auto-grant via JobResourceAssignment: user → Resource.user_id → assignment
    # su un Job del project
    if _has_assignment_in_project(user, project_id, db):
        return True
    return False


def _has_assignment_in_project(user: User, project_id: int, db: Session) -> bool:
    """True se user ha una Resource con assignment su un job del project."""
    # Resource.user_id legato a user (Resource ha campo user_id? verifica)
    resources = db.query(Resource).filter(
        Resource.user_id == user.id,
        Resource.tenant_id == CURRENT_TENANT,
    ).all()
    if not resources:
        return False
    resource_ids = [r.id for r in resources]
    # Job del project con assignment di queste risorse
    n = (
        db.query(JobResourceAssignment)
        .join(Job, Job.id == JobResourceAssignment.job_id)
        .filter(
            Job.project_id == project_id,
            JobResourceAssignment.resource_id.in_(resource_ids),
        )
        .count()
    )
    return n > 0


def accessible_project_ids(user: Optional[User], db: Session) -> Set[int]:
    """Set di project_ids visibili all'user. Per admin/manager → tutti
    del tenant. Altrimenti unione di grant + assignments."""
    if not user:
        return set()
    if _is_elevated(user):
        rows = db.query(Project.id).filter(
            Project.tenant_id == CURRENT_TENANT,
        ).all()
        return {r[0] for r in rows}
    out: Set[int] = set()
    # Grants attivi
    grants = db.query(ProjectAccessGrant.project_id).filter(
        ProjectAccessGrant.user_id == user.id,
        ProjectAccessGrant.revoked_at.is_(None),
        ProjectAccessGrant.tenant_id == CURRENT_TENANT,
    ).all()
    out.update(g[0] for g in grants)
    # Auto-grants via Resource.user_id → JobResourceAssignment → Job.project_id
    resources = db.query(Resource.id).filter(
        Resource.user_id == user.id,
        Resource.tenant_id == CURRENT_TENANT,
    ).all()
    if resources:
        resource_ids = [r[0] for r in resources]
        job_projects = (
            db.query(Job.project_id)
            .join(JobResourceAssignment, JobResourceAssignment.job_id == Job.id)
            .filter(JobResourceAssignment.resource_id.in_(resource_ids))
            .filter(Job.project_id.isnot(None))
            .distinct()
            .all()
        )
        out.update(jp[0] for jp in job_projects)
    return out


def user_can_access_asset(user: Optional[User], asset, db: Session) -> bool:
    """Asset access. project_id=NULL ⇒ internal queue, visibile solo a:
      - admin / manager (bypass)
      - uploader (proprio file in transito verso assegnazione)
    Altrimenti delega a user_can_access_project.
    """
    if not user or not asset:
        return False
    if _is_elevated(user):
        return True
    if asset.project_id is None:
        return getattr(asset, "uploaded_by", None) == user.id
    return user_can_access_project(user, asset.project_id, db)


def log_asset_access(
    db: Session,
    *,
    user: Optional[User],
    action: AssetAccessAction,
    asset_id: Optional[int] = None,
    project_id: Optional[int] = None,
    request=None,
    extra: Optional[str] = None,
    commit: bool = True,
) -> None:
    """Audit log accesso/azione asset. Append-only. v3.5.0-alpha.70.1.
    Idempotente NON: ogni call crea una nuova riga.
    Se commit=False, il caller deve fare db.commit()."""
    ip = None
    ua = None
    if request is not None:
        try:
            ip = (
                (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
                or (request.client.host if request.client else None)
            )
        except Exception:
            ip = None
        try:
            ua = (request.headers.get("user-agent") or "")[:255]
        except Exception:
            ua = None
    log = AssetAccessLog(
        tenant_id=CURRENT_TENANT,
        asset_id=asset_id,
        user_id=user.id if user else None,
        action=action,
        project_id=project_id,
        ip_address=ip,
        user_agent=ua,
        extra=extra,
        ts=datetime.utcnow(),
    )
    db.add(log)
    if commit:
        db.commit()
