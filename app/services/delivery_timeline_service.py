"""v3.5.0-alpha.172.127 — Eredità timeline/TC: l'item usa i propri campi se
valorizzati, altrimenti eredita i default del DeliveryTemplate (D3)."""
from __future__ import annotations
from sqlalchemy.orm import Session
from app.models.models import DeliveryItem, DeliveryTemplate


def effective_timeline(db: Session, item: DeliveryItem) -> dict:
    """Ritorna i valori timeline/TC effettivi + flag *_inherited per la UI."""
    tpl = db.get(DeliveryTemplate, item.delivery_template_id)

    def pick(item_val, tpl_val):
        if item_val not in (None, "", []):
            return item_val, False
        if tpl_val not in (None, "", []):
            return tpl_val, True
        return None, False

    tc, tc_inh = pick(item.tc_start, tpl.default_tc_start if tpl else None)
    pg, pg_inh = pick(item.program_start, tpl.default_program_start if tpl else None)
    seg, seg_inh = pick(item.timeline_segments,
                        tpl.default_timeline_segments if tpl else None)
    return {
        "tc_start": tc, "tc_start_inherited": tc_inh,
        "program_start": pg, "program_start_inherited": pg_inh,
        "timeline_segments": seg or [], "timeline_segments_inherited": seg_inh,
    }
