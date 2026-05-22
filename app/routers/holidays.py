"""Router festività custom (α.172.29).

Endpoint:
- `GET    /hr/api/holidays?year=2026` — lista festività custom + nazionali risolte
- `POST   /hr/api/holidays` — crea festività custom
- `PUT    /hr/api/holidays/{id}` — modifica
- `DELETE /hr/api/holidays/{id}` — soft (is_active=False)
- `POST   /hr/api/holidays/bulk-import` — import CSV (date,name,kind,scope_location)
- `GET    /hr/api/holidays/effective?year=2026&resource_id=` — risolte (nazionali+custom)
- `GET    /hr/api/leave-balance?resource_id=&year=` — saldo dinamico
"""
from __future__ import annotations
from datetime import date as _date, datetime
from typing import Optional
import csv
import io

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Body
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Holiday, HolidayKind, Resource
from app.services.rbac import current_user_optional, has_permission, is_elevated
from app.services.holidays_service import (
    get_effective_holidays, get_effective_holiday_dates,
)
from app.services.leave_balance import compute_leave_balance
from app.context import current_tenant_id

router = APIRouter(prefix="/hr", tags=["holidays"])


def _tpl():
    from app.main import templates
    return templates


@router.get("/holidays", response_class=HTMLResponse)
async def holidays_page(request: Request, db: Session = Depends(get_db)):
    """Pagina HTML gestione festività custom (α.172.29)."""
    user = current_user_optional(request)
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login?next=/hr/holidays", status_code=302)
    resources = db.query(Resource).filter(
        Resource.tenant_id == current_tenant_id(),
        Resource.is_active == True,  # noqa: E712
    ).order_by(Resource.name).all()
    resources_data = [
        {"id": r.id, "name": r.name, "loc": r.location_tag or ""} for r in resources
    ]
    # α.172.33 — policy CCNL tenant per scope dropdown
    from app.models import WorkingHoursPolicy
    policies = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == current_tenant_id(),
    ).order_by(WorkingHoursPolicy.is_default.desc(), WorkingHoursPolicy.name).all()
    policies_data = [
        {"id": p.id, "name": p.name, "is_default": p.is_default,
         "ccnl_label": p.ccnl_label or ""}
        for p in policies
    ]
    return _tpl().TemplateResponse(
        "pages/holidays.html",
        {
            "request": request,
            "resources": resources,
            "resources_data": resources_data,
            "policies": policies,
            "policies_data": policies_data,
            "kinds": [{"value": k.value, "label": _kind_label(k)} for k in HolidayKind],
            # α.172.33.1 — Rinominato da is_elevated (collideva con funzione
            # globale Jinja `is_elevated(_user)` chiamata in base.html).
            "user_is_elevated": is_elevated(user),
            "current_year": datetime.utcnow().year,
        },
    )


def _kind_label(k: HolidayKind) -> str:
    return {
        HolidayKind.local: "Locale (es. patrono cittadino)",
        HolidayKind.company: "Aziendale (es. ponte, chiusura)",
        HolidayKind.national_override: "Sostituisce nome nazionale",
        HolidayKind.exclude: "Esclude festività nazionale",
    }.get(k, k.value)


def _h_dict(h: Holiday) -> dict:
    return {
        "id": h.id,
        "tenant_id": h.tenant_id,
        "date": h.date.isoformat() if h.date else None,
        "name": h.name,
        "kind": h.kind.value if hasattr(h.kind, "value") else str(h.kind),
        "scope_policy_id": h.scope_policy_id,  # α.172.33
        "scope_resource_id": h.scope_resource_id,  # legacy, kept for back-compat
        "scope_location": h.scope_location,        # legacy
        "is_active": h.is_active,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


@router.get("/api/holidays")
async def list_holidays(
    request: Request,
    year: Optional[int] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Login richiesto")
    q = db.query(Holiday).filter(Holiday.tenant_id == current_tenant_id())
    if not include_inactive:
        q = q.filter(Holiday.is_active == True)  # noqa: E712
    if year:
        from sqlalchemy import extract
        q = q.filter(extract("year", Holiday.date) == year)
    rows = q.order_by(Holiday.date).all()
    return {"holidays": [_h_dict(h) for h in rows]}


@router.get("/api/holidays/effective")
async def list_effective_holidays(
    request: Request,
    year: int,
    resource_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Festività risolte (nazionali + custom + scope match). Read-only."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Login richiesto")
    eff = get_effective_holidays(db, current_tenant_id(), year, resource_id)
    return {
        "year": year,
        "resource_id": resource_id,
        "effective": [
            {"date": d.isoformat(), "name": name}
            for d, name in sorted(eff.items())
        ],
    }


@router.post("/api/holidays")
async def create_holiday(
    request: Request,
    date: _date = Form(...),
    name: str = Form(...),
    kind: HolidayKind = Form(HolidayKind.local),
    scope_policy_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea festività custom. α.172.33 — scope via WorkingHoursPolicy.
    NULL = tenant-wide (tutte le risorse). Altrimenti applica solo a risorse
    con quella policy effettiva (override o default tenant)."""
    user = current_user_optional(request)
    if not is_elevated(user):
        raise HTTPException(403, "Solo admin/manager/producer possono gestire festività")
    name = (name or "").strip()
    if not name:
        raise HTTPException(422, "Nome obbligatorio")
    if scope_policy_id:
        from app.models import WorkingHoursPolicy
        p = db.query(WorkingHoursPolicy).filter(
            WorkingHoursPolicy.id == scope_policy_id,
            WorkingHoursPolicy.tenant_id == current_tenant_id(),
        ).first()
        if not p:
            raise HTTPException(404, "Policy scope non trovata")
    h = Holiday(
        tenant_id=current_tenant_id(),
        date=date, name=name[:200], kind=kind,
        scope_policy_id=scope_policy_id,
        created_by_user_id=user.id if user else None,
    )
    db.add(h); db.commit(); db.refresh(h)
    return _h_dict(h)


@router.put("/api/holidays/{h_id}")
async def update_holiday(
    h_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not is_elevated(user):
        raise HTTPException(403, "Solo admin/manager/producer possono gestire festività")
    h = db.query(Holiday).filter(
        Holiday.id == h_id, Holiday.tenant_id == current_tenant_id(),
    ).first()
    if not h:
        raise HTTPException(404, "Festività non trovata")
    if "date" in payload and payload["date"]:
        try:
            h.date = _date.fromisoformat(payload["date"])
        except Exception:
            raise HTTPException(422, "Data non valida (YYYY-MM-DD)")
    if "name" in payload:
        h.name = (payload["name"] or "").strip()[:200] or h.name
    if "kind" in payload:
        try:
            h.kind = HolidayKind(payload["kind"])
        except ValueError:
            raise HTTPException(422, "Kind non valido")
    # α.172.33 — scope via policy
    if "scope_policy_id" in payload:
        spid = payload["scope_policy_id"]
        if spid:
            from app.models import WorkingHoursPolicy
            p = db.query(WorkingHoursPolicy).filter(
                WorkingHoursPolicy.id == int(spid),
                WorkingHoursPolicy.tenant_id == current_tenant_id(),
            ).first()
            if not p:
                raise HTTPException(404, "Policy scope non trovata")
            h.scope_policy_id = int(spid)
        else:
            h.scope_policy_id = None
    # Legacy fields (back-compat, ignorati dal resolver)
    if "scope_resource_id" in payload:
        h.scope_resource_id = payload["scope_resource_id"] or None
    if "scope_location" in payload:
        sl = payload["scope_location"]
        h.scope_location = (sl.strip()[:100] if sl else None)
    if "is_active" in payload:
        h.is_active = bool(payload["is_active"])
    db.commit(); db.refresh(h)
    return _h_dict(h)


@router.delete("/api/holidays/{h_id}")
async def delete_holiday(
    h_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not is_elevated(user):
        raise HTTPException(403, "Solo admin/manager/producer possono gestire festività")
    h = db.query(Holiday).filter(
        Holiday.id == h_id, Holiday.tenant_id == current_tenant_id(),
    ).first()
    if not h:
        raise HTTPException(404, "Festività non trovata")
    h.is_active = False  # soft delete
    db.commit()
    return {"ok": True}


@router.post("/api/holidays/bulk-import")
async def bulk_import_holidays(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Import CSV testuale. Atteso: una festività per riga.

    Payload: `{"csv_text": "...", "skip_existing": true}`.
    Header CSV: `date,name,kind,scope_location` (kind/scope_location opzionali).
    Date format ISO (YYYY-MM-DD).
    """
    user = current_user_optional(request)
    if not is_elevated(user):
        raise HTTPException(403, "Solo admin/manager/producer possono importare festività")
    csv_text = (payload.get("csv_text") or "").strip()
    if not csv_text:
        raise HTTPException(422, "csv_text vuoto")
    skip_existing = bool(payload.get("skip_existing", True))

    reader = csv.DictReader(io.StringIO(csv_text))
    created: list[dict] = []
    errors: list[str] = []
    skipped = 0
    for i, row in enumerate(reader, start=2):  # riga 1 = header
        try:
            d = _date.fromisoformat((row.get("date") or "").strip())
            name = (row.get("name") or "").strip()
            if not name:
                errors.append(f"Riga {i}: nome vuoto")
                continue
            kind_str = (row.get("kind") or "local").strip()
            try:
                kind = HolidayKind(kind_str)
            except ValueError:
                kind = HolidayKind.local
            scope_loc = (row.get("scope_location") or "").strip() or None

            if skip_existing:
                exists = db.query(Holiday).filter(
                    Holiday.tenant_id == current_tenant_id(),
                    Holiday.date == d,
                    Holiday.name == name[:200],
                ).first()
                if exists:
                    skipped += 1
                    continue

            h = Holiday(
                tenant_id=current_tenant_id(),
                date=d, name=name[:200], kind=kind,
                scope_location=scope_loc[:100] if scope_loc else None,
                created_by_user_id=user.id if user else None,
            )
            db.add(h)
            created.append({"date": d.isoformat(), "name": name})
        except Exception as e:
            errors.append(f"Riga {i}: {e}")
    db.commit()
    return {
        "created": len(created),
        "skipped": skipped,
        "errors": errors,
        "preview": created[:10],
    }


@router.get("/api/leave-balance")
async def leave_balance(
    request: Request,
    resource_id: int,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Saldo dinamico ferie/ROL/permessi/malattia (α.172.29)."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Login richiesto")
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    # Scope: staff può vedere solo propria risorsa
    if not is_elevated(user):
        if not r.user_id or r.user_id != user.id:
            raise HTTPException(403, "Puoi consultare solo il tuo saldo")
    return compute_leave_balance(db, resource_id, year=year)
