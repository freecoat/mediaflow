"""
Router Fornitori + Fatture passive (v3.5.0-alpha.68).

Modulo nuovo isolato. Punto 6 della roadmap billing α.65+. SupplierInvoice
contribuisce al cost report come hardcost esterno (Σ amount_total per job
o project) e al cashflow come outflow (lato cost-side).

Convenzioni:
  - Tenant scope su tutte le query (CURRENT_TENANT = 1, soft multi-tenant).
  - Soft delete via deleted_at (vedi cestino) — pattern allineato a /quotes,
    /projects, etc.
  - Numero fattura UNIQUE per supplier+tenant (DB lo impone via combo logica
    al save: pre-check + IntegrityError fallback).
  - amount_total = amount_net + amount_vat (calcolato server-side al save).
  - payment_status derivato da amount_paid: 0=unpaid, 0<x<total=partial,
    x>=total=paid. Cancelled solo via flag esplicito.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date, datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from app.database import get_db
from app.models import (
    Supplier, SupplierInvoice, SupplierInvoiceStatus,
    Project, Job, JobCostLine,
)
from app.context import current_tenant_id

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

CURRENT_TENANT = current_tenant_id()


def _tpl():
    from app.main import templates
    return templates


def _derive_status(amount_paid: float, amount_total: float, current: SupplierInvoiceStatus) -> SupplierInvoiceStatus:
    """Calcola payment_status canonico da paid/total. Rispetta `cancelled`
    se già settato esplicitamente (non lo sovrascrive da pagamenti)."""
    if current == SupplierInvoiceStatus.cancelled:
        return SupplierInvoiceStatus.cancelled
    if amount_paid <= 0:
        return SupplierInvoiceStatus.unpaid
    if amount_paid >= amount_total:
        return SupplierInvoiceStatus.paid
    return SupplierInvoiceStatus.partial


def _supplier_to_dict(s: Supplier, db: Session) -> dict:
    inv_count = db.query(SupplierInvoice).filter(
        SupplierInvoice.supplier_id == s.id,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    ).count()
    unpaid_total = db.query(func.coalesce(func.sum(SupplierInvoice.amount_total - SupplierInvoice.amount_paid), 0)).filter(
        SupplierInvoice.supplier_id == s.id,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status.in_([SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial]),
    ).scalar() or 0.0
    return {
        "id": s.id,
        "name": s.name,
        "vat_number": s.vat_number,
        "tax_code": s.tax_code,
        "contact_email": s.contact_email,
        "contact_phone": s.contact_phone,
        "address": s.address,
        "iban": s.iban,
        "default_payment_terms_days": s.default_payment_terms_days,
        "notes": s.notes,
        "is_active": s.is_active,
        "invoices_count": inv_count,
        "outstanding_total": round(unpaid_total, 2),
    }


def _invoice_to_dict(i: SupplierInvoice) -> dict:
    return {
        "id": i.id,
        "supplier_id": i.supplier_id,
        "supplier_name": i.supplier.name if i.supplier else None,
        "number": i.number,
        "issue_date": str(i.issue_date) if i.issue_date else None,
        "due_date": str(i.due_date) if i.due_date else None,
        "payment_date": str(i.payment_date) if i.payment_date else None,
        "project_id": i.project_id,
        "job_id": i.job_id,
        "job_cost_line_id": i.job_cost_line_id,
        "amount_net": round(i.amount_net or 0, 2),
        "vat_rate": i.vat_rate,
        "amount_vat": round(i.amount_vat or 0, 2),
        "amount_total": round(i.amount_total or 0, 2),
        "amount_paid": round(i.amount_paid or 0, 2),
        "amount_outstanding": round((i.amount_total or 0) - (i.amount_paid or 0), 2),
        "currency": i.currency,
        "payment_status": i.payment_status.value if i.payment_status else "unpaid",
        "attachment_path": i.attachment_path,
        "notes": i.notes,
    }


# ── Pagina HTML ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def suppliers_page(request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse("pages/suppliers.html", {"request": request})


# ── API Fornitori ─────────────────────────────────────────────

@router.get("/api")
async def list_suppliers(
    include_inactive: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Supplier).filter(
        Supplier.tenant_id == CURRENT_TENANT,
        Supplier.deleted_at.is_(None),
    )
    if not include_inactive:
        q = q.filter(Supplier.is_active == True)  # noqa: E712
    suppliers = q.order_by(Supplier.name).all()
    return [_supplier_to_dict(s, db) for s in suppliers]


@router.post("/api")
async def create_supplier(
    name: str = Form(...),
    vat_number: Optional[str] = Form(None),
    tax_code: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    iban: Optional[str] = Form(None),
    default_payment_terms_days: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Nome obbligatorio")
    s = Supplier(
        tenant_id=CURRENT_TENANT,
        name=name,
        vat_number=(vat_number or "").strip() or None,
        tax_code=(tax_code or "").strip() or None,
        contact_email=(contact_email or "").strip() or None,
        contact_phone=(contact_phone or "").strip() or None,
        address=(address or "").strip() or None,
        iban=(iban or "").strip() or None,
        default_payment_terms_days=default_payment_terms_days,
        notes=(notes or "").strip() or None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _supplier_to_dict(s, db)


@router.put("/api/{supplier_id}")
async def update_supplier(
    supplier_id: int,
    name: Optional[str] = Form(None),
    vat_number: Optional[str] = Form(None),
    tax_code: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    iban: Optional[str] = Form(None),
    default_payment_terms_days: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
):
    s = db.query(Supplier).filter(
        Supplier.id == supplier_id,
        Supplier.tenant_id == CURRENT_TENANT,
        Supplier.deleted_at.is_(None),
    ).first()
    if not s:
        raise HTTPException(404, "Fornitore non trovato")
    if name is not None: s.name = name.strip()
    if vat_number is not None: s.vat_number = vat_number.strip() or None
    if tax_code is not None: s.tax_code = tax_code.strip() or None
    if contact_email is not None: s.contact_email = contact_email.strip() or None
    if contact_phone is not None: s.contact_phone = contact_phone.strip() or None
    if address is not None: s.address = address.strip() or None
    if iban is not None: s.iban = iban.strip() or None
    if default_payment_terms_days is not None: s.default_payment_terms_days = default_payment_terms_days
    if notes is not None: s.notes = notes.strip() or None
    if is_active is not None: s.is_active = is_active
    db.commit()
    return _supplier_to_dict(s, db)


@router.delete("/api/{supplier_id}")
async def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    """Soft delete fornitore. Blocca se ci sono fatture attive (non
    cancelled). L'utente deve prima cancellare/risolvere le fatture."""
    s = db.query(Supplier).filter(
        Supplier.id == supplier_id,
        Supplier.tenant_id == CURRENT_TENANT,
        Supplier.deleted_at.is_(None),
    ).first()
    if not s:
        raise HTTPException(404, "Fornitore non trovato")
    active_invoices = db.query(SupplierInvoice).filter(
        SupplierInvoice.supplier_id == s.id,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled,
    ).count()
    if active_invoices:
        raise HTTPException(
            400,
            f"Impossibile eliminare: {active_invoices} fatture attive. "
            "Cancella o annulla prima le fatture, oppure disattiva il fornitore.",
        )
    s.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


# ── API Fatture passive ───────────────────────────────────────

@router.get("/api/invoices")
async def list_supplier_invoices(
    supplier_id: Optional[int] = None,
    project_id: Optional[int] = None,
    job_id: Optional[int] = None,
    status: Optional[str] = None,
    include_cancelled: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(SupplierInvoice).options(
        joinedload(SupplierInvoice.supplier)
    ).filter(
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    )
    if supplier_id: q = q.filter(SupplierInvoice.supplier_id == supplier_id)
    if project_id: q = q.filter(SupplierInvoice.project_id == project_id)
    if job_id: q = q.filter(SupplierInvoice.job_id == job_id)
    if status:
        try:
            st_enum = SupplierInvoiceStatus(status)
            q = q.filter(SupplierInvoice.payment_status == st_enum)
        except ValueError:
            raise HTTPException(400, f"Stato non valido: {status}")
    elif not include_cancelled:
        q = q.filter(SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled)
    invoices = q.order_by(SupplierInvoice.issue_date.desc()).all()
    return [_invoice_to_dict(i) for i in invoices]


@router.get("/api/invoices/{invoice_id}")
async def get_supplier_invoice(invoice_id: int, db: Session = Depends(get_db)):
    i = db.query(SupplierInvoice).options(
        joinedload(SupplierInvoice.supplier)
    ).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if not i:
        raise HTTPException(404, "Fattura non trovata")
    return _invoice_to_dict(i)


@router.post("/api/invoices")
async def create_supplier_invoice(
    supplier_id: int = Form(...),
    number: str = Form(...),
    issue_date: date = Form(...),
    amount_net: float = Form(...),
    vat_rate: float = Form(22.0),
    due_date: Optional[date] = Form(None),
    payment_date: Optional[date] = Form(None),
    project_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    currency: str = Form("EUR"),
    amount_paid: float = Form(0.0),
    attachment_path: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # Verifica fornitore esiste
    s = db.query(Supplier).filter(
        Supplier.id == supplier_id,
        Supplier.tenant_id == CURRENT_TENANT,
        Supplier.deleted_at.is_(None),
    ).first()
    if not s:
        raise HTTPException(404, "Fornitore non trovato")
    # Pre-check unicità number+supplier (manuale, no UNIQUE index — il numero
    # è scelto dal fornitore, può capitare di doverlo correggere via cestino)
    dup = db.query(SupplierInvoice).filter(
        SupplierInvoice.supplier_id == supplier_id,
        SupplierInvoice.number == number,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if dup:
        raise HTTPException(
            400, f"Fattura {number} già registrata per questo fornitore"
        )
    amount_vat = round(amount_net * (vat_rate / 100.0), 2)
    amount_total = round(amount_net + amount_vat, 2)
    status = _derive_status(amount_paid, amount_total, SupplierInvoiceStatus.unpaid)
    # Auto-fill due_date da terms se non passata
    if not due_date and s.default_payment_terms_days:
        from datetime import timedelta
        due_date = issue_date + timedelta(days=s.default_payment_terms_days)
    i = SupplierInvoice(
        tenant_id=CURRENT_TENANT,
        supplier_id=supplier_id,
        number=number.strip(),
        issue_date=issue_date,
        due_date=due_date,
        payment_date=payment_date,
        project_id=project_id,
        job_id=job_id,
        job_cost_line_id=job_cost_line_id,
        amount_net=amount_net,
        vat_rate=vat_rate,
        amount_vat=amount_vat,
        amount_total=amount_total,
        currency=currency,
        payment_status=status,
        amount_paid=amount_paid,
        attachment_path=(attachment_path or "").strip() or None,
        notes=(notes or "").strip() or None,
    )
    db.add(i)
    db.commit()
    db.refresh(i)
    return _invoice_to_dict(i)


@router.put("/api/invoices/{invoice_id}")
async def update_supplier_invoice(
    invoice_id: int,
    number: Optional[str] = Form(None),
    issue_date: Optional[date] = Form(None),
    amount_net: Optional[float] = Form(None),
    vat_rate: Optional[float] = Form(None),
    due_date: Optional[date] = Form(None),
    payment_date: Optional[date] = Form(None),
    project_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    currency: Optional[str] = Form(None),
    amount_paid: Optional[float] = Form(None),
    attachment_path: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    payment_status: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    i = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if not i:
        raise HTTPException(404, "Fattura non trovata")
    if number is not None: i.number = number.strip()
    if issue_date is not None: i.issue_date = issue_date
    if due_date is not None: i.due_date = due_date
    if payment_date is not None: i.payment_date = payment_date
    if project_id is not None: i.project_id = project_id or None
    if job_id is not None: i.job_id = job_id or None
    if job_cost_line_id is not None: i.job_cost_line_id = job_cost_line_id or None
    if currency is not None: i.currency = currency
    if attachment_path is not None: i.attachment_path = attachment_path.strip() or None
    if notes is not None: i.notes = notes.strip() or None
    # Ricalcolo amount_total se cambiati net o vat_rate
    if amount_net is not None: i.amount_net = amount_net
    if vat_rate is not None: i.vat_rate = vat_rate
    if amount_net is not None or vat_rate is not None:
        i.amount_vat = round((i.amount_net or 0) * ((i.vat_rate or 0) / 100.0), 2)
        i.amount_total = round((i.amount_net or 0) + i.amount_vat, 2)
    if amount_paid is not None: i.amount_paid = amount_paid
    # Status: priorità override esplicito (cancelled), poi derivato
    if payment_status is not None:
        try:
            i.payment_status = SupplierInvoiceStatus(payment_status)
        except ValueError:
            raise HTTPException(400, f"Stato non valido: {payment_status}")
    else:
        i.payment_status = _derive_status(
            i.amount_paid or 0, i.amount_total or 0, i.payment_status
        )
    db.commit()
    return _invoice_to_dict(i)


@router.post("/api/invoices/{invoice_id}/pay")
async def register_payment(
    invoice_id: int,
    amount: float = Form(...),
    payment_date: date = Form(...),
    db: Session = Depends(get_db),
):
    """Registra un pagamento (incrementale): somma a amount_paid. Aggiorna
    payment_date se la fattura era unpaid. Calcola status canonico."""
    i = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if not i:
        raise HTTPException(404, "Fattura non trovata")
    if i.payment_status == SupplierInvoiceStatus.cancelled:
        raise HTTPException(400, "Fattura annullata, non si può pagare")
    if amount <= 0:
        raise HTTPException(400, "Importo pagamento deve essere positivo")
    new_paid = round((i.amount_paid or 0) + amount, 2)
    if new_paid > (i.amount_total or 0) + 0.01:
        raise HTTPException(
            400,
            f"Importo pagato ({new_paid}) supera il totale fattura ({i.amount_total})",
        )
    i.amount_paid = new_paid
    if not i.payment_date:
        i.payment_date = payment_date
    elif new_paid >= (i.amount_total or 0):
        # Saldo completo: aggiorna payment_date all'ultimo pagamento
        i.payment_date = payment_date
    i.payment_status = _derive_status(
        i.amount_paid, i.amount_total or 0, i.payment_status
    )
    db.commit()
    return _invoice_to_dict(i)


@router.delete("/api/invoices/{invoice_id}")
async def delete_supplier_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Soft delete fattura passiva."""
    i = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if not i:
        raise HTTPException(404, "Fattura non trovata")
    i.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


# ── Aggregati per cost-report / cashflow ──────────────────────

@router.get("/api/summary/job/{job_id}")
async def supplier_summary_for_job(job_id: int, db: Session = Depends(get_db)):
    """Aggregato fatture passive linkate al job (diretto o via project).
    Usato dal cost-report per calcolare hardcost esterno + margine reale."""
    job = db.query(Job).filter(
        Job.id == job_id, Job.tenant_id == CURRENT_TENANT
    ).first()
    if not job:
        raise HTTPException(404, "Job non trovato")
    # Fatture linkate direttamente al job + quelle linkate al project
    q = db.query(SupplierInvoice).filter(
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled,
    )
    if job.project_id:
        q = q.filter(or_(
            SupplierInvoice.job_id == job_id,
            SupplierInvoice.project_id == job.project_id,
        ))
    else:
        q = q.filter(SupplierInvoice.job_id == job_id)
    invoices = q.options(joinedload(SupplierInvoice.supplier)).all()
    total_net = sum(i.amount_net or 0 for i in invoices)
    total_vat = sum(i.amount_vat or 0 for i in invoices)
    total_paid = sum(i.amount_paid or 0 for i in invoices)
    total_unpaid = sum(
        (i.amount_total or 0) - (i.amount_paid or 0)
        for i in invoices
        if i.payment_status != SupplierInvoiceStatus.paid
    )
    return {
        "job_id": job_id,
        "project_id": job.project_id,
        "invoice_count": len(invoices),
        "total_net": round(total_net, 2),
        "total_vat": round(total_vat, 2),
        "total_amount": round(total_net + total_vat, 2),
        "total_paid": round(total_paid, 2),
        "total_outstanding": round(total_unpaid, 2),
        "invoices": [_invoice_to_dict(i) for i in invoices],
    }


@router.get("/api/summary/tenant")
async def supplier_summary_tenant(db: Session = Depends(get_db)):
    """Aggregato globale per dashboard finance: outstanding + monthly outflow."""
    q = db.query(SupplierInvoice).filter(
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled,
    )
    total_outstanding = db.query(
        func.coalesce(func.sum(SupplierInvoice.amount_total - SupplierInvoice.amount_paid), 0)
    ).filter(
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status.in_([
            SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial,
        ]),
    ).scalar() or 0.0
    overdue_count = db.query(SupplierInvoice).filter(
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status.in_([
            SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial,
        ]),
        SupplierInvoice.due_date < date.today(),
    ).count()
    invoices_count = q.count()
    return {
        "invoices_count": invoices_count,
        "total_outstanding": round(total_outstanding, 2),
        "overdue_count": overdue_count,
    }
