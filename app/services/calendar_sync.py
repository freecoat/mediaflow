# app/services/calendar_sync.py
"""Orchestrazione sync calendario Claqo <-> Google — Fase C.

- maybe_autosync_event: hook on-save (push/delete immediato se toggle ON).
- sync_user_pending: push/delete in blocco di tutto il pending (bottone manuale).
Best-effort: nessuna eccezione propagata al CRUD locale.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.models import CalendarEvent
from app.services import google_calendar
from app.services.oauth_providers import get_token

log = logging.getLogger(__name__)


def maybe_autosync_event(db: Session, user_id, ev, deleted: bool = False) -> None:
    if not user_id:
        return
    row = get_token(db, user_id, "google")
    if not row or not row.auto_sync_calendar:
        return
    try:
        if deleted:
            google_calendar.delete_event(db, user_id, ev)
        else:
            ok = google_calendar.push_event(db, user_id, ev)
            if not ok and ev.sync_state == "error":
                ev.sync_state = "pending_push"
    except Exception as e:  # best-effort: non rompere il CRUD locale
        log.warning(f"maybe_autosync_event ev={getattr(ev, 'id', '?')}: {e}")
        ev.sync_state = "pending_push"
        ev.sync_error = str(e)[:500]


def sync_user_pending(db: Session, user_id: int) -> dict:
    pushed = deleted = failed = 0
    to_push = db.query(CalendarEvent).filter(
        CalendarEvent.owner_user_id == user_id,
        CalendarEvent.is_active == True,  # noqa: E712
        CalendarEvent.sync_state.in_(("local", "pending_push", "error")),
    ).all()
    for ev in to_push:
        if google_calendar.push_event(db, user_id, ev):
            pushed += 1
        else:
            failed += 1
    to_delete = db.query(CalendarEvent).filter(
        CalendarEvent.owner_user_id == user_id,
        CalendarEvent.is_active == False,  # noqa: E712
        CalendarEvent.external_event_id.isnot(None),
        CalendarEvent.sync_state != "deleted",
    ).all()
    for ev in to_delete:
        if google_calendar.delete_event(db, user_id, ev):
            deleted += 1
        else:
            failed += 1
    db.commit()
    return {"pushed": pushed, "deleted": deleted, "failed": failed}
