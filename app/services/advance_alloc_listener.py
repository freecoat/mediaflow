"""v3.5.0-alpha.166 — Auto-sync pct derivato su AdvancePaymentAllocation.

`AdvancePaymentAllocation.amount` è autoritativo. `pct` resta come campo display
(`= amount / AdvancePayment.amount`). Per evitare drift quando codice legacy
modifica amount senza aggiornare pct, listener before_insert/before_update
ricalcola pct automaticamente.

Idempotente: se AP.amount = 0 (caso edge) pct viene messo a 0.0.
"""
from __future__ import annotations

from sqlalchemy import event, select

from app.models import AdvancePayment, AdvancePaymentAllocation


def _recompute_pct(connection, target: AdvancePaymentAllocation) -> None:
    if target.advance_payment_id is None:
        return
    ap_amt = connection.execute(
        select(AdvancePayment.amount).where(AdvancePayment.id == target.advance_payment_id)
    ).scalar()
    if ap_amt is None or ap_amt <= 0:
        target.pct = 0.0
        return
    amt = target.amount or 0.0
    target.pct = round(amt / float(ap_amt), 6)


@event.listens_for(AdvancePaymentAllocation, "before_insert")
def _on_insert(mapper, connection, target: AdvancePaymentAllocation) -> None:  # noqa: ARG001
    _recompute_pct(connection, target)


@event.listens_for(AdvancePaymentAllocation, "before_update")
def _on_update(mapper, connection, target: AdvancePaymentAllocation) -> None:  # noqa: ARG001
    _recompute_pct(connection, target)


def install() -> None:
    """Import-time side-effect register listeners. Funzione no-op pubblica per
    forzare import esplicito da main.py / startup. Idempotente."""
    return None
