"""Router pianificazione — job, clienti, prenotazioni risorse."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date, datetime
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Job, JobStatus, Client, Booking, BookingStatus, Resource

router = APIRouter(prefix="/planning", tags=["planning"])

CURRENT_TENANT = 1


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ───────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def planning_page(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(Job).options(joinedload(Job.client)).all()
    clients = db.query(Client).all()
    return _tpl().TemplateResponse(
        "pages/planning.html", {"request": request, "jobs": jobs, "clients": clients}
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, db: Session = Depends(get_db)):
    resources = db.query(Resource).filter(Resource.is_active == True).all()
    return _tpl().TemplateResponse(
        "pages/calendar.html", {"request": request, "resources": resources}
    )


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
    db: Session = Depends(get_db),
):
    q = db.query(Job).options(joinedload(Job.client))
    if status:
        q = q.filter(Job.status == status)
    if client_id:
        q = q.filter(Job.client_id == client_id)
    jobs = q.all()
    return [
        {
            "id": j.id, "code": j.code, "title": j.title,
            "status": j.status, "client": j.client.name if j.client else None,
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

@router.get("/api/bookings")
async def list_bookings(
    job_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Booking).options(
        joinedload(Booking.resource), joinedload(Booking.job)
    ).filter(Booking.tenant_id == CURRENT_TENANT)
    if job_id:
        q = q.filter(Booking.job_id == job_id)
    if resource_id:
        q = q.filter(Booking.resource_id == resource_id)
    if from_date:
        q = q.filter(Booking.end_datetime >= from_date)
    if to_date:
        q = q.filter(Booking.start_datetime <= to_date)
    bookings = q.all()
    # Formato FullCalendar-compatible
    return [
        {
            "id": b.id,
            "title": f"{b.job.title} — {b.resource.name}",
            "start": b.start_datetime.isoformat(),
            "end": b.end_datetime.isoformat(),
            "color": b.resource.color,
            "extendedProps": {
                "job_id": b.job_id, "resource_id": b.resource_id,
                "status": b.status, "notes": b.notes,
            }
        }
        for b in bookings
    ]


@router.post("/api/bookings")
async def create_booking(
    job_id: int = Form(...),
    resource_id: int = Form(...),
    start_datetime: datetime = Form(...),
    end_datetime: datetime = Form(...),
    status: BookingStatus = Form(BookingStatus.tentative),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
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
        job_id=job_id, resource_id=resource_id,
        start_datetime=start_datetime, end_datetime=end_datetime,
        status=status, notes=notes,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


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
