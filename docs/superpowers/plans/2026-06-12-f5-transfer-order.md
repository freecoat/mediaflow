# F5 TransferOrder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ordini di transfer digitale dalla facility: adapter interface (manual + aspera agent-driven), tracking link/scadenza, verifica esito, AssetMovement outgest.

**Architecture:** Spec `docs/superpowers/specs/2026-06-12-f5-transfer-order-design.md` — leggila per intero prima. Pattern di riferimento già nel repo: F4 ArchiveTicket (FSM service + router + tab /storage), agent browse/preview (job round-trip, guard binari, traversal), `AgentJobType.transfer` già nell'enum.

**Convenzioni vincolanti:** identiche a F4 (tenant filter, Form-based, auto-create_all per tabelle nuove, commenti italiani, fixture client_admin di tests/test_f4_endpoints.py, Asset ctor original_name/asset_type/uploaded_by, `.venv/Scripts/python`, commit con Co-Authored-By Claude Fable 5).

---

### Task 1: Modello `TransferOrder` + adapter registry

**Files:** Modify `app/models/models.py` (dopo ArchiveTicket); Create `app/services/transfer_adapters.py`; Test `tests/test_f5_model_adapters.py`

- [ ] Test RED: (a) modello — ordine manual con asset_ids JSON [1,2], default status requested, created_at; (b) registry — `ADAPTERS` contiene "manual" (mode manual) e "aspera" (mode agent); (c) `ADAPTERS["aspera"].build_job_payload(order, files)` → `{"tool":"aspera","files":files,"destination":order.destination,"extra_args":[]}`; (d) manual.build_job_payload → NotImplementedError o None (mode manual non lo usa).
- [ ] Implementa modello (colonne esatte da spec §Modello: tool String(20), destination String(500), recipient_email String(255) nullable, asset_ids JSON, status String(15) default+server_default "requested", link_url String(800) nullable, link_expires_at DateTime nullable, verification JSON nullable, agent_job_id FK agent_jobs nullable, note Text nullable, requested_by/closed_by FK users nullable, created_at/updated_at(onupdate)/closed_at) + export in app/models/__init__.py.
- [ ] Implementa transfer_adapters.py: classe base `TransferAdapter` (key, label, mode, build_job_payload solleva NotImplementedError), `ManualAdapter`, `AsperaAdapter` (label "Aspera (ascp)"; payload come sopra), `ADAPTERS = {a.key: a for a in (ManualAdapter(), AsperaAdapter())}`. Docstring: driver futuri shuttle/s3/backlot si aggiungono qui.
- [ ] GREEN → commit `feat(F5): modello TransferOrder + adapter registry (manual, aspera)`.

### Task 2: Service `transfer_orders.py`

**Files:** Create `app/services/transfer_orders.py`; Test `tests/test_f5_transfer_service.py`

- [ ] Test RED (DB in-memory; monkeypatch notify_permission; helper asset registrato con storage_volume_id+rel_path e uno SENZA):
  1. create manual con 2 asset → ordine requested, nessun AgentJob
  2. create aspera → AgentJob type=transfer accodato, payload files [{volume_id,rel_path}×2], agent_job_id salvato
  3. create aspera con asset senza rel_path → ValueError esplicito
  4. create tool ignoto / asset_ids vuoti / destination vuota / asset inesistente tenant → ValueError
  5. close_order ok=True method="manual" + link → status done, verification JSON, closed_at/by, **2 AssetMovement outgest** (asset_id, to_party=destination, to_contact=recipient, carrier=tool, tracking_number=link, contents_description contiene "TransferOrder #")
  6. close_order ok=False → status failed + notify_permission chiamata, NESSUN movimento
  7. transition: requested→cancelled ok; done→* ValueError; requested→in_progress ok (manual preso in carico)
  8. apply_transfer_result(job done result {ok:True,...}) → ordine done via close_order method="tool_rc" + movimenti
  9. apply_transfer_failure → ordine failed + notifica
  10. ordine già chiuso: apply_result/close → no-op o ValueError (scegli ValueError, testalo)
- [ ] Implementa (firme della spec §Service; risolvi l'ordine da agent_job_id con select; `from app.services.transfer_adapters import ADAPTERS`; movimenti: leggi i campi reali di AssetMovement nel modello — to_party/to_contact/carrier/tracking_number/contents_description/movement_type=AssetMovementType.outgest/asset_id/tenant_id; flush no commit).
- [ ] GREEN → commit `feat(F5): service transfer_orders — create/close/FSM, movimenti outgest, esiti job`.

### Task 3: Agent `agent/transfer.py` + ramo main + result wiring server

**Files:** Create `agent/transfer.py`; Modify `agent/main.py`, `app/routers/agent_api.py`; Test `tests/test_f5_agent_transfer.py`

- [ ] Test RED (puri):
  1. `build_ascp_cmd(["/mnt/a.mxf","/mnt/b.wav"], "user@host:/in", key_path="/k/id_rsa", extra_args=["-l","500M"])` → ["ascp","-i","/k/id_rsa","-l","500M","-d","/mnt/a.mxf","/mnt/b.wav","user@host:/in"]
  2. senza key_path → niente "-i"
  3. `run_transfer` con ascp assente (monkeypatch shutil.which→None) → RuntimeError messaggio chiaro
  4. traversal: file con rel_path "../../etc" → ValueError "fuori dal volume" (riusa la logica realpath di agent/browse.py — estraila o replicala)
  5. run_transfer con subprocess mockato rc=0 → {ok:True, files:2, log_tail str}; rc=1 → RuntimeError con stderr tail
- [ ] Implementa agent/transfer.py (env: `ASPERA_SSH_KEY_PATH` opz., `ASPERA_EXTRA_ARGS` opz. split shlex; timeout 43200; encoding utf-8 errors replace). main.py: ramo `transfer` prima di scan (payload files multi-volume: risolvi ogni file col SUO volume_id da volumes_by_id, volume ignoto → failed) + CAPABILITIES += "transfer".
- [ ] Wiring server in `process_job_result` (agent_api.py): ramo failed → `apply_transfer_failure` se type transfer; ramo done → `apply_transfer_result`. Test endpoint minimale in tests/test_f5_agent_transfer.py o riusa pattern test_f3_preview_endpoints (result done → ordine done).
- [ ] GREEN + regressione agent tests → commit `feat(F5): agent transfer ascp + wiring esiti`.

### Task 4: Router + UI

**Files:** Modify `app/routers/storage_admin.py`, `app/templates/pages/storage.html`; Test `tests/test_f5_endpoints.py`

- [ ] Test RED (client_admin): GET /storage/api/transfer-tools → [{key,label,mode}×2]; POST /storage/api/transfers (Form tool=manual, asset_ids="1,2", destination, recipient_email, note) → 200 id; tool=aspera con asset registrati → 200 + job; ValueError → 400; GET /storage/api/transfers?status= → lista serializzata (assets:[{id,filename}], tool, status, link_url, link_expires_at, requested_by); POST /{id}/close (Form ok=true, method=manual, link_url, link_expires_at="2026-12-31") → 200 + movimenti; POST /{id}/transition cancelled → 200; 404 cross-tenant.
- [ ] Implementa endpoint (serializer batch come ticket — riusa/estendi `_build_ticket_lookups` o fai equivalente; asset_ids CSV parse tollerante; date parse YYYY-MM-DD).
- [ ] UI storage.html: 6° tab "🚚 Transfer" (pattern tab Ticket F4): filtri tool/stato; tabella Tool, Asset (count + primo filename), Destinazione, Stato badge, Link (🔗 + badge ⏰ "scade tra Ng"/"SCADUTO" rosso se link_expires_at), Richiesto da, Azioni (requested manual → "✔ Chiudi" apre modal chiusura + "✕ Annulla"; in_progress idem; aspera requested → solo "✕"); modal nuovo (select tool da /transfer-tools con hint mode, asset_ids CSV, destination con hint formato ascp se aspera, recipient, note); modal chiusura (radio esito ok/ko, metodo select manual/checksum/size, link, scadenza date, dettagli). Vincoli JS soliti (data-*, escapeHtml, no Jinja in commenti).
- [ ] Verifiche template jinja + grep onclick + pytest -k f5 → commit `feat(F5): endpoint + UI tab Transfer`.

### Task 5: E2E + bump + push

**Files:** Create `tools/_e2e_f5.py`; Modify `app/main.py` (3.5.0-alpha.172.215), CHANGELOG, STATO

- [ ] E2E (pattern _e2e_f4): manual end-to-end: create (2 asset) → close ok con link+scadenza → done, 2 movimenti outgest, link in GET; aspera: create → job in coda → claim con agent token → handle_job con subprocess/ascp MOCKATO (monkeypatch agent.transfer.subprocess.run rc=0 e shutil.which→path finto) → post result → ordine done + movimenti; aspera failure (rc=1) → ordine failed + notifica in tabella; asset senza rel_path su aspera → 400; transition cancelled; GET filtri.
- [ ] Suite completa 0 failed; bump versione; CHANGELOG entry; STATO sezione (+ Prossimo: F6); graphify update; export DB ZIP; commit bump; push.

## Self-review (fatto)
- Spec coverage: modello+adapter T1, service+movimenti+notifiche T2, agent+wiring T3, router+UI+link badge T4, E2E T5. TPN escluso come da decisione. ✔
- Tipi coerenti: files=[{volume_id,rel_path}] uniforme adapter→payload→agent; verification JSON shape unica; FSM stessa semantica di ArchiveTicket. ✔
