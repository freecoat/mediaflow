"""
MediaFlow — Migrazione Bundle I (v3.5.0-alpha.172.89)
Stati nested Deliverable + cascade QC reject.

Aggiunge:
  - job_deliverables.qc_substatus (VARCHAR 20 NULL)
  - assets.status (VARCHAR 20 NOT NULL DEFAULT 'planned')
  - INDEX ix_deliverables_status_substatus (status, qc_substatus)
  - INDEX ix_assets_tenant_status (tenant_id, status)

Mappa enum DeliverableStatus legacy → nuovi 5 valori + qc_substatus:
  in_production / file_attached  →  in_progress
  qc_running                     →  qc + qc_substatus=in_progress
  qc_passed                      →  qc + qc_substatus=passed
  qc_failed                      →  qc + qc_substatus=rejected
  accepted                       →  closed
  rejected                       →  delivered (riapertura, non closed)
  planned / delivered            →  invariati

Backfill Asset.status:
  file_path valorizzato → uploaded
  else                  → planned

Idempotente: solo ALTER su colonne mancanti + UPDATE su valori legacy.
Esegui dopo aver pull-ato il codice:

  python scripts/migrate_phase_i_deliverable_status.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from app.database import engine, create_tables


STATUS_MAP = [
    ("in_production", "in_progress", None),
    ("file_attached", "in_progress", None),
    ("qc_running",    "qc",          "in_progress"),
    ("qc_passed",     "qc",          "passed"),
    ("qc_failed",     "qc",          "rejected"),
    ("accepted",      "closed",      None),
    ("rejected",      "delivered",   None),
]


def _col_exists(conn, table, col):
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def main():
    print("[bundle-i] inizio migrazione stati nested deliverable")
    create_tables()
    with engine.begin() as conn:
        # 1. ALTER TABLE job_deliverables ADD qc_substatus
        if not _col_exists(conn, "job_deliverables", "qc_substatus"):
            conn.execute(text(
                "ALTER TABLE job_deliverables ADD COLUMN qc_substatus VARCHAR(20) NULL"
            ))
            print("  + job_deliverables.qc_substatus aggiunta")
        else:
            print("  = job_deliverables.qc_substatus gia' presente")

        # 2. ALTER TABLE assets ADD status
        if not _col_exists(conn, "assets", "status"):
            conn.execute(text(
                "ALTER TABLE assets ADD COLUMN status VARCHAR(20) "
                "NOT NULL DEFAULT 'planned'"
            ))
            print("  + assets.status aggiunta (default 'planned')")
        else:
            print("  = assets.status gia' presente")

        # 3. Mapping enum legacy
        total_updated = 0
        for old, new_main, new_sub in STATUS_MAP:
            if new_sub:
                res = conn.execute(text(
                    "UPDATE job_deliverables SET status=:nm, qc_substatus=:ns "
                    "WHERE status=:old"
                ), {"nm": new_main, "ns": new_sub, "old": old})
            else:
                res = conn.execute(text(
                    "UPDATE job_deliverables SET status=:nm, qc_substatus=NULL "
                    "WHERE status=:old"
                ), {"nm": new_main, "old": old})
            if res.rowcount:
                tag = f"{new_main}+{new_sub}" if new_sub else new_main
                print(f"  > {res.rowcount:>4} deliverable.status {old} -> {tag}")
                total_updated += res.rowcount
        if total_updated == 0:
            print("  = nessun deliverable con status legacy (gia' mappato)")

        # 4. Backfill Asset.status: file_path valorizzato -> uploaded
        res = conn.execute(text(
            "UPDATE assets SET status='uploaded' "
            "WHERE status='planned' AND file_path IS NOT NULL AND file_path != ''"
        ))
        if res.rowcount:
            print(f"  > {res.rowcount} asset.status planned -> uploaded (file_path presente)")
        else:
            print("  = nessun asset da promuovere a uploaded")

        # 5. Indici
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_deliverables_status_substatus "
            "ON job_deliverables(status, qc_substatus)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_assets_tenant_status "
            "ON assets(tenant_id, status)"
        ))
        print("  + indici verificati / creati")

    # 6. Riepilogo
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT status, qc_substatus, COUNT(*) "
            "FROM job_deliverables "
            "GROUP BY status, qc_substatus "
            "ORDER BY status, qc_substatus"
        )).fetchall()
        print("\n[riepilogo deliverable]")
        for st, sub, n in rows:
            sub_lbl = f"+{sub}" if sub else ""
            print(f"  {st}{sub_lbl}: {n}")
        rows = conn.execute(text(
            "SELECT status, COUNT(*) FROM assets GROUP BY status ORDER BY status"
        )).fetchall()
        print("\n[riepilogo asset]")
        for st, n in rows:
            print(f"  {st}: {n}")
    print("\n[bundle-i] migrazione completata")


if __name__ == "__main__":
    main()
