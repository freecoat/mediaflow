# Design — F5 TransferOrder (asset registry MAM)

**Data**: 2026-06-12 · **Versione target**: v3.5.0-alpha.172.215 · **Approvato da**: Matteo (remote, AskUserQuestion + OK design)

## Contesto

Consegne digitali dalla facility: i byte vivono sulla SAN, quindi l'esecuzione
automatica spetta all'**agent** (tool CLI in facility). Tool reali di Matteo:
Aspera ascp, Signiant Media Shuttle, AWS S3, Netflix Backlot/Content Hub (client
aspera). Scope v1 deciso: **adapter interface + driver `manual` + driver `aspera`
(agent)**; Shuttle/S3/Backlot = driver futuri sull'interfaccia. TPN gate sui
transfer: rimandato (nota per F6). Esito = verifica + `AssetMovement` outgest + link.

NB: esiste già `delivery_portals.py` (upload server-side per portali broadcaster,
DeliveryUpload) — dominio DIVERSO: lì il server ha il file (documenti), qui i
contenuti stanno in facility. Nessuna fusione in v1.

## Modello `TransferOrder` (tabella nuova, create_all al boot)

- `tenant_id`, `tool` (String: `manual` | `aspera`), `destination` (String 500 —
  es. `user@host:/path` o descrizione share), `recipient_email` (nullable)
- `asset_ids` JSON (lista id Asset — multi-asset per ordine, ≥1)
- `status` String FSM: `requested → in_progress → done | failed | cancelled`
  (terminali immutabili; requested→done diretto consentito per manual)
- `link_url` (nullable), `link_expires_at` (DateTime nullable)
- `verification` JSON nullable: `{method: checksum|size|manual|tool_rc, ok: bool,
  details: str}`
- `agent_job_id` FK nullable (solo tool agent-driven)
- `note`, `requested_by_user_id`, `closed_by_user_id`, `created_at/updated_at/closed_at`

## Adapter interface — `app/services/transfer_adapters.py`

Registry `ADAPTERS: dict[str, TransferAdapter]`. Interface (classe base):
- `key: str`, `label: str`, `mode: "manual" | "agent"`
- `build_job_payload(order, files) -> dict` (solo mode agent): `files` =
  `[{volume_id, rel_path}]` risolti dagli Asset (richiede asset registrati via
  agent: `storage_volume_id` + `rel_path`, altrimenti ValueError esplicito)
- Driver v1:
  - **`manual`** (mode manual): nessun job. L'operatore esegue col tool che vuole
    (Shuttle/MASV/Backlot web/S3 console) e chiude l'ordine con esito+link.
  - **`aspera`** (mode agent): payload `{tool:"aspera", files, destination,
    extra_args}`. **Niente credenziali nel payload/DB**: l'agent usa env locali
    (`ASPERA_SSH_KEY_PATH`, opz. `ASPERA_EXTRA_ARGS`). Destination = formato ascp
    `user@host:/path`.

## Service — `app/services/transfer_orders.py`

- `create_order(db, *, tool, asset_ids, destination, recipient_email=None,
  note=None, user_id=None) -> TransferOrder`
  - valida tool nel registry, asset esistenti tenant-scoped (404 logico = ValueError),
    destination non vuota
  - mode agent → risolve files dagli asset (ValueError se un asset non ha
    volume/rel_path) → `enqueue_job(type=AgentJobType.transfer, payload, asset_id=
    primo asset)` → salva `agent_job_id`, status resta `requested` (passa a
    `in_progress` quando l'agent claima? semplificazione: resta `requested`; il
    result del job la chiude direttamente)
- `close_order(db, order, *, ok, method, details=None, link_url=None,
  link_expires_at=None, user_id=None)` — chiusura comune: status `done`/`failed`,
  verification JSON, closed_*; su **done** crea `AssetMovement` per OGNI asset:
  `movement_type=outgest, asset_id, to_party=destination, to_contact=
  recipient_email, carrier=tool, contents_description="TransferOrder #N"`,
  `tracking_number=link_url[:120]` se presente; su **failed** notifica
  (`notify_permission edit_planning_all`, "Transfer fallito: ...").
- `transition(db, order, new_status, *, user_id)` per cancelled/in_progress manuali
  (FSM guard come ArchiveTicket).
- `apply_transfer_result(db, job, result)` / `apply_transfer_failure(db, job, error)`
  — chiamate da `process_job_result` (ramo `AgentJobType.transfer`): risolve
  l'ordine da `agent_job_id`, chiude con esito del tool
  (`method="tool_rc"`, details=log tail).

## Agent — `agent/transfer.py`

- `build_ascp_cmd(files_abs, destination, *, key_path, extra_args) -> list[str]`
  (puro, testabile): `ascp -i {key_path} -d {file1} {file2} ... {destination}`
  (+ extra args splittati). 
- `run_transfer(payload, volumes_by_id) -> dict`: guard `shutil.which("ascp")`
  → RuntimeError chiaro; risolve path assoluti (guard traversal dentro mount come
  browse); esegue (timeout 12h, encoding utf-8/replace); rc!=0 → RuntimeError con
  stderr tail; ritorna `{ok: True, files: n, bytes_total, log_tail}`.
- `main.py`: ramo `transfer` (payload multi-volume: ogni file ha volume_id) +
  CAPABILITIES += "transfer". Env credenziali lette in agent (`ASPERA_SSH_KEY_PATH`).

## Router + UI

- `storage_admin.py`: `GET /storage/api/transfers` (filtri tool/status, serializer
  batch con filename asset + utenti), `POST /storage/api/transfers` (Form: tool,
  asset_ids CSV "1,2,3", destination, recipient_email?, note? — ValueError→400),
  `POST /storage/api/transfers/{id}/close` (Form: ok bool, method, details?,
  link_url?, link_expires_at? date — solo manual o force-close admin),
  `POST /storage/api/transfers/{id}/transition` (cancelled / in_progress).
  Tutti RequireStorage.
- UI `/storage` 6° tab **🚚 Transfer**: lista (tool badge, asset count, destinazione,
  stato badge, link con badge scadenza ⏰ se < 7 giorni o scaduto, richiedente,
  azioni), filtri, modal nuovo ordine (select tool dal registry — endpoint
  `GET /storage/api/transfer-tools` con label+mode, input asset_ids CSV,
  destination, recipient, note; hint per aspera sul formato destination),
  modal chiusura manuale (esito ok/ko, metodo, link, scadenza, dettagli).

## Sicurezza

- Credenziali tool SOLO env agent-side, mai payload/DB.
- Tenant scoping ovunque; RequireStorage.
- Path resolution agent-side con guard traversal (riuso pattern browse).
- TPN/lockdown gate: FUORI scope v1 (decisione Matteo) — nota: in F6 il megaswitch
  dovrà gateare `create_order`.

## Test (TDD)

- Adapter: registry, manual no-payload, aspera payload corretto, asset senza
  volume/rel_path → ValueError.
- Service: create (validazioni, job enqueued per aspera), close done → N movimenti
  outgest con campi giusti + link, close failed → notifica, FSM, apply_result/failure.
- Agent: build_ascp_cmd puro (key, multi-file, extra args), guard ascp assente,
  traversal bloccato.
- Router: CRUD + close + 400/404; E2E `tools/_e2e_f5.py`: manual end-to-end
  (create→close→movimenti+link) + aspera con runner subprocess mockato
  (monkeypatch) → result→ordine done→movimenti.

## Fuori scope

Driver Media Shuttle API / S3 / Backlot (arrivano con credenziali reali), email
automatica destinatario, whitelist TPN, retry automatico, progress streaming
dell'agent, multi-destinazione per ordine.
