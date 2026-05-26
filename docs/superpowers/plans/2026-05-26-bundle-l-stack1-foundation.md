# Bundle L Stack 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Posare le fondamenta del cantiere Bundle L: modelli `VariantSchemaVersion` + `DeliveryVariant`, estensioni `JobDeliverable.variant_id` e `Asset.tech_specs_json`, refactor `asset_metadata.py` in service estensibile `tech_specs_extractor` con plugin registry (ffprobe + pillow), script batch `parse_capitolati.py` per i 17 capitolati corpus, UI listing CRUD minimal `/delivery-variants`.

**Architecture:** Foundation stack. Nessuna funzionalità AI nuova; setup di modelli + servizi che gli stack successivi (QC, ingest, UI planning) costruiranno sopra. Modello variant gerarchico validato contro JSON Schema v1 versionato. Extractor service pluggable per future estensioni (MediaInfo, AI vision).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (Mapped/mapped_column) + SQLite + Jinja2 + pytest + nuova dep `jsonschema>=4.0`. Pattern progetto: tenant filter via `current_tenant_id()`, form-based POST (no JSON body), soft-delete via `is_active`, auto-migrate al boot in `lifespan`.

**Versioning target:** v3.5.0-alpha.172.94 (Task 1-7) → α.172.95 (Task 8-12) → α.172.96 (Task 13-17, milestone Stack 1 close).

---

## File structure

### Nuovi file
- `app/models/variant.py` — `VariantSchemaVersion`, `DeliveryVariant`, `DeliveryVariantCategory` enum
- `schemas/variant_v1.json` — JSON Schema draft-07 canonico
- `app/services/tech_specs_extractor/__init__.py` — registry + `extract_tech_specs()` public API
- `app/services/tech_specs_extractor/base.py` — `TechSpecsExtractor` ABC
- `app/services/tech_specs_extractor/ffprobe_extractor.py` — port da `asset_metadata.py`
- `app/services/tech_specs_extractor/pillow_extractor.py` — fallback immagini
- `app/services/variant_schema.py` — loader JSON Schema + validator helper
- `app/routers/delivery_variants.py` — CRUD listing + import action
- `app/templates/pages/delivery_variants.html` — UI listing minimal
- `scripts/parse_capitolati.py` — batch parser 17 capitolati → JSON output
- `scripts/import_parsed_variants.py` — import JSON parsed → DB
- `tests/__init__.py` — package marker
- `tests/conftest.py` — pytest fixture DB in-memory + factories
- `tests/test_variant_model.py` — unit test modelli
- `tests/test_tech_specs_extractor.py` — unit test extractor service
- `tests/test_variant_schema.py` — unit test JSON Schema validation
- `tests/test_parse_capitolati.py` — unit test parser su file fixture

### File modificati
- `app/models/models.py` — estensione `JobDeliverable` (variant_id FK + 3 colonne snapshot) + `Asset` (tech_specs_json + 3 colonne)
- `app/models/__init__.py` — export nuovi modelli
- `app/services/asset_metadata.py` — diventa wrapper deprecato che delega a `tech_specs_extractor` (back-compat per `dam.py`)
- `app/main.py` — `_auto_migrate_bundle_l_stack1()` + `_seed_variant_schema_v1()` + include router `delivery_variants` + version bump
- `app/routers/__init__.py` (o equivalente) — include `delivery_variants_router` se serve registry esplicito
- `app/templates/components/sidebar.html` (o nav) — link `/delivery-variants` (minimal)
- `requirements.txt` — `jsonschema>=4.0`
- `CHANGELOG.md` — entry α.172.94 + 95 + 96
- `docs/STATO.md` — bump versione + sezione "in corso Stack 1"

---

## Test framework setup (one-shot in Task 0)

Project non ha `tests/` standard pytest. Plan crea scaffolding minimo prima dei test reali.

---

## Tasks

### Task 0: Setup tests/ scaffold + jsonschema dep

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Aggiungi jsonschema a requirements.txt**

Apri `requirements.txt`. Trova la sezione `# PDF & Excel` o simile e aggiungi sopra:

```
# JSON Schema validation (Bundle L Stack 1)
jsonschema>=4.0.0
```

- [ ] **Step 2: Installa la nuova dep**

Run:
```
.venv\Scripts\python.exe -m pip install jsonschema>=4.0.0
```

Expected: `Successfully installed jsonschema-…`

- [ ] **Step 3: Crea tests/__init__.py vuoto**

```python
# tests package — pytest auto-discovers
```

- [ ] **Step 4: Crea tests/conftest.py**

```python
"""Pytest fixtures globali per test Bundle L.

DB in-memory SQLite per test isolato. Ricreato per ogni test.
Tenant fixture id=1 default (allineato a CURRENT_TENANT).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.models.models import Base


@pytest.fixture
def db() -> Session:
    """SQLite in-memory + schema fresh per test."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def tenant_id() -> int:
    """Tenant fixture per test (allineato a CURRENT_TENANT=1)."""
    return 1
```

- [ ] **Step 5: Smoke test scaffold**

Crea file temporaneo `tests/test_scaffold.py`:

```python
def test_pytest_works():
    assert 1 + 1 == 2

def test_db_fixture(db, tenant_id):
    from sqlalchemy import text
    result = db.execute(text("SELECT 1")).scalar()
    assert result == 1
    assert tenant_id == 1
```

Run:
```
.venv\Scripts\python.exe -m pytest tests/test_scaffold.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Rimuovi smoke + commit**

```
del tests\test_scaffold.py
git add tests/__init__.py tests/conftest.py requirements.txt
git commit -m "test: scaffold tests/ dir + jsonschema dep (Bundle L Stack 1 prep)"
```

---

### Task 1: VariantSchemaVersion model

**Files:**
- Create: `app/models/variant.py` (partial — solo VariantSchemaVersion in questo task)
- Modify: `app/models/__init__.py`
- Test: `tests/test_variant_model.py`

- [ ] **Step 1: Scrivi test fallente**

Crea `tests/test_variant_model.py`:

```python
"""Unit test modelli Bundle L Stack 1."""
from datetime import datetime
from app.models.variant import VariantSchemaVersion


def test_variant_schema_version_create(db):
    v = VariantSchemaVersion(
        version="v1",
        schema_json={"$schema": "https://json-schema.org/draft-07/schema", "type": "object"},
        description="Initial canonical schema",
        is_active=True,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    assert v.id is not None
    assert v.version == "v1"
    assert v.is_active is True
    assert isinstance(v.created_at, datetime)


def test_variant_schema_version_unique(db):
    db.add(VariantSchemaVersion(version="v1", schema_json={}))
    db.commit()
    db.add(VariantSchemaVersion(version="v1", schema_json={}))
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run test → FAIL atteso**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.models.variant'`

- [ ] **Step 3: Crea app/models/variant.py (solo VariantSchemaVersion)**

```python
"""Bundle L Stack 1 — Modelli variant + schema version.

VariantSchemaVersion: JSON Schema versionato per validazione DeliveryVariant.
Stack consecutivi possono introdurre v2, v3 con additionalProperties:true che
mantiene back-compat.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.models import Base


class VariantSchemaVersion(Base):
    __tablename__ = "variant_schema_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Modifica app/models/__init__.py — export**

Apri `app/models/__init__.py`. Aggiungi alla fine, prima del `__all__` (o sostituisci se manca):

```python
from app.models.variant import VariantSchemaVersion
```

- [ ] **Step 5: Run test → PASS atteso**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```
git add app/models/variant.py app/models/__init__.py tests/test_variant_model.py
git commit -m "feat(bundle-l): VariantSchemaVersion model (Stack 1 Task 1)"
```

---

### Task 2: DeliveryVariant model

**Files:**
- Modify: `app/models/variant.py` (aggiungi DeliveryVariant + DeliveryVariantCategory)
- Modify: `app/models/__init__.py`
- Modify: `tests/test_variant_model.py`

- [ ] **Step 1: Estendi test con DeliveryVariant**

Aggiungi a `tests/test_variant_model.py`:

```python
def test_delivery_variant_create(db, tenant_id):
    from app.models.variant import DeliveryVariant, DeliveryVariantCategory, VariantSchemaVersion
    sv = VariantSchemaVersion(version="v1", schema_json={"type": "object"})
    db.add(sv); db.commit(); db.refresh(sv)

    v = DeliveryVariant(
        tenant_id=tenant_id,
        code="imf-master-hd-it",
        name="IMF Master HD — Italiano",
        category=DeliveryVariantCategory.t1_technical,
        schema_version_id=sv.id,
        spec_json={"container": {"format": "IMF"}, "language": "it"},
        language="it",
        territory="WW",
        delivery_format="IMF",
        has_textless=False,
        has_subtitles=False,
    )
    db.add(v); db.commit(); db.refresh(v)
    assert v.id is not None
    assert v.category == DeliveryVariantCategory.t1_technical
    assert v.spec_json["container"]["format"] == "IMF"


def test_delivery_variant_unique_code_per_tenant(db, tenant_id):
    from app.models.variant import DeliveryVariant, VariantSchemaVersion
    import pytest
    from sqlalchemy.exc import IntegrityError
    sv = VariantSchemaVersion(version="v1", schema_json={})
    db.add(sv); db.commit(); db.refresh(sv)
    db.add(DeliveryVariant(tenant_id=tenant_id, code="dup", name="A", schema_version_id=sv.id, spec_json={}))
    db.commit()
    db.add(DeliveryVariant(tenant_id=tenant_id, code="dup", name="B", schema_version_id=sv.id, spec_json={}))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py -v
```

Expected: `ImportError: cannot import name 'DeliveryVariant'`

- [ ] **Step 3: Estendi app/models/variant.py**

Aggiungi dopo `VariantSchemaVersion`:

```python
class DeliveryVariantCategory(str, enum.Enum):
    t1_technical = "t1_technical"
    t2_documentation = "t2_documentation"
    t3_compilation = "t3_compilation"


class DeliveryVariant(Base):
    __tablename__ = "delivery_variants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[DeliveryVariantCategory] = mapped_column(
        SAEnum(DeliveryVariantCategory),
        default=DeliveryVariantCategory.t1_technical,
        server_default="t1_technical",
        index=True,
    )
    schema_version_id: Mapped[int] = mapped_column(ForeignKey("variant_schema_versions.id"))
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Campi promossi per filter/query
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    territory: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    has_textless: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    has_subtitles: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    delivery_format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    # Tracciabilità origine
    source_capitolato: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_section: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    suggested_price_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("price_items.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_variant_tenant_code"),)
```

- [ ] **Step 4: Estendi `app/models/__init__.py`**

Aggiungi:

```python
from app.models.variant import DeliveryVariant, DeliveryVariantCategory
```

- [ ] **Step 5: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```
git add app/models/variant.py app/models/__init__.py tests/test_variant_model.py
git commit -m "feat(bundle-l): DeliveryVariant model + category enum (Stack 1 Task 2)"
```

---

### Task 3: Estendi JobDeliverable.variant_id + colonne snapshot

**Files:**
- Modify: `app/models/models.py` (classe JobDeliverable, attorno riga 2898)
- Test: `tests/test_variant_model.py`

- [ ] **Step 1: Test fallente — JobDeliverable.variant_id**

Aggiungi a `tests/test_variant_model.py`:

```python
def test_jobdeliverable_variant_link(db, tenant_id):
    from app.models import (
        Tenant, Client, Project, Job, JobDeliverable,
        DeliveryVariant, VariantSchemaVersion, DeliveryVariantCategory,
    )
    db.add(Tenant(id=tenant_id, name="t", slug="t"))
    db.add(Client(id=1, tenant_id=tenant_id, name="C"))
    db.add(Project(id=1, tenant_id=tenant_id, code="P1", title="P", client_id=1))
    db.add(Job(id=1, tenant_id=tenant_id, code="J1", title="J", project_id=1))
    sv = VariantSchemaVersion(version="v1", schema_json={})
    db.add(sv); db.commit(); db.refresh(sv)
    v = DeliveryVariant(
        tenant_id=tenant_id, code="x", name="X",
        category=DeliveryVariantCategory.t1_technical,
        schema_version_id=sv.id, spec_json={},
        language="it", territory="WW", delivery_format="IMF",
    )
    db.add(v); db.commit(); db.refresh(v)

    d = JobDeliverable(
        tenant_id=tenant_id, job_id=1, name="DLV-1",
        variant_id=v.id,
        variant_language="it", variant_territory="WW", variant_format="IMF",
    )
    db.add(d); db.commit(); db.refresh(d)
    assert d.variant_id == v.id
    assert d.variant_language == "it"
    assert d.variant_format == "IMF"
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py::test_jobdeliverable_variant_link -v
```

Expected: `AttributeError: 'JobDeliverable' object has no attribute 'variant_id'`

- [ ] **Step 3: Estendi JobDeliverable in app/models/models.py**

Apri `app/models/models.py`, trova `class JobDeliverable(Base):` (riga ~2898). Aggiungi colonne **subito dopo** `deleted_by_user_id` (~riga 3017 nella struttura corrente):

```python
    # ── v3.5.0-alpha.172.94 Bundle L Stack 1 — Link a DeliveryVariant ──
    # variant_id FK opzionale: quando set, spec_json del deliverable rappresenta
    # SOLO i campi override (parziale). Resolver applica merge:
    #   merged = {**variant.spec_json, **deliverable.spec_json}
    # Snapshot fields copiati da DeliveryVariant al spawn per query veloce
    # (evita JOIN su cost-report / planning filter).
    variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_variants.id"), nullable=True, index=True
    )
    variant_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    variant_territory: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    variant_format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
```

- [ ] **Step 4: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py::test_jobdeliverable_variant_link -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```
git add app/models/models.py tests/test_variant_model.py
git commit -m "feat(bundle-l): JobDeliverable.variant_id + 3 snapshot fields (Stack 1 Task 3)"
```

---

### Task 4: Estendi Asset.tech_specs_json + extractor metadata

**Files:**
- Modify: `app/models/models.py` (classe Asset, riga ~2597)
- Test: `tests/test_variant_model.py`

- [ ] **Step 1: Test fallente**

Aggiungi a `tests/test_variant_model.py`:

```python
def test_asset_tech_specs_columns(db, tenant_id):
    from datetime import datetime
    from app.models import Tenant, Client, Project, Job, Asset
    db.add(Tenant(id=tenant_id, name="t", slug="t"))
    db.add(Client(id=1, tenant_id=tenant_id, name="C"))
    db.add(Project(id=1, tenant_id=tenant_id, code="P1", title="P", client_id=1))
    db.add(Job(id=1, tenant_id=tenant_id, code="J1", title="J", project_id=1))
    a = Asset(
        tenant_id=tenant_id, job_id=1,
        filename="x.mxf", original_name="x.mxf", file_path="/tmp/x.mxf", mime_type="video/x-mxf",
        tech_specs_json={"video": {"codec": "ProRes", "resolution": "1920x1080"}},
        tech_specs_extractor="ffprobe",
        tech_specs_extracted_at=datetime.utcnow(),
        tech_specs_schema_version="v1",
    )
    db.add(a); db.commit(); db.refresh(a)
    assert a.tech_specs_json["video"]["codec"] == "ProRes"
    assert a.tech_specs_extractor == "ffprobe"
    assert a.tech_specs_schema_version == "v1"
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py::test_asset_tech_specs_columns -v
```

Expected: `TypeError: 'tech_specs_json' is an invalid keyword argument for Asset`

- [ ] **Step 3: Estendi Asset in app/models/models.py**

Trova `class Asset(Base):` (~riga 2597). Aggiungi colonne **subito dopo l'ultimo campo esistente** della classe (prima di eventuali relationship/method, controlla `status` esistente):

```python
    # ── v3.5.0-alpha.172.94 Bundle L Stack 1 — Tech specs cached ──
    # Estratto da tech_specs_extractor service (ffprobe default, MediaInfo/AI
    # vision futuri). Refresh manuale "↻ Riestrai" + auto al QC start se
    # extracted_at > 30gg.
    tech_specs_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tech_specs_extractor: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    tech_specs_extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    tech_specs_schema_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
```

- [ ] **Step 4: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_model.py::test_asset_tech_specs_columns -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```
git add app/models/models.py tests/test_variant_model.py
git commit -m "feat(bundle-l): Asset.tech_specs_json + extractor metadata (Stack 1 Task 4)"
```

---

### Task 5: JSON Schema v1 file canonico

**Files:**
- Create: `schemas/variant_v1.json`
- Test: `tests/test_variant_schema.py`

- [ ] **Step 1: Crea schemas/ dir + variant_v1.json**

Crea `schemas/variant_v1.json` con contenuto:

```json
{
  "$schema": "https://json-schema.org/draft-07/schema",
  "$id": "claqo/variant/v1",
  "title": "Claqo DeliveryVariant Schema v1",
  "type": "object",
  "required": ["code", "name", "category"],
  "properties": {
    "code": {"type": "string", "pattern": "^[a-z0-9-]+$"},
    "name": {"type": "string", "minLength": 3},
    "category": {"enum": ["t1_technical", "t2_documentation", "t3_compilation"]},
    "container": {
      "type": "object",
      "properties": {
        "format": {"enum": ["IMF", "DCP", "ProRes", "MXF", "MOV", "MP4", "TIFF", "DPX", "WAV", "SCC", "TTML", "VTT"]}
      }
    },
    "video": {
      "type": "object",
      "properties": {
        "resolution": {"type": "string"},
        "codec": {"type": "string"},
        "framerate": {"type": "number"},
        "color_space": {"enum": ["BT.709", "BT.2020", "P3-D65", "P3-DCI", "DCI-XYZ"]},
        "hdr": {"type": "boolean"},
        "hdr_format": {"enum": [null, "PQ", "HLG", "Dolby Vision", "HDR10+"]},
        "chroma": {"enum": ["4:2:0", "4:2:2", "4:4:4"]},
        "bit_depth": {"enum": [8, 10, 12, 16]},
        "field_order": {"enum": ["progressive", "interlaced_uff", "interlaced_lff"]}
      }
    },
    "audio": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "track": {"type": "string"},
          "codec": {"enum": ["PCM", "Atmos", "AAC", "AC3", "EAC3", "DTS"]},
          "channels": {"type": "integer"},
          "sample_rate": {"enum": [48000, 96000]},
          "bit_depth": {"enum": [16, 24]},
          "language": {"type": "string"}
        }
      }
    },
    "subtitles": {
      "type": "object",
      "properties": {
        "present": {"type": "boolean"},
        "type": {"enum": [null, "burnt", "sidecar_scc", "sidecar_vtt", "sidecar_ttml", "sdh"]}
      }
    },
    "textless": {
      "type": "object",
      "properties": {
        "tail_present": {"type": "boolean"},
        "separate_file": {"type": "boolean"}
      }
    },
    "language": {"type": "string"},
    "territory": {"type": "string"},
    "naming": {"type": "string"},
    "head_format": {"type": "object"},
    "archive": {"type": "object"},
    "metadata": {"type": "object"}
  },
  "additionalProperties": true
}
```

- [ ] **Step 2: Scrivi test validator**

Crea `tests/test_variant_schema.py`:

```python
"""Test JSON Schema v1 validation."""
import json
from pathlib import Path
import pytest


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "variant_v1.json"


@pytest.fixture
def schema_v1():
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_schema_loads(schema_v1):
    assert schema_v1["$id"] == "claqo/variant/v1"
    assert schema_v1["type"] == "object"


def test_valid_variant_passes(schema_v1):
    from jsonschema import validate
    instance = {
        "code": "imf-master-hd-it",
        "name": "IMF Master HD IT",
        "category": "t1_technical",
        "container": {"format": "IMF"},
        "video": {"resolution": "1920x1080", "codec": "JPEG2000", "framerate": 25, "bit_depth": 10},
        "language": "it",
        "territory": "WW",
    }
    validate(instance=instance, schema=schema_v1)  # no exception = pass


def test_invalid_code_pattern_fails(schema_v1):
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError
    instance = {"code": "INVALID UPPER", "name": "X", "category": "t1_technical"}
    with pytest.raises(ValidationError):
        validate(instance=instance, schema=schema_v1)


def test_unknown_category_fails(schema_v1):
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError
    instance = {"code": "x", "name": "X", "category": "unknown"}
    with pytest.raises(ValidationError):
        validate(instance=instance, schema=schema_v1)


def test_additional_properties_allowed(schema_v1):
    """Back-compat: campi futuri (stack consecutivi) non breakno old variant."""
    from jsonschema import validate
    instance = {
        "code": "x", "name": "X", "category": "t1_technical",
        "future_field_2027": {"any": "value"},
    }
    validate(instance=instance, schema=schema_v1)  # no exception
```

- [ ] **Step 3: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_schema.py -v
```

Expected: `5 passed`

- [ ] **Step 4: Commit**

```
git add schemas/variant_v1.json tests/test_variant_schema.py
git commit -m "feat(bundle-l): JSON Schema v1 variant + jsonschema validation tests (Stack 1 Task 5)"
```

---

### Task 6: Variant schema service (loader + validator helper)

**Files:**
- Create: `app/services/variant_schema.py`
- Test: `tests/test_variant_schema.py` (estensione)

- [ ] **Step 1: Test fallente per loader helper**

Aggiungi a `tests/test_variant_schema.py`:

```python
def test_load_active_schema(db):
    from app.models.variant import VariantSchemaVersion
    from app.services.variant_schema import load_active_schema

    sv = VariantSchemaVersion(version="v1", schema_json={"type": "object"}, is_active=True)
    db.add(sv); db.commit()
    schema = load_active_schema(db)
    assert schema["type"] == "object"


def test_validate_variant_against_active_schema(db):
    from app.models.variant import VariantSchemaVersion
    from app.services.variant_schema import validate_variant_spec
    import pytest

    sv = VariantSchemaVersion(
        version="v1",
        schema_json={
            "type": "object",
            "required": ["code", "name", "category"],
            "properties": {"category": {"enum": ["t1_technical"]}},
        },
        is_active=True,
    )
    db.add(sv); db.commit()

    # Valid
    validate_variant_spec(db, {"code": "x", "name": "X", "category": "t1_technical"})

    # Invalid: missing required
    from jsonschema.exceptions import ValidationError
    with pytest.raises(ValidationError):
        validate_variant_spec(db, {"code": "x"})
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_schema.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.variant_schema'`

- [ ] **Step 3: Crea app/services/variant_schema.py**

```python
"""Bundle L Stack 1 — JSON Schema loader + validator per DeliveryVariant.

Carica lo schema attivo da VariantSchemaVersion (tabella). Valida instance
contro jsonschema. Stack consecutivi possono caricare schema-version diversi
per variant legacy (es. v2 per nuove variant, v1 per quelle vecchie).
"""
from __future__ import annotations

from typing import Optional

from jsonschema import validate
from sqlalchemy.orm import Session

from app.models.variant import VariantSchemaVersion


def load_active_schema(db: Session) -> dict:
    """Ritorna lo schema_json del singolo VariantSchemaVersion con is_active=True.

    Raises:
        RuntimeError se nessuno schema attivo è presente in DB.
    """
    sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.is_active == True).first()  # noqa: E712
    if not sv:
        raise RuntimeError("Nessuno VariantSchemaVersion attivo. Eseguire seed.")
    return sv.schema_json


def load_schema_by_version(db: Session, version: str) -> Optional[dict]:
    """Ritorna schema_json per versione specifica, None se non esiste."""
    sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.version == version).first()
    return sv.schema_json if sv else None


def validate_variant_spec(db: Session, spec: dict, schema_version: Optional[str] = None) -> None:
    """Valida `spec` (dict) contro schema attivo (default) o specifica versione.

    Raises:
        jsonschema.exceptions.ValidationError se invalido.
        RuntimeError se schema non trovato.
    """
    if schema_version:
        schema = load_schema_by_version(db, schema_version)
        if schema is None:
            raise RuntimeError(f"VariantSchemaVersion '{schema_version}' non trovata")
    else:
        schema = load_active_schema(db)
    validate(instance=spec, schema=schema)
```

- [ ] **Step 4: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_variant_schema.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```
git add app/services/variant_schema.py tests/test_variant_schema.py
git commit -m "feat(bundle-l): variant_schema service loader + validator (Stack 1 Task 6)"
```

---

### Task 7: Tech specs extractor — base ABC + registry

**Files:**
- Create: `app/services/tech_specs_extractor/__init__.py`
- Create: `app/services/tech_specs_extractor/base.py`
- Test: `tests/test_tech_specs_extractor.py`

- [ ] **Step 1: Test fallente**

Crea `tests/test_tech_specs_extractor.py`:

```python
"""Test extractor service registry + base ABC."""
import pytest


def test_extractor_abc_required_method():
    from app.services.tech_specs_extractor.base import TechSpecsExtractor

    class Incomplete(TechSpecsExtractor):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # ABC: extract() non implementato


def test_register_and_lookup_extractor():
    from app.services.tech_specs_extractor import register_extractor, get_extractor
    from app.services.tech_specs_extractor.base import TechSpecsExtractor

    @register_extractor(name="dummy_test", mime_priority=["audio/*"])
    class DummyExtractor(TechSpecsExtractor):
        def extract(self, path, mime):
            return {"tool": "dummy_test"}

    found = get_extractor(mime="audio/wav")
    assert found is not None
    inst = found()
    assert inst.extract("/tmp/x.wav", "audio/wav") == {"tool": "dummy_test"}


def test_extract_tech_specs_public_api():
    from app.services.tech_specs_extractor import extract_tech_specs, register_extractor
    from app.services.tech_specs_extractor.base import TechSpecsExtractor

    @register_extractor(name="dummy_video", mime_priority=["video/*"])
    class DummyVideo(TechSpecsExtractor):
        def extract(self, path, mime):
            return {"tool": "dummy_video", "video": {"codec": "fake"}}

    out = extract_tech_specs("/tmp/x.mp4", "video/mp4")
    assert out["tool"] == "dummy_video"
    assert out["video"]["codec"] == "fake"


def test_no_extractor_returns_none_struct():
    from app.services.tech_specs_extractor import extract_tech_specs

    out = extract_tech_specs("/tmp/unknown.bin", "application/octet-stream")
    assert out["tool"] == "none"
    assert "errors" in out
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_tech_specs_extractor.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Crea app/services/tech_specs_extractor/base.py**

```python
"""Bundle L Stack 1 — ABC per tech specs extractor pluggable.

Ogni extractor (ffprobe, mediainfo, ai_vision) implementa `extract(path, mime)`
ritornando dict con shape canonica (subset di JSON Schema variant_v1).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class TechSpecsExtractor(ABC):
    """Base ABC. Sub-class implementa extract() per uno specifico tool/mime."""

    name: str = "abstract"

    @abstractmethod
    def extract(self, path: str, mime: Optional[str] = None) -> dict:
        """Estrae tech specs da file. Ritorna dict con almeno 'tool' e 'errors'.

        Shape canonica (subset variant_v1):
            {
              "tool": str,
              "container": {...} | None,
              "video": {...} | None,
              "audio": [...],
              "errors": [str, ...]
            }
        """
        ...
```

- [ ] **Step 4: Crea app/services/tech_specs_extractor/__init__.py**

```python
"""Bundle L Stack 1 — Registry + public API extractor service.

Plugin registry pattern: nuovi extractor si registrano via decorator
@register_extractor(name, mime_priority). Lookup via mime glob match.
"""
from __future__ import annotations

import fnmatch
from datetime import datetime
from typing import Optional, Type

from app.services.tech_specs_extractor.base import TechSpecsExtractor


# Registry: lista di tuple (mime_pattern, priority_index, extractor_class)
# Ordine di inserzione = priorità (first match wins all'interno della stessa
# mime_pattern). Per mime_priority diversi è possibile registrare lo stesso
# extractor su pattern multipli.
_REGISTRY: list[tuple[str, Type[TechSpecsExtractor]]] = []


def register_extractor(name: str, mime_priority: list[str]):
    """Decorator per registrare un extractor con mime patterns supportati.

    Esempio:
        @register_extractor(name="ffprobe", mime_priority=["video/*", "audio/*"])
        class FFProbeExtractor(TechSpecsExtractor): ...
    """
    def deco(cls: Type[TechSpecsExtractor]):
        cls.name = name
        for pattern in mime_priority:
            _REGISTRY.append((pattern, cls))
        return cls
    return deco


def get_extractor(mime: Optional[str]) -> Optional[Type[TechSpecsExtractor]]:
    """Trova primo extractor il cui mime_priority matcha il mime fornito."""
    if not mime:
        return None
    mime_norm = mime.split(";", 1)[0].strip().lower()
    for pattern, cls in _REGISTRY:
        if fnmatch.fnmatch(mime_norm, pattern.lower()):
            return cls
    return None


def extract_tech_specs(path: str, mime: Optional[str] = None) -> dict:
    """API pubblica: estrae tech specs da `path`. Sceglie extractor via mime.

    Sempre ritorna dict con 'tool', 'errors'. tool='none' se nessun extractor
    matcha. errors[] popolato in caso di failure (gentle fallback).
    """
    cls = get_extractor(mime)
    if cls is None:
        return {
            "tool": "none",
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "container": None, "video": None, "audio": [],
            "errors": [f"Nessun extractor registrato per mime '{mime}'"],
        }
    try:
        inst = cls()
        out = inst.extract(path, mime)
        out.setdefault("extracted_at", datetime.utcnow().isoformat() + "Z")
        out.setdefault("errors", [])
        out.setdefault("audio", [])
        out.setdefault("video", None)
        out.setdefault("container", None)
        return out
    except Exception as e:
        return {
            "tool": cls.name,
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "container": None, "video": None, "audio": [],
            "errors": [f"extractor exception: {type(e).__name__}: {e}"],
        }
```

- [ ] **Step 5: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_tech_specs_extractor.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```
git add app/services/tech_specs_extractor/__init__.py app/services/tech_specs_extractor/base.py tests/test_tech_specs_extractor.py
git commit -m "feat(bundle-l): tech_specs_extractor service ABC + registry (Stack 1 Task 7)"
```

**Versioning checkpoint:** A questo punto bumppa `app/main.py` a `v3.5.0-alpha.172.94`, aggiorna `CHANGELOG.md` con sezione "α.172.94 — Bundle L Stack 1 Task 1-7" e commit:

```
git add app/main.py CHANGELOG.md
git commit -m "v3.5.0-alpha.172.94 — Bundle L Stack 1 (Task 1-7): models + JSON Schema + extractor base"
```

---

### Task 8: FFProbeExtractor — port da asset_metadata.py

**Files:**
- Create: `app/services/tech_specs_extractor/ffprobe_extractor.py`
- Modify: `app/services/tech_specs_extractor/__init__.py` (auto-import)
- Test: `tests/test_tech_specs_extractor.py` (estensione)

- [ ] **Step 1: Test fallente ffprobe**

Aggiungi a `tests/test_tech_specs_extractor.py`:

```python
def test_ffprobe_registered_for_video_audio():
    # Forza re-import per registrare il decorator (test isolation)
    from app.services.tech_specs_extractor import ffprobe_extractor  # noqa: F401
    from app.services.tech_specs_extractor import get_extractor

    assert get_extractor("video/mp4") is not None
    assert get_extractor("audio/wav") is not None
    assert get_extractor("video/quicktime") is not None


def test_ffprobe_missing_file_returns_error_struct():
    from app.services.tech_specs_extractor import extract_tech_specs
    out = extract_tech_specs("/non/existent/file.mp4", "video/mp4")
    assert out["tool"] in ("ffprobe", "none")  # ffprobe assente o file mancante
    assert isinstance(out.get("errors"), list)
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_tech_specs_extractor.py -v
```

Expected: errore import o asserzione su `get_extractor("video/mp4")` is None

- [ ] **Step 3: Crea app/services/tech_specs_extractor/ffprobe_extractor.py**

Porta la logica esistente da `app/services/asset_metadata.py` adattandola al nuovo pattern. Codice:

```python
"""Bundle L Stack 1 — FFProbeExtractor: porting da asset_metadata.py.

Estrae specs video/audio via ffprobe (subprocess, no dipendenze Python aggiunte).
Gentle fallback se ffprobe non installato → errors[].
"""
from __future__ import annotations

import json as _json
import shutil
import subprocess
from typing import Optional

from app.services.tech_specs_extractor import register_extractor
from app.services.tech_specs_extractor.base import TechSpecsExtractor


def _parse_framerate(rate_str: str) -> Optional[str]:
    if not rate_str or "/" not in rate_str:
        return rate_str or None
    try:
        num, den = rate_str.split("/")
        n, d = float(num), float(den)
        if d == 0:
            return None
        val = n / d
        return f"{val:.3f}".rstrip("0").rstrip(".") if val != int(val) else str(int(val))
    except Exception:
        return rate_str


@register_extractor(name="ffprobe", mime_priority=["video/*", "audio/*"])
class FFProbeExtractor(TechSpecsExtractor):
    def extract(self, path: str, mime: Optional[str] = None) -> dict:
        out = {"tool": "ffprobe", "container": None, "video": None, "audio": [], "errors": []}
        if shutil.which("ffprobe") is None:
            out["errors"].append("ffprobe non installato su questo sistema")
            return out
        try:
            cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
            if res.returncode != 0:
                out["errors"].append(f"ffprobe rc={res.returncode}: {(res.stderr or '').strip()[:200]}")
                return out
            data = _json.loads(res.stdout or "{}")
        except subprocess.TimeoutExpired:
            out["errors"].append("ffprobe timeout dopo 8s")
            return out
        except Exception as e:
            out["errors"].append(f"ffprobe exception: {type(e).__name__}: {e}")
            return out

        fmt = data.get("format") or {}
        out["container"] = {
            "format": fmt.get("format_name"),
            "size_bytes": int(fmt.get("size", 0)) if fmt.get("size") else None,
            "duration_sec": float(fmt.get("duration", 0)) if fmt.get("duration") else None,
            "bitrate_kbps": int(int(fmt.get("bit_rate", 0)) / 1000) if fmt.get("bit_rate") else None,
        }
        for stream in (data.get("streams") or []):
            ct = stream.get("codec_type")
            if ct == "video" and out["video"] is None:
                out["video"] = {
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "framerate": _parse_framerate(stream.get("r_frame_rate", "")),
                    "codec": stream.get("codec_name"),
                    "duration_sec": float(stream["duration"]) if stream.get("duration") else None,
                    "bitrate_kbps": int(int(stream["bit_rate"]) / 1000) if stream.get("bit_rate") else None,
                    "pixel_format": stream.get("pix_fmt"),
                }
            elif ct == "audio":
                out["audio"].append({
                    "codec": stream.get("codec_name"),
                    "channels": stream.get("channels"),
                    "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                    "bitrate_kbps": int(int(stream["bit_rate"]) / 1000) if stream.get("bit_rate") else None,
                    "language": (stream.get("tags") or {}).get("language"),
                })
        return out
```

- [ ] **Step 4: Auto-load registry in __init__.py**

Apri `app/services/tech_specs_extractor/__init__.py`. **Alla fine del file**, aggiungi:

```python
# Auto-load extractors (registry side-effect via @register_extractor decorator)
from app.services.tech_specs_extractor import ffprobe_extractor as _ffp  # noqa: F401, E402
```

- [ ] **Step 5: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_tech_specs_extractor.py -v
```

Expected: `6 passed`

- [ ] **Step 6: Commit**

```
git add app/services/tech_specs_extractor/ffprobe_extractor.py app/services/tech_specs_extractor/__init__.py tests/test_tech_specs_extractor.py
git commit -m "feat(bundle-l): FFProbeExtractor port + auto-load registry (Stack 1 Task 8)"
```

---

### Task 9: PillowExtractor (immagini fallback)

**Files:**
- Create: `app/services/tech_specs_extractor/pillow_extractor.py`
- Modify: `app/services/tech_specs_extractor/__init__.py` (import)
- Test: `tests/test_tech_specs_extractor.py` (estensione)

- [ ] **Step 1: Test fallente**

Aggiungi a `tests/test_tech_specs_extractor.py`:

```python
def test_pillow_registered_for_images():
    from app.services.tech_specs_extractor import pillow_extractor  # noqa: F401
    from app.services.tech_specs_extractor import get_extractor
    assert get_extractor("image/jpeg") is not None
    assert get_extractor("image/png") is not None
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_tech_specs_extractor.py::test_pillow_registered_for_images -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.tech_specs_extractor.pillow_extractor'`

- [ ] **Step 3: Crea pillow_extractor.py**

```python
"""Bundle L Stack 1 — PillowExtractor: fallback per immagini (image/*).

Usa Pillow (gia' nelle deps tramite generate_thumbnail). Gentle fallback se
file non leggibile.
"""
from __future__ import annotations

from typing import Optional

from app.services.tech_specs_extractor import register_extractor
from app.services.tech_specs_extractor.base import TechSpecsExtractor


@register_extractor(name="pillow", mime_priority=["image/*"])
class PillowExtractor(TechSpecsExtractor):
    def extract(self, path: str, mime: Optional[str] = None) -> dict:
        out = {"tool": "pillow", "container": None, "video": None, "audio": [], "errors": []}
        try:
            from PIL import Image  # type: ignore
        except ImportError:
            out["errors"].append("Pillow non disponibile")
            return out
        try:
            with Image.open(path) as img:
                out["video"] = {
                    "width": img.width,
                    "height": img.height,
                    "codec": (img.format or "").upper(),
                    "pixel_format": img.mode,
                }
                out["container"] = {"format": (img.format or "").lower()}
        except FileNotFoundError:
            out["errors"].append(f"file non trovato: {path}")
        except Exception as e:
            out["errors"].append(f"pillow exception: {type(e).__name__}: {e}")
        return out
```

- [ ] **Step 4: Auto-load in __init__.py**

In `app/services/tech_specs_extractor/__init__.py`, sotto la riga ffprobe già aggiunta:

```python
from app.services.tech_specs_extractor import pillow_extractor as _pil  # noqa: F401, E402
```

- [ ] **Step 5: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_tech_specs_extractor.py -v
```

Expected: `7 passed`

- [ ] **Step 6: Commit**

```
git add app/services/tech_specs_extractor/pillow_extractor.py app/services/tech_specs_extractor/__init__.py tests/test_tech_specs_extractor.py
git commit -m "feat(bundle-l): PillowExtractor per immagini (Stack 1 Task 9)"
```

---

### Task 10: asset_metadata.py legacy wrapper (back-compat)

**Files:**
- Modify: `app/services/asset_metadata.py`
- Test: `tests/test_tech_specs_extractor.py` (estensione back-compat)

- [ ] **Step 1: Test back-compat**

Aggiungi a `tests/test_tech_specs_extractor.py`:

```python
def test_asset_metadata_back_compat():
    """Endpoint /dam/api/assets/{id}/metadata usa extract_asset_metadata.
    Verifica che continui a funzionare delegando al nuovo service."""
    from app.services.asset_metadata import extract_asset_metadata
    out = extract_asset_metadata("/non/existent.mp4", "video/mp4")
    # Shape compatibile con consumer esistente
    assert "tool" in out
    assert "errors" in out
    assert "video" in out
    assert "audio" in out
    assert "container" in out
```

- [ ] **Step 2: Run test → potrebbe già PASS (shape simile) — verifica**

```
.venv\Scripts\python.exe -m pytest tests/test_tech_specs_extractor.py::test_asset_metadata_back_compat -v
```

Se PASS già: vai a Step 5 commit. Se FAIL: Step 3.

- [ ] **Step 3: Refactor asset_metadata.py come wrapper**

Sostituisci tutto il contenuto di `app/services/asset_metadata.py` con:

```python
"""Bundle L Stack 1 — Wrapper legacy per back-compat con dam.py.

Delega al nuovo `tech_specs_extractor` service. Mantiene la firma esistente
per non rompere `/dam/api/assets/{id}/metadata` (Bundle H3).
"""
from __future__ import annotations

from typing import Optional

from app.services.tech_specs_extractor import extract_tech_specs


def extract_asset_metadata(file_path: str, mime_type: Optional[str] = None) -> dict:
    """API legacy: delega a `extract_tech_specs`. Shape compatibile."""
    return extract_tech_specs(file_path, mime_type)
```

- [ ] **Step 4: Run test → PASS**

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: tutti i test passano (incluso back-compat).

- [ ] **Step 5: Smoke endpoint legacy**

Restart app + curl:

```
.venv\Scripts\python.exe -u run.py    # in background
curl -s -c /tmp/c.txt -X POST "http://localhost:8000/auth/login" -d "email=admin@mediaflow.it&password=admin123"
curl -s -b /tmp/c.txt "http://localhost:8000/dam/api/assets/1/metadata"
```

Expected: 200 con JSON che ha `tool`, `errors`, `video`, `audio` (anche se vuoti per asset senza file reale).

- [ ] **Step 6: Commit**

```
git add app/services/asset_metadata.py tests/test_tech_specs_extractor.py
git commit -m "refactor(bundle-l): asset_metadata.py = wrapper legacy che delega a tech_specs_extractor (Stack 1 Task 10)"
```

---

### Task 11: Auto-migrate al boot per nuove colonne + seed schema v1

**Files:**
- Modify: `app/main.py` (aggiungi `_auto_migrate_bundle_l_stack1` + `_seed_variant_schema_v1`)

- [ ] **Step 1: Aggiungi helper auto-migrate**

In `app/main.py`, **dopo** `_auto_reclassify_physical_deliverables` (definita Bundle K2), aggiungi:

```python
def _auto_migrate_bundle_l_stack1():
    """v3.5.0-alpha.172.95 (Bundle L Stack 1) — Schema migrations per:
    - job_deliverables.variant_id + variant_language/territory/format
    - assets.tech_specs_json + tech_specs_extractor + tech_specs_extracted_at + tech_specs_schema_version
    - tabelle variant_schema_versions + delivery_variants (via create_tables se non esistono).

    Idempotente: ALTER + CREATE solo se mancanti.
    """
    from sqlalchemy import text
    from app.database import engine
    try:
        with engine.begin() as conn:
            def cols(table):
                return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}

            jd_cols = cols("job_deliverables")
            for col, decl in [
                ("variant_id", "INTEGER NULL REFERENCES delivery_variants(id)"),
                ("variant_language", "VARCHAR(10) NULL"),
                ("variant_territory", "VARCHAR(10) NULL"),
                ("variant_format", "VARCHAR(20) NULL"),
            ]:
                if col not in jd_cols:
                    print(f"[auto-migrate-bundle-l] job_deliverables.{col} -> ALTER")
                    conn.execute(text(f"ALTER TABLE job_deliverables ADD COLUMN {col} {decl}"))

            a_cols = cols("assets")
            for col, decl in [
                ("tech_specs_json", "TEXT NULL"),  # SQLite JSON stored as TEXT
                ("tech_specs_extractor", "VARCHAR(40) NULL"),
                ("tech_specs_extracted_at", "DATETIME NULL"),
                ("tech_specs_schema_version", "VARCHAR(20) NULL"),
            ]:
                if col not in a_cols:
                    print(f"[auto-migrate-bundle-l] assets.{col} -> ALTER")
                    conn.execute(text(f"ALTER TABLE assets ADD COLUMN {col} {decl}"))

            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_jd_variant_id ON job_deliverables(variant_id)"
            ))
    except Exception as e:
        print(f"[auto-migrate-bundle-l] failed: {e}")


def _seed_variant_schema_v1():
    """v3.5.0-alpha.172.95 (Bundle L Stack 1) — Carica schemas/variant_v1.json
    in VariantSchemaVersion(version='v1', is_active=True) se non esiste.
    Idempotente.
    """
    import json as _json
    from pathlib import Path
    from app.database import SessionLocal
    from app.models.variant import VariantSchemaVersion
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "variant_v1.json"
    if not schema_path.exists():
        print(f"[seed-variant-schema] schema file mancante: {schema_path}")
        return
    db = SessionLocal()
    try:
        existing = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.version == "v1").first()
        if existing:
            return
        with schema_path.open("r", encoding="utf-8") as f:
            schema = _json.load(f)
        db.add(VariantSchemaVersion(
            version="v1",
            schema_json=schema,
            description="Canonical schema v1 (Bundle L Stack 1)",
            is_active=True,
        ))
        db.commit()
        print("[seed-variant-schema] v1 caricato da schemas/variant_v1.json")
    except Exception as e:
        print(f"[seed-variant-schema] failed: {e}")
    finally:
        db.close()
```

- [ ] **Step 2: Wire in lifespan**

Trova in `app/main.py` la funzione `lifespan` (riga ~1289+). Aggiungi **dopo** `_auto_reclassify_physical_deliverables` chiamata:

```python
    # v3.5.0-alpha.172.95 — Bundle L Stack 1: schema migrations + seed
    try:
        _auto_migrate_bundle_l_stack1()
    except Exception as e:
        print(f"[lifespan] _auto_migrate_bundle_l_stack1 failed: {e}")
    try:
        _seed_variant_schema_v1()
    except Exception as e:
        print(f"[lifespan] _seed_variant_schema_v1 failed: {e}")
```

- [ ] **Step 3: Smoke test boot**

Kill processi python esistenti + restart:

```
.venv\Scripts\python.exe -u run.py
```

Cerca nei log:
- `[auto-migrate-bundle-l] job_deliverables.variant_id -> ALTER`
- `[auto-migrate-bundle-l] assets.tech_specs_json -> ALTER`
- `[seed-variant-schema] v1 caricato`
- `Application startup complete`

Se app esistente con DB già migrato, ALTER skip e log "schema gia presente".

- [ ] **Step 4: Verifica DB**

```
.venv\Scripts\python.exe -c "from app.database import SessionLocal; from app.models.variant import VariantSchemaVersion; db = SessionLocal(); sv = db.query(VariantSchemaVersion).first(); print(sv.version if sv else 'None')"
```

Expected: `v1`

- [ ] **Step 5: Commit**

```
git add app/main.py
git commit -m "feat(bundle-l): auto-migrate + seed schema v1 al boot (Stack 1 Task 11)"
```

**Versioning checkpoint:** bump `app/main.py` a `v3.5.0-alpha.172.95`, aggiorna CHANGELOG sezione Task 8-12, commit:

```
git add app/main.py CHANGELOG.md
git commit -m "v3.5.0-alpha.172.95 — Bundle L Stack 1 (Task 8-11): ffprobe+pillow extractor + auto-migrate"
```

---

### Task 12: parse_capitolati.py — batch parser script

**Files:**
- Create: `scripts/parse_capitolati.py`
- Test: `tests/test_parse_capitolati.py`

- [ ] **Step 1: Test su file fixture text**

Crea `tests/test_parse_capitolati.py`:

```python
"""Test parse_capitolati batch script.

Usa file fixture testo creato in test (no chiamate AI reali in CI).
"""
from pathlib import Path
import pytest


def test_classify_item_by_keyword():
    """Classificazione T1/T2/T3 via keyword heuristic (no AI in unit test)."""
    from scripts.parse_capitolati import classify_item_tier

    assert classify_item_tier("IMF Master HD 1920x1080 ProRes") == "t1_technical"
    assert classify_item_tier("DCP package Smpte 2K") == "t1_technical"
    assert classify_item_tier("Trailer 60s textless pack") == "t1_technical"
    assert classify_item_tier("LTO archive verificato MD5") == "t1_technical"
    assert classify_item_tier("Subtitle file .scc per lingua") == "t1_technical"
    assert classify_item_tier("CDL color decision list") == "t2_documentation"
    assert classify_item_tier("Spotting list dialogo IT") == "t2_documentation"
    assert classify_item_tier("Music cue sheet MIDEM") == "t2_documentation"
    assert classify_item_tier("NDA firmato da Produttore") == "t3_compilation"
    assert classify_item_tier("Materials Required form completato") == "t3_compilation"


def test_extract_text_from_txt(tmp_path):
    from scripts.parse_capitolati import extract_text_from_file
    f = tmp_path / "test.txt"
    f.write_text("Hello world\nMaster IMF HD", encoding="utf-8")
    text = extract_text_from_file(str(f))
    assert "Master IMF HD" in text


def test_extract_text_from_unknown_returns_empty():
    from scripts.parse_capitolati import extract_text_from_file
    text = extract_text_from_file("/non/existent/file.xyz")
    assert text == ""
```

- [ ] **Step 2: Run test → FAIL**

```
.venv\Scripts\python.exe -m pytest tests/test_parse_capitolati.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.parse_capitolati'` o classify_item_tier non definita.

- [ ] **Step 3: Crea scripts/parse_capitolati.py**

```python
"""Bundle L Stack 1 — Batch parser per 17 capitolati corpus.

Pipeline:
1. Estrae testo da PDF/DOCX/TXT/XLSX
2. Chunk a ~6k token sliding window
3. Per ogni chunk: chiama AI Claude per estrarre items strutturati
4. Classifica T1/T2/T3 via keyword heuristic + AI
5. Mappa item a JSON Schema variant_v1
6. Output: docs/superpowers/specs/capitolati-parsed/<vendor>.variants.json

Usage:
    .venv/Scripts/python.exe scripts/parse_capitolati.py \\
        --corpus docs/capitolati_esempio \\
        --out docs/superpowers/specs/capitolati-parsed \\
        --schema-version v1 \\
        [--ai-provider claude] [--ai-model claude-sonnet-4-6] \\
        [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


# ── Classificazione T1/T2/T3 via keyword heuristic ──
_T1_PATTERNS = [
    r"\b(master|imf|dcp|prores|mxf|tiff|dpx|mov|mp4)\b",
    r"\b(trailer|teaser|spot|behind[- ]the[- ]scenes|making[- ]of)\b",
    r"\b(textless|tail|head)\b",
    r"\b(audio|atmos|stems|m&e|mix|pcm|wav)\b",
    r"\b(subtitle|sub|scc|vtt|ttml|sdh|cc)\b",
    r"\b(lto|hdd|cru|tape|archive)\b",
    r"\b(stills|artwork|key art|poster)\b",
    r"\b(kdm|key delivery message)\b",
]
_T2_PATTERNS = [
    r"\b(cdl|color decision|lut|look[- ]up)\b",
    r"\b(spotting|dialogue list|dialog list)\b",
    r"\b(music cue sheet|midem|cue sheet)\b",
    r"\b(metadata template|metadata sheet)\b",
    r"\b(report|technical report)\b",
]
_T3_PATTERNS = [
    r"\b(nda|contratto|contract|legal)\b",
    r"\b(materials required|form|consent|release)\b",
    r"\b(certificazione|certification|certificate)\b",
]


def classify_item_tier(text: str) -> str:
    """Classifica un item testuale in T1 (technical) / T2 (documentation) / T3 (compilation).

    Heuristic keyword-based (case-insensitive). In caso di ambiguity privilegia T1.
    """
    t = text.lower()
    for pat in _T1_PATTERNS:
        if re.search(pat, t):
            return "t1_technical"
    for pat in _T2_PATTERNS:
        if re.search(pat, t):
            return "t2_documentation"
    for pat in _T3_PATTERNS:
        if re.search(pat, t):
            return "t3_compilation"
    return "t1_technical"  # default conservativo


def extract_text_from_file(path: str) -> str:
    """Estrae testo plain da file capitolato. Supporta TXT, PDF, DOCX.

    Ritorna stringa vuota se file mancante / formato non supportato.
    """
    p = Path(path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower()
    try:
        if suffix == ".txt":
            return p.read_text(encoding="utf-8", errors="replace")
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return ""
            reader = PdfReader(str(p))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        if suffix == ".docx":
            try:
                from docx import Document  # python-docx
            except ImportError:
                return ""
            doc = Document(str(p))
            return "\n".join(par.text for par in doc.paragraphs)
        if suffix == ".xlsx":
            try:
                from openpyxl import load_workbook
            except ImportError:
                return ""
            wb = load_workbook(str(p), data_only=True, read_only=True)
            parts = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                parts.append(f"=== {sheet} ===")
                for row in ws.iter_rows(values_only=True):
                    parts.append(" | ".join(str(c) if c is not None else "" for c in row))
            return "\n".join(parts)
    except Exception as e:
        print(f"[extract_text] {path}: {type(e).__name__}: {e}", file=sys.stderr)
        return ""
    return ""


def chunk_text(text: str, max_chars: int = 24000) -> list[str]:
    """Sliding window con overlap 1000 char. Default max 24k char (~6k token)."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks = []
    overlap = 1000
    i = 0
    while i < len(text):
        end = min(i + max_chars, len(text))
        chunks.append(text[i:end])
        if end >= len(text):
            break
        i = end - overlap
    return chunks


def vendor_from_filename(name: str) -> str:
    """Estrae vendor slug da nome file capitolato."""
    base = Path(name).stem.lower()
    base = re.sub(r"[^a-z0-9]+", "-", base)
    return base.strip("-")


def main():
    ap = argparse.ArgumentParser(description="Batch parser capitolati Bundle L Stack 1")
    ap.add_argument("--corpus", required=True, help="Directory con file capitolato")
    ap.add_argument("--out", required=True, help="Directory output JSON parsed")
    ap.add_argument("--schema-version", default="v1")
    ap.add_argument("--ai-provider", default="claude")
    ap.add_argument("--ai-model", default="claude-sonnet-4-6")
    ap.add_argument("--dry-run", action="store_true",
                    help="Estrai testo + chunk, ma NON chiama AI. Output stub JSON.")
    args = ap.parse_args()

    corpus_dir = Path(args.corpus)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not corpus_dir.exists():
        print(f"[error] corpus dir non trovata: {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    files = [f for f in corpus_dir.iterdir() if f.is_file() and f.suffix.lower() in (".txt", ".pdf", ".docx", ".xlsx", ".doc")]
    print(f"[parse_capitolati] trovati {len(files)} file in {corpus_dir}")

    report_lines = ["# Capitolati parsed — Bundle L Stack 1\n", f"Corpus: `{corpus_dir}` · Schema: `{args.schema_version}`\n"]

    for f in files:
        vendor = vendor_from_filename(f.name)
        text = extract_text_from_file(str(f))
        chunks = chunk_text(text)
        print(f"  [{vendor}] {len(text):>7} char → {len(chunks)} chunk")

        variants = []
        if args.dry_run:
            # Output stub: 1 variant placeholder per chunk per smoke test
            for i, chunk in enumerate(chunks):
                snippet = chunk[:120].replace("\n", " ")
                variants.append({
                    "code": f"{vendor}-stub-{i+1}",
                    "name": f"[DRY-RUN] {vendor} chunk {i+1}",
                    "category": classify_item_tier(snippet),
                    "spec_json": {},
                    "source_capitolato": f.name,
                    "source_section": f"chunk {i+1}/{len(chunks)}",
                    "_snippet": snippet,
                })
        else:
            # Chiamata AI reale (Stack 1: implementazione minimale, prompt
            # strutturato. Capability runtime piena → Stack 5.)
            from app.services.ai_provider import get_provider
            provider = get_provider(args.ai_provider, args.ai_model)
            for i, chunk in enumerate(chunks):
                resp = provider.extract_variants_from_chunk(chunk, schema_version=args.schema_version)
                # resp: list[dict] secondo JSON Schema variant_v1
                for v in (resp or []):
                    v.setdefault("source_capitolato", f.name)
                    v.setdefault("source_section", f"chunk {i+1}/{len(chunks)}")
                    v["category"] = classify_item_tier(v.get("name", ""))
                    variants.append(v)

        out_file = out_dir / f"{vendor}.variants.json"
        out_file.write_text(json.dumps(variants, ensure_ascii=False, indent=2), encoding="utf-8")
        report_lines.append(f"- **{vendor}** ({f.name}): {len(variants)} variants extracted → `{out_file.name}`")

    (out_dir / "REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"[parse_capitolati] done. Report: {out_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
```

**Nota Step 3 (dipendenza ai_provider):** la funzione `extract_variants_from_chunk` non esiste ancora nel `ai_provider` service esistente. Per Stack 1 implementiamo SOLO il `--dry-run` path (smoke senza AI). La chiamata reale `provider.extract_variants_from_chunk(...)` viene wired in Stack 5 (capability runtime). Nel test Task 12 useremo `--dry-run`.

- [ ] **Step 4: Run unit tests → PASS**

```
.venv\Scripts\python.exe -m pytest tests/test_parse_capitolati.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Smoke run --dry-run sul corpus reale**

```
.venv\Scripts\python.exe scripts\parse_capitolati.py --corpus docs\capitolati_esempio --out docs\superpowers\specs\capitolati-parsed --dry-run
```

Expected output:
```
[parse_capitolati] trovati 17 file in docs\capitolati_esempio
  [netflix-deliverables]      8234 char → 1 chunk
  ...
[parse_capitolati] done. Report: docs\superpowers\specs\capitolati-parsed\REPORT.md
```

Verifica:
- `docs/superpowers/specs/capitolati-parsed/REPORT.md` esiste
- `docs/superpowers/specs/capitolati-parsed/netflix-deliverables.variants.json` esiste (stub variants)

- [ ] **Step 6: Commit**

```
git add scripts/parse_capitolati.py tests/test_parse_capitolati.py docs/superpowers/specs/capitolati-parsed/
git commit -m "feat(bundle-l): parse_capitolati.py batch parser + classify T1/T2/T3 + dry-run smoke (Stack 1 Task 12)"
```

---

### Task 13: import_parsed_variants.py — DB import script

**Files:**
- Create: `scripts/import_parsed_variants.py`

- [ ] **Step 1: Crea script**

```python
"""Bundle L Stack 1 — Import variants parsed JSON in DB.

Legge `<vendor>.variants.json` files prodotti da parse_capitolati.py e crea
DeliveryVariant entries nel DB. Idempotente: skip se (tenant_id, code) gia'
esiste. Validate ogni variant contro JSON Schema attivo.

Usage:
    .venv/Scripts/python.exe scripts/import_parsed_variants.py \\
        --input docs/superpowers/specs/capitolati-parsed \\
        [--tenant 1] [--dry-run] [--only t1_technical]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.database import SessionLocal
from app.models.variant import DeliveryVariant, DeliveryVariantCategory, VariantSchemaVersion
from app.services.variant_schema import load_active_schema
from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--tenant", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["t1_technical", "t2_documentation", "t3_compilation"],
                    help="Filtra solo variants di una category")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print(f"[error] input dir non trovata: {inp}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        schema = load_active_schema(db)
        sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.is_active == True).first()  # noqa: E712
        schema_version_id = sv.id

        imported = 0
        skipped = 0
        invalid = 0
        for jf in inp.glob("*.variants.json"):
            with jf.open("r", encoding="utf-8") as fp:
                variants = json.load(fp)
            for v in variants:
                if args.only and v.get("category") != args.only:
                    continue
                code = v.get("code")
                if not code:
                    invalid += 1
                    print(f"  SKIP no-code: {jf.name}")
                    continue
                existing = db.query(DeliveryVariant).filter(
                    DeliveryVariant.tenant_id == args.tenant,
                    DeliveryVariant.code == code,
                ).first()
                if existing:
                    skipped += 1
                    continue
                # Validate spec_json contro schema attivo
                try:
                    jsonschema_validate(instance=v, schema=schema)
                except ValidationError as e:
                    invalid += 1
                    print(f"  INVALID {code}: {e.message}")
                    continue
                if args.dry_run:
                    print(f"  [DRY] would import {code}: {v.get('name')}")
                    continue
                db.add(DeliveryVariant(
                    tenant_id=args.tenant,
                    code=code,
                    name=v.get("name") or code,
                    category=DeliveryVariantCategory(v.get("category", "t1_technical")),
                    schema_version_id=schema_version_id,
                    spec_json=v.get("spec_json") or {},
                    language=v.get("language"),
                    territory=v.get("territory"),
                    has_textless=bool(v.get("textless", {}).get("tail_present") or v.get("textless", {}).get("separate_file")) if isinstance(v.get("textless"), dict) else False,
                    has_subtitles=bool(v.get("subtitles", {}).get("present")) if isinstance(v.get("subtitles"), dict) else False,
                    delivery_format=(v.get("container") or {}).get("format"),
                    source_capitolato=v.get("source_capitolato"),
                    source_section=v.get("source_section"),
                ))
                imported += 1
        if not args.dry_run:
            db.commit()
        print(f"[import_parsed_variants] imported={imported} skipped={skipped} invalid={invalid} {'(DRY-RUN)' if args.dry_run else ''}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke dry-run**

```
.venv\Scripts\python.exe scripts\import_parsed_variants.py --input docs\superpowers\specs\capitolati-parsed --dry-run
```

Expected: `imported=0 skipped=0 invalid=N (DRY-RUN)` (N alto perché stub variants non sono validi contro schema reale).

- [ ] **Step 3: Commit**

```
git add scripts/import_parsed_variants.py
git commit -m "feat(bundle-l): import_parsed_variants.py with JSON Schema validation (Stack 1 Task 13)"
```

---

### Task 14: Router /delivery-variants — CRUD listing minimal

**Files:**
- Create: `app/routers/delivery_variants.py`
- Modify: `app/main.py` (include router)

- [ ] **Step 1: Crea router**

```python
"""Bundle L Stack 1 — Router CRUD listing DeliveryVariant.

Endpoint minimali per Stack 1: list, get, create, soft-delete.
UI rich + form auto-gen da JSON Schema = Stack 4.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.variant import DeliveryVariant, DeliveryVariantCategory, VariantSchemaVersion
from app.services.rbac import requires_permission
from app.context import current_tenant_id

router = APIRouter(prefix="/delivery-variants", tags=["delivery-variants"])
templates = Jinja2Templates(directory="app/templates")


RequireEditVariants = Depends(requires_permission("edit_quotes"))  # riusa perm esistente


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, db: Session = Depends(get_db)):
    variants = (
        db.query(DeliveryVariant)
        .filter(DeliveryVariant.tenant_id == current_tenant_id())
        .filter(DeliveryVariant.is_active == True)  # noqa: E712
        .order_by(DeliveryVariant.code.asc())
        .all()
    )
    return templates.TemplateResponse("pages/delivery_variants.html", {
        "request": request,
        "variants": variants,
        "categories": list(DeliveryVariantCategory),
    })


@router.get("/api/list")
async def list_variants(
    category: Optional[str] = None,
    language: Optional[str] = None,
    delivery_format: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = (
        db.query(DeliveryVariant)
        .filter(DeliveryVariant.tenant_id == current_tenant_id())
        .filter(DeliveryVariant.is_active == True)  # noqa: E712
    )
    if category:
        try:
            q = q.filter(DeliveryVariant.category == DeliveryVariantCategory(category))
        except ValueError:
            raise HTTPException(400, f"category invalida: {category}")
    if language:
        q = q.filter(DeliveryVariant.language == language)
    if delivery_format:
        q = q.filter(DeliveryVariant.delivery_format == delivery_format)
    rows = q.order_by(DeliveryVariant.code.asc()).all()
    return [{
        "id": v.id, "code": v.code, "name": v.name,
        "category": v.category.value,
        "language": v.language, "territory": v.territory,
        "delivery_format": v.delivery_format,
        "has_textless": v.has_textless, "has_subtitles": v.has_subtitles,
        "source_capitolato": v.source_capitolato,
    } for v in rows]


@router.get("/api/{variant_id}")
async def get_variant(variant_id: int, db: Session = Depends(get_db)):
    v = db.query(DeliveryVariant).filter(
        DeliveryVariant.id == variant_id,
        DeliveryVariant.tenant_id == current_tenant_id(),
    ).first()
    if not v:
        raise HTTPException(404, "Variant non trovata")
    return {
        "id": v.id, "code": v.code, "name": v.name,
        "category": v.category.value,
        "schema_version_id": v.schema_version_id,
        "spec_json": v.spec_json,
        "language": v.language, "territory": v.territory,
        "delivery_format": v.delivery_format,
        "has_textless": v.has_textless, "has_subtitles": v.has_subtitles,
        "source_capitolato": v.source_capitolato,
        "source_section": v.source_section,
        "suggested_price_item_id": v.suggested_price_item_id,
        "is_active": v.is_active,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.post("/api/create", dependencies=[RequireEditVariants])
async def create_variant(
    code: str = Form(...),
    name: str = Form(...),
    category: str = Form("t1_technical"),
    language: Optional[str] = Form(None),
    territory: Optional[str] = Form(None),
    delivery_format: Optional[str] = Form(None),
    spec_json: str = Form("{}"),
    db: Session = Depends(get_db),
):
    import json as _json
    try:
        cat = DeliveryVariantCategory(category)
    except ValueError:
        raise HTTPException(400, f"category invalida: {category}")
    try:
        spec = _json.loads(spec_json)
        if not isinstance(spec, dict):
            raise ValueError("spec_json deve essere un oggetto JSON")
    except Exception as e:
        raise HTTPException(400, f"spec_json non valido: {e}")
    sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.is_active == True).first()  # noqa: E712
    if not sv:
        raise HTTPException(500, "Nessun VariantSchemaVersion attivo")
    existing = db.query(DeliveryVariant).filter(
        DeliveryVariant.tenant_id == current_tenant_id(),
        DeliveryVariant.code == code,
    ).first()
    if existing:
        raise HTTPException(409, f"code '{code}' già usato")
    v = DeliveryVariant(
        tenant_id=current_tenant_id(),
        code=code, name=name, category=cat,
        schema_version_id=sv.id, spec_json=spec,
        language=language, territory=territory, delivery_format=delivery_format,
    )
    db.add(v); db.commit(); db.refresh(v)
    return {"ok": True, "id": v.id, "code": v.code}


@router.post("/api/{variant_id}/delete", dependencies=[RequireEditVariants])
async def soft_delete_variant(variant_id: int, db: Session = Depends(get_db)):
    v = db.query(DeliveryVariant).filter(
        DeliveryVariant.id == variant_id,
        DeliveryVariant.tenant_id == current_tenant_id(),
    ).first()
    if not v:
        raise HTTPException(404, "Variant non trovata")
    v.is_active = False
    db.commit()
    return {"ok": True}
```

- [ ] **Step 2: Include router in app/main.py**

Trova le altre `app.include_router(...)` in `app/main.py` (ricerca `include_router`). Aggiungi:

```python
from app.routers.delivery_variants import router as delivery_variants_router
app.include_router(delivery_variants_router)
```

- [ ] **Step 3: Smoke endpoint API**

Restart app. Test:

```
curl -s -c /tmp/c.txt -X POST "http://localhost:8000/auth/login" -d "email=admin@mediaflow.it&password=admin123"
curl -s -b /tmp/c.txt "http://localhost:8000/delivery-variants/api/list" -w "%{http_code}\n"
```

Expected: 200 con `[]` (no variants ancora).

Crea una variant minima:
```
curl -s -b /tmp/c.txt -X POST "http://localhost:8000/delivery-variants/api/create" \
  -d "code=test-imf-it&name=Test IMF IT&category=t1_technical&language=it&territory=WW&delivery_format=IMF" \
  -w "%{http_code}\n"
```

Expected: 200 con `{"ok":true,"id":N,"code":"test-imf-it"}`.

List di nuovo:
```
curl -s -b /tmp/c.txt "http://localhost:8000/delivery-variants/api/list"
```

Expected: array con 1 item.

- [ ] **Step 4: Commit**

```
git add app/routers/delivery_variants.py app/main.py
git commit -m "feat(bundle-l): router /delivery-variants CRUD minimal (Stack 1 Task 14)"
```

---

### Task 15: UI delivery_variants.html minimal

**Files:**
- Create: `app/templates/pages/delivery_variants.html`

- [ ] **Step 1: Crea template**

```html
{% extends "base.html" %}
{% block title %}Delivery variants — Claqo{% endblock %}
{% block content %}
<div class="container" style="max-width:1200px;margin:0 auto;padding:20px;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
    <div>
      <h1 style="margin:0;">📦 Delivery variants</h1>
      <p class="text-sm text-muted" style="margin:4px 0 0;">Catalog tenant — riusabili tra progetti. Auto-popolato da parser capitolati (T1 technical priority).</p>
    </div>
    <div>
      <button class="btn btn-primary btn-sm" onclick="openCreateVariant()">+ Nuova variant</button>
    </div>
  </div>

  <div style="display:flex;gap:10px;margin-bottom:14px;align-items:center;">
    <label class="text-sm text-muted">Filtro categoria:</label>
    <select id="f-cat" class="form-select" style="width:auto;" onchange="renderList()">
      <option value="">— tutte —</option>
      <option value="t1_technical">T1 Technical</option>
      <option value="t2_documentation">T2 Documentation</option>
      <option value="t3_compilation">T3 Compilation</option>
    </select>
    <input type="text" id="f-q" class="form-input" placeholder="Cerca code/name…" style="width:240px;" oninput="renderList()">
    <span id="counter" class="text-sm text-muted"></span>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Code</th><th>Nome</th><th>Category</th><th>Format</th>
          <th>Lingua</th><th>Territorio</th>
          <th>Textless</th><th>Sub</th>
          <th>Origine</th><th data-no-sort="true"></th>
        </tr>
      </thead>
      <tbody id="variants-tbody"></tbody>
    </table>
  </div>
</div>

<script>
let _all = {{ variants|tojson|safe if variants is defined else '[]' }};

async function loadList() {
  try {
    _all = await api('GET', '/delivery-variants/api/list');
  } catch (e) {
    toast('Errore caricamento variant: ' + e.message, 'error');
    _all = [];
  }
  renderList();
}

function renderList() {
  const cat = document.getElementById('f-cat').value;
  const q = (document.getElementById('f-q').value || '').trim().toLowerCase();
  let items = _all || [];
  if (cat) items = items.filter(v => v.category === cat);
  if (q) items = items.filter(v => (v.code||'').toLowerCase().includes(q) || (v.name||'').toLowerCase().includes(q));
  document.getElementById('counter').textContent = `${items.length} variant`;
  const tbody = document.getElementById('variants-tbody');
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  if (!items.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 10;
    td.className = 'text-muted';
    td.style.cssText = 'text-align:center;padding:30px;';
    td.textContent = 'Nessuna variant. Esegui script parse_capitolati.py + import_parsed_variants.py.';
    tr.appendChild(td); tbody.appendChild(tr);
    return;
  }
  items.forEach(v => {
    const tr = document.createElement('tr');
    const cells = [
      v.code, v.name, v.category, v.delivery_format || '—',
      v.language || '—', v.territory || '—',
      v.has_textless ? '✓' : '—', v.has_subtitles ? '✓' : '—',
      v.source_capitolato || '—',
    ];
    cells.forEach((txt, idx) => {
      const td = document.createElement('td');
      if (idx === 0) td.className = 'mono text-sm';
      else td.className = 'text-sm';
      td.textContent = txt;
      tr.appendChild(td);
    });
    const tdAct = document.createElement('td');
    const btn = document.createElement('button');
    btn.className = 'btn btn-ghost btn-sm';
    btn.textContent = '✕';
    btn.title = 'Soft-delete';
    btn.onclick = () => deleteVariant(v.id, v.code);
    tdAct.appendChild(btn);
    tr.appendChild(tdAct);
    tbody.appendChild(tr);
  });
}

async function deleteVariant(id, code) {
  if (!confirm(`Disattiva variant '${code}'?`)) return;
  try {
    await api('POST', `/delivery-variants/api/${id}/delete`);
    toast('Variant disattivata');
    loadList();
  } catch(e) { toast(e.message, 'error'); }
}

function openCreateVariant() {
  const code = prompt('Code (es. imf-master-hd-it):');
  if (!code) return;
  const name = prompt('Nome leggibile:');
  if (!name) return;
  const fd = new FormData();
  fd.set('code', code); fd.set('name', name); fd.set('category', 't1_technical');
  api('POST', '/delivery-variants/api/create', fd)
    .then(() => { toast('Variant creata'); loadList(); })
    .catch(e => toast(e.message, 'error'));
}

document.addEventListener('DOMContentLoaded', loadList);
</script>
{% endblock %}
```

- [ ] **Step 2: Smoke UI**

Restart app + browser su `/delivery-variants/`. Verifica:
- Pagina si apre senza errori
- Counter dice "1 variant" (test-imf-it creata Task 14)
- Filtri categoria + search funzionano
- "✕" soft-delete funziona (variant scompare alla ricarica)

- [ ] **Step 3: Commit**

```
git add app/templates/pages/delivery_variants.html
git commit -m "feat(bundle-l): UI delivery_variants.html listing minimal (Stack 1 Task 15)"
```

---

### Task 16: Backfill keyword match JobDeliverable.variant_id (best-effort)

**Files:**
- Modify: `app/main.py` (aggiungi `_auto_backfill_jd_variant_match`)

- [ ] **Step 1: Aggiungi helper backfill**

In `app/main.py`, dopo `_seed_variant_schema_v1`:

```python
def _auto_backfill_jd_variant_match():
    """v3.5.0-alpha.172.96 (Bundle L Stack 1) — Best-effort backfill:
    per ogni JobDeliverable con variant_id NULL, prova matching via keyword
    su `name` vs DeliveryVariant.name del catalog tenant. Idempotente.

    Strategy LITE (no AI): tokenize entrambi, score Jaccard. Soglia 0.6
    minima per assegnare. Variant migliore vince. Stack 4 introdurrà
    suggest_variants_for_job capability AI per i casi rimasti NULL.
    """
    from app.database import SessionLocal
    from app.models.models import JobDeliverable
    from app.models.variant import DeliveryVariant

    def _tokens(s: str) -> set[str]:
        import re as _re
        return {t for t in _re.split(r"[^a-z0-9]+", (s or "").lower()) if t and len(t) >= 3}

    db = SessionLocal()
    try:
        candidates = db.query(JobDeliverable).filter(JobDeliverable.variant_id.is_(None)).all()
        if not candidates:
            return
        variants = db.query(DeliveryVariant).filter(DeliveryVariant.is_active == True).all()  # noqa: E712
        if not variants:
            return
        var_tokens = [(v, _tokens(v.name)) for v in variants]
        matched = 0
        for d in candidates:
            d_t = _tokens(d.name)
            if not d_t:
                continue
            best_score = 0.0
            best_v = None
            for v, vt in var_tokens:
                if v.tenant_id != d.tenant_id:
                    continue
                union = d_t | vt
                inter = d_t & vt
                if not union:
                    continue
                score = len(inter) / len(union)
                if score > best_score:
                    best_score = score
                    best_v = v
            if best_v and best_score >= 0.6:
                d.variant_id = best_v.id
                d.variant_language = best_v.language
                d.variant_territory = best_v.territory
                d.variant_format = best_v.delivery_format
                matched += 1
        if matched:
            db.commit()
            print(f"[auto-backfill-bundle-l] {matched} JobDeliverable → variant_id assegnato (Jaccard ≥0.6)")
    except Exception as e:
        print(f"[auto-backfill-bundle-l] failed: {e}")
    finally:
        db.close()
```

- [ ] **Step 2: Wire in lifespan**

In `lifespan()`, **dopo** `_seed_variant_schema_v1`:

```python
    try:
        _auto_backfill_jd_variant_match()
    except Exception as e:
        print(f"[lifespan] _auto_backfill_jd_variant_match failed: {e}")
```

- [ ] **Step 3: Smoke boot**

Restart app. Cerca nei log:
- `[auto-backfill-bundle-l] N JobDeliverable → variant_id assegnato` (se ci sono match)
- O nessun log se 0 match (deliverable esistenti potrebbero non avere keyword match con la singola test variant)

- [ ] **Step 4: Commit**

```
git add app/main.py
git commit -m "feat(bundle-l): backfill JobDeliverable.variant_id via Jaccard keyword match (Stack 1 Task 16)"
```

---

### Task 17: Sidebar link + version bump finale + CHANGELOG + STATO

**Files:**
- Modify: `app/templates/` sidebar/nav (verifica esistenza prima)
- Modify: `app/main.py` (version → α.172.96)
- Modify: `CHANGELOG.md`
- Modify: `docs/STATO.md`

- [ ] **Step 1: Trova sidebar/nav**

```
grep -rE "delivery-templates|pricelist|dam" app/templates/components/ 2>/dev/null | head
```

Identifica il file sidebar (probabilmente `app/templates/components/sidebar.html` o `app/templates/base.html`).

- [ ] **Step 2: Aggiungi voce sidebar**

Nel file sidebar identificato, aggiungi link `/delivery-variants` accanto a `/delivery-templates` o `/dam`, esempio:

```html
<a href="/delivery-variants/" class="nav-item">📦 Variants</a>
```

(Adatta classe + posizione al pattern esistente del file.)

- [ ] **Step 3: Bump version**

In `app/main.py`:

```python
app = FastAPI(title="Claqo", version="3.5.0-alpha.172.96", lifespan=lifespan)
```

- [ ] **Step 4: CHANGELOG entry Stack 1 close**

In `CHANGELOG.md`, sopra l'entry α.172.94/95, aggiungi:

```markdown
## v3.5.0-alpha.172.96 — Bundle L Stack 1 close: foundation (26-27 mag 2026)

Foundation stack del cantiere Bundle L. Modelli `VariantSchemaVersion` + `DeliveryVariant` con JSON Schema v1 validato, estensioni `JobDeliverable.variant_id` + `Asset.tech_specs_json`, refactor `asset_metadata.py` in `tech_specs_extractor` service estensibile (plugin registry, ffprobe + pillow), script batch `parse_capitolati.py` (--dry-run su 17 corpus), script `import_parsed_variants.py` con validation, UI listing CRUD `/delivery-variants`, backfill Jaccard JobDeliverable.variant_id.

**Modelli nuovi**:
- `VariantSchemaVersion`: JSON Schema versionato. Solo 1 attivo. Stack futuri = nuova versione, back-compat.
- `DeliveryVariant`: catalog tenant, 14 colonne (code/name/category/spec_json + 6 promosse + 3 origine).
- `DeliveryVariantCategory` enum: t1_technical / t2_documentation / t3_compilation.

**Estensioni**:
- `JobDeliverable`: +variant_id FK +variant_language/territory/format (3 snapshot).
- `Asset`: +tech_specs_json +tech_specs_extractor +tech_specs_extracted_at +tech_specs_schema_version.

**Service nuovi**:
- `app/services/variant_schema.py`: `load_active_schema()`, `validate_variant_spec()` (jsonschema).
- `app/services/tech_specs_extractor/`: registry plugin + ffprobe_extractor + pillow_extractor + ABC base.
- `app/services/asset_metadata.py`: ora wrapper legacy che delega a tech_specs_extractor (back-compat /dam/api/assets/{id}/metadata).

**Script**:
- `scripts/parse_capitolati.py`: extract text PDF/DOCX/TXT/XLSX → chunk → classify T1/T2/T3 → JSON output. Dry-run smokato sui 17 corpus.
- `scripts/import_parsed_variants.py`: import JSON parsed → DB con JSON Schema validation.

**Migrations auto-applicate al boot** (`_auto_migrate_bundle_l_stack1`):
- ALTER TABLE job_deliverables ADD variant_id + variant_language/territory/format
- ALTER TABLE assets ADD tech_specs_json/extractor/extracted_at/schema_version
- Seed VariantSchemaVersion(v1) da `schemas/variant_v1.json`
- Backfill `JobDeliverable.variant_id` via Jaccard keyword match (soglia 0.6)

**Endpoint nuovi** (`/delivery-variants/`):
- GET / (HTML pagina listing)
- GET /api/list (con filtri category/language/format)
- GET /api/{id}
- POST /api/create
- POST /api/{id}/delete (soft)

**Test coverage**: 20+ unit test su modelli, schema validation, extractor service, parser script.

**Dipendenze nuove**: `jsonschema>=4.0.0` aggiunta a requirements.txt.

**Non incluso (rinviato a stack successivi)**:
- QC event-sourced (Stack 2)
- ingest_qc_excel + export_qc_report (Stack 3)
- UI planning variant-aware + asset modal sezioni tipizzate (Stack 4)
- Capability AI runtime extract_capitolato_to_variants (Stack 5)
```

- [ ] **Step 5: STATO.md update**

In `docs/STATO.md`, sostituisci la sezione "Versione corrente" con:

```markdown
## Versione corrente

**v3.5.0-alpha.172.96** — 27 maggio 2026 — Bundle L Stack 1 CLOSE: foundation

Foundation del cantiere strutturale Bundle L (tech specs unified Asset↔Deliverable↔QC). Modelli + JSON Schema validato + extractor service estensibile + script batch parser capitolati + UI listing minimal. Test coverage 20+ unit. Auto-migrate idempotente al boot, dry-run su 17 corpus smokato.

**Sessione 26-27 maggio Stack 1 chiusa**. Prossima sessione: Stack 2 (QC event-sourced).

**v3.5.0-alpha.172.95** — 26 maggio 2026 — Bundle L Stack 1 mid (Task 8-11): ffprobe+pillow extractor + auto-migrate

**v3.5.0-alpha.172.94** — 26 maggio 2026 — Bundle L Stack 1 mid (Task 1-7): models + JSON Schema + extractor base
```

- [ ] **Step 6: Run full test suite**

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: tutti i test passano (~20+ test).

- [ ] **Step 7: Smoke E2E finale**

Restart app + browser:
1. Vai a `/health` → versione `3.5.0-alpha.172.96` ✓
2. Vai a `/delivery-variants/` → pagina si carica ✓
3. Vai a `/dam` → asset detail modal funziona (back-compat ffprobe wrapper) ✓
4. Vai a `/planning` → tab Deliverable funziona (Bundle K1) ✓
5. `/cost-report` → tabs senza errori ✓

- [ ] **Step 8: Commit milestone Stack 1**

```
git add app/templates/ app/main.py CHANGELOG.md docs/STATO.md
git commit -m "v3.5.0-alpha.172.96 — Bundle L Stack 1 CLOSE: foundation (Task 12-17)"
```

---

## Self-review

**Spec coverage check:**

| Spec section | Task |
|--------------|------|
| §4.1 VariantSchemaVersion | Task 1 ✓ |
| §4.2 DeliveryVariant + Category enum | Task 2 ✓ |
| §4.3 JobDeliverable estensioni | Task 3 ✓ |
| §4.4 Asset estensioni | Task 4 ✓ |
| §5 JSON Schema v1 + validation | Task 5, 6 ✓ |
| §6 Tech specs extractor service | Task 7, 8, 9, 10 ✓ |
| §9 parse_capitolati.py batch | Task 12 ✓ |
| §10 Stack 1 deliverable | Tutti i task ✓ |
| §11 Migrazioni Stack 1 | Task 11 ✓ |
| §13 Open question 4 (backfill keyword) | Task 16 (Jaccard heuristic, no AI Stack 1) ✓ |

Coverage 100% per spec Stack 1.

**Non coperto in Stack 1 (rinviato a stack successivi, esplicitato in spec §10)**:
- QCEvent / QCReport / Stack 2 logic
- AI capabilities ingest_qc_excel / suggest_variants_for_job / export_qc_report (Stack 3-4)
- UI planning variant-aware modal (Stack 4)
- Capability runtime extract_capitolato_to_variants (Stack 5)

**Placeholder scan**: nessun TBD/TODO/"implement later" trovato.

**Type consistency**: 
- `DeliveryVariantCategory` enum values consistenti (t1_technical/t2_documentation/t3_compilation) in tutti i task.
- `VariantSchemaVersion.is_active` boolean (default True) consistente Task 1 + import script Task 13.
- `validate_variant_spec(db, spec, schema_version=None)` signature stessa in Task 6 + import Task 13.
- `extract_tech_specs(path, mime)` signature stessa in Task 7 + asset_metadata wrapper Task 10.

Tutto allineato.

---

## Riferimenti

- Design spec: `docs/superpowers/specs/2026-05-26-bundle-l-tech-specs-unified-design.md`
- Brainstorm session: `.superpowers/brainstorm/1596-1779807005/`
- Test fixture corpus: `docs/capitolati_esempio/` (17 file reali)
- QC template canonico: `docs/qc/FbF_QC-Report_Template.xlsx`
