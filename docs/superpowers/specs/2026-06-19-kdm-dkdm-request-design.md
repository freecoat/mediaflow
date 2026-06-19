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

## Riferimenti

- [The Encrypted DCP Delivery Workflow — MASV](https://massive.io/workflow/encrypted-dcp-delivery/)
- [What is a Distribution KDM (DKDM) — DCP Maker](https://dcpmaker.com/docs/what-is-a-distribution-kdm/)
- [Key Delivery Message (KDM) — Cinepedia](https://cinepedia.com/security/key-delivery-message/)
- [KDM Creation and Delivery — dcpomatic / DeepWiki](https://deepwiki.com/cth103/dcpomatic/3.5-kdm-creation-and-delivery)
