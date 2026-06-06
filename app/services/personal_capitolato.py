"""Capitolato Personale — un DeliveryTemplate per-tenant che ospita i preset
audio ad-hoc definiti dall'utente (non legati a un capitolato d'emittente).

v3.5.0-alpha.172.203 — Supporto preset audio custom (AudioConfigPreset CRUD).
Gli AudioConfigPreset sono legati a UN DeliveryTemplate (UniqueConstraint su
delivery_template_id+code). I preset "liberi" salvati dall'utente vivono qui.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import DeliveryTemplate

# Codice riservato del capitolato personale (uno per tenant).
PERSONAL_TEMPLATE_CODE = "PERSONAL-PRESETS"
PERSONAL_TEMPLATE_NAME = "Capitolato Personale"
PERSONAL_TEMPLATE_BROADCASTER = "Personale"


def get_or_create_personal_template(db: Session, tenant_id: int) -> DeliveryTemplate:
    """Ritorna (creando se assente) il DeliveryTemplate "Capitolato Personale"
    del tenant. Idempotente: un solo record per tenant identificato dal
    code=PERSONAL_TEMPLATE_CODE. Se manca lo crea + flush (commit al chiamante).
    """
    tpl = (
        db.query(DeliveryTemplate)
        .filter(
            DeliveryTemplate.tenant_id == tenant_id,
            DeliveryTemplate.code == PERSONAL_TEMPLATE_CODE,
        )
        .first()
    )
    if tpl:
        return tpl
    tpl = DeliveryTemplate(
        tenant_id=tenant_id,
        code=PERSONAL_TEMPLATE_CODE,
        name=PERSONAL_TEMPLATE_NAME,
        broadcaster=PERSONAL_TEMPLATE_BROADCASTER,
        version="1.0",
        description="Preset audio personalizzati definiti dall'utente.",
        ai_generated=False,
        is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl
