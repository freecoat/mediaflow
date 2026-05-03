"""RBAC helpers (v3.4.23 — permessi configurabili).

Sistema:
  - **Permission keys** (PERMISSIONS) sono stringhe granulari (es. "view_finance",
    "approve_unavailability"). Definite a livello di codice, riconosciute dal sistema.
  - **Role** (modello DB) lega un set di permessi → assegnabile a User.
  - Preset built-in (`admin`, `manager`, `producer`, `accounting`, `operator`,
    `viewer`) creati al boot via `_ensure_built_in_roles()`. `is_system=True`.
    L'admin può modificare permessi dei preset (eccetto `admin` che ha sempre tutti)
    e creare ruoli custom.
  - User.role_id punta al Role attivo. Il vecchio enum `User.role` è kept per
    back-compat (usato come fallback se role_id è None).

Helper principale: `has_permission(user, "view_finance") -> bool`.
Tutti i `can_*` legacy ora chiamano `has_permission`.
"""
from typing import Iterable, Optional, Set, Dict, List

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import User, UserRole, Resource, Role


# ── Permission keys ─────────────────────────────────────────────
# Categorizzati per UI matrix. Aggiungerne uno qui = automaticamente
# disponibile nel pannello /admin/roles.

PERMISSIONS: Dict[str, Dict[str, List[str]]] = {
    "Anagrafica": {
        "view_clients":     ["Visualizza clienti"],
        "edit_clients":     ["Crea/modifica clienti"],
        "view_projects":    ["Visualizza progetti (info tecniche)"],
        "edit_projects":    ["Modifica progetti"],
        "create_projects":  ["Crea nuovi progetti"],
        "delete_projects":  ["Elimina progetti (cestino)"],
    },
    "Pianificazione": {
        "view_planning":         ["Visualizza pianificazione"],
        "edit_planning_own":     ["Modifica i propri booking"],
        "edit_planning_all":     ["Modifica booking di tutti"],
        "assign_resources":      ["Assegna risorse a job (kanban)"],
        "approve_overtime":      ["Approva straordinari sui booking"],
    },
    "HR / Timbrature": {
        "view_punches_own":       ["Visualizza proprie timbrature"],
        "view_punches_all":       ["Visualizza tutte le timbrature"],
        "edit_punches_own":       ["Modifica proprie timbrature"],
        "edit_punches_all":       ["Modifica timbrature di tutti"],
        "approve_unavailability": ["Approva ferie/malattie/permessi"],
    },
    "Finanza": {
        "view_finance":     ["Visualizza dati finanziari"],
        "view_quotes":      ["Visualizza quotazioni"],
        "edit_quotes":      ["Crea/modifica quotazioni"],
        "delete_quotes":    ["Elimina quotazioni (cestino)"],
        "view_pricelist":   ["Visualizza listino prezzi"],
        "edit_pricelist":   ["Modifica listino prezzi"],
        "view_cost_report": ["Visualizza cost report"],
        "view_invoices":    ["Visualizza fatture"],
        "edit_invoices":    ["Crea/modifica fatture"],
        # v3.4.54 — override manuale del maturato (ore lavorate). Default
        # deriva dai booking marcati `done` (cost_line_sync). Solo admin /
        # accounting / manager possono fare override in fase di verifica.
        "edit_cost_actuals": ["Override manuale ore lavorate (cost line)"],
    },
    "Cestino / Pulizia": {
        # v3.5.0-alpha.7 — soft-delete framework
        "view_trash":      ["Visualizza cestino + log eliminazioni"],
        "restore_trash":   ["Ripristina record dal cestino"],
        # Pulizia totale admin: HARD-DELETE atomico di Quote + Job +
        # JobCostLine + Booking quando l'utente vuole davvero spazzare via
        # un'intera linea (es. quote di test con tutto il suo strascico).
        # Irreversibile, niente passaggio dal cestino.
        "purge_total":     ["Pulizia totale (hard-delete cascade quote+job+booking)"],
    },
    "Risorse": {
        "view_resources":   ["Visualizza anagrafica risorse"],
        "edit_resources":   ["Modifica anagrafica risorse"],
    },
    "Configurazione": {
        "manage_departments":      ["Gestione reparti"],
        "manage_settings_global":  ["Modifica impostazioni globali (orari, AI)"],
        "manage_users":            ["Gestione utenti"],
        "manage_roles":            ["Gestione ruoli e permessi"],
    },
}

# Flat set per validazione
ALL_PERMISSION_KEYS: Set[str] = {
    k for cat in PERMISSIONS.values() for k in cat.keys()
}


# ── Preset built-in ─────────────────────────────────────────────
# Definiscono i permessi default di ogni ruolo "di sistema" creato al boot.
# Eseguibile e modificabile da admin via /admin/roles, ma non eliminabile.

PRESET_PERMISSIONS: Dict[str, List[str]] = {
    "admin": list(ALL_PERMISSION_KEYS),  # tutto
    "manager": [
        "view_clients", "edit_clients",
        "view_projects", "edit_projects", "create_projects", "delete_projects",
        "view_planning", "edit_planning_own", "edit_planning_all", "assign_resources",
        "approve_overtime",
        "view_punches_own", "view_punches_all", "edit_punches_own", "edit_punches_all",
        "approve_unavailability",
        "view_finance", "view_quotes", "edit_quotes", "delete_quotes",
        "view_pricelist", "edit_pricelist",
        "view_cost_report", "view_invoices", "edit_invoices", "edit_cost_actuals",
        "view_resources", "edit_resources",
        "manage_departments",
        "view_trash", "restore_trash",
    ],
    "producer": [
        "view_clients",
        "view_projects", "edit_projects", "create_projects", "delete_projects",
        "view_planning", "edit_planning_own", "edit_planning_all", "assign_resources",
        "approve_overtime",
        "view_punches_own", "view_punches_all", "edit_punches_own", "edit_punches_all",
        "approve_unavailability",
        "view_finance", "view_quotes", "edit_quotes", "delete_quotes",
        "view_pricelist",
        "view_cost_report",
        "view_resources",
    ],
    "accounting": [
        "view_clients",
        "view_projects",
        "view_planning",
        "view_punches_all",
        "view_finance", "view_quotes", "edit_quotes", "delete_quotes",
        "view_pricelist",
        "view_cost_report", "view_invoices", "edit_invoices", "edit_cost_actuals",
    ],
    "operator": [
        "view_projects",
        "view_planning", "edit_planning_own",
        "view_punches_own", "edit_punches_own",
    ],
    "viewer": [
        "view_clients", "view_projects",
        "view_planning",
        "view_punches_own",
    ],
}

PRESET_DESCRIPTIONS: Dict[str, str] = {
    "admin":      "Amministratore di sistema — accesso completo a tutto",
    "manager":    "Manager / produzione esecutiva — full progetto + finanza, no impostazioni globali",
    "producer":   "Producer / project manager — full progetto, no editing listino, no fatture",
    "accounting": "Contabilità — finanza + fatturazione, no editing operativo",
    "operator":   "Tecnico / risorsa — solo info tecniche progetti, propria pianificazione e timbrature",
    "viewer":     "Sola lettura — accesso in lettura ai dati operativi",
}


# ── Set di convenienza per logica legacy (mantieni per back-compat) ─
ELEVATED_ROLE_CODES: Set[str] = {"admin", "manager", "producer"}


# ── Resolver permessi per User ─────────────────────────────────
def _user_permissions(user: Optional[User]) -> Set[str]:
    """Set permessi attivi per l'utente.

    = permessi del Role attivo (o preset enum legacy come fallback)
    + permessi extra individuali (User.extra_permissions, additivi).
    """
    if not user:
        return set()
    # 1. Permessi base dal ruolo
    base: Set[str] = set()
    if user.role_id and user.role_obj and user.role_obj.is_active:
        perms = user.role_obj.permissions or []
        if isinstance(perms, list):
            base = set(perms)
    else:
        # Fallback su enum legacy → preset built-in
        role_code = (user.role.value if hasattr(user.role, "value") else str(user.role or "")).lower()
        if role_code == "staff":
            role_code = "operator"
        base = set(PRESET_PERMISSIONS.get(role_code, []))
    # 2. Extra additivi per-utente
    extra = getattr(user, "extra_permissions", None) or []
    if isinstance(extra, list):
        base = base | set(extra)
    return base


def has_permission(user: Optional[User], permission: str) -> bool:
    if not user:
        return False
    return permission in _user_permissions(user)


def has_any(user: Optional[User], *permissions: str) -> bool:
    if not user:
        return False
    p = _user_permissions(user)
    return any(perm in p for perm in permissions)


# ── Dependency: estrae l'utente dal middleware auth_guard ───────────
def current_user(request: Request) -> User:
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Non autenticato")
    return user


def current_user_optional(request: Request) -> Optional[User]:
    return getattr(request.state, "current_user", None)


# ── Predicati di alto livello (back-compat con v3.4.22) ────────
def is_admin(user: Optional[User]) -> bool:
    return has_permission(user, "manage_roles")  # admin = chi può gestire ruoli


def is_manager(user: Optional[User]) -> bool:
    if not user:
        return False
    role_code = _resolve_role_code(user)
    return role_code == "manager"


def is_producer(user: Optional[User]) -> bool:
    if not user:
        return False
    return _resolve_role_code(user) == "producer"


def is_staff(user: Optional[User]) -> bool:
    if not user:
        return False
    code = _resolve_role_code(user)
    return code in ("staff", "operator")


def is_viewer(user: Optional[User]) -> bool:
    if not user:
        return False
    return _resolve_role_code(user) == "viewer"


def is_elevated(user: Optional[User]) -> bool:
    """Almeno permesso assign_resources O approve_unavailability O edit_planning_all
    → considerato 'elevated' per logiche di scoping. Equivalente al concetto
    admin/manager/producer pre-v3.4.23."""
    return has_any(user, "edit_planning_all", "assign_resources", "approve_unavailability")


def can_view_finance(user: Optional[User]) -> bool:
    return has_permission(user, "view_finance")


def can_edit_cost_actuals(user: Optional[User]) -> bool:
    """Override manuale di JobCostLine.quantity_actual (ore lavorate).
    v3.4.54 — admin/manager/accounting; producer/operator/viewer no."""
    return has_permission(user, "edit_cost_actuals")


def can_edit_settings(user: Optional[User]) -> bool:
    return has_permission(user, "manage_settings_global")


def can_edit_pricelist(user: Optional[User]) -> bool:
    return has_permission(user, "edit_pricelist")


def can_assign_resources(user: Optional[User]) -> bool:
    return has_permission(user, "assign_resources")


def can_approve_unavailability(user: Optional[User]) -> bool:
    return has_permission(user, "approve_unavailability")


def can_manage_users(user: Optional[User]) -> bool:
    return has_permission(user, "manage_users")


def can_manage_roles(user: Optional[User]) -> bool:
    return has_permission(user, "manage_roles")


# ── Helper interno ──────────────────────────────────────────────
def _resolve_role_code(user: User) -> str:
    """Ritorna il code del Role (FK) se presente, altrimenti enum legacy."""
    if user.role_id and user.role_obj:
        return (user.role_obj.code or "").lower()
    return (user.role.value if hasattr(user.role, "value") else str(user.role or "")).lower()


# ── Dependency factory: 403 se permesso mancante ───────────────
def requires_permission(*perms: str):
    def _dep(request: Request) -> User:
        user = current_user(request)
        if not all(has_permission(user, p) for p in perms):
            raise HTTPException(403, "Permesso negato")
        return user
    return _dep


def requires_any_permission(*perms: str):
    def _dep(request: Request) -> User:
        user = current_user(request)
        if not has_any(user, *perms):
            raise HTTPException(403, "Permesso negato")
        return user
    return _dep


# ── Scope helper: Resource linkata all'utente ─────────────────────
def scope_resource_id(db: Session, user: Optional[User]) -> Optional[int]:
    if not user:
        return None
    r = (
        db.query(Resource)
        .filter(Resource.user_id == user.id, Resource.is_active == True)  # noqa: E712
        .first()
    )
    return r.id if r else None


def scope_resource_ids(db: Session, user: Optional[User]) -> Iterable[int]:
    if is_elevated(user):
        ids = [r.id for r in db.query(Resource.id).filter(Resource.is_active == True).all()]  # noqa: E712
        return ids
    rid = scope_resource_id(db, user)
    return [rid] if rid else []


# ── Bootstrap: crea Role preset al boot se mancanti ────────────
def ensure_built_in_roles(db: Session, tenant_id: int = 1) -> None:
    """Assicura che esistano i 6 preset (admin, manager, producer, accounting,
    operator, viewer) come Role(is_system=True). Idempotente: aggiorna solo
    descrizione/permessi se la riga esiste ed è is_system. Non tocca custom roles."""
    for code, perms in PRESET_PERMISSIONS.items():
        r = db.query(Role).filter(Role.code == code).first()
        if r is None:
            db.add(Role(
                tenant_id=tenant_id,
                code=code,
                name=code.capitalize(),
                description=PRESET_DESCRIPTIONS.get(code),
                permissions=perms,
                is_system=True,
                is_active=True,
            ))
        elif r.is_system:
            # Non sovrascriviamo permessi (l'admin potrebbe averli editati).
            # Aggiorniamo solo description se vuota e tenant_id se mancante.
            if not r.description:
                r.description = PRESET_DESCRIPTIONS.get(code)
            if not r.tenant_id:
                r.tenant_id = tenant_id
    db.commit()
