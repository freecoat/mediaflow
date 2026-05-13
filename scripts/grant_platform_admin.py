"""v3.5.0-alpha.109 — Grant/revoke platform admin flag.

Usage:
    python scripts/grant_platform_admin.py --email matteo@mediaflow.it
    python scripts/grant_platform_admin.py --email X --revoke
    python scripts/grant_platform_admin.py --list
"""
import os, sys, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import User


def grant(email: str, revoke: bool = False) -> int:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            print(f"ERROR: utente {email} non trovato")
            return 1
        u.is_platform_admin = not revoke
        db.commit()
        action = "REVOCATO" if revoke else "PROMOSSO"
        print(f"OK: {action} {email} (tenant_id={u.tenant_id})")
        return 0
    finally:
        db.close()


def list_admins() -> int:
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.is_platform_admin == True,  # noqa: E712
        ).all()
        print(f"Platform admin attivi: {len(users)}")
        for u in users:
            print(f"  - {u.email} (tenant_id={u.tenant_id}, role={u.role})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email")
    p.add_argument("--revoke", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    if args.list:
        sys.exit(list_admins())
    if not args.email:
        p.error("--email obbligatorio (o usa --list)")
    sys.exit(grant(args.email, revoke=args.revoke))
