"""Builder del preset listino lean (v3.5.0-alpha.66.8).

Riduce 79 → 43 voci accorpando per natura simile + descrizione modulare
con placeholder che il PM completa quando aggiunge la riga in quote.

Output: app/data/pricelist_presets/lean_2026q3_v1.json (schema 1.1)
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "pricelist_presets" / "lean_2026q3_v1.json"


# 4 reparti (gli stessi del legacy)
DEPARTMENTS = [
    {"code": "DI-VIDEO",  "name": "DI / Video", "color": "#6272f5", "sort_order": 10,
     "description": "Digital Intermediate: dailies, conform, color grading, mastering DCP/DCDM, deliverables video, archive, QC"},
    {"code": "VFX",        "name": "VFX / Finishing", "color": "#a855f7", "sort_order": 20,
     "description": "Visual Effects e finishing: compositing, 3D, matte painting, rotoscoping, paint"},
    {"code": "AUDIO",      "name": "Audio", "color": "#2ec4b6", "sort_order": 30,
     "description": "Post-produzione audio: editing, mix, foley, ADR, deliverables sound, localization, doppiaggio"},
    {"code": "COMMERCIAL", "name": "Commercial / Produzione", "color": "#f59e0b", "sort_order": 40,
     "description": "Project management, coordinamento produzione, preventivazione, amministrazione"},
]

# 12 categorie con sort_order incrementali
CATEGORIES = [
    {"name": "DAILIES",              "description": "Lavorazione dailies, sync, proxy, review",                  "sort_order": 10},
    {"name": "PICTURE / DI",         "description": "Conform, color grading, versioning",                        "sort_order": 20},
    {"name": "MASTERING DCP / DCDM", "description": "Mastering Digital Cinema Package + Dolby Vision/Atmos",     "sort_order": 30},
    {"name": "DELIVERABLES VIDEO",   "description": "Master ProRes, screener, IMF/DPP/AS-11",                    "sort_order": 40},
    {"name": "ARCHIVE / TRANSFER",   "description": "LTO archive, drive consegna, transfer elettronico",          "sort_order": 50},
    {"name": "VFX",                  "description": "Compositing, plates, motion graphics, roto/paint",           "sort_order": 60},
    {"name": "SOUND EDIT",           "description": "Sound editorial, foley, ADR",                                "sort_order": 70},
    {"name": "MIX",                  "description": "Re-recording mix surround/Atmos, sala mix",                  "sort_order": 80},
    {"name": "DELIVERABLES SOUND",   "description": "Printmaster, M&E, DME stems, Atmos ADM, audio description",  "sort_order": 90},
    {"name": "LOCALIZATION",         "description": "Sottotitolazione, caption, doppiaggio",                      "sort_order": 100},
    {"name": "QC / METADATA",        "description": "QC manuale e automatico, metadata, music cue sheet",         "sort_order": 110},
    {"name": "PROJECT MANAGEMENT",   "description": "Project management, coordinamento, preventivazione",         "sort_order": 120},
]


# Schema record voce: (cat, dept, name, description, unit_pre, unit, price, hardcost, [keywords])
# La description è pensata come "template modulare": il PM la completa
# riempiendo i placeholder quando aggiunge la riga in una quote.
ITEMS = [
    # ── DAILIES (2) ────────────────────────────────────────────
    ("DAILIES", "DI-VIDEO", "Dailies workflow",
     "Turnaround dailies completo: sync audio, color base con LUT, transcoding proxy editing, QC operatore, "
     "upload su piattaforma review (Frame.io / Pix / Aspera). Dettagliare nella descrizione di riga: "
     "piattaforma upload, eventuali limiti di accesso, frame range giornaliero, LUT custom.",
     "per", "day", 450, None,
     ["dailies", "sync", "color", "proxy", "qc", "upload", "frameio", "pix", "lut", "ingest", "review"]),

    ("DAILIES", "DI-VIDEO", "Camera card offload + verify",
     "Offload card camera con generazione MHL/MD5, verifica integrità, backup ridondante. "
     "Dettagliare: tipo card, quantità per turno, destinazione storage primaria + secondaria.",
     "per", "day", 280, None,
     ["camera", "cards", "offload", "mhl", "md5", "verify", "ingest", "backup"]),

    # ── PICTURE / DI (4) ───────────────────────────────────────
    ("PICTURE / DI", "DI-VIDEO", "Online conform",
     "Conform da EDL/AAF con riferimento offline, gestione VFX shots. "
     "Dettagliare: risoluzione (2K ≈€900/day, 4K ≈€1100/day, IMF), frame rate, sorgente offline (Avid/Resolve/Premiere).",
     "per", "day", 1000, None,
     ["conform", "online", "finishing", "edl", "aaf", "2k", "4k", "imf", "vfx"]),

    ("PICTURE / DI", "DI-VIDEO", "Color grading SDR",
     "Sessione color grading SDR Rec.709 con colorist e sala certificata. "
     "Dettagliare: risoluzione (2K ≈€1500/day, 4K ≈€1800/day), durata sessione, nome colorist.",
     "per", "day", 1650, None,
     ["color", "grading", "sdr", "rec709", "colorist", "di", "2k", "4k"]),

    ("PICTURE / DI", "DI-VIDEO", "Color grading HDR Dolby Vision (incl. trim pass)",
     "Sessione HDR P3 D65 PQ con monitor Dolby e generazione metadata Dolby Vision. "
     "Trim pass per ogni target HDR/SDR aggiuntivo (1000nit / 600nit / 100nit / Rec.709) ≈€600/pass.",
     "per", "day", 2200, None,
     ["hdr", "dolby", "vision", "grading", "p3", "pq", "metadata", "trim", "1000nit", "600nit", "rec709"]),

    ("PICTURE / DI", "DI-VIDEO", "Versioning / textless / alternative cuts",
     "Creazione versione textless o alternative cut (VF, OAR, festival cut) con conform aggiuntivo.",
     "per", "version", 400, None,
     ["textless", "version", "recompositing", "vf", "oar", "alternative", "festival"]),

    # ── MASTERING DCP / DCDM (3) ───────────────────────────────
    ("MASTERING DCP / DCDM", "DI-VIDEO", "Mastering DCP standard",
     "Mastering Digital Cinema Package con CPL/PKL/naming DCNC. "
     "Dettagliare: formato (INTEROP / SMPTE), risoluzione (2K ≈€700, 4K ≈€900), audio (5.1/7.1), "
     "encryption (KDM per singola sala / DKDM per validità lunga), festival pass se richiesto.",
     "per", "pc", 750, None,
     ["dcp", "smpte", "interop", "2k", "4k", "cinema", "distribution", "dcnc", "kdm", "dkdm", "encryption", "festival"]),

    ("MASTERING DCP / DCDM", "DI-VIDEO", "Mastering DCP Dolby Vision/Atmos (SMPTE Bv2.1)",
     "DCP SMPTE Bv2.1 premium con Dolby Vision XYZ TIFF e/o Dolby Atmos MXF immersivo. "
     "Richiede sorgente HDR già masterizzata e mix Atmos approvato.",
     "per", "pc", 1500, None,
     ["dcp", "dolby", "vision", "atmos", "smpte", "bv2.1", "immersive", "premium"]),

    ("MASTERING DCP / DCDM", "DI-VIDEO", "DCDM 16-bit XYZ TIFF",
     "Digital Cinema Distribution Master 16-bit XYZ TIFF in rulli per archive. "
     "Output non-encrypted, tipicamente per long-term archive cliente.",
     "per", "pc", 1200, None,
     ["dcdm", "xyz", "tiff", "16bit", "master", "archive"]),

    # ── DELIVERABLES VIDEO (5) ─────────────────────────────────
    ("DELIVERABLES VIDEO", "DI-VIDEO", "Master ProRes 4444 XQ",
     "Master ProRes 4444 XQ con head format completo (bars, slate, tone). "
     "Dettagliare: target (HD 1080p ≈€350, UHD SDR Rec.709 ≈€500, UHD HDR P3 D65 PQ + sidecar Dolby Vision XML v2.9 ≈€700), "
     "frame rate, audio config, eventuali burn (timecode, watermark).",
     "per", "pc", 500, None,
     ["prores", "4444", "hd", "1080p", "uhd", "4k", "sdr", "hdr", "dolby", "vision", "master", "head", "slate"]),

    ("DELIVERABLES VIDEO", "DI-VIDEO", "Proxy ProRes 422 HQ",
     "Proxy ProRes 422 HQ per screener interni, broadcast preview o editing offline. "
     "Dettagliare: HD 1080p ≈€250 / UHD ≈€350.",
     "per", "pc", 300, None,
     ["prores", "422", "hd", "uhd", "proxy", "screener", "broadcast"]),

    ("DELIVERABLES VIDEO", "DI-VIDEO", "Screener H.264 / H.265",
     "Export H.264 (o H.265) 1080p15Mbps. "
     "Dettagliare: clean ≈€120 / con watermark dinamico per security review ≈€180 / con timecode burn ≈€150. "
     "Non confondere con il proxy editorial.",
     "per", "pc", 150, None,
     ["h264", "h265", "screener", "mp4", "preview", "clean", "watermark", "security", "timecode", "burn"]),

    ("DELIVERABLES VIDEO", "DI-VIDEO", "Textless ProRes",
     "Export ProRes textless backgrounds (titoli, end credits, lower thirds) per localization e versioning.",
     "per", "pc", 280, None,
     ["textless", "prores", "backgrounds", "credits", "lower thirds"]),

    ("DELIVERABLES VIDEO", "DI-VIDEO", "IMF / DPP / AS-11 broadcast master",
     "Mastering package per piattaforme broadcast e streaming moderne. "
     "Dettagliare: standard target (IMF Netflix/Amazon, DPP UK, AS-11 broadcast IT), "
     "package format, audio loudness target (-23 LUFS / -24 LKFS), QC tool richiesto.",
     "per", "pc", 800, None,
     ["imf", "dpp", "as-11", "as11", "broadcast", "streaming", "netflix", "amazon", "mxf", "package", "loudness"]),

    # ── ARCHIVE / TRANSFER (4) ─────────────────────────────────
    ("ARCHIVE / TRANSFER", "DI-VIDEO", "LTO LTFS archive",
     "Archive su nastri LTO7/8 LTFS con verifica MD5. "
     "Dettagliare nella riga il tipo di materiale archiviato (camera original ≈€120/TB, "
     "DPX graded ≈€150/TB, DPX ungraded ≈€130/TB, Dolby Vision master ≈€180/TB, "
     "ProRes deliverables ≈€100/TB) — il prezzo varia con la natura del materiale.",
     "per", "TB", 130, None,
     ["lto", "ltfs", "archive", "md5", "dpx", "prores", "dolby", "vision", "camera", "original", "graded", "ungraded"]),

    ("ARCHIVE / TRANSFER", "DI-VIDEO", "Drive consegna fisica + shipping",
     "Drive di consegna materiali al cliente: USB 3.0 exFAT/NTFS, CRU EXT3 per DCP, o equivalente. "
     "Dettagliare: tipo, capacità, shipping incluso o a parte. "
     "Hardcost del supporto stimato 80-100€/drive (verrà ridiscusso in α.66.9 cost-rate).",
     "per", "pc", 170, 90,
     ["usb", "hdd", "drive", "delivery", "exfat", "ntfs", "cru", "ext3", "shipping", "courier"]),

    ("ARCHIVE / TRANSFER", "DI-VIDEO", "Transfer elettronico (Aspera/Signiant/Mediashuttle)",
     "Trasferimento elettronico via Signiant/Aspera/Mediashuttle. Tariffa per TB trasferito.",
     "per", "TB", 80, None,
     ["signiant", "mediashuttle", "aspera", "transfer", "upload", "download"]),

    ("ARCHIVE / TRANSFER", "DI-VIDEO", "Checksum generation MD5/xxHash",
     "Generazione e verifica checksum MD5 / xxHash su deliverables/archive. Forfait per consegna.",
     "just", "allow", 150, None,
     ["md5", "xxhash", "checksum", "hash", "verify"]),

    # ── VFX (4) ────────────────────────────────────────────────
    ("VFX", "VFX", "VFX shot composite",
     "Composite VFX shot per shot. "
     "Dettagliare: standard ≈€450/shot (cleanup, screen replacement, comp semplici) / "
     "complex ≈€1200/shot (hero shot, multi-layer, integrazione 3D). Negoziare per shot count totale.",
     "per", "shot", 700, None,
     ["vfx", "composite", "shot", "comp", "cleanup", "hero", "complex", "3d", "screen replacement"]),

    ("VFX", "VFX", "VFX plates pull / handles export",
     "Estrazione plates da DI con maniglie configurabili per VFX vendor. Forfait per progetto.",
     "just", "allow", 600, None,
     ["vfx", "plates", "pull", "handles", "export"]),

    ("VFX", "VFX", "Title design / motion graphics",
     "Sessione design titoli, lower thirds, end roller, motion graphics.",
     "per", "day", 1100, None,
     ["titles", "motion", "graphics", "opening", "credits", "lower thirds"]),

    ("VFX", "VFX", "Roto / paint / cleanup",
     "Lavorazione shot per shot. Dettagliare: roto (mask/isolation/holdouts) ≈€350 / "
     "paint (cleanup wire/rig, beauty fix) ≈€280 / stabilization.",
     "per", "shot", 315, None,
     ["roto", "rotoscope", "paint", "cleanup", "stabilize", "beauty", "rig", "wire", "mask", "isolation"]),

    # ── SOUND EDIT (3) ─────────────────────────────────────────
    ("SOUND EDIT", "AUDIO", "Sound editorial day",
     "Sessione sound editorial in Pro Tools. "
     "Dettagliare ruolo: dialogue editing ≈€750/day / sound design + FX editing ≈€750/day / music editing ≈€700/day. "
     "Tariffa simile, scelta per disponibilità sala/figura.",
     "per", "day", 750, None,
     ["dialogue", "sound", "design", "sfx", "music", "edit", "audio", "protools", "score", "cue", "stems"]),

    ("SOUND EDIT", "AUDIO", "Foley session",
     "Registrazione foley con artist, engineer e sala foley.",
     "per", "day", 900, None,
     ["foley", "recording", "footsteps", "props"]),

    ("SOUND EDIT", "AUDIO", "ADR session",
     "Sessione ADR con sound engineer, sala ADR e direttore.",
     "per", "day", 1100, None,
     ["adr", "looping", "dub", "recording", "vocal"]),

    # ── MIX (3) ────────────────────────────────────────────────
    ("MIX", "AUDIO", "Re-recording mix surround",
     "Mix theatrical con re-recording mixer e sala certificata. "
     "Dettagliare formato: 5.1 ≈€1800/day / 7.1 ≈€2100/day. "
     "Hardcost (consumabili sala / setup) ≈€500/day.",
     "per", "day", 1950, 500,
     ["mix", "5.1", "7.1", "surround", "rerecord", "theater"]),

    ("MIX", "AUDIO", "Re-recording mix Dolby Atmos",
     "Mix immersivo Dolby Atmos con sala certificata e renderer. "
     "Hardcost (license renderer / setup) ≈€800/day.",
     "per", "day", 2800, 800,
     ["atmos", "dolby", "immersive", "mix", "renderer"]),

    ("MIX", "AUDIO", "Mix theater rental",
     "Affitto sala mix certificata Dolby — solo struttura, no mixer. Per sessioni con team esterno.",
     "per", "day", 900, None,
     ["theater", "dub", "stage", "room", "rental"]),

    # ── DELIVERABLES SOUND (5) ─────────────────────────────────
    ("DELIVERABLES SOUND", "AUDIO", "Surround printmaster / M&E",
     "Printmaster surround o M&E (Music & Effects) conform DCP, head format completo. "
     "Dettagliare: tipo (printmaster vs M&E vs entrambi), formato (5.1 ≈€600 / 7.1 ≈€750), frame rate.",
     "per", "pc", 600, None,
     ["printmaster", "me", "music", "effects", "5.1", "7.1", "surround", "dcp", "master", "international"]),

    ("DELIVERABLES SOUND", "AUDIO", "DME stems",
     "Dialogue/Music/Effects stems separati 5.1 (o 7.1) per future relocalization e mix alternativi.",
     "per", "pc", 750, None,
     ["dme", "dialogue", "music", "effects", "stems", "5.1", "7.1"]),

    ("DELIVERABLES SOUND", "AUDIO", "Atmos ADM BWF master",
     "Master Dolby Atmos ADM BWF immersivo + renderer config. Output certificato per piattaforme Atmos.",
     "per", "pc", 1200, None,
     ["atmos", "adm", "bwf", "immersive", "dolby", "master"]),

    ("DELIVERABLES SOUND", "AUDIO", "Stereo LtRt fold-down",
     "Fold-down stereo Lt/Rt da 5.1/7.1, conform al DCP. Spesso richiesto come deliverable obbligatorio.",
     "per", "pc", 350, None,
     ["stereo", "ltrt", "fold", "downmix"]),

    ("DELIVERABLES SOUND", "AUDIO", "Audio description (script + recording)",
     "Audiodescrizione italiana o multilingua. "
     "Dettagliare componenti: stesura script ≈€350/pc + registrazione narratore + mix ≈€18/min finito. "
     "Per quote dettagliata, valutare separatamente i due componenti.",
     "per", "pc", 450, None,
     ["ad", "audiodescription", "accessibility", "narrator", "script", "italiano"]),

    # ── LOCALIZATION (4) ───────────────────────────────────────
    ("LOCALIZATION", "AUDIO", "Subtitle translation",
     "Traduzione sottotitoli con QC linguistico. "
     "Dettagliare direzione: EN→IT ≈€15/min / IT→EN ≈€18/min / altre coppie linguistiche.",
     "per", "min", 16, None,
     ["subtitle", "translation", "italian", "english", "spotting"]),

    ("LOCALIZATION", "AUDIO", "Subtitle conformance multi-format",
     "Conformance sottotitoli a IMSC1.1 / STL / SRT / iTT / TimedText XML INTEROP-SMPTE. Per ogni formato.",
     "per", "pc", 280, None,
     ["imsc", "stl", "srt", "itt", "timedtext", "subtitle", "conform"]),

    ("LOCALIZATION", "AUDIO", "Caption authoring (SDH / CC / forced)",
     "Authoring caption per non udenti (SDH/CC, 32 char/line standard) o sottotitoli forzati narrativi (lingue straniere in scena). "
     "Dettagliare tipo (SDH ≈€450 / forced ≈€280).",
     "per", "pc", 400, None,
     ["sdh", "cc", "deaf", "accessibility", "closed", "caption", "forced", "narrative", "subtitle"]),

    ("LOCALIZATION", "AUDIO", "Dubbing direction + recording",
     "Sessione doppiaggio con direttore, attori, fonico, sala. Hardcost (rimborsi attori / spese sala) ≈€200/day.",
     "per", "day", 1500, 200,
     ["dub", "dubbing", "voiceover", "loop"]),

    # ── QC / METADATA (3) ──────────────────────────────────────
    ("QC / METADATA", "DI-VIDEO", "Manual QC",
     "QC manuale con report tecnico (artefatti video, audio, sub). "
     "Dettagliare: HD/SDR ≈€280/pc / UHD/HDR (con monitor Dolby Vision e analisi metadata) ≈€450/pc.",
     "per", "pc", 365, None,
     ["qc", "manual", "review", "hd", "sdr", "uhd", "hdr", "dolby"]),

    ("QC / METADATA", "DI-VIDEO", "Auto-QC Baton/Vidcheck",
     "QC automatico Baton/Vidcheck/Aurora con report XML. Veloce ed economico, complementare al manual QC.",
     "per", "pc", 120, None,
     ["baton", "vidcheck", "aurora", "autoqc", "automated"]),

    ("QC / METADATA", "DI-VIDEO", "Metadata XML + Music Cue Sheet",
     "Compilazione metadata XML (Sky/RAI/NBCU TechOps/IMF/IMSC) ≈€280 OR Music Cue Sheet (autori, editori, ISWC) ≈€350. "
     "Dettagliare tipo nella riga.",
     "per", "pc", 315, None,
     ["metadata", "xml", "techops", "gtm", "sidecar", "imf", "cue", "sheet", "music", "iswc"]),

    # ── PROJECT MANAGEMENT (3) ─────────────────────────────────
    ("PROJECT MANAGEMENT", "COMMERCIAL", "Production management",
     "Project manager o production coordinator dedicato al progetto. "
     "Dettagliare ruolo: PM (coordinamento, scheduling, deliverables tracking) ≈€700/day / "
     "Coordinator (liaison vendor, calendari, materiali) ≈€450/day.",
     "per", "day", 575, None,
     ["project", "manager", "pm", "coordinator", "production", "tpr", "liaison", "tracking", "scheduling"]),

    ("PROJECT MANAGEMENT", "COMMERCIAL", "Quote / estimate preparation",
     "Preparazione quotazione con analisi capitolato e stima risorse. Forfait per quote.",
     "per", "pc", 450, None,
     ["quote", "estimate", "bid", "preventivo"]),

    ("PROJECT MANAGEMENT", "COMMERCIAL", "Travel / shipping allowance",
     "Forfait spese di trasferimento personale e shipping deliverables. Da dettagliare nella riga in base al progetto.",
     "just", "allow", 350, None,
     ["travel", "shipping", "courier", "transfer"]),
]


def build_payload() -> dict:
    return {
        "schema_version": "1.1",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "exported_by": "build_lean_preset.py",
        "source_app_version": "3.5.0-alpha.66.8",
        "tenant_id": 1,
        "description": (
            "Listino MediaFlow lean 2026-Q3 v1 — 43 voci con descrizione modulare. "
            "Riduzione del 46% rispetto al legacy 79 voci tramite accorpamento di varianti "
            "vicine (es. DCP INTEROP+SMPTE 2K+4K → 'Mastering DCP'). Le specifiche tecniche "
            "scendono dalla voce di listino alla descrizione di riga in quote, dove il PM le "
            "dettaglia per progetto. Aggiunge IMF/DPP/AS-11 broadcast moderno (mancante nel legacy)."
        ),
        "departments": DEPARTMENTS,
        "categories": CATEGORIES,
        "items": [
            {
                "category": cat, "department_code": dep,
                "name": name, "description": desc,
                "unit_pre": unit_pre, "unit": unit,
                "price_list": price, "price_average": price, "price_low": price,
                "hardcosts": hardcost,
                "keywords": keywords, "is_active": True,
            }
            for (cat, dep, name, desc, unit_pre, unit, price, hardcost, keywords) in ITEMS
        ],
    }


if __name__ == "__main__":
    payload = build_payload()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"preset salvato: {OUT}")
    print(f"  items: {len(payload['items'])}")
    print(f"  categories: {len(payload['categories'])}")
    print(f"  departments: {len(payload['departments'])}")
    # Sanity: items per categoria
    from collections import Counter
    by_cat = Counter(it['category'] for it in payload['items'])
    for cat, n in by_cat.items():
        print(f"  {cat}: {n}")
