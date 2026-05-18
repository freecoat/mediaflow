"""MediaFlow — migrazione v3.5.0-alpha.166: semantica AdvancePaymentAllocation.

Bug pre-α.166: `alloc.amount` calcolato come `AP.amount × pct`, dove pct ha
semantica ambigua. Modello dichiara "% di JCL coperta da AP" (default 1.0 =
copre tutta riga), codice interpreta "% di AP allocata a JCL" → con default
1.0 per N allocations si allocava N×AP.amount, valori incoerenti.

Post-α.166: `alloc.amount` autoritativo, `pct` derivato (= amount / AP.amount,
display only). Ricalcolo via preset utente.

Preset disponibili:
  - "fill_sequential" (default): riempi voci in ordine fino a coprire AP, ultima parziale.
    Esempio: AP=25k, JCL=[Color 10k, Dailies 10k, VFX 10k] →
      Color 100% (10k), Dailies 100% (10k), VFX 50% (5k).
  - "pro_rata": distribuisci AP proporzionalmente a JCL.total_quoted.
    Esempio: stesso → Color 8.333 (83%), Dailies 8.333, VFX 8.333.
  - "keep_pct": back-compat — mantieni vecchio calcolo amount = AP × pct.

Ordine "voci selezionate" per fill_sequential = ordine `apa.id` ASC
(approssima ordine inserimento UI; in α.166 introdotto sort_order esplicito).

Esecuzione:
  python scripts/migrate_advance_alloc_semantics.py            # dry-run (default)
  python scripts/migrate_advance_alloc_semantics.py --apply    # esegue update
  python scripts/migrate_advance_alloc_semantics.py --preset pro_rata --apply
"""
from __future__ import annotations

import sys
import os
import argparse
from typing import Literal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AdvancePayment,
    AdvancePaymentAllocation,
    AdvancePaymentStatus,
    JobCostLine,
    QuoteAdvanceSchedule,
)


def _fix_schedule_pct_amount_exclusivity(db: Session, apply: bool) -> int:
    """v3.5.0-alpha.166 — QuoteAdvanceSchedule con pct E amount_fixed entrambi
    valorizzati. Pre-α.166 amount_fixed vinceva silenziosamente; azzera pct."""
    rows = db.query(QuoteAdvanceSchedule).filter(
        QuoteAdvanceSchedule.pct.isnot(None),
        QuoteAdvanceSchedule.amount_fixed.isnot(None),
    ).all()
    fixed = 0
    for s in rows:
        if (s.pct or 0) > 0 and (s.amount_fixed or 0) > 0:
            print(
                f"  Schedule #{s.id} quote_id={s.quote_id} label={s.label!r}: "
                f"pct={s.pct} + amount_fixed={s.amount_fixed} → azzera pct"
            )
            if apply:
                s.pct = None
            fixed += 1
    return fixed


Preset = Literal["fill_sequential", "pro_rata", "keep_pct"]


def compute_new_amounts(
    ap: AdvancePayment,
    allocs: list[AdvancePaymentAllocation],
    jcl_map: dict[int, JobCostLine],
    preset: Preset,
) -> dict[int, float]:
    """Ritorna {alloc_id: new_amount} secondo preset."""
    ap_amount = ap.amount or 0.0
    if ap_amount <= 0 or not allocs:
        return {a.id: 0.0 for a in allocs}

    if preset == "keep_pct":
        return {a.id: round(ap_amount * (a.pct or 0.0), 2) for a in allocs}

    if preset == "pro_rata":
        # Distribuzione proporzionale al peso quotato di ogni JCL.
        weights: dict[int, float] = {}
        total_q = 0.0
        for a in allocs:
            jcl = jcl_map.get(a.job_cost_line_id)
            q = (jcl.total_quoted or 0.0) if jcl else 0.0
            weights[a.id] = q
            total_q += q
        if total_q <= 0:
            equal = round(ap_amount / len(allocs), 2)
            return {a.id: equal for a in allocs}
        return {aid: round(ap_amount * (w / total_q), 2) for aid, w in weights.items()}

    # fill_sequential (default): ordina per apa.id ASC, riempi 100% sequenziale.
    ordered = sorted(allocs, key=lambda a: a.id)
    remaining = ap_amount
    out: dict[int, float] = {}
    for a in ordered:
        jcl = jcl_map.get(a.job_cost_line_id)
        cap = (jcl.total_quoted or 0.0) if jcl else 0.0
        take = min(cap, remaining)
        if take < 0:
            take = 0.0
        out[a.id] = round(take, 2)
        remaining = round(remaining - take, 2)
        if remaining <= 0:
            remaining = 0.0
    return out


def fmt(x: float) -> str:
    return f"{x:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preset",
        choices=["fill_sequential", "pro_rata", "keep_pct"],
        default="fill_sequential",
        help="Strategia ricalcolo amount per allocation (default fill_sequential).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Esegui update (default = dry-run, mostra solo diff).",
    )
    parser.add_argument(
        "--ap-id",
        type=int,
        default=None,
        help="Filtra a singolo AdvancePayment.id (per test mirato).",
    )
    args = parser.parse_args()

    print("=" * 90)
    print(f"MediaFlow — migrate_advance_alloc_semantics  preset={args.preset}  apply={args.apply}")
    print("=" * 90)

    db: Session = SessionLocal()
    try:
        # Fix schedule pct/amount_fixed exclusivity prima delle allocations
        print("\n--- Fix QuoteAdvanceSchedule pct/amount_fixed exclusivity ---")
        n_sched_fix = _fix_schedule_pct_amount_exclusivity(db, args.apply)
        if n_sched_fix == 0:
            print("  (nessuna schedule da correggere)")
        else:
            print(f"  {n_sched_fix} schedule corrette")
        q = db.query(AdvancePayment).filter(
            AdvancePayment.status != AdvancePaymentStatus.cancelled,
        )
        if args.ap_id:
            q = q.filter(AdvancePayment.id == args.ap_id)
        aps = q.order_by(AdvancePayment.id.asc()).all()
        if not aps:
            print("Nessun AdvancePayment trovato. Nothing to do.")
            return

        total_changes = 0
        total_alloc = 0
        for ap in aps:
            allocs = db.query(AdvancePaymentAllocation).filter(
                AdvancePaymentAllocation.advance_payment_id == ap.id,
            ).all()
            if not allocs:
                continue
            total_alloc += len(allocs)
            jcl_ids = [a.job_cost_line_id for a in allocs]
            jcls = db.query(JobCostLine).filter(JobCostLine.id.in_(jcl_ids)).all()
            jcl_map = {j.id: j for j in jcls}

            new_amounts = compute_new_amounts(ap, allocs, jcl_map, args.preset)
            sum_new = round(sum(new_amounts.values()), 2)

            print(f"\nAP #{ap.id}  project_id={ap.project_id}  amount={fmt(ap.amount)}  status={ap.status.value}")
            print(f"  schedule_id={ap.quote_advance_schedule_id}  invoice_id={ap.invoice_id}  label={ap.label!r}")
            print(f"  {'alloc':>6} {'jcl':>5} {'quoted':>12} {'old_pct':>8} {'old_amt':>12} {'new_amt':>12} {'new_pct':>8} {'Δ':>10}  desc")
            for a in sorted(allocs, key=lambda x: x.id):
                jcl = jcl_map.get(a.job_cost_line_id)
                jq = (jcl.total_quoted or 0.0) if jcl else 0.0
                desc = (jcl.description if jcl else "<missing>")[:38]
                new_amt = new_amounts.get(a.id, 0.0)
                delta = round(new_amt - (a.amount or 0.0), 2)
                new_pct = (new_amt / ap.amount) if ap.amount else 0.0
                flag = ""
                if abs(delta) >= 0.01:
                    flag = " ← CHANGE"
                    total_changes += 1
                print(
                    f"  {a.id:>6} {a.job_cost_line_id:>5} {fmt(jq)} {a.pct or 0.0:>8.3f} "
                    f"{fmt(a.amount or 0.0)} {fmt(new_amt)} {new_pct:>8.3f} {fmt(delta)}  {desc}{flag}"
                )
                if args.apply and abs(delta) >= 0.01:
                    a.amount = new_amt
                    a.pct = round(new_pct, 6)
            print(f"  Σ alloc.amount new = {fmt(sum_new)}  (AP.amount = {fmt(ap.amount)})  ", end="")
            diff = round(ap.amount - sum_new, 2)
            if diff > 0.01:
                print(f"WARN residuo non allocato: {fmt(diff)} (AP non interamente coperto)")
            elif diff < -0.01:
                print(f"WARN over-alloc: {fmt(-diff)} oltre AP.amount")
            else:
                print("OK Σ = AP")

        print("\n" + "=" * 90)
        print(f"Totale AP processati: {len(aps)}  Allocations: {total_alloc}  Changes: {total_changes}")
        if args.apply:
            db.commit()
            print("Commit eseguito.")
        else:
            print("DRY-RUN — nessuna modifica scritta. Usa --apply per applicare.")
        print("=" * 90)
    finally:
        db.close()


if __name__ == "__main__":
    main()
