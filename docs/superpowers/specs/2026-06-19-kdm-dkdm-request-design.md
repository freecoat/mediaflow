# KDM/DKDM Request Tracking — Design

**Data:** 2026-06-19
**Versione target:** v3.5.0-alpha.172.226+
**Stato:** approvato (brainstorming), pronto per implementation plan

---

## Problema

MediaFlow è usato da una casa di post che crea **DCP cifrati** (Digital Cinema Package).
I clienti (distributori, cinema/esibitori) richiedono le **chiavi** per sbloccare quei DCP:

- **KDM** (Key Delivery Message): chiave per **un singolo server cinema**, legata al
  certificato di quel server e a una **finestra di proiezione** (date valid_from/valid_to)
  e a una **CPL** specifica (Composition Playlist, identificata da UUID).
- **DKDM** (Distribution KDM): chiave **master** consegnata a un **distributore**, che la
  userà per generare a valle le proprie KDM per i cinema.

Oggi MediaFlow non ha nessun concetto di DCP-crypto, CPL, certificati o richieste chiavi.
Le richieste cliente vengono gestite fuori sistema, senza tracciabilità né link al progetto.

## Obiettivo

Nuova **pagina top-level `/kdm`**: coda centralizzata delle richieste KDM/DKDM.
Ogni richiesta:

1. viene registrata (tipo, cliente, target, finestra date);
2. il sistema **cerca automaticamente le CPL dei DCP esistenti** e le matcha con la
   richiesta (CPL UUID esatto → fuzzy titolo → titolo progetto);
3. al match, la richiesta **si linka al delivery item DCP e al progetto** —
   diventa a tutti gli effetti un **delivery item** con workflow di stato.

## Scope v1 (decisioni confermate)

- **Solo tracking, no crypto.** MediaFlow registra/traccia la richiesta come workflow.
  La KDM la genera l'operatore con tool esterno (easyDCP / dcpomatic / Qube / Eclair) e
  la carica/segna come fatta. Zero gestione chiavi private nel sistema.
  Lo schema dati è però progettato per agganciare la generazione in fase 2 senza rifare i modelli.
- **Fonti CPL multiple** (tutte): parse `CPL.xml` caricato, scan filesystem via agent
  esistente, inserimento manuale UUID, fuzzy su titolo progetto. I metadati CPL vivono
  legati al **delivery item DCP** esistente (`JobDeliverable`).
- **Pagina top-level dedicata** `/kdm` con tab interni (Richieste / Cinema-Server / CPL DCP).
- **Target = registry riusabile** `CinemaFacility` → `CinemaServer` (anagrafica tipo fornitori),
  con upload certificato `.pem`, thumbprint, scadenza, alert cert scaduto.
- **API per-utente = adapter pluggable.** Non esiste un'API pubblica universale per i
  certificati cinema; i cert arrivano per email/Trusted Device List/portali SaaS
  (Qube Wire, Gofilex, Deluxe One, Eclair Play). v1 = adapter `manual`. Fase 2 = adapter
  reale verso un servizio KDM, con chiave cifrata Fernet per-tenant (riusa pattern
  `UserAISettings` + adapter `TransferOrder` già nel codice).
- **No portale cliente** in v1: la richiesta la inserisce l'operatore (o l'AI copilot).

## Modello dati

Tutte le entità: `tenant_id` FK + soft-delete (`is_active` o `deleted_at` secondo convenzione).
Tutto in **tabelle nuove** — nessuna colonna aggiunta a tabelle esistenti.

### CPL metadata (legata al DCP deliverable)

```
DcpCpl
  id, tenant_id
  job_deliverable_id  FK→JobDeliverable    # il delivery item DCP esistente
  cpl_uuid            (str, indexed)        # chiave di match esatto
  content_title_text                        # ContentTitleText dal CPL.xml
  edit_rate, duration_frames, encrypted (bool)
  key_ids             (JSON list)           # KeyId per traccia
  source              (enum: parsed_xml | agent_scan | manual | fuzzy)
  is_active
```

### Target registry (riusabile)

```
CinemaFacility
  id, tenant_id, name, city, country, contact_email
  kind (cinema | distributor)
  is_active

CinemaServer                                # 1 cert = 1 server
  id, tenant_id, facility_id FK→CinemaFacility
  manufacturer (dolby | christie | gdc | barco | sony | qube | other)
  model, serial
  cert_pem (text), cert_thumbprint, cert_expires_at
  is_active
```

### Richiesta (diventa delivery item)

```
KdmRequest
  id, tenant_id
  request_type     (kdm | dkdm)
  client_id        FK→Client                # chi chiede
  project_id       FK (nullable)            # riempito dal match
  dcp_cpl_id       FK→DcpCpl (nullable)     # risultato match → link
  job_deliverable_id FK (nullable)          # denormalizzato dal match (delivery item)
  target_facility_id FK→CinemaFacility (nullable)
  target_server_id   FK→CinemaServer (nullable)   # KDM: obbligatorio; DKDM: distributore
  valid_from, valid_to (datetime)           # finestra proiezione
  delivery_method  (email | portal | aspera | usb)
  status           (FSM, sotto)
  matched_confidence (0-100), match_source
  requested_by, requested_at, notes
  generated_at, delivered_at, confirmed_at
  kdm_file_asset_id FK (nullable)           # KDM prodotta fuori, caricata qui
  deleted_at, deleted_by_user_id

KdmRequestEvent                             # audit event-sourced leggero (pattern QC events)
  id, kdm_request_id FK, event_type, payload_json, user_id, created_at
```

### FSM stato

```
received → matched → keys_pending → generated → delivered → confirmed
         ↘ rejected        ↘ expired
```

Transizioni valide centralizzate (un solo punto, niente set diretto di `status`).

## Match engine

`app/services/kdm_match.py`

```
match_request(req) → [candidati con confidence]
  1. cpl_uuid esatto su DcpCpl          → confidence 100
  2. ContentTitleText / titolo fuzzy    → 60-90
  3. titolo progetto + risoluzione      → 40-70
```

- 1 hit ≥ soglia → **auto-link** (set `dcp_cpl_id`, `job_deliverable_id`, `project_id`, status `matched`).
  Soglia auto-link **configurabile** (default 95, settabile per-tenant): valore reale da
  tarare in beta sul corpus richieste/CPL reali — non giudicabile a priori.
- N candidati → scelta operatore (endpoint `/link`).
- 0 candidati → richiesta **orfana** in attesa di CPL (badge ⚠).

Fuzzy: `rapidfuzz` se già dipendenza, altrimenti `difflib.SequenceMatcher`.

## Parser CPL

`app/services/cpl_parser.py` — solo `xml.etree`, namespace-tolerant (SMPTE + Interop).
Estrae: `cpl_uuid` (`<Id>urn:uuid:…</Id>`), `ContentTitleText`, `EditRate`,
durata (somma reel), `encrypted?` (presenza `<KeyId>`), lista `KeyId`. **Niente crypto.**
Riusa il pattern dei parser capitolati (2-pass, namespace-agnostic).

## Router e API

`app/routers/kdm.py` — scope `CURRENT_TENANT` su ogni query, permesso RBAC nuovo
`manage_kdm` su tutti i mutator, POST/PUT via `Form(...)` (convenzione progetto).

```
GET  /kdm                              pagina coda (Jinja)
GET  /kdm/api/requests                 lista filtrabile (status/type/scadenza/progetto)
POST /kdm/api/requests                 nuova richiesta → lancia auto-match
POST /kdm/api/requests/{id}/match      ri-lancia match, ritorna candidati
POST /kdm/api/requests/{id}/link       conferma link a dcp_cpl_id (N match)
POST /kdm/api/requests/{id}/transition FSM transition
POST /kdm/api/requests/{id}/upload-kdm carica file KDM esterno → asset
DELETE /kdm/api/requests/{id}          soft-delete

GET/POST/PUT/DELETE /kdm/api/facilities
GET/POST/PUT/DELETE /kdm/api/servers
POST /kdm/api/servers/{id}/cert        upload .pem → estrai thumbprint + scadenza

POST /kdm/api/cpl/parse                upload CPL.xml → estrai + salva DcpCpl
POST /kdm/api/cpl/scan                 agent scan storage DCP (riusa agent esistente)
```

## UI

Pagina `/kdm` top-level (voce sidebar, icona key 🔑). Tab interni
(pattern `data-i18n` + tab-switch JS esistente):

- **Richieste** — coda principale: tabella stato/tipo/cliente/film/cinema/finestra,
  badge scadenza finestra, badge match (✓ linkato / ⚠ orfano / N candidati).
  Riga → drawer dettaglio: timeline eventi, link progetto/deliverable, azioni FSM.
  Bottone "+ Nuova richiesta": tipo, cliente, titolo/CPL UUID, target server, finestra →
  al salvataggio auto-match → candidati inline.
- **Cinema/Server** — registry `CinemaFacility` + `CinemaServer`, alert cert scaduto.
- **CPL DCP** — elenco `DcpCpl` indicizzate + import `CPL.xml` / scan agent.

i18n: ogni stringa nuova in it/en/fr/de/es (`i18n.js` + `data-i18n`), stesso commit.

## AI capabilities

Registry esistente (`app/services/ai_capability_registry.py`):

- `propose_kdm_request` — cliente, tipo, titolo/cpl, target, finestra → crea richiesta + match.
- `propose_cinema_server` — registra cinema/server dal testo della richiesta cliente.

Schema tool con `description` esplicite sui `*_id` (lezione allucinazione FK).
Copilot: richieste aperte + CPL disponibili nel `build_context` (non solo come tool,
per provider senza tool nativi).

## Integration adapter (API per-utente)

`app/services/kdm_adapters/`

```
base.py    KdmAdapter(send_kdm, fetch_certs)
manual.py  v1: no-op, operatore carica a mano
[fase 2]   qube_wire.py, gofilex.py — chiave cifrata Fernet per-tenant
           (riusa UserAISettings pattern); adapter scelto in /settings
```

## Migrazione

`scripts/migrate_kdm.py` + `_auto_migrate_kdm_tables()` nel lifespan di `main.py`.
`create_tables` nuove + ALTER idempotenti. Seed: registry vuoto, 0 dati.

## Test

- **pytest**: parser CPL (fixture `CPL.xml` SMPTE + Interop), match engine
  (uuid esatto / fuzzy / orfano), FSM transizioni valide/invalide, RBAC gate `manage_kdm`,
  tenant scope, soft-delete + unique bypass (`include_deleted=True`).
- **E2E Playwright**: crea richiesta → match → link → FSM → upload KDM → confirmed.
- Fixture `CPL.xml` reale minimale in `tests/fixtures/`.

## Fuori scope v1 (YAGNI)

- Generazione crypto KDM/DKDM (XML cifrato, chiavi private).
- API reale verso servizi KDM (solo adapter `manual`; adapter reali in fase 2).
- Portale cliente self-service (richiesta inserita da operatore/AI).
- Trusted Device List import automatico.

---

## Revisione 2026-06-19b — Form pubblico cliente + ciclo completo

Estensione confermata dopo il primo design. Lo scope tracking-only resta; si aggiunge
il **canale di ingresso lato cliente** e il **ciclo di vita completo** fino al deliverable.

### Form pubblico via link (cliente compila)

- **Link riusabile per-progetto** + **link standalone** (non legato a progetto).
  Modello `KdmRequestLink` (token 64-hex, `project_id` nullable, `prefill_json`, `is_active`).
  Riusa il pattern public-token già nel codice (tech-sheet `/public/.../edit`, portale magic-link).
- L'**operatore pre-compila** parzialmente i campi (titolo, CPL, note, tipo) → genera il link →
  lo invia al cliente. Il link è **riusabile** (N submission) finché attivo; revocabile.
- Il **cliente** apre `/public/kdm/{token}` (no auth) e completa:
  certificato/i server (upload `.pem`), **data + ora di sblocco** (valid_from/valid_to),
  titolo film, CPL UUID del DCP, **contatto cinema/laboratorio destinatario** della KDM,
  **contatto produzione**, note. Submit → crea `KdmRequest` (status `received`,
  `project_id` dal link se presente) + esegue auto-match CPL.
- Campi contatto aggiunti a `KdmRequest`: `cinema_contact_name`, `cinema_contact_email`
  (destinatario chiave), `lab_contact_email`, `production_contact_name`,
  `production_contact_email`. Cert caricato dal cliente: se non c'è un `CinemaServer`
  registrato, si crea al volo `CinemaFacility`+`CinemaServer` dai dati contatto + cert
  (thumbprint/scadenza via `kdm_cert.parse_cert`).

### Notifica finishing (Claqo + email)

- Alla submission: **notifica in-app** agli utenti finishing via
  `notify_permission(db, "manage_kdm", …)` (`app/services/notifications.py`) **+ email**
  best-effort via SMTP (`app/services/invoice_email.py` pattern, `.env` SMTP_*).
  Se SMTP non configurato → solo notifica in-app, nessun errore bloccante.

### KDM prodotta = deliverable nella lista consegne

- Quando il finishing porta la richiesta a `generated` (chiave prodotta col tool esterno e
  caricata), il sistema **materializza un `JobDeliverable`** nel job collegato:
  natura/quantità 1, `price_item_id` = voce listino KDM/DKDM, **data di emissione** =
  `generated_at`, link al `KdmRequest`. La KDM resta così come item nella lista delle
  **deliveries prodotte** con data di emissione. Richiede che la richiesta sia agganciata a
  un job (finishing lo fa allo step matched→keys_pending). Se manca il job, lo step
  `generated` chiede prima l'aggancio (HTTP 400 con messaggio).
- Campo `KdmRequest.job_deliverable_produced_id` FK→JobDeliverable (output materializzato),
  distinto da `job_deliverable_id` (il DCP di origine matchato).

### Voci listino

- Aggiungere a listino due voci: **KDM** (20 €) e **DKDM** (300 €), reparto **DI-Video**
  (finishing/mastering), unit `pc`. In `seed_demo.py` (`LISTINO_ESEMPIO`) **e** via
  `scripts/migrate_kdm.py` (upsert idempotente per DB esistenti, `code` `KDM`/`DKDM`).
  La materializzazione del deliverable linka questo `price_item` per tipo richiesta.

### Riepilogo nuove entità/campi (revisione)

```
KdmRequestLink
  id, tenant_id, token(64hex, unique), project_id FK nullable,
  prefill_json (JSON), is_active, created_at, created_by_user_id

KdmRequest  (+ campi)
  cinema_contact_name, cinema_contact_email, lab_contact_email,
  production_contact_name, production_contact_email,
  client_cert_pem (text, nullable),            # cert grezzo se no server registrato
  job_deliverable_produced_id FK→JobDeliverable (nullable)
```

### Sicurezza form pubblico

- Token 64-hex (`secrets.token_hex(32)`), no enumerazione. Rate-limit best-effort sulla POST.
- Upload `.pem` parsato con `kdm_cert.parse_cert` (no exec). CPL UUID solo stringa.
- **Nessun dato sensibile esposto in GET**: il form pre-compilato mostra solo i campi
  prefillati dall'operatore, mai elenco progetti/clienti (link standalone non rivela nulla;
  link per-progetto mostra solo titolo progetto). Submit CSRF-safe (token nell'URL = capability).

## Riferimenti

- [The Encrypted DCP Delivery Workflow — MASV](https://massive.io/workflow/encrypted-dcp-delivery/)
- [What is a Distribution KDM (DKDM) — DCP Maker](https://dcpmaker.com/docs/what-is-a-distribution-kdm/)
- [Key Delivery Message (KDM) — Cinepedia](https://cinepedia.com/security/key-delivery-message/)
- [KDM Creation and Delivery — dcpomatic / DeepWiki](https://deepwiki.com/cth103/dcpomatic/3.5-kdm-creation-and-delivery)
