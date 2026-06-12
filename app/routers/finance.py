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
from app.services.tenant_guard import scoped, fetch_or_404, fetch_invoice_or_404
from app.context import current_tenant_id

router = APIRouter(prefix="/finance", tags=["finance"])

# v3.5.0-alpha.66.16.0 — Sprint R3 (permission gate sweep). Pattern
# identico a quotes.RequireEditQuotes (α.66.14.5).
RequireEditInvoices = Depends(requires_permission("edit_invoices"))
RequireEditPlanningOwn = Depends(requires_permission("edit_planning_own"))


def _tpl():
    from app.main import templates
    return templates


def _tenant_base_currency(db: Session) -> str:
    """Valuta base del tenant corrente (default EUR se non configurata)."""
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    return (getattr(t, "default_currency", None) or "EUR").upper() if t else "EUR"


# ── Pagine HTML ───────────────────────────────────────────────────────


@router.get("/cashflow", response_class=HTMLResponse)
async def cashflow_page(request: Request, db: Session = Depends(get_db)):
    """Pagina cashflow timeline 12 mesi (revenue-side)."""
    return _tpl().TemplateResponse(
        "pages/cashflow.html", {"request": request}
    )


@router.get("/", response_class=HTMLResponse)
async def finance_page(request: Request, db: Session = Depends(get_db)):
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant scope (era leak: Invoice non ha
    # tenant_id diretto, scope via Client). `scoped()` aggiunge JOIN Client.
    invoices = (
        scoped(db.query(Invoice).options(joinedload(Invoice.client)), Invoice)
        .order_by(Invoice.issue_date.desc()).all()
    )
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
    Filtri cliente/progetto richiedono join con Job.

    v3.5.0-alpha.172.35 (Sprint 1) — tenant scope baseline (era leak: Timesheet
    non ha tenant_id diretto, scoping via Job.tenant_id obbligatorio sempre,
    non solo quando vengono passati i filtri cliente/progetto).
    """
    from app.models import Job as _Job
    q = db.query(Timesheet).join(_Job, Timesheet.job_id == _Job.id).filter(
        _Job.tenant_id == current_tenant_id()
    )
    if job_id:
        q = q.filter(Timesheet.job_id == job_id)
    if user_id:
        q = q.filter(Timesheet.user_id == user_id)
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
        # v3.5.0-alpha.159 — Filter project via job_id OR project_id diretto
        # (acconti project-level hanno solo project_id, no job_id).
        from sqlalchemy import or_
        from sqlalchemy.orm import outerjoin
        q = q.outerjoin(_Job, Invoice.job_id == _Job.id).filter(
            or_(_Job.project_id == project_id, Invoice.project_id == project_id)
        )
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
    # v3.5.0-alpha.159 — Pre-fetch Project per Invoice.project_id diretto
    # (acconti project-level senza job).
    inv_list = q.all()
    direct_proj_ids = {i.project_id for i in inv_list if i.project_id and not i.job_id}
    direct_proj_map: dict[int, "Project"] = {}
    if direct_proj_ids:
        proj_rows = db.query(Project).filter(Project.id.in_(direct_proj_ids)).all()
        direct_proj_map = {p.id: p for p in proj_rows}
    for inv in inv_list:
        # Priorità: job.project (back-compat) → project_id diretto (α.143+)
        proj = inv.job.project if (inv.job and inv.job.project) else None
        if not proj and inv.project_id:
            proj = direct_proj_map.get(inv.project_id)
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
    number: Optional[str] = Form(None),
    client_id: int = Form(...),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    vat_rate: float = Form(22.0),
    notes: Optional[str] = Form(None),
    # v3.5.0-alpha.143 — Link strutturati a project/quote/job/JCL
    project_id: Optional[int] = Form(None),
    quote_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    jcl_id: Optional[int] = Form(None),
    force: Optional[str] = Form(None),  # "true" se senza project+quote
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.143 — Crea fattura con link strutturati.
    Validazione: senza project E quote → 400 (force=true per consentire).
    JCL link salvato in notes finché non c'è colonna dedicata.

    v3.5.0-alpha.168 — `number` ora opzionale: se omesso/vuoto, auto-generato
    via _next_invoice_number (naming convention {anno}-{NNNNN}).
    """
    force_b = (force or "").strip().lower() == "true"
    if not project_id and not quote_id and not force_b:
        raise HTTPException(
            400,
            "Fattura senza progetto/quotazione: aggiungi link strutturato "
            "oppure passa force=true per confermare."
        )
    num = (number or "").strip()
    if num:
        existing = db.query(Invoice).join(Client, Invoice.client_id == Client.id).filter(
            Invoice.number == num,
            Client.tenant_id == current_tenant_id(),
        ).first()
        if existing:
            raise HTTPException(409, f"Numero fattura {num} già esistente")
    else:
        num = _next_invoice_number(db, issue_date.year)
    inv_notes = notes or ""
    if jcl_id:
        inv_notes = (inv_notes + (" · " if inv_notes else "")
                     + f"Lavorazione JCL #{jcl_id}").strip()
    # v3.5.0-alpha.172 (currency Task 9) — valuta + freeze tasso emissione.
    base = _tenant_base_currency(db)
    ccy = base
    if quote_id:
        q = db.query(Quote).filter(Quote.id == quote_id).first()
        if q and getattr(q, "currency", None):
            ccy = q.currency.upper()
    inv = Invoice(
        tenant_id=current_tenant_id(),  # v3.5.0-alpha.172.37 Sprint 3.E
        number=num, client_id=client_id,
        project_id=project_id, quote_id=quote_id, job_id=job_id,
        issue_date=issue_date, due_date=due_date,
        vat_rate=vat_rate, notes=(inv_notes or None),
        currency=ccy,
    )
    from app.services.currency import freeze_invoice_fx
    freeze_invoice_fx(db, inv, base)
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
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    inv = fetch_invoice_or_404(db, invoice_id)
    _enforce_invoice_mutable(inv)  # v3.5.0-alpha.114
    total = quantity * unit_price
    line = InvoiceLine(
        invoice_id=invoice_id, description=description,
        quantity=quantity, unit_price=unit_price, total=total,
        vat_rate=inv.vat_rate,  # default header → uniforme col flusso emit
    )
    db.add(line)
    # v3.5.0-alpha.172.37 (Sprint 3.D BLOCCO 4) — ricomputa totals via helper
    # (era `inv.subtotal += total` + `inv.total = subtotal * (1 + vat)`, che
    # P1: rompeva su `subtotal=None` con TypeError, e P0: rotto in scenari
    # multi-rate. Helper aggrega per-riga + per-aliquota).
    from app.services.invoice_totals import (
        compute_invoice_totals_from_lines, apply_totals_to_invoice,
    )
    db.flush()
    apply_totals_to_invoice(inv, compute_invoice_totals_from_lines(inv.lines))
    db.commit()
    return line


@router.put("/api/invoices/{invoice_id}/status", dependencies=[RequireEditInvoices])
async def update_invoice_status(
    invoice_id: int,
    status: InvoiceStatus = Form(...),
    db: Session = Depends(get_db),
):
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    inv = fetch_invoice_or_404(db, invoice_id)
    # v3.5.0-alpha.114 — transizioni stato consentite:
    #   draft → sent (emissione)
    #   sent → paid (pagamento)
    #   sent → overdue (auto/manuale)
    # v3.5.0-alpha.172.57 — Post-emissione (sent/paid/overdue) NO cancelled diretto.
    # Una volta inviata al cliente/SDI, la fattura è immutabile per legge: storno
    # esclusivamente via Nota di Credito TD04 (endpoint billing.create_credit_note
    # che genera l'NC + marca la sorgente cancelled in transazione).
    # Draft/approved restano cancellabili dirette (non ancora emesse).
    _ALLOWED = {
        InvoiceStatus.draft: {InvoiceStatus.sent, InvoiceStatus.approved, InvoiceStatus.cancelled},
        # α.172.31 (#3) — `approved` = stato iniziale NC (e potenziale future
        # fatture ordinarie non ancora trasmesse). Da approved si invia o si annulla.
        InvoiceStatus.approved: {InvoiceStatus.sent, InvoiceStatus.cancelled},
        # α.172.57 — sent: SOLO paid/overdue. No cancelled diretto.
        InvoiceStatus.sent: {InvoiceStatus.paid, InvoiceStatus.overdue},
        # α.172.57 — overdue: SOLO paid. No cancelled diretto.
        InvoiceStatus.overdue: {InvoiceStatus.paid},
        InvoiceStatus.paid: set(),  # paid è terminal: solo storno NC
        InvoiceStatus.cancelled: set(),  # cancelled terminal
    }
    cur = inv.status
    if status != cur and status not in _ALLOWED.get(cur, set()):
        # Caso speciale: tentativo cancel su fattura emessa → guida verso NC TD04.
        if status == InvoiceStatus.cancelled and cur in (
            InvoiceStatus.sent, InvoiceStatus.overdue, InvoiceStatus.paid,
        ):
            raise HTTPException(
                409,
                detail={
                    "message": (
                        f"Impossibile annullare direttamente: fattura già emessa "
                        f"(stato '{cur.value}').\n\n"
                        f"Una volta inviata al cliente/SDI, la fattura è immutabile "
                        f"per legge. Per stornarla:\n"
                        f"1. Apri la fattura → 'Emetti Nota di Credito (TD04)'\n"
                        f"2. La NC storna integralmente l'importo e marca questa "
                        f"fattura come 'annullata' in transazione."
                    ),
                    "invoice_id": inv.id,
                    "current_status": cur.value,
                    "remediation": "credit_note_td04",
                },
            )
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
    # v3.5.0-alpha.172.42 — Cascade su acconto cancelled (anche da draft/approved):
    # se la fattura acconto viene cancellata SENZA passare da NC TD04, l'AP
    # ledger collegato torna a `draft` (analogo al flow create_credit_note in
    # billing.py:2510). Permette di rieditare e riemettere senza ricreare AP.
    # Idempotente: se inv non è kind=advance, no-op.
    advance_reopened_id = None
    if status == InvoiceStatus.cancelled and inv.kind == InvoiceKind.advance:
        ap_src = db.query(AdvancePayment).filter(
            AdvancePayment.invoice_id == inv.id,
            AdvancePayment.tenant_id == current_tenant_id(),
        ).first()
        if ap_src:
            ap_src.invoice_id = None
            ap_src.status = AdvancePaymentStatus.draft
            advance_reopened_id = ap_src.id
    db.commit()
    result = {"id": inv.id, "status": inv.status}
    if advance_reopened_id:
        result["advance_reopened_id"] = advance_reopened_id
    return result


# ── Acconti progetto (v3.5.0-alpha.136) ────────────────────────────
# Pattern B della decision tree F26/F28: ledger AdvancePayment separato
# che lega Invoice(kind=advance) a Project. Si scompute progressivamente nelle
# fatture batch successive (SAL) e nella closing invoice.
# Vedi app/models/models.py AdvancePayment per semantica completa.


def _next_invoice_number(db: Session, year: int) -> str:
    """Genera prossimo numero progressivo formato `{year}-{NNNNN}` per fattura.

    Convenzione unica (acconto / batch / closing / compose / manuale):
    `{anno}-{seq 5 cifre}`. Tenant-scoped via Client.tenant_id (Invoice non ha
    direttamente tenant_id, scoping per cliente).
    Idempotente: re-genera incrementando finché non collide con numero esistente.

    v3.5.0-alpha.168 — rinominata da `_next_invoice_number_for_advance`,
    riusata da TUTTI gli endpoint che emettono fatture (Matteo: "default da
    naming convention con possibile override"). Alias _for_advance mantenuto.
    """
    from sqlalchemy import desc
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


# Alias retro-compat (v3.5.0-alpha.168). Codice esistente che importa il vecchio
# nome continua a funzionare. Nuovo codice usa _next_invoice_number direttamente.
_next_invoice_number_for_advance = _next_invoice_number


def _next_credit_note_number(db: Session, year: int) -> str:
    """v3.5.0-alpha.172.58 — Numero progressivo per Nota di Credito TD04.

    Serie separata dalle fatture ordinarie: `NC-{year}-{NNNNN}`. Più leggibile
    di una numerazione unica (legge fiscale italiana ammette entrambe le scelte;
    serie separata preferita per chiarezza nel registro vendite).
    """
    from sqlalchemy import desc
    prefix = f"NC-{year}-"
    last = (
        db.query(Invoice.number)
        .join(Client, Invoice.client_id == Client.id)
        .filter(
            Client.tenant_id == current_tenant_id(),
            Invoice.number.like(f"{prefix}%"),
        )
        .order_by(desc(Invoice.number))
        .first()
    )
    if not last:
        return f"{prefix}00001"
    try:
        seq = int(last[0].rsplit("-", 1)[1]) + 1
    except (ValueError, IndexError):
        seq = 1
    for _ in range(1000):
        candidate = f"{prefix}{seq:05d}"
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
    raise HTTPException(500, "Impossibile generare numero progressivo NC univoco")


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

    # v3.5.0-alpha.172.46 — HARD-BLOCK Σ acconti > budget progetto.
    # Pre-α.172.46 nessun limite: utente poteva creare AP per 30% + 80% =
    # 110% del progetto. Controllo: Σ AP non-cancelled + nuovo amount <=
    # Σ Quote.total_after_discount (escluse IVA) delle quote approved.
    # Fallback su `proj.budget_quoted` se nessuna quote approved.
    from app.models import Quote as _Q, QuoteStatus as _QS
    approved_quotes_total = (
        db.query(func.coalesce(func.sum(_Q.total_after_discount), 0.0))
        .filter(
            _Q.project_id == project_id,
            _Q.status == _QS.approved,
            _Q.deleted_at.is_(None),
        )
        .scalar() or 0.0
    )
    project_budget = approved_quotes_total or (getattr(proj, "budget_quoted", None) or 0.0)
    existing_advances_total = (
        db.query(func.coalesce(func.sum(AdvancePayment.amount), 0.0))
        .filter(
            AdvancePayment.project_id == project_id,
            AdvancePayment.tenant_id == current_tenant_id(),
            AdvancePayment.status != AdvancePaymentStatus.cancelled,
        )
        .scalar() or 0.0
    )
    if project_budget > 0:
        total_after_new = existing_advances_total + amount
        if total_after_new > project_budget + 0.01:
            pct_attempt = round(total_after_new / project_budget * 100, 1)
            pct_existing = round(existing_advances_total / project_budget * 100, 1)
            raise HTTPException(
                409,
                detail={
                    "message": (
                        f"La somma degli acconti supererebbe il budget del progetto.\n\n"
                        f"• Budget progetto: € {project_budget:,.2f}\n"
                        f"• Acconti già esistenti: € {existing_advances_total:,.2f} ({pct_existing}%)\n"
                        f"• Nuovo acconto richiesto: € {amount:,.2f}\n"
                        f"• Totale risultante: € {total_after_new:,.2f} ({pct_attempt}%)\n\n"
                        f"Per procedere: riduci l'importo del nuovo acconto, "
                        f"oppure annulla uno degli acconti esistenti."
                    ),
                    "project_budget": round(project_budget, 2),
                    "existing_advances_total": round(existing_advances_total, 2),
                    "attempted_amount": round(amount, 2),
                    "attempted_total_pct": pct_attempt,
                },
            )
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

    # v3.5.0-alpha.172.142 — Decimal/HALF_UP coerente con compute_invoice_totals
    # (era float round() = banker's, path divergente dalle fatture regolari).
    from app.services.money import to_decimal, money_round, money_to_float
    _sub_d = money_round(to_decimal(amount))
    _vat_d = money_round(_sub_d * to_decimal(vat_rate) / to_decimal(100))
    subtotal = money_to_float(_sub_d)
    vat_amount = money_to_float(_vat_d)
    total = money_to_float(money_round(_sub_d + _vat_d))

    inv = Invoice(
        tenant_id=current_tenant_id(),  # v3.5.0-alpha.172.37 Sprint 3.E
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
        # v3.5.0-alpha.172 (currency Task 9) — acconto project-level: valuta
        # ambigua (progetto può avere più quote A/B/C). Default valuta base.
        currency=((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper(),
    )
    # v3.5.0-alpha.172 (currency Task 9) — congela tasso BCE data emissione.
    from app.services.currency import freeze_invoice_fx
    freeze_invoice_fx(db, inv, ((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper())
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
    total_paid = 0.0
    for ap in rows:
        consumed = sum((c.amount_consumed or 0) for c in ap.consumptions)
        inv = ap.invoice
        is_cancelled = (ap.status == AdvancePaymentStatus.cancelled)
        if not is_cancelled:
            total_amount += ap.amount or 0
            total_balance += ap.balance_remaining or 0
            total_consumed += consumed
            # v3.5.0-alpha.159 — Pagato = invoice.amount_paid (cassa incassata)
            # Distinto da consumed (= scomputato in fatture batch successive).
            if inv and inv.amount_paid:
                total_paid += inv.amount_paid
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
            "paid": round(total_paid, 2),
            "balance_remaining": round(total_balance, 2),
        },
    }


@router.get("/api/advances/open")
async def list_open_advances(db: Session = Depends(get_db)):
    """v3.5.0-alpha.143 — Lista acconti aperti (status=open, balance > 0) di
    tutto il tenant. Usato dal widget /finance#invoices per dare visibilità
    immediata degli acconti in attesa di emissione/scomputo."""
    rows = (
        db.query(AdvancePayment)
        .options(
            joinedload(AdvancePayment.invoice),
            joinedload(AdvancePayment.project),
            joinedload(AdvancePayment.consumptions),
        )
        .filter(
            AdvancePayment.tenant_id == current_tenant_id(),
            AdvancePayment.status == AdvancePaymentStatus.open,
            AdvancePayment.balance_remaining > 0.005,
        )
        .order_by(AdvancePayment.created_at.desc())
        .all()
    )
    out = []
    for ap in rows:
        inv = ap.invoice
        proj = ap.project
        consumed = sum((c.amount_consumed or 0) for c in ap.consumptions)
        out.append({
            "id": ap.id,
            "amount": round(ap.amount or 0, 2),
            "consumed": round(consumed, 2),
            "balance_remaining": round(ap.balance_remaining or 0, 2),
            "project_id": ap.project_id,
            "project_code": proj.code if proj else None,
            "project_title": proj.title if proj else None,
            "invoice_id": inv.id if inv else None,
            "invoice_number": inv.number if inv else None,
            "invoice_status": (inv.status.value if inv and hasattr(inv.status, "value") else (inv.status if inv else None)),
            "invoice_total": round(inv.total or 0, 2) if inv else 0,
            "invoice_amount_paid": round(inv.amount_paid or 0, 2) if inv else 0,
            "created_at": ap.created_at.isoformat() if ap.created_at else None,
        })
    return {"count": len(out), "rows": out}


# ── Workflow acconti α.145 ────────────────────────────────────────


@router.get("/api/advances/pending-draft")
async def list_pending_draft_advances(db: Session = Depends(get_db)):
    """v3.5.0-alpha.145 — Lista AP in stato pending/draft/confirmed tenant-wide.
    Sono gli acconti ancora da emettere come fattura (workflow: pending →
    confirmed → invoiced)."""
    from app.models import AdvancePaymentAllocation as _APA
    rows = (
        db.query(AdvancePayment)
        .options(
            joinedload(AdvancePayment.project),
            joinedload(AdvancePayment.allocations).joinedload(_APA.job_cost_line),
        )
        .filter(
            AdvancePayment.tenant_id == current_tenant_id(),
            AdvancePayment.status.in_([
                AdvancePaymentStatus.pending,
                AdvancePaymentStatus.draft,
                AdvancePaymentStatus.confirmed,
            ]),
        )
        .order_by(AdvancePayment.scheduled_due_date.asc().nulls_last(), AdvancePayment.created_at.asc())
        .all()
    )
    out = []
    for ap in rows:
        proj = ap.project
        out.append({
            "id": ap.id,
            "status": ap.status.value,
            "label": ap.label,
            "amount": round(ap.amount or 0, 2),
            "scheduled_due_date": ap.scheduled_due_date.isoformat() if ap.scheduled_due_date else None,
            "project_id": ap.project_id,
            "project_code": proj.code if proj else None,
            "project_title": proj.title if proj else None,
            "quote_advance_schedule_id": ap.quote_advance_schedule_id,
            "notes": ap.notes,
            "allocations": [
                {
                    "id": a.id, "job_cost_line_id": a.job_cost_line_id,
                    "pct": a.pct, "amount": a.amount,
                    "jcl_description": (a.job_cost_line.description if a.job_cost_line else None),
                }
                for a in (ap.allocations or [])
            ],
            "created_at": ap.created_at.isoformat() if ap.created_at else None,
        })
    return {"count": len(out), "rows": out}


@router.get("/api/advances/{advance_id}/jcls-available")
async def list_jcls_for_advance(advance_id: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.158 — Lista TUTTE le JCL del progetto associato a questo AP +
    flag `allocated` (true se già in AdvancePaymentAllocation) + pct corrente.
    UI usa per popolare picker JCL nel modal "Gestisci acconto" — l'utente
    può add/remove/modify allocazioni a piacere."""
    from app.models import AdvancePaymentAllocation as _APA
    ap = db.query(AdvancePayment).filter(
        AdvancePayment.id == advance_id,
        AdvancePayment.tenant_id == current_tenant_id(),
    ).first()
    if not ap:
        raise HTTPException(404, "Acconto non trovato")
    # Tutti JCL del progetto via Job
    jcls = (
        db.query(JobCostLine)
        .join(Job, JobCostLine.job_id == Job.id)
        .filter(Job.project_id == ap.project_id, Job.tenant_id == current_tenant_id())
        .order_by(Job.code.asc(), JobCostLine.id.asc())
        .all()
    )
    # Map alloc esistenti su questo AP
    allocs = db.query(_APA).filter(_APA.advance_payment_id == advance_id).all()
    alloc_map = {a.job_cost_line_id: a for a in allocs}
    # v3.5.0-alpha.172.52 — Σ alloc per JCL su altri AP non-cancelled (esclude self).
    # Serve a UI per mostrare "Disponibile = quoted - billed - altri_AP".
    other_aps_by_jcl: dict[int, float] = {}
    if jcls:
        rows = (
            db.query(_APA.job_cost_line_id, func.coalesce(func.sum(_APA.amount), 0.0))
            .join(AdvancePayment, AdvancePayment.id == _APA.advance_payment_id)
            .filter(
                _APA.job_cost_line_id.in_([j.id for j in jcls]),
                AdvancePayment.id != ap.id,
                AdvancePayment.status != AdvancePaymentStatus.cancelled,
                AdvancePayment.tenant_id == current_tenant_id(),
            )
            .group_by(_APA.job_cost_line_id)
            .all()
        )
        other_aps_by_jcl = {r[0]: float(r[1] or 0.0) for r in rows}
    out = []
    for jcl in jcls:
        a = alloc_map.get(jcl.id)
        q = jcl.total_quoted or 0.0
        billed = jcl.billed_amount or 0.0
        other = other_aps_by_jcl.get(jcl.id, 0.0)
        available = max(0.0, q - billed - other)
        out.append({
            "jcl_id": jcl.id,
            "job_id": jcl.job_id,
            "job_code": jcl.job.code if jcl.job else None,
            "description": jcl.description,
            "unit": jcl.unit,
            "total_quoted": round(q, 2),
            "total_accrued": round(jcl.total_accrued or 0, 2),
            "billed_amount": round(billed, 2),
            "other_aps_alloc": round(other, 2),
            "available_for_this_ap": round(available, 2),
            "billing_status": jcl.billing_status.value if jcl.billing_status else None,
            "allocated": bool(a),
            "alloc_id": a.id if a else None,
            "alloc_pct": (a.pct if a else 0.0),
            "alloc_amount": (a.amount if a else 0.0),
        })
    return {"advance_id": ap.id, "project_id": ap.project_id,
            "amount": ap.amount, "jcls": out}


@router.post("/api/advances/{advance_id}/confirm", dependencies=[RequireEditInvoices])
async def confirm_advance_payment(
    advance_id: int,
    label: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    amount: Optional[float] = Form(None),
    # v3.5.0-alpha.145 — CSV "alloc_id:pct,alloc_id:pct" per update pct allocazioni esistenti
    allocations_update: Optional[str] = Form(None),
    # v3.5.0-alpha.158 — CSV "jcl_id:pct,jcl_id:pct" sostituzione TOTALE allocazioni.
    # Override completo: drop tutte le esistenti + crea nuove. Per add/remove/modify.
    allocations_set: Optional[str] = Form(None),
    next_status: Optional[str] = Form("confirmed"),  # confirmed | draft
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.145 — Conferma/aggiorna AP pending/draft prima dell'emissione.
    Workflow: pending → draft (presa in carico) → confirmed (pronto emit).

    Permette modifica: label, notes, amount, pct allocazioni JCL.
    Non consente modifiche se status già invoiced/paid/consumed."""
    from app.models import AdvancePaymentAllocation as _APA
    ap = db.query(AdvancePayment).filter(
        AdvancePayment.id == advance_id,
        AdvancePayment.tenant_id == current_tenant_id(),
    ).first()
    if not ap:
        raise HTTPException(404, "Acconto non trovato")
    if ap.status not in (
        AdvancePaymentStatus.pending, AdvancePaymentStatus.draft, AdvancePaymentStatus.confirmed,
    ):
        raise HTTPException(409,
            f"Acconto in stato '{ap.status.value}' non più modificabile via confirm. "
            "Usa cancel o storno NC.")
    if label is not None: ap.label = label.strip() or None
    if notes is not None: ap.notes = notes.strip() or None
    if amount is not None:
        if amount <= 0:
            raise HTTPException(400, "amount deve essere > 0")
        consumed = sum((c.amount_consumed or 0) for c in ap.consumptions)
        if amount < consumed:
            raise HTTPException(409, f"amount {amount} < già consumato {consumed}")
        ap.amount = round(amount, 2)
        ap.balance_remaining = round(amount - consumed, 2)
    # v3.5.0-alpha.166 — allocations_update accetta sia amount EUR sia "pct%":
    # "alloc_id:1500.00" → set amount=1500
    # "alloc_id:60%" → set amount = JCL.total_quoted × 0.6
    # Validazione: amount ≤ JCL.total_quoted, Σ ≤ AP.amount.
    if allocations_update:
        for token in allocations_update.split(","):
            token = token.strip()
            if not token or ":" not in token:
                continue
            try:
                a_id_s, val_s = token.split(":", 1)
                a_id = int(a_id_s.strip())
                val_s = val_s.strip()
            except ValueError:
                raise HTTPException(400, f"allocations_update parse error: {token}")
            alloc = db.query(_APA).filter(
                _APA.id == a_id, _APA.advance_payment_id == ap.id,
            ).first()
            if not alloc:
                raise HTTPException(404, f"Allocation #{a_id} non trovata per AP {ap.id}")
            jcl = db.query(JobCostLine).filter(JobCostLine.id == alloc.job_cost_line_id).first()
            try:
                if val_s.endswith("%"):
                    pct_v = float(val_s[:-1].strip()) / 100.0
                    if pct_v < 0 or pct_v > 1.0:
                        raise HTTPException(400, f"pct fuori range 0..1: {pct_v}")
                    amt_v = round((jcl.total_quoted or 0.0) * pct_v, 2) if jcl else 0.0
                else:
                    amt_v = round(float(val_s), 2)
            except ValueError:
                raise HTTPException(400, f"allocations_update parse value: {token}")
            if amt_v < 0:
                raise HTTPException(400, f"allocations_update amount negativo: {amt_v}")
            if jcl and amt_v > (jcl.total_quoted or 0.0) + 0.01:
                raise HTTPException(
                    400,
                    f"alloc.amount {amt_v} eccede JCL.total_quoted {jcl.total_quoted}",
                )
            alloc.amount = amt_v
            # pct ricalcolato auto da listener pre-update
    # v3.5.0-alpha.158/166 — allocations_set: sostituzione totale add/remove/modify.
    # Drop tutte le esistenti + crea nuove dal CSV.
    # Formato α.166 (raccomandato): "jcl_id:amount,jcl_id:amount" — amount in EUR.
    # Formato legacy α.158 con suffisso "%": "jcl_id:60%,jcl_id:40%" → amount calcolato
    #   come JCL.total_quoted × pct (semantica utente "% di JCL coperta"). NB:
    #   pre-α.166 il "60%" era "% di AP", post-α.166 è "% di JCL coperta" —
    #   chiamanti legacy ottengono ora il comportamento naturalmente atteso.
    if allocations_set is not None:
        from app.models import AdvancePaymentAllocation as _APA2
        new_pairs: list[tuple[int, float, int]] = []  # (jcl_id, amount, sort_order)
        for idx, token in enumerate(allocations_set.split(",")):
            token = token.strip()
            if not token:
                continue
            if ":" not in token:
                raise HTTPException(400, f"allocations_set parse error: '{token}' (atteso jcl_id:amount o jcl_id:pct%)")
            jid_s, val_s = token.split(":", 1)
            val_s = val_s.strip()
            try:
                jid = int(jid_s.strip())
            except ValueError:
                raise HTTPException(400, f"allocations_set parse: '{token}'")
            # Verifica JCL esiste + appartiene al progetto AP
            jcl = db.query(JobCostLine).join(Job, JobCostLine.job_id == Job.id).filter(
                JobCostLine.id == jid, Job.project_id == ap.project_id,
            ).first()
            if not jcl:
                raise HTTPException(404, f"JCL {jid} non trovata o non nel progetto {ap.project_id}")
            # Determina amount: suffisso "%" → pct di JCL.quoted; altrimenti EUR.
            try:
                if val_s.endswith("%"):
                    pct_v = float(val_s[:-1].strip()) / 100.0
                    if pct_v <= 0 or pct_v > 1.0:
                        raise HTTPException(400, f"allocations_set pct fuori range (0,1]: {pct_v} per JCL {jid}")
                    amt_v = round((jcl.total_quoted or 0.0) * pct_v, 2)
                else:
                    amt_v = round(float(val_s), 2)
            except ValueError:
                raise HTTPException(400, f"allocations_set parse value: '{token}'")
            if amt_v < 0:
                raise HTTPException(400, f"allocations_set amount negativo: {amt_v} per JCL {jid}")
            # Vincolo: alloc.amount ≤ JCL.total_quoted (no over-coverage SU questa singola AP)
            if amt_v > (jcl.total_quoted or 0.0) + 0.01:
                raise HTTPException(
                    400,
                    detail={
                        "message": (
                            f"L'allocazione richiesta supera il quotato della voce.\n\n"
                            f"• Voce JCL #{jid}: {jcl.description or '(senza descrizione)'}\n"
                            f"• Quotato: € {(jcl.total_quoted or 0):,.2f}\n"
                            f"• Allocazione richiesta: € {amt_v:,.2f}\n\n"
                            f"Riduci l'importo allocato a questa voce."
                        ),
                    },
                )
            # v3.5.0-alpha.172.49 — Cross-AP check: Σ allocazioni esistenti su
            # questa JCL da OTHER AP non-cancelled + nuova allocation
            # dev'essere ≤ JCL.total_quoted. Pre-α.172.49 ogni AP poteva
            # allocare full JCL.total_quoted senza vedere altri AP → overflow
            # complessivo (es. 2 AP da 50% ciascuno = 100% × 2 = 200%).
            other_aps_alloc = (
                db.query(func.coalesce(func.sum(_APA2.amount), 0.0))
                .join(AdvancePayment, AdvancePayment.id == _APA2.advance_payment_id)
                .filter(
                    _APA2.job_cost_line_id == jid,
                    AdvancePayment.id != ap.id,  # escludi self (stiamo riscrivendo le sue alloc)
                    AdvancePayment.status != AdvancePaymentStatus.cancelled,
                    AdvancePayment.tenant_id == current_tenant_id(),
                )
                .scalar() or 0.0
            )
            jcl_quoted = jcl.total_quoted or 0.0
            if (amt_v + other_aps_alloc) > jcl_quoted + 0.01:
                free_remaining = max(0.0, jcl_quoted - other_aps_alloc)
                raise HTTPException(
                    409,
                    detail={
                        "message": (
                            f"La voce è già parzialmente allocata ad altri acconti.\n\n"
                            f"• Voce JCL #{jid}: {jcl.description or '(senza descrizione)'}\n"
                            f"• Quotato totale: € {jcl_quoted:,.2f}\n"
                            f"• Già allocato ad altri acconti: € {other_aps_alloc:,.2f}\n"
                            f"• Disponibile residuo: € {free_remaining:,.2f}\n"
                            f"• Allocazione richiesta da questo acconto: € {amt_v:,.2f}\n\n"
                            f"Riduci l'allocazione a € {free_remaining:,.2f} o meno, "
                            f"oppure annulla l'acconto precedente che la copre."
                        ),
                        "jcl_id": jid,
                        "jcl_quoted": round(jcl_quoted, 2),
                        "other_aps_alloc": round(other_aps_alloc, 2),
                        "free_remaining": round(free_remaining, 2),
                        "attempted_amount": round(amt_v, 2),
                    },
                )
            new_pairs.append((jid, amt_v, idx))
        # Vincolo Σ ≤ AP.amount (no over-alloc su questa AP)
        total_alloc = round(sum(p[1] for p in new_pairs), 2)
        if total_alloc > (ap.amount or 0.0) + 0.01:
            raise HTTPException(
                409,
                detail={
                    "message": (
                        f"La somma delle allocazioni supera il totale dell'acconto.\n\n"
                        f"• Importo acconto: € {(ap.amount or 0):,.2f}\n"
                        f"• Somma allocazioni richieste: € {total_alloc:,.2f}\n\n"
                        f"Riduci una o più allocazioni alle voci."
                    ),
                },
            )
        # Drop existing + crea nuove
        db.query(_APA2).filter(_APA2.advance_payment_id == ap.id).delete()
        for jid, amt_v, order in new_pairs:
            db.add(_APA2(
                advance_payment_id=ap.id, job_cost_line_id=jid,
                amount=amt_v, sort_order=order,
                # pct calcolato auto da listener pre-insert
            ))
    if next_status:
        if next_status not in ("draft", "confirmed"):
            raise HTTPException(400, f"next_status '{next_status}' non valido (atteso draft|confirmed)")
        # v3.5.0-alpha.172.52 — HARD-BLOCK sotto-copertura: confermare un acconto
        # richiede che Σ allocazioni JCL == AP.amount (tolleranza 0.01 EUR).
        # Bozza (draft) accetta copertura parziale; confirmed no — altrimenti
        # emit fattura andrebbe in fail su _emit_invoice_from_advance.
        if next_status == "confirmed":
            from app.models import AdvancePaymentAllocation as _APA_check
            # Flush pending writes (new allocations da allocations_set) prima del check.
            db.flush()
            total_now = (
                db.query(func.coalesce(func.sum(_APA_check.amount), 0.0))
                .filter(_APA_check.advance_payment_id == ap.id)
                .scalar() or 0.0
            )
            total_now = float(total_now)
            ap_amt = ap.amount or 0.0
            if total_now < ap_amt - 0.01:
                gap = round(ap_amt - total_now, 2)
                raise HTTPException(
                    409,
                    detail={
                        "message": (
                            f"Allocazioni JCL non coprono il totale dell'acconto.\n\n"
                            f"• Importo acconto: € {ap_amt:,.2f}\n"
                            f"• Allocato finora: € {total_now:,.2f}\n"
                            f"• Mancano: € {gap:,.2f}\n\n"
                            f"Per confermare l'acconto Σ allocazioni deve uguagliare "
                            f"l'importo acconto. Aggiungi voci o salva come bozza."
                        ),
                        "ap_amount": round(ap_amt, 2),
                        "sum_allocated": round(total_now, 2),
                        "gap": gap,
                    },
                )
        ap.status = AdvancePaymentStatus(next_status)
    db.commit()
    db.refresh(ap)
    return {
        "id": ap.id, "status": ap.status.value,
        "amount": ap.amount, "balance_remaining": ap.balance_remaining,
        "label": ap.label,
    }


@router.post("/api/advances/{advance_id}/preview-preset")
async def preview_advance_preset(
    advance_id: int,
    preset: str = Form(...),  # fill_sequential | pro_rata | pro_rata_remaining | manual
    jcl_ids: str = Form(...),  # CSV "jid,jid,jid" in ordine UI (per fill_sequential)
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.172.52 — Calcola allocazioni proposte per preset selezionato
    senza salvare. Cap per JCL = quoted - billed - Σ_alloc_altri_AP_attivi
    (esclusi cancelled e self). Previene fail al save per overflow cross-AP.

    Preset:
      - fill_sequential: riempi voci in ordine fino a coprire AP.amount, ultima parziale.
      - pro_rata: AP × (JCL.available / Σ JCL.available) — distribuzione proporzionale.
      - pro_rata_remaining: alias di pro_rata (entrambi usano available).
      - manual: nessun calcolo, ritorna 0 per ogni JCL (UI compila a mano).

    Ritorna [{jcl_id, amount, pct, jcl_quoted, jcl_billed, jcl_other_aps,
              jcl_available, jcl_description}].
    """
    from app.models import AdvancePaymentAllocation as _APA
    ap = db.query(AdvancePayment).filter(
        AdvancePayment.id == advance_id,
        AdvancePayment.tenant_id == current_tenant_id(),
    ).first()
    if not ap:
        raise HTTPException(404, "Acconto non trovato")
    if preset not in ("fill_sequential", "pro_rata", "pro_rata_remaining", "manual"):
        raise HTTPException(400, f"preset '{preset}' non valido")
    try:
        jcl_id_list = [int(x.strip()) for x in jcl_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "jcl_ids deve essere CSV di interi")
    if not jcl_id_list:
        return {"advance_id": advance_id, "preset": preset, "allocations": []}
    jcls = db.query(JobCostLine).join(Job, JobCostLine.job_id == Job.id).filter(
        JobCostLine.id.in_(jcl_id_list),
        Job.project_id == ap.project_id,
    ).all()
    jcl_map = {j.id: j for j in jcls}
    # Mantieni ordine richiesto dalla UI (fondamentale per fill_sequential)
    ordered = [jcl_map[i] for i in jcl_id_list if i in jcl_map]
    ap_amount = ap.amount or 0.0

    # Cross-AP allocation per JCL: somma su altri AP non-cancelled (self escluso).
    other_aps_by_jcl: dict[int, float] = {}
    if ordered:
        rows = (
            db.query(_APA.job_cost_line_id, func.coalesce(func.sum(_APA.amount), 0.0))
            .join(AdvancePayment, AdvancePayment.id == _APA.advance_payment_id)
            .filter(
                _APA.job_cost_line_id.in_([j.id for j in ordered]),
                AdvancePayment.id != ap.id,
                AdvancePayment.status != AdvancePaymentStatus.cancelled,
                AdvancePayment.tenant_id == current_tenant_id(),
            )
            .group_by(_APA.job_cost_line_id)
            .all()
        )
        other_aps_by_jcl = {r[0]: float(r[1] or 0.0) for r in rows}

    def _available(j: JobCostLine) -> float:
        q = j.total_quoted or 0.0
        billed = j.billed_amount or 0.0
        other = other_aps_by_jcl.get(j.id, 0.0)
        return max(0.0, q - billed - other)

    def _row(j: JobCostLine, amt: float) -> dict:
        q = j.total_quoted or 0.0
        billed = j.billed_amount or 0.0
        other = other_aps_by_jcl.get(j.id, 0.0)
        avail = _available(j)
        return {
            "jcl_id": j.id, "amount": amt,
            "pct": round(amt / ap_amount, 6) if ap_amount > 0 else 0.0,
            "jcl_quoted": round(q, 2),
            "jcl_billed": round(billed, 2),
            "jcl_other_aps": round(other, 2),
            "jcl_available": round(avail, 2),
            "jcl_description": j.description,
        }

    out = []
    if preset == "manual":
        for j in ordered:
            out.append(_row(j, 0.0))
    elif preset == "fill_sequential":
        remaining = ap_amount
        for j in ordered:
            cap = _available(j)
            take = round(min(cap, remaining), 2)
            if take < 0:
                take = 0.0
            out.append(_row(j, take))
            remaining = round(remaining - take, 2)
            if remaining <= 0:
                remaining = 0.0
    elif preset in ("pro_rata", "pro_rata_remaining"):
        # Entrambi i preset proporzionali usano available (quoted - billed - altri AP).
        weights = [(j, _available(j)) for j in ordered]
        sum_w = sum(w[1] for w in weights)
        for j, w in weights:
            if sum_w > 0:
                amt = round(ap_amount * (w / sum_w), 2)
                amt = min(amt, w)  # mai sopra il disponibile
            else:
                amt = 0.0
            out.append(_row(j, amt))

    sum_amt = round(sum(o["amount"] for o in out), 2)
    return {
        "advance_id": advance_id,
        "preset": preset,
        "ap_amount": round(ap_amount, 2),
        "sum_allocated": sum_amt,
        "residual": round(ap_amount - sum_amt, 2),
        "allocations": out,
    }


@router.post("/api/advances/{advance_id}/emit-invoice", dependencies=[RequireEditInvoices])
async def emit_invoice_from_advance(
    advance_id: int,
    request: Request,
    invoice_number: Optional[str] = Form(None),
    issue_date: date = Form(...),
    due_date: Optional[date] = Form(None),
    vat_rate: float = Form(22.0),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.145 — Emette Invoice(kind=advance, doc_type=TD01) per un AP
    in stato pending/draft/confirmed. Lega `AP.invoice_id` + status → invoiced.

    Snapshot fiscali completi (immutabilità post-emissione). Invoice status=draft
    (admin transirà a sent/paid via /api/invoices/{id}/status).
    """
    ap = db.query(AdvancePayment).filter(
        AdvancePayment.id == advance_id,
        AdvancePayment.tenant_id == current_tenant_id(),
    ).first()
    if not ap:
        raise HTTPException(404, "Acconto non trovato")
    if ap.status not in (
        AdvancePaymentStatus.pending, AdvancePaymentStatus.draft, AdvancePaymentStatus.confirmed,
    ):
        raise HTTPException(409, f"Acconto già emesso/processato (status={ap.status.value})")
    if ap.invoice_id:
        raise HTTPException(409, f"AP #{advance_id} già linkato a Invoice #{ap.invoice_id}")
    # α.172.31 — HARD-BLOCK #2: emit acconto richiede allocazioni JCL.
    # Senza allocazioni, AP non si scomputa correttamente nelle fatture
    # successive e il cost report mostra incoerenze. Matteo: vincolante solo
    # in fatturazione (in quote schedule resta opzionale).
    if not ap.allocations or len(ap.allocations) == 0:
        raise HTTPException(
            422,
            "Impossibile emettere: nessuna allocazione a voci di lavorazione (JCL). "
            "Apri il modal 'Gestisci acconto', seleziona le voci e applica un preset "
            "di riempimento prima di emettere la fattura.",
        )
    proj = db.query(Project).filter(
        Project.id == ap.project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not proj or not proj.client_id:
        raise HTTPException(400, "Progetto senza cliente — impossibile emettere fattura")
    client_obj = db.query(Client).filter(Client.id == proj.client_id).first()
    tenant_obj = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()

    num = invoice_number.strip() if invoice_number else _next_invoice_number_for_advance(db, issue_date.year)
    if invoice_number:
        existing = (
            db.query(Invoice)
            .join(Client, Invoice.client_id == Client.id)
            .filter(Invoice.number == num, Client.tenant_id == current_tenant_id())
            .first()
        )
        if existing:
            raise HTTPException(409, f"Numero fattura {num} già esistente")

    # v3.5.0-alpha.172.142 — Decimal/HALF_UP coerente (era float round()).
    from app.services.money import to_decimal, money_round, money_to_float
    amount = ap.amount or 0
    _amt_d = money_round(to_decimal(amount))
    _vat_d = money_round(_amt_d * to_decimal(vat_rate) / to_decimal(100))
    vat_amount = money_to_float(_vat_d)
    total = money_to_float(money_round(_amt_d + _vat_d))
    desc = (description or ap.label or f"Acconto progetto {proj.code}").strip()

    inv = Invoice(
        tenant_id=current_tenant_id(),  # v3.5.0-alpha.172.37 Sprint 3.E
        number=num,
        client_id=proj.client_id,
        project_id=ap.project_id,
        kind=InvoiceKind.advance,
        status=InvoiceStatus.draft,
        issue_date=issue_date,
        due_date=due_date,
        subtotal=amount,
        vat_rate=vat_rate,
        total=total,
        notes=(ap.notes or f"Acconto progetto {proj.code} — AP #{ap.id}"),
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
        # v3.5.0-alpha.172 (currency Task 9) — acconto project-level: valuta
        # ambigua (progetto può avere più quote A/B/C). Default valuta base.
        currency=((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper(),
    )
    # v3.5.0-alpha.172 (currency Task 9) — congela tasso BCE data emissione.
    from app.services.currency import freeze_invoice_fx
    freeze_invoice_fx(db, inv, ((tenant_obj.default_currency if tenant_obj else None) or "EUR").upper())
    db.add(inv)
    db.flush()
    # v3.5.0-alpha.166 — Fattura acconto itemizzata: N InvoiceLine, una per
    # AdvancePaymentAllocation. UI fattura mostra quali JCL sono coperte.
    # Fallback: se nessuna allocation (acconto senza voci), 1 riga aggregata.
    from app.models import AdvancePaymentAllocation as _APA
    allocs = (
        db.query(_APA)
        .filter(_APA.advance_payment_id == ap.id)
        .order_by(_APA.sort_order.asc().nulls_last(), _APA.id.asc())
        .all()
    )
    sum_alloc = round(sum(a.amount or 0.0 for a in allocs), 2)
    lines_created = 0
    if allocs and sum_alloc > 0:
        for a in allocs:
            jcl = db.query(JobCostLine).filter(JobCostLine.id == a.job_cost_line_id).first()
            line_desc = (jcl.description if jcl else f"JCL #{a.job_cost_line_id}")
            db.add(InvoiceLine(
                invoice_id=inv.id,
                description=f"Acconto su: {line_desc}",
                quantity=1.0,
                unit_price=round(a.amount or 0.0, 2),
                total=round(a.amount or 0.0, 2),
                vat_rate=vat_rate,
                discount_pct=0.0,
            ))
            lines_created += 1
        # Riga residuo: se Σ alloc < AP.amount (acconto non interamente
        # allocato), aggiungi riga generica per la differenza.
        residual = round(amount - sum_alloc, 2)
        if residual > 0.01:
            db.add(InvoiceLine(
                invoice_id=inv.id,
                description=f"Acconto generale — {proj.code}",
                quantity=1.0,
                unit_price=residual,
                total=residual,
                vat_rate=vat_rate,
                discount_pct=0.0,
            ))
            lines_created += 1
    else:
        # Fallback: 1 riga aggregata (comportamento pre-α.166).
        db.add(InvoiceLine(
            invoice_id=inv.id, description=desc,
            quantity=1.0, unit_price=amount, total=amount,
            vat_rate=vat_rate, discount_pct=0.0,
        ))
        lines_created = 1
    ap.invoice_id = inv.id
    ap.status = AdvancePaymentStatus.invoiced
    db.commit()
    db.refresh(ap)
    db.refresh(inv)
    return {
        "advance_payment_id": ap.id,
        "status": ap.status.value,
        "invoice_id": inv.id, "invoice_number": inv.number,
        "amount": amount, "vat_amount": vat_amount, "total": total,
        "lines_created": lines_created,
    }


# v3.5.0-alpha.172.51 — Reset status acconto: HARD reset, elimina anche allocazioni.
# Richiesta Matteo: reset soft (status only) lascia le allocazioni JCL/deliverable
# attaccate all'AP. Il cross-AP overflow block conta TUTTE le allocazioni
# non-cancelled → l'altro AP non può modificare le stesse JCL. Quindi reset
# significa: libera la JCL davvero, ripartendo da zero.
@router.post("/api/advances/{advance_id}/reset-to-pending", dependencies=[RequireEditInvoices])
async def reset_advance_to_pending(advance_id: int, db: Session = Depends(get_db)):
    """Riporta un AdvancePayment da draft/confirmed → pending ed elimina TUTTE
    le allocazioni JCL + deliverable collegate (hard reset).

    Vincoli:
    - AP deve essere in stato draft o confirmed
    - AP non deve avere invoice_id (cioè non ancora emesso)
    - Allocazioni: ELIMINATE (JCL + Deliverable), non preservate
    """
    ap = db.query(AdvancePayment).filter(
        AdvancePayment.id == advance_id,
        AdvancePayment.tenant_id == current_tenant_id(),
    ).first()
    if not ap:
        raise HTTPException(404, "Acconto non trovato")
    if ap.invoice_id:
        raise HTTPException(
            409,
            detail={
                "message": (
                    f"Impossibile resettare: acconto già emesso come fattura.\n\n"
                    f"• AP #{ap.id} → Invoice #{ap.invoice_id}\n\n"
                    f"Per ripristinare lo stato: storna la fattura via Nota di "
                    f"Credito (TD04), così l'AP tornerà automaticamente a draft."
                ),
            },
        )
    if ap.status not in (AdvancePaymentStatus.draft, AdvancePaymentStatus.confirmed):
        raise HTTPException(
            409,
            detail={
                "message": (
                    f"Reset disponibile solo per acconti in stato draft o confirmed.\n\n"
                    f"• Stato corrente: {ap.status.value}\n\n"
                    f"Pending non ha bisogno di reset (è già lo stato iniziale). "
                    f"Cancelled e invoiced richiedono altri flussi."
                ),
            },
        )
    from app.models import (
        AdvancePaymentAllocation as _APA,
        AdvancePaymentDeliverableAllocation as _APDA,
    )
    prev_status = ap.status.value
    # Hard reset: elimina allocations JCL
    jcl_count = db.query(_APA).filter(
        _APA.advance_payment_id == ap.id
    ).delete(synchronize_session=False)
    # Hard reset: elimina allocations Deliverable
    deliv_count = db.query(_APDA).filter(
        _APDA.advance_payment_id == ap.id
    ).delete(synchronize_session=False)
    ap.status = AdvancePaymentStatus.pending
    db.commit()
    return {
        "ok": True, "id": ap.id, "status": ap.status.value,
        "previous_status": prev_status,
        "allocations_deleted_jcl": int(jcl_count or 0),
        "allocations_deleted_deliverable": int(deliv_count or 0),
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


# ── FX rate (v3.5.0-alpha.137) ─────────────────────────────────────


@router.get("/api/fx/{from_ccy}/{to_ccy}")
async def fx_rate(from_ccy: str, to_ccy: str, refresh: bool = False, db: Session = Depends(get_db)):
    """Ritorna tasso cambio from→to. Cache 1h, refresh on-demand via ?refresh=true.
    Provider: Frankfurter (BCE, free, no key). Fail-soft: ritorna 503 se provider down e no cache."""
    from app.services.fx import get_fx_rate, refresh_fx_rate
    from_u = (from_ccy or "").upper().strip()
    to_u = (to_ccy or "").upper().strip()
    if len(from_u) != 3 or len(to_u) != 3:
        raise HTTPException(400, "Valuta deve essere codice ISO 4217 (3 caratteri)")
    rate = (refresh_fx_rate(db, from_u, to_u) if refresh
            else get_fx_rate(db, from_u, to_u))
    if rate is None:
        raise HTTPException(503, f"Provider FX non raggiungibile e cache vuota per {from_u}->{to_u}")
    # Cerco metadata: fetched_at + provider per UI
    from app.models import FXRate
    row = db.query(FXRate).filter(
        FXRate.from_currency == from_u, FXRate.to_currency == to_u,
    ).first()
    return {
        "from": from_u, "to": to_u, "rate": rate,
        "fetched_at": row.fetched_at.isoformat() if row and row.fetched_at else None,
        "provider": row.provider if row else "frankfurter",
        "same_currency": from_u == to_u,
    }


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
        InvoiceStatus.draft: ["sent", "approved", "cancelled"],
        InvoiceStatus.approved: ["sent", "cancelled"],
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
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    inv = fetch_invoice_or_404(db, invoice_id)
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
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard + rimosso fallback hardcoded
    inv = fetch_invoice_or_404(db, invoice_id)
    if inv.status == InvoiceStatus.cancelled:
        raise HTTPException(409, "Fattura cancellata: pagamenti non ammessi")

    user = getattr(request.state, "current_user", None)
    payment = InvoicePayment(
        tenant_id=current_tenant_id(),
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
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard. InvoicePayment ha tenant_id
    # diretto, Invoice scope via Client.
    p = fetch_or_404(db, InvoicePayment, payment_id, error="Pagamento non trovato")
    inv = fetch_invoice_or_404(db, p.invoice_id)
    db.delete(p)
    db.flush()
    if inv is not None:
        db.refresh(inv)
        _refresh_invoice_payment_state(db, inv)
    db.commit()
    return {"deleted": True, "invoice_id": p.invoice_id, "amount_paid": (inv.amount_paid if inv else None)}


# ── SDI / FatturaPA XML export (v3.5.0-alpha.172.41 Sprint 6.B) ──────

@router.get("/api/invoices/{invoice_id}/sdi-xml", dependencies=[RequireEditInvoices])
async def download_sdi_xml(invoice_id: int, db: Session = Depends(get_db)):
    """Genera XML FatturaPA v1.6.1 download per emissione manuale SDI.

    Requisiti:
    - Invoice in stato `draft`/`approved`/`sent` (no draft incompleti? non bloccato)
    - Snapshot client/tenant valorizzati (cristallizzati a emit_invoice)
    - P.IVA cliente o CF + codice SDI o PEC + regime fiscale tenant valorizzati

    Trasmissione automatica via Aruba/Sole24 non implementata (richiede firma
    digitale + accreditamento). Roadmap S8.x.
    """
    from fastapi.responses import Response
    from app.services.sdi_xml import build_fattura_xml
    inv = fetch_invoice_or_404(db, invoice_id)
    # Tenant carico per fallback su snapshot mancanti
    tenant = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    if not tenant:
        raise HTTPException(500, "Tenant non trovato in contesto")
    try:
        xml_str, filename = build_fattura_xml(inv, tenant)
    except Exception as e:
        raise HTTPException(500, f"Errore generazione XML SDI: {e}")
    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    project_id: Optional[str] = None,
    client_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.142 — Accetta CSV per cli/proj (multiselect autocomplete).
    Fix bug: UI inviava "1,2,3" come stringa, FastAPI parser int rifiutava → 422.
    Ora supporto CSV: backend parsa lista e usa IN clause invece di =.
    """
    def _parse_csv_ids(v: Optional[str]) -> Optional[list[int]]:
        if not v:
            return None
        try:
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        except ValueError:
            return None
    pids = _parse_csv_ids(project_id)
    cids = _parse_csv_ids(client_id)
    return cashflow_year_sync(year, pids, cids, db)


@router.get("/api/cashflow/{year}/by-department")
async def cashflow_by_department(
    year: int,
    project_id: Optional[str] = None,
    client_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.123 (F19) — Breakdown annuale per Department.
    Revenue side: Invoice → JCLBilledSlice → JobCostLine → PriceItem.department_id.
    Cost side (supplier): SupplierInvoice → Resource → Resource.department_id.
    Annuale (no mensile per ora) per evitare query O(N×12) sul DB.
    Ritorna sia campi total (IVA inclusa) sia _net (imponibile). UI sceglie
    via toggle Mostra IVA.

    v3.5.0-alpha.170 — Accetta i filtri client_id/project_id (CSV) per
    coerenza con /api/cashflow/{year}. Pre-α.170 lo split per reparto
    mostrava sempre TUTTI i progetti/clienti del tenant → user percepiva
    "filtri non funzionano" (i totali in alto cambiavano, il breakdown no).
    """
    from app.models import (
        JCLBilledSlice, JobCostLine as _JCL, Department, Resource, PriceItem,
    )
    from sqlalchemy import extract, func as _func, case as _case
    tid = current_tenant_id()
    def _parse_csv_ids(v: Optional[str]) -> Optional[list[int]]:
        if not v:
            return None
        try:
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        except ValueError:
            return None
    pids = _parse_csv_ids(project_id)
    cids = _parse_csv_ids(client_id)
    # v3.5.0-alpha.125 (P2.B precision) — revenue_net calcolato preciso per
    # slice via ratio (subtotal/total) di ogni invoice, invece di /1.22 medio.
    # Espressione: Σ (slice.billed_amount × invoice.subtotal / invoice.total)
    # Per invoice con total=0 (caso degenerato): fallback a billed_amount/1.22.
    ratio_net_expr = _case(
        (Invoice.total > 0, JCLBilledSlice.billed_amount * Invoice.subtotal / Invoice.total),
        else_=JCLBilledSlice.billed_amount / 1.22,
    )
    rev_q = (
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
    )
    # v3.5.0-alpha.170 — Filtri cliente/progetto via Invoice.client_id / Invoice.job → Job.project_id
    if cids:
        rev_q = rev_q.filter(Invoice.client_id.in_(cids))
    if pids:
        rev_q = rev_q.join(Job, Invoice.job_id == Job.id).filter(Job.project_id.in_(pids))
    revenue_rows = rev_q.group_by(Department.id, Department.name).all()
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
    cost_q = (
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
    )
    # v3.5.0-alpha.170 — Filtri cliente/progetto. SupplierInvoice ha project_id
    # diretto (denormalizzato) + job_id opzionale; cliente derivabile solo via job.
    from sqlalchemy import or_ as _or
    if cids or pids:
        cost_q = cost_q.outerjoin(Job, SupplierInvoice.job_id == Job.id)
        if cids:
            cost_q = cost_q.filter(Job.client_id.in_(cids))
        if pids:
            cost_q = cost_q.filter(_or(
                SupplierInvoice.project_id.in_(pids),
                Job.project_id.in_(pids),
            ))
    cost_rows = cost_q.group_by(Resource.department_id).all()
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
    year: int, project_id, client_id, db: Session,
):
    # v3.5.0-alpha.142 — Accetta sia int singolo (back-compat) sia lista/CSV
    def _to_id_list(v):
        if v is None or v == "":
            return None
        if isinstance(v, list):
            return [int(x) for x in v if x]
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            try:
                return [int(x.strip()) for x in v.split(",") if x.strip()]
            except ValueError:
                return None
        return None
    project_ids = _to_id_list(project_id)
    client_ids = _to_id_list(client_id)
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
    if client_ids:
        inv_q = inv_q.filter(Invoice.client_id.in_(client_ids))
    if project_ids:
        # v3.5.0-alpha.172.103 — Fix Matteo: filtro progetto usava SOLO join via
        # Job, ma molte Invoice (es. acconti, kind=advance) hanno project_id
        # denormalizzato diretto con job_id=NULL. Il vecchio filtro escludeva
        # tutto -> "filtri progetto = tutto a 0". Ora outer-join + OR su
        # Invoice.project_id direct OR Job.project_id.
        from sqlalchemy import or_ as _or
        inv_q = inv_q.outerjoin(Job, Invoice.job_id == Job.id).filter(
            _or(
                Invoice.project_id.in_(project_ids),
                Job.project_id.in_(project_ids),
            )
        )
    invoices = inv_q.all()
    invoice_ids = [i.id for i in invoices]

    # v3.5.0-alpha.172.103 — Fix Matteo: cancelled "orfane" gonfiavano cashflow.
    # Regola contabile italiana: TD01 cancelled DEVE restare nel cashflow del suo
    # mese SOLO se esiste NC TD04 corrispondente (la NC storna nel mese suo, saldo
    # netto annuale = 0). Senza NC, la cancelled e' annullamento amministrativo
    # extra-contabile e NON deve contare (= dato sporco).
    # Matching NC<->TD01: stesso client_id, stesso total (tolleranza 0.01),
    # NC issue_date >= TD01 issue_date. Heuristico ma robusto in mancanza di FK.
    # Una NC consuma una TD01 (1:1), no double-count.
    def extract_year_safe(d):
        return d.year if d else None
    all_inv_for_match = db.query(Invoice).filter(
        Invoice.status != InvoiceStatus.draft,
    ).all()
    td04_by_client: dict = {}
    for nc in all_inv_for_match:
        if getattr(nc, "doc_type", None) != "TD04":
            continue
        if not nc.issue_date:
            continue
        td04_by_client.setdefault(nc.client_id, []).append(nc)
    # Set di TD01 cancelled stornate (id) — costruito greedy: per ogni NC, trova
    # la TD01 cancelled non-ancora-matchata con stesso client+total+issue_date
    # precedente o uguale.
    stornata_ids: set = set()
    consumed_nc_ids: set = set()
    td01_id_to_nc_id: dict = {}  # mapping per re-include NC sotto filtro project
    cancelled_td01 = [
        i for i in all_inv_for_match
        if i.status == InvoiceStatus.cancelled
        and getattr(i, "doc_type", None) != "TD04"
        and i.issue_date is not None
    ]
    for td01 in cancelled_td01:
        candidates = td04_by_client.get(td01.client_id, [])
        for nc in candidates:
            if nc.id in consumed_nc_ids:
                continue
            if abs((nc.total or 0.0) - (td01.total or 0.0)) > 0.01:
                continue
            if nc.issue_date < td01.issue_date:
                continue
            stornata_ids.add(td01.id)
            consumed_nc_ids.add(nc.id)
            td01_id_to_nc_id[td01.id] = nc.id
            break

    # v3.5.0-alpha.172.103 fix 2/2 — Re-include NC TD04 quando la TD01 stornata
    # passa il filtro corrente. Senza questo, filtro project_id=X include la TD01
    # (project_id valorizzato) ma NON la NC (project_id NULL spesso) → saldo
    # rimane positivo fantasma (= valore TD01 senza la NC che la storna).
    nc_by_id = {nc.id: nc for nc in all_inv_for_match if getattr(nc, "doc_type", None) == "TD04"}
    invoice_ids_set = set(invoice_ids)
    for td01 in invoices:
        if td01.id in stornata_ids:
            nc_id = td01_id_to_nc_id.get(td01.id)
            if nc_id and nc_id not in invoice_ids_set:
                nc = nc_by_id.get(nc_id)
                if nc and extract_year_safe(nc.issue_date) == year:
                    invoices.append(nc)
                    invoice_ids.append(nc.id)
                    invoice_ids_set.add(nc.id)

    invoices_missing_date: list[int] = []
    cancelled_orphan_ids: list[int] = []
    for inv in invoices:
        if not inv.issue_date:
            # v3.5.0-alpha.142 (#3 cashflow fix) — Invoice senza issue_date
            # (incluse NC TD04 mal-create) NON vengono buccatate in gennaio
            # fallback. Skip + log. UI mostrerà notice "N fatture senza data
            # — escluse dal cashflow, vai a /finance#invoices per correggere".
            invoices_missing_date.append(inv.id)
            continue
        m = inv.issue_date.month
        doc_t = getattr(inv, "doc_type", None)
        # v3.5.0-alpha.172.103 — TD01 cancelled SENZA NC corrispondente: skip
        # dal calcolo invoiced (dato sporco / annullamento extra-contabile).
        if (inv.status == InvoiceStatus.cancelled
                and doc_t != "TD04"
                and inv.id not in stornata_ids):
            cancelled_orphan_ids.append(inv.id)
            continue
        # v3.5.0-alpha.114 — include anche cancelled (post-storno): la fattura
        # originale resta nel cashflow storico del suo mese di emissione, e
        # la NC TD04 storna come negativo nel mese del NC. Saldo finale netto.
        if inv.status in (InvoiceStatus.sent, InvoiceStatus.paid,
                          InvoiceStatus.overdue, InvoiceStatus.cancelled):
            sign = -1 if (doc_t == "TD04") else 1
            series[m - 1]["invoiced"] += sign * (inv.total or 0.0)
            series[m - 1]["invoiced_net"] += sign * (inv.subtotal or 0.0)
        # outstanding: NC TD04 non genera outstanding (è un credito, non un debito da incassare)
        # v3.5.0-alpha.172.42 — BUG FIX: outstanding ESCLUDE cancelled (era
        # solo paid). Fatture annullate via NC TD04 non sono debiti da
        # incassare. Matteo: filtro Fandango mostrava 57.528€ = 3×19176 net
        # delle 3 invoice cancelled, ma nessun progetto Fandango aveva
        # davvero importi in attesa. Coerente con sign=-1 dell'NC sopra che
        # storna l'invoiced; l'outstanding deve allinearsi.
        if getattr(inv, "doc_type", None) != "TD04":
            remaining = max(0.0, (inv.total or 0.0) - (inv.amount_paid or 0.0))
            if remaining > 0 and inv.status not in (InvoiceStatus.paid, InvoiceStatus.cancelled):
                series[m - 1]["outstanding"] += remaining
                # v3.5.0-alpha.123 (F16) — outstanding_net pro-quota
                total_v = inv.total or 0.0
                if total_v > 0:
                    ratio_net = (inv.subtotal or 0.0) / total_v
                    series[m - 1]["outstanding_net"] += remaining * ratio_net

    pay_q = db.query(InvoicePayment).filter(
        extract("year", InvoicePayment.payment_date) == year,
    )
    if client_ids or project_ids:
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
    if project_ids:
        sup_billed_q = sup_billed_q.filter(SupplierInvoice.project_id.in_(project_ids))
    elif client_ids:
        # SupplierInvoice non ha client_id diretto: join via job → client
        sup_billed_q = sup_billed_q.join(
            Job, SupplierInvoice.job_id == Job.id
        ).join(
            Project, Job.project_id == Project.id
        ).filter(Project.client_id.in_(client_ids))
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
    if client_ids or project_ids:
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
    if project_ids:
        sup_due_q = sup_due_q.filter(SupplierInvoice.project_id.in_(project_ids))
    elif client_ids:
        sup_due_q = sup_due_q.join(
            Job, SupplierInvoice.job_id == Job.id
        ).join(
            Project, Job.project_id == Project.id
        ).filter(Project.client_id.in_(client_ids))
    sup_due_rows = sup_due_q.all()
    for s in sup_due_rows:
        m = s.due_date.month if s.due_date else 1
        residuo = max(0.0, (s.amount_total or 0.0) - (s.amount_paid or 0.0))
        series[m - 1]["supplier_due"] += residuo
        if (s.amount_total or 0) > 0:
            ratio_net = (s.amount_net or 0.0) / s.amount_total
            series[m - 1]["supplier_due_net"] += residuo * ratio_net

    # v3.5.0-alpha.77 — Forecast pipeline (soft+committed+lost) per mese
    # v3.5.0-alpha.142 — passa primo id da lista (forecast non supporta multi)
    from app.services.quote_forecast import yearly_forecast
    _first_pid = project_ids[0] if project_ids else None
    _first_cid = client_ids[0] if client_ids else None
    fc = yearly_forecast(db, year, project_id=_first_pid, client_id=_first_cid)
    fc_by_month = {m["month"]: m for m in fc["months"]}

    # v3.5.0-alpha.87 (S8.4) — Overhead outflow per mese.
    # Solo overhead non legato a project (overhead tenant-pure). Quelli con
    # source_project_id si filtrano via project_id se richiesto.
    from app.models import OverheadCost
    oh_q = db.query(OverheadCost).filter(
        extract("year", OverheadCost.cost_date) == year,
        OverheadCost.deleted_at.is_(None),
    )
    if project_ids:
        oh_q = oh_q.filter(OverheadCost.source_project_id.in_(project_ids))
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
        # v3.5.0-alpha.142 (#3) — Invoice senza issue_date escluse dal cashflow
        # (no fallback gennaio fuorviante). UI mostra warning con link a /finance#invoices.
        "invoices_missing_date": invoices_missing_date,
        # v3.5.0-alpha.172.103 — Cancelled TD01 senza NC TD04 corrispondente
        # (matching heuristico client+total+date). Escluse dal cashflow per non
        # gonfiare i totali. UI dovrebbe mostrare warning con link a /finance#invoices.
        "cancelled_orphan_invoices": cancelled_orphan_ids,
    }


# ── Anomalie financial (v3.4.39) ──────────────────────────────────────


@router.get("/api/anomalies/floating-jobs")
async def list_floating_jobs(db: Session = Depends(get_db)):
    """Job senza quote_id (orfani). Possono nascere da migrazione versioning con
    `orphan_strategy=floating_job`, o da cancellazione manuale della quote.

    Ritorna la lista per la sezione Anomalie di /finance, e per generare
    notifiche `job_floating_alert` periodiche.

    v3.5.0-alpha.172.35 (Sprint 1) — tenant scope (era leak)."""
    jobs = (
        scoped(
            db.query(Job).options(
                joinedload(Job.project), joinedload(Job.client), joinedload(Job.cost_lines)
            ),
            Job,
        )
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

    # v3.5.0-alpha.172.35 (Sprint 1) — tenant scope (era leak)
    cost_lines = (
        scoped(
            db.query(JobCostLine).options(
                joinedload(JobCostLine.job).joinedload(Job.project)
            ),
            JobCostLine,
        )
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
    # v3.5.0-alpha.172.60 — Intestazione fattura completa FatturaPA-compliant:
    # indirizzo destinatario + CAP/comune/provincia + P.IVA/CF + PEC/SDI.
    # Preferisce snapshot (immutabili) con fallback live al cliente attuale.
    def _snap_or_live(snap_field: str, live_field: str):
        s = getattr(inv, snap_field, None)
        if s:
            return s
        return getattr(inv.client, live_field, None) if inv.client else None
    cli_addr = _snap_or_live("client_address_snap", "address")
    cli_zip = _snap_or_live("client_zip_snap", "zip_code")
    cli_city = _snap_or_live("client_city_snap", "city")
    cli_prov = _snap_or_live("client_province_snap", "province")
    cli_country = _snap_or_live("client_country_snap", "country") or "IT"
    cli_vat = _snap_or_live("client_vat_snap", "vat_number")
    cli_cf = _snap_or_live("client_tax_code_snap", "tax_code")
    cli_pec = _snap_or_live("client_pec_snap", "pec")
    cli_sdi = _snap_or_live("client_sdi_snap", "sdi_code")
    # Linea indirizzo: "Via, 123 — 20121 Milano (MI), IT"
    addr_bits = []
    if cli_addr:
        addr_bits.append(cli_addr.strip())
    loc_bits = []
    if cli_zip: loc_bits.append(cli_zip.strip())
    if cli_city: loc_bits.append(cli_city.strip())
    if cli_prov: loc_bits.append(f"({cli_prov.strip()})")
    if loc_bits:
        addr_bits.append(" ".join(loc_bits))
    if cli_country and cli_country.upper() != "IT":
        addr_bits.append(cli_country.upper())
    client_info_parts = []
    if addr_bits:
        client_info_parts.append(" — ".join(addr_bits))
    fiscal_bits = []
    if cli_vat: fiscal_bits.append(f"P.IVA {cli_vat}")
    if cli_cf and cli_cf != cli_vat: fiscal_bits.append(f"C.F. {cli_cf}")
    if fiscal_bits:
        client_info_parts.append(" · ".join(fiscal_bits))
    if cli_sdi:
        client_info_parts.append(f"SDI: {cli_sdi}")
    elif cli_pec:
        client_info_parts.append(f"PEC: {cli_pec} · SDI: 0000000")
    if admin_email:
        client_info_parts.append(f"Att.ne Amministrazione · {admin_email}")
    invoice_data = {
        "number":            inv.number,
        "issue_date":        inv.issue_date.strftime("%d/%m/%Y") if inv.issue_date else "—",
        "due_date":          inv.due_date.strftime("%d/%m/%Y") if inv.due_date else None,
        "client_name":       inv.client.name if inv.client else "—",
        "client_info":       "<br/>".join(client_info_parts),
        "subtotal":          inv.subtotal,
        "vat_rate":          inv.vat_rate,
        "total":             inv.total,
        "notes":             inv.notes,
        "is_closing":        bool(getattr(inv, "is_closing", False)),
        # v3.5.0-alpha.172.156 Task 10 — valuta display PDF
        "currency":          getattr(inv, "currency", "EUR") or "EUR",
        "fx_rate_to_base":   getattr(inv, "fx_rate_to_base", 1.0) or 1.0,
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


# ── SAL — Stato Avanzamento Lavori (v3.5.0-alpha.172.217) ──────────────
# Vista read-only ore quotate/pianificate/lavorate + temporale. Gate
# view_finance come le altre pagine/API finance. Riusa app.services.sal_metrics.

RequireViewFinance = Depends(requires_permission("view_finance"))


@router.get("/sal", response_class=HTMLResponse, dependencies=[RequireViewFinance])
async def sal_page(request: Request, db: Session = Depends(get_db)):
    """Pagina SAL (tab Per progetto / Temporale). Read-only."""
    return _tpl().TemplateResponse("pages/sal.html", {"request": request})


@router.get("/api/sal/projects", dependencies=[RequireViewFinance])
async def sal_projects(
    status: Optional[str] = None,
    client_id: Optional[int] = None,
    q: Optional[str] = None,
    alarm_only: Optional[bool] = False,
    db: Session = Depends(get_db),
):
    """Lista righe progetto col monte ore q/p/l, % avanzamento, allarme.

    Tenant-scoped, progetti cestinati esclusi (deleted_at IS NULL). Batch
    pre-fetch (no N+1): client + jobs + cost_lines + price_item + quote +
    bookings → assignments → resource. Filtri SQL (status/client_id/q);
    alarm_only filtrato in Python (deriva da project_metrics).
    """
    from sqlalchemy import or_
    from app.models import Project, Job, Booking, BookingAssignment
    from app.services import sal_metrics

    query = (
        db.query(Project)
        .options(
            joinedload(Project.client),
            joinedload(Project.jobs).joinedload(Job.cost_lines).joinedload(JobCostLine.price_item),
            joinedload(Project.jobs).joinedload(Job.quote),
            joinedload(Project.jobs)
            .joinedload(Job.bookings)
            .joinedload(Booking.assignments)
            .joinedload(BookingAssignment.resource),
        )
        .filter(
            Project.tenant_id == current_tenant_id(),
            Project.deleted_at.is_(None),
        )
    )
    if client_id:
        query = query.filter(Project.client_id == client_id)
    if status:
        query = query.filter(Project.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Project.code.ilike(like), Project.title.ilike(like)))

    rows = []
    for prj in query.order_by(Project.created_at.desc()).all():
        m = sal_metrics.project_metrics(db, prj)
        if alarm_only and m["alarm"] == "none":
            continue
        # Quotazioni distinte dei job del progetto.
        seen: set = set()
        quotes = []
        for job in (prj.jobs or []):
            qt = getattr(job, "quote", None)
            if qt is not None and qt.id not in seen:
                seen.add(qt.id)
                quotes.append({"number": qt.number, "title": qt.title})
        rows.append({
            "id": prj.id,
            "code": prj.code,
            "title": prj.title,
            "client": prj.client.name if prj.client else None,
            "quotes": quotes,
            "quoted": m["quoted"],
            "planned": m["planned"],
            "worked": m["worked"],
            "pct": m["pct"],
            "alarm": m["alarm"],
            "job_count": m["job_count"],
        })
    return rows


@router.get("/api/sal/projects/{project_id}/detail", dependencies=[RequireViewFinance])
async def sal_project_detail(
    project_id: int,
    db: Session = Depends(get_db),
):
    """Drill-down progetto: breakdown reparto + lista job. 404 cross-tenant."""
    from app.models import Project, Job, Booking, BookingAssignment, Department
    from app.services import sal_metrics

    prj = (
        db.query(Project)
        .options(
            joinedload(Project.jobs).joinedload(Job.cost_lines).joinedload(JobCostLine.price_item),
            joinedload(Project.jobs).joinedload(Job.quote),
            joinedload(Project.jobs)
            .joinedload(Job.bookings)
            .joinedload(Booking.assignments)
            .joinedload(BookingAssignment.resource),
        )
        .filter(
            Project.id == project_id,
            Project.tenant_id == current_tenant_id(),
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if prj is None:
        raise HTTPException(404, "Progetto non trovato")

    # Aggrega breakdown reparto su tutti i job del progetto.
    dept_acc: dict = {}
    jobs_out = []
    for job in (prj.jobs or []):
        daily = sal_metrics._daily_hours_for_job(db, job)
        bd = sal_metrics.by_department(job, daily_hours=daily)
        for dep_id, vals in bd.items():
            acc = dept_acc.setdefault(
                dep_id, {"quoted": 0.0, "planned": 0.0, "worked": 0.0}
            )
            acc["quoted"] += vals["quoted"]
            acc["planned"] += vals["planned"]
            acc["worked"] += vals["worked"]
        jm = sal_metrics.job_metrics(job, daily_hours=daily)
        qt = getattr(job, "quote", None)
        jobs_out.append({
            "id": job.id,
            "code": job.code,
            "title": job.title,
            "quote_number": qt.number if qt is not None else None,
            "quoted": jm["quoted"],
            "planned": jm["planned"],
            "worked": jm["worked"],
            "pct": jm["pct"],
            "alarm": jm["alarm"],
        })

    # Nomi reparto in batch (0 → "Altro").
    dep_ids = [d for d in dept_acc.keys() if d]
    name_map: dict = {}
    if dep_ids:
        for d in (
            db.query(Department)
            .filter(
                Department.id.in_(dep_ids),
                Department.tenant_id == current_tenant_id(),
            )
            .all()
        ):
            name_map[d.id] = d.name
    departments = []
    for dep_id, vals in dept_acc.items():
        departments.append({
            "department_id": dep_id,
            "name": name_map.get(dep_id, "Altro") if dep_id else "Altro",
            "quoted": vals["quoted"],
            "planned": vals["planned"],
            "worked": vals["worked"],
        })

    return {"departments": departments, "jobs": jobs_out}


@router.get("/api/sal/timeline", dependencies=[RequireViewFinance])
async def sal_timeline(
    year: Optional[int] = None,
    granularity: str = "month",
    db: Session = Depends(get_db),
):
    """Vista temporale mese/trimestre: pianificate/lavorate/fatturato/%."""
    from app.services import sal_metrics
    if year is None:
        year = date.today().year
    return sal_metrics.timeline_metrics(db, year=year, granularity=granularity)


@router.get("/api/sal/matrix", dependencies=[RequireViewFinance])
async def sal_matrix(
    year: Optional[int] = None,
    granularity: str = "month",
    db: Session = Depends(get_db),
):
    """Calendario SAL: righe progetti × colonne mesi/trimestri, cella = %
    cumulativa a fine periodo (lavorate cumulate / quotate totali)."""
    from app.services import sal_metrics
    if year is None:
        year = date.today().year
    return sal_metrics.matrix_metrics(db, year=year, granularity=granularity)
