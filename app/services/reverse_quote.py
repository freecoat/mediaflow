"""
Reverse quote-flow (v3.4.52) — booking su progetto senza quotazione attiva.

Architettura:
- Il booking è il driver. La sua durata (somma assignments) è la "domanda di ore".
- L'utente (producer) sceglie SOLO la voce di listino conforme. Quantità e prezzo
  sono derivati: qty = ore / 8 se unit=day, ore se unit=hour, 1 altrimenti.
- Due modalità:
    1) `attach_existing` — esiste una quote in draft|sent: si aggiunge la riga,
       la quote viene **implicitamente approvata** (status=approved), il Job viene
       auto-creato col flusso forward standard, gli account manager (permesso
       `edit_quotes`) ricevono notifica perché potrebbero voler attivare la
       procedura di migrate-job/versioning.
    2) `create_phantom` — non esiste alcuna quote: viene creata una `Quote` con
       `is_phantom=True`, status=approved, una sola line, e il Job viene
       auto-creato. Phantom quote = mai inviata al cliente; può essere promossa
       a quote di riferimento da /finance toggling `is_phantom=False`.
"""
from datetime import date as _date
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Job, JobCostLine, NotificationKind, NotificationSeverity, PriceItem,
    Project, Quote, QuoteLine, QuoteStatus, User,
)


WORKING_HOURS_PER_DAY = 8.0


def compute_quantity_from_hours(hours: float, unit: str) -> float:
    """Converte ore-persona in quantità coerente con l'unità del listino.

    - "day" → ore / 8 (giornata standard)
    - "hour" / "h" → ore così come sono
    - altrimenti → 1.0 (one-shot deliverable, l'utente potrà aggiustare)
    """
    if hours <= 0:
        return 1.0
    u = (unit or "day").strip().lower()
    if u in ("hour", "hours", "h", "ora", "ore"):
        return round(hours, 2)
    if u in ("day", "days", "d", "giorno", "giorni"):
        return round(hours / WORKING_HOURS_PER_DAY, 2)
    return 1.0


def _next_position(quote: Quote) -> str:
    """Calcola posizione progressiva 'A.{N+1}' per la nuova riga."""
    used = []
    for ln in quote.lines:
        try:
            tail = (ln.position or "").rsplit(".", 1)[-1]
            used.append(int(tail))
        except (ValueError, IndexError):
            pass
    n = (max(used) + 1) if used else len(quote.lines) + 1
    return f"A.{n}"


def _next_sort_order(quote: Quote) -> int:
    if not quote.lines:
        return 10
    return max((ln.sort_order or 0) for ln in quote.lines) + 10


def add_line_from_price_item(
    db: Session,
    quote: Quote,
    price_item: PriceItem,
    *,
    quantity: float,
    description_override: Optional[str] = None,
    allow_zero: bool = False,
) -> QuoteLine:
    """Aggiunge una QuoteLine alla quote a partire da una voce di listino.
    Eredita unit, unit_price, hardcosts. Calcola total = qty × unit_price.

    v3.5.0-alpha.171.4 — `allow_zero=True` permette quantity=0 (usato per
    voci di Quotazione a Consuntivo: la voce esiste a preventivo ma con
    quantità preventivata=0, le ore reali vengono dai booking via JCL
    `quantity_actual`).
    """
    if quantity < 0 or (quantity == 0 and not allow_zero):
        raise HTTPException(400, "quantity deve essere > 0 (o = 0 con allow_zero)")
    desc = (description_override or price_item.name or "").strip()[:255]
    unit = (price_item.unit or "day")
    unit_price = float(price_item.price_list or 0.0)
    total = round(quantity * unit_price, 2)
    line = QuoteLine(
        price_item_id=price_item.id,
        section="A",
        position=_next_position(quote),
        description=desc,
        quantity=quantity,
        unit=unit,
        unit_price=unit_price,
        total=total,
        hardcosts=float(price_item.hardcosts or 0.0),
        sort_order=_next_sort_order(quote),
    )
    line.quote = quote
    db.add(line)
    db.flush()
    return line


def _recalc_quote_totals(quote: Quote) -> None:
    """Ricalcolo minimale dei totali quote dopo aggiunta riga reverse.
    Volutamente ignoro sconti per categoria/pacchetto: la phantom non ne ha,
    e per attach_existing la riga reverse è 'puro accodamento' — l'AM rifarà
    il giro di sconti se serve."""
    subtotal_gross = 0.0
    subtotal = 0.0
    for ln in quote.lines:
        unit_price = float(ln.unit_price or 0.0)
        qty = float(ln.quantity or 0.0)
        allowance = float(ln.allowance or 0.0)
        line_disc = float(ln.line_discount_pct or 0.0)
        gross = qty * unit_price * (1 + allowance)
        net = gross * (1 - line_disc)
        subtotal_gross += gross
        subtotal += net
    quote.subtotal_gross = round(subtotal_gross, 2)
    quote.subtotal = round(subtotal, 2)
    pkg_disc = float(quote.package_discount or 0.0)
    quote.total_after_discount = round(subtotal * (1 - pkg_disc), 2)
    vat = float(quote.vat_rate or 0.0)
    quote.total_with_vat = round(quote.total_after_discount * (1 + vat / 100.0), 2)


def _ensure_job_for_quote(db: Session, quote: Quote) -> Job:
    """Crea (o riusa) il Job per una quote approvata. Riusa il forward-flow
    canonico in app.routers.quotes._create_job_from_quote."""
    from app.routers.quotes import _create_job_from_quote
    job = _create_job_from_quote(db, quote)
    db.flush()
    return job


def attach_to_pending_quote(
    db: Session,
    quote_id: int,
    project_id: int,
    price_item_id: int,
    quantity: float,
    actor: Optional[User] = None,
) -> dict:
    """Attacca una riga reverse a una quote draft|sent → approva implicitamente
    → ensure Job → notifica account managers.

    Vincoli:
    - quote_id deve appartenere al project_id
    - quote.status deve essere draft o sent (non approved/rejected/superseded)
    - price_item deve esistere
    """
    quote = db.query(Quote).filter(Quote.id == quote_id, Quote.project_id == project_id).first()
    if not quote:
        raise HTTPException(404, "Quote non trovata o non appartiene al progetto")
    if quote.status not in (QuoteStatus.draft, QuoteStatus.sent):
        raise HTTPException(
            400,
            f"La quote {quote.number} ha stato '{quote.status.value}', "
            "non è ammessa l'approvazione implicita reverse (solo da draft o sent)."
        )
    pi = db.query(PriceItem).filter(PriceItem.id == price_item_id).first()
    if not pi:
        raise HTTPException(404, "Voce listino non trovata")

    line = add_line_from_price_item(db, quote, pi, quantity=quantity)
    _recalc_quote_totals(quote)

    # Approvazione implicita
    prev_status = quote.status
    quote.status = QuoteStatus.approved

    # Ensure Job (forward-flow standard)
    job = _ensure_job_for_quote(db, quote)

    # v3.5.0-alpha.172.2 Restructure — branching JCL/Deliverable per unit.
    # _create_job_from_quote popola da q.lines AL MOMENTO creazione job:
    # se job esisteva già prima della reverse-attach, righe nuove non ci sono.
    # Le aggiungiamo ora secondo unit_nature.
    from app.models import JobDeliverable, DeliverableUnitNature, DeliverableBillingStatus
    TIME_UNITS = ("hr", "day")
    unit_l = (line.unit or "").strip().lower()
    jcl = None
    spawned_deliverables = []
    if unit_l in TIME_UNITS:
        jcl = db.query(JobCostLine).filter(
            JobCostLine.quote_line_id == line.id
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
    else:
        existing = db.query(JobDeliverable).filter(
            JobDeliverable.quote_line_id == line.id,
            JobDeliverable.job_id == job.id,
        ).count()
        if existing == 0:
            # v3.5.0-alpha.172.14 — Spawn rule per nature (vedi quotes.py):
            # deliverable_qty → N row 1 per unità; volume/manual_allow → 1 row aggregato.
            from app.services.cost_line_sync import unit_nature_for
            nature_code = unit_nature_for(line.unit)
            nature = DeliverableUnitNature(nature_code)
            qty_total = float(line.quantity or 0.0)
            up = float(line.unit_price or 0.0)
            if nature_code == "deliverable_qty":
                n_rows = max(1, int(round(qty_total)))
                per_row_qty = 1.0
            else:
                n_rows = 1
                per_row_qty = qty_total if qty_total > 0 else 1.0
            for idx in range(n_rows):
                d = JobDeliverable(
                    tenant_id=quote.tenant_id,
                    job_id=job.id,
                    quote_line_id=line.id,
                    price_item_id=line.price_item_id,
                    name=line.description,
                    unit=line.unit,
                    unit_price=up,
                    unit_nature=nature,
                    quantity_planned=per_row_qty,
                    quantity_delivered=0.0,
                    total_quoted=round(per_row_qty * up, 2),
                    total_accrued=0.0,
                    total_cost_accrued=0.0,
                    billing_status=DeliverableBillingStatus.not_billed,
                )
                db.add(d); db.flush()
                spawned_deliverables.append(d.id)

    db.commit()
    db.refresh(quote); db.refresh(job); db.refresh(line)
    if jcl:
        db.refresh(jcl)

    # Notifica account managers (permesso edit_quotes)
    try:
        from app.services.notifications import notify_permission
        notify_permission(
            db,
            permission="edit_quotes",
            exclude_user_ids=[actor.id] if actor else None,
            kind=NotificationKind.quote_reverse_approval.value,
            severity=NotificationSeverity.action_required.value,
            title=f"Quote {quote.number} approvata implicitamente (reverse-flow)",
            body=(
                f"Riga aggiunta da booking su progetto '{quote.project.title if quote.project else '?'}': "
                f"{line.quantity}× {line.description} = € {line.total:.2f}. "
                f"Stato precedente: {prev_status.value}. Verifica e attiva eventuali "
                f"procedure di migrate-job o versioning standard."
            ),
            link=f"/quotes#{quote.id}",
            payload={
                "quote_id": quote.id, "quote_number": quote.number,
                "job_id": job.id, "job_code": job.code,
                "line_id": line.id, "amount": line.total,
                "previous_status": prev_status.value,
            },
            actor_user_id=actor.id if actor else None,
        )
    except Exception as e:
        print(f"[reverse_quote] notify failed: {e}")

    return {
        "quote_id": quote.id, "quote_number": quote.number,
        "quote_status": quote.status.value,
        "previous_status": prev_status.value,
        "is_phantom": False,
        "job_id": job.id, "job_code": job.code,
        "cost_line_id": jcl.id if jcl else None,
        "cost_line_description": jcl.description if jcl else line.description,
        "deliverable_ids": spawned_deliverables,
        "was_implicit_approval": True,
    }


def add_line_to_existing_phantom(
    db: Session,
    phantom_quote: Quote,
    price_item: PriceItem,
    quantity_hint: float,
    actor: Optional[User] = None,
) -> dict:
    """v3.5.0-alpha.171.4 — Aggiunge una voce a una Quotazione a Consuntivo
    già esistente (standby). Voce parte SEMPRE da quantity_quoted=0
    (regola Matteo): la lavorazione esiste a preventivo ma il monte ore
    quotato è 0, le ore reali confluiscono via booking → JCL.quantity_actual.

    `quantity_hint` non viene applicato alla QuoteLine; serve solo per
    contesto/log. La JCL collegata verrà sincronizzata da `cost_line_sync`
    quando i booking done emergono.
    """
    line = add_line_from_price_item(
        db, phantom_quote, price_item, quantity=0.0, allow_zero=True
    )
    _recalc_quote_totals(phantom_quote)

    job = _ensure_job_for_quote(db, phantom_quote)
    db.flush()

    jcl = db.query(JobCostLine).filter(JobCostLine.quote_line_id == line.id).first()
    db.commit()
    db.refresh(phantom_quote); db.refresh(line)
    if jcl: db.refresh(jcl)
    if job: db.refresh(job)

    try:
        from app.services.notifications import notify_permission
        notify_permission(
            db,
            permission="edit_quotes",
            exclude_user_ids=[actor.id] if actor else None,
            kind=NotificationKind.quote_reverse_approval.value,
            severity=NotificationSeverity.info.value,
            title=f"Voce aggiunta a Quotazione a Consuntivo {phantom_quote.number}",
            body=(
                f"Voce '{line.description}' aggiunta alla Consuntivo standby (qty quotata=0, "
                f"ore reali da booking). Decidere se promuovere o accorpare la Consuntivo."
            ),
            link=f"/quotes#{phantom_quote.id}",
            payload={
                "quote_id": phantom_quote.id, "quote_number": phantom_quote.number,
                "line_id": line.id, "is_phantom": True, "added_to_existing": True,
            },
            actor_user_id=actor.id if actor else None,
        )
    except Exception as e:
        print(f"[reverse_quote] notify failed (existing phantom): {e}")

    return {
        "quote_id": phantom_quote.id, "quote_number": phantom_quote.number,
        "quote_status": phantom_quote.status.value,
        "previous_status": None,
        "is_phantom": True,
        "added_to_existing_phantom": True,
        "job_id": job.id if job else None,
        "job_code": job.code if job else None,
        "cost_line_id": jcl.id if jcl else None,
        "cost_line_description": jcl.description if jcl else line.description,
        "was_implicit_approval": False,
    }


def create_phantom_quote_with_line(
    db: Session,
    project: Project,
    price_item_id: int,
    quantity: float,
    title: Optional[str] = None,
    actor: Optional[User] = None,
) -> dict:
    """v3.5.0-alpha.171.2 (Sprint 2 Step 2) — Crea "Quotazione a Consuntivo"
    (ex "Phantom Quote") con una line dal listino + Job auto-creato.

    Pre-condizioni (regola Matteo redesign):
    - Progetto NON deve avere quote attiva con status sent/approved
      (forward-flow normale → usa quote esistente, non Consuntivo)
    - Progetto NON deve avere già una Consuntivo standby (UNIQUE 1-per-progetto)

    Effetti:
    - Crea Quote(is_phantom=True, phantom_status=standby, status=approved)
    - Crea Job + JCL legate
    - Notifica account managers per decisione promozione/accorpamento
    """
    from app.models import PhantomStatus
    pi = db.query(PriceItem).filter(PriceItem.id == price_item_id).first()
    if not pi:
        raise HTTPException(404, "Voce listino non trovata")

    # Pre-check 1: no Consuntivo se quote attiva (sent/approved non-phantom).
    active_quote = next(
        (q for q in (project.quotes or [])
         if q.status in (QuoteStatus.sent, QuoteStatus.approved)
         and not getattr(q, "is_phantom", False)),
        None,
    )
    if active_quote:
        raise HTTPException(
            409,
            f"Impossibile creare Quotazione a Consuntivo: il progetto ha già la quote "
            f"{active_quote.number} ({active_quote.status.value}). "
            f"Aggancia il booking alla quote esistente."
        )

    # v3.5.0-alpha.171.4 (Step 4) — Se Consuntivo standby esiste, NON
    # bloccare con 409: AGGIUNGI la voce alla Consuntivo esistente (regola
    # Matteo: "Eventuali nuove lavorazioni si legano alla phantom esistente").
    existing_standby = next(
        (q for q in (project.quotes or [])
         if getattr(q, "is_phantom", False)
         and getattr(q, "phantom_status", None) == PhantomStatus.standby),
        None,
    )
    if existing_standby:
        return add_line_to_existing_phantom(db, existing_standby, pi, quantity, actor)

    from app.routers.quotes import _next_quote_number_progressive
    today = _date.today()
    quote = Quote(
        number=_next_quote_number_progressive(db),
        version=1,
        project_id=project.id,
        client_id=project.client_id,
        title=(title or f"Consuntivo — {project.title}").strip()[:255],
        status=QuoteStatus.approved,
        is_phantom=True,
        phantom_status=PhantomStatus.standby,
        issue_date=today,
        notes="Quotazione a Consuntivo: generata da booking reverse-flow. Mai inviata al cliente. In standby: in attesa di promozione o accorpamento.",
    )
    db.add(quote)
    db.flush()

    # v3.5.0-alpha.171.4 — Voci Consuntivo partono da quantity=0: la voce
    # esiste a preventivo (per binding listino + price) ma la quantità
    # preventivata è 0. Le ore reali confluiscono in JCL.quantity_actual
    # tramite cost_line_sync su booking done. Regola Matteo redesign.
    line = add_line_from_price_item(db, quote, pi, quantity=0.0, allow_zero=True)
    _recalc_quote_totals(quote)

    job = _ensure_job_for_quote(db, quote)
    db.flush()

    jcl = db.query(JobCostLine).filter(JobCostLine.quote_line_id == line.id).first()
    # Anche JCL.quantity_quoted parte da 0 (la JCL viene creata da
    # _ensure_job_for_quote che eredita dalla QuoteLine).
    db.commit()
    db.refresh(quote); db.refresh(job); db.refresh(line)
    if jcl: db.refresh(jcl)

    try:
        from app.services.notifications import notify_permission
        notify_permission(
            db,
            permission="edit_quotes",
            exclude_user_ids=[actor.id] if actor else None,
            kind=NotificationKind.quote_reverse_approval.value,
            severity=NotificationSeverity.action_required.value,
            title=f"Quotazione a Consuntivo {quote.number} creata (reverse-flow)",
            body=(
                f"Booking su progetto '{project.title}' senza quote attiva → "
                f"creata Quotazione a Consuntivo (standby): {line.quantity}× {line.description} = € {line.total:.2f}. "
                f"Promuovibile a quote di riferimento o accorpabile a quote esistente."
            ),
            link=f"/quotes#{quote.id}",
            payload={
                "quote_id": quote.id, "quote_number": quote.number,
                "job_id": job.id, "job_code": job.code,
                "line_id": line.id, "amount": line.total,
                "is_phantom": True,
            },
            actor_user_id=actor.id if actor else None,
        )
    except Exception as e:
        print(f"[reverse_quote] notify failed: {e}")

    return {
        "quote_id": quote.id, "quote_number": quote.number,
        "quote_status": quote.status.value,
        "previous_status": None,
        "is_phantom": True,
        "job_id": job.id, "job_code": job.code,
        "cost_line_id": jcl.id if jcl else None,
        "cost_line_description": jcl.description if jcl else line.description,
        "was_implicit_approval": False,
    }
