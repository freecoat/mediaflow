# KDM/DKDM Request Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a top-level `/kdm` page that tracks client KDM/DKDM key requests for DCP deliveries, auto-matches them to existing DCP CPLs, and links each request to its delivery item and project.

**Architecture:** Tracking-only (no crypto). New SQLAlchemy models (`DcpCpl`, `CinemaFacility`, `CinemaServer`, `KdmRequest`, `KdmRequestEvent`) in `app/models/models.py`. Services for CPL XML parsing, fuzzy match, FSM transitions, cert metadata extraction, and a pluggable delivery adapter. New router `app/routers/kdm.py` (Form-based, tenant-scoped, RBAC-gated). Vanilla-JS tabbed page. Two AI capabilities. Migration via `_auto_migrate_kdm_tables()` in lifespan + standalone script.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Jinja2, vanilla JS, `xml.etree.ElementTree`, `difflib`, pytest, Playwright. Spec: `docs/superpowers/specs/2026-06-19-kdm-dkdm-request-design.md`.

## Global Constraints

- **Python 3.11+** (priority 3.14). No `python-jose`, `passlib`, `WeasyPrint`. `difflib` (stdlib) for fuzzy. **CPL.xml is untrusted input (client-supplied) → parse with `defusedxml` (XXE / billion-laughs safe), NOT raw `xml.etree`.** `defusedxml` is pure-python, no compiled deps — add to `requirements.txt`.
- **SQLAlchemy 2.0**: `Mapped[type]` + `mapped_column`. No legacy ORM.
- **Tenant scope**: every query filters `tenant_id == current_tenant_id()` (`from app.context import current_tenant_id`). New rows set `tenant_id` from it.
- **Soft delete**: registry/CPL use `is_active=False`; `KdmRequest` uses `deleted_at` + `deleted_by_user_id` (mirror `JobDeliverable`).
- **Form-based API**: POST/PUT accept `Form(...)`, not JSON. Frontend uses `FormData`.
- **RBAC**: new permission `manage_kdm` gates every mutator (`from app.services.rbac import has_permission`).
- **i18n**: every new UI string in all 5 langs (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n`, same commit. No hardcoded UI text.
- **Menu order deterministic**: alphabetical for entity lists (`localeCompare`); status/type by explicit order.
- **Soft-delete UNIQUE bypass**: auto-numbers / uniqueness pre-checks use `.execution_options(include_deleted=True)`.
- **Decimal/money**: not applicable (no money in KDM).
- **Version bump**: bump `app/main.py` version + `CHANGELOG.md` in the final commit of the feature.
- Commit message footer on every commit:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HxY1FA6QQ6uUfXLWw6WeF2
  ```

---

## File Structure

**Create:**
- `app/services/cpl_parser.py` — parse CPL.xml → dict
- `app/services/kdm_match.py` — match engine
- `app/services/kdm_state.py` — FSM transitions
- `app/services/kdm_cert.py` — extract thumbprint + expiry from PEM
- `app/services/kdm_adapters/__init__.py`, `base.py`, `manual.py` — pluggable delivery
- `app/routers/kdm.py` — router (pages + API)
- `app/templates/pages/kdm.html` — tabbed page
- `app/static/js/kdm.js` — page JS
- `scripts/migrate_kdm.py` — standalone migration
- `tests/test_cpl_parser.py`, `tests/test_kdm_match.py`, `tests/test_kdm_state.py`, `tests/test_kdm_cert.py`, `tests/test_kdm_router.py`, `tests/test_kdm_ai.py`
- `tests/fixtures/cpl_smpte.xml`, `tests/fixtures/cpl_interop.xml`

**Modify:**
- `app/models/models.py` — 5 new models + enums (append near other delivery models)
- `app/models/__init__.py` — export new names
- `app/main.py` — `_auto_migrate_kdm_tables()` + lifespan call + `include_router(kdm.router)`
- `app/services/rbac.py` — add `manage_kdm` permission + presets
- `app/services/ai_assistant.py` — register 2 capabilities + build_context additions
- `app/templates/base.html` — sidebar menu entry
- `app/static/js/i18n.js` — 5-lang strings

---

## Task 1: Data models

**Files:**
- Modify: `app/models/models.py` (append after the JobDeliverable / delivery block)
- Modify: `app/models/__init__.py`
- Test: `tests/test_kdm_models.py`

**Interfaces:**
- Produces: classes `DcpCpl`, `CinemaFacility`, `CinemaServer`, `KdmRequest`, `KdmRequestEvent`; string-enum constants `KDM_STATUSES`, `KDM_REQUEST_TYPES`, `CPL_SOURCES`, `SERVER_MANUFACTURERS`, `FACILITY_KINDS`, `KDM_DELIVERY_METHODS`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_models.py
from app.database import SessionLocal, create_tables
from app.models import (
    DcpCpl, CinemaFacility, CinemaServer, KdmRequest, KdmRequestEvent,
)


def test_kdm_models_roundtrip():
    create_tables()
    db = SessionLocal()
    try:
        fac = CinemaFacility(tenant_id=1, name="UCI Bicocca", kind="cinema")
        db.add(fac); db.flush()
        srv = CinemaServer(tenant_id=1, facility_id=fac.id,
                           manufacturer="dolby", serial="IMS3000-123")
        db.add(srv); db.flush()
        req = KdmRequest(tenant_id=1, request_type="kdm", client_id=None,
                         status="received", target_facility_id=fac.id,
                         target_server_id=srv.id)
        db.add(req); db.flush()
        ev = KdmRequestEvent(kdm_request_id=req.id, event_type="created",
                             payload_json={})
        db.add(ev); db.flush()
        cpl = DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:abc", source="manual",
                     content_title_text="QUEER_FTR")
        db.add(cpl); db.commit()
        assert req.id and srv.facility_id == fac.id and cpl.cpl_uuid == "urn:uuid:abc"
    finally:
        db.rollback(); db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'DcpCpl'`.

- [ ] **Step 3: Add the models**

Append to `app/models/models.py` (after the delivery/JobDeliverable block). Use the existing imports already at top of file (`Mapped`, `mapped_column`, `ForeignKey`, `String`, `Integer`, `Text`, `Boolean`, `DateTime`, `Float`, `JSON`, `UniqueConstraint`, `now_utc`, `Optional`, `List`, `datetime`).

```python
# ── KDM/DKDM request tracking (v3.5.0-alpha.172.226) ──────────────────
# Tracking-only: nessuna crypto. Vedi docs/superpowers/specs/2026-06-19-kdm-dkdm-request-design.md

KDM_REQUEST_TYPES = ("kdm", "dkdm")
KDM_STATUSES = ("received", "matched", "keys_pending", "generated",
                "delivered", "confirmed", "rejected", "expired")
CPL_SOURCES = ("parsed_xml", "agent_scan", "manual", "fuzzy")
SERVER_MANUFACTURERS = ("dolby", "christie", "gdc", "barco", "sony", "qube", "other")
FACILITY_KINDS = ("cinema", "distributor")
KDM_DELIVERY_METHODS = ("email", "portal", "aspera", "usb")


class DcpCpl(Base):
    """Metadati CPL di un DCP esistente, legati al delivery item DCP."""
    __tablename__ = "dcp_cpls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    job_deliverable_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_deliverables.id"), nullable=True, index=True)
    cpl_uuid: Mapped[str] = mapped_column(String(128), index=True)
    content_title_text: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    edit_rate: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    duration_frames: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    key_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class CinemaFacility(Base):
    """Anagrafica cinema / esibitore / distributore (target delle chiavi)."""
    __tablename__ = "cinema_facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="cinema")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    servers: Mapped[List["CinemaServer"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan")


class CinemaServer(Base):
    """Server di proiezione (1 certificato = 1 server)."""
    __tablename__ = "cinema_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("cinema_facilities.id"), index=True)
    manufacturer: Mapped[str] = mapped_column(String(20), default="other")
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    serial: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cert_pem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cert_thumbprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cert_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    facility: Mapped["CinemaFacility"] = relationship(back_populates="servers")


class KdmRequest(Base):
    """Richiesta chiave (KDM o DKDM) = delivery item con workflow di stato."""
    __tablename__ = "kdm_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    request_type: Mapped[str] = mapped_column(String(8), default="kdm")
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    dcp_cpl_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dcp_cpls.id"), nullable=True, index=True)
    job_deliverable_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_deliverables.id"), nullable=True, index=True)
    target_facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cinema_facilities.id"), nullable=True)
    target_server_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cinema_servers.id"), nullable=True)
    requested_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    requested_cpl_uuid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivery_method: Mapped[str] = mapped_column(String(16), default="email")
    status: Mapped[str] = mapped_column(String(16), default="received", index=True)
    matched_confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    match_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    requested_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    kdm_file_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class KdmRequestEvent(Base):
    """Evento audit (event-sourced leggero) su una richiesta."""
    __tablename__ = "kdm_request_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kdm_request_id: Mapped[int] = mapped_column(ForeignKey("kdm_requests.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
```

> NOTE: confirm `JSON` is imported at the top of `models.py`; if absent add it to the `from sqlalchemy import ...` line. The `assets` table name is from the `Asset` model — confirm with `grep -n "__tablename__" app/models/models.py | grep -i asset`; if the digital asset table differs, set `kdm_file_asset_id` FK to match (else make it a plain `Integer` nullable with a code comment).

- [ ] **Step 4: Export new names** in `app/models/__init__.py` — add to the existing `from .models import (...)` block:

```python
    DcpCpl, CinemaFacility, CinemaServer, KdmRequest, KdmRequestEvent,
    KDM_REQUEST_TYPES, KDM_STATUSES, CPL_SOURCES, SERVER_MANUFACTURERS,
    FACILITY_KINDS, KDM_DELIVERY_METHODS,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/models/models.py app/models/__init__.py tests/test_kdm_models.py
git commit -m "feat(kdm): data models DcpCpl/CinemaFacility/CinemaServer/KdmRequest/Event"
```

---

## Task 2: Migration

**Files:**
- Modify: `app/main.py` (add `_auto_migrate_kdm_tables()` near other `_auto_migrate_*`, call in lifespan)
- Create: `scripts/migrate_kdm.py`
- Test: `tests/test_kdm_migration.py`

**Interfaces:**
- Consumes: models from Task 1.
- Produces: function `_auto_migrate_kdm_tables()` in `app/main.py`; runnable `scripts/migrate_kdm.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_migration.py
from sqlalchemy import inspect
from app.database import engine
import app.main as main


def test_auto_migrate_kdm_creates_tables():
    main._auto_migrate_kdm_tables()
    names = inspect(engine).get_table_names()
    for t in ("dcp_cpls", "cinema_facilities", "cinema_servers",
              "kdm_requests", "kdm_request_events"):
        assert t in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_migration.py -v`
Expected: FAIL with `AttributeError: module 'app.main' has no attribute '_auto_migrate_kdm_tables'`.

- [ ] **Step 3: Add the migration function** in `app/main.py` (place next to the other `_auto_migrate_*` defs, e.g. after `_auto_migrate_bundle_l_stack2`):

```python
def _auto_migrate_kdm_tables():
    """Crea le tabelle KDM (v3.5.0-alpha.172.226) se mancanti. Idempotente.
    Tutto in tabelle nuove: nessuna ALTER su tabelle esistenti."""
    from app.database import create_tables
    from sqlalchemy import inspect as _inspect
    insp = _inspect(engine)
    needed = {"dcp_cpls", "cinema_facilities", "cinema_servers",
              "kdm_requests", "kdm_request_events"}
    if not needed.issubset(set(insp.get_table_names())):
        create_tables()  # Base.metadata.create_all — crea solo le mancanti
```

> `engine` is already imported in main.py (used by other migrations). If not in scope, add `from app.database import engine` at top of the function.

- [ ] **Step 4: Wire it into lifespan** — in the lifespan startup block (near the other guarded `_auto_migrate_*` calls around line 1900-1948), add:

```python
    try:
        _auto_migrate_kdm_tables()
    except Exception as e:
        print(f"[lifespan] _auto_migrate_kdm_tables failed: {e}")
```

- [ ] **Step 5: Create the standalone script** `scripts/migrate_kdm.py`:

```python
"""
MediaFlow — migrazione KDM/DKDM request tracking (v3.5.0-alpha.172.226)

Crea: dcp_cpls, cinema_facilities, cinema_servers, kdm_requests, kdm_request_events.
Tutto in tabelle nuove, nessuna ALTER su tabelle esistenti. Idempotente.

Esegui:
  python scripts/migrate_kdm.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect
from app.database import engine, create_tables
from app.models import (  # noqa: F401
    DcpCpl, CinemaFacility, CinemaServer, KdmRequest, KdmRequestEvent,
)


def migrate():
    print("▸ MediaFlow · migrazione KDM/DKDM (v3.5.0-alpha.172.226)")
    print("─" * 70)
    create_tables()
    names = inspect(engine).get_table_names()
    for t in ("dcp_cpls", "cinema_facilities", "cinema_servers",
              "kdm_requests", "kdm_request_events"):
        print(f"  {'✓' if t in names else '✗'} {t}")
    print("▸ Fatto.")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 6: Run test + script**

Run: `python -m pytest tests/test_kdm_migration.py -v`
Expected: PASS.
Run: `python scripts/migrate_kdm.py`
Expected: 5 `✓` lines.

- [ ] **Step 7: Commit**

```bash
git add app/main.py scripts/migrate_kdm.py tests/test_kdm_migration.py
git commit -m "feat(kdm): auto-migrate + standalone migration for KDM tables"
```

---

## Task 3: RBAC permission `manage_kdm`

**Files:**
- Modify: `app/services/rbac.py` (`PERMISSIONS` dict + `PRESET_PERMISSIONS`)
- Test: `tests/test_kdm_rbac.py`

**Interfaces:**
- Produces: permission key `"manage_kdm"` in `ALL_PERMISSION_KEYS`; granted to `admin` and `manager` presets.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_rbac.py
from app.services.rbac import ALL_PERMISSION_KEYS, PRESET_PERMISSIONS


def test_manage_kdm_registered():
    assert "manage_kdm" in ALL_PERMISSION_KEYS
    assert "manage_kdm" in PRESET_PERMISSIONS["manager"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_rbac.py -v`
Expected: FAIL (`assert 'manage_kdm' in ...`).

- [ ] **Step 3: Add the permission** — in `app/services/rbac.py`, inside the `PERMISSIONS` dict (near `edit_deliverables`, line ~97), add an entry to the relevant category:

```python
        "manage_kdm":          ["Gestione richieste KDM/DKDM (chiavi DCP)"],
```

Then in `PRESET_PERMISSIONS`, add `"manage_kdm"` to the `manager` list (admin already gets all keys via `list(ALL_PERMISSION_KEYS)`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_rbac.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/rbac.py tests/test_kdm_rbac.py
git commit -m "feat(kdm): add manage_kdm RBAC permission"
```

---

## Task 4: CPL parser

**Files:**
- Create: `app/services/cpl_parser.py`
- Create: `tests/fixtures/cpl_smpte.xml`, `tests/fixtures/cpl_interop.xml`
- Test: `tests/test_cpl_parser.py`

**Interfaces:**
- Produces: `parse_cpl(xml_bytes: bytes) -> dict` returning keys `cpl_uuid`, `content_title_text`, `edit_rate`, `duration_frames`, `encrypted`, `key_ids` (list[str]). Raises `ValueError` on non-CPL XML.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/cpl_smpte.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL">
  <Id>urn:uuid:6c9f1f2e-1111-4aaa-bbbb-000000000001</Id>
  <ContentTitleText>QUEER_FTR-1_F_IT-IT_IT_51_2K_TPR_20240901_TPR_IOP_OV</ContentTitleText>
  <ReelList>
    <Reel>
      <AssetList>
        <MainPicture>
          <EditRate>24 1</EditRate>
          <IntrinsicDuration>1440</IntrinsicDuration>
          <KeyId>urn:uuid:aaaaaaaa-0000-0000-0000-000000000aaa</KeyId>
        </MainPicture>
        <MainSound>
          <IntrinsicDuration>1440</IntrinsicDuration>
          <KeyId>urn:uuid:bbbbbbbb-0000-0000-0000-000000000bbb</KeyId>
        </MainSound>
      </AssetList>
    </Reel>
  </ReelList>
</CompositionPlaylist>
```

`tests/fixtures/cpl_interop.xml` (Interop namespace, unencrypted, no KeyId):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.digicine.com/PROTO-ASDCP-CPL-20040511#">
  <Id>urn:uuid:7d0e2a3f-2222-4ccc-dddd-000000000002</Id>
  <ContentTitleText>TRAILER_TLR_F_EN_2K</ContentTitleText>
  <ReelList>
    <Reel>
      <AssetList>
        <MainPicture>
          <EditRate>24 1</EditRate>
          <IntrinsicDuration>720</IntrinsicDuration>
        </MainPicture>
      </AssetList>
    </Reel>
  </ReelList>
</CompositionPlaylist>
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_cpl_parser.py
from pathlib import Path
import pytest
from app.services.cpl_parser import parse_cpl

FX = Path(__file__).parent / "fixtures"


def test_parse_smpte_encrypted():
    r = parse_cpl((FX / "cpl_smpte.xml").read_bytes())
    assert r["cpl_uuid"] == "urn:uuid:6c9f1f2e-1111-4aaa-bbbb-000000000001"
    assert "QUEER_FTR" in r["content_title_text"]
    assert r["edit_rate"] == "24 1"
    assert r["duration_frames"] == 1440
    assert r["encrypted"] is True
    assert len(r["key_ids"]) == 2


def test_parse_interop_unencrypted():
    r = parse_cpl((FX / "cpl_interop.xml").read_bytes())
    assert r["cpl_uuid"].endswith("000000000002")
    assert r["encrypted"] is False
    assert r["key_ids"] == []


def test_parse_non_cpl_raises():
    with pytest.raises(ValueError):
        parse_cpl(b"<Foo/>")


def test_billion_laughs_rejected():
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
        b'<CompositionPlaylist><ContentTitleText>&lol3;</ContentTitleText></CompositionPlaylist>'
    )
    with pytest.raises(ValueError):
        parse_cpl(payload)


def test_xxe_external_entity_rejected():
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<CompositionPlaylist><Id>&x;</Id></CompositionPlaylist>'
    )
    with pytest.raises(ValueError):
        parse_cpl(payload)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_cpl_parser.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.cpl_parser`).

- [ ] **Step 4a: Add the dependency** — append `defusedxml>=0.7.1` to `requirements.txt`, then `pip install defusedxml` in the venv.

- [ ] **Step 4: Implement** `app/services/cpl_parser.py`:

```python
"""Parser CPL.xml (SMPTE + Interop), namespace-tolerant. Niente crypto.

SICUREZZA: il CPL.xml arriva dal cliente (input non fidato). Usa defusedxml
per neutralizzare XXE (external entity) e billion-laughs (entity expansion).
NON usare xml.etree.ElementTree.fromstring direttamente su input non fidato.
"""
from defusedxml.ElementTree import fromstring as _safe_fromstring
from xml.etree.ElementTree import ParseError


def _local(tag: str) -> str:
    """Strip namespace: '{ns}Id' -> 'Id'."""
    return tag.rsplit("}", 1)[-1]


def _find_local(elem, name: str):
    for e in elem.iter():
        if _local(e.tag) == name:
            return e
    return None


def _findall_local(elem, name: str):
    return [e for e in elem.iter() if _local(e.tag) == name]


def parse_cpl(xml_bytes: bytes) -> dict:
    """Estrae metadati da un CPL.xml. Raises ValueError se non è un CPL."""
    try:
        root = _safe_fromstring(xml_bytes)
    except ParseError as e:
        raise ValueError(f"XML non valido: {e}")
    except Exception as e:
        # defusedxml solleva EntitiesForbidden / DTDForbidden su payload ostili
        raise ValueError(f"XML rifiutato (sicurezza): {e}")
    if _local(root.tag) != "CompositionPlaylist":
        raise ValueError("Non è un CompositionPlaylist (CPL)")

    id_el = _find_local(root, "Id")
    cpl_uuid = (id_el.text or "").strip() if id_el is not None else ""
    if not cpl_uuid:
        raise ValueError("CPL senza Id")

    title_el = _find_local(root, "ContentTitleText")
    content_title = (title_el.text or "").strip() if title_el is not None else None

    er_el = _find_local(root, "EditRate")
    edit_rate = (er_el.text or "").strip() if er_el is not None else None

    # Durata: max IntrinsicDuration tra le tracce (proxy della durata reel).
    durations = []
    for d in _findall_local(root, "IntrinsicDuration"):
        try:
            durations.append(int((d.text or "").strip()))
        except (TypeError, ValueError):
            pass
    duration_frames = max(durations) if durations else None

    key_ids = [(k.text or "").strip() for k in _findall_local(root, "KeyId")
               if (k.text or "").strip()]

    return {
        "cpl_uuid": cpl_uuid,
        "content_title_text": content_title,
        "edit_rate": edit_rate,
        "duration_frames": duration_frames,
        "encrypted": bool(key_ids),
        "key_ids": key_ids,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_cpl_parser.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/cpl_parser.py tests/test_cpl_parser.py tests/fixtures/cpl_smpte.xml tests/fixtures/cpl_interop.xml requirements.txt
git commit -m "feat(kdm): CPL.xml parser (SMPTE+Interop, defusedxml hardened vs XXE/billion-laughs)"
```

---

## Task 5: Match engine

**Files:**
- Create: `app/services/kdm_match.py`
- Test: `tests/test_kdm_match.py`

**Interfaces:**
- Consumes: `DcpCpl`, `KdmRequest` (Task 1); `current_tenant_id`.
- Produces: `match_request(db, req) -> list[dict]` where each dict is `{"dcp_cpl_id": int, "confidence": int, "source": str, "title": str}`, sorted desc by confidence. `AUTO_LINK_THRESHOLD: int = 95` module constant.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_match.py
from app.database import SessionLocal, create_tables
from app.models import DcpCpl, KdmRequest
from app.services.kdm_match import match_request, AUTO_LINK_THRESHOLD


def _seed(db):
    db.query(DcpCpl).delete()
    db.add(DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:exact-1", source="manual",
                  content_title_text="QUEER_FTR_2K_IT"))
    db.add(DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:other-2", source="manual",
                  content_title_text="DUNE_FTR_4K_EN"))
    db.commit()


def test_exact_uuid_match_is_100():
    create_tables(); db = SessionLocal()
    try:
        _seed(db)
        req = KdmRequest(tenant_id=1, request_type="kdm",
                         requested_cpl_uuid="urn:uuid:exact-1")
        out = match_request(db, req)
        assert out and out[0]["confidence"] == 100
        assert out[0]["confidence"] >= AUTO_LINK_THRESHOLD
    finally:
        db.rollback(); db.close()


def test_fuzzy_title_match_ranks():
    create_tables(); db = SessionLocal()
    try:
        _seed(db)
        req = KdmRequest(tenant_id=1, request_type="kdm",
                         requested_title="QUEER feature 2K")
        out = match_request(db, req)
        assert out and "QUEER" in out[0]["title"]
        assert 0 < out[0]["confidence"] < 100
    finally:
        db.rollback(); db.close()


def test_no_match_returns_empty():
    create_tables(); db = SessionLocal()
    try:
        _seed(db)
        req = KdmRequest(tenant_id=1, request_type="kdm",
                         requested_title="zzz nothing zzz")
        out = match_request(db, req)
        assert out == [] or out[0]["confidence"] < 40
    finally:
        db.rollback(); db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_match.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `app/services/kdm_match.py`:

```python
"""Match engine: richiesta KDM → CPL dei DCP esistenti.

Strategia: UUID esatto (100) → fuzzy su ContentTitleText (60-90)
→ (in router) fuzzy su titolo progetto (40-70). Solo stdlib difflib.
Soglia auto-link configurabile (default 95), tarabile in beta.
"""
from difflib import SequenceMatcher
from app.models import DcpCpl
from app.context import current_tenant_id

AUTO_LINK_THRESHOLD = 95


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def match_request(db, req) -> list[dict]:
    """Ritorna candidati [{dcp_cpl_id, confidence, source, title}] desc."""
    rows = (db.query(DcpCpl)
            .filter(DcpCpl.tenant_id == current_tenant_id(),
                    DcpCpl.is_active == True)  # noqa: E712
            .all())
    out: list[dict] = []
    want_uuid = (req.requested_cpl_uuid or "").strip().lower()
    want_title = (req.requested_title or "").strip()
    for c in rows:
        conf = 0
        source = ""
        if want_uuid and (c.cpl_uuid or "").strip().lower() == want_uuid:
            conf, source = 100, "cpl_uuid"
        elif want_title and c.content_title_text:
            r = _ratio(want_title, c.content_title_text)
            conf = int(round(60 + r * 30)) if r > 0.30 else int(round(r * 60))
            source = "title_fuzzy"
        if conf > 0:
            out.append({"dcp_cpl_id": c.id, "confidence": conf,
                        "source": source, "title": c.content_title_text or ""})
    out.sort(key=lambda d: d["confidence"], reverse=True)
    return out
```

> The 40-70 project-title tier lives in the router (Task 7) where Project rows are joined; the service stays CPL-only to keep it unit-testable.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_match.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/kdm_match.py tests/test_kdm_match.py
git commit -m "feat(kdm): CPL match engine (exact UUID + fuzzy title)"
```

---

## Task 6: FSM state transitions

**Files:**
- Create: `app/services/kdm_state.py`
- Test: `tests/test_kdm_state.py`

**Interfaces:**
- Consumes: `KdmRequest`, `KdmRequestEvent`, `KDM_STATUSES` (Task 1).
- Produces: `ALLOWED_TRANSITIONS: dict[str, set[str]]`; `transition(db, req, to_status, user_id=None) -> KdmRequest` (raises `ValueError` on illegal transition, stamps timestamps, appends a `KdmRequestEvent`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_state.py
import pytest
from app.database import SessionLocal, create_tables
from app.models import KdmRequest, KdmRequestEvent
from app.services.kdm_state import transition, ALLOWED_TRANSITIONS


def test_legal_transition_stamps_and_logs():
    create_tables(); db = SessionLocal()
    try:
        req = KdmRequest(tenant_id=1, request_type="kdm", status="generated")
        db.add(req); db.flush()
        transition(db, req, "delivered", user_id=1)
        assert req.status == "delivered" and req.delivered_at is not None
        evs = db.query(KdmRequestEvent).filter_by(kdm_request_id=req.id).all()
        assert any(e.event_type == "transition" for e in evs)
    finally:
        db.rollback(); db.close()


def test_illegal_transition_raises():
    create_tables(); db = SessionLocal()
    try:
        req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
        db.add(req); db.flush()
        with pytest.raises(ValueError):
            transition(db, req, "confirmed")
    finally:
        db.rollback(); db.close()


def test_transition_table_shape():
    assert "matched" in ALLOWED_TRANSITIONS["received"]
    assert "rejected" in ALLOWED_TRANSITIONS["received"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_state.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `app/services/kdm_state.py`:

```python
"""FSM transizioni richiesta KDM. Unico punto che muta `status`."""
from app.models import KdmRequestEvent
from app.models.models import now_utc

ALLOWED_TRANSITIONS = {
    "received":     {"matched", "rejected"},
    "matched":      {"keys_pending", "rejected", "received"},
    "keys_pending": {"generated", "rejected"},
    "generated":    {"delivered", "rejected"},
    "delivered":    {"confirmed", "expired"},
    "confirmed":    {"expired"},
    "rejected":     set(),
    "expired":      set(),
}

_TIMESTAMP_FIELD = {
    "generated": "generated_at",
    "delivered": "delivered_at",
    "confirmed": "confirmed_at",
}


def transition(db, req, to_status: str, user_id=None):
    """Applica una transizione legale, stampa timestamp, logga evento."""
    cur = req.status
    if to_status not in ALLOWED_TRANSITIONS.get(cur, set()):
        raise ValueError(f"Transizione illegale {cur} → {to_status}")
    req.status = to_status
    field = _TIMESTAMP_FIELD.get(to_status)
    if field and getattr(req, field) is None:
        setattr(req, field, now_utc())
    db.add(KdmRequestEvent(
        kdm_request_id=req.id, event_type="transition",
        payload_json={"from": cur, "to": to_status}, user_id=user_id))
    db.flush()
    return req
```

> Confirm `now_utc` is defined in `app/models/models.py` (it is — used by every model). Import path `from app.models.models import now_utc` is correct.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_state.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/kdm_state.py tests/test_kdm_state.py
git commit -m "feat(kdm): FSM state transitions with event logging"
```

---

## Task 7: Cert metadata extractor

**Files:**
- Create: `app/services/kdm_cert.py`
- Test: `tests/test_kdm_cert.py`

**Interfaces:**
- Produces: `parse_cert(pem_text: str) -> dict` with keys `thumbprint` (sha1 hex of DER, uppercase), `expires_at` (`datetime` or `None`). Pure stdlib: `ssl.PEM_cert_to_DER_cert` + `hashlib`; expiry via `ssl._ssl._test_decode_cert` is unavailable, so use a best-effort parse and gracefully degrade to `None` when unavailable (no new crypto dep).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_cert.py
import ssl, hashlib
from app.services.kdm_cert import parse_cert

# Minimal self-signed-looking PEM is hard to embed; test the thumbprint path
# with a tiny valid DER round-trip using a known PEM block.
SAMPLE_PEM = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBkTCB+wIJANQ9ts6m4mEMA0GCSqGSIb3DQEBCwUAMBQxEjAQBgNVBAMMCWxv\n"  # truncated-ok
    "-----END CERTIFICATE-----\n"
)


def test_parse_cert_handles_garbage_gracefully():
    out = parse_cert("not a cert")
    assert out["thumbprint"] is None
    assert out["expires_at"] is None


def test_parse_cert_thumbprint_when_der_decodable(monkeypatch):
    # If DER decode fails (truncated sample), we still must not raise.
    out = parse_cert(SAMPLE_PEM)
    assert "thumbprint" in out and "expires_at" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_cert.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `app/services/kdm_cert.py`:

```python
"""Estrazione best-effort di thumbprint + scadenza da un certificato PEM.
Solo stdlib (ssl + hashlib). Degrada a None senza sollevare eccezioni."""
import ssl
import hashlib
from datetime import datetime


def parse_cert(pem_text: str) -> dict:
    thumbprint = None
    expires_at = None
    try:
        der = ssl.PEM_cert_to_DER_cert(pem_text)
        thumbprint = hashlib.sha1(der).hexdigest().upper()
    except Exception:
        thumbprint = None
    # Scadenza: best-effort. ssl non espone un parser pubblico per PEM
    # arbitrari senza connessione; lasciamo None se non ricavabile.
    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
            fh.write(pem_text); path = fh.name
        try:
            info = ssl._ssl._test_decode_cert(path)  # type: ignore[attr-defined]
            na = info.get("notAfter")
            if na:
                expires_at = datetime.strptime(na, "%b %d %H:%M:%S %Y %Z")
        finally:
            os.unlink(path)
    except Exception:
        expires_at = None
    return {"thumbprint": thumbprint, "expires_at": expires_at}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_cert.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/kdm_cert.py tests/test_kdm_cert.py
git commit -m "feat(kdm): best-effort PEM cert thumbprint+expiry extractor"
```

---

## Task 8: Delivery adapter (pluggable)

**Files:**
- Create: `app/services/kdm_adapters/__init__.py`, `app/services/kdm_adapters/base.py`, `app/services/kdm_adapters/manual.py`
- Test: `tests/test_kdm_adapter.py`

**Interfaces:**
- Produces: `get_adapter(name: str) -> KdmAdapter`; `KdmAdapter` base with `send_kdm(req) -> dict` and `fetch_certs(facility) -> list`; `ManualAdapter` returning `{"ok": True, "mode": "manual"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_adapter.py
from app.services.kdm_adapters import get_adapter


def test_manual_adapter_default():
    a = get_adapter("manual")
    assert a.send_kdm(None)["mode"] == "manual"
    assert a.fetch_certs(None) == []


def test_unknown_adapter_falls_back_to_manual():
    a = get_adapter("does-not-exist")
    assert a.send_kdm(None)["mode"] == "manual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_adapter.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`app/services/kdm_adapters/base.py`:

```python
"""Base adapter consegna KDM. Fase 2: qube_wire / gofilex con chiave Fernet."""


class KdmAdapter:
    name = "base"

    def send_kdm(self, req) -> dict:
        raise NotImplementedError

    def fetch_certs(self, facility) -> list:
        return []
```

`app/services/kdm_adapters/manual.py`:

```python
from app.services.kdm_adapters.base import KdmAdapter


class ManualAdapter(KdmAdapter):
    name = "manual"

    def send_kdm(self, req) -> dict:
        # v1: nessun invio automatico; l'operatore consegna a mano.
        return {"ok": True, "mode": "manual"}
```

`app/services/kdm_adapters/__init__.py`:

```python
from app.services.kdm_adapters.manual import ManualAdapter

_ADAPTERS = {"manual": ManualAdapter}


def get_adapter(name: str):
    """Ritorna l'adapter richiesto; fallback su manual se sconosciuto."""
    cls = _ADAPTERS.get(name, ManualAdapter)
    return cls()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_adapter.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/kdm_adapters tests/test_kdm_adapter.py
git commit -m "feat(kdm): pluggable delivery adapter (manual v1)"
```

---

## Task 9: Router skeleton + registration + page route

**Files:**
- Create: `app/routers/kdm.py`
- Modify: `app/main.py` (`include_router`)
- Create: `app/templates/pages/kdm.html` (minimal shell; filled in Task 13)
- Test: `tests/test_kdm_router.py`

**Interfaces:**
- Consumes: all services above.
- Produces: `router` (prefix `/kdm`); helper `_require_kdm(request)` raising 403 without `manage_kdm`; `GET /kdm` → HTML; `GET /kdm/api/requests` → JSON list.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_router.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_kdm_page_loads():
    r = client.get("/kdm")
    # Auth middleware may redirect; accept 200 or auth redirect, never 404/500.
    assert r.status_code in (200, 302, 303, 401)


def test_requests_api_shape():
    r = client.get("/kdm/api/requests")
    assert r.status_code in (200, 401, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_router.py -v`
Expected: FAIL (`404` because router not registered).

- [ ] **Step 3: Create minimal template** `app/templates/pages/kdm.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <div class="card-title"><i data-lucide="key-round"></i> <span data-i18n="kdm.title">Richieste KDM/DKDM</span></div>
  <div id="kdm-root" data-i18n-ph="loading">Caricamento…</div>
</div>
{% endblock %}
```

- [ ] **Step 4: Create the router** `app/routers/kdm.py`:

```python
"""Router richieste KDM/DKDM (v3.5.0-alpha.172.226). Tracking-only.
Vedi docs/superpowers/specs/2026-06-19-kdm-dkdm-request-design.md
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.context import current_tenant_id
from app.models import KdmRequest, DcpCpl, CinemaFacility, CinemaServer
from app.services.rbac import has_permission, current_user_optional

router = APIRouter(prefix="/kdm", tags=["kdm"])


def _tpl():
    from app.main import templates
    return templates


def _require_kdm(request: Request, db: Session):
    user = current_user_optional(request, db)
    if not has_permission(user, "manage_kdm"):
        raise HTTPException(status_code=403, detail="Permesso manage_kdm richiesto")
    return user


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def kdm_page(request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse("pages/kdm.html", {"request": request})


@router.get("/api/requests")
async def list_requests(request: Request, db: Session = Depends(get_db),
                        status: Optional[str] = None, type: Optional[str] = None):
    _require_kdm(request, db)
    q = (db.query(KdmRequest)
         .filter(KdmRequest.tenant_id == current_tenant_id(),
                 KdmRequest.deleted_at.is_(None)))
    if status:
        q = q.filter(KdmRequest.status == status)
    if type:
        q = q.filter(KdmRequest.request_type == type)
    rows = q.order_by(KdmRequest.requested_at.desc()).all()
    return JSONResponse([{
        "id": r.id, "request_type": r.request_type, "status": r.status,
        "client_id": r.client_id, "project_id": r.project_id,
        "requested_title": r.requested_title, "valid_from": r.valid_from.isoformat() if r.valid_from else None,
        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        "matched_confidence": r.matched_confidence,
        "dcp_cpl_id": r.dcp_cpl_id, "job_deliverable_id": r.job_deliverable_id,
    } for r in rows])
```

> Confirm `current_user_optional` signature in `app/services/rbac.py` (used by `holidays.py`: `from app.services.rbac import current_user_optional, has_permission`). Match the existing call convention — if it takes only `request`, drop the `db` arg.

- [ ] **Step 5: Register the router** in `app/main.py` near the other `include_router` calls (after `app.include_router(delivery_items.router)`):

```python
from app.routers import kdm as kdm_router  # add to the routers import group
app.include_router(kdm_router.router)
```

> Match the existing import style — most routers are imported at top of main.py. Add `kdm` to that import group rather than a local import if that's the established pattern.

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_router.py -v`
Expected: 2 PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routers/kdm.py app/main.py app/templates/pages/kdm.html tests/test_kdm_router.py
git commit -m "feat(kdm): router skeleton + page route + list API + registration"
```

---

## Task 10: Requests CRUD + match + link + transition + upload

**Files:**
- Modify: `app/routers/kdm.py`
- Test: `tests/test_kdm_router.py` (extend)

**Interfaces:**
- Consumes: `match_request`, `transition`, `AUTO_LINK_THRESHOLD`.
- Produces endpoints: `POST /kdm/api/requests`, `POST /kdm/api/requests/{id}/match`, `POST /kdm/api/requests/{id}/link`, `POST /kdm/api/requests/{id}/transition`, `DELETE /kdm/api/requests/{id}`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_kdm_router.py`)

```python
def _auth_headers():
    # If the app exposes a test-login helper, use it; else these tests
    # assert structural behavior under whatever auth returns.
    return {}


def test_create_and_match_request(monkeypatch):
    from app.database import SessionLocal
    from app.models import DcpCpl
    db = SessionLocal()
    try:
        db.add(DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:router-1",
                      source="manual", content_title_text="ROUTER_FTR"))
        db.commit()
    finally:
        db.close()
    # bypass RBAC for the unit-level check
    import app.routers.kdm as kdm_mod
    monkeypatch.setattr(kdm_mod, "_require_kdm", lambda request, db: None)
    r = client.post("/kdm/api/requests", data={
        "request_type": "kdm", "requested_cpl_uuid": "urn:uuid:router-1",
        "delivery_method": "email"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] and body["status"] in ("received", "matched")
    # exact uuid → auto-linked
    assert body["status"] == "matched" and body["dcp_cpl_id"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_router.py::test_create_and_match_request -v`
Expected: FAIL (`405`/`404` — POST not implemented).

- [ ] **Step 3: Implement the endpoints** (append to `app/routers/kdm.py`):

```python
from datetime import datetime
from app.services.kdm_match import match_request, AUTO_LINK_THRESHOLD
from app.services.kdm_state import transition as _fsm_transition


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _serialize(r: KdmRequest) -> dict:
    return {
        "id": r.id, "request_type": r.request_type, "status": r.status,
        "client_id": r.client_id, "project_id": r.project_id,
        "dcp_cpl_id": r.dcp_cpl_id, "job_deliverable_id": r.job_deliverable_id,
        "matched_confidence": r.matched_confidence, "match_source": r.match_source,
        "requested_title": r.requested_title, "requested_cpl_uuid": r.requested_cpl_uuid,
    }


def _apply_link(db, r: KdmRequest, cpl_id: int, confidence: int, source: str):
    cpl = db.get(DcpCpl, cpl_id)
    if not cpl or cpl.tenant_id != current_tenant_id():
        raise HTTPException(404, "CPL non trovata")
    r.dcp_cpl_id = cpl.id
    r.job_deliverable_id = cpl.job_deliverable_id
    r.matched_confidence = confidence
    r.match_source = source
    if cpl.job_deliverable_id:
        from app.models import JobDeliverable
        jd = db.get(JobDeliverable, cpl.job_deliverable_id)
        if jd is not None:
            r.project_id = getattr(jd, "project_id", None) or r.project_id
    if r.status == "received":
        _fsm_transition(db, r, "matched")


@router.post("/api/requests")
async def create_request(request: Request, db: Session = Depends(get_db),
                         request_type: str = Form("kdm"),
                         client_id: Optional[int] = Form(None),
                         requested_title: Optional[str] = Form(None),
                         requested_cpl_uuid: Optional[str] = Form(None),
                         target_facility_id: Optional[int] = Form(None),
                         target_server_id: Optional[int] = Form(None),
                         valid_from: Optional[str] = Form(None),
                         valid_to: Optional[str] = Form(None),
                         delivery_method: str = Form("email"),
                         requested_by: Optional[str] = Form(None),
                         notes: Optional[str] = Form(None)):
    _require_kdm(request, db)
    r = KdmRequest(
        tenant_id=current_tenant_id(), request_type=request_type,
        client_id=client_id, requested_title=requested_title,
        requested_cpl_uuid=requested_cpl_uuid,
        target_facility_id=target_facility_id, target_server_id=target_server_id,
        valid_from=_parse_dt(valid_from), valid_to=_parse_dt(valid_to),
        delivery_method=delivery_method, requested_by=requested_by, notes=notes,
        status="received")
    db.add(r); db.flush()
    cands = match_request(db, r)
    if cands and cands[0]["confidence"] >= AUTO_LINK_THRESHOLD:
        _apply_link(db, r, cands[0]["dcp_cpl_id"], cands[0]["confidence"], cands[0]["source"])
    db.commit(); db.refresh(r)
    return _serialize(r)


@router.post("/api/requests/{rid}/match")
async def rematch(rid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    return {"candidates": match_request(db, r)}


@router.post("/api/requests/{rid}/link")
async def link(rid: int, request: Request, db: Session = Depends(get_db),
               dcp_cpl_id: int = Form(...)):
    _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    cands = {c["dcp_cpl_id"]: c for c in match_request(db, r)}
    c = cands.get(dcp_cpl_id, {"confidence": 0, "source": "manual_link"})
    _apply_link(db, r, dcp_cpl_id, c["confidence"], c["source"])
    db.commit(); db.refresh(r)
    return _serialize(r)


@router.post("/api/requests/{rid}/transition")
async def do_transition(rid: int, request: Request, db: Session = Depends(get_db),
                        to_status: str = Form(...)):
    user = _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    try:
        _fsm_transition(db, r, to_status, user_id=getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit(); db.refresh(r)
    return _serialize(r)


@router.delete("/api/requests/{rid}")
async def soft_delete(rid: int, request: Request, db: Session = Depends(get_db)):
    user = _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    from app.models.models import now_utc
    r.deleted_at = now_utc()
    r.deleted_by_user_id = getattr(user, "id", None)
    db.commit()
    return {"ok": True}
```

> `JobDeliverable.project_id`: confirm the column exists (the explore report shows `job_id`, not `project_id`). If `JobDeliverable` has no `project_id`, resolve project via `Job`: `jd.job_id → Job.project_id`. Adjust `_apply_link` accordingly:
> ```python
> if jd is not None:
>     from app.models import Job
>     job = db.get(Job, jd.job_id)
>     r.project_id = getattr(job, "project_id", None) or r.project_id
> ```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/kdm.py tests/test_kdm_router.py
git commit -m "feat(kdm): request create/match/link/transition/delete endpoints"
```

---

## Task 11: Facilities + servers CRUD + cert upload

**Files:**
- Modify: `app/routers/kdm.py`
- Test: `tests/test_kdm_router.py` (extend)

**Interfaces:**
- Consumes: `parse_cert` (Task 7).
- Produces: `GET/POST /kdm/api/facilities`, `PUT/DELETE /kdm/api/facilities/{id}`, `GET/POST /kdm/api/servers`, `PUT/DELETE /kdm/api/servers/{id}`, `POST /kdm/api/servers/{id}/cert`.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_facility_and_server_crud(monkeypatch):
    import app.routers.kdm as kdm_mod
    monkeypatch.setattr(kdm_mod, "_require_kdm", lambda request, db: None)
    r = client.post("/kdm/api/facilities", data={"name": "Arcadia", "kind": "cinema"})
    assert r.status_code == 200
    fid = r.json()["id"]
    r2 = client.post("/kdm/api/servers", data={
        "facility_id": fid, "manufacturer": "christie", "serial": "S-1"})
    assert r2.status_code == 200
    r3 = client.get("/kdm/api/facilities")
    assert any(f["id"] == fid for f in r3.json())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_router.py::test_facility_and_server_crud -v`
Expected: FAIL (`404`).

- [ ] **Step 3: Implement** (append to `app/routers/kdm.py`):

```python
from app.services.kdm_cert import parse_cert


def _fac_json(f: CinemaFacility) -> dict:
    return {"id": f.id, "name": f.name, "city": f.city, "country": f.country,
            "contact_email": f.contact_email, "kind": f.kind}


def _srv_json(s: CinemaServer) -> dict:
    return {"id": s.id, "facility_id": s.facility_id, "manufacturer": s.manufacturer,
            "model": s.model, "serial": s.serial,
            "cert_thumbprint": s.cert_thumbprint,
            "cert_expires_at": s.cert_expires_at.isoformat() if s.cert_expires_at else None}


@router.get("/api/facilities")
async def list_facilities(request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    rows = (db.query(CinemaFacility)
            .filter(CinemaFacility.tenant_id == current_tenant_id(),
                    CinemaFacility.is_active == True)  # noqa: E712
            .order_by(CinemaFacility.name).all())
    return [_fac_json(f) for f in rows]


@router.post("/api/facilities")
async def create_facility(request: Request, db: Session = Depends(get_db),
                          name: str = Form(...), kind: str = Form("cinema"),
                          city: Optional[str] = Form(None),
                          country: Optional[str] = Form(None),
                          contact_email: Optional[str] = Form(None)):
    _require_kdm(request, db)
    f = CinemaFacility(tenant_id=current_tenant_id(), name=name, kind=kind,
                       city=city, country=country, contact_email=contact_email)
    db.add(f); db.commit(); db.refresh(f)
    return _fac_json(f)


@router.put("/api/facilities/{fid}")
async def update_facility(fid: int, request: Request, db: Session = Depends(get_db),
                          name: Optional[str] = Form(None), kind: Optional[str] = Form(None),
                          city: Optional[str] = Form(None), country: Optional[str] = Form(None),
                          contact_email: Optional[str] = Form(None)):
    _require_kdm(request, db)
    f = db.get(CinemaFacility, fid)
    if not f or f.tenant_id != current_tenant_id():
        raise HTTPException(404, "Facility non trovata")
    for k, v in (("name", name), ("kind", kind), ("city", city),
                 ("country", country), ("contact_email", contact_email)):
        if v is not None:
            setattr(f, k, v)
    db.commit(); db.refresh(f)
    return _fac_json(f)


@router.delete("/api/facilities/{fid}")
async def delete_facility(fid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    f = db.get(CinemaFacility, fid)
    if not f or f.tenant_id != current_tenant_id():
        raise HTTPException(404, "Facility non trovata")
    f.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/api/servers")
async def list_servers(request: Request, db: Session = Depends(get_db),
                       facility_id: Optional[int] = None):
    _require_kdm(request, db)
    q = (db.query(CinemaServer)
         .filter(CinemaServer.tenant_id == current_tenant_id(),
                 CinemaServer.is_active == True))  # noqa: E712
    if facility_id:
        q = q.filter(CinemaServer.facility_id == facility_id)
    return [_srv_json(s) for s in q.order_by(CinemaServer.serial).all()]


@router.post("/api/servers")
async def create_server(request: Request, db: Session = Depends(get_db),
                        facility_id: int = Form(...),
                        manufacturer: str = Form("other"),
                        model: Optional[str] = Form(None),
                        serial: Optional[str] = Form(None)):
    _require_kdm(request, db)
    fac = db.get(CinemaFacility, facility_id)
    if not fac or fac.tenant_id != current_tenant_id():
        raise HTTPException(404, "Facility non trovata")
    s = CinemaServer(tenant_id=current_tenant_id(), facility_id=facility_id,
                     manufacturer=manufacturer, model=model, serial=serial)
    db.add(s); db.commit(); db.refresh(s)
    return _srv_json(s)


@router.put("/api/servers/{sid}")
async def update_server(sid: int, request: Request, db: Session = Depends(get_db),
                        manufacturer: Optional[str] = Form(None),
                        model: Optional[str] = Form(None),
                        serial: Optional[str] = Form(None)):
    _require_kdm(request, db)
    s = db.get(CinemaServer, sid)
    if not s or s.tenant_id != current_tenant_id():
        raise HTTPException(404, "Server non trovato")
    for k, v in (("manufacturer", manufacturer), ("model", model), ("serial", serial)):
        if v is not None:
            setattr(s, k, v)
    db.commit(); db.refresh(s)
    return _srv_json(s)


@router.delete("/api/servers/{sid}")
async def delete_server(sid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    s = db.get(CinemaServer, sid)
    if not s or s.tenant_id != current_tenant_id():
        raise HTTPException(404, "Server non trovato")
    s.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/api/servers/{sid}/cert")
async def upload_cert(sid: int, request: Request, db: Session = Depends(get_db),
                      cert_pem: str = Form(...)):
    _require_kdm(request, db)
    s = db.get(CinemaServer, sid)
    if not s or s.tenant_id != current_tenant_id():
        raise HTTPException(404, "Server non trovato")
    meta = parse_cert(cert_pem)
    s.cert_pem = cert_pem
    s.cert_thumbprint = meta["thumbprint"]
    s.cert_expires_at = meta["expires_at"]
    db.commit(); db.refresh(s)
    return _srv_json(s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_router.py::test_facility_and_server_crud -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/kdm.py tests/test_kdm_router.py
git commit -m "feat(kdm): cinema facility + server registry CRUD + cert upload"
```

---

## Task 12: CPL parse + manual + scan endpoints

**Files:**
- Modify: `app/routers/kdm.py`
- Test: `tests/test_kdm_router.py` (extend)

**Interfaces:**
- Consumes: `parse_cpl` (Task 4).
- Produces: `GET /kdm/api/cpl`, `POST /kdm/api/cpl/parse` (multipart file `file` + optional `job_deliverable_id`), `POST /kdm/api/cpl/manual`, `POST /kdm/api/cpl/scan` (stub returning 501-style payload for v1).

- [ ] **Step 1: Write the failing test** (append)

```python
def test_cpl_parse_endpoint(monkeypatch):
    import app.routers.kdm as kdm_mod
    monkeypatch.setattr(kdm_mod, "_require_kdm", lambda request, db: None)
    from pathlib import Path
    xml = (Path(__file__).parent / "fixtures" / "cpl_smpte.xml").read_bytes()
    r = client.post("/kdm/api/cpl/parse",
                    files={"file": ("cpl.xml", xml, "application/xml")})
    assert r.status_code == 200
    assert r.json()["cpl_uuid"].startswith("urn:uuid:")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_router.py::test_cpl_parse_endpoint -v`
Expected: FAIL (`404`).

- [ ] **Step 3: Implement** (append; add `UploadFile, File` to the fastapi import line at top):

```python
from fastapi import UploadFile, File


def _cpl_json(c: DcpCpl) -> dict:
    return {"id": c.id, "cpl_uuid": c.cpl_uuid,
            "content_title_text": c.content_title_text, "source": c.source,
            "encrypted": c.encrypted, "job_deliverable_id": c.job_deliverable_id}


@router.get("/api/cpl")
async def list_cpl(request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    rows = (db.query(DcpCpl)
            .filter(DcpCpl.tenant_id == current_tenant_id(),
                    DcpCpl.is_active == True)  # noqa: E712
            .order_by(DcpCpl.content_title_text).all())
    return [_cpl_json(c) for c in rows]


@router.post("/api/cpl/parse")
async def cpl_parse(request: Request, db: Session = Depends(get_db),
                    file: UploadFile = File(...),
                    job_deliverable_id: Optional[int] = Form(None)):
    _require_kdm(request, db)
    from app.services.cpl_parser import parse_cpl
    data = await file.read()
    try:
        meta = parse_cpl(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    c = DcpCpl(tenant_id=current_tenant_id(), cpl_uuid=meta["cpl_uuid"],
              content_title_text=meta["content_title_text"],
              edit_rate=meta["edit_rate"], duration_frames=meta["duration_frames"],
              encrypted=meta["encrypted"], key_ids=meta["key_ids"],
              source="parsed_xml", job_deliverable_id=job_deliverable_id)
    db.add(c); db.commit(); db.refresh(c)
    return _cpl_json(c)


@router.post("/api/cpl/manual")
async def cpl_manual(request: Request, db: Session = Depends(get_db),
                     cpl_uuid: str = Form(...),
                     content_title_text: Optional[str] = Form(None),
                     job_deliverable_id: Optional[int] = Form(None)):
    _require_kdm(request, db)
    c = DcpCpl(tenant_id=current_tenant_id(), cpl_uuid=cpl_uuid,
              content_title_text=content_title_text, source="manual",
              job_deliverable_id=job_deliverable_id)
    db.add(c); db.commit(); db.refresh(c)
    return _cpl_json(c)


@router.post("/api/cpl/scan")
async def cpl_scan(request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    # v1: lo scan filesystem via agent è progettato ma non implementato.
    # Riusa l'agent storage esistente in fase 2 (memory: browse storage via agent).
    return JSONResponse(status_code=501,
                        content={"ok": False, "detail": "Scan agent in fase 2"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_router.py::test_cpl_parse_endpoint -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/kdm.py tests/test_kdm_router.py
git commit -m "feat(kdm): CPL list/parse/manual endpoints (+scan stub for phase 2)"
```

---

## Task 13: Page UI — tabs + requests table

**Files:**
- Modify: `app/templates/pages/kdm.html` (full version)
- Create: `app/static/js/kdm.js`
- Modify: `app/templates/base.html` (sidebar entry; cache-buster `?v=` on the script)

**Interfaces:**
- Consumes: all `/kdm/api/*` endpoints.
- Produces: page with 3 tabs (`requests`, `facilities`, `cpl`); JS functions `kdmInit()`, `kdmSwitchTab(name)`, `kdmLoadRequests()`, `kdmOpenNewRequest()`.

- [ ] **Step 1: Add the sidebar entry** in `app/templates/base.html` — find the nav block with the other links (search `href="/dam"` or `data-i18n="nav.`), add (place alphabetically/by group near deliveries), gated by permission:

```html
{% if has_permission(current_user, 'manage_kdm') %}
<a href="/kdm" class="nav-link" data-nav="kdm">
  <i data-lucide="key-round"></i> <span data-i18n="nav.kdm">KDM/DKDM</span>
</a>
{% endif %}
```

> Match the exact surrounding markup/classes of adjacent nav links. Confirm the template var for the current user (some templates use `current_user`, some `user`). Use whatever the neighbors use.

- [ ] **Step 2: Write the full page** `app/templates/pages/kdm.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="card">
  <div class="flex items-center justify-between mb-3">
    <div class="card-title"><i data-lucide="key-round"></i>
      <span data-i18n="kdm.title">Richieste KDM/DKDM</span></div>
    <button class="btn btn-primary btn-sm" onclick="kdmOpenNewRequest()">
      + <span data-i18n="kdm.new_request">Nuova richiesta</span></button>
  </div>

  <div class="tab-bar" style="display:flex;gap:6px;margin-bottom:12px;">
    <button class="tab-btn active" data-tab="requests" onclick="kdmSwitchTab('requests')"
      data-i18n="kdm.tab.requests">Richieste</button>
    <button class="tab-btn" data-tab="facilities" onclick="kdmSwitchTab('facilities')"
      data-i18n="kdm.tab.facilities">Cinema/Server</button>
    <button class="tab-btn" data-tab="cpl" onclick="kdmSwitchTab('cpl')"
      data-i18n="kdm.tab.cpl">CPL DCP</button>
  </div>

  <div id="kdm-tab-requests" class="kdm-tab">
    <table class="table" id="kdm-requests-table">
      <thead><tr>
        <th data-i18n="kdm.col.status">Stato</th>
        <th data-i18n="kdm.col.type">Tipo</th>
        <th data-i18n="kdm.col.title">Film/CPL</th>
        <th data-i18n="kdm.col.window">Finestra</th>
        <th data-i18n="kdm.col.match">Match</th>
        <th></th>
      </tr></thead>
      <tbody id="kdm-requests-body"></tbody>
    </table>
  </div>
  <div id="kdm-tab-facilities" class="kdm-tab" style="display:none;"></div>
  <div id="kdm-tab-cpl" class="kdm-tab" style="display:none;"></div>
</div>
<script src="/static/js/kdm.js?v={{ app_version }}"></script>
<script>document.addEventListener('DOMContentLoaded', kdmInit);</script>
{% endblock %}
```

> `app_version` is exposed as a Jinja global (cache-buster convention). Confirm with `grep -n "app_version" app/main.py`.

- [ ] **Step 3: Write** `app/static/js/kdm.js`:

```javascript
// KDM/DKDM page — vanilla JS, usa helper globali api()/toast()/escapeHtml() da global.js
function kdmInit() {
  kdmSwitchTab('requests');
}

function kdmSwitchTab(name) {
  document.querySelectorAll('.kdm-tab').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === name));
  const pane = document.getElementById('kdm-tab-' + name);
  if (pane) pane.style.display = '';
  if (name === 'requests') kdmLoadRequests();
  else if (name === 'facilities') kdmLoadFacilities();
  else if (name === 'cpl') kdmLoadCpl();
}

const KDM_STATUS_ORDER = ['received','matched','keys_pending','generated',
  'delivered','confirmed','rejected','expired'];

async function kdmLoadRequests() {
  const body = document.getElementById('kdm-requests-body');
  body.innerHTML = '';
  let rows = [];
  try { rows = await api('/kdm/api/requests'); }
  catch (e) { toast(t('kdm.load_error') || 'Errore caricamento', 'error'); return; }
  rows.sort((a,b) => KDM_STATUS_ORDER.indexOf(a.status) - KDM_STATUS_ORDER.indexOf(b.status));
  for (const r of rows) {
    const matchBadge = r.dcp_cpl_id
      ? `✓ ${r.matched_confidence ?? ''}` : '⚠';
    const win = (r.valid_from || '') + (r.valid_to ? ' → ' + r.valid_to : '');
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td>${escapeHtml(r.status)}</td>` +
      `<td>${escapeHtml(r.request_type.toUpperCase())}</td>` +
      `<td>${escapeHtml(r.requested_title || r.requested_cpl_uuid || '')}</td>` +
      `<td>${escapeHtml(win)}</td>` +
      `<td>${matchBadge}</td>` +
      `<td><button class="btn btn-sm" onclick="kdmRematch(${r.id})" ` +
      `data-i18n="kdm.action.match">Match</button></td>`;
    body.appendChild(tr);
  }
  if (window.applyI18n) applyI18n();
}

async function kdmRematch(id) {
  try {
    const res = await api('/kdm/api/requests/' + id + '/match', {method:'POST'});
    const n = (res.candidates || []).length;
    toast((t('kdm.candidates') || 'Candidati') + ': ' + n, 'info');
  } catch (e) { toast('Errore match', 'error'); }
}

function kdmOpenNewRequest() {
  // openModal() helper globale; form FormData → POST /kdm/api/requests
  openModal('kdm-new-request');
}

async function kdmLoadFacilities() {
  const pane = document.getElementById('kdm-tab-facilities');
  let rows = [];
  try { rows = await api('/kdm/api/facilities'); } catch (e) { rows = []; }
  pane.innerHTML = rows.map(f =>
    `<div class="row">${escapeHtml(f.name)} — ${escapeHtml(f.kind)}</div>`).join('')
    || '<div data-i18n="kdm.empty.facilities">Nessun cinema</div>';
  if (window.applyI18n) applyI18n();
}

async function kdmLoadCpl() {
  const pane = document.getElementById('kdm-tab-cpl');
  let rows = [];
  try { rows = await api('/kdm/api/cpl'); } catch (e) { rows = []; }
  pane.innerHTML = rows.map(c =>
    `<div class="row">${escapeHtml(c.content_title_text || c.cpl_uuid)}</div>`).join('')
    || '<div data-i18n="kdm.empty.cpl">Nessuna CPL</div>';
  if (window.applyI18n) applyI18n();
}
```

> Use the project's real global helpers. Confirm names with `grep -n "function api\|function toast\|function openModal\|function escapeHtml\|function t(" app/static/js/global.js`. If `t()` / `applyI18n()` differ, match the actual i18n API used by other pages (open `app/static/js/i18n.js` to see the exported function).

- [ ] **Step 4: Manual smoke (server must be restarted — OneDrive breaks reload)**

Run (PowerShell): restart server, then:
Run: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/kdm`
Expected: `200` (when logged in) or auth redirect. Open `/kdm` in browser: 3 tabs switch, no JS ReferenceError in console.

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/kdm.html app/static/js/kdm.js app/templates/base.html
git commit -m "feat(kdm): tabbed page UI + sidebar entry + requests/facilities/cpl tabs"
```

---

## Task 14: i18n strings (5 languages)

**Files:**
- Modify: `app/static/js/i18n.js`
- Test: `tests/test_kdm_i18n.py`

**Interfaces:**
- Produces: keys `nav.kdm`, `kdm.title`, `kdm.new_request`, `kdm.tab.requests`, `kdm.tab.facilities`, `kdm.tab.cpl`, `kdm.col.status`, `kdm.col.type`, `kdm.col.title`, `kdm.col.window`, `kdm.col.match`, `kdm.action.match`, `kdm.candidates`, `kdm.load_error`, `kdm.empty.facilities`, `kdm.empty.cpl` in all 5 locale blocks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_i18n.py
import re
from pathlib import Path

I18N = Path("app/static/js/i18n.js").read_text(encoding="utf-8")
KEYS = ["nav.kdm", "kdm.title", "kdm.tab.requests", "kdm.tab.facilities",
        "kdm.tab.cpl", "kdm.col.status", "kdm.action.match"]


def test_kdm_keys_present_in_all_locales():
    # crude: each key string must appear at least 5 times (it/en/fr/de/es)
    for k in KEYS:
        assert I18N.count(f'"{k}"') >= 5, f"{k} missing in some locale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_i18n.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the strings** — open `app/static/js/i18n.js`, locate each of the 5 locale objects (`it`, `en`, `fr`, `de`, `es`) and add the keys. Match the file's existing key style (flat `"kdm.tab.requests"` vs nested — inspect a neighboring key like `"nav.dam"` first and follow it exactly). Translations:

| key | it | en | fr | de | es |
|---|---|---|---|---|---|
| nav.kdm | KDM/DKDM | KDM/DKDM | KDM/DKDM | KDM/DKDM | KDM/DKDM |
| kdm.title | Richieste KDM/DKDM | KDM/DKDM Requests | Demandes KDM/DKDM | KDM/DKDM-Anfragen | Solicitudes KDM/DKDM |
| kdm.new_request | Nuova richiesta | New request | Nouvelle demande | Neue Anfrage | Nueva solicitud |
| kdm.tab.requests | Richieste | Requests | Demandes | Anfragen | Solicitudes |
| kdm.tab.facilities | Cinema/Server | Cinemas/Servers | Cinémas/Serveurs | Kinos/Server | Cines/Servidores |
| kdm.tab.cpl | CPL DCP | DCP CPLs | CPL DCP | DCP-CPLs | CPL DCP |
| kdm.col.status | Stato | Status | Statut | Status | Estado |
| kdm.col.type | Tipo | Type | Type | Typ | Tipo |
| kdm.col.title | Film/CPL | Film/CPL | Film/CPL | Film/CPL | Película/CPL |
| kdm.col.window | Finestra | Window | Fenêtre | Zeitfenster | Ventana |
| kdm.col.match | Match | Match | Correspondance | Treffer | Coincidencia |
| kdm.action.match | Match | Match | Associer | Zuordnen | Asociar |
| kdm.candidates | Candidati | Candidates | Candidats | Kandidaten | Candidatos |
| kdm.load_error | Errore caricamento | Load error | Erreur de chargement | Ladefehler | Error de carga |
| kdm.empty.facilities | Nessun cinema | No cinemas | Aucun cinéma | Keine Kinos | Sin cines |
| kdm.empty.cpl | Nessuna CPL | No CPLs | Aucune CPL | Keine CPLs | Sin CPL |

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_i18n.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/i18n.js tests/test_kdm_i18n.py
git commit -m "feat(kdm): i18n strings (it/en/fr/de/es)"
```

---

## Task 15: AI capabilities

**Files:**
- Modify: `app/services/ai_assistant.py` (register handlers + extend `build_context`)
- Test: `tests/test_kdm_ai.py`

**Interfaces:**
- Consumes: `match_request`, models.
- Produces: capabilities `propose_kdm_request`, `propose_cinema_server` registered in the AI registry; `build_context` includes open KDM requests + available CPL count.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_ai.py
from app.services.ai_capability_registry import get_action_types, get_handler


def test_kdm_capabilities_registered():
    import app.services.ai_assistant  # noqa: F401  (forces registration)
    types = get_action_types()
    assert "propose_kdm_request" in types
    assert "propose_cinema_server" in types
    assert callable(get_handler("propose_kdm_request"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kdm_ai.py -v`
Expected: FAIL.

- [ ] **Step 3: Register the capabilities** — in `app/services/ai_assistant.py`, follow the existing `@ai_capability("propose_...")` handler pattern (same signature as `propose_quote_line` — inspect one first). Add:

```python
from app.services.ai_capability_registry import ai_capability
from app.context import current_tenant_id


@ai_capability("propose_cinema_server", category="mutation")
def _h_propose_cinema_server(db, data, context=None):
    """Crea/registra un cinema + server dal testo della richiesta cliente.
    data: {facility_name, city?, manufacturer?, serial?, kind?}"""
    from app.models import CinemaFacility, CinemaServer
    fac = CinemaFacility(tenant_id=current_tenant_id(),
                         name=data["facility_name"], city=data.get("city"),
                         kind=data.get("kind", "cinema"))
    db.add(fac); db.flush()
    srv = CinemaServer(tenant_id=current_tenant_id(), facility_id=fac.id,
                       manufacturer=data.get("manufacturer", "other"),
                       serial=data.get("serial"))
    db.add(srv); db.commit()
    return {"facility_id": fac.id, "server_id": srv.id}


@ai_capability("propose_kdm_request", category="mutation")
def _h_propose_kdm_request(db, data, context=None):
    """Crea una richiesta KDM/DKDM e lancia l'auto-match CPL.
    data: {request_type(kdm|dkdm), client_id?(PK int), requested_title?,
           requested_cpl_uuid?, target_server_id?(PK int), valid_from?, valid_to?}"""
    from app.models import KdmRequest
    from app.services.kdm_match import match_request, AUTO_LINK_THRESHOLD
    r = KdmRequest(tenant_id=current_tenant_id(),
                   request_type=data.get("request_type", "kdm"),
                   client_id=data.get("client_id"),
                   requested_title=data.get("requested_title"),
                   requested_cpl_uuid=data.get("requested_cpl_uuid"),
                   target_server_id=data.get("target_server_id"),
                   status="received")
    db.add(r); db.flush()
    cands = match_request(db, r)
    if cands and cands[0]["confidence"] >= AUTO_LINK_THRESHOLD:
        r.dcp_cpl_id = cands[0]["dcp_cpl_id"]
        r.matched_confidence = cands[0]["confidence"]
        r.match_source = cands[0]["source"]
        r.status = "matched"
    db.commit()
    return {"kdm_request_id": r.id, "status": r.status,
            "candidates": cands[:5]}
```

> The handler signature MUST match the project's registry calling convention. Inspect an existing handler (e.g. `grep -n "def _h_propose_quote_line" app/services/ai_assistant.py`) and mirror its exact parameters (it may be `(db, data, ...)` or include `user`/`context`). Adjust the two handlers above to match — same params, same return shape (dict serialized into the AIAction proposal).

- [ ] **Step 4: Extend `build_context`** — find `def build_context(` in `app/services/ai_assistant.py` and add, near where other DB overviews are assembled, a compact KDM summary (guard with try/except so it never breaks context for legacy providers — memory: copilot legacy provider context):

```python
    try:
        from app.models import KdmRequest, DcpCpl
        open_kdm = (db.query(KdmRequest)
                    .filter(KdmRequest.tenant_id == current_tenant_id(),
                            KdmRequest.deleted_at.is_(None),
                            KdmRequest.status.notin_(["confirmed", "rejected", "expired"]))
                    .count())
        cpl_count = (db.query(DcpCpl)
                     .filter(DcpCpl.tenant_id == current_tenant_id(),
                             DcpCpl.is_active == True).count())  # noqa: E712
        context_lines.append(f"RICHIESTE KDM APERTE: {open_kdm} · CPL DCP indicizzate: {cpl_count}")
    except Exception:
        pass
```

> `context_lines` is illustrative — append to whatever string/list `build_context` actually accumulates. Inspect the function body and match its real accumulation variable.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_kdm_ai.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/ai_assistant.py tests/test_kdm_ai.py
git commit -m "feat(kdm): AI capabilities propose_kdm_request + propose_cinema_server + context"
```

---

## Task 16: E2E + version bump + changelog

**Files:**
- Create: `tests/e2e/test_kdm_e2e.py` (Playwright) — or extend the existing E2E suite following its pattern
- Modify: `app/main.py` (version bump), `CHANGELOG.md`, `docs/STATO.md`

**Interfaces:** none new.

- [ ] **Step 1: Find the E2E pattern** — locate the existing Playwright E2E directory (`grep -rln "playwright\|sync_playwright\|page.goto" tests/` ). Mirror its login + fixture-DB setup helper. Do NOT invent a new harness.

- [ ] **Step 2: Write the E2E test** following that pattern. Flow to assert:

```
1. login as admin
2. goto /kdm → 3 tabs visible
3. CPL tab → import tests/fixtures/cpl_smpte.xml → row appears with QUEER title
4. Requests tab → new request, type=kdm, requested_cpl_uuid = the CPL's uuid
   → after save, row shows status "matched" + ✓ badge (auto-link ≥95)
5. open request → transition matched→keys_pending→generated→delivered→confirmed
   → each step persists (reload, status stays)
```

Use the existing E2E helpers for login/navigation; assert on visible text (status badges) and absence of console errors.

- [ ] **Step 3: Run E2E**

Run: the project's E2E command (check `package.json`/`pytest.ini`/a `run_e2e` script; e.g. `python -m pytest tests/e2e/test_kdm_e2e.py -v`). Server must be running and restarted (OneDrive reload caveat).
Expected: PASS.

- [ ] **Step 4: Run the full unit suite (no regressions)**

Run: `python -m pytest tests/test_kdm_*.py tests/test_cpl_parser.py -v`
Expected: all PASS.
Run: `python -m pytest -q` (full suite)
Expected: no new failures vs baseline.

- [ ] **Step 5: Bump version + changelog** — bump the version constant in `app/main.py` (find with `grep -n "172.225\|version" app/main.py | head`) to `3.5.0-alpha.172.226`. Add a `CHANGELOG.md` entry. Update `docs/STATO.md` (current version + "in corso"/"prossimo step" sections).

- [ ] **Step 6: Commit**

```bash
git add tests/e2e app/main.py CHANGELOG.md docs/STATO.md
git commit -m "feat(kdm): E2E KDM flow + bump v3.5.0-alpha.172.226 + changelog/STATO"
```

---

## Self-Review Notes (resolve during execution)

These are codebase-fact confirmations the implementer MUST verify (flagged inline above):

1. `JSON` imported in `models.py`; `assets` table name for `kdm_file_asset_id` FK.
2. `JobDeliverable` has no `project_id` — resolve project via `Job.project_id` in `_apply_link`.
3. `current_user_optional(request, db)` exact signature (arg count) in `rbac.py`.
4. Global JS helpers actual names: `api`, `toast`, `openModal`, `escapeHtml`, i18n `t()`/`applyI18n()`.
5. `app_version` Jinja global exists (cache-buster); template var for current user in `base.html` nav.
6. AI handler calling convention in `ai_assistant.py` (params + return shape) — mirror an existing `propose_*`.
7. `build_context` real accumulation variable.
8. PERMISSIONS dict category to place `manage_kdm`; manager preset list location.

Each is a 1-line grep before writing the dependent code. None changes the design — they pin the plan to current code.
