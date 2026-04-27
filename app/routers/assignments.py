"""
Router assegnazioni — vista kanban risorse → job (drag&drop).

Mostra tutti i job attivi del tenant con la colonna "Risorse disponibili" come sorgente.
Le mutazioni passano dagli stessi modelli di /projects/api/{id}/assignments.
"""
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Project, Job, Resource, JobStatus
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
async def assignments_page(request: Request):
    return _tpl().TemplateResponse("pages/assignments.html", {"request": request})


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
