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
    admin = "admin"; manager = "manager"; staff = "staff"; viewer = "viewer"

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

class InvoiceStatus(str, enum.Enum):
    draft = "draft"; sent = "sent"; paid = "paid"
    overdue = "overdue"; cancelled = "cancelled"


# ── UTENTI ───────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.staff)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Provider AI attivo per questo utente (claude|openai|gemini|perplexity|ollama|None=disabilitato)
    active_ai_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    resources: Mapped[List["Resource"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    timesheets: Mapped[List["Timesheet"]] = relationship(back_populates="user")
    assets: Mapped[List["Asset"]] = relationship(back_populates="uploaded_by_user")
    ai_settings: Mapped[List["UserAISettings"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


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
    
    # Dati fiscali
    vat_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tax_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sdi_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pec: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Sede
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
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


# ── PROGETTO (NUOVA ENTITÀ) ──────────────────────────────────

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
    
    client: Mapped["Client"] = relationship(back_populates="projects")
    quotes: Mapped[List["Quote"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[List["Job"]] = relationship(back_populates="project")


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
    # Contatti (utili per freelance ma validi anche per sale/attrezzature)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    internal_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
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


class UnavailabilityKind(str, enum.Enum):
    vacation = "vacation"     # ferie
    sick = "sick"             # malattia
    holiday = "holiday"        # festività (auto-generata da policy)
    other = "other"


class ResourceUnavailability(Base):
    __tablename__ = "resource_unavailabilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[UnavailabilityKind] = mapped_column(SAEnum(UnavailabilityKind), default=UnavailabilityKind.vacation)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── QUOTAZIONE (collegata a Progetto, non più direttamente a Cliente) ──

class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
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
    vat_rate: Mapped[float] = mapped_column(Float, default=22.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # subtotal_gross = somma qty*unit_price*(1+allowance) di tutte le voci, prima di
    # qualsiasi sconto. Mostrato in PDF/UI per visibilità del valore pieno al cliente.
    subtotal_gross: Mapped[float] = mapped_column(Float, default=0.0)
    # subtotal = post-sconti riga + sconti categoria, pre-sconto pacchetto.
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    # total_after_discount = post-sconto pacchetto, base imponibile per IVA.
    total_after_discount: Mapped[float] = mapped_column(Float, default=0.0)
    total_with_vat: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Tracking AI: se generata da capitolato
    generated_from_deliverables: Mapped[bool] = mapped_column(Boolean, default=False)
    source_document_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    project: Mapped["Project"] = relationship(back_populates="quotes")
    client: Mapped["Client"] = relationship(back_populates="quotes")
    lines: Mapped[List["QuoteLine"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    job: Mapped[Optional["Job"]] = relationship(back_populates="quote", uselist=False)


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
    quote: Mapped["Quote"] = relationship(back_populates="lines")
    price_item: Mapped[Optional["PriceItem"]] = relationship()


# ── JOB (collegato a Progetto) ───────────────────────────────

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
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
    # Lavorazione "extra": aggiunta dopo l'approvazione della quote (es. cliente
    # chiede un upres in più). quote_line_id è NULL per gli extra puri.
    # Una riga ereditata dalla quote può comunque generare extra senza is_extra=True
    # se quantity_actual > quantity_quoted (sforamento monte ore).
    is_extra: Mapped[bool] = mapped_column(Boolean, default=False)
    work_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job: Mapped["Job"] = relationship(back_populates="cost_lines")


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
    # Envelope min/max degli assignments. Auto-calcolato dal router al save.
    start_datetime: Mapped[datetime] = mapped_column(DateTime)
    end_datetime: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[BookingStatus] = mapped_column(SAEnum(BookingStatus), default=BookingStatus.tentative)
    kind: Mapped[BookingKind] = mapped_column(SAEnum(BookingKind), default=BookingKind.project)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    client: Mapped["Client"] = relationship(back_populates="invoices")
    job: Mapped[Optional["Job"]] = relationship(back_populates="invoices")
    lines: Mapped[List["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit_price: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)
    invoice: Mapped["Invoice"] = relationship(back_populates="lines")


# ── DAM ──────────────────────────────────────────────────────

class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class AssetTag(Base):
    __tablename__ = "asset_tags"
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    job: Mapped[Optional["Job"]] = relationship(back_populates="assets")
    uploaded_by_user: Mapped["User"] = relationship(back_populates="assets")
    tags: Mapped[List["Tag"]] = relationship(secondary="asset_tags")
    versions: Mapped[List["Asset"]] = relationship(
        foreign_keys=[parent_asset_id], back_populates="parent")
    parent: Mapped[Optional["Asset"]] = relationship(
        foreign_keys=[parent_asset_id], back_populates="versions", remote_side=[id])


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
