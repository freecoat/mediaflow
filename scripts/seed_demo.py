"""
MediaFlow — seed_demo.py (v3.5.0-alpha.66.8, listino lean 2026-Q3)

Crea database demo con:
- Tenant default
- 4 Reparti: DI-Video, VFX, Audio, Commercial
- Listino LEAN 2026-Q3 (43 voci) caricato dal preset
  `app/data/pricelist_presets/lean_2026q3_v1.json` (single source of truth
  condivisa con UI Listino → Snapshot). Riduzione del 46% dal legacy 79
  voci tramite accorpamento + descrizione modulare con placeholder.
  Aggiunge IMF/DPP/AS-11 broadcast moderno.
- Prezzo singolo per voce (List/Average/Low collassati: lo sconto a cascata
  riga + categoria + pacchetto sostituisce i tre livelli storici).
- Keywords inline per matching AI capitolato → voce.
- 2 clienti, 3 progetti, 1 quotazione approvata, 1 job attivo.

Per ripristinare il listino legacy completo (79 voci): UI → Listino →
📦 Snapshot → Preset built-in → "Preset: legacy_2026q2_full" → Ripristina.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from datetime import date, datetime, timedelta
from app.database import SessionLocal, create_tables
from app.models import (
    User, UserRole, Resource, ResourceType, Client, Job, JobStatus,
    Booking, BookingAssignment, BookingStatus, Timesheet, Invoice, InvoiceLine, InvoiceStatus,
    Tag, PriceCategory, PriceItem, PriceLevel, Quote, QuoteLine, QuoteStatus,
    JobResourceAssignment, JobCostLine,
    Project, ProjectStatus,
    Tenant, Department, DeliveryTemplate,
)
from app.services.auth import hash_password



# ── LISTINO GENERICO ──────────────────────────────────────────────────
#
# Il listino di default e' definito nel preset committato
#   app/data/pricelist_presets/lean_2026q3_v1.json (43 voci, schema 1.1)
# che e' single source of truth condivisa con la UI di Listino → Snapshot.
#
# Per modificare il listino di default: edita
#   scripts/build_lean_preset.py + ri-esegui per rigenerare il preset.
# ──────────────────────────────────────────────────────────────────────




DEFAULT_DEPARTMENTS = [
    ("DI-VIDEO", "DI / Video", "#6272f5", 10,
     "Digital Intermediate: dailies, conform, color grading, mastering DCP/DCDM, deliverables video, archive, QC"),
    ("VFX", "VFX / Finishing", "#a855f7", 20,
     "Visual Effects e finishing: compositing, 3D, matte painting, rotoscoping, paint"),
    ("AUDIO", "Audio", "#2ec4b6", 30,
     "Post-produzione audio: editing, mix, foley, ADR, deliverables sound, localization, doppiaggio"),
    ("COMMERCIAL", "Commercial / Produzione", "#f59e0b", 40,
     "Project management, coordinamento produzione, preventivazione, amministrazione"),
]


def seed():
    create_tables()
    db = SessionLocal()

    # ── 1. TENANT DEFAULT (idempotente — può esistere già da migrazioni) ──
    tenant = db.query(Tenant).filter(Tenant.id == 1).first()
    if tenant is None:
        tenant = Tenant(
            id=1,
            name="Default",
            slug="default",
            legal_name="Casa di Post-Produzione Demo S.r.l.",
            default_currency="EUR",
            default_vat_rate=22.0,
            default_language="it",
            onboarding_completed=False,
        )
        db.add(tenant); db.flush()

    # ── 2. UTENTI ─────────────────────────────────────────────
    admin = User(email="admin@mediaflow.it", full_name="Admin MediaFlow",
                 hashed_password=hash_password("admin123"), role=UserRole.admin)
    editor = User(email="editor@mediaflow.it", full_name="Luca Bianchi",
                  hashed_password=hash_password("editor123"), role=UserRole.staff)
    db.add_all([admin, editor]); db.flush()

    # ── 3. REPARTI ────────────────────────────────────────────
    departments = {}
    for code, name, color, sort_order, desc in DEFAULT_DEPARTMENTS:
        d = Department(
            tenant_id=1, code=code, name=name,
            color=color, sort_order=sort_order, description=desc,
        )
        db.add(d); db.flush()
        departments[code] = d

    # ── 4. LISTINO LEAN 2026-Q3 (v3.5.0-alpha.66.8) ────────────
    # Il listino di default per nuove installazioni viene caricato dal preset
    # `lean_2026q3_v1.json` in app/data/pricelist_presets/. Single source of
    # truth: lo stesso preset è esposto anche in UI (Listino → Snapshot →
    # Preset built-in) ed è il template che il PM applicherà a un tenant esistente
    # quando vorrà sostituire un listino legacy con quello scremato.
    from app.services import pricelist_snapshot as _plsnap
    payload = _plsnap.load_preset_payload("lean_2026q3_v1.json")
    stats = _plsnap.apply_snapshot_payload(
        db, tenant_id=1, payload=payload, mode="merge", auto_backup=False,
    )
    items_count = stats["items_created"] + stats["items_updated"]
    categories_count = stats["categories_created"] + stats["categories_updated"]
    db.flush()

    # ── 5. CLIENTI ────────────────────────────────────────────
    rai = Client(tenant_id=1, name="RAI Documentari", contact_name="Marco Ferretti",
                 contact_email="prod@rai.it", vat_number="IT00001000001")
    sky = Client(tenant_id=1, name="Sky Italia", contact_name="Laura Drenker",
                 contact_email="commissioning@sky.it", vat_number="IT00002000002")
    db.add_all([rai, sky]); db.flush()

    # ── 6. RISORSE ────────────────────────────────────────────
    di_id = departments["DI-VIDEO"].id
    audio_id = departments["AUDIO"].id

    luca = Resource(
        tenant_id=1, department_id=di_id,
        name="Luca Bianchi", role="Online Editor",
        type=ResourceType.person_internal,
        email="luca.bianchi@mediaflow.it", internal_phone="201",
        hourly_rate=75, daily_rate=600, color="#6272f5", user_id=editor.id,
    )
    sara = Resource(
        tenant_id=1, department_id=di_id,
        name="Sara Conti", role="Senior Colorist",
        type=ResourceType.person_internal,
        email="sara.conti@mediaflow.it", internal_phone="202",
        daily_rate=800, color="#2ec4b6",
    )
    davide = Resource(
        tenant_id=1, department_id=audio_id,
        name="Davide Moretti", role="Re-recording Mixer",
        type=ResourceType.person_freelance,
        email="davide.moretti@freelance.it", phone="+39 333 1234567",
        daily_rate=550, color="#a855f7",
    )
    studio_a = Resource(
        tenant_id=1, department_id=audio_id,
        name="Studio A — Mixing Stage", role="Sala mix Dolby Atmos certificata",
        type=ResourceType.studio,
        daily_rate=1800, color="#f43f5e",
    )
    db.add_all([luca, sara, davide, studio_a]); db.flush()

    # ── 7. DELIVERY TEMPLATE PLACEHOLDER ──────────────────────
    db.add(DeliveryTemplate(
        tenant_id=1,
        code="EXAMPLE-THEATRICAL",
        name="Esempio — Theatrical Feature 4K Dolby Vision",
        broadcaster="Generico",
        version="1.0",
        description="Template di riferimento per consegne theatrical 4K HDR. "
                    "I template reali verranno costruiti dai capitolati dei distributori "
                    "tramite import AI nella Fase 2.",
        video_specs={
            "codec": "ProRes 4444 XQ", "resolution": "3840x2160",
            "framerate": "23.98", "colorspace": "Rec 2020 / P3 D65",
            "transfer_function": "PQ", "aspect_ratio": "Original Aspect Ratio",
            "hdr": "Dolby Vision v2.9 + HDR10",
        },
        audio_specs={
            "format": "PCM 24bit 48kHz",
            "channels": [
                {"ch": 1, "label": "Stereo Left Total"},
                {"ch": 2, "label": "Stereo Right Total"},
                {"ch": 3, "label": "M&E Left"},
                {"ch": 4, "label": "M&E Right"},
                {"ch": 5, "label": "5.1 Left"},
                {"ch": 6, "label": "5.1 Right"},
                {"ch": 7, "label": "5.1 Center"},
                {"ch": 8, "label": "5.1 LFE"},
                {"ch": 9, "label": "5.1 Left Surround"},
                {"ch": 10, "label": "5.1 Right Surround"},
            ],
            "atmos": "Dolby Atmos opzionale (printmaster + M&E master)",
        },
        text_specs={
            "subtitle_format": "IMSC 1.1 (.ttml)",
            "closed_caption_format": "SCC, 32 chars/line max",
            "forced_narrative": "separato, non burnato",
        },
        head_format={
            "bars_tone_start": "00:57:50:00", "slate_start": "00:58:50:00",
            "black_start": "00:59:00:00", "program_start": "01:00:00:00",
        },
        textless_format={
            "position": "60s dopo end of program",
            "separator": "1s di nero tra elementi",
        },
        naming_convention={
            "pattern": "[Title]_UHD_HDR_FTR_[FPS]_[Resolution]_OAR_[AR]_[ColorSpace]_[YYYYMMDD].mov",
            "example": "MyFilm_UHD_HDR_FTR_2398fps_3840x2160_OAR_239_P3D65_20250115.mov",
        },
        archive_specs={
            "media": "LTO7 / LTO8 LTFS", "checksum": "MD5 obbligatorio",
            "deliverables": ["DCDM 16-bit XYZ TIFF", "Graded DPX", "Dolby Vision XML"],
        },
        metadata_requirements={
            "MaxFALL": "richiesto", "MaxCLL": "richiesto",
            "ISAN": "opzionale", "music_cue_sheet": "obbligatorio",
        },
        ai_generated=False,
        is_active=True,
    ))
    db.flush()

    # ── 8. PROGETTI ───────────────────────────────────────────
    today = date.today()

    project_mare = Project(
        tenant_id=1, code="P-2024-001", title="Mare Nostrum",
        client_id=rai.id, project_type="documentary",
        length_minutes=86, fps="24",
        shooting_format="ARRI Alexa 2.8K ProRes 4444",
        delivery_format="4K-DCI-Scope",
        director="Anna Moretti", producer="RAI Documentari",
        shoot_start=today - timedelta(days=180),
        shoot_end=today - timedelta(days=90),
        post_start=today - timedelta(days=60),
        delivery_deadline=today + timedelta(days=30),
        status=ProjectStatus.active,
        description="Documentario sulle rotte migratorie nel Mediterraneo. Finalizzazione DCP e mix 7.1 per distribuzione cinematografica.",
    )
    project_sky = Project(
        tenant_id=1, code="P-2024-002", title="Spot Istituzionale Sky",
        client_id=sky.id, project_type="spot",
        length_minutes=1.5, fps="25",
        delivery_format="HD 1080p25 ProRes",
        status=ProjectStatus.completed,
        description="Spot pubblicitario 90 secondi per campagna abbonamenti Sky Italia.",
        shoot_start=today - timedelta(days=100),
        delivery_deadline=today - timedelta(days=15),
    )
    project_serie = Project(
        tenant_id=1, code="P-2025-001", title="Città d'Arte",
        client_id=rai.id, project_type="series",
        length_minutes=50, fps="25",
        delivery_format="HD 1080p25",
        status=ProjectStatus.quoting,
        description="Serie documentaria in 6 episodi sulle città d'arte italiane patrimonio UNESCO.",
        shoot_start=today + timedelta(days=30),
        delivery_deadline=today + timedelta(days=240),
    )
    db.add_all([project_mare, project_sky, project_serie]); db.flush()

    # ── 9. QUOTAZIONE DEMO con voci dal nuovo listino ─────────
    quote = Quote(
        number="Q-P-2024-001-v1", version=1,
        project_id=project_mare.id, client_id=rai.id,
        title="Mare Nostrum — DCP & Sound Finishing",
        status=QuoteStatus.approved,
        issue_date=today - timedelta(days=45),
        valid_until=today - timedelta(days=15),
        production_material="ARRI Alexa 2.8K ProRes 4444",
        length_minutes=86, fps="24",
        delivery_format="4K-DCI-Scope",
        shooting_days=32,
        package_discount=-0.10, vat_rate=22,
        payment_terms="20% Project Start / 40% Grading / 40% Mix",
        notes="Termini generali di servizio si applicano. Spedizioni e trasferimenti a parte.",
    )
    db.add(quote); db.flush()

    # Helper: trova price item per nome
    def find_item(name):
        return db.query(PriceItem).filter(
            PriceItem.tenant_id == 1, PriceItem.name == name
        ).first()

    def ql(sort_idx, item_name, qty, detail=None, hc=0):
        item = find_item(item_name)
        if not item:
            raise ValueError(f"Voce listino non trovata: {item_name}")
        unit_price = item.price_list or 0
        total = round(qty * unit_price, 2)
        return QuoteLine(
            quote_id=quote.id, position=f"{sort_idx//10}.{sort_idx%10 or 1}",
            section="A", description=item.name, detail=detail,
            quantity=qty, unit=item.unit,
            price_level=PriceLevel.list_price, unit_price=unit_price,
            allowance=0, line_discount_pct=0, total=total,
            hardcosts=hc, sort_order=sort_idx,
            price_item_id=item.id,
        )

    # Quote demo aggiornata per voci lean (v3.5.0-alpha.66.8). Le specifiche
    # tecniche scendono in `detail` (descrizione di riga) anziché nel nome
    # della voce listino, secondo il pattern di descrizione modulare del lean.
    qlines = [
        ql(10,  "Online conform", 3, "4K, frame rate 24fps, sorgente Avid"),
        ql(20,  "Color grading SDR", 5, "4K Rec.709"),
        ql(30,  "Mastering DCP standard", 1, "INTEROP 4K, VF italiana 24fps, encryption KDM"),
        ql(40,  "Master ProRes 4444 XQ", 1, "UHD SDR Rec.709 — master archive e versions"),
        ql(50,  "Screener H.264 / H.265", 86, "H.264 1080p con watermark dinamico (security review)"),
        ql(60,  "Sound editorial day", 6, "Dialogue editing"),
        ql(70,  "Foley session", 2),
        ql(80,  "Re-recording mix surround", 8, "Mix theatrical 7.1", 500),
        ql(90,  "Surround printmaster / M&E", 2, "Printmaster 5.1 + M&E 5.1"),
        ql(100, "Manual QC", 1, "UHD/HDR con monitor Dolby Vision"),
        ql(110, "LTO LTFS archive", 4, "DPX graded — TB"),
        ql(120, "Production management", 25, "PM senior — coordinamento + scheduling"),
    ]
    for l in qlines: db.add(l)
    db.flush()

    # Calcolo subtotali (matematica coerente con _recalc_quote backend)
    subtotal_gross = sum(l.quantity * l.unit_price for l in qlines)
    quote.subtotal_gross = round(subtotal_gross, 2)
    quote.subtotal = round(subtotal_gross, 2)  # nessuno sconto riga/categoria nel demo
    after = subtotal_gross * (1 + quote.package_discount)
    quote.total_after_discount = round(after, 2)
    quote.total_with_vat = round(after * (1 + quote.vat_rate / 100), 2)

    # ── 10. JOB attivo derivato dalla quotazione ──────────────
    job = Job(code="2024-0041", title="Mare Nostrum — DCP & Sound Finishing",
              client_id=rai.id, project_id=project_mare.id,
              quote_id=quote.id, status=JobStatus.active,
              start_date=today - timedelta(days=30),
              end_date=today + timedelta(days=30),
              budget_quoted=quote.total_after_discount)
    db.add(job); db.flush()

    for res, role, days, rate in [(sara, "Colorist", 8, 800), (davide, "Re-recording Mixer", 15, 550), (studio_a, "Mixing Stage", 10, 1800)]:
        db.add(JobResourceAssignment(job_id=job.id, resource_id=res.id, role_in_project=role, planned_days=days, agreed_daily_rate=rate))

    for line in qlines:
        db.add(JobCostLine(
            job_id=job.id, quote_line_id=line.id, price_item_id=line.price_item_id,
            description=line.description, quantity_quoted=line.quantity,
            quantity_actual=line.quantity * 0.6, unit=line.unit,
            unit_price=line.unit_price, total_quoted=line.total,
            total_accrued=round(line.total * 0.6, 2),
            total_expected=round(line.total * 1.05, 2),
        ))

    def bk(resource, days_offset, hours=8):
        # v3.4.16+: Booking ha solo `start/end` di envelope; le risorse sono
        # tracciate in BookingAssignment. Genera entrambi.
        start = datetime.combine(today + timedelta(days=days_offset), datetime.min.time()).replace(hour=9)
        end = start + timedelta(hours=hours)
        b = Booking(
            job_id=job.id, start_datetime=start, end_datetime=end,
            status=BookingStatus.confirmed, tenant_id=1,
        )
        db.add(b); db.flush()
        db.add(BookingAssignment(
            booking_id=b.id, resource_id=resource.id,
            start_datetime=start, end_datetime=end,
        ))
        return b
    for b in [bk(sara,0), bk(sara,1), bk(davide,2,10), bk(studio_a,2,12), bk(davide,3,10)]: pass

    for i in range(1, 6):
        db.add(Timesheet(user_id=editor.id, job_id=job.id, work_date=today - timedelta(days=i),
                         hours=8, hourly_rate=75, is_billable=True, description="Conform & Grading"))

    inv = Invoice(number="2024-0016", client_id=rai.id, job_id=job.id, status=InvoiceStatus.sent,
                  issue_date=today - timedelta(days=5), due_date=today + timedelta(days=25),
                  subtotal=round(quote.total_after_discount * 0.2, 2), vat_rate=22,
                  total=round(quote.total_after_discount * 0.2 * 1.22, 2), notes="Acconto 20% Project Start")
    db.add(inv); db.flush()
    db.add(InvoiceLine(invoice_id=inv.id, description="Acconto 20% Project Start",
                       quantity=1, unit_price=inv.subtotal, total=inv.subtotal))

    # NB: il progetto Sky resta deliberatamente senza Job — è scenario di test
    # per il flusso "reverse" (v3.4.51): un booking sul progetto attiva il modal
    # "Crea job extra (progetto senza quotazione)". Prima della v3.4.51 c'era qui
    # un Job 2024-0042 con budget arbitrario 18000€: non più ammesso (un Job
    # senza quote non può avere valore commerciale dal nulla, deve nascere da
    # un booking che genera un JobCostLine extra).

    for t in ["raw","finale","client-delivery","broll","interview","dailies","grade","mix","dcp","vfx"]:
        db.add(Tag(name=t))

    db.commit(); db.close()

    print(f"✓ Seed v3.1 (listino generico Aprile 2026) completato")
    print(f"  - Tenant default")
    print(f"  - {len(DEFAULT_DEPARTMENTS)} reparti: DI-Video, VFX, Audio, Commercial")
    print(f"  - {items_count} voci listino in {categories_count} categorie (preset lean_2026q3_v1, mercato IT 2026)")
    print(f"  - 1 delivery template di esempio")
    print(f"  - 3 progetti (1 con quote→job, 1 senza job — scenario reverse-flow)")
    print(f"  - 1 quotazione approvata, 1 job (Mare Nostrum)")
    print()
    print("Credenziali:")
    print("  admin@mediaflow.it / admin123")
    print("  editor@mediaflow.it / editor123")


if __name__ == "__main__":
    seed()
