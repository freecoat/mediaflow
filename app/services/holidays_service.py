"""Festività efficaci per tenant/resource (α.172.29).

Combina holidays.IT nazionale (libreria `holidays`) con custom Holiday
tenant-scoped, gestendo scope per-resource e per-location.

API pubblica:
- `get_effective_holidays(db, tenant_id, year, resource_id=None)` → dict[date, str]
  Ritorna mappa date → nome festività efficaci per la resource (o tenant-wide).
- `get_effective_holiday_dates(...)` → set[date] (shortcut senza nomi)

Sostituisce gli usi diretti di `holidays.IT(...)` nel codice.
"""
from __future__ import annotations
from datetime import date
from typing import Optional, Dict, Set

from sqlalchemy import extract
from sqlalchemy.orm import Session

from app.models import Holiday, HolidayKind, Resource, Tenant


def _national_holidays(country_code: str, year: int) -> Dict[date, str]:
    """Ritorna nazionali (holidays lib). country_code es. 'IT'."""
    try:
        import holidays as _hol
    except Exception:
        return {}
    klass = getattr(_hol, country_code.upper(), None)
    if not klass:
        return {}
    try:
        return dict(klass(years=[year]).items())
    except Exception:
        return {}


def get_effective_holidays(
    db: Session,
    tenant_id: int,
    year: int,
    resource_id: Optional[int] = None,
) -> Dict[date, str]:
    """Risolve festività efficaci per la combinazione (tenant, resource, anno).

    α.172.33 — scope refactored su WorkingHoursPolicy:
    1. Se `tenant.use_national_holidays` → carica nazionali.
    2. Holiday con `scope_policy_id=NULL` (tenant-wide) → sempre applicato.
    3. Holiday con `scope_policy_id=P` → applicato solo se resource ha
       working_hours_policy_id=P (o policy default tenant=P se resource non
       ha override).
    4. `kind=exclude` rimuove date corrispondenti.
    5. `kind=national_override` sostituisce nome festività nazionale.

    `resource_id=None` → ritorna solo festività tenant-wide + nazionali
    (no policy-scope match).
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return {}

    out: Dict[date, str] = {}
    if tenant.use_national_holidays:
        out.update(_national_holidays(tenant.holidays_country_code or "IT", year))

    # Determina la policy effettiva della resource (override per-resource OR
    # policy default tenant). None se nessuna resource passata.
    effective_policy_id: Optional[int] = None
    if resource_id is not None:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if resource:
            if resource.working_hours_policy_id:
                effective_policy_id = resource.working_hours_policy_id
            else:
                from app.models import WorkingHoursPolicy
                default = db.query(WorkingHoursPolicy).filter(
                    WorkingHoursPolicy.tenant_id == tenant_id,
                    WorkingHoursPolicy.is_default == True,  # noqa: E712
                ).first()
                if default:
                    effective_policy_id = default.id

    q = db.query(Holiday).filter(
        Holiday.tenant_id == tenant_id,
        Holiday.is_active == True,  # noqa: E712
        extract("year", Holiday.date) == year,
    )

    for h in q.all():
        # Scope filtering (α.172.33 — policy-based)
        if h.scope_policy_id is not None:
            # Festività legata a policy specifica → applica solo se resource
            # ha quella policy effettiva
            if effective_policy_id != h.scope_policy_id:
                continue
        # else: tenant-wide → applica sempre

        if h.kind in (HolidayKind.local, HolidayKind.company):
            out[h.date] = h.name
        elif h.kind == HolidayKind.national_override:
            out[h.date] = h.name
        elif h.kind == HolidayKind.exclude:
            out.pop(h.date, None)

    return out


def get_effective_holiday_dates(
    db: Session,
    tenant_id: int,
    year: int,
    resource_id: Optional[int] = None,
) -> Set[date]:
    """Shortcut: solo le date, senza i nomi."""
    return set(get_effective_holidays(db, tenant_id, year, resource_id).keys())


def get_effective_holidays_range(
    db: Session,
    tenant_id: int,
    year_from: int,
    year_to: int,
    resource_id: Optional[int] = None,
) -> Dict[date, str]:
    """Aggrega effective holidays su un intervallo di anni."""
    out: Dict[date, str] = {}
    for y in range(year_from, year_to + 1):
        out.update(get_effective_holidays(db, tenant_id, y, resource_id))
    return out
