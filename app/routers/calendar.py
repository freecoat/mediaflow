"""Router calendario — Fase B (v3.5.0-alpha.172.240).

CRUD CalendarEvent Form-based + list con range temporale e marcatori
derivati (Activity.next_action_date, Acquisition.expected_close_date).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.context import current_tenant_id
from app.models.models import (
    CalendarEvent, CalendarEventStatus, Activity, Acquisition,
)
from app.services.rbac import requires_permission, current_user_optional
from app.services.calendar_sync import maybe_autosync_event, sync_user_pending

router = APIRouter(tags=["calendar"])

RequireView = Depends(requires_permission("view_calendar"))
RequireManage = Depends(requires_permission("manage_calendar"))


def _parse_dt(s: str) -> datetime:
    if not s:
        raise HTTPException(400, "Data mancante")
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Data non valida: {s}")


def _serialize_event(ev: CalendarEvent) -> dict:
    return {
        "id": ev.id, "title": ev.title, "description": ev.description,
        "start": ev.start_at.isoformat() if ev.start_at else None,
        "end": ev.end_at.isoformat() if ev.end_at else None,
        "all_day": ev.all_day, "location": ev.location, "meeting_url": ev.meeting_url,
        "status": ev.status.value if ev.status else "confirmed",
        "owner_user_id": ev.owner_user_id,
        "acquisition_id": ev.acquisition_id, "project_id": ev.project_id,
        "activity_id": ev.activity_id, "client_id": ev.client_id,
        "attendees": ev.attendees or [], "source": ev.source,
        "sync_state": ev.sync_state, "external_event_id": ev.external_event_id,
    }


def _int_or_none(v: Optional[str]) -> Optional[int]:
    if v is None or str(v).strip() in ("", "0"):
        return None
    return int(v)


def _parse_attendees(s: Optional[str]) -> list:
    """Stringa (virgole/newline/;) → lista di email deduplicate, ordine preservato."""
    if not s:
        return []
    import re
    seen, out = set(), []
    for p in re.split(r"[,\n;]+", s):
        e = p.strip()
        if e and e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    return out


@router.get("/calendar", response_class=HTMLResponse, dependencies=[RequireView])
async def calendar_page(request: Request):
    from app.main import templates
    return templates.TemplateResponse(
        "pages/calendar.html", {"request": request, "active_page": "calendar"})


@router.get("/calendar/api/events", dependencies=[RequireView])
async def list_events(
    request: Request,
    start: Optional[str] = None, end: Optional[str] = None,
    owner: Optional[str] = None, scope: str = "team",
    acquisition_id: Optional[int] = None, project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    tid = current_tenant_id()
    q = db.query(CalendarEvent).filter(
        CalendarEvent.tenant_id == tid,
        CalendarEvent.is_active == True,  # noqa: E712
    )
    if acquisition_id:
        q = q.filter(CalendarEvent.acquisition_id == acquisition_id)
    if project_id:
        q = q.filter(CalendarEvent.project_id == project_id)
    if scope == "mine":
        u = current_user_optional(request)
        q = q.filter(CalendarEvent.owner_user_id == (u.id if u else None))
    elif owner:
        q = q.filter(CalendarEvent.owner_user_id == int(owner))
    start_dt = _parse_dt(start) if start else None
    end_dt = _parse_dt(end) if end else None
    if start_dt:
        q = q.filter(CalendarEvent.end_at >= start_dt)
    if end_dt:
        q = q.filter(CalendarEvent.start_at <= end_dt)
    events = [_serialize_event(ev) for ev in q.all()]

    # Marcatori derivati (read-only): Acquisition.expected_close_date + Activity.next_action_date
    markers = []
    aq = db.query(Acquisition).filter(
        Acquisition.tenant_id == tid, Acquisition.is_active == True,  # noqa: E712
        Acquisition.expected_close_date.isnot(None))
    for a in aq.all():
        d = a.expected_close_date
        if start_dt and d < start_dt.date():
            continue
        if end_dt and d > end_dt.date():
            continue
        markers.append({"kind": "acquisition_close", "date": d.isoformat(),
                        "title": a.title, "acquisition_id": a.id})
    acts = db.query(Activity).filter(
        Activity.tenant_id == tid, Activity.is_active == True,  # noqa: E712
        Activity.next_action_date.isnot(None))
    for act in acts.all():
        d = act.next_action_date
        if start_dt and d < start_dt.date():
            continue
        if end_dt and d > end_dt.date():
            continue
        markers.append({"kind": "activity_next", "date": d.isoformat(),
                        "title": act.subject, "activity_id": act.id,
                        "acquisition_id": act.acquisition_id})
    return {"events": events, "markers": markers}


def _apply_fields(ev: CalendarEvent, *, title, start_at, end_at, all_day, location,
                  meeting_url, status, acquisition_id, project_id, activity_id, client_id,
                  description=None, attendees=None):
    if title is not None:
        ev.title = title.strip()
    if start_at is not None:
        ev.start_at = _parse_dt(start_at)
    if end_at is not None:
        ev.end_at = _parse_dt(end_at)
    if all_day is not None:
        ev.all_day = str(all_day).lower() in ("1", "true", "on", "yes")
    if location is not None:
        ev.location = location.strip() or None
    if meeting_url is not None:
        ev.meeting_url = meeting_url.strip() or None
    if description is not None:
        ev.description = description.strip() or None
    if attendees is not None:
        ev.attendees = _parse_attendees(attendees)
    if status is not None and status.strip():
        ev.status = CalendarEventStatus(status.strip())
    if acquisition_id is not None:
        ev.acquisition_id = _int_or_none(acquisition_id)
    if project_id is not None:
        ev.project_id = _int_or_none(project_id)
    if activity_id is not None:
        ev.activity_id = _int_or_none(activity_id)
    if client_id is not None:
        ev.client_id = _int_or_none(client_id)


@router.post("/calendar/api/events", dependencies=[RequireManage])
async def create_event(
    request: Request,
    title: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    all_day: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    meeting_url: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    attendees: Optional[str] = Form(None),
    acquisition_id: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    activity_id: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    u = current_user_optional(request)
    ev = CalendarEvent(tenant_id=current_tenant_id(), title=title.strip(),
                       start_at=_parse_dt(start_at), end_at=_parse_dt(end_at),
                       owner_user_id=(u.id if u else None), created_by=(u.id if u else None))
    _apply_fields(ev, title=None, start_at=None, end_at=None, all_day=all_day,
                  location=location, meeting_url=meeting_url, status=status,
                  description=description, attendees=attendees,
                  acquisition_id=acquisition_id, project_id=project_id,
                  activity_id=activity_id, client_id=client_id)
    db.add(ev); db.commit(); db.refresh(ev)
    maybe_autosync_event(db, ev.owner_user_id, ev)
    db.commit(); db.refresh(ev)
    return _serialize_event(ev)


@router.put("/calendar/api/events/{event_id}", dependencies=[RequireManage])
async def update_event(
    event_id: int,
    title: Optional[str] = Form(None),
    start_at: Optional[str] = Form(None),
    end_at: Optional[str] = Form(None),
    all_day: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    meeting_url: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    attendees: Optional[str] = Form(None),
    acquisition_id: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    activity_id: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    ev = db.query(CalendarEvent).filter(
        CalendarEvent.id == event_id, CalendarEvent.tenant_id == current_tenant_id(),
        CalendarEvent.is_active == True).first()  # noqa: E712
    if not ev:
        raise HTTPException(404, "Appuntamento non trovato")
    _apply_fields(ev, title=title, start_at=start_at, end_at=end_at, all_day=all_day,
                  location=location, meeting_url=meeting_url, status=status,
                  description=description, attendees=attendees,
                  acquisition_id=acquisition_id, project_id=project_id,
                  activity_id=activity_id, client_id=client_id)
    db.commit(); db.refresh(ev)
    maybe_autosync_event(db, ev.owner_user_id, ev)
    db.commit(); db.refresh(ev)
    return _serialize_event(ev)


@router.delete("/calendar/api/events/{event_id}", dependencies=[RequireManage])
async def delete_event(event_id: int, db: Session = Depends(get_db)):
    ev = db.query(CalendarEvent).filter(
        CalendarEvent.id == event_id, CalendarEvent.tenant_id == current_tenant_id(),
        CalendarEvent.is_active == True).first()  # noqa: E712
    if not ev:
        raise HTTPException(404, "Appuntamento non trovato")
    ev.is_active = False
    db.commit()
    maybe_autosync_event(db, ev.owner_user_id, ev, deleted=True)
    db.commit()
    return {"ok": True}


@router.post("/calendar/api/sync", dependencies=[RequireManage])
async def sync_now(request: Request, db: Session = Depends(get_db)):
    u = current_user_optional(request)
    if not u:
        raise HTTPException(401, "Non autenticato")
    return sync_user_pending(db, u.id)


@router.get("/calendar/api/google-overlay", dependencies=[RequireView])
async def google_overlay(start: Optional[str] = None, end: Optional[str] = None,
                         request: Request = None, db: Session = Depends(get_db)):
    u = current_user_optional(request)
    if not u or not start or not end:
        return {"events": []}
    from app.services import google_calendar
    try:
        return {"events": google_calendar.list_google_events(db, u.id, start, end)}
    except Exception:
        return {"events": []}


def _google_body_from_form(*, title, start_at, end_at, all_day, location,
                           description, meeting_url, status, attendees) -> dict:
    """Costruisce il body Google (PATCH parziale) dai campi form del modal.
    Solo i campi valorizzati vengono inclusi."""
    body = {}
    if title is not None:
        body["summary"] = title.strip()
    desc = (description or "").strip()
    if meeting_url and meeting_url.strip():
        desc = (desc + "\n\n" + meeting_url.strip()).strip()
    if description is not None or (meeting_url and meeting_url.strip()):
        body["description"] = desc
    if location is not None:
        body["location"] = location.strip()
    if status is not None and status.strip():
        body["status"] = status.strip()
    if attendees is not None:
        body["attendees"] = [{"email": e} for e in _parse_attendees(attendees)]
    is_all = str(all_day or "").lower() in ("1", "true", "on", "yes")
    if start_at:
        dt = _parse_dt(start_at)
        body["start"] = {"date": dt.date().isoformat()} if is_all else {"dateTime": dt.isoformat()}
    if end_at:
        dt = _parse_dt(end_at)
        body["end"] = {"date": dt.date().isoformat()} if is_all else {"dateTime": dt.isoformat()}
    return body


@router.put("/calendar/api/google-event", dependencies=[RequireManage])
async def update_google_event_ep(
    request: Request,
    calendar_id: str = Form(...),
    event_id: str = Form(...),
    title: Optional[str] = Form(None),
    start_at: Optional[str] = Form(None),
    end_at: Optional[str] = Form(None),
    all_day: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    meeting_url: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    attendees: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Modifica un evento Google ESISTENTE sul suo calendario (scope full)."""
    u = current_user_optional(request)
    if not u:
        raise HTTPException(401, "Non autenticato")
    from app.services import google_calendar
    body = _google_body_from_form(title=title, start_at=start_at, end_at=end_at, all_day=all_day,
                                  location=location, description=description, meeting_url=meeting_url,
                                  status=status, attendees=attendees)
    res = google_calendar.update_google_event(db, u.id, calendar_id, event_id, body)
    if res is None:
        raise HTTPException(502, "Aggiornamento Google fallito")
    return {"ok": True, "id": res.get("id")}


@router.delete("/calendar/api/google-event", dependencies=[RequireManage])
async def delete_google_event_ep(request: Request, calendar_id: str, event_id: str,
                                 db: Session = Depends(get_db)):
    """Elimina un evento Google esistente sul suo calendario (scope full)."""
    u = current_user_optional(request)
    if not u:
        raise HTTPException(401, "Non autenticato")
    from app.services import google_calendar
    ok = google_calendar.delete_google_event(db, u.id, calendar_id, event_id)
    if not ok:
        raise HTTPException(502, "Eliminazione Google fallita")
    return {"ok": True}
