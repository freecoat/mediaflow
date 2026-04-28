"""
Router HR — gestione timbrature e ore di lavoro.

Sezione amministrativa per la rendicontazione delle ore di lavoro di tutte le
risorse umane (interne + freelance). Modello `TimePunch` separato dai Booking:
booking = intenzione di pianificazione, time_punch = presenza effettiva.

MVP: CRUD + lista filtrabile + totali per kind. Aggregazioni avanzate (report
mensile, costo orario × ore, esportazione cedolino) in iterazione successiva.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    Resource, ResourceType, TimePunch, PunchKind, Job, JobCostLine, User,
)
from app.services.auth import get_current_user_from_token

router = APIRouter(prefix="/hr", tags=["hr"])

CURRENT_TENANT = 1

# Tipi di Resource che rappresentano persone (rendicontano ore).
PERSON_TYPES = (
    ResourceType.person_internal,
    ResourceType.person_freelance,
    ResourceType.person,  # legacy
)

# Colori per tipologia di timbratura nel calendario / badge.
KIND_COLOR = {
    PunchKind.shift: None,       # usa il colore della risorsa
    PunchKind.idle: "#9ca3af",   # grigio
    PunchKind.leave: "#c084fc",  # lavanda
    PunchKind.sick: "#f87171",   # rosso chiaro
    PunchKind.break_: "#fbbf24", # giallo
    PunchKind.overtime: "#fb923c",  # arancione
}

KIND_LABEL = {
    PunchKind.shift: "Turno",
    PunchKind.idle: "Idle",
    PunchKind.leave: "Ferie/Permesso",
    PunchKind.sick: "Malattia",
    PunchKind.break_: "Pausa",
    PunchKind.overtime: "Straordinario",
}


def _tpl():
    from app.main import templates
    return templates


def _resolve_current_user(db: Session, token: Optional[str]) -> Optional[User]:
    if token:
        u = get_current_user_from_token(db, token)
        if u:
            return u
    return db.query(User).filter(User.is_active == True).order_by(User.id).first()


def _punch_dict(p: TimePunch, *, fullcalendar: bool = False) -> dict:
    """Serializza una timbratura. Se fullcalendar=True, formato compatibile FullCalendar."""
    duration_h = None
    if p.end_datetime:
        delta = p.end_datetime - p.start_datetime
        duration_h = round(delta.total_seconds() / 3600.0, 2)

    if fullcalendar:
        kind_color = KIND_COLOR.get(p.kind)
        color = kind_color or (p.resource.color if p.resource else "#6272f5")
        title_parts = [p.resource.name if p.resource else "?"]
        title_parts.append(KIND_LABEL.get(p.kind, str(p.kind)))
        if p.job:
            title_parts.append(p.job.title)
        return {
            "id": f"punch-{p.id}",
            "title": " · ".join(title_parts),
            "start": p.start_datetime.isoformat(),
            "end": p.end_datetime.isoformat() if p.end_datetime else None,
            "color": color,
            "extendedProps": {
                "source": "punch",
                "punch_id": p.id,
                "resource_id": p.resource_id,
                "job_id": p.job_id,
                "job_cost_line_id": p.job_cost_line_id,
                "kind": p.kind.value if hasattr(p.kind, "value") else p.kind,
                "notes": p.notes,
                "duration_h": duration_h,
            },
        }

    return {
        "id": p.id,
        "tenant_id": p.tenant_id,
        "resource_id": p.resource_id,
        "resource_name": p.resource.name if p.resource else None,
        "resource_color": p.resource.color if p.resource else None,
        "job_id": p.job_id,
        "job_title": p.job.title if p.job else None,
        "job_code": p.job.code if p.job else None,
        "job_cost_line_id": p.job_cost_line_id,
        "cost_line_description": p.cost_line.description if p.cost_line else None,
        "start_datetime": p.start_datetime.isoformat(),
        "end_datetime": p.end_datetime.isoformat() if p.end_datetime else None,
        "duration_h": duration_h,
        "kind": p.kind.value if hasattr(p.kind, "value") else p.kind,
        "kind_label": KIND_LABEL.get(p.kind, str(p.kind)),
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ── Pagina HTML ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def hr_page(request: Request, db: Session = Depends(get_db)):
    persons = (
        db.query(Resource)
        .filter(
            Resource.tenant_id == CURRENT_TENANT,
            Resource.is_active == True,
            Resource.type.in_(PERSON_TYPES),
        )
        .order_by(Resource.name)
        .all()
    )
    jobs = (
        db.query(Job)
        .filter(Job.client_id.isnot(None))
        .order_by(Job.created_at.desc())
        .limit(200)
        .all()
    )
    kinds = [{"value": k.value, "label": KIND_LABEL[k], "color": KIND_COLOR.get(k)} for k in PunchKind]
    return _tpl().TemplateResponse(
        "pages/hr.html",
        {"request": request, "persons": persons, "jobs": jobs, "kinds": kinds},
    )


# ── API ──────────────────────────────────────────────────────

@router.get("/api/punches")
async def list_punches(
    resource_id: Optional[int] = None,
    job_id: Optional[int] = None,
    kind: Optional[PunchKind] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    format: str = "json",
    db: Session = Depends(get_db),
):
    q = (
        db.query(TimePunch)
        .options(joinedload(TimePunch.resource), joinedload(TimePunch.job))
        .filter(TimePunch.tenant_id == CURRENT_TENANT)
    )
    if resource_id:
        q = q.filter(TimePunch.resource_id == resource_id)
    if job_id:
        q = q.filter(TimePunch.job_id == job_id)
    if kind:
        q = q.filter(TimePunch.kind == kind)
    if from_date:
        # Prendi anche punches in corso che si sovrappongono al range
        q = q.filter(
            (TimePunch.end_datetime.is_(None)) | (TimePunch.end_datetime >= from_date)
        )
    if to_date:
        q = q.filter(TimePunch.start_datetime <= to_date)
    q = q.order_by(TimePunch.start_datetime.desc())
    punches = q.all()

    fc = format == "fullcalendar"
    return [_punch_dict(p, fullcalendar=fc) for p in punches]


@router.post("/api/punches")
async def create_punch(
    resource_id: int = Form(...),
    start_datetime: datetime = Form(...),
    end_datetime: Optional[datetime] = Form(None),
    kind: PunchKind = Form(PunchKind.shift),
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    r = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.tenant_id == CURRENT_TENANT,
    ).first()
    if not r:
        raise HTTPException(404, "Risorsa non trovata")
    if r.type not in PERSON_TYPES:
        raise HTTPException(400, f"Le timbrature sono solo per persone (resource type={r.type})")

    if end_datetime and end_datetime <= start_datetime:
        raise HTTPException(400, "end_datetime deve essere successivo a start_datetime")

    if job_id:
        j = db.query(Job).filter(Job.id == job_id).first()
        if not j:
            raise HTTPException(404, "Job non trovato")
    if job_cost_line_id:
        line = db.query(JobCostLine).filter(JobCostLine.id == job_cost_line_id).first()
        if not line:
            raise HTTPException(404, "Lavorazione non trovata")
        if job_id and line.job_id != job_id:
            raise HTTPException(400, f"Lavorazione #{job_cost_line_id} non appartiene al job #{job_id}")
        # Se non c'è job_id ma c'è cost_line, deduco il job dalla riga
        if not job_id:
            job_id = line.job_id

    u = _resolve_current_user(db, access_token)
    p = TimePunch(
        tenant_id=CURRENT_TENANT,
        resource_id=resource_id,
        job_id=job_id,
        job_cost_line_id=job_cost_line_id,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        kind=kind,
        notes=notes,
        created_by_user_id=u.id if u else None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _punch_dict(p)


@router.put("/api/punches/{punch_id}")
async def update_punch(
    punch_id: int,
    start_datetime: Optional[datetime] = Form(None),
    end_datetime: Optional[datetime] = Form(None),
    kind: Optional[PunchKind] = Form(None),
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    clear_end: bool = Form(False),
    clear_job: bool = Form(False),
    clear_cost_line: bool = Form(False),
    db: Session = Depends(get_db),
):
    p = db.query(TimePunch).filter(
        TimePunch.id == punch_id,
        TimePunch.tenant_id == CURRENT_TENANT,
    ).first()
    if not p:
        raise HTTPException(404, "Timbratura non trovata")

    if start_datetime is not None:
        p.start_datetime = start_datetime
    if end_datetime is not None:
        p.end_datetime = end_datetime
    elif clear_end:
        p.end_datetime = None
    if kind is not None:
        p.kind = kind
    if job_id is not None:
        p.job_id = job_id
    elif clear_job:
        p.job_id = None
        p.job_cost_line_id = None  # cancellando job, cancello anche la lavorazione
    if job_cost_line_id is not None:
        p.job_cost_line_id = job_cost_line_id
    elif clear_cost_line:
        p.job_cost_line_id = None
    if notes is not None:
        p.notes = notes

    if p.end_datetime and p.end_datetime <= p.start_datetime:
        raise HTTPException(400, "end_datetime deve essere successivo a start_datetime")

    db.commit()
    db.refresh(p)
    return _punch_dict(p)


@router.delete("/api/punches/{punch_id}")
async def delete_punch(punch_id: int, db: Session = Depends(get_db)):
    p = db.query(TimePunch).filter(
        TimePunch.id == punch_id,
        TimePunch.tenant_id == CURRENT_TENANT,
    ).first()
    if not p:
        raise HTTPException(404, "Timbratura non trovata")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/api/summary")
async def punches_summary(
    resource_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Totali ore per kind nel periodo. Esclude timbrature in corso (end NULL)."""
    q = db.query(TimePunch).filter(
        TimePunch.tenant_id == CURRENT_TENANT,
        TimePunch.end_datetime.isnot(None),
    )
    if resource_id:
        q = q.filter(TimePunch.resource_id == resource_id)
    if from_date:
        q = q.filter(TimePunch.start_datetime >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        q = q.filter(TimePunch.start_datetime <= datetime.combine(to_date, datetime.max.time()))

    totals = {k.value: 0.0 for k in PunchKind}
    grand_total = 0.0
    for p in q.all():
        hours = (p.end_datetime - p.start_datetime).total_seconds() / 3600.0
        kv = p.kind.value if hasattr(p.kind, "value") else p.kind
        totals[kv] = totals.get(kv, 0.0) + hours
        grand_total += hours

    return {
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "grand_total": round(grand_total, 2),
        "labels": {k.value: KIND_LABEL[k] for k in PunchKind},
        "colors": {k.value: KIND_COLOR.get(k) for k in PunchKind},
    }
