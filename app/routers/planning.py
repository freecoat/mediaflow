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
    BookingStatus, BookingKind, BookingExecutionStatus,
    Resource, ResourceType, JobCostLine, Department, User,
    WorkingHoursPolicy, ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
)
from datetime import date as _date, timedelta as _td
from app.services.auth import get_current_user_from_token
from app.services.rbac import is_elevated, scope_resource_id, current_user_optional

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

def _compute_job_progress(db: Session, job_id: int) -> dict:
    """v3.4.37 — Progresso job calcolato dai Booking.
    progress_pct = ore execution_status='done' / ore totali (escluse cancelled
    e not_done con count_in_costs=False). Ritorna 0 se nessun booking valido.
    """
    rows = (
        db.query(BookingAssignment, Booking)
        .join(Booking, BookingAssignment.booking_id == Booking.id)
        .filter(
            Booking.job_id == job_id,
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )
    done_h = 0.0
    total_h = 0.0
    for a, b in rows:
        if a.start_datetime and a.end_datetime and a.end_datetime > a.start_datetime:
            h = (a.end_datetime - a.start_datetime).total_seconds() / 3600.0
        else:
            continue
        # Salta pool not_done non conteggiato
        is_pool = (
            b.execution_status == BookingExecutionStatus.not_done and not b.count_in_costs
        )
        if is_pool:
            continue
        total_h += h
        if b.execution_status == BookingExecutionStatus.done:
            done_h += h
    pct = round((done_h / total_h * 100) if total_h > 0 else 0, 1)
    return {
        "progress_pct": pct,
        "done_hours": round(done_h, 2),
        "total_hours": round(total_h, 2),
    }


@router.get("/api/jobs/{job_id}/progress")
async def job_progress(job_id: int, db: Session = Depends(get_db)):
    """v3.4.37 — Avanzamento del job calcolato sui Booking."""
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job non trovato")
    return _compute_job_progress(db, job_id)


@router.get("/api/jobs")
async def list_jobs(
    status: Optional[JobStatus] = None,
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    department_id: Optional[int] = None,
    q: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_progress: bool = False,
    db: Session = Depends(get_db),
):
    """Lista job con filtri. Tenant filter implicito via project/client.
    `include_progress=true` aggrega le ore booking per ogni job (più lento).
    """
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
    out = []
    for j in jobs:
        row = {
            "id": j.id, "code": j.code, "title": j.title,
            "status": j.status.value if hasattr(j.status, "value") else j.status,
            "client_id": j.client_id,
            "client": j.client.name if j.client else None,
            "project_id": j.project_id,
            "project_code": j.project.code if j.project else None,
            "start_date": j.start_date, "end_date": j.end_date,
            "budget": j.budget_quoted,
        }
        if include_progress:
            row.update(_compute_job_progress(db, j.id))
        out.append(row)
    return out


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


# v3.4.38 (R3.4): FSM transizioni JobStatus. Matrice esplicita di
# transizioni legali. Una transizione non listata viene rifiutata con 400.
# `cancelled` può essere riportato a `approved` (riapertura), ma da `completed`/
# `invoiced` non si torna indietro (chiusura definitiva, salvo intervento DB).
JOB_STATUS_TRANSITIONS = {
    JobStatus.draft:     {JobStatus.quoting, JobStatus.approved, JobStatus.cancelled},
    JobStatus.quoting:   {JobStatus.draft, JobStatus.approved, JobStatus.cancelled},
    JobStatus.approved:  {JobStatus.active, JobStatus.on_hold, JobStatus.cancelled, JobStatus.completed},
    JobStatus.active:    {JobStatus.on_hold, JobStatus.completed, JobStatus.cancelled},
    JobStatus.on_hold:   {JobStatus.active, JobStatus.cancelled, JobStatus.completed},
    JobStatus.completed: {JobStatus.invoiced, JobStatus.active},  # active = riapertura
    JobStatus.invoiced:  set(),  # terminale: nessuna transizione admissible (solo via DB op)
    JobStatus.cancelled: {JobStatus.approved},  # riapertura legacy via quotes.py:40
}


@router.put("/api/jobs/{job_id}/status")
async def update_job_status(
    job_id: int,
    request: Request,
    status: JobStatus = Form(...),
    db: Session = Depends(get_db),
):
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job non trovato")
    # v3.4.38 (R3.4): valida transizione contro FSM
    current = j.status
    allowed = JOB_STATUS_TRANSITIONS.get(current, set())
    if status != current and status not in allowed:
        allowed_str = ", ".join(s.value for s in sorted(allowed, key=lambda x: x.value)) or "nessuna"
        raise HTTPException(
            400,
            f"Transizione non ammessa: {current.value} → {status.value}. "
            f"Da '{current.value}' sono consentite: {allowed_str}."
        )
    user = current_user_optional(request)
    j.status = status
    db.commit()
    print(f"[job_status] #{j.id} ({j.code}): {current.value} → {status.value} "
          f"by user_id={user.id if user else 'system'}")
    return {"id": j.id, "status": j.status.value}


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
                # v3.4.32 — booking esecutivo
                "priority": b.priority.value if hasattr(b.priority, "value") else (b.priority or "normal"),
                "execution_status": b.execution_status.value if hasattr(b.execution_status, "value") else (b.execution_status or "planned"),
                "overtime_status": b.overtime_status.value if hasattr(b.overtime_status, "value") else (b.overtime_status or "none"),
                "not_done_reason": b.not_done_reason,
                "count_in_costs": bool(b.count_in_costs),
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
            ResourceUnavailability.status == UnavailabilityStatus.approved,
        ).all()
        slots = split_booking_smart(pa["start_datetime"], pa["end_datetime"], policy, unavs)
        if not slots:
            # Range completamente fuori orario → niente da creare
            continue
        for sl in slots:
            out.append({"resource_id": rid, "start_datetime": sl.start, "end_datetime": sl.end})
    return out


def _enforce_planning_scope(request: Request, db: Session, resource_ids):
    """Per staff/viewer ammette solo booking sulla propria risorsa."""
    user = current_user_optional(request)
    if is_elevated(user):
        return
    own = scope_resource_id(db, user)
    if own is None:
        raise HTTPException(403, "Nessuna risorsa associata al tuo utente")
    for rid in resource_ids:
        if rid != own:
            raise HTTPException(403, "Puoi pianificare solo la tua risorsa")


@router.post("/api/bookings")
async def create_booking(
    request: Request,
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

    # RBAC: staff può creare booking solo per la propria risorsa
    _enforce_planning_scope(request, db, {pa["resource_id"] for pa in parsed_ass})

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
    request: Request,
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
    _enforce_planning_scope(request, db, {a.resource_id for a in b.assignments})

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
    request: Request,
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
    _enforce_planning_scope(request, db, {a.resource_id, new_rid})
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
    # v3.4.38 (R3.3): se booking aveva overtime_status=approved e ora il
    # nuovo end_datetime è dentro la fascia regolare (non più overtime),
    # resetto overtime_status=none e original_end_datetime=None — non c'è
    # più ragione di tracciare l'estensione storica.
    b_for_check = a.booking
    if b_for_check and b_for_check.overtime_status == BookingOvertimeStatus.approved:
        from app.services.booking_cost import has_overtime_window
        from app.services.working_hours import get_holidays
        from app.models import WorkingHoursPolicy
        res = a.resource
        if res:
            policy = res.working_hours_policy or db.query(WorkingHoursPolicy).filter(
                WorkingHoursPolicy.is_default == True  # noqa: E712
            ).first()
            if policy:
                hols = get_holidays(policy, a.start_datetime.year, a.end_datetime.year)
                still_overtime = any(
                    has_overtime_window(x.start_datetime, x.end_datetime, policy, hols)
                    for x in b_for_check.assignments
                )
                if not still_overtime:
                    b_for_check.overtime_status = BookingOvertimeStatus.none
                    b_for_check.original_end_datetime = None
                    _log_change(
                        db, b_for_check.id, "overtime_revert",
                        "Booking riportato in fascia regolare → overtime_status azzerato",
                        None,
                    )
    db.commit()

    # v3.4.32.1: dopo il drop, se l'assignment ora cade in fascia overtime
    # (fuori orario regolare, sabato/domenica, festivo) → flag overtime_pending
    # e notifica approvatori. Idempotente: non ri-notifica se già pending/approved.
    overtime_payload = _maybe_flag_overtime_on_assignment_change(a, request, db)

    out = {
        "id": a.id, "booking_id": a.booking_id, "resource_id": a.resource_id,
        "start_datetime": a.start_datetime.isoformat(),
        "end_datetime": a.end_datetime.isoformat(),
    }
    if overtime_payload:
        out.update(overtime_payload)
    return out


def _maybe_flag_overtime_on_assignment_change(
    a: BookingAssignment, request: Request, db: Session,
) -> Optional[dict]:
    """Verifica se l'assignment, dopo modifica, è ora in fascia overtime.
    Se sì e booking non è già pending/approved, marca overtime_status=pending
    e notifica gli approvatori. Ritorna info diagnostiche per il client."""
    from app.services.booking_cost import has_overtime_window
    from app.services.working_hours import get_holidays
    b = a.booking
    if not b:
        return None
    if b.overtime_status in (BookingOvertimeStatus.pending, BookingOvertimeStatus.approved):
        return {"overtime_status": b.overtime_status.value}

    res = a.resource
    if not res:
        return None
    policy = res.working_hours_policy or db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.is_default == True  # noqa: E712
    ).first()
    if not policy:
        return None
    holidays = get_holidays(policy, a.start_datetime.year, a.end_datetime.year)
    needs_ot = has_overtime_window(a.start_datetime, a.end_datetime, policy, holidays)
    # Verifica anche festivi/sabato/domenica
    from datetime import timedelta as _ttd
    cur = a.start_datetime.date()
    end_d = a.end_datetime.date()
    is_special = False
    while cur <= end_d:
        if cur.weekday() == 6 or cur in holidays:
            is_special = True
            break
        cur = cur + _ttd(days=1)
    if not (needs_ot or is_special):
        return None

    user = current_user_optional(request)
    # v3.4.32.2: auto-approve solo manager/admin (non producer). Vedi commento
    # in extend_booking per la motivazione governance.
    from app.services.rbac import is_manager, is_admin
    can_auto_approve = is_manager(user) or is_admin(user)
    if can_auto_approve:
        b.overtime_status = BookingOvertimeStatus.approved
        _log_change(db, b.id, "overtime_auto_approved",
                    "Auto-approvato: drop in fascia speciale + manager/admin",
                    {"by_user_id": user.id if user else None})
        db.commit()
        # Notifica info agli altri manager+admin per visibilità governance
        try:
            other_admins = [
                u.id for u in db.query(User).filter(User.is_active == True).all()  # noqa: E712
                if (is_manager(u) or is_admin(u)) and u.id != (user.id if user else -1)
            ]
            if other_admins:
                notif_svc.notify(
                    db,
                    user_ids=other_admins,
                    kind=NotificationKind.booking_overtime_resolved.value,
                    severity=NotificationSeverity.info.value,
                    title=f"ℹ Straordinario auto-approvato (drop): {_booking_short_label(b)}",
                    body=f"{user.full_name if user else '?'} ha spostato un booking in "
                         f"fascia speciale e l'ha auto-approvato.",
                    link=f"/jobs/{b.job_id}" if b.job_id else "/planning?view=jobs",
                    actor_user_id=user.id if user else None,
                    payload={"booking_id": b.id, "auto_approved": True},
                )
        except Exception as e:
            print(f"[overtime auto-approve drop] governance notify failed: {e}")
        return {"overtime_status": "approved", "auto_approved": True}

    b.overtime_status = BookingOvertimeStatus.pending
    _log_change(db, b.id, "overtime_pending",
                "Auto-flag pending: drop in fascia speciale (overtime/festivo/domenica)",
                None)
    db.commit()

    notified = 0
    try:
        approver_ids = _overtime_approver_ids(db, exclude=user.id if user else None)
        if approver_ids:
            ns = notif_svc.notify(
                db,
                user_ids=approver_ids,
                kind=NotificationKind.booking_overtime_pending.value,
                severity=NotificationSeverity.action_required.value,
                title=f"⚠ Straordinario da approvare: {_booking_short_label(b)}",
                body="Un booking è stato spostato in fascia straordinaria/festiva. "
                     "Approva o rifiuta dalla pagina del booking.",
                link=f"/jobs/{b.job_id}" if b.job_id else "/planning?view=jobs",
                actor_user_id=user.id if user else None,
                payload={"booking_id": b.id},
            )
            notified = len(ns)
    except Exception as e:
        print(f"[overtime auto-flag] notify failed: {e}")
    return {"overtime_status": "pending", "notified_count": notified}


@router.delete("/api/booking-assignments/{assignment_id}")
async def delete_assignment(assignment_id: int, request: Request, db: Session = Depends(get_db)):
    """Cancella un singolo assignment. Se è l'ultimo del booking, cancella il booking intero."""
    a = db.query(BookingAssignment).join(Booking).filter(
        BookingAssignment.id == assignment_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not a:
        raise HTTPException(404, "Assignment non trovato")
    _enforce_planning_scope(request, db, {a.resource_id})
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
async def delete_booking(booking_id: int, request: Request, db: Session = Depends(get_db)):
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    _enforce_planning_scope(request, db, {a.resource_id for a in b.assignments})
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
            ResourceUnavailability.status == UnavailabilityStatus.approved,
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
        # Solo approved blocca timeline. Pending = soft (non blocca, non mostriamo a non-elevated).
        if u.status != UnavailabilityStatus.approved:
            continue
        out.append({
            "id": f"u{u.id}",
            "resource_id": u.resource_id,
            "start_date": u.start_date.isoformat(),
            "end_date": u.end_date.isoformat(),
            "kind": u.kind.value if hasattr(u.kind, "value") else u.kind,
            "reason": u.reason,
            "status": u.status.value if hasattr(u.status, "value") else u.status,
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


def _u_dict(u: "ResourceUnavailability") -> dict:
    return {
        "id": u.id,
        "resource_id": u.resource_id,
        "resource_name": u.resource.name if u.resource else None,
        "start_date": u.start_date.isoformat(),
        "end_date": u.end_date.isoformat(),
        "kind": u.kind.value if hasattr(u.kind, "value") else u.kind,
        "reason": u.reason,
        "status": u.status.value if hasattr(u.status, "value") else u.status,
        "requested_by_user_id": u.requested_by_user_id,
        "approved_by_user_id": u.approved_by_user_id,
        "approved_at": u.approved_at.isoformat() if u.approved_at else None,
        "rejection_reason": u.rejection_reason,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("/api/my-unavailabilities")
async def list_my_unavailabilities(
    request: Request,
    from_date: Optional[_date] = None,
    to_date: Optional[_date] = None,
    db: Session = Depends(get_db),
):
    """Lista ferie/malattie della risorsa associata all'utente loggato (tutti gli status).

    Usata dalla vista "Le mie" del planning per mostrare le proprie richieste
    con il loro stato (pending/approved/rejected).
    """
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Non autenticato")
    own = scope_resource_id(db, user)
    if own is None:
        return []
    q = db.query(ResourceUnavailability).filter(
        ResourceUnavailability.resource_id == own,
    )
    if from_date:
        q = q.filter(ResourceUnavailability.end_date >= from_date)
    if to_date:
        q = q.filter(ResourceUnavailability.start_date <= to_date)
    items = q.order_by(ResourceUnavailability.start_date.desc()).all()
    return [_u_dict(u) for u in items]


@router.post("/api/unavailabilities")
async def create_unavailability(
    request: Request,
    resource_id: int = Form(...),
    start_date: _date = Form(...),
    end_date: _date = Form(...),
    kind: UnavailabilityKind = Form(UnavailabilityKind.vacation),
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea una richiesta di ferie/malattia/permesso.

    - Staff/viewer: scope forzato sulla propria risorsa, status=pending
    - Admin/manager/producer: può creare per qualsiasi risorsa, status=approved
      di default (saltano il workflow visto che sono già autorizzati).
    """
    from app.services.rbac import is_elevated, current_user_optional, scope_resource_id
    user = current_user_optional(request)
    if end_date < start_date:
        raise HTTPException(400, "end_date deve essere >= start_date")

    if not is_elevated(user):
        own = scope_resource_id(db, user)
        if own is None:
            raise HTTPException(403, "Nessuna risorsa associata al tuo utente")
        if resource_id != own:
            raise HTTPException(403, "Puoi richiedere ferie solo per la tua risorsa")
        status = UnavailabilityStatus.pending
    else:
        status = UnavailabilityStatus.approved

    u = ResourceUnavailability(
        resource_id=resource_id, start_date=start_date, end_date=end_date,
        kind=kind, reason=reason,
        status=status,
        requested_by_user_id=user.id if user else None,
        approved_by_user_id=user.id if (user and is_elevated(user)) else None,
        approved_at=datetime.utcnow() if status == UnavailabilityStatus.approved else None,
    )
    db.add(u)
    db.commit()
    db.refresh(u)

    # v3.4.27: notify managers se la richiesta è pending
    if status == UnavailabilityStatus.pending:
        from app.services import notifications as notif_svc
        kind_lbl = {"vacation": "Ferie", "sick": "Malattia", "other": "Permesso"}.get(
            kind.value if hasattr(kind, "value") else str(kind), "Richiesta"
        )
        resource_name = u.resource.name if u.resource else f"risorsa #{resource_id}"
        notif_svc.notify_permission(
            db,
            permission="approve_unavailability",
            exclude_user_ids=[user.id] if user else None,
            kind="unavailability_pending",
            severity="action_required",
            title=f"{kind_lbl} da approvare — {resource_name}",
            body=f"{start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}" + (f" · {reason}" if reason else ""),
            link="/hr/",
            payload={"unavailability_id": u.id, "resource_id": resource_id, "kind": kind.value if hasattr(kind, "value") else str(kind)},
            actor_user_id=user.id if user else None,
        )
    return _u_dict(u)


@router.get("/api/unavailabilities/pending")
async def list_pending_unavailabilities(
    request: Request,
    db: Session = Depends(get_db),
):
    """Lista richieste in attesa di approvazione (admin/manager/producer)."""
    from app.services.rbac import can_approve_unavailability, current_user_optional
    user = current_user_optional(request)
    if not can_approve_unavailability(user):
        raise HTTPException(403, "Solo manager/producer/admin possono visualizzare le richieste pendenti")
    items = (
        db.query(ResourceUnavailability)
        .join(Resource, ResourceUnavailability.resource_id == Resource.id)
        .filter(
            Resource.tenant_id == CURRENT_TENANT,
            ResourceUnavailability.status == UnavailabilityStatus.pending,
        )
        .order_by(ResourceUnavailability.created_at.desc())
        .all()
    )
    return [_u_dict(u) for u in items]


@router.post("/api/unavailabilities/{u_id}/approve")
async def approve_unavailability(
    u_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from app.services.rbac import can_approve_unavailability, current_user_optional
    user = current_user_optional(request)
    if not can_approve_unavailability(user):
        raise HTTPException(403, "Permesso negato")
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == CURRENT_TENANT,
    ).first()
    if not u:
        raise HTTPException(404, "Richiesta non trovata")
    u.status = UnavailabilityStatus.approved
    u.approved_by_user_id = user.id
    u.approved_at = datetime.utcnow()
    u.rejection_reason = None
    db.commit()
    db.refresh(u)

    # v3.4.27: notify il richiedente
    if u.requested_by_user_id and u.requested_by_user_id != user.id:
        from app.services import notifications as notif_svc
        kind_lbl = {"vacation": "Ferie", "sick": "Malattia", "other": "Permesso"}.get(
            u.kind.value if hasattr(u.kind, "value") else str(u.kind), "Richiesta"
        )
        notif_svc.notify(
            db,
            user_ids=[u.requested_by_user_id],
            kind="unavailability_approved",
            severity="info",
            title=f"{kind_lbl} approvata",
            body=f"{u.start_date.strftime('%d/%m/%Y')} → {u.end_date.strftime('%d/%m/%Y')}",
            link="/hr/",
            payload={"unavailability_id": u.id},
            actor_user_id=user.id,
        )
    return _u_dict(u)


@router.post("/api/unavailabilities/{u_id}/reject")
async def reject_unavailability(
    u_id: int,
    request: Request,
    rejection_reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    from app.services.rbac import can_approve_unavailability, current_user_optional
    user = current_user_optional(request)
    if not can_approve_unavailability(user):
        raise HTTPException(403, "Permesso negato")
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == CURRENT_TENANT,
    ).first()
    if not u:
        raise HTTPException(404, "Richiesta non trovata")
    u.status = UnavailabilityStatus.rejected
    u.approved_by_user_id = user.id
    u.approved_at = datetime.utcnow()
    u.rejection_reason = rejection_reason
    db.commit()
    db.refresh(u)

    # v3.4.27: notify il richiedente
    if u.requested_by_user_id and u.requested_by_user_id != user.id:
        from app.services import notifications as notif_svc
        kind_lbl = {"vacation": "Ferie", "sick": "Malattia", "other": "Permesso"}.get(
            u.kind.value if hasattr(u.kind, "value") else str(u.kind), "Richiesta"
        )
        notif_svc.notify(
            db,
            user_ids=[u.requested_by_user_id],
            kind="unavailability_rejected",
            severity="action_required",
            title=f"{kind_lbl} rifiutata",
            body=(rejection_reason or "Nessun motivo specificato") + f" · {u.start_date.strftime('%d/%m/%Y')} → {u.end_date.strftime('%d/%m/%Y')}",
            link="/hr/",
            payload={"unavailability_id": u.id, "rejection_reason": rejection_reason},
            actor_user_id=user.id,
        )
    return _u_dict(u)


@router.delete("/api/unavailabilities/{u_id}")
async def delete_unavailability(u_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services.rbac import is_elevated, current_user_optional, scope_resource_id
    user = current_user_optional(request)
    u = db.query(ResourceUnavailability).join(Resource).filter(
        ResourceUnavailability.id == u_id,
        Resource.tenant_id == CURRENT_TENANT,
    ).first()
    if not u:
        raise HTTPException(404, "Unavailability non trovata")
    # Staff può cancellare solo le proprie richieste in pending
    if not is_elevated(user):
        own = scope_resource_id(db, user)
        if u.resource_id != own:
            raise HTTPException(403, "Permesso negato")
        if u.status != UnavailabilityStatus.pending:
            raise HTTPException(403, "Solo richieste pending possono essere cancellate dall'utente")
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


# ── Booking esecutivo (v3.4.32) ─────────────────────────────────────
# Cambio priorità, cambio stato esecuzione (planned/in_progress/done/not_done),
# estensione durata adattiva con cascade + detection overtime, approvazione
# overtime con split-su-rifiuto.

from app.models import (
    BookingPriority, BookingExecutionStatus, BookingOvertimeStatus,
    NotificationKind, NotificationSeverity,
)
from app.services import notifications as notif_svc
from app.services.booking_cascade import (
    extend_booking_adaptive, split_overtime_to_next_day,
)
from app.services.rbac import has_permission


def _booking_short_label(b: Booking) -> str:
    """Etichetta breve per titoli notifica."""
    parts = []
    if b.job and b.job.code:
        parts.append(b.job.code)
    if b.cost_line and b.cost_line.description:
        parts.append(b.cost_line.description)
    if not parts:
        parts.append(f"#{b.id}")
    when = b.start_datetime.strftime("%d/%m %H:%M") if b.start_datetime else ""
    return " · ".join(parts) + (f" — {when}" if when else "")


def _can_edit_booking_execution(request: Request, db: Session, booking: Booking) -> bool:
    """Operatore può cambiare stato dei suoi booking; manager/producer/admin
    di tutti."""
    user = current_user_optional(request)
    if is_elevated(user):
        return True
    own = scope_resource_id(db, user)
    if own is None:
        return False
    return any(a.resource_id == own for a in booking.assignments)


@router.patch("/api/bookings/{booking_id}/priority")
async def update_booking_priority(
    booking_id: int,
    request: Request,
    priority: BookingPriority = Form(...),
    db: Session = Depends(get_db),
):
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    _enforce_planning_scope(request, db, {a.resource_id for a in b.assignments})
    old = b.priority.value if hasattr(b.priority, "value") else (b.priority or "normal")
    b.priority = priority
    _log_change(db, b.id, "priority", f"Priorità {old} → {priority.value}",
                {"old": old, "new": priority.value})
    db.commit()
    return {"id": b.id, "priority": priority.value}


@router.patch("/api/bookings/{booking_id}/execution")
async def update_booking_execution(
    booking_id: int,
    request: Request,
    execution_status: BookingExecutionStatus = Form(...),
    not_done_reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Cambio stato esecuzione del booking. Su not_done richiede motivazione.
    Su transizione → done o → not_done emette notifica a producer/manager.
    Su → in_progress: silenzio (rumore)."""
    b = db.query(Booking).options(joinedload(Booking.job)).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    if not _can_edit_booking_execution(request, db, b):
        raise HTTPException(403, "Non puoi modificare lo stato di questo booking")
    if execution_status == BookingExecutionStatus.not_done and not (not_done_reason or "").strip():
        raise HTTPException(400, "Motivazione obbligatoria per stato 'Non fatto'")

    user = current_user_optional(request)
    old_status = b.execution_status
    b.execution_status = execution_status
    if execution_status == BookingExecutionStatus.not_done:
        b.not_done_reason = (not_done_reason or "").strip()
    else:
        b.not_done_reason = None
        # v3.4.38 (R3.1): invariante count_in_costs ↔ execution_status.
        # count_in_costs ha senso SOLO con execution_status=not_done (pool).
        # Se torno a planned/in_progress/done, il flag va resettato a False
        # (le ore tornano nel calcolo standard del cost report).
        if b.count_in_costs:
            b.count_in_costs = False

    summary_text = (
        f"Esecuzione: {old_status.value if hasattr(old_status, 'value') else old_status}"
        f" → {execution_status.value}"
    )
    _log_change(db, b.id, "execution", summary_text,
                {"old": old_status.value if hasattr(old_status, "value") else old_status,
                 "new": execution_status.value,
                 "not_done_reason": b.not_done_reason})
    # v3.4.41: sync JobCostLine.quantity_actual + total_accrued. Ogni
    # cambio di stato esecuzione di/da `done` ricomputa l'aggregato dai
    # booking done della cost line associata. Idempotente.
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as e:
        print(f"[update_booking_execution] cost line sync failed: {e}")
    db.commit()
    db.refresh(b)

    # Notifiche selettive
    if execution_status in (BookingExecutionStatus.done, BookingExecutionStatus.not_done):
        is_not_done = (execution_status == BookingExecutionStatus.not_done)
        title = (
            f"❌ Booking non fatto: {_booking_short_label(b)}"
            if is_not_done
            else f"✅ Booking completato: {_booking_short_label(b)}"
        )
        body = (
            f"Motivazione: {b.not_done_reason}"
            if is_not_done and b.not_done_reason else None
        )
        link = f"/jobs/{b.job_id}" if b.job_id else "/planning?view=jobs"
        try:
            notif_svc.notify_role(
                db,
                role_codes=["producer", "manager", "admin"],
                exclude_user_ids=[user.id] if user else None,
                kind=NotificationKind.booking_status_changed.value,
                severity=(
                    NotificationSeverity.action_required.value
                    if is_not_done
                    else NotificationSeverity.info.value
                ),
                title=title,
                body=body,
                link=link,
                actor_user_id=user.id if user else None,
                payload={
                    "booking_id": b.id, "execution_status": execution_status.value,
                    "not_done_reason": b.not_done_reason,
                },
            )
        except Exception as e:
            print(f"[booking_execution] notify failed: {e}")

    return {
        "id": b.id,
        "execution_status": execution_status.value,
        "not_done_reason": b.not_done_reason,
    }


@router.patch("/api/bookings/{booking_id}/extend")
async def extend_booking(
    booking_id: int,
    request: Request,
    delta_minutes: int = Form(...),
    db: Session = Depends(get_db),
):
    """Estensione adattiva: cascade sui booking adiacenti dello stesso giorno
    (stessa risorsa). Se il cascade fa entrare uno o più booking in fascia
    overtime, quelli vengono marcati `overtime_status=pending` e gli
    approvatori (permesso approve_overtime) ricevono notifica."""
    b = db.query(Booking).options(
        joinedload(Booking.assignments).joinedload(BookingAssignment.resource),
        joinedload(Booking.job),
    ).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")

    # v3.4.32.1: l'operatore membro del booking può estendere anche se ci sono
    # altre risorse coinvolte. In quel caso il cascade è ristretto alla sua
    # risorsa (non spinge i booking dei colleghi).
    user = current_user_optional(request)
    own_rid = scope_resource_id(db, user)
    restrict_cascade = None
    if not is_elevated(user):
        if own_rid is None:
            raise HTTPException(403, "Nessuna risorsa associata al tuo utente")
        booking_resource_ids = {a.resource_id for a in b.assignments}
        if own_rid not in booking_resource_ids:
            raise HTTPException(403, "Puoi modificare solo booking in cui sei assegnato")
        if len(booking_resource_ids) > 1:
            restrict_cascade = own_rid

    if abs(delta_minutes) < 1:
        raise HTTPException(400, "delta_minutes troppo piccolo")
    if abs(delta_minutes) > 24 * 60:
        raise HTTPException(400, "delta_minutes oltre 24 ore non ammesso")

    result = extend_booking_adaptive(b, delta_minutes, db,
                                      restrict_cascade_to_resource_id=restrict_cascade)
    if result.rejected:
        raise HTTPException(409, result.reject_reason or "Estensione rifiutata")

    # v3.4.32.2: auto-approve è ammesso SOLO per manager+admin (non producer).
    # Producer ha permesso `approve_overtime` ma estendendo va sempre in pending
    # → dev'essere il manager a confermare. Questo riflette la decisione
    # governance: "approvazione straordinari deve darla il manager".
    from app.services.rbac import is_manager, is_admin
    can_auto_approve = is_manager(user) or is_admin(user)
    auto_approved_ids: list[int] = []
    if can_auto_approve and result.overtime_pending_booking_ids:
        for bid in result.overtime_pending_booking_ids:
            bk = db.query(Booking).filter(Booking.id == bid).first()
            if bk and bk.overtime_status == BookingOvertimeStatus.pending:
                bk.overtime_status = BookingOvertimeStatus.approved
                _log_change(db, bk.id, "overtime_auto_approved",
                            f"Auto-approvato da {user.full_name if user else '?'} "
                            "(manager/admin con approve_overtime)",
                            {"by_user_id": user.id if user else None})
                auto_approved_ids.append(bid)
        db.commit()
        # Notifica info agli ALTRI manager+admin per visibilità governance
        # (severity=info, no action_required: è solo per audit/awareness).
        try:
            other_admins = [
                u.id for u in db.query(User).filter(User.is_active == True).all()  # noqa: E712
                if (is_manager(u) or is_admin(u)) and u.id != (user.id if user else -1)
            ]
            if other_admins and auto_approved_ids:
                for bid in auto_approved_ids:
                    bk = db.query(Booking).options(joinedload(Booking.job)).filter(Booking.id == bid).first()
                    if not bk:
                        continue
                    notif_svc.notify(
                        db,
                        user_ids=other_admins,
                        kind=NotificationKind.booking_overtime_resolved.value,
                        severity=NotificationSeverity.info.value,
                        title=f"ℹ Straordinario auto-approvato: {_booking_short_label(bk)}",
                        body=f"{user.full_name if user else '?'} ha esteso un booking in fascia "
                             f"straordinaria e l'ha auto-approvato.",
                        link=f"/jobs/{bk.job_id}" if bk.job_id else "/planning?view=jobs",
                        actor_user_id=user.id if user else None,
                        payload={"booking_id": bk.id, "auto_approved": True},
                    )
        except Exception as e:
            print(f"[extend_booking] governance notify failed: {e}")

    # Notifiche overtime per i booking ancora in pending (NON auto-approvati)
    pending_to_notify = [bid for bid in result.overtime_pending_booking_ids
                         if bid not in auto_approved_ids]
    notified_count = 0
    for bid in pending_to_notify:
        bk = db.query(Booking).options(joinedload(Booking.job)).filter(Booking.id == bid).first()
        if not bk:
            continue
        try:
            target_user_ids = _overtime_approver_ids(db, exclude=user.id if user else None)
            if not target_user_ids:
                # Nessun altro approvatore disponibile → resta pending. Log avvertenza.
                print(f"[extend_booking] overtime pending #{bk.id}: nessun approvatore diverso da chi ha esteso")
                continue
            ns = notif_svc.notify(
                db,
                user_ids=target_user_ids,
                kind=NotificationKind.booking_overtime_pending.value,
                severity=NotificationSeverity.action_required.value,
                title=f"⚠ Straordinario da approvare: {_booking_short_label(bk)}",
                body=(
                    "Un booking è stato esteso (cascade adattivo) ed è ora in fascia "
                    "straordinaria. Approva o rifiuta dalla pagina del booking."
                ),
                link=f"/jobs/{bk.job_id}" if bk.job_id else "/planning?view=jobs",
                actor_user_id=user.id if user else None,
                payload={"booking_id": bk.id},
            )
            notified_count += len(ns)
        except Exception as e:
            print(f"[extend_booking] notify overtime failed: {e}")

    # v3.4.41: se il booking esteso era già done, ricomputa la JobCostLine
    # actual (la durata cambiata cambia le ore "fatte"). Idempotente.
    try:
        from app.services.cost_line_sync import recompute_for_booking
        affected_ids = list(set(
            [b.id] + list(result.overtime_pending_booking_ids or [])
        ))
        for bid in affected_ids:
            bk = db.query(Booking).filter(Booking.id == bid).first()
            if bk and bk.execution_status == BookingExecutionStatus.done:
                recompute_for_booking(db, bk)
        db.commit()
    except Exception as e:
        print(f"[extend_booking] cost line sync failed: {e}")

    payload = result.as_dict()
    payload["overtime_auto_approved_ids"] = auto_approved_ids
    payload["overtime_notified_count"] = notified_count
    return payload


def _overtime_approver_ids(db: Session, exclude: Optional[int] = None) -> list[int]:
    """Ritorna user_id di chi può approvare overtime (permesso approve_overtime)."""
    users = db.query(User).filter(User.is_active == True).all()  # noqa: E712
    return [u.id for u in users
            if has_permission(u, "approve_overtime") and u.id != exclude]


@router.post("/api/bookings/{booking_id}/overtime")
async def decide_booking_overtime(
    booking_id: int,
    request: Request,
    decision: str = Form(...),  # "approved" | "rejected"
    reason: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Decisione approvatore overtime. Su rifiuto: split del booking → la parte
    overtime diventa nuovo booking il giorno successivo (D1)."""
    b = db.query(Booking).options(
        joinedload(Booking.assignments).joinedload(BookingAssignment.resource),
        joinedload(Booking.job),
    ).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    user = current_user_optional(request)
    if not has_permission(user, "approve_overtime"):
        raise HTTPException(403, "Non hai il permesso di approvare straordinari")
    if b.overtime_status != BookingOvertimeStatus.pending:
        raise HTTPException(409, "Booking non in attesa di approvazione overtime")

    decision = (decision or "").lower().strip()
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision deve essere 'approved' o 'rejected'")

    new_booking_id: Optional[int] = None
    if decision == "approved":
        b.overtime_status = BookingOvertimeStatus.approved
        _log_change(db, b.id, "overtime_approved",
                    "Straordinario approvato",
                    {"by_user_id": user.id if user else None, "reason": reason})
        db.commit()
    else:
        # Split: la parte regolare resta, la parte overtime → nuovo booking domani
        b.overtime_status = BookingOvertimeStatus.rejected
        _log_change(db, b.id, "overtime_rejected",
                    "Straordinario rifiutato — split al giorno successivo",
                    {"by_user_id": user.id if user else None, "reason": reason})
        db.commit()
        db.refresh(b)
        new_booking = split_overtime_to_next_day(b, db)
        if new_booking:
            new_booking_id = new_booking.id

    # Notifica all'operatore (assegnatari) del booking
    try:
        operator_user_ids = []
        for a in b.assignments:
            if a.resource and a.resource.user_id:
                operator_user_ids.append(a.resource.user_id)
        if operator_user_ids:
            outcome = "approvato" if decision == "approved" else "rifiutato"
            extra = ""
            if new_booking_id:
                extra = f" — è stato creato un nuovo booking il giorno successivo (#{new_booking_id})"
            notif_svc.notify(
                db,
                user_ids=operator_user_ids,
                kind=NotificationKind.booking_overtime_resolved.value,
                severity=NotificationSeverity.info.value,
                title=f"Straordinario {outcome}: {_booking_short_label(b)}",
                body=(reason or "") + extra,
                link=f"/jobs/{b.job_id}" if b.job_id else "/planning?view=jobs",
                actor_user_id=user.id if user else None,
                payload={"booking_id": b.id, "decision": decision,
                         "new_booking_id": new_booking_id},
            )
    except Exception as e:
        print(f"[decide_overtime] notify operator failed: {e}")

    return {
        "id": b.id,
        "overtime_status": b.overtime_status.value,
        "new_booking_id": new_booking_id,
    }


@router.patch("/api/bookings/{booking_id}/count-in-costs")
async def update_booking_count_in_costs(
    booking_id: int,
    request: Request,
    count_in_costs: bool = Form(...),
    db: Session = Depends(get_db),
):
    """Manager/producer decide se un booking not_done conta comunque nei costi
    (pool not_done → recuperate). Cambia solo il flag count_in_costs.
    Permesso: edit_planning_all."""
    user = current_user_optional(request)
    if not has_permission(user, "edit_planning_all"):
        raise HTTPException(403, "Solo manager/producer possono gestire il pool not_done")
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    # v3.4.38 (R3.1): invariante. count_in_costs True ha senso SOLO se il
    # booking è in stato not_done (pool ore non maturate ma da contare).
    if count_in_costs and b.execution_status != BookingExecutionStatus.not_done:
        raise HTTPException(
            400,
            "Il flag 'conta nei costi' è applicabile solo a booking in stato "
            "'Non fatto' (pool not_done). Cambia prima lo stato esecuzione."
        )
    b.count_in_costs = bool(count_in_costs)
    _log_change(db, b.id, "count_in_costs",
                f"Pool not_done: count_in_costs → {b.count_in_costs}",
                {"count_in_costs": b.count_in_costs})
    db.commit()
    return {"id": b.id, "count_in_costs": b.count_in_costs}


# ── Endpoint "Le mie" arricchito (v3.4.32) ──────────────────────────
# Restituisce solo i booking dell'utente loggato con tutto il contesto
# necessario per la card interattiva (priority/execution_status/overtime/...).

@router.get("/api/my-bookings")
async def my_bookings(
    request: Request,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    today_only: bool = False,
    db: Session = Depends(get_db),
):
    """Booking dell'utente loggato (via Resource collegata).

    Restituisce dati arricchiti (priority/execution_status/overtime_status/notes/job)
    pronti per la card "Le mie" e per la dashboard "I miei booking di oggi".
    """
    user = current_user_optional(request)
    rid = scope_resource_id(db, user)
    if rid is None:
        return []
    if today_only:
        from datetime import date as _d, datetime as _dt
        d = _d.today()
        from_date = _dt.combine(d, datetime.min.time())
        to_date = _dt.combine(d, datetime.max.time())

    q = db.query(BookingAssignment).options(
        joinedload(BookingAssignment.resource),
        joinedload(BookingAssignment.booking).joinedload(Booking.job),
        joinedload(BookingAssignment.booking).joinedload(Booking.cost_line),
    ).join(Booking, BookingAssignment.booking_id == Booking.id).filter(
        Booking.tenant_id == CURRENT_TENANT,
        BookingAssignment.resource_id == rid,
        Booking.status != BookingStatus.cancelled,
    )
    if from_date:
        q = q.filter(BookingAssignment.end_datetime >= from_date)
    if to_date:
        q = q.filter(BookingAssignment.start_datetime <= to_date)
    rows = q.order_by(BookingAssignment.start_datetime.asc()).all()

    out = []
    for a in rows:
        b = a.booking
        out.append({
            "assignment_id": a.id,
            "booking_id": b.id,
            "title": _booking_title_for_assignment(b, a.resource.name if a.resource else "?"),
            "start": a.start_datetime.isoformat(),
            "end": a.end_datetime.isoformat(),
            "duration_minutes": int(round((a.end_datetime - a.start_datetime).total_seconds() / 60)),
            "job_id": b.job_id,
            "job_code": b.job.code if b.job else None,
            "job_title": b.job.title if b.job else None,
            "cost_line_description": b.cost_line.description if b.cost_line else None,
            "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
            "status": b.status.value if hasattr(b.status, "value") else b.status,
            "priority": b.priority.value if hasattr(b.priority, "value") else (b.priority or "normal"),
            "execution_status": b.execution_status.value if hasattr(b.execution_status, "value") else (b.execution_status or "planned"),
            "overtime_status": b.overtime_status.value if hasattr(b.overtime_status, "value") else (b.overtime_status or "none"),
            "not_done_reason": b.not_done_reason,
            "notes": b.notes,
        })
    return out
