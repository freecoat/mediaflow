# Design — F4 LTO YoYotta (asset registry MAM)

**Data**: 2026-06-11 · **Versione target**: v3.5.0-alpha.172.214 · **Approvato da**: Matteo (remote, AskUserQuestion + OK design)

## Contesto

L'ingest MHL YoYotta oggi crea il PhysicalAsset LTO e incrementa la consegna
(`_volume_increment`, α.172.207), ma NON registra i singoli file sul tape: il
residuo "per-file AssetMembership da MHL" è il cuore di F4. In più: ticket
archivio/restore assistito (YoYotta write-side resta fuori scope) e QR tape
come lookup del contenuto.

Decisioni Matteo: match checksum + fallback nome/size · entità ArchiveTicket
dedicata · QR solo lookup informativo (chiusura ticket da desktop) · MHL + CSV
generico subito.

## 1. Backfill membership da catalogo (MHL + CSV)

**Service nuovo `app/services/lto_catalog.py`:**
- `ingest_catalog_entries(db, physical_asset, entries, *, user_id) -> dict`
  - `entries`: lista `{filename, size_bytes, checksum, path}` (output di
    `mhl_parser.parse_mhl_bytes` o del nuovo parser CSV).
  - Match Asset tenant-scoped: 1) `Asset.checksum_xxhash == checksum` (case-insensitive),
    2) fallback `filename + file_size` (solo se match unico — ambiguo = orfana).
  - Crea `AssetMembership(physical_asset_id, asset_id?, path_on_media, checksum,
    file_size, added_by)`. Entry senza match → membership **orfana** (`asset_id NULL`).
  - **Dedup su re-ingest**: membership attiva (removed_at NULL) stesso physical +
    stesso checksum (o stesso path se checksum assente) → skip.
  - Ritorna `{"matched": n, "orphan": n, "skipped": n}`.
- `parse_catalog_csv(data: bytes, mapping: dict | None) -> list[entry]`
  - Auto-detect header comuni (name/file/filename · size/bytes/length ·
    hash/checksum/md5/xxhash · path/directory/folder), delimitatore sniffato
    (`csv.Sniffer`, fallback `,`). `mapping` opzionale `{colonna_csv: campo}`
    per CSV non riconosciuti. ValueError se manca almeno filename.

**Migrazione**: `AssetMembership.asset_id` diventa NULLABLE (membership orfane).
SQLite non rilassa NOT NULL via ALTER → **table-rebuild** idempotente al boot
(pattern AudioTrackSpec α.172.202).

**Wire-up:**
- `/ingest/yoyotta-mhl` (ingest_deliverables.py): dopo la creazione del
  PhysicalAsset chiama `ingest_catalog_entries`; response += stats membership.
- Nuovo `POST /physical-assets/api/{id}/catalog-csv` (upload CSV su tape
  esistente, Form file + mapping JSON opzionale) → stesse stats.

Il backfill NON tocca `Asset.content_state` (lo fanno solo i ticket, esplicito).

## 2. ArchiveTicket

**Modello `ArchiveTicket`** (auto-migrate, tabella nuova):
- `kind`: `archive | restore` · `status`: `requested | in_progress | done | cancelled`
- target: `asset_id` (nullable) e/o `job_deliverable_id` (nullable) — almeno uno
- `physical_asset_id` nullable (tape: per restore suggerito automaticamente dalla
  membership attiva più recente dell'asset; per archive compilato a posteriori)
- `requested_by_user_id`, `assigned_to_user_id` (nullable), `note`,
  `created_at/updated_at/closed_at`, `closed_by_user_id`
- Soft lifecycle via status (niente delete).

**Service `app/services/archive_tickets.py`:**
- `create_ticket(db, *, kind, asset=None, deliverable=None, note, user_id)` —
  per restore: risolve tape suggerito da membership; notifica
  `notify_permission("edit_planning_all", ...)` (ruolo storage).
- `transition(db, ticket, new_status, *, user_id)` — guardia transizioni
  (requested→in_progress→done; cancelled da requested/in_progress).
  - restore→done: notifica il richiedente (`notify`) + se asset →
    `content_state = online`.
  - archive→done: se asset ha membership LTO attiva → `content_state =
    archived_only`; senza membership → 409 ("ingest prima il catalogo del tape").

**Router**: endpoint sotto `/storage/api/tickets` (RequireStorage, Form-based):
list (filtri kind/status), create, transition. Serializer con nomi risolti
(asset filename, tape code/name, utenti).

## 3. UI

- **/storage tab nuovo "🎫 Ticket"**: tabella (tipo, target, tape, stato badge,
  richiedente, età), filtri stato/tipo, bottoni transizione per riga
  (Prendi in carico / Fatto / Annulla), modal "Nuovo ticket" (kind + ricerca
  asset per nome via endpoint esistente o input id + note).
- **physical_assets.html (scheda tape)**: sezione "📼 File sul supporto" —
  membership attive (filename o `(non collegato)` per orfane, path, size) +
  conteggio; bottone "♻️ Richiedi restore" per riga collegata (crea ticket
  restore precompilato); upload "Catalogo CSV".
- **physical_asset_scan.html (QR)**: sezione read-only contenuto (membership
  attive) + ticket aperti sul tape. Nessuna azione.

## 4. Sicurezza
- Tutti gli endpoint nuovi: tenant filter + RequireStorage (o auth scan
  esistente per la pagina QR).
- CSV: size cap 10 MB, niente esecuzione/formule (solo parsing testo).

## Test (TDD)
- lto_catalog: match checksum, fallback nome+size (unico vs ambiguo), orfane,
  dedup re-ingest, CSV auto-detect + mapping + errori.
- Migrazione table-rebuild: asset_id nullable preservando righe esistenti.
- archive_tickets: create con tape suggerito, transizioni legali/illegali,
  content_state su done, 409 archive senza membership, notifiche chiamate.
- Router: CRUD ticket + ingest MHL ritorna stats + upload CSV.
- E2E `tools/_e2e_f4.py`: MHL sintetico con 2 file (1 match checksum asset
  registry, 1 orfana) → ingest → membership; ticket restore → done → notifica
  + content_state.

## Fuori scope
YoYotta Automation API, job agent lto_archive/lto_restore, chiusura ticket da
QR, CSV proprietari non riconosciuti dall'auto-detect (mapping manuale li copre),
verifica periodica contenuto tape.
