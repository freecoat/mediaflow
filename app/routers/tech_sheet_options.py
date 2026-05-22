"""Router opzioni dropdown campi scheda tecnica (α.172.34).

Pannello admin in /settings → "Scheda tecnica" per gestire i valori
ammessi per ciascun field_path (es. cameras.codec). Quando popolato,
l'editor scheda tecnica usa `<select>` strict invece di input free.

Endpoint:
- GET    /settings/api/tech-sheet-options          — lista (filtro field_path opz)
- GET    /settings/api/tech-sheet-options/paths     — lista distinct field_path
- POST   /settings/api/tech-sheet-options          — crea
- PUT    /settings/api/tech-sheet-options/{id}     — modifica
- DELETE /settings/api/tech-sheet-options/{id}     — soft (is_active=False)
- POST   /settings/api/tech-sheet-options/seed-netflix — bulk seed Netflix delivery
- GET    /settings/api/tech-sheet-options/by-path  — risposta indicizzata per field_path (usata da editor)
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Body
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TechSheetFieldOption
from app.services.rbac import current_user_optional, is_admin
from app.context import current_tenant_id

router = APIRouter(prefix="/settings", tags=["tech-sheet-options"])


# Field paths supportati dal modello tech_sheet (vedi DEFAULT_DATA in tech_sheets.py)
# Path = "<section>.<field>" per oggetti annidati, oppure "<section>" per stringa.
KNOWN_FIELD_PATHS = [
    # general
    "general.production_company",
    # cameras (lista di camera object)
    "cameras.codec", "cameras.sensor_res", "cameras.format_aspect",
    "cameras.framing_aspect", "cameras.fps", "cameras.hi_speed_max_fps",
    "cameras.shutter", "cameras.color_space_in", "cameras.working_color_space",
    "cameras.odt", "cameras.squeeze", "cameras.mag_type",
    # audio
    "audio.recorder", "audio.file_format", "audio.sample_rate", "audio.bit_depth",
    "audio.tc_fps", "audio.sync_method", "audio.track_layout",
    # looks (lista)
    "looks.type", "looks.range_transform",
    # storage
    "storage.master", "storage.backup", "storage.shuttle",
    "storage.checksum_onset", "storage.checksum_lab", "storage.lto_type",
    "storage.shuttle_freq",
    # dailies
    "dailies.editorial_format", "dailies.editorial_container",
    "dailies.online_format", "dailies.online_bitrate", "dailies.nle",
    "dailies.review_platform", "dailies.exchange_format",
    # process
    "process.qc_onset", "process.qc_lab",
]


def _o_dict(o: TechSheetFieldOption) -> dict:
    return {
        "id": o.id,
        "field_path": o.field_path,
        "value": o.value,
        "label": o.label or o.value,
        "sort_order": o.sort_order,
        "is_active": o.is_active,
    }


@router.get("/api/tech-sheet-options")
async def list_options(
    request: Request,
    field_path: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Login richiesto")
    q = db.query(TechSheetFieldOption).filter(
        TechSheetFieldOption.tenant_id == current_tenant_id(),
    )
    if field_path:
        q = q.filter(TechSheetFieldOption.field_path == field_path)
    if not include_inactive:
        q = q.filter(TechSheetFieldOption.is_active == True)  # noqa: E712
    rows = q.order_by(
        TechSheetFieldOption.field_path, TechSheetFieldOption.sort_order, TechSheetFieldOption.value,
    ).all()
    return {"options": [_o_dict(o) for o in rows]}


@router.get("/api/tech-sheet-options/paths")
async def list_paths(request: Request, db: Session = Depends(get_db)):
    """Field paths supportati + conteggio options attive per ciascuno."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Login richiesto")
    rows = db.query(TechSheetFieldOption).filter(
        TechSheetFieldOption.tenant_id == current_tenant_id(),
        TechSheetFieldOption.is_active == True,  # noqa: E712
    ).all()
    counts: dict[str, int] = {}
    for o in rows:
        counts[o.field_path] = counts.get(o.field_path, 0) + 1
    return {
        "known_paths": KNOWN_FIELD_PATHS,
        "active_counts": counts,
    }


@router.get("/api/tech-sheet-options/by-path")
async def options_by_path(request: Request, db: Session = Depends(get_db)):
    """Mappa field_path → [{value, label}, ...]. Usata da editor scheda tecnica
    per render <select> strict quando esiste almeno 1 option attiva."""
    rows = db.query(TechSheetFieldOption).filter(
        TechSheetFieldOption.tenant_id == current_tenant_id(),
        TechSheetFieldOption.is_active == True,  # noqa: E712
    ).order_by(
        TechSheetFieldOption.field_path, TechSheetFieldOption.sort_order, TechSheetFieldOption.value,
    ).all()
    out: dict[str, list] = {}
    for o in rows:
        out.setdefault(o.field_path, []).append({"value": o.value, "label": o.label or o.value})
    return out


@router.post("/api/tech-sheet-options")
async def create_option(
    request: Request,
    field_path: str = Form(...),
    value: str = Form(...),
    label: Optional[str] = Form(None),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not is_admin(user):
        raise HTTPException(403, "Solo admin può configurare le opzioni scheda tecnica")
    field_path = field_path.strip()
    value = value.strip()
    if not field_path or not value:
        raise HTTPException(422, "field_path e value obbligatori")
    existing = db.query(TechSheetFieldOption).filter(
        TechSheetFieldOption.tenant_id == current_tenant_id(),
        TechSheetFieldOption.field_path == field_path,
        TechSheetFieldOption.value == value,
    ).first()
    if existing:
        raise HTTPException(409, f"Opzione '{value}' già esistente per {field_path}")
    o = TechSheetFieldOption(
        tenant_id=current_tenant_id(),
        field_path=field_path[:120], value=value[:200],
        label=(label.strip()[:200] if label else None),
        sort_order=sort_order,
        created_by_user_id=user.id if user else None,
    )
    db.add(o); db.commit(); db.refresh(o)
    return _o_dict(o)


@router.put("/api/tech-sheet-options/{opt_id}")
async def update_option(
    opt_id: int, request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not is_admin(user):
        raise HTTPException(403, "Solo admin può configurare le opzioni scheda tecnica")
    o = db.query(TechSheetFieldOption).filter(
        TechSheetFieldOption.id == opt_id,
        TechSheetFieldOption.tenant_id == current_tenant_id(),
    ).first()
    if not o:
        raise HTTPException(404, "Opzione non trovata")
    if "value" in payload:
        o.value = (payload["value"] or "").strip()[:200] or o.value
    if "label" in payload:
        lab = payload["label"]
        o.label = (lab.strip()[:200] if lab else None)
    if "sort_order" in payload:
        try: o.sort_order = int(payload["sort_order"])
        except (TypeError, ValueError): pass
    if "is_active" in payload:
        o.is_active = bool(payload["is_active"])
    db.commit(); db.refresh(o)
    return _o_dict(o)


@router.delete("/api/tech-sheet-options/{opt_id}")
async def delete_option(opt_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user_optional(request)
    if not is_admin(user):
        raise HTTPException(403, "Solo admin può configurare le opzioni scheda tecnica")
    o = db.query(TechSheetFieldOption).filter(
        TechSheetFieldOption.id == opt_id,
        TechSheetFieldOption.tenant_id == current_tenant_id(),
    ).first()
    if not o:
        raise HTTPException(404, "Opzione non trovata")
    o.is_active = False
    db.commit()
    return {"ok": True}


# ── Seed Netflix delivery ─────────────────────────────────────
# Valori da Netflix Delivery Specifications (camera approved list +
# proxies + dailies). Subset pragmatico, espandibile via UI.
NETFLIX_SEED = {
    "cameras.codec": [
        "ARRIRAW", "Apple ProRes 4444 XQ", "Apple ProRes 4444",
        "REDCODE RAW (R3D)", "Sony Venice X-OCN ST", "Sony Venice X-OCN LT",
        "Blackmagic RAW Q0", "Blackmagic RAW Q1", "Canon RAW Light (.crm)",
        "DNxHR 444", "DNxHR HQX",
    ],
    "cameras.sensor_res": [
        "3.4K", "4K UHD (3840×2160)", "4K DCI (4096×2160)", "4.5K", "5K",
        "6K", "6.5K", "8K UHD (7680×4320)",
    ],
    "cameras.format_aspect": ["16:9", "17:9", "4:3", "6:5", "3:2", "1:1"],
    "cameras.framing_aspect": ["1.85:1", "2.39:1", "2.00:1", "16:9", "4:3", "1.66:1", "1.77:1"],
    "cameras.fps": ["23.976", "24", "25", "29.97", "30", "48", "50", "59.94", "60", "120"],
    "cameras.color_space_in": [
        "ARRI LogC3 / Wide Gamut", "ARRI LogC4 / Wide Gamut 4",
        "Sony S-Log3 / S-Gamut3.Cine", "Sony S-Log3 / S-Gamut3",
        "RED IPP2 (Log3G10 / REDWideGamutRGB)",
        "Blackmagic Film Gen 5", "Canon Log 2 / Cinema Gamut",
        "ACEScct", "ACES2065-1",
    ],
    "cameras.working_color_space": ["ACEScct", "ACES2065-1", "Rec.709", "Rec.2020", "P3-D65"],
    "cameras.odt": ["Rec.709 (BT.1886)", "P3-D65 100nit", "Rec.2020 PQ 1000nit", "Rec.2020 HLG"],
    "cameras.squeeze": ["1.0x", "1.3x", "1.8x", "2.0x"],
    "audio.recorder": [
        "Sound Devices 833", "Sound Devices Scorpio", "Sound Devices MixPre-10 II",
        "Zaxcom Nova", "Zaxcom Deva 24", "Sonosax SX-R4+",
    ],
    "audio.file_format": ["BWF (Broadcast Wave)", "Polyphonic WAV", "Monophonic WAV"],
    "audio.sample_rate": ["48 kHz", "96 kHz"],
    "audio.bit_depth": ["24-bit", "32-bit float"],
    "audio.tc_fps": ["23.976 NDF", "24 NDF", "25", "29.97 DF", "29.97 NDF", "30 NDF"],
    "audio.sync_method": [
        "TC genlock (jam-sync ogni 4h)", "Master clock dedicato",
        "Free-run sync", "Pilot tone",
    ],
    "audio.track_layout": [
        "Boom L+R / Lavs / Mix", "Multitrack ISO + Mix L/R",
        "5.1 stem (L/R/C/LFE/Ls/Rs)", "Stereo L/R",
    ],
    "storage.master": ["LTO-9 (18TB)", "LTO-8 (12TB)", "RAID 6 NAS", "Object storage (S3)"],
    "storage.backup": ["LTO-9 mirror", "Cloud archive (S3 Glacier)", "Secondary RAID 6"],
    "storage.shuttle": ["SSD G-DRIVE Mobile", "SSD Samsung T7", "HDD G-DRIVE ev RaW", "Sandisk Extreme Pro"],
    "storage.checksum_onset": ["MD5", "SHA-1", "xxHash64", "MHL (Media Hash List)"],
    "storage.checksum_lab": ["MD5", "SHA-1", "xxHash64", "MHL"],
    "storage.lto_type": ["LTO-9", "LTO-8", "LTO-7"],
    "storage.shuttle_freq": ["Daily", "Twice daily (am/pm)", "Weekly", "On wrap"],
    "dailies.editorial_format": [
        "Apple ProRes 422 Proxy", "Apple ProRes 422 LT", "Apple ProRes 422",
        "DNxHR LB", "DNxHR SQ", "H.264 (review)",
    ],
    "dailies.editorial_container": ["MOV", "MXF OP1a"],
    "dailies.online_format": [
        "Apple ProRes 4444 XQ", "Apple ProRes 4444", "Apple ProRes 422 HQ",
        "DNxHR 444", "DNxHR HQX",
    ],
    "dailies.online_bitrate": ["330 Mbps", "440 Mbps", "750 Mbps", "1 Gbps+"],
    "dailies.nle": ["Avid Media Composer", "Adobe Premiere Pro", "DaVinci Resolve", "FCPX"],
    "dailies.review_platform": ["Frame.io", "Wipster", "PIX System", "Disney/Netflix internal"],
    "dailies.exchange_format": ["AAF", "XML (FCP7)", "EDL CMX 3600", "OTIO"],
    "process.qc_onset": ["Pomfort Silverstack", "ShotPut Pro", "YoYotta", "Hedge"],
    "process.qc_lab": ["Colorfront Transkoder", "Baton (Interra)", "Aurora (Tektronix)", "Manual QC"],
}


@router.post("/api/tech-sheet-options/seed-netflix")
async def seed_netflix(
    request: Request,
    overwrite: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Popola le opzioni con valori Netflix Delivery Specifications.
    Idempotente: salta valori già esistenti (a meno di overwrite=True →
    riattiva is_active=True se erano disattivate).
    """
    user = current_user_optional(request)
    if not is_admin(user):
        raise HTTPException(403, "Solo admin può eseguire il seed")
    created = 0
    reactivated = 0
    skipped = 0
    for field_path, values in NETFLIX_SEED.items():
        for idx, val in enumerate(values):
            existing = db.query(TechSheetFieldOption).filter(
                TechSheetFieldOption.tenant_id == current_tenant_id(),
                TechSheetFieldOption.field_path == field_path,
                TechSheetFieldOption.value == val,
            ).first()
            if existing:
                if overwrite and not existing.is_active:
                    existing.is_active = True
                    reactivated += 1
                else:
                    skipped += 1
                continue
            o = TechSheetFieldOption(
                tenant_id=current_tenant_id(),
                field_path=field_path, value=val,
                sort_order=idx * 10,
                created_by_user_id=user.id if user else None,
            )
            db.add(o)
            created += 1
    db.commit()
    return {
        "created": created,
        "reactivated": reactivated,
        "skipped": skipped,
        "total_paths": len(NETFLIX_SEED),
    }
