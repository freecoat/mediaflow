# Calendario/Account Fase D — Documenti collegati (Google Drive) — Design

> Raffinamento implementabile della sezione "Fase D — Documenti collegati" del design master
> `docs/superpowers/specs/2026-07-04-account-linking-calendar-documents-design.md`, con le decisioni
> di scope prese il 2026-07-06.

## Contesto

Fasi A (OAuth foundation), B/B.1 (CalendarEvent + FullCalendar), C (sync Google) completate sul ramo
`feat/calendar-phaseB` (NON pushato/merged). Fase D è l'ultima del programma "account linking + calendario
+ documenti". Scope `drive.file` già concesso in Fase A. Nessun `documents.py`/`google_drive.py`/
`migrate_documents.py` esistente: slate pulito.

## Obiettivo

Collegare file **Google Drive** a **progetti** e **trattative (acquisitions)** senza storage locale: si salva
solo un **riferimento** (metadata + link) apribile in nuova scheda. Due modi di aggancio: **incolla-link**
(sempre attivo) e **Google Picker** (se configurato).

## Decisioni di scope (2026-07-06)

| Tema | Scelta |
|------|--------|
| Aggancio | **Entrambi**: incolla-link + Google Picker (degrado grazioso: Picker solo se `GOOGLE_PICKER_API_KEY` presente + utente Google connesso). |
| Entità con UI | **Progetto + Acquisition**. `activity_id`/`client_id` nello schema (future-proof) ma senza UI dedicata ora. |
| Ramo | **`feat/calendar-phaseB`** (tiene A/B/C/D insieme, un solo merge→main a fine programma). |

## Architettura

### 1. Modello `DocumentLink` (tabella `document_links`)

Tenant-scoped, soft-delete. Colonne:
`id, tenant_id, provider (str, default 'google'), external_file_id (str), name (str), mime_type (str|null),
web_url (str), icon_url (str|null), owner_email (str|null),
project_id (FK|null), acquisition_id (FK|null), activity_id (FK|null), client_id (FK|null),
added_by (FK users|null), created_at, is_active (bool default True)`.

SQLAlchemy 2.0 `Mapped`/`mapped_column`. Almeno uno dei link espliciti valorizzato (validazione nel router,
non vincolo DB). Nessun UNIQUE (stesso file collegabile a più entità); dedup best-effort per
`(tenant, external_file_id, entità)` a livello router.

### 2. Servizio `app/services/google_drive.py`

Layer HTTP isolato (urllib, coerente con `google_calendar.py`/`oauth_providers.py`). Unico `_drive_request`
= punto di mock nei test.

- `parse_drive_file_id(url: str) -> Optional[str]` — regex per le varianti Drive/Docs/Sheets/Slides:
  `/file/d/{id}/`, `/document/d/{id}`, `/spreadsheets/d/{id}`, `/presentation/d/{id}`, `?id={id}`,
  `open?id={id}`, `uc?id={id}`. Ritorna `None` se non riconosciuto.
- `_drive_request(method, url, token, params=None) -> dict` — GET all'API Drive; solleva su >=400 (i chiamanti
  gestiscono).
- `fetch_file_metadata(db, user_id, file_id) -> Optional[dict]` — `get_valid_access_token` → se assente `None`;
  `GET drive/v3/files/{id}?fields=id,name,mimeType,webViewLink,iconLink,owners`. **Best-effort**: qualunque
  eccezione (403 file non creato dall'app / 404 / rete) → `None`, mai propaga. Ritorna dict normalizzato
  `{file_id, name, mime_type, web_url, icon_url, owner_email}`.

Nota `drive.file`: lo scope vede solo i file creati o aperti dall'app. Un URL incollato di un file non ancora
"toccato" dall'app può dare 403/404 → metadata `None`. In quel caso il link si salva comunque con `name`
= fallback (ultimo segmento URL o "Documento Drive") e `web_url` = URL originale. Il Picker invece "apre" il
file → concede l'accesso `drive.file` e restituisce metadata pieni dal client.

### 3. Router `app/routers/documents.py`

`CURRENT_TENANT = 1` in cima. Form-based. Helpers `tenant_guard.scoped`/`fetch_or_404`. Permessi via il
gate RBAC esistente (dependency come negli altri router).

| Method | Path | Perm | Note |
|--------|------|------|------|
| POST | `/documents/api/link` | `manage_projects` o `manage_acquisitions` (secondo `linked_type`) | Due modi (sotto) |
| GET | `/documents/api/list?linked_type&linked_id` | view dell'entità | Lista attivi ordinati per `created_at` desc |
| DELETE | `/documents/api/link/{id}` | manage dell'entità | Soft-delete idempotente |
| GET | `/documents/api/picker-config` | autenticato | `{enabled, api_key?, app_id?, oauth_token?}` |

`POST /documents/api/link` — Form:
- Comune: `linked_type` ∈ {`project`,`acquisition`}, `linked_id`.
- **Modo incolla-link**: `url` → `parse_drive_file_id` → se id: `fetch_file_metadata`; salva DocumentLink con
  metadata (o fallback se `None`). Se URL non è Drive → 400.
- **Modo Picker**: `file_id` (+ `name,mime_type,web_url,icon_url` opzionali dal client) → salva diretto.
- Validazione: `linked_id` esiste ed è tenant-scoped (`fetch_or_404`); `added_by = current_user.id`;
  `tenant_id = CURRENT_TENANT`. Ritorna il DocumentLink serializzato.

`GET /documents/api/picker-config`: se `settings.google_picker_api_key` e utente ha token Google valido →
`{enabled:true, api_key, app_id (da client_id), oauth_token}`; altrimenti `{enabled:false}`.

### 4. Aggancio frontend (degrado grazioso)

Nuovo `app/static/js/documents.js` con funzioni globali riutilizzabili nei due detail:
- `mfDocList(linkedType, linkedId, containerEl)` — fetch list, render righe (iconLink + name + owner_email,
  click apre `web_url` in `_blank rel=noopener`), bottone 🗑 per riga (DELETE + refresh).
- `mfDocAddByUrl(linkedType, linkedId)` — legge input URL, POST, refresh, toast.
- `mfDocPicker(linkedType, linkedId)` — carica `picker-config`; se `enabled` carica gapi+picker via CDN,
  apre Picker; on-pick POST modo Picker. Bottone "Scegli da Drive" reso visibile solo se `enabled`.

Helper globali (`escapeHtml`, `api`, `toast`, `openModal`) da `global.js`, non ridefiniti. Niente
`JSON.stringify` in onclick: usare `data-*`.

### 5. Embed 📎 Documenti

- `project_detail.html`: nuova sezione/scheda "📎 Documenti" → `<div id="doc-list-project">` + input URL +
  bottone Picker. `mfDocList('project', {{project.id}}, ...)` al load.
- `acquisitions.html` (detail-panel): stessa sezione dentro il pannello dettaglio trattativa, con
  `linked_type='acquisition'`.

### 6. Trasversali

- **Migrazione**: `scripts/migrate_documents.py` idempotente (CREATE TABLE IF NOT EXISTS + populate permessi
  se serve). Registrare `document_links` in `_auto_migrate_columns()` (`main.py`) per non crashare al boot se
  l'utente non migra. Voce dedicata in `strumenti.bat`/`strumenti.sh`.
- **Config**: `GOOGLE_PICKER_API_KEY` in `config.py` (default "") + `.env.example`. `app_id` derivato dal
  numeric prefix di `GOOGLE_OAUTH_CLIENT_ID`.
- **i18n**: chiavi `doc.*` (`doc.section`, `doc.addByUrl`, `doc.urlPlaceholder`, `doc.pick`, `doc.empty`,
  `doc.remove`, `doc.added`, `doc.error`, `doc.invalidUrl`, `doc.openInDrive`) in 5 lingue, stesso commit.
- **Cache-buster** `?v={app_version}` su `documents.js`.
- **Permessi**: riuso `manage_projects`/`manage_acquisitions`/`view_*` esistenti. Nessun permesso nuovo
  (documenti seguono l'entità collegata).
- **Versioning**: bump `main.py` `.242`→`.243`, CHANGELOG + STATO, commit a fine fase.

### 7. Sicurezza

- `web_url` aperto solo se schema `http(s)` (anti `javascript:`), `rel="noopener noreferrer"`,
  `target="_blank"` — coerente con la linkificazione anti-XSS di Fase B.
- `oauth_token` in `picker-config` esposto al client SOLO per il Picker (necessario a gapi); è l'access_token
  effimero, non il refresh (che resta cifrato server-side). Nessun refresh token verso il client.
- Tenant-scope su ogni query; `fetch_or_404` per `linked_id`.

## Componenti (isolamento)

| Unità | Cosa fa | Dipende da |
|-------|---------|-----------|
| `google_drive.py` | parse URL + fetch metadata Drive, best-effort | oauth_providers, urllib |
| `documents.py` (router) | CRUD DocumentLink + picker-config, RBAC, tenant-scope | google_drive, tenant_guard, models |
| `documents.js` | render lista + add(url/picker) + remove, degrado Picker | global.js, endpoints |
| embed nei detail | monta la sezione per project/acquisition | documents.js |
| `migrate_documents.py` | crea tabella idempotente | — |

## Testing

- `tests/test_google_drive.py`: `parse_drive_file_id` su ~6 varianti + non-Drive→None; `fetch_file_metadata`
  mock (`_drive_request`) → dict; best-effort: token assente→None, 403→None (no raise).
- `tests/test_documents_api.py`: link via url (metadata mock), link via picker payload, link con URL non-Drive
  →400, list filtrata per entità, delete soft idempotente, RBAC (staff senza manage→403), tenant-scope
  (entità altrui→404), fallback name quando metadata None.
- `tests/test_documents_page.py`: `project_detail.html` e `acquisitions.html` contengono la sezione
  (`doc-list-project` / hook acquisition) + `documents.js` incluso; chiavi i18n `doc.*` presenti in i18n.js.
- Smoke browser (uvicorn senza reload, 127.0.0.1): incolla-link (metadata mock o file reale), lista+rimuovi,
  Picker nascosto senza key, 0 errori console.

## Fuori scope (YAGNI)

Microsoft/OneDrive, upload/storage locale, versioning file, anteprima embedded, link ad Activity/Client via UI,
ricerca full-text nei documenti.

## Rischi & note

- `drive.file` non vede file arbitrari: incolla-link di file mai aperti dall'app → metadata `None` (fallback
  name). Documentato in UI (hint). Il Picker aggira (l'atto di scegliere concede l'accesso).
- `GOOGLE_PICKER_API_KEY` + Drive API abilitata nel progetto Google Cloud = prerequisito operativo Matteo per
  il Picker; l'incolla-link funziona senza.
- Re-consent scope già gestito in Fase A (nessun cambio scope qui: `drive.file` già presente).
