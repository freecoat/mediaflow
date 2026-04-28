"""
MediaFlow — migrazione: Booking.tenant_id

Aggiunge `tenant_id INTEGER NOT NULL DEFAULT 1` su `bookings` e backfilla
tutti i record esistenti a tenant_id=1 (il tenant default Fase 1-bis).

Allinea Booking alla convenzione multi-tenant soft del resto del modello.

Idempotente: se la colonna esiste già non fa nulla.

Esegui:
  python scripts/migrate_booking_tenant.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect, text
from app.database import SessionLocal, engine, create_tables


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · migrazione tenant_id su bookings")
    print("─" * 60)

    create_tables()
    db = SessionLocal()
    try:
        if not column_exists("bookings", "tenant_id"):
            print("▸ ALTER TABLE bookings ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1")
            db.execute(text(
                "ALTER TABLE bookings ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
            ))
            db.commit()
            print("  ✓ aggiunta")
            existing = db.execute(text(
                "SELECT COUNT(*) FROM bookings WHERE tenant_id = 1"
            )).scalar()
            print(f"  ✓ {existing} booking esistenti assegnati a tenant_id=1")
        else:
            print("  ✓ tenant_id già presente")

        print("─" * 60)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
