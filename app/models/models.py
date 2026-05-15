"""
MediaFlow v3 — modelli ORM
Gerarchia: Cliente → Progetto → Quotazioni → Job
Fase 1-bis: aggiunti Tenant, Department, DeliveryTemplate, PriceItem.keywords
"""
from __future__ import annotations
import enum
import json
from datetime import datetime, date, time
from typing import Optional, List, Any
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, Date, DateTime, Time, JSON,
    ForeignKey, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# ── ENUMS ────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    producer = "producer"   # producer/PM: full progetto, no impostazioni globali
    staff = "staff"         # tecnico/risorsa: vede solo info tecniche + propria pianificazione/timbrature
    viewer = "viewer"       # sola lettura

class ResourceType(str, enum.Enum):
    person_internal = "person_internal"  # dipendente della casa di post
    person_freelance = "person_freelance"  # freelance esterno
    studio = "studio"                    # sala/suite fisica
    equipment = "equipment"              # attrezzatura (monitor, deck, ecc.)
    software = "software"                # licenza software/postazione
    vehicle = "vehicle"
    # deprecato ma manteniamo retrocompatibilità:
    person = "person"

class BookingStatus(str, enum.Enum):
    tentative = "tentative"; confirmed = "confirmed"
    cancelled = "cancelled"; completed = "completed"

class BookingPriority(str, enum.Enum):
    """Priorità booking (v3.4.32). Visualizzata via colore bordo card.
    `low` = informativa, `normal` = default, `high` = urgente."""
    low = "low"
    normal = "normal"
    high = "high"

class BookingExecutionStatus(str, enum.Enum):
    """[DEPRECATED v3.5.0-alpha.66.5] Stato di esecuzione del booking.
    Manteniamo per back-compat (slice-lock, billing, recompute leggono questo
    e BookingStatus). La fonte canonica è ora `Booking.state` (BookingState).
    Sincronizzato automaticamente quando state cambia."""
    planned = "planned"
    in_progress = "in_progress"
    done = "done"
    not_done = "not_done"


class BookingState(str, enum.Enum):
    """Ciclo di vita unificato del booking (v3.5.0-alpha.66.5).

    5 stati esclusivi nel selettore UI + cancelled per soft-delete (azione
    separata via "Elimina"). Sostituisce concettualmente `BookingStatus` e
    `BookingExecutionStatus` che restano nel DB come campi DERIVATI per
    back-compat con slice-lock/billing/recompute.

    Sequenza tipica (transizioni libere): tentative → confirmed → in_progress
    → done | not_done. Cancelled è soft-delete, non appare nel selettore."""
    tentative = "tentative"
    confirmed = "confirmed"
    in_progress = "in_progress"
    done = "done"
    not_done = "not_done"
    cancelled = "cancelled"


# v3.5.0-alpha.66.5 — Mapper canonico state → (status, execution_status).
# Quando si cambia BookingState, status+execution_status devono essere
# sincronizzati a questo. Importato dal sync helper.
BOOKING_STATE_TO_LEGACY: dict = {
    "tentative":   ("tentative",  "planned"),
    "confirmed":   ("confirmed",  "planned"),
    "in_progress": ("confirmed",  "in_progress"),
    "done":        ("confirmed",  "done"),
    "not_done":    ("confirmed",  "not_done"),
    "cancelled":   ("cancelled",  "planned"),
}


def compute_state_from_legacy(status_value: str, execution_value: str) -> "BookingState":
    """Migrazione 1-shot: deriva BookingState dai 2 campi legacy.
    1. cancelled → cancelled (soft-delete)
    2. tentative + qualsiasi execution → tentative (status precede)
    3. confirmed + execution → in_progress/done/not_done o confirmed (planned)"""
    if status_value == "cancelled":
        return BookingState.cancelled
    if status_value == "tentative":
        return BookingState.tentative
    if execution_value == "in_progress":
        return BookingState.in_progress
    if execution_value == "done":
        return BookingState.done
    if execution_value == "not_done":
        return BookingState.not_done
    return BookingState.confirmed

class BookingOvertimeStatus(str, enum.Enum):
    """Workflow approvazione straordinari (v3.4.32).
    Booking che cade (anche solo parzialmente) oltre la fascia regolare della
    WorkingHoursPolicy della risorsa entra in `pending` e attende approvazione
    da chi ha permesso `approve_overtime`. Su rifiuto: split intra-day + nuovo
    booking giorno successivo per le ore eccedenti."""
    none = "none"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class BookingKind(str, enum.Enum):
    # Pianificazione di una lavorazione su un job (default — comportamento storico).
    # job_id richiesto, job_cost_line_id opzionale (preferito quando si pianifica
    # una lavorazione specifica della quote).
    project = "project"
    # Booking interni: senza job, generano costo (ore risorsa) ma non profitto.
    # Vanno in cost report interno come spese, NON nel cost report cliente.
    internal_maintenance = "internal_maintenance"  # manutenzione attrezzature/sale
    internal_research = "internal_research"        # R&D, demo, prove
    internal_training = "internal_training"        # formazione personale

class PunchKind(str, enum.Enum):
    # Tipologie di timbratura/presenza per la sezione HR.
    # `shift` con job_id valorizzato = ore lavorate su progetto.
    # `shift` senza job_id = presenza generica al lavoro.
    shift = "shift"
    idle = "idle"          # presente, non allocato a progetto
    leave = "leave"        # ferie/permesso retribuito
    sick = "sick"          # malattia
    break_ = "break"       # pausa (non retribuita)
    overtime = "overtime"  # straordinario

class PriceLevel(str, enum.Enum):
    list_price = "list"; average = "average"; low = "low"; custom = "custom"

class QuoteStatus(str, enum.Enum):
    draft = "draft"; sent = "sent"; approved = "approved"
    rejected = "rejected"; expired = "expired"
    # v3.4.39 — quote sostituita da una versione successiva approvata
    # (distinta da rejected: non rifiutata dal cliente, è stata superata)
    superseded = "superseded"

class ProjectStatus(str, enum.Enum):
    prospect = "prospect"; quoting = "quoting"; active = "active"
    completed = "completed"; archived = "archived"

class JobStatus(str, enum.Enum):
    draft = "draft"; quoting = "quoting"; approved = "approved"
    active = "active"; on_hold = "on_hold"; completed = "completed"
    invoiced = "invoiced"; cancelled = "cancelled"

class AssetType(str, enum.Enum):
    video = "video"; audio = "audio"; image = "image"
    document = "document"; other = "other"


# v3.5.0-alpha.66.9 — Asset fisici (LTO/HDD/CRU/Blu-Ray/DVD/Case)
class PhysicalAssetKind(str, enum.Enum):
    lto = "lto"           # tape LTO LTFS (capacity_gb tipica 6000/9000/12000/18000)
    hdd = "hdd"           # hard disk USB/Thunderbolt/EXT
    cru = "cru"           # CRU drive (DCP fisico, EXT3/EXT4)
    bluray = "bluray"     # Blu-Ray disc (BD25/BD50/BD100)
    dvd = "dvd"           # DVD disc
    case = "case"         # case/packaging fisico (per shipping)
    other = "other"       # tutto il resto fisico


# v3.5.0-alpha.66.9 — Stato del ciclo di vita di un JobDeliverable
class DeliverableStatus(str, enum.Enum):
    planned = "planned"             # specifica nota, produzione non iniziata
    in_production = "in_production" # ≥1 booking attivo o file in lavorazione
    file_attached = "file_attached" # asset (digital o physical) linkato
    qc_running = "qc_running"       # AI QC in corso
    qc_passed = "qc_passed"         # QC ok, pronto consegna
    qc_failed = "qc_failed"         # QC fallito, da rifare
    delivered = "delivered"         # consegnato al cliente / portale
    accepted = "accepted"           # cliente ha approvato
    rejected = "rejected"           # cliente ha rifiutato


# v3.5.0-alpha.66.9 — Natura del deliverable: digital o physical (mutually exclusive)
class DeliverableNature(str, enum.Enum):
    digital = "digital"   # file/output digitale (ProRes, DCP master, IMF, ecc.)
    physical = "physical" # supporto fisico consegnato (LTO, HDD, CRU, Blu-Ray)


# v3.5.0-alpha.66.9 — Tipo di costo della risorsa, per calcolo hardcost interno
# nel cost report. Separato dalle tariffe di vendita esistenti (hourly_rate /
# daily_rate) che restano per la quote al cliente.
class ResourceCostType(str, enum.Enum):
    employee = "employee"     # dipendente — costo derivato da monthly_gross_salary × multiplier
    freelance = "freelance"   # freelance — costo = freelance_hourly_cost (tariffa pagata, ≠ hourly_rate venduto)
    studio = "studio"         # sala interna — costo = studio_hourly_cost (allocazione struttura)
    external = "external"     # risorsa esterna a uso (sala/equipment a noleggio)

class InvoiceStatus(str, enum.Enum):
    draft = "draft"; sent = "sent"; paid = "paid"
    overdue = "overdue"; cancelled = "cancelled"


# ── Cost report → Billing flow (v3.5.0-alpha.46) ──────────────
class JCLBillingStatus(str, enum.Enum):
    """Stato fatturazione di una JobCostLine.

    Flow: not_billed → in_batch → billed → paid
    Ramo alternativo: in_batch → lost (manager scarta dal batch o riduce a zero).
    """
    not_billed = "not_billed"   # default: maturato non ancora trasmesso a fatturazione
    in_batch = "in_batch"       # incluso in un BillingBatch in approvazione/approvato
    billed = "billed"           # fattura emessa
    paid = "paid"               # fattura pagata
    lost = "lost"               # parziale/totale scartato in fase di approvazione manager


class BillingBatchStatus(str, enum.Enum):
    """Stato di un BillingBatch (proposta di fatturazione mensile/extra)."""
    draft = "draft"             # creato dal cost report, in attesa approvazione manager
    approved = "approved"       # manager ha approvato gli importi, pronto per emissione
    invoiced = "invoiced"       # fattura emessa, batch chiuso (collegato a Invoice)
    cancelled = "cancelled"     # batch annullato senza emissione (no impatto JCL)


class LossReason(str, enum.Enum):
    """Motivo della voce 'perso' (delta tra proposed e approved nel batch)."""
    manager_discount = "manager_discount"   # manager ha ridotto importo per gentlezza/negoziazione
    written_off = "written_off"             # cancellato a fine progetto (non più recuperabile)
    client_complaint = "client_complaint"   # rimborsato per disservizio/contestazione cliente
    rounding = "rounding"                   # arrotondamento per allineare con accordo cliente
    other = "other"


class NotificationKind(str, enum.Enum):
    """Tipologia di notifica (v3.4.27).

    Estendibile: nuovo kind = aggiungi qui + emit con `notifications.notify(...)`.
    Il client UI può mappare kind → icona/colore custom.
    """
    # Workflow ferie/malattia/permessi
    unavailability_pending = "unavailability_pending"      # → manager (approvazione)
    unavailability_approved = "unavailability_approved"    # → richiedente
    unavailability_rejected = "unavailability_rejected"    # → richiedente
    # Cantieri futuri (riservati, già supportati lato modello):
    booking_conflict = "booking_conflict"
    quote_status_changed = "quote_status_changed"
    job_deadline_approaching = "job_deadline_approaching"
    # Workflow booking esecutivo (v3.4.32)
    booking_status_changed = "booking_status_changed"        # → producer/manager su done/not_done
    booking_overtime_pending = "booking_overtime_pending"    # → approvatori overtime
    booking_overtime_resolved = "booking_overtime_resolved"  # → operatore (esito approvazione)
    # Anomalie financial (v3.4.39) — Job orfani, discrepanze quote/consuntivo
    job_floating_alert = "job_floating_alert"                # → admin/accounting (job senza quote)
    quote_discrepancy_alert = "quote_discrepancy_alert"      # → admin/accounting (sforamenti / extra)
    # Reverse-flow (v3.4.52) — booking ha forzato approvazione implicita o creato phantom
    quote_reverse_approval = "quote_reverse_approval"        # → edit_quotes (account managers)
    # v3.4.56 — quote approvata ma il job risultante non ha ancora risorse assegnate
    quote_approved_no_resources = "quote_approved_no_resources"  # → assign_resources (producer/manager)
    # v3.5.0-alpha.10 — editor (operator) richiede creazione booking al producer/manager
    booking_request = "booking_request"  # → can_create_booking (admin/manager/producer)
    # v3.5.0-alpha.61 — extra emerso su progetto già fatturato in periodo X
    extra_after_billed = "extra_after_billed"  # → accounting + producer/manager
    # v3.5.0-alpha.111.26 — fine mese: verifica CR completati da trasmettere
    cr_eom_review = "cr_eom_review"  # → producer (ultimo giorno mese)
    custom = "custom"


class NotificationSeverity(str, enum.Enum):
    info = "info"                     # blu, informativa
    action_required = "action_required"   # giallo, richiede attenzione
    alert = "alert"                   # rosso, critica


# ── UTENTI ───────────────────────────────────────────────────

class Role(Base):
    """Ruolo configurabile con lista di permessi (v3.4.23).

    I preset built-in (admin, manager, producer, accounting, operator, viewer)
    sono creati al boot via seed `_ensure_built_in_roles()` e flagged is_system=True.
    L'admin può creare ruoli custom oltre a quelli preset.
    """
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Lista permessi (vedi rbac.PERMISSIONS per i key validi)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    # is_system=True: preset built-in, non eliminabili. Permessi però sono editabili
    # tranne 'admin' che resta sempre con tutti i permessi.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    # v3.5.0-alpha.101 — Multi-tenant HARD R-MT1: email UNIQUE per tenant,
    # non più globale. Stesso email può esistere su tenant diversi (es.
    # admin@acme.it su tenant1 e admin@acme.it su tenant2 sono DUE user
    # distinti). UniqueConstraint composito.
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    # Legacy enum role (kept per backward compat). Il sistema permessi v3.4.23
    # legge da Role (FK role_id). Quando role_id è popolato, ha priorità.
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.staff)
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id"), nullable=True, index=True)
    role_obj: Mapped[Optional["Role"]] = relationship(foreign_keys=[role_id])
    # Permessi extra (additivi sopra il ruolo) — v3.4.25.
    # Lista di chiavi PERMISSIONS aggiunte al singolo utente sopra quelle del ruolo.
    extra_permissions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Provider AI attivo per questo utente (claude|openai|gemini|perplexity|ollama|None=disabilitato)
    active_ai_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # v3.5.0-alpha.70.4 — MFA TOTP (pyotp). Secret Fernet-encrypted con
    # AI_KEY_ENCRYPTION_KEY (riuso chiave per non aggiungere env var nuova).
    # mfa_enabled è True solo dopo verify-setup riuscito.
    mfa_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_enabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # v3.5.0-alpha.104 — Super-admin platform: vede TUTTI i tenant.
    # Solo user di tenant=1 (Default) con questo flag → accesso /platform/*.
    # Bypass tenant filter su endpoint cross-tenant management.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resources: Mapped[List["Resource"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    timesheets: Mapped[List["Timesheet"]] = relationship(back_populates="user")
    assets: Mapped[List["Asset"]] = relationship(back_populates="uploaded_by_user")
    ai_settings: Mapped[List["UserAISettings"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


# ── PORTALE CLIENTE (v3.5.0-alpha.97 #10 fase A) ────────────────
#
# Auth separata dal sistema admin. Il cliente accede via magic link
# (token JWT-like, 7gg validità default). Vede solo progetti del SUO
# cliente_id. Layout pulito (no sidebar admin). Permessi limitati a:
#   - Lettura progetto (scheda + milestone + deliverables)
#   - Lettura DAM filtrato per progetto
#   - Lettura fatture emesse al cliente
# Niente edit, niente delete, niente sviluppo di funzionalità admin.
class ClientPortalAccess(Base):
    __tablename__ = "client_portal_access"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    # Identità cliente — chi accederà al portale
    email: Mapped[str] = mapped_column(String(255), index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Token magic link (random 64 char hex). Singolo cookie portal_token.
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # Scope progetti (opt: lista di project_id che può vedere; vuoto/null =
    # TUTTI i progetti del client_id).
    project_scope: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Audit
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ── TENANT (multi-tenant soft) ───────────────────────────────
#
# Fase 1-bis: prepariamo l'architettura multi-tenant senza ancora
# costruire onboarding/billing. Tutte le entità "di business" hanno
# tenant_id con default=1. In futuro basterà popolare e filtrare.

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Info aziendali
    legal_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vat_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    logo_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Preferenze locali
    default_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    default_vat_rate: Mapped[float] = mapped_column(Float, default=22.0)
    default_language: Mapped[str] = mapped_column(String(5), default="it")
    # v3.5.0-alpha.52 — Dati fiscali estesi per emissione fatture
    tax_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)         # CF se ≠ P.IVA
    iban: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)             # IBAN bancario
    sdi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)         # codice destinatario SDI proprio
    rea_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)       # es. "MI-1234567"
    fiscal_capital: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)   # Capitale sociale es. "10.000,00 i.v."
    fiscal_regime: Mapped[str] = mapped_column(String(8), default="RF01")              # RF01=ordinario, RF19=forfettario
    payment_terms_default: Mapped[int] = mapped_column(Integer, default=30)            # giorni
    payment_method_default: Mapped[str] = mapped_column(String(80), default="Bonifico bancario")
    invoice_footer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)         # testo libero in calce
    # v3.5.0-alpha.66.13 — Branding aziendale per PDF (quote/cost report/invoice)
    tagline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)        # claim/sottotitolo opzionale
    brand_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)      # hex es. #6272f5 — usato come accent nei PDF
    show_powered_by: Mapped[bool] = mapped_column(Boolean, default=True)              # toggle "Generato da MediaFlow" in footer PDF
    document_header: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # intestazione libera (HTML-light) sopra ogni doc
    # v3.5.0-alpha.72.1 — Numerazione automatica asset fisici.
    # JSON: {"LTO": {"prefix":"LTO-", "counter":1, "pad":3},
    #        "HDD": {"prefix":"HDD-", "counter":1, "pad":3}, ...}
    # Counter incrementato ad ogni create. pad = zero-padding (003 vs 3).
    # Esempio risultato: "LTO-001", "LTO-002", "HDD-042".
    asset_numbering_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # v3.5.0-alpha.87 — Soglia auto-CAPEX per OverheadCost.
    # PhysicalAsset acquisito con unit_cost > soglia crea OverheadCost
    # is_capex=True (ammortamento attivo). Sotto soglia → categoria normale
    # (spese deduc. anno). Default €500. Configurabile in /settings tenant.
    capex_threshold_eur: Mapped[float] = mapped_column(Float, default=500.0)
    # v3.5.0-alpha.96 — Filesystem scan generic: whitelist path autorizzati
    # per il scan ESTERNO (oltre uploads/). Lista di assoluti, validati al
    # boot. Es. ["/Volumes/StorageA", "/mnt/nas/deliverables"]. Vuoto =
    # nessun path autorizzato → endpoint /admin/fs-scan rifiuta tutto.
    fs_scan_allowed_paths: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Stato
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    departments: Mapped[List["Department"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    delivery_templates: Mapped[List["DeliveryTemplate"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


# ── DEPARTMENT ───────────────────────────────────────────────
#
# Entità centrale trasversale: ogni Risorsa (persona/studio/attrezzatura)
# e ogni Voce listino appartiene a un reparto.
# Il reparto è l'unità di responsabilità finanziaria.

class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_dept_tenant_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(50))  # es. "DI-VIDEO", "VFX", "AUDIO"
    name: Mapped[str] = mapped_column(String(100))  # es. "DI / Video", "VFX / Finishing"
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(7), default="#6272f5")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Budget di reparto (opzionale, utile per reportistica futura)
    annual_budget: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Head of department (collegamento a un utente)
    head_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    # v3.5.0-alpha.106 — Indirizzo reparto: usato come destinatario spedizione
    # quando il reparto ha sede diversa dal tenant principale (es. sala VFX
    # in altra città). Default: vuoto = usa tenant.address.
    shipping_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shipping_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship(back_populates="departments")
    resources: Mapped[List["Resource"]] = relationship(back_populates="department")
    price_items: Mapped[List["PriceItem"]] = relationship(back_populates="department")


# ── DELIVERY TEMPLATE ────────────────────────────────────────
#
# Template strutturato per capitolati di consegna (A24, Netflix, Sky, RAI...).
# Non è una lista piatta di voci ma una struttura a blocchi che copre
# tutti i requisiti tipici di un capitolato post-produzione.

class DeliveryTemplate(Base):
    __tablename__ = "delivery_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_delivery_tenant_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(50))  # es. "A24-THEATRICAL", "NETFLIX-IMF"
    name: Mapped[str] = mapped_column(String(255))  # es. "A24 — Theatrical Dolby Vision Feature"
    broadcaster: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # "A24", "Netflix", "Sky"
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # I 8 blocchi strutturati del capitolato, ciascuno JSON flessibile.
    # Esempio video_specs:
    # {"codec": "ProRes 4444 XQ", "resolution": "3840x2160", "colorspace": "P3 D65", ...}
    video_specs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    audio_specs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    text_specs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # subs, CC, FN
    head_format: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # bars, slate, timecode
    textless_format: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    naming_convention: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    archive_specs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_requirements: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Quali voci del listino sono tipicamente richieste da questo template
    # Esempio: [{"price_item_id": 7, "notes": "INTEROP DCP", "qty_hint": 1}, ...]
    suggested_items: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Riferimento al documento sorgente (PDF capitolato)
    source_document_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_document_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # AI enrichment: il template è stato estratto da AI o compilato a mano?
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship(back_populates="delivery_templates")


# ── LISTINO ──────────────────────────────────────────────────

class PriceCategory(Base):
    __tablename__ = "price_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_pricecat_tenant_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[List["PriceItem"]] = relationship(back_populates="category", cascade="all, delete-orphan")


class PriceItem(Base):
    __tablename__ = "price_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("price_categories.id"))
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit_pre: Mapped[str] = mapped_column(String(20), default="per")
    unit: Mapped[str] = mapped_column(String(20))
    price_list: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_average: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hardcosts: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Fase 1-bis: keywords per matching AI
    # Lista di parole chiave (es. ["dcp", "cinema", "mastering"]) per il
    # matching testo libero → voce listino e per l'import capitolati.
    keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    category: Mapped["PriceCategory"] = relationship(back_populates="items")
    department: Mapped[Optional["Department"]] = relationship(back_populates="price_items")


# v3.5.0-alpha.66.6 — Snapshot del listino (backup/restore).
# Un PricelistSnapshot cristallizza l'intero listino di un tenant (departments
# + categories + items) in un payload JSON versionato. Permette:
#   - backup manuale prima di modifiche aggressive
#   - ripristino con modalità replace o merge
#   - export/import file .json per portabilità tra installazioni
#   - preset built-in (kind=preset) committati in repo
#   - auto-snapshot pre-replace per sicurezza (kind=auto)
class PricelistSnapshotKind(str, enum.Enum):
    manual = "manual"   # creato esplicitamente dall'utente
    auto = "auto"       # auto-snapshot pre-restore o pre-reset
    preset = "preset"   # preset built-in caricato da app/data/pricelist_presets/

class PricelistSnapshot(Base):
    __tablename__ = "pricelist_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kind: Mapped[PricelistSnapshotKind] = mapped_column(
        SAEnum(PricelistSnapshotKind), default=PricelistSnapshotKind.manual, index=True
    )
    # Counters denormalizzati per ListView veloce (no parse del payload).
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    category_count: Mapped[int] = mapped_column(Integer, default=0)
    department_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    source_app_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    # Soft-delete (cestino degli snapshot). Recuperabile.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)


# ── CLIENTE (con arricchimento AI) ───────────────────────────

class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    legal_form: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # SRL, SPA, ecc.
    
    # Contatti referente
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # v3.5.0-alpha.113 — Email amministrazione/ufficio fatturazione.
    # Usato come destinatario in intestazione fattura (separato dal
    # contact_email del referente commerciale).
    admin_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Dati fiscali
    vat_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tax_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sdi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pec: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Sede
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # v3.5.0-alpha.52 — Dati fattura estesi
    zip_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    province: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)  # sigla "MI"

    # Informazioni aziendali (arricchite da AI)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    company_size: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    founded_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Filmografia / portfolio (JSON come testo)
    recent_productions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Flag arricchimento AI
    ai_enriched: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ai_sources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # URL sorgenti
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    projects: Mapped[List["Project"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    jobs: Mapped[List["Job"]] = relationship(back_populates="client")
    quotes: Mapped[List["Quote"]] = relationship(back_populates="client")
    invoices: Mapped[List["Invoice"]] = relationship(back_populates="client")
    works: Mapped[List["ClientWork"]] = relationship(back_populates="client", cascade="all, delete-orphan")


# ── FILMOGRAFIA / PORTFOLIO CLIENTE (v3.5.0-alpha.25) ────────
# Tabella separata da `Client.recent_productions` (testo libero AI-generated):
# qui ogni opera è un record strutturato cercabile/filtrabile, popolabile via
# AI con fonti esterne (filmitalia.org, cinema.cultura.gov.it, IMDB, MyMovies)
# o manualmente. Il rapporto N:1 verso Client lascia spazio a future feature
# come cross-link verso Project quando un cliente porta dentro MediaFlow una
# delle proprie opere come progetto attivo.

class ClientWork(Base):
    __tablename__ = "client_works"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # Tipo opera: film, serie, documentario, spot, cortometraggio, altro
    kind: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Ruolo del cliente nell'opera: produzione, post-produzione, distribuzione,
    # co-produzione, ecc. Free-form per non vincolare la tassonomia.
    our_role: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    director: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Lista JSON di {name, url} delle fonti consultate (filmitalia, cinema.cultura, ...)
    sources_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # v3.5.0-alpha.28 — campi estesi per pagina filmografia dedicata
    synopsis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # JSON {"mibac": bool, "regional": str, "eu": bool, "notes": str}
    funding_public: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON {"director": str, "dop": str, "executive_producer": str,
    #       "editor": str, "sound_design": str, "music": str,
    #       "screenplay": str, "lead_cast": [str, ...]}
    # `director` qui ridondante con il campo top-level: lo manteniamo per
    # avere un blocco compatto da editare insieme.
    cast_crew: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON [{"label": str, "url": str}] — link esterni (trailer, sito,
    # streaming, IMDB extra, rassegna stampa, ecc.). Distinto da `sources`
    # (che è il tracking delle fonti AI consultate).
    external_links: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON [{"name": str, "year": int, "category": str, "won": bool}]
    awards: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Marker provenienza: True se il record è stato proposto dall'AI e
    # confermato dall'utente; False se inserito manualmente.
    ai_imported: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    client: Mapped["Client"] = relationship(back_populates="works")


# ── PROGETTO (NUOVA ENTITÀ) ──────────────────────────────────

# Project con TPN compliance fields (v3.5.0-alpha.70.3)
class Project(Base):
    """
    Un progetto è un'opera audiovisiva (film, serie, spot, doc) del cliente.
    Un cliente ha N progetti. Un progetto ha N quotazioni e N job.
    """
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    
    # Tipologia progetto
    project_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # feature_film, short_film, series, documentary, spot, music_video, corporate
    
    # Dettagli tecnici del progetto
    length_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fps: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shooting_format: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    delivery_format: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Crew / ruoli chiave
    director: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    producer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dop: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Date chiave
    shoot_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    shoot_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    post_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    delivery_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    
    status: Mapped[ProjectStatus] = mapped_column(SAEnum(ProjectStatus), default=ProjectStatus.prospect)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # v3.5.0-alpha.8 — Soft-delete (cestino).
    deleted_at:         Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    deleted_by_user_id: Mapped[Optional[int]]      = mapped_column(ForeignKey("users.id"), nullable=True)

    # v3.5.0-alpha.70.3 — TPN security policy per-progetto.
    # ip_allowlist: JSON con array stringhe CIDR (es. ["1.2.3.0/24","10.0.0.5"]).
    #   Se popolato e DAM access richiesto: l'IP richiedente deve matchare,
    #   altrimenti 403 + log deny. Vuoto/NULL = no restrizione IP.
    # mfa_required: placeholder per α.70.3+ (MFA TOTP), non ancora applicato.
    # min_role_for_access: ruolo minimo richiesto (es. "manager" su progetti
    #   sensibili). Future use.
    ip_allowlist: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    mfa_required: Mapped[bool] = mapped_column(Boolean, default=False)
    min_role_for_access: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # v3.5.0-alpha.90 — Periodicità fatturazione (sprint accrual billing).
    # I batch trasmessi/approvati dal cost report restano "in cassetto" e
    # vengono aggregati in una fattura unica al fine periodo. Valori:
    # - monthly         (default): 1 fattura/mese aggregando tutti i batch
    # - quarterly       : 1 fattura/trimestre
    # - milestone       : su milestone consegna (manuale)
    # - on_completion   : 1 fattura unica alla chiusura progetto
    # - custom          : termini pattuiti in fase di quotazione (manuale)
    # Definito in fase di quotazione, modificabile da manager fino alla
    # prima fattura emessa.
    billing_frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    # v3.5.0-alpha.111 — Giorni scadenza fattura dal cliente. Default ereditato
    # da Tenant.payment_terms_default se NULL. Propagato da Quote.billing_terms_days
    # in fase di promotion Quote→Project.
    billing_terms_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # v3.5.0-alpha.105 — Storage per-project (TPN compartimentazione stagna).
    # Default = ereditato da Tenant (storage_backend + uploads/t{tid}/).
    # Quando settato: il progetto ha la propria area isolata. Asset.file_path
    # punterà sotto storage_root. fs_scan_paths è una whitelist per-progetto
    # che sovrascrive Tenant.fs_scan_allowed_paths (es. cliente A può
    # scansionare solo /Volumes/ClienteA, cliente B solo /Volumes/ClienteB).
    storage_backend: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # local | s3 | s3_minio | s3_r2 | s3_wasabi (S3-compatibile via boto3)
    storage_root: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Local: path assoluto (es. /Volumes/MediaFlow/p42/)
    # S3: prefix (es. s3://mybucket/p42/)
    s3_bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Solo se storage_backend = s3*. ENV var contiene endpoint+access_key+
    # secret per il bucket. Multi-bucket cross-tenant via singolo set credenziali.
    fs_scan_paths: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Lista path filesystem locali autorizzati per scan (override tenant-level).
    # v3.5.0-alpha.94 — Markup % sui costi spedizione riaddebitati al cliente.
    # Quando IngestBatch ha shipping_payer=charged_to_client e questo project
    # è il billable, la JCL auto-generata applica:
    #   unit_price = shipping_cost * (1 + shipping_markup_pct/100)
    # Default 15% (decisione Matteo 13 mag). Configurabile in /quotes editor
    # progetto-side per quote-specifico (es. cliente con accordi diversi).
    # 0 = pass-through esatto del costo vettore (no margine).
    shipping_markup_pct: Mapped[float] = mapped_column(Float, nullable=False, default=15.0, server_default="15.0")

    # v3.5.0-alpha.112 — Chiusura finanziaria progetto.
    # Stato indipendente da `status` operativo (Job.status / ProjectStatus).
    # `active` (default) → progetto operativamente vivo; `closed` → emessa
    # fattura di chiusura, lato finanza non si fattura più nulla.
    # Riapertura solo via storno NC TD04 sulla closing invoice.
    finance_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    finance_closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finance_closing_invoice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoices.id"), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="projects")
    quotes: Mapped[List["Quote"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[List["Job"]] = relationship(back_populates="project")
    milestones: Mapped[List["ProjectMilestone"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="ProjectMilestone.target_date",
    )


# ── PROJECT MILESTONE (v3.5.0-alpha.21) ──────────────────────
#
# Marker di deadline relativo al progetto. NON è un booking (non occupa risorsa,
# non genera ore/costo). È un punto di riferimento temporale: "consegna trailer
# il 15 maggio", "screening cliente il 22 maggio", "DCP master il 30 maggio".
# Visualizzato come linea verticale nella timeline di pianificazione + lista
# nella scheda progetto. Notifica deadline_approaching quando si avvicina.

class ProjectMilestone(Base):
    __tablename__ = "project_milestones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    target_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Colore opzionale (default = colore tema progetto). Hex senza #.
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    # Stato: pending | done | missed (calcolato in UI da target_date vs today
    # quando is_completed=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="milestones")


# ── RISORSE ──────────────────────────────────────────────────

class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[ResourceType] = mapped_column(SAEnum(ResourceType))
    # Ruolo specifico all'interno del reparto (Colorist, Flame Artist, Mixer, ecc.)
    role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    daily_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # ── Cost-rate interno (v3.5.0-alpha.66.9) ────────────────────
    # Le tariffe sopra (daily_rate / hourly_rate) sono di VENDITA al cliente.
    # I campi sotto sono di COSTO interno per cost report → hardcost.
    cost_type: Mapped[Optional[ResourceCostType]] = mapped_column(
        SAEnum(ResourceCostType), nullable=True, index=True
    )
    # Per cost_type=employee: calcolo deterministico
    #   internal_cost_hourly = monthly_gross_salary × annual_bonus_months ×
    #                          cost_multiplier_oneri / annual_working_hours
    monthly_gross_salary: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    annual_bonus_months: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=13.0)
    cost_multiplier_oneri: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=1.30)
    annual_working_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=1720.0)
    # Per cost_type=freelance: tariffa oraria PAGATA al freelance
    # (NON la hourly_rate sopra, che è di vendita al cliente).
    freelance_hourly_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Per cost_type=studio: allocazione oraria della struttura (sala interna).
    # Tariffa fissa decisa dal manager (futuro: derivata via AI da visura).
    studio_hourly_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Contatti (utili per freelance ma validi anche per sale/attrezzature)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    internal_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # v3.5.0-alpha.113 — link a fornitore esterno (la P.IVA che emette
    # fatture passive per questa risorsa). Permette il matching automatico
    # delle fatture ricevute con i booking della risorsa nei job.
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str] = mapped_column(String(7), default="#6272f5")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Override policy orario lavorativo (NULL = usa il default tenant)
    working_hours_policy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("working_hours_policies.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[Optional["User"]] = relationship(back_populates="resources")
    department: Mapped[Optional["Department"]] = relationship(back_populates="resources")
    booking_assignments: Mapped[List["BookingAssignment"]] = relationship(back_populates="resource", cascade="all, delete-orphan")
    unavailabilities: Mapped[List["ResourceUnavailability"]] = relationship(back_populates="resource")
    working_hours_policy: Mapped[Optional["WorkingHoursPolicy"]] = relationship(foreign_keys=[working_hours_policy_id])
    job_assignments: Mapped[List["JobResourceAssignment"]] = relationship(back_populates="resource")
    time_punches: Mapped[List["TimePunch"]] = relationship(back_populates="resource")
    # v3.5.0-alpha.113 — relationship verso fornitore esterno
    supplier: Mapped[Optional["Supplier"]] = relationship(foreign_keys=[supplier_id])

    @property
    def internal_cost_hourly(self) -> Optional[float]:
        """Costo orario aziendale interno per cost report (hardcost ore).
        Derivato dal cost_type. Restituisce None se non configurato.
        """
        ct = self.cost_type
        if ct == ResourceCostType.employee:
            mensile = self.monthly_gross_salary or 0.0
            bonus = self.annual_bonus_months or 13.0
            mult = self.cost_multiplier_oneri or 1.30
            hours = self.annual_working_hours or 1720.0
            if mensile > 0 and hours > 0:
                return round(mensile * bonus * mult / hours, 2)
            return None
        if ct == ResourceCostType.freelance:
            return self.freelance_hourly_cost
        if ct == ResourceCostType.studio:
            return self.studio_hourly_cost
        if ct == ResourceCostType.external:
            # Per external usiamo, in mancanza di altro, hourly_rate (tariffa pagata
            # = tariffa "noleggio" per la sessione, tipicamente coincide con vendita).
            return self.hourly_rate
        return None


# v3.4.50 — Preset di selezione multipla di risorse (es. "Crew base color HDR",
# "Mix audio standard"). Usato dal modal multi-risorsa per caricare in un click
# un set di risorse ricorrenti. Tenant-scoped, condiviso tra utenti dello stesso
# tenant. Visibile a tutti, modificabile solo dal creatore o admin/manager.
class ResourcePreset(Base):
    __tablename__ = "resource_presets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Lista di Resource.id (JSON). L'ordine viene preservato all'apply.
    resource_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UnavailabilityKind(str, enum.Enum):
    vacation = "vacation"     # ferie
    sick = "sick"             # malattia
    holiday = "holiday"        # festività (auto-generata da policy)
    other = "other"


class UnavailabilityStatus(str, enum.Enum):
    pending = "pending"        # creata da staff, in attesa di approvazione
    approved = "approved"      # approvata da admin/manager/producer → blocca planning
    rejected = "rejected"      # rifiutata, non blocca


class ResourceUnavailability(Base):
    __tablename__ = "resource_unavailabilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[UnavailabilityKind] = mapped_column(SAEnum(UnavailabilityKind), default=UnavailabilityKind.vacation)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Workflow approvazione (v3.4.22 cantiere D)
    status: Mapped[UnavailabilityStatus] = mapped_column(
        SAEnum(UnavailabilityStatus), default=UnavailabilityStatus.approved, index=True,
    )
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resource: Mapped["Resource"] = relationship(back_populates="unavailabilities")


# ── ORARIO LAVORATIVO (E3 v3.4.17) ────────────────────────────
# Definisce quando una risorsa è disponibile a essere prenotata.
# Una policy "globale" (is_default=True) per il tenant + override
# per-risorsa via Resource.working_hours_policy_id.

class WorkingHoursPolicy(Base):
    __tablename__ = "working_hours_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(80))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Mattina (sempre presente)
    morning_start: Mapped[time] = mapped_column(Time)  # es. 09:00
    morning_end: Mapped[time] = mapped_column(Time)    # es. 13:00
    # Pomeriggio (opzionale: NULL = orario continuato senza pausa)
    afternoon_start: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    afternoon_end: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    # Giorni lavorativi come bitmask: bit 0 = lun, bit 1 = mar, ..., bit 6 = dom
    # Default 0b0011111 = 31 = lun-ven
    working_days: Mapped[int] = mapped_column(Integer, default=31)
    # Festività auto-importate: paese ISO (es. "IT") o NULL per disabilitare
    holidays_country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, default="IT")
    # ── Soglie e moltiplicatori straordinari (v3.4.21) ──
    # Oltre questa soglia giornaliera (sommando tutti i punch shift del giorno)
    # le ore eccedenti contano come overtime.
    daily_hours_threshold: Mapped[float] = mapped_column(Float, default=8.0)
    # Limite settimanale: ore extra oltre questa soglia (anche se sotto soglia
    # giornaliera) contano come overtime settimanale.
    weekly_hours_threshold: Mapped[float] = mapped_column(Float, default=40.0)
    # Moltiplicatori applicati alle ore eccedenti per il calcolo del costo.
    overtime_multiplier: Mapped[float] = mapped_column(Float, default=1.25)
    night_multiplier: Mapped[float] = mapped_column(Float, default=1.50)
    sunday_multiplier: Mapped[float] = mapped_column(Float, default=1.50)
    holiday_multiplier: Mapped[float] = mapped_column(Float, default=2.00)
    # v3.5.0-alpha.111.19 — Moltiplicatore ore di permesso ROL (Riduzione
    # Orario di Lavoro). Applicato SOLO al report HR per consulente lavoro,
    # NON al cost report / billing. Default 1.0 = neutro (nessun coefficiente).
    # Standard italiano comune: 1.33 (copre TFR + 13ª/14ª proporzionali +
    # ferie accrual). Facoltativo per contratto.
    permit_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    # Fascia notturna: ore tra night_start e night_end del giorno dopo
    # ricevono il night_multiplier (anche se non eccedono soglia diurna).
    night_start: Mapped[Optional[time]] = mapped_column(Time, nullable=True, default=time(22, 0))
    night_end: Mapped[Optional[time]] = mapped_column(Time, nullable=True, default=time(6, 0))
    # v3.4.32.2 — Scaglioni overtime per CCNL.
    # JSON list: [{"from_hour": 0, "multiplier": 1.0}, {"from_hour": 2, "multiplier": 1.30}, ...]
    # Interpretazione: ordinato per from_hour. Le ore overtime di una giornata
    # sono distribuite secondo gli scaglioni: ore 0..2 → 1.0 (base), ore 2..4 → 1.30, ...
    # Se NULL, l'engine usa il singolo `overtime_multiplier`. Configurazione
    # tipica per CCNL Cinema Doppiaggio: prime 2 ore al 30%, poi 60%.
    overtime_brackets: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
    # Etichetta opzionale del CCNL/preset (es. "Italia base", "CCNL Cinema · Doppiaggio")
    ccnl_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── QUOTAZIONE (collegata a Progetto, non più direttamente a Cliente) ──

class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # v3.5.0-alpha.66.15.0 — tenant_id aggiunto in sprint R1 (audit HIGH #1).
    # default=1 per back-compat single-tenant; backfill auto in _auto_migrate.
    # Il vincolo UNIQUE su `number` resta GLOBALE per ora — sarà migrato a
    # UniqueConstraint(tenant_id, number) in R1.5 quando arriverà multi-tenant
    # hard. Memo: per multi-tenant fisico vedi Department/PriceCategory pattern.
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Collegamento: Progetto è primario, Cliente viene dal progetto
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))   # denormalized per query veloci
    
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[QuoteStatus] = mapped_column(SAEnum(QuoteStatus), default=QuoteStatus.draft)
    issue_date: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    
    production_material: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    length_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fps: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    delivery_format: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shooting_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shooting_format: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    package_discount: Mapped[float] = mapped_column(Float, default=0.0)
    # Sconti per categoria (raggruppamento dinamico in fase di rendering quotazione).
    # Mappa {nome_categoria: pct_sconto}, dove pct è positivo (es. 0.15 = 15% sconto).
    # Esempio: {"PICTURE": 0.10, "SOUND": 0.05, "Altro": 0.0}
    category_discounts: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # v3.4.34 — Ordine custom delle categorie (drag&drop in editor).
    # Lista di nomi categoria nell'ordine voluto. Le categorie non listate
    # appaiono dopo nell'ordine naturale (prima riga di una nuova categoria).
    # Esempio: ["PICTURE", "SOUND", "Altro"]
    category_order: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    vat_rate: Mapped[float] = mapped_column(Float, default=22.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # v3.5.0-alpha.111 — Scadenze fatturazione dichiarate in quotazione.
    # billing_frequency: monthly/quarterly/milestone/on_completion/custom (mirror Project).
    # billing_terms_days: giorni scadenza fattura (es. 30/60/90). All'accettazione
    # della quote, questi campi si propagano sul Project di destinazione.
    billing_frequency: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    billing_terms_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # v3.5.0-alpha.106 — Clausola ricarico spedizioni esplicita in quote.
    # Default 15% editabile, riflette Project.shipping_markup_pct ma
    # configurabile per quote (es. cliente con accordi diversi).
    # Quando >0 la clausola viene aggiunta automaticamente al PDF/UI come
    # nota nei "Termini di pagamento" o nel blocco condizioni economiche.
    shipping_markup_pct: Mapped[float] = mapped_column(Float, nullable=False, default=15.0, server_default="15.0")

    # subtotal_gross = somma qty*unit_price*(1+allowance) di tutte le voci, prima di
    # qualsiasi sconto. Mostrato in PDF/UI per visibilità del valore pieno al cliente.
    subtotal_gross: Mapped[float] = mapped_column(Float, default=0.0)
    # subtotal = post-sconti riga + sconti categoria, pre-sconto pacchetto.
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    # total_after_discount = post-sconto pacchetto, base imponibile per IVA.
    total_after_discount: Mapped[float] = mapped_column(Float, default=0.0)
    total_with_vat: Mapped[float] = mapped_column(Float, default=0.0)
    
    # v3.5.0-alpha.77 — Sales pipeline forecast.
    # win_probability_pct: 0..100, override manuale del default-da-status.
    # Default-da-status (vedi `DEFAULT_WIN_PROBABILITY` in quote_forecast.py):
    #   draft=10, sent=30, approved=90, expired=5, rejected=0, superseded=0.
    # expected_close_date: data attesa di firma/incasso (default = issue_date + 30gg
    # se NULL). Usata da forecast mensile cashflow.
    win_probability_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)

    # Tracking AI: se generata da capitolato
    generated_from_deliverables: Mapped[bool] = mapped_column(Boolean, default=False)
    source_document_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # v3.4.39 — Versioning. Una catena di versioni condivide lo stesso "lineage":
    # V1 (root) → V2 (parent_quote_id=V1) → V3 (parent_quote_id=V2). `version` è
    # monotono nella catena. Quando una nuova versione viene approvata e prende il
    # posto della precedente, V_old.status=superseded + V_old.superseded_by_id=V_new.
    parent_quote_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    superseded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    # v3.4.52 — Phantom quote: generata in reverse-flow (booking su progetto senza
    # quote). Stessa struttura di una quote normale (status, lines, total) ma mai
    # inviata al cliente. Visualizzata come anomalia in /finance, può essere
    # promossa a quote di riferimento (toggle is_phantom=False).
    is_phantom: Mapped[bool] = mapped_column(Boolean, default=False)

    # v3.5.0-alpha.7 — Soft-delete (cestino).
    # Una Quote con `deleted_at` non NULL è "in cestino": invisibile alla UI
    # principale (filter automatico via SQLAlchemy event listener), ripristinabile
    # da chi ha `restore_trash`, purgata definitivamente dopo retention.
    # Le QuoteLine non hanno il proprio flag: ereditano lo stato dal parent via
    # relationship Quote.lines (il parent eliminato non è caricabile, le righe
    # diventano de facto invisibili).
    deleted_at:         Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    deleted_by_user_id: Mapped[Optional[int]]      = mapped_column(ForeignKey("users.id"), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="quotes")
    client: Mapped["Client"] = relationship(back_populates="quotes")
    lines: Mapped[List["QuoteLine"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    job: Mapped[Optional["Job"]] = relationship(back_populates="quote", uselist=False)
    parent_quote: Mapped[Optional["Quote"]] = relationship(
        foreign_keys=[parent_quote_id], remote_side=[id], post_update=True)
    superseded_by: Mapped[Optional["Quote"]] = relationship(
        foreign_keys=[superseded_by_id], remote_side=[id], post_update=True)


class QuoteLine(Base):
    __tablename__ = "quote_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id"))
    price_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("price_items.id"), nullable=True)
    section: Mapped[str] = mapped_column(String(10), default="A")
    position: Mapped[str] = mapped_column(String(20), default="A.1")
    description: Mapped[str] = mapped_column(String(255))
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str] = mapped_column(String(20), default="day")
    price_level: Mapped[PriceLevel] = mapped_column(SAEnum(PriceLevel), default=PriceLevel.list_price)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    # allowance = mark-up % (positivo aumenta, negativo riduce). Storico, mantenuto.
    allowance: Mapped[float] = mapped_column(Float, default=0.0)
    # line_discount_pct = sconto sulla singola voce, positivo = riduzione.
    # Es. 0.15 = 15% di sconto. Applicato dopo allowance.
    line_discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    hardcosts: Mapped[float] = mapped_column(Float, default=0.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Override categoria per il raggruppamento in editor/PDF/export.
    # Se NULL, usa price_item.category. Permette di spostare voci tra categorie
    # senza cambiare la voce listino, e di organizzare voci libere (senza price_item).
    category_override: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Per tracking AI matching (quale voce del capitolato ha generato questa riga)
    source_hint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # v3.4.39 — Eredità riga-per-riga nelle nuove versioni di quote.
    # Quando una Quote V2 è creata da V1 (new-version), ogni riga di V2 ha
    # parent_line_id = id della riga sorgente in V1. Permette il re-bind preciso
    # dei JobCostLine durante migrate-job, anche se descrizione/quantity cambiano.
    parent_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quote_lines.id"), nullable=True)
    # v3.5.0-alpha.27 — Riga "opzionale": il totale è calcolato ma non sommato
    # nel subtotal/cat_bucket della quote. Mostrato come blocco separato.
    is_optional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    # v3.5.0-alpha.27 — Etichetta libera per raggruppamento intra-categoria
    # (es. "SKY Originals", "NBCU TechOps", "Beta Film"). Righe consecutive
    # con lo stesso label vengono raggruppate visivamente con header e
    # subtotale di sezione, dentro la categoria.
    section_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # v3.5.0-alpha.64 — Tracciabilità "rimanda al commerciale". Quando una
    # JCL in over/extra viene rimandata via /finance/api/billing/refer-to-sales
    # (α.62) o via /batches/.../refer-to-sales (α.64), la riga [EXTRA] generata
    # punta alla JCL d'origine. Permette badge bidirezionali UI quote↔cost-report
    # e (in futuro) ereditare la catena quando la quote viene promossa a job.
    referred_from_jcl_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_cost_lines.id"), nullable=True, index=True
    )
    quote: Mapped["Quote"] = relationship(back_populates="lines")
    price_item: Mapped[Optional["PriceItem"]] = relationship()
    parent_line: Mapped[Optional["QuoteLine"]] = relationship(
        foreign_keys=[parent_line_id], remote_side=[id], post_update=True)
    referred_from_jcl: Mapped[Optional["JobCostLine"]] = relationship(
        foreign_keys=[referred_from_jcl_id])


# ── JOB (collegato a Progetto) ───────────────────────────────

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # v3.5.0-alpha.66.15.0 — tenant_id aggiunto in sprint R1 (audit HIGH #1).
    # Vedi nota su Quote.tenant_id per la policy UNIQUE su `code`.
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    quote_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quotes.id"), nullable=True, unique=True)
    
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus), default=JobStatus.draft)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    budget_quoted: Mapped[float] = mapped_column(Float, default=0.0)
    # v3.5.0-alpha.65 — Pass-through OT al cliente (opt-in per progetto).
    # Quando True, l'engine `compute_assignment_breakdown.weighted_factor`
    # alimenta JCL.quantity_actual (e quindi total_accrued) → l'overtime/notte/
    # domenica/festivo gonfia anche il MATURATO cliente. Default False:
    # comportamento storico (giornate fisiche, OT solo cost-side via
    # `_bookings_hours_cost`). Si abilita su progetti dove il cliente ha
    # accettato addendum di pass-through (rush, urgenze, festivi).
    weighted_revenue: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["Project"] = relationship(back_populates="jobs")
    client: Mapped["Client"] = relationship(back_populates="jobs")
    quote: Mapped[Optional["Quote"]] = relationship(back_populates="job")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="job")
    timesheets: Mapped[List["Timesheet"]] = relationship(back_populates="job")
    invoices: Mapped[List["Invoice"]] = relationship(back_populates="job")
    assets: Mapped[List["Asset"]] = relationship(back_populates="job")
    resource_assignments: Mapped[List["JobResourceAssignment"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    cost_lines: Mapped[List["JobCostLine"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    expenses: Mapped[List["Expense"]] = relationship(back_populates="job")


class JobResourceAssignment(Base):
    __tablename__ = "job_resource_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    planned_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    planned_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    agreed_daily_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    agreed_hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    role_in_project: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    job: Mapped["Job"] = relationship(back_populates="resource_assignments")
    resource: Mapped["Resource"] = relationship(back_populates="job_assignments")


class JobCostLine(Base):
    __tablename__ = "job_cost_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # v3.5.0-alpha.66.15.0 — tenant_id aggiunto in sprint R1 (audit HIGH #1).
    # Denormalized da job.tenant_id per scope efficiente nel cost-report.
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    quote_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quote_lines.id"), nullable=True)
    price_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("price_items.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(255))
    quantity_quoted: Mapped[float] = mapped_column(Float, default=0.0)
    quantity_actual: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(20), default="day")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    total_quoted: Mapped[float] = mapped_column(Float, default=0.0)
    total_accrued: Mapped[float] = mapped_column(Float, default=0.0)
    total_expected: Mapped[float] = mapped_column(Float, default=0.0)
    is_billable: Mapped[bool] = mapped_column(Boolean, default=True)
    # v3.5.0-alpha.66.21 — α.67 cost-side risorsa.
    # Somma ore_done × Resource.internal_cost_hourly per ciascun assignment
    # del booking associato. Permette margine reale = total_accrued − total_cost_accrued.
    # Popolato da `recompute_cost_line_actual` insieme a `total_accrued`.
    # 0.0 se nessun assignment ha cost_type configurato (es. tutte freelance senza tariffa).
    # v3.5.0-alpha.115 — Cost STIMATO (rate × ore done teorico).
    total_cost_accrued: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # v3.5.0-alpha.115 — Cost REALE: Σ SupplierInvoice.amount_total delle
    # fatture passive linkate via SupplierInvoice.resource_id a risorse che
    # hanno booking su questa JCL. Permette confronto stimato vs reale:
    # discrepanza = forecast anomaly (sezione finance).
    # 0.0 se nessuna fattura passiva linkata.
    total_cost_external: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # v3.5.0-alpha.115 — Dirty flag per reconcile lazy (perf).
    # Booking-mutate paths settano True; reconcile-all WHERE stale=True ricomputa.
    accrued_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Lavorazione "extra": aggiunta dopo l'approvazione della quote (es. cliente
    # chiede un upres in più). quote_line_id è NULL per gli extra puri.
    # Una riga ereditata dalla quote può comunque generare extra senza is_extra=True
    # se quantity_actual > quantity_quoted (sforamento monte ore).
    is_extra: Mapped[bool] = mapped_column(Boolean, default=False)
    work_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # v3.5.0-alpha.46 — flow Cost Report ↔ Fatturazione.
    # Stato fatturazione della singola riga: progredisce da `not_billed`
    # (maturato in cost report ma non ancora trasmesso) → `in_batch`
    # (incluso in BillingBatch in approvazione) → `billed` (fattura
    # emessa) → `paid`. Ramo alternativo `lost` se il manager scarta
    # in approvazione. `billed_amount` è l'importo effettivo fatturato
    # (può differire da `total_accrued` se il manager ha modificato
    # l'importo nel batch, il delta finisce in LossEntry).
    billing_status: Mapped[JCLBillingStatus] = mapped_column(
        SAEnum(JCLBillingStatus), default=JCLBillingStatus.not_billed, index=True
    )
    billing_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("billing_batches.id"), nullable=True, index=True
    )
    billed_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    job: Mapped["Job"] = relationship(back_populates="cost_lines")
    # v3.4.33 — relazione opzionale a PriceItem (mancava, causava AttributeError
    # quando il cost_report tentava joinedload(JobCostLine.price_item)).
    price_item: Mapped[Optional["PriceItem"]] = relationship(foreign_keys=[price_item_id])


# ── PLANNING ─────────────────────────────────────────────────

class Booking(Base):
    """Booking = contenitore di N risorse impegnate sullo stesso job/lavorazione,
    ognuna con il suo intervallo. Le assegnazioni vivono in BookingAssignment.
    `start_datetime`/`end_datetime` sono l'envelope (min/max degli assignments)."""
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    # job_id nullable: NULL per booking interni (manutenzione, R&D, training)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    job_cost_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_cost_lines.id"), nullable=True, index=True)
    # v3.5.0-alpha.66.9 — Booking attribuibili a un JobDeliverable specifico.
    # Quando settato, le ore del booking accumulano hardcost interno per il
    # deliverable (ore × Resource.internal_cost_hourly). NULL = booking generico
    # di lavorazione, non legato a un deliverable specifico.
    job_deliverable_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_deliverables.id"), nullable=True, index=True
    )
    # Envelope min/max degli assignments. Auto-calcolato dal router al save.
    start_datetime: Mapped[datetime] = mapped_column(DateTime)
    end_datetime: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[BookingStatus] = mapped_column(SAEnum(BookingStatus), default=BookingStatus.tentative)
    kind: Mapped[BookingKind] = mapped_column(SAEnum(BookingKind), default=BookingKind.project)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ── Stato unificato (v3.5.0-alpha.66.5) ─────────────────────
    # Campo CANONICO del ciclo di vita del booking. UI mostra solo questo.
    # `status` e `execution_status` sotto restano per back-compat con
    # slice-lock, billing, recompute. Sincronizzati automaticamente via
    # `apply_state_to_booking()` quando state cambia.
    state: Mapped[BookingState] = mapped_column(
        SAEnum(BookingState), default=BookingState.tentative, index=True
    )
    # ── Booking esecutivo (v3.4.32) — DEPRECATED, derivato da state ────
    priority: Mapped[BookingPriority] = mapped_column(
        SAEnum(BookingPriority), default=BookingPriority.normal, index=True
    )
    execution_status: Mapped[BookingExecutionStatus] = mapped_column(
        SAEnum(BookingExecutionStatus), default=BookingExecutionStatus.planned, index=True
    )
    not_done_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Pool not_done: default False = NON entra nei costi del cost report.
    # Manager/producer può flippare a True per far conteggiare comunque le ore.
    count_in_costs: Mapped[bool] = mapped_column(Boolean, default=False)
    overtime_status: Mapped[BookingOvertimeStatus] = mapped_column(
        SAEnum(BookingOvertimeStatus), default=BookingOvertimeStatus.none, index=True
    )
    # Snapshot dell'envelope originale prima di adaptive extend, per supportare
    # revert/split su rifiuto overtime (D1).
    original_end_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    job: Mapped[Optional["Job"]] = relationship(back_populates="bookings")
    cost_line: Mapped[Optional["JobCostLine"]] = relationship()
    assignments: Mapped[List["BookingAssignment"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingAssignment.start_datetime"
    )


class BookingAssignment(Base):
    """N risorse per booking, ognuna con il suo intervallo (può differire dal padre)."""
    __tablename__ = "booking_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    start_datetime: Mapped[datetime] = mapped_column(DateTime)
    end_datetime: Mapped[datetime] = mapped_column(DateTime)
    booking: Mapped["Booking"] = relationship(back_populates="assignments")
    resource: Mapped["Resource"] = relationship(back_populates="booking_assignments")


class BookingChange(Base):
    """Audit log delle modifiche ai booking (E5 v3.4.19).
    `kind` = create/update/delete/restore. `payload` = JSON snapshot di cosa è cambiato."""
    __tablename__ = "booking_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # create/update/delete/restore/assignment_*
    summary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ── TIMBRATURE / PRESENZE (HR) ─────────────────────────────────
# Dominio separato dal Booking: il booking esprime un'intenzione di pianificazione
# (chi sarà su quale job e quando), il TimePunch registra una presenza effettiva
# (chi è stato a lavoro e per quanto). Tutte le risorse umane (interne + freelance)
# rendicontano qui. Lavorare su un job = TimePunch con kind=shift e job_id valorizzato.

class TimePunch(Base):
    __tablename__ = "time_punches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    # Job opzionale: solo per kind=shift quando si lavora su un progetto specifico.
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    # Riferimento alla lavorazione specifica: permette di consuntivare ore reali
    # contro il monte ore di una specifica JobCostLine (extra calcolato per riga).
    job_cost_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_cost_lines.id"), nullable=True, index=True)
    start_datetime: Mapped[datetime] = mapped_column(DateTime)
    # end_datetime nullable = "in corso" (timbratura ingresso senza ancora uscita).
    end_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    kind: Mapped[PunchKind] = mapped_column(SAEnum(PunchKind), default=PunchKind.shift)
    # Pausa pranzo (minuti) sottratta al totale ore lavorate del shift.
    # Default 60 min, opzioni 0..240 a step 15 nel modal. Solo per kind=shift.
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Chi ha registrato la timbratura (manager/HR per freelance senza login).
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resource: Mapped["Resource"] = relationship(back_populates="time_punches")
    job: Mapped[Optional["Job"]] = relationship()
    cost_line: Mapped[Optional["JobCostLine"]] = relationship()


# ── TIMESHEET & SPESE ────────────────────────────────────────

class Timesheet(Base):
    __tablename__ = "timesheets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    cost_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_cost_lines.id"), nullable=True)
    work_date: Mapped[date] = mapped_column(Date)
    hours: Mapped[float] = mapped_column(Float)
    hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_billable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped["User"] = relationship(back_populates="timesheets")
    job: Mapped["Job"] = relationship(back_populates="timesheets")


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float)
    expense_date: Mapped[date] = mapped_column(Date)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_billable: Mapped[bool] = mapped_column(Boolean, default=True)
    receipt_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    job: Mapped["Job"] = relationship(back_populates="expenses")


# ── FORNITORI / FATTURE PASSIVE (v3.5.0-alpha.68) ────────────
# Modulo nuovo per tracciare commesse esterne / freelance fatturati
# direttamente al tenant (non risorse interne). Punto 6 della roadmap
# billing α.65+. SupplierInvoice è "passiva" (in entrata, costo per
# il tenant) → contribuisce al cost report come hardcost esterno e al
# cashflow come outflow.

class SupplierInvoiceStatus(str, enum.Enum):
    """Stato pagamento fattura passiva (visto dal tenant pagatore)."""
    unpaid = "unpaid"       # ricevuta, non ancora pagata
    partial = "partial"     # pagata parzialmente (amount_paid > 0 ma < total)
    paid = "paid"           # saldata
    cancelled = "cancelled" # annullata (storno o errore)


class Supplier(Base):
    """Anagrafica fornitore/commessa esterna. Soft-delete via deleted_at."""
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    vat_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tax_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    iban: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    default_payment_terms_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    invoices: Mapped[List["SupplierInvoice"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )


class SupplierInvoice(Base):
    """Fattura passiva ricevuta da un fornitore. Può essere associata a
    project (più granulare) o direttamente a job o job_cost_line.

    `amount_total = amount_net + amount_vat`. `amount_paid` denormalizzato
    per query veloci (= Σ payments.amount). `payment_status` derivato
    canonico: unpaid|partial|paid|cancelled.

    v3.5.0-alpha.68.2 — pagamenti storicizzati in SupplierInvoicePayment
    (analogia con InvoicePayment). `payment_date` resta come "ultima
    data di saldo" per back-compat/UX, ma la fonte verità è la tabella
    payments per il cashflow."""
    __tablename__ = "supplier_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    number: Mapped[str] = mapped_column(String(80), index=True)
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    job_cost_line_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_cost_lines.id"), nullable=True, index=True
    )
    # v3.5.0-alpha.113 — link a risorsa esterna (freelance/studio/equipment).
    # Permette di marcare la fattura passiva come "costo di QUESTA risorsa",
    # così il match con i booking del job genera la quadratura preventivo/
    # consuntivo costo-side. Opzionale.
    resource_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resources.id"), nullable=True, index=True
    )
    amount_net: Mapped[float] = mapped_column(Float, default=0.0)
    vat_rate: Mapped[float] = mapped_column(Float, default=22.0)
    amount_vat: Mapped[float] = mapped_column(Float, default=0.0)
    amount_total: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    payment_status: Mapped[SupplierInvoiceStatus] = mapped_column(
        SAEnum(SupplierInvoiceStatus), default=SupplierInvoiceStatus.unpaid, index=True
    )
    amount_paid: Mapped[float] = mapped_column(Float, default=0.0)
    attachment_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    supplier: Mapped["Supplier"] = relationship(back_populates="invoices")
    # v3.5.0-alpha.113 — relationship per joinedload in lista
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])
    job: Mapped[Optional["Job"]] = relationship(foreign_keys=[job_id])
    resource: Mapped[Optional["Resource"]] = relationship(foreign_keys=[resource_id])
    payments: Mapped[List["SupplierInvoicePayment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class SupplierInvoicePayment(Base):
    """Pagamento (anche parziale) verso un fornitore (v3.5.0-alpha.68.2).
    Analogia esatta con InvoicePayment. amount_paid sull'invoice è
    denormalizzato; fonte verità sono i payments."""
    __tablename__ = "supplier_invoice_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    supplier_invoice_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_invoices.id"), index=True
    )
    amount: Mapped[float] = mapped_column(Float)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    method: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    recorded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    invoice: Mapped["SupplierInvoice"] = relationship(back_populates="payments")


# ── FATTURE ──────────────────────────────────────────────────

class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    quote_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    status: Mapped[InvoiceStatus] = mapped_column(SAEnum(InvoiceStatus), default=InvoiceStatus.draft)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    vat_rate: Mapped[float] = mapped_column(Float, default=22.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # v3.5.0-alpha.52 — Tipo documento + condizioni pagamento + IBAN snapshot
    doc_type: Mapped[str] = mapped_column(String(8), default="TD01")          # TD01=fattura ord, TD04=NC, TD06=parcella
    payment_method: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payment_terms_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    iban_snapshot: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # Snapshot fiscali cliente (cessionario) al momento dell'emissione — immutabili
    client_legal_name_snap: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_vat_snap: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    client_tax_code_snap: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    client_pec_snap: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_sdi_snap: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # v3.5.0-alpha.113 — Email amministrazione cliente snapshot
    client_admin_email_snap: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_address_snap: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_zip_snap: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    client_city_snap: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    client_province_snap: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    client_country_snap: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Snapshot fiscali tenant (cedente) al momento dell'emissione
    tenant_legal_name_snap: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tenant_vat_snap: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tenant_tax_code_snap: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tenant_address_snap: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tenant_email_snap: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tenant_phone_snap: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tenant_iban_snap: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    tenant_sdi_snap: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    tenant_rea_snap: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    tenant_fiscal_capital_snap: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tenant_fiscal_regime_snap: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    # v3.5.0-alpha.66.20 — pagamenti denormalizzati
    amount_paid: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # v3.5.0-alpha.112 — Fattura di chiusura progetto.
    # Quando True, è l'ultima fattura del Project: il PDF include sezione
    # riepilogo di tutte le fatture precedenti del progetto. L'emissione
    # marca Project.finance_status='closed'. Storno via NC TD04 → riapre.
    is_closing: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    closing_project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True)
    client: Mapped["Client"] = relationship(back_populates="invoices")
    job: Mapped[Optional["Job"]] = relationship(back_populates="invoices")
    lines: Mapped[List["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payments: Mapped[List["InvoicePayment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit_price: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)
    # v3.5.0-alpha.52 — IVA per riga + sconto % per riga
    vat_rate: Mapped[float] = mapped_column(Float, default=22.0)
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    invoice: Mapped["Invoice"] = relationship(back_populates="lines")


# ── Pagamenti fattura (v3.5.0-alpha.66.20) ────────────────────
# Sblocca cashflow revenue-side: una fattura può ricevere uno o più
# pagamenti parziali (es. acconto + saldo). amount_paid sull'Invoice è
# denormalizzato per query veloci, fonte verità sono i pagamenti.
class InvoicePayment(Base):
    __tablename__ = "invoice_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    # Metodo libero (bonifico/cassa/carta/assegno/altro) — string, no enum:
    # i metodi cambiano per paese/banca, vogliamo flessibilità senza migrazione.
    method: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Riferimento bancario / TRN (per riconciliazione futura con estratto conto)
    reference: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    recorded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    invoice: Mapped["Invoice"] = relationship(back_populates="payments")


# ── Cost report → Billing flow (v3.5.0-alpha.46) ──────────────
# Workflow: il Cost Report aggrega le JobCostLine maturate (ore done × tariffa)
# di un periodo (mese tipico, oppure extra). Producer/admin "trasmette" a
# fatturazione → si crea un BillingBatch in stato draft con snapshot delle
# righe (BillingBatchLine). Il manager rivede in /finance, eventualmente
# modifica gli importi → ogni riduzione genera una LossEntry tracciata.
# Approva → status approved. Emessa fattura (Invoice) → status invoiced,
# JCL.billing_status passa a `billed`. Pagata → JCL → `paid`. A progetto
# chiuso, producer comunica fine lavorazioni → si emette fattura finale
# con extra a consuntivo + perso totale aggregato per rendicontazione.

class BillingBatch(Base):
    """Proposta di fatturazione (mensile o extra). Aggrega righe maturate
    di un progetto in un periodo, prima di emettere la Invoice.

    Lo `code` segue pattern `BB-{anno}-{NNN}` univoco per tenant.
    `total_*` sono cache numeriche aggiornate al transmit/approve."""
    __tablename__ = "billing_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[BillingBatchStatus] = mapped_column(
        SAEnum(BillingBatchStatus), default=BillingBatchStatus.draft, index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    # Snapshot importo proposto al momento della trasmissione (somma JCL maturate).
    # `total_approved` viene aggiornato dal manager in fase di approvazione.
    # `total_lost` = total_proposed - total_approved (delta tracked in LossEntry).
    total_proposed: Mapped[float] = mapped_column(Float, default=0.0)
    total_approved: Mapped[float] = mapped_column(Float, default=0.0)
    total_lost: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Audit
    transmitted_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    transmitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    project: Mapped["Project"] = relationship()
    invoice: Mapped[Optional["Invoice"]] = relationship(foreign_keys=[invoice_id])
    lines: Mapped[List["BillingBatchLine"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class BillingBatchLine(Base):
    """Snapshot di una JobCostLine al momento della trasmissione al batch.

    I campi snapshot evitano inconsistenze: se la JCL viene modificata dopo
    il transmit (es. nuove ore lavorate), il batch resta con i valori al
    momento dell'invio. `total_proposed` = importo originale, `total_approved`
    può essere diverso se il manager ha ridotto l'importo (delta → LossEntry)."""
    __tablename__ = "billing_batch_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("billing_batches.id", ondelete="CASCADE"), index=True)
    job_cost_line_id: Mapped[int] = mapped_column(ForeignKey("job_cost_lines.id"), index=True)
    # Snapshot per audit / immutabilità documento
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(20), default="day")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    total_proposed: Mapped[float] = mapped_column(Float, default=0.0)
    total_approved: Mapped[float] = mapped_column(Float, default=0.0)
    is_extra: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    batch: Mapped["BillingBatch"] = relationship(back_populates="lines")
    job_cost_line: Mapped["JobCostLine"] = relationship(foreign_keys=[job_cost_line_id])


class LossEntry(Base):
    """Voce 'perso' nel report finanziario. Generata quando manager riduce
    l'importo di una BillingBatchLine in approvazione, o quando una JCL viene
    write-off a chiusura progetto.

    `amount` sempre positivo = importo NON fatturato/recuperato. Aggregato
    per progetto nella rendicontazione finanziaria finale."""
    __tablename__ = "loss_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    job_cost_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_cost_lines.id"), nullable=True, index=True)
    billing_batch_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("billing_batch_lines.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[LossReason] = mapped_column(SAEnum(LossReason), default=LossReason.manager_discount)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    project: Mapped["Project"] = relationship()
    job_cost_line: Mapped[Optional["JobCostLine"]] = relationship(foreign_keys=[job_cost_line_id])


# v3.5.0-alpha.58 — JCLBilledSlice: porzione di una JCL fatturata in uno
# specifico periodo. Supera il binario JCLBillingStatus che imprigiona la
# JCL come "billed" anche se il lavoro continua su periodi successivi.
#
# Una JCL può avere N slice nel tempo (es. progetto trimestrale fatturato
# mensilmente: tre slice distinti, ognuno copre il maturato del proprio
# mese). Lo slice è un oggetto immutabile (snapshot al momento della
# emissione fattura) — modifiche successive a JCL non lo toccano.
#
# Used by α.59 (hard-block backedit booking dentro periodo già slice-ato),
# α.60 (cost report 3 colonne: slice-ato/post-periodo/futuro), α.61
# (notifica EXTRA_AFTER_BILLED quando emerge extra su periodo già chiuso).
class JCLBilledSlice(Base):
    """Snapshot della porzione di JobCostLine fatturata per uno specifico
    periodo. Generato in `emit_invoice` (uno per BillingBatchLine con
    total_approved>0) e mai modificato post-creazione.

    `period_start`/`period_end` ricalcano il periodo del BillingBatch da
    cui lo slice deriva. `billed_quantity`/`billed_amount` snapshottano
    la quantità e l'importo realmente fatturati (corrispondono a
    BillingBatchLine.quantity e BillingBatchLine.total_approved).

    Invariante α.59: i Booking done con start_datetime.date() compreso
    in [period_start, period_end] di una slice della loro JCL non sono
    più editabili (HARD-BLOCK 409 — uscita formale via endpoint dedicato
    di rettifica)."""
    __tablename__ = "jcl_billed_slices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    job_cost_line_id: Mapped[int] = mapped_column(
        ForeignKey("job_cost_lines.id"), index=True
    )
    billing_batch_line_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("billing_batch_lines.id"), nullable=True, index=True
    )
    invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("invoices.id"), nullable=True, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    billed_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    billed_amount: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price_snap: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # v3.5.0-alpha.111 — Storno fattura: slice resa nulla da una nota di
    # credito (TD04). Quando popolato, lo slice non blocca più i booking
    # nel periodo: il maturato torna disponibile per nuova fatturazione.
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    voided_by_invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("invoices.id"), nullable=True
    )
    job_cost_line: Mapped["JobCostLine"] = relationship(foreign_keys=[job_cost_line_id])
    billing_batch_line: Mapped[Optional["BillingBatchLine"]] = relationship(
        foreign_keys=[billing_batch_line_id]
    )
    invoice: Mapped[Optional["Invoice"]] = relationship(foreign_keys=[invoice_id])


# ── DAM ──────────────────────────────────────────────────────

class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class AssetTag(Base):
    __tablename__ = "asset_tags"
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


# ── PROJECT ACCESS / TPN COMPLIANCE (v3.5.0-alpha.70) ─────────
# Compartimentalizzazione DAM e access control per progetto. Implementa
# il principio TPN "need-to-know": un utente vede solo gli asset dei
# progetti a cui è esplicitamente assegnato (o derivato da
# JobResourceAssignment via Resource.user_id).
#
# 3 livelli di accesso:
#   1. Admin → bypass (vede tutto, audit log)
#   2. ProjectAccessGrant esplicito (producer/manager/external) → True
#   3. JobResourceAssignment via Resource.user_id → True (auto-grant
#      staff/operator basato su pianificazione)
# Default = no access.

class ProjectAccessGrant(Base):
    """Concessione esplicita di accesso a un progetto per un user.
    Soft-revoke via `revoked_at`. Granted da admin/manager via UI."""
    __tablename__ = "project_access_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Ruolo nel progetto (informativo per UI). Non condiziona access RBAC
    # (per quello servono i permessi globali). Esempi: "producer",
    # "external_consultant", "client_observer", "auditor".
    role_in_project: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    revoked_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AssetAccessAction(str, enum.Enum):
    """Azioni tracciate nel log accessi asset (audit TPN)."""
    view = "view"
    download = "download"
    upload = "upload"
    delete = "delete"
    update = "update"
    share = "share"
    deny = "deny"   # tentativo accesso negato (audit trail security)


class AssetAccessLog(Base):
    """Audit trail accessi/azioni su Asset. Append-only. v3.5.0-alpha.70.1.
    Conservato indefinitamente per compliance TPN (no retention).
    Indici per query per asset, per user, per ts."""
    __tablename__ = "asset_access_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("assets.id"), nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[AssetAccessAction] = mapped_column(
        SAEnum(AssetAccessAction), index=True
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extra: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Asset(Base):
    """Asset DIGITALE in DAM. File: ProRes, DCP master, IMF, immagini, audio,
    sub. Per asset FISICI (LTO, HDD, CRU, Blu-Ray, ecc.) vedi PhysicalAsset.

    v3.5.0-alpha.70 — TPN: project_id=NULL ⇒ "internal queue" visibile solo
    a admin + uploader, finché non viene assegnato a un progetto.
    """
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # v3.5.0-alpha.66.15.0 — tenant_id aggiunto in sprint R1 (audit HIGH #1).
    # Denormalized da project.tenant_id (asset → project.tenant_id implicito)
    # per scope diretto dal DAM senza JOIN.
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    asset_type: Mapped[AssetType] = mapped_column(SAEnum(AssetType))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    # v3.5.0-alpha.66.9 — Bridge DAM ↔ JobDeliverable + flag archive/delivery.
    # Lega l'asset al deliverable di produzione di cui rappresenta "il file".
    # Promosso dall'utente con click "Questo è il file finale per [deliverable]".
    job_deliverable_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_deliverables.id"), nullable=True, index=True
    )
    # Flag ortogonali (un asset può essere SIA archiviato internamente SIA
    # consegnato a qualcuno — es. master DPX su LTO interno + drive USB al cliente).
    is_internal_archive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_delivered_external: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_method: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    delivery_tracking: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    job: Mapped[Optional["Job"]] = relationship(back_populates="assets")
    uploaded_by_user: Mapped["User"] = relationship(back_populates="assets")
    tags: Mapped[List["Tag"]] = relationship(secondary="asset_tags")
    versions: Mapped[List["Asset"]] = relationship(
        foreign_keys=[parent_asset_id], back_populates="parent")
    parent: Mapped[Optional["Asset"]] = relationship(
        foreign_keys=[parent_asset_id], back_populates="versions", remote_side=[id])


# ── ASSET MOVEMENTS / LOGISTICS (v3.5.0-alpha.72) ─────────────
# Movimenti ingest/outgest di PhysicalAsset: bolle di ingresso/uscita,
# tracking corriere, dettaglio collo, conferma consegna, etichetta QR.
# Append-only per audit completo.

class AssetMovementType(str, enum.Enum):
    """Tipologia movimento asset fisico."""
    ingest = "ingest"           # ingresso (cliente → noi, fornitore → noi)
    outgest = "outgest"         # uscita (noi → cliente, noi → terzo)
    transfer = "transfer"       # spostamento interno (stanza → cassaforte)
    return_to_client = "return_to_client"   # restituzione (era prestito)
    return_from_client = "return_from_client"  # cliente restituisce nostro


class AssetOwnerType(str, enum.Enum):
    """Proprietà del PhysicalAsset. TPN-relevant: asset cliente
    richiedono tracking dedicato."""
    internal = "internal"           # nostro (default)
    client = "client"               # proprietà cliente, custodia temporanea
    supplier = "supplier"           # noleggio da fornitore (es. CRU)
    third_party = "third_party"     # altro (es. consulente esterno)


class AssetMembership(Base):
    """v3.5.0-alpha.74 — Link N:M digital Asset → PhysicalAsset con storico.

    Use case: HDD cliente con DCP + mix audio + sub. Sapere quando è stato
    aggiunto/rimosso ogni file, da chi, con quale path.
    `removed_at` IS NULL = ancora presente sul supporto.
    """
    __tablename__ = "asset_memberships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    physical_asset_id: Mapped[int] = mapped_column(
        ForeignKey("physical_assets.id"), index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    # Path/posizione sul supporto fisico (es. "/DCP/feature_2k/", "/MIX/")
    path_on_media: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Checksum salvato (per verifica integrità futura)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    added_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    removed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class IngestBatch(Base):
    """v3.5.0-alpha.73 — Raggruppa N AssetMovement nello stesso DDT (bolla).
    Use case: cliente consegna 1 disco con 5 file digitali → 1 IngestBatch
    + 1 AssetMovement physical (il disco) + 5 AssetMovement digital (i file)
    + 1 manifest CSV/JSON con checksum.

    v3.5.0-alpha.93 — Estesa a "Shipment" (spedizione vera e propria):
    raggruppa più colli con costo unico, vettore unico, e tracking del
    payer (internal / client_direct / charged_to_client). Se charged_to_client
    genera JobCostLine automatica nella categoria "Spedizioni" del Job
    referenziato in billable_to_project_id, riaddebitando il costo al
    cliente nel ciclo di fatturazione standard.
    """
    __tablename__ = "ingest_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # BATCH-YYYY-NNN
    direction: Mapped[str] = mapped_column(String(20), default="ingest")  # ingest/outgest
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True, index=True)
    delivery_note_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    batch_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    manifest_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # v3.5.0-alpha.93 — Spedizione (vettore + costo + payer)
    # carrier/tracking a livello batch (sostituisce dato sparso su singolo
    # movimento; i movement mantengono i loro per back-compat ma il batch
    # è la sorgente canonica per spedizioni raggruppate).
    carrier: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    shipping_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # shipping_payer: chi sostiene il costo della spedizione.
    # - internal:           costo a carico nostro, no riaddebito (entra solo
    #                       come costo interno nel cost report).
    # - client_direct:      cliente paga DIRETTO al vettore (nostro costo = 0,
    #                       audit only).
    # - charged_to_client:  noi anticipiamo, riaddebitiamo via JCL Spedizioni
    #                       sul Job di billable_to_project_id.
    shipping_payer: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # pickup_mode: chi gestisce ritiro/consegna.
    # - we_ship:                noi diamo i colli al nostro corriere (carrier nostro).
    # - client_carrier_pickup:  cliente manda corriere a ritirare (carrier del cliente).
    # - client_in_person:       cliente ritira di persona (no corriere).
    pickup_mode: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # Per "charged_to_client" e "internal" che vuole tracking progetto.
    billable_to_project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    # JCL generata automaticamente al save (se charged_to_client).
    # Permette di evitare duplicati e tracciare il riaddebito back-ref.
    auto_billed_jcl_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_cost_lines.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class AssetMovement(Base):
    """Movimento logistico di un Asset (digital o physical). Append-only audit.

    v3.5.0-alpha.73: asset_id (digital) E physical_asset_id (physical) MUTEX:
    almeno uno valorizzato, ma non entrambi. Constraint logico (SQLite no CHECK).
    """
    __tablename__ = "asset_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    # v3.5.0-alpha.73 — Mutex: physical_asset_id OR asset_id (digital)
    physical_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("physical_assets.id"), nullable=True, index=True
    )
    asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("assets.id"), nullable=True, index=True
    )
    ingest_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ingest_batches.id"), nullable=True, index=True
    )
    movement_type: Mapped[AssetMovementType] = mapped_column(
        SAEnum(AssetMovementType), index=True
    )
    # Bolla di consegna / DDT (Delivery Note)
    delivery_note_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    movement_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expected_return_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Mittente / Destinatario (text libero, può linkare a Client/Supplier
    # tramite from_client_id / to_client_id o lasciare descrittivo)
    from_party: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    from_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    from_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    to_party: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    to_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    to_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # FK opt a Client / Supplier per traccia esplicita
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True, index=True)
    # Dettaglio collo
    package_count: Mapped[int] = mapped_column(Integer, default=1)
    total_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dimensions_lwh_cm: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)  # "30x20x10"
    contents_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Spedizione
    carrier: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    shipping_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Conferma consegna/ritiro
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    confirmed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_by_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # nome firma manuale
    # Allegati (PDF bolla firmata, foto del collo, ecc.)
    attachment_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    signature_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


# v3.5.0-alpha.66.9 — Asset FISICO (LTO/HDD/CRU/Blu-Ray/DVD/Case).
# Modello separato da Asset (file digitale): la gestione di un supporto
# fisico (location, courier, batch, calibrazione, capacità) è strutturalmente
# diversa dal video/codec/container di un file digitale.
class PhysicalAsset(Base):
    __tablename__ = "physical_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    job_deliverable_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_deliverables.id"), nullable=True, index=True
    )
    kind: Mapped[PhysicalAssetKind] = mapped_column(SAEnum(PhysicalAssetKind), index=True)
    label: Mapped[str] = mapped_column(String(255))                  # es. "LTO #042 - Mare Nostrum"
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    capacity_gb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # capacità nominale
    used_gb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)      # spazio occupato
    # Stato fisico/condizione (per nastri: nuovo / verificato / sospetto / dismesso).
    condition: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # Location dove si trova fisicamente (es. "Cassaforte sala server", "Spedito al cliente").
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    custodian_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Flag ortogonali (vedi commento Asset).
    is_internal_archive: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_delivered_external: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Campi consegna (popolati quando is_delivered_external=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    courier: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Costo del supporto (€) — usato come hardcost in cost report quando il
    # supporto è venduto al cliente (non quando è archivio interno).
    unit_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Hash di integrità (MD5/xxHash) calcolato al write/verify
    checksum_md5: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    checksum_xxhash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Per tape LTO: data ultima verifica integrità + scadenza calibrazione
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_verification_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    # v3.5.0-alpha.72 — Ownership tracking (TPN: asset cliente vanno
    # tracciati a parte da quelli interni).
    owner_type: Mapped[AssetOwnerType] = mapped_column(
        SAEnum(AssetOwnerType), default=AssetOwnerType.internal, index=True
    )
    owner_client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id"), nullable=True, index=True
    )
    owner_supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True, index=True
    )
    owner_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # QR token univoco per scan / etichetta. Generato al create.
    qr_code_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)
    # Stato logistico corrente (derivato ma denormalizzato per query rapide)
    # Es. "in_storage", "transit_out", "delivered_external", "transit_in"
    logistics_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)


# v3.5.0-alpha.66.9 — JobDeliverable: nodo di produzione tra JobCostLine
# (riga prezzo cliente) e Asset/PhysicalAsset (file/supporto consegnato).
# - spec_json cristallizza le specifiche tecniche dal DeliveryTemplate
#   al momento della pianificazione.
# - status traccia il workflow planned → in_production → file_attached →
#   qc_passed → delivered → accepted.
# - Booking.job_deliverable_id collega le ore di produzione a questo deliverable
#   per calcolare l'hardcost interno (ore × Resource.internal_cost_hourly).
# - Asset.job_deliverable_id (digital) o PhysicalAsset.job_deliverable_id
#   (fisico) — mutually exclusive a livello di "file consegnato".
class JobDeliverable(Base):
    __tablename__ = "job_deliverables"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    job_cost_line_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_cost_lines.id"), nullable=True, index=True
    )
    price_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("price_items.id"), nullable=True, index=True
    )
    # Identità
    name: Mapped[str] = mapped_column(String(255))           # es. "DCP INTEROP 2K — Featurette IT"
    file_naming: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Natura: digital o physical (mutually exclusive)
    nature: Mapped[DeliverableNature] = mapped_column(
        SAEnum(DeliverableNature), default=DeliverableNature.digital, index=True
    )
    # Specifiche tecniche
    delivery_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_templates.id"), nullable=True
    )
    spec_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Produzione
    primary_resource_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resources.id"), nullable=True, index=True
    )
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Output / asset bridge (FK separate per chiarezza; popolato uno solo)
    digital_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("assets.id"), nullable=True
    )
    physical_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("physical_assets.id"), nullable=True
    )
    asset_locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # QC AI
    qc_report_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    qc_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    qc_run_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # Stato e date
    status: Mapped[DeliverableStatus] = mapped_column(
        SAEnum(DeliverableStatus), default=DeliverableStatus.planned, index=True
    )
    target_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    delivered_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    accepted_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)


# ── AI ASSISTANT (storico conversazioni) ─────────────────────

class AIConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Contesto opzionale
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True)
    quote_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # v3.5.0 — stato del loop tool_use serializzato (lista messages canonica
    # formato Anthropic: blocks misti text/tool_use/tool_result). Persistito
    # SOLO quando il loop si è interrotto in attesa che l'utente applichi una
    # mutation; ripreso al successivo /apply per continuare il ragionamento.
    tool_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    messages: Mapped[List["AIMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id"))
    role: Mapped[str] = mapped_column(String(20))   # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    conversation: Mapped["AIConversation"] = relationship(back_populates="messages")


# ── AI SETTINGS PER-UTENTE ───────────────────────────────────
#
# Ogni utente può configurare le proprie credenziali per più provider
# (Claude, OpenAI, Gemini, Perplexity, Ollama). La api_key è cifrata
# (Fernet, chiave AI_KEY_ENCRYPTION_KEY in .env). Il provider attivo
# è scelto via User.active_ai_provider.

class UserAISettings(Base):
    __tablename__ = "user_ai_settings"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(32))   # claude|openai|gemini|perplexity|ollama
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Ollama
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                 onupdate=datetime.utcnow)
    user: Mapped["User"] = relationship(back_populates="ai_settings")


# ── AI ACTION (pattern AI propone, utente dispone) ───────────
#
# Ogni azione che l'AI suggerisce (creare cliente, voce listino, riga quote, ecc.)
# viene salvata qui in stato "proposed". L'utente conferma → "applied" o
# rifiuta → "rejected". Niente esecuzione senza conferma esplicita.

class AIAction(Base):
    __tablename__ = "ai_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_conversations.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action_type: Mapped[str] = mapped_column(String(64))
    # propose_price_item | propose_client | propose_quote_line |
    # propose_project_metadata | web_search
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serializzato
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    # proposed | applied | rejected | failed
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # v3.5.0 — id del tool_use Anthropic/OpenAI/Gemini che ha generato questa
    # azione, necessario per costruire il tool_result al momento dell'Apply
    # e riprendere correttamente il loop tool_use. NULL per le azioni create
    # via il vecchio path markdown ```action``` (Ollama/Perplexity legacy).
    tool_use_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


# ── AI USAGE LOG (v3.5.0-alpha.66.16.4 — sprint R10) ─────────
#
# Una riga per ogni call API a un provider AI (Claude/OpenAI/Gemini/...).
# Sostituisce il logger.info ad-hoc α.66.14.7 con audit persistente per:
# - Costo per user/tenant/periodo (billing AI interno + reportistica)
# - Hit ratio prompt cache reale
# - Rate limiting per-user (futuro: cap token/giorno)
# - Debug latenza/errori
#
# Una conversazione N-turn produce N righe (un turno = una request HTTP
# al provider). NULL su user_id se chiamata system (es. enrich_client).

class AIUsageLog(Base):
    __tablename__ = "ai_usage_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_conversations.id"), nullable=True, index=True
    )
    # Provider e modello effettivi al momento della call (non per-utente:
    # un user può cambiare provider e voglio sapere chi ha pagato cosa).
    provider: Mapped[str] = mapped_column(String(32))  # claude | openai | ollama | gemini | perplexity
    model: Mapped[str] = mapped_column(String(64))
    # Token reali da `resp.usage` (Anthropic/OpenAI/Gemini hanno tutti questo).
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Specifici Anthropic prompt caching (α.66.14.7). 0 se provider non supporta.
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_create_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Costo USD calcolato lato app via tabella prezzi
    # (`app.services.ai_provider.compute_cost_usd`). Float, non Decimal:
    # microcent precision OK per analytics; Decimal solo per fatturazione.
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Tipo call: "chat_with_tools" | "complete" | "chat" | "extract_json_with_web_search"
    call_kind: Mapped[str] = mapped_column(String(32), default="chat_with_tools")
    # Errore o stop_reason (es. "end_turn", "tool_use", "max_tokens", "error:...")
    stop_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ── NOTIFICATIONS (v3.4.27) ──────────────────────────────────
#
# Sistema generico di notifiche utente. Ogni evento "interessante" del
# sistema (richiesta ferie pending, conflitto booking, deadline progetto, ecc.)
# emette una Notification per ciascun destinatario. Il client UI le mostra
# con un badge counter sulla campanella in topbar e un drawer laterale.
#
# Pattern: una row per destinatario (multi-recipient = N rows). Più semplice
# per unread_count e mark_read. Il payload JSON contiene riferimenti
# strutturati all'entità (es. {"unavailability_id": 42}).

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    actor: Mapped[Optional["User"]] = relationship(foreign_keys=[actor_user_id])


# ── SCHEDA TECNICA PROGETTO (v3.4.31) ────────────────────────
#
# Scheda tecnica/workflow sheet di un progetto: catena di lavorazione
# (camere, audio, look, storage, dailies, crew, process). Schema flessibile
# JSON per gestire varianti tra case di post diverse senza rigidare lo schema.
# 1:1 con Project. Pubblicabile come link readonly con token UUID + scadenza.
# Distinguere da DeliveryTemplate: questa è la *catena di produzione*, l'altro
# è la *spec di consegna* (Netflix/A24/ecc.).

class ProjectTechSheet(Base):
    __tablename__ = "project_tech_sheets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), unique=True, index=True)
    delivery_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_templates.id"), nullable=True)

    # Stato e versionamento
    version: Mapped[str] = mapped_column(String(50), default="0.1")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|preview|approved
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Pubblicazione readonly via link
    public_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)
    is_public_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Dati strutturati (vedi tech_sheet_schema docstring per layout)
    # general / cameras / audio / looks / storage / dailies / folder_struct / contacts / process / notes
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped["Project"] = relationship()
    delivery_template: Mapped[Optional["DeliveryTemplate"]] = relationship()


# ── SPESE AZIENDALI / POZZO COSTI GENERICI (v3.5.0-alpha.87) ──────────
#
# OverheadCost = costi NON fatturabili al cliente che vivono nel quadro
# finanziario del tenant. Riguardano: manutenzione, licenze software, affitti,
# utenze, stipendi non-billable, formazione, marketing, legal/admin, tasse,
# investimenti CAPEX, acquisto beni durevoli. NON include write-off
# (che restano in LossEntry — single source of truth per perdite su
# fatturazione, evita doppia tracciatura).
#
# Sorgenti possibili (popolazione):
#   - manuale (UI form)
#   - auto da SupplierInvoice senza project/job
#   - auto da Booking kind=internal_maintenance/research/training
#   - auto da PhysicalAsset.unit_cost > tenant.capex_threshold_eur
# In reportistica P&L: aggregato per categoria + periodo + reparto.
# Cashflow: outflow non-job (separato da supplier outflow per job).
#
# is_capex=True attiva tracking ammortamento (useful_life_months + linear).
# is_recurring=True attiva schedule mensile/trimestrale/annuale via next_due_date.

class OverheadCostCategory(str, enum.Enum):
    maintenance      = "maintenance"        # manutenzione attrezzature/sale
    software_license = "software_license"   # canoni software
    rent_utilities   = "rent_utilities"     # affitto + bollette
    staff_overhead   = "staff_overhead"     # stipendi non-billable
    capex            = "capex"              # piani investimenti / beni durevoli capitalizzati
    training         = "training"           # corsi/certificazioni staff
    marketing        = "marketing"          # pubblicità/web/eventi
    legal_admin      = "legal_admin"        # commercialista, avvocato, consulenza
    bank_fees        = "bank_fees"          # commissioni bancarie
    tax              = "tax"                # IRES/IRAP/altre tasse (non IVA)
    other            = "other"


class RecurrenceInterval(str, enum.Enum):
    monthly   = "monthly"
    quarterly = "quarterly"
    yearly    = "yearly"


class OverheadCost(Base):
    __tablename__ = "overhead_costs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # OH-YYYY-NNNN
    category: Mapped[OverheadCostCategory] = mapped_column(
        SAEnum(OverheadCostCategory), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Importi
    amount_net: Mapped[float] = mapped_column(Float, default=0.0)
    vat_rate: Mapped[float] = mapped_column(Float, default=22.0)
    amount_vat: Mapped[float] = mapped_column(Float, default=0.0)
    amount_total: Mapped[float] = mapped_column(Float, default=0.0)
    cost_date: Mapped[date] = mapped_column(Date, index=True)
    # Ricorrenti (template + scheduling)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    recurrence_interval: Mapped[Optional[RecurrenceInterval]] = mapped_column(
        SAEnum(RecurrenceInterval), nullable=True
    )
    next_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    # parent_recurring_id: punta al template "master" per istanze auto-generate
    parent_recurring_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("overhead_costs.id"), nullable=True
    )
    # CAPEX (ammortamento)
    is_capex: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    useful_life_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amortization_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'linear' | 'accelerated'
    asset_acquisition_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Link contestuali (tutti opzionali, popolati al feed automatico)
    department_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("departments.id"), nullable=True, index=True
    )
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True, index=True
    )
    supplier_invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("supplier_invoices.id"), nullable=True, index=True
    )
    booking_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bookings.id"), nullable=True, index=True
    )
    physical_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("physical_assets.id"), nullable=True, index=True
    )
    source_project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    # Audit
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    deleted_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Relationships
    department: Mapped[Optional["Department"]] = relationship(foreign_keys=[department_id])
    supplier: Mapped[Optional["Supplier"]] = relationship(foreign_keys=[supplier_id])
    supplier_invoice: Mapped[Optional["SupplierInvoice"]] = relationship(foreign_keys=[supplier_invoice_id])


# ── ANOMALY WORKFLOW (v3.5.0-alpha.89, sprint S4) ──────────────────
#
# Stateful workflow per anomalie fatturazione. Pre-α.89 le anomalie erano
# calcolate stateless (vedi /finance/api/anomalies/*) — riemergevano a ogni
# refresh e non c'era track di quali fossero già gestite. Ora ogni anomalia
# rilevata diventa una AnomalyEntry (open/handled/dismissed) con audit
# trail dell'azione applicata (rimanda commerciale / rivaluta producer /
# write-off perso / costo aziendale).
#
# Detector: scanner idempotente che genera AnomalyEntry da:
# - JCLBilledSlice + done post-billed → extra_after_billed
# - JobCostLine quantity_actual > quantity_quoted → sforamento_monte_ore
# - JobCostLine is_extra=True senza quote_line_id → extra (over-budget)
# - Invoice due_date < today + status != paid → mancato_recupero
# - Quote vs Job consuntivo > threshold → quote_discrepancy
#
# `dedup_key` (anomaly_type + source_kind + source_id) garantisce
# idempotenza: re-detect non duplica righe esistenti, riapre solo se
# precedentemente dismissed.

class AnomalyType(str, enum.Enum):
    """5 tipi di anomalie fatturazione tracciate (tassonomia ticket Matteo
    12 mag 2026)."""
    extra_after_billed = "extra_after_billed"        # done emerso dopo slice fatturata
    sforamento_monte_ore = "sforamento_monte_ore"    # quantity_actual > quoted
    quote_discrepancy = "quote_discrepancy"          # quote ufficiale ≠ consuntivo Job
    mancato_recupero = "mancato_recupero"            # fattura scaduta, status != paid
    over_budget = "over_budget"                      # extra puro (is_extra=True, no quote_line)


class AnomalyStatus(str, enum.Enum):
    open = "open"            # rilevata, da gestire
    handled = "handled"      # azione applicata
    dismissed = "dismissed"  # ignorata (falso positivo o gestita altrove)


class AnomalyAction(str, enum.Enum):
    """Azione applicata per chiudere l'anomalia (tracking audit)."""
    rimanda_commerciale = "rimanda_commerciale"   # ritorna al commerciale per ridiscutere col cliente
    rivaluta_producer = "rivaluta_producer"        # producer rivaluta budget/scope
    write_off_loss = "write_off_loss"              # → LossEntry (perso, non recuperato)
    overhead_cost = "overhead_cost"                # → OverheadCost (spesa aziendale ricorrente/strutturale)


class AnomalySourceKind(str, enum.Enum):
    """Tipo dell'entità sorgente. Polymorphic: source_id punta al record di
    questo tipo. Lookup viene fatto lato detector/action handler."""
    jcl = "jcl"                          # JobCostLine
    job = "job"                          # Job (per quote_discrepancy)
    invoice = "invoice"                  # Invoice (per mancato_recupero)
    supplier_invoice = "supplier_invoice"  # SupplierInvoice (per fatture passive scadute)
    billed_slice = "billed_slice"        # JCLBilledSlice (per extra_after_billed)


class AnomalyEntry(Base):
    """Singola anomalia rilevata sul workflow fatturazione. Stateful:
    open → handled (con action+target) | dismissed.

    Idempotenza detect: `dedup_key` univoca per (tenant, type, source).
    Re-scan non duplica; riapre solo se l'anomalia era dismissed e il
    dato sottostante è cambiato (es. nuovo over-budget dopo aggiornamento)."""
    __tablename__ = "anomaly_entries"
    # v3.5.0-alpha.91 audit fix P0: la UNIQUE su (tenant_id, dedup_key)
    # era documentata in commento ma non costruita lato DB → due detect
    # paralleli passavano il check db.query().first() e creavano duplicati.
    # Ora la garanzia di idempotenza è enforced dal DB.
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key", name="uq_anomaly_tenant_dedup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)

    anomaly_type: Mapped[AnomalyType] = mapped_column(SAEnum(AnomalyType), index=True)
    source_kind: Mapped[AnomalySourceKind] = mapped_column(SAEnum(AnomalySourceKind), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    # Idempotency key: "{type}:{source_kind}:{source_id}". UNIQUE per tenant
    # (enforced via __table_args__ UniqueConstraint).
    dedup_key: Mapped[str] = mapped_column(String(120), index=True)

    # Contesto denormalizzato per query veloci (no join). Aggiornato a ogni detect.
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)

    amount: Mapped[float] = mapped_column(Float, default=0.0)  # valore monetario in gioco
    description: Mapped[str] = mapped_column(String(500))
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Stato + azione
    status: Mapped[AnomalyStatus] = mapped_column(SAEnum(AnomalyStatus), default=AnomalyStatus.open, index=True)
    handled_action: Mapped[Optional[AnomalyAction]] = mapped_column(SAEnum(AnomalyAction), nullable=True)
    handled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    handled_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Target dell'azione: LossEntry.id per write_off_loss, OverheadCost.id per overhead_cost,
    # null per rimanda_commerciale / rivaluta_producer (sono solo cambio stato workflow).
    handled_target_kind: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    handled_target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])
    job: Mapped[Optional["Job"]] = relationship(foreign_keys=[job_id])
    client: Mapped[Optional["Client"]] = relationship(foreign_keys=[client_id])


# ── v3.5.0-alpha.112 — Regole di nomenclatura documenti ─────────────────
# Pannello in /settings consente di definire format dinamici per codici/numeri
# emessi (Quote, BillingBatch, Invoice, Job, ClosingInvoice, ecc.). Le regole
# sono persistite per-tenant e per-doc_type. Il numbering service le legge a
# runtime; se mancanti applica il default storico (back-compat retroattiva).
# Storico NON viene rinumerato.
#
# Variabili supportate nel format_pattern:
#   {YYYY}  anno corrente (4 cifre)
#   {YY}    anno corrente (2 cifre)
#   {MM}    mese (zero-padded)
#   {DD}    giorno (zero-padded)
#   {NNN}   progressivo zero-padded (default 3 cifre)
#   {NN}    progressivo (2 cifre)
#   {NNNN}  progressivo (4 cifre)
#   {PROJECT_CODE}  codice progetto del documento (se applicabile)
#   {CLIENT_CODE}   codice cliente (se applicabile)
class NumberingConfig(Base):
    __tablename__ = "numbering_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "doc_type", name="uq_numbering_tenant_doctype"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    # Identificatore canonico del tipo doc — uno tra:
    #   quote, billing_batch, invoice, invoice_closing, invoice_credit_note,
    #   job, cost_report_export, supplier_invoice.
    doc_type: Mapped[str] = mapped_column(String(40), index=True)
    format_pattern: Mapped[str] = mapped_column(String(200))
    reset_yearly: Mapped[bool] = mapped_column(Boolean, default=True)
    # Stato sequenza
    current_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_seq: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
