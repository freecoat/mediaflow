# Media Library — Fase B: azioni (associa / archivia / export / unlink + supersede)

> Design approvato 13 lug 2026. Segue Fase A (α.172.244, `/media` read-only).
> Ramo di lavoro: continua su `feat/media-library`.

## Obiettivo

Attivare le azioni mutanti oggi disabilitate nel browser `/media` (Fase A):
**Associa a consegna**, **Archivia/marca**, **Export CSV**, **Unlink**. Introdurre
la semantica **supersede**: un file riprodotto (errore o QC negativo) viene
ri-associato alla consegna, sostituendo il precedente asset attivo della stessa
natura, che resta come **storico** (non cancellato). Il supersede fa
**auto-reset** dello stato della consegna.

Tutte le mutazioni sono dietro il gate RBAC `manage_assets` (già introdotto in
Fase A). `media_library.py` resta read-only; le azioni vivono in un servizio
separato `media_actions.py` (confine pulito).

## Vincoli di progetto (invarianti)

- **Tenant filter** su ogni query: `tenant_id == current_tenant_id()`.
- **Visibilità TPN**: le azioni operano solo su asset/consegne accessibili
  all'utente (riuso `accessible_project_ids` / `is_admin`, come in `media_library.py`).
- **Form-based API**: i POST accettano `Form(...)`, non JSON puro. Liste (items)
  passate come stringa JSON in un campo Form.
- **Soft-delete / storico**: mai DELETE fisico dei link superati; supersede via
  colonne di stato.
- **i18n**: ogni stringa UI nuova in 5 lingue (`it/en/fr/de/es`) in `i18n.js`,
  stesso commit.
- **Cache-buster**: nessun nuovo static file (si estende `media_library.js`); il
  bump versione a fine fase invalida comunque `?v=`.
- **Riuso**: `deliverable_assets.link_asset/unlink_asset` (dedup + resync FK
  cache) è la fonte di verità per i link. `qc_cascade.cascade_qc_reject` è il
  pattern di riferimento per reset stato + notifica (NON riusato tal quale: il
  supersede è manuale e più leggero).

## Decisioni prese (brainstorming)

- **Supersede automatico**: associare un asset a una consegna che ha già un
  asset attivo della stessa natura → il vecchio diventa superseded, il nuovo
  attivo. Storico mantenuto.
- **Auto-reset stato**: su supersede, se `deliverable.status ∈ {qc, delivered,
  closed}` → `status = in_progress`, `qc_substatus = None` (il file c'è, pronto
  per re-QC/review). Se già `planned`/`in_progress`: nessun cambio.
- **Target picker**: modal a cascata Progetto→Job→Consegna **+** campo ricerca
  consegna nello stesso modal.
- **Export**: **CSV**. Senza selezione → esporta il **filtro corrente** (tutti i
  risultati del filtro, non solo la pagina).
- **Confine**: `media_actions.py` separato da `media_library.py`.

## Modello dati

### `DeliverableAsset` — nuove colonne
Migrazione idempotente `scripts/migrate_deliverable_asset_supersede.py` (pattern
`scripts/migrate_*.py`, ALTER TABLE grezzo + `_auto_migrate_columns` al boot in
`main.py` per non rompere DB non migrati):

| Colonna | Tipo | Note |
|---|---|---|
| `superseded_at` | `DateTime` nullable, index | link attivo ⇔ `superseded_at IS NULL` |
| `superseded_by_id` | `Integer` FK `deliverable_assets.id` nullable | link che lo ha sostituito |
| `supersede_reason` | `String(255)` nullable | es. "QC negativo", "errore render" |

### `_resync_primary` (in `deliverable_assets.py`)
Aggiornare la scelta del primario per **ignorare le righe superseded**
(`superseded_at IS NOT NULL`), in aggiunta all'esclusione `source='qc_report'`
già presente. Nessuna modifica alla firma pubblica di `link_asset`/`unlink_asset`.

## Servizio — `app/services/media_actions.py`

Read-write, tenant-scoped, riusa `link_asset`/`unlink_asset`. Nessuna funzione
committa (commit gestito dal router), coerente con il resto del codebase.

### `associate(db, user, *, deliverable_id, items, reason=None) -> dict`
- `items`: lista `[{"nature": "digital"|"physical", "id": int}]`.
- Carica il `JobDeliverable` (tenant + accessibile, altrimenti errore → 404 nel router).
- Per ogni item:
  - Individua l'eventuale link **attivo** della **stessa natura** già presente
    sulla consegna (`superseded_at IS NULL`, `asset_id`/`physical_asset_id` valorizzato).
  - Chiama `link_asset(db, deliverable, asset_id=… | physical_asset_id=…, source="manual", user_id=user.id, notes=reason)`.
  - Se esisteva un attivo diverso della stessa natura → marcalo superseded:
    `superseded_at=now`, `superseded_by_id=<nuovo link>.id`, `supersede_reason=reason`.
- Se **almeno un** supersede è avvenuto e `deliverable.status ∈ {qc, delivered,
  closed}` → `status=in_progress`, `qc_substatus=None`, e
  `notify_permission(view_finance, kind="deliverable_reopened_supersede", …)`
  (best-effort, non bloccante, `commit=False`).
- Return: `{"linked": n, "superseded": m, "status_reset": bool}`.

### `set_flags(db, user, items, *, internal_archive=None, delivered_external=None) -> dict`
- Toggle bulk dei flag ortogonali su Asset (digital) e PhysicalAsset (physical).
- `None` = non toccare; `True`/`False` = imposta. Tenant + visibilità.
- Return `{"updated": n}`.

### `unlink(db, user, *, deliverable_id, items) -> dict`
- Per ogni item: `unlink_asset(db, deliverable, asset_id=… | physical_asset_id=…)`.
- Return `{"removed": n}`.

### `export_manifest_csv(db, user, *, items=None, filters=None) -> str`
- Se `items` valorizzato: esporta quegli asset. Altrimenti usa `filters` →
  `media_library.list_assets` (senza paginazione, cap di sicurezza es. 5000 righe,
  con `log` se troncato).
- Colonne CSV: `nature, name, type, project_code, client, department,
  delivery_status, linked_to_delivery, checksum, size_bytes, storage_path, created_at`.
- Ritorna stringa CSV (UTF-8, header). Il router la serve come download.

## Router — `app/routers/media.py` (estensione)

Gate `manage_assets` su tutte. POST `Form(...)`.

| Metodo | Path | Corpo | Risposta |
|---|---|---|---|
| POST | `/media/api/associate` | `deliverable_id`, `items` (JSON str), `reason?` | `{linked, superseded, status_reset}` |
| POST | `/media/api/flags` | `items` (JSON str), `internal_archive?`, `delivered_external?` | `{updated}` |
| POST | `/media/api/unlink` | `deliverable_id`, `items` (JSON str) | `{removed}` |
| GET | `/media/api/export` | query filtri **o** `items` (JSON str) | CSV `text/csv` (Content-Disposition attachment) |
| GET | `/media/api/deliverables` | `project_id?`, `job_id?`, `q?` | `[{id, name, job, project, status}]` per il modal |

`404` se `deliverable_id` inesistente/non accessibile. `400` su `items` malformato.

## UI — `media_library.html` + `media_library.js`

- **Bulk bar**: abilitare i 3 bottoni esistenti (Associa / Archivia / Export) +
  aggiungere **Unlink**. Attivi solo con selezione ≥1 (Export attivo sempre:
  usa il filtro corrente).
- **Modal Associa** (nuovo markup): dropdown cascata Progetto→Job→Consegna
  (popolati via `GET /media/api/deliverables`) + campo ricerca consegna (filtra
  in-modal) + campo `reason` opzionale + avviso "sostituirà l'asset attivo
  esistente della stessa natura" + conferma. Su conferma → POST associate → toast
  esito → reload lista + chiudi modal.
- **Archivia**: piccolo menu (marca/smarca archivio interno, marca/smarca
  consegnato) → POST flags → reload.
- **Export**: bottone → naviga a `GET /media/api/export?…` (download).
- **Unlink**: richiede una consegna target (riusa modal minimale o input) → POST unlink.
- **Dettaglio**: nella lista `deliverables` mostrare i link superseded barrati con
  badge "superseduto" (l'API detail espone già i deliverable; estendere per
  includere lo stato supersede del link).
- **i18n**: nuove chiavi `media.assoc*`, `media.archive*`, `media.export*`,
  `media.unlink*`, `media.superseded`, `media.reason`, ecc. in 5 lingue.

## Gestione errori

- Ogni mutazione è transazionale nel router: `try` → chiama servizio → `commit`;
  su eccezione → `rollback` + `500` (o `400`/`404` per input/entità).
- La notifica di supersede è best-effort (try/except, non blocca la mutazione).
- Export: cap righe (5000) con log se troncato — no silent truncation.
- `link_asset` valida XOR digital/physical; il servizio costruisce i kwargs
  corretti per natura.

## Testing

- **`tests/test_media_actions.py`** (unit, sessione in-memory come Fase A):
  - associate: crea link, riga pivot attiva; item multipli.
  - supersede: linkare nuovo asset stessa natura su consegna con attivo →
    vecchio `superseded_at` valorizzato + `superseded_by_id` = nuovo; primario
    (`digital_asset_id`) = nuovo.
  - auto-reset: consegna `delivered` → dopo supersede `in_progress`,
    `qc_substatus=None`; consegna `in_progress` → invariata.
  - notifica: mock `notify_permission`, verifica chiamata su supersede da stato QC/delivered.
  - set_flags: toggle internal_archive/delivered_external su digital e physical.
  - unlink: rimuove riga pivot, resync primario.
  - export CSV: header + righe attese, cap.
  - tenant-scope + visibilità: asset/consegna di altro tenant → errore/nessun effetto.
- **`tests/test_media_api.py`** (estensione): nuovi endpoint con gate JWT-cookie,
  200/404/400, download CSV (content-type + header), viewer → 403.
- **Smoke Playwright**: DB copia con 1 consegna `delivered` + asset; login admin →
  `/media` → seleziona asset → modal Associa → conferma con supersede → verifica
  toast, badge "superseduto" nel dettaglio, stato consegna tornato `in_progress`,
  **0 errori console**.

## Fuori scope (Fase B)

- QC automatico / event-sourcing (resta in `qc.py`).
- Upload file (Media Library non fa upload: associa file esistenti).
- Multi-select drag, undo temporizzato (le azioni sono reversibili via unlink /
  smarca / un-supersede in una fase successiva se servirà).
- Export ZIP dei file binari (i file non sono in storage locale).

## Self-review

- **Placeholder**: nessun TBD. Le colonne, gli endpoint, le firme servizio sono
  esplicite. La chiave i18n esatta è elencata come prefisso (`media.assoc*`) da
  espandere nel piano.
- **Consistenza**: `link_asset`/`unlink_asset` riusati ovunque; `_resync_primary`
  aggiornato in un solo punto; auto-reset stato in un solo punto (associate).
- **Scope**: singola fase, un piano. Modello (1 migrazione) + servizio + router +
  UI + test. Coerente con Fase A.
- **Ambiguità risolte**: export senza selezione = filtro corrente; auto-reset
  target = `in_progress`; supersede solo tra stessa natura; confine
  `media_actions.py` ≠ `media_library.py`.
