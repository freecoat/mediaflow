# Media Library — Fase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire `/media` — browser unificato read-only di asset digitali + fisici con 4 gruppi di filtri (incl. tech-specs), selezione multipla e dettaglio.

**Architecture:** Nuovo router `media.py` + servizio `media_library.py` che fonde `Asset` (digitale) e `PhysicalAsset` (fisico) tenant-scoped in righe omogenee, applica filtri e pagina. Frontend vanilla (`media_library.html` + `media_library.js`). Nessun nuovo schema/tabella; solo migrazione RBAC (permesso `manage_assets`). Nessuna azione mutante (fasi C/B/D).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (SQLite, `json_extract` per tech-specs) + Jinja2 + vanilla JS (`global.js` helpers, `i18n.js`) + pytest + Playwright (smoke).

## Global Constraints

- Ramo: creare `feat/media-library` da `main` prima di iniziare (il lavoro email è su `feat/mobile-responsive-email`, non mergiato — non mischiare). `git checkout main && git checkout -b feat/media-library`.
- Tenant filter obbligatorio su OGNI query: `Filter(tenant_id == current_tenant_id())`. `current_tenant_id()` da `app.context`.
- Visibilità TPN: riusare `accessible_project_ids(user, db)` + `is_admin(user)` da `app.services.project_access` / `rbac` (pattern `dam.py:56-75`).
- Form-based API per POST/PUT (non JSON) — non applicabile in Fase A (solo GET).
- Soft-delete: leggere solo record attivi dove il modello ha il flag.
- i18n: ogni stringa UI nuova in tutte le 5 lingue (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n`, stesso commit. Nessun debito.
- Cache-buster: gli `<script src>`/`<link>` nuovi usano `?v={{ app_version }}`.
- Ordine menu/colonne deterministico (mai ordine di inserimento DB).
- Python: usare `py`/venv Windows: eseguire i test con `.venv/Scripts/python.exe -m pytest`.
- Test router: JWT cookie reale + `monkeypatch` di `app.database.engine` e `SessionLocal` (pattern `tests/test_mail_api_read.py`), NON basta override di `current_user`.
- Bump versione + CHANGELOG + STATO a fine Fase A (ultimo task).

---

## File Structure

- **Create** `app/services/media_library.py` — serializer unificato + filtri + opzioni filtri. Cuore logico, testabile in isolamento.
- **Create** `app/routers/media.py` — route `/media` + API read + gate RBAC.
- **Create** `app/templates/pages/media_library.html` — shell pagina + markup filtri/tabella/dettaglio.
- **Create** `app/static/js/media_library.js` — fetch, render tabella, filtri, selezione, dettaglio, paginazione.
- **Create** `scripts/migrate_manage_assets.py` — concede `manage_assets` ai ruoli con `edit_planning_all`.
- **Create** `tests/test_media_library.py` — serializer + filtri + tenant-scope.
- **Create** `tests/test_media_api.py` — router + gate RBAC.
- **Modify** `app/services/rbac.py` — aggiunge `manage_assets` a `PERMISSIONS` + ai default ruolo.
- **Modify** `app/main.py` — registra `media.router`; bump versione; auto-nothing (nessuna colonna).
- **Modify** `app/templates/base.html` (o partial sidebar) — voce menu "Media Library".
- **Modify** `app/static/js/i18n.js` — chiavi `media.*` in 5 lingue.
- **Modify** `app/static/css/sleek.css` — blocco `.media-*`.
- **Modify** `CHANGELOG.md`, `docs/STATO.md` — a fine fase.

---

### Task 1: Permesso RBAC `manage_assets` + gate + migrazione ruoli

**Files:**
- Modify: `app/services/rbac.py` (dict `PERMISSIONS` ~riga 102 "Consegne / Deliverable"; default ruoli ~riga 146+)
- Create: `scripts/migrate_manage_assets.py`
- Test: `tests/test_media_rbac.py`

**Interfaces:**
- Produces: permesso stringa `"manage_assets"`; dependency factory `requires_manage_assets` usata in Task 6 come `Depends(requires_manage_assets())`.

- [ ] **Step 1: Scrivere il test del permesso**

`tests/test_media_rbac.py`:
```python
from app.services.rbac import PERMISSIONS, has_permission
from app.models.models import User, UserRole


def _all_perm_keys():
    keys = set()
    for cat in PERMISSIONS.values():
        keys.update(cat.keys())
    return keys


def test_manage_assets_permission_exists():
    assert "manage_assets" in _all_perm_keys()


def test_manage_assets_gate_accepts_planning_fallback():
    # un utente con edit_planning_all deve superare il gate media (retrocompat)
    from app.services.media_gate import user_can_media
    u = User(id=1, tenant_id=1, email="a@t.local", full_name="A",
             hashed_password="x", role=UserRole.manager, is_active=True)
    # manager ha edit_planning_all nei default → gate ok anche senza manage_assets
    assert user_can_media(u) is True
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_rbac.py -v`
Expected: FAIL (`manage_assets` assente / `media_gate` inesistente).

- [ ] **Step 3: Aggiungere il permesso a `PERMISSIONS`**

In `app/services/rbac.py`, dentro la categoria `"Consegne / Deliverable"` (dopo `view_deliverables`), aggiungere:
```python
        "manage_assets":       ["Gestione Media Library (asset digitali/fisici, associazioni)"],
```
E aggiungere `"manage_assets"` alle liste default dei ruoli che già contengono `"edit_planning_all"` (cercare ogni occorrenza di `"edit_planning_all"` nelle liste ruolo ~righe 148/174 e aggiungere `"manage_assets"` accanto).

- [ ] **Step 4: Creare il gate helper**

Create `app/services/media_gate.py`:
```python
"""Gate RBAC Media Library. manage_assets è il permesso dedicato; per
retrocompatibilità (il DAM usava edit_planning_all) il gate accetta anche
edit_planning_all finché la migrazione ruoli non è diffusa."""
from typing import Optional
from fastapi import Depends, HTTPException, Request
from app.models.models import User
from app.services.rbac import has_permission, current_user_optional


def user_can_media(user: Optional[User]) -> bool:
    return bool(user) and (has_permission(user, "manage_assets")
                           or has_permission(user, "edit_planning_all"))


def requires_manage_assets():
    def _dep(request: Request) -> User:
        user = current_user_optional(request)
        if not user_can_media(user):
            raise HTTPException(403, "Permesso Media Library mancante")
        return user
    return _dep
```
(Verificare che `current_user_optional` sia esportato da `rbac`; è importato così in `dam.py:24`.)

- [ ] **Step 5: Eseguire i test — devono passare**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_rbac.py -v`
Expected: PASS.

- [ ] **Step 6: Scrivere la migrazione ruoli**

Create `scripts/migrate_manage_assets.py` (idempotente, pattern `scripts/migrate_*.py`):
```python
"""Concede manage_assets ai ruoli/utenti che hanno edit_planning_all.
Idempotente: rilanciabile senza effetti doppi."""
from app.database import SessionLocal
from app.models.models import Role


def run():
    db = SessionLocal()
    try:
        changed = 0
        for role in db.query(Role).all():
            perms = list(role.permissions or [])
            if "edit_planning_all" in perms and "manage_assets" not in perms:
                perms.append("manage_assets")
                role.permissions = perms
                changed += 1
        db.commit()
        print(f"[migrate_manage_assets] ruoli aggiornati: {changed}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
```
(Verificare il nome del campo permessi su `Role` — se è `permissions` JSON list. Se diverso, adattare al modello reale.)

- [ ] **Step 7: Commit**

```bash
git add app/services/rbac.py app/services/media_gate.py scripts/migrate_manage_assets.py tests/test_media_rbac.py
git commit -m "feat(media): permesso RBAC manage_assets + gate + migrazione ruoli"
```

---

### Task 2: Serializer — righe digitali con filtri base

**Files:**
- Create: `app/services/media_library.py`
- Test: `tests/test_media_library.py`

**Interfaces:**
- Produces:
  - `row_from_asset(asset, *, project, client) -> dict` (riga unificata, `nature="digital"`).
  - `list_assets(db, user, filters: dict, *, offset=0, limit=50) -> dict` con `{"rows": [...], "total": int, "next_offset": int|None}`. In Task 2 gestisce SOLO asset digitali; physical arriva in Task 3.
  - Schema riga: `{nature,id,name,asset_type,physical_kind,project,client,department,delivery_status,linked_to_delivery,proposed_state,flags,storage,checksum,size_bytes,tech,created_at}` (department/delivery_status/linked_to_delivery valorizzati in Task 4; in Task 2 = `None`/`False`).

- [ ] **Step 1: Scrivere i test (digital)**

`tests/test_media_library.py` (usa lo helper sessione in-memory come `tests/test_gmail_read.py`, creando Tenant, Project, Client, Asset). Test da includere:
```python
# fixtures: _session() con Tenant(1), Client, Project(code=PRJ, client), utente admin
def test_list_digital_basic(session):
    # 2 Asset confirmed nel progetto
    rows = media_library.list_assets(session, admin, {})["rows"]
    assert all(r["nature"] == "digital" for r in rows)
    assert {r["name"] for r in rows} == {"a.mov", "b.wav"}

def test_filter_project(session):
    out = media_library.list_assets(session, admin, {"project_id": PRJ_ID})
    assert out["total"] == 2

def test_filter_asset_type(session):
    out = media_library.list_assets(session, admin, {"asset_type": "video"})
    assert [r["name"] for r in out["rows"]] == ["a.mov"]

def test_filter_q_name(session):
    out = media_library.list_assets(session, admin, {"q": "wav"})
    assert [r["name"] for r in out["rows"]] == ["b.wav"]

def test_default_hides_pending_proposals(session):
    # un Asset proposed_state=pending non appare senza filtro
    names = {r["name"] for r in media_library.list_assets(session, admin, {})["rows"]}
    assert "pending.mov" not in names

def test_filter_proposed_pending(session):
    out = media_library.list_assets(session, admin, {"proposed_state": "pending"})
    assert "pending.mov" in {r["name"] for r in out["rows"]}

def test_tenant_scope(session):
    # Asset di tenant 2 non visibile
    assert all(r["id"] != OTHER_TENANT_ASSET_ID
               for r in media_library.list_assets(session, admin, {})["rows"])
```

- [ ] **Step 2: Eseguire — deve fallire**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_library.py -v`
Expected: FAIL (`media_library` inesistente).

- [ ] **Step 3: Implementare il serializer digitale**

Create `app/services/media_library.py`:
```python
"""Media Library — serializer unificato Asset (digitale) + PhysicalAsset (fisico).
Read-only (Fase A). Tenant-scoped + visibilità TPN. Righe omogenee per il browser."""
from __future__ import annotations
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.models import (
    Asset, AssetProposedState, PhysicalAsset, Project, Client,
)
from app.context import current_tenant_id
from app.services.rbac import is_admin
from app.services.project_access import accessible_project_ids


def _tech_from_json(tech_specs_json) -> Optional[dict]:
    if not isinstance(tech_specs_json, dict):
        return None
    g = tech_specs_json.get
    res = tech_specs_json.get("resolution")
    if not res and g("width") and g("height"):
        res = f"{g('width')}x{g('height')}"
    return {"resolution": res, "codec": g("codec") or g("codec_name"),
            "hdr": g("hdr") or g("color_transfer"), "frame_rate": g("frame_rate") or g("fps")}


def row_from_asset(a: Asset, *, project=None, client=None) -> dict:
    return {
        "nature": "digital", "id": a.id,
        "name": a.original_name or a.filename or f"asset-{a.id}",
        "asset_type": getattr(a.asset_type, "value", None) or (a.asset_type and str(a.asset_type)),
        "physical_kind": None,
        "project": {"id": project.id, "code": project.code, "title": project.title} if project else None,
        "client": {"id": client.id, "name": client.name} if client else None,
        "department": None,          # Task 4
        "delivery_status": None,     # Task 4
        "linked_to_delivery": False, # Task 4
        "proposed_state": getattr(a.proposed_state, "value", None),
        "flags": {"internal_archive": bool(a.is_internal_archive),
                  "delivered_external": bool(a.is_delivered_external)},
        "storage": {"volume_id": a.storage_volume_id,
                    "volume_name": None,  # opzionale (join volume) — rinviabile
                    "path": a.rel_path or a.file_path},
        "checksum": a.checksum_xxhash,
        "size_bytes": a.file_size,
        "tech": _tech_from_json(a.tech_specs_json),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _visible_project_filter(q, user, db):
    """Applica la visibilità TPN come dam.py: admin vede tutto; altrimenti
    progetti accessibili + coda interna (project_id NULL) solo propria."""
    if is_admin(user):
        return q
    proj_ids = accessible_project_ids(user, db)
    filters = []
    if proj_ids:
        filters.append(Asset.project_id.in_(proj_ids))
    if user:
        filters.append((Asset.project_id.is_(None)) & (Asset.uploaded_by == user.id))
    return q.filter(or_(*filters)) if filters else q.filter(Asset.id < 0)


def _digital_query(db, user, f: dict):
    q = db.query(Asset).filter(
        Asset.tenant_id == current_tenant_id(),
        Asset.parent_asset_id.is_(None),
    )
    # proposte agent: default solo confirmed
    ps = f.get("proposed_state")
    if ps:
        q = q.filter(Asset.proposed_state == AssetProposedState(ps))
    else:
        q = q.filter(Asset.proposed_state == AssetProposedState.confirmed)
    if f.get("project_id"):
        q = q.filter(Asset.project_id == int(f["project_id"]))
    if f.get("job_id"):
        q = q.filter(Asset.job_id == int(f["job_id"]))
    if f.get("asset_type"):
        q = q.filter(Asset.asset_type == f["asset_type"])
    if f.get("internal_archive") in ("1", "true", True):
        q = q.filter(Asset.is_internal_archive.is_(True))
    if f.get("delivered_external") in ("1", "true", True):
        q = q.filter(Asset.is_delivered_external.is_(True))
    if f.get("checksum"):
        q = q.filter(Asset.checksum_xxhash.like(f["checksum"] + "%"))
    if f.get("q"):
        like = f"%{f['q']}%"
        q = q.filter(or_(Asset.original_name.like(like), Asset.filename.like(like),
                         Asset.rel_path.like(like), Asset.file_path.like(like)))
    q = _visible_project_filter(q, user, db)
    return q


def list_assets(db: Session, user, filters: dict, *, offset: int = 0, limit: int = 50) -> dict:
    limit = max(1, min(200, int(limit)))
    nature = (filters or {}).get("nature")
    rows = []
    total = 0
    if nature in (None, "", "digital"):
        dq = _digital_query(db, user, filters or {})
        total += dq.count()
        for a in dq.order_by(Asset.created_at.desc()).offset(offset).limit(limit).all():
            project = db.get(Project, a.project_id) if a.project_id else None
            client = db.get(Client, project.client_id) if (project and project.client_id) else None
            rows.append(row_from_asset(a, project=project, client=client))
    # physical: Task 3
    next_offset = offset + limit if len(rows) == limit else None
    return {"rows": rows, "total": total, "next_offset": next_offset}
```
(Nota: i nomi dei campi di `Asset` sono da `models.py` righe 3177+; verificare `asset_type` enum value; le chiavi di `tech_specs_json` sono ipotizzate — **step di verifica**: `grep -rn "tech_specs_json" app/services/` per trovare l'extractor e confermare le chiavi reali, poi adattare `_tech_from_json`.)

- [ ] **Step 4: Eseguire — devono passare**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_library.py -v`
Expected: PASS (i test digital di Step 1).

- [ ] **Step 5: Commit**

```bash
git add app/services/media_library.py tests/test_media_library.py
git commit -m "feat(media): serializer righe digitali + filtri base"
```

---

### Task 3: Serializer — righe fisiche + merge + paginazione + filtro nature

**Files:**
- Modify: `app/services/media_library.py`
- Test: `tests/test_media_library.py` (aggiunta)

**Interfaces:**
- Consumes: `list_assets` (Task 2).
- Produces: `row_from_physical(pa, *, project, client) -> dict` (`nature="physical"`); `list_assets` ora fonde digital+physical ordinati per `created_at DESC`, con `nature` filter, `total` combinato e `next_offset` corretto.

- [ ] **Step 1: Scrivere i test (physical + merge)**

Aggiungere a `tests/test_media_library.py`:
```python
def test_list_physical(session):
    out = media_library.list_assets(session, admin, {"nature": "physical"})
    assert all(r["nature"] == "physical" for r in out["rows"])
    assert "LTO-001" in {r["name"] for r in out["rows"]}

def test_nature_both_merges(session):
    out = media_library.list_assets(session, admin, {})
    natures = {r["nature"] for r in out["rows"]}
    assert natures == {"digital", "physical"}

def test_physical_kind_filter(session):
    out = media_library.list_assets(session, admin, {"nature": "physical", "physical_kind": "lto"})
    assert all(r["physical_kind"] == "lto" for r in out["rows"])

def test_pagination(session):
    p1 = media_library.list_assets(session, admin, {}, offset=0, limit=2)
    assert len(p1["rows"]) == 2 and p1["next_offset"] == 2
    p2 = media_library.list_assets(session, admin, {}, offset=2, limit=2)
    ids = {(r["nature"], r["id"]) for r in p1["rows"]} & {(r["nature"], r["id"]) for r in p2["rows"]}
    assert not ids  # nessuna sovrapposizione
```

- [ ] **Step 2: Eseguire — nuovi test falliscono**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_library.py -k "physical or nature or pagination" -v`
Expected: FAIL.

- [ ] **Step 3: Implementare physical + merge**

Aggiungere a `media_library.py`:
```python
def row_from_physical(pa: PhysicalAsset, *, project=None, client=None) -> dict:
    return {
        "nature": "physical", "id": pa.id,
        "name": pa.label or pa.serial_number or f"physical-{pa.id}",
        "asset_type": None,
        "physical_kind": getattr(pa.kind, "value", None) or (pa.kind and str(pa.kind)),
        "project": {"id": project.id, "code": project.code, "title": project.title} if project else None,
        "client": {"id": client.id, "name": client.name} if client else None,
        "department": None, "delivery_status": None, "linked_to_delivery": False,
        "proposed_state": None,
        "flags": {"internal_archive": bool(pa.is_internal_archive),
                  "delivered_external": bool(pa.is_delivered_external)},
        "storage": {"volume_id": None, "volume_name": None, "path": pa.location},
        "checksum": getattr(pa, "checksum", None),
        "size_bytes": (pa.capacity_gb or 0) * (1024 ** 3) if getattr(pa, "capacity_gb", None) else None,
        "tech": None,
        "created_at": pa.created_at.isoformat() if getattr(pa, "created_at", None) else None,
    }


def _physical_query(db, user, f: dict):
    q = db.query(PhysicalAsset).filter(PhysicalAsset.tenant_id == current_tenant_id())
    if f.get("project_id"):
        q = q.filter(PhysicalAsset.project_id == int(f["project_id"]))
    if f.get("job_id"):
        q = q.filter(PhysicalAsset.job_id == int(f["job_id"]))
    if f.get("physical_kind"):
        q = q.filter(PhysicalAsset.kind == f["physical_kind"])
    if f.get("internal_archive") in ("1", "true", True):
        q = q.filter(PhysicalAsset.is_internal_archive.is_(True))
    if f.get("delivered_external") in ("1", "true", True):
        q = q.filter(PhysicalAsset.is_delivered_external.is_(True))
    if f.get("q"):
        like = f"%{f['q']}%"
        q = q.filter(or_(PhysicalAsset.label.like(like), PhysicalAsset.serial_number.like(like),
                         PhysicalAsset.location.like(like)))
    if not is_admin(user):
        proj_ids = accessible_project_ids(user, db)
        q = q.filter(PhysicalAsset.project_id.in_(proj_ids)) if proj_ids else q.filter(PhysicalAsset.id < 0)
    return q
```
Riscrivere `list_assets` per fondere le due liste ordinate (merge su `created_at`):
```python
def list_assets(db, user, filters, *, offset=0, limit=50):
    f = filters or {}
    limit = max(1, min(200, int(limit)))
    nature = f.get("nature")
    total = 0
    built = []
    if nature in (None, "", "digital"):
        dq = _digital_query(db, user, f)
        total += dq.count()
        for a in dq.order_by(Asset.created_at.desc()).limit(offset + limit).all():
            project = db.get(Project, a.project_id) if a.project_id else None
            client = db.get(Client, project.client_id) if (project and project.client_id) else None
            built.append((a.created_at, row_from_asset(a, project=project, client=client)))
    if nature in (None, "", "physical"):
        pq = _physical_query(db, user, f)
        total += pq.count()
        for pa in pq.order_by(PhysicalAsset.created_at.desc()).limit(offset + limit).all():
            project = db.get(Project, pa.project_id) if pa.project_id else None
            client = db.get(Client, project.client_id) if (project and project.client_id) else None
            built.append((pa.created_at, row_from_physical(pa, project=project, client=client)))
    built.sort(key=lambda t: (t[0] or __import__("datetime").datetime.min), reverse=True)
    page = [r for _, r in built[offset:offset + limit]]
    next_offset = offset + limit if (offset + limit) < len(built) else None
    return {"rows": page, "total": total, "next_offset": next_offset}
```
(Nota merge: si materializza fino a `offset+limit` righe per natura, poi si fonde e si taglia — corretto per pagine piccole. `next_offset` è approssimato su ciò che è stato materializzato; documentare che la paginazione è best-effort per merge cross-natura, accettabile per Fase A.)

- [ ] **Step 4: Eseguire — tutti passano**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_library.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/media_library.py tests/test_media_library.py
git commit -m "feat(media): righe fisiche + merge digital/physical + paginazione"
```

---

### Task 4: Filtri delivery (linked/status) + tech-specs + department

**Files:**
- Modify: `app/services/media_library.py`
- Test: `tests/test_media_library.py`

**Interfaces:**
- Consumes: `list_assets`, `_digital_query`, `_physical_query`.
- Produces: righe con `linked_to_delivery`/`delivery_status`/`department` valorizzati; filtri `linked_to_delivery`, `delivery_status`, `tech_resolution`/`tech_codec`/`tech_hdr`/`tech_frame_rate`, `department_id`.

- [ ] **Step 1: Scrivere i test**
```python
def test_linked_to_delivery(session):
    # asset linkato via DeliverableAsset a un JobDeliverable(status=delivered)
    out = media_library.list_assets(session, admin, {"linked_to_delivery": "yes"})
    r = next(x for x in out["rows"] if x["name"] == "a.mov")
    assert r["linked_to_delivery"] is True
    assert r["delivery_status"] == "delivered"
    out2 = media_library.list_assets(session, admin, {"linked_to_delivery": "no"})
    assert "a.mov" not in {x["name"] for x in out2["rows"]}

def test_delivery_status_filter(session):
    out = media_library.list_assets(session, admin, {"delivery_status": "delivered"})
    assert all(r["delivery_status"] in ("delivered", "multi") for r in out["rows"] if r["linked_to_delivery"])

def test_tech_resolution_filter(session):
    # Asset con tech_specs_json {"width":3840,"height":2160}
    out = media_library.list_assets(session, admin, {"tech_resolution": "3840x2160"})
    assert "uhd.mov" in {r["name"] for r in out["rows"]}
```

- [ ] **Step 2: Eseguire — falliscono**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_library.py -k "linked or delivery_status or tech" -v`
Expected: FAIL.

- [ ] **Step 3: Implementare join delivery + tech + department**

In `media_library.py`: aggiungere una funzione che dato un `asset_id`/`physical_asset_id` ritorna `(linked: bool, status: str|None, department: dict|None)` interrogando il pivot `DeliverableAsset` → `JobDeliverable`:
```python
from app.models.models import DeliverableAsset, JobDeliverable, PriceItem, Department

def _delivery_info(db, *, asset_id=None, physical_asset_id=None):
    col = DeliverableAsset.asset_id == asset_id if asset_id else DeliverableAsset.physical_asset_id == physical_asset_id
    links = db.query(DeliverableAsset).filter(col).all()
    if not links:
        return False, None, None
    statuses, dept = set(), None
    for ln in links:
        jd = db.get(JobDeliverable, ln.job_deliverable_id)
        if not jd:
            continue
        statuses.add(getattr(jd.status, "value", None) or str(jd.status))
        if dept is None and jd.price_item_id:
            pi = db.get(PriceItem, jd.price_item_id)
            if pi and getattr(pi, "department_id", None):
                d = db.get(Department, pi.department_id)
                if d:
                    dept = {"id": d.id, "name": d.name}
    status = next(iter(statuses)) if len(statuses) == 1 else ("multi" if statuses else None)
    return True, status, dept
```
Nel loop di `list_assets`, dopo aver costruito la riga, valorizzarla:
```python
    linked, status, dept = _delivery_info(db, asset_id=a.id)
    row["linked_to_delivery"], row["delivery_status"], row["department"] = linked, status, dept
```
(idem per physical con `physical_asset_id=pa.id`).
Filtri (applicati POST-costruzione riga, perché derivati; oppure via subquery EXISTS se performance):
```python
    # dentro list_assets, dopo aver costruito `built`:
    def _keep(row):
        if f.get("linked_to_delivery") == "yes" and not row["linked_to_delivery"]:
            return False
        if f.get("linked_to_delivery") == "no" and row["linked_to_delivery"]:
            return False
        if f.get("delivery_status") and row["delivery_status"] != f["delivery_status"]:
            return False
        if f.get("department_id") and (not row["department"] or row["department"]["id"] != int(f["department_id"])):
            return False
        return True
    built = [(ts, r) for ts, r in built if _keep(r)]
```
Tech-specs (digital, via `json_extract` in `_digital_query`):
```python
    from sqlalchemy import func
    if f.get("tech_codec"):
        q = q.filter(func.json_extract(Asset.tech_specs_json, "$.codec") == f["tech_codec"])
    if f.get("tech_hdr"):
        q = q.filter(func.json_extract(Asset.tech_specs_json, "$.hdr") == f["tech_hdr"])
    if f.get("tech_frame_rate"):
        q = q.filter(func.json_extract(Asset.tech_specs_json, "$.frame_rate") == f["tech_frame_rate"])
    if f.get("tech_resolution"):
        # supporta sia "$.resolution" sia width/height combinati
        w, _, h = f["tech_resolution"].partition("x")
        q = q.filter(or_(
            func.json_extract(Asset.tech_specs_json, "$.resolution") == f["tech_resolution"],
            (func.json_extract(Asset.tech_specs_json, "$.width") == int(w)) &
            (func.json_extract(Asset.tech_specs_json, "$.height") == int(h)) if h.isdigit() else False,
        ))
```
(Adattare le chiavi `$.codec/$.hdr/...` a quelle reali confermate nello step di verifica del Task 2.)

- [ ] **Step 4: Eseguire — passano**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_library.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/media_library.py tests/test_media_library.py
git commit -m "feat(media): filtri delivery-link/status + tech-specs + department"
```

---

### Task 5: Opzioni filtri + dettaglio asset

**Files:**
- Modify: `app/services/media_library.py`
- Test: `tests/test_media_library.py`

**Interfaces:**
- Produces:
  - `filter_options(db, user) -> dict` con `projects/clients/jobs/departments/asset_types/physical_kinds/delivery_statuses/tech{resolution,codec,hdr,frame_rate}` (valori distinti reali).
  - `asset_detail(db, user, nature, id) -> dict|None` (riga unificata + campi estesi: `tech_specs_json` completo, `deliverables:[{id,job,status,source}]`, `memberships` per digital, `history`). `None` se non accessibile.

- [ ] **Step 1: Scrivere i test**
```python
def test_filter_options(session):
    opt = media_library.filter_options(session, admin)
    assert any(p["code"] == "PRJ" for p in opt["projects"])
    assert "video" in opt["asset_types"]
    assert "3840x2160" in opt["tech"]["resolution"]

def test_asset_detail(session):
    d = media_library.asset_detail(session, admin, "digital", A_ID)
    assert d["name"] == "a.mov"
    assert d["deliverables"][0]["status"] == "delivered"

def test_asset_detail_denied_other_tenant(session):
    assert media_library.asset_detail(session, admin, "digital", OTHER_TENANT_ASSET_ID) is None
```

- [ ] **Step 2: Eseguire — falliscono** (`filter_options`/`asset_detail` inesistenti).

- [ ] **Step 3: Implementare**

Aggiungere a `media_library.py`: `filter_options` (query distinct su Project/Client/Job accessibili + `AssetType`/`PhysicalAssetKind`/`DeliverableStatus` enum values + `SELECT DISTINCT json_extract(...)` per tech) e `asset_detail` (riusa `row_from_asset`/`row_from_physical` + `_delivery_info` + carica `tech_specs_json` intero + lista `DeliverableAsset` con job/status/source; applica lo stesso gate di visibilità, ritorna `None` se fuori scope).

- [ ] **Step 4: Eseguire — passano.**

- [ ] **Step 5: Commit**
```bash
git add app/services/media_library.py tests/test_media_library.py
git commit -m "feat(media): opzioni filtri + dettaglio asset"
```

---

### Task 6: Router `media.py` (page + API + gate)

**Files:**
- Create: `app/routers/media.py`
- Modify: `app/main.py` (import + `app.include_router(media.router)`)
- Test: `tests/test_media_api.py`

**Interfaces:**
- Consumes: `media_library.list_assets/filter_options/asset_detail`; `media_gate.requires_manage_assets`.
- Produces: route `GET /media`, `GET /media/api/assets`, `GET /media/api/asset/{nature}/{id}`, `GET /media/api/filters`.

- [ ] **Step 1: Scrivere i test router** (pattern `tests/test_mail_api_read.py`: JWT cookie reale + monkeypatch `database.engine`/`SessionLocal`).
```python
def test_media_page_requires_permission(client_noperm):
    assert client_noperm.get("/media").status_code in (302, 403)

def test_assets_api_ok(client_admin, monkeypatch):
    import app.routers.media as m
    monkeypatch.setattr(m.media_library, "list_assets",
                        lambda db, u, f, **k: {"rows": [{"nature": "digital", "id": 1, "name": "x"}], "total": 1, "next_offset": None})
    r = client_admin.get("/media/api/assets?nature=digital")
    assert r.status_code == 200 and r.json()["rows"][0]["id"] == 1

def test_asset_detail_404(client_admin, monkeypatch):
    import app.routers.media as m
    monkeypatch.setattr(m.media_library, "asset_detail", lambda db, u, n, i: None)
    assert client_admin.get("/media/api/asset/digital/999").status_code == 404

def test_filters_api(client_admin, monkeypatch):
    import app.routers.media as m
    monkeypatch.setattr(m.media_library, "filter_options", lambda db, u: {"projects": [], "asset_types": ["video"]})
    assert "video" in client_admin.get("/media/api/filters").json()["asset_types"]
```

- [ ] **Step 2: Eseguire — falliscono.**

- [ ] **Step 3: Implementare il router**

Create `app/routers/media.py`:
```python
"""Router Media Library (Fase A) — browser unificato read-only asset digitali+fisici."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.media_gate import requires_manage_assets
from app.services import media_library

router = APIRouter(prefix="/media", tags=["media"])
_Gate = Depends(requires_manage_assets())

_FILTER_KEYS = ("nature", "project_id", "client_id", "job_id", "department_id",
                "asset_type", "physical_kind", "delivery_status", "proposed_state",
                "internal_archive", "delivered_external", "linked_to_delivery",
                "volume_id", "q", "checksum",
                "tech_resolution", "tech_codec", "tech_hdr", "tech_frame_rate")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def media_page(request: Request, user=_Gate):
    from app.main import templates
    return templates.TemplateResponse("pages/media_library.html",
                                      {"request": request, "active_page": "media"})


@router.get("/api/assets")
async def media_assets(request: Request, user=_Gate, db: Session = Depends(get_db),
                       offset: int = 0, limit: int = 50):
    filters = {k: v for k, v in request.query_params.items() if k in _FILTER_KEYS and v}
    return media_library.list_assets(db, user, filters, offset=offset, limit=limit)


@router.get("/api/filters")
async def media_filters(user=_Gate, db: Session = Depends(get_db)):
    return media_library.filter_options(db, user)


@router.get("/api/asset/{nature}/{asset_id}")
async def media_asset_detail(nature: str, asset_id: int, user=_Gate, db: Session = Depends(get_db)):
    if nature not in ("digital", "physical"):
        raise HTTPException(404, "natura non valida")
    d = media_library.asset_detail(db, user, nature, asset_id)
    if d is None:
        raise HTTPException(404, "Asset non trovato o non accessibile")
    return d
```
In `app/main.py`: aggiungere `media` all'import dei router e `app.include_router(media.router)` accanto agli altri.
(Nota: il gate come `Depends` inietta `user`; verificare che `_Gate` funzioni sia sulla pagina sia sulle API. Se il middleware auth redirige gli anonimi prima del gate, il test pagina accetta 302.)

- [ ] **Step 4: Eseguire — passano.**

- [ ] **Step 5: Commit**
```bash
git add app/routers/media.py app/main.py tests/test_media_api.py
git commit -m "feat(media): router /media + API read + gate RBAC"
```

---

### Task 7: Frontend browser + menu + sleek + i18n + smoke

**Files:**
- Create: `app/templates/pages/media_library.html`
- Create: `app/static/js/media_library.js`
- Modify: `app/templates/base.html` (voce menu sidebar, gruppo Operativo)
- Modify: `app/static/js/i18n.js` (chiavi `media.*`)
- Modify: `app/static/css/sleek.css` (blocco `.media-*`)
- Modify: `app/main.py` (bump versione), `CHANGELOG.md`, `docs/STATO.md`

**Interfaces:**
- Consumes: API di Task 6.

- [ ] **Step 1: Pagina + JS**

`media_library.html`: shell con barra filtri (4 gruppi + campo `q` + toggle "Mostra proposte agent"), tabella `#media-table` (thead colonne: sel/nome/natura/tipo/progetto·cliente/stato/storage/checksum/dimensione), barra selezione `#media-actionbar` con conteggio + 3 pulsanti bulk **disabled** (`title` "disponibile a breve"), pannello dettaglio `#media-detail`, `#media-loadmore`. `<script src="/static/js/media_library.js?v={{ app_version }}">` + init `DOMContentLoaded`.

`media_library.js` (vanilla, pattern `mail.js`): stato `_mediaFilters/_mediaSel/_mediaOffset`; `mfMediaInit()` → carica `filter_options` (popola dropdown) + `mfMediaLoad(true)`; `mfMediaLoad(reset)` → `GET /media/api/assets?<filtri>&offset&limit` → render righe (escapeHtml, icona natura, checksum breve); selezione multipla (checkbox + select-all + `mfMediaSyncBar`); click riga → `GET /media/api/asset/{nature}/{id}` → render `#media-detail`; "Carica altro" append via `next_offset`. Nessuna azione mutante (pulsanti bulk disabilitati).

- [ ] **Step 2: i18n** — aggiungere in `i18n.js` le chiavi `media.title`, `media.nature`, `media.digital`, `media.physical`, `media.type`, `media.status`, `media.storage`, `media.checksum`, `media.size`, `media.showProposals`, `media.selected` (`{n}`), `media.loadMore`, `media.empty`, `media.detail`, `media.linkedDelivery`, `media.bulkSoon`, + label filtri (`media.fltContext/Nature/Status/Storage`, `media.fltProject/Client/Job/Department/AssetType/PhysicalKind/DeliveryStatus/Archive/Delivered/Linked/Volume/Checksum/Resolution/Codec/Hdr/FrameRate`), in **5 lingue** (`it/en/fr/de/es`).

- [ ] **Step 3: Menu + sleek** — aggiungere voce "Media Library" (`data-i18n="media.title"`, `href="/media"`) nel gruppo **Operativo** della sidebar in `base.html`. Aggiungere in `sleek.css` un blocco `body.sleek-mode .media-*` coerente col blocco `.mail-*` (radius, border tenui, hover, tabella refined già coperta da `table`).

- [ ] **Step 4: Smoke browser (Playwright)** — boot uvicorn 127.0.0.1 (no reload), login `admin@mediaflow.it/admin123`, `/media`: verificare tabella resa, applicare un filtro (`nature=physical`) → lista cambia, ricerca `q`, selezione multipla + conteggio barra, click riga → dettaglio, **0 errori console**. (Con DB demo; se vuoto, iniettare righe fake via `evaluate` come negli smoke email.)

- [ ] **Step 5: Bump + docs + commit** — `app.version` → prossima alpha in `main.py`; voce `CHANGELOG.md` + `docs/STATO.md` (Fase A Media Library fatta, prossimo Fase C). Poi:
```bash
git add app/templates/pages/media_library.html app/static/js/media_library.js app/static/js/i18n.js app/templates/base.html app/static/css/sleek.css app/main.py CHANGELOG.md docs/STATO.md
git commit -m "feat(media): browser Media Library UI + menu + sleek + i18n (Fase A)"
```

---

## Self-Review

**Spec coverage:** A1 route+RBAC+API → Task 1/6; A2 serializer unificato → Task 2/3; A3 filtri 4 gruppi incl tech → Task 2/3/4; A4 UI browser+selezione+dettaglio → Task 5/7; A5 testing → ogni task + smoke Task 7. Menu, i18n, sleek → Task 7. Migrazione RBAC → Task 1. Tutte le sezioni della spec hanno un task.

**Placeholder scan:** i punti "verificare chiavi `tech_specs_json`" e "verificare campo permessi `Role`" sono **step di verifica espliciti** (grep il codice reale) con codice di default fornito, non placeholder di logica. Nessun "TODO/implementa dopo".

**Type consistency:** schema riga unificata identico tra `row_from_asset`/`row_from_physical`; `list_assets` firma stabile (Task 2→3→4); `filter_options`/`asset_detail` firme coerenti tra Task 5 e Task 6; `requires_manage_assets()` (Task 1) usato come `Depends(...)` in Task 6.

**Rischi noti (dalla spec):** paginazione merge cross-natura best-effort (documentato Task 3); `department`/filtri delivery derivati post-query (Task 4, accettabile per volumi Fase A); tech-specs keys da confermare (Task 2/4).
