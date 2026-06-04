"""Cleanup deliverable orfani (quote_line_id NULL) 'vergini', guardato.

Soft-delete dei deliverable senza riga di quote che non hanno impegni a valle
(via _deliverable_safe_to_remove). Parametrico per job o tenant. Default dry-run.

Uso:
  python scripts/cleanup_orphan_deliverables.py --job-id 1 --dry-run
  python scripts/cleanup_orphan_deliverables.py --job-id 1 --apply
"""
from __future__ import annotations
import argparse

from app.services.clock import now_utc
from app.models import models as m
from app.routers.quotes import _deliverable_safe_to_remove


def cleanup_orphans(db, *, job_id=None, tenant_id=None, apply: bool = False) -> dict:
    """Soft-delete orfani NULL vergini. Ritorna report.
    apply=False → dry-run (nessuna mutazione)."""
    qy = db.query(m.JobDeliverable).filter(
        m.JobDeliverable.quote_line_id.is_(None),
        m.JobDeliverable.deleted_at.is_(None),
    )
    if job_id is not None:
        qy = qy.filter(m.JobDeliverable.job_id == job_id)
    if tenant_id is not None:
        qy = qy.filter(m.JobDeliverable.tenant_id == tenant_id)
    cands = qy.all()
    removed = 0
    kept = []
    for d in cands:
        if _deliverable_safe_to_remove(db, d):
            if apply:
                d.deleted_at = now_utc()
            removed += 1
        else:
            kept.append(d.id)
    if apply:
        db.commit()
    return {
        "candidates": len(cands),
        "removed": removed if apply else 0,
        "would_remove": removed,
        "kept_locked": len(kept),
        "kept_ids": kept,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", type=int, default=None)
    ap.add_argument("--tenant-id", type=int, default=None)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    apply = bool(args.apply)  # default dry-run se nessuno
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        res = cleanup_orphans(db, job_id=args.job_id, tenant_id=args.tenant_id, apply=apply)
    finally:
        db.close()
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] candidati={res['candidates']} rimovibili={res['would_remove']} "
          f"rimossi={res['removed']} tenuti(impegni)={res['kept_locked']} kept_ids={res['kept_ids']}")


if __name__ == "__main__":
    main()
