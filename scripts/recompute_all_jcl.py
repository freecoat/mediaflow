"""MediaFlow — recompute_all_jcl (v3.5.0-alpha.171).

Script one-shot per ricomputare TUTTE le JobCostLine del DB applicando la
nuova logica α.171:
- CR-1: voci non time-based → actual=expected=quoted (binario)
- CR-1: voci time-based con 0 booking → expected=0 (era=quoted)
- CR-2: ore billable max umana || max non-umana (no double-count sala+persona)

Idempotente. Riesegue `recompute_cost_line_actual` su ogni JCL. Trasaction-safe:
commit per ogni job (evita lock lunghi su DB grandi).

Uso:
  .venv/Scripts/python.exe scripts/recompute_all_jcl.py
  .venv/Scripts/python.exe scripts/recompute_all_jcl.py --tenant 1
  .venv/Scripts/python.exe scripts/recompute_all_jcl.py --dry-run

Output:
  Per ogni job: progress + N JCL aggiornate.
  Summary finale: totali (jobs visitati, JCL totali, JCL cambiate, secs).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Rendi importabile il package app/ quando lanciato da root repo
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import Job, JobCostLine  # noqa: E402
from app.services.cost_line_sync import recompute_cost_line_actual  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Recompute all JCL with α.171 logic.")
    parser.add_argument("--tenant", type=int, default=None, help="Filtra per tenant_id (default: tutti).")
    parser.add_argument("--dry-run", action="store_true", help="Calcola ma NON committa.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Stampa dettaglio per ogni JCL aggiornata.")
    args = parser.parse_args()

    db = SessionLocal()
    t0 = time.time()
    jobs_q = db.query(Job)
    if args.tenant is not None:
        jobs_q = jobs_q.filter(Job.tenant_id == args.tenant)
    jobs = jobs_q.order_by(Job.id).all()

    print(f"[recompute] Found {len(jobs)} job(s) to scan.")
    if args.dry_run:
        print("[recompute] DRY RUN — nessun commit verra' eseguito.")

    tot_jcl = 0
    tot_changed = 0
    failed_jobs = []

    for i, job in enumerate(jobs, 1):
        jcls = db.query(JobCostLine).filter(JobCostLine.job_id == job.id).all()
        if not jcls:
            continue
        job_changed = 0
        for jcl in jcls:
            tot_jcl += 1
            try:
                # Salva valori vecchi per log diff
                old = (jcl.quantity_actual or 0, jcl.total_accrued or 0, jcl.total_expected or 0)
                result = recompute_cost_line_actual(db, jcl)
                new = (jcl.quantity_actual or 0, jcl.total_accrued or 0, jcl.total_expected or 0)
                if result.get("updated"):
                    tot_changed += 1
                    job_changed += 1
                    if args.verbose:
                        print(
                            f"  JCL#{jcl.id} [{jcl.description[:40] if jcl.description else ''}] "
                            f"qty {old[0]:.2f}->{new[0]:.2f} "
                            f"accr €{old[1]:.2f}->€{new[1]:.2f} "
                            f"exp €{old[2]:.2f}->€{new[2]:.2f}"
                        )
            except Exception as e:
                failed_jobs.append((job.id, jcl.id, str(e)))
                print(f"  [ERR] job#{job.id} jcl#{jcl.id}: {e}")
        if not args.dry_run and job_changed > 0:
            try:
                db.commit()
            except Exception as e:
                print(f"  [COMMIT-ERR] job#{job.id}: {e}")
                db.rollback()
                failed_jobs.append((job.id, None, f"commit-error: {e}"))
        if i % 20 == 0 or i == len(jobs):
            print(f"  ...{i}/{len(jobs)} job processed, {tot_changed} JCL changed so far")

    if args.dry_run:
        db.rollback()

    elapsed = time.time() - t0
    print("\n=== SUMMARY ===")
    print(f"Jobs visited:    {len(jobs)}")
    print(f"JCL total:       {tot_jcl}")
    print(f"JCL changed:     {tot_changed}")
    print(f"Errors:          {len(failed_jobs)}")
    print(f"Elapsed:         {elapsed:.2f}s")
    if failed_jobs:
        print("\nFailed entries:")
        for job_id, jcl_id, err in failed_jobs[:20]:
            print(f"  job#{job_id} jcl#{jcl_id}: {err}")
        if len(failed_jobs) > 20:
            print(f"  ... and {len(failed_jobs) - 20} more")
    db.close()


if __name__ == "__main__":
    main()
