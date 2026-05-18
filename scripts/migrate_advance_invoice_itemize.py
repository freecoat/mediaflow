"""v3.5.0-alpha.166 — Re-itemizzazione fatture acconto pre-α.166.

Pre-α.166: emit_invoice_from_advance creava 1 InvoiceLine aggregata
("Acconto progetto X — €Y"). Post-α.166: N InvoiceLine, una per
AdvancePaymentAllocation, con description = JCL.description.

Migration: per ogni Invoice(kind=advance) con AP associato, drop le InvoiceLine
esistenti + ricrea N InvoiceLine basate sulle allocations attuali.

Idempotente: skip Invoice se già ha N>1 InvoiceLine (proxy "già itemizzata").
Salta se Invoice.status == cancelled (non toccare NC).

ATTENZIONE: rigenera InvoiceLine — se utente aveva editato manualmente la
riga aggregata (description custom, sconto), PERDI quel customizzato. Da
applicare prima di test estensivo o backup DB.

Esecuzione:
  python scripts/migrate_advance_invoice_itemize.py            # dry-run
  python scripts/migrate_advance_invoice_itemize.py --apply    # esegue
"""
from __future__ import annotations

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AdvancePayment,
    AdvancePaymentAllocation,
    Invoice,
    InvoiceKind,
    InvoiceLine,
    InvoiceStatus,
    JobCostLine,
)


def fmt(x: float) -> str:
    return f"{x:>10,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Esegui DROP+CREATE")
    parser.add_argument("--invoice-id", type=int, default=None, help="Filtra a singola Invoice")
    args = parser.parse_args()

    print("=" * 90)
    print(f"MediaFlow — migrate_advance_invoice_itemize  apply={args.apply}")
    print("=" * 90)

    db: Session = SessionLocal()
    try:
        q = (
            db.query(Invoice)
            .filter(
                Invoice.kind == InvoiceKind.advance,
                Invoice.status != InvoiceStatus.cancelled,
            )
        )
        if args.invoice_id:
            q = q.filter(Invoice.id == args.invoice_id)
        invoices = q.order_by(Invoice.id.asc()).all()
        if not invoices:
            print("Nessuna Invoice acconto trovata. Nothing to do.")
            return

        total_changes = 0
        for inv in invoices:
            ap = db.query(AdvancePayment).filter(AdvancePayment.invoice_id == inv.id).first()
            if not ap:
                print(f"Invoice #{inv.id} {inv.number}: NO AP associato → skip")
                continue
            allocs = (
                db.query(AdvancePaymentAllocation)
                .filter(AdvancePaymentAllocation.advance_payment_id == ap.id)
                .order_by(
                    AdvancePaymentAllocation.sort_order.asc().nulls_last(),
                    AdvancePaymentAllocation.id.asc(),
                )
                .all()
            )
            existing_lines = (
                db.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv.id).all()
            )
            n_existing = len(existing_lines)
            print(
                f"\nInvoice #{inv.id} {inv.number}  AP #{ap.id} amount={fmt(ap.amount)} "
                f"sub={fmt(inv.subtotal)}  existing_lines={n_existing}  allocs={len(allocs)}"
            )
            if not allocs:
                print("  → no allocations, lascio riga aggregata invariata")
                continue
            if n_existing > 1:
                print(f"  → già itemizzata ({n_existing} lines), skip per idempotenza")
                continue

            sum_alloc = round(sum(a.amount or 0.0 for a in allocs), 2)
            residual = round((inv.subtotal or 0.0) - sum_alloc, 2)
            print(f"  Σ alloc = {fmt(sum_alloc)}  residual = {fmt(residual)}")
            print(f"  {'jcl':>5} {'amount':>12}  description")
            for a in allocs:
                jcl = db.query(JobCostLine).filter(JobCostLine.id == a.job_cost_line_id).first()
                desc = (jcl.description if jcl else f"<JCL #{a.job_cost_line_id}>")[:50]
                print(f"  {a.job_cost_line_id:>5} {fmt(a.amount or 0.0)}  Acconto su: {desc}")
            if residual > 0.01:
                print(f"  {'-':>5} {fmt(residual)}  Acconto generale (residuo)")

            if args.apply:
                # Drop existing
                for line in existing_lines:
                    db.delete(line)
                db.flush()
                # Create new itemized
                for a in allocs:
                    jcl = db.query(JobCostLine).filter(JobCostLine.id == a.job_cost_line_id).first()
                    line_desc = (jcl.description if jcl else f"JCL #{a.job_cost_line_id}")
                    db.add(InvoiceLine(
                        invoice_id=inv.id,
                        description=f"Acconto su: {line_desc}",
                        quantity=1.0,
                        unit_price=round(a.amount or 0.0, 2),
                        total=round(a.amount or 0.0, 2),
                        vat_rate=inv.vat_rate or 22.0,
                        discount_pct=0.0,
                    ))
                if residual > 0.01:
                    db.add(InvoiceLine(
                        invoice_id=inv.id,
                        description=f"Acconto generale — fattura {inv.number}",
                        quantity=1.0,
                        unit_price=residual,
                        total=residual,
                        vat_rate=inv.vat_rate or 22.0,
                        discount_pct=0.0,
                    ))
                total_changes += 1
                print(f"  ✓ Re-itemizzata")

        print("\n" + "=" * 90)
        print(f"Invoices processate: {len(invoices)}  Modificate: {total_changes}")
        if args.apply:
            db.commit()
            print("Commit eseguito.")
        else:
            print("DRY-RUN — nessuna modifica. Usa --apply per applicare.")
        print("=" * 90)
    finally:
        db.close()


if __name__ == "__main__":
    main()
