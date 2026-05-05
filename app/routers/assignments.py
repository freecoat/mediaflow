"""
Router assegnazioni — vista Kanban + vista Matrice (v3.5.0-alpha.20).

Pre-alpha.20: solo vista kanban (drag&drop colonna risorse → colonna job),
adatta a pochi job attivi. A 200 progetti la kanban diventa muro orizzontale.

Alpha.20: aggiunta vista **Matrice** (Risorsa × Job) con filtri scalabili
(stato job, reparto risorsa, tipo risorsa, ricerca testuale) + click cella =
toggle/edit assegnazione. Pattern Float/Resource Guru: panoramica densa di
"chi fa cosa".

Endpoint:
- GET  /assignments/                → page (toggle vista in UI, default matrice)
- GET  /assignments/api/board       → kanban dataset (legacy)
- GET  /assignments/api/matrix      → matrice dataset (alpha.20)
- POST /assignments/api/move        → idempotente create
- POST /assignments/api/cells       → upsert cell con planned_days/hours/role
- DELETE /assignments/api/{id}      → delete (sia kanban che matrix)
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    Booking, BookingAssignment, BookingStatus,
    Department, Job, JobStatus, Project, Resource, ResourceType,
)
from app.models.models import JobResourceAssignment

router = APIRouter(prefix="/assignments", tags=["assignments"])

CURRENT_TENANT = 1

# Stati job che mostriamo nel kanban (esclusi: invoiced/completed troppo "vecchi"
# se manager non li vuole — per ora li includiamo tutti tranne completed/invoiced)
ACTIVE_JOB_STATUSES = (
    JobStatus.draft, JobStatus.quoting, JobStatus.approved,
    JobStatus.active, JobStatus.on_hold,
)


def _tpl():
    from app.main import templates
    return templates


@router.get("/", response_class=HTMLResponse)
async def assignments_page(request: Request, db: Session = Depends(get_db)):
    departments = (
        db.query(Department)
        .filter(Department.tenant_id == CURRENT_TENANT, Department.is_active == True)  # noqa: E712
        .order_by(Department.name)
        .all()
    )
    return _tpl().TemplateResponse(
        "pages/assignments.html",
        {"request": request, "departments": departments},
    )


@router.get("/api/board")
async def get_board(db: Session = Depends(get_db)):
    """Tutti i job 'attivi' + risorse disponibili. Una sola chiamata per il rendering iniziale."""
    jobs = db.query(Job).options(
        joinedload(Job.project).joinedload(Project.client),
        joinedload(Job.resource_assignments).joinedload(JobResourceAssignment.resource),
    ).filter(Job.status.in_(ACTIVE_JOB_STATUSES)).order_by(Job.id.desc()).all()

    jobs_out = []
    for j in jobs:
        jobs_out.append({
            "job_id": j.id, "code": j.code, "title": j.title, "status": j.status,
            "project_id": j.project_id,
            "project_code": j.project.code if j.project else None,
            "project_title": j.project.title if j.project else None,
            "client_name": j.project.client.name if (j.project and j.project.client) else None,
            "assignments": [
                {
                    "id": a.id, "resource_id": a.resource_id,
                    "resource_name": a.resource.name if a.resource else "?",
                    "resource_color": a.resource.color if a.resource else "#6272f5",
                    "resource_type": a.resource.type.value if a.resource and a.resource.type else None,
                    "role_in_project": a.role_in_project,
                }
                for a in j.resource_assignments
            ],
        })

    res_rows = db.query(Resource).options(joinedload(Resource.department)).filter(
        Resource.tenant_id == CURRENT_TENANT, Resource.is_active == True
    ).order_by(Resource.name).all()
    available = [
        {
            "id": r.id, "name": r.name, "color": r.color,
            "type": r.type.value if r.type else None,
            "role": r.role,
            "department_id": r.department_id,
            "department_name": r.department.name if r.department else None,
            "daily_rate": r.daily_rate, "hourly_rate": r.hourly_rate,
        }
        for r in res_rows
    ]
    return {"jobs": jobs_out, "available_resources": available}


@router.post("/api/move")
async def move_assignment(
    job_id: int = Form(...),
    resource_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Crea una nuova assegnazione (idempotente: no-op se già esiste)."""
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job non trovato")
    r = db.query(Resource).filter(Resource.id == resource_id, Resource.is_active == True).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    existing = db.query(JobResourceAssignment).filter(
        JobResourceAssignment.job_id == job_id,
        JobResourceAssignment.resource_id == resource_id,
    ).first()
    if existing:
        return {"id": existing.id, "duplicate": True}
    a = JobResourceAssignment(
        job_id=job_id, resource_id=resource_id,
        role_in_project=r.role,
        agreed_daily_rate=r.daily_rate,
        agreed_hourly_rate=r.hourly_rate,
    )
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "duplicate": False}


@router.delete("/api/{assignment_id}")
async def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    a = db.query(JobResourceAssignment).filter(JobResourceAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(404)
    db.delete(a); db.commit()
    return {"ok": True}


# ── Matrice (v3.5.0-alpha.20): Risorsa × Job ──────────────────


@router.get("/api/matrix")
async def matrix_dataset(
    job_status: Optional[str] = None,            # CSV
    department_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    only_persons: bool = False,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    """Vista matriciale scalabile a 200+ progetti.

    Filtri server-side (riducono payload a ciò che serve), poi il client può
    fare typeahead/filter ulteriore senza re-fetch.
    """
    rq = db.query(Resource).options(joinedload(Resource.department)).filter(
        Resource.tenant_id == CURRENT_TENANT,
    )
    if not include_inactive:
        rq = rq.filter(Resource.is_active == True)  # noqa: E712
    if only_persons:
        rq = rq.filter(Resource.type.in_([
            ResourceType.person_internal, ResourceType.person_freelance, ResourceType.person,
        ]))
    if resource_type:
        try:
            rq = rq.filter(Resource.type == ResourceType(resource_type))
        except ValueError:
            raise HTTPException(400, f"resource_type non valido: {resource_type}")
    if department_id:
        rq = rq.filter(Resource.department_id == department_id)
    resources = rq.order_by(Resource.name).all()

    jq = db.query(Job).options(
        joinedload(Job.client),
        joinedload(Job.project),
        joinedload(Job.quote),
    ).filter(Job.client_id.isnot(None))
    if job_status:
        try:
            statuses = [JobStatus(s.strip()) for s in job_status.split(",") if s.strip()]
            jq = jq.filter(Job.status.in_(statuses))
        except ValueError as e:
            raise HTTPException(400, f"job_status invalido: {e}")
    jobs = jq.order_by(Job.created_at.desc()).all()

    job_ids = [j.id for j in jobs]
    res_ids = [r.id for r in resources]

    assignments = []
    if job_ids and res_ids:
        assignments = (
            db.query(JobResourceAssignment)
            .filter(
                JobResourceAssignment.job_id.in_(job_ids),
                JobResourceAssignment.resource_id.in_(res_ids),
            )
            .all()
        )

    bk_rows = []
    if job_ids and res_ids:
        bk_rows = (
            db.query(
                BookingAssignment.resource_id.label("rid"),
                Booking.job_id.label("jid"),
                func.sum(
                    (
                        func.julianday(BookingAssignment.end_datetime)
                        - func.julianday(BookingAssignment.start_datetime)
                    ) * 24.0
                ).label("hours"),
            )
            .join(Booking, BookingAssignment.booking_id == Booking.id)
            .filter(
                Booking.job_id.in_(job_ids),
                BookingAssignment.resource_id.in_(res_ids),
                Booking.status != BookingStatus.cancelled,
            )
            .group_by(BookingAssignment.resource_id, Booking.job_id)
            .all()
        )

    return {
        "resources": [
            {
                "id": r.id, "name": r.name, "color": r.color,
                "type": r.type.value if hasattr(r.type, "value") else r.type,
                "role": r.role,
                "department_id": r.department_id,
                "department_name": r.department.name if r.department else None,
                "daily_rate": r.daily_rate, "hourly_rate": r.hourly_rate,
            }
            for r in resources
        ],
        "jobs": [
            {
                "id": j.id, "code": j.code, "title": j.title,
                "status": j.status.value if hasattr(j.status, "value") else j.status,
                "client_id": j.client_id,
                "client_name": j.client.name if j.client else None,
                "project_id": j.project_id,
                "project_title": j.project.title if j.project else None,
                "quote_number": j.quote.number if j.quote else None,
                "start_date": j.start_date.isoformat() if j.start_date else None,
                "end_date": j.end_date.isoformat() if j.end_date else None,
                "budget_quoted": j.budget_quoted,
            }
            for j in jobs
        ],
        "assignments": [
            {
                "id": a.id, "resource_id": a.resource_id, "job_id": a.job_id,
                "planned_days": a.planned_days, "planned_hours": a.planned_hours,
                "agreed_daily_rate": a.agreed_daily_rate,
                "agreed_hourly_rate": a.agreed_hourly_rate,
                "role": a.role_in_project, "notes": a.notes,
            }
            for a in assignments
        ],
        "bookings_hours": [
            {"resource_id": int(r.rid), "job_id": int(r.jid), "hours": round(float(r.hours or 0), 2)}
            for r in bk_rows
        ],
    }


@router.post("/api/cells")
async def upsert_cell(
    job_id: int = Form(...),
    resource_id: int = Form(...),
    role: Optional[str] = Form(None),
    planned_days: Optional[float] = Form(None),
    planned_hours: Optional[float] = Form(None),
    agreed_daily_rate: Optional[float] = Form(None),
    agreed_hourly_rate: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upsert assignment per cella matrice. Idempotente (update se esiste)."""
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job non trovato")
    r = db.query(Resource).filter(Resource.id == resource_id).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")

    a = (
        db.query(JobResourceAssignment)
        .filter(
            JobResourceAssignment.job_id == job_id,
            JobResourceAssignment.resource_id == resource_id,
        )
        .first()
    )
    created = False
    if not a:
        a = JobResourceAssignment(
            job_id=job_id, resource_id=resource_id,
            role_in_project=role or r.role,
            agreed_daily_rate=(agreed_daily_rate if agreed_daily_rate is not None else r.daily_rate),
            agreed_hourly_rate=(agreed_hourly_rate if agreed_hourly_rate is not None else r.hourly_rate),
        )
        db.add(a)
        created = True
    if role is not None: a.role_in_project = role
    if planned_days is not None: a.planned_days = planned_days
    if planned_hours is not None: a.planned_hours = planned_hours
    if agreed_daily_rate is not None: a.agreed_daily_rate = agreed_daily_rate
    if agreed_hourly_rate is not None: a.agreed_hourly_rate = agreed_hourly_rate
    if notes is not None: a.notes = notes

    db.commit()
    db.refresh(a)
    return {
        "id": a.id, "job_id": a.job_id, "resource_id": a.resource_id,
        "role": a.role_in_project,
        "planned_days": a.planned_days, "planned_hours": a.planned_hours,
        "created": created,
    }
