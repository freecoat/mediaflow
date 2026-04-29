"""
MediaFlow — migrazione orario lavorativo + ferie tipizzate (v3.4.17)

1. CREATE TABLE working_hours_policies (con default Italia 9-13/14-18 lun-ven)
2. ALTER TABLE resources ADD COLUMN working_hours_policy_id INTEGER NULL
3. ALTER TABLE resource_unavailabilities ADD COLUMN kind TEXT NOT NULL DEFAULT 'vacation'

Idempotente: re-eseguibile senza danni.

Esegui:
  python scripts/migrate_working_hours.py
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
from app.models import WorkingHoursPolicy, Resource, ResourceUnavailability  # noqa: F401


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def table_exists(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def migrate():
    print("▸ MediaFlow · migrazione WorkingHoursPolicy + ferie tipizzate (v3.4.17)")
    print("─" * 70)

    create_tables()  # crea working_hours_policies via Base.metadata

    db = SessionLocal()
    try:
        # 1. Tabella creata?
        if not table_exists("working_hours_policies"):
            print("▸ Tabella working_hours_policies non creata, abort.")
            return
        print("  ✓ tabella working_hours_policies presente")

        # 2. Default Italia se non esiste
        n = db.execute(text("SELECT COUNT(*) FROM working_hours_policies WHERE is_default=1")).scalar()
        if n == 0:
            print("▸ Inserimento policy default 'Italia 9-13/14-18 lun-ven'")
            db.execute(text("""
                INSERT INTO working_hours_policies
                  (tenant_id, name, is_default, morning_start, morning_end,
                   afternoon_start, afternoon_end, working_days, holidays_country, created_at)
                VALUES (1, 'Italia standard', 1, '09:00', '13:00',
                        '14:00', '18:00', 31, 'IT', CURRENT_TIMESTAMP)
            """))
            db.commit()
            print("  ✓ default policy creata")
        else:
            print(f"  ✓ {n} policy default già presente")

        # 3. Colonna su resources
        if not column_exists("resources", "working_hours_policy_id"):
            print("▸ ALTER TABLE resources ADD COLUMN working_hours_policy_id")
            db.execute(text("ALTER TABLE resources ADD COLUMN working_hours_policy_id INTEGER"))
            db.commit()
            print("  ✓ aggiunta")
        else:
            print("  ✓ resources.working_hours_policy_id già presente")

        # 4. Colonna kind su resource_unavailabilities
        if not column_exists("resource_unavailabilities", "kind"):
            print("▸ ALTER TABLE resource_unavailabilities ADD COLUMN kind")
            db.execute(text("ALTER TABLE resource_unavailabilities ADD COLUMN kind TEXT NOT NULL DEFAULT 'vacation'"))
            db.commit()
            print("  ✓ aggiunta")
        else:
            print("  ✓ resource_unavailabilities.kind già presente")

        # 5. Verifica finale
        n_pol = db.execute(text("SELECT COUNT(*) FROM working_hours_policies")).scalar()
        n_unav = db.execute(text("SELECT COUNT(*) FROM resource_unavailabilities")).scalar()
        print(f"  · {n_pol} policy, {n_unav} unavailabilities")

        print("─" * 70)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
