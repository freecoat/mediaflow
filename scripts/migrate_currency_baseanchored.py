"""Verifica precondizione base-anchored (α.172.155) + backfill currency/fx.

Base-anchored: tutti gli importi DB sono in valuta base. Precondizione: nessuna
quote/fattura reale espressa in valuta != base con tasso != 1.0 (la conversione
non ha mai funzionato pre-155, quindi non dovrebbero esistere). Se ne trova,
STOP con report (vanno valutate a mano). Backfilla currency/fx_rate_to_base dove null.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.database import SessionLocal
from app.models import models as m


def main(dry=False):
    db = SessionLocal()
    try:
        base = (db.query(m.Tenant).filter(m.Tenant.id == 1).first().default_currency or "EUR").upper()
        bad = []
        for Q in (m.Quote, m.Invoice):
            for row in db.query(Q).all():
                ccy = (getattr(row, "currency", None) or base).upper()
                rate = getattr(row, "fx_rate_to_base", 1.0) or 1.0
                if ccy != base and abs(rate - 1.0) > 1e-9:
                    bad.append((Q.__name__, row.id, ccy, rate))
        if bad:
            print("STOP — esistono quote/fatture in valuta estera con tasso !=1, da gestire a mano:")
            for b in bad:
                print("  ", b)
            return 1
        fixed = 0
        for Q in (m.Quote, m.Invoice):
            for row in db.query(Q).all():
                if not getattr(row, "currency", None):
                    row.currency = base; fixed += 1
                if getattr(row, "fx_rate_to_base", None) in (None, 0):
                    row.fx_rate_to_base = 1.0; fixed += 1
        if not dry:
            db.commit()
        print(f"{'[DRY] ' if dry else ''}precondizione OK (base={base}); backfill campi: {fixed}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(dry="--dry" in sys.argv))
