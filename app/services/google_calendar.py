# app/services/google_calendar.py
"""Google Calendar API client — Fase C (v3.5.0-alpha.172.242).

Layer HTTP isolato (urllib, coerente con oauth_providers). Tutte le chiamate
passano da `_google_request` → punto unico di mock nei test.

Scope (α.172.247): `calendar` full — read/write su TUTTI i calendari
dell'utente. Permette di editare eventi Google esistenti e invitare
partecipanti (`attendees` + `sendUpdates=all`), oltre a gestire il calendario
secondario 'Claqo' per gli appuntamenti creati in Claqo.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from sqlalchemy.orm import Session

from app.services.clock import now_utc
from app.services.oauth_providers import get_token, get_valid_access_token

log = logging.getLogger(__name__)

_API_BASE = "https://www.googleapis.com/calendar/v3"
CLAQO_CALENDAR_SUMMARY = "Claqo"


def _google_request(method: str, url: str, token: str, body=None, params=None,
                    extra_headers: Optional[dict] = None) -> dict:
    """Chiamata HTTP all'API Google Calendar. Ritorna dict JSON (o {} se vuoto).
    Punto unico di mock nei test. Solleva urllib.error.HTTPError su status >=400
    (i chiamanti gestiscono i casi rilevanti, es. 404 su delete).
    `extra_headers`: header aggiuntivi (es. If-Match per il conflict detection)."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def has_calendar_write_scope(row) -> bool:
    """True se lo scope concesso copre la scrittura eventi (opt-in, design
    2026-07-15 Domanda 1). Accetta anche lo scope `calendar` pieno: è un superset
    funzionale di calendar.events, ed è quanto Google ha effettivamente concesso
    su alcuni account reali oltre a quanto richiesto dal bundle."""
    if not row or not row.scopes:
        return False
    if "calendar.events" in row.scopes:
        return True
    # `.../auth/calendar` pieno. Il match è sul token esatto: calendar.readonly e
    # calendar.app.created NON devono passare (hanno un suffisso dopo 'calendar').
    return any(s.endswith("/auth/calendar") for s in row.scopes.split())


def ensure_claqo_calendar(db: Session, user_id: int) -> Optional[str]:
    row = get_token(db, user_id, "google")
    if not row:
        return None
    if row.claqo_calendar_id:
        return row.claqo_calendar_id
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    try:  # best-effort: token revocato/scaduto (403) o rete → None, mai propagare
        res = _google_request("POST", _API_BASE + "/calendars", token,
                              body={"summary": CLAQO_CALENDAR_SUMMARY})
    except Exception as e:
        log.warning(f"ensure_claqo_calendar fallita user={user_id}: {e}")
        return None
    cal_id = (res or {}).get("id")
    if cal_id:
        row.claqo_calendar_id = cal_id
        row.updated_at = now_utc()
    return cal_id


def _event_to_google(ev) -> dict:
    status = "cancelled" if (ev.status and getattr(ev.status, "value", ev.status) == "cancelled") else "confirmed"
    desc = ev.description or ""
    # meeting_url non ha un campo nativo su Google: lo appendiamo alla descrizione.
    if getattr(ev, "meeting_url", None):
        desc = (desc + "\n\n" + ev.meeting_url).strip() if desc else ev.meeting_url
    body = {
        "summary": ev.title or "",
        "description": desc,
        "location": ev.location or "",
        "status": status,
    }
    attendees = getattr(ev, "attendees", None) or []
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees if e]
    if ev.all_day:
        body["start"] = {"date": ev.start_at.date().isoformat()}
        body["end"] = {"date": ev.end_at.date().isoformat()}
    else:
        body["start"] = {"dateTime": ev.start_at.isoformat()}
        body["end"] = {"dateTime": ev.end_at.isoformat()}
    return body


def push_event(db: Session, user_id: int, ev) -> bool:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    cal = ensure_claqo_calendar(db, user_id)
    if not cal:
        return False
    try:
        body = _event_to_google(ev)
        # Notifica i partecipanti solo se presenti (invito via email).
        params = {"sendUpdates": "all"} if body.get("attendees") else None
        base = _API_BASE + "/calendars/" + urllib.parse.quote(cal) + "/events"
        if ev.external_event_id:
            _google_request("PUT", base + "/" + urllib.parse.quote(ev.external_event_id),
                            token, body=body, params=params)
        else:
            res = _google_request("POST", base, token, body=body, params=params)
            ev.external_event_id = (res or {}).get("id")
            ev.external_calendar_id = cal
        ev.sync_state = "synced"
        ev.last_synced_at = now_utc()
        ev.sync_error = None
        return True
    except Exception as e:
        log.warning(f"push_event fallito ev={getattr(ev, 'id', '?')}: {e}")
        ev.sync_state = "error"
        ev.sync_error = str(e)[:500]
        return False


def update_google_event(db: Session, user_id: int, calendar_id: str, event_id: str,
                        fields: dict) -> Optional[dict]:
    """PATCH parziale di un evento Google ESISTENTE sul suo calendario di origine
    (scope `calendar` full). `fields` = dict già in formato Google (summary,
    description, location, start, end, status, attendees). Best-effort: None su errore."""
    token = get_valid_access_token(db, user_id, "google")
    if not token or not calendar_id or not event_id:
        return None
    url = (_API_BASE + "/calendars/" + urllib.parse.quote(calendar_id) +
           "/events/" + urllib.parse.quote(event_id))
    params = {"sendUpdates": "all"} if fields.get("attendees") else None
    try:
        return _google_request("PATCH", url, token, body=fields, params=params)
    except Exception as e:
        log.warning(f"update_google_event fallito cal={calendar_id} ev={event_id}: {e}")
        return None


def delete_google_event(db: Session, user_id: int, calendar_id: str, event_id: str) -> bool:
    """Elimina un evento Google esistente sul suo calendario. Idempotente su 404."""
    token = get_valid_access_token(db, user_id, "google")
    if not token or not calendar_id or not event_id:
        return False
    url = (_API_BASE + "/calendars/" + urllib.parse.quote(calendar_id) +
           "/events/" + urllib.parse.quote(event_id))
    try:
        _google_request("DELETE", url, token, params={"sendUpdates": "all"})
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True
        log.warning(f"delete_google_event fallito cal={calendar_id} ev={event_id}: {e}")
        return False
    except Exception as e:
        log.warning(f"delete_google_event fallito cal={calendar_id} ev={event_id}: {e}")
        return False


def delete_event(db: Session, user_id: int, ev) -> bool:
    if not ev.external_event_id:
        ev.sync_state = "deleted"
        return True
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    cal = ev.external_calendar_id or ensure_claqo_calendar(db, user_id)
    if not cal:
        return False
    try:
        url = (_API_BASE + "/calendars/" + urllib.parse.quote(cal) +
               "/events/" + urllib.parse.quote(ev.external_event_id))
        _google_request("DELETE", url, token)
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 = già assente → idempotente
            log.warning(f"delete_event fallito ev={ev.id}: {e}")
            ev.sync_error = str(e)[:500]
            return False
    except Exception as e:
        log.warning(f"delete_event fallito ev={ev.id}: {e}")
        ev.sync_error = str(e)[:500]
        return False
    ev.external_event_id = None
    ev.sync_state = "deleted"
    ev.sync_error = None
    return True


def _is_recurring(g: dict) -> bool:
    """Ricorrenze escluse dall'editing: modificare una serie (o una sua istanza)
    ha semantiche multiple su Google (questo evento / tutti / successivi) che
    Claqo non modella. Riduzione di scope esplicita, design Domanda 3."""
    return bool(g.get("recurrence")) or bool(g.get("recurringEventId"))


def list_calendars(db: Session, user_id: int) -> list:
    """Lista dei calendari dell'utente (per la sidebar 'I miei calendari').
    Esclude il calendario secondario 'Claqo' (mostrato a parte come eventi locali).
    Best-effort: token/rete/403 → []."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    row = get_token(db, user_id, "google")
    claqo_id = row.claqo_calendar_id if row else None
    try:
        cal_list = _google_request("GET", _API_BASE + "/users/me/calendarList", token) or {}
    except Exception as e:
        log.warning(f"list_calendars fallita user={user_id}: {e}")
        return []
    out = []
    for cal in cal_list.get("items", []):
        cid = cal.get("id")
        if not cid or cid == claqo_id:
            continue
        out.append({
            "id": cid,
            "summary": cal.get("summary") or cid,
            "color": cal.get("backgroundColor"),
            "access_role": cal.get("accessRole") or "",
            "primary": bool(cal.get("primary")),
        })
    return out


def _normalize_google_event(g: dict, cal_summary: str, calendar_id: str,
                            access_role: Optional[str], write_scope_ok: bool,
                            cal_color: Optional[str] = None) -> dict:
    """Un evento è editabile solo se TUTTE e tre: accessRole owner/writer sul
    calendario, opt-in scope scrittura concesso, e non è ricorrente.
    `cal_color` è opzionale e sesto: i test chiamano questa funzione con 5
    posizionali, aggiungerlo prima li romperebbe."""
    start = g.get("start", {})
    end = g.get("end", {})
    editable = (access_role in ("owner", "writer")) and write_scope_ok and not _is_recurring(g)
    return {
        # etag anche nella lista: senza, il drag&drop non ha If-Match da mandare e
        # l'ultima scrittura vince in silenzio (limite noto di α.172.248).
        "etag": g.get("etag"),
        "id": g.get("id"),
        "title": g.get("summary") or "(senza titolo)",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "calendar": cal_summary,
        "calendar_id": calendar_id,
        "access_role": access_role,
        "read_only": not editable,
        "editable": editable,
        "color": cal_color,
        "description": g.get("description") or "",
        "location": g.get("location") or "",
        "status": g.get("status") or "confirmed",
        "attendees": [a.get("email") for a in (g.get("attendees") or []) if a.get("email")],
    }


def list_google_events(db: Session, user_id: int, time_min: str, time_max: str) -> list:
    """Overlay eventi Google di TUTTI i calendari (escluso il secondario 'Claqo',
    già rappresentato dagli eventi locali). Con scope `calendar` full gli eventi
    su calendari con accessRole owner/writer sono editabili in Claqo."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    row = get_token(db, user_id, "google")
    claqo_id = row.claqo_calendar_id if row else None
    # Calcolato una volta per la lista, non per evento: dipende dal token, non dal calendario.
    write_scope_ok = has_calendar_write_scope(row)
    try:
        cal_list = _google_request("GET", _API_BASE + "/users/me/calendarList", token) or {}
    except Exception as e:
        log.warning(f"calendarList fallita user={user_id}: {e}")
        return []
    out = []
    for cal in cal_list.get("items", []):
        cid = cal.get("id")
        if not cid or cid == claqo_id:
            continue
        access_role = cal.get("accessRole")
        cal_color = cal.get("backgroundColor")
        try:
            res = _google_request(
                "GET", _API_BASE + "/calendars/" + urllib.parse.quote(cid) + "/events", token,
                params={"timeMin": time_min, "timeMax": time_max,
                        "singleEvents": "true", "maxResults": "250", "orderBy": "startTime"}) or {}
        except Exception as e:
            log.warning(f"events {cid} falliti: {e}")
            continue
        for g in res.get("items", []):
            if g.get("status") == "cancelled":
                continue
            out.append(_normalize_google_event(g, cal.get("summary") or cid, cid,
                                               access_role, write_scope_ok,
                                               cal_color=cal_color))
    return out


def get_external_event(db: Session, user_id: int, calendar_id: str,
                       event_id: str) -> Optional[dict]:
    """Evento singolo + etag per il conflict detection. None se non connesso/404."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    url = (_API_BASE + "/calendars/" + urllib.parse.quote(calendar_id) +
           "/events/" + urllib.parse.quote(event_id))
    try:
        g = _google_request("GET", url, token)
    except Exception as e:
        log.warning(f"get_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return None
    if not g:
        return None
    row = get_token(db, user_id, "google")
    return _normalize_google_event(g, "", calendar_id, "writer",
                                   has_calendar_write_scope(row))


def _patch_body(*, title, start_at, end_at, all_day, location,
                description=None, meeting_url=None, status=None, attendees=None) -> dict:
    """Solo i campi passati finiscono nel body: PATCH parziale, così i campi che
    Claqo non modella (allegati, conferenza…) restano intatti.
    `attendees` = lista di email (il parsing della stringa form sta nel router).
    `meeting_url` non ha campo nativo su Google: si appende alla descrizione,
    stessa convenzione di `_event_to_google`."""
    body = {}
    if title is not None:
        body["summary"] = title
    if location is not None:
        body["location"] = location
    desc = (description or "").strip()
    if meeting_url and meeting_url.strip():
        desc = (desc + "\n\n" + meeting_url.strip()).strip()
    if description is not None or (meeting_url and meeting_url.strip()):
        body["description"] = desc
    if status is not None and str(status).strip():
        body["status"] = str(status).strip()
    if attendees is not None:
        body["attendees"] = [{"email": e} for e in attendees if e]
    if start_at is not None and end_at is not None:
        if all_day:
            body["start"] = {"date": start_at[:10]}
            body["end"] = {"date": end_at[:10]}
        else:
            body["start"] = {"dateTime": start_at}
            body["end"] = {"dateTime": end_at}
    return body


_HTTP_ERROR_MAP = {412: "conflict", 403: "forbidden", 404: "not_found"}


def update_external_event(db: Session, user_id: int, calendar_id: str, event_id: str, *,
                          title=None, start_at=None, end_at=None, all_day=None,
                          location=None, etag=None, description=None,
                          meeting_url=None, status=None, attendees=None) -> dict:
    """PATCH (non PUT) di un evento Google. `etag` → If-Match: se l'evento è
    cambiato nel frattempo Google risponde 412 e noi NON sovrascriviamo.
    Con `attendees` valorizzati Google manda l'invito (`sendUpdates=all`)."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return {"ok": False, "error": "not_connected", "http_status": None, "event": None}
    body = _patch_body(title=title, start_at=start_at, end_at=end_at,
                       all_day=all_day, location=location, description=description,
                       meeting_url=meeting_url, status=status, attendees=attendees)
    # Notifica i partecipanti solo se presenti: senza, Google non manda inviti.
    params = {"sendUpdates": "all"} if body.get("attendees") else None
    headers = {"If-Match": etag} if etag else None
    url = (_API_BASE + "/calendars/" + urllib.parse.quote(calendar_id) +
           "/events/" + urllib.parse.quote(event_id))
    try:
        res = _google_request("PATCH", url, token, body=body, params=params,
                              extra_headers=headers)
        log.info(f"update_external_event ok user={user_id} cal={calendar_id} evt={event_id}")
        return {"ok": True, "error": None, "http_status": 200, "event": res}
    except urllib.error.HTTPError as e:
        log.warning(f"update_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": _HTTP_ERROR_MAP.get(e.code, "http_error"),
                "http_status": e.code, "event": None}
    except Exception as e:
        log.warning(f"update_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": "http_error", "http_status": None, "event": None}


def delete_external_event(db: Session, user_id: int, calendar_id: str, event_id: str, *,
                          etag: Optional[str] = None) -> dict:
    """DELETE di un evento Google. IRREVERSIBILE: nessun soft-delete lato Google
    (la conferma a due passi vive nella UI, design Domanda 7)."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return {"ok": False, "error": "not_connected", "http_status": None}
    headers = {"If-Match": etag} if etag else None
    url = (_API_BASE + "/calendars/" + urllib.parse.quote(calendar_id) +
           "/events/" + urllib.parse.quote(event_id))
    try:
        _google_request("DELETE", url, token, extra_headers=headers)
        log.info(f"delete_external_event ok user={user_id} cal={calendar_id} evt={event_id}")
        return {"ok": True, "error": None, "http_status": 200}
    except urllib.error.HTTPError as e:
        if e.code == 404:  # già assente = successo idempotente (come delete_event locale)
            return {"ok": True, "error": None, "http_status": 404}
        log.warning(f"delete_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": _HTTP_ERROR_MAP.get(e.code, "http_error"),
                "http_status": e.code}
    except Exception as e:
        log.warning(f"delete_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": "http_error", "http_status": None}
