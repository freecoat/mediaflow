"""Assegna reparto + prezzi (media nazionale IT) alle voci-bucket della
categoria "Deliveries" (create da migrate_deliveries_buckets.py, α.172.135,
nate con department_id=None e price_list=None).

Regole reparto (richiesta Matteo, 31 mag 2026):
  - voci AUDIO  → reparto Audio (Suono)
  - voci VIDEO + SOTTOTITOLI + altro (KDM/ISO/Document) → reparto DI / Video

Prezzi = fee di mastering/delivery per deliverable (encode + QC + wrap di un
master finito nel formato target; NON il grading/mix creativo, fatturato a
giornata). Flat per deliverable, sovrascrivibile per riga in quote. 3 livelli
(list / average / low). DM&E è per-minuto (unit=min).

Idempotente: ri-eseguibile, riassegna sempre in base al nome. `--dry` per
preview senza scrivere.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import models as m

DEPT_DI = "DI-VIDEO"      # code reparto DI / Video
DEPT_AUDIO = "AUDIO"      # code reparto Audio

# (list, average, low) in EUR
P = {
    "dcp_2k":        (1200, 950, 750),
    "dcp_4k":        (1800, 1450, 1100),
    "imf":           (1500, 1200, 950),
    "mxf_uhd":       (700, 550, 430),
    "mxf_hd":        (450, 350, 280),
    "mp4_web":       (180, 140, 110),
    "pr422_hd":      (350, 280, 220),
    "pr422_uhd":     (550, 440, 350),
    "pr4444":        (750, 600, 480),
    "pr4444_xq":     (900, 720, 580),
    "imgseq":        (900, 720, 580),
    "sd_master":     (250, 200, 160),
    "subtitle":      (120, 95, 75),
    "kdm":           (80, 60, 45),
    "iso":           (150, 120, 90),
    "document":      (0, 0, 0),
    "full_mix":      (600, 480, 380),
    "stem_single":   (250, 200, 160),
    "me":            (450, 360, 280),
    "stems_bundle":  (700, 560, 450),
    "opt_audio":     (350, 280, 220),
    "dme_min":       (18, 14, 11),   # per minuto
}

AUDIO_PREFIX = ("DM&E", "Dialogue Stem", "Effects Stem", "Foley Stem",
                "Full Mix", "M&E (", "Music Stem", "Optional Audio", "Stems (")


def classify(name: str):
    """Ritorna (is_audio, price_key) per una voce-bucket dal suo nome."""
    n = name
    # ── AUDIO ──────────────────────────────────────────────────────────
    if n.startswith("Full Mix"):
        return True, "full_mix"
    if n.startswith("DM&E"):
        return True, "dme_min"
    if n.startswith("M&E ("):
        return True, "me"
    if n.startswith("Stems ("):
        return True, "stems_bundle"
    if n.startswith("Optional Audio"):
        return True, "opt_audio"
    if n.startswith(("Dialogue Stem", "Effects Stem", "Foley Stem", "Music Stem")):
        return True, "stem_single"
    # ── SOTTOTITOLI / ALTRO ────────────────────────────────────────────
    if n.startswith("Subtitle"):
        return False, "subtitle"
    if n.startswith("KDM"):
        return False, "kdm"
    if n.startswith("Optical Disc"):
        return False, "iso"
    if n.startswith("Document"):
        return False, "document"
    # ── VIDEO ──────────────────────────────────────────────────────────
    if n.startswith("DCP"):
        return False, "dcp_4k" if "4K" in n else "dcp_2k"
    if n.startswith("IMF"):
        return False, "imf"
    if n.startswith("Image Sequence"):
        return False, "imgseq"
    if n.startswith("MXF OP1a"):
        if "SD " in n:
            return False, "sd_master"
        if "300" in n and ("UHD" in n or "4K" in n):
            return False, "mxf_uhd"
        return False, "mxf_hd"
    if n.startswith("MP4"):
        return False, "sd_master" if "SD " in n else "mp4_web"
    if n.startswith("QuickTime"):
        if "MPEG-2" in n or "SD " in n:
            return False, "sd_master"
        if "H.264" in n or "H.265" in n:
            return False, "mp4_web"
        if "4444 XQ" in n:
            return False, "pr4444_xq"
        if "4444" in n:
            return False, "pr4444"
        if "422 HQ" in n or "422HQ" in n:
            return False, "pr422_uhd" if ("UHD" in n or "4K" in n) else "pr422_hd"
        return False, "pr422_hd"  # ProRes 422 generico
    # Fallback: video HD generico (non dovrebbe capitare nel corpus attuale)
    return False, "pr422_hd"


def main(dry=False):
    db = SessionLocal()
    try:
        di = db.query(m.Department).filter(m.Department.code == DEPT_DI).first()
        audio = db.query(m.Department).filter(m.Department.code == DEPT_AUDIO).first()
        if not di or not audio:
            print(f"ERRORE: reparti non trovati (DI={di}, AUDIO={audio})")
            return 1
        cat = db.query(m.PriceCategory).filter(m.PriceCategory.name == "Deliveries").first()
        if not cat:
            print("ERRORE: categoria 'Deliveries' non trovata")
            return 1
        items = db.query(m.PriceItem).filter(
            m.PriceItem.category_id == cat.id,
            m.PriceItem.is_active == True,  # noqa: E712
        ).all()
        n_audio = n_di = 0
        for it in items:
            is_audio, key = classify(it.name)
            pl, pa, lo = P[key]
            dept_id = audio.id if is_audio else di.id
            if not dry:
                it.department_id = dept_id
                it.price_list = float(pl)
                it.price_average = float(pa)
                it.price_low = float(lo)
            if is_audio:
                n_audio += 1
            else:
                n_di += 1
            print(f"  #{it.id:>3} {'AUDIO' if is_audio else 'DI   '} "
                  f"{key:<13} {pl:>5}/{pa:>4}/{lo:>4}  {it.name}")
        if not dry:
            db.commit()
        print(f"\n{'[DRY] ' if dry else ''}voci: {len(items)} "
              f"(audio->Suono={n_audio}, video/sub/altro->DI={n_di})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(dry="--dry" in sys.argv))
