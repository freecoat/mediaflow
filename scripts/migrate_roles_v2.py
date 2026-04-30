"""
MediaFlow — sistema permessi configurabili (v3.4.23)

1. CREATE TABLE roles (id, tenant_id, code, name, description, permissions JSON,
                       is_system, is_active, created_at)
2. ALTER TABLE users ADD COLUMN role_id INTEGER NULL FK roles.id
3. Inserimento 6 preset built-in (admin, manager, producer, accounting,
   operator, viewer) con i permessi codificati in `app.services.rbac.PRESET_PERMISSIONS`.
4. Mappatura back-compat: assegna role_id ai user esistenti in base al loro
   enum legacy `role`:
     admin   → role.code='admin'
     manager → role.code='manager'
     producer→ role.code='producer'
     staff   → role.code='operator'
     viewer  → role.code='viewer'

Idempotente.

Esegui:
  python scripts/migrate_roles_v2.py
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
from app.models import Role, User  # noqa: F401
from app.services.rbac import ensure_built_in_roles


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def table_exists(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def migrate():
    print("▸ MediaFlow · sistema permessi configurabili (v3.4.23)")
    print("─" * 70)

    create_tables()  # crea `roles` via Base.metadata

    db = SessionLocal()
    try:
        if not table_exists("roles"):
            print("▸ Tabella roles non creata, abort.")
            return
        print("  ✓ tabella roles presente")

        # ALTER users ADD role_id
        if not column_exists("users", "role_id"):
            print("▸ ALTER TABLE users ADD COLUMN role_id INTEGER")
            db.execute(text("ALTER TABLE users ADD COLUMN role_id INTEGER"))
            db.commit()
            print("  ✓ users.role_id aggiunta")
        else:
            print("  ✓ users.role_id già presente")

        # Bootstrap preset
        ensure_built_in_roles(db)
        print(f"  ✓ {db.query(Role).count()} ruoli totali (preset + custom)")

        # Back-compat: per ogni utente con role_id NULL, mappa enum legacy → Role
        legacy_map = {
            "admin": "admin", "manager": "manager", "producer": "producer",
            "staff": "operator", "viewer": "viewer",
        }
        users = db.query(User).filter(User.role_id.is_(None)).all()
        roles_by_code = {r.code: r for r in db.query(Role).all()}
        updated = 0
        for u in users:
            legacy = (u.role.value if hasattr(u.role, "value") else str(u.role or "")).lower()
            target_code = legacy_map.get(legacy, "operator")
            target = roles_by_code.get(target_code)
            if target:
                u.role_id = target.id
                updated += 1
        db.commit()
        print(f"  ✓ {updated} utenti mappati al nuovo Role")

        print("─" * 70)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
