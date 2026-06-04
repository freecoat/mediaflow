"""Collega un JobDeliverable orfano (quote_line_id NULL) a una riga di una
phantom/ghost quote (Consuntivo) del progetto, per renderlo tracciabile.

Parte del fix orphan-deliverables (Task 3). Quando un deliverable manuale
viene creato direttamente su un job senza passare da una riga di quote, resta
"orfano": non compare nella catena di tracciabilità quote→job. Questo servizio
crea (o riusa) una phantom quote "Consuntivo" a livello progetto e ci aggancia
una riga che rappresenta il deliverable, popolando il suo quote_line_id.
"""
from __future__ import annotations

from datetime import date as _date

from sqlalchemy.orm import Session

from app.context import current_tenant_id
from app.models import models as m
from app.models.models import PhantomStatus, QuoteStatus


def _get_or_create_project_phantom(db: Session, project_id: int, client_id: int):
    """Riusa la phantom standby del progetto, o la crea se assente."""
    existing = db.query(m.Quote).filter(
        m.Quote.project_id == project_id,
        m.Quote.is_phantom == True,  # noqa: E712
        m.Quote.phantom_status == PhantomStatus.standby,
    ).first()
    if existing:
        return existing
    from app.routers.quotes import _next_quote_number_progressive
    ph = m.Quote(
        number=_next_quote_number_progressive(db),
        version=1,
        project_id=project_id,
        client_id=client_id,
        title="Consuntivo — extra deliverable",
        status=QuoteStatus.approved,
        is_phantom=True,
        phantom_status=PhantomStatus.standby,
        issue_date=_date.today(),
        tenant_id=current_tenant_id(),
    )
    db.add(ph)
    db.flush()
    return ph


def link_deliverable_to_ghost(db: Session, deliverable_id: int) -> dict:
    """Collega il deliverable orfano a una riga di phantom quote.

    Idempotente: se già linkato, ritorna no-op con already_linked=True.
    """
    tid = current_tenant_id()
    d = db.query(m.JobDeliverable).filter(
        m.JobDeliverable.id == deliverable_id,
        m.JobDeliverable.tenant_id == tid,
    ).first()
    if not d:
        raise ValueError(f"Deliverable #{deliverable_id} non trovato")
    if d.quote_line_id:
        return {
            "ok": True,
            "already_linked": True,
            "quote_line_id": d.quote_line_id,
            "quote_id": None,
        }
    job = db.query(m.Job).filter(m.Job.id == d.job_id).first()
    if not job:
        raise ValueError("Job del deliverable non trovato")
    phantom = _get_or_create_project_phantom(db, job.project_id, job.client_id)

    from app.services.reverse_quote import _next_position, _next_sort_order
    qty = d.quantity_planned or 1.0
    price = d.unit_price or 0.0
    ql = m.QuoteLine(
        quote_id=phantom.id,
        price_item_id=d.price_item_id,
        section="A",
        position=_next_position(phantom),
        description=d.name or "Extra deliverable",
        quantity=qty,
        unit=d.unit or "pc",
        unit_price=price,
        total=round(qty * price, 2),
        sort_order=_next_sort_order(phantom),
        delivery_item_id=d.delivery_item_id,
    )
    db.add(ql)
    db.flush()
    d.quote_line_id = ql.id
    db.flush()
    return {
        "ok": True,
        "already_linked": False,
        "quote_id": phantom.id,
        "quote_line_id": ql.id,
    }
