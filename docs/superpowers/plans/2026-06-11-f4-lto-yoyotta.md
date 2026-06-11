# F4 LTO YoYotta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catalogo per-file dei tape LTO (MHL + CSV → AssetMembership con match al registry) + ticket archivio/restore assistito + QR tape come lookup contenuto.

**Architecture:** Riusa `mhl_parser` (parse) e `AssetMembership` (storico N:M). Nuovo service `lto_catalog` per match+backfill; nuovo modello+service `ArchiveTicket`; UI in /storage (tab Ticket), scheda PhysicalAsset (file sul supporto) e pagina QR scan (lookup). Spec: `docs/superpowers/specs/2026-06-11-f4-lto-yoyotta-design.md` — leggila prima.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + SQLite (table-rebuild per rilassare NOT NULL), stdlib csv, vanilla JS.

**Convenzioni vincolanti:** tenant filter ovunque, Form-based POST, soft-delete/status (no DELETE), auto-migrate al boot in app/main.py (pattern blocchi F1/F3 adiacenti), commenti italiani, helper JS solo da global.js, niente Jinja in commenti JS. Test: fixture `client_admin` pattern `tests/test_f3_preview_upload.py` (Role permissions includano "edit_planning_all","view_finance","assign_resources"). Asset ctor nei test: `original_name`, `asset_type=AssetType.video`, `uploaded_by=1`. Python `.venv/Scripts/python`. Ogni task: TDD red→green→commit con `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Migrazione — `AssetMembership.asset_id` nullable (table-rebuild)

**Files:** Modify `app/models/models.py` (~L3248), `app/main.py` (lifespan auto-migrate); Test `tests/test_f4_membership_nullable.py`

- [ ] Test RED: crea membership con `asset_id=None` su DB in-memory (`Base.metadata.create_all`) → oggi TypeError/IntegrityError. Secondo test: simula DB legacy — crea engine file temp, crea tabella vecchia via SQL raw `CREATE TABLE asset_memberships (...asset_id INTEGER NOT NULL...)` con 1 riga, esegui la funzione di migrazione nuova `_rebuild_asset_memberships_nullable(engine)`, verifica: colonna nullable (PRAGMA table_info → notnull==0), riga preservata, INSERT con asset_id NULL ok.
- [ ] Implementa: nel modello `asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)`. In `app/main.py`: funzione `_rebuild_asset_memberships_nullable(engine)` — idempotente: PRAGMA table_info, se `asset_id` ha notnull=1 → rebuild (BEGIN; CREATE TABLE asset_memberships_new con DDL dal modello; INSERT INTO ... SELECT; DROP old; RENAME; ricrea indici). COPIA il pattern table-rebuild già esistente per AudioTrackSpec (grep "rebuild" o "audio_track_specs" in main.py / scripts — replica). Chiamala nel lifespan vicino agli altri auto-migrate.
- [ ] GREEN + regressione `tests/ -q -k "membership or physical"` → commit `feat(F4): AssetMembership.asset_id nullable (membership orfane da catalogo)`.

### Task 2: Service `lto_catalog` — backfill membership + parser CSV

**Files:** Create `app/services/lto_catalog.py`; Test `tests/test_f4_lto_catalog.py`

- [ ] Test RED (DB in-memory, helper asset con checksum_xxhash="abc123", size=100):
  1. match per checksum (case-insensitive) → membership con asset_id, stats matched=1
  2. checksum diverso ma filename+file_size unici → match fallback
  3. fallback ambiguo (2 asset stesso nome+size) → orfana
  4. nessun match → orfana (asset_id NULL, checksum/path/size salvati)
  5. dedup re-ingest: seconda chiamata stesse entries → skipped, niente doppioni
  6. dedup per path quando checksum assente
  7. `parse_catalog_csv`: header `File Name,Size,xxHash64,Path` auto-detect → entries normalizzate (size int)
  8. CSV con `;` come delimitatore (Sniffer) → ok
  9. CSV header ignoto senza mapping → ValueError; con mapping `{"colA":"filename",...}` → ok
  10. CSV senza colonna filename risolvibile → ValueError
- [ ] Implementa contratto (vedi spec §1):

```python
"""F4 (spec 2026-06-11) — Catalogo LTO: backfill AssetMembership da MHL/CSV."""
from __future__ import annotations
import csv, io
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.models import Asset, AssetMembership, PhysicalAsset
from app.services.clock import now_utc

_FIELD_ALIASES = {
    "filename": {"filename", "file", "name", "file name", "file_name"},
    "size_bytes": {"size", "size_bytes", "bytes", "length", "file size"},
    "checksum": {"checksum", "hash", "xxhash", "xxhash64", "md5", "c4id"},
    "path": {"path", "directory", "folder", "dir"},
}

def parse_catalog_csv(data: bytes, mapping: Optional[dict] = None) -> list[dict]:
    # decode utf-8-sig errors=replace; Sniffer su primo KB (fallback ',');
    # DictReader; risolvi header → campo via mapping esplicito PRIMA, poi
    # _FIELD_ALIASES (lower/strip). filename obbligatorio → ValueError.
    # size int tollerante (strip, '' → None). Ritorna lista entry dict.

def ingest_catalog_entries(db: Session, physical_asset: PhysicalAsset,
                           entries: list[dict], *, user_id: Optional[int]) -> dict:
    # esistenti: membership attive del tape (removed_at IS NULL) →
    #   set di checksum.lower() e set di path per dedup
    # per entry: checksum match (func.lower(Asset.checksum_xxhash)==checksum.lower(),
    #   tenant==physical_asset.tenant_id) → asset; fallback filename+size con
    #   count==1; crea AssetMembership(tenant_id, physical_asset_id, asset_id,
    #   path_on_media=path o filename, checksum, file_size, added_by_user_id)
    # stats {"matched","orphan","skipped"}; flush, NO commit (caller)
```
- [ ] GREEN → commit `feat(F4): lto_catalog — match checksum/nome+size, membership orfane, CSV auto-detect`.

### Task 3: Modello `ArchiveTicket` + auto-migrate

**Files:** Modify `app/models/models.py` (dopo AssetMembership), `app/main.py`; Test `tests/test_f4_ticket_model.py`

- [ ] Test RED: crea ticket archive con asset, default status "requested", created_at valorizzato; ticket restore con deliverable; enum-like via String semplice.
- [ ] Implementa:

```python
class ArchiveTicket(Base):
    """F4 (spec 2026-06-11) — Ticket assistito archivio/restore LTO.
    YoYotta resta manuale: il ticket traccia richiesta → lavorazione → esito."""
    __tablename__ = "archive_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)       # archive|restore
    status: Mapped[str] = mapped_column(String(15), default="requested",
                                        server_default="requested", index=True)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    job_deliverable_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_deliverables.id"), nullable=True, index=True)
    physical_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_assets.id"), nullable=True, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```
  Auto-migrate: tabella nuova → `Base.metadata.create_all` al boot la crea già (verifica come F1 ha gestito le tabelle nuove in main.py — replica; se serve niente, basta il modello).
- [ ] GREEN → commit `feat(F4): modello ArchiveTicket`.

### Task 4: Service `archive_tickets` — create/transition + notifiche + content_state

**Files:** Create `app/services/archive_tickets.py`; Test `tests/test_f4_archive_tickets.py`

- [ ] Test RED (monkeypatch `app.services.archive_tickets.notify` e `notify_permission` con stub che registra chiamate):
  1. create restore con asset con membership attiva → physical_asset_id = tape della membership più recente; notify_permission chiamata
  2. create restore asset senza membership → physical_asset_id None (ticket comunque creato)
  3. create senza asset né deliverable → ValueError
  4. transition requested→in_progress→done ok; requested→done ok (salto consentito? NO — test che requested→done è VIETATO, va in_progress prima? Decisione: CONSENTITO requested→done direttamente, semplifica operatività) → consenti {requested→in_progress, requested→done, requested→cancelled, in_progress→done, in_progress→cancelled}; done/cancelled → qualsiasi transizione = ValueError
  5. restore done → asset.content_state==online + notify al richiedente
  6. archive done con membership LTO attiva (PhysicalAsset.kind=="lto") → content_state==archived_only
  7. archive done SENZA membership → ValueError con messaggio "ingest prima il catalogo"
  8. done setta closed_at/closed_by; updated_at cambia
- [ ] Implementa: `create_ticket(db,*,kind,asset=None,deliverable=None,note=None,user_id=None) -> ArchiveTicket` e `transition(db,ticket,new_status,*,user_id=None) -> ArchiveTicket`. Notifiche: leggi firma in `app/services/notifications.py` (`notify(db, user_ids=[...], kind="archive_ticket", title=..., link="/storage")`, `notify_permission(db, permission="edit_planning_all", ...)` — verifica firma esatta nel file). kind notifiche: `"archive_ticket"`. Link: `/storage`.
- [ ] GREEN → commit `feat(F4): service archive_tickets — transizioni, notifiche, content_state`.

### Task 5: Router — wire MHL stats + catalog CSV + endpoint ticket

**Files:** Modify `app/routers/ingest_deliverables.py` (`_process_ingest` o ingest_yoyotta_mhl), `app/routers/physical_assets.py`, `app/routers/storage_admin.py`; Test `tests/test_f4_endpoints.py`

- [ ] Test RED (client_admin):
  1. POST /ingest/yoyotta-mhl con MHL sintetico (2 file: 1 checksum match con Asset esistente, 1 ignoto) + job esistente → response contiene `membership: {matched:1, orphan:1, skipped:0}`; AssetMembership create
  2. POST /physical-assets/api/{id}/catalog-csv con CSV → stats; 404 tape altrui/inesistente; 400 CSV invalido
  3. GET /storage/api/tickets?status=requested → lista; POST /storage/api/tickets (Form kind/asset_id/note) → 200; POST /storage/api/tickets/{id}/transition (Form status) → 200; transizione illegale → 400; 404 cross-tenant
- [ ] Implementa:
  - ingest_deliverables: nel punto dove il PhysicalAsset è creato/risolto (leggi `_process_ingest`), chiama `ingest_catalog_entries(db, pa, parsed["entries"], user_id=user.id)` e aggiungi `"membership": stats` alla response. Costruisci MHL sintetico nel test con il formato accettato da `parse_mhl_bytes` (leggi mhl_parser per i tag: hashlist/hash con name/size/xxhash64).
  - physical_assets: `POST /api/{id}/catalog-csv` — UploadFile + Form mapping JSON opzionale (stringa → json.loads tollerante), cap 10MB (413), tenant check, parse_catalog_csv → ingest → `{"ok": True, **stats}`. RBAC: stesso gate degli altri mutator del router (leggilo).
  - storage_admin: `GET /api/tickets` (filtri kind/status query), `POST /api/tickets` (Form: kind, asset_id opz, deliverable_id opz, note opz — ValueError→400), `POST /api/tickets/{id}/transition` (Form status — ValueError→400, 404 tenant). Serializer: id, kind, status, asset {id,filename} se c'è, deliverable {id,name}, tape {id,name/code}, note, requested_by nome, created_at, closed_at. RequireStorage.
- [ ] GREEN + `pytest tests/test_f2_confirm.py tests/test_agent_api.py -q` no regressioni → commit `feat(F4): ingest MHL→membership stats + catalog CSV + endpoint ticket`.

### Task 6: UI — tab Ticket, scheda tape, QR lookup

**Files:** Modify `app/templates/pages/storage.html`, `app/templates/pages/physical_assets.html`, `app/templates/pages/physical_asset_scan.html` + router fetch dati scan (leggi come la pagina scan riceve i dati: server-side render o api)

- [ ] storage.html: 5° tab "🎫 Ticket" (pattern tab esistenti: bottone + pane + entry in `_STORAGE_TABS` + load in init). Pane: filtri select stato/tipo + tabella (Tipo, Target, Tape, Stato badge colore, Richiesto da, Età, Azioni). Azioni per riga via data-* (niente JSON.stringify): "▶ Prendi in carico" (requested), "✔ Fatto" (requested/in_progress, confirm), "✕ Annulla" (confirm). Bottone "+ Ticket" → modal: select kind, input asset_id (hint: id asset dal registry/DAM), note. Refresh dopo ogni azione. Errori → toast.
- [ ] physical_assets.html: nella scheda/dettaglio del supporto (trova il modal/sezione dettaglio esistente) aggiungi blocco "📼 File sul supporto (N)": lista membership attive via nuovo `GET /physical-assets/api/{id}/memberships` (AGGIUNGILO in Task 5 se non esiste — verifica prima: grep memberships physical_assets.py; serializer: filename asset o "(non collegato)", path_on_media, file_size umano, added_at) + per riga collegata bottone "♻️ Restore" → POST /storage/api/tickets (kind=restore, asset_id) → toast. + Bottone "📄 Carica catalogo CSV" → input file + POST catalog-csv → toast stats.
- [ ] physical_asset_scan.html: sezione read-only "Contenuto" (stesse membership, fetch dalla pagina scan — usa lo stesso meccanismo dati della pagina: se è server-rendered estendi il context del router scan, NON aggiungere fetch autenticati che il token-scan non può fare) + "Ticket aperti" sul tape. Nessun bottone.
- [ ] Verifiche: jinja get_template sui 3 template; grep funzioni onclick definite; `.venv/Scripts/python -m pytest tests/ -q -k f4` verde.
- [ ] Commit `feat(F4): UI ticket /storage + file sul supporto + QR lookup contenuto`.

### Task 7: E2E + bump + push

**Files:** Create `tools/_e2e_f4.py`; Modify `app/main.py` (version 3.5.0-alpha.172.214), `CHANGELOG.md`, `docs/STATO.md`

- [ ] E2E (pattern tools/_e2e_f3.py, TestClient, niente browser): asset registry con checksum noto → MHL sintetico 2 entry (1 match, 1 orfana) → POST yoyotta-mhl → check membership 1 matched + 1 orphan + tape creato; re-ingest → skipped=2; ticket restore sull'asset → tape suggerito == quello del MHL; transition in_progress → done → asset.content_state==online + notifica al richiedente presente in tabella notifications; ticket archive → done → content_state==archived_only; archive su asset senza membership → 400/ValueError; CSV upload su stesso tape con 1 file nuovo → matched/orphan corretti. Run con PYTHONIOENCODING=utf-8 → tutti check verdi.
- [ ] Suite completa `pytest tests/ -q` → 0 failed.
- [ ] Bump version + CHANGELOG entry (formato α.172.213) + STATO.md (sezione nuova + Prossimo: F5 TransferOrder) + `graphify update .` + export DB ZIP in docs/ (build_export_zip come α.172.213) + commit bump + push origin main.

## Self-review (fatto)
- Spec coverage: §1 backfill→T1/T2/T5, §2 ticket→T3/T4/T5, §3 UI→T6, QR lookup→T6, sicurezza→T5 (gate+cap), test/E2E→tutti+T7. ✔
- Tipi coerenti: entries dict uniformi tra mhl_parser e parse_catalog_csv; stats dict {"matched","orphan","skipped"} identico ovunque; status ticket stringhe semplici. ✔
- Nessun placeholder: i punti "leggi il file X" sono ricerche obbligatorie su codice esistente, non TBD. ✔
