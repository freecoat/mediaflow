"""
Router progetti — entità intermedia tra Cliente e Quotazioni/Job.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from datetime import datetime as _dt
from app.models import Project, Client, Quote, Job, ProjectStatus, Resource, ProjectMilestone
from app.models.models import JobResourceAssignment
from app.models import ProjectAccessGrant, User, AssetAccessAction
from app.services.rbac import can_view_finance, current_user_optional, is_admin
from app.services.project_access import log_asset_access
from app.context import current_tenant_id

router = APIRouter(prefix="/projects", tags=["projects"])


def _tpl():
    from app.main import templates
    return templates


@router.get("/", response_class=HTMLResponse)
async def projects_page(request: Request, db: Session = Depends(get_db)):
    tid = current_tenant_id()
    projects = db.query(Project).options(joinedload(Project.client)).filter(
        Project.tenant_id == tid,
    ).order_by(Project.created_at.desc()).all()
    clients = db.query(Client).filter(Client.tenant_id == tid).order_by(Client.name).all()
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
    # v3.5.0-alpha.103 R-MT4: tenant scope (era leak)
    q = db.query(Project).options(joinedload(Project.client)).filter(
        Project.tenant_id == current_tenant_id(),
    )
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
    # v3.5.0-alpha.66.15.4 — pre-check soft-delete-aware: se esiste un
    # Project (anche in cestino) con questo code, l'INSERT violerebbe UNIQUE
    # con un IntegrityError 500. Helper centralizzato bypassa il filter auto.
    from app.services.soft_delete import is_unique_or_deleted_aware
    if not is_unique_or_deleted_aware(db, Project, "code", code):
        raise HTTPException(
            400,
            f"Codice progetto '{code}' già esistente (anche se in cestino: ripristinalo o usa un altro codice)"
        )
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
    # v3.5.0-alpha.103 R-MT4: tenant scope filter (era leak cross-tenant).
    p = db.query(Project).options(
        joinedload(Project.client),
        joinedload(Project.quotes),
        joinedload(Project.jobs),
    ).filter(
        Project.id == project_id,
        Project.tenant_id == current_tenant_id(),
    ).first()
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
        "billing_frequency": getattr(p, "billing_frequency", "monthly"),
        "shipping_markup_pct": getattr(p, "shipping_markup_pct", 15.0),
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
    billing_frequency: Optional[str] = Form(None),
    shipping_markup_pct: Optional[float] = Form(None),
    db: Session = Depends(get_db),
):
    p = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404)
    for field in ("title", "project_type", "length_minutes", "fps",
                  "shooting_format", "delivery_format", "director",
                  "producer", "dop", "delivery_deadline",
                  "status", "description", "notes",
                  "billing_frequency", "shipping_markup_pct"):
        val = locals()[field]
        if val is not None and val != "":
            setattr(p, field, val)
    db.commit()
    return {"id": p.id}


@router.post("/api/{project_id}/cross-check")
async def cross_check_project(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.96 (#9d) — Cross-check progetto vs web (IMDB/BoxOffice/
    Variety). Ritorna differenze + info esterne aggiornate. NO DB write —
    la UI mostra preview, l'utente decide cosa applicare."""
    from app.services.web_crosscheck import check_project
    from app.services.ai_provider import get_provider_for_user
    from app.services.rbac import current_user_optional
    p = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    u = current_user_optional(request)
    provider = get_provider_for_user(u.id if u else None, db)
    if not provider:
        raise HTTPException(503, "AI provider non configurato")
    project_data = {
        "id": p.id, "code": p.code, "title": p.title,
        "project_type": p.project_type,
        "length_minutes": p.length_minutes, "fps": p.fps,
        "shooting_format": p.shooting_format,
        "delivery_format": p.delivery_format,
        "director": p.director, "producer": p.producer, "dop": p.dop,
        "shoot_start": str(p.shoot_start) if p.shoot_start else None,
        "shoot_end": str(p.shoot_end) if p.shoot_end else None,
        "delivery_deadline": str(p.delivery_deadline) if p.delivery_deadline else None,
        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
        "description": p.description,
        "notes": p.notes,
    }
    result = check_project(project_data, provider=provider)
    if not result:
        raise HTTPException(500, "Cross-check fallito (tutti i path AI hanno fallito).")
    return {
        "project_id": p.id,
        "title": p.title,
        **result,
    }


@router.get("/api/{project_id}/job-context")
async def get_project_job_context(project_id: int, db: Session = Depends(get_db)):
    """Contesto quote/job di un progetto per il reverse-flow v3.4.52.

    Usato dal modal booking quando il progetto non ha quote attive non-phantom:
    il client decide se attaccare la riga a una quote pending (draft|sent) con
    approvazione implicita, oppure creare una phantom quote.

    Ritorna:
    - approved_quotes: quote già approvate non-phantom (forward-flow normale, no reverse)
    - pending_quotes: quote draft|sent attaccabili (reverse implicit-approval)
    - phantom_quotes: quote phantom esistenti (reverse precedenti)
    - jobs_with_quote / jobs_without_quote (legacy: orfani residui da seed pre-v3.4.51)
    """
    from app.models import Quote
    p = db.query(Project).options(
        joinedload(Project.quotes), joinedload(Project.jobs)
    ).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")

    approved_quotes = [q for q in p.quotes if q.status == "approved" and not getattr(q, "is_phantom", False)]
    pending_quotes = [q for q in p.quotes if q.status in ("draft", "sent")]
    phantom_quotes = [q for q in p.quotes if getattr(q, "is_phantom", False)]
    jobs_without_quote = [j for j in p.jobs if j.quote_id is None]
    jobs_with_quote = [j for j in p.jobs if j.quote_id is not None]

    def _q(q):
        return {"id": q.id, "number": q.number, "title": q.title,
                "status": q.status.value if hasattr(q.status, "value") else str(q.status),
                "total_with_vat": q.total_with_vat}
    def _j(j):
        return {"id": j.id, "code": j.code, "title": j.title}

    return {
        "project_id": p.id, "project_code": p.code, "project_title": p.title,
        "project_type": p.project_type,
        "is_internal": (p.project_type or "") == "internal",
        "approved_quotes": [_q(q) for q in approved_quotes],
        "pending_quotes": [_q(q) for q in pending_quotes],
        "phantom_quotes": [_q(q) for q in phantom_quotes],
        "jobs_with_quote": [_j(j) for j in jobs_with_quote],
        "jobs_without_quote": [_j(j) for j in jobs_without_quote],
        # Convenienza per UI: quale flusso suggerire
        "suggested_flow": (
            "use_existing_job" if jobs_with_quote else
            ("attach_existing" if pending_quotes else "create_phantom")
        ),
    }


@router.delete("/api/{project_id}")
async def delete_project(
    project_id: int,
    request: Request,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Soft-delete del progetto (sposta nel cestino) o pulizia totale (admin).

    - `delete_projects` (admin/manager/producer): soft-delete. HARD-BLOCK
      409 se ha quote ATTIVE (non in cestino), con elenco. Le quote già
      cestinate non bloccano: il progetto può essere cestinato sopra.
    - `purge_total` (solo admin): `?force=true` → cascade hard-delete su
      Project + Quote + Job + JobCostLine + Booking + assignments.
      Bypassa cestino, irreversibile.
    """
    from app.services.rbac import has_permission
    from app.services.soft_delete import (
        soft_delete_project, fetch_project_including_trash, DeleteBlocked,
    )
    from fastapi.responses import JSONResponse

    user = current_user_optional(request)
    if not has_permission(user, "delete_projects"):
        raise HTTPException(403, "Permesso negato (delete_projects)")
    if force and not has_permission(user, "purge_total"):
        raise HTTPException(403, "Solo un admin con permesso 'purge_total' può forzare la pulizia totale")

    p = fetch_project_including_trash(db, project_id)
    if not p:
        raise HTTPException(404, "Progetto non trovato")

    try:
        result = soft_delete_project(db, p, user=user, force=force)
    except DeleteBlocked as e:
        return JSONResponse(
            status_code=409,
            content={
                "detail":    e.message,
                # Riuso campo `jobs` di DeleteBlocked per quote bloccanti
                # (lato project il "blocking" sono le quote attive).
                "blocking":  {"quotes": e.jobs},
                "can_force": has_permission(user, "purge_total"),
            },
        )
    db.commit()
    return result


@router.post("/api/{project_id}/restore")
async def restore_project_endpoint(project_id: int, request: Request,
                                    db: Session = Depends(get_db)):
    """Ripristina un progetto dal cestino. Permesso `restore_trash`."""
    from app.services.rbac import has_permission
    from app.services.soft_delete import fetch_project_including_trash, restore_project
    user = current_user_optional(request)
    if not has_permission(user, "restore_trash"):
        raise HTTPException(403, "Permesso negato (restore_trash)")
    p = fetch_project_including_trash(db, project_id)
    if not p:
        raise HTTPException(404)
    result = restore_project(db, p)
    db.commit()
    return result


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
    ).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first()
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


# ── Milestones (v3.5.0-alpha.21) ─────────────────────────────


def _milestone_dict(m: ProjectMilestone) -> dict:
    today = date.today()
    if m.is_completed:
        status = "done"
    elif m.target_date < today:
        status = "missed"
    elif (m.target_date - today).days <= 7:
        status = "imminent"
    else:
        status = "pending"
    return {
        "id": m.id, "project_id": m.project_id,
        "title": m.title, "description": m.description,
        "target_date": m.target_date.isoformat(),
        "color": m.color,
        "is_completed": bool(m.is_completed),
        "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        "status": status,
    }


@router.get("/api/{project_id}/milestones")
async def list_milestones(project_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(ProjectMilestone)
        .filter(ProjectMilestone.project_id == project_id)
        .order_by(ProjectMilestone.target_date)
        .all()
    )
    return [_milestone_dict(m) for m in rows]


@router.post("/api/{project_id}/milestones")
async def create_milestone(
    project_id: int,
    request: Request,
    title: str = Form(...),
    target_date: date = Form(...),
    description: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    p = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    user = current_user_optional(request)
    m = ProjectMilestone(
        project_id=project_id,
        title=title.strip(),
        target_date=target_date,
        description=description,
        color=color,
        created_by_user_id=user.id if user else None,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _milestone_dict(m)


@router.put("/api/{project_id}/milestones/{milestone_id}")
async def update_milestone(
    project_id: int, milestone_id: int,
    title: Optional[str] = Form(None),
    target_date: Optional[date] = Form(None),
    description: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    is_completed: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
):
    m = db.query(ProjectMilestone).filter(
        ProjectMilestone.id == milestone_id,
        ProjectMilestone.project_id == project_id,
    ).first()
    if not m:
        raise HTTPException(404, "Milestone non trovata")
    if title is not None: m.title = title.strip()
    if target_date is not None: m.target_date = target_date
    if description is not None: m.description = description
    if color is not None: m.color = color or None
    if is_completed is not None:
        m.is_completed = bool(is_completed)
        m.completed_at = _dt.utcnow() if is_completed else None
    db.commit()
    db.refresh(m)
    return _milestone_dict(m)


@router.delete("/api/{project_id}/milestones/{milestone_id}")
async def delete_milestone(project_id: int, milestone_id: int, db: Session = Depends(get_db)):
    m = db.query(ProjectMilestone).filter(
        ProjectMilestone.id == milestone_id,
        ProjectMilestone.project_id == project_id,
    ).first()
    if not m:
        raise HTTPException(404)
    db.delete(m); db.commit()
    return {"ok": True}


# ── Project Access Grants (TPN compliance, v3.5.0-alpha.70) ──────────



@router.get("/api/{project_id}/access")
async def list_project_access(
    project_id: int,
    request: Request,
    include_revoked: int = 0,
    db: Session = Depends(get_db),
):
    """Lista grants attivi (e opt revoked) per il progetto + lista risorse
    auto-grant via JobResourceAssignment.user_id."""
    user = current_user_optional(request)
    if not is_admin(user):
        raise HTTPException(403, "Solo admin può vedere la lista access grants")
    p = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    q = db.query(ProjectAccessGrant).filter(
        ProjectAccessGrant.project_id == project_id,
        ProjectAccessGrant.tenant_id == current_tenant_id(),
    )
    if not include_revoked:
        q = q.filter(ProjectAccessGrant.revoked_at.is_(None))
    grants = q.order_by(ProjectAccessGrant.granted_at.desc()).all()
    # Hydrate user info
    user_ids = list({g.user_id for g in grants} | {g.granted_by_user_id for g in grants if g.granted_by_user_id})
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    out_grants = []
    for g in grants:
        u = users.get(g.user_id)
        gb = users.get(g.granted_by_user_id) if g.granted_by_user_id else None
        out_grants.append({
            "id": g.id,
            "user_id": g.user_id,
            "user_email": u.email if u else None,
            "user_name": getattr(u, "full_name", None) or (u.email if u else None),
            "role_in_project": g.role_in_project,
            "granted_at": str(g.granted_at)[:19] if g.granted_at else None,
            "granted_by_email": gb.email if gb else None,
            "revoked_at": str(g.revoked_at)[:19] if g.revoked_at else None,
            "notes": g.notes,
            "source": "explicit",
        })
    # Auto-grants da JobResourceAssignment
    auto_assignments = (
        db.query(Resource, User)
        .join(JobResourceAssignment, JobResourceAssignment.resource_id == Resource.id)
        .join(Job, Job.id == JobResourceAssignment.job_id)
        .outerjoin(User, User.id == Resource.user_id)
        .filter(Job.project_id == project_id)
        .filter(Resource.user_id.isnot(None))
        .distinct()
        .all()
    )
    auto_out = []
    seen_users = set()
    for r, u in auto_assignments:
        if u and u.id not in seen_users:
            seen_users.add(u.id)
            auto_out.append({
                "user_id": u.id,
                "user_email": u.email,
                "user_name": getattr(u, "full_name", None) or u.email,
                "resource_id": r.id,
                "resource_name": r.name,
                "source": "auto_assignment",
            })
    return {
        "project_id": project_id,
        "project_code": p.code,
        "project_title": p.title,
        "grants": out_grants,
        "auto_grants": auto_out,
    }


@router.post("/api/{project_id}/access")
async def create_project_access(
    project_id: int,
    request: Request,
    user_id: int = Form(...),
    role_in_project: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Concedi access esplicito a un user per il progetto."""
    actor = current_user_optional(request)
    if not is_admin(actor):
        raise HTTPException(403, "Solo admin può concedere access")
    if not db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first():
        raise HTTPException(404, "Progetto non trovato")
    if not db.query(User).filter(User.id == user_id).first():
        raise HTTPException(404, "User non trovato")
    # Pre-check: se grant attivo esiste già, no duplicate
    existing = db.query(ProjectAccessGrant).filter(
        ProjectAccessGrant.project_id == project_id,
        ProjectAccessGrant.user_id == user_id,
        ProjectAccessGrant.revoked_at.is_(None),
        ProjectAccessGrant.tenant_id == current_tenant_id(),
    ).first()
    if existing:
        raise HTTPException(409, "Grant attivo già esistente")
    g = ProjectAccessGrant(
        tenant_id=current_tenant_id(),
        project_id=project_id,
        user_id=user_id,
        role_in_project=(role_in_project or "").strip() or None,
        granted_by_user_id=actor.id if actor else None,
        notes=(notes or "").strip() or None,
    )
    db.add(g)
    db.flush()
    log_asset_access(db, user=actor, action=AssetAccessAction.share,
                     project_id=project_id, request=request,
                     extra=f"grant access to user_id={user_id} role={role_in_project}",
                     commit=False)
    db.commit()
    return {"id": g.id, "ok": True}


@router.delete("/api/{project_id}/access/{grant_id}")
async def revoke_project_access(
    project_id: int,
    grant_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Soft-revoke grant. Mantiene riga per audit trail."""
    actor = current_user_optional(request)
    if not is_admin(actor):
        raise HTTPException(403, "Solo admin può revocare access")
    g = db.query(ProjectAccessGrant).filter(
        ProjectAccessGrant.id == grant_id,
        ProjectAccessGrant.project_id == project_id,
        ProjectAccessGrant.tenant_id == current_tenant_id(),
    ).first()
    if not g:
        raise HTTPException(404, "Grant non trovato")
    if g.revoked_at:
        return {"ok": True, "already_revoked": True}
    from datetime import datetime as _dt2
    g.revoked_at = _dt2.utcnow()
    g.revoked_by_user_id = actor.id if actor else None
    log_asset_access(db, user=actor, action=AssetAccessAction.deny,
                     project_id=project_id, request=request,
                     extra=f"revoked grant_id={grant_id} for user_id={g.user_id}",
                     commit=False)
    db.commit()
    return {"ok": True, "revoked_at": str(g.revoked_at)}


@router.put("/api/{project_id}/security")
async def update_project_security(
    project_id: int,
    request: Request,
    ip_allowlist: Optional[str] = Form(None),  # JSON array string
    mfa_required: Optional[bool] = Form(None),
    min_role_for_access: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.70.3 — Aggiorna policy security TPN del progetto.
    Solo admin. ip_allowlist JSON: ["1.2.3.0/24", "10.0.0.5"]."""
    actor = current_user_optional(request)
    if not is_admin(actor):
        raise HTTPException(403, "Solo admin può modificare security")
    p = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    if ip_allowlist is not None:
        import json as _json
        try:
            parsed = _json.loads(ip_allowlist) if ip_allowlist.strip() else None
            if parsed is not None and not isinstance(parsed, list):
                raise HTTPException(400, "ip_allowlist deve essere lista JSON")
            # Validazione CIDR/IP
            import ipaddress
            for entry in (parsed or []):
                try:
                    if "/" in str(entry):
                        ipaddress.ip_network(entry, strict=False)
                    else:
                        ipaddress.ip_address(str(entry))
                except ValueError as e:
                    raise HTTPException(400, f"Entry non valida: {entry} ({e})")
            p.ip_allowlist = parsed
        except (TypeError, ValueError) as e:
            raise HTTPException(400, f"ip_allowlist JSON malformato: {e}")
    if mfa_required is not None:
        p.mfa_required = mfa_required
    if min_role_for_access is not None:
        p.min_role_for_access = min_role_for_access.strip() or None
    log_asset_access(db, user=actor, action=AssetAccessAction.update,
                     project_id=project_id, request=request,
                     extra="security policy updated", commit=False)
    db.commit()
    return {
        "ok": True,
        "ip_allowlist": p.ip_allowlist,
        "mfa_required": p.mfa_required,
        "min_role_for_access": p.min_role_for_access,
    }


@router.get("/api/{project_id}/security")
async def get_project_security(
    project_id: int, request: Request, db: Session = Depends(get_db),
):
    actor = current_user_optional(request)
    if not is_admin(actor):
        raise HTTPException(403, "Solo admin può vedere security")
    p = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "Progetto non trovato")
    return {
        "project_id": project_id,
        "ip_allowlist": p.ip_allowlist or [],
        "mfa_required": bool(p.mfa_required),
        "min_role_for_access": p.min_role_for_access,
    }


# ── HTML page detail (DOPO le API per evitare conflitti di path) ─────

@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse(
        "pages/project_detail.html",
        {"request": request, "project_id": project_id},
    )
