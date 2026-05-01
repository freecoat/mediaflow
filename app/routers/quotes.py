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
    """
    cat_disc = quote.category_discounts or {}
    subtotal_gross = 0.0
    cat_buckets: dict[str, float] = {}

    for l in quote.lines:
        gross = (l.quantity or 0.0) * (l.unit_price or 0.0) * (1 + (l.allowance or 0.0))
        net_after_line = gross * (1 - (l.line_discount_pct or 0.0))
        l.total = round(net_after_line, 2)
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
    if package_discount is not None: q.package_discount = package_discount
    if vat_rate is not None: q.vat_rate = vat_rate
    if notes is not None: q.notes = notes
    if payment_terms is not None: q.payment_terms = payment_terms
    _recalc_quote(q)
    db.commit()
    return {
        "id": q.id,
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
    line = QuoteLine(
        quote_id=quote_id, description=description, section=section,
        position=position, detail=detail, quantity=quantity, unit=unit,
        price_level=price_level, unit_price=unit_price,
        allowance=allowance, line_discount_pct=line_discount_pct,
        total=0.0, hardcosts=hardcosts,
        price_item_id=price_item_id, sort_order=sort_order,
        category_override=cat_override_clean,
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
        "job_cost_line_synced": job_cost_line_synced,
    }


@router.delete("/api/{quote_id}/lines/{line_id}")
async def delete_quote_line(quote_id: int, line_id: int, db: Session = Depends(get_db)):
    """v3.4.36 (R1.1): cascade ai JobCostLine collegati. Per ogni JobCostLine
    con quote_line_id=line_id, soft-detach i Booking/TimePunch (job_cost_line_id
    → NULL) e poi cancella la JobCostLine. Blocca se job in stato terminale."""
    line = db.query(QuoteLine).filter(QuoteLine.id == line_id).first()
    if not line:
        raise HTTPException(404)

    # Trova JobCostLine collegate
    cost_lines = db.query(JobCostLine).filter(
        JobCostLine.quote_line_id == line_id
    ).all()
    for jcl in cost_lines:
        # Blocca se il job è in stato terminale (no retroattive)
        if jcl.job and jcl.job.status in (JobStatus.completed, JobStatus.invoiced):
            raise HTTPException(
                409,
                f"Impossibile cancellare: il job {jcl.job.code} è in stato "
                f"{jcl.job.status.value} e ha già consuntivato questa lavorazione."
            )
        # Soft-detach: Booking → SET NULL job_cost_line_id
        db.query(Booking).filter(
            Booking.job_cost_line_id == jcl.id
        ).update({"job_cost_line_id": None}, synchronize_session=False)
        # Soft-detach: TimePunch → SET NULL job_cost_line_id
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
