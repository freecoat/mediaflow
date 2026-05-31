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
from app.services.clock import now_utc
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
    Project, Job, JobStatus, Invoice, InvoiceLine, InvoiceStatus, InvoiceKind, Client,
    Tenant,
    Booking, BookingStatus, BookingExecutionStatus,
    AdvancePayment, AdvancePaymentConsumption, AdvancePaymentStatus,
)
from app.services.rbac import (
    current_user_optional, is_admin, is_manager, can_view_finance,
)
from app.context import current_tenant_id


router = APIRouter(prefix="/finance/api/billing", tags=["billing"])



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


# v3.5.0-alpha.138 — Acconti Step 2: scomputo automatico nelle fatture batch.
# Parsing input formato CSV: "<advance_id>:<amount>,<advance_id>:<amount>"
# Esempio: "5:1000.0,7:500.5"
# Validazione: ogni amount ≤ balance_remaining, project_id match con invoice/batch project.
# Genera InvoiceLine negative (descrittive) + AdvancePaymentConsumption records.
# Riduce balance_remaining; status=consumed se balance=0.
def _parse_advance_consumptions_csv(csv: Optional[str]) -> list[tuple[int, float]]:
    """Parse "id:amt,id:amt" → [(id, amt), ...]. Vuoto → []. Solleva 400 su parse error."""
    if not csv or not csv.strip():
        return []
    out = []
    for token in csv.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise HTTPException(400, f"advance_consumptions formato invalido: '{token}' (atteso id:amt)")
        a_id_s, amt_s = token.split(":", 1)
        try:
            a_id = int(a_id_s.strip())
            amt = float(amt_s.strip())
        except ValueError:
            raise HTTPException(400, f"advance_consumptions parse error su '{token}'")
        if amt <= 0:
            raise HTTPException(400, f"advance_consumptions amount deve essere > 0 (advance #{a_id})")
        out.append((a_id, amt))
    return out


def _apply_advance_consumptions(
    db: Session, invoice: Invoice, project_id: int,
    consumptions: list[tuple[int, float]],
    billing_batch_id: Optional[int] = None,
    vat_rate: float = 22.0,
) -> dict:
    """Per ogni (advance_id, amount) valida + crea InvoiceLine negativa + AdvancePaymentConsumption
    + riduce balance. Ritorna {applied: [...], total_consumed: float}.

    Solleva 409 se: advance non open / amount > balance / project mismatch.
    Idempotente NON garantita: chiamare 1 volta per invoice."""
    if not consumptions:
        return {"applied": [], "total_consumed": 0.0}
    applied = []
    total_consumed = 0.0
    for a_id, amt in consumptions:
        ap = db.query(AdvancePayment).filter(
            AdvancePayment.id == a_id,
            AdvancePayment.tenant_id == current_tenant_id(),
        ).first()
        if not ap:
            raise HTTPException(404, f"Acconto #{a_id} non trovato")
        if ap.project_id != project_id:
            raise HTTPException(
                409,
                f"Acconto #{a_id} appartiene al progetto {ap.project_id}, non a {project_id}"
            )
        if ap.status != AdvancePaymentStatus.open:
            raise HTTPException(409, f"Acconto #{a_id} non è in stato 'open' (attuale: {ap.status.value})")
        if amt > (ap.balance_remaining or 0) + 0.001:
            raise HTTPException(
                409,
                f"Acconto #{a_id} residuo €{ap.balance_remaining:.2f} insufficiente per scomputo €{amt:.2f}"
            )
        # InvoiceLine negativa (total = -amt)
        adv_inv_num = ap.invoice.number if ap.invoice else f"#{a_id}"
        il = InvoiceLine(
            invoice_id=invoice.id,
            description=f"Scomputo acconto {adv_inv_num}",
            quantity=1.0,
            unit_price=-amt,
            total=-amt,
            vat_rate=vat_rate,
            discount_pct=0.0,
        )
        db.add(il)
        # Consumption ledger
        cons = AdvancePaymentConsumption(
            tenant_id=current_tenant_id(),
            advance_payment_id=ap.id,
            invoice_id=invoice.id,
            billing_batch_id=billing_batch_id,
            amount_consumed=amt,
        )
        db.add(cons)
        # Update balance + status
        ap.balance_remaining = round((ap.balance_remaining or 0) - amt, 2)
        if ap.balance_remaining <= 0.005:
            ap.balance_remaining = 0.0
            ap.status = AdvancePaymentStatus.consumed
        applied.append({"advance_payment_id": ap.id, "amount_consumed": amt,
                        "balance_remaining": ap.balance_remaining,
                        "status": ap.status.value})
        total_consumed += amt
    # Aggiusta totali Invoice (subtotal/total include scomputi negativi)
    invoice.subtotal = round((invoice.subtotal or 0) - total_consumed, 2)
    invoice.total = round((invoice.total or 0) - total_consumed * (1 + (invoice.vat_rate or vat_rate) / 100), 2)
    return {"applied": applied, "total_consumed": total_consumed}


def _next_batch_code(db: Session, project=None) -> str:
    """v3.5.0-alpha.66.14.8 — Wrapper sul numbering service unificato.
    v3.5.0-alpha.115 — Cabling NumberingConfig "billing_batch".
    Variabili supportate: YYYY/YY/MM/DD/NNN/NN/NNNN/PROJECT_CODE/CLIENT_CODE.
    Fallback default BB-{YYYY}-{NNN}.
    """
    from app.services.numbering import gen_doc_code, next_year_progressive
    client = (project.client if project and getattr(project, "client", None) else None)
    try:
        code, _ = gen_doc_code(
            db, "billing_batch",
            tenant_id=current_tenant_id(),
            project_code=(project.code if project else None),
            client_code=(client.name[:8].upper() if client and getattr(client, "name", None) else None),
        )
        # Verifica uniqueness vs DB
        exists = (
            db.query(BillingBatch).execution_options(include_deleted=True)
            .filter(BillingBatch.code == code,
                    BillingBatch.tenant_id == current_tenant_id()).first()
        )
        if exists:
            return next_year_progressive(
                db, BillingBatch, base="BB", code_field="code",
                include_deleted=True,
                extra_filter=(BillingBatch.tenant_id == current_tenant_id()),
            )
        return code
    except Exception as _e:
        print(f"[batch_numbering] gen_doc_code failed, fallback: {_e}")
        return next_year_progressive(
            db, BillingBatch, base="BB", code_field="code",
            include_deleted=True,
            extra_filter=(BillingBatch.tenant_id == current_tenant_id()),
        )


def _batch_to_dict(b: BillingBatch, with_lines: bool = False) -> dict:
    # v3.5.0-alpha.90 — Esponi client_id/client_name nella lista batch
    # (richiesta Matteo: voglio vedere il cliente anche qui).
    _client = (b.project.client if (b.project and getattr(b.project, "client", None)) else None)
    out = {
        "id": b.id,
        "code": b.code,
        "project_id": b.project_id,
        "project_title": b.project.title if b.project else None,
        "project_code": b.project.code if b.project else None,
        "client_id": _client.id if _client else None,
        "client_name": _client.name if _client else None,
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
        # v3.5.0-alpha.111 — date emissione + status fattura nella row batch.
        "invoice_issue_date": (
            b.invoice.issue_date.isoformat() if (b.invoice and b.invoice.issue_date) else None
        ),
        "invoice_status": (
            b.invoice.status.value if (b.invoice and hasattr(b.invoice.status, "value"))
            else (b.invoice.status if b.invoice else None)
        ),
        "invoice_doc_type": (getattr(b.invoice, "doc_type", None) if b.invoice else None),
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
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not proj:
        raise HTTPException(404, f"Progetto #{project_id} non trovato")

    # v3.5.0-alpha.168 — Allargato a billed/paid: la PORZIONE over (accrued >
    # already_filled) di JCL "chiuse" è trasmissibile come supplemento.
    q = db.query(JobCostLine).join(Job).options(joinedload(JobCostLine.job)).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status.in_([
            JCLBillingStatus.not_billed,
            JCLBillingStatus.billed,
            JCLBillingStatus.paid,
        ]),
        JobCostLine.total_accrued > 0,
        JobCostLine.is_billable == True,
    )
    if not include_extras:
        q = q.filter(JobCostLine.is_extra == False)
    raw_candidates = q.all()

    # v3.5.0-alpha.168 — Calcolo already_filled per filtro saturati.
    from app.services.billing_slice_guard import billed_locked_bulk
    raw_ids = [c.id for c in raw_candidates]
    billed_locked_map = billed_locked_bulk(db, raw_ids) if raw_ids else {}
    advance_paid_map: dict[int, float] = {}
    if raw_ids:
        from app.models import AdvancePaymentAllocation as _APA
        ap_rows = (
            db.query(
                _APA.job_cost_line_id, _APA.amount,
                Invoice.amount_paid, Invoice.total.label("inv_total"),
            )
            .join(AdvancePayment, AdvancePayment.id == _APA.advance_payment_id)
            .outerjoin(Invoice, Invoice.id == AdvancePayment.invoice_id)
            .filter(
                _APA.job_cost_line_id.in_(raw_ids),
                AdvancePayment.status != AdvancePaymentStatus.cancelled,
                AdvancePayment.tenant_id == current_tenant_id(),
            )
            .all()
        )
        for jcl_id_, alloc_amt_, paid_amt_, inv_total_ in ap_rows:
            if not inv_total_ or inv_total_ <= 0:
                continue
            ratio = min(1.0, (paid_amt_ or 0) / inv_total_)
            advance_paid_map[jcl_id_] = advance_paid_map.get(jcl_id_, 0.0) + (alloc_amt_ or 0) * ratio

    candidates = []
    saturated_count = 0
    billable_now_by_jcl: dict[int, float] = {}
    for c in raw_candidates:
        already = (billed_locked_map.get(c.id, 0.0) or 0.0) + (advance_paid_map.get(c.id, 0.0) or 0.0)
        billable_now = round((c.total_accrued or 0.0) - already, 2)
        if billable_now <= 0.005:
            saturated_count += 1
            continue
        candidates.append(c)
        billable_now_by_jcl[c.id] = billable_now

    # v3.5.0-alpha.112 — conteggio esclusioni per UX (chiarezza stato)
    excl_in_batch = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        JobCostLine.billing_status == JCLBillingStatus.in_batch,
    ).count()
    excl_billed = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        JobCostLine.billing_status.in_([
            JCLBillingStatus.billed, JCLBillingStatus.paid
        ]),
    ).count()

    period_start, period_end, period_source = _period_from_bookings(
        db, [c.id for c in candidates]
    )

    # v3.5.0-alpha.56: breakdown esplicito quote vs extra + sforamento.
    # Sforamento = max(0, total_accrued - total_quoted) sulle righe NON extra
    # (le extra sono già "fuori budget" per definizione).
    # v3.5.0-alpha.168: totali usano billable_now (residuo da fatturare) invece
    # di accrued totale → coerenti con il batch creato post-trasmissione.
    quote_lines = [c for c in candidates if not c.is_extra]
    extra_lines = [c for c in candidates if c.is_extra]
    quote_total = round(sum(billable_now_by_jcl.get(c.id, 0.0) for c in quote_lines), 2)
    extra_total = round(sum(billable_now_by_jcl.get(c.id, 0.0) for c in extra_lines), 2)
    overrun_total = round(sum(
        max(0.0, (c.total_accrued or 0) - (c.total_quoted or 0))
        for c in quote_lines
    ), 2)
    total_proposed = round(sum(billable_now_by_jcl.get(c.id, 0.0) for c in candidates), 2)
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
        # v3.5.0-alpha.112 — esclusioni esplicite per UX
        "excluded_in_batch": excl_in_batch,
        "excluded_billed": excl_billed,
        "lines": [
            {
                "id": c.id,
                "description": c.description,
                "quantity": c.quantity_actual,
                "unit": c.unit,
                "unit_price": c.unit_price,
                "total_quoted": c.total_quoted,
                "total_accrued": c.total_accrued,
                # v3.5.0-alpha.168 — billable_now = residuo disponibile per
                # questo batch (accrued − slice precedenti − acconto pagato).
                # UI usa questo come "Maturato" mostrato e subtotale.
                "billable_now": round(billable_now_by_jcl.get(c.id, c.total_accrued or 0.0), 2),
                "already_filled": round(
                    (billed_locked_map.get(c.id, 0.0) or 0.0)
                    + (advance_paid_map.get(c.id, 0.0) or 0.0), 2
                ),
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
        # v3.5.0-alpha.168 — n. JCL escluse per saturazione (riempite da slice
        # + acconto pagato, residuo = 0). UI può mostrare info chip.
        "saturated_excluded": saturated_count,
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
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not proj:
        raise ValueError(f"Progetto #{project_id} non trovato")

    # v3.5.0-alpha.168 — Gate "vasi comunicanti" Bug 2+4 (semantica Matteo).
    # Fatturazione blocca CR salvo superamento quotato. JCL candidate solo se
    # billable_now = accrued − already_filled > 0, dove already_filled include
    # slice immutabili + acconto pagato (advance_paid_coverage).
    # Estende anche stati `billed`/`paid` per consentire trasmissione della
    # PORZIONE OVER quando la JCL è "chiusa" ma matura ancora oltre quoted.
    q = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status.in_([
            JCLBillingStatus.not_billed,
            JCLBillingStatus.billed,
            JCLBillingStatus.paid,
        ]),
        JobCostLine.total_accrued > 0,
        JobCostLine.is_billable == True,
    )
    if not include_extras:
        q = q.filter(JobCostLine.is_extra == False)
    raw_candidates = q.all()

    # v3.5.0-alpha.64: filtro per selezione esplicita
    if jcl_ids is not None:
        ids_set = set(jcl_ids)
        raw_candidates = [c for c in raw_candidates if c.id in ids_set]
        if not raw_candidates:
            raise ValueError(
                "Nessuna delle JCL selezionate è candidata valida "
                "(non in stato fatturabile con maturato > 0)."
            )

    # v3.5.0-alpha.168 — Calcolo already_filled per ogni candidate:
    #   already_filled = Σ JCLBilledSlice.billed_amount + Σ advance_paid_coverage
    # Slice via billed_locked_bulk. Advance coverage via APA × ratio paid/total.
    from app.services.billing_slice_guard import billed_locked_bulk
    cand_ids = [c.id for c in raw_candidates]
    billed_locked_map = billed_locked_bulk(db, cand_ids) if cand_ids else {}
    advance_paid_map: dict[int, float] = {}
    if cand_ids:
        from app.models import AdvancePaymentAllocation
        ap_rows = (
            db.query(
                AdvancePaymentAllocation.job_cost_line_id,
                AdvancePaymentAllocation.amount,
                Invoice.amount_paid,
                Invoice.total.label("inv_total"),
            )
            .join(AdvancePayment, AdvancePayment.id == AdvancePaymentAllocation.advance_payment_id)
            .outerjoin(Invoice, Invoice.id == AdvancePayment.invoice_id)
            .filter(
                AdvancePaymentAllocation.job_cost_line_id.in_(cand_ids),
                AdvancePayment.status != AdvancePaymentStatus.cancelled,
                AdvancePayment.tenant_id == current_tenant_id(),
            )
            .all()
        )
        for jcl_id_, alloc_amt_, paid_amt_, inv_total_ in ap_rows:
            if not inv_total_ or inv_total_ <= 0:
                continue
            ratio = min(1.0, (paid_amt_ or 0) / inv_total_)
            advance_paid_map[jcl_id_] = advance_paid_map.get(jcl_id_, 0.0) + (alloc_amt_ or 0) * ratio

    # Filtra a JCL con billable_now > 0 (residuo da fatturare).
    # Calcola billable_now per ciascuna e tieni la mappa per la creazione lines.
    candidates = []
    billable_now_map: dict[int, float] = {}
    saturated_count = 0
    for c in raw_candidates:
        already = (billed_locked_map.get(c.id, 0.0) or 0.0) + (advance_paid_map.get(c.id, 0.0) or 0.0)
        billable_now = round((c.total_accrued or 0.0) - already, 2)
        if billable_now <= 0.005:
            saturated_count += 1
            continue
        candidates.append(c)
        billable_now_map[c.id] = billable_now

    if not candidates:
        if jcl_ids is not None:
            raise ValueError(
                f"JCL selezionate già saturate (fatturate o coperte da acconto pagato). "
                f"{saturated_count} riga/e senza residuo da fatturare."
            )
        raise ValueError(
            f"Nessuna JCL trasmissibile: tutte saturate da fatturazione precedente "
            f"o coperte da acconto pagato ({saturated_count} riga/e). Solo over-quote "
            f"trasmissibile (extras o supero quotato non ancora trasmesso)."
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

    # v3.5.0-alpha.115 — passa project per espandere {PROJECT_CODE}/{CLIENT_CODE}
    _proj = db.query(Project).filter(Project.id == project_id).first()
    batch = BillingBatch(
        tenant_id=current_tenant_id(),
        code=_next_batch_code(db, project=_proj),
        project_id=project_id,
        status=BillingBatchStatus.draft,
        period_start=period_start,
        period_end=period_end,
        notes=notes,
        transmitted_by_user_id=user_id,
        transmitted_at=now_utc(),
    )
    db.add(batch)
    db.flush()

    for jcl in candidates:
        # v3.5.0-alpha.168 — Default total_approved = billable_now (vasi
        # comunicanti). billable_now = accrued − already_filled (slice precedenti
        # + acconto pagato). Pre-α.168 propose era `quoted` per UNDER (inflato
        # rispetto al maturato reale) o `accrued` totale (ignorava slice già
        # fatturate → doppia fatturazione). Ora il default è ESATTAMENTE quello
        # che serve trasmettere ora, l'admin può ridurre come sconto/loss.
        _accrued = jcl.total_accrued or 0.0
        _billable_now = billable_now_map.get(jcl.id, _accrued)
        # total_proposed riflette il "maturato disponibile per questo batch"
        # (≠ maturato totale: già toglie slice precedenti + acconto pagato).
        line = BillingBatchLine(
            batch_id=batch.id,
            job_cost_line_id=jcl.id,
            description=jcl.description,
            quantity=jcl.quantity_actual,
            unit=jcl.unit,
            unit_price=jcl.unit_price,
            total_proposed=_billable_now,
            total_approved=_billable_now,
            is_extra=jcl.is_extra,
        )
        db.add(line)
        # v3.5.0-alpha.168 — Solo not_billed → in_batch. Stati billed/paid
        # restano: il batch raccoglie la PORZIONE over, non chiude la JCL.
        if jcl.billing_status == JCLBillingStatus.not_billed:
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
    client_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Lista BillingBatch con filtri opzionali. Default: tutti del tenant
    in ordine cronologico decrescente di trasmissione.

    v3.5.0-alpha.86 (S3.1) — Filtri estesi: client_id + period.
    client_id richiede join con Project (Project.client_id)."""
    _require_finance(request)
    q = db.query(BillingBatch).options(
        joinedload(BillingBatch.project).joinedload(Project.client),  # α.90: eager client
        joinedload(BillingBatch.invoice),
    ).filter(BillingBatch.tenant_id == current_tenant_id())
    if project_id:
        q = q.filter(BillingBatch.project_id == project_id)
    if client_id:
        from app.models import Project as _Project
        q = q.join(_Project, BillingBatch.project_id == _Project.id).filter(_Project.client_id == client_id)
    if from_date:
        q = q.filter(BillingBatch.period_end >= from_date)
    if to_date:
        q = q.filter(BillingBatch.period_start <= to_date)
    if status:
        try:
            q = q.filter(BillingBatch.status == BillingBatchStatus(status))
        except ValueError:
            raise HTTPException(400, f"Status non valido: {status}")
    batches = q.order_by(BillingBatch.transmitted_at.desc()).all()
    return [_batch_to_dict(b, with_lines=False) for b in batches]


@router.get("/composable-batches")
async def list_composable_batches(
    request: Request,
    project_id: int,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.90 — Lista batch approved "in cassetto" per un progetto.
    Anteprima per UI `Componi fattura periodo`: mostra all'utente cosa verrà
    aggregato prima di confermare. Senza periodo: tutti gli approved.

    `billing_frequency` del project viene esposto come hint per il default
    periodo (es. monthly = primo-ultimo del mese corrente).

    v3.5.0-alpha.92 fix: spostata sopra `/{batch_id}` perché altrimenti il
    segmento "composable-batches" veniva matchato dalla route parametrica
    e Pydantic tornava 422 (int_parsing). FastAPI matcha le route in ordine
    di registrazione; le route specifiche vanno prima delle catch-all.
    """
    _require_finance(request)
    project = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not project:
        raise HTTPException(404, "Progetto non trovato")
    q = db.query(BillingBatch).options(
        joinedload(BillingBatch.project).joinedload(Project.client),
    ).filter(
        BillingBatch.tenant_id == current_tenant_id(),
        BillingBatch.project_id == project_id,
        BillingBatch.status == BillingBatchStatus.approved,
        BillingBatch.invoice_id.is_(None),
    )
    if period_start:
        q = q.filter(BillingBatch.period_end >= period_start)
    if period_end:
        q = q.filter(BillingBatch.period_start <= period_end)
    batches = q.order_by(BillingBatch.period_start.asc()).all()
    return {
        "project_id": project_id,
        "project_code": project.code,
        "project_title": project.title,
        "billing_frequency": getattr(project, "billing_frequency", "monthly"),
        "client_name": project.client.name if project.client else None,
        "batches": [_batch_to_dict(b, with_lines=False) for b in batches],
        "total_approved_sum": round(sum(b.total_approved or 0 for b in batches), 2),
    }


@router.get("/{batch_id}")
async def get_batch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Dettaglio batch con tutte le lines snapshot."""
    _require_finance(request)
    batch = db.query(BillingBatch).options(
        joinedload(BillingBatch.project).joinedload(Project.client),  # α.90: eager client
        joinedload(BillingBatch.invoice),
        joinedload(BillingBatch.lines),
    ).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
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
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
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
            tenant_id=current_tenant_id(),
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
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
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
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
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
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    if batch.status != BillingBatchStatus.draft:
        raise HTTPException(400, f"Batch non può essere approvato dallo stato {batch.status.value}")
    if not batch.lines:
        raise HTTPException(400, "Batch senza linee, niente da approvare")
    batch.status = BillingBatchStatus.approved
    batch.approved_by_user_id = user.id if user else None
    batch.approved_at = now_utc()
    db.commit()
    db.refresh(batch)
    return _batch_to_dict(batch, with_lines=True)


@router.post("/{batch_id}/invoice")
async def emit_invoice(
    batch_id: int,
    request: Request,
    invoice_number: Optional[str] = Form(None),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    vat_rate: float = Form(22.0),
    # v3.5.0-alpha.138 — Scomputo acconti (Step 2). Formato "id:amt,id:amt".
    advance_consumptions: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Emette una Invoice da un batch approved. Crea Invoice + InvoiceLine
    (1 per BillingBatchLine), collega `invoice_id` al batch, marca le JCL
    coinvolte → billed con `billed_amount` = total_approved della line.

    Manager+ richiesto.

    v3.5.0-alpha.168 — `invoice_number` ora opzionale: se omesso/vuoto,
    auto-generato via _next_invoice_number (naming {anno}-{NNNNN}). Override
    manuale conservato per coerenza con gestionale fiscale esterno."""
    _require_manager(request)
    batch = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
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
    # v3.5.0-alpha.168 — Auto numero se non fornito (Bug 3).
    from app.routers.finance import _next_invoice_number
    num = (invoice_number or "").strip()
    if num:
        existing = db.query(Invoice).join(Client, Invoice.client_id == Client.id).filter(
            Invoice.number == num,
            Client.tenant_id == current_tenant_id(),
        ).first()
        if existing:
            raise HTTPException(409, f"Numero fattura {num} già esistente")
    else:
        num = _next_invoice_number(db, issue_date.year)
    invoice_number = num
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
    tenant_obj = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()

    # v3.5.0-alpha.172.41 (Sprint 6.A BLOCCO 6 parte 2) — pre-emit SDI
    # compliance HARD-BLOCK. Verifica P.IVA/CF/SDI/regime/natura prima di
    # creare Invoice (no rollback per integrity error tardivo).
    from app.services.italian_tax import invoice_sdi_compliance_check
    sdi_errs = invoice_sdi_compliance_check(
        client_vat=(client_obj.vat_number if client_obj else None),
        client_tax_code=(client_obj.tax_code if client_obj else None),
        client_sdi=(client_obj.sdi_code if client_obj else None),
        client_pec=(client_obj.pec if client_obj else None),
        client_country=(client_obj.country if client_obj else None),
        tenant_vat=(tenant_obj.vat_number if tenant_obj else None),
        tenant_fiscal_regime=(tenant_obj.fiscal_regime if tenant_obj else None),
        vat_rate=vat_rate,
        natura=None,
        # v3.5.0-alpha.172.60 — anagrafica sede + ragione sociale
        client_address=(client_obj.address if client_obj else None),
        client_zip=(client_obj.zip_code if client_obj else None),
        client_city=(client_obj.city if client_obj else None),
        client_province=(client_obj.province if client_obj else None),
        tenant_street=(getattr(tenant_obj, "street_address", None) if tenant_obj else None),
        tenant_zip=(getattr(tenant_obj, "zip_code", None) if tenant_obj else None),
        tenant_city=(getattr(tenant_obj, "city", None) if tenant_obj else None),
        tenant_province=(getattr(tenant_obj, "province", None) if tenant_obj else None),
        tenant_legal_name=(tenant_obj.legal_name or tenant_obj.name if tenant_obj else None),
    )
    if sdi_errs:
        raise HTTPException(422, detail={
            "message": "Fattura non emissibile: campi fiscali mancanti o invalidi",
            "errors": sdi_errs,
            "hint": "Completa P.IVA cliente, codice SDI o PEC, regime fiscale tenant",
        })

    invoice = Invoice(
        # v3.5.0-alpha.172.37 (Sprint 3.E) — denormalizzato tenant_id
        tenant_id=current_tenant_id(),
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
        client_admin_email_snap=(getattr(client_obj, "admin_email", None) if client_obj else None),
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
        # v3.5.0-alpha.172 (currency Task 9) — fattura da batch project-level:
        # valuta ambigua (più quote/job). Default valuta base.
        currency=((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper(),
    )
    # v3.5.0-alpha.172 (currency Task 9) — congela tasso BCE data emissione.
    from app.services.currency import freeze_invoice_fx
    freeze_invoice_fx(db, invoice, ((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper())
    db.add(invoice)
    db.flush()

    # Linee fattura snapshot da batch lines
    # v3.5.0-alpha.111 — periodo validità lavorazione nella descrizione riga.
    period_lbl = ""
    if batch.period_start and batch.period_end:
        period_lbl = f" [{batch.period_start.isoformat()} → {batch.period_end.isoformat()}]"
    for bl in batch.lines:
        if bl.total_approved <= 0:
            continue  # skip lines azzerate (loss totale)
        # v3.5.0-alpha.169 — Quantity in fattura = total_approved / unit_price
        # (era bl.quantity = quantity_actual totale, gonfio per JCL parzialmente
        # fatturate o con total_approved < quoted). Garantisce qty × prezzo =
        # total (coerenza interna) e mostra solo la quota effettivamente
        # fatturata in questa specifica fattura (Matteo Bug 4).
        if bl.unit_price and bl.unit_price > 0:
            inv_qty = round(bl.total_approved / bl.unit_price, 4)
        else:
            inv_qty = bl.quantity  # fallback se unit_price=0 (improbabile)
        il = InvoiceLine(
            invoice_id=invoice.id,
            description=bl.description + period_lbl + (" [extra]" if bl.is_extra else ""),
            quantity=inv_qty,
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
            tenant_id=current_tenant_id(),
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
    # v3.5.0-alpha.138 — Acconti Step 2: scomputo opzionale.
    # Applica DOPO aver creato tutte le invoice line normali (per consistenza
    # del subtotal/total prima di sottrarre gli scomputi).
    consumptions_in = _parse_advance_consumptions_csv(advance_consumptions)
    consumed_result = _apply_advance_consumptions(
        db, invoice, batch.project_id, consumptions_in,
        billing_batch_id=batch.id, vat_rate=vat_rate,
    )
    # v3.5.0-alpha.138 — link diretto Invoice→Project (foundation cost report)
    invoice.project_id = batch.project_id
    # v3.5.0-alpha.172.37 (Sprint 3.D BLOCCO 4) — IVA per-riga: ricomputa
    # subtotal/total da Σ InvoiceLine invece di subtotal*vat_rate aggregato.
    # In flusso single-rate i due valori coincidono; in multi-rate (futuro UI
    # con vat_rate per riga, requisito FatturaPA <DatiRiepilogo>) corregge il
    # rounding. Audit BLOCCO 4.
    from app.services.invoice_totals import (
        compute_invoice_totals_from_lines, apply_totals_to_invoice,
    )
    db.flush()  # rende visibile invoice.lines aggiornato
    apply_totals_to_invoice(invoice, compute_invoice_totals_from_lines(invoice.lines))
    db.commit()
    db.refresh(batch)
    # v3.5.0-alpha.169 — Auto-detect anomalie dopo emit (Bug 3b): se manager ha
    # forzato total_approved > total_quoted, scatta sforamento_monte_ore;
    # se JCL extra fatturata senza quantity, scatta over_budget.
    try:
        from app.services.anomaly_detector import detect_all
        detect_all(db)
        db.commit()
    except Exception:
        db.rollback()  # non blocking
    return {
        "batch": _batch_to_dict(batch, with_lines=True),
        "invoice_id": invoice.id,
        "invoice_number": invoice.number,
        "subtotal": invoice.subtotal,  # post-scomputo
        "vat_amount": invoice.total - invoice.subtotal,
        "total": invoice.total,
        "advance_consumptions": consumed_result,
    }


@router.post("/compose-invoice")
async def compose_invoice_from_batches(
    request: Request,
    project_id: int = Form(...),
    invoice_number: Optional[str] = Form(None),
    issue_date: date = Form(...),
    period_start: Optional[date] = Form(None),
    period_end: Optional[date] = Form(None),
    due_date: Optional[date] = Form(None),
    vat_rate: float = Form(22.0),
    batch_ids: Optional[str] = Form(None),  # CSV opzionale: se vuoto, prende tutti gli approved
    notes: Optional[str] = Form(None),
    # v3.5.0-alpha.138 — Scomputo acconti (Step 2). Formato "id:amt,id:amt".
    advance_consumptions: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.90 — Accrual billing: aggrega N BillingBatch approved
    del progetto nel periodo → 1 Invoice unica (richiesta Matteo 13 mag).

    Pre-α.90 era 1 batch = 1 fattura. Ora i batch trasmessi+approvati
    restano "in cassetto" finché l'amministrazione compone la fattura
    aggregata (mensile/trimestrale/custom secondo Project.billing_frequency).

    Algoritmo:
    1. Trova BillingBatch del project con status=approved + period nel range
       (o batch_ids esplicito) + invoice_id IS NULL
    2. Crea Invoice unica con cliente del project, subtotal = Σ batch.total_approved
    3. Per ogni batch line con total_approved>0 → InvoiceLine + JCLBilledSlice
    4. Linka tutti i batch a Invoice + status=invoiced
    5. Marca JCL come billed/lost come emit_invoice singolo
    """
    _require_manager(request)
    # v3.5.0-alpha.168 — Auto numero se non fornito (Bug 3).
    from app.routers.finance import _next_invoice_number
    num = (invoice_number or "").strip()
    if num:
        existing = db.query(Invoice).join(Client, Invoice.client_id == Client.id).filter(
            Invoice.number == num,
            Client.tenant_id == current_tenant_id(),
        ).first()
        if existing:
            raise HTTPException(409, f"Numero fattura {num} già esistente")
    else:
        num = _next_invoice_number(db, issue_date.year)
    invoice_number = num
    project = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not project or not project.client_id:
        raise HTTPException(400, "Progetto senza cliente, impossibile fatturare")

    # Trova batch da aggregare
    q = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.tenant_id == current_tenant_id(),
        BillingBatch.project_id == project_id,
        BillingBatch.status == BillingBatchStatus.approved,
        BillingBatch.invoice_id.is_(None),
    )
    if batch_ids:
        try:
            ids = [int(x.strip()) for x in batch_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "batch_ids deve essere CSV di interi")
        q = q.filter(BillingBatch.id.in_(ids))
    else:
        # v3.5.0-alpha.111 — Periodo OPZIONALE + OVERLAP invece di containment.
        # Modalità "tutti i batch aperti del progetto" → period_*=None.
        # Modalità "per periodo" → mantieni batch il cui intervallo si sovrappone.
        if period_start:
            q = q.filter(BillingBatch.period_end >= period_start)
        if period_end:
            q = q.filter(BillingBatch.period_start <= period_end)
    batches = q.order_by(BillingBatch.period_start.asc()).all()
    if not batches:
        raise HTTPException(404, "Nessun batch approvato in cassetto per i criteri forniti")

    # Subtotal cumulativo
    subtotal = sum(b.total_approved or 0 for b in batches)
    if subtotal <= 0:
        raise HTTPException(400, "Subtotal aggregato ≤ 0: niente da fatturare")
    vat_amount = subtotal * vat_rate / 100
    total = subtotal + vat_amount

    # v3.5.0-alpha.111 — auto due_date da Project.billing_terms_days se omessa
    if due_date is None and getattr(project, "billing_terms_days", None):
        from datetime import timedelta
        due_date = issue_date + timedelta(days=int(project.billing_terms_days))

    # Snapshot fiscali
    client_obj = db.query(Client).filter(Client.id == project.client_id).first()
    tenant_obj = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()

    batch_codes = ", ".join(b.code for b in batches)
    invoice = Invoice(
        # v3.5.0-alpha.172.37 (Sprint 3.E)
        tenant_id=current_tenant_id(),
        number=invoice_number,
        client_id=project.client_id,
        status=InvoiceStatus.draft,
        issue_date=issue_date,
        due_date=due_date,
        subtotal=subtotal,
        vat_rate=vat_rate,
        total=total,
        notes=(notes or "") + f"\nGenerata aggregando {len(batches)} batch ({batch_codes})",
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
        tenant_rea_snap=(tenant_obj.rea_number if tenant_obj else None),
        tenant_fiscal_capital_snap=(tenant_obj.fiscal_capital if tenant_obj else None),
        tenant_fiscal_regime_snap=(tenant_obj.fiscal_regime if tenant_obj else None),
        # v3.5.0-alpha.172 (currency Task 9) — fattura aggregata multi-batch
        # project-level: valuta ambigua. Default valuta base.
        currency=((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper(),
    )
    # v3.5.0-alpha.172 (currency Task 9) — congela tasso BCE data emissione.
    from app.services.currency import freeze_invoice_fx
    freeze_invoice_fx(db, invoice, ((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper())
    db.add(invoice)
    db.flush()

    invoice_lines_count = 0
    for batch in batches:
        for bl in batch.lines:
            if bl.total_approved <= 0:
                # Marca JCL azzerate come lost (manager le ha scartate)
                jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
                if jcl and (bl.total_approved or 0) <= 0.001:
                    jcl.billing_status = JCLBillingStatus.lost
                    jcl.billed_amount = 0
                continue
            # v3.5.0-alpha.111 — descrizione include periodo validità lavorazione
            # (richiesto Matteo: "In fattura vengono riportati i periodi di
            # validità delle lavorazioni").
            period_lbl = ""
            if batch.period_start and batch.period_end:
                period_lbl = f" [{batch.period_start.isoformat()} → {batch.period_end.isoformat()}]"
            # v3.5.0-alpha.169 — quantity recomputed da total_approved (Bug 4)
            if bl.unit_price and bl.unit_price > 0:
                inv_qty = round(bl.total_approved / bl.unit_price, 4)
            else:
                inv_qty = bl.quantity
            il = InvoiceLine(
                invoice_id=invoice.id,
                description=f"[{batch.code}]{period_lbl} " + bl.description + (" [extra]" if bl.is_extra else ""),
                quantity=inv_qty,
                unit_price=bl.unit_price,
                total=bl.total_approved,
                vat_rate=vat_rate,
                discount_pct=0.0,
            )
            db.add(il)
            invoice_lines_count += 1
            # Marca JCL → billed
            # v3.5.0-alpha.91 audit fix P1: overwrite invece di accumulo
            # (asimmetria con emit_invoice singolo). Lo storico cumulativo
            # vive nelle JCLBilledSlice; jcl.billed_amount è snapshot ultimo.
            jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
            if jcl:
                jcl.billing_status = JCLBillingStatus.billed
                jcl.billed_amount = bl.total_approved
            # JCLBilledSlice immutabile per la porzione fatturata
            slice_ = JCLBilledSlice(
                tenant_id=current_tenant_id(),
                job_cost_line_id=bl.job_cost_line_id,
                billing_batch_line_id=bl.id,
                invoice_id=invoice.id,
                period_start=batch.period_start,
                period_end=batch.period_end,
                billed_quantity=inv_qty or 0.0,
                billed_amount=bl.total_approved,
                unit_price_snap=bl.unit_price or 0.0,
            )
            db.add(slice_)
        # Linka batch → invoice
        batch.status = BillingBatchStatus.invoiced
        batch.invoice_id = invoice.id
    # v3.5.0-alpha.138 — Scomputo acconti progetto (Step 2)
    consumptions_in = _parse_advance_consumptions_csv(advance_consumptions)
    consumed_result = _apply_advance_consumptions(
        db, invoice, project_id, consumptions_in,
        billing_batch_id=None, vat_rate=vat_rate,
    )
    # v3.5.0-alpha.138 — link diretto Invoice→Project
    invoice.project_id = project_id
    # v3.5.0-alpha.172.37 (Sprint 3.D BLOCCO 4) — IVA per-riga: ricomputa
    # totals da Σ InvoiceLine (stesso pattern di emit_invoice).
    from app.services.invoice_totals import (
        compute_invoice_totals_from_lines, apply_totals_to_invoice,
    )
    db.flush()
    apply_totals_to_invoice(invoice, compute_invoice_totals_from_lines(invoice.lines))
    # v3.5.0-alpha.91 audit fix P1: gestisce race condition su Invoice.number
    # unique. Pre-fix: 500 IntegrityError grezzo. Ora: 409 dedicato.
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        from sqlalchemy.exc import IntegrityError
        if isinstance(e, IntegrityError) and "UNIQUE" in str(e).upper():
            raise HTTPException(409, f"Numero fattura {invoice_number} già esistente (race condition)")
        raise HTTPException(500, f"Errore compose: {e}")
    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.number,
        "subtotal": round(invoice.subtotal, 2),  # post-scomputo
        "vat_amount": round(invoice.total - invoice.subtotal, 2),
        "total": round(invoice.total, 2),
        "batches_aggregated": len(batches),
        "batch_codes": [b.code for b in batches],
        "invoice_lines_count": invoice_lines_count,
        "advance_consumptions": consumed_result,
    }


# ── v3.5.0-alpha.112 — Fattura di chiusura progetto ────────────────────
@router.get("/closing-precheck/{project_id}")
async def closing_invoice_precheck(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Verifica se il progetto può essere chiuso finanziariamente.

    Condizione: tutte le JobCostLine del progetto devono avere
    billing_status in (billed, paid, lost). Voci ancora in `not_billed`
    o `in_batch` bloccano la chiusura.
    Ritorna l'elenco fatture emesse per il riepilogo.
    """
    _require_finance(request)
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not proj:
        raise HTTPException(404, "Progetto non trovato")
    if proj.finance_status == "closed":
        raise HTTPException(409, "Progetto già finanziariamente chiuso")
    # JCL non-pronte = blocco
    pending = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status.in_([
            JCLBillingStatus.not_billed,
            JCLBillingStatus.in_batch,
        ]),
        JobCostLine.is_billable == True,
        JobCostLine.total_accrued > 0,
    ).all()
    # v3.5.0-alpha.114 A16: JCL not_billed con total_accrued=0 ma total_quoted>0
    # (= preventivato ma mai eseguito). Non bloccano, ma vanno mostrate per
    # double-check pre-chiusura: forse vanno lost esplicito, forse vanno revise.
    zero_accrued = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status == JCLBillingStatus.not_billed,
        JobCostLine.is_billable == True,
        (JobCostLine.total_accrued == 0) | (JobCostLine.total_accrued.is_(None)),
        JobCostLine.total_quoted > 0,
    ).all()
    # Riepilogo fatture progetto
    invoices = db.query(Invoice).join(Job, Invoice.job_id == Job.id).filter(
        Job.project_id == project_id,
    ).order_by(Invoice.issue_date.asc()).all()
    inv_summary = [
        {
            "id": i.id, "number": i.number,
            "issue_date": i.issue_date.isoformat() if i.issue_date else None,
            "subtotal": i.subtotal, "total": i.total,
            "status": i.status.value if hasattr(i.status, "value") else i.status,
            "amount_paid": i.amount_paid or 0,
            "is_closing": bool(getattr(i, "is_closing", False)),
            "doc_type": i.doc_type,
        }
        for i in invoices
    ]
    total_billed = round(sum((i["total"] or 0) for i in inv_summary if i["doc_type"] != "TD04"), 2)
    total_paid = round(sum((i["amount_paid"] or 0) for i in inv_summary if i["doc_type"] != "TD04"), 2)
    # v3.5.0-alpha.114 A16: confronto quotato vs maturato per JCL zero-accrued.
    # Mostra dettaglio per double-check pre-emissione closing.
    zero_accrued_total_quoted = round(sum((j.total_quoted or 0) for j in zero_accrued), 2)
    return {
        "project_id": project_id,
        "project_code": proj.code,
        "project_title": proj.title,
        "can_close": len(pending) == 0,
        "pending_lines_count": len(pending),
        "pending_sample": [
            {"id": p.id, "description": p.description,
             "status": p.billing_status.value if hasattr(p.billing_status, "value") else p.billing_status,
             "total_accrued": p.total_accrued}
            for p in pending[:10]
        ],
        # v3.5.0-alpha.114 A16: zero-accrued JCL (quotate ma non eseguite)
        "zero_accrued_count": len(zero_accrued),
        "zero_accrued_total_quoted": zero_accrued_total_quoted,
        "zero_accrued_sample": [
            {"id": z.id, "description": z.description,
             "total_quoted": z.total_quoted, "total_accrued": z.total_accrued or 0,
             "is_extra": z.is_extra}
            for z in zero_accrued[:20]
        ],
        "invoices": inv_summary,
        "invoices_count": len(inv_summary),
        "total_billed": total_billed,
        "total_paid": total_paid,
        "residual_to_pay": round(total_billed - total_paid, 2),
    }


@router.post("/closing-invoice/{project_id}")
async def emit_closing_invoice(
    project_id: int,
    request: Request,
    invoice_number: Optional[str] = Form(None),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    vat_rate: float = Form(22.0),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Emette la fattura di chiusura progetto.

    - Aggrega tutti i batch ancora aperti (approved, invoice_id IS NULL) del
      progetto come ultima fattura "reale" (NON €0).
    - Marca Project.finance_status='closed' + finance_closed_at + link a
      questa invoice (finance_closing_invoice_id).
    - Invoice.is_closing=True per il PDF (sezione riepilogo).
    """
    _require_manager(request)
    # v3.5.0-alpha.114 A7: row-lock per prevenire double-close race.
    # SQLite WAL serializza i writer; with_for_update no-op su SQLite ma
    # forward-compatible con PostgreSQL.
    proj = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).with_for_update().first()
    if not proj:
        raise HTTPException(404, "Progetto non trovato")
    if proj.finance_status == "closed":
        raise HTTPException(409, "Progetto già chiuso finanziariamente")

    # Precheck pending lines (HARD BLOCK)
    pending = db.query(JobCostLine).join(Job).filter(
        Job.project_id == project_id,
        Job.status != JobStatus.cancelled,
        JobCostLine.billing_status.in_([
            JCLBillingStatus.not_billed,
            JCLBillingStatus.in_batch,
        ]),
        JobCostLine.is_billable == True,
        JobCostLine.total_accrued > 0,
    ).count()
    if pending > 0:
        raise HTTPException(409, f"{pending} JCL ancora da fatturare/in approvazione — non si può chiudere")

    # v3.5.0-alpha.168 — Auto numero se non fornito (Bug 3).
    from app.routers.finance import _next_invoice_number
    num = (invoice_number or "").strip()
    if num:
        existing = db.query(Invoice).join(Client, Invoice.client_id == Client.id).filter(
            Invoice.number == num,
            Client.tenant_id == current_tenant_id(),
        ).first()
        if existing:
            raise HTTPException(409, f"Numero fattura {num} già esistente")
    else:
        num = _next_invoice_number(db, issue_date.year)
    invoice_number = num

    # Batch aperti residui → confluiscono nella closing
    open_batches = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.tenant_id == current_tenant_id(),
        BillingBatch.project_id == project_id,
        BillingBatch.status == BillingBatchStatus.approved,
        BillingBatch.invoice_id.is_(None),
    ).all()

    subtotal = sum(b.total_approved or 0 for b in open_batches)
    vat_amount = subtotal * vat_rate / 100
    total = subtotal + vat_amount

    client_obj = db.query(Client).filter(Client.id == proj.client_id).first()
    tenant_obj = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()

    closing_note = (notes or "") + f"\nFATTURA DI CHIUSURA PROGETTO {proj.code}"
    invoice = Invoice(
        tenant_id=current_tenant_id(),  # v3.5.0-alpha.172.37 Sprint 3.E
        number=invoice_number,
        client_id=proj.client_id,
        status=InvoiceStatus.draft,
        issue_date=issue_date,
        due_date=due_date,
        subtotal=subtotal,
        vat_rate=vat_rate,
        total=total,
        notes=closing_note,
        doc_type="TD01",
        is_closing=True,
        closing_project_id=project_id,
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
        tenant_rea_snap=(tenant_obj.rea_number if tenant_obj else None),
        tenant_fiscal_capital_snap=(tenant_obj.fiscal_capital if tenant_obj else None),
        tenant_fiscal_regime_snap=(tenant_obj.fiscal_regime if tenant_obj else None),
        # v3.5.0-alpha.172 (currency Task 9) — fattura di chiusura project-level:
        # valuta ambigua. Default valuta base.
        currency=((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper(),
    )
    # v3.5.0-alpha.172 (currency Task 9) — congela tasso BCE data emissione.
    from app.services.currency import freeze_invoice_fx
    freeze_invoice_fx(db, invoice, ((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper())
    db.add(invoice)
    db.flush()

    invoice_lines_count = 0
    for batch in open_batches:
        for bl in batch.lines:
            if bl.total_approved <= 0:
                jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
                if jcl:
                    jcl.billing_status = JCLBillingStatus.lost
                    jcl.billed_amount = 0
                continue
            period_lbl = ""
            if batch.period_start and batch.period_end:
                period_lbl = f" [{batch.period_start.isoformat()} → {batch.period_end.isoformat()}]"
            # v3.5.0-alpha.169 — quantity recomputed da total_approved (Bug 4)
            if bl.unit_price and bl.unit_price > 0:
                inv_qty = round(bl.total_approved / bl.unit_price, 4)
            else:
                inv_qty = bl.quantity
            il = InvoiceLine(
                invoice_id=invoice.id,
                description=f"[{batch.code}]{period_lbl} " + bl.description + (" [extra]" if bl.is_extra else ""),
                quantity=inv_qty,
                unit_price=bl.unit_price,
                total=bl.total_approved,
                vat_rate=vat_rate,
                discount_pct=0.0,
            )
            db.add(il)
            invoice_lines_count += 1
            jcl = db.query(JobCostLine).filter(JobCostLine.id == bl.job_cost_line_id).first()
            if jcl:
                jcl.billing_status = JCLBillingStatus.billed
                jcl.billed_amount = bl.total_approved
            slice_ = JCLBilledSlice(
                tenant_id=current_tenant_id(),
                job_cost_line_id=bl.job_cost_line_id,
                billing_batch_line_id=bl.id,
                invoice_id=invoice.id,
                period_start=batch.period_start,
                period_end=batch.period_end,
                billed_quantity=inv_qty or 0.0,
                billed_amount=bl.total_approved,
                unit_price_snap=bl.unit_price or 0.0,
            )
            db.add(slice_)
        batch.status = BillingBatchStatus.invoiced
        batch.invoice_id = invoice.id

    # v3.5.0-alpha.138 — Acconti Step 2: auto-scompute TUTTI gli acconti open
    # del progetto. Genera InvoiceLine negative + AdvancePaymentConsumption.
    # Se la closing invoice ha subtotal < Σ residuo, scompute proporzionalmente:
    # in ordine cronologico (FIFO), fermandosi quando si annulla la fattura.
    # Edge case: subtotal positivo dopo scomputi = saldo dovuto. subtotal=0 =
    # closing a costo zero (interamente coperta da acconti). subtotal negativo
    # = acconti in eccesso → bloccato 409 (manager deve emettere NC TD04 manuale).
    open_advances = db.query(AdvancePayment).filter(
        AdvancePayment.tenant_id == current_tenant_id(),
        AdvancePayment.project_id == project_id,
        AdvancePayment.status == AdvancePaymentStatus.open,
    ).order_by(AdvancePayment.created_at.asc()).all()
    auto_consumptions: list[tuple[int, float]] = []
    remaining_invoice_subtotal = invoice.subtotal or 0.0
    for ap in open_advances:
        if remaining_invoice_subtotal <= 0.005:
            break
        bal = ap.balance_remaining or 0.0
        if bal <= 0.005:
            continue
        take = min(bal, remaining_invoice_subtotal)
        auto_consumptions.append((ap.id, round(take, 2)))
        remaining_invoice_subtotal -= take
    if auto_consumptions:
        consumed_result = _apply_advance_consumptions(
            db, invoice, project_id, auto_consumptions,
            billing_batch_id=None, vat_rate=vat_rate,
        )
    else:
        consumed_result = {"applied": [], "total_consumed": 0.0}
    # Hard-block se totale residuo acconti > closing subtotal (= overflow)
    # Questo NON è coperto sopra (FIFO ferma a 0): segnale che manager ha
    # accreditato troppo. Manager risolve con NC TD04 sull'acconto eccedente.
    leftover_open = sum(
        (ap.balance_remaining or 0)
        for ap in open_advances
        if ap.status == AdvancePaymentStatus.open
    )
    overflow_warning = leftover_open if leftover_open > 0.005 else 0.0

    # v3.5.0-alpha.138 — link diretto Invoice→Project
    invoice.project_id = project_id

    # Marca progetto chiuso
    proj.finance_status = "closed"
    proj.finance_closed_at = now_utc()
    proj.finance_closing_invoice_id = invoice.id

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        from sqlalchemy.exc import IntegrityError
        if isinstance(e, IntegrityError) and "UNIQUE" in str(e).upper():
            raise HTTPException(409, f"Numero fattura {invoice_number} già esistente (race)")
        raise HTTPException(500, f"Errore chiusura: {e}")

    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.number,
        "project_id": project_id,
        "subtotal": round(invoice.subtotal, 2),  # post-scomputo
        "vat_amount": round(invoice.total - invoice.subtotal, 2),
        "total": round(invoice.total, 2),
        "invoice_lines_count": invoice_lines_count,
        "batches_aggregated": len(open_batches),
        "project_finance_status": "closed",
        "advance_consumptions": consumed_result,
        "advance_overflow_open": round(overflow_warning, 2),
    }


@router.post("/{batch_id}/cancel")
async def cancel_batch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Annulla un batch ancora non fatturato. Riporta le JCL → not_billed
    (le rilibera per future trasmissioni). Cancella le LossEntry collegate
    (il perso non era ancora 'reale')."""
    _require_manager(request)
    batch = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
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
        Project.tenant_id == current_tenant_id(),
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
        LossEntry.tenant_id == current_tenant_id(),
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

def _invoice_pdf_response(invoice: Invoice, db: Session):
    from fastapi.responses import Response
    from app.services.invoice_pdf import generate_invoice_pdf
    tenant_obj = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    client_obj = db.query(Client).filter(Client.id == invoice.client_id).first()
    # v3.5.0-alpha.120 (F15) — Prefetch project per intestazione PDF.
    # Senza questo la NC non mostrava il progetto di riferimento.
    project_obj = None
    if invoice.job_id:
        from app.models import Job as _Job, Project as _Project
        job_row = db.query(_Job).filter(_Job.id == invoice.job_id).first()
        if job_row and job_row.project_id:
            project_obj = db.query(_Project).filter(_Project.id == job_row.project_id).first()
    pdf = generate_invoice_pdf(invoice, tenant=tenant_obj, client=client_obj, project=project_obj)
    safe_num = (invoice.number or f"invoice-{invoice.id}").replace("/", "-")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="Fattura-{safe_num}.pdf"',
        },
    )


@router.get("/invoice/{invoice_id}/pdf")
async def get_invoice_pdf_direct(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.111 — PDF formale dato invoice_id (link diretto da
    elenco fatture / batch list). Snapshot fiscali immutabili."""
    _require_finance(request)
    invoice = db.query(Invoice).options(joinedload(Invoice.lines)).join(
        Client, Invoice.client_id == Client.id,
    ).filter(
        Invoice.id == invoice_id,
        Client.tenant_id == current_tenant_id(),
    ).first()
    if not invoice:
        raise HTTPException(404, "Fattura non trovata")
    # v3.5.0-alpha.120 (F14) — cancelled non stampabile
    if invoice.status == InvoiceStatus.cancelled:
        raise HTTPException(
            409,
            f"Fattura {invoice.number} è in stato 'cancelled' e non può essere stampata. "
            "Stornare via Nota di Credito (TD04) e riemettere se necessario."
        )
    return _invoice_pdf_response(invoice, db)


@router.get("/{batch_id}/invoice-pdf")
async def get_invoice_pdf(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Scarica il PDF della fattura collegata al batch (status=invoiced).

    Usa snapshot fiscali catturati al momento dell'emissione: modifiche
    successive a tenant/cliente NON corrompono questo PDF storico.

    v3.5.0-alpha.111: fallback via JCLBilledSlice se batch.invoice_id è NULL
    ma le slice contengono già un invoice_id (caso batch riassegnato/
    rollback parziale). Errore più descrittivo se davvero non c'è fattura.
    """
    _require_finance(request)
    batch = db.query(BillingBatch).options(joinedload(BillingBatch.lines)).filter(
        BillingBatch.id == batch_id, BillingBatch.tenant_id == current_tenant_id(),
    ).first()
    if not batch:
        raise HTTPException(404, "Batch non trovato")
    invoice_id = batch.invoice_id
    if not invoice_id:
        # Fallback: prova a recuperare via JCLBilledSlice delle righe del batch
        slice_inv = db.query(JCLBilledSlice.invoice_id).filter(
            JCLBilledSlice.billing_batch_line_id.in_([l.id for l in batch.lines]),
        ).first()
        if slice_inv:
            invoice_id = slice_inv[0]
    if not invoice_id:
        raise HTTPException(
            400,
            f"Il batch {batch.code} (stato={batch.status.value}) non ha ancora una "
            f"fattura emessa. Approva il batch e usa '💶 Emetti fattura' o 'Componi "
            f"fattura periodo' per emettere la fattura.",
        )
    invoice = db.query(Invoice).options(joinedload(Invoice.lines)).filter(
        Invoice.id == invoice_id,
    ).first()
    if not invoice:
        raise HTTPException(404, "Fattura non trovata")
    return _invoice_pdf_response(invoice, db)


# ── v3.5.0-alpha.111: Storno fattura (nota di credito TD04) ─────────

@router.post("/invoice/{invoice_id}/storno")
async def storno_invoice(
    invoice_id: int,
    request: Request,
    credit_number: Optional[str] = Form(None),
    issue_date: date = Form(...),
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.111 — Emette nota di credito TD04 che storna integralmente
    la fattura sorgente.

    v3.5.0-alpha.172.58 — credit_number opzionale: se omesso, auto-genera serie
    separata `NC-{year}-NNNNN` via `_next_credit_note_number`.

    Effetti:
    1. Crea Invoice TD04 con stessi line snapshot + cliente snapshot, status=draft.
    2. Marca la fattura sorgente come `cancelled`.
    3. Marca le JCLBilledSlice della sorgente come voided (voided_at + voided_by_invoice_id).
       Slice voided non bloccano più i booking nel periodo: il maturato torna
       disponibile per nuova fatturazione.
    4. Resetta JCL.billing_status → not_billed se la slice voided era l'unica
       della JCL (altrimenti resta billed con slice residue).

    Manager+ richiesto. Numero NC manuale, univoco a livello tenant.
    """
    _require_manager(request)
    src = db.query(Invoice).options(joinedload(Invoice.lines)).join(
        Client, Invoice.client_id == Client.id,
    ).filter(
        Invoice.id == invoice_id,
        Client.tenant_id == current_tenant_id(),
    ).first()
    if not src:
        raise HTTPException(404, "Fattura sorgente non trovata")
    if src.doc_type == "TD04":
        raise HTTPException(400, "Non puoi stornare una nota di credito (TD04)")
    if src.status == InvoiceStatus.cancelled:
        raise HTTPException(400, "Fattura già annullata")
    # v3.5.0-alpha.172.58 — Auto-gen numero NC se non fornito (`NC-{year}-NNNNN`).
    if credit_number is None or not credit_number.strip():
        from app.routers.finance import _next_credit_note_number
        credit_number = _next_credit_note_number(db, issue_date.year)
    else:
        credit_number = credit_number.strip()
    # Univocità numero NC
    existing = db.query(Invoice).join(Client, Invoice.client_id == Client.id).filter(
        Invoice.number == credit_number,
        Client.tenant_id == current_tenant_id(),
    ).first()
    if existing:
        raise HTTPException(409, f"Numero {credit_number} già esistente")

    # NC: importi positivi con TD04 — convenzione FatturaPA. Il segno contabile
    # è espresso dal tipo documento, non dal segno numerico.
    # α.172.31 (#3) — NC nasce `approved` (era `sent` in α.120): rappresenta uno
    # storno ufficiale già contabilizzato, ma l'invio effettivo al cliente è
    # un'azione separata (transizione approved → sent via mark-sent endpoint).
    # cashflow_year_sync conta sia approved che sent come storni efficaci
    # (vs draft che resta escluso). Memory feedback Matteo.
    nc = Invoice(
        tenant_id=current_tenant_id(),  # v3.5.0-alpha.172.37 Sprint 3.E
        number=credit_number,
        client_id=src.client_id,
        status=InvoiceStatus.approved,
        issue_date=issue_date,
        subtotal=src.subtotal or 0.0,
        vat_rate=src.vat_rate or 22.0,
        total=src.total or 0.0,
        notes=(
            f"Nota di credito a storno totale della fattura {src.number} "
            f"emessa il {src.issue_date.isoformat() if src.issue_date else '?'}."
            + (f"\nMotivo: {reason}" if reason else "")
        ),
        doc_type="TD04",
        quote_id=src.quote_id,
        job_id=src.job_id,
        payment_method=src.payment_method,
        payment_terms_days=src.payment_terms_days,
        iban_snapshot=src.iban_snapshot,
        client_legal_name_snap=src.client_legal_name_snap,
        client_vat_snap=src.client_vat_snap,
        client_tax_code_snap=src.client_tax_code_snap,
        client_pec_snap=src.client_pec_snap,
        client_admin_email_snap=getattr(src, "client_admin_email_snap", None),
        client_sdi_snap=src.client_sdi_snap,
        client_address_snap=src.client_address_snap,
        client_zip_snap=src.client_zip_snap,
        client_city_snap=src.client_city_snap,
        client_province_snap=src.client_province_snap,
        client_country_snap=src.client_country_snap,
        tenant_legal_name_snap=src.tenant_legal_name_snap,
        tenant_vat_snap=src.tenant_vat_snap,
        tenant_tax_code_snap=src.tenant_tax_code_snap,
        tenant_address_snap=src.tenant_address_snap,
        tenant_email_snap=src.tenant_email_snap,
        tenant_phone_snap=src.tenant_phone_snap,
        tenant_iban_snap=src.tenant_iban_snap,
        tenant_sdi_snap=src.tenant_sdi_snap,
        tenant_rea_snap=src.tenant_rea_snap,
        tenant_fiscal_capital_snap=src.tenant_fiscal_capital_snap,
        tenant_fiscal_regime_snap=src.tenant_fiscal_regime_snap,
        # v3.5.0-alpha.172 (currency Task 9) — la NC storna la fattura sorgente
        # AL TASSO ORIGINALE (non si ri-congela alla data della NC): lo storno
        # deve essere numericamente equivalente all'originale in valuta cliente.
        currency=(getattr(src, "currency", None) or "EUR"),
        fx_rate_to_base=(getattr(src, "fx_rate_to_base", None) or 1.0),
        fx_rate_fixed_at=getattr(src, "fx_rate_fixed_at", None),
    )
    db.add(nc)
    db.flush()
    # Copia righe
    for l in src.lines:
        db.add(InvoiceLine(
            invoice_id=nc.id,
            description=f"[Storno] {l.description}",
            quantity=l.quantity,
            unit_price=l.unit_price,
            total=l.total,
            vat_rate=l.vat_rate,
            discount_pct=l.discount_pct,
        ))

    # Void slice + restore JCL billing_status
    slices = db.query(JCLBilledSlice).filter(JCLBilledSlice.invoice_id == src.id).all()
    affected_jcl_ids = set()
    for s in slices:
        if s.voided_at is None:
            s.voided_at = now_utc()
            s.voided_by_invoice_id = nc.id
            affected_jcl_ids.add(s.job_cost_line_id)
    # Per ogni JCL toccata, se non ha più slice attive → torna not_billed
    for jcl_id in affected_jcl_ids:
        live = db.query(JCLBilledSlice).filter(
            JCLBilledSlice.job_cost_line_id == jcl_id,
            JCLBilledSlice.voided_at.is_(None),
        ).first()
        jcl = db.query(JobCostLine).filter(JobCostLine.id == jcl_id).first()
        if jcl and not live:
            jcl.billing_status = JCLBillingStatus.not_billed
            jcl.billed_amount = 0

    # Annulla fattura sorgente
    src.status = InvoiceStatus.cancelled
    src.notes = (src.notes or "") + f"\nStornata con NC {credit_number} il {issue_date.isoformat()}."

    # Riapre batch collegati (status → approved per consentire nuova emissione)
    batches = db.query(BillingBatch).filter(BillingBatch.invoice_id == src.id).all()
    for b in batches:
        b.invoice_id = None
        b.status = BillingBatchStatus.approved

    # α.172.31 (#4) — Se la fattura stornata era un ACCONTO (kind=advance),
    # riapri l'AdvancePayment ledger collegato: invoice_id=None, status=draft.
    # Permette di rieditare allocazioni / importo e riemettere fattura
    # successiva senza dover ricreare l'AP da zero.
    reopened_advance_id = None
    if src.kind == InvoiceKind.advance:
        ap_src = db.query(AdvancePayment).filter(
            AdvancePayment.invoice_id == src.id,
            AdvancePayment.tenant_id == current_tenant_id(),
        ).first()
        if ap_src:
            ap_src.invoice_id = None
            ap_src.status = AdvancePaymentStatus.draft
            reopened_advance_id = ap_src.id

    # v3.5.0-alpha.112 — se la fattura stornata era CLOSING di un progetto:
    # riapri il progetto finanziariamente (finance_status='active').
    # v3.5.0-alpha.114 A6: ALSO reset JCL lost zero-approved → not_billed.
    # Le JCL marcate lost durante closing emit con total_approved=0 non hanno
    # JCLBilledSlice (lo storno NC sopra non le vede in affected_jcl_ids) →
    # restavano "lost" permanente mentre il progetto era riaperto. Bug audit.
    reopened_project_id = None
    if bool(getattr(src, "is_closing", False)) and getattr(src, "closing_project_id", None):
        pr = db.query(Project).filter(Project.id == src.closing_project_id).first()
        if pr and pr.finance_status == "closed":
            pr.finance_status = "active"
            pr.finance_closed_at = None
            pr.finance_closing_invoice_id = None
            reopened_project_id = pr.id
            # Reset JCL lost (zero-approved durante closing) → not_billed
            jcls_lost = db.query(JobCostLine).join(Job).filter(
                Job.project_id == pr.id,
                JobCostLine.billing_status == JCLBillingStatus.lost,
                (JobCostLine.billed_amount == 0) | (JobCostLine.billed_amount.is_(None)),
            ).all()
            for jcl in jcls_lost:
                jcl.billing_status = JCLBillingStatus.not_billed

    db.commit()
    db.refresh(nc)
    return {
        "credit_note_id": nc.id,
        "credit_note_number": nc.number,
        "source_invoice_id": src.id,
        "source_invoice_number": src.number,
        "voided_slices": len(slices),
        "reopened_batches": [b.code for b in batches],
        "reopened_project_id": reopened_project_id,
        "total": nc.total,
    }
