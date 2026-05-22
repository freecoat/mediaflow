"""Router risorse — CRUD personale, attrezzature, studi.
Fase 1-bis: aggiunti department_id, role, email, phone, internal_phone.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Resource, ResourceType, ResourceUnavailability, Department, WorkingHoursPolicy
from app.services.rbac import requires_permission
from datetime import date
from app.context import current_tenant_id

router = APIRouter(prefix="/resources", tags=["resources"])

# router resources (CRUD risorsa + ferie). Prima erano completamente aperti
# ai viewer (audit HIGH #4: leak salary inclusi).
RequireEditResources = Depends(requires_permission("edit_resources"))

TYPE_LABEL = {
    "person_internal": "Personale interno",
    "person_freelance": "Freelance",
    "person": "Personale",
    "studio": "Studio/Sala",
    "equipment": "Attrezzatura",
    "software": "Software",
    "vehicle": "Veicolo",
}


def _get_templates():
    from app.main import templates
    return templates


# ── Pagine HTML ───────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def resources_list(
    request: Request,
    department_id: Optional[int] = None,
    type: Optional[str] = None,
    include_inactive: int = 0,
    db: Session = Depends(get_db),
):
    # v3.5.0-alpha.126 (P2.E/F21) — param include_inactive per toggle UI
    # "Mostra inattive" nella pagina /resources. Default 0 = solo attive.
    q = db.query(Resource).filter(
        Resource.tenant_id == current_tenant_id(),
    )
    if not include_inactive:
        q = q.filter(Resource.is_active == True)
    if department_id:
        q = q.filter(Resource.department_id == department_id)
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        if types:
            q = q.filter(Resource.type.in_(types))
    resources = q.order_by(Resource.name).all()

    departments = (
        db.query(Department)
        .filter(Department.tenant_id == current_tenant_id(), Department.is_active == True)
        .order_by(Department.sort_order, Department.name)
        .all()
    )
    wh_policies = (
        db.query(WorkingHoursPolicy)
        .filter(WorkingHoursPolicy.tenant_id == current_tenant_id())
        .order_by(WorkingHoursPolicy.is_default.desc(), WorkingHoursPolicy.name)
        .all()
    )

    return _get_templates().TemplateResponse(
        "pages/resources.html",
        {
            "request": request,
            "resources": resources,
            "departments": departments,
            "wh_policies": wh_policies,
            "selected_dept_id": department_id,
            "selected_type": type,
            "include_inactive": bool(include_inactive),
            "TYPE_LABEL": TYPE_LABEL,
        }
    )


# ── API JSON ──────────────────────────────────────────────────────────

@router.get("/api")
async def list_resources(
    type: Optional[ResourceType] = None,
    department_id: Optional[int] = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    q = db.query(Resource).filter(Resource.tenant_id == current_tenant_id())
    if active_only:
        q = q.filter(Resource.is_active == True)
    if type:
        q = q.filter(Resource.type == type)
    if department_id:
        q = q.filter(Resource.department_id == department_id)
    return q.all()


@router.post("/api", dependencies=[RequireEditResources])
async def create_resource(
    name: str = Form(...),
    type: ResourceType = Form(...),
    department_id: Optional[int] = Form(None),
    role: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    daily_rate: Optional[float] = Form(None),
    hourly_rate: Optional[float] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    internal_phone: Optional[str] = Form(None),
    color: str = Form("#6272f5"),
    # v3.5.0-alpha.66.10 — cost-rate interno
    cost_type: Optional[str] = Form(None),
    monthly_gross_salary: Optional[float] = Form(None),
    annual_bonus_months: Optional[float] = Form(None),
    cost_multiplier_oneri: Optional[float] = Form(None),
    annual_working_hours: Optional[float] = Form(None),
    freelance_hourly_cost: Optional[float] = Form(None),
    studio_hourly_cost: Optional[float] = Form(None),
    create_user: bool = Form(False),
    user_role_code: Optional[str] = Form(None),  # default: operator
    supplier_id: Optional[int] = Form(None),  # v3.5.0-alpha.113 — link a fornitore esterno
    db: Session = Depends(get_db),
):
    from app.models import ResourceCostType
    cost_type_enum = None
    if cost_type:
        try: cost_type_enum = ResourceCostType(cost_type)
        except ValueError: cost_type_enum = None

    # v3.5.0-alpha.114 A15: tenant scope su supplier_id (create path)
    if supplier_id:
        from app.models import Supplier as _Supplier
        sup_check = db.query(_Supplier).filter(
            _Supplier.id == supplier_id,
            _Supplier.tenant_id == current_tenant_id(),
        ).first()
        if not sup_check:
            raise HTTPException(400, f"Fornitore #{supplier_id} non trovato")

    r = Resource(
        tenant_id=current_tenant_id(),
        name=name.strip(),
        type=type,
        department_id=department_id,
        role=role.strip() if role else None,
        description=description,
        daily_rate=daily_rate,
        hourly_rate=hourly_rate,
        email=email.strip() if email else None,
        phone=phone.strip() if phone else None,
        internal_phone=internal_phone.strip() if internal_phone else None,
        color=color,
        cost_type=cost_type_enum,
        monthly_gross_salary=monthly_gross_salary,
        annual_bonus_months=annual_bonus_months,
        cost_multiplier_oneri=cost_multiplier_oneri,
        annual_working_hours=annual_working_hours,
        freelance_hourly_cost=freelance_hourly_cost,
        studio_hourly_cost=studio_hourly_cost,
        supplier_id=supplier_id,
    )
    db.add(r); db.flush()

    # v3.4.23: opzionale auto-create User se è una persona
    temp_password = None
    user_email = None
    PERSON_TYPES_LOCAL = (ResourceType.person_internal, ResourceType.person_freelance, ResourceType.person)
    if create_user and type in PERSON_TYPES_LOCAL:
        if not r.email:
            db.rollback()
            raise HTTPException(400, "Email obbligatoria per creare un utente collegato")
        from app.models import User, UserRole, Role
        from app.services.auth import hash_password
        from app.routers.admin import _gen_temp_password, _role_code_to_enum
        if db.query(User).filter(User.email == r.email).first():
            db.rollback()
            raise HTTPException(400, f"Esiste già un utente con email {r.email}")
        target_code = (user_role_code or "operator").lower()
        target_role = db.query(Role).filter(Role.code == target_code, Role.is_active == True).first()  # noqa: E712
        if not target_role:
            target_role = db.query(Role).filter(Role.code == "operator").first()
        temp_password = _gen_temp_password()
        u = User(
            email=r.email,
            full_name=r.name,
            hashed_password=hash_password(temp_password),
            role=_role_code_to_enum(target_role.code) if target_role else UserRole.staff,
            role_id=target_role.id if target_role else None,
            is_active=True,
        )
        db.add(u); db.flush()
        r.user_id = u.id
        user_email = u.email

    db.commit(); db.refresh(r)
    out = {"id": r.id, "name": r.name}
    if temp_password:
        out["created_user"] = {"email": user_email, "temp_password": temp_password}
    return out


@router.get("/api/{resource_id}")
async def get_resource(resource_id: int, db: Session = Depends(get_db)):
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == current_tenant_id()
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    return {
        "id": r.id, "name": r.name,
        "type": r.type.value if r.type else None,
        "department_id": r.department_id, "role": r.role,
        "description": r.description,
        "daily_rate": r.daily_rate, "hourly_rate": r.hourly_rate,
        "email": r.email, "phone": r.phone, "internal_phone": r.internal_phone,
        "color": r.color, "is_active": r.is_active,
        "working_hours_policy_id": r.working_hours_policy_id,
        # v3.5.0-alpha.66.10 — cost-rate interno
        "cost_type": r.cost_type.value if r.cost_type else None,
        "monthly_gross_salary": r.monthly_gross_salary,
        "annual_bonus_months": r.annual_bonus_months,
        "cost_multiplier_oneri": r.cost_multiplier_oneri,
        "annual_working_hours": r.annual_working_hours,
        "freelance_hourly_cost": r.freelance_hourly_cost,
        "studio_hourly_cost": r.studio_hourly_cost,
        "internal_cost_hourly": r.internal_cost_hourly,
        # α.172.32 B
        "location_tag": getattr(r, "location_tag", None),
        "annual_leave_days_override": getattr(r, "annual_leave_days_override", None),
        "monthly_rol_hours_override": getattr(r, "monthly_rol_hours_override", None),
        "monthly_permit_hours_override": getattr(r, "monthly_permit_hours_override", None),
    }


@router.put("/api/{resource_id}", dependencies=[RequireEditResources])
async def update_resource(
    resource_id: int,
    request: Request,
    # v3.5.0-alpha.120 (F22) — supplier_id letto da Request.form() raw per
    # distinguere "key non passata" (no change) da "key vuota" (clear esplicito).
    # FastAPI con Optional[int]/Optional[str] converte '' → None, perdendo
    # la distinzione. Pattern frontend modal supplier cleanup A.supplier_id=NULL
    # falliva silenziosamente. Vedi parsing più sotto.
    name: Optional[str] = Form(None),
    type: Optional[ResourceType] = Form(None),
    department_id: Optional[int] = Form(None),
    role: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    daily_rate: Optional[float] = Form(None),
    hourly_rate: Optional[float] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    internal_phone: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    working_hours_policy_id: Optional[int] = Form(None),
    # v3.5.0-alpha.66.10 — cost-rate interno
    cost_type: Optional[str] = Form(None),
    monthly_gross_salary: Optional[float] = Form(None),
    annual_bonus_months: Optional[float] = Form(None),
    cost_multiplier_oneri: Optional[float] = Form(None),
    annual_working_hours: Optional[float] = Form(None),
    freelance_hourly_cost: Optional[float] = Form(None),
    studio_hourly_cost: Optional[float] = Form(None),
    # α.172.32 B — Override accrual per-resource + location tag
    annual_leave_days_override: Optional[float] = Form(None),
    monthly_rol_hours_override: Optional[float] = Form(None),
    monthly_permit_hours_override: Optional[float] = Form(None),
    location_tag: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == current_tenant_id()
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    # v3.5.0-alpha.120 F22 — Parse supplier_id da form raw (no FastAPI Form
    # type-coercion che cancella la differenza '' vs missing).
    form_raw = await request.form()
    if "supplier_id" in form_raw:
        sid_raw = (form_raw.get("supplier_id") or "").strip()
        if sid_raw == "":
            r.supplier_id = None
        else:
            try:
                sid = int(sid_raw)
            except ValueError:
                raise HTTPException(400, f"supplier_id non valido: '{sid_raw}'")
            from app.models import Supplier as _Supplier
            sup = db.query(_Supplier).filter(
                _Supplier.id == sid,
                _Supplier.tenant_id == current_tenant_id(),
            ).first()
            if not sup:
                raise HTTPException(400, f"Fornitore #{sid} non trovato")
            r.supplier_id = sid
    if name is not None: r.name = name.strip()
    if type is not None: r.type = type
    if department_id is not None: r.department_id = department_id or None
    if role is not None: r.role = role.strip() or None
    if description is not None: r.description = description
    if daily_rate is not None: r.daily_rate = daily_rate
    if hourly_rate is not None: r.hourly_rate = hourly_rate
    if email is not None: r.email = email.strip() or None
    if phone is not None: r.phone = phone.strip() or None
    if internal_phone is not None: r.internal_phone = internal_phone.strip() or None
    if color is not None: r.color = color
    if is_active is not None: r.is_active = is_active
    if working_hours_policy_id is not None:
        r.working_hours_policy_id = working_hours_policy_id or None
    # α.172.32 B — Override accrual per-resource (NULL = inherit from policy)
    form_raw_x = await request.form()
    for fld in ("annual_leave_days_override", "monthly_rol_hours_override", "monthly_permit_hours_override"):
        if fld in form_raw_x:
            raw = (form_raw_x.get(fld) or "").strip()
            if raw == "":
                setattr(r, fld, None)
            else:
                try:
                    setattr(r, fld, float(raw))
                except ValueError:
                    raise HTTPException(400, f"{fld} non numerico: '{raw}'")
    if "location_tag" in form_raw_x:
        loc = (form_raw_x.get("location_tag") or "").strip()
        r.location_tag = loc[:100] if loc else None
    # v3.5.0-alpha.66.10 — cost-rate interno
    from app.models import ResourceCostType
    if cost_type is not None:
        if cost_type == "":
            r.cost_type = None
        else:
            try: r.cost_type = ResourceCostType(cost_type)
            except ValueError: pass
    if monthly_gross_salary is not None: r.monthly_gross_salary = monthly_gross_salary
    if annual_bonus_months is not None: r.annual_bonus_months = annual_bonus_months
    if cost_multiplier_oneri is not None: r.cost_multiplier_oneri = cost_multiplier_oneri
    if annual_working_hours is not None: r.annual_working_hours = annual_working_hours
    if freelance_hourly_cost is not None: r.freelance_hourly_cost = freelance_hourly_cost
    if studio_hourly_cost is not None: r.studio_hourly_cost = studio_hourly_cost
    db.commit()
    return {"ok": True, "id": r.id, "internal_cost_hourly": r.internal_cost_hourly}


@router.delete("/api/{resource_id}", dependencies=[RequireEditResources])
async def delete_resource(resource_id: int, db: Session = Depends(get_db)):
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == current_tenant_id()
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    r.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/api/{resource_id}/generate-supplier", dependencies=[RequireEditResources])
async def generate_supplier_from_resource(resource_id: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.127 (F11) — Genera un Supplier collegato a questa
    Resource freelance. Pre-popola name/email/phone dalla resource e setta
    `resource.supplier_id` per il link inverso.

    Idempotente: se la resource ha già supplier_id valido, ritorna lo
    stesso (no double-create).

    Restrizione: solo per risorse di tipo `person_freelance`. Altri tipi
    (internal/studio/equipment/etc) non hanno semantica supplier.
    """
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    if r.type != ResourceType.person_freelance:
        raise HTTPException(
            400,
            "Solo risorse di tipo 'freelance' possono generare un fornitore collegato. "
            "Le altre risorse non hanno semantica supplier."
        )
    from app.models import Supplier as _Supplier
    # Se già linked, ritorna esistente.
    if r.supplier_id:
        existing = db.query(_Supplier).filter(
            _Supplier.id == r.supplier_id,
            _Supplier.tenant_id == current_tenant_id(),
            _Supplier.deleted_at.is_(None),
        ).first()
        if existing:
            return {"already_linked": True, "supplier_id": existing.id, "name": existing.name}
        # Stale link → ripulisci.
        r.supplier_id = None

    sup = _Supplier(
        tenant_id=current_tenant_id(),
        name=r.name or f"Fornitore #{r.id}",
        contact_email=r.email,
        contact_phone=r.phone,
        notes=f"Generato da risorsa freelance #{r.id} ({r.name})",
        is_active=True,
    )
    db.add(sup)
    db.flush()
    r.supplier_id = sup.id
    db.commit()
    return {"already_linked": False, "supplier_id": sup.id, "name": sup.name}


@router.get("/api/{resource_id}/unavailabilities")
async def list_unavailabilities_for_resource(resource_id: int, db: Session = Depends(get_db)):
    """Lista ferie/malattia di una risorsa (esplicite, no festività auto)."""
    rows = db.query(ResourceUnavailability).filter(
        ResourceUnavailability.resource_id == resource_id,
    ).order_by(ResourceUnavailability.start_date.desc()).all()
    return [
        {"id": u.id, "start_date": u.start_date.isoformat(),
         "end_date": u.end_date.isoformat(),
         "kind": u.kind.value if hasattr(u.kind, "value") else u.kind,
         "reason": u.reason}
        for u in rows
    ]


@router.post("/api/{resource_id}/unavailability", dependencies=[RequireEditResources])
async def add_unavailability(
    resource_id: int,
    start_date: date = Form(...),
    end_date: date = Form(...),
    kind: Optional[str] = Form("vacation"),
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    from app.models import UnavailabilityKind
    if end_date < start_date:
        raise HTTPException(400, "end_date deve essere >= start_date")
    try:
        k = UnavailabilityKind(kind or "vacation")
    except Exception:
        k = UnavailabilityKind.vacation
    u = ResourceUnavailability(
        resource_id=resource_id,
        start_date=start_date,
        end_date=end_date,
        kind=k,
        reason=reason,
    )
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id, "start_date": u.start_date.isoformat(),
            "end_date": u.end_date.isoformat(),
            "kind": u.kind.value if hasattr(u.kind, "value") else u.kind,
            "reason": u.reason}


@router.delete("/api/unavailability/{u_id}", dependencies=[RequireEditResources])
async def delete_unavailability(u_id: int, db: Session = Depends(get_db)):
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == current_tenant_id(),
    ).first()
    if not u:
        raise HTTPException(404, "Unavailability non trovata")
    db.delete(u); db.commit()
    return {"ok": True}
