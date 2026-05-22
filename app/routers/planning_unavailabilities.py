"""Router ferie/malattia/permessi (ResourceUnavailability).

v3.5.0-alpha.66.20 — Estratto da planning.py (sprint R7.x audit pattern G
"file giganti"). Endpoint `/planning/api/unavailabilities*` e
`/planning/api/my-unavailabilities` spostati qui senza alterare path
esterni. Le helper riusabili rimangono in planning.py (es.
`_parse_id_list`, `scope_resource_id`).

Endpoint:
  - GET    /planning/api/unavailabilities      (timeline background items)
  - GET    /planning/api/my-unavailabilities   (vista utente loggato)
  - POST   /planning/api/unavailabilities      (richiesta ferie/malattia)
  - GET    /planning/api/unavailabilities/pending
  - POST   /planning/api/unavailabilities/{u_id}/approve
  - POST   /planning/api/unavailabilities/{u_id}/reject
  - DELETE /planning/api/unavailabilities/{u_id}
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from typing import Optional
from datetime import date as _date, datetime, time as _time, timedelta as _td
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Resource, ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
    WorkingHoursPolicy, TimePunch, PunchKind,
)
from app.services.rbac import (
    is_elevated, current_user_optional, scope_resource_id,
    can_approve_unavailability,
)
from app.context import current_tenant_id

router = APIRouter(prefix="/planning/api", tags=["planning-unavailabilities"])



def _u_dict(u: "ResourceUnavailability") -> dict:
    return {
        "id": u.id,
        "resource_id": u.resource_id,
        "resource_name": u.resource.name if u.resource else None,
        "start_date": u.start_date.isoformat(),
        "end_date": u.end_date.isoformat(),
        "start_time": u.start_time.strftime("%H:%M") if u.start_time else None,
        "end_time": u.end_time.strftime("%H:%M") if u.end_time else None,
        "hours_duration": u.hours_duration,
        "is_partial": u.is_partial,
        "kind": u.kind.value if hasattr(u.kind, "value") else u.kind,
        "reason": u.reason,
        "status": u.status.value if hasattr(u.status, "value") else u.status,
        "requested_by_user_id": u.requested_by_user_id,
        "approved_by_user_id": u.approved_by_user_id,
        "approved_at": u.approved_at.isoformat() if u.approved_at else None,
        "rejection_reason": u.rejection_reason,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _parse_time_quarter(s: Optional[str]) -> Optional[_time]:
    """Parse HH:MM stringa accettando solo step di 15min. None se vuoto.

    Raise ValueError se formato invalido o non-step-15.
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        parts = s.split(":")
        h = int(parts[0]); m = int(parts[1])
    except Exception:
        raise ValueError(f"Orario non valido: {s} (atteso HH:MM)")
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"Orario fuori range: {s}")
    if m % 15 != 0:
        raise ValueError(f"Granularità deve essere 15 minuti: {s}")
    return _time(h, m)


@router.get("/unavailabilities")
async def list_unavailabilities(
    from_date: Optional[_date] = None,
    to_date: Optional[_date] = None,
    resource_id: Optional[str] = None,
    include_holidays: bool = True,
    include_weekends: bool = True,
    db: Session = Depends(get_db),
):
    """Ritorna le fasce non lavorative per la timeline (background items).
    Combina:
      - ResourceUnavailability esplicite (vacation/sick/other)
      - Festività nazionali auto-derivate dalla policy (kind=holiday)
      - Weekend in base alla policy (kind=weekend, opzionale)

    v3.4.47 — `resource_id` accetta comma-separated.
    """
    from app.routers.planning import _parse_id_list

    if not from_date:
        from_date = _date.today() - _td(days=30)
    if not to_date:
        to_date = _date.today() + _td(days=180)

    resource_ids = _parse_id_list(resource_id)
    out = []
    q = db.query(ResourceUnavailability).join(Resource).filter(
        Resource.tenant_id == current_tenant_id(),
        ResourceUnavailability.end_date >= from_date,
        ResourceUnavailability.start_date <= to_date,
    )
    if resource_ids:
        q = q.filter(ResourceUnavailability.resource_id.in_(resource_ids))
    for u in q.all():
        if u.status != UnavailabilityStatus.approved:
            continue
        out.append({
            "id": f"u{u.id}",
            "resource_id": u.resource_id,
            "start_date": u.start_date.isoformat(),
            "end_date": u.end_date.isoformat(),
            "kind": u.kind.value if hasattr(u.kind, "value") else u.kind,
            "reason": u.reason,
            "status": u.status.value if hasattr(u.status, "value") else u.status,
        })

    if include_holidays or include_weekends:
        resources_q = db.query(Resource).filter(
            Resource.tenant_id == current_tenant_id(),
            Resource.is_active == True,  # noqa: E712
        )
        if resource_ids:
            resources_q = resources_q.filter(Resource.id.in_(resource_ids))
        all_res = resources_q.all()

        default_policy = db.query(WorkingHoursPolicy).filter(
            WorkingHoursPolicy.tenant_id == current_tenant_id(),
            WorkingHoursPolicy.is_default == True,  # noqa: E712
        ).first()
        policies_by_id = {default_policy.id: default_policy} if default_policy else {}
        for r in all_res:
            if r.working_hours_policy_id and r.working_hours_policy_id not in policies_by_id:
                p = db.query(WorkingHoursPolicy).filter(WorkingHoursPolicy.id == r.working_hours_policy_id).first()
                if p:
                    policies_by_id[p.id] = p

        holidays_set = set()
        if include_holidays and default_policy and default_policy.holidays_country:
            from app.services.working_hours import get_holidays
            holidays_set = get_holidays(default_policy, from_date.year, to_date.year)

        for r in all_res:
            policy = policies_by_id.get(r.working_hours_policy_id) or default_policy
            if not policy:
                continue
            cur = from_date
            run_start = None
            run_kind = None
            while cur <= to_date:
                is_holiday = include_holidays and cur in holidays_set
                is_weekend = include_weekends and not (policy.working_days & (1 << cur.weekday()))
                kind = "holiday" if is_holiday else ("weekend" if is_weekend else None)
                if kind != run_kind:
                    if run_kind:
                        out.append({
                            "id": f"auto-{r.id}-{run_start.isoformat()}",
                            "resource_id": r.id,
                            "start_date": run_start.isoformat(),
                            "end_date": (cur - _td(days=1)).isoformat(),
                            "kind": run_kind,
                            "reason": None,
                        })
                    run_kind = kind
                    run_start = cur
                cur += _td(days=1)
            if run_kind:
                out.append({
                    "id": f"auto-{r.id}-{run_start.isoformat()}",
                    "resource_id": r.id,
                    "start_date": run_start.isoformat(),
                    "end_date": to_date.isoformat(),
                    "kind": run_kind,
                    "reason": None,
                })
    return out


@router.get("/my-unavailabilities")
async def list_my_unavailabilities(
    request: Request,
    from_date: Optional[_date] = None,
    to_date: Optional[_date] = None,
    db: Session = Depends(get_db),
):
    """Lista ferie/malattie della risorsa associata all'utente loggato (tutti gli status)."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Non autenticato")
    own = scope_resource_id(db, user)
    if own is None:
        return []
    q = db.query(ResourceUnavailability).filter(
        ResourceUnavailability.resource_id == own,
    )
    if from_date:
        q = q.filter(ResourceUnavailability.end_date >= from_date)
    if to_date:
        q = q.filter(ResourceUnavailability.start_date <= to_date)
    items = q.order_by(ResourceUnavailability.start_date.desc()).all()
    return [_u_dict(u) for u in items]


@router.post("/unavailabilities")
async def create_unavailability(
    request: Request,
    resource_id: int = Form(...),
    start_date: _date = Form(...),
    end_date: _date = Form(...),
    kind: UnavailabilityKind = Form(UnavailabilityKind.vacation),
    reason: Optional[str] = Form(None),
    # α.172.29 — Assenza intra-giorno (granularità 15min). Se entrambi
    # popolati, start_date == end_date obbligatorio. Se vuoti → giorno intero.
    start_time: Optional[str] = Form(None),
    end_time: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea una richiesta di ferie/malattia/permesso/ROL/recupero.

    - Staff/viewer: scope forzato sulla propria risorsa, status=pending
    - Admin/manager/producer: può creare per qualsiasi risorsa, status=approved
      di default (saltano il workflow visto che sono già autorizzati).
    - α.172.29: se `start_time` e `end_time` popolati → assenza intra-giorno
      (richiede start_date == end_date, granularità 15min).
    """
    user = current_user_optional(request)
    if end_date < start_date:
        raise HTTPException(400, "end_date deve essere >= start_date")

    # α.172.29 — Validazione assenza intra-giorno
    try:
        st = _parse_time_quarter(start_time)
        et = _parse_time_quarter(end_time)
    except ValueError as e:
        raise HTTPException(422, str(e))
    is_partial = bool(st and et)
    hours_duration: Optional[float] = None
    if is_partial:
        if start_date != end_date:
            raise HTTPException(400, "Assenza a ore: start_date deve coincidere con end_date")
        if et <= st:
            raise HTTPException(400, "end_time deve essere posteriore a start_time")
        hours_duration = ((et.hour * 60 + et.minute) - (st.hour * 60 + st.minute)) / 60.0
    elif st or et:
        raise HTTPException(400, "Specifica entrambi start_time e end_time, o nessuno dei due")

    if not is_elevated(user):
        own = scope_resource_id(db, user)
        if own is None:
            raise HTTPException(403, "Nessuna risorsa associata al tuo utente")
        if resource_id != own:
            raise HTTPException(403, "Puoi richiedere ferie solo per la tua risorsa")
        status = UnavailabilityStatus.pending
    else:
        status = UnavailabilityStatus.approved

    span_start = datetime.combine(start_date, datetime.min.time())
    span_end = datetime.combine(end_date, datetime.max.time())
    existing_punches = db.query(TimePunch).filter(
        TimePunch.resource_id == resource_id,
        TimePunch.kind == PunchKind.shift,
        TimePunch.start_datetime <= span_end,
        TimePunch.end_datetime >= span_start,
    ).first()
    if existing_punches and status == UnavailabilityStatus.approved:
        raise HTTPException(
            409,
            f"La risorsa ha già una timbratura registrata il "
            f"{existing_punches.start_datetime.strftime('%d/%m/%Y %H:%M')}. "
            f"Elimina la timbratura prima di creare l'assenza.",
        )

    u = ResourceUnavailability(
        resource_id=resource_id, start_date=start_date, end_date=end_date,
        start_time=st, end_time=et, hours_duration=hours_duration,
        kind=kind, reason=reason,
        status=status,
        requested_by_user_id=user.id if user else None,
        approved_by_user_id=user.id if (user and is_elevated(user)) else None,
        approved_at=datetime.utcnow() if status == UnavailabilityStatus.approved else None,
    )
    db.add(u)
    db.commit()
    db.refresh(u)

    if status == UnavailabilityStatus.pending:
        from app.services import notifications as notif_svc
        kind_lbl = {"vacation": "Ferie", "sick": "Malattia", "other": "Permesso"}.get(
            kind.value if hasattr(kind, "value") else str(kind), "Richiesta"
        )
        resource_name = u.resource.name if u.resource else f"risorsa #{resource_id}"
        notif_svc.notify_permission(
            db,
            permission="approve_unavailability",
            exclude_user_ids=[user.id] if user else None,
            kind="unavailability_pending",
            severity="action_required",
            title=f"{kind_lbl} da approvare — {resource_name}",
            body=f"{start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}" + (f" · {reason}" if reason else ""),
            link="/hr/",
            payload={"unavailability_id": u.id, "resource_id": resource_id, "kind": kind.value if hasattr(kind, "value") else str(kind)},
            actor_user_id=user.id if user else None,
        )
    return _u_dict(u)


@router.get("/unavailabilities/pending")
async def list_pending_unavailabilities(request: Request, db: Session = Depends(get_db)):
    """Lista richieste in attesa di approvazione (admin/manager/producer)."""
    user = current_user_optional(request)
    if not can_approve_unavailability(user):
        raise HTTPException(403, "Solo manager/producer/admin possono visualizzare le richieste pendenti")
    items = (
        db.query(ResourceUnavailability)
        .join(Resource, ResourceUnavailability.resource_id == Resource.id)
        .filter(
            Resource.tenant_id == current_tenant_id(),
            ResourceUnavailability.status == UnavailabilityStatus.pending,
        )
        .order_by(ResourceUnavailability.created_at.desc())
        .all()
    )
    return [_u_dict(u) for u in items]


@router.post("/unavailabilities/{u_id}/approve")
async def approve_unavailability(u_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user_optional(request)
    if not can_approve_unavailability(user):
        raise HTTPException(403, "Permesso negato")
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not u:
        raise HTTPException(404, "Richiesta non trovata")
    span_start = datetime.combine(u.start_date, datetime.min.time())
    span_end = datetime.combine(u.end_date, datetime.max.time())
    existing_punch = db.query(TimePunch).filter(
        TimePunch.resource_id == u.resource_id,
        TimePunch.kind == PunchKind.shift,
        TimePunch.start_datetime <= span_end,
        TimePunch.end_datetime >= span_start,
    ).first()
    if existing_punch:
        raise HTTPException(
            409,
            f"Impossibile approvare: la risorsa ha una timbratura il "
            f"{existing_punch.start_datetime.strftime('%d/%m/%Y %H:%M')}. "
            f"Rifiuta la richiesta o elimina la timbratura.",
        )
    u.status = UnavailabilityStatus.approved
    u.approved_by_user_id = user.id
    u.approved_at = datetime.utcnow()
    u.rejection_reason = None
    db.commit()
    db.refresh(u)

    if u.requested_by_user_id and u.requested_by_user_id != user.id:
        from app.services import notifications as notif_svc
        kind_lbl = {"vacation": "Ferie", "sick": "Malattia", "other": "Permesso"}.get(
            u.kind.value if hasattr(u.kind, "value") else str(u.kind), "Richiesta"
        )
        notif_svc.notify(
            db,
            user_ids=[u.requested_by_user_id],
            kind="unavailability_approved",
            severity="info",
            title=f"{kind_lbl} approvata",
            body=f"{u.start_date.strftime('%d/%m/%Y')} → {u.end_date.strftime('%d/%m/%Y')}",
            link="/hr/",
            payload={"unavailability_id": u.id},
            actor_user_id=user.id,
        )
    return _u_dict(u)


@router.post("/unavailabilities/{u_id}/reject")
async def reject_unavailability(
    u_id: int,
    request: Request,
    rejection_reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not can_approve_unavailability(user):
        raise HTTPException(403, "Permesso negato")
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not u:
        raise HTTPException(404, "Richiesta non trovata")
    u.status = UnavailabilityStatus.rejected
    u.approved_by_user_id = user.id
    u.approved_at = datetime.utcnow()
    u.rejection_reason = rejection_reason
    db.commit()
    db.refresh(u)

    if u.requested_by_user_id and u.requested_by_user_id != user.id:
        from app.services import notifications as notif_svc
        kind_lbl = {"vacation": "Ferie", "sick": "Malattia", "other": "Permesso"}.get(
            u.kind.value if hasattr(u.kind, "value") else str(u.kind), "Richiesta"
        )
        notif_svc.notify(
            db,
            user_ids=[u.requested_by_user_id],
            kind="unavailability_rejected",
            severity="action_required",
            title=f"{kind_lbl} rifiutata",
            body=(rejection_reason or "Nessun motivo specificato") + f" · {u.start_date.strftime('%d/%m/%Y')} → {u.end_date.strftime('%d/%m/%Y')}",
            link="/hr/",
            payload={"unavailability_id": u.id, "rejection_reason": rejection_reason},
            actor_user_id=user.id,
        )
    return _u_dict(u)


@router.get("/unavailabilities/{u_id}")
async def get_unavailability(u_id: int, request: Request, db: Session = Depends(get_db)):
    """α.172.30.1 — Fetch singola unavailability per UI edit."""
    user = current_user_optional(request)
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not u:
        raise HTTPException(404, "Unavailability non trovata")
    if not is_elevated(user):
        own = scope_resource_id(db, user)
        if u.resource_id != own:
            raise HTTPException(403, "Permesso negato")
    return _u_dict(u)


@router.put("/unavailabilities/{u_id}")
async def update_unavailability(
    u_id: int,
    request: Request,
    start_date: Optional[_date] = Form(None),
    end_date: Optional[_date] = Form(None),
    kind: Optional[UnavailabilityKind] = Form(None),
    reason: Optional[str] = Form(None),
    start_time: Optional[str] = Form(None),
    end_time: Optional[str] = Form(None),
    clear_time: bool = Form(False),
    db: Session = Depends(get_db),
):
    """α.172.30 — Modifica unavailability esistente.

    Per staff: solo propria + status pending.
    Per admin/manager: qualsiasi (anche approved).
    Tutti i campi opzionali (PATCH-style). `clear_time=true` per rimuovere
    start_time/end_time (assenza intra-giorno → giorno intero).
    """
    user = current_user_optional(request)
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not u:
        raise HTTPException(404, "Unavailability non trovata")
    if not is_elevated(user):
        own = scope_resource_id(db, user)
        if u.resource_id != own:
            raise HTTPException(403, "Permesso negato")
        if u.status != UnavailabilityStatus.pending:
            raise HTTPException(403, "Solo richieste pending possono essere modificate dall'utente")

    if start_date is not None:
        u.start_date = start_date
    if end_date is not None:
        u.end_date = end_date
    if u.end_date < u.start_date:
        raise HTTPException(400, "end_date deve essere >= start_date")
    if kind is not None:
        u.kind = kind
    if reason is not None:
        u.reason = reason.strip() or None

    if clear_time:
        u.start_time = None
        u.end_time = None
        u.hours_duration = None
    else:
        if start_time is not None or end_time is not None:
            try:
                new_st = _parse_time_quarter(start_time) if start_time is not None else u.start_time
                new_et = _parse_time_quarter(end_time) if end_time is not None else u.end_time
            except ValueError as e:
                raise HTTPException(422, str(e))
            if (new_st and not new_et) or (new_et and not new_st):
                raise HTTPException(400, "Specifica entrambi start_time/end_time o usa clear_time=true")
            if new_st and new_et:
                if u.start_date != u.end_date:
                    raise HTTPException(400, "Assenza a ore: start_date deve coincidere con end_date")
                if new_et <= new_st:
                    raise HTTPException(400, "end_time deve essere posteriore a start_time")
                u.start_time = new_st
                u.end_time = new_et
                u.hours_duration = ((new_et.hour * 60 + new_et.minute) - (new_st.hour * 60 + new_st.minute)) / 60.0

    db.commit(); db.refresh(u)
    return _u_dict(u)


@router.delete("/unavailabilities/{u_id}")
async def delete_unavailability(u_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user_optional(request)
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not u:
        raise HTTPException(404, "Unavailability non trovata")
    if not is_elevated(user):
        own = scope_resource_id(db, user)
        if u.resource_id != own:
            raise HTTPException(403, "Permesso negato")
        if u.status != UnavailabilityStatus.pending:
            raise HTTPException(403, "Solo richieste pending possono essere cancellate dall'utente")
    db.delete(u)
    db.commit()
    return {"ok": True}
