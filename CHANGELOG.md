# MediaFlow — Changelog

## v3.4.31 — Scheda tecnica progetto + link pubblico (1 maggio 2026)

Cantiere "scheda tecnica" (G nel backlog). Workflow sheet di un progetto: catena di lavorazione (camere, audio, look, storage, dailies, crew, process). Schema flessibile JSON per varianti tra case di post diverse.

> **Distinzione netta** dal modello esistente `DeliveryTemplate`: il `ProjectTechSheet` descrive la *catena di produzione* (3 PDF di esempio in `docs/workflow_esempio/`: ISIDE, Gomorra, FUME). Il `DeliveryTemplate` resta per le *specs di consegna* (Netflix, A24, Vision…). Il primo può linkare al secondo via `delivery_template_id` opzionale.

### Modello `ProjectTechSheet` (1:1 con Project)

```
id, tenant_id, project_id (UNIQUE), delivery_template_id (FK opt)
version (str), status (draft|preview|approved)
approved_by_user_id, approved_at
public_token (UUID-safe nullable), is_public_enabled, expires_at, published_at
data (JSON) ─ sezioni: general, cameras[], audio, looks[], storage, dailies,
             folder_struct, contacts[], process, notes
created_at, updated_at
```

Tabella creata automaticamente da `Base.metadata.create_all()` al boot (no migration script).

### Endpoint

- `GET /projects/api/{pid}/tech-sheet` — auto-crea draft se manca (auth: `view_projects` o `edit_projects`)
- `PUT /projects/api/{pid}/tech-sheet` — accetta JSON body `{version, status, delivery_template_id, data}` (auth: `edit_projects`)
- `POST /projects/api/{pid}/tech-sheet/publish` — Form `expires_days` (default 90, 0=senza scadenza), `rotate_token` (bool)
- `DELETE /projects/api/{pid}/tech-sheet/public` — disattiva link
- `GET /public/tech-sheet/{token}` — vista readonly **no auth**, ritorna 410 Gone se scaduto, 404 se token revocato

`PUBLIC_PATHS` in `main.py` esteso con `/public/` per saltare auth guard.

### UI editor — tab "🛠 Scheda tecnica" in `/projects/{id}`

- Sub-tabs: Generale · Camere · Audio · Look · Storage · Dailies · Crew · Process · Note.
- **Camere come array**: aggiungi/rimuovi camere (A/B/C/D…) con specs indipendenti (FUME-style: A≠B). Ottiche come lista per camera.
- **Look multipli**: array di LUT/LMT con scope (main/flashback/etc), tipo (ASC-CDL/Powergrade), 3DLUT size, range transform.
- **Crew**: lista contatti free-form (ruolo + nome + email + telefono). Resource link rinviato a iter successiva (per ora `name_text`).
- Lista campi (burnins, report recipients, notify emails) come textarea "uno per riga" → array.
- Toolbar: version + status + delivery_template dropdown + bottone "🔗 Link pubblico". Indicatore dirty/saved.
- Salvataggio esplicito tramite "💾 Salva modifiche" (non auto-save).

### Vista pubblica `/public/tech-sheet/{token}`

- Template `pages/tech_sheet_public.html` standalone (no sidebar, no topbar).
- Layout pulito: header con titolo/codice/regista + sezioni espanse con tutti i campi compilati.
- Pagina errore `tech_sheet_public_error.html` per token scaduto/revocato.
- Footer con data ultima modifica + scadenza link.

### Pubblicazione

- Modal con dropdown scadenza (30/60/90/180/365 giorni o senza scadenza).
- Bottone "Rigenera token" per invalidare il link precedente (security best practice).
- Display URL completa con copy-to-clipboard.
- Bottone "Disattiva link" dal modal stesso se già pubblicato.

### Estensione `api()` in `global.js`

`api(method, url, body, options)` ora accetta opzioni: `{json: true}` invia il body come JSON (`Content-Type: application/json`). Compatibile con tutte le chiamate esistenti FormData/urlencoded. Cache-buster `?v=3.4.31`.

### Cosa è esplicitamente fuori da questa versione

- Import auto-popolazione campi da capitolato (Netflix Specs / A24 / ecc.) via AI: cantiere a sé per v3.4.32+.
- Crew come FK Resource (oggi solo `name_text`): rinviato a quando serve query incrociate.
- Storage policy come oggetto separato riusabile: oggi inline, da estrarre se ricorrenza concreta.
- Datarate auto-calcolato da camera+formato+fps: oggi manuale.

File toccati: `app/models/models.py`, `app/models/__init__.py`, `app/routers/tech_sheets.py` (nuovo), `app/main.py`, `app/static/js/global.js`, `app/templates/pages/project_detail.html`, `app/templates/pages/tech_sheet_public.html` (nuovo), `app/templates/pages/tech_sheet_public_error.html` (nuovo), `app/templates/base.html`.

## v3.4.30 — Vista calendario complessiva in /hr (1 maggio 2026)

In `/hr` toggle "📋 Tabella timbrature | 📅 Calendario complessivo". Vista calendario mensile con sommario per categoria, ferie/malattia/permessi inclusi.

### Backend

- Endpoint **`GET /hr/api/calendar?from_date&to_date&resource_id`**:
  - Per ogni giorno restituisce `{date, regular_h, overtime_h, night_h, vacation_h, sick_h, other_h, total_h, resource_count, unav_kinds}`.
  - **Single-resource**: usa `compute_overtime` con la policy della risorsa per il breakdown preciso (regolari/overtime/notturne).
  - **All-resources**: somma cross-tenant le timbrature shift+overtime e raggruppa per giorno (no split per policy diverse).
  - **Ferie/malattia/permessi** da `ResourceUnavailability.status=approved` → ore = `daily_hours_threshold` × giorni nel range, attribuiti per `kind`.
  - Rispetta `_enforce_scope`: staff vede solo le proprie ore, manager vedono tutto.
  - Restituisce anche `totals` aggregati di periodo per i KPI cards.

### UI

- Toggle `Tabella | Calendario` sopra i filtri (preferenza salvata in `localStorage` → `mf_hr_view`).
- Vista calendario:
  - Toolbar con navigazione mese (prev/next/oggi) + label "Maggio 2026".
  - 7 KPI compatti: Regolari · Straordinari · Notturne · Ferie · Malattia · Permessi · Totale.
  - Griglia 7×6 (Lun-Dom × 6 settimane) con celle giorno mostranti barre per categoria > 0.
  - Evidenziazioni: oggi (bordo indaco), weekend (sfondo tenue), giorni con ferie (sfondo viola), malattia (sfondo rosso), giorni di altri mesi opacizzati.
  - **Click su giorno** → switch a vista Tabella con filtro `from=to=quel giorno` per dettaglio.
- Cambio del filtro Risorsa nei filtri principali aggiorna anche il calendario se aperto.

File toccati: `app/routers/hr.py` (nuovo endpoint), `app/templates/pages/hr.html` (CSS + UI + JS).

## v3.4.29 — Listino laterale + drag&drop in editor quote (1 maggio 2026)

In `/quotes` editor: bottone "📋 Listino" in topbar apre/chiude un pannello laterale destro fisso accanto al riepilogo economico. Le voci di listino sono draggable e si possono trascinare direttamente nella tabella "Voci preventivo" per aggiungerle alla quote.

- **Toggle pannello** persistito in `localStorage` (`mf_side_pricelist_open`): se l'avevi attivato, riapre automaticamente alla prossima quote.
- **Layout grid**: 2 colonne default (editor + riepilogo) → 3 colonne con listino aperto. Responsive: collassa in stack su <1024px.
- **Ricerca**: stesso match di `alMatchesText` (nome, descrizione, categoria, reparto, keywords). Limite render 80 voci per fluidità.
- **Drag&drop**: HTML5 native API con MIME custom `application/x-mf-priceitem`. Drop target = tutta la card "Voci preventivo" (`#lines-card`), evidenziata con bordo indaco durante hover.
- **Drop = POST** `/quotes/api/{id}/lines` con `price_item_id` + `quantity=1`, prezzo/unità ereditati dal listino, descrizione = `name`. Reload quote per vedere subtotali/sconti aggiornati.
- Modal "+ Aggiungi voce" mantenuto come alternativa (utile per voce libera o input rapido tastiera-only).

File toccati: `app/templates/pages/quotes.html`. Nessun cambio backend (riusa endpoint esistenti).

## v3.4.28 — Fix sidebar + engine notifica job_deadline_approaching (1 maggio 2026)

Due cantieri in una versione.

### A — Fix riordino sidebar (auto-discovery + per-sezione)

Sintomo: dopo aver toccato il drag&drop in `/settings#sidebar`, la sidebar nelle altre pagine veniva "compromessa" — voci impilate senza separatori, con voci come `hr`, `assignments`, `admin_users`, `admin_roles` che apparivano in fondo o sparivano dall'elenco di riordino.

Causa doppia:
1. `NAV_ITEMS_DEF` in `settings.html` era una lista hardcoded di 12 voci, mentre `base.html` ne ha 14 (più condizionali per ruolo). Le voci mancanti non comparivano nel pannello di riordino e venivano relegate in coda dall'`applySidebarOrder`.
2. `applySidebarOrder()` faceva flatten di tutte le sezioni in un unico container `.nav-section nav-section-custom`, perdendo le label "Anagrafica", "Operativo", … e l'identità visiva dei raggruppamenti.

Fix generico (no patchwork):
- **Auto-discovery**: il pannello di `/settings#sidebar` ora legge la sidebar reale dal DOM (`.sidebar-nav .nav-item[data-nav-id]` raggruppati per `.nav-section`). Niente più liste duplicate da mantenere — quando si aggiunge una voce in `base.html` appare automaticamente.
- **Riordino per-sezione**: drag&drop opera dentro ciascun gruppo (Principale, Anagrafica, Operativo, Preventivi, Finanza, Media, Configurazione, Amministrazione). Le label di sezione restano intatte.
- **Format salvato**: object `{sectionName: [navId, …]}` invece di array piatto. Il vecchio formato viene ignorato silenziosamente (default torna ad applicarsi).
- Reset disponibile via "Ripristina ordine default".

File toccati: `app/templates/pages/settings.html`, `app/static/js/global.js`. Cache-buster `?v=3.4.28` su `base.html`.

### B — Engine notifica `job_deadline_approaching`

Cantiere riusabile dal pattern v3.4.27 (sistema notifiche). Emette `kind=job_deadline_approaching` quando un Job ha `end_date` imminente.

- **Servizio** `app/services/job_deadline_check.py` — `check_job_deadlines(db)`:
  - Soglie: 1 giorno (`action_required`), 3 giorni (`action_required`), 7 giorni (`info`).
  - Esclude job in stati `completed`, `cancelled`, `invoiced`.
  - **Idempotente**: prima di emettere verifica `Notification.payload->>'job_id'+'threshold_days'` nelle ultime 14 giorni; se già emesso skippa.
  - Notifica via `notify_permission("assign_resources")` → producer/manager/admin/operator (chi gestisce davvero pianificazione job).
  - Payload contiene `job_id`, `job_code`, `end_date`, `days_left`, `threshold_days` per dedup e link.
- **Lifespan startup** in `main.py`: chiama `check_job_deadlines()` al boot. Riavvio server = check immediato, zero-config.
- **Endpoint trigger** `POST /admin/api/check-deadlines` (richiede `manage_settings_global`) per eseguire on-demand.
- **Job di test**: `scripts/seed_test_deadline.py` (idempotente) crea/aggiorna `JOB-TEST-DEADLINE` con `end_date = today + 2`. Voce `[T]` aggiunta a `strumenti.bat`/`strumenti.sh`.

Estendibilità: futuri eventi periodici (cron via /schedule) chiamano `check_job_deadlines()` o servizi simili. Gli stessi pattern di soglie + dedup-by-payload sono riusabili per `quote_status_changed`, `booking_conflict`, ecc.

## v3.4.27 — Sistema notifiche generico + UI approvazione ferie (30 aprile 2026 notte tarda)

Cantiere generico riusabile per qualsiasi futura notifica (workflow ferie, conflitti booking, deadline, alert sistema, ecc.). Pattern AI propone / utente dispone esteso a "sistema notifica / utente apre".

### Modello

- `Notification(id, tenant_id, user_id, actor_user_id, kind, severity, title, body, link, payload JSON, is_read, is_archived, created_at, read_at)`
- Pattern una-row-per-destinatario (multi-recipient = N rows). Più semplice per `unread_count` e `mark_read` per-utente.
- Enum `NotificationKind` con 7 valori iniziali (3 per workflow ferie + 4 riservati per cantieri futuri: booking_conflict, quote_status_changed, job_deadline_approaching, custom).
- Enum `NotificationSeverity`: info / action_required / alert.
- Indici su `(user_id, is_read, created_at desc)` per query veloci sul polling.

### Servizio centrale (`app/services/notifications.py`)

Single point per emit:
- `notify(db, user_ids=[...], kind, title, severity, body, link, payload, actor)` — base
- `notify_permission(db, permission="approve_unavailability", ...)` — broadcast a chi ha quel permesso
- `notify_role(db, role_codes=[...], ...)` — broadcast a ruoli
- `mark_read(db, user, ids)` / `mark_all_read(db, user)`
- `unread_count(db, user) → {total, action_required}`
- `list_for_user(db, user, only_unread, include_archived, limit, offset)`
- `archive(db, user, id)` (soft)
- `cleanup_old(db, days=90)` — soft-archive notifiche lette > 90gg

### Endpoint REST (`/notifications/api/*`)

- `GET /unread-count` — lightweight per polling 30s (ritorna `{total, action_required}`)
- `GET /list?only_unread=&include_archived=&limit=&offset=`
- `POST /{id}/read`
- `POST /mark-all-read`
- `DELETE /{id}` (soft archive)

### Hook iniziali (workflow ferie/malattia)

| Evento | Destinatari | Severity |
|---|---|---|
| `create_unavailability(status=pending)` | tutti con `approve_unavailability` (escluso il richiedente) | action_required |
| `approve_unavailability` | richiedente | info |
| `reject_unavailability` | richiedente (con `rejection_reason` nel body) | action_required |

### UI

- **Topbar campanella 🔔** in `base.html` (sempre visibile per utenti loggati): badge counter rosso (giallo se ci sono `action_required`).
- **Drawer notifiche** laterale destra (`components/notifications.html`): lista con icona-per-kind, titolo, body, tempo relativo (Ora / N min fa / Nh fa / data). Click su notifica = mark_read + redirect al `link`.
- **Polling 30s** automatico su `/unread-count` (basso costo).
- **Bottone "Tutte lette"** in header drawer.
- **Card "🔔 Richieste in attesa"** in `/hr/` per chi ha `approve_unavailability`: lista pending con bottoni Approva / Rifiuta (con motivo opzionale via prompt). Auto-refresh post-azione + ping `notifFetchUnread()`.

### Conseguenze e interazioni

- **Multi-tenant hard (Fase 7)**: `tenant_id` già pronto.
- **Portale cliente futuro**: stesso modello, basta filtrare per `client_id` (richiederà piccola estensione).
- **Cantieri futuri**: emit di `booking_conflict` quando si crea un booking sovrapposto, `job_deadline_approaching` come cron (cantiere /schedule), `quote_status_changed` quando il client accetta/rifiuta. Tutti già supportati lato modello.
- **Audit**: ogni notification è una traccia di chi-quando-cosa, utile per workflow di approvazione.

### Migrazione

Nessuno script: la tabella `notifications` viene creata automaticamente da `Base.metadata.create_all()` al boot tramite `create_tables()`. Idempotente.

## v3.4.26 — Spostamento richiesta ferie da planning a /hr ("Le mie ore") (30 aprile 2026 notte)

In v3.4.24 avevo messo la card richiesta ferie + riepilogo ore nel tab "✓ Le mie" del planning. Matteo: la voce sidebar "Le mie ore" è la pagina `/hr/`, non quella → spostato lì.

- `/hr/` ora mostra (solo per utenti con Resource collegata):
  - **Riepilogo ore** del periodo filtrato (regolari · straordinari · notturne · ferie · malattia · totale)
  - **Form richiesta ferie/malattia/permesso** + lista delle proprie con stato pending/approved/rejected
- `/planning/` tab "✓ Le mie" torna a contenere SOLO la lista attività programmate, con un piccolo banner che linka a `/hr/`
- Modal timbratura: helper text aggiornato ("→ sezione qui sotto" invece di "→ planning").

## v3.4.25.1 — Hotfix auto-bootstrap users.extra_permissions (30 aprile 2026 notte)

In v3.4.25 ho aggiunto la colonna `users.extra_permissions` ma se l'utente fa pull e riavvia il server senza lanciare la migrazione `[K]`, il login crasha con `OperationalError: no such column: users.extra_permissions`.

- Aggiunto `_auto_migrate_columns()` nel lifespan di `app/main.py`: al boot fa `ALTER TABLE users ADD COLUMN extra_permissions TEXT NULL` se la colonna manca. Idempotente.
- Lo script `scripts/migrate_user_extra_permissions.py` resta utile (esplicito + visibile nei log), ma non è più strettamente obbligatorio per single-user dev DB.

## v3.4.25 — Permessi extra per-utente (30 aprile 2026 notte)

Permessi del singolo utente ora = permessi del ruolo + extra individuali (additivi).

### Modello

- Nuova colonna `users.extra_permissions: JSON NULL` (lista di chiavi `PERMISSIONS`).
- `_user_permissions(user)` in `rbac.py` ora unisce: ruolo + `extra_permissions`.
- Solo additivi: non è possibile sottrarre permessi del ruolo dal singolo utente. Per sottrazioni serve un ruolo custom dedicato.

### API

- Nuovo `PUT /admin/api/users/{id}/permissions` con form `extra_permissions=csv`.
- Validazione: solo chiavi presenti in `ALL_PERMISSION_KEYS`.
- Pulizia automatica: chiavi già coperte dal ruolo vengono scartate per evitare ridondanza.

### UI modal `/admin/users` (edit mode)

- Sezione "Permessi extra" sotto l'anteprima del ruolo.
- Matrix per categoria: i permessi del ruolo appaiono già checked + disabled (etichetta "(da ruolo)" + grigio), gli altri sono toggle attivabili.
- Counter "N attivi" live.
- Salvataggio integrato nel flusso `Salva utente`.

### Migrazione

- `scripts/migrate_user_extra_permissions.py` — opzione `[K]` su `strumenti.bat/sh`. Idempotente.

## v3.4.24.1 — Hotfix cache-buster global.js (30 aprile 2026 notte)

In v3.4.24 ho aggiunto `escapeHtml` a `app/static/js/global.js` ma ho dimenticato di bumpare il querystring `?v=` in `base.html`. Il browser continuava a servire la versione cached (`?v=3.2.1`) → bug `escapeHtml is not defined` persisteva su `/admin/users`, `/admin/roles`, `/hr`, ecc.

- `base.html`: `global.js?v=3.2.1` → `?v=3.4.24.1`.
- **Regola**: ogni volta che modifico `static/js/global.js` o `static/css/main.css`, devo bumpare il cache-buster nel template che li include.

## v3.4.24 — UX feedback Matteo: bug escapeHtml + ferie/malattia in Le mie ore + cleanup overtime (30 aprile 2026)

Bump dedicato ai 4 punti emersi nei test sul Mac di v3.4.23.

### Bug fix critico — `escapeHtml` non definito globalmente

`/admin/users` e `/admin/roles` crashavano al caricamento con `ReferenceError: escapeHtml is not defined`. La funzione era ridefinita localmente in 5 template ma non in `global.js`, e i due template admin nuovi non avevano la copia locale.

- Aggiunto `escapeHtml(s)` in `app/static/js/global.js` (helper globale).
- Rimosse le 4 definizioni locali ridondanti (resources, hr, planning, job_detail).
- **Conseguenza**: l'auto-User da Resource funzionava già correttamente (l'utente *veniva* creato), ma la pagina `/admin/users` crashava su `loadUsers()` e l'utente sembrava sparito. Stesso bug anche su `/admin/roles`.

### Modal timbratura — rimossa scelta manuale "Straordinario"

Lo straordinario è un calcolo deterministico (no AI) basato su `WorkingHoursPolicy` + `compute_overtime()`. La voce `overtime` nel dropdown del modal timbratura era ridondante e fuorviante.

- `hr.html` modal punch: solo **Turno** e **Pausa** come opzioni manuali.
- Aggiunto helper text esplicito: "Lo straordinario viene calcolato automaticamente in base alla policy oraria".
- Edit di record storici con `kind=overtime`: vengono aperti come `shift` (mini-migrazione opportunistica al primo salvataggio).

### Ferie/malattia in "Le mie ore" + conteggio rendicontazione

La vista `/planning/` tab "✓ Le mie" ora include 3 sezioni:

1. **Riepilogo ore** del mese corrente (o periodo filtrato): regolari · straordinari · notturne · ferie · malattia · **totale**. Card a 6 KPI con colori distinti.
2. **Le mie ferie e malattie**: form richiesta inline (kind, da/al, motivo) + lista delle proprie richieste con stato (⏳ in attesa / ✅ approvata / ❌ rifiutata) + bottone annulla per richieste pending.
3. **Attività programmate** (booking + timbrature): comportamento precedente, invariato.

Endpoint nuovi/estesi:
- `GET /planning/api/my-unavailabilities` — lista delle proprie richieste con tutti gli status (vs `/api/unavailabilities` che ritorna solo approvate per la timeline).
- `GET /hr/api/overtime` esteso con campi `unavailability` (vacation_days/hours, sick_days/hours, other_days/hours) e `grand_total_hours` (lavorate + ferie + malattia + altro). Conversione giorni→ore con `daily_hours_threshold` della policy.

### Anteprima permessi nel modal utente

Sotto la dropdown Ruolo in `/admin/users`, badge dei permessi inclusi nel ruolo selezionato, raggruppati per categoria. Aggiornato live al cambio di selezione e mostrato in apertura modal (sia create che edit). Link "Modifica permessi →" punta a `/admin/roles`.

---

## v3.4.23 — Permessi configurabili + pannello admin utenti/ruoli + auto-User da Resource (30 aprile 2026)

Sistema RBAC v2: 6 preset built-in + ruoli custom configurabili dall'admin.

### Modello

- Nuovo modello `Role` (tabella `roles`):
  - `code`, `name`, `description`
  - `permissions: JSON` lista di stringhe (chiavi granulari)
  - `is_system: bool` (preset built-in non eliminabili)
  - `is_active`
- `User.role_id` FK opzionale a `roles` (legacy enum `User.role` mantenuto per back-compat)
- 6 **preset built-in** creati automaticamente al boot via `ensure_built_in_roles()`:
  - **admin**: tutti i 23 permessi (matrice non modificabile)
  - **manager**: tutto tranne `manage_users`/`manage_roles`/`manage_settings_global`
  - **producer**: full progetto + finanza view, no editing listino, no fatture
  - **accounting**: solo view finanziaria + fatturazione
  - **operator**: scope auto su Resource (planning/punches own), info tecniche progetti
  - **viewer**: sola lettura

### Permessi

23 chiavi granulari in 6 categorie (Anagrafica, Pianificazione, HR/Timbrature, Finanza, Risorse, Configurazione). Aggiungerne uno in `app/services/rbac.py:PERMISSIONS` lo rende automaticamente disponibile nella UI matrix.

### Pannello admin

- **`/admin/users`**: lista utenti, edit ruolo, attiva/disattiva, reset password con credenziali one-shot, soft-delete. Solo `manage_users`.
- **`/admin/roles`**: split-pane lista ruoli + editor permessi a checkbox per categoria. CRUD ruoli custom (clone da preset). Built-in non eliminabili. Admin role permessi non modificabili. Solo `manage_roles`.
- Voce sidebar "Amministrazione" con icone 👤 Utenti / 🔐 Ruoli e permessi.

### Auto-User da Resource personale

- Modal `/resources` person_internal/freelance: toggle "Crea utenza con accesso al sistema"
- Quando attivo: email obbligatoria, password temp generata (12 char alfanumerici readable), ruolo iniziale scelto da dropdown (default operator), User collegato via `Resource.user_id`
- Credenziali mostrate UNA SOLA VOLTA dopo creazione

### rbac.py riscritto

- `has_permission(user, "key") -> bool` legge da `User.role_obj.permissions` (JSON), fallback a preset enum legacy
- Tutti i `can_*` legacy (can_view_finance, can_edit_settings, …) ora chiamano `has_permission`
- Nuovo `requires_permission(*perms)` dependency per protezione fine
- Eager-load `User.role_obj` in `_resolve_user_from_token` (auth_guard) per evitare DetachedInstanceError nei template

### Bug fix

- **`/hr/` 500**: conflitto context Jinja `is_elevated` (chiave bool) shadowsa il global function. Rinominato a `user_is_elevated`
- **Drag inerziale timeline**: `transition: transform .12s` su `.vis-item` faceva scivolare gli item durante drag. Rimosso `transform` dalla transition (resta solo box-shadow + filter per hover)
- **"Nuovo progetto"** hidden a staff/operator (sia bottone UI che endpoint POST `/projects/api`)

### Migrazione

`scripts/migrate_roles_v2.py` (opzione `[J]` su `strumenti.bat/sh`):
- CREATE TABLE `roles` via Base.metadata
- ALTER TABLE users ADD COLUMN role_id
- Bootstrap 6 preset
- Mappa utenti esistenti dall'enum legacy (`admin`→admin, `staff`→operator, ecc.)

## v3.4.22 — RBAC + workflow ferie + timbratura semplificata + UX (30 aprile 2026)

Sessione lunga: 6 cantieri E/D/C/B/A/F in una passata.

### E — RBAC ruoli e permessi

- Nuovo ruolo **`producer`** (oltre admin/manager/staff/viewer)
- `app/services/rbac.py`: helpers `is_admin/manager/producer/staff/elevated`, `can_view_finance`, `can_edit_settings`, `can_assign_resources`, `can_approve_unavailability`, dependency `current_user(request)`, `requires_role(*roles)`, `scope_resource_id(db, user)` (link User↔Resource via `Resource.user_id`)
- Helpers esposti come globals Jinja per condizionali UI (`{% if can_view_finance(user) %}`)
- **Auth guard** middleware esteso con blacklist path/role:
  - Staff/viewer: niente `/quotes`, `/cost-report`, `/finance`, `/pricelist`, `/clients`, `/assignments`, `/resources`
  - Solo admin: `/departments`, `/settings/api/working-hours`, `/settings/api/ai`
  - 403 con pagina HTML pulita (no JSON crudo)
- **Sidebar conditional**: nasconde Quotazioni/Cost Report/Fatturazione/Listino/Reparti/Impostazioni a non-elevated; mostra "Le mie ore" invece di "Ore lavoro" per staff
- **HR scope auto** (`/hr/*`): staff vede e modifica solo le proprie timbrature. Helper `_enforce_scope(request, db, requested_resource_id)` usato in tutti gli endpoint API
- **Planning scope** (`/planning/api/bookings`, `/planning/api/booking-assignments`): staff può creare/modificare/cancellare booking solo per la propria risorsa
- **Project detail**: tab Quotazioni nascosto a staff, colonna Budget rimossa nei job, bottone "+ Nuova quotazione" hidden
- Robustezza JS: `getElementById` null-safe per evitare errori sulle sezioni nascoste

### D — Workflow approvazione ferie/malattia/permessi

- `ResourceUnavailability` esteso con: `status` (pending/approved/rejected), `requested_by_user_id`, `approved_by_user_id`, `approved_at`, `rejection_reason`, `created_at`
- Nuovo enum `UnavailabilityStatus`
- **POST `/api/unavailabilities`**: staff → status=pending (richiesta), elevated → status=approved (azione diretta)
- **GET `/api/unavailabilities/pending`**: lista richieste in attesa (solo elevated)
- **POST `/api/unavailabilities/{id}/approve`** + **`/reject`** (elevated only)
- **DELETE `/api/unavailabilities/{id}`**: staff può cancellare solo le proprie richieste pending
- Solo `status=approved` blocca planning (smart split, suggest-resources, timeline overlay)
- Migrazione `[I]` `migrate_unavailability_approval.py` (idempotente, backfill record esistenti come 'approved' per back-compat)

### C — Timbrature semplificate + visibility timeline

- Modal `/hr` Nuova timbratura:
  - Job/lavorazione **rimossi** per staff (legame inferito dai booking pianificati)
  - Job opzionale solo per elevated (manager/producer/admin) per ricostruzioni manuali
  - Per staff: solo `kind` shift/overtime/break — ferie/malattia vanno via richiesta approvazione
  - Box durata live con preview overtime (`>8h` → highlight arancione)
- **Overlay timbrature in `/planning` Resource Timeline**:
  - Background items `tl-bg-punch` con bordo verde (shift) / arancio (overtime) / giallo (break) / rosso (sick) / lavanda (leave) / grigio (idle)
  - Tooltip con data, durata, kind label
  - Solo timbrature chiuse (con `end_datetime`) visualizzate
  - Nessun drag/resize sugli overlay (skip in `onMoving`)

### B — Bug fix booking modal

- **Popup ore (tooltip durata) ripristinato** durante drag/resize di un item: titolo dinamico in onMoving con `start → end` + durata formattata (h o gg+h)
- **"+ Aggiungi risorsa"** ora copia data/orari della prima riga (nuovo `tlbAddAssignmentRowFromFirst()`) — la risorsa va comunque scelta dall'utente

### A — Login centrato

- Fix `.login-page`: `body` è `display:flex` (per app-shell), prima la card finiva a sinistra
- Aggiunto `width:100%; flex:1` per espandere il container al viewport
- Background con radial gradient indaco subtle (estetica)

### F — Look refined timeline risorse

- `/planning` Resource Timeline polish CSS:
  - Container con shadow elevata + inset highlight + radius
  - Time axis: maiuscolo letter-spacing, gradient header, weekend tint indaco
  - Labels: zebra simmetrica, transition .12s, hover indaco
  - Reparti header: gradient orizzontale + bordo sx 3px indaco + uppercase 700
  - Items: shape morbida con shadow + inset highlight, hover lift e brightness +8%, selected con doppio glow indaco
  - Drag handles: gradient rampa che si rivela in hover
  - Punch overlay: opacity 0.85 → 1 in hover, no border/shadow per non disturbare booking sopra

## v3.4.21.1 — Auth guard + UX login (30 aprile 2026)

Pagina login esisteva già ma non proteggeva niente: si entrava in `/dashboard` anche
senza cookie. Patch UX per testare il flusso punch in/out come Luca Bianchi.

### Auth guard middleware

- Nuovo middleware `auth_guard` in `app/main.py`
- Cookie `access_token` mancante o JWT invalido su path protetto → redirect 303 a `/auth/login?next=<path>`
- Whitelist: `/auth/*`, `/static/*`, `/health`, `/docs`, `/openapi.json`, `/favicon.ico`, `/redoc`
- API (path con `/api/`) ricevono 401 JSON invece di redirect
- `request.state.current_user` popolato a ogni request con l'oggetto User (hit DB minimo)

### UX login

- POST `/auth/login` con credenziali sbagliate ora **rerender** il template con `{{ error }}` (era 401 JSON crudo)
- Email pre-compilata se sbagli password (UX)
- Hidden input `next` nel form per redirect smart post-login (lettura via `request.form()` per evitare collision col builtin Python `next`)
- Card "Account demo" in fondo al login con credenziali pre-popolate per i 2 utenti seed (`admin@mediaflow.it` / `editor@mediaflow.it`)

### Topbar utente loggato

- Badge `topbar-user` con nome + ruolo + bottone logout veloce
- Visibile su tutte le pagine via `base.html`
- CSS dedicato in `main.css`: surface elevata, role uppercase 10px, logout hover rosa

## v3.4.21 — Soglie e moltiplicatori straordinari (30 aprile 2026)

Fondamenta del cost report doppio: la `WorkingHoursPolicy` impara a distinguere
ore regolari da overtime e applicare maggiorazioni economiche. Senza questo
livello le ore TimePunch finiscono nel cost report tutte allo stesso peso e i
numeri sulle risorse interne sono sballati.

### Modello

`WorkingHoursPolicy` esteso con 8 campi nuovi:
- `daily_hours_threshold` — default 8.0 (oltre = overtime giornaliero)
- `weekly_hours_threshold` — default 40.0 (oltre = overtime settimanale, no doppio conteggio col daily)
- `overtime_multiplier` — default 1.25 (+25%)
- `night_multiplier` — default 1.50 (+50%, fascia 22-06)
- `sunday_multiplier` — default 1.50
- `holiday_multiplier` — default 2.00
- `night_start` / `night_end` — default 22:00 / 06:00

### Engine

Nuovo `app/services/overtime.py` con `compute_overtime(punches, policy) → OvertimeBreakdown`:
- Considera solo `kind` shift + overtime; ferie/malattia/pausa/idle escluse
- Splitta TimePunch che attraversano mezzanotte
- Calcola per giorno: total, night overlap, is_sunday, is_holiday
- Aggrega per settimana ISO per overtime settimanale
- Applica priorità MAX moltiplicatore (no cumulo): festivo > domenica > overtime > notturno > regolare
- Output: `regular_hours`, `overtime_daily_hours`, `overtime_weekly_hours`, `night_hours`, `sunday_hours`, `holiday_hours`, `weighted_factor` (ore equivalenti per costo), `total_hours`, `daily` dettaglio

### Endpoint

- `GET /hr/api/overtime?resource_id=X&from_date=Y&to_date=Z` ritorna breakdown completo + policy applicata
- Override per-risorsa onorato: `Resource.working_hours_policy_id` ha precedenza, fallback su default tenant

### UI

- `/settings` tab "Orari lavorativi" → nuova sezione "Straordinari · soglie e maggiorazioni" con 8 input (soglie giornaliera/settimanale, 4 moltiplicatori, fascia notturna start/end)
- Validazione: soglie > 0, moltiplicatori ≥ 1.0
- Caricamento e salvataggio integrati al form esistente

### Migrazione

`scripts/migrate_overtime_thresholds.py` (opzione `[H]` su `strumenti.bat/sh`):
- ALTER TABLE working_hours_policies con 8 colonne nuove (idempotente)
- Default backfill per `night_start=22:00` / `night_end=06:00` su policy esistenti

### Cosa NON fa ancora

- Niente UI per visualizzare il breakdown su `/hr` (arriverà nel cost report v3.4.22)
- Niente cost report `/jobs/{id}/cost-report` (prossimo step)
- Niente banca ore / quadratura mensile / export cedolino

## v3.4.20.4 — Form ferie/malattia + override policy nel modal risorsa (29 aprile 2026)

Modal `/resources` esteso con due nuove sezioni di gestione disponibilità.

### Override policy orari per-risorsa

- **Dropdown "Orario lavorativo"** sotto le note
- Vuoto = usa default tenant (la "Italia standard")
- Lista popolata da `wh_policies` (passati al template dal router)
- Salva via `working_hours_policy_id` su `PUT /resources/api/{id}` (campo aggiunto già al backend)

### Sezione ferie/malattie (solo in edit mode)

- **Lista esistenti** in scroll-y (max-height 160px) con dot color, kind label, range date, eventuale note, bottone × per eliminare
- **Form aggiungi** inline: Dal / Al / Tipo (Ferie/Malattia/Altro) / Note + bottone "+ Aggiungi"
- Counter `(N)` accanto al titolo
- Hidden in create mode (serve prima salvare la risorsa)

### Backend

Nuovi endpoint in `app/routers/resources.py`:
- `GET /resources/api/{id}/unavailabilities` — lista ferie esistenti per risorsa
- `POST /resources/api/{id}/unavailability` — esteso con `kind` (vacation/sick/holiday/other)
- `DELETE /resources/api/unavailability/{u_id}` — soft delete (hard delete sul DB)
- `PUT /resources/api/{id}` accetta `working_hours_policy_id`
- `GET /resources/api/{id}` ritorna anche `working_hours_policy_id`

### Integrazione downstream

Le ferie aggiunte qui appaiono **automaticamente** sulla timeline `/planning/?view=timeline` come fasce striate indaco/rosse (logica già implementata in v3.4.17). Smart split rispetta queste date. Hard block drag su ferie attivo.

### File toccati

- `app/main.py` — version 3.4.20.4
- `app/routers/resources.py` — `wh_policies` nel context, GET/POST/DELETE unavailabilities, PUT con policy_id, GET con policy_id
- `app/templates/pages/resources.html`:
  - Modal: dropdown policy + sezione ferie collapsible
  - JS: `rsUnavLoad`, `rsUnavAdd`, `rsUnavDelete`, integrate in `editResource`/`openNewResource`
  - `saveResource` invia `working_hours_policy_id`

### Smoke

- `/resources/` 200, contiene `rs-wh-policy`, `rs-unav-list`, `rsUnavLoad`, `rsUnavAdd`
- `GET /resources/api/1/unavailabilities` 200

### Test sul Mac

1. `/resources/` → click su una risorsa
2. Modal mostra dropdown policy + sezione "Ferie e malattie"
3. Aggiungi periodo Vac/Mal/Altro con date e note
4. Verifica che timeline (`/planning/?view=timeline`) mostri lo strip nei giorni
5. Drag booking sopra ferie → hard block

---

## v3.4.20.3 — UI settings: tab "Orari lavorativi" (29 aprile 2026)

Nuova tab in `/settings` per modificare la `WorkingHoursPolicy` default senza dover passare per le API.

### Form

- **Nome policy**
- **Mattina · Inizio / Fine** (input `time` step 15min)
- **Pomeriggio · Inizio / Fine** (opzionali — vuoto = orario continuato senza pausa)
- **Giorni lavorativi**: 7 checkbox (Lun-Dom)
- **Festività nazionali**: select country code (IT default + 5 altri paesi comuni, "—" disabilita auto-import)
- **Salva** chiama `PUT /settings/api/working-hours/{id}` esistente
- **Annulla modifiche**: ricarica via GET

`showPane('hours')` triggera auto-load della policy default.

### File toccati

- `app/main.py` — version 3.4.20.3
- `app/templates/pages/settings.html`:
  - Nuova tab "🕐 Orari lavorativi"
  - Pannello `pane-hours` con form completo
  - Funzioni `whReload()`, `whSave()` (working_days bitmask)
  - `showPane` chiama `whReload()` quando si apre il tab

### Smoke

- `/settings/` 200, contiene `pane-hours`, `whReload`, `whSave`, `wh-morning-start`
- `GET /settings/api/working-hours` 200

---

## v3.4.20.2 — Modal multi-row leggibilità + cambio status veloce (29 aprile 2026)

### Modal multi-row (fix leggibilità >5 righe)

- Container `#tlb-assignments` ora ha **`max-height: 380px` + `overflow-y: auto`** → con molte risorse appare scrollbar interno
- Scrollbar custom indaco (Chromium)
- **Badge `Risorsa #N`** posizionato in alto-sinistra di ogni riga (negative top, rounded pill)
- **Counter `(N)`** indaco vicino al titolo "Risorse" si aggiorna a ogni add/remove
- Funzione `_tlbUpdateRemoveButtons` estesa per renumerare automaticamente le righe rimanenti dopo remove

### Cambio status veloce dal right-click

Voce dinamica nel context menu su item:
- Se booking è `tentative` → **`✓ Conferma booking`** (chiama PUT con status=confirmed)
- Se booking è `confirmed` → **`⏳ Rendi tentative`** (PUT con status=tentative)

Riusa endpoint `PUT /api/bookings/{id}` esistente (passa solo `status`). Toast feedback. Refresh timeline. Timeline visivamente aggiorna il bordo (tratteggiato/solido) automaticamente.

### File toccati

- `app/main.py` — version 3.4.20.2
- `app/templates/pages/planning.html`:
  - CSS: `#tlb-assignments { max-height/overflow }`, scrollbar custom, `.ass-num` pill
  - HTML: `<span class="ass-num">` in row template, counter in label
  - JS: `_tlbUpdateRemoveButtons` rinumera + counter, voce status nel context menu

### Smoke

- HTML contiene `ass-num`, `tlb-ass-counter`, `Conferma booking`, `Rendi tentative`, `max-height: 380px`

---

## v3.4.20.1 — Filtri sidebar con autocomplete (29 aprile 2026)

I 4 filtri "lunghi" della sidebar pianificazione (Cliente / Progetto / Job / Risorsa) erano `<select>` lunghi e poco scalabili. Ora sono **input search con dropdown autocomplete**, stesso pattern del modal "Nuovo booking".

### Pattern uniforme

- Helper riusabile **`FA_CONFIG`**: oggetto `{client, project, job, resource}` con `data` (seed), `search` (predicato match), `display` (testo input), `render` (HTML suggestion).
- Per ogni filtro:
  - Input testuale `<input data-fa="...">` per la ricerca live
  - Hidden `<input id="f-{key}">` per il valore (id) compatibile col flow esistente (`getFilterParams`, URL state)
  - Bottone `✕` per cancellare la selezione
  - Dropdown `.fa-suggestions` posizionato sotto l'input
- Click su suggestion → riempie input visibile + setta hidden + triggera `onFilterChange()`.

### Filtri specifici

| Filtro | Cerca su | Suggestion |
|---|---|---|
| **Cliente** | `name` | nome cliente |
| **Progetto** | `code`, `title`, `client_name` | `[CODE] title` + cliente come meta |
| **Job** | `code`, `title`, `client`, `project_code`, `project_title` | `[CODE] title` + cliente · progetto |
| **Risorsa** | `name` | dot color + nome + reparto come meta |

Reparto, Stato, Tipo restano `<select>` (pochi valori, fissi).

### Seed JSON aggiunti

- `CLIENTS_SEED`: `{id, name}`
- `PROJECTS_SEED`: `{id, code, title, client_name}`
- (`JOBS_SEED` e `RESOURCES_SEED` già presenti dal modal)

### Compatibilità

- URL state (`?client=N`): all'`readFiltersFromURL` ricarica display dall'id via `_faSetFromId`
- `renderActiveFiltersBar`: per gli autocomplete usa `FA_CONFIG[k].display(item)` invece del valore raw
- `resetFilters`: reset display + classe `has-value` + bottoni clear
- Niente cambi backend, solo riformattazione frontend dei filtri esistenti

### CSS

- `.fa-suggestions` dropdown indaco, hover indaco
- `.fa-input.has-value` sfondo leggermente indaco per indicare filtro attivo
- `.fa-meta` per riga secondaria (cliente/reparto)

### File toccati

- `app/main.py` — version 3.4.20.1
- `app/templates/pages/planning.html`:
  - HTML: 4 filtri convertiti in input + hidden + dropdown
  - JS: `FA_CONFIG`, `_faSearch`, `_faSetVisible`, `_faClear`, `_faSetFromId`, listener init
  - CSS: `.fa-suggestions`, `.fa-item`, `.fa-input.has-value`
  - Seed `CLIENTS_SEED`, `PROJECTS_SEED`
  - `readFiltersFromURL`, `renderActiveFiltersBar`, `resetFilters` aggiornati

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `FA_CONFIG`, `CLIENTS_SEED`, `PROJECTS_SEED`, `data-fa`, `fa-suggestions`

### Test sul Mac

1. Click su input "Cliente" → vedi tutti i clienti
2. Digita "TPR" → filtra
3. Click suggestion → riempie input + filtri timeline aggiornati
4. ✕ → cancella
5. Stesso flow per Progetto, Job (cross-search), Risorsa
6. URL `?client=3` → display popolato in input

---

## v3.4.20 — E6: AI propose_booking + suggest-resources (29 aprile 2026)

Sesta e ultima fase del piano core-planning. AI può ora proporre booking direttamente.

### Capability AI `propose_booking`

Aggiunta a `app/services/ai_assistant.py`:

```json
{
  "action": "propose_booking",
  "data": {
    "job_id": 42,           // oppure "job_code": "J-2026-001"
    "kind": "project",      // o internal_*
    "job_cost_line_id": 7,  // opzionale
    "notes": "Sessione color HDR",
    "assignments": [
      {"resource_id": 3, "start_datetime": "2026-05-04T09:00", "end_datetime": "2026-05-04T13:00"},
      {"resource_name": "Luca Bianchi", "start_datetime": "2026-05-04T10:00", "end_datetime": "2026-05-04T18:00"}
    ]
  }
}
```

- Risolve `job_code` → `job_id` se necessario
- Risolve `resource_name` → `resource_id` (case-insensitive)
- Conflict check per ogni assignment vs altri booking attivi
- Crea Booking + N BookingAssignment in singola transazione
- Status default `tentative`

System prompt aggiornato con la doc capability.

### Endpoint `GET /planning/api/suggest-resources`

Nuovo endpoint per AI auto-suggest e UI futura:
- `from_datetime`, `to_datetime`, `department_id?`, `type?`
- Per ogni risorsa attiva del tenant, ritorna due liste:
  - `available`: nessun conflitto in quel range
  - `busy`: con `conflict_assignment_id` o `unavailability_kind`
- Permette al copilot di rispondere "chi è libero il X" e proporre `propose_booking`

### File toccati

- `app/main.py` — version 3.4.20
- `app/services/ai_assistant.py` — `_h_propose_booking` handler, registrato in `_ACTION_HANDLERS`, doc nel system prompt
- `app/routers/planning.py` — `GET /api/suggest-resources`

### Smoke

- `GET /api/suggest-resources` con range 2026-05-04 09:00-13:00 dept=1 → 2 disponibili, 0 occupate
- `propose_booking` capability registrata in `_ACTION_HANDLERS`

### Esempio uso copilot (dopo questa versione)

> Utente: "Chi è libero giovedì 7 maggio dalle 14 per fare audio mix?"
> AI: chiama internamente `suggest-resources` (o riusa context), risponde:
> "Sono libere: **Mario Rossi** (Audio mixer, dept Audio) e **Luca Verdi** (Audio engineer). Vuoi assegnare uno?"
>
> Utente: "Sì, Mario, 14-18 sul job J-2026-005"
> AI:
> ```action
> {"action": "propose_booking", "data": {
>   "job_code": "J-2026-005",
>   "assignments": [{"resource_name": "Mario Rossi",
>     "start_datetime": "2026-05-07T14:00", "end_datetime": "2026-05-07T18:00"}]
> }}
> ```
> User clicca "Applica" → booking creato.

### Roadmap completata

E1→E6 di "Core planning" tutte chiuse:

| Fase | Versione | Tema |
|---|---|---|
| E1 | v3.4.14 | Editing diretto (drag/resize/delete) |
| E2 | v3.4.15 | Click&drag create + capacity heatmap + menu contestuale |
| E3 | v3.4.17 | Working hours + ferie/festività + smart split |
| E4 | v3.4.18 | Multi-select + keyboard + bulk paste |
| E5 | v3.4.19 | Ricorrenti + tentative + audit log |
| E6 | v3.4.20 | AI propose_booking + suggest-resources |

E2 ha incluso anche multi-resource (v3.4.16/16.1).

### Restano (backlog)

- v3.4.20.1 UI settings working hours editabile
- v3.4.20.2 Multi-row >5 leggibilità (collapse, scroll)
- v3.4.20.3 Snap line visiva durante drag
- v3.4.20.4 Endpoint POST/PUT cambio status tentative↔confirmed dal modal

---

## v3.4.19 — E5: ricorrenti + tentative visivo + audit log (29 aprile 2026)

### Booking ricorrenti

POST `/planning/api/bookings` ora accetta `recurrence_rule` + `recurrence_until`:

| Rule | Significato |
|---|---|
| `DAILY` | Tutti i giorni |
| `WEEKDAYS` | Lun-Ven |
| `WEEKENDS` | Sab-Dom |
| `MON` / `TUE` / `WED` / `THU` / `FRI` / `SAT` / `SUN` | Singolo giorno |
| `MON,WED,FRI` (CSV) | Combinazione custom |

Server espande in **N booking distinti**, uno per occorrenza, mantenendo orari + risorse + job. Conflict check su ogni occorrenza. Esempio: MON/WED/FRI dal 4 al 22 mag = **9 booking** creati.

UI nel modal: checkbox "Ricorri" → dropdown regola + date "fino al". Disabilitato in edit mode.

### Tentative bookings (visivo)

- `Booking.status` esistente già supportava `tentative` / `confirmed` / `cancelled`. Aggiunta solo viz.
- CSS `.vis-item.tl-tentative`: bordo tratteggiato 2px, opacità 70%
- Tooltip include " (tentative)"
- `tlBookingToItem` setta classe in base a `status === 'tentative'`

### Audit log (`booking_changes` table)

- **Nuovo modello `BookingChange`**: `id, booking_id, user_id, kind, summary, payload (JSON), created_at`
- Hook `_log_change(db, booking_id, kind, summary, payload)` chiamato in:
  - POST create (1 entry per ogni booking creato, anche in caso di ricorrenza)
  - PUT update
  - DELETE (soft → kind=delete)
  - POST restore
- **Nuovo endpoint `GET /planning/api/bookings/{id}/audit`** ritorna cronologia ordinata desc
- Nessuna migration esplicita (Base.metadata.create_all crea la tabella al boot)

### File toccati

- `app/main.py` — version 3.4.19
- `app/models/models.py` — `BookingChange`
- `app/models/__init__.py` — export
- `app/routers/planning.py` — `_log_change`, `_expand_recurrence`, parametri POST, audit hooks su update/delete/restore, endpoint audit GET
- `app/templates/pages/planning.html` — CSS `tl-tentative`, classe in `tlBookingToItem`, modal sezione "Ricorri" con dropdown + date until, reset/submit aggiornati

### Smoke E2E

- POST recurrence MON/WED/FRI 04→22 mag → 9 booking, audit log scritto
- GET audit log → entries con summary "Booking ricorrente MON,WED,FRI (occ 2026-05-04)"

### Da testare sul Mac

1. Modal nuovo → spunta "Ricorri" → dropdown "Lun/Mer/Ven" + data fine → crea
2. Verifica N booking creati nei giorni giusti
3. Booking con `status=tentative` (default in alcuni flussi) appare tratteggiato
4. `GET /planning/api/bookings/{id}/audit` ritorna cronologia

### Restano

- v3.4.19.1 endpoint POST/PUT change tentative↔confirmed dal modal
- v3.4.20 E6 AI auto-suggest assegnazione

---

## v3.4.18 — E4: Multi-select + keyboard shortcuts + bulk paste (29 aprile 2026)

Quarta fase del piano core-planning. Polish power-user senza nuove dipendenze backend.

### Multi-select

- vis-timeline `multiselect: true`, `multiselectPerGroup: false`
- **Ctrl+click** (Cmd su Mac) aggiunge/rimuove item dalla selezione
- **Shift+click** seleziona range (nativo vis-timeline)
- Items selezionati restano evidenziati col bordo bianco standard

### Keyboard shortcuts su timeline

Listener `keydown` globale, attivo solo se vista timeline è la corrente e nessun input ha focus.

| Tasto | Azione |
|---|---|
| **Ctrl+Z** | Undo dell'ultima azione (riusa stack già esistente) |
| **Ctrl+C** | Copia gli items selezionati nel clipboard interno (`window._tlClipboard`). Toast `Copiati N booking…` |
| **Ctrl+V** | Incolla il clipboard ad oggi (preserva offset relativo dal primo) |
| **Delete** | Bulk delete di TUTTI gli items selezionati. Conferma `Eliminare N assegnazioni?`. Mostra contatore success/fail. |
| **←  / →** | Nudge ±15min di un singolo item selezionato (PUT su assignment singolo, undo abilitato) |
| **Esc** | Pulisce la selezione |

Skip su background items (ferie/festa, id `u-*`).

### Bulk paste

- `tlBulkPaste()`: per ogni item nel clipboard, calcola offset rispetto al primo
- Crea N nuovi booking (1 assignment ognuno) ad oggi alla stessa ora
- Toast finale `N incollati a oggi` o warning se errori (es. conflitti)
- Conserva job_id, kind, cost_line_id, notes dell'originale

### Hint UI

`Drag = pan · Drag item = sposta · Bordi = durata · Alt+drag = duplica · Ctrl+click = multi-select · Canc/←→/⌘C/V/⌘Z · doppio click vuoto = nuovo`

### File toccati

- `app/main.py` — version 3.4.18
- `app/templates/pages/planning.html`:
  - Opzioni `multiselect: true` + `multiselectPerGroup: false`
  - Listener `keydown` con shortcuts
  - Funzione `tlBulkPaste`
  - `window._tlClipboard` state
  - Hint UI aggiornato

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `multiselect`, `_tlClipboard`, `tlBulkPaste`, `ArrowLeft/Right`

### Da testare sul Mac

1. Ctrl+click su 2 items diversi → entrambi selezionati
2. Ctrl+C → toast `Copiati 2 booking`
3. Ctrl+V → 2 booking creati ad oggi alla stessa ora dell'originale
4. Selezione + Canc → conferma + bulk delete
5. Selezione singola + freccia ← / → → nudge ±15min
6. Esc → pulisce selezione
7. Ctrl+Z → undo dopo nudge

### Restano (E5/E6)

- v3.4.18.1: snap line visiva durante drag, multi-row >5 leggibilità
- v3.4.19 E5: ricorrenti + tentative bookings + audit log
- v3.4.20 E6: AI auto-suggest assegnazione

---

## v3.4.17 — E3: Working hours policy + ferie/festività bloccanti + smart split (29 aprile 2026)

Terza fase del piano core-planning. Tre feature integrate:

### 1. Modello WorkingHoursPolicy

- **Nuova tabella `working_hours_policies`** con: `name`, `is_default`, `morning_start/end`, `afternoon_start/end` (NULL = orario continuato), `working_days` (bitmask lun=bit0..dom=bit6, default 31=lun-ven), `holidays_country` (ISO, default "IT").
- **Resource.working_hours_policy_id** override opzionale per risorsa.
- **Default tenant**: "Italia standard" 09:00-13:00 / 14:00-18:00 lun-ven, festività `IT`.
- **ResourceUnavailability.kind** enum (`vacation` / `sick` / `holiday` / `other`).
- Migration `scripts/migrate_working_hours.py` idempotente, voce `[G]` su strumenti.

### 2. Engine `split_booking_smart` (`app/services/working_hours.py`)

- Dato `(start, end, policy, unavailabilities)` ritorna lista `TimeSlot` ritagliati su:
  - giorni lavorativi (skip weekend)
  - mattina + pomeriggio (split su pausa pranzo)
  - festività nazionali (libreria Python `holidays` — `holidays.IT(years=...)`)
  - ferie/malattia (date escluse)
- Esempio: lun 4 mag 08:00 → mer 6 mag 22:00 → 6 slot (mat+pom × 3gg).

### 3. Backend planning API

- **`GET /planning/api/unavailabilities`**: ritorna ferie/malattia espliciti + festività auto + weekend (opzionali) per il range. Aggregazione run consecutivi per ridurre payload. `resource_id` opzionale.
- **`POST /planning/api/unavailabilities`**: crea ferie/malattia (validazione date).
- **`DELETE /planning/api/unavailabilities/{id}`**: cancellazione.
- **`POST /planning/api/bookings`** ora accetta flag `smart_split=true`: server espande gli assignments con l'engine prima di salvare.
- **`GET /settings/api/working-hours`** + **`PUT /settings/api/working-hours/{id}`** per gestione policy (UI dedicata in v3.4.17.1).

### 4. Frontend timeline

- **Background items** per ferie/malattia/festività: pattern striato indaco (vacation), rosso (sick), arancio (holiday). Render via vis-timeline `type: 'background'`, classe `tl-bg-{kind}`.
- **Hard block durante drag**: `onMoving` rileva overlap con item bloccante (`vacation`/`sick`/`holiday`), applica classe `tl-conflict-hard` (sfondo rosso scuro pieno + animazione shake). `onMove` rifiuta drop con toast `Risorsa non disponibile in questo periodo (ferie/festività)`.
- **Skip drag su background items**: i bg-items non sono trascinabili.

### 5. Modal smart split

- **Checkbox "Smart split"** sotto le note (sfondo verde). Default off.
- Quando attivo (e non in edit mode), invia `smart_split=true` al POST. Server splitta ogni assignment del payload in N sub-slot rispettando policy + unavailabilities della risorsa.
- In edit mode il toggle è disabilitato (replace-all assignments diretti).

### File toccati

- `app/main.py` — version 3.4.17
- `app/models/models.py` — `UnavailabilityKind`, `WorkingHoursPolicy`, `Resource.working_hours_policy_id`, `ResourceUnavailability.kind`
- `app/models/__init__.py` — export
- `scripts/migrate_working_hours.py` — nuovo
- `app/services/working_hours.py` — nuovo (engine split)
- `app/routers/planning.py` — endpoint unavailabilities CRUD, smart_split flag su POST, helper `_resolve_policy_for_resource` e `_expand_assignments_smart`
- `app/routers/settings.py` — endpoint policy GET/PUT
- `app/templates/pages/planning.html` — fetch unavailabilities, render bg-items, hard block onMoving/onMove, checkbox smart split, CSS `tl-bg-*` e `tl-conflict-hard`
- `requirements.txt` — `holidays>=0.60`
- `strumenti.bat` / `strumenti.sh` — voce `[G]`

### Smoke E2E

- `/health` 200
- `GET /planning/api/unavailabilities` ritorna festività italiane (25 apr Liberazione, 1 mag Lavoratori) + weekend riconosciuti
- `POST /planning/api/bookings` con `smart_split=true` su range lun-mer 8-22 → 6 assignments (mat/pom × 3gg, 9-13 + 14-18)
- `GET /settings/api/working-hours` ritorna policy default

### Da testare sul Mac

1. `[G]` su strumenti per migrare DB
2. Su timeline: weekend e festività italiane (es. 25 apr) appaiono striati
3. Drag booking sopra una festività → bordo rosso animato + drop rifiutato
4. Modal nuovo booking → checkbox "Smart split" → range multi-day → 1 booking ma con N assignments rispettosi di pausa/weekend/festa
5. `pip install -r requirements.txt --upgrade` per ottenere `holidays`

### Restano per v3.4.17.1

- UI settings page con form policy modificabile
- Override policy per-risorsa (UI in `/resources` page)
- Form ferie/malattia in `/resources/{id}` (oggi solo via API)

---

## v3.4.16.1 — Multi-resource UI completa (modal multi-row + edit) (29 aprile 2026)

Frontend completo per multi-resource. Modal "Nuovo/Modifica booking" ora supporta **N risorse con orari distinti** in un unica operazione.

### Modal multi-row

- **Sezione "Risorse"** sostituisce la vecchia "Orari + Risorsa" globale
- **Bottone `+ Aggiungi risorsa`** in alto a destra: aggiunge una nuova riga
- Ogni riga assignment contiene:
  - **Select risorsa** raggruppato per reparto (`<optgroup>` per ogni Department + "Senza reparto")
  - **Inizio**: data + ora separati (input nativi + step 15min)
  - **Fine**: data + ora separati
  - **Display durata** live (`Xh` / `Yg Zh`, rosso se invalida)
  - **Preset rapidi**: 1h, 2h, 4h, 8h, 2gg, 1sett (applicati alla SOLA riga del bottone)
  - **Bottone × Rimuovi** (disabilitato se è l'unica riga, almeno 1 sempre richiesta)
- Container `#tlb-assignments` popolato dinamicamente da `tlbAddAssignmentRow(preset)`
- Helper `_readRow(row)`, `_setRow(row, data)`, `_tlbCollectAssignments()` per raccolta + validazione

### Edit mode (nuova feature)

- Right-click su booking → **"Modifica…"** ora chiama `tlbOpenEdit(bookingId)` invece di aprire modal con range singolo
- `tlbOpenEdit`:
  1. Reset modal, set `tlb-editing-booking-id`, cambia titolo a `Modifica booking #N`, bottone a `Aggiorna`
  2. Filtra `window._tlBookings` per booking_id selezionato → array di items (1 per assignment)
  3. Pre-popola metadata (kind, job, lavorazione, notes) dal primo item
  4. Crea **N righe**, una per ogni assignment esistente
- Submit fa **PUT `/api/bookings/{id}`** (replace-all assignments) invece di POST nuovo

### tlbSubmit unificato

- Detect editing via hidden `tlb-editing-booking-id`
- `_tlbCollectAssignments()` valida ogni riga (resource_id, start, end, end > start)
- Form data invia `assignments` JSON, kind, job_id, line_id, notes
- POST se nuovo, PUT se editing
- Toast "Booking creato" o "Booking aggiornato"

### File toccati

- `app/main.py` — version 3.4.16.1
- `app/templates/pages/planning.html`:
  - Modal HTML rifatto (sezione Risorse multi-row)
  - CSS `.tlb-ass-row`, `.ass-grid`, `.ass-labels`, `.ass-footer`
  - Funzioni JS: `_resourceOptionsHTML`, `tlbAddAssignmentRow`, `tlbRemoveAssignmentRow`, `_tlbUpdateRemoveButtons`, `tlbAssOnChange`, `_readRow`, `_setRow`, `tlbAssUpdateDuration`, `tlbAssSetDur`, `tlbAssSetDurDays`, `_tlbCollectAssignments`, `tlbOpenEdit`
  - Refactor `tlbOpen` / `tlbOpenWithRange` (creano 1 riga preset)
  - Refactor `tlbSubmit` (POST vs PUT in base a edit mode)
  - Rimosse funzioni obsolete `tlbSetDuration`, `tlbSetDurationDays`, `tlbUpdateDurationDisplay`, `_setDtFields`, `_readDtFields`, `tlbSyncStart`, `tlbSyncEnd`
  - Right-click "Modifica…" usa `tlbOpenEdit(bookingId)`
  - `window._tlBookings = bookings` esposto per edit mode

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `tlbAddAssignmentRow`, `tlbOpenEdit`, `_tlbCollectAssignments`, `tlb-assignments` container, `tlb-editing-booking-id` hidden

### Da testare sul Mac

1. Doppio click su area vuota → modal con 1 riga preset
2. Click `+ Aggiungi risorsa` → seconda riga
3. Cambia risorsa, orari (data + ora separati), preset durata
4. Submit → booking creato con 2 assignments
5. Right-click su un booking esistente → `Modifica…` → modal precaricato con tutte le risorse del booking
6. Modifica una riga, aggiungi una risorsa, salva → PUT funziona, timeline aggiornata
7. Bottone × disabilitato se 1 sola riga; toast "Almeno 1 risorsa richiesta" se provi a rimuovere l'ultima

### Restano per dopo

- Warning visivo booking senza assignments (improbabile in UI normale, backend rifiuta già)
- Undo cancellazione assignment singolo (richiede soft-delete o redux pattern)
- Raggruppamento visivo timeline degli assignments dello stesso booking (collega visibilmente con linea/badge)

---

## v3.4.16 — Multi-resource booking (parte 1: backend + adattamento frontend) (29 aprile 2026)

Cambio architetturale: un Booking può avere **N risorse**, ognuna con il proprio intervallo (anche differenti tra loro). Riferimento: cinema/post-production dove uno stesso turno può vedere colorist + assistant + producer presenti con orari diversi.

### Modello

- **Nuova tabella `booking_assignments`** — `id, booking_id, resource_id, start_datetime, end_datetime`. Cascade delete dal booking padre.
- **Rimosso `Booking.resource_id`**: Booking ora è un contenitore puro.
- **`Booking.start_datetime` / `end_datetime` diventano envelope** auto-calcolati come `min/max` degli `assignments`.
- **Relazione**: `Booking.assignments` ↔ `BookingAssignment.booking`. `Resource.booking_assignments` (era `Resource.bookings`).

### Migration `scripts/migrate_multi_resource.py`

1. Crea tabella `booking_assignments`
2. Per ogni Booking esistente → 1 assignment con `(resource_id, start, end)` (1:1 con il vecchio comportamento)
3. Drop column `bookings.resource_id` via recreate-table dance SQLite (idempotente)
4. Disponibile dal menu strumenti `[F]` (.bat e .sh)

### Backend (`app/routers/planning.py`)

- **GET `/api/bookings`** — restituisce **1 item per assignment** (non più 1 per booking). Item id `a{N}`. ExtendedProps include `group_size`, `group_position` per badge "1/3".
- **POST `/api/bookings`** — accetta `assignments` come stringa JSON (lista di `{resource_id, start_datetime, end_datetime}`). Almeno 1 assignment richiesto. Conflict check su tutti.
- **PUT `/api/bookings/{id}`** — aggiorna metadata (kind/job/status/notes) + opzionale replace-all `assignments`.
- **NUOVO `PUT /api/booking-assignments/{aid}`** — aggiorna un singolo assignment (drag/resize/reassign del singolo item timeline).
- **NUOVO `DELETE /api/booking-assignments/{aid}`** — cancella singolo assignment. Se è l'ultimo del booking → cancella (soft) il booking intero.
- **POST `/api/bookings/{id}/restore`** — conflict check ora su tutti gli assignments del booking.
- Helper riusabili: `_check_assignment_conflict`, `_recalc_booking_envelope`, `_validate_kind_job`.

### Refactor downstream

- `app/routers/jobs.py` — `_aggregate_planned_hours` e `_aggregate_unassigned` ora aggregano `BookingAssignment` invece di `Booking` (un booking N risorse = somma per assignment, non envelope).

### Frontend (planning.html, adattamenti minimi)

- **`tlBookingToItem`** — usa `id="a{N}"` dal backend, badge "N/M" se booking multi-risorsa.
- **`onMove`** — chiama `PUT /api/booking-assignments/{aid}` (singolo assignment) invece di PUT booking.
- **`onRemove`** — chiama `DELETE /api/booking-assignments/{aid}`.
- **Right-click "Elimina"** — etichetta "Elimina assegnazione" + endpoint assignment.
- **`_tlDoMove` / `_tlDoDuplicate`** — sui nuovi endpoint. Duplica crea sempre 1 nuovo Booking con 1 assignment.
- **`tlbSubmit` (modal "Nuovo")** — invia `assignments=[{resource_id,start,end}]` come JSON nel form. UI mono-row per ora (multi-row in v3.4.16.1).
- **`tlPerformUndo`** — gestisce `update_assignment` e `remove_assignment` types.

### Smoke E2E backend

- GET `/api/bookings` → 9 items, formato `a{N}`, `group_size=1`, `group_position=1`
- POST con 2 assignments → booking con env start=09:00, end=18:00, 2 assignments distinti
- PUT singolo assignment → start/end aggiornati, envelope ricalcolato
- DELETE 1 assignment di booking con 2 → booking_cancelled=false
- DELETE ultimo assignment → booking_cancelled=true

### Restano per v3.4.16.1

- **Modal multi-resource UI**: righe dinamiche (`+ Aggiungi risorsa`), ognuna con resource select + start + end + remove
- **Warning visivo** booking senza risorse
- **Cancel-fissaggio**: undo per assignment cancellato (richiede `POST /restore-assignment` o approach diverso)

### File toccati

- `app/main.py` — version 3.4.16
- `app/models/models.py` — `BookingAssignment`, rimosso `Booking.resource_id`, `Resource.booking_assignments`
- `app/models/__init__.py` — export `BookingAssignment`
- `scripts/migrate_multi_resource.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce `[F]` migrazione
- `app/routers/planning.py` — refactor completo endpoint booking
- `app/routers/jobs.py` — aggregazioni via assignments
- `app/templates/pages/planning.html` — adattamento item id, helpers, modal submit, undo

### Da testare sul Mac

1. `./strumenti.sh` → `[f]` per migrare DB
2. Verificare che nessun booking esistente sia "perso" (dovrebbero apparire tutti)
3. Drag/resize/delete su timeline (ora opera su singolo assignment)
4. Modal nuovo booking → crea
5. Multi-row assignment ancora **non disponibile** in UI (backend lo supporta, UI in v3.4.16.1)

---

## v3.4.15.6 — Rimosso Shift + time picker custom (29 aprile 2026)

### Shift+drag rimosso

Dopo 3 tentativi di stabilizzazione (capture phase, setOptions toggle, sync da event), Shift+drag continuava a essere instabile (cursor crosshair "appendeva", il drag non sempre catturato). Tolto del tutto. Tutti i listener `_tlSetShiftMode`/`_tlSyncShiftFromEvent`/`tlCreateMouseDown` rimossi insieme alle ghost rectangle handlers e mouseup globali.

**Metodi nuovo booking residui** (entrambi affidabili):
- **Doppio click** su area vuota timeline
- **Click destro** su area vuota → "Nuovo booking qui"

Hint UI aggiornato: `Drag = pan · Drag item = sposta · Bordi item = durata · Alt+drag = duplica · click destro = menu · doppio click vuoto = nuovo`.

### Time picker custom

`<input type="time">` browser nativo era poco preciso/incoerente tra browser. Sostituito con:

- **Trigger button** `<button class="tlb-tp-trigger">` mostra `HH:MM`, click apre popup
- **Popup** `#tlb-tp-popup` (riusabile per entrambi i campi inizio/fine) con due colonne scrollabili:
  - Ore: 00–23 (24 celle)
  - Minuti: 00, 15, 30, 45 (4 celle)
- Click su cella → setta valore, evidenzia selezione, sync hidden + duration display
- Auto-scroll alla selezione corrente all'apertura
- Click fuori chiude popup, riposiziona se sfora viewport
- Hidden `<input type="hidden" id="tlb-start-time">` mantiene formato `HH:MM` per submit

CSS coerente con palette indaco MediaFlow (selected = `#6272f5` background + bianco bold).

### File toccati

- `app/main.py` — version 3.4.15.6
- `app/templates/pages/planning.html` — rimossi listener Shift e ghost rectangle, rimosso `tlCreateMouseDown`, sostituito `<input type="time">` con trigger + popup, aggiunte `_initTimePicker`, `tlbOpenTimePicker`, `_tlbTpOutside`, `tlbSetTimePart`, `_setDtFields` aggiornato per scrivere su trigger + hidden, `_tlbReset` chiude eventuale popup, hint UI aggiornato

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `_initTimePicker`, `tlbOpenTimePicker`, `tlb-tp-trigger`, `tlb-tp-popup`. Niente residui `_tlShiftDown`/`_tlSetShiftMode`.

---

## v3.4.15.5 — Hotfix: Shift robusto + split data/ora nel modal (29 aprile 2026)

### Bug 1 — Shift sticky

Lo stato `_tlShiftDown` poteva restare bloccato a `true` quando keyup non scattava (es. apertura modal cambia focus, switch tab, alt-tab).

**Fix multipli ridondanti**:
- Funzione `_tlSetShiftMode(on)` centralizzata
- `_tlSyncShiftFromEvent(e)` riallinea stato con `e.shiftKey` reale a OGNI mousemove e mouseup
- Reset esplicito su `blur`, `visibilitychange` (tab nascosta), e all'apertura del modal (`tlbOpen`/`tlbOpenWithRange`)

In pratica: anche se keyup non scatta, alla prima `mousemove` post-modal lo stato si auto-corregge dal valore di `e.shiftKey`.

### Bug 2 — Orari poco precisi nel pop-up

`<input type="datetime-local">` mostra un picker che varia molto tra browser e talvolta non espone bene l'ora. Soluzione: **split in 4 input**.

- `<input type="date" id="tlb-start-date">` + `<input type="time" id="tlb-start-time" step="900">`
- Stesso per fine
- Hidden `tlb-start` / `tlb-end` combinano i due in `yyyy-MM-ddTHH:mm` per il submit
- Helper `_setDtFields(prefix, date)` / `_readDtFields(prefix)` per scrittura/lettura
- Sync automatico via `oninput="tlbSyncStart(); tlbUpdateDurationDisplay()"` su entrambi i sub-input
- `tlbSubmit` fa sync esplicito + guard "Compila inizio e fine"
- Preset durata e display durata aggiornati per usare i nuovi helper

UX: ora data e ora sono input separati e visibili, picker browser nativo per ognuno è più affidabile, time input ha step 15min esplicito.

### File toccati

- `app/main.py` — version 3.4.15.5
- `app/templates/pages/planning.html` — `_tlSetShiftMode`, `_tlSyncShiftFromEvent`, listener `mousemove/mouseup/visibilitychange`, modal HTML rifatto con 4 sub-input + 2 hidden, `_setDtFields`/`_readDtFields`/`tlbSyncStart`/`tlbSyncEnd`, refactor `tlbOpen`, `tlbOpenWithRange`, `tlbSetDuration`, `tlbSetDurationDays`, `tlbUpdateDurationDisplay`, `tlbSubmit`

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `_tlSetShiftMode`, `_tlSyncShiftFromEvent`, `visibilitychange`, `tlb-start-date`, `tlb-start-time`, `tlbSyncStart`

---

## v3.4.15.4 — Hotfix Shift via toggle moveable + modal "Nuovo booking" espanso (29 aprile 2026)

### Fix Shift+drag definitivo

Il listener su document capture fase non bastava: vis-timeline cattura mousedown sui suoi sub-elementi prima di rilasciare il bubble. Approccio invertito: invece di intercettare l'evento, **disabilito `moveable` quando Shift è premuto**.

- `keydown` Shift → `tlInstance.setOptions({moveable: false})` + cursor `crosshair`
- `keyup` Shift / blur → `tlInstance.setOptions({moveable: true})` + cursor reset
- `tlInstance` esposto come `window._tlInstance` per accesso dai listener globali
- Con `moveable: false` durante shift, vis-timeline non intercetta più mousedown per pan, e il listener custom su `document` capture parte regolarmente

### Modal "Nuovo booking" espanso

**Sezione Orari evidenziata** (sfondo indaco):
- Input `datetime-local` con `step="900"` (15 minuti precisione)
- Display "Durata: Xh / Yg Zh" calcolato live, color indaco se valido / rosso se fine ≤ inizio
- **Preset durata rapidi**: bottoni `1h / 2h / 4h / 8h (giornata) / 2 giorni / 1 settimana` — click setta `end = start + N`

**Job search autocomplete cross-progetto**:
- Input testuale con dropdown suggerimenti sotto (max 12 risultati)
- Filtro su 5 campi: code, title, client, project_code, project_title
- Suggestion mostra: `[CODE] Title — Cliente · Progetto-code Progetto-title`
- Click suggestion → riempie input visibile, popola `tlb-job-id` (hidden), carica lavorazioni del job
- Click outside o focus loss → chiude dropdown
- Seed `JOBS_SEED` aggiunto al template con campi arricchiti (project + client tramite joinedload già presente)

**Note → textarea** (resize verticale, 3 righe iniziali, font monospace come i campi).

**Modal width** allargato 560 → 640px per il nuovo contenuto.

### File toccati

- `app/main.py` — version 3.4.15.4
- `app/templates/pages/planning.html` — `_tlShiftDown` + setOptions toggle, `JOBS_SEED` seed, modal HTML rifatto, `tlbJobSearch`, `tlbSelectJob`, `tlbSetDuration`, `tlbSetDurationDays`, `tlbUpdateDurationDisplay`, `_tlbReset`, `tlbSubmit` aggiornato per `tlb-job-id` hidden, click-outside per dropdown, CSS `.tlb-job-item:hover`

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `JOBS_SEED`, `tlbJobSearch`, `tlbSetDuration`, `_tlShiftDown`, `window._tlInstance`

### Da testare sul Mac

- Tieni premuto Shift mentre sei sulla timeline → cursor diventa crosshair
- Shift+drag su area vuota di una risorsa → ghost rectangle + tooltip durata → modal pre-popolato
- Modal: digita "ma" → vedi job che matchano, click → si compila tutto, lavorazioni popolate
- Click presets durata → end aggiornato, display sotto si aggiorna

---

## v3.4.15.3 — Hotfix: Shift+drag affidabile + preserve window (29 aprile 2026)

Due bug:

### Bug 1 — Shift+drag non scattava

vis-timeline catturava `mousedown` sui suoi sub-elementi prima del listener su `host` (anche con capture phase). Risultato: lo shift+drag non avviava la creazione.

**Fix**: listener spostato su `document` in capture phase. Filtro per `host.contains(e.target)` per limitare alla timeline corrente. Aggiunto `e.stopImmediatePropagation()` oltre a `stopPropagation()` per fermare definitivamente vis-timeline. Cleanup del listener precedente via `window._tlCreateHandler` riferimento globale per evitare doppi handler dopo re-render.

### Bug 2 — Refresh tornava a oggi

Dopo creazione/modifica/elimina un booking, `renderTimeline()` veniva chiamato per refresh. Re-buildava la finestra a `tlWindowFor(tlZoom, new Date())` = "oggi → +N giorni". Se l'utente stava lavorando su una settimana futura, la vista saltava indietro.

**Fix**: `renderTimeline(preserveWindow=false)` accetta un flag. Se true, `tlInstance.getWindow()` viene salvato prima del destroy e usato come `win` nel re-render. Tutte le chiamate post-action (`tlbSubmit`, undo, onMove duplicate, right-click duplicate/reassign/delete) passano `true`. Solo le chiamate di prima inizializzazione (setView, init) restano default.

### File toccati

- `app/main.py` — version 3.4.15.3
- `app/templates/pages/planning.html` — `tlCreateMouseDown` su document capture, `renderTimeline(preserveWindow)` con savedWin, 6 chiamate aggiornate a `renderTimeline(true)`

### Smoke

- HTML contiene `tlCreateMouseDown`, `preserveWindow`, `savedWin`, `renderTimeline(true)`
- `/planning/?view=timeline` 200

---

## v3.4.15.2 — Hotfix: blocca drop booking su gruppo reparto (29 aprile 2026)

Bug: era possibile droppare un booking su un'intestazione di reparto (DI/Video, Audio, ...) invece che su una risorsa specifica. I reparti sono `nestedGroups` con `id` stringa (`'d1'`, `'d2'`, `'d0'`), le risorse foglia hanno `id` numerico.

### Fix doppia protezione

1. **`onMoving` live**: durante il drag, se `typeof item.group !== 'number'` (cioè si trascina sopra un'intestazione reparto), forzo `item.group` indietro al group originale → l'item visivamente non si sposta sul reparto.
2. **`onMove` al drop**: guard finale che rifiuta il commit con `callback(null)` + toast warning `Sposta su una risorsa, non su un reparto`.

### File toccati

- `app/main.py` — version 3.4.15.2
- `app/templates/pages/planning.html` — guard in `onMoving` + `onMove`

---

## v3.4.15.1 — Hotfix E2: drag pan + Shift+drag create + right-click menu (29 aprile 2026)

Feedback Matteo: "Non funzionano i punti da 1 a 6. Scoll wheel funziona ma preferivo il trascinamento. Inserisci menù tramite click mouse destro per operazioni su task."

### Cosa cambia rispetto a v3.4.15

- **`moveable: true` ripristinato**: drag pan funziona di nuovo (preferenza utente). Era stato disabilitato in v3.4.15 per liberare drag su background. Trade-off invertito.
- **Click&drag create → Shift+drag**: per non interferire col drag pan, l'attivazione del nuovo booking è ora `Shift+drag` (modifier convenzione standard). Listener registrato in fase di **capture** (`useCapture: true`) per anticipare vis-timeline.
- **Right-click context menu** introdotto:
  - Su un **booking esistente**: `Modifica… / Duplica qui / Sposta su altra risorsa… / Elimina / Annulla`. "Sposta" apre sub-menu con elenco risorse.
  - Su **area vuota**: `+ Nuovo booking qui… / Annulla`.
  - Listener `tlInstance.on('contextmenu')` con `event.preventDefault()` per sopprimere menu nativo browser.

### Heatmap robustezza

- Bug potenziale fix: `groupsDS.clear() + add()` veniva chiamato su `rangechanged` e poteva rompere `nestedGroups` dei reparti. Ora aggiorna **solo le foglie risorsa** (`id` numerico) via `groupsDS.update(g)`, preserva la gerarchia.
- CSS espliciti per visibilità heatmap dentro le label vis-timeline (`width`, `height`, `display:flex`, padding-bottom su label foglia).
- Guard su `props.start || tlInstance.getWindow().start`.

### Hint UI

`Drag = pan · Shift+drag su vuoto = nuovo · Drag item = sposta (menu cross-resource) · Bordi item = durata · Alt+drag = duplica · click destro = menu`

### File toccati

- `app/main.py` — version 3.4.15.1
- `app/templates/pages/planning.html` — `moveable: true`, `e.shiftKey` guard nel mousedown create + capture, `tlInstance.on('contextmenu')` con submenu per Sposta, `groupsDS.update(g)` per heatmap, CSS visibilità heatmap

### Smoke

- HTML contiene: `moveable: true`, `e.shiftKey`, `tlInstance.on('contextmenu')`, `tl-heat` CSS
- `/planning/?view=timeline` 200

### Da testare sul Mac

- Drag normale → pan finestra (come scroll wheel ma più fluido)
- Shift+drag su vuoto → ghost item + tooltip + modal
- Click destro su booking → menu Modifica/Duplica/Sposta/Elimina
- Click destro su vuoto → "Nuovo booking qui"
- Heatmap visibile sotto ogni nome risorsa
- Cambio zoom → heatmap si aggiorna senza rompere nesting reparti

---

## v3.4.15 — E2 — Click&drag create + capacity heatmap + menu contestuale (29 aprile 2026)

Seconda fase del piano "core planning". Tre feature in una versione.

### Click&drag su area vuota crea booking

- Mousedown su background o group-label → tracking → mouseup
- **Ghost rectangle** floating sopra il cursore, semitrasparente con bordo dashed indaco
- **Tooltip live durata** dentro il ghost: `Lun 4 mag · 09:00 → 13:00 · 4h` (single-day) o `Lun 4 mag 09:00 → Mer 6 mag 18:00 · …` (multi-day)
- Snap adattivo già attivo (15/30/60min)
- Mouseup → modal pre-popolato con risorsa locked + start/end calcolati. Funzione nuova `tlbOpenWithRange(resourceId, startDate, endDate)` parallela a `tlbOpen`.
- Soglia minima drag 5px per evitare ghost spurio su click puro; durata minima 1 minuto per scartare click accidentali.
- **Disabilitato pan via drag** (`moveable: false`) per liberare il drag sul background. Pan resta via bottoni ◀/Oggi/▶ + scroll wheel + selettore Vai a.

### Capacity heatmap sotto nome risorsa

- Calcolo client-side dai booking attivi nella finestra visibile.
- Per ogni risorsa, una **barra orizzontale** sotto il nome con un segmento per ogni giorno del range.
- Colorazione per ratio occupazione (8h = piena giornata):
  - 0% → trasparente
  - 0-50% → verde chiaro `rgba(34,197,94,.45)`
  - 50-100% → verde pieno
  - 100-150% → arancio `#fb923c`
  - 150%+ → rosso `#dc2626`
- Tooltip nativo per cella: `Lun 4 mag · 6.5h`.
- Skip render se range > 100 giorni (zoom Trimestre con span estesi).
- **Live update** su `rangechanged` (debounced 150ms): cambia zoom o sposta finestra → heatmap si ricalcola e si ridisegna.

### Menu contestuale al drop cross-resource

- Drag entro stessa risorsa = move silente (PUT diretto).
- Drag su altra risorsa **senza** Alt = popover fluttuante con 3 voci:
  - `↪  Sposta su altra risorsa` (default azione)
  - `⊕  Duplica su altra risorsa` (POST nuovo, originale resta)
  - `✕  Annulla` (callback null, item torna in posizione)
- Posizionamento del menu: ultime coordinate mouse tracciate via `mousemove` su host, riposizionato se sfora viewport.
- Chiusura: click outside, Escape, o scelta. Implementato come Promise.
- Alt+drag (cross-resource o stessa risorsa) = scorciatoia diretta a duplica senza menu — preserva pattern E1 per power user.
- Refactor `_tlDoMove(item, orig, id)` e `_tlDoDuplicate(item, origBooking)` come helper riutilizzabili.

### File toccati

- `app/main.py` — version 3.4.15
- `app/templates/pages/planning.html` — `tlContextMenu`, `_tlDoMove`, `_tlDoDuplicate`, `tlComputeHeatmap`, `tlHeatmapHTML`, `tlBuildGroups(bookings, rangeStart, rangeEnd)`, `tlbOpenWithRange`, mousedown/move/up handlers per click&drag create, listener rangechanged con debounce per rebuild heatmap, `moveable: false` + `horizontalScroll: true`, hint UI aggiornato.

### Smoke test

- `/planning/?view=timeline` 200
- HTML contiene: `tlComputeHeatmap`, `tlContextMenu`, `tlbOpenWithRange`, `tl-ghost-create`, `moveable: false`

### Da testare sul Mac

- Click&drag su area vuota → ghost item con tooltip durata → modal pre-popolato
- Trim drag (<5px) o durata <1min → scartato
- Heatmap visibile sotto ogni risorsa, colori coerenti con carico
- Cambio zoom → heatmap si aggiorna
- Drag booking su altra risorsa → menu Sposta/Duplica/Annulla
- Alt+drag su altra risorsa → duplica diretto (no menu)
- Scroll wheel → pan orizzontale (sostituisce drag pan disabilitato)

### Prossimo step

- v3.4.16 — E3 — WorkingHoursPolicy globale+override + split smart + pausa rigida + ferie/malattia bloccanti + holiday Italia auto

---

## v3.4.14 — E1 — Editing diretto sulla timeline (29 aprile 2026)

Prima fase del piano "core planning" in 6 step. Drag/resize/delete dei booking direttamente sulla Resource Timeline, con undo + conflict viz live + duplica via Alt+drag.

### Backend

- **Nuovo `PUT /planning/api/bookings/{id}`** con conflict check che esclude se stesso. Tutti i campi opzionali, semantica PATCH ma metodo PUT (coerenza form-based con il resto dei router). Validazioni: `kind=project` richiede `job_id`, `kind=internal_*` azzera job/cost_line.
- **Nuovo `POST /planning/api/bookings/{id}/restore`** per undo di cancellazioni. Conflict check sul ripristino (può fallire se nel frattempo è stato creato un booking sopra).
- **Fix `GET /planning/api/bookings`**: di default ora esclude `status=cancelled` (bug pre-esistente che mostrava cancellati nelle viste). Il filtro esplicito `?status=cancelled` continua a funzionare.

### Frontend (vis-timeline)

- `editable: {updateTime, updateGroup, remove, overrideItems}` attivi.
- **Snap adattivo allo zoom**: 15min in Giorno, 30min in Settimana, 60min in Mese/Trimestre. Funzione `tlSnap(date, scale, step)`.
- **Drag**: sposta booking nello stesso giorno o su altra risorsa (cross-group). Bordo aggiornato live, snap durante il drag.
- **Resize**: handle laterali sui bordi, cursor `ew-resize`. Ghost durante resize.
- **Conflict viz live**: durante drag/resize, se l'item collide con un altro stesso resource → classe `.tl-conflict` (sfondo rosso `#dc2626`, ring `rgba(220,38,38,.4)`). Solo viz, drop comunque permesso → backend fa il vero check.
- **Alt+drag = duplica**: se Alt è premuto durante il drag, al drop viene fatto POST di nuovo booking (con stessa risorsa/job/cost_line ma posizione nuova) invece di PUT update. L'originale resta dov'era. Tracking `window._tlAltDown` via keydown/keyup globali.
- **Delete**: tasto Canc su item selezionato. vis-timeline `editable.remove: true` gestisce il prompt nativo, callback chiama DELETE.
- **Doppio click su area vuota**: apre modal "Nuovo booking" pre-popolato (era click in v3.4.13.1, andava in conflitto con drag pan). Click singolo su area vuota = niente, drag pan funziona normalmente.
- **Hint UI**: riga sotto il label settimana con `Drag = sposta · Bordo = durata · Alt+drag = duplica · Canc = elimina · doppio-click su vuoto = nuovo`.

### Undo toast (5s)

- Stack `window._tlUndoStack` (max 20 elementi).
- Dopo update/delete/duplica: toast custom in basso al centro `Booking aggiornato | [Annulla] | 5s` con countdown live.
- Clic Annulla → ripristino: per `update` chiama PUT con valori precedenti, per `remove` chiama POST `/restore`, per `create` chiama DELETE.
- Errore ripristino → toast errore.

### CSS

- `.tl-conflict` rosso pieno con shadow ring durante drag.
- `.vis-drag-left` / `.vis-drag-right` (handle resize) leggermente più visibili su hover.
- `.vis-item.vis-editable { cursor: move; }`.

### File toccati

- `app/main.py` — version 3.4.14
- `app/routers/planning.py` — `update_booking`, `restore_booking`, fix list cancelled
- `app/templates/pages/planning.html` — `tlSnap`, `tlPushUndo/Show/Dismiss/Perform`, `tlHasConflict`, editable + onMoving + onMove + onRemove, doubleClick handler, Alt tracking, hint UI

### Smoke test

- `/planning/api/bookings/{id}` PUT con start/end → response OK con valori aggiornati
- DELETE poi GET → cancellato non più in lista
- POST restore → ok, ricompare in lista
- Conflict check escludendo self funziona
- HTML contiene `tlSnap`, `tlPushUndo`, `_tlAltDown`, `tl-conflict`

### Da testare sul Mac

- Drag booking su altra risorsa → riassegnato
- Drag con Alt premuto → originale resta + nuovo creato
- Resize bordo → durata cambia con snap
- Bordo rosso live durante drag su collisione
- Tasto Canc su selezione → cancella + toast Undo
- Click Undo entro 5s → ripristina
- Doppio click su area vuota → modal nuovo booking

### Prossimo step

- v3.4.15 — E2 — Click&drag su vuoto crea booking con ghost + tooltip durata + capacity heatmap (anticipata da E4)

---

## v3.4.13.1 — Hotfix: filtri + click-to-add timeline (29 aprile 2026)

### Bug fix: nascondi filtri rompeva il layout

Il refactor in v3.4.13 usava `grid-template-columns: 0 1fr` per collassare la sidebar. Il `1fr` con vis-timeline dentro non si comportava in modo prevedibile (probabilmente `min-content` del widget forzava overflow).

**Fix**: passato a `display: flex` con `flex: 1 1 auto; min-width: 0` sul main item. Più robusto: il flex item può ora effettivamente comprimersi sotto la sua content-width, e vis-timeline ha sempre la larghezza giusta sia con sidebar aperta che chiusa.

### Click su timeline → modal nuovo booking pre-popolato

Click su area vuota della Resource Timeline (background, group-label o asse) apre un modal "Nuovo booking" con:
- **Risorsa locked** (è la riga cliccata)
- **Inizio** = ora cliccata, arrotondata all'ora (minuti=0)
- **Fine** = inizio + 1h (default editabile)
- **Tipo** dropdown (project / internal_*)
- **Job** dropdown (visibile solo se kind=project, popolato da `jobs` template-side)
- **Lavorazione** dropdown opzionale (popolato dinamicamente da `GET /jobs/api/{job_id}` quando il job viene scelto)
- **Note** libere

Submit → `POST /planning/api/bookings` (endpoint esistente, validazione conflitti già lì) → toast success → refresh timeline.

### File toccati

- `app/main.py` — version 3.4.13.1
- `app/templates/pages/planning.html` — refactor pl-shell a flex, modal `#modal-tl-booking`, handlers `tlbOpen/tlbOnKindChange/tlbOnJobChange/tlbSubmit`, listener `click` su `tlInstance`

### Smoke

- `/planning/?view=timeline` 200, contiene `pl-main`, `min-width: 0`, `modal-tl-booking`, `tlbOpen`

### Da verificare sul Mac

- Click su area vuota di una riga risorsa apre il modal
- Inizio = ora cliccata arrotondata
- Cambio kind nasconde job/lavorazione
- Selezione job popola lavorazione
- Submit crea booking + appare in timeline

---

## v3.4.13 — Pulizia UX hub Pianificazione (29 aprile 2026)

Iterazione di rifinitura su `/planning/` dopo feedback uso reale della Resource Timeline.

### Timeline risorse — controlli più chiari

- **Tasto "Oggi"**: ora la finestra parte da OGGI (oggi → fine periodo selezionato). Non centra più la settimana corrente.
- **Selettore data + bottone "Vai a"**: input `<date>` per saltare a una data precisa. La finestra si estende per N giorni dopo quella data secondo lo zoom corrente (1/7/30/90).
- **Etichetta sopra la timeline**: `Settimana N — Mese Anno` calcolata sul punto medio della finestra. ISO week numbering.
- **Linea "ora"** più visibile (arancio `#fb923c`, 2px).

### Timeline — visualizzazione risorse più curata

- **Zebra rows** alternate (sfondo `rgba(255,255,255,.015)`) sia nelle label sia nel foreground.
- **Reparto padre** = grassetto, uppercase, color indaco `#6272f5` con sfondo accent.
- **Risorsa figlia** = padding-left 18px per gerarchia chiara, peso normale.
- **Hover row** highlight indaco.
- Items con border-radius 4px e ombra sottile, padding interno.

### Filtri collassabili

- Bottone "Nascondi filtri / Mostra filtri" sopra le tab. Stato persistito in `localStorage['pl-filters-collapsed']`.
- Sidebar collassa a `0` con grid-template-columns animato (transizione 180ms). Main area si espande full-width.
- **Badge contatore** sul bottone toggle: numero di filtri attivi visibile anche a sidebar chiusa.
- Su collapse/expand, vis-timeline `redraw()` e FullCalendar `updateSize()` per riadattarsi.

### Pulizia ridondanze

- **Vista Trimestre rimossa** dall'hub (poco utile coi filtri trasversali, copre già il mese × 3 mesi). Codice + CSS + JS rimossi. View parameter `trimester` cade su `jobs` default.
- **Voce sidebar "Calendario" rimossa** (`base.html`, `settings.html` config). Calendario ora accessibile solo dentro `/planning/?view=calendar`. Redirect `/planning/calendar` mantenuto per backward compat.
- Template `pages/calendar.html` legacy eliminato (dead code, nessun router lo serviva più).
- Link "Vai al calendario" della dashboard puntano ora a `/planning/?view=calendar`.

### File toccati

- `app/main.py` — version 3.4.13
- `app/routers/planning.py` — `VALID_VIEWS` senza `trimester`
- `app/templates/base.html` — rimossa voce sidebar Calendario
- `app/templates/pages/dashboard.html` — link al calendario aggiornato
- `app/templates/pages/settings.html` — rimosso `calendar` da `NAV_ITEMS_DEF`
- `app/templates/pages/planning.html` — toggle filtri, controlli timeline (Oggi/Vai-a/label), zebra+radius+hover, drop renderTrimester
- `app/templates/pages/calendar.html` — eliminato

### Smoke test

- `/health` 200 v3.4.13
- `/planning/?view=timeline` 200, contiene `pl-toggle-filters`, `tl-week-label`, `tl-goto-date`, `isoWeekNum`, `filters-collapsed`
- `/planning/calendar` 302 → redirect compat
- Nessun riferimento `trimester` residuo nell'HTML

### Prossimi step

- v3.4.14 — Booking editabili (drag/resize/delete + PUT API)
- v3.4.15 — Overlay prenotato vs effettivo + funzione "adeguamento" + report delta per producer

---

## v3.4.12 — Resource Timeline (vis-timeline) (29 aprile 2026)

Sesta vista dell'hub `/planning/`: **🧭 Timeline risorse** basata su vis-timeline 7.7.3 (CSS+JS già caricati dal v3.4.11).

### Cosa fa

- **Righe verticali** = risorse, raggruppate per **reparto** (nested groups, padre = nome reparto in grassetto, figli = risorse). Risorse senza reparto in gruppo "Senza reparto".
- **Tempo orizzontale** con zoom **Giorno / Settimana / Mese / Trimestre** (default settimana corrente, lunedì → domenica).
- Bottoni **◀ / Oggi / ▶** per spostarsi avanti-indietro di una finestra alla volta.
- Etichetta range visibile in alto a destra (es. `28 apr 2026 → 5 mag 2026`).

### Dati e filtri

- Riusa endpoint `GET /planning/api/bookings` (già supporta tutti i 9 filtri trasversali). Zero nuovi endpoint server-side.
- Filtri client-side anche sui groups: filtro **reparto** nasconde gli altri reparti, filtro **risorsa** mostra solo quella riga.
- Items vis-timeline: id `b{booking_id}`, group = `resource_id`, colore = `resource.color`, classe `kind-internal` (grigio) per booking interni (manutenzione/R&D/formazione).
- Tooltip nativo vis-timeline su hover, click su item → toast con titolo + range orario formattato.

### Tema dark

- Override CSS coerenti con palette indaco MediaFlow (`#6272f5`): bordi `var(--border)`, sfondo `var(--bg-elev)`, testo `var(--text)`. Item interni colore `#6b7280` (grigio neutro).

### File toccati

- `app/routers/planning.py` — `VALID_VIEWS` esteso con `"timeline"`
- `app/templates/pages/planning.html` — tab #6, container `#tl-host`, barra zoom/nav, seed JSON `RESOURCES_SEED`/`DEPARTMENTS_SEED`, ~150 righe JS (`renderTimeline`, `tlBuildGroups`, `tlBookingToItem`, `tlWindowFor`, `tlMove`, `tlUpdateRangeLabel`)

### Smoke test

- `/health` 200 v3.4.12
- `/planning/?view=timeline` 200, HTML contiene markup atteso e seed JSON ben formato

### Prossimi step

- v3.4.12.1 — **Kanban per stato job** (SortableJS già in uso)
- v3.4.12.2 — **Gantt per job** dentro `/jobs/{id}` (Frappe Gantt MIT)

---

## v3.4.11 — Hub Pianificazione con 5 viste + filtri trasversali (28 aprile 2026)

`/planning/` diventa un hub con **5 viste** selezionabili da tab e **9 filtri trasversali** applicabili a tutte. Architettura C: una sola entry sidebar, switcher in topbar dell'area main. URL-state (`?view=…&filtro=…`) bookmarkable.

Risponde alla richiesta di flessibilità nelle visualizzazioni del calendario e di poter vedere fino al trimestre.

### Viste implementate (parte 1/2 — top 6 split)

1. **📋 Tabella** — la vecchia lista job, ora filtrata server-side via API
2. **📅 Calendario** — FullCalendar timeGridWeek/dayGridMonth/timeGridDay (era `/planning/calendar`, ora hostato qui)
3. **🗓️ Trimestre** — `multiMonthYear` con `multiMonthMaxColumns: 3`, mostra 3 mesi affiancati
4. **📑 Agenda** — lista cronologica raggruppata per giorno, con badge sorgente (Booking / Timbratura)
5. **✓ Le mie attività** — filtrata sulla resource collegata al `current_user`. Card con label "In ritardo" / "Oggi" / "[giorno]" colorate

Top 6 priorità — viste rinviate a v3.4.12: **Resource Timeline (vis-timeline)**, **Kanban stato job**, **Gantt per job**.

### Filtri trasversali (sidebar fissa)

9 filtri applicati su **tutte** le viste live, server-side:
- search testuale (`q` su code/title)
- reparto (`department_id` — su jobs filtra via cost_lines, su booking via resource)
- cliente (`client_id`)
- progetto (`project_id`)
- job (`job_id`)
- risorsa (`resource_id`)
- stato job (`status`)
- tipo booking (`kind` — project / internal_*)
- periodo da/a (`from_date` / `to_date`)

Ogni filtro è riflesso nella query string → URL bookmarkable. Pulsante "Reset filtri" pulisce tutti.

### Backend

`/planning/api/jobs` esteso: `project_id`, `department_id` (subquery EXISTS via JobCostLine.price_item.department), `q` (LIKE su code/title), `from_date`/`to_date`. Response include `client_id`, `project_id`, `project_code`.

`/planning/api/bookings` esteso: `kind`, `client_id` (join Job), `project_id` (join Job), `department_id` (join Resource), `status`.

`/hr/api/punches` esteso: `client_id`, `project_id`, `department_id` (join analoghi).

### Backward-compat

`/planning/calendar` redirige 302 → `/planning/?view=calendar`. Vecchio template `pages/calendar.html` resta on-disk ma non più routato (rimovibile in futuro).

### Dipendenze

`vis-timeline@7.7.3` caricato via CDN nel template (preparazione v3.4.12 — Resource Timeline). FullCalendar 6.1.11 già caricato include `multiMonth` plugin in core.

### Smoke test E2E

- AST OK
- HTTP 200 su tutte le 5 viste: `?view=jobs|calendar|trimester|agenda|todo`
- `/planning/calendar` → 302 → 200 (redirect)
- Filtri API: `?status=approved` → 1 job, `?client_id=1` → 2 job, `?q=mare` → match Mare Nostrum, `?kind=project` → 7 booking

### File toccati

- `app/main.py` — bump 3.4.10 → 3.4.11
- `app/routers/planning.py` — `/` riscritto come hub con `?view=`, filtri estesi su `/api/jobs` e `/api/bookings`, `_resolve_current_user` aggiunto, `/calendar` → redirect
- `app/routers/hr.py` — `/api/punches` esteso con `client_id`/`project_id`/`department_id`
- `app/templates/pages/planning.html` — riscritto come hub con sidebar filtri + 5 viste tab + URL-state JS

### Limitazioni note

- "Le mie attività" è vuota se l'utente loggato non ha `Resource.user_id` collegato → mostra messaggio guida
- Il `/planning/api/jobs` filtro `from_date`/`to_date` è permissivo (job con date NULL passano sempre): è il comportamento desiderato per non perdere job senza scadenza
- Il vecchio `pages/calendar.html` resta on-disk; rimovibile dopo verifica sul Mac

---

## v3.4.10 — Booking legati a lavorazione + booking interni (28 aprile 2026)

Terzo step del re-design del flusso operativo. Il calendario diventa granulare: pianifico "Sara · Color HDR · Mare Nostrum" invece di "Sara · Mare Nostrum". Aggregazione ore pianificate/lavorate **per singola lavorazione**, non più solo a livello job.

Inoltre apre la categoria "booking interni" (manutenzione, R&D, formazione): ore senza job, generano costo senza profitto, traceabili nel cost report interno.

### Modello

**`BookingKind`** enum nuovo:
- `project` (default, comportamento storico): job_id richiesto, job_cost_line_id opzionale
- `internal_maintenance` / `internal_research` / `internal_training`: senza job, senza lavorazione

**`Booking`**:
- `kind: BookingKind` default `project`
- `job_cost_line_id: int?` FK opzionale a `job_cost_lines.id` (indicizzato): pianifica una lavorazione specifica
- `job_id` ora **nullable** (era NOT NULL): richiede recreate-table su SQLite
- Relationship `Booking.cost_line`

**`TimePunch`**:
- `job_cost_line_id: int?` FK opzionale: consuntiva ore reali contro il monte ore di una specifica lavorazione (calcolo extra per riga)
- Relationship `TimePunch.cost_line`

### Migrazione

`scripts/migrate_booking_cost_line_kind.py` (idempotente): 4 step distinti
1. ALTER ADD `bookings.kind TEXT DEFAULT 'project'`
2. ALTER ADD `bookings.job_cost_line_id INTEGER NULL`
3. ALTER ADD `time_punches.job_cost_line_id INTEGER NULL`
4. **Recreate-table dance** per rilassare `bookings.job_id` da NOT NULL → NULL (SQLite non supporta ALTER COLUMN per nullabilità). Disabilita FK durante, ricrea schema, copia dati con intersezione colonne, ricrea indici.

Voce **[E]/[e]** in `strumenti.bat` / `strumenti.sh`.

### Router /planning

`POST /api/bookings`: nuova firma con validazione coerenza:
- `kind=project`: `job_id` obbligatorio (errore 400 altrimenti); `job_cost_line_id` deve appartenere al job (errore 400 altrimenti)
- `kind=internal_*`: `job_id` e `job_cost_line_id` forzati a NULL
- Helper `_booking_title(b)` produce titolo umano: "Job · Lavorazione · Risorsa" per `project`, "[Tipo] · Risorsa" per interni

`GET /api/bookings`: response include ora `kind`, `job_cost_line_id`, `cost_line_description` in `extendedProps`. Source marker `"source": "booking"`.

### Router /hr

`POST/PUT /api/punches` accetta `job_cost_line_id`. Validazione: la lavorazione deve esistere, e se `job_id` è valorizzato deve appartenere allo stesso job. Se non c'è `job_id` ma c'è `job_cost_line_id`, il `job_id` viene dedotto dalla riga.

Sentinel `clear_cost_line=true` per cancellare l'associazione su PUT (analogo a `clear_end`/`clear_job` esistenti).

### Router /jobs (aggregazione per riga)

- `_aggregate_planned_hours(db, job_id, cost_line_id=None)` ora opzionalmente filtra su riga
- `_aggregate_actual_hours(db, job_id, cost_line_id=None)` idem
- Nuovo `_aggregate_unassigned(db, job_id)`: ore registrate sul job ma con `job_cost_line_id IS NULL` — esposte come `unassigned_planned_hours` / `unassigned_actual_hours` nei totali, mostrate come avviso UI ("⚠ Da assegnare manualmente")
- `_line_dict(line, db=...)` ora include `planned_hours` e `actual_hours` per riga

### UI /jobs/{id}

Tabella lavorazioni: 2 colonne nuove tra "Quotate" e "Extra":
- **Pian.** (ore pianificate via Booking legati a questa riga)
- **Lavor.** (ore lavorate via TimePunch legati a questa riga)

Avviso sotto la tabella se ci sono ore non assegnate a una lavorazione specifica (backward compat per booking/punch creati prima di v3.4.10).

### Smoke test E2E

- AST OK su tutti i file modificati
- T1 GET payload con `planned_hours`/`actual_hours` per riga (default 0 prima di test)
- T2 POST `kind=project` + `job_cost_line_id=15` → ok, booking #7
- T3 POST `kind=internal_maintenance` senza job → ok, `job_id=null`, `job_cost_line_id=null`
- T4 POST `kind=project` senza `job_id` → 400 "Per kind=project serve job_id"
- T5 POST `kind=project` con cost_line di altro job → 400 "non appartiene al job"
- T6 GET dopo T2: line 15 `planned_hours=4`, `unassigned=0`
- T7 POST punch su line 15 + 5h → response include `cost_line_description`
- T8 GET dopo T7: line 15 `planned=4 actual=5`

### File toccati

- `app/main.py` — bump 3.4.9.1 → 3.4.10
- `app/models/models.py` — `BookingKind` enum, `Booking.kind/job_cost_line_id/cost_line`, `Booking.job_id` nullable, `TimePunch.job_cost_line_id/cost_line`
- `app/models/__init__.py` — export `BookingKind`
- `app/routers/planning.py` — POST/GET bookings con validazione kind, helper `_booking_title`
- `app/routers/hr.py` — POST/PUT punches con `job_cost_line_id` + sentinel `clear_cost_line`
- `app/routers/jobs.py` — aggregazione per riga + unassigned, `_line_dict` con planned/actual_hours
- `app/templates/pages/job_detail.html` — colonne Pian./Lavor., avviso unassigned
- `scripts/migrate_booking_cost_line_kind.py` — nuovo (4 step idempotenti + SQLite recreate-table)
- `strumenti.bat` / `strumenti.sh` — voce E

### Limitazioni note (deferite a v3.4.11)

- UI calendario non ha ancora modal aggiornato per scegliere `kind` o `job_cost_line_id` (Matteo: "calendario è davvero brutto, ci lavoriamo poi"). Per ora la creazione di booking interni o legati a lavorazione passa solo da API. Il calendario li **mostra** correttamente con il titolo distinto, ma il modal "+ Booking" mostra il vecchio form con `job_id` obbligatorio.
- L'aggregazione cost-line specifica funziona solo per booking/punch creati con `job_cost_line_id`. I record storici senza il riferimento appaiono nel totale "unassigned" (avviso UI).

---

## v3.4.9.1 — Hotfix: stesso bug `j.budget` in finance service (28 aprile 2026)

Stesso pattern del bug v3.4.8 ma in un altro file. Il modal "dettaglio job" in `/planning` fa due chiamate in parallelo: `/planning/api/jobs/{id}` (fixato in v3.4.8) e `/finance/api/report/job/{id}` (questo). Il secondo restituiva 500 → modal vuoto/rotto → bottone "→ Vai al dettaglio job" mai visibile.

`app/services/finance.py:46,51,59` mappava `job.budget` ma il modello ha `budget_quoted`. Tre occorrenze sostituite tutte insieme.

Fix verificato: `GET /finance/api/report/job/1` ora 200 con `{"budget":64917.0,"margin":61917.0,"margin_pct":95.4,...}`.

---

## v3.4.9 — Lavorazioni come prima class + extra (28 aprile 2026)

Secondo step del re-design del flusso operativo. Le `JobCostLine` (lavorazioni) ora hanno una vita propria nella pagina dettaglio job: ore quotate, lavorate, extra calcolate per riga, con possibilità di aggiungere lavorazioni "extra puro" post-approvazione (caso "il cliente chiede un upres in più").

### Modello

- `JobCostLine.is_extra: bool = False` — marca lavorazioni aggiunte dopo l'approvazione della quote (`quote_line_id` solitamente NULL). Distinto dallo "sforamento monte ore" su lavorazione standard, che si calcola come `quantity_actual > quantity_quoted`.
- Migrazione idempotente `scripts/migrate_jobcostline_extra.py`, voce **[D]/[d]** in `strumenti.bat` / `strumenti.sh`.

### Router /jobs (nuovo)

- `GET /jobs/{id}` — pagina dettaglio
- `GET /jobs/api/{id}` — payload completo con lavorazioni + aggregazioni:
  - `quoted_hours_lines` somma `quantity_quoted` (escluse extra)
  - `actual_hours_lines` somma `quantity_actual` (tutte)
  - `extra_hours_lines` somma per riga: `quantity_actual` se `is_extra`, oppure `max(0, actual - quoted)` per riga standard sforata
  - `planned_hours_calendar` somma durate Booking attivi sul job
  - `actual_hours_punch` somma durate TimePunch chiusi sul job
- `POST /jobs/api/{id}/cost-lines` — crea lavorazione (default `is_extra=true`)
- `PUT /jobs/api/{id}/cost-lines/{line_id}` — modifica con ricalcolo automatico totali
- `DELETE /jobs/api/{id}/cost-lines/{line_id}` — solo se `is_extra=true`. Le lavorazioni ereditate dalla quote possono essere solo modificate (o marcate non-fatturabili)

Helper interni: `_aggregate_planned_hours`, `_aggregate_actual_hours`, `_line_dict`, `_job_payload`.

### Pagina /jobs/{id}

- Header con meta (cliente, progetto, quote, stato, budget quotato)
- 4 cards riepilogo ore: Quotate (indaco), Pianificate calendario (verde menta), Lavorate timbrature (lime), Extra (arancione, sfondo evidenziato)
- Tabella lavorazioni con colonne: descrizione + badge `EXTRA` se applicabile, unità, € unitario, ore quotate (con barra progresso `actual/quoted` arancione se sfora 100%), ore lavorate (in arancione se > quotate), ore extra, totale previsto
- Click riga → modal modifica (per le ereditate, `quantity_quoted` non editabile; bottone elimina visibile solo per extra)
- Bottone topbar "+ Aggiungi lavorazione extra" → modal con descrizione, qty, unit, prezzo, note, fatturabile

### Link da /planning

Modal dettaglio job ora ha bottone "→ Vai al dettaglio job (lavorazioni e ore)" che linka a `/jobs/{id}`.

### Smoke test E2E

- AST OK su tutti i file modificati
- T1 GET `/jobs/api/3` ritorna 4 lavorazioni Gomorra (Conforming, Color HDR, QC, Deliverables) con `quoted_hours_lines=72`
- T2 POST extra "Upres 2K → 4K episodio 5" 8h × €120: id 23, `is_extra=true`, `quoted=0`, `total_expected=960`
- T3 PUT line 15 (Conforming, quoted 30h) con `actual=35` → `extra=5` calcolato, `total_expected=8750` (35×250)
- T4 totali job aggiornati: `actual_hours_lines=35`, `extra_hours_lines=5`
- T5 DELETE riga non-extra (Color HDR) → 400 con messaggio "Le lavorazioni ereditate non possono essere eliminate"
- T6 DELETE riga extra (id 23) → ok
- T7 GET `/jobs/3` HTML → 200

### File toccati

- `app/main.py` — bump 3.4.8.1 → 3.4.9, registrato router `jobs`
- `app/models/models.py` — `JobCostLine.is_extra`
- `app/routers/jobs.py` — nuovo, ~250 righe
- `app/templates/pages/job_detail.html` — nuovo
- `app/templates/pages/planning.html` — link "→ Vai al dettaglio job"
- `scripts/migrate_jobcostline_extra.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce D

### Limitazioni note (deferite a v3.4.10)

- Ore pianificate/lavorate sono aggregate **al livello job**, non per singola lavorazione. Per granularità per-lavorazione serve `Booking.job_cost_line_id` (FK opzionale, in v3.4.10) e `TimePunch.job_cost_line_id` (analogo).
- La modifica di una quote dopo l'approvazione non si propaga al job: serve una "sync" esplicita (UI in v3.4.10 o v3.4.11).

---

## v3.4.8.1 — Hotfix: STATUS_LABEL redeclaration + FullCalendar CSS 404 (28 aprile 2026)

Due bug front-end che bloccavano `/planning` e generavano warning console: la pagina mostrava "nulla" anche dopo il fix v3.4.8 perché lo script JS falliva alla prima riga di parsing.

### Bug 1 — `SyntaxError: redeclaration of const STATUS_LABEL`

`/static/js/global.js` dichiara `const STATUS_LABEL` come globale (caricato in `base.html`). Le pagine `planning.html` e `calendar.html` lo ri-dichiaravano localmente con `const`, causando SyntaxError → l'intero script di pagina non veniva mai parsato → `loadJobs()` mai chiamata → tabella job vuota.

Fix: rimosse le ridichiarazioni locali. Il `STATUS_LABEL` globale ha già tutti i valori necessari (`tentative`, `confirmed`, `cancelled`, `completed`, ecc.).

### Bug 2 — FullCalendar CSS 404 → MIME type block

`base.html` linkava `https://cdnjs.cloudflare.com/ajax/libs/fullcalendar/6.1.11/main.min.css`. Quel file non esiste in FullCalendar 6.x: il CDN restituiva una pagina HTML 404 con `Content-Type: text/html`, e il browser bloccava il caricamento per `X-Content-Type-Options: nosniff` su tutte le pagine. In v6 lo stylesheet è incorporato in `index.global.min.js`, niente CSS separato.

Fix: rimosso il `<link rel="stylesheet">` da `base.html`.

### File toccati

- `app/main.py` — bump 3.4.8 → 3.4.8.1
- `app/templates/base.html` — rimosso link `fullcalendar/main.min.css`
- `app/templates/pages/planning.html` — rimossa redeclaration `STATUS_LABEL`
- `app/templates/pages/calendar.html` — rimossa redeclaration `STATUS_LABEL`

---

## v3.4.8 — Quote → Job automatico + bug "non vedo nessun job" (28 aprile 2026)

Primo passo del re-design del flusso operativo discusso con Matteo. Cambia la natura del Job: non è più un'entità da creare a mano, è la materializzazione operativa automatica di una quote approvata. Eredita identità dal progetto.

### Bug fix critico

`/planning/api/jobs` restituiva 500 (`AttributeError: 'Job' object has no attribute 'budget'`). Il codice mappava `j.budget` ma il modello ha `budget_quoted`. Effetto: l'app non mostrava nessun job, anche se in DB c'erano. Una riga di fix in `routers/planning.py:81`.

### Auto-promote Quote → Job

Riscritto `PUT /quotes/api/{id}/status` con side-effect deterministici:

- **draft|sent → approved**: crea il `Job` collegato + `JobCostLine` da ogni `QuoteLine`. Idempotente: se il job esiste già lo ritorna così com'è. Se esiste ma è `cancelled` (riapprovazione dopo rollback), lo ri-attiva senza duplicare lavorazioni.
- **approved → altro**: cancella il job (status=`cancelled`, preserva storico) se non ha attività operative; **blocca con 400** se ci sono booking non-cancelled o TimePunch sul job.
- Codice job auto-generato `{project.code}-J{N}` (es. `MARE-J1`, `MARE-J2`). Decisione: leggibile + chiaro a colpo d'occhio quale progetto + nessun registro globale di numerazione.
- Titolo job ereditato da `project.title` (non da `quote.title` come prima — il riferimento canonico è il progetto).
- Helper `_create_job_from_quote()` + `_job_has_activity()` + `_next_job_code()` esposti per riuso (anche AI capability futura).

Risposta API arricchita: `{"id", "status", "job_created": {id, code, title, lines_count}}` su approve, `{..., "job_cancelled_id"}` su rollback.

### Nuovo stato `JobStatus.cancelled`

Aggiunto valore `cancelled` all'enum `JobStatus`. SQLAlchemy `SAEnum` su SQLite non crea constraint a livello DB → niente migrazione struttura necessaria. Per Postgres in futuro servirà un ALTER TYPE.

### Rimossa creazione job manuale

- Bottone "+ Nuovo job" rimosso da `/planning` (sostituito da link "→ Vai a quotazioni")
- Modal "Nuovo job" rimosso, funzione `createJob()` JS rimossa
- Bottone "▶ Converti in Job" nell'editor quote sostituito con "✓ Approva quote → Job" che fa direttamente `PUT /status?status=approved` con conferma → toast con codice job → redirect `/planning`
- Modal "modal-convert" rimosso, funzione `convertToJob()` rimpiazzata da `approveAndCreateJob()`
- Endpoint `POST /quotes/api/{id}/convert-to-job` marcato deprecated, ora ignora `job_code`/`start_date`/`end_date` e delega a `_create_job_from_quote`
- Endpoint `POST /planning/api/jobs` marcato deprecated (mantenuto per scenari import/migrazione legacy)

### Smoke test E2E

- AST OK su `quotes.py`, `planning.py`, `models.py`
- T1 — `/planning/api/jobs` ora 200, ritorna 4 job esistenti con `budget` corretto
- T2 — PUT quote 2 (draft, project_code="sada") → approved: crea Job 5 `sada-J1` con `title="awdad"` (da project.title), 2 lavorazioni, `budget=2180.8`
- T3 — PUT quote 2 → draft: Job 5 → cancelled (nessuna attività)
- T4 — PUT quote 2 → approved (di nuovo): Job 5 ri-attivato (no duplicazione)
- T5 — POST booking su job 5 + PUT quote 2 → draft: 400 con messaggio "il job sada-J1 ha attività…"

### File toccati

- `app/main.py` — bump 3.4.7 → 3.4.8 (FastAPI + /health hardcoded)
- `app/models/models.py` — `JobStatus.cancelled`
- `app/routers/quotes.py` — `_next_job_code` + `_create_job_from_quote` + `_job_has_activity` helper, `update_quote_status` riscritto, `convert_to_job` deprecato
- `app/routers/planning.py` — fix bug budget, `POST /api/jobs` deprecated
- `app/templates/pages/quotes.html` — bottone "Approva → Job" + modal-convert rimosso + `approveAndCreateJob()`
- `app/templates/pages/planning.html` — modal nuovo job rimosso + bottone topbar sostituito + `createJob()` JS rimossa

### Decisioni non prese (deferite a v3.4.9+)

- Modifica quote dopo approvazione: oggi NON propaga al job. Serve un meccanismo "ricarica monte ore" o richiesta esplicita di ri-sincronizzazione (in v3.4.9 con la pagina dettaglio job)
- `JobCostLine.is_extra` flag per nuove lavorazioni post-quote (v3.4.9)
- `Booking.job_cost_line_id` FK opzionale per legare booking a lavorazione specifica (v3.4.10)
- `BookingKind` per booking interni senza job (manutenzione/training/research) (v3.4.10)

---

## v3.4.7 — Sezione HR e timbrature (28 aprile 2026)

Apre il dominio amministrativo/HR per la rendicontazione delle ore di lavoro. Tutte le risorse umane (interne + freelance) rendicontano qui — i freelance senza login possono essere "timbrati" da un manager.

Step "timbrature/idle" del cantiere calendario, scelta architetturale: **Opzione 2 — modello `TimePunch` separato**. Booking resta dominio della pianificazione (intenzione: chi sarà su quale job e quando), TimePunch è il consuntivo di presenza (chi è stato a lavoro e per quanto). Niente over-loading del modello Booking.

### Modello

- `TimePunch(tenant_id, resource_id, job_id?, start_datetime, end_datetime?, kind, notes, created_by_user_id?)`
- `end_datetime` nullable = "in corso" (ingresso senza ancora uscita)
- `job_id` nullable = ore non legate a progetto specifico
- `created_by_user_id` nullable = chi ha registrato (manager/HR per freelance senza login)
- Enum `PunchKind`: `shift` (turno, con o senza job), `idle` (presente non allocato), `leave` (ferie/permesso), `sick` (malattia), `break_` (pausa), `overtime` (straordinario)
- Relationship: `Resource.time_punches` (back_populates)

### Router `/hr`

- `GET /hr` — pagina HR: filtri (risorsa, periodo, tipo) + tabella + footer totali
- `GET /hr/api/punches` con filtri `resource_id`, `job_id`, `kind`, `from_date`, `to_date`, `format=json|fullcalendar`
- `POST /hr/api/punches` — crea (validazione: risorsa esistente + tipo person, end > start, job esiste se presente)
- `PUT /hr/api/punches/{id}` — modifica (sentinel `clear_end=true` / `clear_job=true` per cancellare; `Form(None)` non distinguibile da assente)
- `DELETE /hr/api/punches/{id}` — elimina (hard delete, non soft — le timbrature errate vanno tolte)
- `GET /hr/api/summary` — totali ore per kind nel periodo (esclude le in-progress); ritorna `totals`, `grand_total`, `labels`, `colors`

### UI sezione HR `/hr`

- Filtri: dropdown risorse persona, range date (con shortcut "settimana corrente" / "mese corrente"), kind, reset
- Cards totali in alto con accent-color per kind + card grand-total indaco
- Tabella: data, risorsa (con dot colore), inizio/fine (in corso → tag indaco), durata (h), kind (badge col bordo colore kind), job (codice + titolo), note
- Click riga → modal modifica con bottone Elimina; "+ Nuova timbratura" in topbar
- Modal: risorsa, kind, datetime-local start/end (vuoto = in corso), job opzionale, note

### Integrazione calendario

- `/planning/calendar` ora ha **2 eventSources** (FullCalendar): bookings + punches (`format=fullcalendar`)
- Legenda riorganizzata: sezione "Sorgenti" (toggle bookings/punches) + sezione "Risorse" (toggle per risorsa)
- Filtri ora **funzionanti server-side via render-time hide** (`eventDidMount` setProp display:none) — prima il filtro risorsa era no-op
- Eventi punch hanno colore per kind (idle grigio, leave lavanda, sick rosso, break giallo, overtime arancione, shift = colore risorsa)
- Click su punch mostra durata + "in corso" se end null

### Sidebar

Voce **🕐 Ore lavoro** sotto Operativo (dopo Assegnazioni, prima della sezione Preventivi).

### Migrazione

- `scripts/migrate_time_punches.py` — crea tabella `time_punches` via `Base.metadata.create_all` (idempotente: skip se già esiste)
- Voce **[C]/[c]** in `strumenti.bat` / `strumenti.sh`

### Smoke test E2E

- AST OK su `models.py`, `routers/hr.py`, `main.py`, migration script
- Migration: tabella creata, re-run idempotente
- `/health` 3.4.7, `/hr/` 200, `/hr/api/punches` 200, `/hr/api/summary` 200, `/planning/calendar` 200
- POST punch chiusa: durata 9.00h calcolata, kind=shift colore risorsa
- POST punch in-progress (end null): duration_h null, summary lo esclude correttamente
- PUT chiude la in-progress: end aggiornato, duration ricalcolata 1.5h
- DELETE: hard delete, lista finale vuota
- Format `fullcalendar`: title `risorsa · kind`, colore per kind, extendedProps con `source=punch`

### File toccati

- `app/main.py` — bump 3.4.6 → 3.4.7, registrazione router `hr`
- `app/models/models.py` — `PunchKind` enum, `TimePunch` class, `Resource.time_punches` relationship
- `app/models/__init__.py` — export `TimePunch`, `PunchKind`
- `app/routers/hr.py` — nuovo, ~280 righe
- `app/templates/pages/hr.html` — nuovo
- `app/templates/pages/calendar.html` — secondo eventSource, legenda sorgenti, filtro client-side via `eventDidMount`
- `app/templates/base.html` — voce sidebar 🕐
- `scripts/migrate_time_punches.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce C

### Promemoria backlog

- **Aggregazioni HR avanzate** (rinviate): report ore lavorate per progetto e per risorsa nel mese, costo orario × ore in cost report, esportazione CSV/PDF cedolino, integrazione con `JobCostLine` consuntivo
- **Auto-timbratura per utenti con login**: bottone "🟢 Inizio turno" / "🔴 Fine turno" nella topbar per chi è collegato (oggi: solo creazione manuale via modal)
- **Mancano gli orari standard** per tipo risorsa (full-time / part-time / freelance senza vincolo) per calcolare straordinari automaticamente

---

## v3.4.6 — Booking multi-tenant (28 aprile 2026)

Fix di coerenza con la convenzione Fase 1-bis: il modello `Booking` era l'unica entità di business senza `tenant_id`. Tutti i restanti modelli (Resource, PriceItem, Client, Project, Department…) lo avevano già da v3.0.

Primo passo del cantiere "calendario e pianificazione" — propedeutico a tutto il resto (UX calendario, ferie/indisponibilità, riconciliazione assignment↔booking, capability AI, timbrature/idle).

### Modello

- `Booking.tenant_id` (FK `tenants.id`, default 1, indicizzato)
- Convenzione: ogni query nel router parte con `Booking.tenant_id == CURRENT_TENANT`

### Router `/planning`

- `CURRENT_TENANT = 1` in cima al file (pattern allineato a `resources.py` / `pricelist.py`)
- `GET /api/bookings` filtra per tenant
- `POST /api/bookings` imposta `tenant_id=CURRENT_TENANT` sul nuovo record + il check di conflitto risorsa è anch'esso tenant-scoped (in multi-tenant hard, due tenant possono avere booking sovrapposti senza falsi conflitti)
- `DELETE /api/bookings/{id}` filtra per tenant prima del soft-cancel

### Migrazione

- `scripts/migrate_booking_tenant.py` (idempotente): `ALTER TABLE bookings ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1`. Tutti i booking esistenti vengono backfillati a `tenant_id=1`.
- Voce **[B]/[b]** in `strumenti.bat` / `strumenti.sh`.

### Smoke test

- AST OK su `models.py`, `routers/planning.py`, script di migrazione
- Migrazione applicata sul DB locale: 5 booking esistenti backfillati a tenant 1
- Re-run idempotente (`tenant_id già presente`)
- `/health` 200 v3.4.6
- `/planning/calendar` 200, `/planning/api/bookings` 200 con i 5 booking seed visibili
- `POST /planning/api/bookings` validazione corretta (422 sui campi obbligatori mancanti)

### File toccati

- `app/main.py` — bump 3.4.5 → 3.4.6 (FastAPI version + `/health` hardcoded)
- `app/models/models.py` — `Booking.tenant_id`
- `app/routers/planning.py` — `CURRENT_TENANT` + filtri/set tenant
- `scripts/migrate_booking_tenant.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce B

---

## v3.4.5 — Modal "Aggiungi voce" ridisegnato (28 aprile 2026)

Il modal di selezione voce nella quotazione era confuso: form sempre visibile con i campi vuoti prima della scelta, sidebar piatta senza raggruppamento, risultati con metadata scarna e separatore "·" poco leggibile.

### Modal redesign

- **Sidebar categorie raggruppate per reparto**, con dot colorato nel colore reparto e label maiuscoletto. La voce attiva ha bordo sinistro nel colore reparto. "Tutte le voci" e "+ voce libera" stanno in cima come scorciatoie sticky.
- **Risultati listino più leggibili**: card con striscia colorata reparto a sinistra, nome + prezzo in cima, badge categoria (indaco) + badge reparto (nel colore reparto), descrizione e keyword sotto. Hover e selected hanno feedback visivo distinto.
- **Pannello selezione condizionale**: prima di scegliere si vede solo il messaggio _"Seleziona una voce dal listino, oppure crea voce libera"_. Dopo la scelta appare un header con nome + tag categoria/reparto + prezzo listino di riferimento, poi i campi qty/unità/prezzo/descrizione/dettaglio in una griglia 8-col.
- **Voce libera** richiamabile sia dalla sidebar (bottone tratteggiato) che dall'empty state che dal "no results" → riusa lo stesso pannello con etichetta `✏️ Voce libera (non in listino)`.
- **Conteggio risultati** in alto a destra (`X di Y voci` se troncato a 80, altrimenti totale). La sidebar conta voci sul filtro testo, indipendentemente dalla categoria attiva (così si vede dove "vivono" i match in altre categorie).
- Search input più grande (14px), modal a 1080px, layout flex column con altezze gestite (sidebar+lista 48vh, pannello selezione flex-shrink:0).

### File toccati

- `app/templates/pages/quotes.html` — sostituiti markup modal-add-line, blocco `<style>` dedicato, funzioni JS `openAddLine`, `renderAlSidebar`, `setAlCat`, `filterPricelist`, `pickPriceItem`. Aggiunte `clearSelection`, `enableFreeLine`, helper `alEscape` / `alMatchesText`.
- Nessuna modifica a `addLine()` (gli id `al-desc/-detail/-qty/-unit/-price/-price-item-id/-base-unit/-base-price` sono preservati) né alle API backend.

---

## v3.4.4 — AI search-first nel listino + scenario C (27 aprile 2026, sera tardi)

Risponde alla nota originale **#5** di Matteo e al bug **#6** (copilot non aggiunge righe a quote esistente). Tre cambi sostanziali al copilot AI.

### A. Voci listino nel context AI
`build_context()` ora include un blocco `VOCI LISTINO ATTIVE (id | name | category | unit | €list | keywords)` con tutte le voci attive (limite 200, oggi 75 voci × ~2KB = trascurabile sui token). Senza questo blocco il modello non aveva modo di sapere quali voci esistono → spiegava perché le righe AI venivano sempre messe come "voci libere" con `unit_price=0`. Il blocco viene rigenerato live ad ogni turno (nessuna cache, niente da invalidare).

### B. `propose_quote_line` esteso con `price_item_id`
Schema accetta nuovo campo opzionale `price_item_id` (numero PK voce listino). Quando passato:
- la riga viene legata al listino (`QuoteLine.price_item_id` valorizzato)
- `unit_price`, `unit`, `description` vengono ereditati dalla voce listino se non specificati esplicitamente dall'AI
- in v3.4.3 le righe AI erano sempre "voci libere" → ora possono essere "voci dal listino"

### C. Nuova capability `propose_new_item_and_line` (scenario C)
Quando l'utente conferma "non c'è in listino, creala", l'AI propone questa azione che in **singola transazione**:
1. Crea la `PriceItem` (richiede `category_name`, `name`, `unit`, `price_list`)
2. Crea la `QuoteLine` collegata (con `quantity` e prezzo del listino appena creato)

Una sola conferma utente, niente "doppio click" come scenario B. Categoria autocreata se nuova.

### D. System prompt: REGOLA SEARCH-FIRST
Nuova sezione esplicita prima di "FORMATO JSON OBBLIGATORIO". Cascata su 3 livelli per ogni richiesta di aggiunta voce a quote:

| Caso | Comportamento atteso AI |
|---|---|
| **1 match chiaro** in listino | `propose_quote_line` con `price_item_id` (basta `quantity`) |
| **2-4 match plausibili** | NON azione, risposta in **markdown numerato** che chiede quale scegliere |
| **0 match** | Markdown con due opzioni: (a) voce libera o (b) scenario C, e attesa risposta |
| **Voce esplicitamente nuova** | `propose_new_item_and_line` direttamente |

Esempio nel prompt: utente "5 giorni di Color HDR", listino ha `12 | Color HDR | Color | day | €1200` → AI propone `{"price_item_id": 12, "quantity": 5}`, e il backend completa con `unit_price=1200`, `unit="day"`, `description="Color HDR"`.

### E. UI copilot
- `actionTypeLabel` e `renderActionSummary` aggiornati per il nuovo type
- `summaryQuoteLine` ora mostra `✓ legata a voce listino #N` o `⚠ voce libera (non legata al listino)` per dare feedback visivo immediato
- Nuovo `summaryNewItemAndLine` con anteprima totale (`qty × price = subtotale`)

### Smoke test
- Sintassi Python OK, copilot.js 162/347 braces/parens matched, HTTP 200
- `/health` → 3.4.4 ✓
- 8 capability totali registrate (era 7)
- `build_context()` include 75 voci listino, ~2140 token totali (era ~600)
- Test E2E con prompt reali: rinviato a Matteo (richiede provider AI attivo). Suggeriti:
  - `"aggiungi a Q-2026-001 due giorni di Color HDR"` → match chiaro, `propose_quote_line` con `price_item_id`
  - `"aggiungi del color"` → match multipli, AI elenca opzioni in markdown
  - `"aggiungi a Q-2026-001 una nuova voce Foley editing, listino 350/giorno categoria Audio"` → `propose_new_item_and_line`

### Promemoria backlog
- Aggiornamento context al cambio listino: oggi è già live (rigenerato ad ogni turno). Se in futuro le voci listino superano ~500 e il context diventa pesante, valutare cache + invalidazione su create/update/delete `PriceItem`.

### File toccati
- `app/services/ai_assistant.py` — context esteso + REGOLA SEARCH-FIRST + nuovo handler + dispatch + schema in prompt
- `app/static/js/copilot.js` — label e renderer per `propose_new_item_and_line`, `summaryQuoteLine` riscritto con feedback listino
- `app/main.py` — bump 3.4.3 → 3.4.4

---

## v3.4.3 — Card copilot human-readable (27 aprile 2026, sera tardi)

Refactor UX delle card di proposta AI nel drawer copilot. Prima si vedeva solo il payload JSON crudo escapato, ora ogni `action_type` ha un renderer dedicato che mostra solo i campi rilevanti in formato leggibile, con un toggle `</> Mostra dati grezzi` per chi vuole vedere il JSON completo (utile per debug).

### Renderer per type
- **propose_client** → nome (bold) + forma giuridica · industry + città/paese + P.IVA + email
- **propose_project** → codice (bold) · titolo + cliente + minuti/material/fps
- **propose_project_metadata** → coppie `chiave: valore` per ogni campo passato
- **propose_quote** → numero · titolo · date/IVA + tabella mini con righe (descrizione, q.tà, unità, €), tronca dopo 8 righe con "+N altre"
- **propose_quote_line** → descrizione (bold) + quantità × prezzo + riferimenti (quote#, listino#, categoria override)
- **propose_price_item** → descrizione (bold) + categoria · unità + 3 livelli prezzo + keywords
- **web_search** → "Cerca: <query>"
- **fallback** → messaggio "Nessun renderer per questo tipo. Apri 'dati grezzi'."

### Toggle JSON
Bottone `</> Mostra dati grezzi` sotto la card; al click rivela un `<pre>` con il JSON completo della `data` (con scroll, max-height 200px). Stato chiuso di default.

### Stile
Box summary con bordo sinistro indaco e sfondo semi-trasparente (lo stesso accento del resto dell'app). Mini-tabelle con header maiuscoletto, valori monospace allineati a destra. Niente impatto sulle `applied/rejected/failed` card storiche: il summary si genera dal `data` salvato come al solito.

### File toccati
- `app/static/js/copilot.js` — `renderActionCard` riscritta, nuove `renderActionSummary` + 6 funzioni `summary*` + helper `fmtCur` + `copilotToggleJSON`
- `app/templates/components/copilot.html` — CSS per `.cp-action-summary`, `.cp-mini-table`, `.cp-debug-toggle`, `.cp-muted`
- `app/main.py` — bump 3.4.2 → 3.4.3

### Smoke test
- `/health` → 3.4.3 ✓
- copilot.js: 148 braces matched, 319 parens matched, HTTP 200 ✓
- `/quotes/`, `/assignments/` → 200 ✓
- Test E2E browser: rinviato a Matteo (richiede provider AI attivo per generare card)

---

## v3.4.2 — Quick wins copilot + categoria libera quote (27 aprile 2026, sera tardi)

Quattro micro-feature richieste in batch dopo il test del copilot.

### #21 + #22 — Textarea + a capo + stop thinking (copilot)
- Drawer copilot: input convertito da `<input>` a `<textarea>` auto-resize. Nuova convenzione tasti: **Enter = a capo**, **Ctrl/⌘+Enter = invia**.
- Bottone Invia diventa "✕ Stop" durante la generazione: click annulla la fetch lato client via `AbortController`. La generazione lato server (Ollama/Claude) prosegue fino a fine, ma il client non aspetta più la risposta — sufficiente per evitare sovraccarico richieste e UX bloccata.

### #23 — Categoria libera in quotazione (override per riga)
**Modello**: nuova colonna `quote_lines.category_override TEXT NULL`. Se valorizzata, prevale su `price_item.category` nei raggruppamenti (editor / PDF / CSV / XLSX). Permette di:
- spostare voci tra categorie senza cambiare la voce listino
- dare una categoria a "voci libere" (senza `price_item_id`)
- creare categorie ad hoc per la singola quotazione

**UI editor quote**: nuovo bottone 📁 sulla riga (vicino al ✕). Apre un prompt con elenco numerato di tutte le categorie note (dalle voci della quote + dal listino) + opzione "+ Nuova categoria…" + "0. Ripristina categoria del listino" se override attivo. Si può anche scrivere un nome libero. Niente layout cambiato: il bottone si infila accanto al ✕.

**Backend**:
- `POST /quotes/api/{id}/lines` accetta `category_override: Form(Optional[str])`
- `PUT /quotes/api/{id}/lines/{line_id}` idem; per **cancellare** un override usa il sentinel `__CLEAR__` (FastAPI con `Form(None)` parsa la stringa vuota come `None`, indistinguibile da "non passato")
- `GET /quotes/api/{id}` espone `category_override` nella response per ogni line
- helper `_line_category` centralizza la logica → editor JS, CSV, XLSX, PDF rispettano automaticamente l'override

**Migrazione**: `scripts/migrate_quote_category_override.py` (idempotente). Aggiunta voce **[9]** in `strumenti.bat`/`strumenti.sh` (la voce "uploads" si è spostata su `[A]` / `[a]`).

### #24 — Parser AI tollera commenti Python (`#`)
Già rilasciato in v3.4.1: `_strip_json_comments_and_trailing_commas` riconosce `// …`, `/* … */` E `# …` a fine riga, rispettando stringhe ed escape. Documentato qui per completezza del giro.

### Smoke test E2E (live)
- Migrazione applicata su `mediaflow.db` (colonna aggiunta)
- `PUT /lines/{id}` con `category_override="Color"` → riga 18 ora in gruppo "Color"
- `PUT` con sentinel `__CLEAR__` → override cancellato, riga torna in "Altro"
- `POST /lines` con `category_override="Servizi extra"` → nuovo gruppo creato
- `GET /quotes/api/3/export.csv` → tre gruppi distinti con subtotali separati ✓
- `GET /quotes/api/3/export.xlsx` → 6.2 KB validato
- `GET /quotes/api/3/pdf` → 4.4 KB, magic `%PDF-1.4`, raggruppamento corretto

### File toccati
- `app/main.py` — bump 3.4.1 → 3.4.2
- `app/models/models.py` — colonna `QuoteLine.category_override` (già in 3.4.1)
- `app/routers/quotes.py` — helper `_line_category` con override, GET espone override, POST/PUT line accettano `category_override` con sentinel `__CLEAR__`
- `app/services/quote_pdf.py` — `_line_category` allineata
- `app/templates/pages/quotes.html` — bottone 📁 sulla riga, funzione `changeLineCategory(lineId)`
- `app/templates/components/copilot.html` — `<textarea>` auto-resize (già in 3.4.1)
- `app/static/js/copilot.js` — `AbortController` + bottone stop (già in 3.4.1)
- `app/services/ai_provider.py` + `ai_assistant.py` — parser JSON lenient (già in 3.4.1)
- `scripts/migrate_quote_category_override.py` — nuovo
- `strumenti.bat` + `strumenti.sh` — voce [9] migrazione, `[A]`/`[a]` per uploads

---

## v3.4.1 — Bugfix copilot: JSON con commenti (27 aprile 2026, sera)

**Sintomo riportato**: il copilot non aggiunge la quotazione richiesta; il drawer non mostra la card di conferma. Log AI: l'azione viene generata correttamente (`type: propose_quote`, `lines` complete) ma silenziosamente scartata.

**Root cause**: il modello attivo (Ollama llama3.1:8b) infila commenti JavaScript dentro il JSON dell'azione:
```json
"number": null, // verrà generato automaticamente
"issue_date": "2026-04-27", // data corrente
"vat_rate": 22, // aliquota IVA predefinita
```
JSON è strict: `json.loads()` solleva `JSONDecodeError`, `safe_json_parse` ritorna None, l'azione non viene salvata come `AIAction` e non torna in risposta. Niente errore visibile, solo silenzio.

**Fix**:
1. `safe_json_parse` ora esegue tre tentativi in cascata: (a) parse strict → (b) strip di `// ...`, `/* ... */` e trailing commas state-aware (rispetta stringhe ed escape, non tocca URL `https://...`) → (c) regex sul primo blocco `{...}`.
2. System prompt rinforzato con sezione **"FORMATO JSON OBBLIGATORIO"**: zero commenti, zero virgole finali, zero apici singoli, numeri non quotati, omettere campi invece di metterli a `null`.
3. `extract_proposed_actions` logga ora i casi di `parse fallito` o `type non valido` con i primi 200 char del payload — niente più silenzio se in futuro si presenta un altro pattern di output deviante.

**Smoke test**: payload reale dal log `Aggiungi una quotazione per il prog.txt` (con 4 commenti `//` + 1 trailing comma) → `safe_json_parse` ora estrae `type=propose_quote, data.project_id=6, lines=1` correttamente. Prima falliva al char 135.

### File toccati
- `app/services/ai_provider.py` — nuova `_strip_json_comments_and_trailing_commas`, cascata in `safe_json_parse`
- `app/services/ai_assistant.py` — sezione "FORMATO JSON OBBLIGATORIO" in `ASSISTANT_SYSTEM_PROMPT`, regola 6 aggiornata ("OMETTI il campo invece di null"), warning log in `extract_proposed_actions`

---

## v3.4 — Export tabellari + PDF italiano + categorie editabili (27 aprile 2026)

### Export listino e quotazioni in CSV / Excel

Nuovi endpoint, scaricabili da menu dropdown "⬇ Esporta" sia in `/pricelist` (topbar) sia nell'editor quotazione:

- `GET /pricelist/api/export.csv` — UTF-8 con BOM (apre dritto in Excel/Numbers), separatore `;`, colonne: Categoria · Reparto · Nome · Descrizione · Unità pre · Unità · Prezzo · Prezzo medio · Prezzo basso · Hardcosts · Keywords · Attivo
- `GET /pricelist/api/export.xlsx` — Excel nativo con header brand indigo, larghezze auto, freeze pane prima riga
- `GET /quotes/api/{id}/export.csv` — quote con righe raggruppate per categoria, **subtotali**, sconti categoria, totals footer
- `GET /quotes/api/{id}/export.xlsx` — stessa struttura ma con styling: header brand, righe categoria evidenziate, riga "TOTALE IVA inclusa" su sfondo indigo, format numerico `#,##0.00`

L'export JSON pre-esistente resta come "backup completo" reimportabile.

### Subtotali per categoria

Aggiunta riga subtotale **prima** dello sconto categoria, sia nell'editor live (UI quote) sia nel PDF e negli export tabellari. Permette di leggere a colpo d'occhio quanto pesa ciascun gruppo.

### PDF quotazione: redesign in italiano

`quote_pdf.py` riscritto:

- Header con dati tenant (nome, indirizzo, P.IVA, contatti) letti dalla tabella `tenants`
- Blocco cliente strutturato con righe etichettate (Cliente, Titolo, Data, Validità) e separatori sottili
- Sezione "PREMESSE TECNICHE" con materiale, durata, fps, formato consegna
- Tabella righe con righe alternate (`ROWBACKGROUNDS`), header indigo, header categoria su banda BAND (`#eef1ff`), riga subtotale su grigio chiaro
- Box totali a destra (62mm + 38mm) con riquadro grigio chiaro, riga finale "TOTALE (IVA inclusa)" su sfondo indigo
- Etichette tutte in italiano: "QUOTAZIONE", "Q.tà", "Sconto %", "Totale lordo", "Subtotale", "TERMINI DI PAGAMENTO", "NOTE", footer con "Si applicano le nostre Condizioni Generali di Vendita"
- Date formattate `dd/mm/yyyy` (helper `_fmt_date`)

### UI editing categorie listino

Sidebar categorie in `/pricelist`: pulsante ✏️ accanto a ogni categoria → modal di modifica con nome, descrizione, ordine + bottone "Elimina" (visibile solo se la categoria non ha voci collegate). Endpoint `PUT/DELETE /pricelist/api/categories/{id}` esistevano già — solo cablaggio UI.

### File toccati

- `app/routers/pricelist.py` — `_pricelist_rows_for_export`, `/api/export.csv`, `/api/export.xlsx`
- `app/routers/quotes.py` — `_quote_export_rows`, `/api/{id}/export.csv`, `/api/{id}/export.xlsx`
- `app/services/quote_pdf.py` — riscritto in italiano, header tenant, subtotali, box totali laterale
- `app/templates/pages/pricelist.html` — dropdown export, modal `modal-edit-cat`, funzioni `editCategory`/`saveCategoryEdit`/`deleteCategoryFromEdit`
- `app/templates/pages/quotes.html` — dropdown export nell'editor, riga subtotale per categoria, stile `.ql-cat-sub-row`
- `app/main.py` — version `3.3.0` → `3.4.0`

### Smoke test live
- `/pricelist/api/export.csv` → 200 (12.9 KB)
- `/pricelist/api/export.xlsx` → 200 (12.8 KB)
- `/quotes/api/2/export.csv` → 200
- `/quotes/api/2/export.xlsx` → 200, struttura verificata via `openpyxl.load_workbook`: header riga 5, riga categoria, riga voce con format numerico
- `/quotes/api/2/pdf` → 200 magic bytes `%PDF-1.4`, 4.3 KB con tutte le sezioni nuove

### Bug risolto in corso d'opera

`MergedCell.column_letter` non esiste — colpiva l'export xlsx delle quote (header riga 1 mergiato). Sostituito `ws.cell(row=1, column=i).column_letter` con `openpyxl.utils.get_column_letter(i)`. Stesso pattern preventivamente sistemato in pricelist.

---

## v3.3 — Fase 4 step F1: interazioni immediate (27 aprile 2026)

### Click-to-open su tutte le tabelle

Sostituiti i bottoni "Apri" con click sull'intera riga. Pattern già presente in `/projects` esteso a:
- **Clienti** — `<tr onclick="openClientDetail(id)">`
- **Listino** — riga apre l'editor; bottone ✏️ rimosso (ridondante), 🗑️ resta con `event.stopPropagation()`
- **Quotazioni** — riga apre l'editor; rimosso link cliccabile sul project_title interno (apriva il progetto, conflitto con click di riga)
- **Reparti** — riga apre il modal di modifica; 🗑️ resta isolato
- **Risorse** — già click-to-open dal precedente refactor

### Drag&drop assegnazione risorse → job

Due viste diverse, stessa meccanica (SortableJS):

1. **Pagina progetto** (`/projects/{id}` → tab "Risorse")
   - Colonna sinistra: lista risorse attive del tenant con search live
   - Colonna destra: card per ogni job del progetto con drop target
   - Drag risorsa nella card del job → POST `/projects/api/{id}/assignments` con job_id+resource_id (idempotente)
   - Click ✕ sul chip → DELETE assignment
   - Default intelligenti: `agreed_daily_rate`/`agreed_hourly_rate`/`role_in_project` ereditati dalla risorsa

2. **Pagina kanban** (`/assignments`)
   - Colonna sinistra fissa: tutte le risorse attive con filtro reparto + search
   - Colonne orizzontali scroll: tutti i job in stato `draft|quoting|approved|active|on_hold` del tenant
   - Drag tra colonne sposta l'assegnazione (DELETE+POST atomicità lato client)
   - Voce sidebar 🧩 Assegnazioni

### File toccati

- `app/routers/projects.py` — endpoint `GET/POST/PUT/DELETE /projects/api/{id}/assignments[/{aid}]` con tenant filter implicito (project_id) + lista risorse disponibili nello stesso payload del GET
- `app/routers/assignments.py` (nuovo) — kanban globale: `GET /assignments/api/board`, `POST /assignments/api/move`, `DELETE /assignments/api/{aid}`
- `app/templates/pages/assignments.html` (nuovo) — vista kanban con SortableJS CDN
- `app/templates/pages/project_detail.html` — tab "Risorse" + drag&drop + style chip/drop
- `app/templates/pages/clients.html`, `pricelist.html`, `quotes.html`, `departments.html` — click-to-open
- `app/templates/base.html` — voce sidebar 🧩 Assegnazioni
- `app/main.py` — registrato router `assignments`

### Smoke test
- `/assignments/api/board` → 200, jobs+risorse caricate
- `POST /assignments/api/move` su risorsa già assegnata → `{duplicate:true}` correttamente
- `/projects/api/1/assignments` → 200 con jobs e available_resources nel payload
- `/assignments/` (HTML) → 200

---

## v3.2.1 — Patch capability AI + fix tenant clienti (26 aprile 2026, sera)

### Capability AI completate / aggiunte

- **`propose_quote` end-to-end**: la capability era esposta nel system prompt ma il primo test live (`Crea quotazione per "Una storia inquinata"…`) falliva con `Stato: failed · Manca 'number'`. Sistemato:
  - `number` auto-generato `Q-{anno}-NNN` se non specificato (progressivo basato sulle quote esistenti).
  - `title` ← titolo del progetto se mancante.
  - `issue_date` default oggi, `valid_until` default +30gg, override se l'AI mette date allucinate (es. 2023 quando siamo nel 2026).
  - `lines` opzionali: se presenti, quote+righe vengono create in **singola transazione** (un solo Apply nel drawer copilot). Rollback completo se anche una sola riga è invalida.
- **`propose_project`** (nuova capability): crea un progetto con `code` + `title` + `client_id` (PK) o `client_name` (lookup esatto). Errore esplicito se il cliente non esiste, invece di indovinare.
- System prompt rinforzato con tre regole critiche: `id` ≠ `code`, no date passate inventate, una sola azione per turno.

Totale capability disponibili: **7** (`propose_client`, `propose_project`, `propose_project_metadata`, `propose_quote`, `propose_quote_line`, `propose_price_item`, `web_search`).

### `/clients` — bottone "Crea + popola con AI"

Nel modal "Nuovo cliente", oltre a "Crea cliente" è disponibile **"✨ Crea + popola con AI"**: crea il cliente con i dati inseriti dall'utente e poi chiama subito `/clients/api/{id}/enrich` per popolare metadati mancanti (P.IVA, sede, sito, filmografia recente). Se l'arricchimento fallisce, il cliente resta comunque creato e l'utente è avvisato. Il bottone appare solo quando un provider AI è configurato per l'utente.

### Fix `clients.py`

- Tutte le query by-id (`get_client`, `update_client`, `delete_client`, `enrich_client_api`) ora filtrano per `tenant_id == CURRENT_TENANT`. Convenzione Fase 1-bis allineata con `pricelist.py` / `resources.py`.
- `search_and_create` (`/clients/api/search-enrich`) ora imposta `tenant_id=CURRENT_TENANT` sul nuovo cliente e tenant-filtra la verifica duplicati.
- Migrazione dal legacy `get_provider()` (singleton globale `.env`) a `get_provider_for_user(user_id, db)` con risoluzione utente da cookie JWT. Risolve il caso in cui un utente con provider configurato in DB non vedeva i bottoni AI perché `.env` non aveva `AI_PROVIDER`.
- `enrich_client(name, known_info, provider=None)`: accetta provider iniettato dal router; fallback al legacy globale per retrocompat.

### Enrichment AI multi-step (sera tardi)

- **Web search nativo Anthropic**: nuovo metodo `extract_json_with_web_search()` su `AIProvider` (default no-op) implementato in `ClaudeProvider` con il tool server-side `web_search_20250305`. Il modello decide autonomamente quante query fare (cap 5), legge i risultati lato Anthropic, segue link, produce JSON strutturato in singola chiamata. Costo ~$10/1000 ricerche oltre ai token.
- **Cascata in `enrich_client`**: priorità (1) provider con web_search nativo (Claude), (2) Tavily se configurato, (3) AI knowledge only. Ogni path gestito da una funzione separata (`_try_native_web_search`, `_try_tavily`, `_try_noweb`); se uno fallisce, il successivo viene tentato. La response API include sempre `web_search_used` per il toast UI.
- Effetto pratico: con Claude attivo, "Mad Entertainment" ora ricerca davvero il sito ufficiale, sede, filmografia recente — niente più dipendenza da Tavily.

### Bugfix `/clients` (sera tardi)

- **Tasto "Elimina" non funzionava**: il render del footer faceva `onclick="deleteClient(${id}, ${JSON.stringify(c.name)}, ...)"`. Le virgolette doppie del JSON dentro un attributo HTML che usa esso stesso virgolette doppie come delimitatore rompevano il parsing → l'handler onclick non veniva mai chiamato. Fix: passaggio via `data-client-id` / `data-has-projects` sul bottone e `data-client-name` sul modal, lette dentro la funzione. Niente più escaping pasticciato in template literal.
- **Tasto "Arricchisci con AI" → 500**: `enrich_client()` dipendeva da Tavily come unica fonte; senza `TAVILY_API_KEY` ritornava None → 500 generico. Fix: fallback a "AI knowledge only" (l'AI usa il proprio training, segnando `notes` con un disclaimer esplicito). Il response include ora `web_search_used: bool` così il toast UI può distinguere "Cliente arricchito con AI" da "Cliente arricchito (senza ricerca web — fonti AI)". Tavily resta opzionale ma non più bloccante.
- `aiEnrich(id, btn)`: passaggio esplicito di `this` invece di `event.target` (più robusto, restore dello stato originale del bottone in caso di errore).
- **Audit preventivo template**: `quotes.html:714` (sidebar categorie listino in editor quotazione) escapava solo `'` ma non `"`/`&`/`<`. Sostituito con `data-cat` attribute + escape HTML completo + lettura via `this.dataset.cat`. Nessun bug attivo — fix preventivo per categorie listino con caratteri speciali.

### File toccati

- `app/main.py` — versione `3.2.0` → `3.2.1`
- `app/services/ai_assistant.py` — handler `propose_quote`, `propose_project`, `_next_quote_number`, prompt aggiornato
- `app/routers/clients.py` — tenant filter + per-user provider + cookie resolution + `web_search_used` in response enrich
- `app/services/ai_provider.py` — `supports_web_search()` su base class + `ClaudeProvider.extract_json_with_web_search()` con tool `web_search_20250305`
- `app/services/client_enrichment.py` — `provider` parameter, fallback no-web (`ENRICHMENT_SYSTEM_PROMPT_NOWEB`), cascata `_try_native_web_search` → `_try_tavily` → `_try_noweb`
- `app/templates/pages/clients.html` — bottone "Crea + popola con AI", helper `_newClientFormData()`, fix delete + aiEnrich

---

## v3.2 — AI per-utente + copilot context-aware (26 aprile 2026)

### Configurazione AI per-utente

Ogni utente configura i propri provider AI in `Impostazioni → tab 🤖 AI`. Le api_key sono salvate cifrate nel DB (Fernet, chiave dedicata `AI_KEY_ENCRYPTION_KEY` separata da `SECRET_KEY` per disaccoppiare la rotazione di JWT e la cifratura segreti).

Provider supportati:
- **Anthropic Claude** (Opus 4.7 / Sonnet 4.6 / Haiku 4.5)
- **OpenAI** (GPT-4o / o1 / o3-mini)
- **Google Gemini** (2.0 Flash / Flash Thinking / 1.5 Pro)
- **Perplexity** (Sonar Pro / Sonar / Sonar Reasoning)
- **Ollama** (locale, base URL configurabile)

Per ogni provider: salva, test connessione (ping minimale che valida auth), attiva. Solo il provider attivo viene usato dal copilot. Niente lock-in.

### Copilot context-aware

Pulsante 💬 fisso in basso a destra, presente su tutte le pagine. Drawer laterale con:
- storia conversazioni cliccabile
- context auto-detection da URL (progetto, quote, job)
- pattern "AI propone, utente dispone": ogni azione concreta restituita dall'AI come blocco strutturato `action`, mostrata come card di conferma con bottoni Applica/Rifiuta. Nessuna esecuzione senza click esplicito.

Capability primo push (delimitate per controllo):
- `propose_price_item` — proporre nuova voce di listino
- `propose_client` — proporre creazione cliente
- `propose_quote_line` — proporre riga su quote attiva
- `propose_project_metadata` — aggiornare metadata progetto (durata, fps, formato)
- `web_search` — ricerca read-only via Tavily

Tutte le azioni vengono salvate in tabella `ai_actions` con stato `proposed → applied | rejected | failed` per audit completo.

### Migrazione

Script non distruttivo: `scripts/migrate_ai_per_user.py` (opzione `[8]` su `strumenti.sh/.bat`). Crea `user_ai_settings`, `ai_actions`, aggiunge `users.active_ai_provider` e genera `AI_KEY_ENCRYPTION_KEY` in `.env` se mancante.

### Dipendenze

Aggiunte: `google-generativeai>=0.8.3`, `cryptography>=43.0.0`. Perplexity chiamata via `httpx` raw (no SDK ufficiale stabile).

---

## v3.1 — Quotazioni UX + listino generico (25 aprile 2026)

### Quotazioni — sconti multilivello e UX rifatta

- Nuovo modello dati: `QuoteLine.line_discount_pct`, `Quote.subtotal_gross`, `Quote.category_discounts` (JSON)
- Cascata sconti: voce → categoria dinamica (per `PriceItem.category`) → pacchetto → IVA. Convenzione UI: tutti gli sconti sono percentuali positive (es. 15% = riduzione 15%); il `package_discount` resta negativo internamente per retrocompat.
- Editor quotazione rifatto: voci raggruppate dinamicamente per categoria, edit inline su qualsiasi campo con auto-save al blur, drag-and-drop righe via SortableJS (CDN), riga "Sconto categoria %" sotto ogni gruppo, sconto pacchetto editabile inline accanto al totale.
- Riepilogo economico mostra: totale lordo (no sconti) per visibilità cliente, sconti voci+categoria, subtotale, sconto pacchetto, totale netto base IVA, IVA, totale finale.
- Modal "Aggiungi voce" rifatto con ricerca live nel listino (nome/descrizione/keywords/categoria).
- PDF aggiornato: raggruppamento per categoria, colonna sconto riga, sconti categoria mostrati per gruppo, breakdown completo dei totali.
- Endpoint nuovi: `PUT /quotes/api/{id}/category-discount`, `PUT /quotes/api/{id}/lines-reorder`.
- Migrazione non distruttiva: `scripts/migrate_quote_discounts.py` (opzione `[7]` su `strumenti.sh/.bat`).

### Listino — generico mercato italiano + export/import

- **Reset completo** del listino. Sostituite le 76 voci di esempio TPR Berlin con 75 voci generiche da workflow standard di post-produzione + pattern ricorrenti dei capitolati reali (A24, Vision, Fremantle, Sky, NBCU TechOps).
- 12 nuove categorie: DAILIES, PICTURE / DI, MASTERING DCP / DCDM, DELIVERABLES VIDEO, ARCHIVE / TRANSFER, VFX, SOUND EDIT, MIX, DELIVERABLES SOUND, LOCALIZATION, QC / METADATA, PROJECT MANAGEMENT.
- Prezzi orientativi mercato italiano 2026 (modificabili). Keywords AI inline per matching capitolato → voce.
- **Schema collassato**: solo `price_list` (rinominato "Prezzo €" in UI). I campi `price_average`/`price_low` restano in DB per retrocompat ma non sono più editati. La cascata sconti sostituisce i tre livelli storici.
- Toggle UI **Giorno ↔ Ora** sul listino (1 turno = 8h): converte la visualizzazione senza modificare il prezzo memorizzato.
- Conversione automatica day↔hour anche in editor quotazione: cambiando l'unità di una voce, il prezzo si ricalcola.
- Export/import listino: `GET /pricelist/api/export` (download JSON portabile), `POST /pricelist/api/import` con modalità `merge` (aggiorna voci esistenti, aggiunge nuove) o `replace` (cancella tutto, ricarica). UI con due bottoni in topbar `/pricelist`. Backup pre-reset salvato in `docs/listino_attuale.json`.
- Capitolati di riferimento estratti in testo in `docs/capitolati_text/` (9 documenti su 17 leggibili: PDF, DOCX). Veterans .doc e BETA Film PDF non estraibili — da convertire manualmente per Fase 2.

## v3.0.1 — Transizione a Claude Code (25 aprile 2026)

### Diagnosi all'apertura del progetto

Trasferimento da chat web a Claude Code. Audit del codice ha rivelato gap rispetto alla documentazione:

- Servizi AI (`ai_provider.py`, `ai_assistant.py`, `client_enrichment.py`, `web_search.py`, `deliverables_parser.py`, `routers/ai.py`) presenti come scaffolding ma mai integrati end-to-end. Default `AI_PROVIDER=disabled`.
- Listino generico estratto da capitolati: NON fatto. `LISTINO_ESEMPIO` ancora basato su esempio TPR.
- 17 capitolati reali disponibili in `docs/capitolati_esempio/` (RAI, Sky, Netflix, Amazon, A24, MUBI, NBCU, Vision, BETA, FREMANTLE, IRDA, Veterans, ContentArmor) — non ancora analizzati.

### Fix

- **`/resources/` 500 error** — `resources.html` referenziava `TYPE_LABEL` (costante JS) dentro Jinja `{{ ... }}`. Iniettato dict equivalente server-side da `routers/resources.py`.
- **Modello AI default** — `config.py` e `.env.example` aggiornati da `claude-sonnet-4-5` a `claude-sonnet-4-6`. Aggiunto commento con i modelli disponibili (Opus 4.7, Sonnet 4.6, Haiku 4.5).

### Roadmap aggiornata

Prima di completare la Fase 2, refactor UX urgente su Quotazioni e Listino (gap rispetto a uso reale Matteo):
- Quotazioni: raggruppamento per categoria, edit voci inline, drag-and-drop, sconto inline
- Listino: nuovo seed da capitolati reali, ricerca migliorata, menu selezione voci dentro quotazione più efficace

Poi Fase 2 vera (UI Impostazioni AI, upload capitolato → DeliveryTemplate, test E2E).

---

## v3.0.0 — Fase 1-bis: fondamenta multi-tenant e reparti (Aprile 2026)

### Visione strategica

Pivot importante: MediaFlow non è più pensato come gestionale per una singola casa di post-produzione, ma come **piattaforma flessibile e adattabile**. Il listino di TPR Berlin diventa esempio iniziale, non standard. Architettura multi-tenant pronta dal primo giorno (per ora in modalità "soft", tutto a tenant_id=1).

### Cosa è cambiato — Modelli dati

- **Tenant** (nuovo modello) — Rappresenta l'azienda che usa il sistema. Per ora ne esiste uno solo "default", ma l'architettura è già predisposta per il multi-azienda futuro.
- **Department** (nuovo modello) — Reparti trasversali (DI/Video, VFX, Audio, Commercial). Ogni risorsa e ogni voce listino appartiene a un reparto. Il reparto è l'unità di responsabilità finanziaria.
- **DeliveryTemplate** (nuovo modello) — Template strutturati per capitolati di consegna (A24, Netflix, Sky, RAI…). Contiene 8 blocchi JSON: video_specs, audio_specs, text_specs, head_format, textless_format, naming_convention, archive_specs, metadata_requirements. Verranno popolati nella Fase 2 tramite import AI dai capitolati reali.
- **PriceItem** — Aggiunti `department_id` e `keywords`. Le keywords sono usate per il matching AI testo-libero → voce listino.
- **Resource** — Aggiunti `department_id`, `role`, `email`, `phone`, `internal_phone`. Esteso ResourceType con `person_internal`, `person_freelance`, `software` (mantenuto `person` per retrocompatibilità).
- **Client / Project / PriceCategory** — Aggiunto `tenant_id` (default=1) per coerenza multi-tenant.

### Cosa è cambiato — Interfaccia

- **Nuova pagina /departments** con CRUD completo dei reparti (creazione, modifica, eliminazione protetta).
- **Pagina Risorse** rivista: filtro per reparto, tab esteso (interno, freelance, studio, attrezzatura, software, veicolo), modal con tutti i nuovi campi (ruolo, email, telefono, interno).
- **Pagina Listino** rivista: filtro per reparto, ricerca anche su keywords, modal di voce con campo keywords editabile.
- Listino di esempio ripulito: descrizioni neutre, nessun riferimento a marchi specifici (FilmMaster, Nucoda, Barco, Euphonix sono stati sostituiti da descrizioni generiche).

### Migrazione

Per database esistenti è stato creato `scripts/migrate_phase1bis.py`. È **non distruttivo**: aggiunge le colonne mancanti via ALTER TABLE, crea il tenant default, i 4 reparti predefiniti, mappa le voci sul reparto corrispondente e popola le keywords delle 76 voci di esempio.

```
python scripts/migrate_phase1bis.py
```

Per database nuovi è sufficiente `python scripts/seed_demo.py` come al solito.

### Roadmap successiva

- **Fase 2** — AI Provider configurabile (Claude / GPT / Ollama) + import capitolati che popolano i DeliveryTemplate
- **Fase 3** — Arricchimento dati clienti/progetti via web (Tavily, Film Italia, IMDB Pro, LinkedIn)
- **Fase 4** — AI co-pilot contestuale + notifiche proattive deterministiche
- **Fase 5** — Import capitolato con matching automatico sulle voci di listino
- **Fase 6** — Reporting AI-assisted con narrative reports
- **Fase 7** — Multi-tenant completo (opzionale, per commercializzazione)

---



### Cosa cambia

Le dipendenze sono state aggiornate per funzionare su Python 3.14 (oltre che 3.11, 3.12, 3.13). Le versioni precedenti di alcune librerie — tipicamente Pillow 10.x, python-jose, passlib — non avevano ancora wheel precompilate per Python 3.14 e la loro installazione falliva con errori di build.

### Dettagli tecnici

- Sostituito `python-jose` con `PyJWT` (più leggero, wheel universali)
- Sostituito `passlib[bcrypt]` con `bcrypt` diretto (passlib non è aggiornato per 3.14)
- Aggiornati tutti i pacchetti alle versioni più recenti con wheel per Python 3.14
- Il modulo `app/services/auth.py` è stato riscritto per usare le nuove librerie — API pubblica invariata

### Per utenti esistenti

Se hai già un venv creato con la versione precedente, cancellalo e ricrealo:

- **Windows:** chiudi l'app, elimina la cartella `.venv`, poi doppio clic su `avvia.bat`
- **Mac/Linux:** `rm -rf .venv` e poi `./avvia.sh`

Il database e i dati esistenti non vengono toccati.

### Aggiunto script avvio Mac/Linux

Nuovo file `avvia.sh` per utenti macOS e Linux (in aggiunta a `avvia.bat` per Windows). Usa `./avvia.sh` dal terminale dopo averlo reso eseguibile con `chmod +x avvia.sh`.

---

## v2.1 — Fase 1: Struttura Progetti (Aprile 2026)

### Cosa cambia nella struttura dati

Prima la gerarchia era lineare: `Cliente → Quotazione → Job`. Questo costringeva a duplicare i dati tecnici (durata, formati, crew) su ogni quotazione anche quando riguardavano lo stesso film o la stessa serie.

Adesso la gerarchia riflette il mondo reale della produzione audiovisiva:

    Cliente → Progetto → Quotazione → Job
                      └→ Altre quotazioni (v2, v3...)
                      └→ Altri job

Un cliente (es. Cattleya) ha più progetti (Romanzo Criminale, Suburra, ACAB), ogni progetto può avere più quotazioni iterative (v1 rifiutata, v2 rivista, v3 approvata), e quando una quotazione viene approvata diventa un job operativo collegato allo stesso progetto.

### Nuove pagine

- **Clienti** (`/clients`) — anagrafica completa con contatti e P.IVA
- **Progetti** (`/projects`) — lista filtrata per cliente, tipo (lungometraggio, serie, spot, doc…), stato, con dashboard per progetto
- **Dettaglio progetto** (`/projects/{id}`) — hub centrale con tabs: tutte le quotazioni del progetto, tutti i job derivati, specifiche tecniche e crew

### Cambiamenti nelle pagine esistenti

- **Quotazioni** — la creazione ora richiede la selezione di un progetto. I campi durata, FPS e formato consegna vengono auto-compilati dai dati del progetto. Se il progetto non esiste, va creato prima dalla pagina Progetti.
- **Sidebar** — nuova sezione "Anagrafica" con Clienti e Progetti sopra la sezione Operativo.

### Come aggiornare un database esistente

Se hai già dati nel database da una versione precedente, usa lo script di migrazione **non-distruttivo**. Su Windows:

1. Apri `strumenti.bat`
2. Scegli opzione **[5] Migra database esistente**
3. Conferma con `s`

Lo script:
- Aggiunge la tabella `projects` e le colonne `project_id` a `quotes` e `jobs`
- Per ogni quotazione/job senza progetto, crea automaticamente un progetto "legacy" basato sui dati esistenti
- Collega tutto correttamente preservando i dati originali

Oppure da riga di comando:
```
python scripts\migrate_to_projects.py
```

### Resettare con i nuovi dati demo

Se preferisci ripartire da zero con i nuovi dati demo (che include 3 progetti: Mare Nostrum, Spot Sky, Città d'Arte):

1. `strumenti.bat` → opzione **[2] Resetta database**

### Cosa arriva nella Fase 2

Provider AI configurabile (Claude / GPT / Ollama locale) con pagina Impostazioni dedicata, test di connessione e selezione modello.

### Cosa arriva nella Fase 3

Arricchimento automatico delle schede cliente via AI + ricerca web (Tavily). Digiti "Cattleya srl" → l'AI compila P.IVA, sede, filmografia, contatti di produzione.

### Cosa arriva nella Fase 4

Assistente AI contestuale (chat laterale sempre accessibile) che conosce il listino e il progetto corrente.

### Cosa arriva nella Fase 5

Importazione capitolato di consegne (PDF, Word, Excel, testo libero) con matching AI contro il listino e conferma interattiva riga per riga prima di generare la bozza di quotazione.
