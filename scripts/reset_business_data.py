"""
MediaFlow — reset business data (v3.4.49).

Pulisce il database delle entità "business" per ripartire con un setup pulito
mantenendo listino, utenti, ruoli, reparti, tenant, policy ore, AI settings.

Cancella (in ordine FK-safe):
  - notifications, ai_actions
  - ai_messages, ai_conversations
  - booking_changes, booking_assignments, bookings
  - time_punches, timesheets, job_resource_assignments
  - expenses, invoice_lines, invoices
  - asset_tags, assets, project_tech_sheets
  - job_cost_lines, jobs
  - quote_lines, quotes
  - projects
  - clients
  - resource_unavailabilities, resources

Mantiene:
  - users, roles
  - tenants, departments
  - price_categories, price_items
  - delivery_templates
  - working_hours_policies
  - user_ai_settings
  - tags

Idempotente. In transazione: rollback su errore. Resetta sqlite_sequence
per le tabelle pulite (ID ripartono da 1).

Esegui:
  python scripts/reset_business_data.py        # chiede conferma
  python scripts/reset_business_data.py --yes  # senza conferma (per strumenti)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text, inspect
from app.database import engine

# Ordine FK-safe: foglie → radici
TABLES_TO_PURGE = [
    "notifications",
    "ai_actions",
    "ai_messages",
    "ai_conversations",
    "booking_changes",
    "booking_assignments",
    "bookings",
    "time_punches",
    "timesheets",
    "job_resource_assignments",
    "expenses",
    "invoice_lines",
    "invoices",
    "asset_tags",
    "assets",
    "project_tech_sheets",
    "job_cost_lines",
    "jobs",
    "quote_lines",
    "quotes",
    "projects",
    "clients",
    "resource_unavailabilities",
    "resources",
]

PRESERVED = [
    "users", "roles",
    "tenants", "departments",
    "price_categories", "price_items",
    "delivery_templates",
    "working_hours_policies",
    "user_ai_settings",
    "tags",
]


def _count_rows(conn, table_name: str) -> int:
    try:
        r = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        return int(r or 0)
    except Exception:
        return -1


def reset(confirm: bool = False) -> int:
    print("▸ MediaFlow · Reset business data (v3.4.49)")
    print("─" * 70)

    insp = inspect(engine)
    existing = set(insp.get_table_names())

    # Counter prima
    print("\n[BEFORE]")
    with engine.connect() as conn:
        for t in TABLES_TO_PURGE:
            if t in existing:
                c = _count_rows(conn, t)
                print(f"  {t:36s} {c:>6d} rows")
            else:
                print(f"  {t:36s} (table missing — skip)")
    print("\n[PRESERVED — non toccate]")
    with engine.connect() as conn:
        for t in PRESERVED:
            if t in existing:
                c = _count_rows(conn, t)
                print(f"  {t:36s} {c:>6d} rows")

    if not confirm:
        print("\n" + "─" * 70)
        ans = input("Confermi cancellazione? Scrivi 'YES' per procedere: ").strip()
        if ans != "YES":
            print("Annullato. Nessuna modifica.")
            return 1

    deleted = {}
    failed = []
    has_sqlite_sequence = "sqlite_sequence" in existing

    with engine.begin() as conn:
        for t in TABLES_TO_PURGE:
            if t not in existing:
                continue
            try:
                # Conta prima della cancellazione
                pre = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0
                if pre > 0:
                    conn.execute(text(f"DELETE FROM {t}"))
                deleted[t] = pre
                if has_sqlite_sequence:
                    conn.execute(
                        text("DELETE FROM sqlite_sequence WHERE name = :n").bindparams(n=t)
                    )
            except Exception as e:
                failed.append((t, str(e)))

    print("\n" + "─" * 70)
    print("[DELETED]")
    total = 0
    for t, n in deleted.items():
        if n > 0:
            print(f"  {t:36s} {n:>6d} righe cancellate")
            total += n
    if not deleted:
        print("  (nulla da cancellare)")
    print(f"\n  TOTALE: {total} righe cancellate")

    if failed:
        print("\n[ERRORI]")
        for t, err in failed:
            print(f"  ✗ {t}: {err}")
        return 2

    print("\n✔ Reset completato. Database pronto per setup pulito.")
    print("  Listino + utenti + reparti + AI settings preservati.")
    return 0


if __name__ == "__main__":
    confirmed = "--yes" in sys.argv or "-y" in sys.argv
    sys.exit(reset(confirm=confirmed))
