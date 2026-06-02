"""v3.5.0-alpha.172.171 — Bootstrap minimale produzione.

Idempotente: se NON esiste alcun utente, crea il tenant di default + un admin
con credenziali da ENV (ADMIN_EMAIL / ADMIN_PASSWORD, default admin@claqo.local /
'changeme'). Niente dati demo (a differenza di seed_demo.py). Pensato per il
primo boot in produzione (docker-entrypoint).

NON tocca nulla se ci sono già utenti → sicuro da lanciare a ogni avvio.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, create_tables
from app.models.models import User, UserRole, Tenant
from app.services.auth import hash_password


def main():
    create_tables()
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print("[bootstrap] utenti già presenti — nessuna azione.")
            return
        # Tenant default (id=1, allineato a CURRENT_TENANT)
        if not db.query(Tenant).filter(Tenant.id == 1).first():
            db.add(Tenant(id=1, name="Claqo", slug="claqo"))
            db.flush()
        email = os.environ.get("ADMIN_EMAIL", "admin@claqo.local").strip()
        pw = os.environ.get("ADMIN_PASSWORD", "changeme")
        db.add(User(
            tenant_id=1, email=email, full_name="Administrator",
            hashed_password=hash_password(pw), role=UserRole.admin, is_active=True,
        ))
        db.commit()
        print(f"[bootstrap] admin creato: {email} "
              f"(password da ADMIN_PASSWORD — CAMBIALA al primo accesso)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
