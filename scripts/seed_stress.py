"""
MediaFlow — seed_stress.py
Stress-test seed: large-scale realistic dataset for full system simulation.

Targets:
- 100 clients with filmographies (>=3 works each)
- 500 resources (150 internal users with login)
- 1000 projects across statuses (prospect/quoting/active/completed/archived)
- Quotes in all states (draft/sent/approved/rejected/expired/superseded)
- Invoices with payments (paid/partial/unpaid/overdue/cancelled)
- 3 years (2024-2026) of TimePunch for 150 internal users
- 3 years of ResourceUnavailability (vacation/sick/holiday)
- 3 years of Booking + BookingAssignment across projects
- 3000 PhysicalAsset, 5000 Asset (digital), 1000 AssetMovement, ~200 IngestBatch
- Suppliers + SupplierInvoice (cost-side)
- BillingBatch + JCLBilledSlice for closed periods
- Notifications + AIConversations sample

Usage:
    .venv/Scripts/python.exe scripts/seed_stress.py [--reset]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import shutil
import string
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, create_tables
from app.models.models import (
    Tenant, Department, User, UserRole, Role,
    Client, ClientWork,
    Project, ProjectStatus, ProjectMilestone,
    Resource, ResourceType, ResourceCostType, ResourcePreset,
    ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
    WorkingHoursPolicy,
    PriceCategory, PriceItem, PriceLevel,
    Quote, QuoteLine, QuoteStatus,
    Job, JobStatus, JobResourceAssignment, JobCostLine, JCLBillingStatus,
    Booking, BookingAssignment, BookingStatus, BookingKind, BookingState,
    BookingPriority, BookingExecutionStatus,
    TimePunch, PunchKind, Timesheet, Expense,
    Invoice, InvoiceLine, InvoicePayment, InvoiceStatus,
    BillingBatch, BillingBatchLine, BillingBatchStatus, LossEntry, LossReason,
    JCLBilledSlice,
    Supplier, SupplierInvoice, SupplierInvoicePayment, SupplierInvoiceStatus,
    Asset, AssetType, Tag,
    PhysicalAsset, PhysicalAssetKind, AssetOwnerType,
    IngestBatch, AssetMovement, AssetMovementType, AssetMembership,
    JobDeliverable, DeliverableNature, DeliverableStatus, DeliveryTemplate,
    Notification,
    AIConversation, AIMessage, AIAction,
)
from app.services.auth import hash_password
from app.services.rbac import ensure_built_in_roles

# Deterministic stress test
RANDOM_SEED = 4242
random.seed(RANDOM_SEED)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger("seed_stress")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
engine.echo = False


# ─────────────────────────────────────────────────────────────
# Pools of realistic Italian + international data
# ─────────────────────────────────────────────────────────────

FIRST_NAMES_M = [
    "Marco", "Luca", "Andrea", "Matteo", "Francesco", "Alessandro", "Davide",
    "Stefano", "Giovanni", "Paolo", "Roberto", "Federico", "Riccardo", "Lorenzo",
    "Daniele", "Simone", "Antonio", "Gabriele", "Tommaso", "Mattia", "Giulio",
    "Pietro", "Niccolò", "Edoardo", "Filippo", "Alberto", "Enrico", "Massimo",
    "Cristian", "Carlo", "Vittorio", "Giorgio", "Salvatore", "Emanuele",
]
FIRST_NAMES_F = [
    "Giulia", "Sara", "Chiara", "Martina", "Francesca", "Anna", "Laura",
    "Elena", "Federica", "Alessia", "Valentina", "Silvia", "Giorgia", "Eleonora",
    "Camilla", "Beatrice", "Arianna", "Aurora", "Maria", "Sofia", "Greta",
    "Vittoria", "Lucia", "Emma", "Roberta", "Cristina", "Daniela", "Marta",
    "Paola", "Veronica", "Caterina", "Carlotta", "Ilaria", "Stella",
]
LAST_NAMES = [
    "Rossi", "Bianchi", "Romano", "Ferrari", "Esposito", "Russo", "Bruno", "Gallo",
    "Conti", "De Luca", "Costa", "Giordano", "Mancini", "Rizzo", "Lombardi", "Moretti",
    "Barbieri", "Fontana", "Santoro", "Mariani", "Marini", "Greco", "Bruno", "Gatti",
    "Vitale", "Coppola", "De Angelis", "Pellegrini", "Caruso", "Ferrara", "Galli",
    "Martini", "Leone", "Longo", "Gentile", "Martinelli", "Vitali", "Lombardo",
    "Serra", "Sala", "Marchetti", "Ricci", "Marino", "Greco", "Bruno", "Riva",
    "Pisani", "Romano", "Caputo", "Sanna", "Monti", "Palumbo", "Farina",
]
CITIES_IT = [
    ("Milano", "MI", "20100", "Lombardia"),
    ("Roma", "RM", "00100", "Lazio"),
    ("Torino", "TO", "10100", "Piemonte"),
    ("Napoli", "NA", "80100", "Campania"),
    ("Firenze", "FI", "50100", "Toscana"),
    ("Bologna", "BO", "40100", "Emilia-Romagna"),
    ("Genova", "GE", "16100", "Liguria"),
    ("Padova", "PD", "35100", "Veneto"),
    ("Verona", "VR", "37100", "Veneto"),
    ("Palermo", "PA", "90100", "Sicilia"),
    ("Cinecittà (RM)", "RM", "00173", "Lazio"),
    ("Trieste", "TS", "34100", "Friuli-Venezia Giulia"),
]
CITIES_INT = [
    ("London", "UK", "Regno Unito"),
    ("Paris", "FR", "Francia"),
    ("New York", "NY", "USA"),
    ("Los Angeles", "CA", "USA"),
    ("Berlin", "DE", "Germania"),
    ("Madrid", "ES", "Spagna"),
    ("Amsterdam", "NL", "Olanda"),
    ("Zurich", "CH", "Svizzera"),
    ("Lisbona", "PT", "Portogallo"),
]

COMPANY_BASES = [
    "Cinema", "Pictures", "Film", "Studios", "Productions", "Media", "Lab", "House",
    "Group", "Vision", "Tales", "Stories", "Lights", "Frames", "Reel", "Echo", "Wave",
    "Horizon", "Atlas", "Polaris", "Lumen", "Aurora", "Arcadia", "Olimpo",
]
COMPANY_SUFFIXES = ["S.r.l.", "S.p.A.", "S.r.l.s.", "S.n.c.", "S.a.s."]
COMPANY_FOREIGN_SUFFIXES = ["Ltd", "LLC", "GmbH", "BV", "Inc.", "Pictures"]

INDUSTRIES = [
    "Cinema theatrical", "Produzione cinematografica", "Distribuzione",
    "Broadcaster TV", "Streaming OTT", "Spot pubblicitario", "Documentaristica",
    "Post-produzione", "Localizzazione", "Music video", "Branded content",
]

# Film title generator (Italian + international flavor)
TITLE_WORDS_IT = [
    "Mare", "Cielo", "Luce", "Sogno", "Notte", "Strada", "Casa", "Vento",
    "Specchio", "Cuore", "Tempo", "Anima", "Volo", "Ombra", "Eco", "Soglia",
    "Voce", "Pioggia", "Sale", "Pane", "Polvere", "Sabbia", "Fuoco", "Acqua",
]
TITLE_ADJ_IT = [
    "Nostro", "Distante", "Infinito", "Silenzioso", "Profondo", "Spezzato",
    "Perduto", "Ultimo", "Primo", "Sospeso", "Aperto", "Lontano", "Solitario",
    "Caldo", "Freddo", "Lungo", "Breve", "Notturno",
]
TITLE_WORDS_EN = [
    "Light", "Echo", "Storm", "River", "Mountain", "Garden", "Bridge", "Path",
    "Shadow", "Mirror", "Tide", "Horizon", "Silence", "Memory", "Time", "Voice",
]

DIRECTORS_POOL = [
    "Paolo Sorrentino", "Matteo Garrone", "Gabriele Salvatores", "Luca Guadagnino",
    "Saverio Costanzo", "Alice Rohrwacher", "Marco Bellocchio", "Pietro Marcello",
    "Stefano Sollima", "Edoardo De Angelis", "Susanna Nicchiarelli",
    "Daniele Luchetti", "Daniele Vicari", "Roberto Andò", "Gianni Amelio",
    "Christopher Nolan", "Greta Gerwig", "Sofia Coppola", "Sean Baker",
    "Yorgos Lanthimos", "Park Chan-wook", "Pedro Almodóvar", "Wes Anderson",
]
PRODUCERS_POOL = [
    "Domenico Procacci", "Riccardo Tozzi", "Andrea Occhipinti", "Marco Belardi",
    "Nicola Giuliano", "Marco Cohen", "Lorenzo Mieli", "Antonio Pezzuto",
    "Megan Ellison", "Christine Vachon", "Jeremy Thomas", "Saïd Ben Saïd",
]
DOP_POOL = [
    "Luca Bigazzi", "Daria D'Antonio", "Daniele Ciprì", "Vladan Radovic",
    "Matteo Cocco", "Daniele Massaccesi", "Stefano Falivene", "Greig Fraser",
    "Hoyte van Hoytema", "Mihai Mălaimare Jr.", "Linus Sandgren",
]

FUNDING_REGIONI = ["Lazio", "Lombardia", "Toscana", "Piemonte", "Veneto", "Sicilia"]
FUNDING_KINDS = ["MiC contributo selettivo", "MiC tax credit", "Eurimages", "Creative Europe MEDIA"]

# ────────────────────────────────────────────────────────────
# Resource roles + cost rates
# ────────────────────────────────────────────────────────────

ROLES_BY_DEPT = {
    "DI-VIDEO": [
        ("Senior Colorist", 800, 110, "employee"),
        ("Colorist", 600, 80, "employee"),
        ("Online Editor", 550, 75, "employee"),
        ("Conform Editor", 500, 65, "employee"),
        ("Mastering Engineer", 600, 80, "employee"),
        ("QC Engineer", 450, 60, "employee"),
        ("Dailies Operator", 400, 55, "employee"),
        ("DI Operator", 450, 60, "employee"),
        ("Colorist Freelance", 700, 90, "freelance"),
    ],
    "VFX": [
        ("VFX Supervisor", 900, 120, "employee"),
        ("Compositor Senior", 700, 95, "employee"),
        ("Compositor", 500, 70, "employee"),
        ("3D Artist", 550, 75, "employee"),
        ("Roto/Paint", 400, 55, "employee"),
        ("Matte Painter", 600, 80, "freelance"),
        ("FX TD", 750, 100, "freelance"),
        ("Render Wrangler", 400, 55, "employee"),
    ],
    "AUDIO": [
        ("Re-recording Mixer", 800, 110, "employee"),
        ("Sound Designer", 600, 80, "employee"),
        ("Dialogue Editor", 500, 65, "employee"),
        ("Foley Editor", 550, 70, "employee"),
        ("Foley Artist", 500, 65, "freelance"),
        ("ADR Engineer", 550, 70, "employee"),
        ("Music Editor", 500, 65, "freelance"),
    ],
    "COMMERCIAL": [
        ("Producer Senior", 700, 95, "employee"),
        ("Producer", 500, 70, "employee"),
        ("Production Coordinator", 400, 55, "employee"),
        ("Account Manager", 450, 60, "employee"),
        ("Production Assistant", 280, 38, "employee"),
        ("Office Manager", 320, 42, "employee"),
        ("Accountant", 380, 50, "employee"),
    ],
}

STUDIO_DEFS = [
    ("DI-VIDEO", "Sala Color HDR Dolby Vision", 1800),
    ("DI-VIDEO", "Sala Color SDR", 900),
    ("DI-VIDEO", "Sala Mastering DCP/IMF", 1100),
    ("DI-VIDEO", "Suite Online", 800),
    ("DI-VIDEO", "Suite QC HDR", 600),
    ("AUDIO", "Sala Mix Dolby Atmos 9.1.4", 2500),
    ("AUDIO", "Sala Mix Surround 7.1", 1500),
    ("AUDIO", "Sala Mix Surround 5.1", 1100),
    ("AUDIO", "Cabina Doppiaggio Premium", 700),
    ("AUDIO", "Cabina ADR", 550),
    ("AUDIO", "Sala Foley", 800),
    ("VFX", "Render Farm 512 core", 900),
    ("VFX", "VFX Suite Nuke", 500),
]
EQUIPMENT_DEFS = [
    ("DI-VIDEO", "Workstation Resolve HDR", 250, "Apple Mac Studio M2 Ultra"),
    ("DI-VIDEO", "Monitor Dolby Vision 4K", 180, "Sony BVM-HX310"),
    ("DI-VIDEO", "Deck SR Master", 120, "Sony SRW-5500"),
    ("VFX", "Workstation Nuke X", 220, "HP Z8 G5"),
    ("VFX", "GPU Server NVIDIA A6000", 300, "Supermicro 4U"),
    ("AUDIO", "Pro Tools HDX Rig", 200, "Avid HDX3 + Sync HD"),
    ("AUDIO", "Microfono Schoeps", 60, "Schoeps CMC6"),
    ("AUDIO", "Console S6 M40", 350, "Avid S6 M40 32-fader"),
]
SOFTWARE_DEFS = [
    ("DI-VIDEO", "DaVinci Resolve Studio seat", 50),
    ("VFX", "Nuke X seat", 110),
    ("VFX", "Houdini Indie", 80),
    ("AUDIO", "Pro Tools Ultimate", 70),
    ("AUDIO", "Wwise Audio Engine", 50),
    ("AUDIO", "Dolby Atmos Renderer", 90),
]
VEHICLE_DEFS = [
    ("COMMERCIAL", "Furgone trasporti A", 100, "Fiat Ducato 35"),
    ("COMMERCIAL", "Furgone trasporti B", 100, "Mercedes Sprinter"),
    ("COMMERCIAL", "Auto produzione", 80, "Fiat 500X"),
]

DEFAULT_DEPARTMENTS = [
    ("DI-VIDEO", "DI / Video", "#6272f5", 10),
    ("VFX", "VFX / Finishing", "#a855f7", 20),
    ("AUDIO", "Audio", "#2ec4b6", 30),
    ("COMMERCIAL", "Commercial / Produzione", "#f59e0b", 40),
]


def _rand_first():
    return random.choice(FIRST_NAMES_M + FIRST_NAMES_F)


def _rand_full_name():
    return f"{_rand_first()} {random.choice(LAST_NAMES)}"


def _rand_email(name: str, domain: str = "mediaflow.it") -> str:
    parts = name.lower().replace("'", "").split()
    return f"{parts[0]}.{parts[-1]}@{domain}"


def _rand_phone() -> str:
    return f"+39 {random.randint(300, 399)} {random.randint(1000000, 9999999)}"


def _rand_vat_it() -> str:
    return "IT" + "".join(random.choices(string.digits, k=11))


def _rand_iban_it() -> str:
    return "IT" + "".join(random.choices(string.digits, k=2)) + "A" + \
        "".join(random.choices(string.digits, k=5)) + "".join(random.choices(string.digits + string.ascii_uppercase, k=15))


def _rand_company_name(is_foreign: bool = False) -> str:
    base = random.choice(COMPANY_BASES)
    second = random.choice([
        random.choice(LAST_NAMES),
        random.choice(COMPANY_BASES),
        random.choice(TITLE_WORDS_EN),
    ])
    suffix = random.choice(COMPANY_FOREIGN_SUFFIXES if is_foreign else COMPANY_SUFFIXES)
    return f"{base} {second} {suffix}"


def _rand_film_title() -> str:
    kind = random.choice(["it_noun", "it_adj_noun", "en", "en_double"])
    if kind == "it_noun":
        return random.choice(TITLE_WORDS_IT)
    if kind == "it_adj_noun":
        return f"{random.choice(TITLE_WORDS_IT)} {random.choice(TITLE_ADJ_IT).lower()}"
    if kind == "en":
        return random.choice(TITLE_WORDS_EN)
    return f"{random.choice(TITLE_WORDS_EN)} of {random.choice(TITLE_WORDS_EN)}"


COUNTERS: dict[str, int] = {}
ISSUES: list[str] = []


def cnt(key: str, n: int = 1) -> None:
    COUNTERS[key] = COUNTERS.get(key, 0) + n


def issue(msg: str) -> None:
    ISSUES.append(msg)
    log.warning(f"ISSUE: {msg}")


def stage_setup(reset: bool) -> None:
    log.info("STAGE 0 — Setup DB")
    db_path = ROOT / "mediaflow.db"
    if db_path.exists() and reset:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = ROOT / "db_snapshots"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"snapshot-pre-stress-{ts}.db"
        shutil.copy(db_path, backup)
        log.info(f"  backup -> {backup.name}")
        from app.models.models import Base
        Base.metadata.drop_all(bind=engine)
        log.info("  schema dropped")
    create_tables()
    from app.main import _auto_migrate_columns
    _auto_migrate_columns()
    log.info("  schema created + auto_migrate OK")


def stage_tenant_roles(db: Session) -> None:
    log.info("STAGE 1 — Tenant + ruoli + departments")
    tenant = db.query(Tenant).filter(Tenant.id == 1).first()
    if tenant is None:
        tenant = Tenant(
            id=1, name="MediaFlow Stress Test",
            slug="default",
            legal_name="MediaFlow Stress S.r.l.",
            vat_number="IT-12345678901",
            tax_code="12345678901",
            address="Via Cinecittà 1, 00173 Roma",
            email="info@mediaflow.it",
            phone="+39 06 5555 5555",
            website="https://mediaflow.it",
            default_currency="EUR",
            default_vat_rate=22.0,
            default_language="it",
            iban="IT60X0542811101000000123456",
            sdi_code="0000000",
            rea_number="RM-1234567",
            fiscal_capital="100.000,00 i.v.",
            fiscal_regime="RF01",
            payment_terms_default=30,
            tagline="Hub di coordinamento per la post-produzione",
            brand_color="#6272f5",
            show_powered_by=True,
        )
        db.add(tenant)
        db.commit()
        cnt("tenant", 1)
    ensure_built_in_roles(db)
    db.commit()

    depts: dict[str, Department] = {}
    for code, name, color, order in DEFAULT_DEPARTMENTS:
        d = db.query(Department).filter(
            Department.tenant_id == 1, Department.code == code
        ).first()
        if not d:
            d = Department(tenant_id=1, code=code, name=name, color=color,
                           sort_order=order, is_active=True,
                           annual_budget=random.choice([500_000, 800_000, 1_200_000]))
            db.add(d)
        depts[code] = d
    db.commit()
    for d in depts.values():
        db.refresh(d)
    cnt("departments", len(depts))

    # Working hours policy (default)
    if not db.query(WorkingHoursPolicy).filter(WorkingHoursPolicy.is_default == True).first():
        whp = WorkingHoursPolicy(
            tenant_id=1, name="Standard 9-18 lun-ven",
            is_default=True,
            morning_start=time(9, 0), morning_end=time(13, 0),
            afternoon_start=time(14, 0), afternoon_end=time(18, 0),
            working_days=31,  # mon-fri
            holidays_country="IT",
            daily_hours_threshold=8.0,
            weekly_hours_threshold=40.0,
            overtime_multiplier=1.25,
            night_multiplier=1.50,
            sunday_multiplier=1.50,
            holiday_multiplier=2.00,
            ccnl_label="CCNL Cinema base (Italia 2026)",
            overtime_brackets=[
                {"from_hour": 0, "multiplier": 1.0},
                {"from_hour": 2, "multiplier": 1.30},
                {"from_hour": 4, "multiplier": 1.60},
            ],
        )
        db.add(whp)
        db.commit()
        cnt("working_hours_policy", 1)


def stage_users_resources(db: Session) -> dict:
    log.info("STAGE 2 — 150 utenti login + 500 risorse")
    depts = {d.code: d for d in db.query(Department).filter(Department.tenant_id == 1).all()}
    admin_role = db.query(Role).filter(Role.code == "admin").first()
    manager_role = db.query(Role).filter(Role.code == "manager").first()
    producer_role = db.query(Role).filter(Role.code == "producer").first()
    accounting_role = db.query(Role).filter(Role.code == "accounting").first()
    operator_role = db.query(Role).filter(Role.code == "operator").first()
    viewer_role = db.query(Role).filter(Role.code == "viewer").first()

    users_csv_rows = []

    # ── Admin principale (richiesto da Matteo) ──
    admin = db.query(User).filter(User.email == "admin@mediaflow.it").first()
    if not admin:
        admin = User(
            email="admin@mediaflow.it",
            full_name="Admin MediaFlow",
            hashed_password=hash_password("admin123"),
            role=UserRole.admin,
            role_id=admin_role.id if admin_role else None,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
    cnt("users", 1)
    users_csv_rows.append({
        "id": admin.id, "email": admin.email, "name": admin.full_name,
        "password": "admin123", "role": "admin", "department": "",
        "is_resource": False, "note": "Account principale Matteo",
    })

    # ── Matteo (proprietario) ──
    matteo = db.query(User).filter(User.email == "matteo@mediaflow.it").first()
    if not matteo:
        matteo = User(
            email="matteo@mediaflow.it",
            full_name="Matteo Lepore",
            hashed_password=hash_password("matteo123"),
            role=UserRole.admin,
            role_id=admin_role.id if admin_role else None,
            is_active=True,
        )
        db.add(matteo)
        db.commit()
        db.refresh(matteo)
    cnt("users", 1)
    users_csv_rows.append({
        "id": matteo.id, "email": matteo.email, "name": matteo.full_name,
        "password": "matteo123", "role": "admin", "department": "",
        "is_resource": False, "note": "Proprietario / manager casa di post",
    })

    # ── 150 utenze interne (= dipendenti loggabili) ──
    # Distribuzione ruoli: 5 manager, 15 producer, 10 accounting, 110 operator, 10 viewer
    role_distribution = (
        [("manager", manager_role, UserRole.manager)] * 5 +
        [("producer", producer_role, UserRole.producer)] * 15 +
        [("accounting", accounting_role, UserRole.staff)] * 10 +
        [("operator", operator_role, UserRole.staff)] * 110 +
        [("viewer", viewer_role, UserRole.viewer)] * 10
    )
    assert len(role_distribution) == 150
    random.shuffle(role_distribution)

    internal_users = []
    for i, (role_code, role_obj, enum_role) in enumerate(role_distribution):
        name = _rand_full_name()
        email_base = name.lower().replace("'", "")
        parts = email_base.split()
        email = f"{parts[0]}.{parts[-1]}{i+1}@mediaflow.it"  # ensure unique
        pwd = f"pwd{i+1:03d}"
        u = User(
            email=email,
            full_name=name,
            hashed_password=hash_password(pwd),
            role=enum_role,
            role_id=role_obj.id if role_obj else None,
            is_active=True,
        )
        db.add(u)
        internal_users.append((u, role_code, pwd))
        if (i+1) % 50 == 0:
            db.commit()
    db.commit()
    for u, _, _ in internal_users:
        db.refresh(u)
    cnt("users", len(internal_users))

    # ── 500 risorse totali. 150 sono linkate agli internal_users (= dipendenti) ──
    # Distribuzione:
    # - 150 person_internal (linked user_id)
    # - 120 person_freelance
    # - 100 studio (sale fisiche, ~13 base × ricicliamo o numeriamo)
    # - 60 equipment
    # - 40 software
    # - 30 vehicle
    # 500 total
    resources_created = []

    # 1) person_internal — 150 (= utenti)
    for idx, (u, role_code, pwd) in enumerate(internal_users):
        dept_code = random.choice(list(ROLES_BY_DEPT.keys()))
        role_role = random.choice(ROLES_BY_DEPT[dept_code])
        role_name, daily, hourly, ctype_str = role_role
        # alcune persone (es. account) restano in COMMERCIAL anche se ruolo diverso
        # ma random.choice è sufficiente per stress.
        cost_type_enum = ResourceCostType.employee if ctype_str == "employee" else ResourceCostType.freelance
        monthly_salary = round(daily * 18, -1) if cost_type_enum == ResourceCostType.employee else None
        freelance_cost = round(hourly * 0.65, 2) if cost_type_enum == ResourceCostType.freelance else None
        r = Resource(
            tenant_id=1, department_id=depts[dept_code].id,
            name=u.full_name,
            type=ResourceType.person_internal,
            role=role_name,
            description=f"{role_name} reparto {dept_code}",
            daily_rate=daily, hourly_rate=hourly,
            cost_type=cost_type_enum,
            monthly_gross_salary=monthly_salary,
            annual_bonus_months=13.0,
            cost_multiplier_oneri=1.30,
            annual_working_hours=1720.0,
            freelance_hourly_cost=freelance_cost,
            email=u.email,
            phone=_rand_phone(),
            internal_phone=str(200 + idx),
            color=random.choice(["#6272f5", "#2ec4b6", "#a855f7", "#f59e0b", "#f43f5e", "#22c55e"]),
            user_id=u.id,
            is_active=True,
        )
        db.add(r)
        resources_created.append(r)
        users_csv_rows.append({
            "id": "", "email": u.email, "name": u.full_name,
            "password": pwd, "role": role_code, "department": dept_code,
            "is_resource": True, "note": f"Dipendente {role_name}",
        })

    db.commit()
    for r in resources_created:
        db.refresh(r)

    # 2) person_freelance — 120 (no user)
    freelance_count = 0
    while freelance_count < 120:
        dept_code = random.choice(list(ROLES_BY_DEPT.keys()))
        role_role = random.choice(ROLES_BY_DEPT[dept_code])
        role_name, daily, hourly, _ = role_role
        name = _rand_full_name()
        r = Resource(
            tenant_id=1, department_id=depts[dept_code].id,
            name=name,
            type=ResourceType.person_freelance,
            role=role_name + " (freelance)",
            description=f"Freelance {role_name}",
            daily_rate=int(daily * 1.05),
            hourly_rate=int(hourly * 1.05),
            cost_type=ResourceCostType.freelance,
            freelance_hourly_cost=round(hourly * 0.85, 2),
            email=_rand_email(name, domain="freelance.it"),
            phone=_rand_phone(),
            color="#a855f7" if random.random() < 0.5 else "#f43f5e",
            is_active=True,
        )
        db.add(r)
        resources_created.append(r)
        freelance_count += 1
    db.commit()

    # 3) studio rooms — 100 (cycle through STUDIO_DEFS, suffix index)
    studio_count = 0
    studio_idx = 0
    while studio_count < 100:
        dept_code, base_label, daily = STUDIO_DEFS[studio_idx % len(STUDIO_DEFS)]
        suffix = (studio_idx // len(STUDIO_DEFS)) + 1
        label = f"{base_label} #{suffix}"
        r = Resource(
            tenant_id=1, department_id=depts[dept_code].id,
            name=label,
            type=ResourceType.studio,
            role="Sala di lavorazione",
            description=f"Sala / Studio del reparto {dept_code}",
            daily_rate=daily,
            hourly_rate=daily // 8,
            cost_type=ResourceCostType.studio,
            studio_hourly_cost=round(daily * 0.4 / 8, 2),
            color="#f59e0b",
            is_active=True,
        )
        db.add(r)
        resources_created.append(r)
        studio_count += 1
        studio_idx += 1
    db.commit()

    # 4) equipment — 60
    for i in range(60):
        dept_code, base_label, daily, brand = EQUIPMENT_DEFS[i % len(EQUIPMENT_DEFS)]
        suffix = (i // len(EQUIPMENT_DEFS)) + 1
        label = f"{base_label} #{suffix}"
        r = Resource(
            tenant_id=1, department_id=depts[dept_code].id,
            name=label,
            type=ResourceType.equipment,
            role=brand,
            description=f"{brand} — uso reparto {dept_code}",
            daily_rate=daily, hourly_rate=daily // 8,
            cost_type=ResourceCostType.external,
            color="#64748b",
            is_active=True,
        )
        db.add(r)
        resources_created.append(r)
    db.commit()

    # 5) software seats — 40
    for i in range(40):
        dept_code, base_label, daily = SOFTWARE_DEFS[i % len(SOFTWARE_DEFS)]
        suffix = (i // len(SOFTWARE_DEFS)) + 1
        label = f"{base_label} #{suffix}"
        r = Resource(
            tenant_id=1, department_id=depts[dept_code].id,
            name=label,
            type=ResourceType.software,
            role="Licenza",
            description=f"Seat licenza software reparto {dept_code}",
            daily_rate=daily, hourly_rate=daily // 8,
            cost_type=ResourceCostType.external,
            color="#0ea5e9",
            is_active=True,
        )
        db.add(r)
        resources_created.append(r)
    db.commit()

    # 6) vehicle — 30
    for i in range(30):
        dept_code, base_label, daily, brand = VEHICLE_DEFS[i % len(VEHICLE_DEFS)]
        suffix = (i // len(VEHICLE_DEFS)) + 1
        label = f"{base_label} #{suffix}"
        r = Resource(
            tenant_id=1, department_id=depts[dept_code].id,
            name=label,
            type=ResourceType.vehicle,
            role=brand,
            description=f"Veicolo {brand}",
            daily_rate=daily, hourly_rate=daily // 8,
            color="#475569",
            is_active=True,
        )
        db.add(r)
        resources_created.append(r)
    db.commit()
    for r in resources_created:
        db.refresh(r)
    cnt("resources", len(resources_created))
    log.info(f"  -> {len(resources_created)} risorse, di cui {len(internal_users)} = utenti")

    return {
        "admin": admin,
        "matteo": matteo,
        "internal_users": [u for u, _, _ in internal_users],
        "resources": resources_created,
        "users_csv_rows": users_csv_rows,
    }


def stage_pricelist(db: Session) -> None:
    log.info("STAGE 3 — Listino base via preset lean")
    from app.services import pricelist_snapshot as _plsnap
    if not db.query(PriceItem).filter(PriceItem.tenant_id == 1).first():
        payload = _plsnap.load_preset_payload("lean_2026q3_v1.json")
        stats = _plsnap.apply_snapshot_payload(
            db, tenant_id=1, payload=payload, mode="merge", auto_backup=False,
        )
        items_count = stats["items_created"] + stats["items_updated"]
        cnt("price_items", items_count)
        log.info(f"  -> {items_count} voci listino caricate")
    else:
        cnt("price_items", db.query(PriceItem).filter(PriceItem.tenant_id == 1).count())
        log.info(f"  -> {COUNTERS['price_items']} voci listino (esistenti)")


def stage_clients(db: Session) -> list[Client]:
    log.info("STAGE 4 — 100 clienti + filmografie (3-12 opere ciascuno)")
    clients_created: list[Client] = []
    # 80 italiani + 20 stranieri
    for i in range(100):
        is_foreign = i >= 80
        name = _rand_company_name(is_foreign=is_foreign)
        if is_foreign:
            city, country_iso, country_name = random.choice(CITIES_INT)
            province = ""
            zip_code = ""
        else:
            city, province, zip_code, region = random.choice(CITIES_IT)
            country_name = "Italia"
        contact_name = _rand_full_name()
        c = Client(
            tenant_id=1,
            name=name,
            legal_form=name.split()[-1],
            contact_name=contact_name,
            contact_role=random.choice(["Producer", "Account", "Production Manager", "CFO", "Head of Production"]),
            contact_email=_rand_email(contact_name, domain=name.lower().replace(" ", "").replace(".", "")[:18] + ".it"),
            contact_phone=_rand_phone(),
            vat_number=_rand_vat_it() if not is_foreign else f"{country_iso}-{random.randint(10000000, 99999999)}",
            tax_code=_rand_vat_it()[2:] if not is_foreign else None,
            sdi_code=random.choice(["0000000", "M5UXCR1", "T04ZHR3", "USAL8PB"]),
            pec=f"pec@{name.lower().replace(' ', '').replace('.', '')[:18]}.it",
            address=f"Via {random.choice(LAST_NAMES)} {random.randint(1, 200)}",
            city=city,
            province=province,
            zip_code=zip_code,
            country=country_name,
            website=f"https://www.{name.lower().replace(' ', '').replace('.', '')[:24]}.com",
            industry=random.choice(INDUSTRIES),
            company_size=random.choice(["1-10", "10-50", "50-200", "200-1000", "1000+"]),
            founded_year=random.randint(1985, 2023),
            recent_productions=None,  # popolato sotto via ClientWork
            notes=f"Cliente {random.choice(['storico', 'nuovo', 'occasionale', 'top'])} — generato da seed_stress",
            ai_enriched=False,
        )
        db.add(c)
        clients_created.append(c)
        if (i+1) % 20 == 0:
            db.commit()
    db.commit()
    for c in clients_created:
        db.refresh(c)
    cnt("clients", len(clients_created))

    # Filmografie: 3-12 opere per cliente
    works_created = 0
    for c in clients_created:
        n_works = random.randint(3, 12)
        for _ in range(n_works):
            year = random.randint(2015, 2026)
            kind = random.choice(["film", "serie", "documentario", "spot", "cortometraggio"])
            title = _rand_film_title()
            director = random.choice(DIRECTORS_POOL)
            cast_crew = {
                "director": director,
                "dop": random.choice(DOP_POOL),
                "executive_producer": random.choice(PRODUCERS_POOL),
                "editor": _rand_full_name(),
                "sound_design": _rand_full_name(),
                "music": _rand_full_name(),
                "screenplay": _rand_full_name() + ", " + _rand_full_name(),
                "lead_cast": [_rand_full_name() for _ in range(random.randint(2, 5))],
            }
            funding = {
                "mibac": random.random() < 0.3,
                "regional": random.choice(FUNDING_REGIONI) if random.random() < 0.4 else "",
                "eu": random.random() < 0.15,
                "notes": random.choice(FUNDING_KINDS) if random.random() < 0.4 else "",
            }
            awards = []
            if random.random() < 0.25:
                awards.append({
                    "name": random.choice(["Festival di Venezia", "Cannes", "Berlinale", "David di Donatello", "Nastri d'Argento"]),
                    "year": year,
                    "category": random.choice(["Miglior Film", "Miglior Regia", "Miglior Sceneggiatura", "Selezione Ufficiale"]),
                    "won": random.random() < 0.4,
                })
            external_links = [
                {"label": "Trailer", "url": f"https://youtu.be/{''.join(random.choices(string.ascii_letters + string.digits, k=11))}"},
                {"label": "IMDB", "url": f"https://www.imdb.com/title/tt{random.randint(1000000, 9999999)}/"},
            ]
            w = ClientWork(
                tenant_id=1, client_id=c.id,
                title=title, year=year, kind=kind, our_role=random.choice([
                    "Post-produzione completa", "DI / Color", "Audio post", "VFX", "Mastering DCP",
                    "Localizzazione", "Conform online",
                ]),
                director=director,
                country=c.country,
                synopsis=f"{title} è un {kind} del {year} diretto da {director}. Storia di un personaggio che attraversa un viaggio interiore. Generato per stress test.",
                release_date=date(year, random.randint(1, 12), random.randint(1, 28)),
                funding_public=json.dumps(funding, ensure_ascii=False),
                cast_crew=json.dumps(cast_crew, ensure_ascii=False),
                external_links=json.dumps(external_links, ensure_ascii=False),
                awards=json.dumps(awards, ensure_ascii=False),
                sources_json=json.dumps([
                    {"name": "filmitalia.org", "url": "https://www.filmitalia.org"},
                    {"name": "IMDB", "url": "https://www.imdb.com"},
                ]),
                ai_imported=False,
                notes=f"Anno {year}, {kind}",
            )
            db.add(w)
            works_created += 1
        if works_created % 200 == 0:
            db.commit()
    db.commit()
    cnt("client_works", works_created)
    log.info(f"  -> 100 clienti, {works_created} opere in filmografia")
    return clients_created


def stage_projects(db: Session, clients: list[Client]) -> list[Project]:
    log.info("STAGE 5 — 1000 progetti distribuiti su 3 anni e clienti")
    projects_created: list[Project] = []
    # Status distribution:
    # 5% prospect, 15% quoting, 50% active, 25% completed, 5% archived
    STATUS_POOL = (
        [ProjectStatus.prospect] * 50 +
        [ProjectStatus.quoting] * 150 +
        [ProjectStatus.active] * 500 +
        [ProjectStatus.completed] * 250 +
        [ProjectStatus.archived] * 50
    )
    assert len(STATUS_POOL) == 1000
    random.shuffle(STATUS_POOL)

    project_type_pool = ["feature_film", "series", "documentary", "spot", "music_video", "short_film", "corporate"]
    fps_pool = ["24", "23.976", "25", "29.97", "30", "50"]
    shoot_format_pool = [
        "ARRI Alexa Mini LF ProRes 4444 XQ",
        "Sony Venice 2 X-OCN ST",
        "RED V-Raptor REDCODE",
        "ARRI Alexa 35 ARRIRAW",
        "Blackmagic URSA 12K",
        "Canon C500 Mark II RAW",
        "Sony FX9 XAVC-I",
    ]
    delivery_format_pool = [
        "4K-DCI HDR Dolby Vision",
        "4K UHD SDR Rec.709",
        "HD 1080p25 ProRes",
        "IMF Netflix 2K HDR",
        "DPP AS-11 UHD",
        "DCP INTEROP 2K",
        "ProRes 4444 Master + H.264 screener",
    ]

    for i in range(1000):
        status = STATUS_POOL[i]
        client = random.choice(clients)
        year = random.choice([2024, 2024, 2024, 2025, 2025, 2025, 2025, 2026, 2026])
        proj_num = i + 1
        code = f"P-{year}-{proj_num:04d}"
        title = _rand_film_title()
        if random.random() < 0.2:
            title = f"{title} {random.choice(['Stagione', 'Vol.', 'Cap.', 'Ep.'])} {random.randint(1, 5)}"
        ptype = random.choice(project_type_pool)
        length_m = {
            "feature_film": random.uniform(85, 140),
            "series": random.uniform(45, 60),
            "documentary": random.uniform(52, 100),
            "spot": random.uniform(0.25, 2),
            "music_video": random.uniform(3, 6),
            "short_film": random.uniform(8, 25),
            "corporate": random.uniform(2, 15),
        }[ptype]
        shoot_start = date(year, random.randint(1, 10), random.randint(1, 28))
        shoot_end = shoot_start + timedelta(days=random.randint(15, 90))
        post_start = shoot_end + timedelta(days=random.randint(7, 30))
        delivery = post_start + timedelta(days=random.randint(60, 240))
        p = Project(
            tenant_id=1,
            code=code,
            title=title,
            client_id=client.id,
            project_type=ptype,
            length_minutes=round(length_m, 2),
            fps=random.choice(fps_pool),
            shooting_format=random.choice(shoot_format_pool),
            delivery_format=random.choice(delivery_format_pool),
            director=random.choice(DIRECTORS_POOL),
            producer=random.choice(PRODUCERS_POOL),
            dop=random.choice(DOP_POOL),
            shoot_start=shoot_start,
            shoot_end=shoot_end,
            post_start=post_start,
            delivery_deadline=delivery,
            status=status,
            description=f"{ptype.replace('_', ' ').title()} per {client.name}. {title} — generato seed_stress.",
            notes=f"Codice interno {code}, anno produzione {year}.",
        )
        db.add(p)
        projects_created.append(p)
        if (i+1) % 100 == 0:
            db.commit()
    db.commit()
    for p in projects_created:
        db.refresh(p)
    cnt("projects", len(projects_created))
    log.info(f"  -> {len(projects_created)} progetti")

    # Project milestones per ~30% dei progetti (3-5 ciascuno)
    milestones = 0
    for p in projects_created:
        if random.random() < 0.3 and p.delivery_deadline:
            n = random.randint(2, 5)
            for k in range(n):
                offset = random.randint(-180, -10)
                target = p.delivery_deadline + timedelta(days=offset)
                m = ProjectMilestone(
                    project_id=p.id,
                    title=random.choice([
                        "Lock picture", "DI start", "Mix start",
                        "Screening cliente", "DCP master", "Consegna trailer",
                        "QC interno", "Finishing finale",
                    ]),
                    target_date=target,
                    is_completed=target < date.today(),
                    completed_at=datetime.combine(target, time(17, 0)) if target < date.today() else None,
                )
                db.add(m)
                milestones += 1
        if milestones % 500 == 0 and milestones > 0:
            db.commit()
    db.commit()
    cnt("milestones", milestones)
    log.info(f"  -> {milestones} milestone progetto")
    return projects_created


def stage_quotes_jobs(db: Session, projects: list[Project]) -> dict:
    log.info("STAGE 6 — Quote + Job + JobCostLine per progetti non-prospect")
    price_items = db.query(PriceItem).filter(
        PriceItem.tenant_id == 1, PriceItem.is_active == True
    ).all()
    if not price_items:
        issue("Listino vuoto, niente quote generate")
        return {"quotes": [], "jobs": []}

    quotes_created = []
    jobs_created = []
    quote_seq = {2024: 0, 2025: 0, 2026: 0}
    job_seq = {2024: 0, 2025: 0, 2026: 0}

    for p in projects:
        if p.status == ProjectStatus.prospect:
            continue
        # status mappa
        if p.status == ProjectStatus.quoting:
            quote_states_pool = [QuoteStatus.draft, QuoteStatus.sent]
            has_job = False
        elif p.status == ProjectStatus.active:
            quote_states_pool = [QuoteStatus.approved]
            has_job = True
        elif p.status == ProjectStatus.completed:
            quote_states_pool = [QuoteStatus.approved]
            has_job = True
        elif p.status == ProjectStatus.archived:
            quote_states_pool = [QuoteStatus.approved, QuoteStatus.rejected, QuoteStatus.expired]
            has_job = random.random() < 0.5
        else:
            continue

        # numero di versioni (1-3); ultima è quella "attiva"
        n_versions = 1
        if random.random() < 0.2:
            n_versions = random.randint(2, 3)

        chain_prev = None
        active_quote = None
        for v in range(1, n_versions + 1):
            year = p.shoot_start.year if p.shoot_start else 2025
            quote_seq[year] = quote_seq.get(year, 0) + 1
            num = f"Q-{year}-{quote_seq[year]:04d}"

            if v < n_versions:
                # versioni superate
                q_status = QuoteStatus.superseded
            else:
                q_status = random.choice(quote_states_pool)

            issue_date = (p.post_start or p.shoot_start or date(year, 6, 1)) + timedelta(days=random.randint(-30, -7))
            valid_until = issue_date + timedelta(days=45)

            q = Quote(
                tenant_id=1,
                number=num,
                version=v,
                project_id=p.id,
                client_id=p.client_id,
                title=f"{p.title} — Quotazione v{v}",
                status=q_status,
                issue_date=issue_date,
                valid_until=valid_until,
                production_material=p.shooting_format,
                length_minutes=p.length_minutes,
                fps=p.fps,
                delivery_format=p.delivery_format,
                shooting_days=random.randint(10, 60),
                package_discount=round(random.uniform(-0.15, 0.0), 3),
                vat_rate=22.0,
                payment_terms=random.choice([
                    "30% Project Start / 30% Picture Lock / 40% Delivery",
                    "20% Project Start / 40% Grading / 40% Mix",
                    "Pagamento 30 gg DF FM",
                    "Pagamento 60 gg DF",
                    "50% in acconto / 50% a consegna",
                ]),
                notes="Quotazione generata da seed_stress. Termini generali si applicano.",
                parent_quote_id=chain_prev.id if chain_prev else None,
            )
            db.add(q)
            db.flush()
            quotes_created.append(q)

            # 6-15 righe per quote
            n_lines = random.randint(6, 15)
            chosen = random.sample(price_items, min(n_lines, len(price_items)))
            subtotal_gross = 0.0
            for idx, pi in enumerate(chosen):
                qty = round(random.uniform(1, 25), 1)
                unit_price = pi.price_list or random.uniform(200, 1500)
                line_discount = round(random.uniform(0, 0.15), 3) if random.random() < 0.3 else 0
                gross = qty * unit_price
                total = round(gross * (1 - line_discount), 2)
                ql = QuoteLine(
                    quote_id=q.id,
                    price_item_id=pi.id,
                    section="A",
                    position=f"A.{idx+1}",
                    description=pi.name,
                    detail=f"Tariffa applicata: livello list {idx+1}",
                    quantity=qty,
                    unit=pi.unit,
                    price_level=PriceLevel.list_price,
                    unit_price=unit_price,
                    line_discount_pct=line_discount,
                    total=total,
                    hardcosts=pi.hardcosts or 0,
                    sort_order=idx,
                )
                db.add(ql)
                subtotal_gross += gross
            q.subtotal_gross = round(subtotal_gross, 2)
            q.subtotal = round(subtotal_gross, 2)
            after = subtotal_gross * (1 + (q.package_discount or 0))
            q.total_after_discount = round(after, 2)
            q.total_with_vat = round(after * 1.22, 2)
            # forecast win_probability_pct e expected_close_date
            if q.status == QuoteStatus.draft:
                q.win_probability_pct = 10
            elif q.status == QuoteStatus.sent:
                q.win_probability_pct = 30 + random.randint(-5, 20)
            elif q.status == QuoteStatus.approved:
                q.win_probability_pct = 90
            q.expected_close_date = q.issue_date + timedelta(days=30)
            chain_prev = q
            if v < n_versions:
                # superseded by next (riempito dopo flush della prossima)
                pass
            active_quote = q
        # mark superseded_by chain
        if n_versions > 1:
            chain = sorted([qx for qx in quotes_created if qx.project_id == p.id and qx.status == QuoteStatus.superseded],
                           key=lambda qx: qx.version)
            for older in chain:
                # next version in chain
                nxt = next((qx for qx in quotes_created if qx.project_id == p.id and qx.version == older.version + 1), None)
                if nxt:
                    older.superseded_by_id = nxt.id

        db.flush()

        # JOB solo se has_job e quote attiva è approved
        if has_job and active_quote and active_quote.status == QuoteStatus.approved:
            year = active_quote.issue_date.year
            job_seq[year] = job_seq.get(year, 0) + 1
            job = Job(
                tenant_id=1,
                code=f"{year}-{job_seq[year]:04d}",
                title=f"{p.title} — Job",
                description=active_quote.title,
                project_id=p.id,
                client_id=p.client_id,
                quote_id=active_quote.id,
                status=(JobStatus.completed if p.status == ProjectStatus.completed
                        else JobStatus.invoiced if p.status == ProjectStatus.archived
                        else JobStatus.active),
                start_date=p.post_start or active_quote.issue_date,
                end_date=p.delivery_deadline,
                budget_quoted=active_quote.total_after_discount,
            )
            db.add(job)
            db.flush()
            jobs_created.append(job)
            # JobCostLine cascading da QuoteLine
            for ql in active_quote.lines:
                actual_factor = (random.uniform(0.7, 1.1) if job.status != JobStatus.completed
                                 else random.uniform(0.85, 1.15))
                # extra random
                jcl = JobCostLine(
                    tenant_id=1, job_id=job.id, quote_line_id=ql.id,
                    price_item_id=ql.price_item_id,
                    description=ql.description,
                    quantity_quoted=ql.quantity,
                    quantity_actual=round(ql.quantity * actual_factor, 2),
                    unit=ql.unit, unit_price=ql.unit_price,
                    total_quoted=ql.total,
                    total_accrued=round(ql.total * actual_factor, 2),
                    total_expected=round(ql.total * actual_factor * 1.05, 2),
                    is_billable=True,
                )
                db.add(jcl)
            # qualche extra (lavorazioni aggiunte dopo)
            if random.random() < 0.4:
                for _ in range(random.randint(1, 3)):
                    extra_pi = random.choice(price_items)
                    qty = round(random.uniform(0.5, 5), 1)
                    up = extra_pi.price_list or 500
                    jcl_ex = JobCostLine(
                        tenant_id=1, job_id=job.id,
                        price_item_id=extra_pi.id,
                        description=f"[EXTRA] {extra_pi.name}",
                        quantity_quoted=0, quantity_actual=qty,
                        unit=extra_pi.unit, unit_price=up,
                        total_quoted=0, total_accrued=round(qty * up, 2),
                        total_expected=round(qty * up * 1.05, 2),
                        is_billable=True, is_extra=True,
                    )
                    db.add(jcl_ex)
        db.commit()
    db.commit()
    cnt("quotes", len(quotes_created))
    cnt("jobs", len(jobs_created))
    cnt("job_cost_lines", db.query(JobCostLine).count())
    log.info(f"  -> {len(quotes_created)} quote, {len(jobs_created)} job, "
             f"{COUNTERS['job_cost_lines']} cost lines")

    # JobResourceAssignment: assegna 3-6 risorse per job
    all_resources = db.query(Resource).filter(Resource.tenant_id == 1).all()
    assignments = 0
    for job in jobs_created:
        n_res = random.randint(3, 6)
        pool = random.sample(all_resources, min(n_res, len(all_resources)))
        for res in pool:
            db.add(JobResourceAssignment(
                job_id=job.id, resource_id=res.id,
                role_in_project=res.role or "Risorsa",
                planned_days=random.randint(3, 25),
                agreed_daily_rate=res.daily_rate,
                agreed_hourly_rate=res.hourly_rate,
            ))
            assignments += 1
        if assignments % 500 == 0:
            db.commit()
    db.commit()
    cnt("job_resource_assignments", assignments)
    log.info(f"  -> {assignments} job_resource_assignments")
    return {"quotes": quotes_created, "jobs": jobs_created}


def stage_bookings(db: Session, jobs: list[Job], all_resources: list[Resource]) -> None:
    log.info("STAGE 7 — Bookings + assignments su 3 anni (2024-2026)")
    person_resources = [r for r in all_resources
                        if r.type in (ResourceType.person_internal, ResourceType.person_freelance)]
    studio_resources = [r for r in all_resources if r.type == ResourceType.studio]
    today = date.today()

    bookings_count = 0
    assignments_count = 0
    for job in jobs:
        if not job.start_date or not job.end_date:
            continue
        days_span = (job.end_date - job.start_date).days
        if days_span <= 0:
            continue
        # 6-25 booking per job
        n_bookings = random.randint(6, 25)
        for _ in range(n_bookings):
            offset = random.randint(0, max(1, days_span - 1))
            d = job.start_date + timedelta(days=offset)
            if d.weekday() >= 5 and random.random() > 0.05:
                continue  # bias to weekdays
            start_hour = random.choice([9, 10, 14, 15])
            dur_h = random.choice([4, 6, 8, 8, 10])
            start_dt = datetime.combine(d, time(start_hour, 0))
            end_dt = start_dt + timedelta(hours=dur_h)
            # state per data
            if end_dt.date() < today:
                # passato → done / not_done
                state = random.choices(
                    [BookingState.done, BookingState.not_done],
                    weights=[92, 8],
                )[0]
            elif start_dt.date() <= today <= end_dt.date():
                state = BookingState.in_progress
            else:
                state = random.choice([BookingState.confirmed, BookingState.tentative, BookingState.confirmed])
            status_legacy = BOOKING_STATE_MAP[state][0]
            exec_legacy = BOOKING_STATE_MAP[state][1]
            b = Booking(
                tenant_id=1, job_id=job.id,
                start_datetime=start_dt, end_datetime=end_dt,
                kind=BookingKind.project,
                status=getattr(BookingStatus, status_legacy),
                state=state,
                execution_status=getattr(BookingExecutionStatus, exec_legacy),
                priority=random.choices(
                    [BookingPriority.low, BookingPriority.normal, BookingPriority.high],
                    weights=[10, 80, 10],
                )[0],
                notes=random.choice([None, "Conferma cliente", "Slot tentativo", None, None]),
            )
            db.add(b)
            db.flush()
            bookings_count += 1
            # 1-3 risorse persona + opzionale 1 sala
            n_people = random.randint(1, 3)
            for r in random.sample(person_resources, min(n_people, len(person_resources))):
                db.add(BookingAssignment(
                    booking_id=b.id, resource_id=r.id,
                    start_datetime=start_dt, end_datetime=end_dt,
                ))
                assignments_count += 1
            if random.random() < 0.4 and studio_resources:
                sala = random.choice(studio_resources)
                db.add(BookingAssignment(
                    booking_id=b.id, resource_id=sala.id,
                    start_datetime=start_dt, end_datetime=end_dt,
                ))
                assignments_count += 1
        if bookings_count % 500 == 0:
            db.commit()
            log.info(f"    ... {bookings_count} booking creati")
    db.commit()
    cnt("bookings", bookings_count)
    cnt("booking_assignments", assignments_count)
    log.info(f"  -> {bookings_count} booking, {assignments_count} assignments")


BOOKING_STATE_MAP = {
    BookingState.tentative: ("tentative", "planned"),
    BookingState.confirmed: ("confirmed", "planned"),
    BookingState.in_progress: ("confirmed", "in_progress"),
    BookingState.done: ("confirmed", "done"),
    BookingState.not_done: ("confirmed", "not_done"),
    BookingState.cancelled: ("cancelled", "planned"),
}


# Italian public holidays 2024-2026
HOLIDAYS = set()
for yr in (2024, 2025, 2026):
    HOLIDAYS.update([
        date(yr, 1, 1), date(yr, 1, 6), date(yr, 4, 25), date(yr, 5, 1),
        date(yr, 6, 2), date(yr, 8, 15), date(yr, 11, 1),
        date(yr, 12, 8), date(yr, 12, 25), date(yr, 12, 26),
    ])
# Easter rough approximations (skip exact calc, set Monday after each Apr)
HOLIDAYS.update([date(2024, 4, 1), date(2025, 4, 21), date(2026, 4, 6)])


def stage_timepunches_leaves(db: Session, internal_users: list[User], resources: list[Resource]) -> None:
    log.info("STAGE 8 — 3 anni TimePunch + ResourceUnavailability (ferie/malattia)")
    # Map user.id → resource.id (solo person_internal con user_id)
    user_to_resource = {r.user_id: r for r in resources
                        if r.user_id is not None and r.type == ResourceType.person_internal}
    if not user_to_resource:
        issue("Nessuna risorsa person_internal con user_id, niente TimePunch")
        return
    # Tutti i job per linking opzionale
    all_jobs = db.query(Job).filter(Job.tenant_id == 1).all()
    if not all_jobs:
        issue("Niente job, TimePunch senza job_id")

    start_date = date(2024, 1, 1)
    end_date = min(date.today(), date(2026, 12, 31))

    # Ferie: 25 giorni/anno × 3 anni × 150 = 11250 records circa
    # Genera blocchi di 5-10 giorni
    unav_count = 0
    for u in internal_users:
        if u.id not in user_to_resource:
            continue
        r = user_to_resource[u.id]
        for yr in (2024, 2025, 2026):
            if yr == 2026 and end_date.year < 2026:
                continue
            n_blocks = random.randint(3, 5)  # 3-5 blocks/year
            for _ in range(n_blocks):
                month = random.choice([7, 8, 8, 12, 4])  # bias estate/Natale
                day = random.randint(1, 20)
                dur = random.randint(3, 10)
                s = date(yr, month, day)
                e = s + timedelta(days=dur)
                if e > end_date:
                    continue
                kind = random.choices(
                    [UnavailabilityKind.vacation, UnavailabilityKind.sick, UnavailabilityKind.holiday],
                    weights=[70, 15, 15],
                )[0]
                u_status = (UnavailabilityStatus.approved if kind != UnavailabilityKind.sick
                            else random.choice([UnavailabilityStatus.approved, UnavailabilityStatus.pending]))
                db.add(ResourceUnavailability(
                    resource_id=r.id,
                    start_date=s, end_date=e,
                    kind=kind, reason=random.choice([None, "Vacanza", "Influenza", "Permesso famiglia"]),
                    status=u_status,
                    requested_by_user_id=u.id,
                    approved_by_user_id=u.id if u_status == UnavailabilityStatus.approved else None,
                    approved_at=datetime.combine(s, time(9, 0)) if u_status == UnavailabilityStatus.approved else None,
                ))
                unav_count += 1
        if unav_count % 500 == 0:
            db.commit()
    db.commit()
    cnt("unavailabilities", unav_count)
    log.info(f"  -> {unav_count} ResourceUnavailability")

    # TimePunch — denso: per ogni utente e ogni giorno feriale dal 2024 a oggi
    # Use raw SQL bulk insert per velocità
    log.info("  generating TimePunch... (può richiedere ~1 min)")

    # Pre-collect unavailability ranges per resource
    unav_by_res: dict[int, list[tuple[date, date, str]]] = {}
    for u in db.query(ResourceUnavailability).all():
        unav_by_res.setdefault(u.resource_id, []).append((u.start_date, u.end_date, u.kind.value))

    job_by_user_resource: dict[int, list[int]] = {}
    # mappa: per ogni resource_id, lista di job_id assegnati
    for jra in db.query(JobResourceAssignment).all():
        job_by_user_resource.setdefault(jra.resource_id, []).append(jra.job_id)

    punches_bulk = []
    today = date.today()
    d = start_date
    while d <= end_date:
        is_holiday = d in HOLIDAYS
        is_weekend = d.weekday() >= 5
        for u in internal_users:
            if u.id not in user_to_resource:
                continue
            r = user_to_resource[u.id]
            # check unavailability
            unavs = unav_by_res.get(r.id, [])
            in_unav = next(((s, e, k) for s, e, k in unavs if s <= d <= e), None)
            if in_unav:
                kind_str = in_unav[2]
                if kind_str == "vacation":
                    pkind = PunchKind.leave
                elif kind_str == "sick":
                    pkind = PunchKind.sick
                elif kind_str == "holiday":
                    # già festività auto-importata? skip se anche IS_HOLIDAY (no dup)
                    if is_holiday or is_weekend:
                        continue
                    pkind = PunchKind.leave
                else:
                    pkind = PunchKind.leave
                # Skip punch if holiday/weekend (no need to log "leave on weekend")
                if is_weekend or is_holiday:
                    continue
                punches_bulk.append({
                    "tenant_id": 1,
                    "resource_id": r.id,
                    "job_id": None,
                    "job_cost_line_id": None,
                    "start_datetime": datetime.combine(d, time(9, 0)),
                    "end_datetime": datetime.combine(d, time(18, 0)),
                    "kind": pkind.value,
                    "break_minutes": 0,
                    "notes": "Auto-generato da seed_stress",
                    "created_by_user_id": u.id,
                    "created_at": datetime.utcnow(),
                })
                continue
            if is_weekend or is_holiday:
                # 5% chance di shift weekend (overtime)
                if random.random() > 0.05:
                    continue
            # normale giorno lavorativo
            # 70% shift normale, 10% idle, 8% overtime, 12% nulla (assenza non registrata)
            roll = random.random()
            if roll < 0.7:
                start_h = random.choices([8, 9, 10], weights=[20, 70, 10])[0]
                hours = random.choices([8, 8, 8, 9, 7], weights=[60, 15, 10, 10, 5])[0]
                start_dt = datetime.combine(d, time(start_h, 0))
                end_dt = start_dt + timedelta(hours=hours + 1)  # +1h pausa
                # opzionale job_id
                jobs_for_res = job_by_user_resource.get(r.id, [])
                job_id = random.choice(jobs_for_res) if jobs_for_res and random.random() < 0.75 else None
                punches_bulk.append({
                    "tenant_id": 1,
                    "resource_id": r.id,
                    "job_id": job_id,
                    "job_cost_line_id": None,
                    "start_datetime": start_dt,
                    "end_datetime": end_dt,
                    "kind": PunchKind.shift.value,
                    "break_minutes": 60,
                    "notes": None,
                    "created_by_user_id": u.id,
                    "created_at": datetime.utcnow(),
                })
            elif roll < 0.8:
                # idle (presente, non allocato)
                start_dt = datetime.combine(d, time(9, 0))
                end_dt = start_dt + timedelta(hours=8)
                punches_bulk.append({
                    "tenant_id": 1, "resource_id": r.id, "job_id": None,
                    "job_cost_line_id": None,
                    "start_datetime": start_dt, "end_datetime": end_dt,
                    "kind": PunchKind.idle.value, "break_minutes": 60,
                    "notes": None, "created_by_user_id": u.id,
                    "created_at": datetime.utcnow(),
                })
            elif roll < 0.88:
                # overtime giornaliero
                start_dt = datetime.combine(d, time(9, 0))
                end_dt = start_dt + timedelta(hours=11)
                jobs_for_res = job_by_user_resource.get(r.id, [])
                job_id = random.choice(jobs_for_res) if jobs_for_res else None
                punches_bulk.append({
                    "tenant_id": 1, "resource_id": r.id, "job_id": job_id,
                    "job_cost_line_id": None,
                    "start_datetime": start_dt, "end_datetime": end_dt,
                    "kind": PunchKind.shift.value, "break_minutes": 30,
                    "notes": "Overtime", "created_by_user_id": u.id,
                    "created_at": datetime.utcnow(),
                })
            # else: nessun punch (assenza non registrata)
        d += timedelta(days=1)
        # bulk flush every 5000
        if len(punches_bulk) >= 5000:
            db.bulk_insert_mappings(TimePunch, punches_bulk)
            db.commit()
            log.info(f"    ... {COUNTERS.get('time_punches', 0) + len(punches_bulk)} punches written")
            cnt("time_punches", len(punches_bulk))
            punches_bulk = []
    if punches_bulk:
        db.bulk_insert_mappings(TimePunch, punches_bulk)
        db.commit()
        cnt("time_punches", len(punches_bulk))
    log.info(f"  -> {COUNTERS['time_punches']} TimePunch totali")


def stage_invoices(db: Session, jobs: list[Job]) -> None:
    log.info("STAGE 9 — Invoices + payments per job avanzati")
    invoice_num = 0
    invoices_created = 0
    payments_created = 0
    today = date.today()
    for job in jobs:
        if job.status not in (JobStatus.active, JobStatus.completed, JobStatus.invoiced):
            continue
        if not job.quote_id:
            continue
        quote_total = job.budget_quoted or 0
        if quote_total <= 0:
            continue
        # 1-4 fatture per job (acconto, intermedie, saldo)
        n_invoices = random.choices([1, 2, 3, 4], weights=[10, 40, 35, 15])[0]
        cumulative = 0.0
        for i in range(n_invoices):
            invoice_num += 1
            year = (job.start_date or date.today()).year
            num = f"{year}-{invoice_num:05d}"
            if i == 0:
                pct = 0.2
                label = "Acconto 20% Project Start"
            elif i == n_invoices - 1:
                pct = 1.0 - cumulative
                label = "Saldo finale"
            else:
                pct = round(random.uniform(0.2, 0.4), 2)
                label = f"SAL intermedio {i+1}/{n_invoices}"
            sub = round(quote_total * pct, 2)
            cumulative += pct
            total = round(sub * 1.22, 2)
            # status: per job completed/invoiced l'ultima è paid, le precedenti paid; active varie
            if job.status in (JobStatus.completed, JobStatus.invoiced):
                status = InvoiceStatus.paid
            else:
                status = random.choices(
                    [InvoiceStatus.draft, InvoiceStatus.sent, InvoiceStatus.paid, InvoiceStatus.overdue, InvoiceStatus.cancelled],
                    weights=[5, 35, 30, 25, 5],
                )[0]
            issue_d = (job.start_date or date(year, 1, 1)) + timedelta(days=30 * (i + 1))
            if issue_d > today:
                issue_d = today - timedelta(days=random.randint(1, 30))
            due_d = issue_d + timedelta(days=30)
            inv = Invoice(
                number=num,
                client_id=job.client_id, job_id=job.id, quote_id=job.quote_id,
                status=status,
                issue_date=issue_d, due_date=due_d,
                subtotal=sub, vat_rate=22.0, total=total,
                notes=label,
                doc_type="TD01",
                payment_method="Bonifico bancario",
                payment_terms_days=30,
                iban_snapshot="IT60X0542811101000000123456",
                amount_paid=0.0,
            )
            db.add(inv)
            db.flush()
            db.add(InvoiceLine(invoice_id=inv.id, description=label,
                               quantity=1, unit_price=sub, total=sub, vat_rate=22.0))
            invoices_created += 1
            # pagamenti
            if status == InvoiceStatus.paid:
                # full pay
                pay_amt = total
                p = InvoicePayment(
                    tenant_id=1, invoice_id=inv.id, amount=pay_amt,
                    payment_date=issue_d + timedelta(days=random.randint(7, 25)),
                    method="Bonifico", reference=f"TRN{random.randint(100000, 999999)}",
                )
                db.add(p)
                inv.amount_paid = pay_amt
                payments_created += 1
            elif status == InvoiceStatus.sent and random.random() < 0.4:
                # partial pay
                pct_pay = round(random.uniform(0.3, 0.7), 2)
                pay_amt = round(total * pct_pay, 2)
                p = InvoicePayment(
                    tenant_id=1, invoice_id=inv.id, amount=pay_amt,
                    payment_date=issue_d + timedelta(days=random.randint(5, 30)),
                    method=random.choice(["Bonifico", "Cassa", "Assegno"]),
                )
                db.add(p)
                inv.amount_paid = pay_amt
                payments_created += 1
            # overdue / cancelled / draft: no payments
        db.commit()
    cnt("invoices", invoices_created)
    cnt("invoice_payments", payments_created)
    log.info(f"  -> {invoices_created} invoices, {payments_created} payments")


def stage_suppliers(db: Session, jobs: list[Job]) -> None:
    log.info("STAGE 10 — Suppliers + supplier invoices (cost-side)")
    SUPPLIER_NAMES = [
        "Cinelab Italia S.r.l.", "Audio Service Roma", "DCP Master Berlin GmbH",
        "Storage House LTO Distributor", "Subtitler Studio S.r.l.",
        "Mastering Lab Milano", "Translation Bureau International",
        "Courier Express Logistics", "Color Lab Pro", "FX Render Cloud",
    ]
    suppliers = []
    for name in SUPPLIER_NAMES:
        s = Supplier(
            tenant_id=1, name=name,
            vat_number=_rand_vat_it(),
            contact_email=f"amministrazione@{name.lower().replace(' ', '').replace('.', '')[:18]}.com",
            contact_phone=_rand_phone(),
            iban=_rand_iban_it(),
            default_payment_terms_days=random.choice([30, 60, 90]),
            is_active=True,
        )
        db.add(s)
        suppliers.append(s)
    db.commit()
    for s in suppliers:
        db.refresh(s)
    cnt("suppliers", len(suppliers))

    # SupplierInvoice — ~3-8 per job advanced
    inv_count = 0
    pay_count = 0
    today = date.today()
    sup_inv_num = 0
    for job in random.sample(jobs, min(150, len(jobs))):
        n = random.randint(1, 5)
        for _ in range(n):
            sup_inv_num += 1
            sup = random.choice(suppliers)
            net = round(random.uniform(150, 3500), 2)
            vat = round(net * 0.22, 2)
            tot = round(net + vat, 2)
            issue_d = (job.start_date or date(2025, 1, 1)) + timedelta(days=random.randint(7, 200))
            if issue_d > today:
                issue_d = today - timedelta(days=random.randint(1, 60))
            due_d = issue_d + timedelta(days=random.choice([30, 60]))
            status = random.choices(
                [SupplierInvoiceStatus.paid, SupplierInvoiceStatus.partial,
                 SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.cancelled],
                weights=[55, 15, 25, 5],
            )[0]
            si = SupplierInvoice(
                tenant_id=1, supplier_id=sup.id,
                number=f"F/{2024 + sup_inv_num // 200}/{sup_inv_num:04d}",
                issue_date=issue_d, due_date=due_d,
                project_id=job.project_id, job_id=job.id,
                amount_net=net, vat_rate=22.0, amount_vat=vat, amount_total=tot,
                payment_status=status,
                amount_paid=tot if status == SupplierInvoiceStatus.paid else (
                    round(tot * random.uniform(0.3, 0.7), 2) if status == SupplierInvoiceStatus.partial else 0.0
                ),
                payment_date=issue_d + timedelta(days=random.randint(15, 60)) if status == SupplierInvoiceStatus.paid else None,
                notes=f"Fornitore per {job.title}",
            )
            db.add(si)
            db.flush()
            if status in (SupplierInvoiceStatus.paid, SupplierInvoiceStatus.partial):
                db.add(SupplierInvoicePayment(
                    tenant_id=1, supplier_invoice_id=si.id, amount=si.amount_paid,
                    payment_date=issue_d + timedelta(days=random.randint(15, 50)),
                    method="Bonifico",
                ))
                pay_count += 1
            inv_count += 1
        if inv_count % 100 == 0:
            db.commit()
    db.commit()
    cnt("supplier_invoices", inv_count)
    cnt("supplier_invoice_payments", pay_count)
    log.info(f"  -> {len(suppliers)} suppliers, {inv_count} invoices, {pay_count} payments")


def stage_physical_assets(db: Session, projects: list[Project], clients: list[Client]) -> list[PhysicalAsset]:
    log.info("STAGE 11 — 3000 PhysicalAsset (LTO/HDD/CRU/Blu-Ray/...)")
    KIND_POOL = (
        [PhysicalAssetKind.lto] * 35 +
        [PhysicalAssetKind.hdd] * 30 +
        [PhysicalAssetKind.cru] * 12 +
        [PhysicalAssetKind.bluray] * 10 +
        [PhysicalAssetKind.dvd] * 8 +
        [PhysicalAssetKind.case] * 3 +
        [PhysicalAssetKind.other] * 2
    )
    LOCATIONS = ["Cassaforte sala server", "Scaffale archivio piano 1", "Archivio piano -1",
                 "Spedito al cliente", "In magazzino", "Sala server", "Cabinet 3A", "Cabinet 5B"]
    counters = {k.value: 0 for k in PhysicalAssetKind}
    physical_created = []
    active_projects = [p for p in projects if p.status in (ProjectStatus.active, ProjectStatus.completed, ProjectStatus.archived)]
    for i in range(3000):
        kind = random.choice(KIND_POOL)
        counters[kind.value] += 1
        prefix = kind.value.upper()
        seq = counters[kind.value]
        label = f"{prefix}-{seq:04d}"
        # capacity per kind
        if kind == PhysicalAssetKind.lto:
            cap = random.choice([6000, 9000, 12000, 18000])
        elif kind == PhysicalAssetKind.hdd:
            cap = random.choice([2000, 4000, 8000, 16000])
        elif kind == PhysicalAssetKind.cru:
            cap = random.choice([1000, 2000, 4000])
        elif kind == PhysicalAssetKind.bluray:
            cap = random.choice([25, 50, 100])
        elif kind == PhysicalAssetKind.dvd:
            cap = random.choice([4.7, 8.5])
        else:
            cap = None
        used = round(cap * random.uniform(0.3, 0.98), 1) if cap else None
        proj = random.choice(active_projects) if active_projects and random.random() < 0.75 else None
        is_delivered = random.random() < 0.25
        owner_type = random.choices(
            [AssetOwnerType.internal, AssetOwnerType.client, AssetOwnerType.supplier],
            weights=[80, 15, 5],
        )[0]
        client_link = None
        if owner_type == AssetOwnerType.client and proj:
            client_link = proj.client_id
        elif owner_type == AssetOwnerType.client:
            client_link = random.choice(clients).id
        pa = PhysicalAsset(
            tenant_id=1,
            project_id=proj.id if proj else None,
            kind=kind,
            label=label,
            description=f"Supporto fisico {kind.value} #{seq}",
            serial_number=f"SN-{random.randint(100000, 999999999)}",
            manufacturer=random.choice(["IBM", "HP", "Quantum", "Sony", "Verbatim", "Maxell", "CRU"]),
            barcode=f"BAR-{random.randint(1000000000, 9999999999)}",
            capacity_gb=cap,
            used_gb=used,
            condition=random.choice(["nuovo", "verificato", "sospetto", "dismesso"]),
            location=random.choice(LOCATIONS),
            is_internal_archive=not is_delivered,
            is_delivered_external=is_delivered,
            delivered_at=datetime.utcnow() - timedelta(days=random.randint(1, 600)) if is_delivered else None,
            delivered_to=("Cliente " + random.choice(clients).name) if is_delivered else None,
            courier=random.choice(["DHL", "TNT", "GLS", "BRT", "Corriere interno"]) if is_delivered else None,
            tracking_number=f"TRK{random.randint(10000000, 99999999)}" if is_delivered else None,
            unit_cost=random.choice([85, 95, 130, 200, 350]),
            checksum_md5="".join(random.choices(string.hexdigits.lower(), k=32)),
            last_verified_at=datetime.utcnow() - timedelta(days=random.randint(0, 365)) if random.random() < 0.6 else None,
            owner_type=owner_type,
            owner_client_id=client_link,
            qr_code_token="".join(random.choices(string.ascii_lowercase + string.digits, k=24)),
            logistics_status="delivered_external" if is_delivered else "in_storage",
        )
        db.add(pa)
        physical_created.append(pa)
        if (i+1) % 500 == 0:
            db.commit()
            log.info(f"    ... {i+1} physical assets")
    db.commit()
    for pa in physical_created:
        db.refresh(pa)
    cnt("physical_assets", len(physical_created))
    log.info(f"  -> {len(physical_created)} physical assets")
    return physical_created


def stage_digital_assets(db: Session, projects: list[Project], jobs: list[Job], admin_user: User) -> list[Asset]:
    log.info("STAGE 12 — 5000 digital assets")
    tags = []
    for t in ["raw", "finale", "client-delivery", "broll", "interview", "dailies",
              "grade", "mix", "dcp", "vfx", "screener", "master", "kdm", "subtitle",
              "audio", "video", "report", "qc"]:
        existing = db.query(Tag).filter(Tag.name == t).first()
        if not existing:
            db.add(Tag(name=t))
            existing = None
        else:
            tags.append(existing)
    db.commit()
    tags = db.query(Tag).all()

    active_projects = [p for p in projects if p.status in
                       (ProjectStatus.active, ProjectStatus.completed, ProjectStatus.archived)]
    job_by_project = {}
    for j in jobs:
        job_by_project.setdefault(j.project_id, []).append(j)

    EXT_BY_TYPE = {
        AssetType.video: ["mov", "mxf", "mp4", "dpx", "exr"],
        AssetType.audio: ["wav", "aiff", "mp3", "atmos"],
        AssetType.image: ["jpg", "png", "tiff", "exr"],
        AssetType.document: ["pdf", "xlsx", "docx", "csv"],
        AssetType.other: ["zip", "rar", "tar.gz"],
    }
    MIME_BY_TYPE = {
        AssetType.video: "video/quicktime",
        AssetType.audio: "audio/wav",
        AssetType.image: "image/jpeg",
        AssetType.document: "application/pdf",
        AssetType.other: "application/octet-stream",
    }

    assets_created = []
    for i in range(5000):
        proj = random.choice(active_projects) if active_projects else None
        if proj is None:
            continue
        jobs_p = job_by_project.get(proj.id, [])
        job = random.choice(jobs_p) if jobs_p and random.random() < 0.7 else None
        atype = random.choices(
            list(AssetType),
            weights=[45, 20, 15, 15, 5],
        )[0]
        ext = random.choice(EXT_BY_TYPE[atype])
        seq = i + 1
        fname = f"{proj.code}_asset_{seq:05d}.{ext}"
        size = random.randint(1024 * 50, 1024 * 1024 * 1024 * 200)  # 50KB-200GB
        a = Asset(
            tenant_id=1,
            filename=fname,
            original_name=fname,
            file_path=f"uploads/{proj.code}/{fname}",
            thumbnail_path=None,
            asset_type=atype,
            mime_type=MIME_BY_TYPE[atype],
            file_size=size,
            description=f"Asset digitale {seq} per {proj.title}",
            job_id=job.id if job else None,
            project_id=proj.id,
            uploaded_by=admin_user.id,
            version=1,
            is_public=False,
            is_internal_archive=random.random() < 0.7,
            is_delivered_external=random.random() < 0.2,
        )
        db.add(a)
        assets_created.append(a)
        if (i+1) % 500 == 0:
            db.commit()
            log.info(f"    ... {i+1} digital assets")
    db.commit()
    cnt("digital_assets", len(assets_created))
    log.info(f"  -> {len(assets_created)} digital assets")
    return assets_created


def stage_movements(db: Session, physical: list[PhysicalAsset], digital: list[Asset],
                    projects: list[Project], clients: list[Client], admin: User) -> None:
    log.info("STAGE 13 — Asset movements: 500 ingest + 500 outgest = 1000 movimenti")
    # IngestBatch: 1 per ~5 movimenti → ~200 batch
    batch_count = 0
    movement_count = 0
    today = date.today()

    # 200 ingest batches (ingest + outgest mix), 5 movs ciascuno
    for i in range(200):
        bdir = random.choice(["ingest", "outgest"])
        client = random.choice(clients)
        proj = random.choice([p for p in projects if p.client_id == client.id] or projects)
        batch_count += 1
        batch_code = f"BATCH-{2024 + (i // 80)}-{(i % 80) + 1:03d}"
        batch_date = datetime.utcnow() - timedelta(days=random.randint(1, 1095))
        ib = IngestBatch(
            tenant_id=1,
            code=batch_code,
            direction=bdir,
            title=f"{bdir.title()} {proj.title}",
            description=f"Batch {bdir} per progetto {proj.code}",
            project_id=proj.id,
            client_id=client.id,
            delivery_note_number=f"DDT-{random.randint(10000, 99999)}",
            batch_date=batch_date,
            notes=f"Generato da seed_stress, direction={bdir}",
            created_by_user_id=admin.id,
        )
        db.add(ib)
        db.flush()
        # 3-7 movements
        n_movs = random.randint(3, 7)
        for j in range(n_movs):
            mov_type = AssetMovementType.ingest if bdir == "ingest" else AssetMovementType.outgest
            # mutex: 1 physical OR 1 digital
            if random.random() < 0.6 and physical:
                pa = random.choice(physical)
                asset_link = None
                phys_link = pa.id
            else:
                a = random.choice(digital) if digital else None
                if a is None:
                    continue
                asset_link = a.id
                phys_link = None
            mv = AssetMovement(
                tenant_id=1,
                physical_asset_id=phys_link,
                asset_id=asset_link,
                ingest_batch_id=ib.id,
                movement_type=mov_type,
                delivery_note_number=ib.delivery_note_number,
                movement_date=batch_date,
                from_party=client.name if bdir == "ingest" else "MediaFlow Stress S.r.l.",
                to_party="MediaFlow Stress S.r.l." if bdir == "ingest" else client.name,
                from_address=f"Sede {client.city}" if bdir == "ingest" else "Via Cinecittà 1, Roma",
                to_address="Via Cinecittà 1, Roma" if bdir == "ingest" else f"Sede {client.city}",
                client_id=client.id,
                package_count=random.randint(1, 3),
                total_weight_kg=round(random.uniform(0.2, 12), 2),
                contents_description=f"Contenuto batch {batch_code} mov {j+1}",
                carrier=random.choice(["DHL", "TNT", "GLS", "BRT"]),
                tracking_number=f"TRK{random.randint(10000000, 99999999)}",
                shipping_cost=round(random.uniform(15, 80), 2),
                confirmed_at=batch_date + timedelta(days=random.randint(1, 5)),
                confirmed_by_name=f"{_rand_first()} {random.choice(LAST_NAMES)}",
                created_by_user_id=admin.id,
            )
            db.add(mv)
            movement_count += 1
        if batch_count % 50 == 0:
            db.commit()
    db.commit()
    cnt("ingest_batches", batch_count)
    cnt("asset_movements", movement_count)
    log.info(f"  -> {batch_count} batch, {movement_count} movimenti")


def stage_billing_batches(db: Session, jobs: list[Job]) -> None:
    log.info("STAGE 14 — BillingBatch + JCLBilledSlice per closed periods")
    closed = [j for j in jobs if j.status in (JobStatus.completed, JobStatus.invoiced)]
    sample = random.sample(closed, min(50, len(closed)))
    batch_count = 0
    line_count = 0
    slice_count = 0
    year_seq = {2024: 0, 2025: 0, 2026: 0}
    for job in sample:
        if not job.start_date or not job.end_date:
            continue
        # ~2 batch per job (mensili)
        jcl_list = db.query(JobCostLine).filter(JobCostLine.job_id == job.id).all()
        if not jcl_list:
            continue
        for batch_idx in range(2):
            period_start = job.start_date + timedelta(days=batch_idx * 60)
            period_end = period_start + timedelta(days=59)
            if period_end > job.end_date:
                period_end = job.end_date
            year = period_start.year
            year_seq[year] = year_seq.get(year, 0) + 1
            code = f"BB-{year}-{year_seq[year]:04d}"
            bb = BillingBatch(
                tenant_id=1, code=code, project_id=job.project_id,
                status=BillingBatchStatus.invoiced,
                period_start=period_start, period_end=period_end,
                total_proposed=0, total_approved=0, total_lost=0,
                transmitted_at=datetime.combine(period_end, time(18, 0)),
                approved_at=datetime.combine(period_end + timedelta(days=2), time(10, 0)),
            )
            db.add(bb)
            db.flush()
            tot_prop = 0.0
            tot_appr = 0.0
            for jcl in jcl_list:
                share = jcl.total_accrued / max(1, len(jcl_list))
                line_prop = round(share, 2)
                line_appr = round(line_prop * random.uniform(0.85, 1.0), 2)
                tot_prop += line_prop
                tot_appr += line_appr
                bbl = BillingBatchLine(
                    batch_id=bb.id, job_cost_line_id=jcl.id,
                    description=jcl.description,
                    quantity=jcl.quantity_actual or 0,
                    unit=jcl.unit, unit_price=jcl.unit_price,
                    total_proposed=line_prop, total_approved=line_appr,
                    is_extra=jcl.is_extra,
                )
                db.add(bbl)
                db.flush()
                line_count += 1
                # JCLBilledSlice (slice approvata)
                slice_ = JCLBilledSlice(
                    tenant_id=1, job_cost_line_id=jcl.id,
                    billing_batch_line_id=bbl.id,
                    period_start=period_start, period_end=period_end,
                    billed_quantity=bbl.quantity, billed_amount=line_appr,
                    unit_price_snap=jcl.unit_price,
                )
                db.add(slice_)
                slice_count += 1
                # Loss entry se delta significativo
                if line_prop - line_appr > 5:
                    db.add(LossEntry(
                        tenant_id=1, project_id=job.project_id,
                        job_cost_line_id=jcl.id, billing_batch_line_id=bbl.id,
                        amount=round(line_prop - line_appr, 2),
                        reason=random.choice([LossReason.manager_discount, LossReason.rounding]),
                        notes="Auto-generato seed_stress",
                    ))
                jcl.billing_status = JCLBillingStatus.billed
            bb.total_proposed = round(tot_prop, 2)
            bb.total_approved = round(tot_appr, 2)
            bb.total_lost = round(tot_prop - tot_appr, 2)
            batch_count += 1
        db.commit()
    cnt("billing_batches", batch_count)
    cnt("billing_batch_lines", line_count)
    cnt("billed_slices", slice_count)
    log.info(f"  -> {batch_count} billing batches, {line_count} lines, {slice_count} slices")


def stage_notifications(db: Session, internal_users: list[User], projects: list[Project]) -> None:
    log.info("STAGE 15 — Notifiche di esempio (campionatura)")
    sample_users = random.sample(internal_users, min(30, len(internal_users)))
    n = 0
    for u in sample_users:
        for _ in range(random.randint(2, 8)):
            kind = random.choice([
                "unavailability_pending", "booking_status_changed",
                "job_deadline_approaching", "quote_status_changed",
                "extra_after_billed",
            ])
            db.add(Notification(
                tenant_id=1, user_id=u.id, kind=kind,
                severity=random.choice(["info", "action_required", "alert"]),
                title=f"Notifica {kind.replace('_', ' ')}",
                body=f"Auto-generata da seed_stress per stress test.",
                is_read=random.random() < 0.4,
            ))
            n += 1
    db.commit()
    cnt("notifications", n)
    log.info(f"  -> {n} notifications")


def stage_ai_history(db: Session, admin: User, projects: list[Project]) -> None:
    log.info("STAGE 16 — AIConversation/Action campione (pre-test)")
    conv_count = 0
    msg_count = 0
    for proj in random.sample(projects, min(5, len(projects))):
        c = AIConversation(
            user_id=admin.id, project_id=proj.id,
            title=f"Sessione iniziale su {proj.title}",
        )
        db.add(c)
        db.flush()
        db.add(AIMessage(conversation_id=c.id, role="user",
                         content=f"Riassumi lo stato di {proj.title}"))
        db.add(AIMessage(conversation_id=c.id, role="assistant",
                         content=f"{proj.title} è in stato {proj.status.value}. Generato pre-test."))
        conv_count += 1
        msg_count += 2
    db.commit()
    cnt("ai_conversations", conv_count)
    cnt("ai_messages", msg_count)


def write_users_csv(rows: list[dict]) -> Path:
    out = ROOT / "docs" / "users_stress.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "email", "name", "password", "role", "department", "is_resource", "note",
        ])
        writer.writeheader()
        writer.writerows(rows)
    return out


def write_report(out_path: Path, counters: dict, issues: list[str]) -> None:
    lines = [
        "# Stress Test Report — MediaFlow",
        "",
        f"Generato: {datetime.now().isoformat(timespec='seconds')}",
        f"Seed random: {RANDOM_SEED}",
        "",
        "## Conteggi entità",
        "",
        "| Entità | Count |",
        "|--------|-------|",
    ]
    for k, v in sorted(counters.items()):
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Issue / warning",
        "",
    ]
    if issues:
        for it in issues:
            lines.append(f"- {it}")
    else:
        lines.append("Nessuno.")
    lines += [
        "",
        "## Credenziali di accesso",
        "",
        "- **admin@mediaflow.it** / `admin123` — admin completo (Matteo demo)",
        "- **matteo@mediaflow.it** / `matteo123` — admin (proprietario)",
        "- Per le 150 utenze interne: vedere `docs/users_stress.csv` (colonna `password`).",
        "",
        "## Note",
        "",
        "- DB ricostruito da seed_stress con `--reset` (snapshot backup in `db_snapshots/`).",
        "- TimePunch + ResourceUnavailability coprono 2024-01-01 → today.",
        "- Bookings distribuiti sull'intervallo di vita di ogni job.",
        "- Quote in tutti gli stati (draft/sent/approved/rejected/expired/superseded).",
        "- Invoices in tutti gli stati con pagamenti parziali, totali, scaduti.",
        "- PhysicalAsset includono LTO/HDD/CRU/Blu-Ray con ownership cliente/interno/fornitore.",
        "- AssetMovement + IngestBatch coprono ingest + outgest 2024-2026.",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", default=True,
                        help="Reset completo del DB (default ON per stress test)")
    parser.add_argument("--keep", action="store_true", help="Mantieni DB esistente")
    args = parser.parse_args()
    reset = args.reset and not args.keep

    t0 = datetime.now()
    stage_setup(reset=reset)
    db = SessionLocal()
    try:
        stage_tenant_roles(db)
        stage_pricelist(db)
        result = stage_users_resources(db)
        admin = result["admin"]
        internal_users = result["internal_users"]
        resources = result["resources"]
        users_csv_rows = result["users_csv_rows"]

        clients = stage_clients(db)
        projects = stage_projects(db, clients)
        qj = stage_quotes_jobs(db, projects)
        jobs = qj["jobs"]

        all_resources = db.query(Resource).filter(Resource.tenant_id == 1).all()
        stage_bookings(db, jobs, all_resources)
        stage_timepunches_leaves(db, internal_users, all_resources)
        stage_invoices(db, jobs)
        stage_suppliers(db, jobs)
        physical = stage_physical_assets(db, projects, clients)
        digital = stage_digital_assets(db, projects, jobs, admin)
        stage_movements(db, physical, digital, projects, clients, admin)
        stage_billing_batches(db, jobs)
        stage_notifications(db, internal_users, projects)
        stage_ai_history(db, admin, projects)

        csv_path = write_users_csv(users_csv_rows)
        log.info(f"CSV utenze: {csv_path}")
    finally:
        db.close()

    duration = datetime.now() - t0
    report_path = ROOT / "docs" / "stress_test_report.md"
    write_report(report_path, COUNTERS, ISSUES)
    log.info("=" * 60)
    log.info(f"DONE in {duration.total_seconds():.1f}s")
    log.info("=" * 60)
    for k, v in sorted(COUNTERS.items()):
        log.info(f"  {k:32s} {v:>8d}")
    log.info("=" * 60)
    log.info(f"Report -> {report_path}")
    if ISSUES:
        log.warning(f"Issue: {len(ISSUES)}")
        for it in ISSUES:
            log.warning(f"  - {it}")


if __name__ == "__main__":
    main()
