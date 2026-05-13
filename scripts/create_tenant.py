"""v3.5.0-alpha.103 R-MT3 — CLI onboarding nuovo tenant.

Crea: Tenant + admin User + Department defaults + cartella uploads/t{id}/.
Listino VUOTO (decisione Matteo). Admin platform invia poi magic link.

Usage:
    python scripts/create_tenant.py --slug acme --name "Acme Post"
                                    --admin-email matteo@acme.it
                                    --admin-name "Matteo Lepore"
                                    [--admin-password XXX]

Senza --admin-password genera password random 16-char hex e la STAMPA
(da copiare/inviare). L'admin del nuovo tenant cambia password al primo
login (TODO: forzato).
"""
import os, sys, secrets, argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.config import settings
from app.models import Tenant, User, Department, Role, UserRole
from app.services.auth import hash_password


DEFAULT_DEPARTMENTS = [
    ("DI", "Digital Intermediate", "#6272f5"),
    ("VFX", "Visual Effects", "#a78bfa"),
    ("AUDIO", "Audio Post", "#10b981"),
    ("COMM", "Commercial", "#fb923c"),
]


def create_tenant(
    slug: str,
    name: str,
    admin_email: str,
    admin_name: str,
    admin_password: str = "",
) -> dict:
    db: Session = SessionLocal()
    try:
        # 1. Check unicità slug
        if db.query(Tenant).filter(Tenant.slug == slug).first():
            print(f"ERROR: slug '{slug}' già esistente")
            return {"error": "slug_exists"}
        # 2. Crea Tenant
        t = Tenant(
            name=name, slug=slug,
            is_active=True, onboarding_completed=False,
        )
        db.add(t); db.flush()
        print(f"OK: Tenant id={t.id} slug='{slug}' creato")
        # 3. Crea departments default
        for code, dname, color in DEFAULT_DEPARTMENTS:
            d = Department(
                tenant_id=t.id, code=code, name=dname, color=color, is_active=True,
            )
            db.add(d)
        # 4. Admin password
        if not admin_password:
            admin_password = secrets.token_urlsafe(12)
            print(f"OK: password generata: {admin_password}")
        # 5. Crea admin user
        # Check unicità (tenant_id, email)
        existing = db.query(User).filter(
            User.tenant_id == t.id, User.email == admin_email,
        ).first()
        if existing:
            print(f"ERROR: user {admin_email} già esistente sul tenant {slug}")
            db.rollback()
            return {"error": "user_exists"}
        u = User(
            tenant_id=t.id,
            email=admin_email.strip().lower(),
            full_name=admin_name,
            hashed_password=hash_password(admin_password),
            role=UserRole.admin,
            is_active=True,
        )
        db.add(u)
        # 6. Cartella uploads tenant-scoped
        upload_dir = Path(settings.upload_dir) / f"t{t.id}"
        (upload_dir / "assets").mkdir(parents=True, exist_ok=True)
        (upload_dir / "thumbnails").mkdir(parents=True, exist_ok=True)
        print(f"OK: cartella {upload_dir}/ creata")
        db.commit()
        print()
        print("=== TENANT PRONTO ===")
        print(f"Slug: {slug}")
        print(f"Admin: {admin_email}")
        print(f"Password: {admin_password}")
        print(f"Login URL (dev): http://{slug}.lvh.me:8000/auth/login")
        print(f"Login URL (prod): http://{slug}.mediaflow.it/auth/login  # quando DNS pronto")
        print(f"Fallback dev: http://localhost:8000/auth/login?tenant={slug}")
        return {
            "tenant_id": t.id, "slug": slug,
            "admin_email": admin_email, "admin_password": admin_password,
        }
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--admin-email", required=True)
    p.add_argument("--admin-name", required=True)
    p.add_argument("--admin-password", default="")
    args = p.parse_args()
    create_tenant(
        slug=args.slug, name=args.name,
        admin_email=args.admin_email, admin_name=args.admin_name,
        admin_password=args.admin_password,
    )
