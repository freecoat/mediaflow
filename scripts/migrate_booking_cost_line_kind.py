"""
MediaFlow — migrazione: Booking.kind + job_cost_line_id, TimePunch.job_cost_line_id
e rilassamento di Booking.job_id da NOT NULL a NULL (per booking interni).

Cambiamenti
1. ALTER TABLE bookings ADD COLUMN kind TEXT NOT NULL DEFAULT 'project'
2. ALTER TABLE bookings ADD COLUMN job_cost_line_id INTEGER NULL
3. ALTER TABLE time_punches ADD COLUMN job_cost_line_id INTEGER NULL
4. Rilassare bookings.job_id NOT NULL → NULL (richiede recreate-table su SQLite)

SQLite non supporta ALTER COLUMN per cambiare nullabilità → la tabella va
ricreata (rename + create + copy + drop). Idempotente: se job_id è già
nullable, salta il passo 4.

Esegui:
  python scripts/migrate_booking_cost_line_kind.py
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
# Import necessario per registrare i modelli su Base.metadata
from app.models import Booking, TimePunch  # noqa: F401


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def column_is_nullable(table: str, column: str) -> bool:
    cols = inspect(engine).get_columns(table)
    for c in cols:
        if c["name"] == column:
            return bool(c.get("nullable", False))
    return True


def migrate():
    print("▸ MediaFlow · migrazione Booking.kind/cost_line + TimePunch.cost_line + job_id nullable")
    print("─" * 70)

    create_tables()
    db = SessionLocal()
    try:
        # 1. bookings.kind
        if not column_exists("bookings", "kind"):
            print("▸ ALTER TABLE bookings ADD COLUMN kind TEXT NOT NULL DEFAULT 'project'")
            db.execute(text("ALTER TABLE bookings ADD COLUMN kind TEXT NOT NULL DEFAULT 'project'"))
            db.commit()
            print("  ✓ aggiunta")
        else:
            print("  ✓ bookings.kind già presente")

        # 2. bookings.job_cost_line_id
        if not column_exists("bookings", "job_cost_line_id"):
            print("▸ ALTER TABLE bookings ADD COLUMN job_cost_line_id INTEGER NULL")
            db.execute(text("ALTER TABLE bookings ADD COLUMN job_cost_line_id INTEGER"))
            db.commit()
            print("  ✓ aggiunta")
        else:
            print("  ✓ bookings.job_cost_line_id già presente")

        # 3. time_punches.job_cost_line_id
        if not column_exists("time_punches", "job_cost_line_id"):
            print("▸ ALTER TABLE time_punches ADD COLUMN job_cost_line_id INTEGER NULL")
            db.execute(text("ALTER TABLE time_punches ADD COLUMN job_cost_line_id INTEGER"))
            db.commit()
            print("  ✓ aggiunta")
        else:
            print("  ✓ time_punches.job_cost_line_id già presente")

        # 4. bookings.job_id nullable (recreate table dance)
        if column_is_nullable("bookings", "job_id"):
            print("  ✓ bookings.job_id già nullable")
        else:
            print("▸ Recreate-table dance per rilassare bookings.job_id NOT NULL → NULL")
            # SQLite richiede ricreazione completa. Disabilito FK checks durante.
            db.execute(text("PRAGMA foreign_keys = OFF"))

            # Schema attuale completo dalla tabella, includendo eventuali colonne aggiunte sopra
            cols = inspect(engine).get_columns("bookings")
            col_names = [c["name"] for c in cols]
            col_list = ", ".join(col_names)

            # Crea tabella nuova con stesso schema ma job_id nullable
            db.execute(text("""
                CREATE TABLE bookings_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL DEFAULT 1,
                    job_id INTEGER NULL,
                    job_cost_line_id INTEGER NULL,
                    resource_id INTEGER NOT NULL,
                    start_datetime DATETIME NOT NULL,
                    end_datetime DATETIME NOT NULL,
                    status VARCHAR(9) NOT NULL DEFAULT 'tentative',
                    kind TEXT NOT NULL DEFAULT 'project',
                    notes TEXT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants(id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id),
                    FOREIGN KEY(job_cost_line_id) REFERENCES job_cost_lines(id),
                    FOREIGN KEY(resource_id) REFERENCES resources(id)
                )
            """))
            # Copia i dati: l'intersezione tra colonne vecchie e nuove
            new_cols = ["id", "tenant_id", "job_id", "job_cost_line_id", "resource_id",
                        "start_datetime", "end_datetime", "status", "kind", "notes", "created_at"]
            common = [c for c in new_cols if c in col_names]
            common_str = ", ".join(common)
            db.execute(text(f"INSERT INTO bookings_new ({common_str}) SELECT {common_str} FROM bookings"))
            db.execute(text("DROP TABLE bookings"))
            db.execute(text("ALTER TABLE bookings_new RENAME TO bookings"))
            # Ricreo gli indici
            db.execute(text("CREATE INDEX ix_bookings_id ON bookings(id)"))
            db.execute(text("CREATE INDEX ix_bookings_tenant_id ON bookings(tenant_id)"))
            db.execute(text("CREATE INDEX ix_bookings_job_id ON bookings(job_id)"))
            db.execute(text("CREATE INDEX ix_bookings_job_cost_line_id ON bookings(job_cost_line_id)"))

            db.execute(text("PRAGMA foreign_keys = ON"))
            db.commit()
            print("  ✓ tabella bookings ricreata con job_id NULL ammesso")

        print("─" * 70)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
