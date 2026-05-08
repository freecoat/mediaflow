"""
Router Billing flow (v3.5.0-alpha.47, Step 2 del Cost Report → Fatturazione).

Espone gli endpoint API che orchestrano il workflow concordato con Matteo:

  Cost Report → [transmit] → BillingBatch (draft)
            ↓
  Manager rivede, modifica importi → LossEntry per ogni delta < proposed
            ↓
  [approve] → BillingBatch (approved)
            ↓
  [invoice] → Invoice creata + linkata, BillingBatch (invoiced),
              JobCostLine.billing_status = billed
            ↓
  [mark-paid] → JobCostLine.billing_status = paid

Step 2 = solo API. UI cost report con bottone "Trasmetti" e UI /finance
con elenco batch / approval / perso arrivano in α.48-49.

RBAC:
- transmit: chiunque ha view_finance (producer/manager/admin)
- edit-line / approve / invoice / cancel: manager+ (decisione finanziaria)
- mark-paid: manager+
- list / get: chiunque ha view_finance

Tutti gli endpoint sotto prefix /finance/api/billing.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    BillingBatch, BillingBatchLine, BillingBatchStatus,
    JobCostLine, JCLBillingStatus,
    LossEntry, LossReason,
    Project, Job, JobStatus, Invoice, InvoiceLine, InvoiceStatus, Client,
)
from app.services.rbac import (
    current_user_optional, is_admin, is_manager, can_view_finance,
)


router = APIRouter(prefix="/finance/api/billing", tags=["billing"])

CURRENT_TENANT = 1  # Multi-tenant soft (vedi CLAUDE.md)


# ── RBAC helpers ───────────────────────────────────────────────────────

def _require_finance(request: Request):
    user = current_user_optional(request)
    if not can_view_finance(user):
        raise HTTPException(403, "Permesso richiesto: view_finance")
    return user


def _require_manager(request: Request):
    user = current_user_optional(request)
    if not (is_admin(user) or is_manager(user)):
        raise HTTPException(403, "Solo manager o admin possono eseguire questa azione")
    return user


# ── Helpers ────────────────────────────────────────────────────────────

def _next_batch_code(db: Session) -> str:
    """Genera prossimo BB-{anno}-{NNN} unico per tenant. Considera anche
    batch cancelled (no riciclo numero)."""
    year = date.today().year
    prefix = f"BB-{year}-"
    last = (
        db.query(BillingBatch)
        .filter(BillingBatch.tenant_id == CURRENT_TENANT, BillingBatch.code.like(f"{prefix}%"))
        .order_by(BillingBatch.id.desc())
        .first()
    )
    next_n = 1
    if last:
        try:
            last_n = int(last.code.rsplit("-", 1)[-1])
            next_n = last_n + 1
        except (ValueError, IndexError):
            pass
    return f"{prefix}{next_n:03d}"


def _batch_to_dict(b: BillingBatch, with_lines: bool = False) -> dict:
    out = {
        "id": b.id,
        "code": b.code,
        "project_id": b.project_id,
        "project_title": b.project.title if b.project else None,
        "project_code": b.project.code if b.project else None,
        "status": b.status.value,
        "period_start": b.period_start.isoformat() if b.period_start else None,
        "period_end": b.period_end.isoformat() if b.period_end else None,
        "total_proposed": b.total_proposed,
        "total_approved": b.total_approved,
        "total_lost": b.total_lost,
        "notes": b.notes,
        "transmitted_by_user_id": b.transmitted_by_user_id,
        "transmitted_at": b.transmitted_at.isoformat() if b.transmitted_at else None,
        "approved_by_user_id": b.approved_by_user_id,
        "approved_at": b.approved_at.isoformat() if b.approved_at else None,
        "invoice_id": b.invoice_id,
        "invoice_number": b.invoice.number if b.invoice else None,
    }
    if with_lines:
        out["lines"] = [
            {
                "id": l.id,
                "job_cost_line_id": l.job_cost_line_id,
                "description": l.description,
                "quantity": l.quantity,
                "unit": l.unit,
                "unit_price": l.unit_price,
                "total_proposed": l.total_proposed,
                "total_approved": l.total_approved,
                "is_extra": l.is_extra,
                "notes": l.notes,
            }
            for l in b.lines
        ]
    return out


def _recompute_batch_totals(b: BillingBatch):
    """Ricalcola total_proposed/approved/lost dalle lines correnti."""
    b.total_proposed = sum(l.total_proposed for l in b.lines)
    b.total_approved = sum(l.total_approved for l in b.lines)
    b.total_lost = max(0.0, b.total_proposed - b.total_approved)


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/preview")
async def preview_transmission(
    request: Request,
    project_id: int,
    include_extras: bool = True,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.48.2: anteprima per il modal Trasmetti.

    Matteo: "il periodo di riferimento della fatturazione dovrebbe essere
    determinato di volta in volta in base al periodo di attività del booking".

    Calcola periodo suggerito da min/max work_date delle JCL candidate del
    progetto (work_date è impostato da cost_line_sync sui booking done).
    Fallback al mese corrente se tutte le JCL candidate hanno work_date NULL
    (caso JCL extra senza booking).

    Ritorna anche count e total per anteprima nel modal.
    """
    _require_finance(request)
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == CURRENT_TENANT,
    ).first()
    if not proj:
        raise HTTPException(404, f"Progetto #{project_id} non trovato")

    q = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status == JCLBillingStatus.not_billed,
        JobCostLine.total_accrued > 0,
        JobCostLine.is_billable == True,
    )
    if not include_extras:
        q = q.filter(JobCostLine.is_extra == False)
    candidates = q.all()

    work_dates = [c.work_date for c in candidates if c.work_date is not None]
    if work_dates:
        period_start = min(work_dates)
        period_end = max(work_dates)
        period_source = "from_bookings"
    else:
        # Fallback: mese corrente (per JCL extra senza booking, ecc.)
        today = date.today()
        period_start = today.replace(day=1)
        # Ultimo giorno del mese corrente
        if today.month == 12:
            next_month = date(today.year + 1, 1, 1)
        else:
            next_month = date(today.year, today.month + 1, 1)
        period_end = date.fromordinal(next_month.toordinal() - 1)
        period_source = "current_month_fallback"

    total_proposed = round(sum(c.total_accrued for c in candidates), 2)
    return {
        "project_id": project_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_source": period_source,
        "include_extras": include_extras,
        "candidate_count": len(candidates),
        "total_proposed": total_proposed,
        "lines": [
            {
                "id": c.id,
                "description": c.description,
                "quantity": c.quantity_actual,
                "unit": c.unit,
                "unit_price": c.unit_price,
                "total_accrued": c.total_accrued,
                "is_extra": c.is_extra,
                "work_date": c.work_date.isoformat() if c.work_date else None,
            }
            for c in candidates
        ],
    }


@router.post("")
async def transmit_to_billing(
    request: Request,
    project_id: int = Form(...),
    period_start: date = Form(...),
    period_end: date = Form(...),
    notes: Optional[str] = Form(None),
    include_extras: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Crea un BillingBatch (status draft) con snapshot delle JobCostLine
    maturate del progetto nel periodo richiesto.

    Una JCL è candidata se:
      - appartiene a un Job del progetto
      - billing_status == not_billed (non già in batch / fatturata)
      - total_accrued > 0 (c'è qualcosa di maturato)
      - work_date in [period_start, period_end] OPPURE work_date NULL
        (default → considerata sempre, l'utente decide caso per caso)
      - is_extra in {True, False}: se include_extras=False, esclude is_extra=True

    Crea N BillingBatchLine snapshot + marca le JCL → in_batch + collega
    JCL.billing_batch_id al nuovo batch. total_approved iniziale = total_proposed
    (manager può ridurre dopo)."""
    user = _require_finance(request)
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == CURRENT_TENANT,
    ).first()
    if not proj:
        raise HTTPException(404, f"Progetto #{project_id} non trovato")
    if period_end < period_start:
        raise HTTPException(400, "period_end precedente a period_start")

    # Trova JCL candidate
    q = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status == JCLBillingStatus.not_billed,
        JobCostLine.total_accrued > 0,
        JobCostLine.is_billable == True,
    )
    if not include_extras:
        q = q.filter(JobCostLine.is_extra == False)
    candidates = q.all()
    # Filtro work_date: ammessi NULL (sempre) o in range
    candidates = [
        c for c in candidates
        if c.work_date is None or (period_start <= c.work_date <= period_end)
    ]
    if not candidates:
        raise HTTPException(
            400,
            f"Nessuna riga maturata da fatturare per progetto #{project_id} nel periodo "
            f"{period_start.isoformat()} → {period_end.isoformat()}"
        )

    # Crea batch
    batch = BillingBatch(
        tenant_id=CURRENT_TENANT,
        code=_next_batch_code(db),
        project_id=project_id,
        status=BillingBatchStatus.draft,
        period_start=period_start,
        period_end=period_end,
        notes=notes,
        transmitted_by_user_id=user.id if user else None,
        transmitted_at=datetime.utcnow(),
    )
    db.add(batch)
    db.flush()  # id disponibile per le lines

    # Snapshot lines + marca JCL
    for jcl in candidates:
        line = BillingBatchLine(
            batch_id=batch.id,
            job_cost_line_id=jcl.id,
            description=jcl.description,
            quantity=jcl.quantity_actual,
            unit=jcl.unit,
            unit_price=jcl.unit_price,
            total_proposed=jcl.total_accrued,
            total_approved=jcl.total_accrued,  # default = proposed
            is_extra=jcl.is_extra,
        )
        db.add(line)
        jcl.billing_status = JCLBillingStatus.in_batch
        jcl.billing_batch_id = batch.id
    db.flush()
    _recompute_batch_totals(batch)
    db.commit()
    db.refresh(batch)
    return _batch_to_dict(batch, with_lines=True)


@router.get("")
async def list_batches(
    request: Request,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Lista BillingBatch con filtri opzionali. Default: tutti del tenant
    in ordine cronologico decrescente di trasmissione."""
    _require_finance(request)
    q = db.query(BillingBatch).options(
        joinedload(BillingBatch.project),
        joinedload(BillingBatch.invoice),
    ).filter(BillingBatch.tenant_id == CURRENT_TENANT)
    if project_id:
        q = q.filter(BillingBatch.project_id == project_id)
    if status:
        try:
            q = q.filter(BillingBatch.status == BillingBatchStatus(status))
        except ValueError:
            raise HTTPException(400, f"Status non valido: {status}")
    batches = q.order_by(BillingBatch.transmitted_at.desc()).all()
    return [_batch_to_dict(b, with_lines=False) for b in batches]


@router.get("/{batch_id}")
async def get_batch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Dettaglio batch con tutte le lines snapshot."""
    _require_finance(request)
    batch = db.query(BillingBatch).options(
        joinedload(BillingBatch.project),
        joinedload(BillingBatch.invoice),
        joinedload(BillingBatch.lines),
    ).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    return _batch_to_dict(batch, with_lines=True)


@router.patch("/{batch_id}/lines/{line_id}")
async def edit_batch_line(
    batch_id: int, line_id: int,
    request: Request,
    total_approved: float = Form(...),
    notes: Optional[str] = Form(None),
    loss_reason: str = Form("manager_discount"),
    db: Session = Depends(get_db),
):
    """Manager modifica l'importo approvato di una linea. Se total_approved <
    total_proposed, viene creato (o aggiornato) un LossEntry con il delta.

    Solo batch in stato `draft`. Manager+ richiesto."""
    user = _require_manager(request)
    batch = db.query(BillingBatch).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status != BillingBatchStatus.draft:
        raise HTTPException(400, f"Batch non modificabile in stato {batch.status.value}")
    line = db.query(BillingBatchLine).filter(
        BillingBatchLine.id == line_id, BillingBatchLine.batch_id == batch_id,
    ).first()
    if not line:
        raise HTTPException(404, "Riga non trovata")
    if total_approved < 0:
        raise HTTPException(400, "total_approved non può essere negativo")
    if total_approved > line.total_proposed * 1.5:
        raise HTTPException(
            400,
            f"total_approved ({total_approved}) eccede troppo il proposed "
            f"({line.total_proposed}). Per maggiorazioni superiori al 50% "
            f"crea una nuova JCL extra invece di modificare il batch."
        )
    try:
        loss_reason_enum = LossReason(loss_reason)
    except ValueError:
        raise HTTPException(400, f"loss_reason non valido: {loss_reason}")

    old_approved = line.total_approved
    line.total_approved = total_approved
    if notes is not None:
        line.notes = notes

    # Gestione LossEntry: rimuovi vecchio (se esisteva) e crea nuovo se delta > 0
    delta = line.total_proposed - line.total_approved
    db.query(LossEntry).filter(
        LossEntry.billing_batch_line_id == line.id
    ).delete(synchronize_session=False)
    if delta > 0.001:  # tolerance float
        loss = LossEntry(
            tenant_id=CURRENT_TENANT,
            project_id=batch.project_id,
            job_cost_line_id=line.job_cost_line_id,
            billing_batch_line_id=line.id,
            amount=delta,
            reason=loss_reason_enum,
            notes=notes,
            created_by_user_id=user.id if user else None,
        )
        db.add(loss)

    _recompute_batch_totals(batch)
    db.commit()
    db.refresh(batch)
    return {
        "ok": True,
        "line_id": line.id,
        "old_approved": old_approved,
        "new_approved": line.total_approved,
        "delta_lost": delta if delta > 0 else 0,
        "batch_total_approved": batch.total_approved,
        "batch_total_lost": batch.total_lost,
    }


@router.post("/{batch_id}/approve")
async def approve_batch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Manager approva il batch (draft → approved). Da qui può essere
    emessa la fattura. Una volta approvato non è più modificabile."""
    user = _require_manager(request)
    batch = db.query(BillingBatch).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status != BillingBatchStatus.draft:
        raise HTTPException(400, f"Batch non può essere approvato dallo stato {batch.status.value}")
    if not batch.lines:
        raise HTTPException(400, "Batch senza linee, niente da approvare")
    batch.status = BillingBatchStatus.approved
    batch.approved_by_user_id = user.id if user else None
    batch.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(batch)
    return _batch_to_dict(batch, with_lines=True)


@router.post("/{batch_id}/invoice")
async def emit_invoice(
    batch_id: int,
    request: Request,
    invoice_number: str = Form(...),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    vat_rate: float = Form(22.0),
    db: Session = Depends(get_db),
):
    """Emette una Invoice da un batch approved. Crea Invoice + InvoiceLine
    (1 per BillingBatchLine), collega `invoice_id` al batch, marca le JCL
    coinvolte → billed con `billed_amount` = total_approved della line.

    Manager+ richiesto. Numero fattura specificato manualmente
    (non auto-numerato per non interferire col tuo gestionale fiscale)."""
    _require_manager(request)
    batch = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status != BillingBatchStatus.approved:
        raise HTTPException(
            400,
            f"Batch deve essere approved per emettere fattura (attuale: {batch.status.value})"
        )
    if not batch.lines:
        raise HTTPException(400, "Batch vuoto, niente da fatturare")
    # Verifica unicità numero fattura (v3.5.0-alpha.51.1 fix A3: scoped per
    # tenant via JOIN client; multi-tenant futuro non subirà collisioni)
    existing = db.query(Invoice).join(Client, Invoice.client_id == Client.id).filter(
        Invoice.number == invoice_number,
        Client.tenant_id == CURRENT_TENANT,
    ).first()
    if existing:
        raise HTTPException(409, f"Numero fattura {invoice_number} già esistente")
    # Ricava client_id dal progetto → cliente
    project = db.query(Project).filter(Project.id == batch.project_id).first()
    if not project or not project.client_id:
        raise HTTPException(400, "Progetto senza cliente, impossibile fatturare")

    subtotal = batch.total_approved
    vat_amount = subtotal * vat_rate / 100
    total = subtotal + vat_amount

    invoice = Invoice(
        number=invoice_number,
        client_id=project.client_id,
        status=InvoiceStatus.draft,
        issue_date=issue_date,
        due_date=due_date,
        subtotal=subtotal,
        vat_rate=vat_rate,
        total=total,
        notes=f"Generata da BillingBatch {batch.code}",
    )
    db.add(invoice)
    db.flush()

    # Linee fattura snapshot da batch lines
    for bl in batch.lines:
        if bl.total_approved <= 0:
            continue  # skip lines azzerate (loss totale)
        il = InvoiceLine(
            invoice_id=invoice.id,
            description=bl.description + (" [extra]" if bl.is_extra else ""),
            quantity=bl.quantity,
            unit_price=bl.unit_price,
            total=bl.total_approved,
        )
        db.add(il)
        # Marca JCL → billed con importo effettivo
        jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
        if jcl:
            jcl.billing_status = JCLBillingStatus.billed
            jcl.billed_amount = bl.total_approved
    # Marca le JCL azzerate come `lost` (manager le ha scartate completamente)
    for bl in batch.lines:
        if bl.total_approved <= 0.001:
            jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
            if jcl:
                jcl.billing_status = JCLBillingStatus.lost
                jcl.billed_amount = 0

    batch.status = BillingBatchStatus.invoiced
    batch.invoice_id = invoice.id
    db.commit()
    db.refresh(batch)
    return {
        "batch": _batch_to_dict(batch, with_lines=True),
        "invoice_id": invoice.id,
        "invoice_number": invoice.number,
        "subtotal": subtotal,
        "vat_amount": vat_amount,
        "total": total,
    }


@router.post("/{batch_id}/cancel")
async def cancel_batch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Annulla un batch ancora non fatturato. Riporta le JCL → not_billed
    (le rilibera per future trasmissioni). Cancella le LossEntry collegate
    (il perso non era ancora 'reale')."""
    _require_manager(request)
    batch = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status == BillingBatchStatus.invoiced:
        raise HTTPException(400, "Batch già fatturato, impossibile annullare. Usa l'annullamento fattura.")
    if batch.status == BillingBatchStatus.cancelled:
        raise HTTPException(400, "Batch già annullato")

    # Rilascia JCL (v3.5.0-alpha.51.1 fix M1: include `lost` per coprire JCL
    # ridotte a 0 dal manager prima del cancel — ritornano disponibili)
    for bl in batch.lines:
        jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
        if jcl and jcl.billing_status in (JCLBillingStatus.in_batch, JCLBillingStatus.lost):
            jcl.billing_status = JCLBillingStatus.not_billed
            jcl.billing_batch_id = None
    # Cancella LossEntry collegate
    line_ids = [l.id for l in batch.lines]
    if line_ids:
        db.query(LossEntry).filter(
            LossEntry.billing_batch_line_id.in_(line_ids)
        ).delete(synchronize_session=False)

    batch.status = BillingBatchStatus.cancelled
    db.commit()
    return {"ok": True, "released_lines": len(batch.lines)}


@router.patch("/jcl/{jcl_id}/billing-status")
async def set_jcl_billing_status(
    jcl_id: int,
    request: Request,
    new_status: str = Form(...),
    db: Session = Depends(get_db),
):
    """Manager+ override manuale dello stato di una singola JCL.
    Usato tipicamente per: (billed → paid) quando la fattura è stata pagata,
    oppure (in_batch → lost) per write-off senza passare dal batch.
    NON sostituisce il flow normale; è una via d'uscita per casi limite."""
    _require_manager(request)
    try:
        st = JCLBillingStatus(new_status)
    except ValueError:
        raise HTTPException(400, f"Stato non valido: {new_status}")
    # v3.5.0-alpha.51.1 fix A1: filtra per tenant via JOIN job→project
    jcl = db.query(JobCostLine).join(Job, JobCostLine.job_id == Job.id).join(
        Project, Job.project_id == Project.id
    ).filter(
        JobCostLine.id == jcl_id,
        Project.tenant_id == CURRENT_TENANT,
    ).first()
    if not jcl:
        raise HTTPException(404, "JCL non trovata")
    old = jcl.billing_status.value
    jcl.billing_status = st
    db.commit()
    return {"ok": True, "jcl_id": jcl_id, "old_status": old, "new_status": st.value}


@router.get("/loss/project/{project_id}")
async def project_loss_summary(
    project_id: int, request: Request, db: Session = Depends(get_db),
):
    """Sommario LossEntry di un progetto, aggregato per reason. Usato per
    rendicontazione finanziaria a chiusura progetto."""
    _require_finance(request)
    losses = db.query(LossEntry).filter(
        LossEntry.tenant_id == CURRENT_TENANT,
        LossEntry.project_id == project_id,
    ).all()
    total = sum(l.amount for l in losses)
    by_reason: dict[str, dict] = {}
    for l in losses:
        r = l.reason.value
        if r not in by_reason:
            by_reason[r] = {"count": 0, "total": 0.0}
        by_reason[r]["count"] += 1
        by_reason[r]["total"] += l.amount
    return {
        "project_id": project_id,
        "total_lost": total,
        "count": len(losses),
        "by_reason": by_reason,
        "entries": [
            {
                "id": l.id,
                "amount": l.amount,
                "reason": l.reason.value,
                "notes": l.notes,
                "job_cost_line_id": l.job_cost_line_id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in sorted(losses, key=lambda x: x.created_at or datetime.min, reverse=True)
        ],
    }
