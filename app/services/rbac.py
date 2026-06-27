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
    "Acquisizioni": {
        "view_acquisitions":   ["Visualizza acquisizioni/trattative"],
        "manage_acquisitions": ["Gestisce acquisizioni/trattative"],
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
        # v3.5.0-alpha.172.35 — Sprint 1: edit_cost_lines = mod. campi editabili
        # delle JCL (total_expected/notes/external_outsourced). I valori derivati
        # (quantity_actual/total_accrued) restano lock dai booking — vedi
        # commento `edit_cost_actuals` rimosso più sotto.
        "edit_cost_lines":  ["Modifica righe di costo job (forecast, note, outsourced)"],
        "view_invoices":    ["Visualizza fatture"],
        "edit_invoices":    ["Crea/modifica fatture"],
        # v3.5.0-alpha.87 — Pozzo costi generici / Spese aziendali (OverheadCost).
        # Costi non fatturabili al cliente che vivono nel quadro finanziario tenant.
        "view_overhead":    ["Visualizza spese aziendali (pozzo costi)"],
        "edit_overhead":    ["Crea/modifica spese aziendali"],
        # v3.5.0-alpha.89 — Workflow anomalie fatturazione (sprint S4).
        # view_anomalies = vede la lista; handle_anomalies = può applicare
        # azioni (rimanda commerciale / rivaluta producer / write-off / overhead).
        "view_anomalies":   ["Visualizza anomalie fatturazione"],
        "handle_anomalies": ["Gestisci anomalie (azioni rimanda/write-off/overhead)"],
        # v3.5.0-alpha.21: edit_cost_actuals rimosso definitivamente. Le ore
        # lavorate sono SEMPRE derivate da booking marcati `done` (cost_line_sync).
        # La fatturazione di extra/sconti/banca-ore forfait passa dal flusso
        # fatturazione dedicato (in roadmap), non da qui.
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
        # v3.5.0-alpha.172.3 — Hard-delete project cascade FULL (Restructure).
        # Irreversibile. ADMIN-ONLY, solo per workflow test/cleanup.
        "hard_delete_project": ["Hard-delete progetto cascade FULL (admin only)"],
    },
    "Consegne / Deliverable": {
        # v3.5.0-alpha.172.3 — Workflow JobDeliverable.
        "view_deliverables":   ["Visualizza consegne"],
        "edit_deliverables":   ["Modifica consegne (specifiche, link asset)"],
        "confirm_deliverables": ["Conferma consegna (quantity_delivered)"],
        # v3.5.0-alpha.172.226 — Gestione KDM/DKDM per consegne DCP.
        "manage_kdm":          ["Gestione richieste KDM/DKDM (chiavi DCP)"],
    },
    "Risorse": {
        "view_resources":   ["Visualizza anagrafica risorse"],
        "edit_resources":   ["Modifica anagrafica risorse"],
    },
    "Configurazione": {
        "manage_departments":      ["Gestione reparti"],
        # v3.5.0-alpha.21: split tra view e manage per dare ai non-admin la
        # possibilità di consultare gli orari lavorativi (read-only) senza
        # poterli modificare.
        "view_settings_global":    ["Visualizza impostazioni globali (orari, AI, anagrafica)"],
        "manage_settings_global":  ["Modifica impostazioni globali (orari, AI, anagrafica)"],
        "manage_users":            ["Gestione utenti"],
        "manage_roles":            ["Gestione ruoli e permessi"],
        # v3.5.0-alpha.172.195 — Content Lockdown (TPN). Solo admin: attiva/
        # disattiva l'egress cloud (AI cloud, ricerca web, enrichment).
        "manage_cloud_lockdown":   ["Gestione Content Lockdown (egress cloud, admin)"],
        # v3.5.0-alpha.172.216 — F6 Distruzione asset (TPN doppia conferma).
        "approve_destruction":     ["Approvazione distruzione asset (TPN)"],
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
        "view_acquisitions", "manage_acquisitions",
        "view_planning", "edit_planning_own", "edit_planning_all", "assign_resources",
        "approve_overtime",
        "view_punches_own", "view_punches_all", "edit_punches_own", "edit_punches_all",
        "approve_unavailability",
        "view_finance", "view_quotes", "edit_quotes", "delete_quotes",
        "view_pricelist", "edit_pricelist",
        "view_cost_report", "edit_cost_lines",
        "view_invoices", "edit_invoices",
        # v3.5.0-alpha.87 — pozzo costi / spese aziendali
        "view_overhead", "edit_overhead",
        "view_resources", "edit_resources",
        "manage_departments",
        # v3.5.0-alpha.21: manager può modificare orari lavorativi (Matteo:
        # "Orari lavorativi definibili solo da autorizzazione manager in su")
        "view_settings_global", "manage_settings_global",
        "view_trash", "restore_trash",
        # v3.5.0-alpha.172.3 — Deliverable workflow (Restructure)
        "view_deliverables", "edit_deliverables", "confirm_deliverables",
        # v3.5.0-alpha.172.226 — KDM/DKDM management
        "manage_kdm",
    ],
    "producer": [
        "view_clients",
        "view_projects", "edit_projects", "create_projects", "delete_projects",
        "view_acquisitions", "manage_acquisitions",
        "view_planning", "edit_planning_own", "edit_planning_all", "assign_resources",
        "approve_overtime",
        "view_punches_own", "view_punches_all", "edit_punches_own", "edit_punches_all",
        "approve_unavailability",
        "view_finance", "view_quotes", "edit_quotes", "delete_quotes",
        "view_pricelist",
        "view_cost_report", "edit_cost_lines",
        "view_overhead",  # v3.5.0-alpha.87 — producer read-only
        "view_resources",
        # v3.5.0-alpha.21: producer ha read-only sugli orari (vede regole CCNL)
        "view_settings_global",
        # v3.5.0-alpha.172.3 — Deliverable workflow (producer = conferma consegne)
        "view_deliverables", "edit_deliverables", "confirm_deliverables",
    ],
    "accounting": [
        "view_clients",
        "view_projects",
        "view_acquisitions", "manage_acquisitions",
        "view_planning",
        "view_punches_all",
        "view_finance", "view_quotes", "edit_quotes", "delete_quotes",
        "view_pricelist",
        "view_cost_report", "edit_cost_lines",
        "view_invoices", "edit_invoices",
        # v3.5.0-alpha.87 — accounting cura pozzo costi
        "view_overhead", "edit_overhead",
        "view_settings_global",
        # v3.5.0-alpha.172.3 — read-only Deliverable per accounting
        "view_deliverables",
    ],
    "operator": [
        "view_projects",
        "view_planning", "edit_planning_own",
        "view_punches_own", "edit_punches_own",
        # v3.5.0-alpha.21: operator/staff vede gli orari lavorativi (read-only)
        # — il regolamento d'azienda gli serve per orientarsi sulle proprie ore
        "view_settings_global",
        # v3.5.0-alpha.172.3 — operator/staff vede + linka deliverable (lavorazione)
        "view_deliverables", "edit_deliverables",
    ],
    "viewer": [
        "view_clients", "view_projects",
        "view_planning",
        "view_punches_own",
        "view_settings_global",
        # v3.5.0-alpha.172.3 — read-only
        "view_deliverables",
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
    """v3.5.0-alpha.21: rimosso definitivamente. Le ore lavorate sono SEMPRE
    derivate dai booking marcati `done` (cost_line_sync). Helper preservato
    perché ancora referenziato in `templates.env.globals` (back-compat) ma
    ritorna sempre False — nessun utente può più editare quantity_actual.
    """
    return False


def can_edit_settings(user: Optional[User]) -> bool:
    return has_permission(user, "manage_settings_global")


def can_view_settings(user: Optional[User]) -> bool:
    """v3.5.0-alpha.21: vedere /settings (orari lavorativi, anagrafica, AI).
    User può vedere ma non modificare se ha solo `view_settings_global`.
    Admin/manager con `manage_settings_global` possono modificare.
    """
    return has_permission(user, "view_settings_global") or has_permission(user, "manage_settings_global")


def can_edit_pricelist(user: Optional[User]) -> bool:
    return has_permission(user, "edit_pricelist")


def can_assign_resources(user: Optional[User]) -> bool:
    return has_permission(user, "assign_resources")


def can_create_booking(user: Optional[User]) -> bool:
    """v3.5.0-alpha.10 — chi può creare booking direttamente (no via richiesta).

    Default: chi ha `edit_planning_all` O `assign_resources` (admin/manager/producer).
    Operator/editor (con solo `edit_planning_own`) NON può creare booking — può
    solo richiederli al producer/manager via flusso 'request_booking'.

    Nota: `edit_planning_own` resta valido per modifiche dei propri booking
    esistenti (priority, execution status, durata in cascade) — quello è già
    gestito dai check granulari sui rispettivi endpoint.
    """
    return has_any(user, "edit_planning_all", "assign_resources")


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
    descrizione/permessi se la riga esiste ed è is_system. Non tocca custom roles.

    v3.5.0-alpha.87 — Admin role: SEMPRE re-sync con ALL_PERMISSION_KEYS.
    L'admin è speciale: deve avere ogni nuova permission aggiunta a PERMISSIONS.
    Niente edit manuale rispettata per admin (è by design: admin ha tutto)."""
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
            # v3.5.0-alpha.87 — Admin role SEMPRE re-sync (deve avere ALL).
            if code == "admin":
                current = set(r.permissions or [])
                expected = set(perms)
                if current != expected:
                    r.permissions = list(expected)
            # Non sovrascriviamo permessi degli altri preset (l'admin potrebbe averli editati).
            # Aggiorniamo solo description se vuota e tenant_id se mancante.
            if not r.description:
                r.description = PRESET_DESCRIPTIONS.get(code)
            if not r.tenant_id:
                r.tenant_id = tenant_id
    db.commit()
