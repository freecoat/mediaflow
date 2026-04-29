"""Router pianificazione — hub viste + job, clienti, booking."""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from datetime import date, datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from app.database import get_db
from app.models import (
    Job, JobStatus, Client, Project, Booking, BookingAssignment, BookingChange,
    BookingStatus, BookingKind,
    Resource, ResourceType, JobCostLine, Department, User,
    WorkingHoursPolicy, ResourceUnavailability, UnavailabilityKind,
)
from datetime import date as _date, timedelta as _td
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


# ── Booking API (multi-resource v3.4.16) ───────────────────────────────

import json as _json

_KIND_LABEL = {
    BookingKind.project: "Progetto",
    BookingKind.internal_maintenance: "Manutenzione",
    BookingKind.internal_research: "R&D",
    BookingKind.internal_training: "Formazione",
}


def _booking_title_for_assignment(b: Booking, resource_name: str) -> str:
    """Titolo umano per un singolo assignment all'interno di un booking."""
    if b.kind == BookingKind.project and b.job:
        parts = [b.job.title]
        if b.cost_line:
            parts.append(b.cost_line.description)
        parts.append(resource_name or "?")
        return " · ".join(parts)
    return f"{_KIND_LABEL.get(b.kind, str(b.kind))} · {resource_name or '?'}"


def _check_assignment_conflict(db: Session, resource_id: int, start: datetime, end: datetime,
                                exclude_assignment_id: Optional[int] = None) -> Optional[BookingAssignment]:
    """Verifica se esiste un altro assignment in conflitto sulla stessa risorsa."""
    q = db.query(BookingAssignment).join(Booking, BookingAssignment.booking_id == Booking.id).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.status != BookingStatus.cancelled,
        BookingAssignment.resource_id == resource_id,
        BookingAssignment.start_datetime < end,
        BookingAssignment.end_datetime > start,
    )
    if exclude_assignment_id:
        q = q.filter(BookingAssignment.id != exclude_assignment_id)
    return q.first()


def _recalc_booking_envelope(b: Booking):
    """Ricalcola Booking.start_datetime/end_datetime come min/max dei suoi assignments."""
    if not b.assignments:
        return
    b.start_datetime = min(a.start_datetime for a in b.assignments)
    b.end_datetime = max(a.end_datetime for a in b.assignments)


def _validate_kind_job(kind: BookingKind, job_id: Optional[int],
                       job_cost_line_id: Optional[int], db: Session):
    """Valida coerenza kind / job_id / cost_line_id. Ritorna (job_id_clean, line_id_clean)."""
    if kind == BookingKind.project:
        if not job_id:
            raise HTTPException(400, "Per kind=project serve job_id")
        if job_cost_line_id:
            line = db.query(JobCostLine).filter(JobCostLine.id == job_cost_line_id).first()
            if not line:
                raise HTTPException(404, "Lavorazione non trovata")
            if line.job_id != job_id:
                raise HTTPException(400, f"La lavorazione #{job_cost_line_id} non appartiene al job #{job_id}")
        return job_id, job_cost_line_id
    return None, None


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
    """Lista assignments come items per la timeline.
    Ogni booking con N risorse → N items distinti (group=resource_id),
    legati allo stesso booking_id via extendedProps."""
    q = db.query(BookingAssignment).options(
        joinedload(BookingAssignment.resource),
        joinedload(BookingAssignment.booking).joinedload(Booking.job),
        joinedload(BookingAssignment.booking).joinedload(Booking.cost_line),
    ).join(Booking, BookingAssignment.booking_id == Booking.id).filter(
        Booking.tenant_id == CURRENT_TENANT,
    )
    if job_id:
        q = q.filter(Booking.job_id == job_id)
    if resource_id:
        q = q.filter(BookingAssignment.resource_id == resource_id)
    if kind:
        q = q.filter(Booking.kind == kind)
    if status:
        q = q.filter(Booking.status == status)
    else:
        q = q.filter(Booking.status != BookingStatus.cancelled)
    if from_date:
        q = q.filter(BookingAssignment.end_datetime >= from_date)
    if to_date:
        q = q.filter(BookingAssignment.start_datetime <= to_date)
    if client_id or project_id:
        q = q.join(Job, Booking.job_id == Job.id, isouter=True)
        if client_id:
            q = q.filter(Job.client_id == client_id)
        if project_id:
            q = q.filter(Job.project_id == project_id)
    if department_id:
        q = q.join(Resource, BookingAssignment.resource_id == Resource.id).filter(
            Resource.department_id == department_id
        )
    assignments = q.all()
    # Cardinalità gruppo per ciascun booking_id (per badge "1/N")
    booking_ids = list({a.booking_id for a in assignments})
    if booking_ids:
        sizes = dict(
            db.query(BookingAssignment.booking_id, db.query(BookingAssignment.id).filter(
                BookingAssignment.booking_id.in_(booking_ids)
            ).count())
            .filter(BookingAssignment.booking_id.in_(booking_ids))
            .group_by(BookingAssignment.booking_id).all()
        )
        # SQLAlchemy non supporta sub-query inline per count gruppo, ricalcolo manuale
        from collections import Counter
        sizes = Counter()
        for a in db.query(BookingAssignment).filter(BookingAssignment.booking_id.in_(booking_ids)).all():
            sizes[a.booking_id] += 1
    else:
        sizes = {}

    # Posizione (1-N) per ordinamento per booking
    by_booking: dict[int, list[BookingAssignment]] = {}
    for a in assignments:
        by_booking.setdefault(a.booking_id, []).append(a)
    pos_map = {}
    for bid, lst in by_booking.items():
        lst_sorted = sorted(lst, key=lambda x: x.start_datetime)
        for i, a in enumerate(lst_sorted, 1):
            pos_map[a.id] = i

    out = []
    for a in assignments:
        b = a.booking
        res_name = a.resource.name if a.resource else "?"
        out.append({
            "id": f"a{a.id}",
            "assignment_id": a.id,
            "booking_id": b.id,
            "title": _booking_title_for_assignment(b, res_name),
            "start": a.start_datetime.isoformat(),
            "end": a.end_datetime.isoformat(),
            "color": a.resource.color if a.resource else "#6272f5",
            "extendedProps": {
                "source": "booking",
                "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
                "job_id": b.job_id,
                "job_cost_line_id": b.job_cost_line_id,
                "cost_line_description": b.cost_line.description if b.cost_line else None,
                "resource_id": a.resource_id,
                "status": b.status.value if hasattr(b.status, "value") else b.status,
                "notes": b.notes,
                "group_size": sizes.get(b.id, 1),
                "group_position": pos_map.get(a.id, 1),
            }
        })
    return out


def _log_change(db: Session, booking_id: int, kind: str, summary: str, payload: Optional[dict] = None):
    """Aggiunge una entry al booking_changes audit log (E5 v3.4.19)."""
    try:
        db.add(BookingChange(booking_id=booking_id, kind=kind, summary=summary, payload=payload or {}))
    except Exception:
        pass  # audit log non blocca operazioni


def _expand_recurrence(start: datetime, end: datetime, rule: str, until: _date) -> list[tuple[datetime, datetime]]:
    """Espande una regola di ricorrenza in una lista di (start, end) per occorrenza.

    `rule` accetta: 'DAILY' (tutti i giorni), 'WEEKDAYS' (lun-ven),
    'WEEKENDS' (sab-dom), oppure CSV di nomi giorno (es. 'MON,WED,FRI').
    Le occorrenze partono da `start.date()` (inclusa) fino a `until` (inclusa).
    Mantengono lo stesso orario start/end del primo.
    """
    rule = (rule or "").upper().strip()
    if not rule:
        return [(start, end)]
    DAYS = {"MON":0, "TUE":1, "WED":2, "THU":3, "FRI":4, "SAT":5, "SUN":6}
    if rule == "DAILY":
        days = set(range(7))
    elif rule == "WEEKDAYS":
        days = {0,1,2,3,4}
    elif rule == "WEEKENDS":
        days = {5,6}
    else:
        days = set()
        for tok in rule.split(","):
            t = tok.strip()
            if t in DAYS:
                days.add(DAYS[t])
    if not days:
        return [(start, end)]
    cur_date = start.date()
    duration = end - start
    out: list[tuple[datetime, datetime]] = []
    last = until or cur_date
    while cur_date <= last:
        if cur_date.weekday() in days:
            slot_start = datetime.combine(cur_date, start.time())
            out.append((slot_start, slot_start + duration))
        cur_date += _td(days=1)
    return out


def _resolve_policy_for_resource(db: Session, resource_id: int) -> Optional[WorkingHoursPolicy]:
    """Ritorna la policy override per la risorsa, oppure la default del tenant."""
    r = db.query(Resource).filter(Resource.id == resource_id).first()
    if r and r.working_hours_policy_id:
        p = db.query(WorkingHoursPolicy).filter(WorkingHoursPolicy.id == r.working_hours_policy_id).first()
        if p:
            return p
    return db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT,
        WorkingHoursPolicy.is_default == True,
    ).first()


def _expand_assignments_smart(db: Session, parsed_ass: list[dict]) -> list[dict]:
    """Per ogni assignment richiesto, applica `split_booking_smart` con la policy
    della risorsa + le sue ferie/malattie. Ritorna la nuova lista espansa."""
    from app.services.working_hours import split_booking_smart
    out = []
    for pa in parsed_ass:
        rid = pa["resource_id"]
        policy = _resolve_policy_for_resource(db, rid)
        if not policy:
            # Nessuna policy → fallback: passa l'assignment intero senza modifiche
            out.append(pa)
            continue
        unavs = db.query(ResourceUnavailability).filter(
            ResourceUnavailability.resource_id == rid,
        ).all()
        slots = split_booking_smart(pa["start_datetime"], pa["end_datetime"], policy, unavs)
        if not slots:
            # Range completamente fuori orario → niente da creare
            continue
        for sl in slots:
            out.append({"resource_id": rid, "start_datetime": sl.start, "end_datetime": sl.end})
    return out


@router.post("/api/bookings")
async def create_booking(
    assignments: str = Form(...),  # JSON: [{"resource_id":1,"start_datetime":"...","end_datetime":"..."}, ...]
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    kind: BookingKind = Form(BookingKind.project),
    status: BookingStatus = Form(BookingStatus.tentative),
    notes: Optional[str] = Form(None),
    smart_split: bool = Form(False),  # E3 v3.4.17
    recurrence_rule: Optional[str] = Form(None),  # E5 v3.4.19: WEEKDAYS, MON, TUE,THU, DAILY...
    recurrence_until: Optional[_date] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea un booking con N assignments (multi-risorsa).

    `assignments` è una stringa JSON con la lista delle assegnazioni.
    Ogni elemento: {"resource_id": int, "start_datetime": ISO, "end_datetime": ISO}.
    Almeno 1 assignment richiesto (warning per 0).
    """
    try:
        ass_list = _json.loads(assignments)
    except Exception:
        raise HTTPException(400, "assignments deve essere JSON valido (lista di oggetti)")
    if not isinstance(ass_list, list) or not ass_list:
        raise HTTPException(400, "Servono almeno 1 risorsa assegnata al booking")

    # Validation kind/job
    job_id, job_cost_line_id = _validate_kind_job(kind, job_id, job_cost_line_id, db)

    # Parse + valida ogni assignment
    parsed_ass = []
    for i, a in enumerate(ass_list):
        if not isinstance(a, dict):
            raise HTTPException(400, f"assignments[{i}] deve essere un oggetto")
        rid = a.get("resource_id")
        s = a.get("start_datetime")
        e = a.get("end_datetime")
        if not rid or not s or not e:
            raise HTTPException(400, f"assignments[{i}]: resource_id, start_datetime, end_datetime richiesti")
        try:
            sd = datetime.fromisoformat(s) if isinstance(s, str) else s
            ed = datetime.fromisoformat(e) if isinstance(e, str) else e
        except Exception:
            raise HTTPException(400, f"assignments[{i}]: date non valide")
        if ed <= sd:
            raise HTTPException(400, f"assignments[{i}]: end_datetime deve essere > start_datetime")
        parsed_ass.append({"resource_id": int(rid), "start_datetime": sd, "end_datetime": ed})

    # E5 v3.4.19: Recurrence — espande il range originale in N occorrenze (indipendenti dalla policy)
    # Crea un Booking distinct per ogni occorrenza, poi return solo il primo per coerenza payload.
    occurrence_offsets: list[tuple[datetime, datetime]] = []
    if recurrence_rule:
        if not recurrence_until:
            raise HTTPException(400, "recurrence_rule richiede recurrence_until")
        # Usa il PRIMO assignment come pattern: ricorrenza moltiplica gli assignments giornalieri
        first = parsed_ass[0]
        occurrence_offsets = _expand_recurrence(first["start_datetime"], first["end_datetime"],
                                                 recurrence_rule, recurrence_until)
        if not occurrence_offsets:
            raise HTTPException(400, "recurrence_rule non genera occorrenze nel range")

    # E3 v3.4.17: Smart split server-side se richiesto
    if smart_split:
        parsed_ass = _expand_assignments_smart(db, parsed_ass)
        if not parsed_ass:
            raise HTTPException(400, "Smart split: il range richiesto non contiene orario lavorativo (tutto fuori orario, weekend, ferie o festivi)")

    # Conflict check su tutti gli assignments (vs altri booking attivi)
    for i, pa in enumerate(parsed_ass):
        c = _check_assignment_conflict(db, pa["resource_id"], pa["start_datetime"], pa["end_datetime"])
        if c:
            raise HTTPException(409, f"Conflitto su risorsa per assignments[{i}] (vs assignment #{c.id})")

    # Crea Booking + assignments. Se recurrence → 1 Booking per occorrenza.
    primary_booking: Optional[Booking] = None
    booking_count = 0
    if occurrence_offsets:
        # Per ogni occorrenza, replica il pattern parsed_ass shiftato sul giorno target
        first_pattern_start = parsed_ass[0]["start_datetime"]
        for occ_start, _occ_end in occurrence_offsets:
            day_offset = (occ_start.date() - first_pattern_start.date()).days
            shifted_ass = []
            for pa in parsed_ass:
                shifted_ass.append({
                    "resource_id": pa["resource_id"],
                    "start_datetime": pa["start_datetime"] + _td(days=day_offset),
                    "end_datetime": pa["end_datetime"] + _td(days=day_offset),
                })
            # Conflict check per ogni occorrenza
            for i, pa in enumerate(shifted_ass):
                c = _check_assignment_conflict(db, pa["resource_id"], pa["start_datetime"], pa["end_datetime"])
                if c:
                    raise HTTPException(409, f"Conflitto su occorrenza {occ_start.date()} (vs assignment #{c.id})")
            env_s = min(pa["start_datetime"] for pa in shifted_ass)
            env_e = max(pa["end_datetime"] for pa in shifted_ass)
            b = Booking(
                tenant_id=CURRENT_TENANT,
                job_id=job_id, job_cost_line_id=job_cost_line_id,
                start_datetime=env_s, end_datetime=env_e,
                status=status, kind=kind, notes=notes,
            )
            db.add(b); db.flush()
            for pa in shifted_ass:
                db.add(BookingAssignment(
                    booking_id=b.id, resource_id=pa["resource_id"],
                    start_datetime=pa["start_datetime"], end_datetime=pa["end_datetime"],
                ))
            _log_change(db, b.id, "create", f"Booking ricorrente {recurrence_rule} (occ {occ_start.date()})", {"recurrence": recurrence_rule, "until": str(recurrence_until)})
            if primary_booking is None:
                primary_booking = b
            booking_count += 1
        db.commit()
        db.refresh(primary_booking)
        return {
            "id": primary_booking.id,
            "kind": primary_booking.kind.value if hasattr(primary_booking.kind, "value") else primary_booking.kind,
            "job_id": primary_booking.job_id, "job_cost_line_id": primary_booking.job_cost_line_id,
            "start_datetime": primary_booking.start_datetime.isoformat(),
            "end_datetime": primary_booking.end_datetime.isoformat(),
            "status": primary_booking.status.value if hasattr(primary_booking.status, "value") else primary_booking.status,
            "notes": primary_booking.notes,
            "assignments": [
                {"id": a.id, "resource_id": a.resource_id,
                 "start_datetime": a.start_datetime.isoformat(),
                 "end_datetime": a.end_datetime.isoformat()}
                for a in primary_booking.assignments
            ],
            "recurrence_count": booking_count,
        }

    # Caso semplice: 1 booking
    env_start = min(pa["start_datetime"] for pa in parsed_ass)
    env_end = max(pa["end_datetime"] for pa in parsed_ass)
    b = Booking(
        tenant_id=CURRENT_TENANT,
        job_id=job_id,
        job_cost_line_id=job_cost_line_id,
        start_datetime=env_start, end_datetime=env_end,
        status=status, kind=kind, notes=notes,
    )
    db.add(b)
    db.flush()  # serve b.id
    for pa in parsed_ass:
        db.add(BookingAssignment(
            booking_id=b.id,
            resource_id=pa["resource_id"],
            start_datetime=pa["start_datetime"],
            end_datetime=pa["end_datetime"],
        ))
    _log_change(db, b.id, "create", f"Booking creato ({len(parsed_ass)} risorse)", None)
    db.commit()
    db.refresh(b)
    return {
        "id": b.id, "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
        "job_id": b.job_id, "job_cost_line_id": b.job_cost_line_id,
        "start_datetime": b.start_datetime.isoformat(),
        "end_datetime": b.end_datetime.isoformat(),
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "notes": b.notes,
        "assignments": [
            {"id": a.id, "resource_id": a.resource_id,
             "start_datetime": a.start_datetime.isoformat(),
             "end_datetime": a.end_datetime.isoformat()}
            for a in b.assignments
        ],
    }


@router.put("/api/bookings/{booking_id}")
async def update_booking(
    booking_id: int,
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    kind: Optional[BookingKind] = Form(None),
    status: Optional[BookingStatus] = Form(None),
    notes: Optional[str] = Form(None),
    assignments: Optional[str] = Form(None),  # se passato, replace-all
    db: Session = Depends(get_db),
):
    """Aggiorna metadata booking (kind/job/status/notes) e/o sostituisce assignments.

    Per drag/resize di un singolo item della timeline → usare PUT /api/booking-assignments/{aid}.
    """
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")

    new_kind = kind if kind is not None else b.kind
    new_job_id = job_id if job_id is not None else b.job_id
    new_line_id = job_cost_line_id if job_cost_line_id is not None else b.job_cost_line_id
    new_job_id, new_line_id = _validate_kind_job(new_kind, new_job_id, new_line_id, db)

    # Replace-all assignments se passato
    if assignments is not None:
        try:
            ass_list = _json.loads(assignments)
        except Exception:
            raise HTTPException(400, "assignments JSON non valido")
        if not isinstance(ass_list, list) or not ass_list:
            raise HTTPException(400, "Servono almeno 1 risorsa assegnata")
        parsed_ass = []
        for i, a in enumerate(ass_list):
            rid = a.get("resource_id"); s = a.get("start_datetime"); e = a.get("end_datetime")
            try:
                sd = datetime.fromisoformat(s) if isinstance(s, str) else s
                ed = datetime.fromisoformat(e) if isinstance(e, str) else e
            except Exception:
                raise HTTPException(400, f"assignments[{i}]: date non valide")
            if ed <= sd:
                raise HTTPException(400, f"assignments[{i}]: fine deve essere > inizio")
            parsed_ass.append({"resource_id": int(rid), "start_datetime": sd, "end_datetime": ed})
        # Conflict check (escludendo gli assignment attuali del booking, che sostituiremo)
        existing_ids = [a.id for a in b.assignments]
        for i, pa in enumerate(parsed_ass):
            q = db.query(BookingAssignment).join(Booking).filter(
                Booking.tenant_id == CURRENT_TENANT,
                Booking.status != BookingStatus.cancelled,
                BookingAssignment.resource_id == pa["resource_id"],
                BookingAssignment.start_datetime < pa["end_datetime"],
                BookingAssignment.end_datetime > pa["start_datetime"],
            )
            if existing_ids:
                q = q.filter(~BookingAssignment.id.in_(existing_ids))
            c = q.first()
            if c:
                raise HTTPException(409, f"Conflitto su risorsa per assignments[{i}] (vs assignment #{c.id})")
        # Replace
        for old in list(b.assignments):
            db.delete(old)
        db.flush()
        for pa in parsed_ass:
            db.add(BookingAssignment(
                booking_id=b.id,
                resource_id=pa["resource_id"],
                start_datetime=pa["start_datetime"],
                end_datetime=pa["end_datetime"],
            ))

    b.kind = new_kind
    b.job_id = new_job_id
    b.job_cost_line_id = new_line_id
    if status is not None:
        b.status = status
    if notes is not None:
        b.notes = notes

    db.flush()
    db.refresh(b)
    _recalc_booking_envelope(b)
    _log_change(db, b.id, "update", "Booking aggiornato", None)
    db.commit()
    return {
        "id": b.id, "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
        "job_id": b.job_id, "job_cost_line_id": b.job_cost_line_id,
        "start_datetime": b.start_datetime.isoformat(),
        "end_datetime": b.end_datetime.isoformat(),
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "notes": b.notes,
        "assignments": [
            {"id": a.id, "resource_id": a.resource_id,
             "start_datetime": a.start_datetime.isoformat(),
             "end_datetime": a.end_datetime.isoformat()}
            for a in b.assignments
        ],
    }


@router.put("/api/booking-assignments/{assignment_id}")
async def update_assignment(
    assignment_id: int,
    resource_id: Optional[int] = Form(None),
    start_datetime: Optional[datetime] = Form(None),
    end_datetime: Optional[datetime] = Form(None),
    db: Session = Depends(get_db),
):
    """Aggiorna un singolo assignment (drag/resize/reassign del singolo item timeline)."""
    a = db.query(BookingAssignment).join(Booking).filter(
        BookingAssignment.id == assignment_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not a:
        raise HTTPException(404, "Assignment non trovato")
    new_rid = resource_id if resource_id is not None else a.resource_id
    new_s = start_datetime if start_datetime is not None else a.start_datetime
    new_e = end_datetime if end_datetime is not None else a.end_datetime
    if new_e <= new_s:
        raise HTTPException(400, "end_datetime deve essere > start_datetime")
    c = _check_assignment_conflict(db, new_rid, new_s, new_e, exclude_assignment_id=assignment_id)
    if c:
        raise HTTPException(409, f"Conflitto con assignment #{c.id}")
    a.resource_id = new_rid
    a.start_datetime = new_s
    a.end_datetime = new_e
    db.flush()
    _recalc_booking_envelope(a.booking)
    db.commit()
    return {
        "id": a.id, "booking_id": a.booking_id, "resource_id": a.resource_id,
        "start_datetime": a.start_datetime.isoformat(),
        "end_datetime": a.end_datetime.isoformat(),
    }


@router.delete("/api/booking-assignments/{assignment_id}")
async def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    """Cancella un singolo assignment. Se è l'ultimo del booking, cancella il booking intero."""
    a = db.query(BookingAssignment).join(Booking).filter(
        BookingAssignment.id == assignment_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not a:
        raise HTTPException(404, "Assignment non trovato")
    booking = a.booking
    db.delete(a)
    db.flush()
    db.refresh(booking)
    if not booking.assignments:
        booking.status = BookingStatus.cancelled
    else:
        _recalc_booking_envelope(booking)
    db.commit()
    return {"ok": True, "booking_cancelled": not bool(booking.assignments)}


@router.delete("/api/bookings/{booking_id}")
async def delete_booking(booking_id: int, db: Session = Depends(get_db)):
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    b.status = BookingStatus.cancelled
    _log_change(db, b.id, "delete", "Booking eliminato (soft)", None)
    db.commit()
    return {"ok": True}


@router.get("/api/suggest-resources")
async def suggest_resources(
    from_datetime: datetime,
    to_datetime: datetime,
    department_id: Optional[int] = None,
    type: Optional[ResourceType] = None,
    db: Session = Depends(get_db),
):
    """Suggerisce risorse libere nel range richiesto.
    Filtra eventualmente per reparto e tipo. Usato anche da AI auto-suggest (E6).
    """
    if to_datetime <= from_datetime:
        raise HTTPException(400, "to_datetime deve essere > from_datetime")
    q = db.query(Resource).filter(
        Resource.tenant_id == CURRENT_TENANT,
        Resource.is_active == True,
    )
    if department_id:
        q = q.filter(Resource.department_id == department_id)
    if type:
        q = q.filter(Resource.type == type)
    candidates = q.all()
    out_free, out_busy = [], []
    range_date_set = set()
    cur = from_datetime.date()
    while cur <= to_datetime.date():
        range_date_set.add(cur); cur += _td(days=1)
    for r in candidates:
        # Conflict booking
        conflict = db.query(BookingAssignment).join(Booking).filter(
            Booking.tenant_id == CURRENT_TENANT,
            Booking.status != BookingStatus.cancelled,
            BookingAssignment.resource_id == r.id,
            BookingAssignment.start_datetime < to_datetime,
            BookingAssignment.end_datetime > from_datetime,
        ).first()
        # Ferie/malattia overlap
        unav = db.query(ResourceUnavailability).filter(
            ResourceUnavailability.resource_id == r.id,
            ResourceUnavailability.end_date >= from_datetime.date(),
            ResourceUnavailability.start_date <= to_datetime.date(),
        ).first()
        info = {
            "id": r.id, "name": r.name, "role": r.role,
            "department_id": r.department_id, "color": r.color,
            "type": r.type.value if hasattr(r.type, "value") else r.type,
        }
        if conflict:
            info["conflict_assignment_id"] = conflict.id
            out_busy.append(info)
        elif unav:
            info["unavailability_kind"] = unav.kind.value if hasattr(unav.kind, "value") else unav.kind
            out_busy.append(info)
        else:
            out_free.append(info)
    return {"available": out_free, "busy": out_busy,
            "range": {"from": from_datetime.isoformat(), "to": to_datetime.isoformat()}}


@router.get("/api/bookings/{booking_id}/audit")
async def booking_audit_log(booking_id: int, db: Session = Depends(get_db)):
    """Cronologia modifiche al booking. Ordine: più recenti prima."""
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    rows = db.query(BookingChange).filter(
        BookingChange.booking_id == booking_id,
    ).order_by(BookingChange.created_at.desc()).all()
    return [
        {"id": r.id, "kind": r.kind, "summary": r.summary,
         "payload": r.payload or {}, "user_id": r.user_id,
         "created_at": r.created_at.isoformat()}
        for r in rows
    ]


# ── Ferie/malattie + festività auto (E3 v3.4.17) ──────────────────────

@router.get("/api/unavailabilities")
async def list_unavailabilities(
    from_date: Optional[_date] = None,
    to_date: Optional[_date] = None,
    resource_id: Optional[int] = None,
    include_holidays: bool = True,
    include_weekends: bool = True,
    db: Session = Depends(get_db),
):
    """Ritorna le fasce non lavorative per la timeline (background items).
    Combina:
      - ResourceUnavailability esplicite (vacation/sick/other)
      - Festività nazionali auto-derivate dalla policy (kind=holiday)
      - Weekend in base alla policy (kind=weekend, opzionale)
    """
    if not from_date:
        from_date = _date.today() - _td(days=30)
    if not to_date:
        to_date = _date.today() + _td(days=180)

    out = []
    # Ferie/malattie esplicite
    q = db.query(ResourceUnavailability).join(Resource).filter(
        Resource.tenant_id == CURRENT_TENANT,
        ResourceUnavailability.end_date >= from_date,
        ResourceUnavailability.start_date <= to_date,
    )
    if resource_id:
        q = q.filter(ResourceUnavailability.resource_id == resource_id)
    for u in q.all():
        out.append({
            "id": f"u{u.id}",
            "resource_id": u.resource_id,
            "start_date": u.start_date.isoformat(),
            "end_date": u.end_date.isoformat(),
            "kind": u.kind.value if hasattr(u.kind, "value") else u.kind,
            "reason": u.reason,
        })

    if include_holidays or include_weekends:
        # Per ogni risorsa filtrata (o tutte) genera festivi/weekend dalla sua policy
        resources_q = db.query(Resource).filter(
            Resource.tenant_id == CURRENT_TENANT,
            Resource.is_active == True,
        )
        if resource_id:
            resources_q = resources_q.filter(Resource.id == resource_id)
        all_res = resources_q.all()

        # Cache policy per ridurre query
        default_policy = db.query(WorkingHoursPolicy).filter(
            WorkingHoursPolicy.tenant_id == CURRENT_TENANT,
            WorkingHoursPolicy.is_default == True,
        ).first()
        policies_by_id = {default_policy.id: default_policy} if default_policy else {}
        for r in all_res:
            if r.working_hours_policy_id and r.working_hours_policy_id not in policies_by_id:
                p = db.query(WorkingHoursPolicy).filter(WorkingHoursPolicy.id == r.working_hours_policy_id).first()
                if p:
                    policies_by_id[p.id] = p

        # Holidays cache per country/year-range
        holidays_set = set()
        if include_holidays and default_policy and default_policy.holidays_country:
            from app.services.working_hours import get_holidays
            holidays_set = get_holidays(default_policy, from_date.year, to_date.year)

        # Per ogni risorsa, emit holidays + weekend come 1 entry per giorno (compatto: aggreghiamo run consecutivi)
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


@router.post("/api/unavailabilities")
async def create_unavailability(
    resource_id: int = Form(...),
    start_date: _date = Form(...),
    end_date: _date = Form(...),
    kind: UnavailabilityKind = Form(UnavailabilityKind.vacation),
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if end_date < start_date:
        raise HTTPException(400, "end_date deve essere >= start_date")
    u = ResourceUnavailability(
        resource_id=resource_id, start_date=start_date, end_date=end_date,
        kind=kind, reason=reason,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "resource_id": u.resource_id,
            "start_date": u.start_date.isoformat(), "end_date": u.end_date.isoformat(),
            "kind": u.kind.value if hasattr(u.kind, "value") else u.kind, "reason": u.reason}


@router.delete("/api/unavailabilities/{u_id}")
async def delete_unavailability(u_id: int, db: Session = Depends(get_db)):
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == CURRENT_TENANT,
    ).first()
    if not u:
        raise HTTPException(404, "Unavailability non trovata")
    db.delete(u)
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
    # Conflict check sul ripristino: ogni assignment vs altri booking attivi
    for a in b.assignments:
        c = _check_assignment_conflict(db, a.resource_id, a.start_datetime, a.end_datetime,
                                        exclude_assignment_id=a.id)
        if c:
            raise HTTPException(409, f"Conflitto al ripristino: assignment #{a.id} vs #{c.id}")
    b.status = BookingStatus.tentative
    _log_change(db, b.id, "restore", "Booking ripristinato", None)
    db.commit()
    return {"ok": True, "id": b.id}
