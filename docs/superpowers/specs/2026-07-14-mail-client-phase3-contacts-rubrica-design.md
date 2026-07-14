# Client email — Sotto-fase 3: Rubrica Contatti

**Data**: 2026-07-14
**Ramo**: `feat/mail-client-phase3` (da `feat/mail-client-phase2`)
**Versione target**: v3.5.0-alpha.172.246
**Predecessore**: [F2 integrazione CRM email](2026-07-07-mail-client-phase2-design.md)

## Contesto e riformulazione

Il programma "Client email" prevedeva come F3 un generico *auto-flow* (auto-associazione thread→trattativa, AI senza pin, notifiche). In sede di brainstorming (14 lug) Matteo ha ri-centrato F3 su una **Rubrica Contatti**: una pagina dedicata con dettaglio contatto, alimentata dalle email (signature + partecipanti thread), con i contatti associabili a **clienti, trattative e progetti**. La rubrica diventa l'hub anagrafico delle persone; l'email è la fonte da cui i contatti emergono.

### Stato attuale rilevante

- `Contact` (tabella `contacts`) è oggi **sotto-risorsa di Client**: `client_id` **NOT NULL** (ondelete CASCADE), gestita in `app/routers/contacts.py` con sync `is_primary` → `Client.contact_*`. Nessuna pagina dedicata, nessun link a trattative/progetti.
- `Activity` ha già `contact_id` nullable (timeline per contatto possibile).
- `EmailLink` (F2) aggancia thread Gmail a `acquisition_id` (NOT NULL), logga `Activity(type=email)`.
- `gmail.py` (F2) è stateless best-effort (urllib, `_gmail_request` mockabile): `get_thread`, `list_threads`, ecc.
- La **scheda tecnica progetto** (`ProjectTechSheet`) ha già un campo JSON `contacts`: `[{role, resource_id, name_text, email, phone}]` (contatti liberi con eventuale link a `Resource`). Concetto di contatto parallelo e disaccoppiato dalla tabella `Contact`.
- Capability copilot `propose_contact` già esiste (Acquisizioni F1).
- Principio MediaFlow: **il sistema funziona al 100% senza AI**; **AI propone, utente dispone**.

## Obiettivi

1. Trasformare `Contact` in un'anagrafica **standalone** (rubrica), pur mantenendo retrocompatibile il flusso client-scoped esistente.
2. Pagina `/contacts` con lista, filtri (incluso triage orfani) e dettaglio con tutte le associazioni.
3. Estrazione contatti da email **ibrida**: deterministica (regex, gratis, offline) + arricchimento AI opzionale.
4. Match & dedup per email per non duplicare.
5. Associazione contatto ↔ cliente / trattativa / progetto (UI + copilot).
6. Ponte leggero con la scheda tecnica progetto.
7. Notifiche on-demand (no infra push).

Non-obiettivi (YAGNI): Gmail push/Pub-Sub, webhook realtime, migrazione del JSON scheda tecnica a righe relazionali, storia contatto multi-azienda nel tempo.

## Architettura

### 1. Modello dati

**`Contact` evolve (migrazione non distruttiva):**
- `client_id`: da NOT NULL a **nullable**. Le righe esistenti restano invariate (tutte hanno già un client). `client_id` rappresenta l'azienda del contatto (0..1).
- Nuovi campi:
  - `company_text: Optional[str]` — azienda in testo libero quando non c'è un `Client` collegato (contatto orfano).
  - `source: str` default `"manual"` — enum leggero `manual|email|ai` (provenienza).
- Retrocompat: gli endpoint client-scoped (`GET/POST /clients/api/{cid}/contacts`, `PUT/DELETE /contacts/api/{id}`) e il sync `is_primary`→`Client.contact_*` restano identici. Il sync `_sync_primary` gira **solo se** `client_id` è valorizzato.

**Nuove tabelle di associazione M:N** (tenant-scoped, soft-delete via riga fisica cancellata o flag; scelta: righe fisiche con delete su unlink, coerente con join semplici):
- `contact_acquisitions`: `id, tenant_id, contact_id (FK), acquisition_id (FK), role: Optional[str], created_at`. UNIQUE `(contact_id, acquisition_id)`.
- `contact_projects`: `id, tenant_id, contact_id (FK), project_id (FK), role: Optional[str], created_at`. UNIQUE `(contact_id, project_id)`.

> Nota: `client_id` resta un singolo FK (l'azienda del contatto), **non** M:N — un contatto appartiene a un'azienda. Le trattative e i progetti sono M:N perché un contatto può toccarne molti.

### 2. Pagina Rubrica `/contacts`

**Router** (estende `app/routers/contacts.py`):
- `GET /contacts` — pagina (template `pages/contacts.html`). Gate `view_clients`.
- `GET /contacts/api/list` — filtri whitelisted: `search` (nome/email/company), `client_id`, `triage` (yes = orfani senza alcun link a client/acquisition/project), `source`. Ordinamento nome case-insensitive. Paginazione best-effort.
- `GET /contacts/api/{id}` — dettaglio: anagrafica + `client` + `acquisitions[]` + `projects[]` + `activities[]` (ultime N) + `email_links[]` (via acquisizioni collegate). Tenant-scoped `fetch_or_404`.
- `POST /contacts/api/create` — crea **standalone** (`client_id` opzionale). Gate `edit_clients`.
- `PUT /contacts/api/{id}` — esteso ai nuovi campi.
- `POST /contacts/api/{id}/link` — Form `target_type` (client|acquisition|project) + `target_id` (+`role` opz). Idempotente (UNIQUE). Gate `edit_clients` (+ `manage_acquisitions` per target acquisition, `edit_projects` per project — RBAC runtime per target).
- `DELETE /contacts/api/{id}/link` — Form `target_type` + `target_id`. Rimuove associazione.

**Frontend** `static/js/contacts.js` + `templates/pages/contacts.html`:
- Lista con `MFFilterBar` (pattern esistente), colonne nome/azienda/email/tel/link-count, badge "orfano".
- Dettaglio (modal o pannello): anagrafica editabile, sezioni Clienti/Trattative/Progetti con associa/dissocia (riusa `openModal/closeModal`, pattern email_links.js), timeline Activity, email agganciate.
- Voce sidebar "Rubrica" nel gruppo Anagrafica (icona lucide `contact`/`users`).

### 3. Estrazione contatti da email (ibrido)

**Servizio** `app/services/contact_extract.py` (nessuna dipendenza AI obbligatoria):
- `extract_from_thread(thread: dict) -> list[dict]`: dato un thread normalizzato gmail (`get_thread`), estrae candidati deterministici:
  - partecipanti da header `from`/`to`/`cc` dei messaggi → `{name, email}` (parse `Display Name <addr>`).
  - blocco signature dell'ultimo messaggio inbound: regex per telefono (pattern internazionali/IT), email, e righe nome/ruolo/azienda euristiche.
  - dedup interno per email.
- `enrich_with_ai(candidate, signature_text, provider) -> dict`: **opzionale**, popola `role`/`company_text` dalla signature via LLM (usa `get_provider_for_user`). Chiamato solo su richiesta esplicita.

**Trigger UI**:
- In `/mail` (vista thread) e su email pinnata di una trattativa (`email_links.js`): bottone **"Estrai contatto"** → `POST /contacts/api/extract` (Form `thread_id`) → ritorna candidati preview.
- Preview modal: candidati editabili, per ciascuno bottone "Arricchisci AI" (chiama `enrich_with_ai`) e "Salva/collega".

**Endpoint**:
- `POST /contacts/api/extract` — Form `thread_id` → `{candidates: [...]}` (usa `gmail.get_thread` best-effort + `contact_extract`). Gate `edit_clients`.
- `POST /contacts/api/extract/enrich` — Form candidato + `signature` → candidato arricchito. Gate `edit_clients`. Best-effort: AI assente/errore → ritorna candidato invariato.

### 4. Match & dedup

- In `POST /contacts/api/create` e nel salvataggio da preview: se `email` fornita, query `Contact` per email (tenant, `is_active`) → se esiste, risposta segnala `existing_id` invece di creare duplicato; UI propone "aggiorna esistente / collega". L'associazione (link a client/acq/project) si applica sul contatto esistente.
- `GET /contacts/api/match?email=` — lookup rapido per la preview.

### 5. Ponte scheda tecnica progetto (leggero)

- La shape JSON `contacts` della scheda tecnica guadagna un campo opzionale `contact_id` (riferimento a `Contact`). Nessuna migrazione dati: le voci esistenti restano senza `contact_id`.
- Editor scheda tecnica: bottone "Salva in rubrica" su una voce contatto → `POST /contacts/api/from-tech-sheet` (crea `Contact` da name_text/email/phone/role + link `contact_projects` al progetto della scheda + scrive `contact_id` nella voce JSON). Idempotente per email.
- Direzione inversa (mostrare in scheda i contatti rubrica del progetto): fuori scope questo build, si abilita col link `contact_projects` già presente.

### 6. AI copilot

- Estendo la capability `propose_contact` con link opzionali `client_id` / `acquisition_id` / `project_id` (schema con `description` sui campi, memoria [[feedback_ai_schema_descriptions]]). L'handler applica il contatto + le associazioni in una singola AIAction.
- Rispetto la trappola snapshot: `@ai_capability` registrato **prima** dello snapshot `_ACTION_HANDLERS`/`VALID_ACTION_TYPES` che sta in fondo a `ai_assistant.py` (memoria α.172.240).

### 7. Notifiche (on-demand, no background)

- Mail stateless → nessun push. Sul dettaglio trattativa (e opzionalmente contatto), badge calcolato all'apertura: "N email recenti da contatti noti non ancora agganciate", via `gmail.list_threads` filtrato per gli indirizzi dei contatti collegati alla trattativa, escludendo i `thread_id` già in `EmailLink`. Best-effort: Gmail assente → badge nascosto, mai 500.
- Nessuna tabella notifiche nuova; è un conteggio derivato read-only.

### 8. Migrazione / i18n / test

- `scripts/migrate_contacts_rubrica.py` (idempotente): `ALTER TABLE contacts` → `client_id` nullable (SQLite: ricrea via pattern esistente se serve; verificare che il DROP NOT NULL sia gestibile — in SQLite si usa il rebuild tabella o si lascia il vincolo a livello ORM se il fisico non lo impone); add colonne `company_text`, `source`; `CREATE TABLE` `contact_acquisitions`, `contact_projects` con UNIQUE. Auto-migrate al boot (`_auto_migrate_columns`, memoria [[feedback_auto_migrate_columns]]). Voce in `strumenti.bat/sh`.
- i18n 5 lingue (`it/en/fr/de/es`) chiavi `contact.*` in `i18n.js` + `data-i18n` nei template, stesso commit (memoria [[feedback_i18n_always]]).
- TDD: model (nullable + join), router list/detail/create/link/unlink, extract deterministico (fixture thread), match/dedup, RBAC, capability copilot, tech-sheet bridge, notifiche badge. Smoke Playwright browser obbligatorio (memoria [[feedback_smoke_e2e_browser]]).

## Rischi e note

- **SQLite DROP NOT NULL**: SQLite non supporta `ALTER COLUMN DROP NOT NULL` diretto. Opzioni: (a) rebuild tabella `contacts` (copia dati) nella migrazione; (b) il vincolo NOT NULL fisico attuale — verificare se esiste davvero a livello DDL o solo ORM. Il piano deve accertarlo come **primo task** e scegliere l'approccio (rebuild vs no-op se il fisico è già nullable).
- **`EmailLink.acquisition_id` NOT NULL**: resta invariato in questo build; l'email si aggancia via trattativa, il contatto vi si collega tramite `contact_acquisitions`. Nessun link email↔contatto diretto (derivato via acquisizione).
- Escaping/anti-XSS su tutti i valori email (nome/azienda da signature non fidati), coerente con F1/F2 (iframe sandbox, `escapeHtml`).

## Criteri di completamento

- `/contacts` funzionante: crea standalone, filtra, triage, dettaglio con associazioni.
- Estrazione da thread reale (deterministica) produce candidati; arricchimento AI opzionale non blocca.
- Match per email evita duplicati.
- Associazione a client/acquisition/project da UI e copilot.
- "Salva in rubrica" da scheda tecnica.
- Badge notifiche on-demand.
- Migrazione idempotente + auto-migrate boot. i18n 5 lingue. Suite verde + smoke browser verde.
