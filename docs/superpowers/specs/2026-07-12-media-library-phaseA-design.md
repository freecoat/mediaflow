# Media Library — Fase A: browser unificato (read + filtri + selezione)

> Spec di design. Data: 2026-07-12. Ramo: `feat/mobile-responsive-email` (o nuovo ramo `feat/media-library`).
> Parte del redesign **Media Library** deciso con Matteo (feedback /remote-control).
> Decomposizione concordata: **A → C → B → D** (questa spec copre solo **A**).

## Contesto e scoperta chiave

Il modello dati per la catena `quotazione → planning → delivery → asset` **esiste già** ed è solido:
`QuoteLine.delivery_item_id → JobDeliverable → BookingDeliverable → DeliverableAsset (pivot M:N) → Asset / PhysicalAsset`.
Esistono già: registro metadata-only (`Asset` con `rel_path`/`agent://`, upload media vietato), filesystem scan + agent watch + auto-match (`fs_scan.py`, `asset_registry.py`, `deliverable_match.py`, `storage_admin.py`), pattern link-not-store (`DocumentLink`/`EmailLink`).

**Il gap non è lo schema — è UI/UX + consolidamento.** Oggi la UX è frammentata in silos: `/dam` (digitale, orientato upload), `/physical-assets` (fisico), `/storage` (proposte agent), `/dam/fs-scan` (import path). Manca una **Media Library unica**: browser globale con filtri multipli per selezionare asset.

**Decisioni Matteo (brainstorming 2026-07-12):**
1. Forma = **browser globale con filtri multipli** (non deliveries-first).
2. Scope = **unifica tutto** (assorbe /dam + /physical-assets + /storage).
3. Azioni sulla selezione (fasi successive): associa a delivery, cambia stato bulk, registra da file esistente, esporta/report, **esplora file su percorso → importa metadata (riusa agenti esistenti)**.
4. Filtri = tutti e 4 i gruppi (contesto, natura&tipo, stato&workflow, storage&tecnici), **tech-specs inclusi da subito**.
5. Ordine fasi = A→C→B→D.

## Obiettivo Fase A

Costruire la **fondazione + il browser in sola lettura**: una route `/media` che elenca in modo unificato asset digitali (`Asset`) e fisici (`PhysicalAsset`) del tenant, con i 4 gruppi di filtri (inclusi tech-specs), ricerca, selezione multipla e pannello dettaglio. Nessuna azione mutante in A (la barra selezione mostra i pulsanti bulk **disabilitati** come placeholder; si attivano in C/B).

### Non-goal di Fase A (fasi successive)
- **Fase C**: file explorer, registra-da-path, import metadata, assorbimento /storage + fs-scan.
- **Fase B**: associa-a-delivery (`deliverable_assets.link_asset`), azioni stato bulk, conferma proposte.
- **Fase D**: export CSV, redirect/ritiro vecchie route, cleanup.

## Architettura

### Route + router
- Nuovo file `app/routers/media.py` (pulito; i silos si ritirano in Fase D — nessun merge dentro `dam.py`).
- `GET /media` → `templates/pages/media_library.html` (pagina shell + JS).
- API read-only:
  - `GET /media/api/assets` — lista filtrata + paginata (query param = filtri, `page_token`/`offset`, `limit`).
  - `GET /media/api/asset/{nature}/{id}` — dettaglio singolo (`nature` ∈ `digital|physical`).
  - `GET /media/api/filters` — opzioni per i dropdown (progetti/clienti/job/reparti/volumi accessibili + enum tipi/stati/kind), già ristrette a ciò che l'utente può vedere.

### Serializer unificato — `app/services/media_library.py`
Funzione pura-ish `list_assets(db, user, filters, *, offset, limit) -> {rows, total, next_offset}` che:
1. Costruisce due query tenant-scoped: `Asset` (digitale) e `PhysicalAsset` (fisico), applicando i filtri pertinenti a ciascuna natura.
2. Applica la **visibilità TPN**: solo progetti accessibili all'utente (riusa l'helper già usato in `dam.py`); asset `project_id IS NULL` = coda interna (visibile secondo la stessa regola di /dam).
3. Fonde in righe omogenee con schema comune (sotto), ordina in modo deterministico, pagina.

**Schema riga unificata** (contratto verso il frontend):
```
{
  "nature": "digital" | "physical",
  "id": int,
  "name": str,                     # Asset.original_name|filename  /  PhysicalAsset.label
  "asset_type": str | null,        # video/audio/image/document/other (solo digital)
  "physical_kind": str | null,     # LTO/HDD/CRU/... (solo physical)
  "project": {"id", "code", "title"} | null,
  "client": {"id", "name"} | null,
  "department": {"id", "name"} | null,   # best-effort (vedi sotto)
  "delivery_status": str | null,   # status del JobDeliverable collegato (se uno solo); "multi" se >1
  "linked_to_delivery": bool,      # esiste almeno un DeliverableAsset per questo asset
  "proposed_state": str | null,    # pending_review/confirmed/discarded (solo digital, registro agent)
  "flags": {"internal_archive": bool, "delivered_external": bool},
  "storage": {"volume_id", "volume_name", "path"},  # path = rel_path|file_path | PhysicalAsset.location
  "checksum": str | null,          # checksum_xxhash (digital) / checksum (physical)
  "size_bytes": int | null,        # file_size (digital) / capacity/used (physical, informativo)
  "tech": {"resolution", "codec", "hdr", "frame_rate"} | null,  # da Asset.tech_specs_json (solo digital)
  "created_at": iso8601
}
```

**department (best-effort):** il reparto non è un FK diretto sull'asset. Derivazione: se l'asset è linkato a un `JobDeliverable` → `price_item.department`; altrimenti dal `job.department` se presente; altrimenti `null`. Il filtro department è quindi "best-effort": esclude gli asset senza reparto derivabile solo quando il filtro è attivo.

## Filtri (4 gruppi, combinabili in AND)

Tutti passati come query param a `GET /media/api/assets`. Vuoto = nessun vincolo.

| Gruppo | Param | Applica a | Mappatura query |
|---|---|---|---|
| **Contesto** | `project_id` | entrambi | `Asset.project_id` / `PhysicalAsset.project_id` |
| | `client_id` | entrambi | via `project.client_id` (join) |
| | `job_id` | entrambi | `.job_id` |
| | `department_id` | entrambi | best-effort (deliverable→price_item.department o job.department) |
| **Natura & tipo** | `nature` | selettore | `digital` → solo Asset; `physical` → solo PhysicalAsset; vuoto → entrambi |
| | `asset_type` | digital | `Asset.asset_type` (enum) |
| | `physical_kind` | physical | `PhysicalAsset.kind` (enum) |
| **Stato & workflow** | `delivery_status` | entrambi | join pivot → `JobDeliverable.status` |
| | `proposed_state` | digital | `Asset.proposed_state` (default lista = solo `confirmed`, come /dam; `?proposed_state=pending` per vedere le proposte agent) |
| | `internal_archive` | entrambi | `is_internal_archive` |
| | `delivered_external` | entrambi | `is_delivered_external` |
| | `linked_to_delivery` | entrambi | `yes` → EXISTS in `DeliverableAsset`; `no` → NOT EXISTS |
| **Storage & tecnici** | `volume_id` | digital | `Asset.storage_volume_id` |
| | `q` | entrambi | ricerca `LIKE` su name/original_name/rel_path/file_path/location |
| | `checksum` | entrambi | match esatto/prefix su checksum_xxhash / checksum |
| | `tech_resolution` | digital | `tech_specs_json ->> resolution` (es. "3840x2160", "1920x1080") |
| | `tech_codec` | digital | `tech_specs_json ->> codec` (es. "ProRes", "H.264") |
| | `tech_hdr` | digital | `tech_specs_json ->> hdr` (es. "HDR10"/"SDR"/"DolbyVision") |
| | `tech_frame_rate` | digital | `tech_specs_json ->> frame_rate` |

**Note tech-specs:** i valori vivono in `Asset.tech_specs_json` (cache ffprobe). In SQLite si filtra con `json_extract(tech_specs_json, '$.resolution')`. I dropdown tech in `GET /media/api/filters` sono popolati con i valori **distinti effettivamente presenti** negli asset del tenant (evita enum divergenti dai dati — cfr. [[feedback_ai_schema_descriptions]]). Se un asset non ha `tech_specs_json`, i filtri tech attivi lo escludono.

**Default vista:** senza filtri, la lista mostra asset `proposed_state = confirmed` (parità con /dam attuale). Un toggle "Mostra proposte agent" imposta `proposed_state=pending` per il workflow di conferma (azione in Fase B/C).

## API — contratti

```
GET /media/api/assets?<filtri>&offset=0&limit=50
 → { "rows": [<riga unificata>...], "total": int, "next_offset": int|null }

GET /media/api/asset/digital/{id}   /  GET /media/api/asset/physical/{id}
 → { <riga unificata> + dettaglio esteso: tutti i metadata, tech_specs_json completo,
     lista deliverable collegati [{id, job, status, source}], membership fisica (se digital),
     storia (created/registered_via/uploaded_by) }
 → 404 se non accessibile (tenant/TPN)

GET /media/api/filters
 → { "projects":[{id,code,title}], "clients":[{id,name}], "jobs":[{id,code}],
     "departments":[{id,name}], "volumes":[{id,name}],
     "asset_types":[...], "physical_kinds":[...], "delivery_statuses":[...],
     "tech": { "resolution":[...], "codec":[...], "hdr":[...], "frame_rate":[...] } }
```

Tutte le query partono da `tenant_id = CURRENT_TENANT` e applicano la visibilità progetti. Paginazione via `offset`/`limit` (default 50, max 200).

## UI — `pages/media_library.html` + `static/js/media_library.js`

- **Layout**: barra filtri in alto (riusa `MFFilterBar` se adatto, altrimenti markup coerente) con i 4 gruppi collassabili + campo ricerca `q` + toggle "Mostra proposte agent". Tabella sotto.
- **Tabella**: colonne = checkbox · nome · natura (icona digital/physical) · tipo · progetto/cliente · stato consegna · storage (volume/path troncato) · checksum (breve) · dimensione. Header ordinabili (ordine deterministico esplicito, cfr. convenzioni progetto). Righe con hover; click riga (non-checkbox) → pannello **dettaglio** laterale/modal.
- **Selezione multipla**: checkbox per riga + select-all (pagina) + **barra selezione** con conteggio e pulsanti bulk **disabilitati** con tooltip "disponibile a breve" (Associa a delivery / Cambia stato / Esporta) — placeholder per B/C/D. `_mediaSel` Set di chiavi `nature:id`.
- **Dettaglio**: pannello con tutti i metadata + `tech_specs_json` formattato + elenco deliverable collegati (link al job) + membership fisica. Read-only in A.
- **Paginazione**: "Carica altro" (append via `next_offset`).
- **i18n**: tutte le stringhe nuove nelle 5 lingue (`it/en/fr/de/es`) in `i18n.js` con `data-i18n` — nessun debito i18n ([[feedback_i18n_always]]).
- **Stile**: coerente con `main.css` + override `sleek.css` (aggiungere blocco `.media-*` come fatto per `.mail-*`).
- **Voce menu**: "Media Library" nel gruppo **Operativo** della sidebar (vicino a DAM). DAM/Physical/Storage restano finché Fase D non li ritira.

## RBAC — permesso `manage_assets`

- Aggiungere `manage_assets` al dizionario `PERMISSIONS` (categoria coerente, es. "Media/DAM").
- Dependency `RequireManageAssets` (pattern `RequireX` esistente). Gate su tutte le `/media/*`:
  **`manage_assets OR edit_planning_all`** (retrocompat: chi gestisce planning oggi vede già il DAM).
- Migrazione ruoli non distruttiva (`scripts/migrate_*.py`): concede `manage_assets` ai ruoli che hanno `edit_planning_all`. Idempotente.
- `manage_assets` è **read+write** concettualmente; in Fase A serve solo il read gate, ma lo introduciamo ora così le fasi B/C lo riusano.

## Testing (Fase A)

**Backend (`tests/test_media_library.py`):**
- Serializer: filtro per `nature` (solo digital / solo physical / entrambi); per `project_id`, `client_id`, `job_id`; per `delivery_status`; `linked_to_delivery` yes/no; `internal_archive`/`delivered_external`; `q` (nome/path); `checksum`; tech (`tech_resolution`/`tech_codec`/`tech_hdr` via json_extract); default `proposed_state=confirmed`; paginazione (`offset`/`limit`/`next_offset`); **tenant-scope** (non vede asset di altri tenant); riga unificata ha lo schema atteso per entrambe le nature.
- Router: `GET /media/api/assets` 200 con filtri; `/asset/{nature}/{id}` 200/404; `/filters` popola i dropdown; **gate RBAC** (utente senza `manage_assets`/`edit_planning_all` → 403).
- Pattern test router: JWT cookie reale + monkeypatch `database.engine`/`SessionLocal` (cfr. trappola `test_documents_api`).

**Smoke browser (Playwright, sleek ON):**
- `/media` rende; applica un filtro (es. nature=physical) → lista cambia; ricerca `q`; selezione multipla + select-all + conteggio barra; click riga → dettaglio; 0 errori console. (Con DB demo esistente: asset di seed o fixture.)

## Rischi / attriti noti (da tenere presenti anche per B/C/D)
- **Cache vs fonte di verità**: `JobDeliverable.digital_asset_id/physical_asset_id` sono cache di `DeliverableAsset`. In A (read) leggiamo il pivot come fonte per `linked_to_delivery`/`delivery_status`. In B ogni write passerà SOLO da `deliverable_assets.link_asset`.
- **Tre modi legacy di legare asset↔deliverable** (`Asset.job_deliverable_id`, `matched_deliverable_id`, pivot). In A il serializer considera il **pivot `DeliverableAsset`** come fonte per il conteggio link, e `matched_deliverable_id` come "proposta non confermata" (mostrata nel dettaglio, non conta come linked).
- **Performance**: due query separate + merge in Python. Con molti asset, paginare per natura e fondere può essere non banale sull'ordinamento globale. Mitigazione A: ordinamento di default `created_at DESC` con merge-sort delle due liste già ordinate; `limit` basso di default.
- **department best-effort**: documentato come derivato; se troppo costoso in query, in A può essere calcolato solo nel dettaglio e il filtro department rinviato a B (da confermare in fase di piano).

## Out of scope (esplicito)
Azioni mutanti, file explorer, registra-da-path, import metadata, export, redirect dei vecchi silos, nuovo schema/tabelle. Nessuna migrazione dati (solo migrazione RBAC ruoli).
