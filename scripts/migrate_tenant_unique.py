"""Migrazione tenant-unique + FK index — v3.5.0-alpha.172.142.

Chiude due finding dell'audit multi-agent (30 mag 2026):

1. FK senza indice (P2 perf) — SAFE, eseguito di default:
   crea gli indici mancanti sulle FK self-referencing di Quote/QuoteLine e
   su JobResourceAssignment(job_id, resource_id). Idempotente, non distruttivo,
   eseguibile anche in produzione a caldo.

2. UNIQUE globale → UNIQUE(tenant_id, code|number) (P1 multi-tenant) — RISKY,
   eseguito SOLO con --rebuild-unique:
   projects.code / jobs.code / quotes.number hanno un vincolo UNIQUE GLOBALE
   (collisione cross-tenant in multi-tenant beta). SQLite non supporta DROP
   CONSTRAINT → serve rebuild tabella. Operazione pesante (FK incrociate su
   quotes) → da fare PRIMA della beta multi-tenant, con snapshot DB fresco.
   In single-tenant (tenant_id sempre =1) il vincolo globale è equivalente al
   composito, quindi nessuna urgenza finché esiste un solo tenant.

Uso:
    .venv/Scripts/python.exe scripts/migrate_tenant_unique.py            # solo indici (safe)
    .venv/Scripts/python.exe scripts/migrate_tenant_unique.py --rebuild-unique  # + rebuild (beta)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "mediaflow.db"

# (index_name, table, columns) — idempotente via IF NOT EXISTS
FK_INDEXES = [
    ("ix_quotes_parent_quote_id", "quotes", "parent_quote_id"),
    ("ix_quotes_superseded_by_id", "quotes", "superseded_by_id"),
    ("ix_quotes_merged_into_quote_id", "quotes", "merged_into_quote_id"),
    ("ix_quote_lines_parent_line_id", "quote_lines", "parent_line_id"),
    ("ix_job_resource_assignments_job_id", "job_resource_assignments", "job_id"),
    ("ix_job_resource_assignments_resource_id", "job_resource_assignments", "resource_id"),
]


def create_fk_indexes(con: sqlite3.Connection) -> int:
    cur = con.cursor()
    existing_tables = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    n = 0
    for idx, table, col in FK_INDEXES:
        if table not in existing_tables:
            print(f"  skip {idx}: tabella {table} assente")
            continue
        cols = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            print(f"  skip {idx}: colonna {table}.{col} assente")
            continue
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON {table}({col})")
        print(f"  ok   {idx} ON {table}({col})")
        n += 1
    con.commit()
    return n


def _has_global_unique(con: sqlite3.Connection, table: str, col: str) -> bool:
    """True se esiste un autoindex UNIQUE su (col) singola (vincolo globale)."""
    cur = con.cursor()
    for r in cur.execute(f"PRAGMA index_list({table})").fetchall():
        # r = (seq, name, unique, origin, partial)
        name, unique = r[1], r[2]
        if not unique:
            continue
        idx_cols = [c[2] for c in cur.execute(f"PRAGMA index_info({name})").fetchall()]
        if idx_cols == [col]:
            return True
    return False


def rebuild_unique(con: sqlite3.Connection) -> None:
    """Rebuild projects/jobs/quotes per spostare UNIQUE globale → composito.

    ATTENZIONE: pesante. Esegui con snapshot DB fresco. Lo facciamo con
    `PRAGMA legacy_alter_table` + rinomina così gli FK esterni (jobs.quote_id,
    quote_lines.quote_id, ...) restano validi puntando alla tabella rinominata.
    """
    print("\n[--rebuild-unique] Rebuild tabelle per UNIQUE composito…")
    print("  PREREQUISITO: snapshot DB fresco. Interrompi ora se non l'hai fatto.")
    targets = [
        ("projects", "code", "uq_project_tenant_code"),
        ("jobs", "code", "uq_job_tenant_code"),
        ("quotes", "number", "uq_quote_tenant_number"),
    ]
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")
    for table, col, uqname in targets:
        if not _has_global_unique(con, table, col):
            print(f"  skip {table}.{col}: nessun UNIQUE globale (già migrato?)")
            continue
        # SQLite: il modo robusto di rimuovere un autoindex UNIQUE singolo è
        # ricreare la tabella. Qui usiamo l'approccio "12-step" semplificato:
        # poiché il vincolo è un autoindex, in pratica conviene fare il rebuild
        # via dump dello schema. Per sicurezza NON automatizziamo il rebuild
        # completo qui: stampiamo le istruzioni e lasciamo il rebuild manuale
        # assistito (le tabelle hanno 40+ colonne + FK incrociate).
        print(f"  ATTENZIONE {table}.{col}: rebuild manuale richiesto.")
        print(f"    1) CREATE TABLE {table}_new (...schema da models.py con")
        print(f"       UNIQUE(tenant_id,{col}) e SENZA unique sul solo {col});")
        print(f"    2) INSERT INTO {table}_new SELECT * FROM {table};")
        print(f"    3) DROP TABLE {table}; ALTER TABLE {table}_new RENAME TO {table};")
        print(f"    4) ricrea indici; constraint name atteso: {uqname}")
    cur.execute("PRAGMA foreign_keys=ON")
    print("  NB: rebuild non eseguito automaticamente (troppo rischioso senza")
    print("      review per-tabella). Vedi STATO.md voce 'beta multi-tenant'.")


def main() -> None:
    if not DB.exists():
        print(f"DB non trovato: {DB}")
        sys.exit(1)
    con = sqlite3.connect(str(DB))
    print(f"DB: {DB}")
    print("[1] Creazione indici FK mancanti (safe)…")
    n = create_fk_indexes(con)
    print(f"    {n} indici verificati/creati.")
    if "--rebuild-unique" in sys.argv:
        rebuild_unique(con)
    else:
        print("\n[2] UNIQUE composito: SKIP (passa --rebuild-unique per istruzioni).")
        print("    In single-tenant non è urgente (tenant_id sempre =1).")
    con.close()
    print("\nFatto.")


if __name__ == "__main__":
    main()
