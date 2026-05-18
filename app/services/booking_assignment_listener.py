"""v3.5.0-alpha.167 — Auto-snapshot cost_rate su BookingAssignment.

Pattern: cost_rate_snap viene popolato da Resource.internal_cost_hourly al
create/update assignment. cost_line_sync legge prima snapshot, fallback live.

Garantisce stabilità storica: modifica tariffa Resource futura NON impatta
assignment già esistenti (cashflow + match fatture fornitori preservato).

Trigger:
- before_insert: se cost_rate_snap NULL, popola da Resource attuale.
- before_update: se resource_id cambia, refresh snapshot dalla nuova Resource.
  Se cost_rate_snap viene esplicitamente settato dal caller (override),
  rispetta la scelta.

Idempotente: skip se Resource senza rate (cost_rate_snap resta NULL → cost_line_sync
fallback alla Resource live).
"""
from __future__ import annotations

from sqlalchemy import event, select
from sqlalchemy.orm.attributes import get_history

from app.models import BookingAssignment, Resource


def _fetch_rate(connection, resource_id: int) -> float | None:
    """Lookup Resource.internal_cost_hourly via raw SQL. Replica logica della
    property (cost_type-dependent) — vedi Resource.internal_cost_hourly in models.py."""
    if not resource_id:
        return None
    row = connection.execute(
        select(
            Resource.cost_type,
            Resource.monthly_gross_salary,
            Resource.annual_bonus_months,
            Resource.cost_multiplier_oneri,
            Resource.annual_working_hours,
            Resource.freelance_hourly_cost,
            Resource.studio_hourly_cost,
        ).where(Resource.id == resource_id)
    ).first()
    if not row:
        return None
    cost_type = (row.cost_type.value if hasattr(row.cost_type, "value") else row.cost_type) if row.cost_type else None
    if cost_type == "employee":
        salary = row.monthly_gross_salary or 0.0
        bonus = row.annual_bonus_months or 13.0
        mult = row.cost_multiplier_oneri or 1.30
        hours = row.annual_working_hours or 1720.0
        if salary <= 0 or hours <= 0:
            return None
        return round(salary * bonus * mult / hours, 2)
    if cost_type == "freelance":
        v = row.freelance_hourly_cost or 0.0
        return float(v) if v > 0 else None
    if cost_type == "studio":
        v = row.studio_hourly_cost or 0.0
        return float(v) if v > 0 else None
    return None  # external / None


@event.listens_for(BookingAssignment, "before_insert")
def _on_insert(mapper, connection, target: BookingAssignment) -> None:  # noqa: ARG001
    if target.cost_rate_snap is not None:
        return  # caller esplicito
    rate = _fetch_rate(connection, target.resource_id)
    target.cost_rate_snap = rate


@event.listens_for(BookingAssignment, "before_update")
def _on_update(mapper, connection, target: BookingAssignment) -> None:  # noqa: ARG001
    # Refresh snapshot SOLO se resource_id cambia. Cambi puri di datetime
    # non rivalutano cost_rate (sarebbe retroattivo).
    hist = get_history(target, "resource_id")
    if not hist.has_changes():
        return
    rate = _fetch_rate(connection, target.resource_id)
    target.cost_rate_snap = rate


def install() -> None:
    """No-op pubblica per import esplicito da main.py lifespan. Idempotente."""
    return None
