"""Backfill JCL post-fix v3.5.0-alpha.172.97 — _booking_billable_hours
sum-per-resource. Le JCL con smart_split avevano quantity_actual a meta'
(stessa risorsa AM+PM contava solo max=4h invece di sum=8h).

Idempotente: ricomputa via recompute_cost_line_actual() — riallinea anche
total_accrued + total_expected + total_cost_accrued.

Uso: .venv/Scripts/python.exe scripts/backfill_jcl_billable_hours_alpha172_97.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import JobCostLine
from app.services.cost_line_sync import recompute_cost_line_actual


def main() -> int:
    db = SessionLocal()
    try:
        jcls = db.query(JobCostLine).all()
        n_total = len(jcls)
        n_updated = 0
        n_unchanged = 0
        n_skipped = 0
        diffs = []
        for jcl in jcls:
            qa_before = jcl.quantity_actual or 0.0
            ac_before = jcl.total_accrued or 0.0
            res = recompute_cost_line_actual(db, jcl)
            if not res.get("updated"):
                n_unchanged += 1
                continue
            if res.get("mode") in ("external_outsourced_legacy_zeroed", "non_time_legacy_zeroed"):
                n_skipped += 1
                continue
            n_updated += 1
            qa_after = jcl.quantity_actual or 0.0
            ac_after = jcl.total_accrued or 0.0
            if abs(qa_after - qa_before) > 1e-6 or abs(ac_after - ac_before) > 1e-2:
                diffs.append((jcl.id, jcl.description, qa_before, qa_after, ac_before, ac_after))
        db.commit()
        print(f"JCL totali: {n_total}")
        print(f"  aggiornate: {n_updated}")
        print(f"  invariate : {n_unchanged}")
        print(f"  skipped   : {n_skipped} (legacy non-time o outsourced)")
        if diffs:
            print()
            print(f"Diff principali ({min(20, len(diffs))} su {len(diffs)}):")
            for d in diffs[:20]:
                jid, desc, qb, qa, ab, aa = d
                print(f"  JCL #{jid:>4} {desc[:40]:<40}  qty {qb:>7.2f} → {qa:>7.2f}   accrued {ab:>9.2f} → {aa:>9.2f}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
