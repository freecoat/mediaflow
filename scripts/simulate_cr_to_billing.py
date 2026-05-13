"""
MediaFlow — simulate_cr_to_billing.py (v3.5.0-alpha.111.2)

Simula passaggio Cost Report -> Fatturazione su N progetti random:
1. Cerca progetti con JCL maturate not_billed (status != cancelled)
2. Per ognuno:
   a. preview -> estrae JCL candidate + periodo
   b. transmit -> BillingBatch draft
   c. approve -> batch approved
   d. emit_invoice -> Invoice creata + slice + JCL billed
3. Su un sottoinsieme dei progetti emessi: storna 1 fattura -> NC TD04
4. Stampa riepilogo: progetti processati, batch creati, fatture emesse,
   NC emesse, errori.

Usage:
    .venv/Scripts/python.exe scripts/simulate_cr_to_billing.py [--n 20] [--storno 3]
"""
from __future__ import annotations

import argparse
import random
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import (
    Project, ProjectStatus,
    Job, JobStatus, JobCostLine, JCLBillingStatus,
    BillingBatch, BillingBatchStatus,
    Invoice, InvoiceStatus,
    Client, Tenant,
)
from app.routers.billing import _transmit_core
from sqlalchemy.orm import joinedload

CURRENT_TENANT = 1
RANDOM_SEED = 4242


def find_eligible_projects(db: Session, limit: int) -> list[Project]:
    """Progetti con JCL maturate not_billed: candidati per trasmissione."""
    rows = (
        db.query(Project)
        .join(Job, Job.project_id == Project.id)
        .join(JobCostLine, JobCostLine.job_id == Job.id)
        .filter(
            Project.tenant_id == CURRENT_TENANT,
            Project.deleted_at.is_(None),
            Project.status.in_([ProjectStatus.active, ProjectStatus.completed]),
            Job.status != JobStatus.cancelled,
            JobCostLine.billing_status == JCLBillingStatus.not_billed,
            JobCostLine.total_accrued > 0,
            JobCostLine.is_billable == True,  # noqa: E712
        )
        .distinct()
        .all()
    )
    random.shuffle(rows)
    return rows[:limit]


def simulate_one(db: Session, project: Project, issue_offset_days: int = 0) -> dict:
    """Full pipeline: transmit -> approve -> emit_invoice."""
    out = {"project_id": project.id, "project_code": project.code, "steps": [], "ok": False}
    # 1) Transmit
    try:
        tr = _transmit_core(
            db,
            project_id=project.id,
            include_extras=True,
            user_id=None,
        )
        n_lines = len(tr.get("lines") or [])
        out["steps"].append(f"transmit->{tr.get('code')} ({n_lines} righe, {tr.get('total_proposed', 0):.2f}€)")
    except Exception as e:
        out["error"] = f"transmit: {e}"
        return out
    batch = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.id == tr["id"]
    ).first()
    if not batch or not batch.lines:
        out["error"] = "batch vuoto post-transmit"
        return out
    # 2) Approve (status draft -> approved). Skip se zero righe approvate.
    batch.status = BillingBatchStatus.approved
    batch.total_approved = batch.total_proposed
    batch.approved_at = datetime.utcnow()
    db.commit()
    out["steps"].append(f"approve->{batch.code}")
    # 3) Emit invoice (compose-invoice equivalent inline)
    try:
        from app.models import InvoiceLine, JobCostLine as _JCL, JCLBilledSlice
        client = db.query(Client).filter(Client.id == project.client_id).first()
        tenant = db.query(Tenant).filter(Tenant.id == CURRENT_TENANT).first()
        if not client:
            out["error"] = "no client"
            return out
        # Numero univoco per tenant: prefix SIM- + epoch
        invoice_number = f"SIM-{project.code}-{int(datetime.utcnow().timestamp())}"
        issue_dt = date.today() + timedelta(days=issue_offset_days)
        subtotal = batch.total_approved
        vat_rate = 22.0
        vat_amount = subtotal * vat_rate / 100
        total = subtotal + vat_amount
        inv = Invoice(
            number=invoice_number,
            client_id=client.id,
            status=InvoiceStatus.draft,
            issue_date=issue_dt,
            due_date=issue_dt + timedelta(days=30),
            subtotal=subtotal,
            vat_rate=vat_rate,
            total=total,
            notes=f"Simulazione CR->billing per {project.code}",
            doc_type="TD01",
            client_legal_name_snap=client.name,
            client_vat_snap=client.vat_number,
            tenant_legal_name_snap=(tenant.legal_name or tenant.name) if tenant else None,
            tenant_vat_snap=(tenant.vat_number if tenant else None),
        )
        db.add(inv)
        db.flush()
        period_lbl = ""
        if batch.period_start and batch.period_end:
            period_lbl = f" [{batch.period_start.isoformat()} -> {batch.period_end.isoformat()}]"
        for bl in batch.lines:
            if (bl.total_approved or 0) <= 0:
                continue
            db.add(InvoiceLine(
                invoice_id=inv.id,
                description=bl.description + period_lbl,
                quantity=bl.quantity,
                unit_price=bl.unit_price,
                total=bl.total_approved,
                vat_rate=vat_rate,
                discount_pct=0.0,
            ))
            jcl = db.query(_JCL).filter(_JCL.id == bl.job_cost_line_id).first()
            if jcl:
                jcl.billing_status = JCLBillingStatus.billed
                jcl.billed_amount = bl.total_approved
            db.add(JCLBilledSlice(
                tenant_id=CURRENT_TENANT,
                job_cost_line_id=bl.job_cost_line_id,
                billing_batch_line_id=bl.id,
                invoice_id=inv.id,
                period_start=batch.period_start,
                period_end=batch.period_end,
                billed_quantity=bl.quantity or 0.0,
                billed_amount=bl.total_approved,
                unit_price_snap=bl.unit_price or 0.0,
            ))
        batch.status = BillingBatchStatus.invoiced
        batch.invoice_id = inv.id
        db.commit()
        out["steps"].append(f"invoice->{invoice_number} (tot {total:.2f}€)")
        out["batch_id"] = batch.id
        out["invoice_id"] = inv.id
        out["invoice_number"] = invoice_number
        out["ok"] = True
    except Exception as e:
        db.rollback()
        out["error"] = f"emit: {e}"
    return out


def simulate_storno(db: Session, invoice_id: int) -> dict:
    """Emette NC TD04 a storno."""
    from app.models import InvoiceLine, JCLBilledSlice, BillingBatch as _BB
    out = {"invoice_id": invoice_id, "ok": False}
    src = db.query(Invoice).options(joinedload(Invoice.lines)).filter(
        Invoice.id == invoice_id,
    ).first()
    if not src or src.doc_type == "TD04" or src.status == InvoiceStatus.cancelled:
        out["error"] = "ineligible"
        return out
    nc_number = f"NC-{src.number}"
    try:
        nc = Invoice(
            number=nc_number,
            client_id=src.client_id,
            status=InvoiceStatus.draft,
            issue_date=date.today(),
            subtotal=src.subtotal,
            vat_rate=src.vat_rate,
            total=src.total,
            notes=f"Simulazione storno {src.number}",
            doc_type="TD04",
            client_legal_name_snap=src.client_legal_name_snap,
            client_vat_snap=src.client_vat_snap,
            tenant_legal_name_snap=src.tenant_legal_name_snap,
            tenant_vat_snap=src.tenant_vat_snap,
        )
        db.add(nc)
        db.flush()
        for l in src.lines:
            db.add(InvoiceLine(
                invoice_id=nc.id,
                description=f"[Storno] {l.description}",
                quantity=l.quantity, unit_price=l.unit_price, total=l.total,
                vat_rate=l.vat_rate, discount_pct=l.discount_pct,
            ))
        slices = db.query(JCLBilledSlice).filter(JCLBilledSlice.invoice_id == src.id).all()
        for s in slices:
            if s.voided_at is None:
                s.voided_at = datetime.utcnow()
                s.voided_by_invoice_id = nc.id
        src.status = InvoiceStatus.cancelled
        # Riapri batch collegato
        batches = db.query(_BB).filter(_BB.invoice_id == src.id).all()
        for b in batches:
            b.invoice_id = None
            b.status = BillingBatchStatus.approved
        db.commit()
        out["nc_number"] = nc_number
        out["voided_slices"] = len(slices)
        out["reopened_batches"] = len(batches)
        out["ok"] = True
    except Exception as e:
        db.rollback()
        out["error"] = str(e)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20, help="Numero progetti da processare")
    parser.add_argument("--storno", type=int, default=3, help="Numero fatture da stornare")
    args = parser.parse_args()
    random.seed(RANDOM_SEED)
    db = SessionLocal()
    print(f"[sim] cerco {args.n} progetti eligible…")
    projects = find_eligible_projects(db, args.n)
    print(f"[sim] trovati {len(projects)} progetti")
    results = []
    for p in projects:
        r = simulate_one(db, p, issue_offset_days=random.randint(-30, 0))
        results.append(r)
        status = "OK" if r["ok"] else "X"
        print(f"  {status} {p.code}: {' -> '.join(r['steps'])}{(' [err: ' + r.get('error', '') + ']') if not r['ok'] else ''}")
    ok = [r for r in results if r["ok"]]
    print(f"\n[sim] OK: {len(ok)}/{len(results)}")
    # Storni
    if args.storno > 0 and ok:
        n_storno = min(args.storno, len(ok))
        targets = random.sample(ok, n_storno)
        print(f"\n[sim] storno NC TD04 su {n_storno} fatture…")
        for t in targets:
            r = simulate_storno(db, t["invoice_id"])
            status = "OK" if r["ok"] else "X"
            extra = f"NC {r['nc_number']}, voided {r['voided_slices']} slice, riaperti {r['reopened_batches']} batch" if r["ok"] else f"err: {r.get('error')}"
            print(f"  {status} inv {t['invoice_number']}: {extra}")
    # Riepilogo
    n_batches = db.query(BillingBatch).filter(BillingBatch.tenant_id == CURRENT_TENANT).count()
    n_invoiced = db.query(BillingBatch).filter(
        BillingBatch.tenant_id == CURRENT_TENANT,
        BillingBatch.status == BillingBatchStatus.invoiced,
    ).count()
    n_invoices_total = db.query(Invoice).count()
    n_invoices_td04 = db.query(Invoice).filter(Invoice.doc_type == "TD04").count()
    print(f"\n[sim] DB state: batches={n_batches} (invoiced={n_invoiced}), invoices total={n_invoices_total} (TD04={n_invoices_td04})")
    db.close()


if __name__ == "__main__":
    main()
