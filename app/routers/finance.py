"""Router finanza — timesheet, spese, fatture, P&L."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models import (
    Timesheet, Expense, Invoice, InvoiceLine, InvoiceStatus, InvoicePayment,
    Job, JobStatus, JobCostLine, Quote, QuoteStatus, Project,
)
from app.services.finance import job_financial_summary, company_pl_summary, departments_pl_summary
from app.services.rbac import requires_permission

router = APIRouter(prefix="/finance", tags=["finance"])

# v3.5.0-alpha.66.16.0 — Sprint R3 (permission gate sweep). Pattern
# identico a quotes.RequireEditQuotes (α.66.14.5).
RequireEditInvoices = Depends(requires_permission("edit_invoices"))
RequireEditPlanningOwn = Depends(requires_permission("edit_planning_own"))


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ───────────────────────────────────────────────────────


@router.get("/cashflow", response_class=HTMLResponse)
async def cashflow_page(request: Request, db: Session = Depends(get_db)):
    """Pagina cashflow timeline 12 mesi (revenue-side)."""
    return _tpl().TemplateResponse(
        "pages/cashflow.html", {"request": request}
    )


@router.get("/", response_class=HTMLResponse)
async def finance_page(request: Request, db: Session = Depends(get_db)):
    invoices = db.query(Invoice).options(joinedload(Invoice.client)).order_by(Invoice.issue_date.desc()).all()
    return _tpl().TemplateResponse(
        "pages/finance.html", {"request": request, "invoices": invoices}
    )


# ── Timesheet API ─────────────────────────────────────────────────────

@router.get("/api/timesheets")
async def list_timesheets(
    job_id: Optional[int] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Timesheet)
    if job_id:
        q = q.filter(Timesheet.job_id == job_id)
    if user_id:
        q = q.filter(Timesheet.user_id == user_id)
    return q.all()


@router.post("/api/timesheets", dependencies=[RequireEditPlanningOwn])
async def log_hours(
    user_id: int = Form(...),
    job_id: int = Form(...),
    work_date: date = Form(...),
    hours: float = Form(...),
    hourly_rate: Optional[float] = Form(None),
    description: Optional[str] = Form(None),
    is_billable: bool = Form(True),
    db: Session = Depends(get_db),
):
    t = Timesheet(
        user_id=user_id, job_id=job_id, work_date=work_date,
        hours=hours, hourly_rate=hourly_rate, description=description,
        is_billable=is_billable,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ── Spese API ─────────────────────────────────────────────────────────

@router.post("/api/expenses", dependencies=[RequireEditInvoices])
async def add_expense(
    job_id: int = Form(...),
    description: str = Form(...),
    amount: float = Form(...),
    expense_date: date = Form(...),
    category: Optional[str] = Form(None),
    is_billable: bool = Form(True),
    db: Session = Depends(get_db),
):
    e = Expense(
        job_id=job_id, description=description, amount=amount,
        expense_date=expense_date, category=category, is_billable=is_billable,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


# ── Fatture API ───────────────────────────────────────────────────────

@router.get("/api/invoices")
async def list_invoices(
    status: Optional[InvoiceStatus] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Invoice).options(joinedload(Invoice.client))
    if status:
        q = q.filter(Invoice.status == status)
    if client_id:
        q = q.filter(Invoice.client_id == client_id)
    return q.all()


@router.post("/api/invoices", dependencies=[RequireEditInvoices])
async def create_invoice(
    number: str = Form(...),
    client_id: int = Form(...),
    job_id: Optional[int] = Form(None),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    vat_rate: float = Form(22.0),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    inv = Invoice(
        number=number, client_id=client_id, job_id=job_id,
        issue_date=issue_date, due_date=due_date,
        vat_rate=vat_rate, notes=notes,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/api/invoices/{invoice_id}/lines", dependencies=[RequireEditInvoices])
async def add_invoice_line(
    invoice_id: int,
    description: str = Form(...),
    quantity: float = Form(1.0),
    unit_price: float = Form(...),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Fattura non trovata")
    total = quantity * unit_price
    line = InvoiceLine(
        invoice_id=invoice_id, description=description,
        quantity=quantity, unit_price=unit_price, total=total,
    )
    db.add(line)
    # Ricalcola totali fattura
    inv.subtotal += total
    inv.total = inv.subtotal * (1 + inv.vat_rate / 100)
    db.commit()
    return line


@router.put("/api/invoices/{invoice_id}/status", dependencies=[RequireEditInvoices])
async def update_invoice_status(
    invoice_id: int,
    status: InvoiceStatus = Form(...),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Fattura non trovata")
    inv.status = status
    db.commit()
    return {"id": inv.id, "status": inv.status}


# ── Report API ────────────────────────────────────────────────────────

@router.get("/api/report/job/{job_id}")
async def job_report(job_id: int, db: Session = Depends(get_db)):
    return job_financial_summary(db, job_id)


@router.get("/api/report/pl/{year}")
async def annual_pl(year: int, db: Session = Depends(get_db)):
    return company_pl_summary(db, year)


@router.get("/api/report/departments/{year}")
async def departments_pl(year: int, db: Session = Depends(get_db)):
    """Aggregato ricavi/costi per reparto, anno corrente.
    Usato dalla dashboard per il widget "Margine per reparto".
    """
    return departments_pl_summary(db, year)


# ── Pagamenti fattura (v3.5.0-alpha.66.20) ────────────────────────────


def _refresh_invoice_payment_state(db: Session, invoice: Invoice) -> None:
    """Ricomputa amount_paid e auto-aggiorna status:
    - amount_paid >= total → InvoiceStatus.paid
    - amount_paid in (0, total) → resta sent (parziale, UI mostra residuo)
    - amount_paid == 0 e era paid → torna a sent (rollback pagamento)
    Idempotente. Chiamato dopo INSERT/DELETE InvoicePayment.
    """
    total_paid = sum((p.amount or 0.0) for p in invoice.payments)
    invoice.amount_paid = round(total_paid, 2)
    inv_total = invoice.total or 0.0
    if invoice.amount_paid >= inv_total - 0.01 and inv_total > 0:
        invoice.status = InvoiceStatus.paid
    elif invoice.status == InvoiceStatus.paid and invoice.amount_paid < inv_total - 0.01:
        invoice.status = InvoiceStatus.sent


@router.get("/api/invoices/{invoice_id}/payments")
async def list_invoice_payments(invoice_id: int, db: Session = Depends(get_db)):
    """Lista pagamenti registrati per una fattura."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Fattura non trovata")
    rows = sorted(inv.payments, key=lambda p: p.payment_date or date.min, reverse=True)
    return {
        "invoice_id": invoice_id,
        "invoice_total": round(inv.total or 0.0, 2),
        "amount_paid": round(inv.amount_paid or 0.0, 2),
        "amount_remaining": round(max(0.0, (inv.total or 0.0) - (inv.amount_paid or 0.0)), 2),
        "payments": [
            {
                "id": p.id,
                "amount": p.amount,
                "payment_date": str(p.payment_date) if p.payment_date else None,
                "method": p.method,
                "reference": p.reference,
                "notes": p.notes,
                "created_at": str(p.created_at)[:19] if p.created_at else None,
            }
            for p in rows
        ],
    }


@router.post("/api/invoices/{invoice_id}/payments", dependencies=[RequireEditInvoices])
async def create_invoice_payment(
    invoice_id: int,
    request: Request,
    amount: float = Form(...),
    payment_date: date = Form(...),
    method: Optional[str] = Form(None),
    reference: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Registra un pagamento (anche parziale) su una fattura.

    Auto-aggiorna `Invoice.amount_paid` e `Invoice.status=paid` se il
    cumulativo supera il totale. Non blocca pagamenti che superano il
    totale (overpayment manuale, raro ma possibile per arrotondamenti);
    documentabile via `notes`.
    """
    if amount <= 0:
        raise HTTPException(400, "Importo deve essere > 0")
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Fattura non trovata")
    if inv.status == InvoiceStatus.cancelled:
        raise HTTPException(409, "Fattura cancellata: pagamenti non ammessi")

    user = getattr(request.state, "current_user", None)
    payment = InvoicePayment(
        tenant_id=getattr(inv, "tenant_id", 1) or 1,
        invoice_id=invoice_id,
        amount=round(amount, 2),
        payment_date=payment_date,
        method=(method or "").strip() or None,
        reference=(reference or "").strip() or None,
        notes=(notes or "").strip() or None,
        recorded_by_user_id=user.id if user else None,
    )
    db.add(payment)
    db.flush()
    db.refresh(inv)
    _refresh_invoice_payment_state(db, inv)
    db.commit()
    return {
        "id": payment.id,
        "invoice_id": invoice_id,
        "amount_paid": inv.amount_paid,
        "status": inv.status,
    }


@router.delete("/api/payments/{payment_id}", dependencies=[RequireEditInvoices])
async def delete_invoice_payment(payment_id: int, db: Session = Depends(get_db)):
    """Elimina un pagamento (annulla incasso). Ricomputa amount_paid + status."""
    p = db.query(InvoicePayment).filter(InvoicePayment.id == payment_id).first()
    if not p:
        raise HTTPException(404, "Pagamento non trovato")
    inv = db.query(Invoice).filter(Invoice.id == p.invoice_id).first()
    db.delete(p)
    db.flush()
    if inv is not None:
        db.refresh(inv)
        _refresh_invoice_payment_state(db, inv)
    db.commit()
    return {"deleted": True, "invoice_id": p.invoice_id, "amount_paid": (inv.amount_paid if inv else None)}


# ── Cashflow timeline (v3.5.0-alpha.66.20) ────────────────────────────


@router.get("/api/cashflow/{year}")
async def cashflow_year(year: int, db: Session = Depends(get_db)):
    """Cashflow revenue-side aggregato per mese dell'anno.

    Per ogni mese ritorna:
      - invoiced: somma Invoice.total emesse (status sent/paid/overdue)
      - paid: somma InvoicePayment.amount per pagamenti del mese
      - outstanding: somma Invoice.total ancora non pagate
        (issue_date nel mese, status != paid)

    Non considera costi (questi arriveranno in α.67 con Resource cost-rate
    + supplier invoice in α.68).
    """
    from sqlalchemy import extract

    series = [
        {"month": m, "invoiced": 0.0, "paid": 0.0, "outstanding": 0.0}
        for m in range(1, 13)
    ]
    invoices = db.query(Invoice).filter(
        extract("year", Invoice.issue_date) == year,
        Invoice.status != InvoiceStatus.cancelled,
    ).all()
    for inv in invoices:
        m = inv.issue_date.month if inv.issue_date else 1
        if inv.status in (InvoiceStatus.sent, InvoiceStatus.paid, InvoiceStatus.overdue, InvoiceStatus.draft):
            series[m - 1]["invoiced"] += inv.total or 0.0
        remaining = max(0.0, (inv.total or 0.0) - (inv.amount_paid or 0.0))
        if remaining > 0 and inv.status != InvoiceStatus.paid:
            series[m - 1]["outstanding"] += remaining

    payments = db.query(InvoicePayment).filter(
        extract("year", InvoicePayment.payment_date) == year,
    ).all()
    for p in payments:
        m = p.payment_date.month if p.payment_date else 1
        series[m - 1]["paid"] += p.amount or 0.0

    for s in series:
        s["invoiced"] = round(s["invoiced"], 2)
        s["paid"] = round(s["paid"], 2)
        s["outstanding"] = round(s["outstanding"], 2)
    return {"year": year, "months": series}


# ── Anomalie financial (v3.4.39) ──────────────────────────────────────


@router.get("/api/anomalies/floating-jobs")
async def list_floating_jobs(db: Session = Depends(get_db)):
    """Job senza quote_id (orfani). Possono nascere da migrazione versioning con
    `orphan_strategy=floating_job`, o da cancellazione manuale della quote.

    Ritorna la lista per la sezione Anomalie di /finance, e per generare
    notifiche `job_floating_alert` periodiche."""
    jobs = (
        db.query(Job)
        .options(joinedload(Job.project), joinedload(Job.client), joinedload(Job.cost_lines))
        .filter(Job.quote_id.is_(None))
        .filter(Job.status != JobStatus.cancelled)
        .order_by(Job.created_at.desc()).all()
    )
    return [
        {
            "id": j.id, "code": j.code, "title": j.title,
            "status": j.status,
            "project_id": j.project_id,
            "project_title": j.project.title if j.project else None,
            "project_code": j.project.code if j.project else None,
            "client": j.client.name if j.client else None,
            "budget_quoted": j.budget_quoted,
            "cost_lines_count": len(j.cost_lines),
            "actual_total": sum(
                (jcl.quantity_actual or 0) * (jcl.unit_price or 0)
                for jcl in j.cost_lines
            ),
            "created_at": str(j.created_at)[:10] if j.created_at else None,
            "start_date": str(j.start_date) if j.start_date else None,
            "end_date": str(j.end_date) if j.end_date else None,
        }
        for j in jobs
    ]


@router.get("/api/anomalies/discrepancies")
async def list_discrepancies(db: Session = Depends(get_db)):
    """Discrepanze quote/consuntivo. Tre tipi:

    1. Sforamenti monte ore: JobCostLine con quantity_actual > quantity_quoted
       (su righe non-extra). Indica che il consuntivo ha superato il preventivo.
    2. Extra puri: JobCostLine con is_extra=True. Lavorazioni aggiunte dopo
       l'approvazione, non coperte dalla quote ufficiale.
    3. JobCostLine con quote_line_id NULL ma is_extra=False (anomalia derivata
       da migrazione orfani con keep_as_extra: il flag is_extra dovrebbe essere
       True; questo identifica eventuali errori di data integrity)."""
    overruns = []
    extras = []
    inconsistent = []

    cost_lines = (
        db.query(JobCostLine)
        .options(joinedload(JobCostLine.job).joinedload(Job.project))
        .filter(JobCostLine.job_id.isnot(None))
        .all()
    )
    for jcl in cost_lines:
        if not jcl.job or jcl.job.status == JobStatus.cancelled:
            continue
        actual = jcl.quantity_actual or 0
        quoted = jcl.quantity_quoted or 0
        delta = actual - quoted
        if not jcl.is_extra and delta > 0.001:
            overruns.append({
                "jobcostline_id": jcl.id,
                "job_id": jcl.job_id,
                "job_code": jcl.job.code,
                "project_title": jcl.job.project.title if jcl.job.project else None,
                "description": jcl.description,
                "quantity_quoted": quoted,
                "quantity_actual": actual,
                "delta": round(delta, 2),
                "unit": jcl.unit,
                "extra_value": round(delta * (jcl.unit_price or 0), 2),
            })
        if jcl.is_extra:
            extras.append({
                "jobcostline_id": jcl.id,
                "job_id": jcl.job_id,
                "job_code": jcl.job.code,
                "project_title": jcl.job.project.title if jcl.job.project else None,
                "description": jcl.description,
                "quantity_actual": actual,
                "unit": jcl.unit,
                "total_value": round(actual * (jcl.unit_price or 0), 2),
            })
        if not jcl.is_extra and not jcl.quote_line_id:
            inconsistent.append({
                "jobcostline_id": jcl.id,
                "job_id": jcl.job_id,
                "job_code": jcl.job.code,
                "description": jcl.description,
                "issue": "is_extra=False ma quote_line_id=NULL",
            })

    return {
        "overruns": overruns,
        "extras": extras,
        "inconsistent": inconsistent,
        "total_overrun_value": round(sum(o["extra_value"] for o in overruns), 2),
        "total_extras_value": round(sum(e["total_value"] for e in extras), 2),
    }


@router.get("/api/anomalies/summary")
async def anomalies_summary(db: Session = Depends(get_db)):
    """Counter aggregato per badge / topbar / dashboard."""
    floating_count = (
        db.query(func.count(Job.id))
        .filter(Job.quote_id.is_(None))
        .filter(Job.status != JobStatus.cancelled)
        .scalar() or 0
    )
    extras_count = (
        db.query(func.count(JobCostLine.id))
        .join(Job, JobCostLine.job_id == Job.id)
        .filter(JobCostLine.is_extra.is_(True))
        .filter(Job.status != JobStatus.cancelled)
        .scalar() or 0
    )
    superseded_count = (
        db.query(func.count(Quote.id))
        .filter(Quote.status == QuoteStatus.superseded)
        .scalar() or 0
    )
    return {
        "floating_jobs": floating_count,
        "extras": extras_count,
        "superseded_quotes": superseded_count,
    }


# ── PDF Export ────────────────────────────────────────────────────────

@router.get("/api/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(invoice_id: int, db: Session = Depends(get_db)):
    """Genera e scarica il PDF della fattura."""
    from app.services.pdf_export import generate_invoice_pdf
    from fastapi.responses import Response

    inv = db.query(Invoice).options(
        joinedload(Invoice.client),
        joinedload(Invoice.lines),
    ).filter(Invoice.id == invoice_id).first()

    if not inv:
        raise HTTPException(404, "Fattura non trovata")

    invoice_data = {
        "number":      inv.number,
        "issue_date":  inv.issue_date.strftime("%d/%m/%Y") if inv.issue_date else "—",
        "due_date":    inv.due_date.strftime("%d/%m/%Y") if inv.due_date else None,
        "client_name": inv.client.name if inv.client else "—",
        "client_info": f"P.IVA {inv.client.vat_number}" if inv.client and inv.client.vat_number else "",
        "subtotal":    inv.subtotal,
        "vat_rate":    inv.vat_rate,
        "total":       inv.total,
        "notes":       inv.notes,
    }
    lines_data = [
        {
            "description": l.description,
            "quantity":    l.quantity,
            "unit_price":  l.unit_price,
            "total":       l.total,
        }
        for l in inv.lines
    ]

    pdf_bytes = generate_invoice_pdf(invoice_data, lines_data)
    filename = f"fattura_{inv.number.replace('/', '-')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
