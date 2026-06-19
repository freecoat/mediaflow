"""Materializza la KDM prodotta come JobDeliverable nella lista consegne.

Chiamata automaticamente dalla FSM kdm_state.transition() quando lo
stato raggiunge 'generated'. Nessun effetto se il deliverable è già
stato creato (idempotente via job_deliverable_produced_id).
"""
from app.models.models import JobDeliverable, PriceItem, DeliverableStatus
from app.services.kdm_pricing import KDM_NAME, DKDM_NAME, ensure_kdm_price_items


def _job_id_for(db, req):
    """Risolvi il job dal DCP di origine matchato (job_deliverable_id → job_id)."""
    if req.job_deliverable_id:
        src = db.get(JobDeliverable, req.job_deliverable_id)
        if src is not None:
            return src.job_id
    return None


def materialize_produced_kdm(db, req) -> JobDeliverable:
    """Crea un JobDeliverable per la KDM/DKDM prodotta.

    Args:
        db: SQLAlchemy Session.
        req: KdmRequest in stato 'generated' (o successivo).

    Returns:
        Il JobDeliverable creato o già esistente.

    Raises:
        ValueError: se req non ha un job associato tramite job_deliverable_id.
    """
    # Idempotenza: se già materializzato, restituisce l'esistente
    if req.job_deliverable_produced_id:
        return db.get(JobDeliverable, req.job_deliverable_produced_id)

    # Risolvi il job dal DCP sorgente
    job_id = _job_id_for(db, req)
    if not job_id:
        raise ValueError("Richiesta senza job: aggancia prima un DCP/progetto")

    # Garantisce che le voci listino KDM/DKDM esistano per il tenant.
    # commit=False: siamo dentro l'unità di lavoro della FSM transition;
    # il commit finale è delegato al chiamante (router do_transition).
    ensure_kdm_price_items(db, req.tenant_id, commit=False)

    # Lookup voce listino per nome (PriceItem non ha campo code)
    name_lookup = KDM_NAME if (req.request_type or "kdm") == "kdm" else DKDM_NAME
    pi = (
        db.query(PriceItem)
        .filter(
            PriceItem.name == name_lookup,
            PriceItem.tenant_id == req.tenant_id,
        )
        .first()
    )

    # Nome descrittivo del deliverable
    title_part = req.requested_title or str(req.id)
    deliverable_name = f"{(req.request_type or 'kdm').upper()} — {title_part}"

    jd = JobDeliverable(
        tenant_id=req.tenant_id,
        job_id=job_id,
        name=deliverable_name,
        status=DeliverableStatus.delivered,
        price_item_id=pi.id if pi else None,
        delivered_date=req.generated_at.date() if req.generated_at else None,
    )

    # Quantità opzionali (guarded per robustezza schema)
    for fld, val in (("quantity_planned", 1), ("quantity_delivered", 1)):
        if hasattr(jd, fld):
            setattr(jd, fld, val)

    db.add(jd)
    db.flush()

    # Collega il deliverable prodotto alla richiesta
    req.job_deliverable_produced_id = jd.id
    db.flush()

    return jd
