# Spec — Versione mobile (PWA staff operativo)

**Data**: 2026-05-31
**Versione target**: v3.5.0-alpha.172.158+
**Richiesta**: Matteo — iniziare la versione mobile in parallelo ai test. Target staff
operativo. Companion del desktop, non sostituto.

Riferimento decisione 6/5/2026: [[project_mobile_port]] — PWA scope ridotto, staff first,
no timeline drag.

---

## 1. Obiettivo

App mobile **companion** per lo **staff operativo** (tecnici/freelance): azioni rapide da
telefono — timbratura, "mie assegnazioni di oggi", richieste ferie, notifiche,
accetta/rifiuta assegnazioni. NON sostituisce il desktop; non include editing pesante
(quote/listino/planning timeline/finance).

## 2. Decisioni confermate

| # | Decisione | Scelta |
|---|-----------|--------|
| D1 | Target primario | **Staff operativo** |
| D2 | Approccio UI | **Area mobile dedicata `/m/*`** — template Jinja lean touch-first, riusa gli endpoint JSON esistenti. NO responsive sul desktop, NO SPA. |
| D3 | Profondità PWA | **Installabile** (manifest + service worker, shell cachata). Azioni **online** (no offline-sync). |
| D4 | Entry | `/m` **esplicito** (no auto-redirect per user-agent). La PWA punta a `/m`. |

## 3. Architettura

- **Router** `app/routers/mobile.py`, prefix `/m`, registrato in `main.py`. Route che
  renderizzano template lean (nessuna logica business: i dati arrivano via fetch agli
  endpoint esistenti).
- **Template** `app/templates/mobile/`:
  - `base_mobile.html` — shell minimale (viewport, manifest link, SW registration, bottom
    tab bar, theme dark coerente). NON estende `base.html` desktop (troppo pesante: sidebar,
    copilot, vis-timeline, ecc.).
  - una pagina per schermata (vedi §5).
- **CSS** `app/static/css/mobile.css` — touch-first: target ≥44px, liste verticali,
  bottom tab bar fixed, palette coerente col tema (indaco `#6272f5`). Cache-buster via
  `?v={{ app_version }}` (convenzione esistente).
- **JS** `app/static/js/mobile.js` — vanilla, helper `api()` (riuso pattern global.js o
  versione minimale), fetch sugli endpoint JSON, render liste, gestione stato timbratura.
- **Auth**: stessa sessione/cookie del desktop (JWT in cookie). Le route `/m/*` richiedono
  utente loggato → redirect a login (`/login` esistente o `/m/login` mobile-styled) se non
  autenticato. Nessun nuovo meccanismo auth.

## 4. PWA

- `app/static/manifest.json`: `name="Claqo"`, `short_name="Claqo"`, `start_url="/m"`,
  `display="standalone"`, `background_color`/`theme_color` (dark indaco), `icons`
  (192×192, 512×512 — riusa/deriva dal brand pack esistente in `docs/brand/` o icona app).
- `app/static/sw.js`: service worker. Cache **app shell** statica (`mobile.css`, `mobile.js`,
  manifest, icone, una pagina `/m/offline` di fallback). Strategia: **cache-first per shell
  statica**, **network-first/network-only per i dati** (endpoint JSON). Le azioni
  (POST timbratura/ferie/read) sono **online-only** (se offline → messaggio chiaro, no coda).
- Registrazione SW + `<link rel="manifest">` + meta theme-color in `base_mobile.html`.
- Versioning cache SW legato a `app_version` per invalidare lo shell ai deploy.

## 5. Schermate MVP (staff)

Bottom tab bar su tutte: **Oggi · Assegnazioni · Timbra · Ferie · Notifiche**.

1. **`/m` — Oggi (home)**: saluto utente; **mie assegnazioni di oggi**
   (`GET /planning/api/my-bookings?today_only=true`); **card timbratura** (stato corrente
   in/out + bottone toggle, da `GET /hr/api/punches`); **badge notifiche non lette**
   (`GET /notifications/api/unread-count`). Link rapidi alle altre sezioni.
2. **`/m/timbra` — Timbratura**: bottone IN/OUT grande (stato corrente) →
   `POST /hr/api/punches`; storico timbrature recenti (`GET /hr/api/punches`).
3. **`/m/assegnazioni` — Mie assegnazioni**: lista per giorno
   (`GET /planning/api/my-bookings`), dettaglio booking; **accetta/rifiuta** la propria
   assegnazione (vedi §6 gap endpoint).
4. **`/m/ferie` — Ferie/assenze**: mie richieste
   (`GET /planning-unavailabilities/my-unavailabilities`); **nuova richiesta**
   (`POST /planning-unavailabilities/unavailabilities`).
5. **`/m/notifiche` — Notifiche**: lista (`GET /notifications/api/list`); segna letto
   (`POST /notifications/api/{id}/read`, `mark-all-read`).

## 6. Endpoint — riuso vs gap

**Riuso diretto (esistono, JSON, filtrano per utente loggato):**
- `GET /planning/api/my-bookings` (+ `today_only`) — mie assegnazioni
- `GET /hr/api/punches`, `POST /hr/api/punches` — timbrature
- `GET /planning-unavailabilities/my-unavailabilities`, `POST .../unavailabilities` — ferie
- `GET /notifications/api/list`, `POST /api/{id}/read`, `POST /api/mark-all-read`,
  `GET /api/unread-count`

**Gap possibile:**
- **Accetta/rifiuta assegnazione propria**: verificare in implementazione se esiste un
  endpoint per lo staff per rispondere alla propria assegnazione. Se NON esiste, aggiungere
  `POST /planning/api/my-bookings/{booking_id}/respond` (form `action=accept|reject`,
  scoped all'utente loggato: solo se il booking è assegnato a una sua Resource). Se la
  funzione non è ancora prevista lato business, la schermata mostra le assegnazioni
  read-only in v1 e l'accetta/rifiuta è follow-up.

## 7. Sicurezza

- Stessa auth/RBAC del desktop. Le route `/m/*` richiedono login.
- Lo staff vede **solo i propri dati**: `my-bookings` e `my-unavailabilities` già filtrano
  per l'utente loggato (via Resource collegata). Nessun endpoint cross-user è esposto su
  mobile. L'eventuale `respond` valida che il booking sia dell'utente.
- Nessun dato finance/quote/listino servito su mobile (fuori scope).

## 8. Fuori scope (MVP)

- Planning timeline drag/multiselect, editing quote/listino/clienti, finance editing,
  approvazioni manageriali, portale cliente. (Companion operativo, non gestionale.)
- Offline-sync (timbratura in coda): defer (D3). Studio = wifi; YAGNI ora.
- Push notifications native (richiede SW push + permessi): defer; v1 mostra le notifiche
  in-app via polling/unread-count.

## 9. Testing

- **Smoke route** (`tests/test_mobile.py`): ogni `/m/*` → 200 con utente loggato; redirect
  a login se non autenticato. (Chiamata diretta alle coroutine route con request/cookie
  fittizi o via i pattern di test esistenti.)
- **Manifest**: `manifest.json` è JSON valido con i campi richiesti (start_url, display, icons).
- **Jinja**: i template `mobile/*.html` compilano.
- **JS**: `mobile.js` + `sw.js` passano `node --check`.
- Endpoint riusati: già coperti dai test esistenti; eventuale `respond` → test dedicato.

## 10. Iteratività

L'MVP è piccolo e coeso, ma le schermate sono **indipendenti** sopra lo scaffold comune
(`base_mobile.html` + tab bar + PWA + mobile.js helper). Ordine consigliato:
scaffold + Oggi → Timbra → Notifiche → Assegnazioni → Ferie. Si può fermare/spedire a ogni
schermata (incrementale, parallelo ai test desktop).

## 11. File toccati (stima)

`app/routers/mobile.py` (nuovo), `app/main.py` (include_router), `app/templates/mobile/*.html`
(nuovi: base_mobile + 5 pagine + offline), `app/static/css/mobile.css` (nuovo),
`app/static/js/mobile.js` (nuovo), `app/static/manifest.json` (nuovo), `app/static/sw.js`
(nuovo), icone in `app/static/` (da brand), eventuale `app/routers/planning.py`
(`respond` se gap), `tests/test_mobile.py` (nuovo).
