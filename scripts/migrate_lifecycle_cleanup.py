"""
MediaFlow — cleanup orfani lifecycle Quote/Job/Booking (v3.4.36, Round 1).

Pulisce i 3 tipi di FK rotte/orfane introdotti silenziosamente da bug pre-v3.4.36:

1. JobCostLine con `quote_line_id` valorizzato che punta a QuoteLine inesistente
   (la riga quote era stata cancellata senza cascade) → cancella la JobCostLine
   solo se NON è is_extra (quelle is_extra sono libere per design).

2. Booking con `job_cost_line_id` valorizzato che punta a JobCostLine
   inesistente → SET NULL.

3. TimePunch con `job_cost_line_id` valorizzato che punta a JobCostLine
   inesistente → SET NULL.

Idempotente: re-eseguibile senza danni.

Esegui:
  python scripts/migrate_lifecycle_cleanup.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text
from app.database import SessionLocal


def migrate():
    print("▸ MediaFlow · cleanup orfani lifecycle Quote/Job/Booking (v3.4.36)")
    print("─" * 70)

    db = SessionLocal()
    try:
        # 1. JobCostLine orfani con quote_line_id che non esiste
        rows = db.execute(text("""
            SELECT jcl.id, jcl.description, jcl.quote_line_id, jcl.is_extra
              FROM job_cost_lines jcl
             WHERE jcl.quote_line_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM quote_lines ql WHERE ql.id = jcl.quote_line_id
               )
        """)).fetchall()
        print(f"\n[1] JobCostLine orfani (quote_line_id → vuoto): {len(rows)}")
        for r in rows:
            tag = "extra (skip)" if r[3] else "ELIMINO"
            print(f"   #{r[0]} «{r[1]}» quote_line_id={r[2]} → {tag}")
        if rows:
            db.execute(text("""
                DELETE FROM job_cost_lines
                 WHERE quote_line_id IS NOT NULL
                   AND is_extra = 0
                   AND NOT EXISTS (
                       SELECT 1 FROM quote_lines ql WHERE ql.id = job_cost_lines.quote_line_id
                   )
            """))
            db.commit()

        # 2. Booking con job_cost_line_id orfano → SET NULL
        n_bk = db.execute(text("""
            SELECT COUNT(*) FROM bookings
             WHERE job_cost_line_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM job_cost_lines jcl WHERE jcl.id = bookings.job_cost_line_id
               )
        """)).scalar()
        print(f"\n[2] Booking con FK rotta a JobCostLine: {n_bk}")
        if n_bk:
            db.execute(text("""
                UPDATE bookings SET job_cost_line_id = NULL
                 WHERE job_cost_line_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM job_cost_lines jcl WHERE jcl.id = bookings.job_cost_line_id
                   )
            """))
            db.commit()
            print(f"   → {n_bk} booking aggiornati (job_cost_line_id → NULL)")

        # 3. TimePunch con job_cost_line_id orfano → SET NULL
        n_tp = db.execute(text("""
            SELECT COUNT(*) FROM time_punches
             WHERE job_cost_line_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM job_cost_lines jcl WHERE jcl.id = time_punches.job_cost_line_id
               )
        """)).scalar()
        print(f"\n[3] TimePunch con FK rotta a JobCostLine: {n_tp}")
        if n_tp:
            db.execute(text("""
                UPDATE time_punches SET job_cost_line_id = NULL
                 WHERE job_cost_line_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM job_cost_lines jcl WHERE jcl.id = time_punches.job_cost_line_id
                   )
            """))
            db.commit()
            print(f"   → {n_tp} timepunch aggiornati (job_cost_line_id → NULL)")

        print()
        print("─" * 70)
        print("Cleanup completato.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
