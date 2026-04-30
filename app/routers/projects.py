"""
Router progetti — entità intermedia tra Cliente e Quotazioni/Job.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Project, Client, Quote, Job, ProjectStatus, Resource
from app.models.models import JobResourceAssignment
from app.services.rbac import can_view_finance, current_user_optional

router = APIRouter(prefix="/projects", tags=["projects"])


def _tpl():
    from app.main import templates
    return templates


@router.get("/", response_class=HTMLResponse)
async def projects_page(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).options(joinedload(Project.client)).order_by(Project.created_at.desc()).all()
    clients = db.query(Client).order_by(Client.name).all()
    return _tpl().TemplateResponse(
        "pages/projects.html",
        {"request": request, "projects": projects, "clients": clients},
    )


# ── API ──────────────────────────────────────────────────────
# IMPORTANTE: le route API devono stare PRIMA di /{project_id}, altrimenti
# FastAPI prova a interpretare "api" come int e ritorna 422.

@router.get("/api")
async def list_projects(
    client_id: Optional[int] = None,
    status: Optional[ProjectStatus] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Project).options(joinedload(Project.client))
    if client_id:
        q = q.filter(Project.client_id == client_id)
    if status:
        q = q.filter(Project.status == status)
    projects = q.order_by(Project.created_at.desc()).all()
    return [
        {
            "id": p.id, "code": p.code, "title": p.title,
            "client_id": p.client_id,
            "client_name": p.client.name if p.client else None,
            "project_type": p.project_type,
            "status": p.status,
            "delivery_deadline": str(p.delivery_deadline) if p.delivery_deadline else None,
            "length_minutes": p.length_minutes,
            "quotes_count": len(p.quotes),
            "jobs_count": len(p.jobs),
        }
        for p in projects
    ]


@router.post("/api")
async def create_project(
    request: Request,
    code: str = Form(...),
    title: str = Form(...),
    client_id: int = Form(...),
    project_type: Optional[str] = Form(None),
    length_minutes: Optional[float] = Form(None),
    fps: Optional[str] = Form(None),
    shooting_format: Optional[str] = Form(None),
    delivery_format: Optional[str] = Form(None),
    director: Optional[str] = Form(None),
    producer: Optional[str] = Form(None),
    shoot_start: Optional[date] = Form(None),
    shoot_end: Optional[date] = Form(None),
    delivery_deadline: Optional[date] = Form(None),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if not can_view_finance(current_user_optional(request)):
        raise HTTPException(403, "Permesso negato")
    existing = db.query(Project).filter(Project.code == code).first()
    if existing:
        raise HTTPException(400, f"Codice progetto '{code}' già esistente")
    p = Project(
        code=code, title=title, client_id=client_id, project_type=project_type,
        length_minutes=length_minutes, fps=fps, shooting_format=shooting_format,
        delivery_format=delivery_format, director=director, producer=producer,
        shoot_start=shoot_start, shoot_end=shoot_end,
        delivery_deadline=delivery_deadline, description=description,
    )
    db.add(p); db.commit(); db.refresh(p)
    return {"id": p.id, "code": p.code}


@router.get("/api/{project_id}")
async def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).options(
        joinedload(Project.client),
        joinedload(Project.quotes),
        joinedload(Project.jobs),
    ).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    return {
        "id": p.id, "code": p.code, "title": p.title,
        "client_id": p.client_id,
        "client": {"id": p.client.id, "name": p.client.name} if p.client else None,
        "project_type": p.project_type,
        "length_minutes": p.length_minutes, "fps": p.fps,
        "shooting_format": p.shooting_format, "delivery_format": p.delivery_format,
        "director": p.director, "producer": p.producer, "dop": p.dop,
        "shoot_start": str(p.shoot_start) if p.shoot_start else None,
        "shoot_end": str(p.shoot_end) if p.shoot_end else None,
        "post_start": str(p.post_start) if p.post_start else None,
        "delivery_deadline": str(p.delivery_deadline) if p.delivery_deadline else None,
        "status": p.status,
        "description": p.description, "notes": p.notes,
        "quotes": [
            {"id": q.id, "number": q.number, "version": q.version,
             "status": q.status, "total_with_vat": q.total_with_vat,
             "issue_date": str(q.issue_date)}
            for q in p.quotes
        ],
        "jobs": [
            {"id": j.id, "code": j.code, "title": j.title,
             "status": j.status, "budget_quoted": j.budget_quoted}
            for j in p.jobs
        ],
    }


@router.put("/api/{project_id}")
async def update_project(
    project_id: int,
    title: Optional[str] = Form(None),
    project_type: Optional[str] = Form(None),
    length_minutes: Optional[float] = Form(None),
    fps: Optional[str] = Form(None),
    shooting_format: Optional[str] = Form(None),
    delivery_format: Optional[str] = Form(None),
    director: Optional[str] = Form(None),
    producer: Optional[str] = Form(None),
    dop: Optional[str] = Form(None),
    delivery_deadline: Optional[date] = Form(None),
    status: Optional[ProjectStatus] = Form(None),
    description: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404)
    for field in ("title", "project_type", "length_minutes", "fps",
                  "shooting_format", "delivery_format", "director",
                  "producer", "dop", "delivery_deadline",
                  "status", "description", "notes"):
        val = locals()[field]
        if val is not None and val != "":
            setattr(p, field, val)
    db.commit()
    return {"id": p.id}


@router.delete("/api/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404)
    if p.jobs:
        raise HTTPException(400, f"Progetto ha {len(p.jobs)} job associati")
    db.delete(p); db.commit()
    return {"ok": True}


# ── Resource assignments (drag&drop su pagina progetto) ─────

@router.get("/api/{project_id}/assignments")
async def list_project_assignments(project_id: int, db: Session = Depends(get_db)):
    """
    Tutte le assegnazioni risorsa→job del progetto + lista delle risorse attive
    disponibili (sorgente del drag&drop). Serializzato per il frontend.
    """
    p = db.query(Project).options(
        joinedload(Project.jobs).joinedload(Job.resource_assignments)
        .joinedload(JobResourceAssignment.resource),
    ).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    jobs_out = []
    for j in p.jobs:
        jobs_out.append({
            "job_id": j.id, "code": j.code, "title": j.title, "status": j.status,
            "assignments": [
                {
                    "id": a.id, "resource_id": a.resource_id,
                    "resource_name": a.resource.name if a.resource else "?",
                    "resource_color": a.resource.color if a.resource else "#6272f5",
                    "resource_type": a.resource.type.value if a.resource and a.resource.type else None,
                    "role_in_project": a.role_in_project,
                    "planned_days": a.planned_days,
                    "planned_hours": a.planned_hours,
                    "agreed_daily_rate": a.agreed_daily_rate,
                    "agreed_hourly_rate": a.agreed_hourly_rate,
                }
                for a in j.resource_assignments
            ],
        })
    # Risorse attive disponibili (sorgente del drag): filtriamo per tenant=1 (Fase 1-bis)
    res_rows = db.query(Resource).filter(
        Resource.tenant_id == 1, Resource.is_active == True
    ).order_by(Resource.name).all()
    available = [
        {
            "id": r.id, "name": r.name, "color": r.color,
            "type": r.type.value if r.type else None,
            "role": r.role, "department_id": r.department_id,
            "department_name": r.department.name if r.department else None,
            "daily_rate": r.daily_rate, "hourly_rate": r.hourly_rate,
        }
        for r in res_rows
    ]
    return {"project_id": p.id, "jobs": jobs_out, "available_resources": available}


@router.post("/api/{project_id}/assignments")
async def create_assignment(
    project_id: int,
    job_id: int = Form(...),
    resource_id: int = Form(...),
    role_in_project: Optional[str] = Form(None),
    planned_days: Optional[float] = Form(None),
    planned_hours: Optional[float] = Form(None),
    agreed_daily_rate: Optional[float] = Form(None),
    agreed_hourly_rate: Optional[float] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea un'assegnazione. Verifica che il job appartenga al progetto."""
    j = db.query(Job).filter(Job.id == job_id, Job.project_id == project_id).first()
    if not j:
        raise HTTPException(404, "Job non appartiene a questo progetto")
    r = db.query(Resource).filter(Resource.id == resource_id, Resource.is_active == True).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    # Idempotenza: se la stessa risorsa è già assegnata al job, no-op
    existing = db.query(JobResourceAssignment).filter(
        JobResourceAssignment.job_id == job_id,
        JobResourceAssignment.resource_id == resource_id,
    ).first()
    if existing:
        return {"id": existing.id, "duplicate": True}
    a = JobResourceAssignment(
        job_id=job_id, resource_id=resource_id,
        role_in_project=role_in_project or r.role,
        planned_days=planned_days, planned_hours=planned_hours,
        agreed_daily_rate=agreed_daily_rate or r.daily_rate,
        agreed_hourly_rate=agreed_hourly_rate or r.hourly_rate,
    )
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "duplicate": False}


@router.put("/api/{project_id}/assignments/{assignment_id}")
async def update_assignment(
    project_id: int,
    assignment_id: int,
    role_in_project: Optional[str] = Form(None),
    planned_days: Optional[float] = Form(None),
    planned_hours: Optional[float] = Form(None),
    agreed_daily_rate: Optional[float] = Form(None),
    agreed_hourly_rate: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    a = db.query(JobResourceAssignment).join(Job).filter(
        JobResourceAssignment.id == assignment_id,
        Job.project_id == project_id,
    ).first()
    if not a:
        raise HTTPException(404)
    for field in ("role_in_project", "planned_days", "planned_hours",
                  "agreed_daily_rate", "agreed_hourly_rate", "notes"):
        val = locals()[field]
        if val is not None and val != "":
            setattr(a, field, val)
    db.commit()
    return {"id": a.id}


@router.delete("/api/{project_id}/assignments/{assignment_id}")
async def delete_assignment(project_id: int, assignment_id: int, db: Session = Depends(get_db)):
    a = db.query(JobResourceAssignment).join(Job).filter(
        JobResourceAssignment.id == assignment_id,
        Job.project_id == project_id,
    ).first()
    if not a:
        raise HTTPException(404)
    db.delete(a); db.commit()
    return {"ok": True}


# ── HTML page detail (DOPO le API per evitare conflitti di path) ─────

@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse(
        "pages/project_detail.html",
        {"request": request, "project_id": project_id},
    )
