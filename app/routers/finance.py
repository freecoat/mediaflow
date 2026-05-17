"""Router finanza — timesheet, spese, fatture, P&L."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models import (
    Timesheet, Expense, Invoice, InvoiceLine, InvoiceStatus, InvoiceKind, InvoicePayment,
    AdvancePayment, AdvancePaymentConsumption, AdvancePaymentStatus,
    Job, JobStatus, JobCostLine, Quote, QuoteStatus, Project, Tenant, Client,
    SupplierInvoice, SupplierInvoiceStatus, SupplierInvoicePayment,
)
from app.services.finance import job_financial_summary, company_pl_summary, departments_pl_summary
from app.services.rbac import requires_permission
from app.context import current_tenant_id

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
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.86 — Filtri estesi (S3.1): client/project/period.
    Filtri cliente/progetto richiedono join con Job."""
    q = db.query(Timesheet)
    if job_id:
        q = q.filter(Timesheet.job_id == job_id)
    if user_id:
        q = q.filter(Timesheet.user_id == user_id)
    if client_id or project_id:
        from app.models import Job as _Job
        q = q.join(_Job, Timesheet.job_id == _Job.id)
        if client_id:
            q = q.filter(_Job.client_id == client_id)
        if project_id:
            q = q.filter(_Job.project_id == project_id)
    if from_date:
        q = q.filter(Timesheet.work_date >= from_date)
    if to_date:
        q = q.filter(Timesheet.work_date <= to_date)
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
    project_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    only_overdue: bool = False,
    number: Optional[str] = None,  # v3.5.0-alpha.112 — search by invoice number
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.86 — Filtri estesi (S3.1): project + period.
    project_id richiede join via Job.

    v3.5.0-alpha.88: only_overdue=true filtra fatture *davvero* scadute
    (due_date < oggi AND status NOT IN (paid, cancelled)) anche se non
    marcate esplicitamente come overdue.

    v3.5.0-alpha.90: ritorna dict arricchito con project (via Job.project).
    Era ORM raw → mancava il progetto in lista fatture (ticket Matteo)."""
    from app.models import Job as _Job, Project as _Project
    q = db.query(Invoice).options(
        joinedload(Invoice.client),
        joinedload(Invoice.job).joinedload(_Job.project),
        joinedload(Invoice.lines),  # v3.5.0-alpha.114 — per drift detection
    )
    if status:
        q = q.filter(Invoice.status == status)
    if client_id:
        q = q.filter(Invoice.client_id == client_id)
    if project_id:
        q = q.join(_Job, Invoice.job_id == _Job.id).filter(_Job.project_id == project_id)
    if from_date:
        q = q.filter(Invoice.issue_date >= from_date)
    if to_date:
        q = q.filter(Invoice.issue_date <= to_date)
    if only_overdue:
        from datetime import date as _date
        today = _date.today()
        q = q.filter(
            Invoice.due_date.isnot(None),
            Invoice.due_date < today,
            Invoice.status.notin_([InvoiceStatus.paid, InvoiceStatus.cancelled]),
        )
    # v3.5.0-alpha.112 — ricerca libera su numero fattura (ilike)
    if number:
        like = f"%{number.strip()}%"
        q = q.filter(Invoice.number.ilike(like))
    out = []
    for inv in q.all():
        proj = inv.job.project if (inv.job and inv.job.project) else None
        # v3.5.0-alpha.114 — drift detection per UI badge ⚠
        lines_sum = round(sum((l.total or 0) for l in inv.lines), 2) if inv.lines else 0
        has_drift = (
            bool(inv.lines) and (inv.subtotal or 0) > 0
            and abs((inv.subtotal or 0) - lines_sum) > 0.01
        )
        out.append({
            "id": inv.id,
            "number": inv.number,
            "client_id": inv.client_id,
            "client": ({"id": inv.client.id, "name": inv.client.name} if inv.client else None),
            "job_id": inv.job_id,
            "job": ({"id": inv.job.id, "code": inv.job.code, "title": inv.job.title} if inv.job else None),
            "project": ({"id": proj.id, "code": proj.code, "title": proj.title} if proj else None),
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "subtotal": inv.subtotal,
            "vat_rate": inv.vat_rate,
            "total": inv.total,
            "status": inv.status.value if hasattr(inv.status, "value") else inv.status,
            "notes": inv.notes,
            "doc_type": getattr(inv, "doc_type", None),
            "payment_method": getattr(inv, "payment_method", None),
            # v3.5.0-alpha.114 — drift fields
            "lines_sum": lines_sum,
            "has_drift": has_drift,
        })
    return out


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


# v3.5.0-alpha.114 — Immutabilità fattura: una volta uscita da draft,
# nessuna modifica al contenuto. Solo storno via NC TD04 + riemissione.
# Stati MUTABLE: draft. Tutti gli altri (sent/paid/overdue/cancelled): IMMUTABLE.
_MUTABLE_INVOICE_STATES = (InvoiceStatus.draft,)


def _enforce_invoice_mutable(inv: Invoice):
    """Solleva 409 se la fattura non è più modificabile (post-emissione).
    Da chiamare in tutti i mutator di Invoice/InvoiceLine."""
    if inv.status not in _MUTABLE_INVOICE_STATES:
        raise HTTPException(
            409,
            f"Fattura {inv.number} è in stato '{inv.status.value if hasattr(inv.status, 'value') else inv.status}' "
            "e non è più modificabile. Le fatture emesse sono immutabili. "
            "Per correggere: storna via Nota di Credito (TD04) e riemetti."
        )


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
    _enforce_invoice_mutable(inv)  # v3.5.0-alpha.114
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
    # v3.5.0-alpha.114 — transizioni stato consentite:
    #   draft → sent (emissione)
    #   sent → paid (pagamento)
    #   sent → overdue (auto/manuale)
    #   sent/paid/overdue → cancelled (solo via storno NC TD04 — vedi billing)
    # Bloccare regressioni (paid → draft, cancelled → sent, etc.)
    _ALLOWED = {
        InvoiceStatus.draft: {InvoiceStatus.sent, InvoiceStatus.cancelled},
        InvoiceStatus.sent: {InvoiceStatus.paid, InvoiceStatus.overdue, InvoiceStatus.cancelled},
        InvoiceStatus.overdue: {InvoiceStatus.paid, InvoiceStatus.cancelled},
        InvoiceStatus.paid: set(),  # paid è terminal: solo storno NC
        InvoiceStatus.cancelled: set(),  # cancelled terminal
    }
    cur = inv.status
    if status != cur and status not in _ALLOWED.get(cur, set()):
        raise HTTPException(
            409,
            f"Transizione stato {cur} → {status} non consentita. "
            "Le fatture emesse sono immutabili: per correggere usa storno NC TD04."
        )
    inv.status = status
    # v3.5.0-alpha.120 (F13) — Quando l'utente marca la fattura paid via UI
    # senza creare un InvoicePayment esplicito, allinea amount_paid = total
    # così outstanding nel cashflow scende a 0. Prima il cambio status era
    # cosmetico per il cashflow: amount_paid restava 0 → remaining = total →
    # outstanding contribuiva ancora come "aperto" anche se status=paid.
    # Idempotente: se l'utente registra un InvoicePayment in seguito, il
    # ricalcolo amount_paid lo sovrascrive correttamente.
    if status == InvoiceStatus.paid:
        total = inv.total or 0.0
        if (inv.amount_paid or 0.0) < total:
            inv.amount_paid = total
    db.commit()
    return {"id": inv.id, "status": inv.status}


# ── Acconti progetto (v3.5.0-alpha.136) ────────────────────────────
# Pattern B della decision tree F26/F28: ledger AdvancePayment separato
# che lega Invoice(kind=advance) a Project. Si scompute progressivamente nelle
# fatture batch successive (SAL) e nella closing invoice.
# Vedi app/models/models.py AdvancePayment per semantica completa.


def _next_invoice_number_for_advance(db: Session, year: int) -> str:
    """Genera prossimo numero progressivo formato `{year}-{NNN}` per acconto.
    Stessa convenzione di emit_invoice (manuale via UI). Tenant-scoped.
    Idempotente: re-genera incrementando finché non collide con numero esistente."""
    from sqlalchemy import desc
    # Pesca ultimo numero del tenant per l'anno
    last = (
        db.query(Invoice.number)
        .join(Client, Invoice.client_id == Client.id)
        .filter(
            Client.tenant_id == current_tenant_id(),
            Invoice.number.like(f"{year}-%"),
        )
        .order_by(desc(Invoice.number))
        .first()
    )
    if not last:
        return f"{year}-00001"
    try:
        seq = int(last[0].split("-")[1]) + 1
    except (ValueError, IndexError):
        seq = 1
    # Loop di sicurezza fino a slot libero
    for _ in range(1000):
        candidate = f"{year}-{seq:05d}"
        exists = (
            db.query(Invoice.id)
            .join(Client, Invoice.client_id == Client.id)
            .filter(
                Client.tenant_id == current_tenant_id(),
                Invoice.number == candidate,
            )
            .first()
        )
        if not exists:
            return candidate
        seq += 1
    raise HTTPException(500, "Impossibile generare numero progressivo univoco")


@router.post("/api/projects/{project_id}/advances", dependencies=[RequireEditInvoices])
async def create_advance_payment(
    project_id: int,
    request: Request,
    amount: float = Form(...),
    description: str = Form("Acconto"),
    vat_rate: float = Form(22.0),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    invoice_number: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.136 — Crea acconto su progetto.

    Genera 1 Invoice(kind=advance, project_id=X, doc_type=TD01) con 1 InvoiceLine
    descrittiva + apre 1 AdvancePayment(balance=amount, status=open).
    L'invoice nasce in stato draft come tutte le fatture: il manager dovrà
    transire a sent/paid via /api/invoices/{id}/status quando appropriato.

    Snapshot fiscali client+tenant come emit_invoice (immutabilità post-emissione)."""
    if amount <= 0:
        raise HTTPException(400, "Importo deve essere positivo")
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not proj:
        raise HTTPException(404, "Progetto non trovato")
    if not proj.client_id:
        raise HTTPException(400, "Progetto senza cliente: assegna cliente prima di creare acconto")
    client_obj = db.query(Client).filter(Client.id == proj.client_id).first()
    tenant_obj = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()

    # Numero: auto se non fornito (formato {year}-{NNNNN} come emit_invoice manuale)
    if invoice_number:
        existing = (
            db.query(Invoice)
            .join(Client, Invoice.client_id == Client.id)
            .filter(
                Invoice.number == invoice_number,
                Client.tenant_id == current_tenant_id(),
            )
            .first()
        )
        if existing:
            raise HTTPException(409, f"Numero fattura {invoice_number} già esistente")
        num = invoice_number
    else:
        num = _next_invoice_number_for_advance(db, issue_date.year)

    subtotal = round(amount, 2)
    vat_amount = round(subtotal * vat_rate / 100, 2)
    total = round(subtotal + vat_amount, 2)

    inv = Invoice(
        number=num,
        client_id=proj.client_id,
        project_id=project_id,
        kind=InvoiceKind.advance,
        status=InvoiceStatus.draft,
        issue_date=issue_date,
        due_date=due_date,
        subtotal=subtotal,
        vat_rate=vat_rate,
        total=total,
        notes=(notes or f"Acconto progetto {proj.code}"),
        doc_type="TD01",
        payment_method=(tenant_obj.payment_method_default if tenant_obj else None),
        payment_terms_days=(tenant_obj.payment_terms_default if tenant_obj else None),
        iban_snapshot=(tenant_obj.iban if tenant_obj else None),
        client_legal_name_snap=(client_obj.name if client_obj else None),
        client_vat_snap=(client_obj.vat_number if client_obj else None),
        client_tax_code_snap=(client_obj.tax_code if client_obj else None),
        client_pec_snap=(client_obj.pec if client_obj else None),
        client_admin_email_snap=(getattr(client_obj, "admin_email", None) if client_obj else None),
        client_sdi_snap=(client_obj.sdi_code if client_obj else None),
        client_address_snap=(client_obj.address if client_obj else None),
        client_zip_snap=(client_obj.zip_code if client_obj else None),
        client_city_snap=(client_obj.city if client_obj else None),
        client_province_snap=(client_obj.province if client_obj else None),
        client_country_snap=(client_obj.country if client_obj else None),
        tenant_legal_name_snap=((tenant_obj.legal_name or tenant_obj.name) if tenant_obj else None),
        tenant_vat_snap=(tenant_obj.vat_number if tenant_obj else None),
        tenant_tax_code_snap=(tenant_obj.tax_code if tenant_obj else None),
        tenant_address_snap=(tenant_obj.address if tenant_obj else None),
        tenant_email_snap=(tenant_obj.email if tenant_obj else None),
        tenant_phone_snap=(tenant_obj.phone if tenant_obj else None),
        tenant_iban_snap=(tenant_obj.iban if tenant_obj else None),
        tenant_sdi_snap=(tenant_obj.sdi_code if tenant_obj else None),
    )
    db.add(inv)
    db.flush()
    line = InvoiceLine(
        invoice_id=inv.id,
        description=description or f"Acconto progetto {proj.code}",
        quantity=1.0, unit_price=subtotal, total=subtotal,
        vat_rate=vat_rate, discount_pct=0.0,
    )
    db.add(line)
    # Ledger: open con balance = full amount
    user_id = getattr(getattr(request.state, "user", None), "id", None)
    ap = AdvancePayment(
        tenant_id=current_tenant_id(),
        project_id=project_id,
        invoice_id=inv.id,
        amount=subtotal,
        balance_remaining=subtotal,
        status=AdvancePaymentStatus.open,
        notes=notes,
        created_by_user_id=user_id,
    )
    db.add(ap)
    db.commit()
    db.refresh(inv)
    db.refresh(ap)
    return {
        "advance_payment_id": ap.id,
        "invoice_id": inv.id,
        "invoice_number": inv.number,
        "amount": subtotal, "vat_rate": vat_rate, "total": total,
        "balance_remaining": ap.balance_remaining,
        "status": ap.status.value,
    }


@router.get("/api/projects/{project_id}/advances")
async def list_project_advances(project_id: int, db: Session = Depends(get_db)):
    """Lista acconti del progetto + totali. Usata in cost-report card "Acconti"."""
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not proj:
        raise HTTPException(404, "Progetto non trovato")
    rows = (
        db.query(AdvancePayment)
        .options(joinedload(AdvancePayment.invoice), joinedload(AdvancePayment.consumptions))
        .filter(
            AdvancePayment.tenant_id == current_tenant_id(),
            AdvancePayment.project_id == project_id,
        )
        .order_by(AdvancePayment.created_at.asc())
        .all()
    )
    out = []
    total_amount = 0.0
    total_balance = 0.0
    total_consumed = 0.0
    for ap in rows:
        consumed = sum((c.amount_consumed or 0) for c in ap.consumptions)
        inv = ap.invoice
        is_cancelled = (ap.status == AdvancePaymentStatus.cancelled)
        if not is_cancelled:
            total_amount += ap.amount or 0
            total_balance += ap.balance_remaining or 0
            total_consumed += consumed
        out.append({
            "id": ap.id,
            "status": ap.status.value,
            "amount": round(ap.amount or 0, 2),
            "balance_remaining": round(ap.balance_remaining or 0, 2),
            "consumed": round(consumed, 2),
            "notes": ap.notes,
            "created_at": ap.created_at.isoformat() if ap.created_at else None,
            "invoice": {
                "id": inv.id, "number": inv.number,
                "status": inv.status.value if hasattr(inv.status, "value") else inv.status,
                "issue_date": str(inv.issue_date) if inv.issue_date else None,
                "due_date": str(inv.due_date) if inv.due_date else None,
                "amount_paid": round(inv.amount_paid or 0, 2),
                "total": round(inv.total or 0, 2),
            } if inv else None,
        })
    return {
        "project_id": project_id, "rows": out,
        "totals": {
            "amount": round(total_amount, 2),
            "consumed": round(total_consumed, 2),
            "balance_remaining": round(total_balance, 2),
        },
    }


@router.post("/api/advances/{advance_id}/cancel", dependencies=[RequireEditInvoices])
async def cancel_advance_payment(advance_id: int, db: Session = Depends(get_db)):
    """Annulla acconto. Consentito solo se balance_remaining == amount (nessun consumo).
    Marca AdvancePayment.status=cancelled. L'Invoice associata NON viene toccata
    (l'utente userà /api/invoices/{id}/status separatamente per cancellarla via NC TD04)."""
    ap = db.query(AdvancePayment).filter(
        AdvancePayment.id == advance_id,
        AdvancePayment.tenant_id == current_tenant_id(),
    ).first()
    if not ap:
        raise HTTPException(404, "Acconto non trovato")
    if ap.status == AdvancePaymentStatus.cancelled:
        raise HTTPException(409, "Acconto già annullato")
    consumed = sum((c.amount_consumed or 0) for c in ap.consumptions)
    if consumed > 0.001:
        raise HTTPException(
            409,
            f"Acconto ha già consumi per €{consumed:.2f}. Annullamento bloccato. "
            "Per stornare: emetti NC TD04 sull'invoice associata."
        )
    ap.status = AdvancePaymentStatus.cancelled
    ap.balance_remaining = 0.0
    db.commit()
    return {"id": ap.id, "status": ap.status.value}


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

    v3.5.0-alpha.111.18 — Propaga lo stato pagamento ai JCL collegati via
    JCLBilledSlice. Senza questa propagazione il cost report mostrava
    "Da fatturare" anche per cost line con fattura già "pagata" (gap
    diagnosticato: JCLBillingStatus.paid esisteva ma mai transito).
    """
    from app.models.models import JCLBilledSlice, JCLBillingStatus
    total_paid = sum((p.amount or 0.0) for p in invoice.payments)
    invoice.amount_paid = round(total_paid, 2)
    inv_total = invoice.total or 0.0
    prev_status = invoice.status
    if invoice.amount_paid >= inv_total - 0.01 and inv_total > 0:
        invoice.status = InvoiceStatus.paid
    elif invoice.status == InvoiceStatus.paid and invoice.amount_paid < inv_total - 0.01:
        invoice.status = InvoiceStatus.sent

    # Propagazione JCL — solo su transizione effettiva di stato.
    if prev_status != invoice.status:
        slices = (
            db.query(JCLBilledSlice)
            .filter(JCLBilledSlice.invoice_id == invoice.id)
            .all()
        )
        jcl_ids = {s.job_cost_line_id for s in slices if s.job_cost_line_id}
        if jcl_ids:
            jcls = db.query(JobCostLine).filter(JobCostLine.id.in_(jcl_ids)).all()
            for jcl in jcls:
                cur = jcl.billing_status
                if invoice.status == InvoiceStatus.paid:
                    # billed → paid (solo se era in stato avanzato)
                    if cur in (JCLBillingStatus.billed, JCLBillingStatus.in_batch):
                        jcl.billing_status = JCLBillingStatus.paid
                elif prev_status == InvoiceStatus.paid:
                    # paid → sent rollback: paid → billed
                    if cur == JCLBillingStatus.paid:
                        jcl.billing_status = JCLBillingStatus.billed


@router.get("/api/project-billing-summary")
async def project_billing_summary(db: Session = Depends(get_db)):
    """v3.5.0-alpha.134 (F25) — Riepilogo per progetto: Quotato vs Fatturato
    vs Pagato vs slice-linked. Visualizza in /finance le incongruenze fra
    fatturato totale (Σ Invoice.subtotal) e fatturato linkato a JCL (Σ slice).

    Ritorna lista progetti con almeno una fattura non-cancelled, ordinati
    per quoted_total desc.
    """
    from app.models import JCLBilledSlice, JobCostLine as _JCL
    from sqlalchemy import func as _func, case as _case
    tid = current_tenant_id()

    # Quote totals per project (somma quote approved/sent del progetto)
    quote_q = (
        db.query(
            Project.id, Project.code, Project.title,
            _func.coalesce(_func.sum(Quote.total_with_vat), 0.0).label("quoted_vat"),
        )
        .select_from(Quote)
        .join(Project, Project.id == Quote.project_id)
        .filter(
            Project.tenant_id == tid,
            Quote.status.in_([QuoteStatus.approved, QuoteStatus.sent, QuoteStatus.superseded]),
        )
        .group_by(Project.id, Project.code, Project.title)
        .all()
    )
    quoted_by_project = {r.id: {"code": r.code, "title": r.title, "quoted": float(r.quoted_vat or 0)} for r in quote_q}

    # Invoiced + paid per project via Job
    inv_q = (
        db.query(
            Project.id,
            _func.coalesce(_func.sum(
                _case((Invoice.doc_type == "TD04", -1), else_=1) * Invoice.subtotal
            ), 0.0).label("invoiced_net"),
            _func.coalesce(_func.sum(
                _case((Invoice.doc_type == "TD04", -1), else_=1) * Invoice.total
            ), 0.0).label("invoiced_vat"),
            _func.coalesce(_func.sum(
                _case((Invoice.doc_type == "TD04", -1), else_=1) * Invoice.amount_paid
            ), 0.0).label("paid_vat"),
        )
        .select_from(Invoice)
        .join(Job, Job.id == Invoice.job_id)
        .join(Project, Project.id == Job.project_id)
        .filter(
            Project.tenant_id == tid,
            Invoice.status != InvoiceStatus.draft,
        )
        .group_by(Project.id)
        .all()
    )

    # Slice-linked subtotal per project
    slice_q = (
        db.query(
            Project.id,
            _func.coalesce(_func.sum(JCLBilledSlice.billed_amount), 0.0).label("slice_total"),
        )
        .select_from(JCLBilledSlice)
        .join(_JCL, _JCL.id == JCLBilledSlice.job_cost_line_id)
        .join(Job, Job.id == _JCL.job_id)
        .join(Project, Project.id == Job.project_id)
        .filter(
            JCLBilledSlice.tenant_id == tid,
            JCLBilledSlice.voided_at.is_(None),
        )
        .group_by(Project.id)
        .all()
    )
    slice_by_project = {r.id: float(r.slice_total or 0) for r in slice_q}

    rows = []
    for inv_row in inv_q:
        pid = inv_row.id
        meta = quoted_by_project.get(pid, {"code": None, "title": "(progetto)", "quoted": 0.0})
        invoiced_net = float(inv_row.invoiced_net or 0)
        invoiced_vat = float(inv_row.invoiced_vat or 0)
        paid_vat = float(inv_row.paid_vat or 0)
        slice_total = slice_by_project.get(pid, 0.0)
        # "amministrativo" = imponibile fatturato non agganciato a slice JCL
        admin_net = round(invoiced_net - slice_total, 2)
        outstanding_vat = round(invoiced_vat - paid_vat, 2)
        rows.append({
            "project_id": pid,
            "project_code": meta["code"],
            "project_title": meta["title"],
            "quoted_vat": round(meta["quoted"], 2),
            "invoiced_net": round(invoiced_net, 2),
            "invoiced_vat": round(invoiced_vat, 2),
            "paid_vat": round(paid_vat, 2),
            "outstanding_vat": outstanding_vat,
            "slice_linked_net": round(slice_total, 2),
            "admin_net": admin_net,
            # delta_vat: invoice IVA inclusa vs quote IVA inclusa (positivo = over-billed)
            "delta_vat": round(invoiced_vat - meta["quoted"], 2),
        })
    rows.sort(key=lambda r: -r["quoted_vat"])
    return {"rows": rows, "count": len(rows)}


@router.get("/api/invoices/{invoice_id}")
async def get_invoice_detail(invoice_id: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.121 (F18) — dettaglio fattura per drawer UI lista.
    Ritorna invoice + lines + payments + transitions allowed (UI hide
    cambio status se terminal)."""
    inv = db.query(Invoice).options(
        joinedload(Invoice.client),
        joinedload(Invoice.lines),
        joinedload(Invoice.job).joinedload(Job.project),
    ).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Fattura non trovata")
    # transitions allowed da _ALLOWED in update_invoice_status (F18)
    _allowed_map = {
        InvoiceStatus.draft: ["sent", "cancelled"],
        InvoiceStatus.sent: ["paid", "overdue", "cancelled"],
        InvoiceStatus.overdue: ["paid", "cancelled"],
        InvoiceStatus.paid: [],
        InvoiceStatus.cancelled: [],
    }
    cur = inv.status
    allowed = _allowed_map.get(cur, [])
    is_terminal = (cur in (InvoiceStatus.paid, InvoiceStatus.cancelled))
    proj = inv.job.project if (inv.job and inv.job.project) else None
    return {
        "id": inv.id,
        "number": inv.number,
        "doc_type": getattr(inv, "doc_type", None),
        "status": cur.value if hasattr(cur, "value") else cur,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "subtotal": inv.subtotal,
        "vat_rate": inv.vat_rate,
        "total": inv.total,
        "amount_paid": inv.amount_paid or 0.0,
        "notes": inv.notes,
        "client": ({"id": inv.client.id, "name": inv.client.name} if inv.client else None),
        "project": ({"id": proj.id, "code": proj.code, "title": proj.title} if proj else None),
        "job": ({"id": inv.job.id, "code": inv.job.code} if inv.job else None),
        "lines": [
            {
                "id": l.id,
                "description": l.description,
                "quantity": l.quantity,
                "unit_price": l.unit_price,
                "total": l.total,
                "discount_pct": l.discount_pct,
                "vat_rate": l.vat_rate,
            }
            for l in inv.lines
        ],
        "allowed_transitions": allowed,
        "is_terminal": is_terminal,
    }


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


@router.get("/forecast", response_class=HTMLResponse)
async def forecast_page(request: Request, db: Session = Depends(get_db)):
    """v3.5.0-alpha.77 — Financial model esteso (pipeline + forecast).

    v3.5.0-alpha.88: pagina forecast accorpata in /finance/cashflow come
    secondo tab. La rotta resta come alias deep-link → redirect 302 al tab
    `forecast` della pagina cashflow combinata.

    v3.5.0-alpha.91 audit fix: i fragment URL (#forecast) vengono strippati
    dai browser sui redirect HTTP (Location header non li trasporta).
    Usiamo `?tab=forecast` query param che sopravvive al 302."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/finance/cashflow?tab=forecast", status_code=302)


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, db: Session = Depends(get_db)):
    """v3.5.0-alpha.78 — Reportistica con YoY + proiezione + export."""
    return _tpl().TemplateResponse("pages/finance_reports.html", {"request": request})


@router.get("/api/reports/comparison")
async def reports_yoy(
    year_a: int, year_b: int,
    granularity: str = "quarter",
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """YoY comparison year_a vs year_b. Granularity: month|quarter|year."""
    from app.services.financial_reports import year_over_year
    return year_over_year(db, year_a, year_b, granularity, project_id=project_id, client_id=client_id)


@router.get("/api/reports/projection/{year}")
async def reports_projection(
    year: int,
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """YTD projection (linear + realistic-with-forecast)."""
    from app.services.financial_reports import ytd_projection
    return ytd_projection(db, year, project_id=project_id, client_id=client_id)


@router.get("/api/reports/export.csv")
async def reports_export_csv(
    year: int,
    granularity: str = "month",
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    from app.services.financial_reports import export_csv
    data = export_csv(db, year, granularity, project_id=project_id, client_id=client_id)
    fname = f"mediaflow-report-{year}-{granularity}.csv"
    return Response(
        content=data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/reports/export.xlsx")
async def reports_export_xlsx(
    year: int,
    granularity: str = "month",
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    from app.services.financial_reports import export_xlsx
    data = export_xlsx(db, year, granularity, project_id=project_id, client_id=client_id)
    fname = f"mediaflow-report-{year}-{granularity}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/forecast/{year}")
async def quote_forecast_year(
    year: int,
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Forecast pipeline da quote (sales funnel)."""
    from app.services.quote_forecast import yearly_forecast
    return yearly_forecast(db, year, project_id=project_id, client_id=client_id)


@router.get("/api/cashflow/{year}")
async def cashflow_year(
    year: int,
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    return cashflow_year_sync(year, project_id, client_id, db)


@router.get("/api/cashflow/{year}/by-department")
async def cashflow_by_department(year: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.123 (F19) — Breakdown annuale per Department.
    Revenue side: Invoice → JCLBilledSlice → JobCostLine → PriceItem.department_id.
    Cost side (supplier): SupplierInvoice → Resource → Resource.department_id.
    Annuale (no mensile per ora) per evitare query O(N×12) sul DB.
    Ritorna sia campi total (IVA inclusa) sia _net (imponibile). UI sceglie
    via toggle Mostra IVA.
    """
    from app.models import (
        JCLBilledSlice, JobCostLine as _JCL, Department, Resource, PriceItem,
    )
    from sqlalchemy import extract, func as _func, case as _case
    tid = current_tenant_id()
    # v3.5.0-alpha.125 (P2.B precision) — revenue_net calcolato preciso per
    # slice via ratio (subtotal/total) di ogni invoice, invece di /1.22 medio.
    # Espressione: Σ (slice.billed_amount × invoice.subtotal / invoice.total)
    # Per invoice con total=0 (caso degenerato): fallback a billed_amount/1.22.
    ratio_net_expr = _case(
        (Invoice.total > 0, JCLBilledSlice.billed_amount * Invoice.subtotal / Invoice.total),
        else_=JCLBilledSlice.billed_amount / 1.22,
    )
    revenue_rows = (
        db.query(
            Department.id, Department.name,
            _func.coalesce(_func.sum(JCLBilledSlice.billed_amount), 0.0),
            _func.coalesce(_func.sum(ratio_net_expr), 0.0),
        )
        .select_from(JCLBilledSlice)
        .join(Invoice, Invoice.id == JCLBilledSlice.invoice_id)
        .join(_JCL, _JCL.id == JCLBilledSlice.job_cost_line_id)
        .outerjoin(PriceItem, PriceItem.id == _JCL.price_item_id)
        .outerjoin(Department, Department.id == PriceItem.department_id)
        .filter(
            JCLBilledSlice.tenant_id == tid,
            extract("year", Invoice.issue_date) == year,
            Invoice.status != InvoiceStatus.draft,
            JCLBilledSlice.voided_at.is_(None),
        )
        .group_by(Department.id, Department.name)
        .all()
    )
    by_dept = {}
    for did, dname, total, net in revenue_rows:
        key = did if did else 0
        by_dept[key] = {
            "department_id": did,
            "department_name": dname or "(senza reparto)",
            "revenue_total": round(float(total or 0), 2),
            "revenue_net": round(float(net or 0), 2),
            "supplier_total": 0.0,
            "supplier_net": 0.0,
        }

    # Cost side per dept: SupplierInvoice.resource → Resource.department_id
    cost_rows = (
        db.query(
            Resource.department_id,
            _func.coalesce(_func.sum(SupplierInvoice.amount_total), 0.0),
            _func.coalesce(_func.sum(SupplierInvoice.amount_net), 0.0),
        )
        .join(SupplierInvoice, SupplierInvoice.resource_id == Resource.id)
        .filter(
            SupplierInvoice.tenant_id == tid,
            extract("year", SupplierInvoice.issue_date) == year,
            SupplierInvoice.deleted_at.is_(None),
            SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled,
        )
        .group_by(Resource.department_id)
        .all()
    )
    dept_names = {d.id: d.name for d in db.query(Department).filter(Department.tenant_id == tid).all()}
    for did, total, net in cost_rows:
        key = did if did else 0
        entry = by_dept.setdefault(key, {
            "department_id": did,
            "department_name": dept_names.get(did) or "(senza reparto)",
            "revenue_total": 0.0,
            "revenue_net": 0.0,
            "supplier_total": 0.0,
            "supplier_net": 0.0,
        })
        entry["supplier_total"] = round(float(total or 0), 2)
        entry["supplier_net"] = round(float(net or 0), 2)

    # Margin = revenue - supplier (sia total che net)
    out = []
    for k, e in by_dept.items():
        e["margin_total"] = round(e["revenue_total"] - e["supplier_total"], 2)
        e["margin_net"] = round(e["revenue_net"] - e["supplier_net"], 2)
        out.append(e)
    # Ordina per revenue_net desc
    out.sort(key=lambda r: -r["revenue_net"])
    return {"year": year, "departments": out}


def cashflow_year_sync(
    year: int, project_id: Optional[int], client_id: Optional[int], db: Session,
):
    """Cashflow completo aggregato per mese dell'anno.

    Per ogni mese ritorna:
    Revenue-side:
      - invoiced: somma Invoice.total emesse (non cancelled)
      - paid: somma InvoicePayment.amount per pagamenti del mese
      - outstanding: somma Invoice residuo non pagato

    Cost-side (v3.5.0-alpha.68.1 — supplier outflow,
    v3.5.0-alpha.68.2 — pagamenti storicizzati):
      - supplier_billed: Σ SupplierInvoice.amount_total fatture passive
        ricevute nel mese (issue_date), non cancelled
      - supplier_paid: Σ SupplierInvoicePayment.amount per pagamenti
        del mese (fonte verità, pagamenti incrementali corretti)
      - supplier_due: Σ residuo (amount_total - amount_paid) per fatture
        con due_date nel mese, ancora unpaid/partial

    Derivati:
      - net_cashflow: paid (revenue) − supplier_paid (cost) = cassa netta
        effettiva del mese.
    """
    from sqlalchemy import extract

    # v3.5.0-alpha.123 (F16) — Affianco campi *_net (imponibile, no IVA) ai
    # campi totali (IVA inclusa). Default UI mostra _net; toggle "Mostra IVA"
    # switcha al totale. Senza i campi net non era possibile rappresentare
    # cashflow al netto IVA — Matteo: "i totali fatture e cashflow dovrebbero
    # essere SENZA IVA di default".
    series = [
        {
            "month": m,
            "invoiced": 0.0, "paid": 0.0, "outstanding": 0.0,
            "invoiced_net": 0.0, "paid_net": 0.0, "outstanding_net": 0.0,
            "supplier_billed": 0.0, "supplier_paid": 0.0, "supplier_due": 0.0,
            "supplier_billed_net": 0.0, "supplier_paid_net": 0.0, "supplier_due_net": 0.0,
            "net_cashflow": 0.0,
            "net_cashflow_net": 0.0,
        }
        for m in range(1, 13)
    ]
    # v3.5.0-alpha.69.1 — filtri project_id + client_id.
    # Invoice → filter by client_id direct + project_id via job
    # v3.5.0-alpha.114 — Storico contabile: include TD01 cancelled (post-storno)
    # per preservare la registrazione nel mese di emissione. La NC TD04 sotto
    # storna come negativo nel mese di emissione NC. Esclude solo le draft
    # mai emesse (status=draft).
    inv_q = db.query(Invoice).filter(
        extract("year", Invoice.issue_date) == year,
        Invoice.status != InvoiceStatus.draft,
    )
    if client_id:
        inv_q = inv_q.filter(Invoice.client_id == client_id)
    if project_id:
        inv_q = inv_q.join(Job, Invoice.job_id == Job.id).filter(Job.project_id == project_id)
    invoices = inv_q.all()
    invoice_ids = [i.id for i in invoices]
    for inv in invoices:
        m = inv.issue_date.month if inv.issue_date else 1
        # v3.5.0-alpha.114 — include anche cancelled (post-storno): la fattura
        # originale resta nel cashflow storico del suo mese di emissione, e
        # la NC TD04 storna come negativo nel mese del NC. Saldo finale netto.
        if inv.status in (InvoiceStatus.sent, InvoiceStatus.paid,
                          InvoiceStatus.overdue, InvoiceStatus.cancelled):
            sign = -1 if (getattr(inv, "doc_type", None) == "TD04") else 1
            series[m - 1]["invoiced"] += sign * (inv.total or 0.0)
            series[m - 1]["invoiced_net"] += sign * (inv.subtotal or 0.0)
        # outstanding: NC TD04 non genera outstanding (è un credito, non un debito da incassare)
        if getattr(inv, "doc_type", None) != "TD04":
            remaining = max(0.0, (inv.total or 0.0) - (inv.amount_paid or 0.0))
            if remaining > 0 and inv.status != InvoiceStatus.paid:
                series[m - 1]["outstanding"] += remaining
                # v3.5.0-alpha.123 (F16) — outstanding_net pro-quota
                total_v = inv.total or 0.0
                if total_v > 0:
                    ratio_net = (inv.subtotal or 0.0) / total_v
                    series[m - 1]["outstanding_net"] += remaining * ratio_net

    pay_q = db.query(InvoicePayment).filter(
        extract("year", InvoicePayment.payment_date) == year,
    )
    if client_id or project_id:
        # Restrict payments alle stesse invoice filtrate sopra
        if invoice_ids:
            pay_q = pay_q.filter(InvoicePayment.invoice_id.in_(invoice_ids))
        else:
            pay_q = pay_q.filter(InvoicePayment.id < 0)  # zero rows
    payments = pay_q.all()
    # v3.5.0-alpha.123 (F16) — paid_net via ratio subtotal/total dell'invoice
    inv_by_id = {inv.id: inv for inv in invoices}
    for p in payments:
        m = p.payment_date.month if p.payment_date else 1
        amt = p.amount or 0.0
        series[m - 1]["paid"] += amt
        inv_ref = inv_by_id.get(p.invoice_id)
        if inv_ref and (inv_ref.total or 0) > 0:
            ratio_net = (inv_ref.subtotal or 0.0) / inv_ref.total
            series[m - 1]["paid_net"] += amt * ratio_net
        else:
            # fallback: assume 22% IVA default
            series[m - 1]["paid_net"] += amt / 1.22

    # v3.5.0-alpha.68.1 — cost-side fatture passive.
    # SupplierInvoice → filter by project_id direct + client_id via job
    sup_billed_q = db.query(SupplierInvoice).filter(
        extract("year", SupplierInvoice.issue_date) == year,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled,
    )
    if project_id:
        sup_billed_q = sup_billed_q.filter(SupplierInvoice.project_id == project_id)
    elif client_id:
        # SupplierInvoice non ha client_id diretto: join via job → client
        sup_billed_q = sup_billed_q.join(
            Job, SupplierInvoice.job_id == Job.id
        ).join(
            Project, Job.project_id == Project.id
        ).filter(Project.client_id == client_id)
    sup_billed = sup_billed_q.all()
    sup_billed_ids = [s.id for s in sup_billed]
    sup_by_id = {s.id: s for s in sup_billed}
    for s in sup_billed:
        m = s.issue_date.month if s.issue_date else 1
        series[m - 1]["supplier_billed"] += s.amount_total or 0.0
        series[m - 1]["supplier_billed_net"] += s.amount_net or 0.0

    # Pagamenti a fornitori del mese (fonte verità: SupplierInvoicePayment).
    # v3.5.0-alpha.68.2 — pagamenti incrementali storicizzati.
    sup_pay_q = db.query(SupplierInvoicePayment).filter(
        extract("year", SupplierInvoicePayment.payment_date) == year,
    )
    if client_id or project_id:
        if sup_billed_ids:
            sup_pay_q = sup_pay_q.filter(
                SupplierInvoicePayment.supplier_invoice_id.in_(sup_billed_ids)
            )
        else:
            sup_pay_q = sup_pay_q.filter(SupplierInvoicePayment.id < 0)
    sup_payments = sup_pay_q.all()
    for p in sup_payments:
        m = p.payment_date.month if p.payment_date else 1
        amt = p.amount or 0.0
        series[m - 1]["supplier_paid"] += amt
        sup_ref = sup_by_id.get(p.supplier_invoice_id)
        if sup_ref and (sup_ref.amount_total or 0) > 0:
            ratio_net = (sup_ref.amount_net or 0.0) / sup_ref.amount_total
            series[m - 1]["supplier_paid_net"] += amt * ratio_net
        else:
            series[m - 1]["supplier_paid_net"] += amt / 1.22

    # Fatture passive con due_date nel mese, ancora non saldate
    sup_due_q = db.query(SupplierInvoice).filter(
        extract("year", SupplierInvoice.due_date) == year,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status.in_([
            SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial,
        ]),
    )
    if project_id:
        sup_due_q = sup_due_q.filter(SupplierInvoice.project_id == project_id)
    elif client_id:
        sup_due_q = sup_due_q.join(
            Job, SupplierInvoice.job_id == Job.id
        ).join(
            Project, Job.project_id == Project.id
        ).filter(Project.client_id == client_id)
    sup_due_rows = sup_due_q.all()
    for s in sup_due_rows:
        m = s.due_date.month if s.due_date else 1
        residuo = max(0.0, (s.amount_total or 0.0) - (s.amount_paid or 0.0))
        series[m - 1]["supplier_due"] += residuo
        if (s.amount_total or 0) > 0:
            ratio_net = (s.amount_net or 0.0) / s.amount_total
            series[m - 1]["supplier_due_net"] += residuo * ratio_net

    # v3.5.0-alpha.77 — Forecast pipeline (soft+committed+lost) per mese
    from app.services.quote_forecast import yearly_forecast
    fc = yearly_forecast(db, year, project_id=project_id, client_id=client_id)
    fc_by_month = {m["month"]: m for m in fc["months"]}

    # v3.5.0-alpha.87 (S8.4) — Overhead outflow per mese.
    # Solo overhead non legato a project (overhead tenant-pure). Quelli con
    # source_project_id si filtrano via project_id se richiesto.
    from app.models import OverheadCost
    oh_q = db.query(OverheadCost).filter(
        extract("year", OverheadCost.cost_date) == year,
        OverheadCost.deleted_at.is_(None),
    )
    if project_id:
        oh_q = oh_q.filter(OverheadCost.source_project_id == project_id)
    overheads = oh_q.all()
    for o in overheads:
        m = o.cost_date.month if o.cost_date else 1
        if o.is_capex:
            series[m - 1].setdefault("capex_paid", 0.0)
            series[m - 1]["capex_paid"] += o.amount_total or 0.0
        else:
            series[m - 1].setdefault("overhead_paid", 0.0)
            series[m - 1]["overhead_paid"] += o.amount_total or 0.0

    for s in series:
        s["invoiced"] = round(s["invoiced"], 2)
        s["paid"] = round(s["paid"], 2)
        s["outstanding"] = round(s["outstanding"], 2)
        s["supplier_billed"] = round(s["supplier_billed"], 2)
        s["supplier_paid"] = round(s["supplier_paid"], 2)
        s["supplier_due"] = round(s["supplier_due"], 2)
        # v3.5.0-alpha.123 (F16) — round dei campi _net
        s["invoiced_net"] = round(s["invoiced_net"], 2)
        s["paid_net"] = round(s["paid_net"], 2)
        s["outstanding_net"] = round(s["outstanding_net"], 2)
        s["supplier_billed_net"] = round(s["supplier_billed_net"], 2)
        s["supplier_paid_net"] = round(s["supplier_paid_net"], 2)
        s["supplier_due_net"] = round(s["supplier_due_net"], 2)
        # v3.5.0-alpha.87 — overhead in cashflow
        s["overhead_paid"] = round(s.get("overhead_paid", 0.0), 2)
        s["capex_paid"] = round(s.get("capex_paid", 0.0), 2)
        # net_cashflow ora include anche overhead+capex
        s["net_cashflow"] = round(
            s["paid"] - s["supplier_paid"] - s["overhead_paid"] - s["capex_paid"], 2
        )
        # v3.5.0-alpha.123 — variante net_cashflow al netto IVA (overhead/capex
        # sono già imponibile fattura passiva, ma per coerenza UI: usiamo
        # supplier_paid_net invece di supplier_paid; overhead resta total
        # poiché non distingue IVA).
        s["net_cashflow_net"] = round(
            s["paid_net"] - s["supplier_paid_net"] - s["overhead_paid"] - s["capex_paid"], 2
        )
        # v3.5.0-alpha.77 — pipeline forecast merge
        fcm = fc_by_month.get(s["month"], {})
        s["forecast_soft"] = round(fcm.get("sent", 0.0) * 0.30, 2)         # sent × default 30%
        s["forecast_committed"] = round(fcm.get("approved", 0.0) * 0.90, 2)  # approved × default 90%
        s["forecast_weighted"] = round(fcm.get("weighted_forecast", 0.0), 2)
        s["pipeline_total"] = round(fcm.get("pipeline_total", 0.0), 2)
        s["quotes_approved"] = round(fcm.get("approved", 0.0), 2)
        s["quotes_sent"] = round(fcm.get("sent", 0.0), 2)
        s["quotes_rejected"] = round(fcm.get("rejected", 0.0), 2)
        # Projected cash = paid + forecast_weighted - supplier_paid
        s["projected_cash"] = round(
            s["paid"] + s["forecast_weighted"] - s["supplier_paid"], 2
        )
    return {
        "year": year,
        "months": series,
        "forecast_totals": fc["totals"],
    }


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


@router.get("/api/anomalies/overdue-supplier")
async def list_overdue_supplier(db: Session = Depends(get_db)):
    """v3.5.0-alpha.68.4 — Fatture passive scadute non pagate.

    due_date < oggi e payment_status in (unpaid, partial). Ritorna anche
    days_overdue per priorità visiva."""
    from datetime import date as _d
    rows = (
        db.query(SupplierInvoice)
        .options(joinedload(SupplierInvoice.supplier))
        .filter(
            SupplierInvoice.deleted_at.is_(None),
            SupplierInvoice.due_date < _d.today(),
            SupplierInvoice.payment_status.in_([
                SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial,
            ]),
        )
        .order_by(SupplierInvoice.due_date.asc())
        .all()
    )
    today = _d.today()
    return [
        {
            "id": i.id,
            "number": i.number,
            "supplier_id": i.supplier_id,
            "supplier_name": i.supplier.name if i.supplier else None,
            "issue_date": str(i.issue_date) if i.issue_date else None,
            "due_date": str(i.due_date) if i.due_date else None,
            "days_overdue": (today - i.due_date).days if i.due_date else None,
            "amount_total": round(i.amount_total or 0, 2),
            "amount_paid": round(i.amount_paid or 0, 2),
            "amount_outstanding": round(
                (i.amount_total or 0) - (i.amount_paid or 0), 2
            ),
            "payment_status": i.payment_status.value if i.payment_status else "unpaid",
        }
        for i in rows
    ]


@router.get("/api/anomalies/summary")
async def anomalies_summary(db: Session = Depends(get_db)):
    """Counter aggregato per badge / topbar / dashboard."""
    from datetime import date as _d
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
    # v3.5.0-alpha.68.4 — fatture passive scadute non pagate
    overdue_supplier_count = (
        db.query(func.count(SupplierInvoice.id))
        .filter(
            SupplierInvoice.deleted_at.is_(None),
            SupplierInvoice.due_date < _d.today(),
            SupplierInvoice.payment_status.in_([
                SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial,
            ]),
        )
        .scalar() or 0
    )
    return {
        "floating_jobs": floating_count,
        "extras": extras_count,
        "superseded_quotes": superseded_count,
        "overdue_supplier_invoices": overdue_supplier_count,
    }


# ── PDF Export ────────────────────────────────────────────────────────

@router.post("/api/invoices/{invoice_id}/send-email", dependencies=[RequireEditInvoices])
async def send_invoice_email(invoice_id: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.127 (F6) — Invia la fattura via email all'admin_email
    del cliente (fallback contact_email) con PDF allegato.

    v3.5.0-alpha.130: logica estratta in `app.services.invoice_email`
    per condivisione con capability AI propose_send_invoice_email.
    """
    from app.services.invoice_email import send_invoice_via_smtp, InvoiceEmailError
    try:
        result = send_invoice_via_smtp(db, invoice_id)
    except InvoiceEmailError as e:
        raise HTTPException(e.code, e.message)
    return {"ok": True, **result}


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

    # v3.5.0-alpha.120 (F14) — Una fattura cancelled non deve essere stampabile:
    # rappresenta un documento annullato, eventualmente già stornato via NC TD04.
    # Riemissione del PDF rischia di confondere fornitori/clienti.
    if inv.status == InvoiceStatus.cancelled:
        raise HTTPException(
            409,
            f"Fattura {inv.number} è in stato 'cancelled' e non può essere stampata. "
            "Le fatture annullate non sono stampabili: stornare via Nota di Credito (TD04) e riemettere se necessario."
        )

    # v3.5.0-alpha.114 — drift detection READ-ONLY (no mutation).
    # Decisione Matteo: fatture emesse sono IMMUTABILI. Una volta sent/paid
    # solo storno via NC TD04 le tocca. Non mutiamo MAI Invoice da download
    # PDF (regressione alpha.112 corretta). Drift = log warning + il PDF
    # mostra cifra "live" (Σ lines) ma stored ORM resta intatto.
    lines_sum = round(sum((l.total or 0) for l in inv.lines), 2)
    if inv.lines and inv.subtotal and abs((inv.subtotal or 0) - lines_sum) > 0.01:
        import logging
        logging.warning(
            f"[invoice-drift] inv#{inv.id} status={inv.status} doc={inv.doc_type} "
            f"stored_subtotal={inv.subtotal} != Σ_lines={lines_sum} — NO auto-fix"
        )
    # v3.5.0-alpha.113 — intestazione completa con email amministrazione
    # (snapshot al momento dell'emissione, fallback al campo live del cliente).
    admin_email = (
        getattr(inv, "client_admin_email_snap", None)
        or (inv.client.admin_email if inv.client and getattr(inv.client, "admin_email", None) else None)
        or (inv.client.contact_email if inv.client and inv.client.contact_email else None)
    )
    client_info_parts = []
    if inv.client and inv.client.vat_number:
        client_info_parts.append(f"P.IVA {inv.client.vat_number}")
    if admin_email:
        client_info_parts.append(f"Att.ne Amministrazione · {admin_email}")
    invoice_data = {
        "number":      inv.number,
        "issue_date":  inv.issue_date.strftime("%d/%m/%Y") if inv.issue_date else "—",
        "due_date":    inv.due_date.strftime("%d/%m/%Y") if inv.due_date else None,
        "client_name": inv.client.name if inv.client else "—",
        "client_info": "<br/>".join(client_info_parts),
        "subtotal":    inv.subtotal,
        "vat_rate":    inv.vat_rate,
        "total":       inv.total,
        "notes":       inv.notes,
        "is_closing":  bool(getattr(inv, "is_closing", False)),
    }
    # v3.5.0-alpha.112 — Fattura di chiusura: aggiungi riepilogo storico
    if getattr(inv, "is_closing", False) and getattr(inv, "closing_project_id", None):
        from app.models import Project as _Project, Job as _Job
        proj = db.query(_Project).filter(_Project.id == inv.closing_project_id).first()
        if proj:
            invoice_data["project_code"] = proj.code
            invoice_data["project_title"] = proj.title
            prev_invs = db.query(Invoice).join(_Job, Invoice.job_id == _Job.id).filter(
                _Job.project_id == proj.id,
                Invoice.id != inv.id,
            ).order_by(Invoice.issue_date.asc()).all()
            invoice_data["closing_summary"] = [
                {
                    "number": pi.number,
                    "issue_date": pi.issue_date.strftime("%d/%m/%Y") if pi.issue_date else "—",
                    "subtotal": pi.subtotal or 0,
                    "total": pi.total or 0,
                    "amount_paid": pi.amount_paid or 0,
                    "doc_type": pi.doc_type or "TD01",
                    "status": pi.status.value if hasattr(pi.status, "value") else pi.status,
                }
                for pi in prev_invs
            ]
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
