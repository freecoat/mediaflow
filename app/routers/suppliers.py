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
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from app.database import get_db
from app.models import (
    Supplier, SupplierInvoice, SupplierInvoiceStatus, SupplierInvoicePayment,
    Project, Job, JobCostLine,
)
from app.context import current_tenant_id

router = APIRouter(prefix="/suppliers", tags=["suppliers"])



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
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
    ).count()
    unpaid_total = db.query(func.coalesce(func.sum(SupplierInvoice.amount_total - SupplierInvoice.amount_paid), 0)).filter(
        SupplierInvoice.supplier_id == s.id,
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status.in_([SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial]),
    ).scalar() or 0.0
    # v3.5.0-alpha.113 — risorsa linkata (1:1 via Resource.supplier_id)
    from app.models import Resource as _Resource
    linked_res = db.query(_Resource).filter(
        _Resource.supplier_id == s.id,
        _Resource.tenant_id == current_tenant_id(),
        _Resource.is_active == True,  # noqa: E712
    ).first()
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
        "resource_id": linked_res.id if linked_res else None,
        "resource_name": linked_res.name if linked_res else None,
    }


def _invoice_to_dict(i: SupplierInvoice) -> dict:
    # v3.5.0-alpha.113 — project + job snapshot per visualizzazione lista
    proj = getattr(i, "project", None)
    job = getattr(i, "job", None)
    return {
        "id": i.id,
        "supplier_id": i.supplier_id,
        "supplier_name": i.supplier.name if i.supplier else None,
        "number": i.number,
        "issue_date": str(i.issue_date) if i.issue_date else None,
        "due_date": str(i.due_date) if i.due_date else None,
        "payment_date": str(i.payment_date) if i.payment_date else None,
        "project_id": i.project_id,
        "project": ({"id": proj.id, "code": proj.code, "title": proj.title} if proj else None),
        "job_id": i.job_id,
        "job": ({"id": job.id, "code": job.code, "title": job.title} if job else None),
        "job_cost_line_id": i.job_cost_line_id,
        # v3.5.0-alpha.113 — resource_id (link risorsa esterna)
        "resource_id": getattr(i, "resource_id", None),
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
        Supplier.tenant_id == current_tenant_id(),
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
        tenant_id=current_tenant_id(),
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
        Supplier.tenant_id == current_tenant_id(),
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
        Supplier.tenant_id == current_tenant_id(),
        Supplier.deleted_at.is_(None),
    ).first()
    if not s:
        raise HTTPException(404, "Fornitore non trovato")
    active_invoices = db.query(SupplierInvoice).filter(
        SupplierInvoice.supplier_id == s.id,
        SupplierInvoice.tenant_id == current_tenant_id(),
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
    client_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    status: Optional[str] = None,
    include_cancelled: int = 0,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.86 — Filtri estesi (S3.2): client_id + period.
    client_id richiede join via Project."""
    # v3.5.0-alpha.113 — eager load project + job per UI lista
    from app.models import Project as _Project, Job as _Job
    q = db.query(SupplierInvoice).options(
        joinedload(SupplierInvoice.supplier),
        joinedload(SupplierInvoice.project),
        joinedload(SupplierInvoice.job),
    ).filter(
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
    )
    if supplier_id: q = q.filter(SupplierInvoice.supplier_id == supplier_id)
    if project_id: q = q.filter(SupplierInvoice.project_id == project_id)
    if job_id: q = q.filter(SupplierInvoice.job_id == job_id)
    if client_id:
        from app.models import Project as _Project
        q = q.join(_Project, SupplierInvoice.project_id == _Project.id).filter(_Project.client_id == client_id)
    if from_date:
        q = q.filter(SupplierInvoice.issue_date >= from_date)
    if to_date:
        q = q.filter(SupplierInvoice.issue_date <= to_date)
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
        SupplierInvoice.tenant_id == current_tenant_id(),
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
    resource_id: Optional[int] = Form(None),  # v3.5.0-alpha.113 — match fattura↔risorsa
    currency: str = Form("EUR"),
    amount_paid: float = Form(0.0),
    attachment_path: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # Verifica fornitore esiste
    s = db.query(Supplier).filter(
        Supplier.id == supplier_id,
        Supplier.tenant_id == current_tenant_id(),
        Supplier.deleted_at.is_(None),
    ).first()
    if not s:
        raise HTTPException(404, "Fornitore non trovato")
    # Pre-check unicità number+supplier (manuale, no UNIQUE index — il numero
    # è scelto dal fornitore, può capitare di doverlo correggere via cestino)
    dup = db.query(SupplierInvoice).filter(
        SupplierInvoice.supplier_id == supplier_id,
        SupplierInvoice.number == number,
        SupplierInvoice.tenant_id == current_tenant_id(),
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
        tenant_id=current_tenant_id(),
        supplier_id=supplier_id,
        number=number.strip(),
        issue_date=issue_date,
        due_date=due_date,
        payment_date=payment_date,
        project_id=project_id,
        job_id=job_id,
        job_cost_line_id=job_cost_line_id,
        resource_id=resource_id,
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
    resource_id: Optional[int] = Form(None),  # v3.5.0-alpha.113
    currency: Optional[str] = Form(None),
    amount_paid: Optional[float] = Form(None),
    attachment_path: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    payment_status: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    i = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == current_tenant_id(),
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
    if resource_id is not None: i.resource_id = resource_id or None  # v3.5.0-alpha.113
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


def _refresh_supplier_invoice_payment_state(db: Session, inv: SupplierInvoice) -> None:
    """Ricomputa amount_paid + payment_status canonico + payment_date
    da Σ payments. Idempotente. Chiamato dopo INSERT/DELETE payment."""
    total = round(sum((p.amount or 0.0) for p in inv.payments), 2)
    inv.amount_paid = total
    inv.payment_status = _derive_status(total, inv.amount_total or 0, inv.payment_status)
    # payment_date = data ultimo pagamento (se ce ne sono)
    if inv.payments:
        latest = max(p.payment_date for p in inv.payments if p.payment_date)
        inv.payment_date = latest
    else:
        inv.payment_date = None


@router.get("/api/invoices/{invoice_id}/payments")
async def list_invoice_payments(invoice_id: int, db: Session = Depends(get_db)):
    """Lista pagamenti per fattura passiva. v3.5.0-alpha.68.2."""
    inv = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if not inv:
        raise HTTPException(404, "Fattura non trovata")
    rows = sorted(inv.payments, key=lambda p: p.payment_date or date.min, reverse=True)
    return {
        "invoice_id": invoice_id,
        "invoice_total": round(inv.amount_total or 0.0, 2),
        "amount_paid": round(inv.amount_paid or 0.0, 2),
        "amount_remaining": round(max(0.0, (inv.amount_total or 0.0) - (inv.amount_paid or 0.0)), 2),
        "payments": [
            {
                "id": p.id,
                "amount": round(p.amount or 0, 2),
                "payment_date": str(p.payment_date) if p.payment_date else None,
                "method": p.method,
                "reference": p.reference,
                "notes": p.notes,
                "created_at": str(p.created_at)[:19] if p.created_at else None,
            }
            for p in rows
        ],
    }


@router.post("/api/invoices/{invoice_id}/pay")
async def register_payment(
    invoice_id: int,
    request: Request,
    amount: float = Form(...),
    payment_date: date = Form(...),
    method: Optional[str] = Form(None),
    reference: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Registra un pagamento (anche parziale). v3.5.0-alpha.68.2:
    crea una riga `SupplierInvoicePayment` (fonte verità), aggiorna
    `amount_paid` e `payment_status` canonici. amount_paid denormalizzato
    per query veloci."""
    inv = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if not inv:
        raise HTTPException(404, "Fattura non trovata")
    if inv.payment_status == SupplierInvoiceStatus.cancelled:
        raise HTTPException(409, "Fattura annullata: pagamenti non ammessi")
    if amount <= 0:
        raise HTTPException(400, "Importo pagamento deve essere positivo")
    new_total = round((inv.amount_paid or 0) + amount, 2)
    if new_total > (inv.amount_total or 0) + 0.01:
        raise HTTPException(
            400,
            f"Importo cumulato ({new_total}) supera totale fattura ({inv.amount_total})",
        )
    user = getattr(request.state, "current_user", None)
    payment = SupplierInvoicePayment(
        tenant_id=current_tenant_id(),
        supplier_invoice_id=invoice_id,
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
    _refresh_supplier_invoice_payment_state(db, inv)
    db.commit()
    return {
        "id": payment.id,
        "invoice_id": invoice_id,
        "amount_paid": inv.amount_paid,
        "payment_status": inv.payment_status.value,
    }


@router.delete("/api/sup-payments/{payment_id}")
async def delete_supplier_payment(payment_id: int, db: Session = Depends(get_db)):
    """Elimina un pagamento singolo (rollback). Ricomputa stato fattura."""
    p = db.query(SupplierInvoicePayment).filter(
        SupplierInvoicePayment.id == payment_id,
        SupplierInvoicePayment.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, "Pagamento non trovato")
    inv = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == p.supplier_invoice_id
    ).first()
    db.delete(p)
    db.flush()
    if inv:
        db.refresh(inv)
        _refresh_supplier_invoice_payment_state(db, inv)
    db.commit()
    return {"ok": True}


@router.delete("/api/invoices/{invoice_id}")
async def delete_supplier_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Soft delete fattura passiva."""
    i = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if not i:
        raise HTTPException(404, "Fattura non trovata")
    i.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


# ── AI parse fattura da upload (v3.5.0-alpha.71) ──────────────


@router.post("/api/invoices/parse-upload")
async def parse_invoice_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Estrae campi fattura passiva da PDF/docx/xlsx/txt + matcha fornitore
    esistente per vat_number o name. NON salva nulla — ritorna preview JSON
    per modal conferma utente."""
    from app.services.deliverables_parser import extract_text_from_file
    from app.services.supplier_invoice_parser import parse_supplier_invoice
    if not file.filename:
        raise HTTPException(400, "Nome file mancante")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "File vuoto")
    if len(file_bytes) > 15 * 1024 * 1024:
        raise HTTPException(413, "File troppo grande (max 15 MB)")
    text = extract_text_from_file(file_bytes, file.filename)
    if not text or len(text.strip()) < 30:
        raise HTTPException(
            400,
            "Estrazione testo fallita o testo troppo breve. "
            "Per fatture scansionate (immagini) serve OCR (scope futuro). "
            "Inserisci manualmente."
        )
    user = getattr(request.state, "current_user", None)
    user_id = user.id if user else None
    parsed = parse_supplier_invoice(text, user_id=user_id, db=db)
    if not parsed:
        raise HTTPException(
            503,
            "AI provider non disponibile o estrazione fallita. "
            "Configura provider in /settings → AI e riprova, oppure inserisci manualmente."
        )
    # Match supplier esistente per vat_number o name
    sup_match = None
    vat = (parsed.get("supplier_vat_number") or "").strip()
    sup_name = (parsed.get("supplier_name") or "").strip()
    if vat:
        sup_match = db.query(Supplier).filter(
            Supplier.tenant_id == current_tenant_id(),
            Supplier.deleted_at.is_(None),
            Supplier.vat_number == vat,
        ).first()
    if not sup_match and sup_name:
        sup_match = db.query(Supplier).filter(
            Supplier.tenant_id == current_tenant_id(),
            Supplier.deleted_at.is_(None),
            func.lower(Supplier.name) == sup_name.lower(),
        ).first()
    # Sanitize date
    def _sanitize_date(v):
        if not v: return None
        if isinstance(v, str):
            try:
                return date.fromisoformat(v[:10]).isoformat()
            except ValueError:
                return None
        return v
    parsed["issue_date"] = _sanitize_date(parsed.get("issue_date"))
    parsed["due_date"] = _sanitize_date(parsed.get("due_date"))
    return {
        "extracted": parsed,
        "supplier_match": (
            _supplier_to_dict(sup_match, db) if sup_match else None
        ),
        "source_filename": file.filename,
        "text_preview": text[:1500],
    }


@router.post("/api/invoices/create-from-parsed")
async def create_invoice_from_parsed(
    request: Request,
    # Supplier resolution: either id (existing) or full data (create new)
    supplier_id: Optional[int] = Form(None),
    supplier_name: Optional[str] = Form(None),
    supplier_vat_number: Optional[str] = Form(None),
    supplier_tax_code: Optional[str] = Form(None),
    supplier_address: Optional[str] = Form(None),
    supplier_iban: Optional[str] = Form(None),
    supplier_email: Optional[str] = Form(None),
    # Invoice fields
    number: str = Form(...),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    amount_net: float = Form(...),
    vat_rate: float = Form(22.0),
    currency: str = Form("EUR"),
    notes: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    attachment_path: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea o trova supplier + crea SupplierInvoice da dati confermati
    dal modal di preview (post parse-upload). Idempotente sul numero
    fattura: 409 se già presente per quel fornitore."""
    # Resolve / create supplier
    sup = None
    if supplier_id:
        sup = db.query(Supplier).filter(
            Supplier.id == supplier_id,
            Supplier.tenant_id == current_tenant_id(),
            Supplier.deleted_at.is_(None),
        ).first()
        if not sup:
            raise HTTPException(404, "Fornitore non trovato")
    else:
        if not (supplier_name or "").strip():
            raise HTTPException(400, "supplier_name richiesto se supplier_id assente")
        sup = Supplier(
            tenant_id=current_tenant_id(),
            name=supplier_name.strip(),
            vat_number=(supplier_vat_number or "").strip() or None,
            tax_code=(supplier_tax_code or "").strip() or None,
            contact_email=(supplier_email or "").strip() or None,
            address=(supplier_address or "").strip() or None,
            iban=(supplier_iban or "").strip() or None,
        )
        db.add(sup)
        db.flush()
    # Pre-check unicità (supplier_id, number)
    dup = db.query(SupplierInvoice).filter(
        SupplierInvoice.supplier_id == sup.id,
        SupplierInvoice.number == number,
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if dup:
        raise HTTPException(
            409, f"Fattura {number} già registrata per {sup.name} (id={dup.id})"
        )
    # Auto due_date da terms se omessa
    if not due_date and sup.default_payment_terms_days:
        due_date = issue_date + timedelta(days=sup.default_payment_terms_days)
    amount_vat = round(amount_net * (vat_rate / 100.0), 2)
    amount_total = round(amount_net + amount_vat, 2)
    inv = SupplierInvoice(
        tenant_id=current_tenant_id(),
        supplier_id=sup.id,
        number=number.strip(),
        issue_date=issue_date,
        due_date=due_date,
        project_id=project_id,
        job_id=job_id,
        amount_net=amount_net,
        vat_rate=vat_rate,
        amount_vat=amount_vat,
        amount_total=amount_total,
        currency=(currency or "EUR").upper(),
        payment_status=SupplierInvoiceStatus.unpaid,
        amount_paid=0.0,
        attachment_path=(attachment_path or "").strip() or None,
        notes=(notes or "").strip() or None,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    db.refresh(sup)
    return {
        "ok": True,
        "supplier_id": sup.id,
        "supplier_name": sup.name,
        "supplier_created": supplier_id is None,
        "invoice_id": inv.id,
        "invoice_number": inv.number,
        "amount_total": inv.amount_total,
    }


# ── Aggregati per cost-report / cashflow ──────────────────────

@router.get("/api/summary/job/{job_id}")
async def supplier_summary_for_job(job_id: int, db: Session = Depends(get_db)):
    """Aggregato fatture passive linkate al job (diretto o via project).
    Usato dal cost-report per calcolare hardcost esterno + margine reale."""
    job = db.query(Job).filter(
        Job.id == job_id, Job.tenant_id == current_tenant_id()
    ).first()
    if not job:
        raise HTTPException(404, "Job non trovato")
    # Fatture linkate direttamente al job + quelle linkate al project
    q = db.query(SupplierInvoice).filter(
        SupplierInvoice.tenant_id == current_tenant_id(),
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
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled,
    )
    total_outstanding = db.query(
        func.coalesce(func.sum(SupplierInvoice.amount_total - SupplierInvoice.amount_paid), 0)
    ).filter(
        SupplierInvoice.tenant_id == current_tenant_id(),
        SupplierInvoice.deleted_at.is_(None),
        SupplierInvoice.payment_status.in_([
            SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial,
        ]),
    ).scalar() or 0.0
    overdue_count = db.query(SupplierInvoice).filter(
        SupplierInvoice.tenant_id == current_tenant_id(),
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
