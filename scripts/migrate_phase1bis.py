"""
MediaFlow — migrazione schema v2 → v3 (Fase 1-bis)

Aggiunge:
  - Tabella `tenants` (multi-tenant soft, default tenant_id=1)
  - Tabella `departments` (reparti trasversali)
  - Tabella `delivery_templates` (capitolati strutturati)
  - Colonna `tenant_id` a: clients, projects, price_categories, price_items, resources
  - Colonna `department_id` a: price_items, resources
  - Colonna `keywords` a: price_items
  - Colonne `role`, `email`, `phone`, `internal_phone` a: resources

Esegue la mappatura di default:
  - Crea tenant "default"
  - Crea 4 reparti: DI-Video, VFX, Audio, Commercial
  - Mappa le 10 categorie TPR sui reparti
  - Popola le keywords delle 76 voci TPR in modo sensato

Esegui una sola volta dopo l'aggiornamento:
  python scripts/migrate_phase1bis.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from app.database import SessionLocal, engine, create_tables
from app.models import Tenant, Department, PriceItem, PriceCategory, Resource


# Mappatura categorie TPR → codice reparto
CATEGORY_TO_DEPARTMENT = {
    "PICTURE": "DI-VIDEO",
    "MASTERING": "DI-VIDEO",
    "DELIVERABLES DCI": "DI-VIDEO",
    "DAILIES": "DI-VIDEO",
    "ARCHIVE": "DI-VIDEO",
    "TRANSFER": "DI-VIDEO",
    "MATERIALS": "DI-VIDEO",
    "VFX": "VFX",
    "SOUND": "AUDIO",
    "DELIVERABLES SOUND": "AUDIO",
}

# Keywords per le 76 voci TPR, indicizzate per nome (match esatto)
# Valori: lista di parole chiave italiane + inglesi per matching AI
KEYWORDS_MAP = {
    # PICTURE
    "2K Picture Conform on FilmMaster": ["conform", "2k", "edl", "filmmaster", "montaggio"],
    "4K Picture Conform on FilmMaster": ["conform", "4k", "edl", "filmmaster", "montaggio"],
    "2K Colour Grading on Nucoda Film Master": ["color", "grading", "2k", "nucoda", "colorist", "d.i.", "di"],
    "4K Colour Grading on Nucoda Film Master": ["color", "grading", "4k", "nucoda", "colorist", "d.i.", "di"],
    "Pull VFX Plates (over 10 Shots)": ["vfx", "plates", "pull", "shots"],
    "QT H264 generation from DI Data": ["h264", "quicktime", "mov", "screener", "preview"],
    "QT H264 watermarked from DI Data": ["h264", "watermark", "screener", "quicktime", "preview"],
    "QT ProRes HD 444/422 from DI Data": ["prores", "quicktime", "hd", "mov"],
    # MASTERING (DCP)
    "4K DCP Mastering VF": ["dcp", "4k", "mastering", "cinema", "interop", "smpte"],
    "2K DCP Mastering VF": ["dcp", "2k", "mastering", "cinema", "interop", "smpte"],
    "4K DCDM Mastering from 2K DPX": ["dcdm", "4k", "dpx", "archive", "master"],
    "2K DCDM Mastering from 2K DPX": ["dcdm", "2k", "dpx", "archive", "master"],
    "Generation of DKDM": ["dkdm", "key", "cinema"],
    "KDM Generation": ["kdm", "key", "cinema"],
    "4K DCP Mastering from 2K DPX": ["dcp", "4k", "dpx", "mastering", "cinema"],
    "2K DCP Mastering from 2K DPX": ["dcp", "2k", "dpx", "mastering", "cinema"],
    # DELIVERABLES DCI
    "DCP Copy incl. Cru Drive & PeliCase": ["dcp", "copy", "cru", "delivery", "cinema"],
    "DCP Copy incl. USB HDD 500GB": ["dcp", "copy", "usb", "hdd", "delivery"],
    "DCP Upload per FTP": ["dcp", "ftp", "upload", "delivery"],
    "2K DCDM Copy incl. HDD": ["dcdm", "copy", "hdd", "archive"],
    "4K DCDM Copy incl. HDD": ["dcdm", "copy", "hdd", "archive"],
    "2K DCP Rewrap from existing DCP": ["dcp", "rewrap", "cpl"],
    "Pan & Scan Session 16:9/4:3": ["pan", "scan", "aspect", "reformat"],
    # SOUND
    "Original Sound Check": ["sound", "check", "dialog", "rerecording", "mixer"],
    "Foley Recording": ["foley", "recording", "sound", "sfx"],
    "Foley Editing": ["foley", "editing", "protools"],
    "Dialog / ADR Editing": ["dialog", "adr", "editing", "protools"],
    "Supervising Sounddesign / FX Editing": ["sounddesign", "sfx", "supervising", "protools"],
    "Pre-and Mainmix 7.1 or 5.1, M&E — Day Shift": ["mix", "mainmix", "premix", "7.1", "5.1", "m&e", "theatrical"],
    "Pre-and Mainmix 7.1 or 5.1, M&E — Late Shift": ["mix", "mainmix", "premix", "7.1", "5.1", "m&e", "theatrical", "late"],
    "Pre-and Mainmix Dolby Atmos, M&E — Day Shift": ["atmos", "dolby", "mix", "mainmix", "theatrical"],
    "Premix 5.1, M&E — Day Shift": ["premix", "5.1", "m&e", "theatrical"],
    "Premix 5.1, M&E — Late Shift": ["premix", "5.1", "m&e", "theatrical", "late"],
    "TV Mix 5.1 or 2.0": ["mix", "tv", "broadcast", "5.1", "stereo", "ebu"],
    "TV M&E/IT Mix 5.1 or 2.0": ["mix", "tv", "m&e", "broadcast", "ebu"],
    "Editors present at mix": ["editor", "mix", "assistance"],
    "Dolby Atmos Home Mastering for BluRay, M&E": ["atmos", "dolby", "bluray", "home", "mastering"],
    "ADR Recording": ["adr", "recording", "studio", "dialog"],
    "ADR Edit": ["adr", "editing", "protools"],
    # DELIVERABLES SOUND
    "2-track Printmaster/OV 24fps": ["printmaster", "stereo", "ov", "delivery", "audio"],
    "6-track Printmaster 24fps": ["printmaster", "5.1", "6-track", "delivery", "audio"],
    "6-track Stems 24fps": ["stems", "6-track", "5.1", "dme", "delivery"],
    "6-track TV Mix 25fps EBU128": ["tv", "mix", "6-track", "ebu", "broadcast", "25fps"],
    "6-track TV M&E Mix 25fps EBU128": ["tv", "m&e", "mix", "6-track", "ebu", "broadcast"],
    "Downmix Stereo DME from 6-track DME Stems": ["downmix", "stereo", "dme", "stems"],
    "ProTools Session D/M/E Stems/6-track Master/LtRt": ["protools", "session", "stems", "ltrt", "dme"],
    "Time Base conversion with Time Factory": ["timebase", "conversion", "framerate", "25fps", "24fps"],
    "Dolby E Encoding from existing 6 track": ["dolby e", "encoding", "6-track", "broadcast"],
    # VFX
    "VFX Supervisor On Set": ["vfx", "supervisor", "on set", "shooting"],
    "3D Artist": ["3d", "artist", "maya", "cinema4d"],
    "2D Artist": ["2d", "nuke", "afterfx", "compositing"],
    "3D Animator": ["3d", "animator", "maya", "animation"],
    "Matte Painter": ["matte", "painting", "painter", "digital"],
    "Rotoscoping": ["roto", "rotoscoping"],
    "Title Artist": ["title", "titling", "afterfx", "motion"],
    "VFX Producer": ["vfx", "producer", "supervisor"],
    "Front Title Sequence & End Roller": ["titles", "end roller", "front title", "credits"],
    # DAILIES
    "DigiLab Workstation, DaVinci Resolve, Mini Panel": ["dailies", "digilab", "davinci", "resolve", "on set"],
    "Digital Image Technician / Rushes Grader": ["dit", "rushes", "grader", "on set", "dailies"],
    "Digital Dailies Upload on MediaHub": ["dailies", "upload", "mediahub", "delivery"],
    "Avid Editing Suite": ["avid", "editing", "suite", "edit"],
    "Avid Assistant (day)": ["avid", "assistant", "day", "dailies"],
    "Avid Assistant (hr)": ["avid", "assistant", "hourly"],
    # ARCHIVE
    "Data Backup on LTO less than 10 TB": ["lto", "backup", "archive", "storage"],
    "Data Backup on LTO more than 10 TB": ["lto", "backup", "archive", "storage", "large"],
    # TRANSFER
    "FTP Services up to 500GB": ["ftp", "transfer", "upload", "delivery"],
    "Signiant Mediashuttle up to 1TB": ["signiant", "mediashuttle", "transfer", "delivery"],
    "Data Transfer / Upload allowance": ["transfer", "upload", "allowance"],
    # MATERIALS
    "USB Hard Drive 3.0 500GB": ["usb", "hdd", "500gb", "drive"],
    "USB Hard Drive 3.0 1TB": ["usb", "hdd", "1tb", "drive"],
    "USB Hard Drive 3.0 2TB": ["usb", "hdd", "2tb", "drive"],
    "CRU DRIVE 500GB": ["cru", "drive", "dcp"],
    "Pelicase": ["pelicase", "case", "shipping"],
    "LTO Tapes 6.25": ["lto", "tape", "archive", "media"],
    "DVD double layer": ["dvd", "media"],
    "BluRay Disc": ["bluray", "media", "disc"],
}


def table_exists(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def column_exists(table: str, column: str) -> bool:
    if not table_exists(table):
        return False
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · migrazione schema v2 → v3 (Fase 1-bis)")
    print("─" * 60)

    # 1. Crea tutte le tabelle mancanti
    create_tables()
    print("✓ create_all eseguito (tabelle nuove create se mancanti)")

    db = SessionLocal()
    try:
        # 2. Aggiungi colonne mancanti a tabelle esistenti
        alter_statements = [
            ("clients", "tenant_id", "INTEGER DEFAULT 1"),
            ("projects", "tenant_id", "INTEGER DEFAULT 1"),
            ("price_categories", "tenant_id", "INTEGER DEFAULT 1"),
            ("price_items", "tenant_id", "INTEGER DEFAULT 1"),
            ("price_items", "department_id", "INTEGER"),
            ("price_items", "keywords", "JSON"),
            ("resources", "tenant_id", "INTEGER DEFAULT 1"),
            ("resources", "department_id", "INTEGER"),
            ("resources", "role", "VARCHAR(100)"),
            ("resources", "email", "VARCHAR(255)"),
            ("resources", "phone", "VARCHAR(50)"),
            ("resources", "internal_phone", "VARCHAR(20)"),
        ]
        for table, col, ddl in alter_statements:
            if not column_exists(table, col):
                print(f"▸ ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                db.commit()

        # 3. Crea tenant di default se mancante
        default_tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not default_tenant:
            default_tenant = Tenant(
                id=1,
                name="Default",
                slug="default",
                default_currency="EUR",
                default_vat_rate=22.0,
                default_language="it",
                onboarding_completed=False,
            )
            db.add(default_tenant)
            db.commit()
            print("✓ Creato tenant default (id=1)")
        else:
            print("✓ Tenant default già esistente")

        # 4. Crea reparti di default se mancanti
        DEFAULT_DEPARTMENTS = [
            ("DI-VIDEO", "DI / Video", "#6272f5", 10,
             "Digital Intermediate: conform, color grading, mastering, DCP, deliverables video"),
            ("VFX", "VFX / Finishing", "#a855f7", 20,
             "Visual Effects e finishing: compositing, 3D, matte painting, rotoscoping"),
            ("AUDIO", "Audio", "#2ec4b6", 30,
             "Post-produzione audio: sound design, mix, foley, ADR, deliverables audio"),
            ("COMMERCIAL", "Commercial / Produzione", "#f59e0b", 40,
             "Produzione e coordinamento: project management, commerciale, amministrazione"),
        ]
        for code, name, color, sort_order, desc in DEFAULT_DEPARTMENTS:
            existing = db.query(Department).filter(
                Department.tenant_id == 1,
                Department.code == code
            ).first()
            if not existing:
                db.add(Department(
                    tenant_id=1, code=code, name=name,
                    color=color, sort_order=sort_order,
                    description=desc,
                ))
                print(f"  ✓ Creato reparto {code} — {name}")
        db.commit()

        # 5. Mappa le voci listino → reparto
        dept_map = {d.code: d.id for d in db.query(Department).filter(Department.tenant_id == 1).all()}
        updated_count = 0
        skipped_count = 0
        for item in db.query(PriceItem).all():
            cat = db.query(PriceCategory).filter(PriceCategory.id == item.category_id).first()
            if not cat:
                continue
            dept_code = CATEGORY_TO_DEPARTMENT.get(cat.name)
            if dept_code and item.department_id is None:
                item.department_id = dept_map.get(dept_code)
                updated_count += 1
            elif not dept_code:
                skipped_count += 1
        if updated_count:
            print(f"✓ Assegnato reparto a {updated_count} voci listino")
        if skipped_count:
            print(f"  (saltate {skipped_count} voci: categoria non mappata)")
        db.commit()

        # 6. Popola keywords per le voci note
        keyword_count = 0
        for item in db.query(PriceItem).all():
            if item.keywords is None and item.name in KEYWORDS_MAP:
                item.keywords = KEYWORDS_MAP[item.name]
                keyword_count += 1
        if keyword_count:
            print(f"✓ Popolate keywords per {keyword_count} voci listino")
        db.commit()

        # 7. Retrocompatibilità ResourceType: converti "person" → "person_internal"
        # per chi stava usando il vecchio enum. Lo facciamo in SQL grezzo perché
        # le risorse potrebbero non avere dati ma la colonna esisteva.
        try:
            result = db.execute(text("UPDATE resources SET type='person_internal' WHERE type='person'"))
            if result.rowcount:
                print(f"✓ Convertiti {result.rowcount} resources da 'person' a 'person_internal'")
            db.commit()
        except Exception:
            db.rollback()  # va bene se la colonna non esiste ancora

        print("─" * 60)
        print("✓ Migrazione Fase 1-bis completata")
        print("")
        print("Riepilogo:")
        print(f"  Tenant: {db.query(Tenant).count()}")
        print(f"  Reparti: {db.query(Department).filter(Department.tenant_id == 1).count()}")
        print(f"  Voci listino con reparto: {db.query(PriceItem).filter(PriceItem.department_id.isnot(None)).count()}/{db.query(PriceItem).count()}")
        print(f"  Voci con keywords: {db.query(PriceItem).filter(PriceItem.keywords.isnot(None)).count()}/{db.query(PriceItem).count()}")

    except Exception as e:
        db.rollback()
        print(f"✗ Errore durante migrazione: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
