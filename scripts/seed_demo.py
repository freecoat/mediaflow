"""
MediaFlow — seed_demo.py (v3.1, listino generico Aprile 2026)

Crea database demo con:
- Tenant default
- 4 Reparti: DI-Video, VFX, Audio, Commercial
- LISTINO_GENERICO (~75 voci) — costruito sui pattern ricorrenti dei capitolati
  reali (A24, Vision, Fremantle, Sky, NBCU TechOps) + workflow standard
  di post-produzione. Prezzi orientativi mercato italiano 2026.
- Prezzo singolo per voce (List/Average/Low rimossi: lo sconto cascata
  riga + categoria + pacchetto sostituisce i tre livelli storici)
- Keywords inline per matching AI capitolato → voce
- 2 clienti, 3 progetti, 1 quotazione approvata, 1 job attivo
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


# ── LISTINO GENERICO (Aprile 2026) ────────────────────────────────────
#
# Schema record:
#   (nome, descrizione, unit_pre, unit, prezzo_eur, hardcost_eur, [keywords])
#
# Convenzioni:
# - "day" = 1 turno = 8 ore (configurabile via UI in fase di quotazione)
# - "pc" = pezzo / unità (es. 1 DCP, 1 deliverable file)
# - "min" = minuto del prodotto finale (per voci legate alla durata)
# - "TB" = unità di archiviazione/trasferimento
# - "shot" = singola lavorazione VFX
# - "version" = versione di mastering aggiuntiva (textless, alternative cuts)
# - "allow" = allowance / forfait
#
# Prezzi: orientativi mercato italiano 2026, da affinare per casa di post.
# ──────────────────────────────────────────────────────────────────────

LISTINO_GENERICO = {
    "DAILIES": {
        "department": "DI-VIDEO",
        "items": [
            ("Dailies sync + color + proxy", "Sincronizzazione audio, color base con LUT, transcoding proxy per editing", "per", "day", 450, None,
                ["dailies", "sync", "proxy", "ingest", "lut", "transcoding"]),
            ("Dailies QC", "Controllo qualità rushes, scarti tecnici, segnalazioni al set", "per", "day", 350, None,
                ["dailies", "qc", "review", "rushes"]),
            ("Dailies upload piattaforma review", "Upload su Frame.io, Pix, Aspera o equivalente con permessi e log", "just", "allow", 200, None,
                ["dailies", "upload", "frameio", "pix", "review"]),
            ("Camera card download e verifica MHL", "Offload card camera con generazione MHL/MD5 e backup ridondante", "per", "day", 280, None,
                ["cards", "ingest", "mhl", "md5", "verify", "offload"]),
        ],
    },
    "PICTURE / DI": {
        "department": "DI-VIDEO",
        "items": [
            ("Online conform 2K", "Conform 2K da EDL/AAF con riferimento offline, gestione VFX shots", "per", "day", 900, None,
                ["conform", "2k", "edl", "aaf", "online", "finishing"]),
            ("Online conform 4K", "Conform 4K da EDL/AAF con riferimento offline e gestione VFX", "per", "day", 1100, None,
                ["conform", "4k", "edl", "aaf", "online", "finishing"]),
            ("Color grading 2K SDR", "Sessione color grading 2K Rec.709 con colorist e sala certificata", "per", "day", 1500, None,
                ["color", "grading", "2k", "sdr", "rec709", "colorist", "di"]),
            ("Color grading 4K SDR", "Sessione color grading 4K Rec.709 con colorist e sala certificata", "per", "day", 1800, None,
                ["color", "grading", "4k", "sdr", "rec709", "colorist", "di"]),
            ("Color grading HDR Dolby Vision", "Sessione HDR P3 D65 PQ con monitor Dolby e generazione metadata Dolby Vision", "per", "day", 2200, None,
                ["hdr", "dolby", "vision", "grading", "p3", "pq", "metadata"]),
            ("HDR trim pass", "Trim pass aggiuntivo per target HDR (4000nit / 1000nit / 600nit / 100nit / Rec.709)", "per", "pc", 600, None,
                ["hdr", "trim", "dolby", "vision", "1000nit", "600nit", "100nit", "rec709"]),
            ("Versioning / textless creation", "Creazione versione textless o alternative cut con conform aggiuntivo", "per", "version", 400, None,
                ["textless", "version", "recompositing", "vf", "oar"]),
        ],
    },
    "MASTERING DCP / DCDM": {
        "department": "DI-VIDEO",
        "items": [
            ("DCP INTEROP 2K", "DCP 2K standard INTEROP con CPL, PKL, naming DCNC, 5.1 audio, encryption opzionale", "per", "pc", 700, None,
                ["dcp", "interop", "2k", "cinema", "distribution", "dcnc"]),
            ("DCP INTEROP 4K", "DCP 4K standard INTEROP con CPL, PKL, naming DCNC, 5.1 audio", "per", "pc", 900, None,
                ["dcp", "interop", "4k", "cinema", "distribution", "dcnc"]),
            ("DCP SMPTE 2K", "DCP 2K standard SMPTE con CPL, PKL, naming DCNC, audio 5.1/7.1", "per", "pc", 700, None,
                ["dcp", "smpte", "2k", "cinema"]),
            ("DCP SMPTE 4K", "DCP 4K standard SMPTE con CPL, PKL, naming DCNC, audio 5.1/7.1", "per", "pc", 900, None,
                ["dcp", "smpte", "4k", "cinema"]),
            ("DCP SMPTE Bv2.1 Dolby Vision/Atmos", "DCP SMPTE Bv2.1 con Dolby Vision XYZ TIFF e/o Dolby Atmos MXF", "per", "pc", 1500, None,
                ["dcp", "dolby", "vision", "atmos", "smpte", "bv2.1"]),
            ("DCDM 16-bit XYZ TIFF", "Digital Cinema Distribution Master 16-bit XYZ TIFF in rulli per archive", "per", "pc", 1200, None,
                ["dcdm", "xyz", "tiff", "16bit", "master", "archive"]),
            ("DCP encryption + KDM/DKDM", "Encryption DCP + generazione DKDM (validità lunga) o KDM per singola sala", "per", "pc", 100, None,
                ["kdm", "dkdm", "encryption", "key", "security"]),
            ("DCP Festival pass", "DCP dedicato per festival con specifiche differenti dal DCP distribuzione", "per", "pc", 500, None,
                ["dcp", "festival", "screening"]),
        ],
    },
    "DELIVERABLES VIDEO": {
        "department": "DI-VIDEO",
        "items": [
            ("ProRes 4444 XQ HD master", "Master ProRes 4444 XQ 1080p con head format completo (bars, slate, tone)", "per", "pc", 350, None,
                ["prores", "4444", "hd", "1080p", "master", "head", "slate"]),
            ("ProRes 4444 XQ UHD SDR master", "Master ProRes 4444 XQ UHD 3840x2160 Rec.709 con head format", "per", "pc", 500, None,
                ["prores", "4444", "uhd", "4k", "sdr", "rec709"]),
            ("ProRes 4444 XQ UHD HDR Dolby Vision", "Master ProRes 4444 XQ UHD P3 D65 PQ con sidecar Dolby Vision XML v2.9", "per", "pc", 700, None,
                ["prores", "hdr", "dolby", "vision", "p3", "pq", "sidecar"]),
            ("ProRes 422 HQ HD proxy", "Proxy ProRes 422 HQ 1080p per screener interni o broadcast", "per", "pc", 250, None,
                ["prores", "422", "hd", "proxy", "screener"]),
            ("ProRes 422 HQ UHD proxy", "Proxy ProRes 422 HQ UHD per screener", "per", "pc", 350, None,
                ["prores", "422", "uhd", "proxy"]),
            ("H.264 screener clean", "Export H.264 1080p15Mbps senza watermark né timecode burn", "per", "pc", 120, None,
                ["h264", "screener", "mp4", "preview", "clean"]),
            ("H.264 screener watermarked", "Export H.264 con watermark dinamico per security review", "per", "pc", 180, None,
                ["h264", "watermark", "security", "screener", "review"]),
            ("H.264 screener with timecode burn", "Export H.264 con timecode visibile a rulli, conform al DCP", "per", "pc", 150, None,
                ["h264", "timecode", "burn", "review"]),
            ("Textless ProRes", "Export ProRes textless backgrounds (titoli, end credits, lower thirds)", "per", "pc", 280, None,
                ["textless", "prores", "backgrounds", "credits"]),
        ],
    },
    "ARCHIVE / TRANSFER": {
        "department": "DI-VIDEO",
        "items": [
            ("LTO LTFS — Camera Original", "Archive camera original su nastri LTO7/8 LTFS con MD5", "per", "TB", 120, None,
                ["lto", "ltfs", "camera", "original", "archive", "md5"]),
            ("LTO LTFS — Graded DPX", "Archive sequenze DPX gradate su LTO7/8 LTFS, una bobina per nastro", "per", "TB", 150, None,
                ["lto", "ltfs", "dpx", "graded", "di", "archive"]),
            ("LTO LTFS — Non-graded DPX", "Archive sequenze DPX non gradate (conform output) su LTO7/8 LTFS", "per", "TB", 130, None,
                ["lto", "ltfs", "dpx", "ungraded", "archive"]),
            ("LTO LTFS — Dolby Vision Master", "Archive Dolby Vision Master DPX/EXR/TIFF + sidecar XML", "per", "TB", 180, None,
                ["lto", "dolby", "vision", "dpx", "exr", "archive"]),
            ("LTO LTFS — ProRes Deliverables backup", "Archive di tutti i ProRes deliverables QC-approved", "per", "TB", 100, None,
                ["lto", "prores", "backup", "archive", "deliverables"]),
            ("Hard Drive USB 3.0 (1-2-4 TB)", "Drive consegna deliverables, USB 3.0 autoalimentato exFAT/NTFS", "per", "pc", 150, 80,
                ["usb", "hdd", "drive", "delivery", "exfat", "ntfs"]),
            ("CRU drive DCP (EXT3)", "CRU drive formattato EXT3 per consegna fisica DCP", "per", "pc", 180, 100,
                ["cru", "drive", "dcp", "ext3", "shipping"]),
            ("Mediashuttle / Aspera transfer", "Trasferimento elettronico via Signiant/Aspera fino a soglia per TB", "per", "TB", 80, None,
                ["signiant", "mediashuttle", "aspera", "transfer", "upload"]),
            ("MD5 / checksum generation", "Generazione e verifica checksum MD5 / xxHash su deliverables/archive", "just", "allow", 150, None,
                ["md5", "xxhash", "checksum", "hash", "verify"]),
        ],
    },
    "VFX": {
        "department": "VFX",
        "items": [
            ("VFX shot composite — standard", "Composite VFX standard: cleanup, screen replacement, semplici comp", "per", "shot", 450, None,
                ["vfx", "composite", "shot", "comp", "cleanup"]),
            ("VFX shot composite — complex", "Composite VFX complesso: hero shot, multi-layer, integrazione 3D", "per", "shot", 1200, None,
                ["vfx", "complex", "hero", "comp", "3d"]),
            ("VFX plates pull / handles export", "Estrazione plates da DI con maniglie configurabili per VFX vendor", "just", "allow", 600, None,
                ["vfx", "plates", "pull", "handles", "export"]),
            ("Title design / motion graphics", "Sessione design titoli, lower thirds, end roller, motion graphics", "per", "day", 1100, None,
                ["titles", "motion", "graphics", "opening", "credits", "lower thirds"]),
            ("Rotoscoping", "Rotoscoping per shot (mask, isolation, holdouts)", "per", "shot", 350, None,
                ["roto", "rotoscope", "mask", "isolation"]),
            ("Paint / cleanup / stabilization", "Lavorazione paint, cleanup wire/rig, stabilizzazione shot per shot", "per", "shot", 280, None,
                ["paint", "cleanup", "stabilize", "beauty", "rig", "wire"]),
        ],
    },
    "SOUND EDIT": {
        "department": "AUDIO",
        "items": [
            ("Sound editorial dialogue", "Dialog editing in Pro Tools, ricostruzione tracce, edit-room", "per", "day", 750, None,
                ["dialogue", "edit", "audio", "protools"]),
            ("Sound design / FX editing", "Sound design e FX editing con sound designer e libreria", "per", "day", 750, None,
                ["sfx", "sound", "design", "fx", "editor"]),
            ("Foley session", "Registrazione foley con artist, engineer e sala foley", "per", "day", 900, None,
                ["foley", "recording", "footsteps", "props"]),
            ("ADR session", "Sessione ADR con sound engineer, sala ADR e direttore", "per", "day", 1100, None,
                ["adr", "looping", "dub", "recording", "vocal"]),
            ("Music editing", "Music editor in postazione Pro Tools, gestione cue e stems", "per", "day", 700, None,
                ["music", "edit", "score", "cue", "stems"]),
        ],
    },
    "MIX": {
        "department": "AUDIO",
        "items": [
            ("Re-recording mix 5.1", "Mix theatrical 5.1 con re-recording mixer e sala certificata", "per", "day", 1800, 500,
                ["mix", "5.1", "surround", "rerecord", "theater"]),
            ("Re-recording mix 7.1", "Mix theatrical 7.1 con re-recording mixer e sala certificata", "per", "day", 2100, 500,
                ["mix", "7.1", "surround", "theater"]),
            ("Re-recording mix Dolby Atmos", "Mix immersivo Dolby Atmos con sala certificata e renderer", "per", "day", 2800, 800,
                ["atmos", "dolby", "immersive", "mix", "renderer"]),
            ("Mix theater rental", "Affitto sala mix certificata (Dolby) — solo struttura, no mixer", "per", "day", 900, None,
                ["theater", "dub", "stage", "room", "rental"]),
        ],
    },
    "DELIVERABLES SOUND": {
        "department": "AUDIO",
        "items": [
            ("5.1 Printmaster", "Printmaster 5.1 conform DCP, head format completo, 24/25 fps", "per", "pc", 600, None,
                ["5.1", "printmaster", "mix", "master"]),
            ("5.1 M&E", "Music & Effects 5.1 per doppiaggio internazionale", "per", "pc", 600, None,
                ["5.1", "me", "music", "effects", "international"]),
            ("5.1 DME stems", "Dialogue/Music/Effects stems separati 5.1", "per", "pc", 750, None,
                ["5.1", "dme", "dialogue", "music", "effects", "stems"]),
            ("7.1 Printmaster", "Printmaster 7.1 conform DCP", "per", "pc", 750, None,
                ["7.1", "printmaster"]),
            ("Atmos ADM BWF master", "Master Dolby Atmos ADM BWF immersivo + renderer config", "per", "pc", 1200, None,
                ["atmos", "adm", "bwf", "immersive", "dolby"]),
            ("Stereo LtRt fold-down", "Fold-down stereo Lt/Rt da 5.1/7.1, conform al DCP", "per", "pc", 350, None,
                ["stereo", "ltrt", "fold", "downmix"]),
            ("Audio description recording IT", "Registrazione audiodescrizione italiana con narratore e mix", "per", "min", 18, None,
                ["audiodescription", "ad", "accessibility", "narrator"]),
            ("Audio description script IT", "Stesura script audiodescrizione conforme alle linee guida", "per", "pc", 350, None,
                ["ad", "script", "audiodescription", "italiano"]),
        ],
    },
    "LOCALIZATION": {
        "department": "AUDIO",
        "items": [
            ("Subtitle translation EN→IT", "Traduzione sottotitoli inglese → italiano con QC linguistico", "per", "min", 15, None,
                ["subtitle", "translation", "italian", "spotting"]),
            ("Subtitle translation IT→EN", "Traduzione sottotitoli italiano → inglese con QC linguistico", "per", "min", 18, None,
                ["subtitle", "translation", "english", "spotting"]),
            ("Subtitle conformance multi-format", "Conformance sottotitoli a IMSC/STL/SRT/iTT/TimedText XML INTEROP-SMPTE", "per", "pc", 280, None,
                ["imsc", "stl", "srt", "itt", "timedtext", "subtitle", "conform"]),
            ("SDH closed caption authoring", "Authoring SDH/CC per non udenti, 32 char/line standard", "per", "pc", 450, None,
                ["sdh", "cc", "deaf", "accessibility", "closed", "caption"]),
            ("Forced subtitle creation", "Creazione sottotitoli forzati narrativi (lingue straniere in scena)", "per", "pc", 280, None,
                ["forced", "subtitle", "narrative", "burn"]),
            ("Dubbing direction + recording", "Sessione doppiaggio con direttore, attori, fonico, sala", "per", "day", 1500, 200,
                ["dub", "dubbing", "voiceover", "loop"]),
        ],
    },
    "QC / METADATA": {
        "department": "DI-VIDEO",
        "items": [
            ("Manual QC HD/SDR", "Visione integrale operatore QC con report tecnico (artefatti, audio, sub)", "per", "pc", 280, None,
                ["qc", "manual", "review", "hd", "sdr"]),
            ("Manual QC UHD/HDR", "QC manuale UHD/HDR con monitor Dolby Vision e analisi metadata", "per", "pc", 450, None,
                ["qc", "manual", "uhd", "hdr", "review", "dolby"]),
            ("Auto-QC Baton/Vidcheck", "QC automatico Baton/Vidcheck/Aurora con report XML", "per", "pc", 120, None,
                ["baton", "vidcheck", "aurora", "autoqc", "automated"]),
            ("Metadata XML / TechOps template", "Compilazione metadata XML Sky/RAI/NBCU TechOps/IMF/IMSC", "per", "pc", 280, None,
                ["metadata", "xml", "techops", "gtm", "sidecar", "imf"]),
            ("Music Cue Sheet preparation", "Compilazione Music Cue Sheet con autori, editori, ISWC", "per", "pc", 350, None,
                ["cue", "sheet", "music", "rights", "iswc"]),
        ],
    },
    "PROJECT MANAGEMENT": {
        "department": "COMMERCIAL",
        "items": [
            ("Project Management", "Project manager dedicato: coordinamento, scheduling, deliverables tracking", "per", "day", 700, None,
                ["project", "manager", "pm", "coordination", "tracking"]),
            ("Production Coordination", "Production coordinator: liaison con vendor, calendari, materiali", "per", "day", 450, None,
                ["coordinator", "production", "tpr", "liaison"]),
            ("Quote / estimate preparation", "Preparazione quotazione con analisi capitolato e stima risorse", "per", "pc", 450, None,
                ["quote", "estimate", "bid", "preventivo"]),
            ("Travel / shipping allowance", "Forfait spese di trasferimento personale e shipping deliverables", "just", "allow", 350, None,
                ["travel", "shipping", "courier", "transfer"]),
        ],
    },
}


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

    # ── 4. LISTINO GENERICO ───────────────────────────────────
    cat_objs = {}
    items_count = 0
    for idx, (cat_name, cat_data) in enumerate(LISTINO_GENERICO.items()):
        cat = PriceCategory(
            tenant_id=1, name=cat_name, sort_order=(idx + 1) * 10,
        )
        db.add(cat); db.flush()
        cat_objs[cat_name] = cat
        dept_code = cat_data["department"]
        dept_id = departments[dept_code].id

        for (name, desc, unit_pre, unit, price, hardcost, keywords) in cat_data["items"]:
            db.add(PriceItem(
                tenant_id=1,
                category_id=cat.id,
                department_id=dept_id,
                name=name, description=desc,
                unit=unit, unit_pre=unit_pre,
                # Prezzo singolo: list/average/low collassati. Lo sconto a cascata
                # (riga + categoria + pacchetto) sostituisce i tre livelli storici.
                price_list=price,
                price_average=None,
                price_low=None,
                hardcosts=hardcost,
                keywords=keywords,
            ))
            items_count += 1
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

    qlines = [
        ql(10,  "Online conform 4K", 3),
        ql(20,  "Color grading 4K SDR", 5),
        ql(30,  "DCP INTEROP 4K", 1, "VF italiana, INTEROP 24fps"),
        ql(40,  "DCP encryption + KDM/DKDM", 1),
        ql(50,  "ProRes 4444 XQ UHD SDR master", 1, "Master per archive e versions"),
        ql(60,  "H.264 screener watermarked", 86),
        ql(70,  "Sound editorial dialogue", 6),
        ql(80,  "Foley session", 2),
        ql(90,  "Re-recording mix 7.1", 8, "Mix theatrical 7.1", 500),
        ql(100, "5.1 Printmaster", 1),
        ql(110, "5.1 M&E", 1),
        ql(120, "Manual QC UHD/HDR", 1),
        ql(130, "LTO LTFS — Graded DPX", 4),
        ql(140, "Project Management", 25),
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

    db.add(Job(code="2024-0042", title="Spot istituzionale Sky",
               client_id=sky.id, project_id=project_sky.id,
               status=JobStatus.invoiced, start_date=today - timedelta(days=90),
               end_date=today - timedelta(days=10), budget_quoted=18000))

    for t in ["raw","finale","client-delivery","broll","interview","dailies","grade","mix","dcp","vfx"]:
        db.add(Tag(name=t))

    db.commit(); db.close()

    print(f"✓ Seed v3.1 (listino generico Aprile 2026) completato")
    print(f"  - Tenant default")
    print(f"  - {len(DEFAULT_DEPARTMENTS)} reparti: DI-Video, VFX, Audio, Commercial")
    print(f"  - {items_count} voci listino in {len(LISTINO_GENERICO)} categorie (prezzi mercato IT 2026)")
    print(f"  - 1 delivery template di esempio")
    print(f"  - 3 progetti, 1 quotazione approvata, 1 job attivo")
    print()
    print("Credenziali:")
    print("  admin@mediaflow.it / admin123")
    print("  editor@mediaflow.it / editor123")


if __name__ == "__main__":
    seed()
