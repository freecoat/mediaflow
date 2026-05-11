"""Seed iniziale DeliveryTemplate per i broadcaster/distributori più comuni.

v3.5.0-alpha.69.3 — Riempie la tabella delivery_templates con scheletri
base (code/name/broadcaster/description), così Matteo può aprire
/delivery-templates e vedere subito i template più diffusi su cui poi
popolare suggested_items + blocchi tech.

Idempotente: skip se code già presente per il tenant.

Uso:
    python scripts/seed_delivery_templates.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import DeliveryTemplate


TEMPLATES = [
    # Cinema theatrical / distribuzione
    {
        "code": "A24-THEATRICAL",
        "name": "A24 — Theatrical Dolby Vision Feature",
        "broadcaster": "A24",
        "description": "Master DCP + IMF Dolby Vision/Atmos per theatrical A24.",
    },
    {
        "code": "MUBI-STREAMING",
        "name": "MUBI — Streaming Exhibit C",
        "broadcaster": "MUBI",
        "description": "Deliverable streaming MUBI (HD/4K SDR + HDR opzionale).",
    },
    {
        "code": "VISION-DISTRIB-IT",
        "name": "Vision Distribution — Allegato A",
        "broadcaster": "Vision Distribution",
        "description": "Distribuzione italiana cinema/TV. DCP INTEROP + IMF.",
    },
    {
        "code": "IRDA-PIPERFILM",
        "name": "IRDA / PiperFilm — Materiali",
        "broadcaster": "IRDA",
        "description": "Allegato materiali distribuzione indie.",
    },
    # TV broadcast italiana
    {
        "code": "RAI-TV-1.4",
        "name": "RAI — Specifiche TV 1.4",
        "broadcaster": "RAI",
        "description": "Specifiche Tecniche Prodotti Televisivi RAI v1.4.",
    },
    {
        "code": "SKY-ORIGINAL",
        "name": "Sky Original — SKY 5.1 Audio",
        "broadcaster": "Sky",
        "description": "SkyOriginal + audio 5.1, master IMF/ProRes.",
    },
    # Streaming globale
    {
        "code": "NETFLIX-IMF",
        "name": "Netflix IMF Standard",
        "broadcaster": "Netflix",
        "description": "Master IMF Netflix originals (HDR10 / Dolby Vision / Atmos).",
    },
    {
        "code": "AMAZON-MGM",
        "name": "Amazon MGM Deliverables",
        "broadcaster": "Amazon MGM",
        "description": "Deliverables Amazon MGM (Prime Video + theatrical).",
    },
    # Distribuzione TV internazionale
    {
        "code": "BETA-FILM",
        "name": "BETA FILM — Delivery Master",
        "broadcaster": "BETA FILM",
        "description": "Master internazionale TV BETA FILM.",
    },
    {
        "code": "FREMANTLE-DCP",
        "name": "FREMANTLE — DCP Deliverables Supplemental",
        "broadcaster": "Fremantle",
        "description": "DCP supplementare Fremantle.",
    },
    {
        "code": "NBCU-TECHOPS-2.8",
        "name": "NBCUniversal TechOps v2.8",
        "broadcaster": "NBCUniversal",
        "description": "TechOps NBCU v2.8 + Metadata Template v1.3.",
    },
]


def main() -> int:
    db = SessionLocal()
    try:
        inserted = 0
        skipped = 0
        for t in TEMPLATES:
            existing = db.query(DeliveryTemplate).filter(
                DeliveryTemplate.tenant_id == 1,
                DeliveryTemplate.code == t["code"],
            ).first()
            if existing:
                skipped += 1
                continue
            row = DeliveryTemplate(
                tenant_id=1,
                code=t["code"],
                name=t["name"],
                broadcaster=t["broadcaster"],
                description=t["description"],
                version="1.0",
                is_active=True,
                ai_generated=False,
            )
            db.add(row)
            inserted += 1
        db.commit()
        print(f"[seed_delivery_templates] inserted={inserted} skipped_existing={skipped}")
        if inserted:
            print(f"  Apri /delivery-templates per editare suggested_items e blocchi tech.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
