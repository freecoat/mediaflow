"""Bundle L Stack 1 — Import variants parsed JSON in DB.

Legge `<vendor>.variants.json` files prodotti da parse_capitolati.py e crea
DeliveryVariant entries nel DB. Idempotente: skip se (tenant_id, code) gia'
esiste. Validate ogni variant contro JSON Schema attivo.

Usage:
    .venv/Scripts/python.exe scripts/import_parsed_variants.py \\
        --input docs/superpowers/specs/capitolati-parsed \\
        [--tenant 1] [--dry-run] [--only t1_technical]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.database import SessionLocal
from app.models.variant import DeliveryVariant, DeliveryVariantCategory, VariantSchemaVersion
from app.services.variant_schema import load_active_schema
from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--tenant", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["t1_technical", "t2_documentation", "t3_compilation"],
                    help="Filtra solo variants di una category")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print(f"[error] input dir non trovata: {inp}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        schema = load_active_schema(db)
        sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.is_active == True).first()  # noqa: E712
        schema_version_id = sv.id

        imported = 0
        skipped = 0
        invalid = 0
        for jf in inp.glob("*.variants.json"):
            with jf.open("r", encoding="utf-8") as fp:
                variants = json.load(fp)
            for v in variants:
                if args.only and v.get("category") != args.only:
                    continue
                code = v.get("code")
                if not code:
                    invalid += 1
                    print(f"  SKIP no-code: {jf.name}")
                    continue
                existing = db.query(DeliveryVariant).filter(
                    DeliveryVariant.tenant_id == args.tenant,
                    DeliveryVariant.code == code,
                ).first()
                if existing:
                    skipped += 1
                    continue
                # Validate spec_json contro schema attivo
                try:
                    jsonschema_validate(instance=v, schema=schema)
                except ValidationError as e:
                    invalid += 1
                    print(f"  INVALID {code}: {e.message}")
                    continue
                if args.dry_run:
                    print(f"  [DRY] would import {code}: {v.get('name')}")
                    continue
                db.add(DeliveryVariant(
                    tenant_id=args.tenant,
                    code=code,
                    name=v.get("name") or code,
                    category=DeliveryVariantCategory(v.get("category", "t1_technical")),
                    schema_version_id=schema_version_id,
                    spec_json=v.get("spec_json") or {},
                    language=v.get("language"),
                    territory=v.get("territory"),
                    has_textless=bool(v.get("textless", {}).get("tail_present") or v.get("textless", {}).get("separate_file")) if isinstance(v.get("textless"), dict) else False,
                    has_subtitles=bool(v.get("subtitles", {}).get("present")) if isinstance(v.get("subtitles"), dict) else False,
                    delivery_format=(v.get("container") or {}).get("format"),
                    source_capitolato=v.get("source_capitolato"),
                    source_section=v.get("source_section"),
                ))
                imported += 1
        if not args.dry_run:
            db.commit()
        print(f"[import_parsed_variants] imported={imported} skipped={skipped} invalid={invalid} {'(DRY-RUN)' if args.dry_run else ''}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
