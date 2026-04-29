"""Router risorse — CRUD personale, attrezzature, studi.
Fase 1-bis: aggiunti department_id, role, email, phone, internal_phone.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Resource, ResourceType, ResourceUnavailability, Department, WorkingHoursPolicy
from datetime import date

router = APIRouter(prefix="/resources", tags=["resources"])

CURRENT_TENANT = 1

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
    db: Session = Depends(get_db),
):
    q = db.query(Resource).filter(
        Resource.tenant_id == CURRENT_TENANT,
        Resource.is_active == True,
    )
    if department_id:
        q = q.filter(Resource.department_id == department_id)
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        if types:
            q = q.filter(Resource.type.in_(types))
    resources = q.order_by(Resource.name).all()

    departments = (
        db.query(Department)
        .filter(Department.tenant_id == CURRENT_TENANT, Department.is_active == True)
        .order_by(Department.sort_order, Department.name)
        .all()
    )
    wh_policies = (
        db.query(WorkingHoursPolicy)
        .filter(WorkingHoursPolicy.tenant_id == CURRENT_TENANT)
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
    q = db.query(Resource).filter(Resource.tenant_id == CURRENT_TENANT)
    if active_only:
        q = q.filter(Resource.is_active == True)
    if type:
        q = q.filter(Resource.type == type)
    if department_id:
        q = q.filter(Resource.department_id == department_id)
    return q.all()


@router.post("/api")
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
    db: Session = Depends(get_db),
):
    r = Resource(
        tenant_id=CURRENT_TENANT,
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
    )
    db.add(r); db.commit(); db.refresh(r)
    return {"id": r.id, "name": r.name}


@router.get("/api/{resource_id}")
async def get_resource(resource_id: int, db: Session = Depends(get_db)):
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == CURRENT_TENANT
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
    }


@router.put("/api/{resource_id}")
async def update_resource(
    resource_id: int,
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
    db: Session = Depends(get_db),
):
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == CURRENT_TENANT
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
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
    db.commit()
    return {"ok": True, "id": r.id}


@router.delete("/api/{resource_id}")
async def delete_resource(resource_id: int, db: Session = Depends(get_db)):
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == CURRENT_TENANT
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    r.is_active = False
    db.commit()
    return {"ok": True}


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


@router.post("/api/{resource_id}/unavailability")
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


@router.delete("/api/unavailability/{u_id}")
async def delete_unavailability(u_id: int, db: Session = Depends(get_db)):
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == CURRENT_TENANT,
    ).first()
    if not u:
        raise HTTPException(404, "Unavailability non trovata")
    db.delete(u); db.commit()
    return {"ok": True}
