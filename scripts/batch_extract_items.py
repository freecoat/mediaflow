"""v3.5.0-alpha.172.115 — Standalone batch re-parse 13 capitolati esistenti per
estrazione DeliveryItem strutturati via parser v2.

Per ogni DeliveryTemplate con `source_document_name` valido + file fisicamente
presente in docs/capitolati_esempio/:
- Estrai testo via extract_text_from_file
- Esegui parse_delivery_items_v2 (pass 1 + pass 2)
- Materialize items + audio_tracks idempotente (skip name duplicati)

Costo stimato: ~30s pass1 + ~60-90s pass2 per template = ~20-25 min totali Claude.

Uso:
    .venv/Scripts/python.exe scripts/batch_extract_items.py
    .venv/Scripts/python.exe scripts/batch_extract_items.py --only RAI-SDHDUHD-1.4 MUBI-FEATURE-DELIVERY
    .venv/Scripts/python.exe scripts/batch_extract_items.py --user-id 1
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.models import DeliveryTemplate, DeliveryItem
from app.services.ai_provider import get_provider_for_user, get_provider
from app.services.deliverables_parser import extract_text_from_file
from app.services.delivery_items_parser import (
    parse_delivery_items_v2, materialize_items,
)

SAMPLES_DIR = ROOT / "docs" / "capitolati_esempio"
CURRENT_TENANT = 1


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, default=1)
    ap.add_argument("--only", nargs="*", default=None,
                    help="Limita ai code template indicati (es. RAI-SDHDUHD-1.4)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        provider = get_provider_for_user(args.user_id, db) or get_provider()
        if not provider:
            print("ERR: nessun provider AI configurato.")
            return 1
        print(f"Provider: {provider.name}")

        q = db.query(DeliveryTemplate).filter(
            DeliveryTemplate.tenant_id == CURRENT_TENANT,
            DeliveryTemplate.is_active == True,  # noqa: E712
            DeliveryTemplate.source_document_name.isnot(None),
        )
        if args.only:
            q = q.filter(DeliveryTemplate.code.in_(args.only))
        templates = q.order_by(DeliveryTemplate.id).all()
        print(f"Templates da processare: {len(templates)}\n")

        stats = {"saved": 0, "skipped": 0, "errors": 0}
        for idx, tpl in enumerate(templates, 1):
            label = f"[{idx}/{len(templates)}] #{tpl.id} {tpl.code[:35]:35}"
            fpath = (SAMPLES_DIR / tpl.source_document_name).resolve()
            if not fpath.is_file():
                print(f"{label} ERR source_document_name manca: {tpl.source_document_name}")
                stats["errors"] += 1
                continue
            existing_items = db.query(DeliveryItem).filter(
                DeliveryItem.delivery_template_id == tpl.id,
                DeliveryItem.tenant_id == CURRENT_TENANT,
            ).count()
            if existing_items > 0:
                print(f"{label} SKIP (ha gia' {existing_items} items)")
                stats["skipped"] += 1
                continue
            t0 = time.time()
            content = fpath.read_bytes()
            text = extract_text_from_file(content, tpl.source_document_name)
            if not text or len(text.strip()) < 20:
                print(f"{label} ERR testo non estraibile ({len(text.strip())} char)")
                stats["errors"] += 1
                continue
            try:
                parsed = parse_delivery_items_v2(text, db, tenant_id=CURRENT_TENANT, provider=provider)
            except Exception as e:
                print(f"{label} ERR provider exception: {e}")
                stats["errors"] += 1
                continue
            dt = time.time() - t0
            if not parsed:
                diag = getattr(provider, "last_extract_diag", {}) or {}
                print(f"{label} ERR parser ({dt:.1f}s) {diag.get('stage','?')}: {diag.get('error','no msg')[:80]}")
                stats["errors"] += 1
                continue
            saved, skip = materialize_items(db, tpl.id, parsed, tenant_id=CURRENT_TENANT)
            n_extracted = len(parsed.get("items") or [])
            print(f"{label} OK ({dt:.0f}s) extracted={n_extracted} saved={saved} skip={skip}")
            stats["saved"] += saved
        print()
        print("=" * 80)
        print(f"FINE batch: saved={stats['saved']} skipped_tpl={stats['skipped']} errors={stats['errors']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
