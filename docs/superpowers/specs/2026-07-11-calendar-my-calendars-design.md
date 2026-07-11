# Sotto-fase 1 — I miei calendari (Google calendar list)

**Data:** 2026-07-11
**Ramo:** `feat/mobile-responsive-email` (continua)
**Versione target:** v3.5.0-alpha.172.248
**Programma:** parte 1 di 4 (Calendari → Email client core → Restyling sleek → AI copilot profondo).

---

## Contesto

`/calendar` (α.172.247) mostra gli eventi Google come **overlay tenue** tramite un
singolo checkbox "Mostra Google". `google_calendar.list_google_events` già legge
`calendarList` e ritorna eventi con `calendar`, `calendar_id`, `color`, `read_only`.

**Problema segnalato da Matteo:** "non vedo i miei calendari". Manca una **lista
gestibile** dei calendari (quali esistono, colore, accendi/spegni singolarmente).

## Obiettivo

Sidebar "I miei calendari" con toggle di visibilità per-calendario e colori,
al posto del singolo checkbox globale.

## Non-obiettivi (sotto-fasi successive)

- Creazione/eliminazione/condivisione calendari.
- Persistenza preferenze visibilità lato server (usiamo localStorage).
- Restyling sleek completo (Sotto-fase 3).

---

## Backend

### Nuovo endpoint `GET /calendar/api/google-calendars`

- Dep: `RequireView`. Ritorna `{ "calendars": [ {id, summary, color, access_role, primary} ] }`.
- Implementazione in `google_calendar.py`: `list_calendars(db, user_id) -> list`.
  - GET `calendarList`; per ogni item: `id`, `summary`, `backgroundColor`→`color`,
    `accessRole`→`access_role`, `primary` (bool).
  - **Esclude** il calendario "Claqo" (`row.claqo_calendar_id`) — rappresentato
    localmente dagli eventi Claqo, mostrato separatamente in sidebar come voce fissa.
  - Best-effort: token/rete/403 → `[]` (mai eccezione).
- Router `calendar.py`: endpoint sottile che chiama il servizio, wrap try/except → `{"calendars": []}`.

### Nessuna modifica DB, nessuna migrazione.

---

## Frontend

### `calendar.html`

- Layout a 2 colonne: `.cal-shell { display:grid; grid-template-columns: 220px 1fr; }`.
  - Sinistra: `<aside id="cal-sidebar">` con titolo "I miei calendari" + `<div id="cal-list">`.
  - Destra: toolbar esistente (scope, Sincronizza, Nuovo) + `#calendar-root`.
- Rimuovere il checkbox singolo "Mostra Google" (sostituito dalla lista).
- Responsive ≤768px: sidebar collassa sopra il calendario (grid-template-columns: 1fr).

### `calendar_page.js`

- `calLoadCalendars()`: fetch `/calendar/api/google-calendars` → popola `#cal-list`.
  - Voce fissa in cima: **Claqo** (colore accent) — toggle mostra/nascondi eventi locali.
  - Per ogni calendario Google: `<label>` con checkbox + pallino colore + nome.
  - Stato visibilità letto/scritto in `localStorage['mf_cal_hidden']` = JSON array di
    `calendar_id` NASCOSTI (default: nessuno nascosto → tutti visibili). Chiave `'claqo'` per il locale.
- `_calHidden()` / `_calSetHidden(id, on)`: helper localStorage.
- `calFetchEvents`:
  - Eventi locali (Claqo): se `'claqo'` nascosto → non aggiungere.
  - Overlay Google: **sempre** fetchato (un solo giro), poi filtrato per `calendar_id` non-nascosto.
    Rimuove la dipendenza dal checkbox `cal-show-google` (ora sempre "on", filtrato per calendario).
  - Colore evento = colore del calendario (già presente).
- Toggle di un calendario → `_cal.refetchEvents()`.

### i18n (5 lingue)

- `cal.myCalendars` = "I miei calendari"
- `cal.claqoCalendar` = "Claqo (appuntamenti)"
- `cal.noCalendars` = "Nessun calendario Google. Riconnetti l'account in Impostazioni."

---

## Test

- `test_calendar_list.py`:
  - `list_calendars` mappa correttamente calendarList (id/summary/color/access_role/primary).
  - Esclude il calendario Claqo (`claqo_calendar_id`).
  - Best-effort: nessun token → `[]`; errore request → `[]`.
- Endpoint `GET /calendar/api/google-calendars` → 200 `{calendars:[...]}` (mock servizio).
- Smoke: `calendar_page.js` parse (node --check); nomi funzioni/chiavi i18n verificati.
- Smoke browser reale = Matteo (richiede account Google connesso + People API).

---

## Prereq utente (se lista vuota)

Dipende dal re-consenso α.172.247: riconnettere l'account Google (`/settings → Account`)
+ abilitare Google People API su Google Cloud. Senza, `calendarList` non è accessibile.

## Rischi

- `calendarList` richiede scope `calendar` (ora full, α.247) — OK.
- localStorage per-browser: la visibilità non segue l'utente tra dispositivi. Accettato (YAGNI).
