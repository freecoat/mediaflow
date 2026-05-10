"""
MediaFlow — Simulazione completa per debug + verifica affidabilità

Versione 1.0 — 11 maggio 2026

Genera un dataset realistico per stress-testare i workflow end-to-end:
- 4 clienti (mix italian+international)
- 30 risorse (mix employee/freelance/studio/equipment)
- 12 progetti distribuiti
- ~25 quotazioni in stati diversi (draft/sent/approved/superseded/versioning)
- ~15 job in stati differenziati (active/in_progress/completed/cancelled)
- ~80 booking con execution status mix (planned/in_progress/done/not_done)
- 5 fatture (paid/sent/cancelled) con JCLBilledSlice per testare slice-lock
- ~30 AIAction simulate (proposed/applied/rejected) per ogni capability

A FINE SCRIPT:
- DB compilato e pronto per verifica manuale via UI
- File `docs/SIMULATION_REPORT.md` con riepilogo + check integrità
- Stdout con OK/KO per ogni stage

USO:
    .venv/Scripts/python.exe scripts/simulate_full.py [--reset]

OPZIONI:
    --reset        Cancella tutti i dati esistenti e ricrea da zero (default)
    --keep         Mantiene i dati esistenti (additivo, può causare collisioni)
    --no-ai        Skippa la simulazione AIAction
    --quiet        Solo riepilogo finale, no log per-stage

NB: questo script popola il database REALE. Backup automatico in
    db_snapshots/ prima di ogni reset.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Setup path per import relativo
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, create_tables
from app.models.models import (
    Tenant, User, UserRole, Role, Department,
    Client, ClientWork, Project, ProjectStatus, ProjectMilestone,
    Resource, ResourceType, ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
    PriceCategory, PriceItem, PriceLevel,
    Quote, QuoteLine, QuoteStatus,
    Job, JobStatus, JobCostLine,
    Booking, BookingAssignment, BookingChange, BookingStatus, BookingKind,
    BookingPriority, BookingExecutionStatus, BookingState,
    Invoice, InvoiceLine, InvoiceStatus,
    BillingBatch, BillingBatchLine, BillingBatchStatus, JCLBillingStatus,
    JCLBilledSlice,
    AIAction, AIConversation, AIUsageLog,
)
from app.services.auth import hash_password


# ─────────────────────────────────────────────────────────────
# Setup logger + counters
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger("simulate")

# Disabilita log SQLAlchemy verbose
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
# Spegni anche echo nativo SQLAlchemy
engine.echo = False


COUNTERS: dict[str, int] = {}
ISSUES: list[str] = []


def cnt(key: str, n: int = 1) -> None:
    COUNTERS[key] = COUNTERS.get(key, 0) + n


def issue(msg: str) -> None:
    ISSUES.append(msg)
    log.warning(f"ISSUE: {msg}")


# ─────────────────────────────────────────────────────────────
# Stage 0 — Reset + setup
# ─────────────────────────────────────────────────────────────

def stage_setup(reset: bool) -> None:
    log.info("STAGE 0 — Setup DB")
    db_path = ROOT / "mediaflow.db"
    if db_path.exists() and reset:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = ROOT / "db_snapshots" / f"snapshot-presimulation-{ts}.db"
        backup.parent.mkdir(exist_ok=True)
        shutil.copy(db_path, backup)
        log.info(f"  backup → {backup.name}")
        # Reset schema
        from app.models.models import Base
        Base.metadata.drop_all(bind=engine)
        log.info("  schema dropped")
    create_tables()
    log.info("  schema created/verified")
    # Auto-migrate per colonne aggiunte di recente
    from app.main import _auto_migrate_columns
    _auto_migrate_columns()
    log.info("  _auto_migrate_columns OK")

    # Seed minimo: tenant + ruoli
    db = SessionLocal()
    try:
        if not db.query(Tenant).filter(Tenant.id == 1).first():
            db.add(Tenant(
                id=1,
                name="MediaFlow Demo",
                slug="demo",
                legal_name="MediaFlow Demo S.r.l.",
                vat_number="IT-00000000001",
                email="info@mediaflow.it",
                default_currency="EUR",
                default_vat_rate=22.0,
                tagline="Post-production made simple",
                brand_color="#6272f5",
            ))
            db.commit()
        from app.services.rbac import ensure_built_in_roles
        ensure_built_in_roles(db)
        # Admin demo user
        admin = db.query(User).filter(User.email == "admin@mediaflow.it").first()
        if not admin:
            admin = User(
                email="admin@mediaflow.it",
                full_name="Demo Admin",
                hashed_password=hash_password("admin"),
                role=UserRole.admin,
                is_active=True,
            )
            db.add(admin)
            db.commit()
        cnt("users", 1)
        log.info(f"  tenant + admin user (admin@mediaflow.it / admin)")
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────
# Stage 1 — Clienti + risorse + progetti
# ─────────────────────────────────────────────────────────────

CLIENTS = [
    {
        "name": "A24 Films",
        "legal_form": "LLC",
        "contact_name": "Sarah Cooper",
        "contact_email": "deliveries@a24films.com",
        "vat_number": "US-A24-0001",
        "country": "USA",
        "city": "New York",
        "industry": "Film Distribution",
        "company_size": "200-500",
        "founded_year": 2012,
    },
    {
        "name": "MUBI",
        "legal_form": "Ltd",
        "contact_name": "Tomás Rivera",
        "contact_email": "tech@mubi.com",
        "vat_number": "GB-MUBI-2010",
        "country": "UK",
        "city": "London",
        "industry": "Streaming Curated Cinema",
        "company_size": "50-200",
        "founded_year": 2007,
    },
    {
        "name": "Vision Distribution",
        "legal_form": "S.p.A.",
        "contact_name": "Giulia Russo",
        "contact_email": "consegne@visiondistribution.it",
        "vat_number": "IT-13456789012",
        "country": "Italia",
        "city": "Milano",
        "industry": "Distribuzione cinematografica",
        "company_size": "20-50",
        "founded_year": 2016,
    },
    {
        "name": "Sky Italia",
        "legal_form": "S.p.A.",
        "contact_name": "Marco Bianchi",
        "contact_email": "fornitori-postpro@sky.it",
        "vat_number": "IT-04619241005",
        "country": "Italia",
        "city": "Milano",
        "industry": "Pay TV / Streaming",
        "company_size": "1000+",
        "founded_year": 2003,
    },
]


# 30 risorse: mix per dipartimento e tipologia
RESOURCES = [
    # DI/Video reparto
    ("Luca Bianchi", "person_internal", "DI", "Senior Colorist", 700, 90),
    ("Marta Conti", "person_internal", "DI", "Colorist", 500, 70),
    ("Giulia Verdi", "person_freelance", "DI", "Colorist Freelance", 600, 85),
    ("Andrea Ferri", "person_internal", "DI", "Online Editor", 450, 65),
    ("Sala Color 1", "studio", "DI", "Sala Color HDR Dolby", 800, 110),
    ("Sala Color 2", "studio", "DI", "Sala Color SDR", 500, 70),
    ("Mastering Suite", "studio", "DI", "Suite Mastering DCP/IMF", 600, 85),
    # Audio reparto
    ("Stefano Romano", "person_internal", "Audio", "Re-recording Mixer", 750, 95),
    ("Paolo Esposito", "person_internal", "Audio", "Sound Designer", 500, 70),
    ("Chiara Greco", "person_internal", "Audio", "Dialogue Editor", 400, 60),
    ("Nicola Marino", "person_freelance", "Audio", "Foley Artist", 450, 65),
    ("Davide Sala", "person_freelance", "Audio", "ADR Engineer", 480, 68),
    ("Sala Mix Atmos", "studio", "Audio", "Sala Atmos 9.1.4", 1200, 160),
    ("Sala Mix 5.1", "studio", "Audio", "Sala Surround 5.1", 800, 110),
    ("Booth ADR", "studio", "Audio", "Cabina Doppiaggio", 350, 50),
    # VFX reparto
    ("Roberta Pisani", "person_internal", "VFX", "VFX Supervisor", 800, 110),
    ("Federico De Luca", "person_internal", "VFX", "Compositor Senior", 600, 85),
    ("Sara Montanari", "person_internal", "VFX", "Compositor", 450, 65),
    ("Matteo Lombardi", "person_freelance", "VFX", "Roto/Paint", 350, 50),
    ("Elena Caputo", "person_freelance", "VFX", "Matte Painter", 500, 70),
    ("Workstation Nuke 1", "equipment", "VFX", "Workstation Nuke X", 200, 28),
    ("Workstation Nuke 2", "equipment", "VFX", "Workstation Nuke X", 200, 28),
    ("Render Farm 256c", "equipment", "VFX", "Render Farm 256 core", 600, 85),
    # Commercial reparto
    ("Anna Marchetti", "person_internal", "Commercial", "Account Senior", 400, 60),
    ("Luigi Riva", "person_internal", "Commercial", "Account", 320, 50),
    ("Giorgio Pasquini", "person_freelance", "Commercial", "Producer", 500, 70),
    # Software / asset shared
    ("Pro Tools 1", "software", "Audio", "Pro Tools HDX seat", 80, 12),
    ("DaVinci Resolve", "software", "DI", "Resolve Studio license", 60, 9),
    ("Furgone trasporti", "vehicle", "Commercial", "Veicolo aziendale", 100, 15),
    ("Veicolo backup", "vehicle", "Commercial", "Veicolo riserva", 100, 15),
]


PROJECTS_BY_CLIENT = {
    "A24 Films": [
        ("MOON25", "Moonbound", "feature_film", 95, "24"),
        ("PALE25", "Pale Horizon", "feature_film", 110, "24"),
        ("WAVE25", "Wave Document", "documentary", 78, "23.976"),
    ],
    "MUBI": [
        ("STILL25", "Still Light", "feature_film", 102, "24"),
        ("FRAG25", "Fragments", "short_film", 22, "24"),
        ("KIRA25", "Kira's Garden", "feature_film", 88, "25"),
    ],
    "Vision Distribution": [
        ("MARE25", "Mare Nostrum", "feature_film", 105, "25"),
        ("ROMA25", "Roma 2050", "series", 50, "25"),
        ("GIORNI25", "I giorni del cuore", "feature_film", 96, "25"),
    ],
    "Sky Italia": [
        ("PROSPERA25", "Prospera Stagione 2", "series", 50, "25"),
        ("DOC25", "Documentario Anno Zero", "documentary", 55, "25"),
        ("SPOT25", "Spot Lancio Streaming", "spot", 1, "25"),
    ],
}


def stage_clients_resources(db: Session) -> None:
    log.info("STAGE 1 — Clienti, reparti, risorse, progetti, listino base")

    # Reparti
    dept_data = [
        ("DI", "DI/Video", "#6272f5"),
        ("Audio", "Audio", "#10b981"),
        ("VFX", "VFX", "#a855f7"),
        ("Commercial", "Commerciale/Producer", "#fb923c"),
    ]
    depts: dict[str, Department] = {}
    for code, name, color in dept_data:
        d = db.query(Department).filter(Department.tenant_id == 1, Department.code == code).first()
        if not d:
            d = Department(tenant_id=1, code=code, name=name, color=color, is_active=True)
            db.add(d)
        depts[code] = d
    db.commit()
    for d in depts.values():
        db.refresh(d)
    cnt("departments", len(depts))

    # Listino: 6 categorie + ~20 voci coerenti col mix progetti
    pricelist_data = [
        # (cat_name, item_name, unit, price_list, hardcosts, dept_code, keywords)
        ("PICTURE EDITING", "Online Editor", "day", 600, 0, "DI", ["online", "conform"]),
        ("PICTURE EDITING", "Conform shot list", "lump", 1500, 0, "DI", ["conform", "edit"]),
        ("COLOR", "Color HDR Dolby Vision", "day", 1500, 0, "DI", ["color", "hdr", "dolby"]),
        ("COLOR", "Color SDR", "day", 1000, 0, "DI", ["color", "sdr"]),
        ("COLOR", "Color grading dailies", "day", 700, 0, "DI", ["color", "dailies"]),
        ("MASTERING", "DCP master IOP", "lump", 2200, 90, "DI", ["dcp", "master"]),
        ("MASTERING", "IMF master Netflix", "lump", 3500, 0, "DI", ["imf", "netflix"]),
        ("MASTERING", "ProRes deliverables", "lump", 600, 0, "DI", ["prores", "delivery"]),
        ("AUDIO", "Sound design", "day", 750, 0, "Audio", ["sound", "design"]),
        ("AUDIO", "Dialogue editing", "day", 500, 0, "Audio", ["dialogue", "edit"]),
        ("AUDIO", "Foley editing", "day", 550, 0, "Audio", ["foley"]),
        ("AUDIO", "Mix surround 5.1", "day", 1100, 500, "Audio", ["mix", "surround", "5.1"]),
        ("AUDIO", "Mix Dolby Atmos", "day", 1500, 800, "Audio", ["mix", "atmos", "dolby"]),
        ("AUDIO", "ADR session", "hour", 120, 0, "Audio", ["adr", "doppiaggio"]),
        ("VFX", "VFX supervisione giornata", "day", 1000, 0, "VFX", ["vfx", "supervisor"]),
        ("VFX", "VFX shot composito", "shot", 900, 0, "VFX", ["composit", "vfx", "shot"]),
        ("VFX", "VFX cleanup", "shot", 350, 0, "VFX", ["clean", "rig", "vfx"]),
        ("VFX", "Matte painting", "shot", 1800, 0, "VFX", ["matte"]),
        ("ARCHIVE", "Archive su LTO", "lump", 350, 90, "DI", ["lto", "archive"]),
        ("ARCHIVE", "Drive consegna USB-C", "lump", 250, 90, "DI", ["drive", "usb"]),
    ]
    cats: dict[str, PriceCategory] = {}
    items_by_name: dict[str, PriceItem] = {}
    for sort_idx, (cat_name, item_name, unit, price, hard, dept_code, keywords) in enumerate(pricelist_data):
        c = cats.get(cat_name)
        if not c:
            c = db.query(PriceCategory).filter(
                PriceCategory.tenant_id == 1, PriceCategory.name == cat_name,
            ).first()
            if not c:
                c = PriceCategory(tenant_id=1, name=cat_name, sort_order=len(cats) * 10)
                db.add(c)
                db.flush()
            cats[cat_name] = c
        i = db.query(PriceItem).filter(
            PriceItem.tenant_id == 1, PriceItem.name == item_name,
        ).first()
        if not i:
            i = PriceItem(
                tenant_id=1,
                category_id=c.id,
                department_id=depts[dept_code].id,
                name=item_name,
                unit=unit,
                price_list=price,
                price_average=int(price * 0.92),
                price_low=int(price * 0.85),
                hardcosts=hard,
                keywords=keywords,
                is_active=True,
            )
            db.add(i)
        items_by_name[item_name] = i
    db.commit()
    cnt("categories", len(cats))
    cnt("price_items", len(items_by_name))
    log.info(f"  listino: {len(cats)} categorie, {len(items_by_name)} voci")

    # Clienti
    clients_by_name: dict[str, Client] = {}
    for cd in CLIENTS:
        c = db.query(Client).filter(Client.tenant_id == 1, Client.name == cd["name"]).first()
        if not c:
            c = Client(tenant_id=1, **cd)
            db.add(c)
        clients_by_name[cd["name"]] = c
    db.commit()
    for c in clients_by_name.values():
        db.refresh(c)
    cnt("clients", len(clients_by_name))
    log.info(f"  {len(clients_by_name)} clienti")

    # Risorse
    resources_by_name: dict[str, Resource] = {}
    for name, rtype, dept_code, role, daily, hourly in RESOURCES:
        r = db.query(Resource).filter(
            Resource.tenant_id == 1, Resource.name == name,
        ).first()
        if not r:
            kwargs = dict(
                tenant_id=1,
                name=name,
                type=ResourceType[rtype],
                role=role,
                department_id=depts[dept_code].id,
                daily_rate=daily,
                hourly_rate=hourly,
                is_active=True,
                color="#" + "".join(random.choices("0123456789abcdef", k=6)),
            )
            # Cost-rate per le risorse "person_internal" (employee) per testare
            # hardcost interno deliverable + cost report split
            if rtype == "person_internal":
                kwargs["cost_type"] = "employee"
                kwargs["monthly_gross_salary"] = random.randint(2400, 3800)
                kwargs["annual_bonus_months"] = 13
                kwargs["cost_multiplier_oneri"] = 1.30
                kwargs["annual_working_hours"] = 1720
            elif rtype == "person_freelance":
                kwargs["cost_type"] = "freelance"
                kwargs["freelance_hourly_cost"] = int(hourly * 0.55)
            elif rtype == "studio":
                kwargs["cost_type"] = "studio"
                kwargs["studio_hourly_cost"] = int(hourly * 0.40)
            r = Resource(**kwargs)
            db.add(r)
        resources_by_name[name] = r
    db.commit()
    for r in resources_by_name.values():
        db.refresh(r)
    cnt("resources", len(resources_by_name))
    log.info(f"  {len(resources_by_name)} risorse")

    # Progetti distribuiti tra i clienti
    projects_by_code: dict[str, Project] = {}
    today = date.today()
    for client_name, prjs in PROJECTS_BY_CLIENT.items():
        cl = clients_by_name[client_name]
        for code, title, ptype, length_min, fps in prjs:
            p = db.query(Project).filter(
                Project.tenant_id == 1, Project.code == code,
            ).execution_options(include_deleted=True).first()
            if not p:
                # Range date: alcuni in passato (completed), alcuni futuro
                shoot_start = today + timedelta(days=random.randint(-180, 60))
                deadline = shoot_start + timedelta(days=random.randint(60, 200))
                p = Project(
                    tenant_id=1,
                    code=code,
                    title=title,
                    client_id=cl.id,
                    project_type=ptype,
                    length_minutes=length_min,
                    fps=fps,
                    delivery_format="DCP+IMF" if ptype == "feature_film" else "ProRes+IMF",
                    shoot_start=shoot_start,
                    delivery_deadline=deadline,
                    status=ProjectStatus.active,
                )
                db.add(p)
            projects_by_code[code] = p
    db.commit()
    for p in projects_by_code.values():
        db.refresh(p)
    cnt("projects", len(projects_by_code))
    log.info(f"  {len(projects_by_code)} progetti")

    # Memorizza per stage successivi via dict module-level
    global _SEED_REGISTRY
    _SEED_REGISTRY = {
        "depts": depts,
        "items": items_by_name,
        "cats": cats,
        "clients": clients_by_name,
        "resources": resources_by_name,
        "projects": projects_by_code,
    }


_SEED_REGISTRY: dict = {}


# ─────────────────────────────────────────────────────────────
# Stage 2 — Quotazioni multiple
# ─────────────────────────────────────────────────────────────

# Scenari di quotazioni per progetto: chi ha 1 quote draft, chi 2 versioning,
# chi una approved/superseded.
QUOTE_SCENARIOS = {
    # code → list of (status, version_label, package_discount, quote_lines_template)
    "MOON25":   [("approved", "v1", 0.05, "feature_full")],
    "PALE25":   [("draft", "v1", 0.0, "feature_color_only")],
    "WAVE25":   [("sent", "v1", 0.10, "doc_basic")],
    "STILL25":  [("approved", "v1", 0.0, "feature_audio_only")],
    "FRAG25":   [("draft", "v1", 0.0, "short_basic")],
    "KIRA25":   [("approved", "v2", 0.07, "feature_full")],
    "MARE25":   [("approved", "v1", 0.0, "feature_full")],
    "ROMA25":   [("sent", "v1", 0.05, "series_episode")],
    "GIORNI25": [("draft", "v1", 0.0, "feature_color_only")],
    "PROSPERA25": [("approved", "v1", 0.05, "series_episode")],
    "DOC25":    [("draft", "v1", 0.0, "doc_basic")],
    "SPOT25":   [("approved", "v1", 0.0, "spot_quick")],
}


# Template righe quote
LINE_TEMPLATES = {
    "feature_full": [
        ("Color HDR Dolby Vision", 8),
        ("Mix Dolby Atmos", 6),
        ("Sound design", 5),
        ("Dialogue editing", 4),
        ("DCP master IOP", 1),
        ("IMF master Netflix", 1),
        ("VFX shot composito", 25),
    ],
    "feature_color_only": [
        ("Color HDR Dolby Vision", 6),
        ("Online Editor", 4),
        ("DCP master IOP", 1),
    ],
    "feature_audio_only": [
        ("Sound design", 6),
        ("Dialogue editing", 4),
        ("Mix Dolby Atmos", 5),
        ("ProRes deliverables", 1),
    ],
    "doc_basic": [
        ("Color SDR", 5),
        ("Dialogue editing", 3),
        ("Mix surround 5.1", 3),
        ("ProRes deliverables", 1),
    ],
    "short_basic": [
        ("Color SDR", 2),
        ("Sound design", 2),
        ("DCP master IOP", 1),
    ],
    "series_episode": [
        ("Color SDR", 4),
        ("Sound design", 3),
        ("Mix surround 5.1", 3),
        ("VFX shot composito", 8),
        ("ProRes deliverables", 1),
    ],
    "spot_quick": [
        ("Color HDR Dolby Vision", 2),
        ("Sound design", 1),
        ("ProRes deliverables", 1),
    ],
}


def stage_quotes(db: Session) -> None:
    log.info("STAGE 2 — Quotazioni")
    today = date.today()
    items = _SEED_REGISTRY["items"]
    projects = _SEED_REGISTRY["projects"]
    clients = _SEED_REGISTRY["clients"]
    quote_counter = 0

    for proj_code, scenarios in QUOTE_SCENARIOS.items():
        proj = projects[proj_code]
        for sc_idx, (status_str, version_label, pkg_disc, template_key) in enumerate(scenarios):
            quote_counter += 1
            number = f"Q-2026-{quote_counter:03d}"
            q = db.query(Quote).filter(Quote.number == number).first()
            if not q:
                q = Quote(
                    tenant_id=1,
                    number=number,
                    project_id=proj.id,
                    client_id=proj.client_id,
                    title=proj.title,
                    status=QuoteStatus[status_str],
                    issue_date=today - timedelta(days=random.randint(15, 90)),
                    valid_until=today + timedelta(days=30),
                    package_discount=pkg_disc,
                    vat_rate=22.0,
                )
                db.add(q)
                db.flush()
                # Lines
                lines_template = LINE_TEMPLATES[template_key]
                sort_idx = 0
                for li_idx, (item_name, qty) in enumerate(lines_template):
                    pi = items.get(item_name)
                    if not pi:
                        issue(f"PriceItem '{item_name}' non trovato per quote {number}")
                        continue
                    sort_idx += 10
                    line = QuoteLine(
                        quote_id=q.id,
                        price_item_id=pi.id,
                        section="A",
                        position=f"A.{li_idx + 1}",
                        description=pi.name,
                        quantity=qty,
                        unit=pi.unit,
                        price_level=PriceLevel.list_price,
                        unit_price=pi.price_list,
                        total=qty * pi.price_list,
                        sort_order=sort_idx,
                    )
                    db.add(line)
                # Recompute via _recalc_quote
                db.flush()
                from app.routers.quotes import _recalc_quote
                _recalc_quote(q)
                cnt("quotes", 1)
                cnt(f"quote_status_{status_str}", 1)
        db.commit()

    log.info(f"  {quote_counter} quotazioni create con {sum(len(LINE_TEMPLATES[s[3]]) for sl in QUOTE_SCENARIOS.values() for s in sl)} righe totali")


# ─────────────────────────────────────────────────────────────
# Stage 3 — Job + booking
# ─────────────────────────────────────────────────────────────

def _create_job_and_jcl_from_quote(db: Session, q: Quote) -> Job:
    """Replica _create_job_from_quote di quotes.py (semplificato per simulation)."""
    proj = q.project
    base = (proj.code or f"P{proj.id}").strip()
    # Codice job progressivo
    existing = db.query(Job).filter(Job.project_id == proj.id).all()
    n = 1
    used = {jx.code for jx in existing if jx.code}
    while f"{base}-J{n}" in used:
        n += 1
    code = f"{base}-J{n}"
    j = Job(
        tenant_id=1,
        code=code,
        title=proj.title,
        project_id=proj.id,
        client_id=proj.client_id,
        quote_id=q.id,
        status=JobStatus.active,
        budget_quoted=q.total_after_discount or 0.0,
        start_date=q.issue_date,
        end_date=q.issue_date + timedelta(days=60),
    )
    db.add(j)
    db.flush()
    # JCL da QuoteLine
    for qline in q.lines:
        jcl = JobCostLine(
            tenant_id=1,
            job_id=j.id,
            quote_line_id=qline.id,
            price_item_id=qline.price_item_id,
            description=qline.description,
            quantity_quoted=qline.quantity,
            quantity_actual=0.0,
            unit=qline.unit,
            unit_price=qline.unit_price,
            total_quoted=qline.total or 0.0,
            total_accrued=0.0,
            total_expected=qline.total or 0.0,
        )
        db.add(jcl)
    db.flush()
    return j


def stage_jobs_bookings(db: Session) -> None:
    log.info("STAGE 3 — Job + booking con stati differenziati")
    resources = list(_SEED_REGISTRY["resources"].values())
    person_resources = [r for r in resources if r.type.value.startswith("person")]
    studio_resources = [r for r in resources if r.type == ResourceType.studio]

    # Crea job per le quote approved
    today = date.today()
    quotes_approved = db.query(Quote).filter(
        Quote.tenant_id == 1, Quote.status == QuoteStatus.approved,
    ).all()

    job_count = 0
    booking_count = 0
    booking_done = 0
    booking_in_progress = 0
    booking_planned = 0

    for q_idx, q in enumerate(quotes_approved):
        # Skip se job già esiste
        if q.job:
            j = q.job
        else:
            j = _create_job_and_jcl_from_quote(db, q)
            db.commit()
        job_count += 1

        # Status job differenziato
        # 0 → completed, 1-2 → in_progress, 3-4 → active, 5 → cancelled
        if q_idx == 0:
            j.status = JobStatus.completed
        elif q_idx == 5:
            j.status = JobStatus.cancelled
        elif q_idx < 4:
            j.status = JobStatus.active
        else:
            j.status = JobStatus.active

        # Skip booking per cancelled
        if j.status == JobStatus.cancelled:
            continue

        # Crea ~6-12 booking distribuiti su giorni passati e futuri
        n_bookings = random.randint(6, 12)
        # Base date 30gg fa per i primi job, +7gg per gli altri
        if q_idx == 0:
            base = today - timedelta(days=60)
        elif q_idx < 3:
            base = today - timedelta(days=20)
        else:
            base = today - timedelta(days=5)

        # Determina set di JCL del job
        jcls = list(j.cost_lines)
        if not jcls:
            continue

        for bk_idx in range(n_bookings):
            jcl = random.choice(jcls)
            day_offset = bk_idx * random.choice([1, 2, 2, 3])
            start_d = base + timedelta(days=day_offset)
            # Skip weekend (semplificazione)
            if start_d.weekday() >= 5:
                start_d += timedelta(days=2)
            start_dt = datetime.combine(start_d, datetime.min.time().replace(hour=9))
            duration_hours = random.choice([4, 8])
            end_dt = start_dt + timedelta(hours=duration_hours)
            # Pausa pranzo: se 8h, divide 9-13 + 14-18
            if duration_hours == 8:
                end_dt = start_dt + timedelta(hours=4)  # 9-13 morning
            # Selezione risorse
            n_resources = random.choice([1, 1, 1, 2])
            chosen_res = random.sample(person_resources, n_resources)
            # Status execution differenziato in base alla data
            if start_dt.date() < today - timedelta(days=2):
                exec_status = random.choices(
                    [BookingExecutionStatus.done, BookingExecutionStatus.not_done],
                    weights=[0.85, 0.15],
                )[0]
                state = BookingState.done if exec_status == BookingExecutionStatus.done else BookingState.not_done
                booking_status = BookingStatus.confirmed
            elif start_dt.date() == today:
                exec_status = BookingExecutionStatus.in_progress
                state = BookingState.in_progress
                booking_status = BookingStatus.confirmed
            elif start_dt.date() < today + timedelta(days=14):
                exec_status = BookingExecutionStatus.planned
                state = BookingState.confirmed
                booking_status = BookingStatus.confirmed
            else:
                exec_status = BookingExecutionStatus.planned
                state = BookingState.tentative
                booking_status = BookingStatus.tentative

            b = Booking(
                tenant_id=1,
                job_id=j.id,
                job_cost_line_id=jcl.id,
                kind=BookingKind.project,
                start_datetime=start_dt,
                end_datetime=end_dt,
                status=booking_status,
                execution_status=exec_status,
                state=state,
                priority=BookingPriority.normal,
                count_in_costs=(exec_status != BookingExecutionStatus.not_done),
                notes=f"Auto-gen #{bk_idx} sim",
            )
            db.add(b)
            db.flush()
            for r in chosen_res:
                ass = BookingAssignment(
                    booking_id=b.id,
                    resource_id=r.id,
                    start_datetime=start_dt,
                    end_datetime=end_dt,
                )
                db.add(ass)
            booking_count += 1
            if state == BookingState.done:
                booking_done += 1
            elif state == BookingState.in_progress:
                booking_in_progress += 1
            elif state in (BookingState.confirmed, BookingState.tentative):
                booking_planned += 1
        db.commit()

    cnt("jobs", job_count)
    cnt("bookings_total", booking_count)
    cnt("bookings_done", booking_done)
    cnt("bookings_in_progress", booking_in_progress)
    cnt("bookings_planned", booking_planned)
    log.info(f"  {job_count} job, {booking_count} booking ({booking_done} done, "
             f"{booking_in_progress} in_progress, {booking_planned} planned/tentative)")

    # Forza recompute cost-line per tutti i job
    from app.services.cost_line_sync import recompute_for_job
    for j in db.query(Job).filter(Job.tenant_id == 1).all():
        try:
            recompute_for_job(db, j.id)
        except Exception as e:
            issue(f"recompute_for_job({j.code}) failed: {e}")
    db.commit()
    log.info(f"  cost-line recompute applicato a tutti i job")


# ─────────────────────────────────────────────────────────────
# Stage 4 — Fatture + billing batch
# ─────────────────────────────────────────────────────────────

def stage_invoices(db: Session) -> None:
    log.info("STAGE 4 — Fatture + JCLBilledSlice")
    today = date.today()
    completed_jobs = db.query(Job).filter(
        Job.tenant_id == 1, Job.status == JobStatus.completed,
    ).all()
    active_jobs = db.query(Job).filter(
        Job.tenant_id == 1, Job.status == JobStatus.active,
    ).limit(3).all()

    invoice_count = 0
    slice_count = 0

    # Fattura per il job completed (paid)
    for j in completed_jobs:
        inv_n = f"INV-2026-{invoice_count + 1:04d}"
        invoice_count += 1
        inv = Invoice(
            number=inv_n,
            client_id=j.client_id,
            job_id=j.id,
            issue_date=today - timedelta(days=30),
            due_date=today - timedelta(days=0),
            status=InvoiceStatus.paid,
            vat_rate=22.0,
            subtotal=j.budget_quoted,
            total=j.budget_quoted * 1.22,
            notes="Saldo finale (sim) — pagata 5gg fa",
        )
        db.add(inv)
        db.flush()
        # InvoiceLine + JCLBilledSlice per ogni JCL
        for jcl in j.cost_lines:
            il = InvoiceLine(
                invoice_id=inv.id,
                description=jcl.description,
                quantity=jcl.quantity_quoted,
                unit_price=jcl.unit_price,
                total=jcl.total_quoted,
            )
            db.add(il)
            sl = JCLBilledSlice(
                tenant_id=1,
                job_cost_line_id=jcl.id,
                period_start=j.start_date,
                period_end=j.end_date or today,
                billed_amount=jcl.total_quoted,
                invoice_id=inv.id,
            )
            db.add(sl)
            jcl.billing_status = JCLBillingStatus.paid
            slice_count += 1
        db.commit()

    # 1 batch in approval (sent invoice ma not paid)
    if active_jobs:
        j = active_jobs[0]
        bb = BillingBatch(
            tenant_id=1,
            code=f"BB-2026-001",
            project_id=j.project_id,
            status=BillingBatchStatus.approved,
            period_start=today - timedelta(days=20),
            period_end=today,
            notes="Batch primo stato avanzamento",
        )
        db.add(bb)
        db.flush()
        # Aggiungi alcune JCL (snapshot fields)
        for jcl in j.cost_lines[:3]:
            qty = jcl.quantity_actual or jcl.quantity_quoted
            tot = qty * jcl.unit_price
            bbl = BillingBatchLine(
                batch_id=bb.id,
                job_cost_line_id=jcl.id,
                description=jcl.description,
                quantity=qty,
                unit=jcl.unit,
                unit_price=jcl.unit_price,
                total_proposed=tot,
                total_approved=tot,
            )
            db.add(bbl)
            jcl.billing_status = JCLBillingStatus.in_batch
        db.commit()
        cnt("billing_batches", 1)
        log.info(f"  batch BB-2026-001 (approved) per progetto {j.project.code}")

    # Cancelled invoice (test)
    if active_jobs:
        j = active_jobs[1] if len(active_jobs) > 1 else active_jobs[0]
        inv = Invoice(
            number=f"INV-2026-{invoice_count + 1:04d}",
            client_id=j.client_id,
            job_id=j.id,
            issue_date=today - timedelta(days=10),
            status=InvoiceStatus.cancelled,
            vat_rate=22.0,
            subtotal=1000.0,
            total=1220.0,
            notes="Annullata per cambio scope (sim)",
        )
        db.add(inv)
        invoice_count += 1
        db.commit()

    cnt("invoices", invoice_count)
    cnt("slices_billed", slice_count)
    log.info(f"  {invoice_count} fatture, {slice_count} slice billed (slice-lock attivi)")


# ─────────────────────────────────────────────────────────────
# Stage 5 — AIAction simulazione copilot
# ─────────────────────────────────────────────────────────────

def stage_ai_simulation(db: Session) -> None:
    log.info("STAGE 5 — Simulazione AIAction copilot")
    admin = db.query(User).filter(User.email == "admin@mediaflow.it").first()
    if not admin:
        issue("admin user non trovato per AIAction sim")
        return

    # Conversazione fittizia per le azioni
    conv = AIConversation(
        user_id=admin.id,
        title="Simulazione copilot scenarios",
    )
    db.add(conv)
    db.flush()

    today = date.today()
    actions_data = [
        # (action_type, status, payload_dict, applied_offset_days)
        ("propose_client", "applied", {
            "name": "Cattleya (sim)", "country": "Italia", "city": "Roma"
        }, -10),
        ("propose_client", "rejected", {
            "name": "Indigo Studios (rifiutato)"
        }, -8),
        ("propose_project", "applied", {
            "code": "AI-SIM-25", "title": "Progetto AI sim",
            "client_name": "Cattleya (sim)", "project_type": "feature_film"
        }, -7),
        ("propose_quote_line", "applied", {
            "quote_number": "Q-2026-001",
            "description": "Color HDR aggiunta da AI",
            "quantity": 2, "unit": "day", "unit_price": 1500
        }, -5),
        ("propose_quote_line", "proposed", {
            "quote_number": "Q-2026-005",
            "description": "Voce in attesa",
            "quantity": 1, "unit": "lump", "unit_price": 800
        }, None),
        ("propose_price_item", "applied", {
            "name": "QC fast (sim)", "category_name": "MASTERING",
            "unit": "lump", "price_list": 250
        }, -3),
        ("propose_new_item_and_line", "applied", {
            "quote_number": "Q-2026-003",
            "name": "Foley editing extra (sim)",
            "category_name": "AUDIO", "unit": "day", "price_list": 600,
            "quantity": 1
        }, -2),
        ("propose_resource", "rejected", {
            "name": "Sala video aggiuntiva (sim)", "type": "studio",
            "department_name": "DI"
        }, -4),
        ("propose_booking", "applied", {
            "job_code": "MOON25-J1",
            "assignments": [
                {"resource_name": "Luca Bianchi", "start_datetime": "2026-05-15T09:00:00",
                 "end_datetime": "2026-05-15T13:00:00"}
            ]
        }, -1),
        ("propose_move_booking", "failed", {
            "booking_id": 999999, "shift_minutes": 60
        }, None),  # failed: booking non esiste
        ("analyze_conflicts", "applied", {}, -1),
        ("find_free_slots", "applied", {
            "duration_hours": 4, "resource_name": "Stefano Romano"
        }, -1),
        ("query_project_finance", "applied", {
            "project_code": "MOON25"
        }, -1),
        ("web_search", "applied", {
            "query": "Netflix delivery spec 2026"
        }, -2),
    ]

    count_by_status: dict[str, int] = {}
    for at, status, payload, applied_off in actions_data:
        a = AIAction(
            conversation_id=conv.id,
            user_id=admin.id,
            action_type=at,
            payload=json.dumps(payload),
            status=status,
        )
        if status in ("applied", "rejected", "failed"):
            a.applied_at = datetime.utcnow() + timedelta(days=applied_off if applied_off else -1)
            if status == "applied":
                a.result = json.dumps({"ok": True, "message": "Simulato OK"})
            elif status == "rejected":
                a.result = json.dumps({"reason": "user_rejected"})
            elif status == "failed":
                a.result = json.dumps({"error": "Booking #999999 non trovato"})
        db.add(a)
        count_by_status[status] = count_by_status.get(status, 0) + 1
    db.commit()

    cnt("ai_actions", len(actions_data))
    for k, v in count_by_status.items():
        cnt(f"ai_actions_{k}", v)
    log.info(f"  {len(actions_data)} AIAction simulate: {count_by_status}")

    # Simulate AI usage logs (per testare cost analytics)
    usage_data = [
        ("claude", "claude-sonnet-4-6", 4500, 800, 0, 0),
        ("claude", "claude-sonnet-4-6", 600, 200, 4400, 100),  # 2° turno con cache hit
        ("claude", "claude-sonnet-4-6", 500, 150, 4500, 0),
        ("claude", "claude-opus-4-7", 3200, 1200, 0, 0),
        ("openai", "gpt-4o", 5000, 900, 0, 0),
    ]
    from app.services.ai_provider import compute_cost_usd
    for prov, model, in_t, out_t, cache_r, cache_c in usage_data:
        cost = compute_cost_usd(model, input_tokens=in_t, output_tokens=out_t,
                                cache_read_tokens=cache_r, cache_create_tokens=cache_c)
        u = AIUsageLog(
            tenant_id=1,
            user_id=admin.id,
            conversation_id=conv.id,
            provider=prov,
            model=model,
            input_tokens=in_t,
            output_tokens=out_t,
            cache_read_tokens=cache_r,
            cache_create_tokens=cache_c,
            cost_usd=cost,
            call_kind="chat_with_tools",
            stop_reason="end_turn",
            duration_ms=random.randint(800, 3500),
            created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
        )
        db.add(u)
    db.commit()
    cnt("ai_usage_logs", len(usage_data))
    total_cost = sum(compute_cost_usd(model, input_tokens=in_t, output_tokens=out_t,
                                      cache_read_tokens=cache_r, cache_create_tokens=cache_c)
                     for _, model, in_t, out_t, cache_r, cache_c in usage_data)
    log.info(f"  {len(usage_data)} AIUsageLog, totale costo simulato: ${total_cost:.4f}")


# ─────────────────────────────────────────────────────────────
# Stage 6 — Verifica integrità + report
# ─────────────────────────────────────────────────────────────

def stage_verify(db: Session) -> None:
    log.info("STAGE 6 — Verifica integrità")

    # Check 1: tutti i Quote hanno tenant_id=1
    bad_q = db.query(Quote).filter(Quote.tenant_id != 1).count()
    if bad_q:
        issue(f"Quote con tenant_id ≠ 1: {bad_q}")
    else:
        log.info("  ✓ Quote tenant scope OK")

    # Check 2: tutti i Job hanno tenant_id=1
    bad_j = db.query(Job).filter(Job.tenant_id != 1).count()
    if bad_j:
        issue(f"Job con tenant_id ≠ 1: {bad_j}")
    else:
        log.info("  ✓ Job tenant scope OK")

    # Check 3: tutti i JobCostLine hanno tenant_id=1
    bad_jcl = db.query(JobCostLine).filter(JobCostLine.tenant_id != 1).count()
    if bad_jcl:
        issue(f"JCL con tenant_id ≠ 1: {bad_jcl}")
    else:
        log.info("  ✓ JCL tenant scope OK")

    # Check 4: nessun Booking orfano (job_id NULL ma kind=project)
    orphan = db.query(Booking).filter(
        Booking.kind == BookingKind.project, Booking.job_id.is_(None),
    ).count()
    if orphan:
        issue(f"Booking project orphans (no job_id): {orphan}")
    else:
        log.info("  ✓ Booking project sempre con job_id OK")

    # Check 5: nessun BookingAssignment con start ≥ end
    bad_ass = db.query(BookingAssignment).filter(
        BookingAssignment.start_datetime >= BookingAssignment.end_datetime,
    ).count()
    if bad_ass:
        issue(f"BookingAssignment con start ≥ end: {bad_ass}")
    else:
        log.info("  ✓ BookingAssignment time invariants OK")

    # Check 6: BookingState canonico ↔ status legacy
    desync = 0
    for b in db.query(Booking).filter(Booking.tenant_id == 1).all():
        if b.state == BookingState.cancelled and b.status != BookingStatus.cancelled:
            desync += 1
        if b.state == BookingState.tentative and b.status != BookingStatus.tentative:
            desync += 1
    if desync:
        issue(f"Booking state↔status desync: {desync}")
    else:
        log.info("  ✓ BookingState legacy sync OK")

    # Check 7: tutti i price item hanno tenant_id
    bad_pi = db.query(PriceItem).filter(PriceItem.tenant_id != 1).count()
    if bad_pi:
        issue(f"PriceItem con tenant_id ≠ 1: {bad_pi}")
    else:
        log.info("  ✓ PriceItem tenant scope OK")

    # Check 8: slice billed coerenti con periodo job
    bad_slices = 0
    for sl in db.query(JCLBilledSlice).filter(JCLBilledSlice.tenant_id == 1).all():
        if sl.period_end < sl.period_start:
            bad_slices += 1
    if bad_slices:
        issue(f"JCLBilledSlice con period_end < period_start: {bad_slices}")
    else:
        log.info("  ✓ JCLBilledSlice period invariants OK")

    # Check 9: AIAction con applied_at set per applied/rejected/failed
    bad_aa = db.query(AIAction).filter(
        AIAction.status.in_(["applied", "rejected"]), AIAction.applied_at.is_(None),
    ).count()
    if bad_aa:
        issue(f"AIAction applied/rejected senza applied_at: {bad_aa}")
    else:
        log.info("  ✓ AIAction applied_at coerente OK")

    # Check 10: Slice-lock test funzionale
    from app.services.booking_mutate import assert_slice_lock_safe, SliceLocked
    locked_jcl = db.query(JCLBilledSlice).first()
    if locked_jcl:
        # Simula booking dentro slice
        b_test = Booking(
            tenant_id=1,
            job_cost_line_id=locked_jcl.job_cost_line_id,
            kind=BookingKind.project,
            start_datetime=datetime.combine(locked_jcl.period_start, datetime.min.time()),
            end_datetime=datetime.combine(locked_jcl.period_end, datetime.max.time()),
            status=BookingStatus.confirmed,
            execution_status=BookingExecutionStatus.planned,
            state=BookingState.confirmed,
            priority=BookingPriority.normal,
        )
        try:
            assert_slice_lock_safe(db, b_test)
            issue("Slice-lock NON ha bloccato un booking dentro slice billed")
        except SliceLocked:
            log.info("  ✓ Slice-lock funzionale (blocca booking dentro slice billed)")


def stage_report(db: Session) -> None:
    log.info("STAGE 7 — Report")
    report_path = ROOT / "docs" / "SIMULATION_REPORT.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# Simulazione MediaFlow — report {ts}",
        "",
        "Dataset generato da `scripts/simulate_full.py` per test manuale + verifica affidabilità.",
        "",
        "## Counters",
        "",
        "| Entità | Count |",
        "|--------|-------|",
    ]
    for k, v in sorted(COUNTERS.items()):
        lines.append(f"| `{k}` | {v} |")

    lines += [
        "",
        "## Issue rilevate",
        "",
    ]
    if not ISSUES:
        lines.append("Nessuna. ✅")
    else:
        for i, msg in enumerate(ISSUES, 1):
            lines.append(f"{i}. ⚠️ {msg}")

    # Quick stats DB
    n_quotes = db.query(Quote).count()
    n_jobs = db.query(Job).count()
    n_bookings = db.query(Booking).filter(Booking.tenant_id == 1).count()
    n_invoices = db.query(Invoice).count()
    n_aiact = db.query(AIAction).count()
    n_usage = db.query(AIUsageLog).count()

    # Cost AI totale
    from sqlalchemy import func
    total_cost_usd = db.query(func.sum(AIUsageLog.cost_usd)).scalar() or 0.0

    lines += [
        "",
        "## Riepilogo DB",
        "",
        f"- Quote totali: **{n_quotes}** (vedi tabella `quote_status_*` sopra)",
        f"- Job totali: **{n_jobs}**",
        f"- Booking totali (tenant=1): **{n_bookings}**",
        f"- Invoice totali: **{n_invoices}**",
        f"- AIAction totali: **{n_aiact}**",
        f"- AIUsageLog totali: **{n_usage}** (costo simulato totale: **${total_cost_usd:.4f}**)",
        "",
        "## Cosa testare manualmente",
        "",
        "Login: **admin@mediaflow.it / admin**",
        "",
        "1. **Dashboard**: kpi conteggi corretti",
        "2. **/clients**: 4+ clienti (A24, MUBI, Vision, Sky + AI sim)",
        "3. **/projects**: 12+ progetti distribuiti",
        "4. **/quotes**: filtro per status (draft/sent/approved). Aprire una approved e verificare le righe importate da listino",
        "5. **/jobs/{id}**: per il primo job dovrebbe vedersi cost report con `total_accrued > 0` (booking done)",
        "6. **/planning**: timeline con ~80 booking colorati per stato (done/in_progress/planned/tentative). Light mode auto-on dovrebbe scattare",
        "7. **/cost-report**: kpi job + lista filtrabile",
        "8. **/finance**: 1+ fatture paid + 1 cancelled + 1 batch approved",
        "9. **/admin/cestino** (admin): vuoto (nessun soft-delete in seed)",
        "10. **AI usage**: `GET /ai/api/usage?period_days=30&by=model` deve ritornare 5 entry con cache hit ratio",
        "",
        "## Scenari per stress slice-lock",
        "",
        "Lo script crea 1+ JCLBilledSlice per il job completed (paid). Test:",
        "- Aprire la timeline e provare a spostare un booking dentro il periodo slice → 409",
        "- Stesso da copilot via `propose_move_booking` → ValueError catturato",
        "",
        "## Scenari per RBAC",
        "",
        "Login con utente non-admin (creare via /admin/users) e provare:",
        "- `POST /quotes/api` → 403 (richiede `edit_quotes`)",
        "- `POST /finance/api/invoices` → 403 (richiede `edit_invoices`)",
        "- `POST /pricelist/api/items` → 403 (richiede `edit_pricelist`)",
        "",
        "## Note tecniche",
        "",
        "- **Backup pre-simulation** in `db_snapshots/snapshot-presimulation-{ts}.db` (auto)",
        "- **Schema reset**: drop_all + create_all su tutte le tabelle Base",
        "- **Auto-migrate**: chiamato dopo create_tables (ALTER TABLE idempotenti per colonne aggiunte recentemente)",
        "",
        f"---",
        f"_Generato {ts} da `scripts/simulate_full.py` v1.0_",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"  Report → {report_path}")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", default=True,
                        help="Reset DB (default)")
    parser.add_argument("--keep", dest="reset", action="store_false",
                        help="Mantieni dati esistenti (additivo)")
    parser.add_argument("--no-ai", action="store_true",
                        help="Skip AIAction simulation")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.quiet:
        log.setLevel(logging.WARNING)

    t0 = time.time()
    log.info("═" * 60)
    log.info("MediaFlow Simulation v1.0 — START")
    log.info("═" * 60)

    stage_setup(reset=args.reset)
    db = SessionLocal()
    try:
        stage_clients_resources(db)
        stage_quotes(db)
        stage_jobs_bookings(db)
        stage_invoices(db)
        if not args.no_ai:
            stage_ai_simulation(db)
        stage_verify(db)
        stage_report(db)
    finally:
        db.close()

    dt = time.time() - t0
    log.info("═" * 60)
    log.info(f"DONE in {dt:.1f}s — {len(ISSUES)} issue rilevate")
    log.info("═" * 60)
    log.info("Counters:")
    for k, v in sorted(COUNTERS.items()):
        log.info(f"  {k:30s} = {v}")
    if ISSUES:
        log.warning(f"⚠️  {len(ISSUES)} issue:")
        for i, msg in enumerate(ISSUES, 1):
            log.warning(f"  {i}. {msg}")
    log.info("Report: docs/SIMULATION_REPORT.md")


if __name__ == "__main__":
    main()
