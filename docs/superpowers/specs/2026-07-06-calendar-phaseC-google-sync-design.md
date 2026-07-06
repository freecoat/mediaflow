# Calendario Fase C — Sync Google bidirezionale — Design

> Approvato da Matteo il 6 lug 2026. Segue Fase A (OAuth foundation, α.239) e Fase B/B.1 (calendario locale, α.240/241).

## Obiettivo

Sincronizzare il calendario Claqo con Google Calendar, **per-utente**, least-privilege:
- **Push**: gli appuntamenti Claqo dell'utente finiscono in un calendario secondario "Claqo" nel suo account Google (li vede su telefono/Google Calendar).
- **Overlay**: gli eventi Google esistenti dell'utente (altri calendari) si vedono read-only dentro `/calendar` per contesto.

Funziona con mock in sviluppo/test; si accende in produzione appena l'utente configura l'OAuth client Google Cloud (`.env`).

## Decisioni (con Matteo)

- **Direzione**: bidirezionale (push Claqo→Google + overlay Google→Claqo read-only).
- **Trigger push**: automatico se `UserOAuthToken.auto_sync_calendar` è ON (ad ogni create/edit/delete) **più** un bottone "Sincronizza ora" sempre disponibile.
- **Prerequisito**: costruire ora con mock (httpx mockato). Il sync live richiede `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` + consenso utente; senza, il layer resta inerte (nessun errore).

## Modello di sync (dettato dagli scope)

Scope concessi in Fase A: `calendar.app.created` (crea/gestisce SOLO un calendario secondario dedicato e i suoi eventi) + `calendar.readonly` (legge tutti i calendari).

Conseguenze architetturali:
- Push **solo** verso il calendario "Claqo" creato dall'app (non sul primary dell'utente): `calendar.app.created` non consente scrittura altrove.
- Overlay legge gli **altri** calendari via `calendar.readonly`, **escludendo** il calendario Claqo (per non duplicare gli eventi Claqo).
- Claqo è l'unica fonte di verità per gli eventi Claqo (mirror one-way): non si ri-leggono modifiche dal calendario Claqo verso Claqo. Gli eventi overlay sono read-only (nessun conflitto da risolvere → niente conflict resolution).
- Sync è intrinsecamente **per-utente**: i token sono per-utente, il calendario "Claqo" vive nell'account Google del singolo utente, e si sincronizzano gli eventi `owner_user_id == user`.

## Vincoli

- **Nessuna migrazione DB**: `CalendarEvent` ha già le colonne sync da Fase B (`source`, `external_calendar_id`, `external_event_id`, `sync_state`, `last_synced_at`, `sync_error`). `UserOAuthToken` ha `auto_sync_calendar` + `claqo_calendar_id`.
- **Token**: usare `get_valid_access_token(db, user_id, "google")` (auto-refresh, NON committa — il chiamante committa).
- **HTTP**: `httpx` (già dipendenza). Chiamate isolate in `google_calendar.py` per mockabilità (monkeypatch di un unico helper `_google_request`).
- **Best-effort**: nessuna chiamata Google deve bloccare o rompere il CRUD locale o il render del calendario.
- **Tenant/RBAC**: gli endpoint calendario restano sotto `view_calendar`/`manage_calendar`. Il sync opera sugli eventi dell'utente corrente (`current_user`).
- **Form-based** per gli endpoint di scrittura; **i18n 5 lingue**; **cache-buster** su static; convenzioni di progetto invariate.
- **Config env**: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_REDIRECT_BASE_URL` (già documentati). Nessuna nuova env.

## Architettura

### 1. `app/services/google_calendar.py` — client Google Calendar API

Unità con una sola responsabilità: parlare con l'API Google Calendar. Tutte le chiamate HTTP passano da un unico helper privato `_google_request(method, url, token, json=None, params=None) -> dict|None` (punto di mock nei test).

Funzioni:
- `ensure_claqo_calendar(db, user_id) -> Optional[str]`
  - Se `UserOAuthToken.claqo_calendar_id` presente → ritorna quello.
  - Altrimenti `POST /calendar/v3/calendars` con `{summary: "Claqo"}` → salva `claqo_calendar_id` sulla riga token (no commit) → ritorna id.
  - Ritorna `None` se non connesso / token assente.
- `push_event(db, user_id, ev) -> bool`
  - Richiede token + `ensure_claqo_calendar`. Costruisce la risorsa Google via `_event_to_google(ev)`.
  - Se `ev.external_event_id` nullo → `POST .../calendars/{cal}/events` → salva `ev.external_event_id`, `ev.external_calendar_id=cal`.
  - Altrimenti → `PUT .../events/{external_event_id}`.
  - Successo → `ev.sync_state="synced"`, `ev.last_synced_at=now_utc()`, `ev.sync_error=None`, ritorna True.
  - Errore → `ev.sync_state="error"` (o `pending_push` in autosync, vedi orchestrazione), `ev.sync_error=str(e)`, ritorna False.
- `delete_event(db, user_id, ev) -> bool`
  - Se `ev.external_event_id` nullo → no-op, ritorna True.
  - `DELETE .../events/{external_event_id}` → `ev.sync_state="deleted"`, `ev.external_event_id=None`. 404 dal server = già assente → trattato come successo.
- `list_google_events(db, user_id, time_min, time_max) -> list[dict]`
  - `GET /calendar/v3/users/me/calendarList` → per ogni calendario con id ≠ `claqo_calendar_id`: `GET .../events?timeMin&timeMax&singleEvents=true&maxResults=...`.
  - Normalizza in `{id, title, start, end, all_day, calendar, read_only: True}`. Errore su un calendario → salta quel calendario (non l'intero overlay).
- Helper puri: `_event_to_google(ev) -> dict` (all_day → `{date}`; timed → `{dateTime, timeZone?}`), `_normalize_google_event(g, cal_summary) -> dict`.

### 2. `app/services/calendar_sync.py` — orchestrazione

- `maybe_autosync_event(db, user_id, ev, deleted=False) -> None`
  - Legge la riga token; se non connessa o `auto_sync_calendar` False → ritorna (no-op).
  - `deleted` → `google_calendar.delete_event`; altrimenti `push_event`.
  - Best-effort: eccezioni catturate; su fallimento `ev.sync_state="pending_push"` + `ev.sync_error`. NON rilancia (il CRUD locale è già committato/valido).
- `sync_user_pending(db, user_id) -> dict`
  - Push: tutti gli `CalendarEvent` attivi con `owner_user_id==user`, `is_active==True`, `sync_state in ("local","pending_push","error")` → `push_event`.
  - Delete: gli `CalendarEvent` con `is_active==False`, `external_event_id` non nullo, `sync_state != "deleted"` → `delete_event`.
  - Ritorna `{"pushed": n, "deleted": m, "failed": k}`. Committa alla fine.

### 3. Router `app/routers/calendar.py`

- `create_event`/`update_event`/`delete_event`: dopo `db.commit()`, chiamare `maybe_autosync_event(db, current_user.id, ev, deleted=…)` poi `db.commit()` (per persistere gli aggiornamenti sync). Import lazy per evitare cicli.
- `POST /calendar/api/sync` (RequireManage) → `sync_user_pending(db, current_user.id)` → JSON risultato.
- `GET /calendar/api/google-overlay?start&end` (RequireView) → `list_google_events`; se non connesso o errore → `{"events": []}` (mai 500).

### 4. Frontend

- `app/static/js/calendar_page.js`:
  - Nuova sorgente overlay: dopo il fetch locale, se il checkbox "Mostra Google" è ON, fetch `/calendar/api/google-overlay` per il range e push come eventi `editable:false`, `classNames:['cal-google']`, `display:'block'` (stile smorzato). `eventClick` su un overlay → no modal (read-only), solo tooltip.
  - Skippare gli overlay in `eventDrop`/`eventResize`/`eventClick` (come i marker).
- `app/templates/pages/calendar.html`:
  - Toolbar: checkbox "Mostra Google" (default ON) + bottone "Sincronizza" (`onclick="calSyncNow()"`). CSS `.cal-google` (colore smorzato, bordo tratteggiato diverso dai marker).
  - `calSyncNow()`: `POST /calendar/api/sync` → toast `pushed/deleted/failed` → `refetchEvents`.
- i18n: `cal.sync.now`, `cal.sync.done` (con conteggi), `cal.sync.error`, `cal.showGoogle`, `cal.google.readonly`.
- Badge "sincronizzato": sugli eventi locali con `external_event_id` (dallo `_serialize_event`, aggiungere `external_event_id` all'output) → piccola icona/tooltip.

### 5. Serializzazione

`_serialize_event` (router, Fase B) aggiunge `sync_state` ed `external_event_id` all'output, così il frontend distingue synced/local/pending/error.

## Flusso dati

```
create/edit (toggle ON) → save locale + commit → maybe_autosync → ensure_calendar → push → external_event_id + synced → commit
delete → soft-delete + commit → maybe_autosync(deleted) → Google DELETE → sync_state=deleted → commit
Sincronizza ora → POST /calendar/api/sync → push pending + delete pending → {pushed,deleted,failed}
load /calendar → eventi locali (+ badge synced) + overlay Google read-only (se ON) + marcatori derivati
```

## Error handling

- `get_valid_access_token` None → tutte le funzioni Google ritornano None/[]/False senza eccezione.
- Errori HTTP in autosync → `pending_push` + `sync_error`; CRUD locale intatto.
- Errori HTTP in `sync_user_pending` → contati in `failed`, gli altri procedono.
- Overlay in errore (o non connesso) → `{"events": []}`, il calendario locale funziona comunque.
- Delete su Google con 404 → successo (idempotente).

## Testing (mock httpx via monkeypatch di `_google_request`)

- `ensure_claqo_calendar`: crea se assente (salva id), riusa se presente, None se non connesso.
- `push_event`: insert (salva external_event_id + synced), update (PUT se id presente), errore → sync_state error.
- `delete_event`: DELETE ok, 404 = successo, no-op se senza external_event_id.
- `list_google_events`: esclude il calendario Claqo, salta calendari in errore, normalizza.
- `maybe_autosync_event`: no-op se toggle OFF / non connesso; push se ON; su errore → pending_push, nessuna eccezione propagata.
- `sync_user_pending`: conta pushed/deleted/failed su un set misto.
- Endpoint: `POST /calendar/api/sync` (403 senza manage_calendar; risultato con manage), `GET /calendar/api/google-overlay` ritorna `{events:[]}` se non connesso.
- Smoke Playwright: con `_google_request` mockato lato server (o token assente → overlay vuoto), verifica bottone Sincronizza + checkbox + 0 errori console.

## Fuori scope (YAGNI)

- Niente pull-edit del calendario Claqo verso Claqo (mirror one-way).
- Niente ricorrenze, niente inviti/attendees su Google, niente webhook/watch (si fa poll al load).
- Niente sync cross-utente o a livello tenant.
- Niente Microsoft (scaffold "Prossimamente" resta).

## Self-review

- Placeholder: nessun TBD.
- Consistenza: `google_calendar.py` = unico layer HTTP; `calendar_sync.py` = orchestrazione; router = wiring. Nessuna doppia fonte.
- Scope: singola iterazione (un plan). Sync non tocca la logica locale Fase B se non nei 3 punti di wiring + serializzazione.
- Ambiguità risolte: push solo su calendario Claqo (scope), overlay esclude Claqo, per-utente, no conflitti (overlay read-only + mirror one-way).
