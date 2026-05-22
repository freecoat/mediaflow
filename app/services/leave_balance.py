"""Saldo dinamico ferie/ROL/permessi (α.172.29).

Calcolato on-demand: NO colonna materializzata. Source of truth =
ResourceUnavailability (consumate) + WorkingHoursPolicy params (maturate).

Convenzioni:
- 1 giorno ferie = `policy.daily_hours_threshold` ore (default 8.0).
- Maturate al pro-rata dei mesi trascorsi dell'anno (mese corrente incluso).
  Es. al 15 marzo: maturate = annual_leave * (3/12) ≈ 25%.
- Override per-resource in `Resource.*_override` ha priorità sui default WHP.
- ResourceUnavailability con `start_time`/`end_time` popolati conta `hours_duration`
  effettive. Altrimenti conta come N giorni interi (end-start+1) * daily_hours.

Pattern: separated balances per kind: ferie / ROL / permessi retribuiti.
Malattia non ha saldo (non si "consuma"), solo conteggio gg/ore.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Resource, ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
    WorkingHoursPolicy,
)


def _resolve_policy(db: Session, resource: Resource) -> Optional[WorkingHoursPolicy]:
    """Policy effettiva: override per-risorsa OR default tenant."""
    if resource.working_hours_policy_id:
        return db.query(WorkingHoursPolicy).filter(
            WorkingHoursPolicy.id == resource.working_hours_policy_id,
        ).first()
    return db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == resource.tenant_id,
        WorkingHoursPolicy.is_default == True,  # noqa: E712
    ).first()


def _unavailability_hours(u: ResourceUnavailability, daily_hours: float) -> float:
    """Ore consumate da una unavailability (parziale o giorno intero)."""
    if u.is_partial and u.hours_duration is not None:
        return float(u.hours_duration or 0.0)
    if u.is_partial:
        # Fallback: calcola da start_time/end_time se hours_duration mancante
        if u.start_time and u.end_time:
            sm = u.start_time.hour * 60 + u.start_time.minute
            em = u.end_time.hour * 60 + u.end_time.minute
            return max(0.0, (em - sm) / 60.0)
        return 0.0
    # Giorno intero: span giorni × daily_hours
    days = (u.end_date - u.start_date).days + 1
    return days * daily_hours


def _is_employee_eligible(resource: Resource) -> bool:
    """α.172.32.1 — Accrual ferie/ROL/permessi si applica SOLO ai dipendenti
    (`person_internal`). Freelance e non-umane sono escluse:
    - Freelance: pagati per giornata/ora, no maturazione
    - Studio/equipment/software/vehicle: cose, non persone
    `person` (legacy pre-α.111) trattato come dipendente per back-compat.
    """
    from app.models import ResourceType
    t = resource.type
    return t in (ResourceType.person_internal, getattr(ResourceType, "person", None))


def compute_leave_balance(
    db: Session,
    resource_id: int,
    year: Optional[int] = None,
    as_of: Optional[date] = None,
) -> dict:
    """Ritorna saldo per risorsa+anno. `as_of` default = oggi.

    Output:
    ```
    {
      "year": 2026,
      "resource_id": 12,
      "as_of": "2026-05-22",
      "daily_hours": 8.0,
      "ferie": {
        "annual_days": 26.0, "matured_days": 10.5,
        "consumed_hours": 16, "consumed_days_eq": 2.0,
        "residual_days": 8.5, "residual_hours": 68.0
      },
      "rol": {"matured_hours": 40.0, "consumed_hours": 8, "residual_hours": 32.0},
      "permit": {"matured_hours": 40.0, "consumed_hours": 0, "residual_hours": 40.0},
      "sick_days": 3.0, "sick_hours": 24.0,
    }
    ```
    """
    if year is None:
        year = (as_of or date.today()).year
    if as_of is None:
        as_of = date.today()
    if as_of.year != year:
        # Se "as_of" è di altro anno, prendiamo fine anno corrente per il pro-rata
        as_of = date(year, 12, 31)

    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        return {"error": "resource_not_found"}

    # α.172.32.1 — Solo dipendenti (person_internal) maturano ferie/ROL/permessi
    if not _is_employee_eligible(resource):
        return {
            "not_applicable": True,
            "reason": "Saldi non applicabili: solo dipendenti maturano ferie/ROL/permessi (freelance e risorse non umane esclusi).",
            "resource_id": resource_id,
            "resource_type": resource.type.value if resource.type else None,
        }

    policy = _resolve_policy(db, resource)
    daily_hours = policy.daily_hours_threshold if policy else 8.0

    # Maturate (pro-rata sul mese as_of; ferie su intero anno se richiesto fine anno)
    months_elapsed = as_of.month if as_of.year == year else 12
    # Considera anche giorni del mese in corso (pro-rata frazionario)
    days_in_month = 30.4375  # media giorni/mese
    months_frac = months_elapsed - 1 + (as_of.day / days_in_month) if as_of.year == year else 12

    annual_leave = (
        resource.annual_leave_days_override
        if resource.annual_leave_days_override is not None
        else (policy.annual_leave_days_default if policy else 26.0)
    )
    rol_monthly = (
        resource.monthly_rol_hours_override
        if resource.monthly_rol_hours_override is not None
        else (policy.monthly_rol_hours_accrual if policy else 8.0)
    )
    permit_monthly = (
        resource.monthly_permit_hours_override
        if resource.monthly_permit_hours_override is not None
        else (policy.monthly_permit_hours_accrual if policy else 8.0)
    )

    matured_ferie_days = annual_leave * (months_frac / 12.0)
    matured_rol_hours = rol_monthly * months_frac
    matured_permit_hours = permit_monthly * months_frac

    # Consumate (status=approved, anno richiesto, overlap)
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    rows = db.query(ResourceUnavailability).filter(
        ResourceUnavailability.resource_id == resource_id,
        ResourceUnavailability.status == UnavailabilityStatus.approved,
        ResourceUnavailability.start_date <= year_end,
        ResourceUnavailability.end_date >= year_start,
    ).all()

    consumed_ferie_h = 0.0
    consumed_rol_h = 0.0
    consumed_permit_h = 0.0
    sick_h = 0.0
    for u in rows:
        hrs = _unavailability_hours(u, daily_hours)
        if u.kind == UnavailabilityKind.vacation:
            consumed_ferie_h += hrs
        elif u.kind == UnavailabilityKind.permit_rol:
            consumed_rol_h += hrs
        elif u.kind == UnavailabilityKind.recovery:
            # Recupero ore: scarica saldo ROL come permesso
            consumed_rol_h += hrs
        elif u.kind == UnavailabilityKind.sick:
            sick_h += hrs
        elif u.kind == UnavailabilityKind.other:
            consumed_permit_h += hrs
        # holiday non scarica (è festività auto)

    matured_ferie_h = matured_ferie_days * daily_hours
    return {
        "year": year,
        "resource_id": resource_id,
        "as_of": as_of.isoformat(),
        "daily_hours": daily_hours,
        "ferie": {
            "annual_days": round(annual_leave, 2),
            "matured_days": round(matured_ferie_days, 2),
            "matured_hours": round(matured_ferie_h, 2),
            "consumed_hours": round(consumed_ferie_h, 2),
            "consumed_days_eq": round(consumed_ferie_h / daily_hours, 2) if daily_hours else 0,
            "residual_hours": round(matured_ferie_h - consumed_ferie_h, 2),
            "residual_days": round((matured_ferie_h - consumed_ferie_h) / daily_hours, 2) if daily_hours else 0,
        },
        "rol": {
            "monthly_accrual": round(rol_monthly, 2),
            "matured_hours": round(matured_rol_hours, 2),
            "consumed_hours": round(consumed_rol_h, 2),
            "residual_hours": round(matured_rol_hours - consumed_rol_h, 2),
        },
        "permit": {
            "monthly_accrual": round(permit_monthly, 2),
            "matured_hours": round(matured_permit_hours, 2),
            "consumed_hours": round(consumed_permit_h, 2),
            "residual_hours": round(matured_permit_hours - consumed_permit_h, 2),
        },
        "sick_hours": round(sick_h, 2),
        "sick_days_eq": round(sick_h / daily_hours, 2) if daily_hours else 0,
    }
