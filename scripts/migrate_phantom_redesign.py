"""MediaFlow — migrate_phantom_redesign (v3.5.0-alpha.171 Sprint 2 Step 1).

Migration idempotente per la riarchitettura Phantom Quote → "Quotazione a
Consuntivo":

1. ALTER TABLE quotes ADD COLUMN phantom_status VARCHAR(20) NULL
2. ALTER TABLE quotes ADD COLUMN merged_into_quote_id INTEGER NULL
3. Backfill: phantom_status='standby' su tutte le Quote con is_phantom=True
4. Partial unique index sul phantom standby per progetto:
   uq_phantom_standby_per_project ON quotes(tenant_id, project_id)
   WHERE is_phantom = 1 AND phantom_status = 'standby' AND deleted_at IS NULL

Re-run: no-op se già applicato.

Uso:
  .venv/Scripts/python.exe scripts/migrate_phantom_redesign.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text, inspect  # noqa: E402
from app.database import engine  # noqa: E402


def _table_has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def _index_exists(conn, name: str) -> bool:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
        {"n": name},
    ).fetchall()
    return len(rows) > 0


def migrate():
    print("[migrate_phantom_redesign] start")
    with engine.begin() as conn:
        if not _table_has_column(conn, "quotes", "phantom_status"):
            print("  ALTER TABLE quotes ADD COLUMN phantom_status VARCHAR(20)")
            conn.execute(text("ALTER TABLE quotes ADD COLUMN phantom_status VARCHAR(20)"))
        else:
            print("  - phantom_status already present")

        if not _table_has_column(conn, "quotes", "merged_into_quote_id"):
            print("  ALTER TABLE quotes ADD COLUMN merged_into_quote_id INTEGER")
            conn.execute(text("ALTER TABLE quotes ADD COLUMN merged_into_quote_id INTEGER"))
        else:
            print("  - merged_into_quote_id already present")

        # Backfill: phantom esistenti → standby (se phantom_status NULL).
        # Non tocca eventuali manualmente settate.
        result = conn.execute(text(
            "UPDATE quotes SET phantom_status='standby' "
            "WHERE is_phantom = 1 AND phantom_status IS NULL"
        ))
        print(f"  Backfilled {result.rowcount} phantom Quote(s) to status=standby")

        # Partial unique index per garantire 1 phantom standby per (tenant, project).
        # SQLite supporta WHERE su CREATE UNIQUE INDEX.
        if not _index_exists(conn, "uq_phantom_standby_per_project"):
            print("  CREATE UNIQUE INDEX uq_phantom_standby_per_project")
            conn.execute(text(
                "CREATE UNIQUE INDEX uq_phantom_standby_per_project "
                "ON quotes(tenant_id, project_id) "
                "WHERE is_phantom = 1 AND phantom_status = 'standby' "
                "AND deleted_at IS NULL"
            ))
        else:
            print("  - uq_phantom_standby_per_project already present")

        # Index su phantom_status per query efficienti
        if not _index_exists(conn, "ix_quotes_phantom_status"):
            print("  CREATE INDEX ix_quotes_phantom_status")
            conn.execute(text(
                "CREATE INDEX ix_quotes_phantom_status ON quotes(phantom_status)"
            ))
        else:
            print("  - ix_quotes_phantom_status already present")

    print("[migrate_phantom_redesign] done")


if __name__ == "__main__":
    migrate()
