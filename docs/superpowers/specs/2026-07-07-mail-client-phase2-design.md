# Client email — Sotto-fase 2: integrazione CRM (trattativa) — Design

> Data: 2026-07-07. Seconda delle 3 sotto-fasi Client email. Costruisce sopra F1
> (`/mail` webmail, `app/services/gmail.py`) e l'estrazione email di Acquisizioni Fase 2.

## Contesto

F1 ha portato `/mail` (webmail standalone) + `gmail.py` (service Gmail best-effort). Acquisizioni Fase 2 ha l'estrazione email nel copilot (bottone 📥 → `EMAIL_EXTRACTION_GUIDANCE` nel system prompt → `propose_activity/contact/update_client/acquisition_stage`). F2 collega le due: aggancia thread email alle **trattative** (acquisitions), con estrazione AI on-demand e log automatico in timeline.

Ambito deciso (brainstorming): **solo trattativa** (no cliente/progetto in questa fase). Tre punti d'aggancio: ricerca-nel-tab, incolla-link Gmail, "Assegna a trattativa" dal client `/mail`. Il pin salva riferimento + anteprima, logga un'Activity automatica, ed espone "Estrai con AI" on-demand.

## Modello

**`EmailLink`** (tabella `email_links`, tenant-scoped, soft-delete; pattern `DocumentLink` di Fase D):
- `id, tenant_id, provider (default "google"), thread_id, message_id (nullable), from_addr (nullable), subject (nullable), snippet (nullable), email_date (nullable, str ISO o testo header), acquisition_id (FK acquisitions.id, index), added_by (FK users.id, nullable), created_at, is_active`.
- Nessun link a client/project/activity in questa fase (YAGNI; si aggiungeranno se F3 lo richiede).
- Migrazione `scripts/migrate_email_links.py` (idempotente) + tabella creata anche da `create_all` al boot + voce `strumenti`.

## Backend

Riusa `app/services/gmail.py` (F1) e il copilot (Fase 2). Un solo router nuovo.

### `app/services/gmail.py` — aggiunta
- `parse_gmail_thread_id(url: str) -> Optional[str]`: estrae il thread id dagli URL Gmail (id nel fragment, es. `https://mail.google.com/mail/u/0/#inbox/FMfcgz...` → `FMfcgz...`; gestisce anche `/#label/Nome/ID`, `/#search/query/ID`, `?th=ID`). Ritorna `None` se non riconosciuto.

### `app/routers/email_links.py` (nuovo)
- `POST /acquisitions/api/{aid}/emails/link` (Form: opz `url`, opz `thread_id`, opz `from_addr`/`subject`/`snippet`/`email_date`/`message_id` da risultato ricerca) → risolve `thread_id` (da `url` via `parse_gmail_thread_id`, o dal campo diretto), best-effort `fetch metadata` (se mancano i campi: `gmail.get_thread` → primo messaggio → from/subject/date/snippet), crea `EmailLink` + **auto `Activity(type=email)`** sulla trattativa (via `acquisition_service`), ritorna `EmailLink` serializzato. RBAC `manage_acquisitions`. Tenant-scope su `Acquisition` via `fetch_or_404`.
- `GET /acquisitions/api/{aid}/emails` → `{"emails": [_serialize(...)]}` (pinnati attivi, ordinati per `created_at` desc). RBAC `view_acquisitions`.
- `DELETE /email-links/{link_id}` → soft-delete (`is_active=False`). RBAC `manage_acquisitions` (deriva la trattativa dall'`EmailLink`). Ritorna `{"ok": True}`.
- `_serialize_email(e) -> dict`: `{id, thread_id, message_id, from_addr, subject, snippet, email_date, acquisition_id}`.
- Registrazione in `app/main.py` (`include_router`) vicino a `mail_router`.

### Ricerca + anteprima (riuso F1, nessun endpoint nuovo)
- Ricerca thread: frontend chiama `GET /mail/api/threads?q=...` (F1) costruendo `q` dagli indirizzi noti (from/to dei contatti della trattativa + `Client.contact_email`).
- Anteprima corpo: frontend chiama `GET /mail/api/thread/{thread_id}` (F1) → render in iframe `sandbox=""` (stesso helper di `mail.js`).

### Estrai con AI (riuso copilot, nessun backend AI nuovo)
- Helper JS `mfEmailExtract(threadId)`: fetch `GET /mail/api/thread/{threadId}` → concatena `body_text` dei messaggi → apre il drawer copilot e precompila la textarea con `mfT('copilot.email.instruction') + "\n\n" + corpo` (identico al flusso del bottone 📥 di Fase 2), quindi invia. Il contesto trattativa è già rilevato dal copilot sulla pagina `/acquisitions`. Le proposte (`propose_activity/contact/update_client/acquisition_stage`, incl. `next_action_date`) compaiono come AIAction confermabili nel drawer.

## Frontend

### Tab "Email" nel detail `/acquisitions`
Come il tab Documenti di Fase D (stesso pattern `acq-det-tab` + `det-tab-*` + reload su switch):
- Box ricerca (prefill `q` dagli indirizzi contatti) → bottone Cerca → lista risultati thread (mittente/oggetto/snippet) con **Pin**.
- Input incolla-link Gmail + bottone **Pin da link**.
- Lista email pinnate: mittente, oggetto, data, snippet; azioni **Espandi** (anteprima corpo iframe sandbox on-demand), **Estrai con AI**, **🗑**.
- File nuovo `app/static/js/email_links.js`: `mfEmailInit(aid)`, `mfEmailList(aid)`, `mfEmailSearch(aid)`, `mfEmailPin(aid, payload)`, `mfEmailPinUrl(aid)`, `mfEmailPreview(threadId, container)`, `mfEmailExtract(threadId)`, `mfEmailRemove(id, aid)`. Handler rimozione delegato bindato una-tantum (flag modulo, come `documents.js`).

### Da `/mail` — assegna a trattativa
- Nel pannello lettura di `mail.js`, bottone **"Assegna a trattativa"** per thread aperto → apre un picker che riusa `GET /acquisitions/api/list` (esistente, RBAC `view_acquisitions`) per elencare le trattative → `POST /acquisitions/api/{aid}/emails/link` con `thread_id`. Nessun endpoint nuovo.

### i18n
- Chiavi `email.*` (`email.tab`, `email.search`, `email.pin`, `email.pinUrl`, `email.urlPlaceholder`, `email.extract`, `email.expand`, `email.remove`, `email.pinned`, `email.empty`, `email.assign`, `email.assignPick`, `email.error`, `email.invalidUrl`) in 5 lingue + `data-i18n`.

## Sicurezza / error handling

- Anteprima corpo email SEMPRE in iframe `sandbox=""` (no script) via `srcdoc` (riuso `_mailRenderBody` di F1 — estrarlo in una funzione condivisa o replicarne il comportamento in `email_links.js`).
- Best-effort: Gmail non raggiungibile / thread inaccessibile → ricerca/anteprima vuote, il pin resta possibile coi metadata minimi (fallback subject "Email"), mai 500.
- `parse_gmail_thread_id` su URL non-Gmail → 400 "Link Gmail non valido".
- Link/URL aperti solo se schema http(s), `rel="noopener noreferrer"`.
- RBAC runtime: view = `view_acquisitions`, manage = `manage_acquisitions` (pattern documenti Fase D).
- Nessun token Gmail verso il client (le chiamate passano dai router server-side F1).

## Testing

- `tests/test_email_link_model.py` — colonne + default (`provider="google"`, `is_active=True`, `created_at`).
- `tests/test_gmail_parse_thread.py` — `parse_gmail_thread_id` sulle varianti URL Gmail + None su non-Gmail.
- `tests/test_email_links_api.py` — pin da `thread_id`, pin da `url`, pin non-Gmail → 400, list filtrata per trattativa, delete soft, acquisition inesistente → 404, auto-Activity creata al pin. Fixture con JWT cookie reale + monkeypatch `database.engine`/`SessionLocal` (come `test_documents_api.py`/`test_mail_api_read.py`); mock `gmail.get_thread`/`gmail.parse_gmail_thread_id`.
- `tests/test_email_links_page.py` — `acquisitions.html` ha tab/sezione Email + `email_links.js`; `email_links.js` definisce le funzioni globali; `mail.js` ha il bottone "Assegna a trattativa"; i18n ha le chiavi `email.*`.
- Smoke browser: tab Email nella trattativa (pin da link → compare in lista + Activity in timeline; espandi anteprima; 🗑), assegna-da-`/mail` degrada senza errori. 0 errori console.

## Versioning / chiusura

- Bump `app/main.py` `3.5.0-alpha.172.244` → `.245` + CHANGELOG + STATO, commit stesso giro. Ramo `feat/mail-client-phase2`. Nessuna nuova dipendenza. Migrazione `scripts/migrate_email_links.py` + voce strumenti.

## Rimandato (F3)

Auto-associazione in ingresso per indirizzo, threading automatico, AI che propone senza pin manuale, notifiche, anchor a cliente/progetto.
