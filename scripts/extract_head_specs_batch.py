"""v3.5.0-alpha.172.128 — Batch estrazione head-specs sui capitolati attivi.
Uso:
  .venv/Scripts/python.exe scripts/extract_head_specs_batch.py --dry-run
  .venv/Scripts/python.exe scripts/extract_head_specs_batch.py --only RAI-SDHDUHD-1.4
  .venv/Scripts/python.exe scripts/extract_head_specs_batch.py            # applica a tutti
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.models import DeliveryTemplate
from app.services.ai_provider import get_provider_for_user
from app.services.capitolato_head_extractor import (
    render_document_for_llm, extract_head_specs, apply_head_specs,
)
from app.routers.delivery_items import _resolve_capitolato_path
from app.context import current_tenant_id


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None, help="CSV di code template")
    ap.add_argument("--user-id", type=int, default=1)
    args = ap.parse_args()

    db = SessionLocal()
    tid = 1
    provider = get_provider_for_user(args.user_id, db)
    if not provider:
        print("[ERR] nessun provider AI per user", args.user_id); return 1
    only = set(args.only.split(",")) if args.only else None
    q = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.tenant_id == tid,
        DeliveryTemplate.is_active == True)  # noqa: E712
    print(f"{'CODE':32} {'mode':7} {'tc':12} {'segs':>4} {'presets':>8} {'sugg':>4}")
    for t in q.all():
        if only and t.code not in only:
            continue
        path = _resolve_capitolato_path(t)
        if not path:
            print(f"{t.code:32} SKIP (no source)"); continue
        rendered = render_document_for_llm(path.read_bytes(), path.name)
        parsed = extract_head_specs(provider, rendered, t.broadcaster or t.code, db, tid)
        if args.dry_run:
            print(f"{t.code:32} {rendered.get('mode'):7} {str(parsed.get('default_tc_start')):12} "
                  f"{len(parsed.get('timeline_segments') or []):>4} {len(parsed.get('audio_config_codes') or []):>8} "
                  f"{len(parsed.get('suggested_taxonomy') or []):>4}")
            print("   PREVIEW:", json.dumps(parsed, ensure_ascii=False)[:500])
        else:
            s = apply_head_specs(db, t.id, parsed, tid)
            db.commit()
            print(f"{t.code:32} {rendered.get('mode'):7} {str(parsed.get('default_tc_start')):12} "
                  f"{s['segments_n']:>4} {s['presets_created']+s['presets_updated']:>8} {len(s['suggested_taxonomy']):>4}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
