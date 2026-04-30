"""RBAC helpers (v3.4.22).

Ruoli (v3.4.22, esteso da v3.0):
  - admin    : full access incluse impostazioni globali (orari, reparti, RBAC)
  - manager  : full progetto + finanza, no impostazioni di tenant
  - producer : full progetto + finanza, no impostazioni di tenant
  - staff    : solo info tecniche progetti, scope su propria risorsa per
               pianificazione e timbrature, no finanza/quote, no settings
  - viewer   : sola lettura, no edit

Pattern:
  - Dependency `current_user(request)` recupera l'utente dal middleware auth_guard.
  - `requires_role("admin", "manager", ...)` blocca con 403 se non match.
  - `is_*` helpers per logica condizionale fine.
  - `scope_resource_id(db, user)` ritorna l'ID della Resource linkata all'utente
    (via Resource.user_id), o None se utente non ha risorsa associata.
"""
from typing import Iterable, Optional, Set

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import User, UserRole, Resource


# ── Set di convenienza ────────────────────────────────────────────
ELEVATED_ROLES: Set[UserRole] = {UserRole.admin, UserRole.manager, UserRole.producer}
ADMIN_ONLY: Set[UserRole] = {UserRole.admin}
FINANCE_VIEWERS: Set[UserRole] = {UserRole.admin, UserRole.manager, UserRole.producer}
EDITORS: Set[UserRole] = {UserRole.admin, UserRole.manager, UserRole.producer, UserRole.staff}


def _coerce(role) -> Optional[UserRole]:
    if role is None:
        return None
    if isinstance(role, UserRole):
        return role
    try:
        return UserRole(str(role))
    except Exception:
        return None


# ── Dependency: estrae l'utente dal middleware auth_guard ───────────
def current_user(request: Request) -> User:
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Non autenticato")
    return user


def current_user_optional(request: Request) -> Optional[User]:
    return getattr(request.state, "current_user", None)


# ── Predicati ────────────────────────────────────────────────────
def is_admin(user: Optional[User]) -> bool:
    return user is not None and _coerce(user.role) == UserRole.admin


def is_manager(user: Optional[User]) -> bool:
    return user is not None and _coerce(user.role) == UserRole.manager


def is_producer(user: Optional[User]) -> bool:
    return user is not None and _coerce(user.role) == UserRole.producer


def is_staff(user: Optional[User]) -> bool:
    return user is not None and _coerce(user.role) == UserRole.staff


def is_viewer(user: Optional[User]) -> bool:
    return user is not None and _coerce(user.role) == UserRole.viewer


def is_elevated(user: Optional[User]) -> bool:
    """admin/manager/producer."""
    return user is not None and _coerce(user.role) in ELEVATED_ROLES


def can_view_finance(user: Optional[User]) -> bool:
    """Vede prezzi, quotazioni, cost report, fatturazione."""
    return user is not None and _coerce(user.role) in FINANCE_VIEWERS


def can_edit_settings(user: Optional[User]) -> bool:
    """Tab Impostazioni globali (orari, AI, ecc.)."""
    return is_admin(user)


def can_edit_pricelist(user: Optional[User]) -> bool:
    return user is not None and _coerce(user.role) in {UserRole.admin, UserRole.manager}


def can_assign_resources(user: Optional[User]) -> bool:
    """Booking/assignment cross-resource (planning libero su tutti)."""
    return is_elevated(user)


def can_approve_unavailability(user: Optional[User]) -> bool:
    """Approva ferie/malattia/permessi."""
    return is_elevated(user)


# ── Dependency factory: 403 se ruolo non in lista ─────────────────
def requires_role(*roles: UserRole):
    role_set: Set[UserRole] = {_coerce(r) for r in roles if _coerce(r)}

    def _dep(request: Request) -> User:
        user = current_user(request)
        if _coerce(user.role) not in role_set:
            raise HTTPException(403, "Permesso negato")
        return user
    return _dep


# ── Scope helper: Resource linkata all'utente ─────────────────────
def scope_resource_id(db: Session, user: Optional[User]) -> Optional[int]:
    """Ritorna l'ID della Resource collegata all'User via Resource.user_id, o None."""
    if not user:
        return None
    r = (
        db.query(Resource)
        .filter(Resource.user_id == user.id, Resource.is_active == True)  # noqa: E712
        .first()
    )
    return r.id if r else None


def scope_resource_ids(db: Session, user: Optional[User]) -> Iterable[int]:
    """Lista IDs di Resource visibili all'utente.

    - Elevated → tutti gli ID delle risorse attive (se chiamata serve un set
      esplicito; il caller spesso preferirà non filtrare e passare None)
    - Staff/viewer → solo la propria (1 elemento) o set vuoto
    """
    if is_elevated(user):
        ids = [r.id for r in db.query(Resource.id).filter(Resource.is_active == True).all()]  # noqa: E712
        return ids
    rid = scope_resource_id(db, user)
    return [rid] if rid else []
