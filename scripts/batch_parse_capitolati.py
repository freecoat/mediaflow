"""v3.5.0-alpha.172.111 — Standalone batch parse 17 capitolati esempio.

Bypassa HTTP (timeout uvicorn) e fa parsing diretto via DB session.
Salva DeliveryTemplate per ciascun file estraibile. Skip idempotente
per source_document_name già parsato. Stampa progresso per-file con
confidence + tempo + tokens.

Uso:
    .venv/Scripts/python.exe scripts/batch_parse_capitolati.py [--dry] [--user-id 1]

Default user_id=1 (admin). --dry stampa risultati senza salvare.
"""
from __future__ import annotations
import argparse, time, sys, json
from pathlib import Path

# Bootstrap import path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.models import DeliveryTemplate
from app.services.ai_provider import get_provider_for_user, get_provider
from app.services.deliverables_parser import (
    extract_text_from_file, parse_delivery_template,
)

SAMPLES_DIR = ROOT / "docs" / "capitolati_esempio"
CURRENT_TENANT = 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Dry-run: no DB save")
    ap.add_argument("--user-id", type=int, default=1, help="Provider per-user (default admin id=1)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        provider = get_provider_for_user(args.user_id, db) or get_provider()
        if not provider:
            print("ERR: nessun provider AI configurato.")
            return 1
        print(f"Provider: {provider.name}")
        print(f"Samples dir: {SAMPLES_DIR}")
        print(f"Dry-run: {args.dry}")
        print()

        existing = {
            t.source_document_name for t in
            db.query(DeliveryTemplate.source_document_name).filter(
                DeliveryTemplate.source_document_name.isnot(None),
                DeliveryTemplate.tenant_id == CURRENT_TENANT,
            ).all() if t.source_document_name
        }

        allowed_ext = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}
        files = sorted([p for p in SAMPLES_DIR.iterdir()
                        if p.is_file() and p.suffix.lower() in allowed_ext])
        print(f"Trovati {len(files)} file. Già parsati: {len(existing)}")
        print()

        stats = {"saved": 0, "dry": 0, "skipped": 0, "errors": 0}

        for idx, fpath in enumerate(files, 1):
            label = f"[{idx}/{len(files)}] {fpath.name[:65]:65}"
            if fpath.name in existing:
                print(f"{label} SKIP (già parsato)")
                stats["skipped"] += 1
                continue
            t0 = time.time()
            content = fpath.read_bytes()
            if len(content) == 0:
                print(f"{label} ERR file vuoto (0 byte)")
                stats["errors"] += 1
                continue
            text = extract_text_from_file(content, fpath.name)
            text_len = len(text.strip())
            if text_len < 20:
                print(f"{label} ERR testo non estraibile ({text_len} char)")
                stats["errors"] += 1
                continue
            try:
                result = parse_delivery_template(text, provider=provider)
            except Exception as e:
                print(f"{label} ERR provider exception: {e}")
                stats["errors"] += 1
                continue
            dt = time.time() - t0
            if not result:
                diag = getattr(provider, "last_extract_diag", None) or {}
                print(f"{label} ERR AI ({dt:.1f}s) {diag.get('stage','?')}: {diag.get('error','no msg')[:80]}")
                stats["errors"] += 1
                continue
            conf = result.get("ai_confidence", "?")
            code = (result.get("code") or "").strip().upper() or f"AI-{fpath.stem[:30]}".upper()
            name = (result.get("name") or "").strip() or fpath.stem
            broadcaster = result.get("broadcaster", "")
            if args.dry:
                print(f"{label} OK  ({dt:.1f}s) conf={conf} code={code} broadcaster={broadcaster}")
                stats["dry"] += 1
                continue
            # Check code collision per-tenant
            existing_code = db.query(DeliveryTemplate).filter(
                DeliveryTemplate.tenant_id == CURRENT_TENANT,
                DeliveryTemplate.code == code,
            ).first()
            if existing_code:
                code = f"{code}-{fpath.stem[:10].upper()}"
            try:
                tpl = DeliveryTemplate(
                    tenant_id=CURRENT_TENANT,
                    code=code, name=name,
                    broadcaster=broadcaster or None,
                    description=result.get("description"),
                    version=result.get("version", "1.0"),
                    video_specs=result.get("video_specs"),
                    audio_specs=result.get("audio_specs"),
                    text_specs=result.get("text_specs"),
                    head_format=result.get("head_format"),
                    textless_format=result.get("textless_format"),
                    naming_convention=result.get("naming_convention"),
                    archive_specs=result.get("archive_specs"),
                    metadata_requirements=result.get("metadata_requirements"),
                    suggested_items=result.get("suggested_items"),
                    source_document_name=fpath.name,
                    ai_generated=True,
                    ai_confidence=conf,
                )
                db.add(tpl)
                db.commit()
                db.refresh(tpl)
                print(f"{label} OK  ({dt:.1f}s) conf={conf} id={tpl.id} code={code}")
                stats["saved"] += 1
            except Exception as e:
                db.rollback()
                print(f"{label} ERR save: {str(e)[:100]}")
                stats["errors"] += 1

        print()
        print("=" * 80)
        print(f"FINE: saved={stats['saved']} dry={stats['dry']} skipped={stats['skipped']} errors={stats['errors']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
