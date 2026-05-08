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
    JCLBilledSlice,
    Project, Job, JobStatus, Invoice, InvoiceLine, InvoiceStatus, Client,
    Tenant,
    Booking, BookingStatus, BookingExecutionStatus,
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
        # v3.5.0-alpha.56: hydration JCL → quotato + over (sforamento) per riga.
        # Serve all'UI /finance per decidere "fattura subito" vs "rimanda
        # a consuntivo". Lookup JCL in singola query via session dell'oggetto.
        from sqlalchemy.orm import object_session
        jcl_quoted: dict[int, float] = {}
        sess = object_session(b)
        jcl_ids = [l.job_cost_line_id for l in b.lines if l.job_cost_line_id]
        if jcl_ids and sess is not None:
            rows = (
                sess.query(JobCostLine.id, JobCostLine.total_quoted)
                .filter(JobCostLine.id.in_(jcl_ids))
                .all()
            )
            jcl_quoted = {r[0]: (r[1] or 0.0) for r in rows}
        out["lines"] = []
        for l in b.lines:
            tq = jcl_quoted.get(l.job_cost_line_id, 0.0)
            tp = l.total_proposed or 0.0
            # over = sforamento sul quotato (per righe non-extra; gli extra
            # sono tutti "fuori budget" per definizione e vengono trattati come
            # categoria a sé nella UI).
            over = 0.0 if l.is_extra else max(0.0, tp - tq)
            out["lines"].append({
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
                # v3.5.0-alpha.56
                "total_quoted": round(tq, 2),
                "over": round(over, 2),
            })
    return out


def _recompute_batch_totals(b: BillingBatch):
    """Ricalcola total_proposed/approved/lost dalle lines correnti."""
    b.total_proposed = sum(l.total_proposed for l in b.lines)
    b.total_approved = sum(l.total_approved for l in b.lines)
    b.total_lost = max(0.0, b.total_proposed - b.total_approved)


def _period_from_bookings(db: Session, jcl_ids: list[int]) -> tuple[date, date, str]:
    """v3.5.0-alpha.57 — Periodo di trasmissione dalle date dei booking done.

    Bug pre-α.57: usavamo min/max di JCL.work_date, ma cost_line_sync
    salva su work_date solo il MAX delle date done (l'ultima data lavorata
    per JCL). Risultato: il "min" tra le JCL era la più precoce *delle ultime
    date*, non la prima data effettivamente lavorata. Es. JCL con booking
    1 mar → 30 apr aveva work_date=30 apr e il 1 mar era perso.

    Fix: leggi direttamente da Booking. Per le JCL candidate prendi:
      - period_start = min(start_datetime.date()) sui booking done non cancellati
      - period_end   = max(end_datetime.date())   sui booking done non cancellati

    Fallback al mese corrente se nessuna delle JCL ha booking done (caso
    JCL extra senza booking, o quote pura senza esecuzione).
    """
    if jcl_ids:
        bookings = db.query(Booking).filter(
            Booking.job_cost_line_id.in_(jcl_ids),
            Booking.status != BookingStatus.cancelled,
            Booking.execution_status == BookingExecutionStatus.done,
        ).all()
    else:
        bookings = []
    if bookings:
        period_start = min(b.start_datetime.date() for b in bookings if b.start_datetime)
        period_end = max(b.end_datetime.date() for b in bookings if b.end_datetime)
        return period_start, period_end, "from_bookings"
    today = date.today()
    period_start = today.replace(day=1)
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    period_end = date.fromordinal(next_month.toordinal() - 1)
    return period_start, period_end, "current_month_fallback"


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

    v3.5.0-alpha.57: il periodo è derivato direttamente dai Booking done
    delle JCL candidate (min start_datetime → max end_datetime), non più
    da JCL.work_date che salvava solo l'ULTIMA data done. Vedi
    `_period_from_bookings` per il dettaglio del fix.

    Ritorna anche count e total per anteprima nel modal.
    """
    _require_finance(request)
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == CURRENT_TENANT,
    ).first()
    if not proj:
        raise HTTPException(404, f"Progetto #{project_id} non trovato")

    q = db.query(JobCostLine).join(Job).options(joinedload(JobCostLine.job)).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status == JCLBillingStatus.not_billed,
        JobCostLine.total_accrued > 0,
        JobCostLine.is_billable == True,
    )
    if not include_extras:
        q = q.filter(JobCostLine.is_extra == False)
    candidates = q.all()

    period_start, period_end, period_source = _period_from_bookings(
        db, [c.id for c in candidates]
    )

    # v3.5.0-alpha.56: breakdown esplicito quote vs extra + sforamento.
    # Sforamento = max(0, total_accrued - total_quoted) sulle righe NON extra
    # (le extra sono già "fuori budget" per definizione).
    quote_lines = [c for c in candidates if not c.is_extra]
    extra_lines = [c for c in candidates if c.is_extra]
    quote_total = round(sum(c.total_accrued for c in quote_lines), 2)
    extra_total = round(sum(c.total_accrued for c in extra_lines), 2)
    overrun_total = round(sum(
        max(0.0, (c.total_accrued or 0) - (c.total_quoted or 0))
        for c in quote_lines
    ), 2)
    total_proposed = round(sum(c.total_accrued for c in candidates), 2)
    return {
        "project_id": project_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_source": period_source,
        "include_extras": include_extras,
        "candidate_count": len(candidates),
        "total_proposed": total_proposed,
        # v3.5.0-alpha.56: breakdown
        "quote_count": len(quote_lines),
        "quote_total": quote_total,
        "extra_count": len(extra_lines),
        "extra_total": extra_total,
        "overrun_total": overrun_total,
        "lines": [
            {
                "id": c.id,
                "description": c.description,
                "quantity": c.quantity_actual,
                "unit": c.unit,
                "unit_price": c.unit_price,
                "total_quoted": c.total_quoted,
                "total_accrued": c.total_accrued,
                "is_extra": c.is_extra,
                "work_date": c.work_date.isoformat() if c.work_date else None,
                # v3.5.0-alpha.64: contesto job per UI tabella checkbox.
                "job_id": c.job_id,
                "job_code": (c.job.code if c.job else None),
                "job_title": (c.job.title if c.job else None),
                # over per riga: per evidenziare in UI le righe in sforamento
                "overrun": round(max(0.0, (c.total_accrued or 0) - (c.total_quoted or 0)), 2)
                           if not c.is_extra else 0.0,
            }
            for c in candidates
        ],
    }


def _transmit_core(
    db: Session,
    *,
    project_id: int,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    notes: Optional[str] = None,
    include_extras: bool = True,
    user_id: Optional[int] = None,
    jcl_ids: Optional[list[int]] = None,
) -> dict:
    """Logica core trasmissione → BillingBatch (estratta da endpoint per
    riuso da AI handler propose_transmit_to_billing).

    Se period_start/end omessi, derivati automaticamente da min/max delle
    date dei Booking done delle JCL candidate (vedi `_period_from_bookings`,
    fix v3.5.0-alpha.57).

    v3.5.0-alpha.64: parametro `jcl_ids` opzionale. Se valorizzato, filtra
    le candidate a quella lista esplicita (selezione granulare in UI). I
    valori che non sono tra le candidate normali (per progetto/billing_status/
    accrued/billable) vengono ignorati con un warning interno.
    `include_extras` resta efficace anche con `jcl_ids` esplicito.

    Solleva ValueError per errori di validazione (l'endpoint HTTP li riconverte
    in HTTPException).
    """
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == CURRENT_TENANT,
    ).first()
    if not proj:
        raise ValueError(f"Progetto #{project_id} non trovato")

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

    # v3.5.0-alpha.64: filtro per selezione esplicita
    if jcl_ids is not None:
        ids_set = set(jcl_ids)
        candidates = [c for c in candidates if c.id in ids_set]
        if not candidates:
            raise ValueError(
                "Nessuna delle JCL selezionate è candidata valida "
                "(non in stato not_billed con maturato > 0)."
            )

    # Auto-derive period se non specificato (v3.5.0-alpha.57: da Booking done)
    if period_start is None or period_end is None:
        derived_start, derived_end, _src = _period_from_bookings(
            db, [c.id for c in candidates]
        )
        period_start = period_start or derived_start
        period_end = period_end or derived_end

    if period_end < period_start:
        raise ValueError("period_end precedente a period_start")

    # Filtro work_date: ammessi NULL (sempre) o in range
    candidates = [
        c for c in candidates
        if c.work_date is None or (period_start <= c.work_date <= period_end)
    ]
    if not candidates:
        raise ValueError(
            f"Nessuna riga maturata da fatturare per progetto #{project_id} nel periodo "
            f"{period_start.isoformat()} → {period_end.isoformat()}"
        )

    batch = BillingBatch(
        tenant_id=CURRENT_TENANT,
        code=_next_batch_code(db),
        project_id=project_id,
        status=BillingBatchStatus.draft,
        period_start=period_start,
        period_end=period_end,
        notes=notes,
        transmitted_by_user_id=user_id,
        transmitted_at=datetime.utcnow(),
    )
    db.add(batch)
    db.flush()

    for jcl in candidates:
        line = BillingBatchLine(
            batch_id=batch.id,
            job_cost_line_id=jcl.id,
            description=jcl.description,
            quantity=jcl.quantity_actual,
            unit=jcl.unit,
            unit_price=jcl.unit_price,
            total_proposed=jcl.total_accrued,
            total_approved=jcl.total_accrued,
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


@router.post("")
async def transmit_to_billing(
    request: Request,
    project_id: int = Form(...),
    period_start: date = Form(...),
    period_end: date = Form(...),
    notes: Optional[str] = Form(None),
    include_extras: bool = Form(True),
    # v3.5.0-alpha.64: selezione granulare. Stringa CSV "12,17,42" oppure NULL
    # per fallback al comportamento "tutte le candidate" (back-compat α.57).
    jcl_ids: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea un BillingBatch (status draft) con snapshot delle JobCostLine
    maturate del progetto nel periodo richiesto.

    v3.5.0-alpha.64: il finance può passare `jcl_ids` (CSV) per scegliere
    esplicitamente quali righe trasmettere (escludendo le altre dal batch).
    Se omesso, il comportamento è "tutte le candidate" come pre-α.64.
    """
    user = _require_finance(request)
    parsed_ids: Optional[list[int]] = None
    if jcl_ids and jcl_ids.strip():
        try:
            parsed_ids = [int(x.strip()) for x in jcl_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, f"jcl_ids non valido: {jcl_ids}")
        if not parsed_ids:
            raise HTTPException(400, "jcl_ids vuoto dopo parsing")
    try:
        return _transmit_core(
            db,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            notes=notes,
            include_extras=include_extras,
            user_id=user.id if user else None,
            jcl_ids=parsed_ids,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


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


@router.post("/{batch_id}/lines/{line_id}/defer")
async def defer_batch_line(
    batch_id: int, line_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.56 — Rimanda una riga del batch al consuntivo finale.

    Operativamente: rimuove la BillingBatchLine dal batch (draft) e riporta la
    JobCostLine collegata a `not_billed` (rilibera per future trasmissioni).
    Eventuali LossEntry collegate alla riga vengono cancellate (era una loss
    ipotizzata, non realizzata).

    Use case: il manager vede una riga in over (es. extra non concordato col
    cliente, o sforamento orario) e decide di NON fatturarla subito; resterà
    in coda per la fattura di consuntivo finale.

    Idempotente: se line_id non appartiene al batch o batch non è draft, 400.
    Manager+ richiesto."""
    user = _require_manager(request)
    batch = db.query(BillingBatch).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status != BillingBatchStatus.draft:
        raise HTTPException(
            400, f"Batch non modificabile in stato {batch.status.value}. "
                 "Per rimandare una riga occorre che il batch sia in bozza."
        )
    line = db.query(BillingBatchLine).filter(
        BillingBatchLine.id == line_id, BillingBatchLine.batch_id == batch_id,
    ).first()
    if not line:
        raise HTTPException(404, "Riga non trovata in questo batch")

    # Rilascia la JCL collegata: torna not_billed, rimossa dal batch
    jcl_id = line.job_cost_line_id
    if jcl_id:
        jcl = db.query(JobCostLine).filter(JobCostLine.id == jcl_id).first()
        if jcl:
            jcl.billing_status = JCLBillingStatus.not_billed
            jcl.billing_batch_id = None

    # Cancella eventuali LossEntry collegate alla riga (loss ipotizzata)
    db.query(LossEntry).filter(
        LossEntry.billing_batch_line_id == line.id
    ).delete(synchronize_session=False)

    # Rimuovi la riga dal batch
    db.delete(line)
    db.flush()

    # Ricalcola totali batch. Se vuoto, lo lascio in draft (manager può
    # cancellarlo manualmente) — non auto-cancello per evitare side-effect
    # "magici" che il manager non si aspetta.
    db.refresh(batch)
    _recompute_batch_totals(batch)
    db.commit()
    db.refresh(batch)
    return {
        "ok": True,
        "deferred_line_id": line_id,
        "released_jcl_id": jcl_id,
        "remaining_lines": len(batch.lines),
        "batch_total_proposed": batch.total_proposed,
        "batch_total_approved": batch.total_approved,
    }


@router.post("/{batch_id}/lines/{line_id}/refer-to-sales")
async def refer_batch_line_to_sales(
    batch_id: int, line_id: int,
    request: Request,
    mode: str = Form(...),  # "extend_existing" | "new_linked"
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.64 — refer-to-sales DA batch detail (oltre che da cost-report).

    Combina `defer` (rilascio JCL dal batch) + refer-to-sales (creazione
    quote/versione con riga `[EXTRA]` collegata). Use case: il manager in
    approvazione batch vede una riga in over, decide di non fatturarla subito
    e di girarla al commerciale → 1 click la rimuove dal batch + estende la
    quote. JCL torna `not_billed`; la riga `[EXTRA]` punta a `referred_from_jcl_id`.

    Vincoli:
      - Batch deve essere in `draft`.
      - JCL collegata DEVE avere `total_accrued > billed_locked` (altrimenti
        ValueError dal core: niente extra da riferire).
    """
    user = _require_manager(request)
    if mode not in ("extend_existing", "new_linked"):
        raise HTTPException(400, f"mode non valido: {mode}")

    batch = db.query(BillingBatch).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status != BillingBatchStatus.draft:
        raise HTTPException(
            400, f"Batch non modificabile in stato {batch.status.value}. "
                 "Per rimandare una riga al commerciale occorre che il batch sia in bozza."
        )
    line = db.query(BillingBatchLine).filter(
        BillingBatchLine.id == line_id, BillingBatchLine.batch_id == batch_id,
    ).first()
    if not line:
        raise HTTPException(404, "Riga non trovata in questo batch")
    if not line.job_cost_line_id:
        raise HTTPException(400, "Riga senza JCL collegata, impossibile riferire")

    jcl_id = line.job_cost_line_id

    # Step 1: rilascia la JCL dal batch (come `defer`)
    jcl = db.query(JobCostLine).filter(JobCostLine.id == jcl_id).first()
    if jcl:
        jcl.billing_status = JCLBillingStatus.not_billed
        jcl.billing_batch_id = None
    db.query(LossEntry).filter(
        LossEntry.billing_batch_line_id == line.id
    ).delete(synchronize_session=False)
    db.delete(line)
    db.flush()
    db.refresh(batch)
    _recompute_batch_totals(batch)
    db.flush()

    # Step 2: refer-to-sales sulla JCL appena rilasciata
    try:
        refer_res = _refer_jcl_to_sales_core(db, jcl_id, mode, notes)
    except ValueError as e:
        # Se refer fallisce, NON commettiamo lo step 1 (rollback completo).
        # La riga torna in batch e JCL torna in_batch.
        db.rollback()
        msg = str(e)
        if "non trovata" in msg or "non trovato" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(400, msg)

    # core ha già committato (vedi _refer_jcl_to_sales_impl). Commit-already.
    return {
        "ok": True,
        "removed_batch_line_id": line_id,
        "released_jcl_id": jcl_id,
        "remaining_batch_lines": len(batch.lines),
        "batch_total_proposed": batch.total_proposed,
        **refer_res,
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

    # v3.5.0-alpha.52 — Snapshot dati fiscali al momento dell'emissione.
    # Modifiche successive a tenant/cliente NON corrompono la fattura storica.
    client_obj = db.query(Client).filter(Client.id == project.client_id).first()
    tenant_obj = db.query(Tenant).filter(Tenant.id == CURRENT_TENANT).first()

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
        doc_type="TD01",
        payment_method=(tenant_obj.payment_method_default if tenant_obj else None),
        payment_terms_days=(tenant_obj.payment_terms_default if tenant_obj else None),
        iban_snapshot=(tenant_obj.iban if tenant_obj else None),
        # Snapshot client (cessionario)
        client_legal_name_snap=(client_obj.legal_form and client_obj.name and f"{client_obj.name} {client_obj.legal_form}".strip()) or (client_obj.name if client_obj else None),
        client_vat_snap=(client_obj.vat_number if client_obj else None),
        client_tax_code_snap=(client_obj.tax_code if client_obj else None),
        client_pec_snap=(client_obj.pec if client_obj else None),
        client_sdi_snap=(client_obj.sdi_code if client_obj else None),
        client_address_snap=(client_obj.address if client_obj else None),
        client_zip_snap=(client_obj.zip_code if client_obj else None),
        client_city_snap=(client_obj.city if client_obj else None),
        client_province_snap=(client_obj.province if client_obj else None),
        client_country_snap=(client_obj.country if client_obj else None),
        # Snapshot tenant (cedente)
        tenant_legal_name_snap=((tenant_obj.legal_name or tenant_obj.name) if tenant_obj else None),
        tenant_vat_snap=(tenant_obj.vat_number if tenant_obj else None),
        tenant_tax_code_snap=(tenant_obj.tax_code if tenant_obj else None),
        tenant_address_snap=(tenant_obj.address if tenant_obj else None),
        tenant_email_snap=(tenant_obj.email if tenant_obj else None),
        tenant_phone_snap=(tenant_obj.phone if tenant_obj else None),
        tenant_iban_snap=(tenant_obj.iban if tenant_obj else None),
        tenant_sdi_snap=(tenant_obj.sdi_code if tenant_obj else None),
        tenant_rea_snap=(tenant_obj.rea_number if tenant_obj else None),
        tenant_fiscal_capital_snap=(tenant_obj.fiscal_capital if tenant_obj else None),
        tenant_fiscal_regime_snap=(tenant_obj.fiscal_regime if tenant_obj else None),
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
            vat_rate=vat_rate,  # uniforme da emit; UI futura potrà differenziare
            discount_pct=0.0,
        )
        db.add(il)
        # Marca JCL → billed con importo effettivo
        jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
        if jcl:
            jcl.billing_status = JCLBillingStatus.billed
            jcl.billed_amount = bl.total_approved
        # v3.5.0-alpha.58 — JCLBilledSlice immutabile per la porzione fatturata.
        # Foundation per α.59/α.60: la JCL non è più "billed/non-billed binaria"
        # ma ha un set di slice con periodi e importi specifici.
        slice_ = JCLBilledSlice(
            tenant_id=CURRENT_TENANT,
            job_cost_line_id=bl.job_cost_line_id,
            billing_batch_line_id=bl.id,
            invoice_id=invoice.id,
            period_start=batch.period_start,
            period_end=batch.period_end,
            billed_quantity=bl.quantity or 0.0,
            billed_amount=bl.total_approved,
            unit_price_snap=bl.unit_price or 0.0,
        )
        db.add(slice_)
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


def _refer_jcl_to_sales_core(
    db: Session, jcl_id: int, mode: str, notes: Optional[str] = None,
) -> dict:
    """v3.5.0-alpha.64: estrazione del core di refer-to-sales per riuso da
    batch-detail (un'altra entry-point oltre al pulsante di cost-report).

    Solleva ValueError sui casi di validazione (chi chiama converte in 4xx).
    Ritorna {ok, mode, quote_id, quote_number, quote_url, jcl_id}.
    """
    if mode not in ("extend_existing", "new_linked"):
        raise ValueError(f"mode non valido: {mode}")
    jcl = (
        db.query(JobCostLine)
        .options(joinedload(JobCostLine.job).joinedload(Job.quote))
        .filter(JobCostLine.id == jcl_id)
        .first()
    )
    if not jcl:
        raise ValueError(f"JobCostLine #{jcl_id} non trovata")
    job = jcl.job
    if not job:
        raise ValueError("JCL senza job, impossibile riferire al commerciale")
    if not job.project_id:
        raise ValueError("Job senza progetto, impossibile creare/estendere quote")
    return _refer_jcl_to_sales_impl(db, jcl, mode, notes)


@router.post("/refer-to-sales")
async def refer_to_sales(
    request: Request,
    jcl_id: int = Form(...),
    mode: str = Form(...),  # "extend_existing" | "new_linked"
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.62 — "Rimanda al commerciale".

    Quando emerge lavoro extra/sforamento su un progetto già fatturato, il
    finance può non fatturarlo subito e invece riportarlo al commerciale per:
      - **extend_existing**: nuova versione della quote già linkata al job,
        con una riga aggiuntiva che riflette il lavoro extra (parent_quote_id
        valorizzato → catena versioning standard).
      - **new_linked**: una NUOVA quote indipendente sullo stesso progetto
        (no parent_quote_id), pensata per un addendum negoziato a parte.

    In entrambi i casi la nuova/aggiornata quote ha `status=draft` e una
    QuoteLine derivata dalla JCL (descrizione, qty=accrued_post_period,
    unit_price snapshot) — il commerciale poi rivede e invia al cliente.

    Manager+ richiesto. Ritorna `{quote_id, quote_number, quote_url, mode}`.
    """
    user = _require_manager(request)
    try:
        return _refer_jcl_to_sales_core(db, jcl_id, mode, notes)
    except ValueError as e:
        # 404 vs 400 differenziato sul testo per back-compat con test/UI
        msg = str(e)
        if "non trovata" in msg or "non trovato" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(400, msg)


def _refer_jcl_to_sales_impl(
    db: Session, jcl, mode: str, notes: Optional[str],
) -> dict:
    """Implementazione effettiva di refer-to-sales (chiamata da
    `_refer_jcl_to_sales_core` dopo aver validato jcl/job/project)."""
    job = jcl.job
    # Determina lavoro residuo: preferisco accrued_post_period (eccedenza
    # rispetto a già fatturato), fallback a total_accrued se nessuna slice.
    from app.services.billing_slice_guard import billed_locked_for_jcl
    billed = billed_locked_for_jcl(db, jcl.id)
    accrued = jcl.total_accrued or 0.0
    qty_extra = max(0.0, accrued - billed)
    if qty_extra <= 0.001:
        raise ValueError(
            "Niente extra da riferire al commerciale: il maturato è già "
            "tutto coperto dalle fatture emesse."
        )
    unit_price = jcl.unit_price or 0.0
    qty = (qty_extra / unit_price) if unit_price > 0 else 1.0

    from app.models import Quote, QuoteLine, QuoteStatus, Client
    project = db.query(Project).filter(Project.id == job.project_id).first()
    if not project:
        raise ValueError("Progetto non trovato")

    note_full = (
        f"Aggiunta da Finance per extra emerso su JCL #{jcl.id} "
        f"({jcl.description}). Maturato post-fatturazione: €{qty_extra:.2f}."
    )
    if notes:
        note_full += f"\nNote operatore: {notes}"

    if mode == "extend_existing":
        if not job.quote_id or not job.quote:
            raise ValueError(
                "Job senza quote linkata. Usa mode=`new_linked` per creare "
                "una nuova quote sul progetto."
            )
        # Crea nuova versione della quote del job (catena versioning).
        # Logica allineata a /quotes/api/{id}/new-version.
        from app.routers.quotes import (
            _quote_root, _quote_chain, _copy_quote_lines, _recalc_quote,
        )
        src = (
            db.query(Quote)
            .options(joinedload(Quote.lines))
            .filter(Quote.id == job.quote_id)
            .first()
        )
        root = _quote_root(db, src)
        chain = _quote_chain(db, root)
        next_version = max(q.version for q in chain) + 1
        import re as _re
        base_number = _re.sub(r"-v\d+$", "", root.number)
        new_number = f"{base_number}-v{next_version}"
        if (
            db.query(Quote)
            .execution_options(include_deleted=True)
            .filter(Quote.number == new_number)
            .first()
        ):
            raise ValueError(f"Numero quotazione `{new_number}` già esistente")

        new_q = Quote(
            number=new_number,
            version=next_version,
            parent_quote_id=src.id,
            project_id=src.project_id,
            client_id=src.client_id,
            title=f"{src.title} — addendum extra (Finance)",
            status=QuoteStatus.draft,
            issue_date=date.today(),
            valid_until=src.valid_until,
            production_material=src.production_material,
            length_minutes=src.length_minutes,
            fps=src.fps,
            delivery_format=src.delivery_format,
            shooting_days=src.shooting_days,
            shooting_format=src.shooting_format,
            package_discount=src.package_discount,
            category_discounts=dict(src.category_discounts) if src.category_discounts else None,
            category_order=list(src.category_order) if src.category_order else None,
            vat_rate=src.vat_rate,
            notes=note_full,
            payment_terms=src.payment_terms,
        )
        db.add(new_q)
        db.flush()
        new_lines = _copy_quote_lines(src.lines, new_q.id, track_parent=True)
        db.add_all(new_lines)
        db.flush()
        # Aggiungi la riga extra
        # v3.5.0-alpha.64: traccia link strutturale a JCL d'origine
        extra_line = QuoteLine(
            quote_id=new_q.id,
            description=f"[EXTRA] {jcl.description}",
            detail=f"Riferito da Finance — JCL #{jcl.id}",
            quantity=round(qty, 2),
            unit=jcl.unit,
            unit_price=unit_price,
            total=round(qty * unit_price, 2),
            sort_order=9999,  # in fondo, manager riordina dopo
            referred_from_jcl_id=jcl.id,
        )
        db.add(extra_line)
        db.flush()
        _recalc_quote(new_q)
        db.commit()
        db.refresh(new_q)
        return {
            "ok": True,
            "mode": "extend_existing",
            "quote_id": new_q.id,
            "quote_number": new_q.number,
            "quote_url": f"/quotes#{new_q.id}",
        }

    # mode == "new_linked"
    # Nuova quote indipendente sullo stesso project (no parent_quote_id).
    from app.routers.quotes import _next_quote_number_progressive, _recalc_quote
    new_number = _next_quote_number_progressive(db)
    new_q = Quote(
        number=new_number,
        version=1,
        project_id=project.id,
        client_id=project.client_id,
        title=f"Addendum extra: {project.title or project.code}",
        status=QuoteStatus.draft,
        issue_date=date.today(),
        notes=note_full,
        vat_rate=22.0,
    )
    db.add(new_q)
    db.flush()
    # v3.5.0-alpha.64: traccia link strutturale a JCL d'origine
    extra_line = QuoteLine(
        quote_id=new_q.id,
        description=f"[EXTRA] {jcl.description}",
        detail=f"Riferito da Finance — JCL #{jcl.id}",
        quantity=round(qty, 2),
        unit=jcl.unit,
        unit_price=unit_price,
        total=round(qty * unit_price, 2),
        sort_order=10,
        referred_from_jcl_id=jcl.id,
    )
    db.add(extra_line)
    db.flush()
    _recalc_quote(new_q)
    db.commit()
    db.refresh(new_q)
    return {
        "ok": True,
        "mode": "new_linked",
        "quote_id": new_q.id,
        "quote_number": new_q.number,
        "quote_url": f"/quotes#{new_q.id}",
    }


@router.get("/jcl/{jcl_id}/origin-info")
async def jcl_origin_info(jcl_id: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.64 — info compatte per UI quote: link cost-report di
    riferimento per una QuoteLine con `referred_from_jcl_id` valorizzato.

    Ritorna {jcl_id, description, job_id, job_code, project_id, project_code,
    project_title, cost_report_url}.
    """
    jcl = (
        db.query(JobCostLine)
        .options(joinedload(JobCostLine.job).joinedload(Job.project))
        .filter(JobCostLine.id == jcl_id)
        .first()
    )
    if not jcl:
        raise HTTPException(404, f"JCL #{jcl_id} non trovata")
    job = jcl.job
    project = job.project if job else None
    return {
        "jcl_id": jcl.id,
        "description": jcl.description,
        "job_id": (job.id if job else None),
        "job_code": (job.code if job else None),
        "project_id": (project.id if project else None),
        "project_code": (project.code if project else None),
        "project_title": (project.title if project else None),
        "cost_report_url": (f"/cost-report#job-{job.id}" if job else None),
    }


@router.get("/jcl/{jcl_id}/referrals")
async def jcl_referrals(jcl_id: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.64 — reverse lookup: quote-line che referenziano questa JCL
    (via `referred_from_jcl_id`, valorizzato in refer-to-sales).

    Usato dalla UI cost-report per mostrare badge "↪ Riferita su Q-NNN-NN v2"
    sulle JCL già rimandate al commerciale.

    Ritorna lista di {quote_line_id, quote_id, quote_number, quote_version,
    quote_status, quote_url, line_description, line_total}.
    """
    from app.models import Quote, QuoteLine
    rows = (
        db.query(QuoteLine, Quote)
        .join(Quote, QuoteLine.quote_id == Quote.id)
        .filter(
            QuoteLine.referred_from_jcl_id == jcl_id,
            Quote.deleted_at.is_(None),
        )
        .order_by(Quote.created_at.desc())
        .all()
    )
    return [
        {
            "quote_line_id": ql.id,
            "quote_id": q.id,
            "quote_number": q.number,
            "quote_version": q.version,
            "quote_status": (q.status.value if hasattr(q.status, "value") else q.status),
            "quote_url": f"/quotes#{q.id}",
            "line_description": ql.description,
            "line_total": ql.total,
        }
        for ql, q in rows
    ]


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


# ── v3.5.0-alpha.52: PDF formale fattura ─────────────────────────────

@router.get("/{batch_id}/invoice-pdf")
async def get_invoice_pdf(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Scarica il PDF della fattura collegata al batch (status=invoiced).

    Usa snapshot fiscali catturati al momento dell'emissione: modifiche
    successive a tenant/cliente NON corrompono questo PDF storico.
    """
    from fastapi.responses import Response
    from app.services.invoice_pdf import generate_invoice_pdf
    _require_finance(request)
    batch = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == CURRENT_TENANT,
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status != BillingBatchStatus.invoiced or not batch.invoice_id:
        raise HTTPException(400, "Il batch non ha ancora una fattura emessa")
    invoice = db.query(Invoice).options(joinedload(Invoice.lines)).filter(
        Invoice.id == batch.invoice_id,
    ).first()
    if not invoice:
        raise HTTPException(404, "Fattura non trovata")
    # Fallback: se snapshot non popolati (fattura pre-α.52), passa anche
    # gli oggetti vivi per compilare il PDF dai campi attuali.
    tenant_obj = db.query(Tenant).filter(Tenant.id == CURRENT_TENANT).first()
    client_obj = db.query(Client).filter(Client.id == invoice.client_id).first()
    pdf = generate_invoice_pdf(invoice, tenant=tenant_obj, client=client_obj)
    safe_num = (invoice.number or f"invoice-{invoice.id}").replace("/", "-")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="Fattura-{safe_num}.pdf"',
        },
    )
