"""Router quotazioni — ora ancorate al Progetto."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import (
    Quote, QuoteLine, Job, JobStatus, QuoteStatus,
    PriceItem, PriceCategory, PriceLevel, Project,
    Booking, BookingStatus, JobCostLine, TimePunch,
)

router = APIRouter(prefix="/quotes", tags=["quotes"])

CATEGORY_FALLBACK = "Altro"


def _next_job_code(db: Session, project: Project) -> str:
    """Genera codice job '{PROJECT_CODE}-J{N}' progressivo per quel progetto."""
    base = (project.code or f"P{project.id}").strip()
    existing = db.query(Job).filter(Job.project_id == project.id).all()
    n = 1
    used = {j.code for j in existing if j.code}
    while f"{base}-J{n}" in used:
        n += 1
    return f"{base}-J{n}"


def _create_job_from_quote(db: Session, q: Quote) -> Job:
    """Crea il Job dalla Quote approvata + JobCostLine da ogni QuoteLine.

    Eredita titolo dal progetto (non dalla quote: spesso coincidono ma il
    riferimento canonico è il progetto). Codice auto-generato {PROJECT}-J{N}.
    Idempotenza: se la quote ha già `q.job` ritorna quello.
    """
    if q.job:
        # Job già collegato: se cancelled lo ri-attivo (riapprovazione della stessa quote
        # dopo un rollback). Se in qualunque altro stato lo ritorno così com'è.
        if q.job.status == JobStatus.cancelled:
            q.job.status = JobStatus.approved
        return q.job
    project = q.project
    if not project:
        raise HTTPException(400, "Quote senza progetto: impossibile promuovere a job")

    job = Job(
        code=_next_job_code(db, project),
        title=project.title,
        project_id=q.project_id,
        client_id=q.client_id,
        quote_id=q.id,
        status=JobStatus.approved,
        budget_quoted=q.total_after_discount,
    )
    db.add(job)
    db.flush()
    for line in q.lines:
        db.add(JobCostLine(
            job_id=job.id,
            quote_line_id=line.id,
            price_item_id=line.price_item_id,
            description=line.description,
            quantity_quoted=line.quantity,
            unit=line.unit,
            unit_price=line.unit_price,
            total_quoted=line.total,
            total_expected=line.total,
        ))
    return job


def _job_has_activity(db: Session, job: Job) -> bool:
    """True se il job ha booking non-cancelled o TimePunch effettivi."""
    active_bk = db.query(Booking).filter(
        Booking.job_id == job.id,
        Booking.status != BookingStatus.cancelled,
    ).first()
    if active_bk:
        return True
    punch = db.query(TimePunch).filter(TimePunch.job_id == job.id).first()
    return punch is not None


def _tpl():
    from app.main import templates
    return templates


def _line_category(line: QuoteLine) -> str:
    """Categoria per il raggruppamento (editor / PDF / export).
    Se `category_override` è valorizzato, prevale su quello del price_item.
    """
    override = (line.category_override or "").strip()
    if override:
        return override
    if line.price_item and line.price_item.category:
        return line.price_item.category.name
    return CATEGORY_FALLBACK


def _recalc_quote(quote: Quote) -> None:
    """
    Cascata sconti:
      1. line_total = qty × unit_price × (1 + allowance) × (1 − line_discount_pct)
      2. subtotal_gross = Σ qty × unit_price × (1 + allowance)        (no sconti)
      3. categoria_subtotale = Σ line_total per categoria
      4. categoria_totale = categoria_subtotale × (1 − category_discount_pct)
      5. subtotal = Σ categoria_totale                                  (post line + cat)
      6. total_after_discount = subtotal × (1 + package_discount)       (package è negativo per retrocompat)
      7. total_with_vat = total_after_discount × (1 + vat_rate/100)

    v3.5.0-alpha.27: le righe con `is_optional=True` hanno il proprio
    `total` calcolato ma NON contribuiscono a subtotal_gross / cat_buckets /
    subtotal / total_after_discount / total_with_vat. Sono mostrate in un
    blocco "Optional aggiuntivi" separato (UI + PDF).
    """
    cat_disc = quote.category_discounts or {}
    subtotal_gross = 0.0
    cat_buckets: dict[str, float] = {}

    for l in quote.lines:
        gross = (l.quantity or 0.0) * (l.unit_price or 0.0) * (1 + (l.allowance or 0.0))
        net_after_line = gross * (1 - (l.line_discount_pct or 0.0))
        l.total = round(net_after_line, 2)
        if l.is_optional:
            continue  # totale calcolato ma fuori dai subtotali
        subtotal_gross += gross
        cat_key = _line_category(l)
        cat_buckets[cat_key] = cat_buckets.get(cat_key, 0.0) + net_after_line

    subtotal_after_cat = sum(
        bucket * (1 - float(cat_disc.get(cat_key, 0.0)))
        for cat_key, bucket in cat_buckets.items()
    )

    total_after = subtotal_after_cat * (1 + (quote.package_discount or 0.0))
    total_with_vat = total_after * (1 + (quote.vat_rate or 0.0) / 100)

    quote.subtotal_gross = round(subtotal_gross, 2)
    quote.subtotal = round(subtotal_after_cat, 2)
    quote.total_after_discount = round(total_after, 2)
    quote.total_with_vat = round(total_with_vat, 2)


@router.get("/", response_class=HTMLResponse)
async def quotes_page(request: Request, db: Session = Depends(get_db)):
    quotes = db.query(Quote).options(
        joinedload(Quote.client),
        joinedload(Quote.project),
    ).order_by(Quote.created_at.desc()).all()
    projects = db.query(Project).options(joinedload(Project.client)).order_by(Project.title).all()
    return _tpl().TemplateResponse(
        "pages/quotes.html",
        {"request": request, "quotes": quotes, "projects": projects},
    )


@router.get("/api")
async def list_quotes(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Quote).options(joinedload(Quote.client), joinedload(Quote.project))
    if project_id:
        q = q.filter(Quote.project_id == project_id)
    qs = q.order_by(Quote.created_at.desc()).all()
    return [
        {
            "id": q.id, "number": q.number, "version": q.version,
            "title": q.title, "status": q.status,
            "project_id": q.project_id,
            "project_title": q.project.title if q.project else None,
            "client": q.client.name if q.client else None,
            "issue_date": str(q.issue_date),
            "valid_until": str(q.valid_until) if q.valid_until else None,
            "subtotal": q.subtotal,
            "total_after_discount": q.total_after_discount,
            "total_with_vat": q.total_with_vat,
            "has_job": q.job is not None,
            "from_deliverables": q.generated_from_deliverables,
        }
        for q in qs
    ]


@router.get("/api/{quote_id}/booking-lines")
async def get_quote_booking_lines(
    quote_id: int,
    dept_ids: Optional[str] = None,  # CSV "1,2,3"
    db: Session = Depends(get_db),
):
    """Linee selezionabili in un booking, partendo dalla quote (v3.4.53).

    Ritorna le lavorazioni della quote filtrate per reparto delle risorse
    selezionate (passate in `dept_ids` come CSV). Job nascosto: l'UI booking
    parla solo in termini di quote+lavorazione.

    Modalità:
    - quote `approved` con Job: ritorna `JobCostLine` (kind=cost_line)
    - quote `draft|sent`: ritorna `QuoteLine` (kind=quote_line) — il booking save
      farà reverse-attach implicito al primo uso (approva la quote, crea il
      JobCostLine, link al booking)

    Filtro dept: include linee con `price_item.department_id ∈ dept_ids` o NULL
    (voce non assegnata a reparto = visibile a tutti). Se `dept_ids` vuoto,
    nessun filtro reparto applicato.
    """
    quote = db.query(Quote).options(
        joinedload(Quote.lines).joinedload(QuoteLine.price_item),
        joinedload(Quote.job).joinedload(Job.cost_lines),
    ).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(404, "Quote non trovata")

    dept_set: Optional[set[int]] = None
    if dept_ids:
        try:
            dept_set = {int(x) for x in dept_ids.split(",") if x.strip()}
        except ValueError:
            raise HTTPException(400, "dept_ids deve essere CSV di interi")

    def _dept_match(price_item) -> bool:
        if dept_set is None:
            return True
        if price_item is None:
            return True  # riga senza price_item → sempre visibile
        pid = getattr(price_item, "department_id", None)
        return pid is None or pid in dept_set

    out = []
    if quote.status == QuoteStatus.approved and quote.job:
        # JobCostLines (canoniche per quote già approvata)
        # Carico esplicitamente price_item su ogni cost line (la relationship esiste in v3.4.33)
        from app.models import PriceItem
        pi_ids = {l.price_item_id for l in quote.job.cost_lines if l.price_item_id}
        pi_map = {}
        if pi_ids:
            pis = db.query(PriceItem).options(joinedload(PriceItem.department)).filter(PriceItem.id.in_(pi_ids)).all()
            pi_map = {p.id: p for p in pis}
        for ln in quote.job.cost_lines:
            pi = pi_map.get(ln.price_item_id) if ln.price_item_id else None
            if not _dept_match(pi):
                continue
            dept = getattr(pi, "department", None) if pi else None
            out.append({
                "id": ln.id, "kind": "cost_line",
                "description": ln.description,
                "unit": ln.unit, "quantity_quoted": ln.quantity_quoted,
                "is_extra": ln.is_extra,
                "department_id": dept.id if dept else None,
                "department_name": dept.name if dept else None,
                "department_color": dept.color if dept else None,
            })
    else:
        # QuoteLines (la quote è ancora in trattativa). Il booking save attiverà
        # reverse-attach implicit-approval per materializzare la JobCostLine.
        for ln in quote.lines:
            pi = ln.price_item
            if not _dept_match(pi):
                continue
            dept = getattr(pi, "department", None) if pi else None
            out.append({
                "id": ln.id, "kind": "quote_line",
                "description": ln.description,
                "unit": ln.unit, "quantity_quoted": ln.quantity,
                "is_extra": False,
                "department_id": dept.id if dept else None,
                "department_name": dept.name if dept else None,
                "department_color": dept.color if dept else None,
            })

    return {
        "quote_id": quote.id, "quote_number": quote.number,
        "quote_status": quote.status.value if hasattr(quote.status, "value") else str(quote.status),
        "is_phantom": getattr(quote, "is_phantom", False),
        "has_job": quote.job is not None,
        "job_id": quote.job.id if quote.job else None,
        "job_code": quote.job.code if quote.job else None,
        "filter_dept_ids": sorted(dept_set) if dept_set else None,
        "lines": out,
    }


@router.post("/api/{quote_id}/promote-line-to-cost-line")
async def promote_line_to_cost_line(
    quote_id: int,
    request: Request,
    quote_line_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Materializza una QuoteLine → JobCostLine al volo (v3.4.53).

    Usato dal modal booking quando l'utente seleziona una linea di una quote
    in trattativa (`draft|sent`) come bersaglio del booking. Effetti:
    - Se la quote è in `draft|sent`: approva implicitamente + notifica AM
      (kind=quote_reverse_approval, severity=action_required)
    - Crea il Job (forward-flow standard) se manca
    - Crea la JobCostLine corrispondente alla QuoteLine se manca
    - Idempotente: se tutto esiste già, no-op + ritorna gli ID

    Ritorna `{quote_id, job_id, cost_line_id, was_implicit_approval}` per il
    binding diretto del booking.
    """
    from app.services.rbac import current_user_optional
    actor = current_user_optional(request)

    quote = db.query(Quote).options(
        joinedload(Quote.lines).joinedload(QuoteLine.price_item),
        joinedload(Quote.job).joinedload(Job.cost_lines),
        joinedload(Quote.project),
    ).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(404, "Quote non trovata")

    line = next((ln for ln in quote.lines if ln.id == quote_line_id), None)
    if not line:
        raise HTTPException(404, "QuoteLine non trovata in questa quote")

    was_implicit = False
    prev_status = quote.status
    if quote.status in (QuoteStatus.draft, QuoteStatus.sent):
        quote.status = QuoteStatus.approved
        was_implicit = True

    job = _create_job_from_quote(db, quote)  # idempotente
    db.flush()

    # Trova o crea la JobCostLine corrispondente alla QuoteLine
    jcl = db.query(JobCostLine).filter(
        JobCostLine.quote_line_id == line.id, JobCostLine.job_id == job.id
    ).first()
    if not jcl:
        jcl = JobCostLine(
            job_id=job.id,
            quote_line_id=line.id,
            price_item_id=line.price_item_id,
            description=line.description,
            quantity_quoted=line.quantity,
            unit=line.unit,
            unit_price=line.unit_price,
            total_quoted=line.total,
            total_expected=line.total,
        )
        db.add(jcl)
        db.flush()

    db.commit()
    db.refresh(quote); db.refresh(job); db.refresh(jcl)

    if was_implicit:
        try:
            from app.services.notifications import notify_permission
            from app.models import NotificationKind, NotificationSeverity
            notify_permission(
                db,
                permission="edit_quotes",
                exclude_user_ids=[actor.id] if actor else None,
                kind=NotificationKind.quote_reverse_approval.value,
                severity=NotificationSeverity.action_required.value,
                title=f"Quote {quote.number} approvata implicitamente (booking → linea)",
                body=(
                    f"Booking su progetto '{quote.project.title if quote.project else '?'}' "
                    f"ha attivato la linea '{line.description}' (€ {line.total:.2f}). "
                    f"Stato precedente: {prev_status.value}. Verifica e attiva eventualmente "
                    f"procedure di migrate-job o versioning standard."
                ),
                link=f"/quotes#{quote.id}",
                payload={
                    "quote_id": quote.id, "quote_number": quote.number,
                    "job_id": job.id, "line_id": line.id,
                    "previous_status": prev_status.value,
                },
                actor_user_id=actor.id if actor else None,
            )
        except Exception as e:
            print(f"[promote-line] notify failed: {e}")

    return {
        "quote_id": quote.id, "quote_number": quote.number,
        "quote_status": quote.status.value,
        "previous_status": prev_status.value,
        "job_id": job.id, "job_code": job.code,
        "cost_line_id": jcl.id,
        "cost_line_description": jcl.description,
        "was_implicit_approval": was_implicit,
    }


@router.post("/api/reverse-attach")
async def reverse_attach(
    request: Request,
    project_id: int = Form(...),
    mode: str = Form(...),  # "attach_existing" | "create_phantom"
    target_quote_id: Optional[int] = Form(None),
    price_item_id: int = Form(...),
    booking_hours: float = Form(0.0),  # somma ore-persona del booking corrente
    quantity_override: Optional[float] = Form(None),
    phantom_title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Reverse-flow v3.4.52: booking su progetto senza quote attiva.

    - mode="attach_existing": riga aggiunta a quote draft|sent → approvazione
      implicita → ensure Job → notifica account managers (edit_quotes).
    - mode="create_phantom": crea Quote(is_phantom=True, status=approved) +
      una line + Job auto-creato → notifica account managers.

    Quantità: se quantity_override è valorizzato lo usa, altrimenti la deriva
    da booking_hours secondo l'unità della voce listino.
    """
    from app.services.rbac import current_user_optional
    from app.services.reverse_quote import (
        attach_to_pending_quote, compute_quantity_from_hours,
        create_phantom_quote_with_line,
    )
    actor = current_user_optional(request)

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Progetto non trovato")
    pi = db.query(PriceItem).filter(PriceItem.id == price_item_id).first()
    if not pi:
        raise HTTPException(404, "Voce listino non trovata")

    qty = float(quantity_override) if quantity_override is not None else compute_quantity_from_hours(
        float(booking_hours or 0.0), pi.unit or "day"
    )
    if qty <= 0:
        raise HTTPException(400, "quantity calcolata <= 0: passa booking_hours o quantity_override > 0")

    if mode == "attach_existing":
        if not target_quote_id:
            raise HTTPException(400, "target_quote_id richiesto in mode=attach_existing")
        result = attach_to_pending_quote(
            db, target_quote_id, project_id, price_item_id, qty, actor=actor,
        )
    elif mode == "create_phantom":
        result = create_phantom_quote_with_line(
            db, project, price_item_id, qty, title=phantom_title, actor=actor,
        )
    else:
        raise HTTPException(400, "mode deve essere 'attach_existing' o 'create_phantom'")

    result["client_name"] = project.client.name if project.client else None
    result["project_code"] = project.code
    result["project_title"] = project.title
    result["computed_quantity"] = qty
    result["price_item_unit"] = pi.unit
    return result


@router.post("/api")
async def create_quote(
    number: str = Form(...),
    project_id: int = Form(...),
    title: str = Form(...),
    issue_date: date = Form(...),
    valid_until: Optional[date] = Form(None),
    production_material: Optional[str] = Form(None),
    length_minutes: Optional[float] = Form(None),
    fps: Optional[str] = Form(None),
    delivery_format: Optional[str] = Form(None),
    shooting_days: Optional[int] = Form(None),
    package_discount: float = Form(0.0),
    vat_rate: float = Form(22.0),
    notes: Optional[str] = Form(None),
    payment_terms: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Progetto non trovato")
    q = Quote(
        number=number, project_id=project_id, client_id=project.client_id,
        title=title, issue_date=issue_date, valid_until=valid_until,
        production_material=production_material or project.shooting_format,
        length_minutes=length_minutes or project.length_minutes,
        fps=fps or project.fps,
        delivery_format=delivery_format or project.delivery_format,
        shooting_days=shooting_days,
        package_discount=package_discount, vat_rate=vat_rate,
        notes=notes, payment_terms=payment_terms,
    )
    db.add(q); db.commit(); db.refresh(q)
    return {"id": q.id, "number": q.number}


@router.get("/api/{quote_id}")
async def get_quote(quote_id: int, db: Session = Depends(get_db)):
    q = db.query(Quote).options(
        joinedload(Quote.client), joinedload(Quote.project),
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category),
    ).filter(Quote.id == quote_id).first()
    if not q:
        raise HTTPException(404, "Quotazione non trovata")
    return {
        "id": q.id, "number": q.number, "version": q.version,
        "title": q.title, "status": q.status,
        "project_id": q.project_id,
        "project_title": q.project.title if q.project else None,
        "client_id": q.client_id,
        "client": q.client.name if q.client else None,
        "issue_date": str(q.issue_date),
        "valid_until": str(q.valid_until) if q.valid_until else None,
        "production_material": q.production_material,
        "length_minutes": q.length_minutes, "fps": q.fps,
        "delivery_format": q.delivery_format, "shooting_days": q.shooting_days,
        "package_discount": q.package_discount, "vat_rate": q.vat_rate,
        "category_discounts": q.category_discounts or {},
        "category_order": q.category_order or [],
        "subtotal_gross": q.subtotal_gross,
        "subtotal": q.subtotal,
        "total_after_discount": q.total_after_discount,
        "total_with_vat": q.total_with_vat,
        "notes": q.notes, "payment_terms": q.payment_terms,
        "generated_from_deliverables": q.generated_from_deliverables,
        "source_document_name": q.source_document_name,
        "subtotal_optional": round(
            sum((l.total or 0.0) for l in q.lines if l.is_optional), 2
        ),
        "lines": [
            {
                "id": l.id, "section": l.section, "position": l.position,
                "description": l.description, "detail": l.detail,
                "quantity": l.quantity, "unit": l.unit,
                "price_level": l.price_level, "unit_price": l.unit_price,
                "allowance": l.allowance,
                "line_discount_pct": l.line_discount_pct or 0.0,
                "total": l.total,
                "hardcosts": l.hardcosts, "sort_order": l.sort_order,
                "price_item_id": l.price_item_id,
                "category": _line_category(l),
                "category_override": l.category_override,
                "is_optional": bool(l.is_optional),
                "section_label": l.section_label or None,
            }
            for l in sorted(q.lines, key=lambda x: x.sort_order)
        ],
    }


@router.put("/api/{quote_id}/status")
async def update_quote_status(
    quote_id: int, status: QuoteStatus = Form(...), db: Session = Depends(get_db),
):
    """Aggiorna lo stato della quote.

    Side-effect: la transizione di stato gestisce automaticamente il Job collegato.
    - draft/sent → approved: crea il Job + JobCostLine (idempotente se già esiste)
    - approved → altro stato: cancella il Job se non ha attività; blocca con 400
      se ha booking attivi o TimePunch (preserva storico operativo).
    """
    q = (
        db.query(Quote)
        .options(joinedload(Quote.lines), joinedload(Quote.project), joinedload(Quote.job))
        .filter(Quote.id == quote_id)
        .first()
    )
    if not q:
        raise HTTPException(404)

    prev = q.status
    new = status
    promoted_job = None
    cancelled_job_id = None

    if new == QuoteStatus.approved and prev != QuoteStatus.approved:
        # Approvazione: crea il job se non esiste
        promoted_job = _create_job_from_quote(db, q)
        # v3.4.56 — warning non bloccante: se il job non ha JobResourceAssignment,
        # notifica chi può assegnare (producer/manager). Auto-assignment via booking
        # resta disponibile (richiesta conferma client-side).
        try:
            from app.models import JobResourceAssignment, NotificationKind, NotificationSeverity
            from app.services.notifications import notify_permission
            ass_count = db.query(JobResourceAssignment).filter(
                JobResourceAssignment.job_id == promoted_job.id
            ).count()
            if ass_count == 0:
                notify_permission(
                    db, permission="assign_resources",
                    kind=NotificationKind.quote_approved_no_resources.value,
                    severity=NotificationSeverity.action_required.value,
                    title=f"Quote {q.number} approvata: nessuna risorsa assegnata",
                    body=(
                        f"Il job {promoted_job.code} ({promoted_job.title}) è stato creato "
                        f"ma non ha ancora risorse assegnate. Aggiungile manualmente in "
                        f"/projects/{q.project_id} oppure scattano in automatico al primo "
                        f"booking (con richiesta di conferma)."
                    ),
                    link=f"/projects/{q.project_id}",
                    payload={
                        "quote_id": q.id, "quote_number": q.number,
                        "job_id": promoted_job.id, "job_code": promoted_job.code,
                        "project_id": q.project_id,
                    },
                )
        except Exception as e:
            print(f"[quote-approve] notify no_resources failed: {e}")
    elif prev == QuoteStatus.approved and new != QuoteStatus.approved and q.job:
        # Disapprovazione: cancella il job se senza attività, altrimenti blocca
        if _job_has_activity(db, q.job):
            raise HTTPException(
                400,
                f"Impossibile riportare la quote a '{new.value}': il job {q.job.code} "
                "ha attività (booking o timbrature). Cancella prima le attività."
            )
        cancelled_job_id = q.job.id
        q.job.status = JobStatus.cancelled

    q.status = new
    db.commit()

    resp = {"id": q.id, "status": q.status}
    if promoted_job:
        db.refresh(promoted_job)
        resp["job_created"] = {
            "id": promoted_job.id,
            "code": promoted_job.code,
            "title": promoted_job.title,
            "lines_count": len(q.lines),
        }
    if cancelled_job_id:
        resp["job_cancelled_id"] = cancelled_job_id
    return resp


@router.put("/api/{quote_id}")
async def update_quote(
    quote_id: int,
    request: Request,
    package_discount: Optional[float] = Form(None),
    vat_rate: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    payment_terms: Optional[str] = Form(None),
    # v3.5.0-alpha.7.5 — rinomina di title (sempre) e number (solo draft)
    title: Optional[str] = Form(None),
    number: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # v3.4.38 (R3.2): guard permission edit_quotes
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_quotes"):
        raise HTTPException(403, "Non hai il permesso di modificare le quotazioni")
    q = db.query(Quote).options(
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category)
    ).filter(Quote.id == quote_id).first()
    if not q: raise HTTPException(404)

    if title is not None:
        new_title = title.strip()
        if not new_title:
            raise HTTPException(400, "Il titolo non può essere vuoto")
        q.title = new_title
    if number is not None:
        new_number = number.strip()
        if not new_number:
            raise HTTPException(400, "Il numero non può essere vuoto")
        if new_number != q.number:
            # Modifica del numero ammessa solo finché la quote è in draft.
            # Una volta "sent" (proposta al cliente) o "approved" (con job
            # collegato), il numero è il riferimento ufficiale e non va toccato.
            if q.status != QuoteStatus.draft:
                raise HTTPException(409,
                    f"Il numero non può essere modificato in stato '{q.status.value}'. "
                    "Solo le bozze sono rinominabili.")
            # Unicità: bypass del filter soft-delete perché le quote in cestino
            # occupano comunque il number (vincolo UNIQUE su DB).
            collision = (db.query(Quote)
                           .execution_options(include_deleted=True)
                           .filter(Quote.number == new_number, Quote.id != q.id)
                           .first())
            if collision:
                raise HTTPException(409,
                    f"Esiste già una quote con number '{new_number}' (eventualmente nel cestino)")
            q.number = new_number

    if package_discount is not None: q.package_discount = package_discount
    if vat_rate is not None: q.vat_rate = vat_rate
    if notes is not None: q.notes = notes
    if payment_terms is not None: q.payment_terms = payment_terms
    _recalc_quote(q)
    db.commit()
    return {
        "id": q.id,
        "number": q.number,
        "title": q.title,
        "subtotal_gross": q.subtotal_gross,
        "subtotal": q.subtotal,
        "total_after_discount": q.total_after_discount,
        "total_with_vat": q.total_with_vat,
    }


@router.put("/api/{quote_id}/category-discount")
async def update_category_discount(
    quote_id: int,
    category: str = Form(...),
    pct: float = Form(...),
    db: Session = Depends(get_db),
):
    """Imposta lo sconto su una categoria (positivo = riduzione, es. 0.15 = 15%).
    Passare pct=0 per rimuovere lo sconto."""
    q = db.query(Quote).options(
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category)
    ).filter(Quote.id == quote_id).first()
    if not q: raise HTTPException(404, "Quotazione non trovata")
    discounts = dict(q.category_discounts or {})
    if pct == 0:
        discounts.pop(category, None)
    else:
        discounts[category] = pct
    q.category_discounts = discounts
    _recalc_quote(q)
    db.commit()
    return {
        "category_discounts": q.category_discounts or {},
        "category_order": q.category_order or [],
        "subtotal_gross": q.subtotal_gross,
        "subtotal": q.subtotal,
        "total_after_discount": q.total_after_discount,
        "total_with_vat": q.total_with_vat,
    }


@router.put("/api/{quote_id}/lines-reorder")
async def reorder_quote_lines(
    quote_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Riordina le voci. Body JSON: {order: [line_id1, line_id2, ...]}"""
    data = await request.json()
    order = data.get("order", [])
    if not isinstance(order, list):
        raise HTTPException(400, "Campo 'order' deve essere una lista di line_id")
    q = db.query(Quote).options(joinedload(Quote.lines)).filter(Quote.id == quote_id).first()
    if not q: raise HTTPException(404)
    line_map = {l.id: l for l in q.lines}
    for idx, line_id in enumerate(order):
        line = line_map.get(int(line_id))
        if line:
            line.sort_order = (idx + 1) * 10
    db.commit()
    return {"ok": True, "count": len(order)}


@router.put("/api/{quote_id}/category-order")
async def reorder_quote_categories(
    quote_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """v3.4.34 — Persiste l'ordine delle categorie nelle voci preventivo.
    Body JSON: {order: ["PICTURE", "SOUND", "Altro"]}.
    Le categorie non listate appaiono dopo nell'ordine naturale."""
    data = await request.json()
    order = data.get("order", [])
    if not isinstance(order, list):
        raise HTTPException(400, "Campo 'order' deve essere una lista di nomi categoria")
    q = db.query(Quote).filter(Quote.id == quote_id).first()
    if not q:
        raise HTTPException(404, "Quotazione non trovata")
    cleaned = [str(c) for c in order if c]
    q.category_order = cleaned or None
    db.commit()
    return {"ok": True, "category_order": q.category_order or []}


@router.post("/api/{quote_id}/lines")
async def add_quote_line(
    quote_id: int,
    description: str = Form(...),
    section: str = Form("A"),
    position: str = Form("A.1"),
    detail: Optional[str] = Form(None),
    quantity: float = Form(1.0),
    unit: str = Form("day"),
    price_level: PriceLevel = Form(PriceLevel.list_price),
    unit_price: float = Form(0.0),
    allowance: float = Form(0.0),
    line_discount_pct: float = Form(0.0),
    hardcosts: float = Form(0.0),
    price_item_id: Optional[int] = Form(None),
    category_override: Optional[str] = Form(None),
    is_optional: bool = Form(False),
    section_label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    q = db.query(Quote).options(
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category)
    ).filter(Quote.id == quote_id).first()
    if not q: raise HTTPException(404)
    if price_item_id and unit_price == 0:
        item = db.query(PriceItem).filter(PriceItem.id == price_item_id).first()
        if item:
            unit_price = {
                PriceLevel.list_price: item.price_list,
                PriceLevel.average: item.price_average,
                PriceLevel.low: item.price_low,
            }.get(price_level, item.price_list) or 0.0
    sort_order = max((l.sort_order for l in q.lines), default=0) + 10
    cat_override_clean = (category_override or "").strip() or None
    section_label_clean = (section_label or "").strip() or None
    line = QuoteLine(
        quote_id=quote_id, description=description, section=section,
        position=position, detail=detail, quantity=quantity, unit=unit,
        price_level=price_level, unit_price=unit_price,
        allowance=allowance, line_discount_pct=line_discount_pct,
        total=0.0, hardcosts=hardcosts,
        price_item_id=price_item_id, sort_order=sort_order,
        category_override=cat_override_clean,
        is_optional=bool(is_optional),
        section_label=section_label_clean,
    )
    db.add(line); db.flush()
    db.refresh(q)
    _recalc_quote(q)

    # v3.4.36 (R1.2): se la quote ha già un job approvato (post-conversione),
    # auto-crea JobCostLine corrispondente per mantenere job e quote allineati.
    # Idempotente: skip se esiste già JobCostLine con quote_line_id=line.id.
    job_cost_line_created = False
    if q.job and q.job.status not in (JobStatus.completed, JobStatus.invoiced, JobStatus.cancelled):
        existing = db.query(JobCostLine).filter(
            JobCostLine.quote_line_id == line.id
        ).first()
        if not existing:
            db.add(JobCostLine(
                job_id=q.job.id,
                quote_line_id=line.id,
                price_item_id=line.price_item_id,
                description=line.description,
                quantity_quoted=line.quantity,
                quantity_actual=0.0,
                unit=line.unit,
                unit_price=line.unit_price,
                total_quoted=line.total or 0.0,
                total_accrued=0.0,
                total_expected=line.total or 0.0,
                is_billable=True,
                is_extra=False,
            ))
            job_cost_line_created = True

    db.commit()
    return {
        "id": line.id, "total": line.total, "quote_total": q.total_with_vat,
        "subtotal_gross": q.subtotal_gross, "subtotal": q.subtotal,
        "total_after_discount": q.total_after_discount,
        "total_with_vat": q.total_with_vat,
        "subtotal_optional": round(
            sum((l.total or 0.0) for l in q.lines if l.is_optional), 2
        ),
        "job_cost_line_created": job_cost_line_created,
    }


@router.put("/api/{quote_id}/lines/{line_id}")
async def update_quote_line(
    quote_id: int, line_id: int,
    description: Optional[str] = Form(None),
    detail: Optional[str] = Form(None),
    quantity: Optional[float] = Form(None),
    unit: Optional[str] = Form(None),
    unit_price: Optional[float] = Form(None),
    allowance: Optional[float] = Form(None),
    line_discount_pct: Optional[float] = Form(None),
    category_override: Optional[str] = Form(None),
    is_optional: Optional[bool] = Form(None),
    section_label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    line = db.query(QuoteLine).filter(QuoteLine.id == line_id, QuoteLine.quote_id == quote_id).first()
    if not line: raise HTTPException(404)
    if description is not None: line.description = description
    if detail is not None: line.detail = detail
    if quantity is not None: line.quantity = quantity
    if unit is not None: line.unit = unit
    if unit_price is not None: line.unit_price = unit_price
    if allowance is not None: line.allowance = allowance
    if line_discount_pct is not None: line.line_discount_pct = line_discount_pct
    if category_override is not None:
        cleaned = category_override.strip()
        # FastAPI Form(None) parsa "" come None, quindi usiamo un sentinel
        # esplicito per cancellare l'override.
        if cleaned in ("__CLEAR__", "__none__"):
            line.category_override = None
        else:
            line.category_override = cleaned or None
    if is_optional is not None:
        line.is_optional = bool(is_optional)
    if section_label is not None:
        cleaned = section_label.strip()
        if cleaned in ("__CLEAR__", "__none__"):
            line.section_label = None
        else:
            line.section_label = cleaned or None
    q = db.query(Quote).options(
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category)
    ).filter(Quote.id == quote_id).first()
    _recalc_quote(q)

    # v3.4.36 (R1.3): sync verso JobCostLine collegata, se presente.
    # Blocca se job in stato terminale (completed/invoiced/cancelled).
    job_cost_line_synced = False
    jcl = db.query(JobCostLine).filter(JobCostLine.quote_line_id == line.id).first()
    if jcl:
        if jcl.job and jcl.job.status in (JobStatus.completed, JobStatus.invoiced, JobStatus.cancelled):
            raise HTTPException(
                409,
                f"Modifica bloccata: il job {jcl.job.code} è in stato "
                f"{jcl.job.status.value}. Riapri/duplica il job per modificare."
            )
        jcl.description = line.description
        jcl.quantity_quoted = line.quantity
        jcl.unit = line.unit
        jcl.unit_price = line.unit_price
        jcl.total_quoted = line.total or 0.0
        # total_expected si aggiorna se non è ancora stato sovrascritto manualmente
        # (heuristica: se total_expected == previous total_quoted, segue).
        # Per sicurezza: lo lasciamo come riferimento iniziale (no sovrascrittura).
        job_cost_line_synced = True

    db.commit()
    return {
        "id": line.id, "total": line.total,
        "subtotal_gross": q.subtotal_gross, "subtotal": q.subtotal,
        "total_after_discount": q.total_after_discount,
        "total_with_vat": q.total_with_vat,
        "subtotal_optional": round(
            sum((l.total or 0.0) for l in q.lines if l.is_optional), 2
        ),
        "is_optional": bool(line.is_optional),
        "section_label": line.section_label or None,
        "job_cost_line_synced": job_cost_line_synced,
    }


@router.delete("/api/{quote_id}/lines/{line_id}")
async def delete_quote_line(quote_id: int, line_id: int, db: Session = Depends(get_db)):
    """v3.4.55 — cancellazione QuoteLine: HARD-BLOCK se ha JobCostLine con
    booking attivi (status != cancelled). Fino a v3.4.54 facevamo soft-detach
    (SET NULL job_cost_line_id sui Booking) → produceva booking orfani senza
    lavorazione → cost report vuoto → paradosso segnalato da Matteo.

    Nuova policy: la riga di quote NON può essere cancellata finché esistono
    booking attivi sulla JobCostLine collegata. Modifica resta consentita.
    Per togliere la riga: cancella prima i booking (o marcali cancelled),
    oppure modifica la riga (descrizione, qty, prezzo) senza eliminarla.
    """
    line = db.query(QuoteLine).filter(QuoteLine.id == line_id).first()
    if not line:
        raise HTTPException(404)

    # Trova JobCostLine collegate
    cost_lines = db.query(JobCostLine).filter(
        JobCostLine.quote_line_id == line_id
    ).all()

    # v3.4.55 — HARD-BLOCK su booking attivi
    blocking_bookings = []
    for jcl in cost_lines:
        active_bk = db.query(Booking).filter(
            Booking.job_cost_line_id == jcl.id,
            Booking.status != BookingStatus.cancelled,
        ).all()
        for b in active_bk:
            blocking_bookings.append({
                "booking_id": b.id,
                "start": b.start_datetime.isoformat() if b.start_datetime else None,
                "execution_status": b.execution_status.value if hasattr(b.execution_status, "value") else str(b.execution_status),
            })
    if blocking_bookings:
        raise HTTPException(
            409,
            f"Impossibile eliminare: questa riga ha {len(blocking_bookings)} "
            f"booking attivi collegati. Cancella o annulla prima i booking, "
            f"oppure modifica la riga senza eliminarla. "
            f"Booking ostativi: {[b['booking_id'] for b in blocking_bookings[:5]]}"
            + (f" e altri {len(blocking_bookings)-5}" if len(blocking_bookings) > 5 else "")
        )

    # Cascade su JobCostLine "pulite" (senza booking attivi): rimosse insieme
    for jcl in cost_lines:
        # Blocca anche se il job è in stato terminale
        if jcl.job and jcl.job.status in (JobStatus.completed, JobStatus.invoiced):
            raise HTTPException(
                409,
                f"Impossibile cancellare: il job {jcl.job.code} è in stato "
                f"{jcl.job.status.value} e ha già consuntivato questa lavorazione."
            )
        # Per TimePunch (HR, separato dal cost report): soft-detach OK
        db.query(TimePunch).filter(
            TimePunch.job_cost_line_id == jcl.id
        ).update({"job_cost_line_id": None}, synchronize_session=False)
        db.delete(jcl)

    db.delete(line)
    q = db.query(Quote).options(
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category)
    ).filter(Quote.id == quote_id).first()
    q.lines = [l for l in q.lines if l.id != line_id]
    _recalc_quote(q)
    db.commit()
    return {"ok": True, "cost_lines_deleted": len(cost_lines)}


# ── Soft-delete dell'intera Quote (v3.5.0-alpha.7) ───────────

@router.delete("/api/{quote_id}")
async def delete_quote(
    quote_id: int,
    request: Request,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Soft-delete di una Quote (sposta nel cestino) o pulizia totale (admin).

    Permessi:
    - `delete_quotes`: soft-delete normale. HARD-BLOCK 409 se ci sono booking
      attivi sul Job collegato (con elenco bloccanti nel response body).
    - `purge_total` (solo admin per default): può passare `?force=true` per
      hard-delete cascade su Quote + Job + JobCostLine + Booking + assignments.

    Response success:
      200 {"ok": true, "mode": "soft" | "purge_total", ...}

    Response HARD-BLOCK:
      409 {"detail": "...", "blocking": {"bookings": [...]}, "can_force": true|false}
    """
    from app.services.rbac import current_user_optional, has_permission
    from app.services.soft_delete import (
        soft_delete_quote, fetch_quote_including_trash, DeleteBlocked,
    )
    from fastapi.responses import JSONResponse

    user = current_user_optional(request)
    if not has_permission(user, "delete_quotes"):
        raise HTTPException(403, "Permesso negato (delete_quotes)")
    if force and not has_permission(user, "purge_total"):
        raise HTTPException(403, "Solo un admin con permesso 'purge_total' può forzare la pulizia totale")

    q = fetch_quote_including_trash(db, quote_id)
    if not q:
        raise HTTPException(404, "Quotazione non trovata")

    try:
        result = soft_delete_quote(db, q, user=user, force=force)
    except DeleteBlocked as e:
        # Mantieni in lista anche se l'utente è admin: il frontend deciderà
        # se mostrare il bottone "Pulizia totale" usando `can_force`.
        return JSONResponse(
            status_code=409,
            content={
                "detail":    e.message,
                "blocking":  {"bookings": e.bookings, "jobs": e.jobs},
                "can_force": has_permission(user, "purge_total"),
            },
        )

    db.commit()
    return result


@router.post("/api/{quote_id}/restore")
async def restore_quote_endpoint(
    quote_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Ripristina una Quote dal cestino. Idempotente."""
    from app.services.rbac import current_user_optional, has_permission
    from app.services.soft_delete import fetch_quote_including_trash, restore_quote

    user = current_user_optional(request)
    if not has_permission(user, "restore_trash"):
        raise HTTPException(403, "Permesso negato (restore_trash)")

    q = fetch_quote_including_trash(db, quote_id)
    if not q:
        raise HTTPException(404, "Quotazione non trovata")
    result = restore_quote(db, q)
    db.commit()
    return result


@router.post("/api/{quote_id}/convert-to-job")
async def convert_to_job_legacy(
    quote_id: int,
    job_code: Optional[str] = Form(None),
    start_date: Optional[date] = Form(None),
    end_date: Optional[date] = Form(None),
    db: Session = Depends(get_db),
):
    """DEPRECATED dal v3.4.8 — usare PUT /api/{quote_id}/status con status=approved.

    Mantenuto come wrapper per retrocompatibilità: ignora `job_code`/`start_date`/
    `end_date` e delega alla nuova logica auto-promote (codice auto-generato
    {project.code}-J{N}, title da project.title, no date hardcoded).
    """
    q = (
        db.query(Quote)
        .options(joinedload(Quote.lines), joinedload(Quote.project), joinedload(Quote.job))
        .filter(Quote.id == quote_id)
        .first()
    )
    if not q:
        raise HTTPException(404)
    if q.job:
        raise HTTPException(400, "Job già esistente")
    job = _create_job_from_quote(db, q)
    q.status = QuoteStatus.approved
    db.commit()
    return {"job_id": job.id, "job_code": job.code, "deprecated": True}


@router.get("/api/{quote_id}/pdf")
async def quote_pdf(quote_id: int, db: Session = Depends(get_db)):
    from app.services.quote_pdf import generate_quote_pdf
    q = db.query(Quote).options(
        joinedload(Quote.client),
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category),
    ).filter(Quote.id == quote_id).first()
    if not q: raise HTTPException(404)
    pdf = generate_quote_pdf(q)
    filename = f"quote_{q.number.replace('/', '-')}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── Export CSV/Excel quotazione ──────────────────────────────

def _quote_export_rows(q: Quote) -> tuple[list[str], list[list], list[list]]:
    """Header colonne + righe per categoria con subtotali + footer totali."""
    headers = ["Categoria", "Posizione", "Descrizione", "Quantità", "Unità",
               "Prezzo unitario €", "Sconto riga %", "Totale riga €"]
    sorted_lines = sorted(q.lines, key=lambda l: l.sort_order)
    groups: dict[str, list] = {}
    order = []
    for l in sorted_lines:
        cat = _line_category(l)
        if cat not in groups:
            groups[cat] = []
            order.append(cat)
        groups[cat].append(l)

    cat_disc = q.category_discounts or {}
    body = []
    for cat in order:
        cat_lines = groups[cat]
        body.append([cat.upper(), "", "", "", "", "", "", ""])
        cat_subtotal = 0.0
        for l in cat_lines:
            disc = (l.line_discount_pct or 0) * 100
            body.append([
                "", l.position or "", l.description or "",
                l.quantity, l.unit or "",
                round(l.unit_price or 0, 2),
                round(disc, 2) if disc else "",
                round(l.total or 0, 2),
            ])
            cat_subtotal += (l.total or 0)
        body.append(["", "", f"Subtotale {cat}", "", "", "", "", round(cat_subtotal, 2)])
        cd = cat_disc.get(cat, 0)
        if cd:
            disc_amount = cat_subtotal * cd
            body.append(["", "", f"Sconto categoria {cd*100:.1f}%", "", "", "", "", -round(disc_amount, 2)])

    pkg_pct = abs((q.package_discount or 0) * 100)
    pkg_amount = (q.subtotal or 0) - (q.total_after_discount or 0)
    vat_amount = (q.total_with_vat or 0) - (q.total_after_discount or 0)
    footer = [
        ["", "", "Totale lordo (no sconti)", "", "", "", "", round(q.subtotal_gross or 0, 2)],
        ["", "", "Subtotale dopo sconti voci/categorie", "", "", "", "", round(q.subtotal or 0, 2)],
    ]
    if pkg_pct > 0.05:
        footer.append(["", "", f"Sconto pacchetto {pkg_pct:.1f}%", "", "", "", "", -round(pkg_amount, 2)])
    footer.extend([
        ["", "", "Totale netto base IVA", "", "", "", "", round(q.total_after_discount or 0, 2)],
        ["", "", f"IVA {q.vat_rate:.0f}%", "", "", "", "", round(vat_amount, 2)],
        ["", "", "TOTALE (incl. IVA)", "", "", "", "", round(q.total_with_vat or 0, 2)],
    ])
    return headers, body, footer


@router.get("/api/{quote_id}/export.csv")
async def quote_export_csv(quote_id: int, db: Session = Depends(get_db)):
    import csv, io
    q = db.query(Quote).options(
        joinedload(Quote.client),
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category),
    ).filter(Quote.id == quote_id).first()
    if not q: raise HTTPException(404)
    headers, body, footer = _quote_export_rows(q)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow([f"Quotazione {q.number} — {q.title or ''}"])
    if q.client:
        w.writerow([f"Cliente: {q.client.name}"])
    w.writerow([f"Data: {q.issue_date}"])
    w.writerow([])
    w.writerow(headers)
    for r in body: w.writerow(r)
    w.writerow([])
    for r in footer: w.writerow(r)
    body_str = "﻿" + buf.getvalue()
    filename = f"quote_{q.number.replace('/', '-')}.csv"
    return Response(content=body_str, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/api/{quote_id}/export.xlsx")
async def quote_export_xlsx(quote_id: int, db: Session = Depends(get_db)):
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    q = db.query(Quote).options(
        joinedload(Quote.client),
        joinedload(Quote.lines).joinedload(QuoteLine.price_item).joinedload(PriceItem.category),
    ).filter(Quote.id == quote_id).first()
    if not q: raise HTTPException(404)

    headers, body, footer = _quote_export_rows(q)
    wb = Workbook()
    ws = wb.active
    ws.title = "Quotazione"

    indigo = PatternFill("solid", fgColor="6272f5")
    cat_fill = PatternFill("solid", fgColor="EEF1FF")
    sub_fill = PatternFill("solid", fgColor="F8F9FB")
    bold_white = Font(bold=True, color="FFFFFF")
    bold_indigo = Font(bold=True, color="6272f5")
    bold_dark = Font(bold=True, color="1A1A2E")
    thin = Side(border_style="thin", color="DDE1F0")

    # Intestazione
    ws.merge_cells("A1:H1")
    ws["A1"] = f"Quotazione {q.number} — {q.title or ''}"
    ws["A1"].font = Font(bold=True, size=14, color="6272f5")
    ws["A2"] = f"Cliente: {q.client.name if q.client else '—'}"
    ws["A3"] = f"Data emissione: {q.issue_date}    Valida fino al: {q.valid_until or '—'}"
    ws["A2"].font = Font(color="6B7280")
    ws["A3"].font = Font(color="6B7280")

    start_row = 5
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=start_row, column=col_idx, value=h)
        c.font = bold_white
        c.fill = indigo
        c.alignment = Alignment(vertical="center", horizontal="center")

    r = start_row + 1
    for row in body:
        for col_idx, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=col_idx, value=v)
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        # Riga categoria (prima colonna piena, altre vuote)
        if row[0] and not row[1]:
            for col_idx in range(1, 9):
                ws.cell(row=r, column=col_idx).fill = cat_fill
                ws.cell(row=r, column=col_idx).font = bold_indigo
        # Riga subtotale (descrizione "Subtotale ..." colonna C, totale colonna H)
        elif (row[2] and (str(row[2]).startswith("Subtotale ") or str(row[2]).startswith("Sconto categoria "))):
            for col_idx in range(1, 9):
                ws.cell(row=r, column=col_idx).fill = sub_fill
            ws.cell(row=r, column=3).font = bold_dark
            ws.cell(row=r, column=8).font = bold_dark
        # Format numerico per colonne prezzi/totali
        for col_idx in (4, 6, 7, 8):
            cell = ws.cell(row=r, column=col_idx)
            if isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
        r += 1

    # Footer totals
    r += 1
    for row in footer:
        for col_idx, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=col_idx, value=v)
            if col_idx == 3: cell.font = bold_dark
            if col_idx == 8 and isinstance(v, (int, float)):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
                cell.font = bold_dark
        # Ultima riga (TOTALE incl. IVA): sfondo indigo
        if str(row[2]).startswith("TOTALE"):
            for col_idx in range(1, 9):
                ws.cell(row=r, column=col_idx).fill = indigo
                ws.cell(row=r, column=col_idx).font = bold_white
        r += 1

    # Larghezze (uso get_column_letter perché row=1 è una merged cell)
    widths = [16, 10, 50, 10, 10, 16, 12, 16]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = f"A{start_row + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    filename = f"quote_{q.number.replace('/', '-')}.xlsx"
    return Response(content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── DUPLICAZIONE / VERSIONING (v3.4.39) ──────────────────────


def _quote_root(db: Session, q: Quote) -> Quote:
    """Risale la catena delle versioni fino alla radice (parent_quote_id IS NULL)."""
    seen = {q.id}
    while q.parent_quote_id is not None:
        parent = db.query(Quote).filter(Quote.id == q.parent_quote_id).first()
        if not parent or parent.id in seen:
            break
        seen.add(parent.id)
        q = parent
    return q


def _quote_chain(db: Session, root: Quote) -> list[Quote]:
    """Ritorna root + tutti i discendenti (BFS sui parent_quote_id)."""
    visited = {root.id}
    chain = [root]
    frontier = [root.id]
    while frontier:
        children = db.query(Quote).filter(Quote.parent_quote_id.in_(frontier)).all()
        frontier = []
        for c in children:
            if c.id not in visited:
                visited.add(c.id)
                chain.append(c)
                frontier.append(c.id)
    return chain


def _next_quote_number_progressive(db: Session) -> str:
    """Wrapper su _next_quote_number di ai_assistant. Inline per evitare circular import.

    BYPASS soft-delete: le quote in cestino occupano il number (vincolo UNIQUE).
    """
    from datetime import date as date_type
    year = date_type.today().year
    prefix = f"Q-{year}-"
    last = (
        db.query(Quote)
          .execution_options(include_deleted=True)
          .filter(Quote.number.like(f"{prefix}%"))
          .order_by(Quote.id.desc()).first()
    )
    n = 1
    if last:
        try:
            tail = last.number.rsplit("-", 1)[1]
            # Se tail è "vNN" (versioning), non è il progressivo: salta indietro
            if tail.startswith("v") and tail[1:].isdigit():
                # Pesca il base
                base = last.number.rsplit("-", 1)[0]
                tail = base.rsplit("-", 1)[1]
            n = int(tail) + 1
        except (ValueError, IndexError):
            n = 1
    return f"{prefix}{n:03d}"


def _copy_quote_lines(src_lines: list, dest_quote_id: int, track_parent: bool) -> list[QuoteLine]:
    """Crea copie delle QuoteLine. Se track_parent, valorizza parent_line_id (versioning).
    Ritorna la lista delle nuove righe (non ancora flushate)."""
    new_lines = []
    for sl in sorted(src_lines, key=lambda x: x.sort_order):
        nl = QuoteLine(
            quote_id=dest_quote_id,
            price_item_id=sl.price_item_id,
            section=sl.section,
            position=sl.position,
            description=sl.description,
            detail=sl.detail,
            quantity=sl.quantity,
            unit=sl.unit,
            price_level=sl.price_level,
            unit_price=sl.unit_price,
            allowance=sl.allowance,
            line_discount_pct=sl.line_discount_pct,
            total=sl.total,
            hardcosts=sl.hardcosts,
            sort_order=sl.sort_order,
            category_override=sl.category_override,
            source_hint=sl.source_hint,
            parent_line_id=sl.id if track_parent else None,
        )
        new_lines.append(nl)
    return new_lines


@router.post("/api/{quote_id}/duplicate")
async def duplicate_quote(
    quote_id: int,
    request: Request,
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Duplica una quote in modo INDIPENDENTE (no parent_quote_id).
    Use case: scenario alternativo, template per un nuovo progetto.
    Numero auto-progressivo `Q-{anno}-NNN`. Status=draft.

    v3.4.43 — `project_id` opzionale: se valorizzato, la copia viene
    associata a un progetto diverso da quello sorgente (use case template
    per nuovo progetto). Il `client_id` viene riallineato al cliente del
    nuovo progetto."""
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_quotes"):
        raise HTTPException(403, "Non hai il permesso di duplicare le quotazioni")

    src = (
        db.query(Quote)
        .options(joinedload(Quote.lines))
        .filter(Quote.id == quote_id).first()
    )
    if not src:
        raise HTTPException(404, "Quotazione sorgente non trovata")

    # v3.4.43 — Risolvi project + client target
    target_project_id = project_id if project_id else src.project_id
    target_client_id = src.client_id
    if project_id and project_id != src.project_id:
        target_project = db.query(Project).filter(Project.id == project_id).first()
        if not target_project:
            raise HTTPException(404, f"Progetto target #{project_id} non trovato")
        target_client_id = target_project.client_id

    new_q = Quote(
        number=_next_quote_number_progressive(db),
        version=1,
        project_id=target_project_id,
        client_id=target_client_id,
        title=src.title,
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
        notes=src.notes,
        payment_terms=src.payment_terms,
        # NESSUN parent_quote_id: duplicato indipendente.
    )
    db.add(new_q); db.flush()

    new_lines = _copy_quote_lines(src.lines, new_q.id, track_parent=False)
    db.add_all(new_lines)
    db.flush()

    _recalc_quote(new_q)
    db.commit()
    db.refresh(new_q)
    return {
        "id": new_q.id,
        "number": new_q.number,
        "title": new_q.title,
        "project_id": new_q.project_id,
        "client_id": new_q.client_id,
        "lines_count": len(new_lines),
        "kind": "duplicate",
    }


@router.put("/api/{quote_id}/move-to-project")
async def move_quote_to_project(
    quote_id: int,
    request: Request,
    project_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """v3.4.43 — Sposta una quote esistente a un altro progetto.
    Vincoli:
      - Solo quote in stato `draft` (una quote già inviata/approvata/etc
        non può cambiare progetto: è un cambio di scope vincolante).
      - La quote NON deve avere un Job collegato (incoerenza grave).
      - Il cliente viene riallineato al cliente del progetto target.
    """
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_quotes"):
        raise HTTPException(403, "Non hai il permesso di spostare le quotazioni")

    q = db.query(Quote).options(joinedload(Quote.job)).filter(Quote.id == quote_id).first()
    if not q:
        raise HTTPException(404, "Quotazione non trovata")
    if q.status != QuoteStatus.draft:
        raise HTTPException(
            400,
            f"Lo spostamento di progetto è ammesso solo su quote in bozza. "
            f"Stato corrente: {q.status.value}."
        )
    if q.job:
        raise HTTPException(
            400,
            f"Quote ha un job collegato ({q.job.code}): impossibile spostare di progetto. "
            "Annulla il job o crea una nuova versione."
        )
    target = db.query(Project).filter(Project.id == project_id).first()
    if not target:
        raise HTTPException(404, f"Progetto target #{project_id} non trovato")

    old_project_id = q.project_id
    q.project_id = project_id
    q.client_id = target.client_id
    db.commit()
    return {
        "id": q.id,
        "number": q.number,
        "old_project_id": old_project_id,
        "new_project_id": project_id,
        "new_client_id": target.client_id,
    }


@router.post("/api/{quote_id}/new-version")
async def new_version_quote(
    quote_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Crea una nuova versione della quote (parent_quote_id valorizzato).
    Numero `{root_number}-v{N}` dove N = max(version) + 1 nella catena.
    Le righe ereditano `parent_line_id` per re-bind preciso al migrate-job."""
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_quotes"):
        raise HTTPException(403, "Non hai il permesso di creare nuove versioni")

    src = (
        db.query(Quote)
        .options(joinedload(Quote.lines))
        .filter(Quote.id == quote_id).first()
    )
    if not src:
        raise HTTPException(404, "Quotazione sorgente non trovata")

    root = _quote_root(db, src)
    chain = _quote_chain(db, root)
    next_version = max(q.version for q in chain) + 1
    # v3.4.50.1: pulisci eventuale suffisso `-vN` dal root.number per evitare
    # numeri duplicati come `Q-2026-001-v1-v2`. Pattern: rstrip al match -v\d+
    import re
    base_number = re.sub(r"-v\d+$", "", root.number)
    new_number = f"{base_number}-v{next_version}"

    # Conflitto improbabile ma garantiamo unicità (anche su cestino)
    if (db.query(Quote)
          .execution_options(include_deleted=True)
          .filter(Quote.number == new_number).first()):
        raise HTTPException(409, f"Numero quotazione '{new_number}' già esistente (eventualmente nel cestino)")

    new_q = Quote(
        number=new_number,
        version=next_version,
        parent_quote_id=src.id,
        project_id=src.project_id,
        client_id=src.client_id,
        title=src.title,
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
        notes=src.notes,
        payment_terms=src.payment_terms,
    )
    db.add(new_q); db.flush()

    new_lines = _copy_quote_lines(src.lines, new_q.id, track_parent=True)
    db.add_all(new_lines)
    db.flush()

    _recalc_quote(new_q)
    db.commit()
    db.refresh(new_q)
    return {
        "id": new_q.id,
        "number": new_q.number,
        "version": new_q.version,
        "parent_quote_id": new_q.parent_quote_id,
        "title": new_q.title,
        "lines_count": len(new_lines),
        "kind": "version",
    }


@router.get("/api/{quote_id}/versions")
async def list_quote_versions(quote_id: int, db: Session = Depends(get_db)):
    """Catena versioni completa (root + discendenti, ordinata per version)."""
    q = db.query(Quote).filter(Quote.id == quote_id).first()
    if not q:
        raise HTTPException(404)
    root = _quote_root(db, q)
    chain = _quote_chain(db, root)
    chain_sorted = sorted(chain, key=lambda x: (x.version, x.id))
    return {
        "root_id": root.id,
        "current_id": q.id,
        "versions": [
            {
                "id": c.id, "number": c.number, "version": c.version,
                "status": c.status, "title": c.title,
                "parent_quote_id": c.parent_quote_id,
                "superseded_by_id": c.superseded_by_id,
                "has_job": c.job is not None,
                "job_id": c.job.id if c.job else None,
                "job_code": c.job.code if c.job else None,
                "issue_date": str(c.issue_date),
                "total_after_discount": c.total_after_discount,
            }
            for c in chain_sorted
        ],
    }


def _build_migration_preview(db: Session, new_q: Quote) -> dict:
    """Analisi pre-migrazione tra V_old (= new_q.parent_quote) e V_new (= new_q).
    Identifica righe nuove, modificate, orfane. Evidenzia righe orfane con
    quantity_actual > 0 o booking done (lavoro registrato).
    """
    if not new_q.parent_quote_id:
        raise HTTPException(400, "Quote senza parent: niente da migrare")
    old_q = db.query(Quote).options(
        joinedload(Quote.lines), joinedload(Quote.job)
    ).filter(Quote.id == new_q.parent_quote_id).first()
    if not old_q:
        raise HTTPException(400, "Parent quote non trovata")

    job = old_q.job
    # Costline mappato per quote_line_id sorgente
    cost_by_old_line = {}
    if job:
        for jcl in job.cost_lines:
            if jcl.quote_line_id:
                cost_by_old_line[jcl.quote_line_id] = jcl

    new_lines_by_parent = {l.parent_line_id: l for l in new_q.lines if l.parent_line_id}
    orphans = []        # righe presenti in V_old ma non più in V_new
    inherited = []      # righe V_new con parent → re-bind ok
    fresh = []          # righe V_new senza parent → nuove pure
    overruns = []       # righe V_new con quantity_quoted < quantity_actual già registrato

    for ol in old_q.lines:
        if ol.id not in new_lines_by_parent:
            jcl = cost_by_old_line.get(ol.id)
            has_actual = bool(jcl and (jcl.quantity_actual or 0) > 0)
            orphans.append({
                "old_line_id": ol.id,
                "description": ol.description,
                "quantity": ol.quantity,
                "unit": ol.unit,
                "total": ol.total,
                "has_jobcostline": jcl is not None,
                "jobcostline_id": jcl.id if jcl else None,
                "quantity_actual": (jcl.quantity_actual if jcl else 0) or 0,
                "has_actual_work": has_actual,
            })

    for nl in new_q.lines:
        if nl.parent_line_id:
            inherited.append({
                "new_line_id": nl.id,
                "old_line_id": nl.parent_line_id,
                "description": nl.description,
            })
            jcl = cost_by_old_line.get(nl.parent_line_id)
            if jcl and (jcl.quantity_actual or 0) > (nl.quantity or 0):
                overruns.append({
                    "new_line_id": nl.id,
                    "description": nl.description,
                    "quantity_quoted_new": nl.quantity,
                    "quantity_actual": jcl.quantity_actual,
                    "delta": (jcl.quantity_actual or 0) - (nl.quantity or 0),
                })
        else:
            fresh.append({
                "new_line_id": nl.id,
                "description": nl.description,
                "quantity": nl.quantity,
            })

    return {
        "old_quote_id": old_q.id,
        "old_quote_number": old_q.number,
        "new_quote_id": new_q.id,
        "new_quote_number": new_q.number,
        "has_job": job is not None,
        "job_id": job.id if job else None,
        "job_code": job.code if job else None,
        "inherited": inherited,
        "fresh": fresh,
        "orphans": orphans,
        "overruns": overruns,
        "has_blockers": False,  # per ora nessun blocker hard, solo avvisi
    }


@router.get("/api/{quote_id}/migrate-preview")
async def migrate_preview(quote_id: int, db: Session = Depends(get_db)):
    """Anteprima della migrazione job da V_old a V_new (questo quote_id)."""
    new_q = (
        db.query(Quote)
        .options(joinedload(Quote.lines))
        .filter(Quote.id == quote_id).first()
    )
    if not new_q:
        raise HTTPException(404)
    return _build_migration_preview(db, new_q)


@router.post("/api/{quote_id}/migrate-job")
async def migrate_job(
    quote_id: int,
    request: Request,
    orphan_strategy: str = Form("keep_as_extra"),
    db: Session = Depends(get_db),
):
    """Applica la migrazione del Job da V_old a V_new (= quote_id).

    `orphan_strategy`:
      - `keep_as_extra` (default): le JobCostLine orfane restano sul Job ma
        vengono marcate `is_extra=True` e perdono `quote_line_id` (SET NULL).
        Il Job rimane legato a V_new; le righe orfane producono extra in
        consuntivo per riconciliazione finance.
      - `floating_job`: il Job viene scollegato (quote_id=NULL) e diventa un
        "Floating Job" gestito in `/financial`. La V_new resta non legata; il
        ciclo di vita del Job va riconciliato manualmente (riassegnazione a un
        nuovo progetto/quote o chiusura).

    Effetti:
      - V_new.status = approved
      - V_old.status = superseded; V_old.superseded_by_id = V_new.id
      - Job.quote_id = V_new.id (a meno di floating_job)
      - JobCostLine: re-bind via QuoteLine.parent_line_id; quote_line_id rimappato
        sull'id della riga V_new corrispondente.
    """
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_quotes"):
        raise HTTPException(403, "Non hai il permesso di migrare le quotazioni")

    if orphan_strategy not in ("keep_as_extra", "floating_job"):
        raise HTTPException(400, f"orphan_strategy non valido: {orphan_strategy}")

    new_q = (
        db.query(Quote)
        .options(joinedload(Quote.lines), joinedload(Quote.parent_quote))
        .filter(Quote.id == quote_id).first()
    )
    if not new_q:
        raise HTTPException(404)
    if not new_q.parent_quote_id:
        raise HTTPException(400, "Quote senza parent: nessuna migrazione possibile")
    if new_q.status not in (QuoteStatus.draft, QuoteStatus.sent):
        raise HTTPException(400, f"V_new in stato {new_q.status.value}: non migrabile")

    old_q = (
        db.query(Quote)
        .options(joinedload(Quote.lines), joinedload(Quote.job))
        .filter(Quote.id == new_q.parent_quote_id).first()
    )
    if not old_q:
        raise HTTPException(400, "Parent quote non trovata")

    job = old_q.job
    # Map old_line_id → new_line per re-bind
    new_line_by_parent = {l.parent_line_id: l for l in new_q.lines if l.parent_line_id}

    job_action = None
    cost_lines_rebound = 0
    cost_lines_orphaned = 0
    cost_lines_created = 0

    if job:
        # Re-bind dei JobCostLine via parent_line_id
        for jcl in list(job.cost_lines):
            if jcl.is_extra:
                continue  # extra puri non toccati
            if jcl.quote_line_id and jcl.quote_line_id in new_line_by_parent:
                # Re-bind: punta alla riga V_new corrispondente
                new_line = new_line_by_parent[jcl.quote_line_id]
                jcl.quote_line_id = new_line.id
                # Aggiorna i campi "pianificati" da V_new (descrizione, quantity_quoted, ecc.)
                jcl.description = new_line.description
                jcl.price_item_id = new_line.price_item_id
                jcl.quantity_quoted = new_line.quantity
                jcl.unit = new_line.unit
                jcl.unit_price = new_line.unit_price
                jcl.total_quoted = new_line.total
                # quantity_actual NON tocco (è effettivo registrato)
                cost_lines_rebound += 1
            else:
                # Orfano: la riga V_old non esiste più in V_new
                if orphan_strategy == "keep_as_extra":
                    jcl.quote_line_id = None
                    jcl.is_extra = True
                cost_lines_orphaned += 1

        # Crea JobCostLine per righe nuove (presenti in V_new ma non in V_old)
        existing_new_line_ids = {jcl.quote_line_id for jcl in job.cost_lines if jcl.quote_line_id}
        for nl in new_q.lines:
            if nl.id not in existing_new_line_ids:
                # È una riga "fresh" (nuova in V_new): crea JobCostLine
                db.add(JobCostLine(
                    job_id=job.id,
                    quote_line_id=nl.id,
                    price_item_id=nl.price_item_id,
                    description=nl.description,
                    quantity_quoted=nl.quantity,
                    unit=nl.unit,
                    unit_price=nl.unit_price,
                    total_quoted=nl.total,
                    total_expected=nl.total,
                ))
                cost_lines_created += 1

        if orphan_strategy == "floating_job":
            job.quote_id = None
            job_action = "floated"
        else:
            job.quote_id = new_q.id
            job_action = "rebound"
        # Aggiorna budget_quoted al nuovo totale
        job.budget_quoted = new_q.total_after_discount

    # Aggiorna stati delle quote
    new_q.status = QuoteStatus.approved
    old_q.status = QuoteStatus.superseded
    old_q.superseded_by_id = new_q.id

    db.commit()

    return {
        "ok": True,
        "old_quote_id": old_q.id,
        "old_quote_number": old_q.number,
        "old_quote_status": old_q.status,
        "new_quote_id": new_q.id,
        "new_quote_number": new_q.number,
        "new_quote_status": new_q.status,
        "job_action": job_action,  # "rebound" | "floated" | None
        "job_id": job.id if job else None,
        "cost_lines_rebound": cost_lines_rebound,
        "cost_lines_orphaned": cost_lines_orphaned,
        "cost_lines_created": cost_lines_created,
        "orphan_strategy": orphan_strategy,
    }
