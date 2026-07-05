# Claqo — Account Linking + Calendario + Documenti — Design

> Design doc del programma "espansione Acquisitions + calendario appuntamenti + collegamento account Google/corporate per calendario e documenti".
> Data: 2026-07-04 · Stato: approvato, pronto per piano di implementazione.

## Contesto

L'utente vuole strutturare meglio ed ampliare la sezione **Acquisitions**, con gli appuntamenti disponibili in un **calendario**, e la possibilità di **collegare l'account Google (o altri provider) per-utente** per abilitare collegamenti diretti a calendario e documenti.

Questa è di fatto la **Acquisizioni Fase 3 (calendar)** già prevista in roadmap, più un'infrastruttura OAuth cross-cutting riusabile.

### Stato attuale del codice (esplorato)

**OAuth — già scaffoldato (α.152), NON cablato in UI:**
- `UserOAuthToken` (`app/models/models.py:2859-2874`): token per-utente, `refresh_token_enc` cifrato Fernet, `scopes`, `account_email`, UNIQUE(user_id, provider).
- `app/services/oauth_providers.py`: `PROVIDERS` (Google: gmail.send + drive.file; Microsoft: Mail.Send + Files.ReadWrite), `authorization_url`, `exchange_code_for_token`, `fetch_userinfo`, `save_token`, `get_token`, `revoke_token`, encrypt/decrypt refresh token.
- `app/routers/oauth.py`: `GET /auth/oauth/status`, `GET /auth/oauth/{provider}/start`, `GET /auth/oauth/{provider}/callback`, `POST /auth/oauth/{provider}/disconnect`.
- Gap: nessuno scope calendario; nessuna UI in `/settings`; nessun refresh automatico; CSRF `_state_store` in-memory (dev-only); nessuna vista calendario.
- `app/services/crypto.py`: `encrypt_secret` / `decrypt_secret` / `generate_key` con `AI_KEY_ENCRYPTION_KEY`.

**Acquisitions:**
- Modelli (`app/models/models.py`): `Acquisition` (4775-4804), `Contact` (4806-4821), `Activity` (4823-4845). Enum `ActivityType` = email|call|meeting|note|task.
- Campi data sparsi: `Activity.occurred_at` (datetime, passato), `Activity.next_action_date` (date), `Acquisition.expected_close_date` (date), `Acquisition.next_action_date` (date). **Nessun concetto di appuntamento con inizio/fine/durata.**
- Router `app/routers/acquisitions.py`: CRUD acquisitions + activities + `/acquisitions/api/agenda` (prossime azioni 30gg).
- Template `app/templates/pages/acquisitions.html`: KPI bar + agenda strip + filtri + kanban/tabella + detail panel (tab Attività / Contatti / Quotes).
- Capability AI: `propose_acquisition`, `propose_activity`, `propose_contact`, `propose_acquisition_stage`.

**Calendario/timeline:** solo `vis-timeline` in planning (`app/templates/pages/planning.html`). Nessun widget calendario riusabile.

## Decisioni

| Tema | Decisione |
|------|-----------|
| Modello calendario | Claqo **owner** degli appuntamenti + **sync bidirezionale** opzionale. Funziona senza account collegato. |
| Entità evento | Nuova entità **`CalendarEvent` generica**, riusabile in tutto Claqo. `Activity` resta log storico. |
| Scope programma | **A + B + C + D**, unica design doc, implementazione a **fasi sequenziali** indipendenti. |
| Provider | **Solo Google** nel primo giro (calendar + drive). Microsoft resta scaffold, cablato dopo. |
| Widget calendario | **FullCalendar** via CDN (vanilla JS, mese/settimana/giorno/agenda). |
| Modello sync | Calendario secondario dedicato **"Claqo"** sull'account per il push + lettura **read-only** del primario per overlay/conflitti + **import selettivo**. |
| Documenti | **Collega riferimenti** (URL + metadata) via Google Picker o incolla-link. Niente storage locale. |

## Architettura & fasi

Programma unico, 4 fasi indipendenti, ognuna con proprio bump versione + commit + spedibile a sé.

| Fase | Cosa | Sblocca |
|------|------|---------|
| **A** Fondamenta OAuth | scope calendario Google, UI `/settings`, refresh token auto, CSRF state firmato | collegamento account riusabile |
| **B** Calendario nativo | `CalendarEvent` + pagina FullCalendar + embed acquisitions + capability AI | appuntamenti interni (senza sync) |
| **C** Sync bidirezionale | servizio `google_calendar`, push/pull/import, background, overlay conflitti | Claqo ↔ Google |
| **D** Documenti | `DocumentLink` + Picker/paste + embed progetto/acquisition | file Drive collegati |

---

## Fase A — Fondamenta OAuth

**Obiettivo:** collegare/scollegare l'account Google per-utente, con scope calendario + documenti, refresh automatico, e CSRF sicuro.

- **Scope Google** ampliati in `oauth_providers.PROVIDERS` (least-privilege, security review 2026-07-04 — NO scope pieno `calendar`):
  - `https://www.googleapis.com/auth/calendar.app.created` (crea/gestisce solo il calendario "Claqo" creato dall'app — stessa postura di `drive.file`; copre push Fase C)
  - `https://www.googleapis.com/auth/calendar.readonly` (lettura del primario per overlay/conflitti Fase C)
  - mantengo `https://www.googleapis.com/auth/drive.file` (documenti creati/aperti dall'app + Picker)
  - mantengo `openid email profile`.
  - Cambio scope ⇒ re-consent utente. Il token porta `scopes`; alla connessione si richiede `access_type=offline` + `prompt=consent` per garantire il refresh token.
- **Refresh automatico:** nuova `get_valid_access_token(db, user, provider) -> str` in `oauth_providers.py`. Se `expires_at` è entro una soglia (es. 120s), rinnova via `refresh_token_enc` (grant `refresh_token`), aggiorna `access_token`/`expires_at`. Ogni chiamata API provider passa da qui.
- **CSRF state stateless:** sostituisco `_state_store` in-memory con **state firmato HMAC** (`SECRET_KEY`): payload `{user_id, provider, exp}` → base64 + firma. Il callback verifica firma + scadenza. Nessuna tabella, regge multi-processo.
- **UI `/settings`:** nuovo tab `🔗 Account`.
  - Card Google: stato (email collegata o "Non collegato"), bottoni **Connetti** (→ `/auth/oauth/google/start`) / **Disconnetti** (→ `POST /auth/oauth/google/disconnect`), scope leggibili, toggle **"Sync calendario automatico"**, ultimo sync + eventuale errore.
  - Card Microsoft: presente ma disabilitata ("Prossimamente").
  - Dati da `GET /auth/oauth/status` (esteso con email/scopes/sync flag).
- **Config/env:** `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_REDIRECT_BASE_URL` in `.env.example` + `config.py`. Redirect URI whitelisted lato Google Cloud Console.
- **Preferenza sync:** aggiungo **entrambe** le colonne a `UserOAuthToken` già in Fase A per non ri-migrare dopo: `auto_sync_calendar` (bool, default False) e `claqo_calendar_id` (str, nullable, usata in Fase C).
- **Sicurezza:** token cifrati (già), scope minimi necessari, niente token nei log, redirect fisso, overlay primario **mai** in scrittura (Fase C).

**Deliverable A:** un utente collega il proprio Google da `/settings`, il token con scope calendar+drive è salvato e rinnovabile.

---

## Fase B — CalendarEvent + calendario nativo

**Obiettivo:** calendario Claqo funzionante sugli appuntamenti, anche senza account collegato.

### Entità `calendar_events` (tabella nuova)

Tenant-scoped, soft-delete. Colonne:

| Campo | Tipo | Note |
|-------|------|------|
| `id` | Integer PK | |
| `tenant_id` | Integer | default 1, indexed |
| `title` | String(255) | required |
| `description` | Text | nullable |
| `start_at` | DateTime (UTC) | required, indexed |
| `end_at` | DateTime (UTC) | required |
| `all_day` | Boolean | default False |
| `location` | String(255) | nullable |
| `meeting_url` | String(500) | nullable |
| `status` | Enum | confirmed \| tentative \| cancelled, default confirmed |
| `owner_user_id` | Integer FK users | di chi è il calendario, indexed |
| `acquisition_id` | Integer FK acquisitions | nullable, indexed |
| `project_id` | Integer FK projects | nullable, indexed |
| `activity_id` | Integer FK activities | nullable, indexed |
| `client_id` | Integer FK clients | nullable, indexed |
| `attendees` | JSON | `[{name,email,response}]`, default [] |
| `source` | Enum | claqo \| google, default claqo |
| `external_calendar_id` | String(255) | nullable (Fase C) |
| `external_event_id` | String(255) | nullable, indexed (Fase C) |
| `sync_state` | Enum | local \| synced \| pending_push \| error, default local |
| `last_synced_at` | DateTime | nullable |
| `sync_error` | Text | nullable |
| `is_active` | Boolean | default True (soft-delete) |
| `created_by` | Integer FK users | nullable |
| `created_at` / `updated_at` | DateTime | now_utc |

Link espliciti nullable (non stringa polimorfica) per coerenza col pattern del codebase (integrità FK + tenant filter + cascade).

### Router `app/routers/calendar.py`

| Method | Path | Perm |
|--------|------|------|
| GET | `/calendar` | `view_calendar` |
| GET | `/calendar/api/events?start&end&owner&scope=mine\|team&linked_type&linked_id` | `view_calendar` |
| POST | `/calendar/api/events` | `manage_calendar` |
| PUT | `/calendar/api/events/{id}` | `manage_calendar` |
| DELETE | `/calendar/api/events/{id}` (soft) | `manage_calendar` |

- `GET events` ritorna `CalendarEvent` nel range + **marcatori derivati** read-only: `Activity.next_action_date`, `Acquisition.expected_close_date` come pin (non-eventi, non editabili, distinti per stile). Valore immediato, zero duplicazione.
- Permessi nuovi `view_calendar` / `manage_calendar` aggiunti al seed RBAC + assegnati ai ruoli di default (admin/manager: manage; staff: view+manage propri; viewer: view).

### Frontend

- FullCalendar via CDN (stesso schema di vis-timeline). Viste mese/settimana/giorno/agenda(list).
- Click su slot vuoto → modal **crea** (prefill start/end). Click su evento → modal **modifica**. Drag/resize → `PUT`.
- Colore per `source` / entità collegata. Filtro **owner** (mie vs team), filtro reparto (via acquisition/project).
- Marcatori derivati mostrati con stile diverso (es. pin tratteggiati), non trascinabili.

### Embed in Acquisitions (ampliamento sezione)

- Detail-panel: nuovo tab **📅 Appuntamenti** → lista `CalendarEvent` con `acquisition_id` = corrente + bottone **Nuovo appuntamento** (prefill `acquisition_id`, `client_id`, owner).
- Agenda-strip esistente ora alimentata da `CalendarEvent` (start_at nei prossimi 30gg) + marcatori `next_action_date`.
- Nessun refactor non correlato: si tocca solo il detail-panel e l'agenda.

### AI

- Nuova capability `propose_calendar_event` (params: `title`, `start_at`, `end_at`, `acquisition_id?`, `project_id?`, `client_id?`, `location?`, `attendees?`) nel registry (`ai_tools.py` + `ai_assistant.py`), pattern "AI propone, utente dispone".

**Deliverable B:** calendario navigabile, creazione/modifica/spostamento appuntamenti, embed in acquisitions, copilot che propone appuntamenti. Nessun sync ancora.

---

## Fase C — Sync bidirezionale Google

**Obiettivo:** Claqo ↔ Google Calendar, pulito e reversibile.

Nuovo servizio `app/services/google_calendar.py` (usa `get_valid_access_token` della Fase A):

- `ensure_claqo_calendar(db, user)` → crea (o ritorna) un calendario secondario **"Claqo"** sull'account Google dell'utente; salva l'id su `UserOAuthToken.claqo_calendar_id`.
- `push_event(db, event)` → create/update/delete dell'evento sul **calendario Claqo**; mappa `external_event_id`/`external_calendar_id`; aggiorna `sync_state`/`last_synced_at`.
- `pull_overlay(db, user, start, end)` → legge il calendario **primario** in **sola lettura** (busy/eventi) per il range visualizzato — dati **live, non salvati** in DB.
- `import_event(db, external, user)` → crea un `CalendarEvent` `source=google` da un evento esterno scelto dall'utente (import **selettivo**, non automatico).

**Trigger sync:**
- Su create/update/delete di `CalendarEvent`, se l'utente ha account collegato **e** `auto_sync_calendar` on → push in **background thread** (pattern già usato per estrazione AI in background; niente blocco della request).
- Bottone **"Sincronizza ora"** manuale (settings o calendario).
- Overlay: gli eventi del primario appaiono in grigio sul calendario; avviso quando si crea un appuntamento che si sovrappone.

**Errori:** `sync_state=error` + `sync_error` mostrati in UI (badge sull'evento + riga in settings). Refresh token integrato; su revoca/scadenza refresh → stato "riconnetti".

**Teardown:** disconnessione account → gli eventi Claqo restano locali (`source=claqo`, `sync_state=local`), il calendario "Claqo" su Google può essere rimosso manualmente; niente residui sul primario (mai scritto).

**Deliverable C:** appuntamenti Claqo compaiono sul Google dell'utente (calendario "Claqo"), impegni personali visibili come overlay, import selettivo di eventi esterni.

---

## Fase D — Documenti collegati

**Obiettivo:** collegare file Drive a progetti/acquisitions/activities senza storage locale.

### Entità `document_links` (tabella nuova)

Tenant-scoped, soft-delete: `id, tenant_id, provider (google), external_file_id, name, mime_type, web_url, icon_url, owner_email`, link espliciti nullable (`project_id, acquisition_id, activity_id, client_id`), `added_by`, `created_at`, `is_active`.

### Router `app/routers/documents.py`

| Method | Path | Perm |
|--------|------|------|
| POST | `/documents/api/link` (da Picker o URL incollato) | `manage_*` dell'entità collegata |
| GET | `/documents/api/list?linked_type&linked_id` | view dell'entità |
| DELETE | `/documents/api/link/{id}` (soft) | manage |

- **Aggancio:** Google Picker API (se `GOOGLE_PICKER_API_KEY` configurato) **oppure** incolla-link → parse dell'id file dall'URL Drive → fetch metadata via Drive API (`drive.file`) usando `get_valid_access_token`. Salvo il riferimento, apro in nuova scheda.
- **Embed:** sezione **📎 Documenti** nel detail di progetto + acquisition (lista + aggiungi + rimuovi).

**Deliverable D:** file Drive collegati e apribili dalle schede progetto/acquisition.

---

## Trasversali (tutte le fasi)

- **Tenant filter** `CURRENT_TENANT` su ogni query; **soft-delete** `is_active`.
- **Migrazioni:** script idempotenti separati (`scripts/migrate_oauth_calendar.py` per A, `scripts/migrate_calendar.py` per B, `scripts/migrate_documents.py` per D) — ALTER/CREATE idempotenti + populate permessi. Voce dedicata in `strumenti.bat`/`strumenti.sh`. Colonne/tabelle nuove registrate in `_auto_migrate_columns()` (`main.py`) per non crashare al boot se l'utente non migra.
- **i18n:** ogni stringa UI nelle 5 lingue (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n`, stesso commit. Niente debito i18n.
- **Cache-buster:** `?v={app_version}` sui nuovi static JS.
- **Test:** TDD per feature (subagent-driven come sessioni precedenti), pytest; smoke E2E browser dove c'è JS nuovo (backend smoke non cattura ReferenceError JS).
- **Versioning/commit:** bump `main.py` + `CHANGELOG.md` + `STATO.md` a fine di ogni fase, commit nello stesso giro (convenzione progetto).
- **Dipendenze:** nessuna nuova libreria Python obbligatoria (OAuth via `urllib`, chiamate Google Calendar/Drive via REST + token). FullCalendar e Google Picker via CDN.

## Rischi & note

- **Scope change Google** richiede re-consent: gli utenti già collegati (nessuno oggi in UI) dovranno riconnettersi. Comunicare in UI.
- **CSRF state firmato** dipende da `SECRET_KEY` stabile; già presente.
- **Google Cloud project:** serve un OAuth client (Web) con redirect URI di dev + prod, e Calendar/Drive API abilitate. Prerequisito operativo per Matteo (fuori codice).
- **Rate limit / quote Google:** overlay `pull_overlay` va limitato al range visibile + cache breve per evitare troppe chiamate.
- **YAGNI:** niente Microsoft, niente CalDAV/Apple, niente reminder/notifiche push, niente file-browser completo in questo giro.

## Ordine di implementazione

A → B → C → D. A e B danno già valore visibile (collegamento account + calendario interno). C e D si innestano senza toccare le fondamenta.
