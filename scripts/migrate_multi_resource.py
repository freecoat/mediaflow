"""
MediaFlow — migrazione multi-resource booking (v3.4.16)

Booking diventa un contenitore di N risorse, ognuna con il proprio intervallo.
Le assegnazioni vivono nella nuova tabella `booking_assignments`.
`Booking.resource_id` viene rimosso.

Cambiamenti:
1. CREATE TABLE booking_assignments (id, booking_id, resource_id, start, end)
2. INSERT INTO booking_assignments → 1 riga per ogni Booking esistente
   (resource_id, start, end ereditati dal booking)
3. Drop column bookings.resource_id via recreate-table dance (SQLite)

Idempotente: se la tabella esiste già non la ricrea; se resource_id già
rimosso non fa nulla.

Esegui:
  python scripts/migrate_multi_resource.py
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
# Import per registrare i modelli su Base.metadata
from app.models import Booking, BookingAssignment, Resource  # noqa: F401


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def table_exists(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def migrate():
    print("▸ MediaFlow · migrazione multi-resource booking (v3.4.16)")
    print("─" * 70)

    create_tables()  # Crea booking_assignments se non esiste (via Base.metadata)
    db = SessionLocal()
    try:
        # 1. Verifica tabella booking_assignments creata
        if not table_exists("booking_assignments"):
            print("▸ Tabella booking_assignments mancante anche dopo create_tables, abort.")
            return
        print("  ✓ tabella booking_assignments presente")

        # 2. Popola da Booking esistenti SOLO se la colonna resource_id esiste ancora
        if column_exists("bookings", "resource_id"):
            existing = db.execute(text("SELECT COUNT(*) FROM booking_assignments")).scalar()
            print(f"  · booking_assignments contiene {existing} righe")
            if existing == 0:
                # Popolazione iniziale
                rows = db.execute(text("""
                    SELECT id, resource_id, start_datetime, end_datetime
                    FROM bookings
                    WHERE resource_id IS NOT NULL
                """)).fetchall()
                print(f"▸ Popolamento booking_assignments da {len(rows)} Booking esistenti")
                for r in rows:
                    db.execute(text("""
                        INSERT INTO booking_assignments
                            (booking_id, resource_id, start_datetime, end_datetime)
                        VALUES (:bid, :rid, :s, :e)
                    """), {"bid": r[0], "rid": r[1], "s": r[2], "e": r[3]})
                db.commit()
                print(f"  ✓ {len(rows)} assignments creati")
            else:
                print("  ✓ booking_assignments già popolata, salto seed")

            # 3. Drop column bookings.resource_id (recreate-table SQLite)
            print("▸ Recreate-table dance per rimuovere bookings.resource_id")
            db.execute(text("PRAGMA foreign_keys = OFF"))

            db.execute(text("""
                CREATE TABLE bookings_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL DEFAULT 1,
                    job_id INTEGER NULL,
                    job_cost_line_id INTEGER NULL,
                    start_datetime DATETIME NOT NULL,
                    end_datetime DATETIME NOT NULL,
                    status VARCHAR(9) NOT NULL DEFAULT 'tentative',
                    kind TEXT NOT NULL DEFAULT 'project',
                    notes TEXT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants(id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id),
                    FOREIGN KEY(job_cost_line_id) REFERENCES job_cost_lines(id)
                )
            """))
            new_cols = ["id", "tenant_id", "job_id", "job_cost_line_id",
                        "start_datetime", "end_datetime", "status", "kind", "notes", "created_at"]
            common_str = ", ".join(new_cols)
            db.execute(text(f"INSERT INTO bookings_new ({common_str}) SELECT {common_str} FROM bookings"))
            db.execute(text("DROP TABLE bookings"))
            db.execute(text("ALTER TABLE bookings_new RENAME TO bookings"))
            db.execute(text("CREATE INDEX ix_bookings_id ON bookings(id)"))
            db.execute(text("CREATE INDEX ix_bookings_tenant_id ON bookings(tenant_id)"))
            db.execute(text("CREATE INDEX ix_bookings_job_id ON bookings(job_id)"))
            db.execute(text("CREATE INDEX ix_bookings_job_cost_line_id ON bookings(job_cost_line_id)"))
            db.execute(text("PRAGMA foreign_keys = ON"))
            db.commit()
            print("  ✓ bookings.resource_id rimosso, schema bookings ricreato")
        else:
            print("  ✓ bookings.resource_id già rimosso")

        # 4. Verifica finale
        n_b = db.execute(text("SELECT COUNT(*) FROM bookings")).scalar()
        n_a = db.execute(text("SELECT COUNT(*) FROM booking_assignments")).scalar()
        print(f"  · {n_b} bookings, {n_a} assignments")

        print("─" * 70)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
