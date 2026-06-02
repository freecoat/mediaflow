"""v3.5.0-alpha.172.164 — Scan dei color primaries nei DeliveryItem dei capitolati.

I primaries (gamut CICP) non erano un campo esplicito finché α.172.163 non l'ha
introdotto. Questo script li DERIVA dalle informazioni colore già estratte dai
capitolati (color_space + hdr_format + risoluzione) e popola ``color_primaries``
dove oggi è NULL ed è inferibile con confidenza. Conservativo: lascia NULL i casi
ambigui (es. UHD SDR senza color_space dichiarato).

Mappatura:
- color_space contiene XYZ        → XYZ          (DCDM cinema)
- color_space contiene P3 (+D65)  → DCI-P3 / P3-D65
- color_space contiene 2020       → BT.2020
- color_space contiene 709        → BT.709
- color_space contiene 601        → BT.601 625
- HDR/HLG/DV/HDR10                 → BT.2020      (container HDR)
- risoluzione ≤576 linee          → BT.601 625   (SD PAL)
- risoluzione 720/1080 (SDR)      → BT.709       (HD SDR)
- altrimenti                      → NULL (ambiguo, scelta a mano)

Uso:
    python scripts/backfill_color_primaries.py            # esegue
    python scripts/backfill_color_primaries.py --dry-run  # solo report
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database import SessionLocal
from app.models.models import DeliveryItem, Resolution


def derive_primaries(color_space, hdr_format, res_height):
    cs = (color_space or "").lower()
    hdr = (hdr_format or "").upper()
    if "xyz" in cs:
        return "XYZ"
    if "p3" in cs:
        return "P3-D65" if "d65" in cs else "DCI-P3"
    if "2020" in cs:
        return "BT.2020"
    if "709" in cs:
        return "BT.709"
    if "601" in cs:
        return "BT.601 625"
    if hdr in ("HDR10", "HDR10+", "DOLBY VISION", "DV", "HLG"):
        return "BT.2020"
    if res_height:
        if res_height <= 576:
            return "BT.601 625"
        if res_height in (720, 1080):
            return "BT.709"
    return None


def backfill(dry_run: bool = False, db=None):
    own = db is None
    if own:
        db = SessionLocal()
    stats = {"scanned": 0, "set": 0, "ambiguous": 0}
    try:
        res_h = {r.id: r.height for r in db.execute(select(Resolution)).scalars().all()}
        items = db.execute(
            select(DeliveryItem).where(DeliveryItem.color_primaries.is_(None))
        ).scalars().all()
        for it in items:
            stats["scanned"] += 1
            prim = derive_primaries(it.color_space, it.hdr_format, res_h.get(it.resolution_id))
            if prim:
                print(f"  [SET] item #{it.id} '{it.name}' "
                      f"(cs={it.color_space!r} hdr={it.hdr_format!r}) -> {prim}")
                if not dry_run:
                    it.color_primaries = prim
                stats["set"] += 1
            else:
                stats["ambiguous"] += 1
        if not dry_run:
            db.commit()
    finally:
        if own:
            db.close()
    print("\n=== Backfill color primaries ===")
    for k, v in stats.items():
        print(f"  {k:12s}: {v}")
    if dry_run:
        print("  (dry-run: nessuna modifica)")
    return stats


if __name__ == "__main__":
    backfill(dry_run="--dry-run" in sys.argv)
