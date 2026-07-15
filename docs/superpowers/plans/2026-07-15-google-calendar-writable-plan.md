# Calendario — Eventi Google editabili da Claqo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettere all'utente di modificare/eliminare, direttamente da `/calendar`, gli eventi Google reali mostrati nell'overlay — solo quando ha `accessRole` owner/writer sul calendario Google **e** ha attivato l'opt-in scope `calendar.events` — senza persistere una copia locale (`CalendarEvent`) e senza toccare il mirror one-way Claqo→Google della Fase C.

**Architecture:** segue il design approvato in `docs/superpowers/specs/2026-07-15-google-calendar-writable-design.md`. `oauth_providers.py` guadagna un bundle scope opt-in `CALENDAR_WRITE_SCOPES` (stesso pattern di `GMAIL_SCOPES`). `google_calendar.py` resta l'unico layer HTTP: guadagna `get_external_event`/`update_external_event`/`delete_external_event` + `has_calendar_write_scope`, ed estende `list_google_events`/`_normalize_google_event` con `accessRole`→`editable` per-evento. Il router `calendar.py` espone 3 nuovi endpoint `/calendar/api/google-events/{calendar_id}/{event_id}` e sistema la diagnosticabilità di `google_overlay`. Il frontend (`calendar_page.js` + `event_modal.js` + `settings_account.js`) distingue visivamente gli eventi editabili, apre il modale condiviso in una nuova "modalità esterna", e richiede un secondo passo di conferma esplicito per la cancellazione (irreversibile su Google).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, urllib.request (coerente con `oauth_providers`/`google_calendar`), FullCalendar 6, vanilla JS, i18n client-side (`app/static/js/i18n.js`).

## Global Constraints

- **Nessuna migrazione DB.** Nessun nuovo modello/colonna: l'overlay resta virtuale (Domanda 2 del design), niente import in `CalendarEvent`.
- **Nessuna nuova dipendenza Python.** HTTP via `urllib.request`, stesso helper `_google_request` (esteso con `extra_headers` opzionale, retrocompatibile).
- **Token/scope:** `get_valid_access_token(db, user_id, "google")` (auto-refresh, non committa) da `oauth_providers.py`. `has_calendar_write_scope(row)` nuovo, in `google_calendar.py`.
- **Best-effort invariato:** `google_overlay` continua a rispondere sempre 200, mai propaga eccezioni. Diagnosticabilità aggiunta via log + campo opzionale `error: true`, MAI un 502 (vedi design, Domanda 6).
- **RBAC:** i nuovi endpoint di scrittura restano sotto `manage_calendar` (stesso gate degli eventi locali). Nessun permesso nuovo introdotto.
- **Form-based** per scrittura (POST/PUT/DELETE via `Form(...)`, frontend con `FormData`), **i18n 5 lingue nello stesso commit** della UI che introduce la stringa, cache-buster su ogni static JS toccato (bump `?v=` in `base.html`).
- **Ricorrenze sempre non editabili** (`recurrence` o `recurringEventId` presente → `editable=False` a prescindere da `accessRole`) — riduzione di scope esplicita, non un edge case dimenticato.
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...`. Commit via `git commit -F <file>` (mai heredoc diretto nel messaggio, hook lo blocca).
- **Versione:** `3.5.0-alpha.172.247` (stato attuale a inizio piano) → `.248`…`.252` (una per task funzionale) → bump finale documentato in Task 10.

---

## Task 1: `oauth_providers.py` — bundle scope opt-in `CALENDAR_WRITE_SCOPES`

**Files:**
- Modify: `app/services/oauth_providers.py` (accanto a `GMAIL_SCOPES`, righe 73-78)
- Test: `tests/test_oauth_calendar_write_scope.py` (new, mirror di `tests/test_oauth_gmail_optin.py`)

**Interfaces:**
- Produces: `CALENDAR_WRITE_SCOPES: str = "https://www.googleapis.com/auth/calendar.events"`.
- Consumes: `authorization_url(provider, state, extra_scopes=...)` (già esistente, invariato).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_calendar_write_scope.py
import urllib.parse
from app.services import oauth_providers as oauth


def _params(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_calendar_write_scopes_constant():
    assert "calendar.events" in oauth.CALENDAR_WRITE_SCOPES


def test_authorization_url_default_no_calendar_write():
    url = oauth.authorization_url("google", "st")
    scope = _params(url)["scope"]
    assert "calendar.events" not in scope  # opt-in: non nel bundle di default


def test_authorization_url_with_calendar_write_extra_scope():
    url = oauth.authorization_url("google", "st", extra_scopes=oauth.CALENDAR_WRITE_SCOPES)
    p = _params(url)
    assert "calendar.events" in p["scope"]
    assert p["include_granted_scopes"] == "true"
    # gli scope base restano presenti (least-privilege bundle invariato)
    assert "calendar.readonly" in p["scope"]
    assert "calendar.app.created" in p["scope"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_oauth_calendar_write_scope.py -v`
Expected: FAIL — `AttributeError: module 'app.services.oauth_providers' has no attribute 'CALENDAR_WRITE_SCOPES'`.

- [ ] **Step 3: Add the constant**

In `app/services/oauth_providers.py`, subito dopo `GMAIL_SCOPES` (riga 78):

```python
# Scope scrittura calendario richiesti SOLO su opt-in esplicito (Domanda 1 design
# 2026-07-15). Non nel bundle base: calendar.events (non 'calendar' pieno) copre
# il minimo necessario per editare/eliminare eventi su calendari dove l'utente
# ha accessRole owner/writer, senza concedere gestione dei calendari stessi.
CALENDAR_WRITE_SCOPES = "https://www.googleapis.com/auth/calendar.events"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_oauth_calendar_write_scope.py tests/test_oauth_google_scopes.py tests/test_oauth_gmail_optin.py -v`
Expected: all pass (nessuna regressione sugli scope esistenti).

- [ ] **Step 5: Commit**

```bash
git add app/services/oauth_providers.py tests/test_oauth_calendar_write_scope.py
git commit -F- <<'EOF'
feat(calendar): CALENDAR_WRITE_SCOPES opt-in incrementale (calendar.events)

v3.5.0-alpha.172.248
EOF
```

---

## Task 2: `oauth.py` — `GET /auth/oauth/{provider}/start?scopes=calendar_write`

**Files:**
- Modify: `app/routers/oauth.py:52-70` (`oauth_start`)
- Test: `tests/test_oauth_router_state.py` (append, riusa la fixture `client` importata da `test_acquisitions_api`)

**Interfaces:**
- Consumes: `oauth.CALENDAR_WRITE_SCOPES` (Task 1).
- Produces: `GET /auth/oauth/google/start?scopes=calendar_write` → redirect con `extra_scopes=CALENDAR_WRITE_SCOPES`, coerente col mapping esistente `scopes=email` → `GMAIL_SCOPES`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_oauth_router_state.py`:

```python
def test_start_with_calendar_write_includes_extra_scope(client, monkeypatch):
    c, s = client
    r = c.get("/auth/oauth/google/start?scopes=calendar_write", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "calendar.events" in r.headers["location"]
    assert "include_granted_scopes=true" in r.headers["location"]


def test_start_without_scopes_param_excludes_calendar_write(client):
    c, s = client
    r = c.get("/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "calendar.events" not in r.headers["location"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_oauth_router_state.py -v`
Expected: FAIL — `test_start_with_calendar_write_includes_extra_scope` fallisce (`scopes=calendar_write` oggi non produce nessun `extra`, redirect senza `calendar.events`).

- [ ] **Step 3: Extend the mapping in `oauth_start`**

In `app/routers/oauth.py`, riga 68, sostituire:

```python
    extra = oauth.GMAIL_SCOPES if (provider == "google" and scopes == "email") else None
```

con:

```python
    extra = None
    if provider == "google" and scopes == "email":
        extra = oauth.GMAIL_SCOPES
    elif provider == "google" and scopes == "calendar_write":
        extra = oauth.CALENDAR_WRITE_SCOPES
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_oauth_router_state.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/routers/oauth.py tests/test_oauth_router_state.py
git commit -F- <<'EOF'
feat(calendar): /auth/oauth/google/start?scopes=calendar_write opt-in editing

v3.5.0-alpha.172.249
EOF
```

---

## Task 3: `google_calendar.py` — `_google_request` header opzionali + `has_calendar_write_scope`

**Files:**
- Modify: `app/services/google_calendar.py:30-65`
- Test: `tests/test_google_calendar.py` (append)

**Interfaces:**
- Produces: `_google_request(method, url, token, body=None, params=None, extra_headers=None) -> dict` (retrocompatibile: firma esistente invariata, nuovo parametro opzionale in coda); `has_calendar_write_scope(row: UserOAuthToken) -> bool`.
- Consumes: nessuna nuova dipendenza.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_google_calendar.py`:

```python
from app.models.models import UserOAuthToken as _UOT  # already imported at top; alias for clarity in new tests


def test_google_request_passes_extra_headers(monkeypatch):
    captured = {}
    real_request_cls = __import__("urllib.request", fromlist=["Request"]).Request

    class _FakeReq:
        def __init__(self, url, data=None, method=None, headers=None):
            captured["headers"] = headers

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    monkeypatch.setattr("urllib.request.Request", _FakeReq)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=15: _FakeResp())
    gc._google_request("PATCH", "https://x", "tok", extra_headers={"If-Match": "abc123"})
    assert captured["headers"]["If-Match"] == "abc123"
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_has_calendar_write_scope_true_for_events_scope():
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="openid email https://www.googleapis.com/auth/calendar.events")
    assert gc.has_calendar_write_scope(row) is True


def test_has_calendar_write_scope_true_for_full_calendar_scope_superset():
    # Caso reale osservato: alcuni token hanno lo scope pieno 'calendar' (superset
    # funzionale di calendar.events) concesso da Google oltre a quanto richiesto.
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="openid https://www.googleapis.com/auth/calendar")
    assert gc.has_calendar_write_scope(row) is True


def test_has_calendar_write_scope_false_for_readonly_only():
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="openid https://www.googleapis.com/auth/calendar.readonly")
    assert gc.has_calendar_write_scope(row) is False


def test_has_calendar_write_scope_false_when_no_row():
    assert gc.has_calendar_write_scope(None) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v -k "extra_headers or has_calendar_write_scope"`
Expected: FAIL — `_google_request` non accetta `extra_headers`, `has_calendar_write_scope` non esiste.

- [ ] **Step 3: Implement**

In `app/services/google_calendar.py`:

```python
def _google_request(method: str, url: str, token: str, body=None, params=None,
                    extra_headers: Optional[dict] = None) -> dict:
    """... (docstring invariata) ..."""
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
    """True se lo scope concesso copre calendar.events (opt-in, Domanda 1
    design 2026-07-15), incluso il caso in cui l'utente ha lo scope 'calendar'
    pieno (superset funzionale, osservato su alcuni account reali)."""
    if not row or not row.scopes:
        return False
    scopes = row.scopes
    if "calendar.events" in scopes:
        return True
    # scope pieno 'calendar' (non 'calendar.app.created'/'calendar.readonly'/
    # 'calendar.events', che contengono tutti '.' dopo 'calendar')
    for token in scopes.split():
        if token.endswith("/auth/calendar"):
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v`
Expected: all pass (nessuna regressione sui test Fase C esistenti).

- [ ] **Step 5: Commit**

```bash
git add app/services/google_calendar.py tests/test_google_calendar.py
git commit -F- <<'EOF'
feat(calendar): _google_request extra_headers + has_calendar_write_scope

v3.5.0-alpha.172.250
EOF
```

---

## Task 4: `google_calendar.py` — `get_external_event` / `update_external_event` / `delete_external_event`

**Files:**
- Modify: `app/services/google_calendar.py` (append dopo `delete_event`, prima di `_normalize_google_event`)
- Test: `tests/test_google_calendar.py` (append)

**Interfaces:**
- Consumes: `get_valid_access_token`, `_google_request` (Task 3).
- Produces:
  - `get_external_event(db, user_id, calendar_id, event_id) -> Optional[dict]` — evento normalizzato + `etag`, o `None` se non connesso/404.
  - `update_external_event(db, user_id, calendar_id, event_id, *, title=None, start_at=None, end_at=None, all_day=None, location=None, etag=None) -> dict` — `{"ok": bool, "error": Optional[str], "http_status": Optional[int], "event": Optional[dict]}`.
  - `delete_external_event(db, user_id, calendar_id, event_id, *, etag=None) -> dict` — `{"ok": bool, "error": Optional[str], "http_status": Optional[int]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_google_calendar.py`:

```python
import urllib.error


def test_get_external_event_returns_normalized_with_etag(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {
            "id": "evt1", "summary": "Riunione", "etag": '"abc123"',
            "start": {"dateTime": "2026-07-10T09:00:00Z"},
            "end": {"dateTime": "2026-07-10T10:00:00Z"}})
    ev = gc.get_external_event(s, 1, "cal1", "evt1")
    assert ev["title"] == "Riunione"
    assert ev["etag"] == '"abc123"'


def test_get_external_event_none_without_connection():
    s = _session()
    assert gc.get_external_event(s, 1, "cal1", "evt1") is None


def test_update_external_event_sends_patch_with_if_match(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    seen = {}
    def fake(m, u, t, body=None, params=None, extra_headers=None):
        seen["method"] = m; seen["headers"] = extra_headers; seen["body"] = body
        return {"id": "evt1", "summary": body["summary"],
                "start": body["start"], "end": body["end"]}
    monkeypatch.setattr(gc, "_google_request", fake)
    res = gc.update_external_event(s, 1, "cal1", "evt1", title="Nuovo titolo",
                                   start_at="2026-07-10T09:00:00", end_at="2026-07-10T10:00:00",
                                   etag='"abc123"')
    assert res["ok"] is True
    assert seen["method"] == "PATCH"
    assert seen["headers"] == {"If-Match": '"abc123"'}
    assert seen["body"]["summary"] == "Nuovo titolo"


def test_update_external_event_conflict_412(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    def boom(*a, **k):
        raise urllib.error.HTTPError("url", 412, "Precondition Failed", {}, None)
    monkeypatch.setattr(gc, "_google_request", boom)
    res = gc.update_external_event(s, 1, "cal1", "evt1", title="X", etag='"stale"')
    assert res["ok"] is False
    assert res["http_status"] == 412
    assert res["error"] == "conflict"


def test_update_external_event_forbidden_403(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    def boom(*a, **k):
        raise urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
    monkeypatch.setattr(gc, "_google_request", boom)
    res = gc.update_external_event(s, 1, "cal1", "evt1", title="X")
    assert res["ok"] is False
    assert res["http_status"] == 403
    assert res["error"] == "forbidden"


def test_delete_external_event_ok(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    seen = {}
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: seen.setdefault("m", m))
    res = gc.delete_external_event(s, 1, "cal1", "evt1")
    assert res["ok"] is True
    assert seen["m"] == "DELETE"


def test_delete_external_event_404_is_idempotent_success(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    def boom(*a, **k):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)
    monkeypatch.setattr(gc, "_google_request", boom)
    res = gc.delete_external_event(s, 1, "cal1", "evt1")
    assert res["ok"] is True  # gia' assente su Google = successo (stesso pattern di delete_event locale)


def test_delete_external_event_not_connected():
    s = _session()
    res = gc.delete_external_event(s, 1, "cal1", "evt1")
    assert res["ok"] is False
    assert res["error"] == "not_connected"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v -k "external_event"`
Expected: FAIL — `AttributeError` (funzioni non esistono).

- [ ] **Step 3: Implement**

Append in `app/services/google_calendar.py`, dopo `delete_event` (prima di `_normalize_google_event`):

```python
def get_external_event(db: Session, user_id: int, calendar_id: str, event_id: str) -> Optional[dict]:
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
    out = _normalize_google_event(g, cal_summary="", calendar_id=calendar_id,
                                  access_role="writer", write_scope_ok=True)
    out["etag"] = g.get("etag")
    return out


def _patch_body(*, title, start_at, end_at, all_day, location) -> dict:
    body = {}
    if title is not None:
        body["summary"] = title
    if location is not None:
        body["location"] = location
    if start_at is not None and end_at is not None:
        if all_day:
            body["start"] = {"date": start_at[:10]}
            body["end"] = {"date": end_at[:10]}
        else:
            body["start"] = {"dateTime": start_at}
            body["end"] = {"dateTime": end_at}
    return body


def update_external_event(db: Session, user_id: int, calendar_id: str, event_id: str, *,
                          title=None, start_at=None, end_at=None, all_day=None,
                          location=None, etag=None) -> dict:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return {"ok": False, "error": "not_connected", "http_status": None, "event": None}
    body = _patch_body(title=title, start_at=start_at, end_at=end_at,
                       all_day=all_day, location=location)
    headers = {"If-Match": etag} if etag else None
    url = (_API_BASE + "/calendars/" + urllib.parse.quote(calendar_id) +
           "/events/" + urllib.parse.quote(event_id))
    try:
        res = _google_request("PATCH", url, token, body=body, extra_headers=headers)
        return {"ok": True, "error": None, "http_status": 200, "event": res}
    except urllib.error.HTTPError as e:
        error = {412: "conflict", 403: "forbidden", 404: "not_found"}.get(e.code, "http_error")
        log.warning(f"update_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": error, "http_status": e.code, "event": None}
    except Exception as e:
        log.warning(f"update_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": "http_error", "http_status": None, "event": None}


def delete_external_event(db: Session, user_id: int, calendar_id: str, event_id: str, *,
                          etag: Optional[str] = None) -> dict:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return {"ok": False, "error": "not_connected", "http_status": None}
    headers = {"If-Match": etag} if etag else None
    url = (_API_BASE + "/calendars/" + urllib.parse.quote(calendar_id) +
           "/events/" + urllib.parse.quote(event_id))
    try:
        _google_request("DELETE", url, token, extra_headers=headers)
        return {"ok": True, "error": None, "http_status": 200}
    except urllib.error.HTTPError as e:
        if e.code == 404:  # gia' assente = successo idempotente (stesso pattern di delete_event)
            return {"ok": True, "error": None, "http_status": 404}
        error = {412: "conflict", 403: "forbidden"}.get(e.code, "http_error")
        log.warning(f"delete_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": error, "http_status": e.code}
    except Exception as e:
        log.warning(f"delete_external_event fallito cal={calendar_id} evt={event_id}: {e}")
        return {"ok": False, "error": "http_error", "http_status": None}
```

Nota: `get_external_event` chiama `_normalize_google_event` con la firma **estesa** che verrà introdotta al Task 5 — se questo task viene eseguito per primo in isolamento, aggiungere temporaneamente i parametri `calendar_id`/`access_role`/`write_scope_ok` come keyword-only con default compatibili, oppure eseguire Task 5 subito prima di questo step (ordine consigliato: se si esegue in sequenza stretta, invertire Task 4/5 non è necessario — la funzione `_normalize_google_event` va comunque estesa una sola volta; questo task la richiama già nella forma finale).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v`
Expected: all pass (inclusi i test Task 5 se eseguito prima; altrimenti eseguire Task 5 immediatamente dopo e ri-lanciare la suite completa).

- [ ] **Step 5: Commit**

```bash
git add app/services/google_calendar.py tests/test_google_calendar.py
git commit -F- <<'EOF'
feat(calendar): get/update/delete_external_event con If-Match e mappa errori

v3.5.0-alpha.172.251
EOF
```

---

## Task 5: `google_calendar.py` — `accessRole` → `editable` per-evento nell'overlay

**Files:**
- Modify: `app/services/google_calendar.py:141-183` (`_normalize_google_event`, `list_google_events`)
- Test: `tests/test_google_calendar.py` (append)

**Interfaces:**
- Produces: `_normalize_google_event(g, cal_summary, calendar_id, access_role, write_scope_ok) -> dict` (firma estesa — aggiunge `calendar_id`, `access_role`, `editable`, `etag` ai campi esistenti `id/title/start/end/all_day/calendar/read_only`); `list_google_events` propaga `write_scope_ok` (una singola chiamata a `has_calendar_write_scope`, non ricalcolata per evento).
- Consumes: `has_calendar_write_scope` (Task 3).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_google_calendar.py`:

```python
def test_normalize_editable_true_for_writer_with_scope():
    g = {"id": "e1", "summary": "X", "start": {"dateTime": "2026-07-10T09:00:00Z"},
         "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "writer", True)
    assert out["editable"] is True
    assert out["calendar_id"] == "cal1"
    assert out["access_role"] == "writer"


def test_normalize_editable_false_for_reader():
    g = {"id": "e1", "summary": "X", "start": {"date": "2026-07-10"}, "end": {"date": "2026-07-11"}}
    out = gc._normalize_google_event(g, "Festivita", "cal2", "reader", True)
    assert out["editable"] is False


def test_normalize_editable_false_without_write_scope():
    g = {"id": "e1", "summary": "X", "start": {"dateTime": "2026-07-10T09:00:00Z"},
         "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "owner", False)
    assert out["editable"] is False


def test_normalize_editable_false_for_recurring_master():
    g = {"id": "e1", "summary": "X", "recurrence": ["RRULE:FREQ=WEEKLY"],
         "start": {"dateTime": "2026-07-10T09:00:00Z"}, "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "owner", True)
    assert out["editable"] is False


def test_normalize_editable_false_for_recurring_instance():
    g = {"id": "e1_20260710", "summary": "X", "recurringEventId": "e1",
         "start": {"dateTime": "2026-07-10T09:00:00Z"}, "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "owner", True)
    assert out["editable"] is False


def test_list_google_events_propagates_access_role(monkeypatch):
    s = _session(); _connect(s, cal_id="claqoCal")
    row = s.query(_UOT).filter_by(user_id=1, provider="google").first()
    row.scopes = "https://www.googleapis.com/auth/calendar.events"
    s.commit()

    def fake(m, url, t, body=None, params=None, extra_headers=None):
        if url.endswith("/users/me/calendarList"):
            return {"items": [
                {"id": "claqoCal", "summary": "Claqo", "accessRole": "owner"},
                {"id": "mine", "summary": "Personale", "accessRole": "owner"},
                {"id": "readonly-cal", "summary": "Kalenderwochen", "accessRole": "reader"},
            ]}
        if "/calendars/mine/events" in url:
            return {"items": [{"id": "g1", "summary": "Riunione",
                               "start": {"dateTime": "2026-07-10T09:00:00Z"},
                               "end": {"dateTime": "2026-07-10T10:00:00Z"}}]}
        if "/calendars/readonly-cal/events" in url:
            return {"items": [{"id": "g2", "summary": "Ferragosto",
                               "start": {"date": "2026-08-15"}, "end": {"date": "2026-08-16"}}]}
        return {"items": []}

    monkeypatch.setattr(gc, "_google_request", fake)
    out = gc.list_google_events(s, 1, "2026-07-01T00:00:00Z", "2026-08-31T00:00:00Z")
    by_id = {e["id"]: e for e in out}
    assert by_id["g1"]["editable"] is True
    assert by_id["g2"]["editable"] is False  # accessRole=reader
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v -k "normalize_editable or propagates_access_role"`
Expected: FAIL — `_normalize_google_event` non accetta i nuovi parametri (`TypeError`), `list_google_events` non popola `editable`.

- [ ] **Step 3: Implement**

Sostituire `_normalize_google_event` e il corpo di `list_google_events`:

```python
def _is_recurring(g: dict) -> bool:
    return bool(g.get("recurrence")) or bool(g.get("recurringEventId"))


def _normalize_google_event(g: dict, cal_summary: str, calendar_id: str,
                            access_role: Optional[str], write_scope_ok: bool) -> dict:
    start = g.get("start", {})
    end = g.get("end", {})
    editable = (access_role in ("owner", "writer")) and write_scope_ok and not _is_recurring(g)
    return {
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
    }


def list_google_events(db: Session, user_id: int, time_min: str, time_max: str) -> list:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    row = get_token(db, user_id, "google")
    claqo_id = row.claqo_calendar_id if row else None
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
                                               access_role, write_scope_ok))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v`
Expected: all pass (inclusi i test Task 4 se non ancora eseguiti — vanno entrambi verdi insieme).

- [ ] **Step 5: Commit**

```bash
git add app/services/google_calendar.py tests/test_google_calendar.py
git commit -F- <<'EOF'
feat(calendar): overlay Google propaga accessRole → editable per-evento (esclude ricorrenze)

v3.5.0-alpha.172.252
EOF
```

---

## Task 6: Router `calendar.py` — endpoint scrittura esterna + diagnosticabilità overlay

**Files:**
- Modify: `app/routers/calendar.py` (import, nuovi endpoint dopo `google_overlay`, fix del bare `except`)
- Test: `tests/test_calendar_google_write_api.py` (new, fixture `client` riusata da `tests/test_calendar_api.py`)

**Interfaces:**
- Consumes: `get_external_event`, `update_external_event`, `delete_external_event` (Task 4).
- Produces:
  - `GET /calendar/api/google-events/{calendar_id}/{event_id}` (RequireView) → evento normalizzato + `etag`, o 404.
  - `PUT /calendar/api/google-events/{calendar_id}/{event_id}` (RequireManage, Form: `title?, start_at?, end_at?, all_day?, location?, etag?`) → risultato `update_external_event` mappato su HTTP (`200` ok, `409` su `conflict`, `403` su `forbidden`, `404` su `not_found`/`not_connected`).
  - `DELETE /calendar/api/google-events/{calendar_id}/{event_id}` (RequireManage, Form opzionale `etag?`) → stesso mapping.
  - `GET /calendar/api/google-overlay` fix: `except Exception as e: log.warning(...); return {"events": [], "error": True}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calendar_google_write_api.py
from tests.test_calendar_api import client  # noqa: F401
from datetime import timedelta
from app.services.clock import now_utc
from app.models.models import UserOAuthToken


def _connect(s, scopes="https://www.googleapis.com/auth/calendar.events"):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         expires_at=now_utc() + timedelta(hours=1), scopes=scopes))
    s.commit()


def test_get_google_event_ok(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {
            "id": "e1", "summary": "Riunione", "etag": '"abc"',
            "start": {"dateTime": "2026-07-10T09:00:00Z"},
            "end": {"dateTime": "2026-07-10T10:00:00Z"}})
    r = c.get("/calendar/api/google-events/cal1/e1")
    assert r.status_code == 200
    assert r.json()["title"] == "Riunione"
    assert r.json()["etag"] == '"abc"'


def test_get_google_event_404_without_connection(client):
    c, s = client
    r = c.get("/calendar/api/google-events/cal1/e1")
    assert r.status_code == 404


def test_put_google_event_updates(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {
            "id": "e1", "summary": body.get("summary"),
            "start": body.get("start"), "end": body.get("end")})
    r = c.put("/calendar/api/google-events/cal1/e1", data={
        "title": "Rinviata", "start_at": "2026-07-10T09:00:00", "end_at": "2026-07-10T10:00:00"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_put_google_event_conflict_returns_409(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    import urllib.error
    def boom(*a, **k):
        raise urllib.error.HTTPError("url", 412, "Precondition Failed", {}, None)
    monkeypatch.setattr(gc, "_google_request", boom)
    r = c.put("/calendar/api/google-events/cal1/e1", data={"title": "X", "etag": '"stale"'})
    assert r.status_code == 409


def test_put_google_event_forbidden_returns_403(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    import urllib.error
    def boom(*a, **k):
        raise urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
    monkeypatch.setattr(gc, "_google_request", boom)
    r = c.put("/calendar/api/google-events/cal1/e1", data={"title": "X"})
    assert r.status_code == 403


def test_delete_google_event_ok(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {})
    r = c.request("DELETE", "/calendar/api/google-events/cal1/e1")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_delete_google_event_404_when_already_gone_is_ok(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    import urllib.error
    def boom(*a, **k):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)
    monkeypatch.setattr(gc, "_google_request", boom)
    r = c.request("DELETE", "/calendar/api/google-events/cal1/e1")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_google_write_endpoints_require_manage_calendar(client, monkeypatch):
    # riusa la fixture: il ruolo di test ha gia' manage_calendar; qui verifichiamo solo
    # che il dependency sia effettivamente cablato leggendo le route registrate.
    import app.main as main_mod
    paths = {r.path for r in main_mod.app.routes if hasattr(r, "path")}
    assert "/calendar/api/google-events/{calendar_id}/{event_id}" in paths


def test_overlay_logs_and_flags_error_on_exception(client, monkeypatch, caplog):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(gc, "list_google_events", boom)
    r = c.get("/calendar/api/google-overlay", params={"start": "2026-07-01T00:00:00Z",
              "end": "2026-07-31T00:00:00Z"})
    assert r.status_code == 200
    assert r.json() == {"events": [], "error": True}


def test_overlay_no_error_flag_when_not_connected(client):
    c, s = client
    r = c.get("/calendar/api/google-overlay", params={"start": "2026-07-01T00:00:00Z",
              "end": "2026-07-31T00:00:00Z"})
    assert r.status_code == 200
    assert r.json() == {"events": []}  # invariato: non connesso non e' un errore
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_google_write_api.py -v`
Expected: FAIL — 404 sui nuovi path (non esistono), `test_overlay_logs_and_flags_error_on_exception` fallisce (`{"events": []}` senza `error`).

- [ ] **Step 3: Implement**

In `app/routers/calendar.py`, import in testa:

```python
from app.services import google_calendar
```

(oggi importato lazy dentro `google_overlay` — spostarlo in testa perché ora serve anche ai nuovi endpoint; nessun ciclo di import noto, `google_calendar.py` non importa `calendar.py`).

Sostituire il blocco `google_overlay` (righe 233-243):

```python
@router.get("/calendar/api/google-overlay", dependencies=[RequireView])
async def google_overlay(start: Optional[str] = None, end: Optional[str] = None,
                         request: Request = None, db: Session = Depends(get_db)):
    u = current_user_optional(request)
    if not u or not start or not end:
        return {"events": []}
    try:
        return {"events": google_calendar.list_google_events(db, u.id, start, end)}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"google_overlay fallito user={u.id}: {e}")
        return {"events": [], "error": True}
```

Aggiungere in fondo al file:

```python
_ERROR_STATUS = {"conflict": 409, "forbidden": 403, "not_found": 404, "not_connected": 404,
                 "http_error": 502}


@router.get("/calendar/api/google-events/{calendar_id}/{event_id}", dependencies=[RequireView])
async def get_google_event(calendar_id: str, event_id: str, request: Request,
                           db: Session = Depends(get_db)):
    u = current_user_optional(request)
    if not u:
        raise HTTPException(401, "Non autenticato")
    ev = google_calendar.get_external_event(db, u.id, calendar_id, event_id)
    if not ev:
        raise HTTPException(404, "Evento Google non trovato o non collegato")
    return ev


@router.put("/calendar/api/google-events/{calendar_id}/{event_id}", dependencies=[RequireManage])
async def put_google_event(
    calendar_id: str, event_id: str, request: Request,
    title: Optional[str] = Form(None), start_at: Optional[str] = Form(None),
    end_at: Optional[str] = Form(None), all_day: Optional[str] = Form(None),
    location: Optional[str] = Form(None), etag: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    u = current_user_optional(request)
    if not u:
        raise HTTPException(401, "Non autenticato")
    allday_bool = None if all_day is None else str(all_day).lower() in ("1", "true", "on", "yes")
    res = google_calendar.update_external_event(
        db, u.id, calendar_id, event_id, title=title, start_at=start_at, end_at=end_at,
        all_day=allday_bool, location=location, etag=etag or None)
    db.commit()
    if not res["ok"]:
        raise HTTPException(_ERROR_STATUS.get(res["error"], 502), res["error"] or "Errore Google")
    return res


@router.delete("/calendar/api/google-events/{calendar_id}/{event_id}", dependencies=[RequireManage])
async def delete_google_event(calendar_id: str, event_id: str, request: Request,
                              etag: Optional[str] = Form(None), db: Session = Depends(get_db)):
    u = current_user_optional(request)
    if not u:
        raise HTTPException(401, "Non autenticato")
    res = google_calendar.delete_external_event(db, u.id, calendar_id, event_id, etag=etag or None)
    db.commit()
    if not res["ok"]:
        raise HTTPException(_ERROR_STATUS.get(res["error"], 502), res["error"] or "Errore Google")
    return res
```

Nota RBAC/route-matching: questi path hanno un prefisso letterale `/calendar/api/google-events/` diverso da `/calendar/api/events/{event_id}` (locale) — nessuna collisione di routing possibile, non serve l'accortezza "letterale-prima-del-parametrico" usata altrove nel progetto.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_google_write_api.py tests/test_calendar_sync_api.py tests/test_calendar_permissions.py -v`
Expected: all pass (compreso il contratto invariato `{"events": []}` senza connessione).

- [ ] **Step 5: Commit**

```bash
git add app/routers/calendar.py tests/test_calendar_google_write_api.py
git commit -F- <<'EOF'
feat(calendar): endpoint GET/PUT/DELETE google-events + overlay logga e flagga errori

v3.5.0-alpha.172.253
EOF
```

---

## Task 7: Frontend `calendar_page.js` — overlay editabile per-evento + drag&drop

**Files:**
- Modify: `app/static/js/calendar_page.js` (righe 29-46 mapping overlay, 82-89 `_calPutTimes`, 109-113 `eventClick`)
- Modify: `app/static/css/main.css` (o lo style block esistente in `calendar.html` — verificare dove vive `.cal-google`/`.cal-marker` prima di aggiungere `.cal-google-editable`)
- Modify: `app/templates/base.html` (cache-buster `?v=` su `calendar_page.js`)
- Test: nessun test Python (JS non testato da pytest in questo progetto); verifica manuale/Playwright in Task 10.

**Interfaces:**
- Consumes: `editable`, `calendar_id`, `event_id`/`id` dai payload `/calendar/api/google-overlay` (Task 5/6).
- Produces: overlay FullCalendar con `editable` per-evento reale; drag&drop instradato su `/calendar/api/google-events/...` per gli eventi Google editabili.

- [ ] **Step 1: Individuare la definizione CSS esistente di `.cal-google`/`.cal-marker`**

```bash
grep -rn "cal-google\|cal-marker" app/static/css/ app/templates/pages/calendar.html
```

Aggiungere accanto la nuova regola (bordo pieno invece di tratteggiato, stesso tono):

```css
.cal-google-editable { border-style: solid !important; opacity: 0.9; }
```

- [ ] **Step 2: Estendere il mapping overlay (righe 29-43)**

```javascript
if (showG && showG.checked) {
  try {
    const gr = await fetch('/calendar/api/google-overlay?start=' +
      encodeURIComponent(info.startStr) + '&end=' + encodeURIComponent(info.endStr));
    if (gr.ok) {
      const gd = await gr.json();
      if (gd.error && window.toast) { /* indicatore leggero, non bloccante */ }
      (gd.events || []).forEach(g => evs.push({
        id: 'g:' + g.calendar_id + ':' + g.id,
        title: g.title, start: g.start, end: g.end, allDay: g.all_day,
        editable: !!g.editable,
        classNames: g.editable ? ['cal-google', 'cal-google-editable'] : ['cal-google'],
        extendedProps: { google: true, editable: !!g.editable,
                         calendar_id: g.calendar_id, event_id: g.id }
      }));
    }
  } catch (e) { /* overlay best-effort */ }
}
```

Nota: l'`id` FullCalendar composito `'g:'+calendar_id+':'+id` evita collisioni con gli id numerici locali (che sono interi puri) e rende `_calPutTimes`/`eventClick` capaci di distinguere subito la sorgente senza guardare solo `extendedProps`.

- [ ] **Step 3: `eventClick` — apre il modale in modalità esterna per i Google editabili**

```javascript
eventClick: function (info) {
  if (info.event.extendedProps.marker) return;
  if (info.event.extendedProps.google && !info.event.extendedProps.editable) return; // read-only, nessuna azione
  info.jsEvent.preventDefault();
  if (info.event.extendedProps.google) {
    window.openEventModal({
      external: { calendar_id: info.event.extendedProps.calendar_id,
                 event_id: info.event.extendedProps.event_id },
      onSaved: () => _cal.refetchEvents()
    });
    return;
  }
  window.openEventModal({ event: _fcEventToObj(info.event), onSaved: () => _cal.refetchEvents() });
},
```

- [ ] **Step 4: `_calPutTimes` — instrada drag&drop verso l'endpoint giusto**

```javascript
function _calPutTimes(info) {
  if (info.event.extendedProps.marker) { info.revert(); return; }
  const isGoogle = info.event.extendedProps.google;
  const startIso = info.event.start.toISOString();
  const endIso = info.event.end ? info.event.end.toISOString() : startIso;
  if (isGoogle) {
    const fd = new FormData();
    fd.append('start_at', startIso);
    fd.append('end_at', endIso);
    const cal = info.event.extendedProps.calendar_id, eid = info.event.extendedProps.event_id;
    fetch('/calendar/api/google-events/' + encodeURIComponent(cal) + '/' + encodeURIComponent(eid),
          { method: 'PUT', body: fd })
      .then(r => { if (!r.ok) { info.revert(); if (window.toast) toast(mfT('cal.google.conflict'), 'error'); } });
    return;
  }
  const fd = new FormData();
  fd.append('start_at', startIso);
  fd.append('end_at', endIso);
  fetch('/calendar/api/events/' + info.event.id, { method: 'PUT', body: fd })
    .then(r => { if (!r.ok) { info.revert(); if (window.toast) toast(mfT('common.error'), 'error'); } });
}
```

- [ ] **Step 5: Cache-buster**

In `app/templates/base.html`, bump `?v=` sul `<script src=".../calendar_page.js?v=...">`.

- [ ] **Step 6: i18n (stesso commit)**

Aggiungere a `app/static/js/i18n.js` (blocco `cal.*`, accanto alle chiavi esistenti):

```javascript
'cal.google.conflict': {it: 'Evento modificato nel frattempo su Google', en: 'Event changed on Google meanwhile', fr: 'Evenement modifie entre-temps sur Google', de: 'Termin wurde zwischenzeitlich in Google geandert', es: 'Evento modificado mientras tanto en Google'},
'cal.google.readonly':  {it: 'Solo lettura (Google)', en: 'Read-only (Google)', fr: 'Lecture seule (Google)', de: 'Nur Lesen (Google)', es: 'Solo lectura (Google)'},
```

- [ ] **Step 7: Verifica manuale rapida**

Avviare l'app (`.venv/Scripts/python.exe run.py`, no reload — memo uvicorn orfani), aprire `/calendar` con un utente senza Google collegato: nessuna regressione (`cal-show-google` off di default o overlay vuoto). Verifica completa e2e rimandata al Task 10 (richiede mock lato server).

- [ ] **Step 8: Commit**

```bash
git add app/static/js/calendar_page.js app/static/css/main.css app/templates/base.html app/static/js/i18n.js
git commit -F- <<'EOF'
feat(calendar): overlay Google editabile per-evento (drag&drop + click condizionali)

v3.5.0-alpha.172.254
EOF
```

---

## Task 8: Frontend `event_modal.js` — modalità "esterna" (Google) con conferma a due passi

**Files:**
- Modify: `app/static/js/event_modal.js` (tutto il file: nuovo ramo `opts.external`)
- Modify: `app/templates/base.html` (cache-buster)
- Test: nessun test Python; verifica Playwright in Task 10.

**Interfaces:**
- Consumes: `GET/PUT/DELETE /calendar/api/google-events/{cal}/{eid}` (Task 6).
- Produces: `openEventModal({ external: {calendar_id, event_id}, onSaved })` — nuova firma accettata in aggiunta a quella esistente (`event`/`prefill`), retrocompatibile.

- [ ] **Step 1: Estendere `_ctx` e `openEventModal` per la modalità esterna**

```javascript
function openEventModal(opts) {
  opts = opts || {};
  _ensureModal();
  _ctx = { id: null, external: opts.external || null, onSaved: opts.onSaved || null };
  if (_ctx.external) { _openExternal(_ctx.external); return; }
  // ... resto invariato per la modalita' locale ...
}

function _openExternal(ext) {
  fetch('/calendar/api/google-events/' + encodeURIComponent(ext.calendar_id) + '/' +
        encodeURIComponent(ext.event_id))
    .then(function (r) {
      if (!r.ok) { if (window.toast) toast(_T('cal.google.notEditable'), 'error'); return null; }
      return r.json();
    })
    .then(function (ev) {
      if (!ev) return;
      _ctx.etag = ev.etag;
      document.getElementById('evm-title').setAttribute('data-i18n', 'cal.event.edit');
      document.getElementById('evm-id').value = '';
      document.getElementById('evm-allday').checked = !!ev.all_day;
      _syncAllDay();
      document.getElementById('evm-field-title').value = ev.title || '';
      document.getElementById('evm-location').value = '';
      document.getElementById('evm-url').value = '';
      document.getElementById('evm-status').closest('.form-group').style.display = 'none'; // Google non modella lo stato Claqo
      var startVal = _toLocalInput(ev.start, ev.all_day);
      document.getElementById('evm-start').value = startVal;
      document.getElementById('evm-end').value = _toLocalInput(ev.end, ev.all_day) || startVal;
      document.getElementById('evm-linked').style.display = 'block';
      document.getElementById('evm-linked').textContent = _T('cal.google.readonly') === ev.title ? '' :
        (window.mfT ? mfT('settings.account.googleLabel') || 'Google' : 'Google');
      document.getElementById('evm-delete').style.display = 'inline-block';
      if (window.applyI18n) applyI18n(document.getElementById(MODAL_ID));
      openModal(MODAL_ID);
    });
}
```

- [ ] **Step 2: `_onSave`/`_onDelete` — smistamento in testa alle funzioni esistenti**

```javascript
function _onSave() {
  if (_ctx.external) { _onSaveExternal(); return; }
  // ... corpo esistente invariato ...
}

function _onSaveExternal() {
  var title = document.getElementById('evm-field-title').value.trim();
  if (!title) { if (window.toast) toast(_T('cal.event.err.title'), 'error'); return; }
  var allday = document.getElementById('evm-allday').checked;
  var start = document.getElementById('evm-start').value;
  var end = document.getElementById('evm-end').value || start;
  var fd = new FormData();
  fd.append('title', title);
  fd.append('start_at', start);
  fd.append('end_at', end);
  fd.append('all_day', allday ? '1' : '0');
  if (_ctx.etag) fd.append('etag', _ctx.etag);
  var url = '/calendar/api/google-events/' + encodeURIComponent(_ctx.external.calendar_id) +
            '/' + encodeURIComponent(_ctx.external.event_id);
  fetch(url, { method: 'PUT', body: fd }).then(function (r) {
    if (r.status === 409) { if (window.toast) toast(_T('cal.google.conflict'), 'error'); closeModal(MODAL_ID); if (_ctx.onSaved) _ctx.onSaved(); return; }
    if (!r.ok) { if (window.toast) toast(_T('common.error'), 'error'); return; }
    if (window.toast) toast(_T('cal.event.saved'), 'success');
    closeModal(MODAL_ID);
    if (_ctx.onSaved) _ctx.onSaved();
  });
}

function _onDelete() {
  if (_ctx.external) { _onDeleteExternalStep1(); return; }
  // ... corpo esistente invariato (confirm() nativo, solo per eventi locali) ...
}

// Conferma a due passi per eventi Google esterni (Domanda 7 design: irreversibile,
// nessun soft-delete lato Google). Primo click mostra un pannello inline col titolo
// dell'evento; il secondo bottone esplicito ("Elimina definitivamente da Google")
// esegue davvero la DELETE.
function _onDeleteExternalStep1() {
  var panel = document.getElementById('evm-external-delete-confirm');
  if (panel) { panel.style.display = 'block'; return; }
  panel = document.createElement('div');
  panel.id = 'evm-external-delete-confirm';
  panel.style.cssText = 'margin-top:8px;padding:8px;border:1px solid #ef4444;border-radius:6px;font-size:12px;';
  panel.innerHTML =
    '<p style="margin:0 0 8px;" data-i18n="cal.google.deleteWarning">' +
    'Eliminazione definitiva da Google Calendar, non recuperabile.</p>' +
    '<button class="btn btn-danger btn-sm" type="button" id="evm-external-delete-confirm-btn" ' +
    'data-i18n="cal.google.deleteConfirmBtn">Elimina definitivamente da Google</button>';
  document.getElementById('evm-delete').insertAdjacentElement('afterend', panel);
  if (window.applyI18n) applyI18n(panel);
  document.getElementById('evm-external-delete-confirm-btn').addEventListener('click', _onDeleteExternalStep2);
}

function _onDeleteExternalStep2() {
  var url = '/calendar/api/google-events/' + encodeURIComponent(_ctx.external.calendar_id) +
            '/' + encodeURIComponent(_ctx.external.event_id);
  fetch(url, { method: 'DELETE' }).then(function (r) {
    if (!r.ok) { if (window.toast) toast(_T('common.error'), 'error'); return; }
    closeModal(MODAL_ID);
    if (_ctx.onSaved) _ctx.onSaved();
  });
}
```

- [ ] **Step 3: reset del pannello di conferma alla chiusura/riapertura del modale**

In `_ensureModal`/`openEventModal`, rimuovere `#evm-external-delete-confirm` se presente prima di ri-popolare (evita che riappaia già "armato" su un evento diverso):

```javascript
var oldPanel = document.getElementById('evm-external-delete-confirm');
if (oldPanel) oldPanel.remove();
```

Inserire questa riga in testa a `openEventModal`, prima del branching `external`/locale.

- [ ] **Step 4: i18n (stesso commit)**

```javascript
'cal.google.notEditable':      {it: 'Evento non modificabile', en: 'Event not editable', fr: 'Evenement non modifiable', de: 'Termin nicht bearbeitbar', es: 'Evento no editable'},
'cal.google.deleteWarning':    {it: 'Eliminazione definitiva da Google Calendar, non recuperabile.', en: 'Permanent deletion from Google Calendar, not recoverable.', fr: 'Suppression definitive de Google Agenda, non recuperable.', de: 'Endgultiges Loschen aus Google Kalender, nicht wiederherstellbar.', es: 'Eliminacion definitiva de Google Calendar, no recuperable.'},
'cal.google.deleteConfirmBtn': {it: 'Elimina definitivamente da Google', en: 'Delete permanently from Google', fr: 'Supprimer definitivement de Google', de: 'Endgultig aus Google loschen', es: 'Eliminar definitivamente de Google'},
```

- [ ] **Step 5: Cache-buster**

Bump `?v=` su `event_modal.js` in `base.html`.

- [ ] **Step 6: Commit**

```bash
git add app/static/js/event_modal.js app/templates/base.html app/static/js/i18n.js
git commit -F- <<'EOF'
feat(calendar): event_modal modalita esterna Google, conferma eliminazione a due passi

v3.5.0-alpha.172.255
EOF
```

---

## Task 9: `settings_account.js` — opt-in "Attiva editing calendario"

**Files:**
- Modify: `app/static/js/settings_account.js` (righe 29-44, stesso blocco dell'opt-in Gmail)
- Modify: `app/templates/base.html` (cache-buster)
- Test: nessun test Python (pagina impostazioni non ha suite dedicata per questo componente — verifica manuale + Task 10).

**Interfaces:**
- Consumes: `GET /auth/oauth/status` (esistente, ritorna già `p.scopes`); `GET /auth/oauth/google/start?scopes=calendar_write` (Task 2).

- [ ] **Step 1: Aggiungere il badge/link accanto al blocco Gmail esistente**

In `app/static/js/settings_account.js`, dentro il blocco `if (pid === 'google') { ... }` (righe 38-44), dopo la riga del badge Gmail:

```javascript
if (pid === 'google') {
  const hasMail = (p.scopes || '').indexOf('gmail.readonly') !== -1;
  actions += hasMail
    ? ' <span class="badge badge-active" style="font-size:11px;">Email &#x2713;</span>'
    : ' <a class="btn btn-secondary btn-sm" href="/auth/oauth/google/start?scopes=email" ' +
      'data-i18n="mail.connect">Collega Gmail</a>';
  const hasCalWrite = (p.scopes || '').indexOf('calendar.events') !== -1 ||
                      /\/auth\/calendar(\s|$)/.test(p.scopes || '');
  actions += hasCalWrite
    ? ' <span class="badge badge-active" style="font-size:11px;" data-i18n="settings.account.calendarWriteActive">Editing calendario &#x2713;</span>'
    : ' <a class="btn btn-secondary btn-sm" href="/auth/oauth/google/start?scopes=calendar_write" ' +
      'data-i18n="settings.account.calendarWrite">Attiva editing calendario</a>';
}
```

- [ ] **Step 2: i18n (stesso commit)**

```javascript
'settings.account.calendarWrite':       {it: 'Attiva editing calendario', en: 'Enable calendar editing', fr: 'Activer edition agenda', de: 'Kalenderbearbeitung aktivieren', es: 'Activar edicion de calendario'},
'settings.account.calendarWriteActive': {it: 'Editing calendario attivo', en: 'Calendar editing active', fr: 'Edition agenda active', de: 'Kalenderbearbeitung aktiv', es: 'Edicion de calendario activa'},
```

- [ ] **Step 3: Cache-buster**

Bump `?v=` su `settings_account.js` in `base.html`.

- [ ] **Step 4: Verifica manuale**

Avviare l'app, `/settings` tab account, verificare che senza `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` configurati il link resti `disabled` (comportamento ereditato dal blocco esistente, invariato), e che con Google collegato ma senza scope scrittura appaia il link "Attiva editing calendario".

- [ ] **Step 5: Commit**

```bash
git add app/static/js/settings_account.js app/templates/base.html app/static/js/i18n.js
git commit -F- <<'EOF'
feat(calendar): opt-in UI "Attiva editing calendario" in /settings

v3.5.0-alpha.172.256
EOF
```

---

## Task 10: Smoke Playwright end-to-end + bump versione + CHANGELOG + STATO

**Files:**
- Modify: `app/main.py` (bump `version=` in `FastAPI(...)`, riga 2408)
- Modify: `CHANGELOG.md`, `docs/STATO.md`
- Verifica: browser reale via `mcp__plugin_playwright_playwright__*` (o skill `run`), mock server-side dove serve (nessuna vera chiamata a Google in dev senza client OAuth configurato — usare `monkeypatch`/variabili d'ambiente di test non applicabili a un browser reale: per lo smoke, collegare un account Google **di test** se disponibile, altrimenti verificare solo il percorso "non connesso"/"connesso senza scope scrittura" che non richiede credenziali reali).

**Criterio di done:** nessun errore console JS, i tre stati dell'overlay sono visivamente distinti (`cal-google` dashed read-only, `cal-google-editable` solid, evento locale invariato), il flusso "Attiva editing calendario" in `/settings` reindirizza correttamente a Google (verificabile fino al redirect, non oltre senza credenziali reali).

- [ ] **Step 1: Riavvio pulito (memo Jinja/OneDrive non ricarica a runtime)**

```bash
# killare eventuali uvicorn residui su :8000, poi:
.venv/Scripts/python.exe -c "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=False)"
```

(no `reload=True` — memo `feedback_uvicorn_reload_orphans_smoke`).

- [ ] **Step 2: Smoke browser — stato "non connesso" (nessuna credenziale richiesta)**

Via Playwright: navigare `/calendar`, login con utente demo, aprire il checkbox "Mostra Google" → verificare che `GET /calendar/api/google-overlay` risponda `{"events": []}` (nessun `error`), zero errori console.

- [ ] **Step 3: Smoke browser — overlay con mock server-side**

Per esercitare il path "editabile" senza un vero account Google, iniettare temporaneamente (solo per questo smoke, non committare) un monkeypatch via un piccolo script di supporto che avvia l'app con `google_calendar._google_request` sostituito da una funzione che ritorna un calendario `accessRole: writer` + uno `reader`, o preparare un `UserOAuthToken` con `scopes` contenente `calendar.events` in un DB di scratch (`db_snapshots/` pattern esistente, MAI il DB reale di Matteo). Verificare via `browser_snapshot`:
- l'evento sul calendario `writer` ha bordo solido (`cal-google-editable`) ed è cliccabile → apre il modale, mostra i campi popolati, il bottone "Elimina" mostra il pannello di conferma a due passi al primo click e non cancella nulla senza il secondo click;
- l'evento sul calendario `reader` ha bordo tratteggiato, il click non apre nulla (comportamento invariato).

- [ ] **Step 4: `browser_console_messages` — zero errori/warning nuovi**

Confrontare con la baseline nota del progetto (memo `feedback_smoke_e2e_browser`: il backend non cattura `ReferenceError` JS, va verificato via browser reale).

- [ ] **Step 5: Bump versione + changelog + stato**

`app/main.py:2408`: `version="3.5.0-alpha.172.257"` (dopo i bump incrementali dei Task 1-9, questo è il bump "di chiusura" della feature).

`CHANGELOG.md`: nuova voce che riassume la feature (scope opt-in, overlay editabile con guardrail ricorrenze/accessRole/etag, conferma a due passi).

`docs/STATO.md`: sezione "in corso" aggiornata con "Eventi Google editabili — CHIUSO, ramo NON pushato, N test, smoke Playwright verde" + prossimo step (probabilmente: smoke di Matteo con un account Google reale prima del push/merge).

- [ ] **Step 6: Suite completa**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v -x -k "calendar or oauth"`
Expected: nessuna regressione sull'intera area calendario/oauth.

- [ ] **Step 7: Commit finale**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -F- <<'EOF'
chore(calendar): chiude eventi Google editabili, bump v3.5.0-alpha.172.257 + changelog + STATO
EOF
```

---

## Note per chi esegue il piano

- Ordine consigliato: Task 1→2 (OAuth) possono girare in parallelo a Task 3 (indipendenti); Task 4 dipende dalla firma finale di `_normalize_google_event` introdotta in Task 5 — se eseguiti da agenti paralleli, unire Task 4+5 in un solo giro prima di lanciare la suite `test_google_calendar.py` per intero. Task 6 dipende da 3+4+5. Task 7+8+9 (frontend) dipendono da 6 e sono indipendenti tra loro. Task 10 chiude tutto.
- Il design doc (`docs/superpowers/specs/2026-07-15-google-calendar-writable-design.md`) è la fonte di verità per il "perché" di ogni scelta; questo piano è il "come". In caso di conflitto tra i due durante l'esecuzione, il design doc vince e va aggiornato esplicitamente se una decisione cambia in corso d'opera.
