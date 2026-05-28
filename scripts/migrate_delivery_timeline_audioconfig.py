"""v3.5.0-alpha.172.127 — Migrazione timeline/TC + audio_config_presets.

Idempotente: ALTER TABLE ADD COLUMN guardati da introspection, CREATE tabella
via create_all, backfill default_* dei template da head_format esistente.

Uso: .venv/Scripts/python.exe scripts/migrate_delivery_timeline_audioconfig.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from app.database import engine, SessionLocal
from app.models.models import Base, DeliveryTemplate

ITEM_COLS = [
    ("tc_start", "VARCHAR(20) NULL"),
    ("program_start", "VARCHAR(20) NULL"),
    ("timeline_segments", "JSON NULL"),
    ("audio_config_preset_id", "INTEGER NULL"),
    ("audio_config_code", "VARCHAR(40) NULL"),
]
TEMPLATE_COLS = [
    ("default_tc_start", "VARCHAR(20) NULL"),
    ("default_program_start", "VARCHAR(20) NULL"),
    ("default_timeline_segments", "JSON NULL"),
]


def _add_cols(table, coldefs):
    insp = inspect(engine)
    existing = {c["name"] for c in insp.get_columns(table)}
    with engine.begin() as conn:
        for col, ddl in coldefs:
            if col not in existing:
                print(f"  + {table}.{col}")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def _backfill_template_defaults(db):
    """Promuove head_format → default_tc_start/program_start dei template."""
    n = 0
    for t in db.query(DeliveryTemplate).all():
        hf = t.head_format or {}
        if not isinstance(hf, dict):
            continue
        changed = False
        if not t.default_tc_start and hf.get("timecode_start"):
            t.default_tc_start = str(hf["timecode_start"])[:20]
            changed = True
        if not t.default_program_start and hf.get("program_start"):
            t.default_program_start = str(hf["program_start"])[:20]
            changed = True
        if changed:
            n += 1
    db.commit()
    return n


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("-> create_all (crea audio_config_presets se mancante)...")
    Base.metadata.create_all(bind=engine)
    print("-> ALTER colonne delivery_items / delivery_templates...")
    _add_cols("delivery_items", ITEM_COLS)
    _add_cols("delivery_templates", TEMPLATE_COLS)
    db = SessionLocal()
    try:
        n = _backfill_template_defaults(db)
        print(f"-> backfill default da head_format: {n} template aggiornati")
    finally:
        db.close()
    print("[OK] migrazione completata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
