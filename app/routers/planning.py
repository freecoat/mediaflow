"""Router pianificazione — hub viste + job, clienti, booking."""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from datetime import date, datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from app.database import get_db
from app.models import (
    Job, JobStatus, Client, Project, Booking, BookingStatus, BookingKind,
    Resource, ResourceType, JobCostLine, Department, User,
)
from app.services.auth import get_current_user_from_token

router = APIRouter(prefix="/planning", tags=["planning"])

CURRENT_TENANT = 1


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ───────────────────────────────────────────────────────

VALID_VIEWS = ("jobs", "calendar", "agenda", "todo", "timeline")


def _resolve_current_user(db: Session, token: Optional[str]) -> Optional[User]:
    if token:
        u = get_current_user_from_token(db, token)
        if u:
            return u
    return db.query(User).filter(User.is_active == True).order_by(User.id).first()


@router.get("/", response_class=HTMLResponse)
async def planning_hub(
    request: Request,
    view: str = "jobs",
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    if view not in VALID_VIEWS:
        view = "jobs"
    # Dati per i filtri trasversali
    clients = db.query(Client).filter(Client.tenant_id == CURRENT_TENANT).order_by(Client.name).all()
    projects = (
        db.query(Project).filter(Project.tenant_id == CURRENT_TENANT)
        .order_by(Project.code).all()
    )
    departments = (
        db.query(Department).filter(
            Department.tenant_id == CURRENT_TENANT, Department.is_active == True
        ).order_by(Department.sort_order, Department.name).all()
    )
    resources = (
        db.query(Resource).filter(
            Resource.tenant_id == CURRENT_TENANT, Resource.is_active == True
        ).order_by(Resource.name).all()
    )
    jobs = (
        db.query(Job).options(joinedload(Job.client), joinedload(Job.project))
        .filter(Job.status != JobStatus.cancelled)
        .order_by(Job.created_at.desc()).all()
    )
    cur_user = _resolve_current_user(db, access_token)
    cur_resource_id = None
    if cur_user:
        my_res = db.query(Resource).filter(Resource.user_id == cur_user.id).first()
        if my_res:
            cur_resource_id = my_res.id
    return _tpl().TemplateResponse(
        "pages/planning.html",
        {
            "request": request,
            "active_view": view,
            "clients": clients,
            "projects": projects,
            "departments": departments,
            "resources": resources,
            "jobs": jobs,
            "current_resource_id": cur_resource_id,
        },
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_redirect():
    """Compat v3.4.10−: ora il calendario è una vista dell'hub."""
    return RedirectResponse(url="/planning/?view=calendar", status_code=302)


# ── Clienti API ───────────────────────────────────────────────────────

@router.get("/api/clients")
async def list_clients(db: Session = Depends(get_db)):
    return db.query(Client).all()


@router.post("/api/clients")
async def create_client(
    name: str = Form(...),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    vat_number: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    c = Client(
        name=name, contact_email=contact_email,
        contact_phone=contact_phone, vat_number=vat_number, address=address,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ── Job API ───────────────────────────────────────────────────────────

@router.get("/api/jobs")
async def list_jobs(
    status: Optional[JobStatus] = None,
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    department_id: Optional[int] = None,
    q: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Lista job con filtri. Tenant filter implicito via project/client."""
    qs = db.query(Job).options(joinedload(Job.client), joinedload(Job.project))
    if status:
        qs = qs.filter(Job.status == status)
    if client_id:
        qs = qs.filter(Job.client_id == client_id)
    if project_id:
        qs = qs.filter(Job.project_id == project_id)
    if department_id:
        # Job tocca dipartimento se almeno una sua JobCostLine ha price_item
        # del reparto. Filtro grossolano: subquery EXISTS.
        from app.models import PriceItem
        sub = (
            db.query(JobCostLine.job_id)
            .join(PriceItem, JobCostLine.price_item_id == PriceItem.id)
            .filter(PriceItem.department_id == department_id)
        )
        qs = qs.filter(Job.id.in_(sub))
    if q:
        like = f"%{q.strip()}%"
        qs = qs.filter(or_(Job.code.ilike(like), Job.title.ilike(like)))
    if from_date:
        qs = qs.filter(or_(Job.end_date.is_(None), Job.end_date >= from_date))
    if to_date:
        qs = qs.filter(or_(Job.start_date.is_(None), Job.start_date <= to_date))
    jobs = qs.order_by(Job.created_at.desc()).all()
    return [
        {
            "id": j.id, "code": j.code, "title": j.title,
            "status": j.status.value if hasattr(j.status, "value") else j.status,
            "client_id": j.client_id,
            "client": j.client.name if j.client else None,
            "project_id": j.project_id,
            "project_code": j.project.code if j.project else None,
            "start_date": j.start_date, "end_date": j.end_date,
            "budget": j.budget_quoted,
        }
        for j in jobs
    ]


@router.post("/api/jobs", deprecated=True)
async def create_job(
    code: str = Form(...),
    title: str = Form(...),
    client_id: int = Form(...),
    status: JobStatus = Form(JobStatus.draft),
    start_date: Optional[date] = Form(None),
    end_date: Optional[date] = Form(None),
    budget: Optional[float] = Form(None),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """DEPRECATED dal v3.4.8. I job nascono solo da quote approvate.
    Mantenuto per scenari di import/migrazione legacy."""
    existing = db.query(Job).filter(Job.code == code).first()
    if existing:
        raise HTTPException(400, f"Codice job '{code}' già esistente")
    j = Job(
        code=code, title=title, client_id=client_id, status=status,
        start_date=start_date, end_date=end_date, budget=budget, description=description,
    )
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.query(Job).options(joinedload(Job.client)).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job non trovato")
    return j


@router.put("/api/jobs/{job_id}/status")
async def update_job_status(
    job_id: int,
    status: JobStatus = Form(...),
    db: Session = Depends(get_db),
):
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job non trovato")
    j.status = status
    db.commit()
    return {"id": j.id, "status": j.status}


# ── Booking API ───────────────────────────────────────────────────────

_KIND_LABEL = {
    BookingKind.project: "Progetto",
    BookingKind.internal_maintenance: "Manutenzione",
    BookingKind.internal_research: "R&D",
    BookingKind.internal_training: "Formazione",
}


def _booking_title(b: Booking) -> str:
    """Titolo umano per il calendario.
    project: 'Job · [Lavorazione] · Risorsa'
    internal_*: '[Tipo] · Risorsa'"""
    res_name = b.resource.name if b.resource else "?"
    if b.kind == BookingKind.project and b.job:
        parts = [b.job.title]
        if b.cost_line:
            parts.append(b.cost_line.description)
        parts.append(res_name)
        return " · ".join(parts)
    return f"{_KIND_LABEL.get(b.kind, str(b.kind))} · {res_name}"


@router.get("/api/bookings")
async def list_bookings(
    job_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    kind: Optional[BookingKind] = None,
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    department_id: Optional[int] = None,
    status: Optional[BookingStatus] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Booking).options(
        joinedload(Booking.resource),
        joinedload(Booking.job),
        joinedload(Booking.cost_line),
    ).filter(Booking.tenant_id == CURRENT_TENANT)
    if job_id:
        q = q.filter(Booking.job_id == job_id)
    if resource_id:
        q = q.filter(Booking.resource_id == resource_id)
    if kind:
        q = q.filter(Booking.kind == kind)
    if status:
        q = q.filter(Booking.status == status)
    else:
        # Default: nascondi cancellati (E1 v3.4.14)
        q = q.filter(Booking.status != BookingStatus.cancelled)
    if from_date:
        q = q.filter(Booking.end_datetime >= from_date)
    if to_date:
        q = q.filter(Booking.start_datetime <= to_date)
    # Filtri via job → client/project
    if client_id or project_id:
        q = q.join(Job, Booking.job_id == Job.id)
        if client_id:
            q = q.filter(Job.client_id == client_id)
        if project_id:
            q = q.filter(Job.project_id == project_id)
    # Filtro reparto via resource
    if department_id:
        q = q.join(Resource, Booking.resource_id == Resource.id).filter(
            Resource.department_id == department_id
        )
    bookings = q.all()
    # Formato FullCalendar-compatible
    return [
        {
            "id": b.id,
            "title": _booking_title(b),
            "start": b.start_datetime.isoformat(),
            "end": b.end_datetime.isoformat(),
            "color": b.resource.color if b.resource else "#6272f5",
            "extendedProps": {
                "source": "booking",
                "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
                "job_id": b.job_id,
                "job_cost_line_id": b.job_cost_line_id,
                "cost_line_description": b.cost_line.description if b.cost_line else None,
                "resource_id": b.resource_id,
                "status": b.status.value if hasattr(b.status, "value") else b.status,
                "notes": b.notes,
            }
        }
        for b in bookings
    ]


@router.post("/api/bookings")
async def create_booking(
    resource_id: int = Form(...),
    start_datetime: datetime = Form(...),
    end_datetime: datetime = Form(...),
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    kind: BookingKind = Form(BookingKind.project),
    status: BookingStatus = Form(BookingStatus.tentative),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea un booking. Tre scenari validati:
    - kind=project: job_id richiesto, job_cost_line_id opzionale (deve appartenere al job)
    - kind=internal_*: job_id e job_cost_line_id devono essere NULL (ignorati se passati)
    """
    if end_datetime <= start_datetime:
        raise HTTPException(400, "end_datetime deve essere > start_datetime")

    if kind == BookingKind.project:
        if not job_id:
            raise HTTPException(400, "Per kind=project serve job_id")
        if job_cost_line_id:
            line = db.query(JobCostLine).filter(JobCostLine.id == job_cost_line_id).first()
            if not line:
                raise HTTPException(404, "Lavorazione non trovata")
            if line.job_id != job_id:
                raise HTTPException(400, f"La lavorazione #{job_cost_line_id} non appartiene al job #{job_id}")
    else:
        # Booking interno: niente job/lavorazione
        job_id = None
        job_cost_line_id = None

    # Controllo conflitti
    conflict = db.query(Booking).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.resource_id == resource_id,
        Booking.status != BookingStatus.cancelled,
        Booking.start_datetime < end_datetime,
        Booking.end_datetime > start_datetime,
    ).first()
    if conflict:
        raise HTTPException(409, f"Conflitto con booking #{conflict.id}")

    b = Booking(
        tenant_id=CURRENT_TENANT,
        job_id=job_id,
        job_cost_line_id=job_cost_line_id,
        resource_id=resource_id,
        start_datetime=start_datetime, end_datetime=end_datetime,
        status=status, kind=kind, notes=notes,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return {
        "id": b.id, "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
        "job_id": b.job_id, "job_cost_line_id": b.job_cost_line_id,
        "resource_id": b.resource_id,
        "start_datetime": b.start_datetime.isoformat(),
        "end_datetime": b.end_datetime.isoformat(),
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "notes": b.notes,
    }


@router.put("/api/bookings/{booking_id}")
async def update_booking(
    booking_id: int,
    resource_id: Optional[int] = Form(None),
    start_datetime: Optional[datetime] = Form(None),
    end_datetime: Optional[datetime] = Form(None),
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    kind: Optional[BookingKind] = Form(None),
    status: Optional[BookingStatus] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Aggiorna un booking. Tutti i campi opzionali (PATCH semantics ma metodo PUT per coerenza form-based)."""
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")

    # Calcolo nuovi valori effettivi
    new_resource_id = resource_id if resource_id is not None else b.resource_id
    new_start = start_datetime if start_datetime is not None else b.start_datetime
    new_end = end_datetime if end_datetime is not None else b.end_datetime
    new_kind = kind if kind is not None else b.kind
    new_job_id = job_id if job_id is not None else b.job_id
    new_line_id = job_cost_line_id if job_cost_line_id is not None else b.job_cost_line_id

    if new_end <= new_start:
        raise HTTPException(400, "end_datetime deve essere > start_datetime")

    if new_kind == BookingKind.project:
        if not new_job_id:
            raise HTTPException(400, "Per kind=project serve job_id")
        if new_line_id:
            line = db.query(JobCostLine).filter(JobCostLine.id == new_line_id).first()
            if not line:
                raise HTTPException(404, "Lavorazione non trovata")
            if line.job_id != new_job_id:
                raise HTTPException(400, f"La lavorazione #{new_line_id} non appartiene al job #{new_job_id}")
    else:
        new_job_id = None
        new_line_id = None

    # Controllo conflitti escludendo se stesso
    conflict = db.query(Booking).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.resource_id == new_resource_id,
        Booking.id != booking_id,
        Booking.status != BookingStatus.cancelled,
        Booking.start_datetime < new_end,
        Booking.end_datetime > new_start,
    ).first()
    if conflict:
        raise HTTPException(409, f"Conflitto con booking #{conflict.id}")

    # Apply
    b.resource_id = new_resource_id
    b.start_datetime = new_start
    b.end_datetime = new_end
    b.kind = new_kind
    b.job_id = new_job_id
    b.job_cost_line_id = new_line_id
    if status is not None:
        b.status = status
    if notes is not None:
        b.notes = notes
    db.commit()
    db.refresh(b)
    return {
        "id": b.id, "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
        "job_id": b.job_id, "job_cost_line_id": b.job_cost_line_id,
        "resource_id": b.resource_id,
        "start_datetime": b.start_datetime.isoformat(),
        "end_datetime": b.end_datetime.isoformat(),
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "notes": b.notes,
    }


@router.delete("/api/bookings/{booking_id}")
async def delete_booking(booking_id: int, db: Session = Depends(get_db)):
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    b.status = BookingStatus.cancelled
    db.commit()
    return {"ok": True}


@router.post("/api/bookings/{booking_id}/restore")
async def restore_booking(booking_id: int, db: Session = Depends(get_db)):
    """Ripristina un booking cancellato (per undo)."""
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    # Conflict check sul ripristino
    conflict = db.query(Booking).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.resource_id == b.resource_id,
        Booking.id != booking_id,
        Booking.status != BookingStatus.cancelled,
        Booking.start_datetime < b.end_datetime,
        Booking.end_datetime > b.start_datetime,
    ).first()
    if conflict:
        raise HTTPException(409, f"Conflitto con booking #{conflict.id}")
    b.status = BookingStatus.tentative
    db.commit()
    return {"ok": True, "id": b.id}
