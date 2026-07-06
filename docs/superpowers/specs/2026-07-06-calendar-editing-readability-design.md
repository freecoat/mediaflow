# Calendario — Editing eventi + leggibilità — Design

> Fase B.1 (rifinitura). Migliora la UX del calendario introdotto in α.172.240.
> Approvato da Matteo il 6 lug 2026.

## Problema

La Fase B (α.172.240) ha portato calendario + tab appuntamenti funzionanti ma con UX grezza (feedback Matteo):

1. **Sovrapposizioni** — vista mese (`dayGridMonth`) default: eventi con orario si accavallano nelle celle.
2. **Orari non visibili** — in vista mese gli orari sono illeggibili; la creazione via `prompt()` non permette di impostare orari.
3. **Nessun editing** — manca `eventClick` sul calendario → cliccare un evento non fa nulla; nel tab acquisizioni la lista è read-only. Impossibile modificare/eliminare un appuntamento.
4. **Tab acquisizioni poco leggibile** — righe minimali, create via `prompt()`.

## Scope (deciso con Matteo)

- **Solo tab Appuntamenti + leggibilità** dentro `/acquisitions`. NON si tocca kanban/tabella/detail-panel del resto della pagina.
- **Vista default settimana** (griglia oraria).
- **Modal evento completo condiviso** — un solo componente usato sia in `/calendar` sia nel tab acquisizioni.

Fuori scope (YAGNI, rimandati a Fase C+): ricorrenze, reminder/notifiche, inviti email. Nessuna modifica backend.

## Vincoli

- Il backend Task 3 (α.172.240) è già sufficiente: `GET /calendar/api/events` serializza tutti i campi (title, start, end, all_day, location, meeting_url, status, acquisition_id, project_id, client_id); `POST`/`PUT`/`DELETE` Form-based esistono. **Nessuna modifica a `app/routers/calendar.py`.**
- Vanilla JS, niente framework. Riuso helper globali (`openModal`/`closeModal`/`toast`/`api`/`escapeHtml`/`mfT`) da `global.js` — non ridefinirli (vedi trappola helper centralizzati).
- Form-based: il modal invia `FormData` a POST/PUT/DELETE.
- Cache-buster `?v={{ app_version }}` su ogni `<script>` static.
- i18n 5 lingue (it/en/fr/de/es) per ogni stringa nuova, stesso commit.
- Anti-XSS: `meeting_url` linkificato solo se schema `http(s)` (già applicato nel tab; replicare nel modal se mostra link).

## Architettura

Tre unità, ciascuna con responsabilità singola:

### 1. `app/static/js/event_modal.js` — modal evento condiviso (unica fonte di verità)

Modulo autonomo, caricato su `/calendar` e `/acquisitions`. Al primo uso inietta una volta il proprio markup modal nel DOM (id `event-modal`), poi lo riusa.

**API pubblica:**
```
openEventModal({ event, prefill, onSaved })
```
- `event` (opz): oggetto evento serializzato dal backend → modalità **edit** (mostra Elimina, PUT su salva).
- `prefill` (opz): `{ start, end, acquisition_id, client_id, project_id }` → modalità **create** (POST).
- `onSaved` (opz): callback invocata dopo save/delete riusciti (es. `_cal.refetchEvents()` o ricarica lista tab).

**Campi form:**
- `title` (text, required)
- `start_at` (`datetime-local`, required)
- `end_at` (`datetime-local`, required)
- `all_day` (checkbox → quando attivo nasconde/disabilita la parte oraria; invia `all_day=1`)
- `location` (text)
- `meeting_url` (url)
- `status` (select: confirmed/tentative/cancelled)
- collegamenti prefill (`acquisition_id`/`client_id`/`project_id`) come hidden, mostrati read-only come etichetta se presenti.

**Pulsanti:** Salva (POST o PUT), Elimina (solo edit; DELETE con conferma), Annulla (chiude).

**Validazione client:** titolo non vuoto; `end_at ≥ start_at` (se non all_day). Errore → `toast(...,'error')`, non chiude.

**Persistenza:** costruisce `FormData`, chiama `POST /calendar/api/events` o `PUT /calendar/api/events/{id}` o `DELETE /calendar/api/events/{id}`. Su successo: `closeModal()`, `toast` ok, `onSaved?.()`.

**datetime-local ↔ backend:** il valore `datetime-local` è `YYYY-MM-DDTHH:MM` (naive locale). `_parse_dt` backend usa `datetime.fromisoformat` → compatibile. In edit, popola i field convertendo l'ISO ricevuto a `slice(0,16)`.

### 2. `app/static/js/calendar_page.js` — modifiche

- `initialView: 'timeGridWeek'`.
- Opzioni leggibilità: `eventTimeFormat {hour:'2-digit',minute:'2-digit',hour12:false}`, `slotMinTime:'07:00:00'`, `slotMaxTime:'22:00:00'`, `nowIndicator:true`, `allDaySlot:true`, `slotDuration:'00:30:00'`, `expandRows:true`.
- `eventClick(info)`: se `info.event.extendedProps.marker` → ignora; altrimenti `openEventModal({ event: _fcEventToObj(info.event), onSaved: () => _cal.refetchEvents() })`.
- `dateClick`/`select`: `openEventModal({ prefill:{start,end}, onSaved: refetch })`.
- `eventResize`: PUT `end_at` (come `eventDrop` esistente).
- Rimuovere `calNewEvent`/`prompt()`. Il bottone toolbar "Nuovo appuntamento" chiama `openEventModal({ prefill:{}, onSaved: refetch })`.
- Helper `_fcEventToObj(fcEvent)`: rimappa un evento FullCalendar → oggetto compatibile con `openEventModal` (id, title, start/end ISO, all_day, e `extendedProps` per location/meeting_url/status/links).

### 3. Tab Appuntamenti in `app/templates/pages/acquisitions.html` — modifiche

- `acqDetLoadCalendarEvents(aid)`: ogni riga renderizzata leggibile:
  `<strong>titolo</strong> · data+fascia oraria · luogo · <span badge stato> · link(http(s))` + pulsanti **✎** (edit) e **🗑** (delete).
  - Formattazione fascia: `start`–`end` con `toLocaleString`/`toLocaleTimeString` (o "tutto il giorno" se all_day).
  - Badge stato: classe per confirmed/tentative/cancelled.
  - Link solo se `/^https?:\/\//i` (anti-XSS, già presente).
  - ✎ → `openEventModal({ event, prefill:{acquisition_id:aid}, onSaved:()=>acqDetLoadCalendarEvents(aid) })`.
  - 🗑 → conferma → DELETE → ricarica lista (può passare per `openEventModal` delete o chiamata diretta; preferito: riusare la logica delete del modal via una funzione esportata, oppure DELETE inline con conferma).
- "Nuovo appuntamento" → `openEventModal({ prefill:{acquisition_id:aid}, onSaved:()=>acqDetLoadCalendarEvents(aid) })` (rimuove `acqNewAppointment` basato su prompt, o lo riscrive per aprire il modal).
- Includere `event_modal.js` (con cache-buster) tra gli script della pagina acquisizioni.

### 4. i18n (`app/static/js/i18n.js`)

Nuove chiavi (5 lingue), namespace `cal.event.*` (alcune già esistono da Task 4: `title/start/end/location/link/save/delete`):
- `cal.event.allday`, `cal.event.status`, `cal.event.status.confirmed`, `cal.event.status.tentative`, `cal.event.status.cancelled`, `cal.event.cancel`, `cal.event.new`, `cal.event.edit`, `cal.event.deleteConfirm`, `cal.event.linkedTo` (etichetta collegamento), `cal.event.saved`, `cal.event.err.title` (titolo obbligatorio), `cal.event.err.range` (fine < inizio).

## Data flow

```
[/calendar]  FullCalendar --click/select--> openEventModal --FormData--> POST/PUT/DELETE /calendar/api/events --> refetchEvents
[/acquisitions tab] lista ✎/🗑/nuovo --> openEventModal --FormData--> POST/PUT/DELETE --> acqDetLoadCalendarEvents(aid)
```

Backend invariato. `event_modal.js` è l'unico punto che parla con l'API di scrittura eventi.

## Error handling

- Fetch non-ok → `toast(mfT('common.error'),'error')`, modal resta aperto (create/edit) o lista invariata (delete).
- Validazione client fallita → toast specifico (`cal.event.err.*`), nessuna chiamata.
- Delete → sempre `confirm()` prima.

## Testing

- **Backend**: già coperto (α.172.240), nessuna modifica.
- **pytest smoke** (`tests/test_calendar_editing.py`):
  - `/calendar` HTML include `event_modal.js`.
  - `/acquisitions` HTML include `event_modal.js` e mantiene tab/container calendar.
  - `i18n.js` contiene le nuove chiavi `cal.event.allday`, `cal.event.status`, `cal.event.new`, `cal.event.edit`.
- **Statico**: `node --check app/static/js/event_modal.js app/static/js/calendar_page.js`; grep guard (funzioni definite/referenziate, helper non ridefiniti).
- **Smoke browser Playwright**: crea evento (con orari) su /calendar in vista settimana, riaprilo → edit → salva → verifica, elimina; nel tab acquisizioni crea/edit/elimina; 0 errori console.

## Self-review

- Placeholder: nessun TBD.
- Consistenza: `event_modal.js` unica scrittura API; calendar_page e tab lo consumano via `openEventModal` — nessuna seconda fonte di verità.
- Scope: singola iterazione, no decomposizione.
- Ambiguità risolte: vista=settimana, modal=condiviso, acquisizioni=solo tab.
