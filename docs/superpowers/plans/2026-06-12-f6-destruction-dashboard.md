# F6 Distruzione + Dashboard + Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distruzione asset con doppia conferma (RBAC) + verify agent-side, dashboard "dove vive ogni asset", report storage, gate TPN whitelist sui transfer.

**Architecture:** Spec `docs/superpowers/specs/2026-06-12-f6-destruction-dashboard-design.md` — LEGGILA PRIMA, contiene tutte le decisioni. Pattern di riferimento nel repo: F4 ArchiveTicket (FSM service+router+tab), F5 transfer (agent ramo+wiring esiti), egress_guard α.172.195 (lockdown), tab /storage F4/F5.

**Convenzioni:** identiche a F4/F5 (tenant filter, Form-based, naive UTC now_utc, fixture client_admin tests/test_f4_endpoints.py, Asset ctor original_name/asset_type/uploaded_by, `.venv/Scripts/python`, commit con Co-Authored-By Claude Fable 5).

---

### Task 1: Enum `destroyed` + modello `DestructionRequest` + permesso RBAC

**Files:** Modify `app/models/models.py` (AssetMovementType + nuova classe dopo TransferOrder), `app/models/__init__.py`, `app/services/rbac.py` (PERMISSIONS + PRESET admin); Test `tests/test_f6_model.py`

- [ ] Test RED: AssetMovementType.destroyed esiste; DestructionRequest default status requested/created_at; verifica via sqlite3 PRAGMA che asset_movements NON abbia CHECK constraint sull'enum (leggi sql da sqlite_master in un engine in-memory create_all — il VARCHAR non vincola); permesso "approve_destruction" in ALL_PERMISSION_KEYS di rbac e nei preset admin.
- [ ] Implementa: `destroyed = "destroyed"` in AssetMovementType (commento: F6 distruzione documentata); modello DestructionRequest (colonne spec §1, stile TransferOrder); rbac.py: chiave `approve_destruction` con label "Approvazione distruzione asset (TPN)" nella categoria dove sta manage_cloud_lockdown + aggiungila al preset admin in PRESET_PERMISSIONS.
- [ ] GREEN + regressione `-k "movement or rbac"` → commit `feat(F6): enum destroyed + modello DestructionRequest + permesso approve_destruction`.

### Task 2: Service `destruction.py` + agent delete_verify + wiring

**Files:** Create `app/services/destruction.py`; Modify `agent/main.py` (ramo delete_verify), `app/routers/agent_api.py` (wiring); Test `tests/test_f6_destruction.py`

- [ ] Test RED (monkeypatch notify/notify_permission; helper asset con/senza membership tape attiva — vedi tests/test_f4_archive_tickets.py per il setup membership LTO):
  1. request_destruction → requested + notify_permission("approve_destruction"); reason vuota → ValueError; seconda richiesta attiva stesso asset → ValueError
  2. approve con user==richiedente → ValueError "approvatore diverso"; con altro user → approved
  3. reject da requested ok; da approved → ValueError
  4. execute_manual da approved → done + AssetMovement destroyed (contents_description=reason) + content_state deleted (senza membership) / archived_only (con membership tape attiva) + notifica richiedente
  5. execute_manual da requested → ValueError
  6. enqueue_verify da approved con asset registrato → AgentJob delete_verify payload {volume_id, rel_path, request_id}, executed_method=agent_verify; asset non registrato → ValueError
  7. apply_verify_result exists=False → finalizza come execute_manual; exists=True → resta approved + notifica "ancora presente"
  8. cancelled da requested/approved; terminali immutabili
- [ ] Implementa service (FSM pattern F4/F5; _finalize condiviso; flush no commit). Agent main.py ramo `delete_verify` (payload volume_id top-level → ramo normale dopo guard vol): risolvi full path con la STESSA logica traversal di transfer/browse → `return "done", {"exists": os.path.isfile(full), "request_id": payload.get("request_id")}, None`. CAPABILITIES += "delete_verify". Wiring process_job_result: done → `destruction.apply_verify_result` (try ValueError → print, return None — pattern transfer); failed → notifica? usa apply analogo `apply_verify_failure(db, job, error)` che notifica il richiedente (richiesta resta approved).
- [ ] GREEN + regressione agent → commit `feat(F6): service destruction doppia-conferma + agent delete_verify`.

### Task 3: TPN gate transfer (whitelist)

**Files:** Modify `app/models/models.py` (Tenant += transfer_destination_whitelist JSON), `app/main.py` (auto-migrate colonna tenants), `app/services/egress_guard.py`, `app/services/transfer_orders.py` (create_order), router/UI Sicurezza (trova il pannello: grep "Sicurezza"/"lockdown" in app/routers e templates/pages/settings.html); Test `tests/test_f6_transfer_gate.py`

- [ ] Test RED: transfer_allowed OPEN → True sempre; LOCKDOWN whitelist ["aspera.netflix.com","backlot"] + destination "user@aspera.netflix.com:/in" → True; "user@evil.com:/x" → False; whitelist vuota/None → False; assert_transfer_allowed solleva EgressLocked(vector="transfer"); create_order in lockdown senza match → EgressLocked; endpoint POST /storage/api/transfers in lockdown → 403 (verifica che l'handler EgressLocked esistente copra il router storage — se EgressLocked→403 è gestito da exception handler globale ok, altrimenti catch nel router); salvataggio whitelist dal pannello Sicurezza round-trip.
- [ ] Implementa: colonna+migrate; funzioni egress_guard (stile assert_cloud_ai_allowed esistenti, match substring case-insensitive); create_order carica Tenant (db.get) e chiama assert; estendi endpoint save del pannello Sicurezza (textarea → righe non vuote → JSON) + textarea nel template con hint; GET del pannello espone la lista.
- [ ] GREEN → commit `feat(F6): gate TPN transfer — whitelist destinazioni in lockdown`.

### Task 4: Endpoint asset-map + storage-report + endpoint distruzione

**Files:** Modify `app/routers/storage_admin.py`; Test `tests/test_f6_endpoints.py`

- [ ] Test RED: GET /storage/api/asset-map (shape spec §2: volume/tapes/preview_status/transfer_count/deliverable/destruction_pending; filtri content_state/volume_id/q; solo confirmed; tenant) — semina 2 asset con tape membership e deliverable link; GET /storage/api/storage-report (chiavi volumes/tapes/content_states/orphan_memberships/previews/pending); POST /storage/api/destructions (Form asset_id, reason) → 200; GET /storage/api/destructions?status=; POST /{id}/approve → 403 senza permesso approve_destruction (crea secondo user/role senza permesso e cookie relativo — pattern multi-user nei test esistenti? se complicato: testa il gate con client_admin che HA il permesso → 200, e il divieto richiedente==approvatore → 400), /reject, /execute-manual, /enqueue-verify, /transition cancelled. ValueError→400, 404 tenant.
- [ ] Implementa: endpoint distruzione con gate `requires_permission("approve_destruction")` SOLO su /approve (gli altri RequireStorage); asset-map e storage-report tutto batch (collect ids → IN query → dict; transfer_count: carica ordini done del tenant una volta e conta in Python su asset_ids JSON; deliverable reverse: select JobDeliverable where digital_asset_id IN). Limit 500 asset-map con `log` implicito nel payload `{"truncated": bool}`.
- [ ] GREEN → commit `feat(F6): endpoint asset-map, storage-report, distruzioni`.

### Task 5: UI tab 🗺 Mappa

**Files:** Modify `app/templates/pages/storage.html`

- [ ] 7° tab "🗺 Mappa" (pattern F4/F5): card riepilogo da storage-report (4-6 card: volumi con barre libero/totale, tape count, stati contenuto, pendenti); filtri (select stato, select volume, input ricerca con debounce 300ms); tabella mappa (File, Stato badge — deleted barrato grigio, Volume, Tapes (labels), Preview ✓/—, Transfer n, Deliverable, Azioni); azione "🗑" → modal reason → POST destructions; badge "🗑 richiesta" se destruction_pending. Sezione "Distruzioni in corso": lista requested/approved con bottoni Approva (POST approve — il 403 senza permesso arriva come toast)/Rifiuta/Fatto a mano/Verifica agent/Annulla (confirm su tutti i distruttivi). Vincoli JS soliti (data-*, escapeHtml, niente Jinja nei commenti, funzioni definite nello stesso script).
- [ ] Verifiche: jinja parse, grep onclick, pytest -k f6 verde → commit `feat(F6): UI tab Mappa — dove vive ogni asset + distruzioni + report`.

### Task 6: E2E + bump + push

**Files:** Create `tools/_e2e_f6.py`; Modify `app/main.py` (3.5.0-alpha.172.216), CHANGELOG, STATO

- [ ] E2E (pattern _e2e_f5, tmp dir reale come volume): asset con file vero → request (user A) → approve con stesso user → 400 → approve con permesso (client admin: simula secondo utente o usa il path service con user_id diverso via endpoint? se il client è uno solo: crea la richiesta via API con requested_by detto dall'utente admin, poi approva via service con user_id diverso INACCETTABILE per E2E API-only — soluzione: crea un secondo utente+role con approve_destruction e secondo TestClient con suo cookie) → enqueue-verify → claim agent → handle_job (file ANCORA presente) → result → resta approved + notifica → cancella il file → secondo enqueue-verify → handle_job → exists False → done + movimento destroyed + content_state deleted; variante con membership tape → archived_only; asset-map riflette (deleted + destruction assente); storage-report conta; lockdown: set tenant LOCKDOWN + whitelist → transfer non whitelistato 403, whitelistato 200.
- [ ] Suite completa 0 failed; bump; CHANGELOG (chiusura roadmap MAM F1→F6!); STATO (Prossimo: smoke Matteo + backlog MAM consolidato); graphify; export ZIP; commit; push.

## Self-review (fatto)
- Spec coverage: §1→T1/T2/T4/T5, §2→T4/T5, §3→T3, E2E→T6. ✔
- Tipi coerenti: FSM stringhe come F4/F5; result delete_verify {exists, request_id}; whitelist lista stringhe. ✔
- Nessun placeholder: i "trova/leggi X" sono ricerche obbligatorie su codice esistente. ✔
