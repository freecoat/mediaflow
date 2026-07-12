"""Concede manage_assets ai ruoli/utenti che hanno edit_planning_all.
Idempotente: rilanciabile senza effetti doppi."""
from app.database import SessionLocal
from app.models.models import Role


def run():
    db = SessionLocal()
    try:
        changed = 0
        for role in db.query(Role).all():
            perms = list(role.permissions or [])
            if "edit_planning_all" in perms and "manage_assets" not in perms:
                perms.append("manage_assets")
                role.permissions = perms
                changed += 1
        db.commit()
        print(f"[migrate_manage_assets] ruoli aggiornati: {changed}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
