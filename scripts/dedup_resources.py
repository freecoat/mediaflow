"""v3.5.0-alpha.98 — Dedup Resource records con stesso nome.

Origine bug: seed/stress test ha creato Resource con stesso nome ma id
diverso (es. "Stefano Marini" id=232 + id=254). Visivamente appaiono come
2 righe distinte sulla timeline (vis-timeline groups = resource_id).

Strategia:
  Per ogni gruppo (name, role, department_id):
    - Tieni il record con id MINORE (più vecchio)
    - Tutti i Booking/Assignment dei duplicati vengono riassegnati al keeper
    - I duplicati vengono soft-deleted (is_active=False)

Dry-run di default — passa --apply per scrivere.
"""
import os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Resource, BookingAssignment


def find_duplicates(db: Session) -> dict:
    """Ritorna {(name, role, dept_id): [Resource, ...]} per i duplicati."""
    resources = db.query(Resource).filter(Resource.is_active == True).all()
    groups = defaultdict(list)
    for r in resources:
        key = (r.name, r.role or "", r.department_id or 0)
        groups[key].append(r)
    return {k: v for k, v in groups.items() if len(v) > 1}


def dedup(apply: bool = False) -> dict:
    db: Session = SessionLocal()
    try:
        dups = find_duplicates(db)
        if not dups:
            print("Nessun duplicato.")
            return {"groups": 0}
        print(f"Trovati {len(dups)} gruppi duplicati.")
        total_merged = 0
        total_reassigned = 0
        for key, resources in dups.items():
            resources.sort(key=lambda r: r.id)
            keeper = resources[0]
            dupes = resources[1:]
            print(f"  {key[0]!r}: keeper id={keeper.id}, dupes={[r.id for r in dupes]}")
            for d in dupes:
                # Riassegna BookingAssignment dal dupe al keeper
                bas = db.query(BookingAssignment).filter(
                    BookingAssignment.resource_id == d.id,
                ).all()
                for ba in bas:
                    ba.resource_id = keeper.id
                    total_reassigned += 1
                if apply:
                    d.is_active = False
                    d.name = (d.name or "") + f" [DUP-of-{keeper.id}]"
                total_merged += 1
        if apply:
            db.commit()
            print(f"OK applicato: {total_merged} duplicati soft-deleted, "
                  f"{total_reassigned} booking riassegnati.")
        else:
            db.rollback()
            print(f"DRY-RUN: avrebbe soft-deleted {total_merged} duplicati, "
                  f"riassegnato {total_reassigned} booking. Lancia con --apply.")
        return {
            "groups": len(dups),
            "merged": total_merged,
            "reassigned": total_reassigned,
            "applied": apply,
        }
    finally:
        db.close()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    dedup(apply=apply)
