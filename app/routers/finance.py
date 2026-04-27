"""Router finanza — timesheet, spese, fatture, P&L."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Timesheet, Expense, Invoice, InvoiceLine, InvoiceStatus
from app.services.finance import job_financial_summary, company_pl_summary

router = APIRouter(prefix="/finance", tags=["finance"])


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ───────────────────────────────────────────────────────

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


@router.post("/api/timesheets")
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

@router.post("/api/expenses")
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


@router.post("/api/invoices")
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


@router.post("/api/invoices/{invoice_id}/lines")
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


@router.put("/api/invoices/{invoice_id}/status")
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
