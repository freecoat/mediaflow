# Design — F6 Distruzione + Dashboard + Report (chiusura roadmap MAM)

**Data**: 2026-06-12 · **Versione target**: v3.5.0-alpha.172.216 · **Approvato da**: Matteo ("subito F6" — decisioni di dettaglio prese da Claude e documentate qui)

## Contesto

Ultima fase della roadmap MAM (design 2026-06-10 §F6): distruzione documentata con
doppia conferma, dashboard "dove vive ogni asset", report storage. In più il **gate
TPN sui TransferOrder** rimandato da F5. Regola cardine dal design: il record Asset
NON muore mai — `content_state=deleted` ma storia permanente; copie residue su tape
→ resta `archived_only`.

Decisioni prese (Matteo ha delegato il dettaglio):
- approvazione con **permesso RBAC nuovo `approve_destruction`** (registry PERMISSIONS,
  preset admin) — approvatore DIVERSO dal richiedente
- agent **verify-only**: il job `delete_verify` (enum esistente) controlla che il file
  NON esista più sul volume; l'agent non cancella mai (coerente con security spec:
  "mai delete senza job approvato" — qui niente delete proprio, v1)
- gate transfer in lockdown = **whitelist destinazioni** per-tenant (design originale)

## 1. Distruzione doppia-conferma

**Modello `DestructionRequest`** (tabella nuova):
- `tenant_id`, `asset_id` FK (richiesto), `reason` Text (richiesto)
- `status` String FSM: `requested → approved → done | rejected | cancelled`
  (terminali immutabili; rejected da requested; cancelled da requested/approved
  SOLO dal richiedente o admin)
- `requested_by_user_id`, `approved_by_user_id`, `closed_by_user_id`
- `executed_method` String nullable: `manual | agent_verify`
- `agent_job_id` FK nullable, `created_at/updated_at/closed_at`

**Permesso RBAC**: `approve_destruction` ("Approvazione distruzione asset (TPN)")
nella categoria storage/TPN del registry `PERMISSIONS` in rbac.py; aggiunto ai
preset admin (guarda PRESET_PERMISSIONS).

**Service `app/services/destruction.py`:**
- `request_destruction(db, *, asset, reason, user_id)` → richiesta + notifica
  `notify_permission("approve_destruction", ...)`. ValueError se esiste già una
  richiesta attiva (requested/approved) per lo stesso asset, o reason vuota.
- `approve(db, req, *, user_id)` → ValueError se user_id == requested_by_user_id
  ("doppia conferma: serve un approvatore diverso") o stato ≠ requested. Il GATE
  RBAC sul permesso sta nel router.
- `reject(db, req, *, user_id, reason=None)` → da requested.
- `execute_manual(db, req, *, user_id)` → solo da approved: finalizza (sotto).
- `enqueue_verify(db, req, *, user_id)` → solo da approved e asset registrato
  (volume+rel_path): AgentJob `delete_verify` payload {volume_id, rel_path,
  request_id}; executed_method=agent_verify.
- `apply_verify_result(db, job, result)`: `result["exists"] is False` → finalizza;
  True → richiesta resta approved + notifica "file ancora presente sul volume".
- **Finalizza** (`_finalize`): `AssetMovement` `movement_type=destroyed` (NUOVO
  membro enum `AssetMovementType.destroyed` — colonna VARCHAR, verifica assenza
  CHECK su asset_movements come fatto per agent_jobs) con contents_description
  = reason; `content_state`: membership tape ATTIVE presenti → `archived_only`
  (copie residue), altrimenti `deleted`; status=done; notifica al richiedente.

**Agent**: ramo `delete_verify` in handle_job (PRIMA del guard vol? no — payload ha
volume_id top-level, ramo normale): risolve path (guard traversal riuso), ritorna
`{"exists": os.path.isfile(full)}`. Niente cancellazione. Wiring in
process_job_result (failed → notifica via apply, done → apply_verify_result).

## 2. Dashboard "dove vive ogni asset" + report storage

**Endpoint `GET /storage/api/asset-map`** (RequireStorage, filtri `content_state`,
`volume_id`, `q` su filename, limit 500): per ogni Asset registry confermato
(proposed_state=confirmed, tenant) → `{id, filename, content_state, volume
{id,name}|null, tapes [{id,label}] (membership attive batch), preview_status,
transfer_count (ordini done che lo includono — count batch su asset_ids JSON:
fai in Python sui 500), deliverable {id,name}|null (digital_asset_id reverse:
batch), destruction_pending bool}`. Tutto batch, no N+1.

**Endpoint `GET /storage/api/storage-report`** (RequireStorage): aggregati:
- `volumes`: per volume {name, asset_count, bytes_total, free_gb/total_gb}
- `tapes`: per PhysicalAsset kind=lto {label, file_count, bytes_total} (membership attive)
- `content_states`: conteggi per stato
- `orphan_memberships`: count
- `previews`: {count, bytes_total} da Asset.preview_status=ready local (somma size file se esiste, tolleranti)
- `pending`: {proposals, tickets_open, transfers_open, destructions_open}

**UI `/storage` 7° tab "🗺 Mappa"**: in alto card riepilogo (da storage-report:
volumi/tape/stati/pendenti); sotto tabella mappa con filtri (stato contenuto,
volume, ricerca) — colonne: File, Stato (badge: online verde/archived_only ambra/
deleted grigio barrato), Volume, Tape(s), Preview (✓/—), Transfer (n), Deliverable,
Azioni: "🗑 Richiedi distruzione" (modal reason) se non pending; se pending badge
"distruzione richiesta". Sezione sotto la tabella: "Distruzioni in corso" (lista
requested/approved con azioni: Approva [solo con permesso, disabilitato se
richiedente è l'utente], Rifiuta, "Fatto a mano", "Verifica via agent", Annulla).

## 3. TPN gate transfer (da F5)

- `Tenant` += `transfer_destination_whitelist` JSON nullable (lista stringhe) +
  auto-migrate colonna.
- `egress_guard.py` += `transfer_allowed(tenant, destination) -> bool` e
  `assert_transfer_allowed(tenant, destination)`: lockdown_master=="LOCKDOWN" →
  destination deve contenere (case-insensitive) almeno una voce della whitelist;
  whitelist vuota/None → blocco totale; OPEN → sempre consentito. Solleva
  `EgressLocked` (classe esistente) con vector="transfer".
- `create_order` (transfer_orders.py): chiama `assert_transfer_allowed` (carica
  tenant). Router già converte EgressLocked→403 (verifica handler esistente).
- UI /settings tab Sicurezza: textarea "Destinazioni transfer consentite in
  lockdown (una per riga)" salvata con gli altri toggle (endpoint esistente del
  pannello Sicurezza — estendilo).

## Test (TDD)

- destruction: doppia richiesta attiva, approvatore==richiedente vietato, FSM,
  finalize con/senza membership tape (deleted vs archived_only), movimento
  destroyed, verify result exists True/False, notifiche.
- agent: delete_verify exists/assente + traversal.
- asset-map/report: shape, filtri, batch (no N+1 sui 500), tenant.
- egress: OPEN sempre ok; LOCKDOWN whitelist match/no-match/vuota; create_order 403.
- E2E `tools/_e2e_f6.py`: request→approve (altro utente)→agent verify (file
  rimosso) → done + movimento + content_state corretto con e senza tape;
  asset-map riflette; lockdown blocca transfer non whitelistato e consente
  whitelistato.

## Fuori scope

Delete attivo da agent (resta verify-only), retention/purge automatica preview,
report schedulati/PDF, mappa per PhysicalAsset non-LTO.
