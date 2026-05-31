"""Router pianificazione — hub viste + job, clienti, booking."""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from app.database import get_db
from app.models import (
    Job, JobStatus, Client, Project, Booking, BookingAssignment, BookingChange,
    BookingStatus, BookingKind, BookingExecutionStatus, BookingPriority, BookingState,
    Resource, ResourceType, JobCostLine, Department, User,
    WorkingHoursPolicy, ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
    ResourcePreset, TimePunch, PunchKind,
)


def _parse_priority(value):
    """v3.5.0-alpha.22: parse `priority` form param → BookingPriority enum.
    None / valore invalido → normal (default). Casefold-tolerant."""
    if value is None:
        return BookingPriority.normal
    v = str(value).strip().lower()
    if v == "low":
        return BookingPriority.low
    if v == "high":
        return BookingPriority.high
    return BookingPriority.normal
from datetime import date as _date, timedelta as _td
from app.services.auth import get_current_user_from_token
from app.services.rbac import is_elevated, scope_resource_id, current_user_optional, requires_permission
from app.services.tenant_guard import scoped, fetch_or_404

# v3.5.0-alpha.66.16.0 — Sprint R3: gate per i 4 mutator planning senza
# protezione (audit HIGH #4). Endpoint duplicati di clients/jobs (CRUD)
# qui chiusi finché non rimossi (refactor R7); job status FSM e restore
# booking ricevono permessi specifici.
RequireEditClients = Depends(requires_permission("edit_clients"))
RequireEditPlanningAll = Depends(requires_permission("edit_planning_all"))

router = APIRouter(prefix="/planning", tags=["planning"])



def _gate_force_unlock(request: Request, force: bool) -> bool:
    """v3.5.0-alpha.111.23 — Solo admin può forzare sblocco slice billed.
    Ritorna `force` validato. Solleva 403 se non-admin tenta force=True.
    """
    if not force:
        return False
    from app.services.rbac import current_user_optional, is_admin
    user = current_user_optional(request)
    if not is_admin(user):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ADMIN_REQUIRED_FOR_UNLOCK",
                "message": (
                    "Solo amministratore può sbloccare booking di periodi "
                    "già fatturati. Contattare admin."
                ),
            },
        )
    return True


async def _force_unlock_dep(
    request: Request,
    force_slice_unlock: bool = Form(False),
) -> bool:
    """FastAPI dependency: parses force_slice_unlock Form + applies admin gate.
    Sostituisce `force_slice_unlock: bool = Form(False)` nei mutator
    booking. Trasparente all'utente: se force_slice_unlock=False (default)
    nessun cambio. Se True senza admin → 403 con code ADMIN_REQUIRED_FOR_UNLOCK.
    """
    return _gate_force_unlock(request, force_slice_unlock)


def _assert_no_blocking_slice(db: Session, b: Booking, *, force: bool = False) -> None:
    """v3.5.0-alpha.59 — HARD-BLOCK 409 se il booking ricade in un periodo
    già fatturato (esiste una `JCLBilledSlice` la cui finestra si sovrappone
    all'envelope del booking).

    v3.5.0-alpha.66.3 — Relax semantico:
    - `b.status == tentative` → SKIP guard. I booking tentative non sono
      "consolidati" e possono essere mossi liberamente anche dentro periodi
      fatturati (rappresentano ipotesi di pianificazione, non lavoro
      maturato).
    - `b.status == confirmed` (o cancelled, raro) → guard attivo, 409 con
      `code=SLICE_LOCK_CONFIRM_REQUIRED`. Il client può intercettare e
      ri-inviare con `force=True` Form param dopo aver ottenuto conferma
      esplicita dall'utente. La fattura emessa resta inalterata: il rischio
      è la divergenza `total_accrued` ↔ `billed_amount` storico, e l'utente
      lo accetta consapevolmente.
    - `force=True` → SKIP guard (override esplicito post-conferma).

    v3.5.0-alpha.66.16.3 — Internamente usa booking_mutate.assert_slice_lock_safe
    (sprint R4). Mantiene API esterna invariata + tentative-bypass + 409 con
    code=SLICE_LOCK_CONFIRM_REQUIRED.

    Idempotente: se non c'è JCL collegata, no-op."""
    if b.status == BookingStatus.tentative:
        return
    from app.services.booking_mutate import assert_slice_lock_safe, SliceLocked
    try:
        assert_slice_lock_safe(db, b, force_unlock=force)
    except SliceLocked as e:
        detail = {
            "code": "SLICE_LOCK_CONFIRM_REQUIRED",
            "message": e.message,
            "slice": e.payload,
            "hint": "Booking confermato in periodo fatturato. Riinvia con "
                    "`force_slice_unlock=true` per forzare la modifica.",
        }
        raise HTTPException(409, detail=detail)


def _assert_no_blocking_slice_for_dates(
    db: Session, b: Booking, new_start: date, new_end: date,
    *, force: bool = False,
) -> None:
    """v3.5.0-alpha.66.16.3 — Variante per check NEW dates (move/resize).

    Sostituisce 2 blocchi inline (linee ~1957 update_assignment, ~2736
    multi-move) che richiamavano `find_blocking_slice_for_dates` + manuale
    HTTPException 409. Stessa policy di `_assert_no_blocking_slice` ma
    sulla posizione PROPOSTA (not current).

    Tentative bypass: stesso comportamento (booking tentative liberamente
    spostabili anche dentro slice billed)."""
    if b.status == BookingStatus.tentative:
        return
    from app.services.booking_mutate import assert_slice_lock_safe, SliceLocked
    try:
        assert_slice_lock_safe(db, b, new_dates=(new_start, new_end), force_unlock=force)
    except SliceLocked as e:
        detail = {
            "code": "SLICE_LOCK_CONFIRM_REQUIRED",
            "message": e.message + " — la nuova posizione del booking ricade in periodo già fatturato.",
            "slice": e.payload,
            "hint": "Riinvia con `force_slice_unlock=true` per forzare la modifica.",
        }
        raise HTTPException(409, detail=detail)


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ───────────────────────────────────────────────────────

VALID_VIEWS = ("jobs", "calendar", "agenda", "todo", "project", "storyboard", "timeline")


# v3.5.0-alpha.66.14.2: alias verso il singleton in app.services.auth.
# La logica fail-closed (settings.auth_required=True → no fallback) vive lì.
from app.services.auth import resolve_current_user as _resolve_current_user  # noqa: E402,F401


@router.get("/", response_class=HTMLResponse)
async def planning_hub(
    request: Request,
    view: str = "jobs",
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    return await _planning_render(request, view, access_token, db, full_screen=False)


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_redirect():
    """Compat v3.4.10−: ora il calendario è una vista dell'hub."""
    return RedirectResponse(url="/planning/?view=calendar", status_code=302)


@router.get("/full", response_class=HTMLResponse)
async def planning_full_screen(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.44: pagina standalone full-screen della timeline.

    Nasconde sidebar + topbar globali (via flag `full_screen=True` interpretato
    da `base.html`) per dedicare tutta la viewport alla timeline. Forza la
    vista a `timeline`. Pensata per essere aperta in popup/tab dedicato dal
    bottone "⛶ Finestra" in toolbar planning, su monitor grandi e per workflow
    planning intensivo.

    Riusa lo stesso template `pages/planning.html` per evitare duplicazione.
    L'auth e tutti i dati di context sono identici a `planning_hub`.
    """
    return await _planning_render(request, "timeline", access_token, db, full_screen=True)


async def _planning_render(
    request: Request,
    view: str,
    access_token: Optional[str],
    db: Session,
    full_screen: bool = False,
):
    """Helper privato per condividere la logica di context tra `planning_hub`
    e `planning_full_screen`. Prima di α.44 era inline in planning_hub."""
    if view not in VALID_VIEWS:
        view = "jobs"
    clients = db.query(Client).filter(Client.tenant_id == current_tenant_id()).order_by(Client.name).all()
    projects = (
        db.query(Project).filter(Project.tenant_id == current_tenant_id())
        .order_by(Project.code).all()
    )
    departments = (
        db.query(Department).filter(
            Department.tenant_id == current_tenant_id(), Department.is_active == True
        ).order_by(Department.sort_order, Department.name).all()
    )
    resources = (
        db.query(Resource).filter(
            Resource.tenant_id == current_tenant_id(), Resource.is_active == True
        ).order_by(Resource.name).all()
    )
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant scope su page-render (era leak)
    jobs = (
        scoped(
            db.query(Job).options(joinedload(Job.client), joinedload(Job.project)),
            Job,
        )
        .filter(Job.status != JobStatus.cancelled)
        .order_by(Job.created_at.desc()).all()
    )
    from app.models import Quote, QuoteStatus
    quotes = (
        scoped(
            db.query(Quote).options(
                joinedload(Quote.client), joinedload(Quote.project)
            ),
            Quote,
        ).filter(
            Quote.status.in_((QuoteStatus.draft, QuoteStatus.sent, QuoteStatus.approved))
        ).order_by(Quote.created_at.desc()).all()
    )
    cur_user = _resolve_current_user(db, access_token)
    cur_resource_id = None
    if cur_user:
        my_res = db.query(Resource).filter(Resource.user_id == cur_user.id).first()
        if my_res:
            cur_resource_id = my_res.id
    user_is_elevated = False
    if cur_user:
        from app.services.rbac import is_admin, is_manager, is_producer, has_permission
        user_is_elevated = (
            is_admin(cur_user) or is_manager(cur_user) or is_producer(cur_user)
            or has_permission(cur_user, "edit_planning")
        )
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
            "quotes": quotes,
            "current_resource_id": cur_resource_id,
            "user_is_elevated": user_is_elevated,
            "full_screen": full_screen,
        },
    )


# ── Clienti API ───────────────────────────────────────────────────────

@router.get("/api/clients")
async def list_clients(db: Session = Depends(get_db)):
    # v3.5.0-alpha.171.11 — tenant scope (era leak cross-tenant)
    return db.query(Client).filter(Client.tenant_id == current_tenant_id()).all()


# v3.5.0-alpha.172.35 (Sprint 1) — RIMOSSO endpoint `POST /planning/api/clients`
# (era deprecated da v3.4.x). Aveva bug: creava Client senza `tenant_id` →
# leak cross-tenant. UI corretta usa `POST /clients/api`. Cross-ref audit
# (Sprint 1) ha confermato nessun caller residuo.


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
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard via fetch_or_404
    fetch_or_404(db, Job, job_id, error="Job non trovato")
    return _compute_job_progress(db, job_id)


@router.get("/api/jobs/{job_id}/resource-coverage")
async def job_resource_coverage(
    job_id: int,
    resource_ids: str,  # CSV "1,2,3"
    db: Session = Depends(get_db),
):
    """v3.4.56 — Verifica quali risorse sono già assegnate al job e quali no.
    Usato dal modal booking PRIMA del save per chiedere conferma all'utente
    se l'auto-assignment sta per aggiungere nuove risorse al progetto.

    Ritorna `{covered: [{id, name}], missing: [{id, name, role, dept_name}]}`.
    """
    from app.models import JobResourceAssignment, Resource
    try:
        rids = [int(x) for x in resource_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "resource_ids deve essere CSV di interi")
    if not rids:
        return {"covered": [], "missing": []}
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    j = fetch_or_404(db, Job, job_id, error="Job non trovato")
    assigned = {
        a.resource_id for a in db.query(JobResourceAssignment).filter(
            JobResourceAssignment.job_id == job_id
        ).all()
    }
    resources = db.query(Resource).filter(Resource.id.in_(rids)).all()
    covered, missing = [], []
    for r in resources:
        info = {
            "id": r.id, "name": r.name, "role": r.role,
            "department_id": r.department_id,
            "department_name": r.department.name if r.department else None,
        }
        (covered if r.id in assigned else missing).append(info)
    return {"job_id": job_id, "job_code": j.code, "covered": covered, "missing": missing}


@router.get("/api/jobs")
async def list_jobs(
    status: Optional[JobStatus] = None,
    client_id: Optional[str] = None,
    project_id: Optional[str] = None,
    department_id: Optional[str] = None,
    q: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_progress: bool = False,
    db: Session = Depends(get_db),
):
    """Lista job con filtri. Tenant filter implicito via project/client.
    `include_progress=true` aggrega le ore booking per ogni job (più lento).

    v3.4.47 — `client_id`/`project_id`/`department_id` accettano comma-separated
    (es. `?client_id=1,5,7`). Compatibile con single-id pre-multi.

    v3.5.0-alpha.172.35 (Sprint 1) — tenant filter ora unconditional (era
    "implicito via client/project" ma solo se uno di quei filtri opzionali
    veniva passato; senza filtri restituiva tutti i job di tutti i tenant).
    """
    qs = scoped(
        db.query(Job).options(joinedload(Job.client), joinedload(Job.project)),
        Job,
    )
    if status:
        qs = qs.filter(Job.status == status)
    client_ids = _parse_id_list(client_id)
    project_ids = _parse_id_list(project_id)
    department_ids = _parse_id_list(department_id)
    if client_ids:
        qs = qs.filter(Job.client_id.in_(client_ids))
    if project_ids:
        qs = qs.filter(Job.project_id.in_(project_ids))
    if department_ids:
        # Job tocca dipartimento se almeno una sua JobCostLine ha price_item
        # del reparto. Filtro grossolano: subquery EXISTS.
        from app.models import PriceItem
        sub = (
            db.query(JobCostLine.job_id)
            .join(PriceItem, JobCostLine.price_item_id == PriceItem.id)
            .filter(PriceItem.department_id.in_(department_ids))
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


# v3.5.0-alpha.172.35 (Sprint 1) — RIMOSSO endpoint `POST /planning/api/jobs`
# (era deprecated da v3.4.8). I job nascono solo da quote approvate. Aveva
# 2 bug: (1) creava Job senza `tenant_id`, (2) check unicità `code` cross-tenant
# (collisione falsa positiva). Nessun caller residuo nel codebase.


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: int, db: Session = Depends(get_db)):
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    j = (
        scoped(db.query(Job).options(joinedload(Job.client)), Job)
        .filter(Job.id == job_id).first()
    )
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


@router.put("/api/jobs/{job_id}/status", dependencies=[RequireEditPlanningAll])
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


def _booking_task_department_id(b: Booking) -> Optional[int]:
    """Reparto canonico del 'task' di un booking. Catena:
    Booking.cost_line → JobCostLine.price_item → PriceItem.department_id.
    Ritorna None se booking senza cost_line o cost_line senza price_item
    o price_item senza department: in quei casi non c'è reparto atteso e
    il check cross-department non si applica.
    """
    if not b or not b.cost_line:
        return None
    pi = b.cost_line.price_item
    if not pi:
        return None
    return pi.department_id


def _dept_mismatch_payload(db: Session, b: Booking, resource_id_target: int) -> Optional[dict]:
    """Se la risorsa target appartiene a un reparto diverso da quello del task
    (entrambi non null), ritorna un payload con i nomi reparto. Altrimenti None.
    Usato dal client per mostrare confirm + badge."""
    task_dept = _booking_task_department_id(b)
    if task_dept is None:
        return None
    res = db.query(Resource).filter(Resource.id == resource_id_target).first()
    if not res or res.department_id is None:
        return None
    if res.department_id == task_dept:
        return None
    depts = {d.id: d.name for d in db.query(Department).filter(
        Department.id.in_([task_dept, res.department_id])
    ).all()}
    return {
        "task_department_id": task_dept,
        "task_department_name": depts.get(task_dept) or f"#{task_dept}",
        "resource_department_id": res.department_id,
        "resource_department_name": depts.get(res.department_id) or f"#{res.department_id}",
    }


def _check_assignment_conflict(db: Session, resource_id: int, start: datetime, end: datetime,
                                exclude_assignment_id: Optional[int] = None,
                                exclude_booking_id: Optional[int] = None) -> Optional[BookingAssignment]:
    """Verifica se esiste un altro assignment in conflitto sulla stessa risorsa.

    `exclude_assignment_id`: esclude un singolo assignment (utile quando si
    edita un assignment, per non vedere se stesso come conflitto).
    `exclude_booking_id` (v3.5.0-alpha.66.5.2): esclude TUTTI gli assignment
    di un dato booking. Necessario quando si modifica un booking smart-split
    (multi-segment stessa risorsa): i segmenti contigui dello stesso booking
    sono fratelli legittimi, non conflitti. L'overlap tra fratelli dello
    stesso booking è gestito separatamente da `_check_intra_payload_overlaps`.
    """
    q = db.query(BookingAssignment).join(Booking, BookingAssignment.booking_id == Booking.id).filter(
        Booking.tenant_id == current_tenant_id(),
        Booking.status != BookingStatus.cancelled,
        BookingAssignment.resource_id == resource_id,
        BookingAssignment.start_datetime < end,
        BookingAssignment.end_datetime > start,
    )
    if exclude_assignment_id:
        q = q.filter(BookingAssignment.id != exclude_assignment_id)
    if exclude_booking_id:
        q = q.filter(BookingAssignment.booking_id != exclude_booking_id)
    return q.first()


def _check_intra_payload_overlaps(parsed_ass: list[dict]) -> Optional[tuple[int, int]]:
    """v3.5.0-alpha.63: rileva risorse duplicate con tempo sovrapposto nello
    stesso payload di assignments (POST/PUT booking). Senza questo guard era
    possibile inserire 2 BookingAssignment per la stessa risorsa nello stesso
    booking → la risorsa appariva 2 volte in /api/bookings/{id}/detail.

    Ritorna (i, j) degli indici in conflitto, oppure None se ok.
    Stessa risorsa con intervalli ADIACENTI o DISGIUNTI è permessa (es. split
    pausa pranzo → 2 assignments stessa risorsa, contigui ma non sovrapposti).
    """
    n = len(parsed_ass)
    for i in range(n):
        for j in range(i + 1, n):
            if parsed_ass[i]["resource_id"] != parsed_ass[j]["resource_id"]:
                continue
            si, ei = parsed_ass[i]["start_datetime"], parsed_ass[i]["end_datetime"]
            sj, ej = parsed_ass[j]["start_datetime"], parsed_ass[j]["end_datetime"]
            if si < ej and sj < ei:
                return (i, j)
    return None


def _recalc_booking_envelope(b: Booking):
    """Ricalcola Booking.start_datetime/end_datetime come min/max dei suoi assignments."""
    if not b.assignments:
        return
    b.start_datetime = min(a.start_datetime for a in b.assignments)
    b.end_datetime = max(a.end_datetime for a in b.assignments)


def _parse_id_list(value) -> Optional[list[int]]:
    """v3.4.47 — Parser tollerante per filtri multi-id: accetta None, int,
    "1", "1,5,7", o list[int|str]. Ritorna None se vuoto, lista pulita altrimenti.
    Compatibile con i filtri pre-multi: una sola id "1" → [1]."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            r = _parse_id_list(v)
            if r:
                out.extend(r)
        return out or None
    out = []
    for part in str(value).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out or None


# ── v3.4.50 — Resource presets (selezioni multiple) ─────────────────


@router.get("/api/resource-presets")
async def list_resource_presets(db: Session = Depends(get_db)):
    """Lista presets risorse del tenant. Ritorna anche resource_count e
    quali risorse sono ancora attive (per UI: alert su risorse rimosse)."""
    presets = (
        db.query(ResourcePreset)
        .filter(ResourcePreset.tenant_id == current_tenant_id())
        .order_by(ResourcePreset.name).all()
    )
    # Cache nomi risorse attive per il counter "valid"
    active_ids = {
        r.id for r in db.query(Resource).filter(
            Resource.tenant_id == current_tenant_id(), Resource.is_active == True  # noqa: E712
        ).all()
    }
    out = []
    for p in presets:
        ids = list(p.resource_ids or [])
        valid = [rid for rid in ids if rid in active_ids]
        out.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "resource_ids": ids,
            "resource_count": len(ids),
            "valid_count": len(valid),
            "created_by": p.created_by,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return out


@router.post("/api/resource-presets")
async def create_resource_preset(
    request: Request,
    name: str = Form(...),
    resource_ids: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea un preset. resource_ids comma-separated. RBAC: tutti gli utenti
    autenticati possono creare (è un'utility personale/condivisa)."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Non autenticato")
    name_clean = (name or "").strip()
    if not name_clean:
        raise HTTPException(400, "Nome obbligatorio")
    ids = _parse_id_list(resource_ids) or []
    if not ids:
        raise HTTPException(400, "Specifica almeno una risorsa")
    # Conflitto nome (case-insensitive nel tenant)
    existing = (
        db.query(ResourcePreset)
        .filter(
            ResourcePreset.tenant_id == current_tenant_id(),
            func.lower(ResourcePreset.name) == name_clean.lower(),
        ).first()
    )
    if existing:
        raise HTTPException(409, f"Esiste già un preset con nome '{name_clean}'")
    p = ResourcePreset(
        tenant_id=current_tenant_id(),
        name=name_clean,
        description=(description or "").strip() or None,
        resource_ids=ids,
        created_by=user.id,
    )
    db.add(p); db.commit(); db.refresh(p)
    return {
        "id": p.id, "name": p.name, "description": p.description,
        "resource_ids": p.resource_ids, "resource_count": len(p.resource_ids or []),
    }


@router.put("/api/resource-presets/{preset_id}")
async def update_resource_preset(
    preset_id: int,
    request: Request,
    name: Optional[str] = Form(None),
    resource_ids: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Aggiorna preset. Il creatore o admin/manager possono modificare."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401)
    p = db.query(ResourcePreset).filter(
        ResourcePreset.id == preset_id,
        ResourcePreset.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, "Preset non trovato")
    from app.services.rbac import is_admin, is_manager
    if p.created_by != user.id and not (is_admin(user) or is_manager(user)):
        raise HTTPException(403, "Solo il creatore o admin/manager può modificare")
    if name is not None and name.strip():
        p.name = name.strip()
    if resource_ids is not None:
        ids = _parse_id_list(resource_ids) or []
        if not ids:
            raise HTTPException(400, "Almeno una risorsa")
        p.resource_ids = ids
    if description is not None:
        p.description = description.strip() or None
    db.commit(); db.refresh(p)
    return {
        "id": p.id, "name": p.name, "description": p.description,
        "resource_ids": p.resource_ids, "resource_count": len(p.resource_ids or []),
    }


@router.delete("/api/resource-presets/{preset_id}")
async def delete_resource_preset(
    preset_id: int, request: Request, db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401)
    p = db.query(ResourcePreset).filter(
        ResourcePreset.id == preset_id,
        ResourcePreset.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404)
    from app.services.rbac import is_admin, is_manager
    if p.created_by != user.id and not (is_admin(user) or is_manager(user)):
        raise HTTPException(403, "Solo il creatore o admin/manager può eliminare")
    db.delete(p); db.commit()
    return {"ok": True}


def _validate_kind_job(kind: BookingKind, job_id: Optional[int],
                       job_cost_line_id: Optional[int], db: Session):
    """Valida coerenza kind / job_id / cost_line_id. Ritorna (job_id_clean, line_id_clean).

    v3.5.0-alpha.172.17 — HARD-BLOCK su `kind=project` senza `job_cost_line_id`:
    senza una lavorazione (JCL) associata il booking non viene mai attribuito nel
    cost report (lavoro fantasma). Applicato lato server in modo da coprire
    POST /api/bookings, PUT /api/bookings/{id}, AI tool `propose_recurring_bookings`
    e qualsiasi altro path che riusi questo validator.
    """
    if kind == BookingKind.project:
        if not job_id:
            raise HTTPException(400, "Per kind=project serve job_id")
        if not job_cost_line_id:
            raise HTTPException(
                400,
                "Lavorazione (JCL) obbligatoria per booking kind=project. "
                "Seleziona una lavorazione del job — senza JCL il booking non "
                "viene attribuito nel cost report."
            )
        line = db.query(JobCostLine).filter(JobCostLine.id == job_cost_line_id).first()
        if not line:
            raise HTTPException(404, "Lavorazione non trovata")
        if line.job_id != job_id:
            raise HTTPException(400, f"La lavorazione #{job_cost_line_id} non appartiene al job #{job_id}")
        return job_id, job_cost_line_id
    return None, None


# v3.5.0-alpha.171.10 (TL-3 dropdown) — Search JCL del progetto filtrato.
# Restituisce lista JCL match-able da PriceItem.name / JobCostLine.description.
# Usato dalla sidebar planning per popolare l'autocomplete "Lavorazione".
@router.get("/api/jcl-search")
async def jcl_search(
    project_id: Optional[str] = None,
    job_id: Optional[str] = None,
    search_q: Optional[str] = Query(None, alias="q"),
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Cerca JCL del tenant, filtrabili per progetto/job + match testuale.

    Response: [{id, description, job_id, job_code, project_id, project_code,
                 price_item_id, unit, quoted_total}]
    """
    from app.models import PriceItem as _PI
    qry = (
        db.query(JobCostLine)
        .options(
            joinedload(JobCostLine.job).joinedload(Job.project),
            joinedload(JobCostLine.price_item),
        )
        .filter(JobCostLine.tenant_id == current_tenant_id())
    )
    project_ids = _parse_id_list(project_id)
    job_ids = _parse_id_list(job_id)
    if project_ids:
        qry = qry.join(Job, JobCostLine.job_id == Job.id).filter(Job.project_id.in_(project_ids))
    if job_ids:
        qry = qry.filter(JobCostLine.job_id.in_(job_ids))
    if search_q and search_q.strip():
        from sqlalchemy import or_ as _or, func as _func
        s = f"%{search_q.strip().lower()}%"
        qry = qry.outerjoin(_PI, JobCostLine.price_item_id == _PI.id).filter(_or(
            _func.lower(JobCostLine.description).like(s),
            _func.lower(_PI.name).like(s),
        ))
    rows = qry.order_by(JobCostLine.id.desc()).limit(limit).all()
    out = []
    for jcl in rows:
        out.append({
            "id": jcl.id,
            "description": jcl.description or (jcl.price_item.name if jcl.price_item else "?"),
            "job_id": jcl.job_id,
            "job_code": jcl.job.code if jcl.job else None,
            "job_title": jcl.job.title if jcl.job else None,
            "project_id": jcl.job.project_id if jcl.job else None,
            "project_code": (jcl.job.project.code if jcl.job and jcl.job.project else None),
            "price_item_id": jcl.price_item_id,
            "price_item_name": jcl.price_item.name if jcl.price_item else None,
            "unit": jcl.unit,
            "quoted_total": round(jcl.total_quoted or 0, 2),
        })
    return out


@router.get("/api/bookings")
async def list_bookings(
    job_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    kind: Optional[BookingKind] = None,
    client_id: Optional[str] = None,
    project_id: Optional[str] = None,
    department_id: Optional[str] = None,
    status: Optional[BookingStatus] = None,
    job_cost_line_id: Optional[str] = None,  # v3.5.0-alpha.171.7 (TL-3)
    # v3.5.0-alpha.172.21 — Filtro booking_id CSV per refresh incrementale UI.
    # Permette al client di re-fetch solo i booking touched dopo mutate senza
    # ricaricare l'intera timeline.
    booking_id: Optional[str] = None,
    # v3.5.0-alpha.171.7 (TL-5) — ricerca testuale; UI invia "q=..."
    search_q: Optional[str] = Query(None, alias="q"),
    db: Session = Depends(get_db),
):
    """Lista assignments come items per la timeline.
    Ogni booking con N risorse → N items distinti (group=resource_id),
    legati allo stesso booking_id via extendedProps.

    v3.4.47 — Tutti i filtri id (job/resource/client/project/department)
    accettano comma-separated (`?resource_id=1,3,5`). Compatibile single.

    v3.5.0-alpha.171.7 (Sprint 3 TL-3+TL-5):
    - `job_cost_line_id` (CSV): filtra per lavorazione (JCL). Subfiltro
      naturale di progetto/job. Permette "mostrami solo i booking di
      Production management del progetto X".
    - `q` (testo libero): ricerca full-text su `Booking.notes`,
      `JobCostLine.description`, `PriceItem.name`, `Job.code`/`Job.title`,
      `Resource.name`/`Resource.role`. Case-insensitive LIKE.
    """
    from app.models import PriceItem  # locale per evitare import cycle
    qry = db.query(BookingAssignment).options(
        joinedload(BookingAssignment.resource),
        joinedload(BookingAssignment.booking).joinedload(Booking.job).joinedload(Job.project),
        joinedload(BookingAssignment.booking).joinedload(Booking.cost_line).joinedload(JobCostLine.price_item),
    ).join(Booking, BookingAssignment.booking_id == Booking.id).filter(
        Booking.tenant_id == current_tenant_id(),
    )
    job_ids = _parse_id_list(job_id)
    resource_ids = _parse_id_list(resource_id)
    client_ids = _parse_id_list(client_id)
    project_ids = _parse_id_list(project_id)
    department_ids = _parse_id_list(department_id)
    jcl_ids = _parse_id_list(job_cost_line_id)  # v3.5.0-alpha.171.7 (TL-3)
    if job_ids:
        qry = qry.filter(Booking.job_id.in_(job_ids))
    if resource_ids:
        qry = qry.filter(BookingAssignment.resource_id.in_(resource_ids))
    if kind:
        qry = qry.filter(Booking.kind == kind)
    if status:
        qry = qry.filter(Booking.status == status)
    else:
        qry = qry.filter(Booking.status != BookingStatus.cancelled)
    if from_date:
        qry = qry.filter(BookingAssignment.end_datetime >= from_date)
    if to_date:
        qry = qry.filter(BookingAssignment.start_datetime <= to_date)
    if client_ids or project_ids:
        qry = qry.join(Job, Booking.job_id == Job.id, isouter=True)
        if client_ids:
            qry = qry.filter(Job.client_id.in_(client_ids))
        if project_ids:
            qry = qry.filter(Job.project_id.in_(project_ids))
    if department_ids:
        qry = qry.join(Resource, BookingAssignment.resource_id == Resource.id).filter(
            Resource.department_id.in_(department_ids)
        )
    # v3.5.0-alpha.171.7 (TL-3) — filtro lavorazione
    if jcl_ids:
        qry = qry.filter(Booking.job_cost_line_id.in_(jcl_ids))
    # v3.5.0-alpha.172.21 — filtro booking_id (refresh incrementale)
    booking_ids_in = _parse_id_list(booking_id)
    if booking_ids_in:
        qry = qry.filter(Booking.id.in_(booking_ids_in))
    # v3.5.0-alpha.171.7 (TL-5) — ricerca testuale full-text
    if search_q and search_q.strip():
        from sqlalchemy import or_ as _or, func as _func
        search = f"%{search_q.strip().lower()}%"
        qry = (
            qry.outerjoin(Job, Booking.job_id == Job.id)
            .outerjoin(JobCostLine, Booking.job_cost_line_id == JobCostLine.id)
            .outerjoin(PriceItem, JobCostLine.price_item_id == PriceItem.id)
            .outerjoin(Resource, BookingAssignment.resource_id == Resource.id)
            .filter(_or(
                _func.lower(Booking.notes).like(search),
                _func.lower(JobCostLine.description).like(search),
                _func.lower(PriceItem.name).like(search),
                _func.lower(Job.code).like(search),
                _func.lower(Job.title).like(search),
                _func.lower(Resource.name).like(search),
                _func.lower(Resource.role).like(search),
            ))
        )
    # Riassegno alias storico `q` (queryset) per il resto della funzione
    # che usa `q.all()` / `q.filter(...)` post-filtri principali.
    q = qry
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

    # v3.5.0-alpha.59 — pre-fetch slice locks per evitare N+1. Una sola query
    # per tutte le JCL coinvolte nei booking della response. Map jcl_id →
    # list of slices ordinate per period_start. Per ogni assignment poi
    # cerchiamo (in memoria) un overlap tra la sua finestra e gli slice
    # della stessa JCL.
    from app.models import JCLBilledSlice
    jcl_ids = {a.booking.job_cost_line_id for a in assignments if a.booking and a.booking.job_cost_line_id}
    slices_by_jcl: dict[int, list[JCLBilledSlice]] = {}
    if jcl_ids:
        slc_rows = (
            db.query(JCLBilledSlice)
            .options(joinedload(JCLBilledSlice.invoice))
            .filter(JCLBilledSlice.job_cost_line_id.in_(jcl_ids))
            .all()
        )
        for s in slc_rows:
            slices_by_jcl.setdefault(s.job_cost_line_id, []).append(s)

    def _lock_for_assignment(a: BookingAssignment) -> Optional[dict]:
        if not (a.booking and a.booking.job_cost_line_id):
            return None
        # v3.5.0-alpha.66.3: tentative NON ottiene lock visivo (resta libero
        # di essere mosso anche dentro periodi fatturati, niente bordo viola).
        if a.booking.status == BookingStatus.tentative:
            return None
        candidates = slices_by_jcl.get(a.booking.job_cost_line_id, [])
        if not candidates:
            return None
        a_start = a.start_datetime.date()
        a_end = a.end_datetime.date()
        for s in candidates:
            if s.period_start <= a_end and s.period_end >= a_start:
                return {
                    "slice_id": s.id,
                    "period_start": s.period_start.isoformat(),
                    "period_end": s.period_end.isoformat(),
                    "invoice_number": (s.invoice.number if s.invoice else None),
                }
        return None

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
                "job_code": b.job.code if b.job else None,
                "job_title": b.job.title if b.job else None,
                "project_id": (b.job.project_id if b.job else None),
                "project_title": (b.job.project.title if (b.job and b.job.project) else None),
                "project_code": (b.job.project.code if (b.job and b.job.project) else None),
                "job_cost_line_id": b.job_cost_line_id,
                "cost_line_description": b.cost_line.description if b.cost_line else None,
                "resource_id": a.resource_id,
                "status": b.status.value if hasattr(b.status, "value") else b.status,
                # v3.5.0-alpha.66.5 — stato unificato (5 valori esclusivi + cancelled).
                # Fonte canonica per la UI. status + execution_status restano
                # per back-compat ma sono derivati da state.
                "state": b.state.value if hasattr(b.state, "value") else b.state,
                "notes": b.notes,
                "group_size": sizes.get(b.id, 1),
                "group_position": pos_map.get(a.id, 1),
                # v3.4.32 — booking esecutivo
                "priority": b.priority.value if hasattr(b.priority, "value") else (b.priority or "normal"),
                "execution_status": b.execution_status.value if hasattr(b.execution_status, "value") else (b.execution_status or "planned"),
                "overtime_status": b.overtime_status.value if hasattr(b.overtime_status, "value") else (b.overtime_status or "none"),
                "not_done_reason": b.not_done_reason,
                "count_in_costs": bool(b.count_in_costs),
                # v3.5.0-alpha.22: durata totale lavorazione (per tooltip hover).
                "job_total_hours": (b.cost_line.quantity_quoted if b.cost_line else None),
                "job_done_hours": (b.cost_line.quantity_actual if b.cost_line else None),
                "cost_line_unit": (b.cost_line.unit if b.cost_line else None),
                # v3.5.0-alpha.23: dept_id della lavorazione (per dept-compat
                # check al drop su altra risorsa nel client). Risale via
                # price_item.department_id.
                "cost_line_department_id": (
                    b.cost_line.price_item.department_id
                    if (b.cost_line and b.cost_line.price_item) else None
                ),
                # v3.5.0-alpha.32: flag persistente cross-department.
                # True se sia il reparto del task (price_item) sia il reparto
                # della risorsa sono noti e diversi. Il client lo usa per il
                # badge ⚠ sull'item, indipendente dal momento del drop.
                # v3.5.0-alpha.163: voci cross_dept (trasversali) → NO warning
                #   (Production Management, Coordination, ecc.: accettano qualsiasi reparto).
                "cross_department": (
                    bool(
                        b.cost_line and b.cost_line.price_item
                        and not getattr(b.cost_line.price_item, "cross_dept", False)
                        and b.cost_line.price_item.department_id is not None
                        and a.resource and a.resource.department_id is not None
                        and b.cost_line.price_item.department_id != a.resource.department_id
                    )
                ),
                # v3.5.0-alpha.163 — Voce trasversale: cross_dept flag esposto al client
                "cost_line_cross_dept": bool(
                    b.cost_line and b.cost_line.price_item
                    and getattr(b.cost_line.price_item, "cross_dept", False)
                ),
                # v3.5.0-alpha.59 — slice lock: presente se l'assignment ricade
                # in un periodo già fatturato. UI mostra lucchetto + tooltip,
                # API mutator → 409 con detail.code=BOOKING_LOCKED_BY_SLICE.
                "slice_lock": _lock_for_assignment(a),
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
        WorkingHoursPolicy.tenant_id == current_tenant_id(),
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


def _classify_assignments_pairing(db: Session, parsed_ass: list[dict]) -> Optional[dict]:
    """v3.5.0-alpha.172.88 (Bundle H1) — Detect anomaly: booking con SOLO
    risorse umane O SOLO risorse non-umane (sala/equipment/software/vehicle).
    Pattern tipico produzione post: umana + sala/equipment vanno appaiate.
    Ritorna dict con `kind` ('human_only' | 'studio_only') + lista risorse,
    o None se mix OK. Caller usa risultato per warning + force-override.
    """
    from app.services.cost_line_sync import HUMAN_RESOURCE_TYPES
    human_res = []
    nonhuman_res = []
    rids = sorted({pa["resource_id"] for pa in parsed_ass})
    for rid in rids:
        r = db.query(Resource).filter(Resource.id == rid).first()
        if not r:
            continue
        rtype = r.type.value if hasattr(r.type, "value") else str(r.type)
        if rtype in HUMAN_RESOURCE_TYPES:
            human_res.append({"id": rid, "name": r.name, "type": rtype})
        else:
            nonhuman_res.append({"id": rid, "name": r.name, "type": rtype})
    if human_res and not nonhuman_res:
        return {
            "kind": "human_only",
            "message": f"Booking con SOLO risorse umane ({len(human_res)}): {', '.join(h['name'] for h in human_res)}. Manca una risorsa tecnica (sala/equipment). Conferma se intenzionale.",
            "human_resources": human_res,
            "nonhuman_resources": [],
        }
    if nonhuman_res and not human_res:
        return {
            "kind": "studio_only",
            "message": f"Booking con SOLO risorse non-umane ({len(nonhuman_res)}): {', '.join(s['name'] for s in nonhuman_res)}. Manca un operatore umano. Conferma se intenzionale.",
            "human_resources": [],
            "nonhuman_resources": nonhuman_res,
        }
    return None


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


# ── DIAGNOSTICA BUG DUPLICAZIONE (v3.5.0-alpha.66.2) ─────────────
# v3.5.0-alpha.66.20 — Estratti in `planning_diag.py` (sprint R7.x). Gli
# endpoint /planning/api/diag/* sono ora montati da app/main.py via
# planning_diag.router. Niente cambia per il chiamante esterno.
# Lo stub originale è ridotto a una nota: il vero codice vive nel nuovo file.

_LEGACY_DIAG_ENDPOINT_RELOCATED = True  # marker per grep storici


@router.post("/api/bookings")
async def create_booking(
    request: Request,
    assignments: str = Form(...),  # JSON: [{"resource_id":1,"start_datetime":"...","end_datetime":"..."}, ...]
    job_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    kind: BookingKind = Form(BookingKind.project),
    status: BookingStatus = Form(BookingStatus.tentative),
    notes: Optional[str] = Form(None),
    priority: Optional[str] = Form(None),  # v3.5.0-alpha.22: low|normal|high
    smart_split: bool = Form(False),  # E3 v3.4.17
    recurrence_rule: Optional[str] = Form(None),  # E5 v3.4.19: WEEKDAYS, MON, TUE,THU, DAILY...
    recurrence_until: Optional[_date] = Form(None),
    force_single_type: bool = Form(False),  # Bundle H1 v3.5.0-alpha.172.88 — bypass anomaly check
    db: Session = Depends(get_db),
):
    """Crea un booking con N assignments (multi-risorsa).

    `assignments` è una stringa JSON con la lista delle assegnazioni.
    Ogni elemento: {"resource_id": int, "start_datetime": ISO, "end_datetime": ISO}.
    Almeno 1 assignment richiesto (warning per 0).

    v3.5.0-alpha.10: gate `can_create_booking` (admin/manager/producer).
    Editor/operator devono usare `POST /api/booking-requests` (notifica al producer).
    """
    from app.services.rbac import can_create_booking as _can_create_booking
    user = current_user_optional(request)
    if not _can_create_booking(user):
        raise HTTPException(
            403,
            "Non hai il permesso di creare booking direttamente. Usa il flusso "
            "'Richiedi booking' (notifica producer/manager).",
        )
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

    # v3.5.0-alpha.63 — guard intra-payload: la stessa risorsa NON può essere
    # presente due volte in OVERLAP nello stesso booking (segmenti contigui ok).
    dup = _check_intra_payload_overlaps(parsed_ass)
    if dup is not None:
        i, j = dup
        raise HTTPException(
            400,
            f"La stessa risorsa è inserita due volte con orari sovrapposti "
            f"(righe #{i+1} e #{j+1}). Rimuovi il duplicato o sistema gli orari."
        )

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

    # v3.5.0-alpha.172.88 (Bundle H1) — anomaly: booking solo umani o solo
    # non-umani. Override esplicito via force_single_type=true.
    if not force_single_type:
        warn = _classify_assignments_pairing(db, parsed_ass)
        if warn is not None:
            raise HTTPException(
                422,
                detail={
                    "code": "SINGLE_TYPE_WARNING",
                    "kind": warn["kind"],
                    "message": warn["message"],
                    "human_resources": warn["human_resources"],
                    "nonhuman_resources": warn["nonhuman_resources"],
                    "remediation": "force_single_type",
                },
            )

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
            # v3.5.0-alpha.66.5.1: sincronizza state con status passato dal client
            recur_state = (BookingState.cancelled if status == BookingStatus.cancelled
                           else BookingState.confirmed if status == BookingStatus.confirmed
                           else BookingState.tentative)
            b = Booking(
                tenant_id=current_tenant_id(),
                job_id=job_id, job_cost_line_id=job_cost_line_id,
                start_datetime=env_s, end_datetime=env_e,
                status=status, kind=kind, notes=notes,
                priority=_parse_priority(priority),
                state=recur_state,
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
        # v3.4.55: auto-assignment Resource → Job (idempotente)
        if primary_booking and primary_booking.job_id:
            from app.services.resource_assignment_sync import ensure_resources_assigned_to_job
            try:
                ensure_resources_assigned_to_job(
                    db, primary_booking.job_id, [pa["resource_id"] for pa in parsed_ass]
                )
            except Exception as e:
                print(f"[booking-create] auto-assignment failed: {e}")
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
    # v3.5.0-alpha.66.5.1: sincronizza state con status passato dal client
    initial_state = (BookingState.cancelled if status == BookingStatus.cancelled
                     else BookingState.confirmed if status == BookingStatus.confirmed
                     else BookingState.tentative)
    b = Booking(
        tenant_id=current_tenant_id(),
        job_id=job_id,
        job_cost_line_id=job_cost_line_id,
        start_datetime=env_start, end_datetime=env_end,
        status=status, kind=kind, notes=notes,
        priority=_parse_priority(priority),
        state=initial_state,
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
    # v3.4.55: auto-assignment Resource → Job (idempotente).
    # Se il booking è legato a un job, le risorse coinvolte vengono auto-aggiunte
    # al JobResourceAssignment per consentire il report ore-per-risorsa.
    if b.job_id:
        from app.services.resource_assignment_sync import ensure_resources_assigned_to_job
        try:
            ensure_resources_assigned_to_job(
                db, b.job_id, [pa["resource_id"] for pa in parsed_ass]
            )
        except Exception as e:
            print(f"[booking-create] auto-assignment failed: {e}")
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


# ── Booking request flow (v3.5.0-alpha.10) ──────────────────────
# Editor/operator non possono creare booking direttamente. Inviano una
# "richiesta" testuale al producer/manager (notifica `booking_request`),
# che crea il booking effettivo dopo verifica disponibilità risorsa.

@router.post("/api/booking-requests")
async def submit_booking_request(
    request: Request,
    proposed_start: datetime = Form(...),
    proposed_end: datetime = Form(...),
    resource_id: Optional[int] = Form(None),
    quote_id: Optional[int] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    notes: str = Form(...),  # motivazione obbligatoria
    db: Session = Depends(get_db),
):
    """Editor/operator manda una richiesta di booking al producer.

    Non crea Booking — crea solo una notifica `booking_request` con i parametri
    proposti. Il producer/manager riceve la notifica, valuta e crea il booking
    direttamente dalla pagina /planning (oppure rifiuta).

    Permesso: chiunque autenticato (la creazione effettiva resta gated da
    `can_create_booking` lato `POST /api/bookings`).
    """
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Non autenticato")
    if proposed_end <= proposed_start:
        raise HTTPException(400, "Fine deve essere > Inizio")
    notes = (notes or "").strip()
    if not notes:
        raise HTTPException(400, "Inserisci una motivazione per la richiesta")

    # Risorsa di default = quella linkata all'utente (se editor)
    if not resource_id:
        rid = scope_resource_id(db, user)
        if rid:
            resource_id = rid
    res = None
    if resource_id:
        res = db.query(Resource).filter(
            Resource.id == resource_id,
            Resource.tenant_id == current_tenant_id(),
        ).first()

    quote = None
    if quote_id:
        from app.models import Quote
        quote = db.query(Quote).filter(
            Quote.id == quote_id,
            Quote.tenant_id == current_tenant_id(),
        ).first()

    cost_line = None
    if job_cost_line_id:
        cost_line = db.query(JobCostLine).filter(
            JobCostLine.id == job_cost_line_id,
        ).first()

    summary_bits = []
    if res:
        summary_bits.append(res.name)
    summary_bits.append(
        f"{proposed_start.strftime('%d/%m %H:%M')} → {proposed_end.strftime('%d/%m %H:%M')}"
    )
    if quote:
        summary_bits.append(f"quote {quote.number}")
    if cost_line:
        summary_bits.append(f"lavorazione: {cost_line.description[:60]}")
    summary = " · ".join(summary_bits)

    from app.services import notifications as notif_svc
    from app.models import NotificationKind, NotificationSeverity
    ns = notif_svc.notify_permission(
        db,
        permission="assign_resources",  # producer/manager/admin
        exclude_user_ids=[user.id],
        kind=NotificationKind.booking_request.value,
        severity=NotificationSeverity.action_required.value,
        title=f"📩 Richiesta booking: {summary}",
        body=notes,
        link="/planning?view=timeline",
        actor_user_id=user.id,
        payload={
            "requester_user_id": user.id,
            "resource_id": resource_id,
            "quote_id": quote_id,
            "job_cost_line_id": job_cost_line_id,
            "proposed_start": proposed_start.isoformat(),
            "proposed_end": proposed_end.isoformat(),
            "notes": notes,
        },
    )
    return {
        "ok": True,
        "notified_count": len(ns),
        "summary": summary,
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
    priority: Optional[str] = Form(None),  # v3.5.0-alpha.22
    assignments: Optional[str] = Form(None),  # se passato, replace-all
    smart_split: bool = Form(False),  # v3.5.0-alpha.172.75 — split a posteriori
    force_single_type: bool = Form(False),  # Bundle H1 v3.5.0-alpha.172.88
    force_slice_unlock: bool = Depends(_force_unlock_dep),  # α.66.3 + α.111.23 admin-gate
    db: Session = Depends(get_db),
):
    """Aggiorna metadata booking (kind/job/status/notes) e/o sostituisce assignments.

    Se `smart_split=true` e `assignments` è passato, la lista replace-all viene
    espansa via `split_booking_smart` per ogni risorsa (rispetta WHP + ferie +
    festivi). Utile per ribaltare un range "naive" su orari lavorativi reali
    senza ricalcolarli lato client.

    Per drag/resize di un singolo item della timeline → usare PUT /api/booking-assignments/{aid}.
    """
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    _enforce_planning_scope(request, db, {a.resource_id for a in b.assignments})
    _assert_no_blocking_slice(db, b, force=force_slice_unlock)

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
        # v3.5.0-alpha.63 — guard intra-payload: rifiuta stessa risorsa in overlap
        dup = _check_intra_payload_overlaps(parsed_ass)
        if dup is not None:
            i, j = dup
            raise HTTPException(
                400,
                f"La stessa risorsa è inserita due volte con orari sovrapposti "
                f"(righe #{i+1} e #{j+1}). Rimuovi il duplicato o sistema gli orari."
            )
        # v3.5.0-alpha.172.75 — smart split a posteriori: espande il range
        # naive su orari lavorativi reali (WHP + ferie + festivi).
        if smart_split:
            parsed_ass = _expand_assignments_smart(db, parsed_ass)
            if not parsed_ass:
                raise HTTPException(
                    400,
                    "Smart split: il range richiesto non contiene orario lavorativo "
                    "(tutto fuori orario, weekend, ferie o festivi)."
                )
        # v3.5.0-alpha.172.88 (Bundle H1) — anomaly check single-type pairing
        if not force_single_type:
            warn = _classify_assignments_pairing(db, parsed_ass)
            if warn is not None:
                raise HTTPException(
                    422,
                    detail={
                        "code": "SINGLE_TYPE_WARNING",
                        "kind": warn["kind"],
                        "message": warn["message"],
                        "human_resources": warn["human_resources"],
                        "nonhuman_resources": warn["nonhuman_resources"],
                        "remediation": "force_single_type",
                    },
                )
        # Conflict check (escludendo gli assignment attuali del booking, che sostituiremo)
        existing_ids = [a.id for a in b.assignments]
        for i, pa in enumerate(parsed_ass):
            q = db.query(BookingAssignment).join(Booking).filter(
                Booking.tenant_id == current_tenant_id(),
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

    # v3.5.0-alpha.114 — A9: traccia old JCL prima del cambio per recompute
    # cross-JCL su re-assign senza touch assignments (gap audit).
    _old_jcl_id_for_resync = b.job_cost_line_id if b.execution_status == BookingExecutionStatus.done else None
    b.kind = new_kind
    b.job_id = new_job_id
    b.job_cost_line_id = new_line_id
    if status is not None:
        b.status = status
        # v3.5.0-alpha.66.5: sincronizza state con i 2 enum legacy.
        # Se status diventa tentative/cancelled, state segue. Se status diventa
        # confirmed e execution_status era planned/in_progress/done/not_done,
        # state riflette quello.
        from app.models import compute_state_from_legacy
        b.state = compute_state_from_legacy(b.status.value, b.execution_status.value)
    if notes is not None:
        b.notes = notes
    if priority is not None and str(priority).strip():
        b.priority = _parse_priority(priority)

    db.flush()
    db.refresh(b)
    _recalc_booking_envelope(b)
    _log_change(db, b.id, "update", "Booking aggiornato", None)
    # v3.5.0-alpha.9: replace-all assignments cambia man-hours → recompute
    # v3.5.0-alpha.114 A9: triggera anche su re-assign JCL senza assignments:
    # old JCL e new JCL vanno ricomputate entrambe (vecchia perde ore, nuova
    # le acquisisce). Pattern uguale a bulk_edit new_cost_line.
    _need_recompute = (
        b.execution_status == BookingExecutionStatus.done
        and (assignments is not None or (_old_jcl_id_for_resync != b.job_cost_line_id))
    )
    if _need_recompute:
        try:
            from app.services.cost_line_sync import recompute_for_booking, recompute_cost_line_actual
            # Old JCL (se cambiata)
            if _old_jcl_id_for_resync and _old_jcl_id_for_resync != b.job_cost_line_id:
                old_jcl = db.query(JobCostLine).filter(JobCostLine.id == _old_jcl_id_for_resync).first()
                if old_jcl:
                    recompute_cost_line_actual(db, old_jcl)
            # New JCL (booking corrente)
            recompute_for_booking(db, b)
        except Exception as e:
            print(f"[update_booking] cost line sync failed: {e}")
    # v3.5.0-alpha.11: replace-all assignments su booking con job → garantisce
    # che le NUOVE risorse siano assegnate al job (JobResourceAssignment).
    # Senza questa chiamata, aggiungere una risorsa via "modifica booking"
    # non la legava al progetto/job — bug v3.4.55 era hook solo su CREATE.
    if assignments is not None and b.job_id:
        try:
            from app.services.resource_assignment_sync import ensure_resources_assigned_to_job
            ensure_resources_assigned_to_job(
                db, b.job_id, [a.resource_id for a in b.assignments]
            )
        except Exception as e:
            print(f"[update_booking] auto-assignment failed: {e}")
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


@router.post("/api/bookings/{booking_id}/cleanup-duplicate-overlaps")
async def cleanup_duplicate_overlaps(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.63 — cancella assignment duplicati con OVERLAP sulla
    stessa risorsa. Tiene il primo (per start_datetime), elimina gli altri.
    Idempotente: se non c'è alcun duplicato, ritorna `removed=0`.

    Necessario per pulire dati sporchi pre-α.63 (il guard intra-payload non
    esisteva → la stessa risorsa poteva apparire 2 volte nello stesso
    booking, quindi 2 volte nel detail modal).
    """
    b = db.query(Booking).options(
        joinedload(Booking.assignments)
    ).filter(Booking.id == booking_id, Booking.tenant_id == current_tenant_id()).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    _enforce_planning_scope(request, db, {a.resource_id for a in b.assignments})

    by_res: dict[int, list[BookingAssignment]] = {}
    for a in b.assignments:
        by_res.setdefault(a.resource_id, []).append(a)
    to_delete: list[int] = []
    for rid, lst in by_res.items():
        if len(lst) < 2:
            continue
        lst_sorted = sorted(lst, key=lambda x: x.start_datetime)
        kept = lst_sorted[0]
        for cand in lst_sorted[1:]:
            # se overlap con il primo (kept) → cancella; se contiguo → conserva
            if kept.start_datetime < cand.end_datetime and cand.start_datetime < kept.end_datetime:
                to_delete.append(cand.id)
            else:
                # cand non in overlap col primo, ma potrebbe esserlo con un
                # altro candidato già conservato — semplifichiamo: se NON
                # overlap con kept, conserviamo (caso pranzo/split).
                pass
    if to_delete:
        db.query(BookingAssignment).filter(BookingAssignment.id.in_(to_delete)).delete(
            synchronize_session=False
        )
        _recalc_booking_envelope(b)
        _log_change(
            db, b.id, "update",
            f"Cleanup duplicati overlap: rimossi {len(to_delete)} assignment",
            {"removed_assignment_ids": to_delete},
        )
        db.commit()
    return {"removed": len(to_delete), "removed_ids": to_delete}


@router.post("/api/bookings/{booking_id}/extend-as-series")
async def extend_booking_as_series(
    booking_id: int,
    request: Request,
    recurrence_rule: str = Form(...),
    recurrence_until: _date = Form(...),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.63 — estende un booking esistente come pattern di serie:
    crea N booking aggiuntivi nelle date generate dalla regola, escludendo la
    data del booking pattern (già materializzato). Mantiene job/cost_line/
    notes/priority/kind del pattern e replica TUTTI gli assignments shiftati
    al delta giornaliero corretto.

    Risolve il bug pre-α.63: il PUT /api/bookings/{id} ignorava i campi
    recurrence_rule/recurrence_until → dalla UI in edit mode l'utente vedeva
    "Booking aggiornato" ma le occorrenze ricorrenti non venivano create.

    Failed list: ogni occorrenza che va in conflitto con un assignment
    esistente viene saltata (skipped) e riportata in `failed`. Operazione
    non all-or-nothing: le occorrenze ok vengono create comunque.
    """
    pattern = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not pattern:
        raise HTTPException(404, "Booking pattern non trovato")
    if not pattern.assignments:
        raise HTTPException(400, "Il booking pattern non ha assignments")
    _enforce_planning_scope(request, db, {a.resource_id for a in pattern.assignments})

    pattern_first_start = min(a.start_datetime for a in pattern.assignments)
    occurrences = _expand_recurrence(
        pattern_first_start,
        max(a.end_datetime for a in pattern.assignments),
        recurrence_rule,
        recurrence_until,
    )
    if not occurrences:
        raise HTTPException(400, "La regola non genera occorrenze nel range indicato")

    pattern_date = pattern_first_start.date()
    created_ids: list[int] = []
    failed: list[dict] = []
    skipped_pattern_day = False

    for (occ_start, _occ_end) in occurrences:
        if occ_start.date() == pattern_date:
            skipped_pattern_day = True
            continue
        day_offset = (occ_start.date() - pattern_date).days

        # Replica gli assignments shiftati
        shifted: list[dict] = []
        for a in pattern.assignments:
            shifted.append({
                "resource_id": a.resource_id,
                "start_datetime": a.start_datetime + _td(days=day_offset),
                "end_datetime": a.end_datetime + _td(days=day_offset),
            })

        # Conflict check per occorrenza (per-assignment) — qualsiasi conflitto
        # → salta l'intera occorrenza (non parziale).
        conflict_msg = None
        for pa in shifted:
            c = _check_assignment_conflict(db, pa["resource_id"], pa["start_datetime"], pa["end_datetime"])
            if c:
                conflict_msg = f"conflitto con assignment #{c.id}"
                break
        if conflict_msg:
            failed.append({"date": occ_start.date().isoformat(), "error": conflict_msg})
            continue

        env_s = min(pa["start_datetime"] for pa in shifted)
        env_e = max(pa["end_datetime"] for pa in shifted)
        b = Booking(
            tenant_id=current_tenant_id(),
            job_id=pattern.job_id,
            job_cost_line_id=pattern.job_cost_line_id,
            start_datetime=env_s,
            end_datetime=env_e,
            status=pattern.status,
            kind=pattern.kind,
            notes=pattern.notes,
            priority=pattern.priority,
        )
        db.add(b); db.flush()
        for pa in shifted:
            db.add(BookingAssignment(
                booking_id=b.id,
                resource_id=pa["resource_id"],
                start_datetime=pa["start_datetime"],
                end_datetime=pa["end_datetime"],
            ))
        _log_change(
            db, b.id, "create",
            f"Estensione serie da booking #{pattern.id} ({recurrence_rule}, occ {occ_start.date()})",
            {"recurrence": recurrence_rule, "until": str(recurrence_until), "pattern_id": pattern.id},
        )
        created_ids.append(b.id)

    # Auto-assignment risorse → job (idempotente)
    if pattern.job_id and created_ids:
        try:
            from app.services.resource_assignment_sync import ensure_resources_assigned_to_job
            ensure_resources_assigned_to_job(
                db, pattern.job_id, [a.resource_id for a in pattern.assignments]
            )
        except Exception as e:
            print(f"[extend_as_series] auto-assignment failed: {e}")

    db.commit()
    return {
        "ok": len(created_ids),
        "failed": failed,
        "total_occurrences": len(occurrences),
        "pattern_date_skipped": skipped_pattern_day,
        "created_ids": created_ids,
    }


@router.put("/api/booking-assignments/{assignment_id}")
async def update_assignment(
    assignment_id: int,
    request: Request,
    resource_id: Optional[int] = Form(None),
    start_datetime: Optional[datetime] = Form(None),
    end_datetime: Optional[datetime] = Form(None),
    force_slice_unlock: bool = Depends(_force_unlock_dep),  # α.66.3 + α.111.23 admin-gate
    db: Session = Depends(get_db),
):
    """Aggiorna un singolo assignment (drag/resize/reassign del singolo item timeline)."""
    a = db.query(BookingAssignment).join(Booking).filter(
        BookingAssignment.id == assignment_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Assignment non trovato")
    new_rid = resource_id if resource_id is not None else a.resource_id
    _enforce_planning_scope(request, db, {a.resource_id, new_rid})
    new_s = start_datetime if start_datetime is not None else a.start_datetime
    new_e = end_datetime if end_datetime is not None else a.end_datetime
    if new_e <= new_s:
        raise HTTPException(400, "end_datetime deve essere > start_datetime")
    # v3.5.0-alpha.59 — HARD-BLOCK slice-lock current + new position.
    # v3.5.0-alpha.66.16.3 — sostituiti 2 blocchi inline con _assert_no_blocking_slice
    # + _assert_no_blocking_slice_for_dates (sprint R4 booking_mutate).
    _assert_no_blocking_slice(db, a.booking, force=force_slice_unlock)
    _assert_no_blocking_slice_for_dates(
        db, a.booking, new_s.date(), new_e.date(), force=force_slice_unlock,
    )
    # v3.5.0-alpha.66.5.2: il check cross-booking esclude TUTTI i fratelli
    # dello stesso booking (smart-split mattina+pomeriggio sulla stessa
    # risorsa = fratelli legittimi, non conflitti).
    c = _check_assignment_conflict(
        db, new_rid, new_s, new_e,
        exclude_assignment_id=assignment_id,
        exclude_booking_id=a.booking_id,
    )
    if c:
        raise HTTPException(409, f"Conflitto con assignment #{c.id}")
    # Check intra-booking dedicato: se il drag/resize porta a un OVERLAP
    # STRETTO con un fratello sulla stessa risorsa nel medesimo booking,
    # blocca (è il caso "duplicate-overlap" pre-α.63 che vogliamo evitare).
    # I segmenti contigui (end == start fratello) restano permessi.
    sib_overlap = db.query(BookingAssignment).filter(
        BookingAssignment.booking_id == a.booking_id,
        BookingAssignment.id != assignment_id,
        BookingAssignment.resource_id == new_rid,
        BookingAssignment.start_datetime < new_e,
        BookingAssignment.end_datetime > new_s,
    ).first()
    if sib_overlap:
        raise HTTPException(
            409,
            f"Sovrapposizione con segmento dello stesso booking "
            f"(#{sib_overlap.id}): {sib_overlap.start_datetime.strftime('%H:%M')}–"
            f"{sib_overlap.end_datetime.strftime('%H:%M')}. Sposta o "
            f"ridimensiona quel segmento prima."
        )
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
    # v3.5.0-alpha.9: drag/resize singolo assignment cambia man-hours →
    # se il booking era done, ricomputo la cost line.
    if a.booking and a.booking.execution_status == BookingExecutionStatus.done:
        try:
            from app.services.cost_line_sync import recompute_for_booking
            recompute_for_booking(db, a.booking)
        except Exception as e:
            print(f"[update_assignment] cost line sync failed: {e}")
    # v3.5.0-alpha.11: reassign (cambio resource_id) su booking con job →
    # garantisce che la nuova risorsa sia assegnata al job. Idempotente.
    if a.booking and a.booking.job_id:
        try:
            from app.services.resource_assignment_sync import ensure_resource_assigned_to_job
            ensure_resource_assigned_to_job(db, a.booking.job_id, a.resource_id)
        except Exception as e:
            print(f"[update_assignment] auto-assignment failed: {e}")
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
    # v3.5.0-alpha.32: cross-department warning. Non blocca il save (il client
    # ha già confermato in onMove). Il client lo usa per registrare audit/log
    # e per refresh badge persistente ⚠ sull'item dopo il drop.
    cd = _dept_mismatch_payload(db, a.booking, a.resource_id)
    if cd:
        out["cross_department"] = cd
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


@router.post("/api/bookings/{booking_id}/assignments")
async def add_assignment_to_booking(
    booking_id: int,
    request: Request,
    resource_id: int = Form(...),
    start_datetime: datetime = Form(...),
    end_datetime: datetime = Form(...),
    role: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.18: aggiunge un assignment singolo a un booking esistente.

    Pensato come tassello per undo/redo (ripristinare un assignment cancellato)
    e per bulk-edit "duplica risorsa". Il PUT /api/bookings/{id} resta il modo
    canonico per definire l'intero set di assignments in un'unica transazione;
    qui invece si aggiunge solo 1 riga senza toccare le altre.
    """
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    _enforce_planning_scope(request, db, {resource_id})
    if end_datetime <= start_datetime:
        raise HTTPException(400, "end_datetime deve essere > start_datetime")
    c = _check_assignment_conflict(db, resource_id, start_datetime, end_datetime)
    if c:
        raise HTTPException(409, f"Conflitto con assignment #{c.id}")
    res = db.query(Resource).filter(Resource.id == resource_id).first()
    if not res:
        raise HTTPException(404, "Risorsa non trovata")
    a = BookingAssignment(
        booking_id=booking_id,
        resource_id=resource_id,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        role=role,
    )
    db.add(a)
    db.flush()
    _recalc_booking_envelope(b)
    # Se il booking era cancelled e l'assignment lo riattiva → ripristina status.
    # v3.5.0-alpha.66.5.1: sync anche state (canonico).
    if b.status == BookingStatus.cancelled:
        b.status = BookingStatus.confirmed
        b.state = BookingState.confirmed
    if b.job_id:
        try:
            from app.services.resource_assignment_sync import ensure_resource_assigned_to_job
            ensure_resource_assigned_to_job(db, b.job_id, resource_id)
        except Exception as e:
            print(f"[add_assignment_to_booking] auto-assignment failed: {e}")
    if b.execution_status == BookingExecutionStatus.done:
        try:
            from app.services.cost_line_sync import recompute_for_booking
            recompute_for_booking(db, b)
        except Exception as e:
            print(f"[add_assignment_to_booking] cost line sync failed: {e}")
    db.commit()
    db.refresh(a)
    return {
        "id": a.id, "booking_id": a.booking_id, "resource_id": a.resource_id,
        "start_datetime": a.start_datetime.isoformat(),
        "end_datetime": a.end_datetime.isoformat(),
        "role": a.role,
    }


def _parse_hhmm(s: Optional[str]) -> Optional[tuple[int, int]]:
    """Parse 'HH:MM' → (h, m). None se vuoto/malformato."""
    if not s:
        return None
    try:
        h, m = s.split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return (h, m)
    except (ValueError, AttributeError):
        pass
    return None


@router.put("/api/bookings/{booking_id}/bulk-edit")
async def bulk_edit_bookings(
    booking_id: int,
    request: Request,
    booking_ids: str = Form(...),  # CSV "1,2,3"
    shift_minutes: Optional[int] = Form(None),
    # v3.5.0-alpha.66.5.1: parametro CANONICO è ora `state` (BookingState 5+1).
    # `execution_status` è deprecated alias per back-compat (non usato dalla UI).
    state: Optional[str] = Form(None),
    not_done_reason: Optional[str] = Form(None),
    execution_status: Optional[str] = Form(None),  # DEPRECATED
    # alpha.38: nuovi parametri per estendere la modifica in blocco
    new_start_date: Optional[date] = Form(None),
    absolute_start_time: Optional[str] = Form(None),  # "HH:MM"
    absolute_end_time: Optional[str] = Form(None),    # "HH:MM"
    # alpha.63: cambio lavorazione (e di conseguenza job) per i booking selezionati
    job_cost_line_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.18+α.38: applica modifiche in blocco a più booking.

    Il `booking_id` nel path identifica il "primario" (coerenza con altri
    endpoint pattern), ma le modifiche vengono applicate a TUTTI i booking
    elencati in `booking_ids` (CSV).

    Operazioni temporali supportate (applicate in QUESTO ORDINE su ciascun
    booking, poi check conflict UNA volta):
      1. `new_start_date`: sposta tutti i booking del delta giornaliero
         (`new_start_date - earliest_start_date_among_bookings`). Usato per
         "ripianificare" un blocco di lavoro a partire da una nuova data
         mantenendo la cadenza relativa tra i singoli booking.
      2. `shift_minutes`: shift relativo aggiuntivo (minuti, +/-).
      3. `absolute_start_time` / `absolute_end_time`: imposta l'orario
         assoluto del giorno (formato HH:MM). Mantiene la data risultante
         dai passi 1+2; sostituisce ore:minuti su start e/o end. Se valorizzati
         entrambi e end < start, il booking viene saltato come errore.

    Operazione di stato:
      4. `execution_status`: applica lo stesso stato (todo/started/done/not_done).
         Se "done", triggera il cost line sync.

    Conflitti orari rilevati DOPO i passi 1+2+3 → il booking viene saltato.
    """
    ids = [int(x.strip()) for x in (booking_ids or "").split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(400, "booking_ids vuoto o malformato")

    # v3.5.0-alpha.66.5.1: validazione state (canonico) con fallback su
    # execution_status legacy. Allineato a BookingState 5+1.
    target_state = None
    if state:
        try:
            target_state = BookingState(state)
        except ValueError:
            raise HTTPException(400, f"state non valido: {state}")
    elif execution_status:
        # Mappa legacy execution_status → BookingState (per back-compat).
        # Old UI usava todo/started/done/not_done che NON esistono nell'enum
        # BookingExecutionStatus reale (planned/in_progress/done/not_done) →
        # bug pre-α.66.5.1. Ora accettiamo entrambe le forme.
        legacy_to_state = {
            "todo": BookingState.confirmed, "planned": BookingState.confirmed,
            "started": BookingState.in_progress, "in_progress": BookingState.in_progress,
            "done": BookingState.done,
            "not_done": BookingState.not_done,
        }
        target_state = legacy_to_state.get(execution_status)
        if not target_state:
            raise HTTPException(400, f"execution_status non valido: {execution_status}")
    if target_state == BookingState.not_done and not (not_done_reason or "").strip():
        raise HTTPException(400, "Motivazione obbligatoria per stato 'Non fatto' (Form not_done_reason)")

    abs_start = _parse_hhmm(absolute_start_time)
    abs_end = _parse_hhmm(absolute_end_time)
    if absolute_start_time and not abs_start:
        raise HTTPException(400, f"absolute_start_time malformato (atteso HH:MM): {absolute_start_time}")
    if absolute_end_time and not abs_end:
        raise HTTPException(400, f"absolute_end_time malformato (atteso HH:MM): {absolute_end_time}")

    bookings = db.query(Booking).filter(
        Booking.id.in_(ids),
        Booking.tenant_id == current_tenant_id(),
    ).all()
    if not bookings:
        raise HTTPException(404, "Nessun booking trovato")
    # RBAC: scope su tutte le risorse coinvolte
    all_rids = set()
    for b in bookings:
        for a in b.assignments:
            all_rids.add(a.resource_id)
    _enforce_planning_scope(request, db, all_rids)

    # Se è richiesto new_start_date: calcola il delta giornaliero rispetto al
    # booking più "antico" tra quelli selezionati (per mantenere la cadenza
    # relativa). Applichiamo lo stesso delta a tutti.
    days_delta: Optional[timedelta] = None
    if new_start_date:
        earliest_dt = None
        for b in bookings:
            for a in b.assignments:
                if earliest_dt is None or a.start_datetime < earliest_dt:
                    earliest_dt = a.start_datetime
        if earliest_dt is not None:
            days_delta = timedelta(days=(new_start_date - earliest_dt.date()).days)

    minute_delta = timedelta(minutes=shift_minutes) if shift_minutes else None

    # v3.5.0-alpha.63 — cambio lavorazione (e job) bulk. Risolve la cost_line
    # una volta sola, deriva il job_id, valida che la lavorazione sia attiva
    # nel tenant. Le modifiche vengono applicate per booking nello stesso
    # giro di check (skip se locked, log error se cost_line non valida).
    new_cost_line = None
    new_job_id_from_cl: Optional[int] = None
    if job_cost_line_id is not None:
        new_cost_line = db.query(JobCostLine).join(Job).join(Project).filter(
            JobCostLine.id == job_cost_line_id,
            Project.tenant_id == current_tenant_id(),
        ).first()
        if not new_cost_line:
            raise HTTPException(404, f"Lavorazione #{job_cost_line_id} non trovata")
        new_job_id_from_cl = new_cost_line.job_id

    ok_count = 0
    failed_ids: list[dict] = []
    # v3.5.0-alpha.59 — pre-check slice lock su tutti i booking selezionati.
    # Se ANCHE UNO solo è dentro un periodo già fatturato, lo escludiamo
    # dalla bulk-edit (lo skippiamo come failed) per non corrompere lo
    # snapshot fattura. Operazione bulk continua sui restanti.
    from app.services.billing_slice_guard import find_blocking_slice
    locked_bookings: dict[int, dict] = {}
    for _b in bookings:
        s = find_blocking_slice(db, _b)
        if s is not None:
            locked_bookings[_b.id] = {
                "slice_id": s.id,
                "period_start": s.period_start.isoformat(),
                "period_end": s.period_end.isoformat(),
                "invoice_number": (s.invoice.number if s.invoice else None),
            }
    skipped_locked_count = 0
    for b in bookings:
        if b.id in locked_bookings:
            sl = locked_bookings[b.id]
            human = (
                f"Booking dentro periodo già fatturato "
                f"({sl['period_start']} → {sl['period_end']}"
                + (f", fattura {sl['invoice_number']}" if sl.get('invoice_number') else "")
                + ")"
            )
            failed_ids.append({
                "id": b.id, "error": "BOOKING_LOCKED_BY_SLICE",
                "reason": human,
                "slice": locked_bookings[b.id],
            })
            skipped_locked_count += 1
            continue
        try:
            # Calcola tutti i nuovi orari in una list, check conflict, poi commit
            updates: list[tuple] = []  # (assignment, new_start, new_end)
            for a in b.assignments:
                ns = a.start_datetime
                ne = a.end_datetime
                if days_delta is not None:
                    ns = ns + days_delta
                    ne = ne + days_delta
                if minute_delta is not None:
                    ns = ns + minute_delta
                    ne = ne + minute_delta
                if abs_start is not None:
                    ns = ns.replace(hour=abs_start[0], minute=abs_start[1], second=0, microsecond=0)
                if abs_end is not None:
                    ne = ne.replace(hour=abs_end[0], minute=abs_end[1], second=0, microsecond=0)
                if ne <= ns:
                    raise ValueError(f"end <= start dopo le modifiche (assignment #{a.id})")
                updates.append((a, ns, ne))

            # Check conflict su tutti i nuovi orari.
            # v3.5.0-alpha.66.5.2: esclude TUTTI i fratelli del booking
            # corrente dal check cross-booking (smart-split = fratelli leciti).
            conflict_msg = None
            for (a, ns, ne) in updates:
                c = _check_assignment_conflict(
                    db, a.resource_id, ns, ne,
                    exclude_assignment_id=a.id,
                    exclude_booking_id=b.id,
                )
                if c:
                    conflict_msg = f"#{a.id} → conflitto con #{c.id}"
                    break
            if conflict_msg:
                failed_ids.append({"id": b.id, "error": conflict_msg})
                continue
            # Check intra-booking: dopo le modifiche, ci sono fratelli sulla
            # stessa risorsa con OVERLAP stretto? (Caso bulk absolute_start/end
            # che collasserebbe i segmenti smart-split su orari identici.)
            intra_dup = None
            for i in range(len(updates)):
                for j in range(i + 1, len(updates)):
                    a_i, s_i, e_i = updates[i]
                    a_j, s_j, e_j = updates[j]
                    if a_i.resource_id != a_j.resource_id:
                        continue
                    if s_i < e_j and s_j < e_i:
                        intra_dup = (a_i.id, a_j.id)
                        break
                if intra_dup:
                    break
            if intra_dup:
                failed_ids.append({
                    "id": b.id,
                    "error": f"Segmenti smart-split #{intra_dup[0]} e #{intra_dup[1]} "
                             "diventerebbero sovrapposti (stesso orario assoluto applicato a "
                             "tutti i segmenti). Rimuovi un segmento o usa shift relativo."
                })
                continue

            # Commit modifiche temporali
            if updates and (days_delta is not None or minute_delta is not None
                            or abs_start is not None or abs_end is not None):
                for (a, ns, ne) in updates:
                    a.start_datetime = ns
                    a.end_datetime = ne
                _recalc_booking_envelope(b)
                # v3.5.0-alpha.114 — Q5 ROOT CAUSE FIX: shift temporale su
                # booking GIÀ done aggiornava timestamp ma NON ricomputava
                # total_accrued della JCL (recompute era gated su
                # target_state==done, che è None per pure-temporal shift).
                # Sintomo: lista CR mostrava maturato vecchio finché user
                # non apriva dettaglio (che ha auto-reconcile).
                if b.execution_status == BookingExecutionStatus.done and b.job_cost_line_id:
                    try:
                        from app.services.cost_line_sync import recompute_for_booking
                        recompute_for_booking(db, b)
                    except Exception as e:
                        print(f"[bulk_edit] cost sync (temporal-shift on done) failed for #{b.id}: {e}")

            # v3.5.0-alpha.66.5.1: applica state via apply_state_to_booking
            # (sincronizza state + status + execution_status atomicamente).
            if target_state is not None:
                from app.services.booking_state import apply_state_to_booking
                apply_state_to_booking(b, target_state)
                if target_state == BookingState.not_done:
                    b.not_done_reason = (not_done_reason or "").strip()
                else:
                    b.not_done_reason = None
                    if b.count_in_costs:
                        b.count_in_costs = False
                if target_state == BookingState.done:
                    try:
                        from app.services.cost_line_sync import recompute_for_booking
                        recompute_for_booking(db, b)
                    except Exception as e:
                        print(f"[bulk_edit] cost sync failed for #{b.id}: {e}")

            # v3.5.0-alpha.63 — cambio job_cost_line_id (e job_id) per il booking
            if new_cost_line is not None:
                old_cl_id = b.job_cost_line_id
                old_was_done = (b.execution_status == BookingExecutionStatus.done)
                b.job_cost_line_id = new_cost_line.id
                b.job_id = new_job_id_from_cl
                if b.kind not in (BookingKind.project,):
                    b.kind = BookingKind.project
                # Se done, ricalcola man-hours sia per la VECCHIA che per la NUOVA cost_line
                if old_was_done:
                    try:
                        from app.services.cost_line_sync import recompute_for_booking, recompute_cost_line_actual
                        if old_cl_id:
                            old_jcl = db.query(JobCostLine).filter(JobCostLine.id == old_cl_id).first()
                            if old_jcl:
                                recompute_cost_line_actual(db, old_jcl)
                        recompute_for_booking(db, b)
                    except Exception as e:
                        print(f"[bulk_edit] cost sync (job-change) failed for #{b.id}: {e}")
                # Auto-assignment delle risorse al nuovo job
                if b.job_id:
                    try:
                        from app.services.resource_assignment_sync import ensure_resources_assigned_to_job
                        ensure_resources_assigned_to_job(
                            db, b.job_id, [a.resource_id for a in b.assignments]
                        )
                    except Exception as e:
                        print(f"[bulk_edit] auto-assignment (job-change) failed for #{b.id}: {e}")
                _log_change(
                    db, b.id, "update",
                    f"Cambio lavorazione bulk: {old_cl_id} → {new_cost_line.id}",
                    {"job_cost_line_id": new_cost_line.id, "job_id": new_job_id_from_cl,
                     "previous_job_cost_line_id": old_cl_id},
                )
            ok_count += 1
        except Exception as e:
            # v3.5.0-alpha.63 — reason leggibile: error tecnico per log,
            # reason umano per UI panel.
            failed_ids.append({"id": b.id, "error": str(e), "reason": str(e)})

    db.commit()
    # v3.5.0-alpha.63 — aggiungi reason umana ai conflitti orari (string error
    # tipo "#42 → conflitto con #99"); UI usa `reason` per il pannello esiti.
    for f in failed_ids:
        if "reason" not in f and f.get("error"):
            err = f["error"]
            if "conflitto" in err or "→" in err:
                f["reason"] = f"Conflitto orario: {err}"
            else:
                f["reason"] = err
    return {
        "ok": ok_count,
        "failed": failed_ids,
        "skipped_locked_count": skipped_locked_count,
        "total": len(bookings),
    }


@router.get("/api/bookings/bulk-edit/eligible-cost-lines")
async def bulk_edit_eligible_cost_lines(
    ids: str,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.63 — ritorna le lavorazioni candidate per un cambio
    bulk del job_cost_line_id su un set di booking.

    Logica:
      - Se TUTTI i booking selezionati appartengono allo stesso progetto →
        ritorna le JobCostLine attive di quel progetto (cross-job nello
        stesso project sono possibili — più job, più quote).
      - Se progetti diversi → `same_project=False` e `lines=[]`. La UI deve
        mostrare un avviso ("seleziona booking dello stesso progetto").
      - I booking interni (job_id NULL) vengono ignorati ai fini del check
        progetto comune.
    """
    booking_ids = [int(x.strip()) for x in (ids or "").split(",") if x.strip().isdigit()]
    if not booking_ids:
        return {"same_project": False, "project_id": None, "lines": []}

    bookings = db.query(Booking).options(
        joinedload(Booking.job),
    ).filter(
        Booking.id.in_(booking_ids),
        Booking.tenant_id == current_tenant_id(),
    ).all()
    project_ids = {b.job.project_id for b in bookings if b.job and b.job.project_id is not None}
    if not project_ids or len(project_ids) > 1:
        return {
            "same_project": len(project_ids) == 1,
            "project_id": (next(iter(project_ids)) if len(project_ids) == 1 else None),
            "lines": [],
            "reason": (
                "MULTI_PROJECT" if len(project_ids) > 1
                else ("NO_PROJECT" if not project_ids else "OK")
            ),
        }

    pid = next(iter(project_ids))
    # Lavorazioni di tutti i job del progetto (Project è il guard del tenant)
    rows = (
        db.query(JobCostLine, Job)
        .join(Job, JobCostLine.job_id == Job.id)
        .join(Project, Job.project_id == Project.id)
        .filter(Job.project_id == pid, Project.tenant_id == current_tenant_id())
        .order_by(Job.code, JobCostLine.id)
        .all()
    )
    out = []
    for cl, j in rows:
        out.append({
            "id": cl.id,
            "description": cl.description,
            "unit": cl.unit,
            "quantity_quoted": cl.quantity_quoted,
            "quantity_actual": cl.quantity_actual,
            "job_id": j.id,
            "job_code": j.code,
            "job_title": j.title,
        })
    return {
        "same_project": True,
        "project_id": pid,
        "lines": out,
    }


@router.post("/api/multi-move")
async def multi_move_assignments(
    request: Request,
    moves: str = Form(...),  # JSON array
    force_slice_unlock: bool = Depends(_force_unlock_dep),  # α.66.3 + α.111.23 admin-gate
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.42: multi-move atomico transazionale.

    Sostituisce il pattern frammentato pre-α.42 (1 PUT + N PUT split-pause +
    1 bulk-edit) che produceva: conflitti spurii (check su stato intermedio),
    sparizioni visive (render parziale post-azione), undo polverizzato in
    N step (split sibling non tracciato), rollback impossibile.

    Input — `moves`: JSON array di
        [{
          "assignment_id": int,
          "new_start": ISO8601 string,   # "YYYY-MM-DDTHH:MM:SS"
          "new_end":   ISO8601 string,
          "new_resource_id": int        # opzionale; default = resource_id corrente
        }, ...]

    Comportamento:
      - All-or-nothing. Se anche un solo move va in conflitto → HTTP 409
        con dettaglio del conflict, NESSUNA modifica applicata.
      - Conflict check escludendo TUTTI gli assignment_id della transazione
        (no falsi positivi: gli assignment in modifica nello stesso gesto
        non si "vedono" tra loro come conflitto).
      - Recalcola Booking envelope per tutti i booking coinvolti.
      - Restituisce snapshot pre-move per ogni assignment (per undo client-side
        atomico) + snapshot post-move.

    Niente cost line sync qui (le ore non cambiano, solo la finestra temporale
    + risorsa). Cross-resource cambia resource_id → eventuale dept change è
    a discrezione UI (badge cross-dept gestito client-side).
    """
    try:
        moves_list = _json.loads(moves)
        if not isinstance(moves_list, list) or not moves_list:
            raise ValueError("moves deve essere un array JSON non vuoto")
    except Exception as e:
        raise HTTPException(400, f"moves malformato: {e}")

    # Parse + validazione di ogni entry
    parsed: list[dict] = []
    for i, m in enumerate(moves_list):
        if not isinstance(m, dict):
            raise HTTPException(400, f"moves[{i}] non è un oggetto")
        try:
            aid = int(m["assignment_id"])
            ns = datetime.fromisoformat(m["new_start"])
            ne = datetime.fromisoformat(m["new_end"])
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(400, f"moves[{i}] campi mancanti/invalidi: {e}")
        if ne <= ns:
            raise HTTPException(400, f"moves[{i}] (assignment {aid}): end <= start")
        new_rid = m.get("new_resource_id")
        if new_rid is not None:
            try:
                new_rid = int(new_rid)
            except (ValueError, TypeError):
                raise HTTPException(400, f"moves[{i}] new_resource_id non numerico")
        parsed.append({
            "assignment_id": aid,
            "new_start": ns,
            "new_end": ne,
            "new_resource_id": new_rid,
        })

    aids = [p["assignment_id"] for p in parsed]
    if len(set(aids)) != len(aids):
        raise HTTPException(400, "Duplicati in assignment_id")

    # Carica tutti gli assignments coinvolti (filtrati su tenant)
    assignments = db.query(BookingAssignment).join(Booking).filter(
        BookingAssignment.id.in_(aids),
        Booking.tenant_id == current_tenant_id(),
    ).all()
    by_id = {a.id: a for a in assignments}
    missing = [aid for aid in aids if aid not in by_id]
    if missing:
        raise HTTPException(404, f"Assignment non trovati: {missing}")

    # RBAC: scope su risorse originarie + risorse target
    all_rids: set[int] = set()
    for a in assignments:
        all_rids.add(a.resource_id)
    for p in parsed:
        if p["new_resource_id"] is not None:
            all_rids.add(p["new_resource_id"])
    _enforce_planning_scope(request, db, all_rids)

    # v3.5.0-alpha.59 — HARD-BLOCK se anche un solo assignment ricade dentro
    # un periodo già fatturato (pre o post move). All-or-nothing: niente
    # parziale.
    # v3.5.0-alpha.66.3: skip per tentative; bypass se force_slice_unlock=True.
    # v3.5.0-alpha.66.16.3 — Sprint R4: usa booking_mutate.assert_slice_lock_safe
    # invece dei 2 check inline duplicati. Pattern di response speciale
    # `success:false + dict` mantenuto per compat client (api() wrappa
    # HTTPException detail dict come "[object Object]").
    from app.services.booking_mutate import assert_slice_lock_safe, SliceLocked
    if not force_slice_unlock:
        for p in parsed:
            a = by_id[p["assignment_id"]]
            if a.booking.status == BookingStatus.tentative:
                continue  # tentative: liberamente movibile
            # Check posizione CORRENTE
            try:
                assert_slice_lock_safe(db, a.booking, force_unlock=False)
            except SliceLocked as e:
                return {
                    "success": False, "code": "SLICE_LOCK_CONFIRM_REQUIRED", "moved": 0,
                    "blocked_assignment_id": a.id, "blocked_booking_id": a.booking_id,
                    "slice": e.payload,
                    "hint": "Booking confermato in periodo fatturato. "
                            "Riinvia con force_slice_unlock=true per forzare.",
                }
            # Check posizione NUOVA
            try:
                assert_slice_lock_safe(
                    db, a.booking,
                    new_dates=(p["new_start"].date(), p["new_end"].date()),
                    force_unlock=False,
                )
            except SliceLocked as e:
                return {
                    "success": False, "code": "SLICE_LOCK_CONFIRM_REQUIRED", "moved": 0,
                    "blocked_assignment_id": a.id, "blocked_booking_id": a.booking_id,
                    "slice": e.payload,
                    "hint": "La nuova posizione cade in periodo fatturato. "
                            "Riinvia con force_slice_unlock=true per forzare.",
                }

    # Snapshot pre-move (per response al client per undo atomico)
    pre_snapshots = [{
        "assignment_id": a.id,
        "booking_id": a.booking_id,
        "start": a.start_datetime.isoformat(),
        "end": a.end_datetime.isoformat(),
        "resource_id": a.resource_id,
    } for a in assignments]

    # Conflict check ATOMICO: per ogni move, esclude TUTTI gli aids della transazione
    # (così assignment "in volo" non collidono tra loro).
    # v3.5.0-alpha.66.5.2: esclude anche i FRATELLI dello stesso booking (smart-split):
    # se l'utente sposta solo 1 segmento, l'altro fratello dello stesso booking NON
    # deve essere visto come conflitto cross-booking. Overlap intra-booking
    # gestito separatamente sotto.
    aids_set = set(aids)
    affected_booking_ids_for_check = {a.booking_id for a in assignments}
    for p in parsed:
        a = by_id[p["assignment_id"]]
        target_rid = p["new_resource_id"] if p["new_resource_id"] is not None else a.resource_id
        ns, ne = p["new_start"], p["new_end"]
        # Query: stesso pattern di _check_assignment_conflict ma con NOT IN
        # (sia su aids che su booking_ids della transazione).
        conflict = db.query(BookingAssignment).join(
            Booking, BookingAssignment.booking_id == Booking.id
        ).filter(
            Booking.tenant_id == current_tenant_id(),
            Booking.status != BookingStatus.cancelled,
            BookingAssignment.resource_id == target_rid,
            BookingAssignment.start_datetime < ne,
            BookingAssignment.end_datetime > ns,
            ~BookingAssignment.id.in_(aids_set),
            ~BookingAssignment.booking_id.in_(affected_booking_ids_for_check),
        ).first()
        if conflict:
            # All-or-nothing: niente commit. Ritorniamo 200 + success=false
            # invece di 409 perché l'helper `api()` client-side wrappa il
            # detail dict in "[object Object]" — più pulito esporre i campi
            # nel body OK.
            db.rollback()
            return {
                "success": False,
                "code": "conflict",
                "moved": 0,
                "conflict": {
                    "blocked_assignment_id": a.id,
                    "blocked_booking_id": a.booking_id,
                    "conflicts_with_assignment_id": conflict.id,
                    "conflicts_with_booking_id": conflict.booking_id,
                    "resource_id": target_rid,
                    "start": conflict.start_datetime.isoformat(),
                    "end": conflict.end_datetime.isoformat(),
                },
                "message": f"Assignment #{a.id} in conflitto con #{conflict.id} sulla risorsa #{target_rid}",
            }

    # v3.5.0-alpha.66.5.2: check intra-booking pre-commit. Costruisco lo
    # stato FINALE simulato per ogni booking toccato (fratelli che restano +
    # fratelli che si muovono con i NUOVI orari). Se uno stesso booking ha
    # 2+ assignment sulla stessa risorsa con OVERLAP stretto post-move,
    # blocca: è il caso "duplicate-overlap" pre-α.63.
    by_book_post: dict[int, list[dict]] = {}
    aids_in_move = {p["assignment_id"] for p in parsed}
    # Step 1: per ogni booking toccato, raccogli i fratelli che NON cambiano
    affected_booking_ids_for_check2 = {a.booking_id for a in assignments}
    if affected_booking_ids_for_check2:
        siblings_other = db.query(BookingAssignment).filter(
            BookingAssignment.booking_id.in_(affected_booking_ids_for_check2),
            ~BookingAssignment.id.in_(aids_in_move),
        ).all()
        for s in siblings_other:
            by_book_post.setdefault(s.booking_id, []).append({
                "id": s.id, "rid": s.resource_id,
                "start": s.start_datetime, "end": s.end_datetime,
            })
    # Step 2: aggiungi gli assignment in volo con i NUOVI orari/risorse
    for p in parsed:
        a = by_id[p["assignment_id"]]
        new_rid = p["new_resource_id"] if p["new_resource_id"] is not None else a.resource_id
        by_book_post.setdefault(a.booking_id, []).append({
            "id": a.id, "rid": new_rid,
            "start": p["new_start"], "end": p["new_end"],
        })
    # Step 3: pairwise overlap check intra-booking, stessa risorsa
    for bid, segs in by_book_post.items():
        n = len(segs)
        for i in range(n):
            for j in range(i + 1, n):
                if segs[i]["rid"] != segs[j]["rid"]:
                    continue
                if segs[i]["start"] < segs[j]["end"] and segs[j]["start"] < segs[i]["end"]:
                    return {
                        "success": False, "code": "INTRA_BOOKING_OVERLAP", "moved": 0,
                        "blocked_booking_id": bid,
                        "blocked_assignment_ids": [segs[i]["id"], segs[j]["id"]],
                        "message": (
                            f"Il move farebbe sovrapporre 2 segmenti dello stesso "
                            f"booking #{bid} sulla stessa risorsa "
                            f"(#{segs[i]['id']} e #{segs[j]['id']}). "
                            f"Sposta o ridimensiona uno dei due."
                        ),
                    }

    # Tutti OK → applica modifiche
    affected_booking_ids: set[int] = set()
    post_snapshots = []
    for p in parsed:
        a = by_id[p["assignment_id"]]
        a.start_datetime = p["new_start"]
        a.end_datetime = p["new_end"]
        if p["new_resource_id"] is not None and p["new_resource_id"] != a.resource_id:
            a.resource_id = p["new_resource_id"]
        affected_booking_ids.add(a.booking_id)
        post_snapshots.append({
            "assignment_id": a.id,
            "booking_id": a.booking_id,
            "start": a.start_datetime.isoformat(),
            "end": a.end_datetime.isoformat(),
            "resource_id": a.resource_id,
        })

    # Recalc envelope per ogni booking coinvolto
    if affected_booking_ids:
        bookings = db.query(Booking).filter(
            Booking.id.in_(affected_booking_ids),
            Booking.tenant_id == current_tenant_id(),
        ).all()
        for b in bookings:
            _recalc_booking_envelope(b)

    db.commit()
    return {
        "success": True,
        "moved": len(parsed),
        "pre": pre_snapshots,
        "post": post_snapshots,
        "affected_booking_ids": sorted(affected_booking_ids),
    }


@router.post("/api/booking-assignments/bulk-delete")
async def bulk_delete_assignments(
    request: Request,
    assignment_ids: Optional[str] = Form(None, description="CSV di assignment_id da cancellare"),
    booking_ids: Optional[str] = Form(None, description="CSV di booking_id (cancella TUTTE le assignment dei booking)"),
    force_slice_unlock: bool = Form(False, description="Admin gate: ignora JCLBilledSlice locks"),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.172.20 — Bulk delete assignment in singola transazione.

    Sostituisce loop client-side N delete con 1 call atomica. Cascade: se un
    booking perde l'ultimo assignment → booking.status=cancelled (allineato a
    `delete_assignment` single).

    Body Form:
    - `assignment_ids` (CSV): solo gli assignment specificati
    - `booking_ids` (CSV): tutti gli assignment dei booking listati (espansione
      server-side per evitare di mandare 100 id se il batch è grande)
    - `force_slice_unlock` (admin): bypass JCLBilledSlice HARD-BLOCK

    Validazione:
    - RBAC scope su union resource_ids
    - `_assert_no_blocking_slice` per ogni booking coinvolto (con force gate)
    - Tenant filter

    Response:
    {
      "ok": true,
      "deleted_assignments": N,
      "cancelled_bookings": M,
      "skipped_billed": K,        # booking saltati per slice lock
      "errors": []
    }
    """
    if not assignment_ids and not booking_ids:
        raise HTTPException(400, "Passa assignment_ids o booking_ids (almeno uno)")

    # Parse input
    def _csv_ints(s: Optional[str]) -> set[int]:
        if not s: return set()
        try:
            return {int(x.strip()) for x in s.split(",") if x.strip()}
        except ValueError:
            raise HTTPException(400, "ID non interi nel CSV")

    a_ids = _csv_ints(assignment_ids)
    b_ids = _csv_ints(booking_ids)

    # Espandi booking_ids → assignment_ids
    if b_ids:
        extra = db.query(BookingAssignment.id).join(Booking).filter(
            BookingAssignment.booking_id.in_(b_ids),
            Booking.tenant_id == current_tenant_id(),
        ).all()
        a_ids.update(e[0] for e in extra)

    if not a_ids:
        return {"ok": True, "deleted_assignments": 0, "cancelled_bookings": 0,
                "skipped_billed": 0, "errors": []}

    # Resolve assignments (tenant filtered via Booking join)
    assignments = db.query(BookingAssignment).join(Booking).filter(
        BookingAssignment.id.in_(a_ids),
        Booking.tenant_id == current_tenant_id(),
    ).all()
    if not assignments:
        return {"ok": True, "deleted_assignments": 0, "cancelled_bookings": 0,
                "skipped_billed": 0, "errors": []}

    # RBAC scope su tutte le risorse coinvolte
    _enforce_planning_scope(request, db, {a.resource_id for a in assignments})

    # Raggruppa per booking
    by_booking: dict[int, list[BookingAssignment]] = {}
    for a in assignments:
        by_booking.setdefault(a.booking_id, []).append(a)

    # Check JCLBilledSlice lock per booking
    skipped_bookings: set[int] = set()
    if not force_slice_unlock:
        for bid, ass_list in by_booking.items():
            booking = ass_list[0].booking
            try:
                _assert_no_blocking_slice(db, booking, force=False)
            except HTTPException as e:
                if e.status_code == 409:
                    skipped_bookings.add(bid)
                else:
                    raise

    deleted_assignments = 0
    cancelled_bookings = 0
    touched_bookings: list[Booking] = []

    for bid, ass_list in by_booking.items():
        if bid in skipped_bookings:
            continue
        booking = ass_list[0].booking
        for a in ass_list:
            db.delete(a)
            deleted_assignments += 1
        touched_bookings.append(booking)

    db.flush()

    # Per ogni booking touched: refresh + cascade cancelled se ultimo assignment
    for booking in touched_bookings:
        db.refresh(booking)
        if not booking.assignments:
            booking.status = BookingStatus.cancelled
            booking.state = BookingState.cancelled
            cancelled_bookings += 1
        else:
            _recalc_booking_envelope(booking)

    # Recompute cost lines per booking touched (man-hours cambiate)
    try:
        from app.services.cost_line_sync import recompute_for_booking
        for booking in touched_bookings:
            recompute_for_booking(db, booking)
    except Exception as e:
        print(f"[bulk_delete_assignments] cost line sync failed: {e}")

    # Audit log per booking
    for booking in touched_bookings:
        try:
            _log_change(
                db, booking.id,
                kind="bulk_delete_assignments",
                summary=f"Bulk delete: {len(by_booking.get(booking.id, []))} assignment rimosse",
                payload={"bulk": True},
            )
        except Exception:
            pass

    db.commit()
    return {
        "ok": True,
        "deleted_assignments": deleted_assignments,
        "cancelled_bookings": cancelled_bookings,
        "skipped_billed": len(skipped_bookings),
        "errors": [],
    }


@router.delete("/api/booking-assignments/{assignment_id}")
async def delete_assignment(
    assignment_id: int,
    request: Request,
    force_slice_unlock: bool = False,  # v3.5.0-alpha.66.3 (query param: ?force_slice_unlock=true)
    db: Session = Depends(get_db),
):
    """Cancella un singolo assignment. Se è l'ultimo del booking, cancella il booking intero.

    v3.5.0-alpha.9: triggera recompute della JobCostLine. Senza questa chiamata
    il cost report mostrava il maturato fantasma post-eliminazione (le ore
    dell'assignment cancellato restavano congelate in `quantity_actual`).
    """
    a = db.query(BookingAssignment).join(Booking).filter(
        BookingAssignment.id == assignment_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Assignment non trovato")
    _enforce_planning_scope(request, db, {a.resource_id})
    _assert_no_blocking_slice(db, a.booking, force=force_slice_unlock)
    booking = a.booking
    db.delete(a)
    db.flush()
    db.refresh(booking)
    if not booking.assignments:
        booking.status = BookingStatus.cancelled
        booking.state = BookingState.cancelled  # v3.5.0-alpha.66.5.1
    else:
        _recalc_booking_envelope(booking)
    # Sync cost line: se il booking era done, le man-hours cambiano (-1 risorsa).
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, booking)
    except Exception as e:
        print(f"[delete_assignment] cost line sync failed: {e}")
    db.commit()
    # v3.5.0-alpha.172.21 — booking_id nel response per UI refresh incrementale.
    return {
        "ok": True,
        "booking_id": booking.id,
        "booking_cancelled": not bool(booking.assignments),
    }


@router.delete("/api/bookings/{booking_id}")
async def delete_booking(
    booking_id: int,
    request: Request,
    force_slice_unlock: bool = False,  # v3.5.0-alpha.66.3
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.9: chiama recompute_for_booking dopo lo soft-delete per
    far ritirare le ore dal `total_accrued` della cost line collegata. La
    query in `recompute_cost_line_actual` filtra `status != cancelled`, quindi
    il booking appena cancellato non rientra più nel totale."""
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    _enforce_planning_scope(request, db, {a.resource_id for a in b.assignments})
    _assert_no_blocking_slice(db, b, force=force_slice_unlock)
    b.status = BookingStatus.cancelled
    b.state = BookingState.cancelled  # v3.5.0-alpha.66.5.1
    _log_change(db, b.id, "delete", "Booking eliminato (soft)", None)
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as e:
        print(f"[delete_booking] cost line sync failed: {e}")
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
        Resource.tenant_id == current_tenant_id(),
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
            Booking.tenant_id == current_tenant_id(),
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
        Booking.tenant_id == current_tenant_id(),
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
# v3.5.0-alpha.66.20 — Endpoint estratti in `planning_unavailabilities.py`
# (sprint R7.x). Path esterni invariati (/planning/api/unavailabilities/*,
# /planning/api/my-unavailabilities). Mount via main.py.

_LEGACY_UNAVAILABILITIES_RELOCATED = True  # marker per grep storici


@router.post("/api/bookings/{booking_id}/restore", dependencies=[RequireEditPlanningAll])
async def restore_booking(booking_id: int, db: Session = Depends(get_db)):
    """Ripristina un booking cancellato (per undo)."""
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
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
    b.state = BookingState.tentative  # v3.5.0-alpha.66.5.1
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
from app.context import current_tenant_id


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
        Booking.tenant_id == current_tenant_id(),
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


@router.patch("/api/bookings/{booking_id}/state")
async def update_booking_state(
    booking_id: int,
    request: Request,
    state: BookingState = Form(...),
    not_done_reason: Optional[str] = Form(None),
    force_slice_unlock: bool = Depends(_force_unlock_dep),  # α.111.23 admin-gate
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.66.5 — Cambio stato unificato del booking.

    Sostituisce concettualmente `PUT /api/bookings/{id}` (per status) e
    `PATCH /api/bookings/{id}/execution` (per execution_status). Riceve
    UN solo `state` (5 valori esclusivi + cancelled per soft-delete) e
    sincronizza `state` + `status` + `execution_status` coerentemente
    via `apply_state_to_booking()`.

    Transizioni libere (qualsiasi → qualsiasi). Su transizione a `not_done`
    richiede motivazione. Slice-lock: skip per tentative, conferma per
    confirmed/in_progress/done/not_done.
    """
    from app.services.booking_state import apply_state_to_booking, state_label

    b = db.query(Booking).options(joinedload(Booking.job)).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    if not _can_edit_booking_execution(request, db, b):
        raise HTTPException(403, "Non puoi modificare lo stato di questo booking")
    if state == BookingState.not_done and not (not_done_reason or "").strip():
        raise HTTPException(400, "Motivazione obbligatoria per stato 'Non fatto'")

    # Slice-lock check (skip per tentative; conferma per confirmed e oltre)
    _assert_no_blocking_slice(db, b, force=force_slice_unlock)

    user = current_user_optional(request)
    sync = apply_state_to_booking(b, state)
    if state == BookingState.not_done:
        b.not_done_reason = (not_done_reason or "").strip()
    else:
        b.not_done_reason = None
        # Invariante v3.4.38: count_in_costs ↔ not_done (pool). Reset se non più not_done.
        if b.count_in_costs:
            b.count_in_costs = False

    summary_text = f"Stato: {state_label(sync['old_state'])} → {state_label(state)}"
    _log_change(db, b.id, "state", summary_text, sync)

    # Sync cost-line: ogni cambio di state che impatta on/off "done" tocca le ore
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as e:
        print(f"[update_booking_state] cost line sync failed: {e}")
    db.commit()
    db.refresh(b)

    # Notifiche selettive: solo done/not_done emettono notifica (allineato con
    # update_booking_execution legacy). Pattern notify_role su producer/manager.
    if state in (BookingState.done, BookingState.not_done):
        from app.services import notifications as notif_svc
        from app.models import NotificationKind, NotificationSeverity
        is_not_done = (state == BookingState.not_done)
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
                payload={"booking_id": b.id, "state": state.value},
            )
        except Exception as e:
            print(f"[update_booking_state] notify failed: {e}")
    return {
        "id": b.id,
        "state": b.state.value,
        "status": b.status.value,
        "execution_status": b.execution_status.value,
        "not_done_reason": b.not_done_reason,
    }


@router.patch("/api/bookings/{booking_id}/execution")
async def update_booking_execution(
    booking_id: int,
    request: Request,
    execution_status: BookingExecutionStatus = Form(...),
    not_done_reason: Optional[str] = Form(None),
    force_slice_unlock: bool = Depends(_force_unlock_dep),  # α.66.3 + α.111.23 admin-gate
    db: Session = Depends(get_db),
):
    """Cambio stato esecuzione del booking. Su not_done richiede motivazione.
    Su transizione → done o → not_done emette notifica a producer/manager.
    Su → in_progress: silenzio (rumore)."""
    b = db.query(Booking).options(joinedload(Booking.job)).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    if not _can_edit_booking_execution(request, db, b):
        raise HTTPException(403, "Non puoi modificare lo stato di questo booking")
    if execution_status == BookingExecutionStatus.not_done and not (not_done_reason or "").strip():
        raise HTTPException(400, "Motivazione obbligatoria per stato 'Non fatto'")
    # v3.5.0-alpha.59 — HARD-BLOCK se booking dentro periodo già fatturato.
    # Cambiare execution_status su un booking slice-ato modifica
    # `total_accrued` della JCL → invalida lo snapshot in fattura.
    # v3.5.0-alpha.66.3: skip per tentative; bypass se force_slice_unlock.
    _assert_no_blocking_slice(db, b, force=force_slice_unlock)

    user = current_user_optional(request)
    old_status = b.execution_status
    b.execution_status = execution_status
    # v3.5.0-alpha.66.5: sincronizza state. Se execution_status passa a in_progress/
    # done/not_done e status era tentative, promuovo a confirmed (transizione
    # implicita). state si ricalcola coerente.
    from app.models import compute_state_from_legacy, BookingStatus as _BS
    if execution_status in (BookingExecutionStatus.in_progress,
                            BookingExecutionStatus.done,
                            BookingExecutionStatus.not_done):
        if b.status == _BS.tentative:
            b.status = _BS.confirmed
    b.state = compute_state_from_legacy(b.status.value, b.execution_status.value)
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

    # v3.5.0-alpha.172.89 (Bundle I) — hook auto-bump deliverable a in_progress
    # quando booking linkato passa a in_progress E deliverable e' ancora planned.
    # Idempotente: skip se deliverable gia' in stato != planned (no clobber).
    if execution_status == BookingExecutionStatus.in_progress:
        try:
            from app.models import BookingDeliverable, JobDeliverable, DeliverableStatus
            pivots = db.query(BookingDeliverable, JobDeliverable).join(
                JobDeliverable, JobDeliverable.id == BookingDeliverable.job_deliverable_id
            ).filter(
                BookingDeliverable.booking_id == b.id,
                JobDeliverable.status == DeliverableStatus.planned,
                JobDeliverable.deleted_at.is_(None),
            ).all()
            for _piv, deliv in pivots:
                deliv.status = DeliverableStatus.in_progress
                _log_change(db, b.id, "deliverable_auto_bump",
                            f"Deliverable #{deliv.id} → in_progress (trigger booking)",
                            {"deliverable_id": deliv.id, "old": "planned", "new": "in_progress"})
        except Exception as e:
            print(f"[update_booking_execution] deliverable auto-bump failed: {e}")

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
        Booking.tenant_id == current_tenant_id(),
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
        Booking.tenant_id == current_tenant_id(),
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
        Booking.tenant_id == current_tenant_id(),
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

@router.get("/api/project-bookings")
async def project_bookings(
    request: Request,
    project_id: int,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    resource_id: Optional[str] = None,
    department_id: Optional[str] = None,    # v3.5.0-alpha.171.7 (TL-4)
    job_id: Optional[str] = None,           # v3.5.0-alpha.171.7 (TL-4)
    job_cost_line_id: Optional[str] = None, # v3.5.0-alpha.171.7 (TL-4)
    kind: Optional[BookingKind] = None,     # v3.5.0-alpha.171.7 (TL-4)
    status: Optional[BookingStatus] = None, # v3.5.0-alpha.171.7 (TL-4)
    search_q: Optional[str] = Query(None, alias="q"),  # v3.5.0-alpha.171.7 (TL-4+TL-5)
    db: Session = Depends(get_db),
):
    """v3.4.44 — Booking di un progetto, formato come "Le mie" ma con info
    risorsa visibile.

    v3.5.0-alpha.13: filtro `resource_id` (csv).
    v3.5.0-alpha.171.7 (TL-4): aggiunti `department_id`, `job_id`,
    `job_cost_line_id`, `kind`, `status`, `q` (search testuale) per coerenza
    con `/api/bookings`. Pre-fix la vista "Per progetto" ignorava tutti i
    filtri sidebar tranne resource_id.
    """
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Non autenticato")
    from app.services.rbac import is_admin, is_manager, is_producer, has_permission
    if not (is_admin(user) or is_manager(user) or is_producer(user) or has_permission(user, "edit_planning")):
        raise HTTPException(403, "Vista riservata a manager / producer / admin")

    q = db.query(BookingAssignment).options(
        joinedload(BookingAssignment.resource),
        joinedload(BookingAssignment.booking).joinedload(Booking.job).joinedload(Job.project),
        joinedload(BookingAssignment.booking).joinedload(Booking.cost_line),
    ).join(Booking, BookingAssignment.booking_id == Booking.id).join(
        Job, Booking.job_id == Job.id
    ).filter(
        Booking.tenant_id == current_tenant_id(),
        Job.project_id == project_id,
        Booking.status != BookingStatus.cancelled,
    )
    if from_date:
        q = q.filter(BookingAssignment.end_datetime >= from_date)
    if to_date:
        q = q.filter(BookingAssignment.start_datetime <= to_date)
    rid_list = _parse_id_list(resource_id)
    if rid_list:
        q = q.filter(BookingAssignment.resource_id.in_(rid_list))
    # v3.5.0-alpha.171.7 (TL-4) — filtri sidebar planning estesi
    job_ids = _parse_id_list(job_id)
    dept_ids = _parse_id_list(department_id)
    jcl_ids = _parse_id_list(job_cost_line_id)
    if job_ids:
        q = q.filter(Booking.job_id.in_(job_ids))
    if dept_ids:
        q = q.join(Resource, BookingAssignment.resource_id == Resource.id).filter(
            Resource.department_id.in_(dept_ids)
        )
    if jcl_ids:
        q = q.filter(Booking.job_cost_line_id.in_(jcl_ids))
    if kind:
        q = q.filter(Booking.kind == kind)
    if status:
        q = q.filter(Booking.status == status)
    if search_q and search_q.strip():
        from sqlalchemy import or_ as _or, func as _func
        from app.models import PriceItem as _PI
        search = f"%{search_q.strip().lower()}%"
        q = (
            q.outerjoin(JobCostLine, Booking.job_cost_line_id == JobCostLine.id)
            .outerjoin(_PI, JobCostLine.price_item_id == _PI.id)
            .filter(_or(
                _func.lower(Booking.notes).like(search),
                _func.lower(JobCostLine.description).like(search),
                _func.lower(_PI.name).like(search),
                _func.lower(Job.code).like(search),
                _func.lower(Job.title).like(search),
            ))
        )
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
            "resource_id": a.resource_id,
            "resource_name": a.resource.name if a.resource else None,
            "resource_color": a.resource.color if a.resource else "#6272f5",
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


@router.get("/api/bookings/{booking_id}/detail")
async def booking_detail(booking_id: int, db: Session = Depends(get_db)):
    """v3.4.42 — dettaglio booking per modal "Le mie" / dashboard / drilldown.
    Ritorna info estese: assegnatari, job/lavorazione, priorità/stato/overtime,
    notes, motivazione not_done, timestamps.
    v3.5.0-alpha.22: aggiunte cliente, dipartimento per risorsa, ore già fatte
    sul job dalle altre prenotazioni done, last-edit timestamp, audit count."""
    b = db.query(Booking).options(
        joinedload(Booking.job).joinedload(Job.project).joinedload(Project.client),
        joinedload(Booking.job).joinedload(Job.client),
        joinedload(Booking.cost_line),
        joinedload(Booking.assignments).joinedload(BookingAssignment.resource).joinedload(Resource.department),
    ).filter(Booking.id == booking_id, Booking.tenant_id == current_tenant_id()).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    duration_min = int(round((b.end_datetime - b.start_datetime).total_seconds() / 60)) if b.start_datetime and b.end_datetime else 0

    # Cliente: prima prova client diretto sul Job, poi via Project.
    client_obj = None
    if b.job:
        if getattr(b.job, "client", None):
            client_obj = b.job.client
        elif getattr(b.job, "project", None) and getattr(b.job.project, "client", None):
            client_obj = b.job.project.client

    # Stats della lavorazione: somma ore done degli altri booking sulla stessa cost_line
    cl_done_hours = 0.0
    cl_total_planned_hours = 0.0
    if b.cost_line:
        sib_q = db.query(Booking).filter(
            Booking.tenant_id == current_tenant_id(),
            Booking.job_cost_line_id == b.cost_line.id,
            Booking.status != BookingStatus.cancelled,
        )
        for sb in sib_q.all():
            for a in sb.assignments:
                seg = (a.end_datetime - a.start_datetime).total_seconds() / 3600.0
                cl_total_planned_hours += seg
                if sb.execution_status == BookingExecutionStatus.done:
                    cl_done_hours += seg

    # v3.5.0-alpha.63 — rileva eventuali assignment duplicati per stessa
    # risorsa CON OVERLAP (residui pre-α.63: il guard intra-payload non
    # esisteva). Espone bandiera `has_duplicate_overlaps` + lista
    # `duplicate_resource_ids` per UI warning.
    duplicate_resource_ids: list[int] = []
    seen_by_res: dict[int, list[BookingAssignment]] = {}
    for a in b.assignments:
        seen_by_res.setdefault(a.resource_id, []).append(a)
    for rid, lst in seen_by_res.items():
        if len(lst) < 2:
            continue
        # check overlap a coppie (segmenti contigui non contano)
        lst_sorted = sorted(lst, key=lambda x: x.start_datetime)
        for i in range(len(lst_sorted) - 1):
            ai, aj = lst_sorted[i], lst_sorted[i + 1]
            if ai.start_datetime < aj.end_datetime and aj.start_datetime < ai.end_datetime:
                duplicate_resource_ids.append(rid)
                break

    # Audit count (booking_changes)
    audit_n = db.query(BookingChange).filter(BookingChange.booking_id == b.id).count()
    last_change = (
        db.query(BookingChange)
        .filter(BookingChange.booking_id == b.id)
        .order_by(BookingChange.created_at.desc())
        .first()
    )
    last_change_at = last_change.created_at.isoformat() if (last_change and last_change.created_at) else None

    return {
        "id": b.id,
        "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "priority": b.priority.value if hasattr(b.priority, "value") else (b.priority or "normal"),
        "execution_status": b.execution_status.value if hasattr(b.execution_status, "value") else (b.execution_status or "planned"),
        "overtime_status": b.overtime_status.value if hasattr(b.overtime_status, "value") else (b.overtime_status or "none"),
        "start_datetime": b.start_datetime.isoformat() if b.start_datetime else None,
        "end_datetime": b.end_datetime.isoformat() if b.end_datetime else None,
        "duration_minutes": duration_min,
        "duration_hours": round(duration_min / 60, 2),
        "notes": b.notes,
        "not_done_reason": b.not_done_reason,
        "count_in_costs": b.count_in_costs,
        "client": (
            {"id": client_obj.id, "name": client_obj.name}
            if client_obj else None
        ),
        "job": {
            "id": b.job.id, "code": b.job.code, "title": b.job.title,
            "project_id": b.job.project_id,
            "project_code": b.job.project.code if b.job.project else None,
            "project_title": b.job.project.title if b.job.project else None,
        } if b.job else None,
        "cost_line": {
            "id": b.cost_line.id,
            "description": b.cost_line.description,
            "unit": b.cost_line.unit,
            "quantity_quoted": b.cost_line.quantity_quoted,
            "quantity_actual": b.cost_line.quantity_actual,
            # v3.5.0-alpha.22: somma cross-booking di ore done (utile per
            # vedere "quanto è già stato fatto su questa lavorazione").
            "total_planned_hours_all_bookings": round(cl_total_planned_hours, 2),
            "done_hours_all_bookings": round(cl_done_hours, 2),
        } if b.cost_line else None,
        "assignments": [
            {
                "id": a.id,
                "resource_id": a.resource_id,
                "resource_name": a.resource.name if a.resource else None,
                "resource_role": (a.resource.role if a.resource else None),
                "department_name": (a.resource.department.name if a.resource and a.resource.department else None),
                "start_datetime": a.start_datetime.isoformat(),
                "end_datetime": a.end_datetime.isoformat(),
                "duration_hours": round((a.end_datetime - a.start_datetime).total_seconds() / 3600.0, 2),
            } for a in b.assignments
        ],
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "audit_count": audit_n,
        "last_change_at": last_change_at,
        # v3.5.0-alpha.63 — bandiera per UI: ci sono assignment dello stesso
        # booking che si sovrappongono sulla stessa risorsa (dato sporco
        # pre-α.63: ora bloccato in create/update da _check_intra_payload_overlaps).
        "has_duplicate_overlaps": bool(duplicate_resource_ids),
        "duplicate_resource_ids": duplicate_resource_ids,
    }


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
        Booking.tenant_id == current_tenant_id(),
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


@router.post("/api/my-bookings/{booking_id}/respond")
async def respond_my_booking(
    booking_id: int,
    request: Request,
    action: str = Form(...),
    db: Session = Depends(get_db),
):
    """Staff accetta o rifiuta la PROPRIA assegnazione (mobile PWA).

    Gate di sicurezza: verifica che il booking abbia un BookingAssignment
    con resource_id legato all'utente loggato. 403 se non è sua assegnazione.
    action ∈ {accept, reject} — 400 altrimenti.
    Persiste response_status sull'assignment: "accepted" / "rejected".
    """
    # v3.5.0-alpha.172.147
    user = current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Non autenticato")

    # Valida action PRIMA di query DB (fail fast)
    action = action.strip().lower()
    if action not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="action deve essere 'accept' o 'reject'")

    # Risolve resource_id del user corrente (ownership scope)
    rid = scope_resource_id(db, user)
    if rid is None:
        raise HTTPException(status_code=403, detail="Nessuna risorsa associata al tuo utente")

    # Verifica che il booking esista + appartenga al tenant
    b = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(status_code=404, detail="Booking non trovato")

    # Cerca l'assignment dell'utente su questo booking (ownership check)
    assignment = db.query(BookingAssignment).filter(
        BookingAssignment.booking_id == booking_id,
        BookingAssignment.resource_id == rid,
    ).first()
    if assignment is None:
        raise HTTPException(
            status_code=403,
            detail="Non sei assegnato a questo booking",
        )

    new_status = "accepted" if action == "accept" else "rejected"
    assignment.response_status = new_status
    db.commit()
    return {"ok": True, "status": new_status}


# ─────────────────────────────────────────────────────────────
# v3.5.0-alpha.172.3 Restructure Sprint 3 — Booking link Deliverable (M:N)
# Pivot booking_deliverables. Permette ad un booking di servire N
# deliverable (cost split equo via deliverable_cost_sync).
# ─────────────────────────────────────────────────────────────

@router.get("/api/bookings/{booking_id}/deliverables")
async def list_booking_deliverables(
    booking_id: int,
    db: Session = Depends(get_db),
):
    """Lista deliverable linkati al booking via pivot booking_deliverables."""
    from app.models import Booking, BookingDeliverable, JobDeliverable

    b = db.query(Booking).filter(
        Booking.id == booking_id, Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")

    rows = (
        db.query(BookingDeliverable, JobDeliverable)
        .join(JobDeliverable, JobDeliverable.id == BookingDeliverable.job_deliverable_id)
        .filter(BookingDeliverable.booking_id == booking_id)
        .order_by(BookingDeliverable.sort_order.asc(), BookingDeliverable.id.asc())
        .all()
    )
    def _file_type(d) -> "str | None":
        """F3.2 — tipo file (package o container) + nome item dal capitolato.
        Letto dallo snapshot spec_json (decisione 7), niente join."""
        sj = d.spec_json or {}
        return sj.get("package") or sj.get("container")

    return [
        {
            "pivot_id": link.id,
            "deliverable_id": d.id,
            "name": d.name,
            "unit": d.unit,
            "unit_nature": d.unit_nature.value if hasattr(d.unit_nature, "value") else d.unit_nature,
            "quantity_planned": d.quantity_planned,
            "quantity_delivered": d.quantity_delivered,
            "status": d.status.value if hasattr(d.status, "value") else d.status,
            "sort_order": link.sort_order,
            # F3.2 — tipo file consegna + nome item capitolato per il booking modal.
            "file_type": _file_type(d),
            "delivery_item_name": (d.spec_json or {}).get("name"),
        }
        for link, d in rows
    ]


@router.post("/api/bookings/{booking_id}/deliverables", dependencies=[RequireEditPlanningAll])
async def link_booking_deliverable(
    booking_id: int,
    job_deliverable_id: int = Form(...),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    """Crea row in booking_deliverables. Idempotente: skip se gia presente.
    Triggera recompute deliverable_cost_sync per ricalcolare cost split.
    """
    from app.models import Booking, BookingDeliverable, JobDeliverable
    from app.services.deliverable_cost_sync import recompute_for_booking

    b = db.query(Booking).filter(
        Booking.id == booking_id, Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")

    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == job_deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    if d.job_id != b.job_id:
        raise HTTPException(
            400,
            f"Deliverable appartiene a job #{d.job_id}, booking a job #{b.job_id}. "
            "Cross-job link non permesso."
        )

    existing = db.query(BookingDeliverable).filter(
        BookingDeliverable.booking_id == booking_id,
        BookingDeliverable.job_deliverable_id == job_deliverable_id,
    ).first()
    if existing:
        return {"ok": True, "pivot_id": existing.id, "already_linked": True}

    link = BookingDeliverable(
        booking_id=booking_id,
        job_deliverable_id=job_deliverable_id,
        sort_order=sort_order,
    )
    db.add(link); db.flush()

    # Ricalcola tutti i deliverable linkati a questo booking (cost split equo)
    recompute_for_booking(db, b)
    db.commit()
    return {"ok": True, "pivot_id": link.id, "already_linked": False}


@router.delete("/api/bookings/{booking_id}/deliverables/{deliverable_id}",
               dependencies=[RequireEditPlanningAll])
async def unlink_booking_deliverable(
    booking_id: int,
    deliverable_id: int,
    db: Session = Depends(get_db),
):
    """Rimuove row da booking_deliverables. Triggera recompute cost_split."""
    from app.models import Booking, BookingDeliverable
    from app.services.deliverable_cost_sync import recompute_for_booking

    b = db.query(Booking).filter(
        Booking.id == booking_id, Booking.tenant_id == current_tenant_id(),
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")

    link = db.query(BookingDeliverable).filter(
        BookingDeliverable.booking_id == booking_id,
        BookingDeliverable.job_deliverable_id == deliverable_id,
    ).first()
    if not link:
        return {"ok": True, "deleted": False}

    db.delete(link); db.flush()
    recompute_for_booking(db, b)
    db.commit()
    return {"ok": True, "deleted": True}
