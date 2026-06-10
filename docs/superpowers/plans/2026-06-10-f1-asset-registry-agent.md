# F1 — Asset Registry metadata-only + Claqo Agent (Fondamenta) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registro asset metadata-only (nessun byte di contenuto sul server) + agent facility minimo: register/heartbeat/poll coda job, probe/checksum per path, proposta asset con conferma operatore, blocco upload contenuti media sul DAM.

**Architecture:** Spec approvata `docs/superpowers/specs/2026-06-10-asset-library-metadata-only-design.md`. Claqo (FastAPI+SQLite su VPS) tiene `StorageVolume`/`AgentNode`/`AgentJob` + estensioni `Asset`; agent = pacchetto Python separato `agent/` (solo `requests`+`xxhash`, NON importa `app.*`) che polla la coda via HTTPS outbound, esegue ffprobe/xxhash in facility, riporta JSON. Risultato probe → proposta Asset `pending_review` → conferma umana.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), SQLite, pytest (fixture `db` in-memory in `tests/conftest.py`), ffprobe, xxhash. Convenzioni progetto: tenant filter `CURRENT_TENANT=1`, Form-based API, soft delete, auto-migrate colonne in `app/main.py::_auto_migrate_columns`, UI vanilla JS con helper `api()`/`openModal()`/`toast()` da `static/js/global.js`.

**Nota polling:** v1 = polling semplice ogni 5s (no long-poll vero). Robusto, zero infrastruttura extra. Eventuale long-poll in F2.

---

### Task 1: Enum + modelli `StorageVolume`, `AgentNode`, `AgentJob` + estensioni `Asset`

**Files:**
- Modify: `app/models/models.py` (enum vicino a `AssetStatus` ~riga 238; modelli nuovi dopo `PhysicalAsset` ~riga 3392)
- Test: `tests/test_agent_models.py`

- [ ] **Step 1: Scrivi il test che fallisce**

```python
"""F1 asset registry — modelli StorageVolume/AgentNode/AgentJob + estensioni Asset."""
import pytest
from datetime import datetime

from app.models.models import (
    Tenant, User, UserRole,
    StorageVolume, AgentNode, AgentJob,
    AgentJobType, AgentJobStatus,
    Asset, AssetType, AssetStatus,
    AssetContentState, AssetProposedState,
)


def _tenant(db, tid=1):
    t = Tenant(id=tid, name="T", slug=f"t{tid}")
    db.add(t)
    db.flush()
    return t


def test_storage_volume_create(db):
    _tenant(db)
    v = StorageVolume(tenant_id=1, name="SAN-01", mount_path="/Volumes/SAN01",
                      watch_dirs=["/OUT"], read_only=True)
    db.add(v)
    db.flush()
    assert v.id is not None
    assert v.is_active is True
    assert v.watch_dirs == ["/OUT"]


def test_agent_node_create(db):
    _tenant(db)
    a = AgentNode(tenant_id=1, name="agent-mac-01",
                  auth_token_hash="a" * 64, capabilities=["probe", "checksum"])
    db.add(a)
    db.flush()
    assert a.id is not None
    assert a.last_heartbeat_at is None
    assert a.is_active is True


def test_agent_job_lifecycle_fields(db):
    _tenant(db)
    a = AgentNode(tenant_id=1, name="ag", auth_token_hash="b" * 64)
    db.add(a)
    db.flush()
    j = AgentJob(tenant_id=1, agent_id=a.id, type=AgentJobType.probe,
                 payload={"volume_id": 1, "rel_path": "OUT/P001/file.mov"})
    db.add(j)
    db.flush()
    assert j.status == AgentJobStatus.queued
    assert j.progress == 0
    assert j.result is None


def test_asset_new_columns_defaults(db):
    _tenant(db)
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u)
    db.flush()
    asset = Asset(tenant_id=1, filename="f.mov", original_name="f.mov",
                  file_path="agent://1/OUT/f.mov", asset_type=AssetType.video,
                  mime_type="video/quicktime", file_size=100, uploaded_by=u.id)
    db.add(asset)
    db.flush()
    assert asset.content_state == AssetContentState.online
    assert asset.proposed_state == AssetProposedState.confirmed
    assert asset.storage_volume_id is None
    assert asset.checksum_xxhash is None
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_models.py -v`
Expected: FAIL `ImportError: cannot import name 'StorageVolume'`

- [ ] **Step 3: Implementa enum + modelli**

In `app/models/models.py`, dopo `class AssetStatus` (~riga 243) aggiungi:

```python
# ── F1 asset registry metadata-only (spec 2026-06-10) ──────────────────────
class AssetContentState(str, enum.Enum):
    """Dove vive fisicamente il contenuto. Il record Asset NON muore mai."""
    online = "online"                 # presente su volume SAN/NAS facility
    archived_only = "archived_only"   # solo su LTO/HDD (vedi AssetMembership)
    deleted = "deleted"               # distrutto ovunque (storia resta)


class AssetProposedState(str, enum.Enum):
    """Workflow proposta: agent/path propone, operatore dispone."""
    pending_review = "pending_review"
    confirmed = "confirmed"
    discarded = "discarded"


class AgentJobType(str, enum.Enum):
    scan = "scan"; probe = "probe"; checksum = "checksum"
    preview = "preview"; copy = "copy"
    lto_archive = "lto_archive"; lto_restore = "lto_restore"
    transfer = "transfer"; delete_verify = "delete_verify"


class AgentJobStatus(str, enum.Enum):
    queued = "queued"; claimed = "claimed"; running = "running"
    done = "done"; failed = "failed"; cancelled = "cancelled"
```

Dopo `class PhysicalAsset` (~riga 3392) aggiungi i 3 modelli:

```python
# ── F1 (spec 2026-06-10) — Storage facility + agent + coda comandi ─────────
class StorageVolume(Base):
    """Volume montato della facility (SAN/NAS). Per-TENANT: la SAN è
    infrastruttura, i progetti si agganciano via convenzione path
    (watch_dirs tipo /OUT/{project_code}/) + override per-progetto futuro."""
    __tablename__ = "storage_volumes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(120))
    mount_path: Mapped[str] = mapped_column(String(512))   # lato agent, es. /Volumes/SAN01
    watch_dirs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # ["/OUT"]
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    total_gb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # refresh da agent
    free_gb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AgentNode(Base):
    """Agent facility registrato. Token mostrato UNA volta al create,
    su DB solo sha256. Connessione SOLO outbound (agent → Claqo)."""
    __tablename__ = "agent_nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(120))
    auth_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    capabilities: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # ["probe","checksum"]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AgentJob(Base):
    """Coda comandi Claqo → agent. Agent polla, esegue, riporta.
    agent_id NULL = qualsiasi agent del tenant può prenderlo."""
    __tablename__ = "agent_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agent_nodes.id"), nullable=True, index=True)
    type: Mapped[AgentJobType] = mapped_column(SAEnum(AgentJobType), index=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[AgentJobStatus] = mapped_column(
        SAEnum(AgentJobStatus), default=AgentJobStatus.queued,
        server_default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    physical_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_assets.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

Su `class Asset` (dopo `tech_specs_schema_version`, ~riga 3150) aggiungi:

```python
    # ── F1 (spec 2026-06-10) — registro metadata-only ──
    # file_path resta per documenti business (upload server) e legacy.
    # Asset di contenuto: file_path = "agent://{volume_id}/{rel_path}" marker.
    storage_volume_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("storage_volumes.id"), nullable=True, index=True)
    rel_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    content_state: Mapped[AssetContentState] = mapped_column(
        SAEnum(AssetContentState), default=AssetContentState.online,
        server_default="online", index=True)
    proposed_state: Mapped[AssetProposedState] = mapped_column(
        SAEnum(AssetProposedState), default=AssetProposedState.confirmed,
        server_default="confirmed", index=True)
    checksum_xxhash: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    mhl_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    registered_via: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # registered_via: legacy_upload | manual_path | agent_scan | agent_watch
```

- [ ] **Step 4: Esegui — deve passare**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_models.py -v`
Expected: 4 PASS

- [ ] **Step 5: Esegui suite completa (no regressioni)**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: tutti PASS (464+ test)

- [ ] **Step 6: Commit**

```bash
git add app/models/models.py tests/test_agent_models.py
git commit -m "feat(agent): modelli StorageVolume/AgentNode/AgentJob + Asset metadata-only (F1)"
```

---

### Task 2: Auto-migrate colonne `assets`

**Files:**
- Modify: `app/main.py` dentro `_auto_migrate_columns()` (~riga 33, aggiungi blocco in coda alla funzione)

Le 3 tabelle NUOVE le crea `create_tables()` da sola. Servono solo gli ALTER su `assets`. I DEFAULT server-side gestiscono il backfill dei record esistenti (= migrazione asset legacy: `content_state='online'`, `proposed_state='confirmed'`).

- [ ] **Step 1: Aggiungi blocco auto-migrate**

```python
    # ── F1 (spec 2026-06-10) — Asset registry metadata-only ──
    if "assets" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("assets")}
        f1_alter = [
            ("storage_volume_id", "INTEGER NULL REFERENCES storage_volumes(id)"),
            ("rel_path", "VARCHAR(1024) NULL"),
            ("content_state", "VARCHAR(20) NOT NULL DEFAULT 'online'"),
            ("proposed_state", "VARCHAR(20) NOT NULL DEFAULT 'confirmed'"),
            ("checksum_xxhash", "VARCHAR(32) NULL"),
            ("mhl_ref", "VARCHAR(512) NULL"),
            ("registered_via", "VARCHAR(30) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in f1_alter:
                if col not in cols:
                    print(f"[auto-migrate] assets.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE assets ADD COLUMN {col} {ddl}"))
```

- [ ] **Step 2: Verifica boot su DB reale**

Run: `.venv\Scripts\python.exe -c "from app.main import app"` poi riavvia server e `Invoke-WebRequest http://localhost:8000/health`
Expected: 200, log `[auto-migrate] assets.*` alla prima esecuzione

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat(agent): auto-migrate colonne assets F1"
```

---

### Task 3: Service `agent_queue` (token + enqueue/claim/complete/fail)

**Files:**
- Create: `app/services/agent_queue.py`
- Test: `tests/test_agent_queue.py`

- [ ] **Step 1: Scrivi i test che falliscono**

```python
"""F1 — coda AgentJob: token, enqueue, claim FIFO tenant-scoped, complete/fail."""
import pytest

from app.models.models import (
    Tenant, AgentNode, AgentJob, AgentJobType, AgentJobStatus,
)
from app.services.agent_queue import (
    generate_agent_token, hash_agent_token,
    enqueue_job, claim_next_job, complete_job, fail_job,
)


def _setup(db, tid=1):
    db.add(Tenant(id=tid, name=f"T{tid}", slug=f"t{tid}"))
    db.flush()
    plain, h = generate_agent_token()
    agent = AgentNode(tenant_id=tid, name="ag", auth_token_hash=h)
    db.add(agent)
    db.flush()
    return agent, plain


def test_token_roundtrip():
    plain, h = generate_agent_token()
    assert len(plain) >= 40
    assert hash_agent_token(plain) == h
    assert len(h) == 64  # sha256 hex


def test_enqueue_and_claim_fifo(db):
    agent, _ = _setup(db)
    j1 = enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={"p": 1})
    j2 = enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={"p": 2})
    got = claim_next_job(db, agent)
    assert got.id == j1.id
    assert got.status == AgentJobStatus.claimed
    assert got.agent_id == agent.id
    assert got.claimed_at is not None
    got2 = claim_next_job(db, agent)
    assert got2.id == j2.id


def test_claim_tenant_isolation(db):
    agent1, _ = _setup(db, tid=1)
    agent2, _ = _setup(db, tid=2)
    enqueue_job(db, tenant_id=2, type=AgentJobType.scan, payload={})
    assert claim_next_job(db, agent1) is None
    assert claim_next_job(db, agent2) is not None


def test_claim_respects_agent_pinning(db):
    agent, _ = _setup(db)
    other = AgentNode(tenant_id=1, name="ag2", auth_token_hash="c" * 64)
    db.add(other)
    db.flush()
    enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={}, agent_id=other.id)
    assert claim_next_job(db, agent) is None       # pinned ad altro agent
    assert claim_next_job(db, other) is not None


def test_complete_and_fail(db):
    agent, _ = _setup(db)
    j = enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={})
    claim_next_job(db, agent)
    complete_job(db, j, {"ok": True})
    assert j.status == AgentJobStatus.done
    assert j.result == {"ok": True}
    assert j.finished_at is not None

    j2 = enqueue_job(db, tenant_id=1, type=AgentJobType.checksum, payload={})
    claim_next_job(db, agent)
    fail_job(db, j2, "ffprobe not found")
    assert j2.status == AgentJobStatus.failed
    assert "ffprobe" in j2.error
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_queue.py -v`
Expected: FAIL `ModuleNotFoundError: app.services.agent_queue`

- [ ] **Step 3: Implementa il service**

```python
"""F1 (spec 2026-06-10) — Coda comandi agent: token, enqueue, claim, esiti.

Claim = FIFO tenant-scoped: job più vecchio `queued` con agent_id NULL
oppure pinnato all'agent chiamante. Niente lock distribuito: SQLite
single-writer basta per N agent piccoli (1-2 per facility).
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models.models import AgentJob, AgentJobStatus, AgentJobType, AgentNode


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_agent_token() -> tuple[str, str]:
    """Ritorna (token_plain, sha256_hex). Plain mostrato UNA volta in UI."""
    plain = secrets.token_urlsafe(32)
    return plain, hash_agent_token(plain)


def hash_agent_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def enqueue_job(db: Session, *, tenant_id: int, type: AgentJobType,
                payload: Optional[dict] = None, agent_id: Optional[int] = None,
                requested_by_user_id: Optional[int] = None,
                asset_id: Optional[int] = None,
                physical_asset_id: Optional[int] = None) -> AgentJob:
    job = AgentJob(tenant_id=tenant_id, type=type, payload=payload or {},
                   agent_id=agent_id, requested_by_user_id=requested_by_user_id,
                   asset_id=asset_id, physical_asset_id=physical_asset_id)
    db.add(job)
    db.flush()
    return job


def claim_next_job(db: Session, agent: AgentNode) -> Optional[AgentJob]:
    job = db.execute(
        select(AgentJob)
        .where(AgentJob.tenant_id == agent.tenant_id,
               AgentJob.status == AgentJobStatus.queued,
               or_(AgentJob.agent_id.is_(None), AgentJob.agent_id == agent.id))
        .order_by(AgentJob.id)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = AgentJobStatus.claimed
    job.agent_id = agent.id
    job.claimed_at = _now()
    db.flush()
    return job


def complete_job(db: Session, job: AgentJob, result: dict) -> AgentJob:
    job.status = AgentJobStatus.done
    job.result = result
    job.progress = 100
    job.finished_at = _now()
    db.flush()
    return job


def fail_job(db: Session, job: AgentJob, error: str) -> AgentJob:
    job.status = AgentJobStatus.failed
    job.error = (error or "")[:4000]
    job.finished_at = _now()
    db.flush()
    return job
```

- [ ] **Step 4: Esegui — deve passare**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_queue.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/agent_queue.py tests/test_agent_queue.py
git commit -m "feat(agent): service agent_queue token+enqueue/claim/complete (F1)"
```

---

### Task 4: Service `asset_registry` (proposta da probe, conferma/scarto, guard upload)

**Files:**
- Create: `app/services/asset_registry.py`
- Test: `tests/test_asset_registry.py`

- [ ] **Step 1: Scrivi i test che falliscono**

```python
"""F1 — proposta asset da probe, dedup checksum, conferma/scarto, guard contenuti."""
import pytest

from app.models.models import (
    Tenant, User, UserRole, StorageVolume,
    Asset, AssetType, AssetStatus, AssetContentState, AssetProposedState,
)
from app.services.asset_registry import (
    create_proposal_from_probe, confirm_proposal, discard_proposal,
    is_content_file,
)


def _setup(db):
    db.add(Tenant(id=1, name="T", slug="t1"))
    db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u)
    v = StorageVolume(tenant_id=1, name="SAN-01", mount_path="/Volumes/SAN01")
    db.add(v)
    db.flush()
    return u, v


PROBE = {
    "rel_path": "OUT/P001/master_v3.mov",
    "file_size": 123456789,
    "mime_type": "video/quicktime",
    "checksum_xxhash": "abcd1234abcd1234",
    "tech_specs": {"tool": "ffprobe", "video": {"codec": "prores"}},
}


def test_create_proposal(db):
    u, v = _setup(db)
    a = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                   probe=PROBE, user_id=u.id)
    assert a.proposed_state == AssetProposedState.pending_review
    assert a.status == AssetStatus.uploaded
    assert a.content_state == AssetContentState.online
    assert a.asset_type == AssetType.video
    assert a.filename == "master_v3.mov"
    assert a.rel_path == "OUT/P001/master_v3.mov"
    assert a.file_path == f"agent://{v.id}/OUT/P001/master_v3.mov"
    assert a.checksum_xxhash == "abcd1234abcd1234"
    assert a.tech_specs_json["tool"] == "ffprobe"
    assert a.registered_via == "manual_path"


def test_proposal_dedup_same_checksum_same_volume(db):
    u, v = _setup(db)
    a1 = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                    probe=PROBE, user_id=u.id)
    a2 = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                    probe=PROBE, user_id=u.id)
    assert a1.id == a2.id  # dedup: stesso file, nessun duplicato


def test_confirm_and_discard(db):
    u, v = _setup(db)
    a = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                   probe=PROBE, user_id=u.id)
    confirm_proposal(db, a, user_id=u.id)
    assert a.proposed_state == AssetProposedState.confirmed

    probe2 = dict(PROBE, checksum_xxhash="ffff0000ffff0000",
                  rel_path="OUT/P001/altro.wav", mime_type="audio/wav")
    b = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                   probe=probe2, user_id=u.id)
    discard_proposal(db, b)
    assert b.proposed_state == AssetProposedState.discarded


def test_is_content_file_guard():
    assert is_content_file("master.mov", "video/quicktime") is True
    assert is_content_file("mix_51.wav", "audio/wav") is True
    assert is_content_file("frame.dpx", None) is True          # ext blocklist
    assert is_content_file("capitolato.pdf", "application/pdf") is False
    assert is_content_file("bolla_firmata.jpg", "image/jpeg") is False
    assert is_content_file("note.txt", "text/plain") is False
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_asset_registry.py -v`
Expected: FAIL ModuleNotFoundError

- [ ] **Step 3: Implementa il service**

```python
"""F1 (spec 2026-06-10) — Registro asset metadata-only.

Crea proposte Asset dai risultati probe dell'agent ("agent propone,
operatore dispone"), dedup per checksum+volume, guard anti-upload
contenuti media sul server.
"""
from __future__ import annotations
from pathlib import PurePosixPath
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Asset, AssetType, AssetStatus, AssetContentState, AssetProposedState,
)

# Estensioni di contenuto professionale che ffprobe/mime non sempre marcano
_CONTENT_EXT = {
    ".mov", ".mxf", ".mp4", ".mkv", ".avi", ".webm",
    ".wav", ".aif", ".aiff", ".flac", ".bwf",
    ".dpx", ".exr", ".ari", ".r3d", ".braw", ".dng",
}


def is_content_file(filename: str, mime_type: Optional[str]) -> bool:
    """True = contenuto media (vietato upload server, solo registrazione agent).
    Documenti business (pdf, immagini singole, office) restano uploadabili."""
    if mime_type and (mime_type.startswith("video/") or mime_type.startswith("audio/")):
        return True
    ext = PurePosixPath(filename.lower().replace("\\", "/")).suffix
    return ext in _CONTENT_EXT


def _asset_type_from_mime(mime: Optional[str]) -> AssetType:
    if not mime:
        return AssetType.other
    if mime.startswith("video/"):
        return AssetType.video
    if mime.startswith("audio/"):
        return AssetType.audio
    if mime.startswith("image/"):
        return AssetType.image
    return AssetType.other


def create_proposal_from_probe(db: Session, *, tenant_id: int, volume_id: int,
                               probe: dict, user_id: int,
                               registered_via: str = "manual_path") -> Asset:
    """Crea Asset `pending_review` dal payload probe agent.
    Dedup: stesso checksum_xxhash sullo stesso volume → ritorna l'esistente."""
    checksum = probe.get("checksum_xxhash")
    if checksum:
        existing = db.execute(
            select(Asset).where(Asset.tenant_id == tenant_id,
                                Asset.storage_volume_id == volume_id,
                                Asset.checksum_xxhash == checksum)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    rel_path = (probe.get("rel_path") or "").lstrip("/")
    name = PurePosixPath(rel_path.replace("\\", "/")).name or rel_path
    mime = probe.get("mime_type")
    asset = Asset(
        tenant_id=tenant_id,
        filename=name, original_name=name,
        file_path=f"agent://{volume_id}/{rel_path}",
        storage_volume_id=volume_id, rel_path=rel_path,
        asset_type=_asset_type_from_mime(mime),
        mime_type=mime or "application/octet-stream",
        file_size=int(probe.get("file_size") or 0),
        uploaded_by=user_id,
        status=AssetStatus.uploaded,
        content_state=AssetContentState.online,
        proposed_state=AssetProposedState.pending_review,
        checksum_xxhash=checksum,
        registered_via=registered_via,
        tech_specs_json=probe.get("tech_specs"),
        tech_specs_extractor="agent-ffprobe",
    )
    db.add(asset)
    db.flush()
    return asset


def confirm_proposal(db: Session, asset: Asset, *, user_id: int) -> Asset:
    asset.proposed_state = AssetProposedState.confirmed
    db.flush()
    return asset


def discard_proposal(db: Session, asset: Asset) -> Asset:
    asset.proposed_state = AssetProposedState.discarded
    db.flush()
    return asset
```

- [ ] **Step 4: Esegui — deve passare**

Run: `.venv\Scripts\python.exe -m pytest tests/test_asset_registry.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/asset_registry.py tests/test_asset_registry.py
git commit -m "feat(agent): service asset_registry proposta/conferma + guard contenuti (F1)"
```

---

### Task 5: Blocco upload contenuti media sul DAM

**Files:**
- Modify: `app/routers/dam.py` (endpoint `upload_asset`, ~riga 372: guard subito dopo lettura `file.filename`)
- Test: `tests/test_asset_registry.py` (già coperto da `test_is_content_file_guard`; qui solo wiring)

- [ ] **Step 1: Aggiungi guard nel router**

In `app/routers/dam.py`, import in testa: `from app.services.asset_registry import is_content_file`.
Dentro `upload_asset`, PRIMA di `save_upload(...)` (~riga 387):

```python
    # F1 (spec 2026-06-10) — Contenuto media MAI sul server Claqo.
    # Asset di contenuto si registrano metadata-only via agent (/storage).
    import mimetypes as _mt
    _guessed_mime, _ = _mt.guess_type(file.filename or "")
    if is_content_file(file.filename or "", _guessed_mime):
        raise HTTPException(
            status_code=422,
            detail="File di contenuto media: vietato l'upload sul server. "
                   "Registralo via agent dalla pagina Storage (metadata-only).")
```

- [ ] **Step 2: Verifica con server**

Riavvia server, poi:
Run: `.venv\Scripts\python.exe -c "import requests"` — se manca requests usa Invoke-WebRequest. Test manuale: upload di un `.txt` (passa) e prova `.mov` finto (422). In alternativa smoke Playwright in Task 10.
Expected: `.mov` → 422 con messaggio; `.pdf`/`.txt` → 200 come prima

- [ ] **Step 3: Commit**

```bash
git add app/routers/dam.py
git commit -m "feat(dam): blocco upload contenuti media - solo metadata via agent (F1)"
```

---

### Task 6: Router `agent_api` (heartbeat, claim, result)

**Files:**
- Create: `app/routers/agent_api.py`
- Modify: `app/main.py` (import + `app.include_router(agent_api.router)` vicino agli altri ~riga 2585)
- Test: `tests/test_agent_api.py`

Auth: header `X-Agent-Token`, lookup `AgentNode` per sha256. Niente JWT utente: l'agent non è un utente. Il result di un job `probe` con esito `done` crea la proposta asset (wiring service Task 4).

- [ ] **Step 1: Scrivi i test che falliscono** (service-level sulla logica di processo risultato, senza TestClient)

```python
"""F1 — processo risultato job agent: done probe → proposta asset."""
import pytest

from app.models.models import (
    Tenant, User, UserRole, StorageVolume, AgentNode,
    AgentJobType, AgentJobStatus, AssetProposedState,
)
from app.services.agent_queue import enqueue_job, claim_next_job
from app.routers.agent_api import process_job_result


def _setup(db):
    db.add(Tenant(id=1, name="T", slug="t1"))
    db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u)
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    db.add(v)
    agent = AgentNode(tenant_id=1, name="ag", auth_token_hash="d" * 64)
    db.add(agent)
    db.flush()
    return u, v, agent


def test_probe_done_creates_proposal(db):
    u, v, agent = _setup(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                      payload={"volume_id": v.id, "rel_path": "OUT/x.mov"},
                      requested_by_user_id=u.id)
    claim_next_job(db, agent)
    asset = process_job_result(db, job, status="done", result={
        "rel_path": "OUT/x.mov", "file_size": 10, "mime_type": "video/quicktime",
        "checksum_xxhash": "ee11ee11ee11ee11",
        "tech_specs": {"tool": "ffprobe"},
    })
    assert job.status == AgentJobStatus.done
    assert asset is not None
    assert asset.proposed_state == AssetProposedState.pending_review
    assert job.asset_id == asset.id


def test_failed_job_no_proposal(db):
    u, v, agent = _setup(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                      payload={"volume_id": v.id, "rel_path": "OUT/x.mov"})
    claim_next_job(db, agent)
    asset = process_job_result(db, job, status="failed", result=None,
                               error="path not found")
    assert job.status == AgentJobStatus.failed
    assert asset is None
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_api.py -v`
Expected: FAIL ModuleNotFoundError

- [ ] **Step 3: Implementa il router**

```python
"""F1 (spec 2026-06-10) — API per Claqo Agent (facility-side).

Auth: header X-Agent-Token (sha256 lookup su AgentNode). SOLO outbound
dall'agent: heartbeat, claim job, push risultato. Nessun byte di
contenuto transita: solo JSON metadata.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    AgentNode, AgentJob, AgentJobType, StorageVolume,
)
from app.services.agent_queue import (
    hash_agent_token, claim_next_job, complete_job, fail_job,
)
from app.services.asset_registry import create_proposal_from_probe

router = APIRouter(prefix="/agent-api", tags=["agent"])


def get_agent(x_agent_token: str = Header(...),
              db: Session = Depends(get_db)) -> AgentNode:
    agent = db.execute(
        select(AgentNode).where(
            AgentNode.auth_token_hash == hash_agent_token(x_agent_token),
            AgentNode.is_active.is_(True))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=401, detail="agent token non valido")
    return agent


class HeartbeatIn(BaseModel):
    version: Optional[str] = None
    capabilities: Optional[list] = None
    volumes: Optional[list] = None  # [{"volume_id":1,"total_gb":..,"free_gb":..}]


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, agent: AgentNode = Depends(get_agent),
              db: Session = Depends(get_db)):
    agent.last_heartbeat_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if body.version:
        agent.version = body.version
    if body.capabilities is not None:
        agent.capabilities = body.capabilities
    for vs in body.volumes or []:
        vol = db.get(StorageVolume, int(vs.get("volume_id") or 0))
        if vol is not None and vol.tenant_id == agent.tenant_id:
            vol.total_gb = vs.get("total_gb")
            vol.free_gb = vs.get("free_gb")
    db.commit()
    # Config volumi del tenant: l'agent la riceve a ogni heartbeat
    vols = db.execute(
        select(StorageVolume).where(StorageVolume.tenant_id == agent.tenant_id,
                                    StorageVolume.is_active.is_(True))
    ).scalars().all()
    return {"ok": True, "volumes": [
        {"id": v.id, "name": v.name, "mount_path": v.mount_path,
         "watch_dirs": v.watch_dirs or [], "read_only": v.read_only}
        for v in vols
    ]}


@router.post("/jobs/claim")
def claim(agent: AgentNode = Depends(get_agent), db: Session = Depends(get_db)):
    job = claim_next_job(db, agent)
    db.commit()
    if job is None:
        return {"job": None}
    return {"job": {"id": job.id, "type": job.type.value, "payload": job.payload}}


class ResultIn(BaseModel):
    status: str               # "done" | "failed"
    result: Optional[dict] = None
    error: Optional[str] = None


def process_job_result(db: Session, job: AgentJob, *, status: str,
                       result: Optional[dict], error: Optional[str] = None):
    """Applica l'esito del job. Probe done → crea proposta asset.
    Ritorna l'Asset creato (o None). Estratta dal route handler per testabilità."""
    if status == "failed":
        fail_job(db, job, error or "errore agent non specificato")
        return None
    complete_job(db, job, result or {})
    if job.type == AgentJobType.probe and result:
        volume_id = int((job.payload or {}).get("volume_id") or 0)
        asset = create_proposal_from_probe(
            db, tenant_id=job.tenant_id, volume_id=volume_id, probe=result,
            user_id=job.requested_by_user_id or 1,
            registered_via="manual_path")
        job.asset_id = asset.id
        db.flush()
        return asset
    return None


@router.post("/jobs/{job_id}/result")
def post_result(job_id: int, body: ResultIn,
                agent: AgentNode = Depends(get_agent),
                db: Session = Depends(get_db)):
    job = db.get(AgentJob, job_id)
    if job is None or job.tenant_id != agent.tenant_id or job.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="job non trovato")
    asset = process_job_result(db, job, status=body.status,
                               result=body.result, error=body.error)
    db.commit()
    return {"ok": True, "asset_id": asset.id if asset else None}
```

In `app/main.py`: aggiungi `agent_api` all'import dei router e `app.include_router(agent_api.router)` accanto a `dam.router`.

- [ ] **Step 4: Esegui — deve passare**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_api.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/agent_api.py app/main.py tests/test_agent_api.py
git commit -m "feat(agent): router agent-api heartbeat/claim/result (F1)"
```

---

### Task 7: Router admin `/storage` (volumi, agent, job, proposte, register-path)

**Files:**
- Create: `app/routers/storage_admin.py`
- Modify: `app/main.py` (include router)
- Test: smoke in Task 10 (endpoint CRUD sottili, logica già testata nei service)

- [ ] **Step 1: Implementa il router**

Pattern di riferimento: `app/routers/departments.py` (CRUD pulito). RBAC: riusa `requires_permission("edit_planning_all")` come `dam.py:39` (tightening permessi dedicati = backlog F2).

```python
"""F1 (spec 2026-06-10) — Admin storage facility: volumi, agent, coda, proposte."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    StorageVolume, AgentNode, AgentJob, AgentJobType,
    Asset, AssetProposedState,
)
from app.services.agent_queue import generate_agent_token, enqueue_job
from app.services.asset_registry import confirm_proposal, discard_proposal
from app.services.auth import requires_permission, get_current_user
from app.templates_env import templates  # stesso import usato dagli altri router

CURRENT_TENANT = 1
RequireStorage = Depends(requires_permission("edit_planning_all"))

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("")
def storage_page(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse("pages/storage.html",
                                      {"request": request, "user": user})


# ── Volumi ──────────────────────────────────────────────────────────
@router.get("/api/volumes")
def list_volumes(db: Session = Depends(get_db)):
    vols = db.execute(select(StorageVolume)
                      .where(StorageVolume.tenant_id == CURRENT_TENANT)
                      .order_by(StorageVolume.name)).scalars().all()
    return [{"id": v.id, "name": v.name, "mount_path": v.mount_path,
             "watch_dirs": v.watch_dirs or [], "read_only": v.read_only,
             "total_gb": v.total_gb, "free_gb": v.free_gb,
             "is_active": v.is_active} for v in vols]


@router.post("/api/volumes", dependencies=[RequireStorage])
def create_volume(name: str = Form(...), mount_path: str = Form(...),
                  watch_dirs: str = Form(""),   # CSV: "/OUT,/EXPORT"
                  read_only: bool = Form(True),
                  db: Session = Depends(get_db)):
    dirs = [d.strip() for d in watch_dirs.split(",") if d.strip()]
    v = StorageVolume(tenant_id=CURRENT_TENANT, name=name,
                      mount_path=mount_path, watch_dirs=dirs,
                      read_only=read_only)
    db.add(v)
    db.commit()
    return {"ok": True, "id": v.id}


@router.put("/api/volumes/{vol_id}", dependencies=[RequireStorage])
def update_volume(vol_id: int, name: str = Form(...),
                  mount_path: str = Form(...), watch_dirs: str = Form(""),
                  read_only: bool = Form(True), is_active: bool = Form(True),
                  db: Session = Depends(get_db)):
    v = db.get(StorageVolume, vol_id)
    if v is None or v.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    v.name = name; v.mount_path = mount_path
    v.watch_dirs = [d.strip() for d in watch_dirs.split(",") if d.strip()]
    v.read_only = read_only; v.is_active = is_active
    db.commit()
    return {"ok": True}


# ── Agent ───────────────────────────────────────────────────────────
@router.get("/api/agents")
def list_agents(db: Session = Depends(get_db)):
    ags = db.execute(select(AgentNode)
                     .where(AgentNode.tenant_id == CURRENT_TENANT)
                     .order_by(AgentNode.name)).scalars().all()
    return [{"id": a.id, "name": a.name, "version": a.version,
             "capabilities": a.capabilities or [],
             "last_heartbeat_at": a.last_heartbeat_at.isoformat() if a.last_heartbeat_at else None,
             "is_active": a.is_active} for a in ags]


@router.post("/api/agents", dependencies=[RequireStorage])
def create_agent(name: str = Form(...), db: Session = Depends(get_db)):
    plain, token_hash = generate_agent_token()
    a = AgentNode(tenant_id=CURRENT_TENANT, name=name, auth_token_hash=token_hash)
    db.add(a)
    db.commit()
    # token plain mostrato UNA SOLA volta
    return {"ok": True, "id": a.id, "token": plain}


@router.delete("/api/agents/{agent_id}", dependencies=[RequireStorage])
def revoke_agent(agent_id: int, db: Session = Depends(get_db)):
    a = db.get(AgentNode, agent_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    a.is_active = False
    db.commit()
    return {"ok": True}


# ── Job + register-path ─────────────────────────────────────────────
@router.get("/api/jobs")
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    jobs = db.execute(select(AgentJob)
                      .where(AgentJob.tenant_id == CURRENT_TENANT)
                      .order_by(AgentJob.id.desc()).limit(limit)).scalars().all()
    return [{"id": j.id, "type": j.type.value, "status": j.status.value,
             "payload": j.payload, "error": j.error, "progress": j.progress,
             "created_at": j.created_at.isoformat(),
             "asset_id": j.asset_id} for j in jobs]


@router.post("/api/register-path", dependencies=[RequireStorage])
def register_path(volume_id: int = Form(...), rel_path: str = Form(...),
                  request: Request = None, db: Session = Depends(get_db)):
    v = db.get(StorageVolume, volume_id)
    if v is None or v.tenant_id != CURRENT_TENANT or not v.is_active:
        raise HTTPException(404, "volume non trovato")
    user = get_current_user(request, db) if request else None
    job = enqueue_job(db, tenant_id=CURRENT_TENANT, type=AgentJobType.probe,
                      payload={"volume_id": volume_id,
                               "rel_path": rel_path.strip().lstrip("/")},
                      requested_by_user_id=getattr(user, "id", None))
    db.commit()
    return {"ok": True, "job_id": job.id}


# ── Proposte ────────────────────────────────────────────────────────
@router.get("/api/proposals")
def list_proposals(db: Session = Depends(get_db)):
    rows = db.execute(select(Asset)
                      .where(Asset.tenant_id == CURRENT_TENANT,
                             Asset.proposed_state == AssetProposedState.pending_review)
                      .order_by(Asset.id.desc())).scalars().all()
    return [{"id": a.id, "filename": a.filename, "rel_path": a.rel_path,
             "file_size": a.file_size, "mime_type": a.mime_type,
             "checksum_xxhash": a.checksum_xxhash,
             "tech_specs": a.tech_specs_json,
             "volume_id": a.storage_volume_id} for a in rows]


@router.post("/api/proposals/{asset_id}/confirm", dependencies=[RequireStorage])
def confirm(asset_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    user = get_current_user(request, db)
    confirm_proposal(db, a, user_id=user.id)
    db.commit()
    return {"ok": True}


@router.post("/api/proposals/{asset_id}/discard", dependencies=[RequireStorage])
def discard(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    discard_proposal(db, a)
    db.commit()
    return {"ok": True}
```

**ATTENZIONE import**: verifica i nomi reali di `templates`, `get_current_user`, `requires_permission` guardando la testa di `app/routers/dam.py` e copia gli stessi import (potrebbero differire: es. `from app.auth import ...`). Stessa cosa per la firma `get_current_user(request, db)` — allinea a come la usano gli altri router.

In `app/main.py`: import + `app.include_router(storage_admin.router)`.

- [ ] **Step 2: Boot check**

Run: `.venv\Scripts\python.exe -c "from app.main import app; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/routers/storage_admin.py app/main.py
git commit -m "feat(storage): router admin volumi/agent/job/proposte/register-path (F1)"
```

---

### Task 8: UI pagina `/storage` (tab Volumi / Agent / Proposte / Job)

**Files:**
- Create: `app/templates/pages/storage.html`
- Modify: `app/templates/base.html` (voce sidebar "Storage" vicino a DAM/Asset — cerca il blocco nav esistente e replica il pattern della voce DAM)

Pattern UI: segui `app/templates/pages/departments.html` (CRUD pulito di riferimento, da leggere PRIMA di scrivere il template). Usa helper globali `api()`, `openModal()`, `closeModal()`, `toast()`, `escapeHtml()` da `static/js/global.js` — NON ridefinirli. Niente `JSON.stringify` negli onclick: usa `data-*` attributes.

- [ ] **Step 1: Crea il template**

Struttura richiesta (adatta markup/classi a quelli reali di `departments.html`):

```html
{% extends "base.html" %}
{% block title %}Storage facility{% endblock %}
{% block content %}
<div class="page-header"><h1>📦 Storage facility</h1></div>

<div class="tabs">
  <button class="tab-btn active" data-tab="proposals">Proposte</button>
  <button class="tab-btn" data-tab="volumes">Volumi</button>
  <button class="tab-btn" data-tab="agents">Agent</button>
  <button class="tab-btn" data-tab="jobs">Job</button>
</div>

<div id="tab-proposals" class="tab-pane active">
  <div class="toolbar">
    <button class="btn btn-primary" onclick="openRegisterPathModal()">+ Registra file per percorso</button>
  </div>
  <table class="data-table"><thead><tr>
    <th>File</th><th>Percorso</th><th>Dimensione</th><th>Checksum</th><th>Specs</th><th></th>
  </tr></thead><tbody id="proposalsBody"></tbody></table>
</div>

<div id="tab-volumes" class="tab-pane" style="display:none">
  <div class="toolbar"><button class="btn btn-primary" onclick="openVolumeModal()">+ Volume</button></div>
  <table class="data-table"><thead><tr>
    <th>Nome</th><th>Mount</th><th>Watch dirs</th><th>Spazio</th><th>Stato</th><th></th>
  </tr></thead><tbody id="volumesBody"></tbody></table>
</div>

<div id="tab-agents" class="tab-pane" style="display:none">
  <div class="toolbar"><button class="btn btn-primary" onclick="openAgentModal()">+ Agent</button></div>
  <table class="data-table"><thead><tr>
    <th>Nome</th><th>Versione</th><th>Heartbeat</th><th>Stato</th><th></th>
  </tr></thead><tbody id="agentsBody"></tbody></table>
</div>

<div id="tab-jobs" class="tab-pane" style="display:none">
  <table class="data-table"><thead><tr>
    <th>#</th><th>Tipo</th><th>Stato</th><th>Payload</th><th>Errore</th>
  </tr></thead><tbody id="jobsBody"></tbody></table>
</div>

<!-- Modal volume / agent / register-path: replica struttura modal di departments.html -->

<script>
const fmtGb = g => g == null ? '—' : `${Number(g).toFixed(0)} GB`;

async function loadProposals() {
  const rows = await api('/storage/api/proposals');
  document.getElementById('proposalsBody').innerHTML = rows.map(p => `
    <tr>
      <td>${escapeHtml(p.filename)}</td>
      <td class="mono">${escapeHtml(p.rel_path || '')}</td>
      <td>${(p.file_size/1e9).toFixed(2)} GB</td>
      <td class="mono">${escapeHtml(p.checksum_xxhash || '—')}</td>
      <td>${p.tech_specs ? escapeHtml(JSON.stringify(p.tech_specs).slice(0,80)) : '—'}</td>
      <td>
        <button class="btn btn-sm btn-success" data-id="${p.id}" onclick="confirmProposal(this.dataset.id)">✓ Conferma</button>
        <button class="btn btn-sm btn-danger" data-id="${p.id}" onclick="discardProposal(this.dataset.id)">✗ Scarta</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="6">Nessuna proposta in attesa.</td></tr>';
}

async function confirmProposal(id) {
  await api(`/storage/api/proposals/${id}/confirm`, {method:'POST'});
  toast('Asset confermato'); loadProposals();
}
async function discardProposal(id) {
  await api(`/storage/api/proposals/${id}/discard`, {method:'POST'});
  toast('Proposta scartata'); loadProposals();
}

async function loadVolumes() { /* GET /storage/api/volumes → render volumesBody,
  bottone Modifica apre modal precompilato (data-* attrs) */ }
async function loadAgents() { /* GET /storage/api/agents → render agentsBody;
  heartbeat < 120s → badge verde "online", altrimenti grigio "offline";
  bottone Revoca → DELETE /storage/api/agents/{id} */ }
async function loadJobs() { /* GET /storage/api/jobs → render jobsBody */ }

async function submitRegisterPath(form) {
  const fd = new FormData(form);
  await api('/storage/api/register-path', {method:'POST', body: fd});
  toast('Job probe accodato — appena l\'agent risponde compare la proposta');
  closeModal('registerPathModal'); loadJobs();
}

// submit agent modal: la risposta contiene {token} → mostralo in un box
// copia-incolla con warning "salvalo ORA, non sarà più visibile"

// tab switching standard + load iniziale
document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tab-btn').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(x => x.style.display = 'none');
  b.classList.add('active');
  document.getElementById('tab-' + b.dataset.tab).style.display = '';
}));
loadProposals(); loadVolumes(); loadAgents(); loadJobs();
</script>
{% endblock %}
```

Le funzioni lasciate come commento (`loadVolumes`, `loadAgents`, `loadJobs`, modali) vanno implementate per intero seguendo il pattern di `departments.html` — render tabella + modal Form-based con `FormData`. Modal create-agent: dopo il POST mostra `resp.token` in un `<input readonly>` con bottone copia.

- [ ] **Step 2: Smoke browser**

Riavvia server (template Jinja non si ricarica a runtime su OneDrive). Apri `/storage`: 4 tab renderizzano, console senza ReferenceError (grep dei nomi funzione prima del commit: ogni `onclick` ha la sua funzione definita).
Expected: pagina carica, tabelle vuote con messaggio, modali aprono/chiudono.

- [ ] **Step 3: Commit**

```bash
git add app/templates/pages/storage.html app/templates/base.html
git commit -m "feat(storage): UI /storage tab volumi/agent/proposte/job (F1)"
```

---

### Task 9: Pacchetto `agent/` (demone facility)

**Files:**
- Create: `agent/__init__.py` (vuoto, solo versione: `__version__ = "0.1.0"`)
- Create: `agent/config.py`
- Create: `agent/probe.py`
- Create: `agent/client.py`
- Create: `agent/main.py`
- Create: `agent/requirements.txt`
- Create: `agent/README.md`
- Test: `tests/test_agent_probe.py`

L'agent NON importa `app.*` (gira su macchina facility senza il server). Dipendenze: solo `requests` + `xxhash`. ffprobe = binario di sistema.

- [ ] **Step 1: Scrivi il test che fallisce** (probe normalizzazione, ffprobe mockato)

```python
"""F1 — agent probe: normalizzazione ffprobe + xxhash file."""
import json
import pytest

from agent.probe import normalize_ffprobe, xxhash_file, build_probe_result


FFPROBE_OUT = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "60.5",
               "size": "1000000"},
    "streams": [
        {"codec_type": "video", "codec_name": "prores", "width": 1920,
         "height": 1080, "r_frame_rate": "25/1", "pix_fmt": "yuv422p10le"},
        {"codec_type": "audio", "codec_name": "pcm_s24le", "channels": 2,
         "sample_rate": "48000"},
    ],
}


def test_normalize_ffprobe():
    specs = normalize_ffprobe(FFPROBE_OUT)
    assert specs["tool"] == "ffprobe"
    assert specs["container"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert specs["duration_sec"] == pytest.approx(60.5)
    assert specs["video"]["codec"] == "prores"
    assert specs["video"]["width"] == 1920
    assert specs["video"]["frame_rate"] == "25/1"
    assert specs["audio"][0]["channels"] == 2


def test_xxhash_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"claqo" * 1000)
    h1 = xxhash_file(str(f))
    h2 = xxhash_file(str(f))
    assert h1 == h2
    assert len(h1) == 16  # xxh64 hex


def test_build_probe_result(tmp_path, monkeypatch):
    f = tmp_path / "OUT" / "file.mov"
    f.parent.mkdir()
    f.write_bytes(b"finto contenuto")
    monkeypatch.setattr("agent.probe.run_ffprobe", lambda p: FFPROBE_OUT)
    res = build_probe_result(str(tmp_path), "OUT/file.mov")
    assert res["rel_path"] == "OUT/file.mov"
    assert res["file_size"] == 15
    assert res["mime_type"] == "video/quicktime"
    assert len(res["checksum_xxhash"]) == 16
    assert res["tech_specs"]["video"]["codec"] == "prores"
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_probe.py -v`
Expected: FAIL ModuleNotFoundError (serve anche `pip install xxhash` nel venv dev)

- [ ] **Step 3: Implementa `agent/probe.py`**

```python
"""Probe locale: ffprobe JSON + xxhash64. Nessun byte lascia la facility."""
from __future__ import annotations
import json
import mimetypes
import os
import subprocess
from typing import Optional

import xxhash

_CHUNK = 8 * 1024 * 1024


def run_ffprobe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe rc={out.returncode}: {out.stderr[:500]}")
    return json.loads(out.stdout or "{}")


def normalize_ffprobe(raw: dict) -> dict:
    fmt = raw.get("format") or {}
    specs = {
        "tool": "ffprobe",
        "container": fmt.get("format_name"),
        "duration_sec": float(fmt["duration"]) if fmt.get("duration") else None,
        "video": None,
        "audio": [],
        "errors": [],
    }
    for s in raw.get("streams") or []:
        if s.get("codec_type") == "video" and specs["video"] is None:
            specs["video"] = {
                "codec": s.get("codec_name"), "width": s.get("width"),
                "height": s.get("height"), "frame_rate": s.get("r_frame_rate"),
                "pix_fmt": s.get("pix_fmt"),
            }
        elif s.get("codec_type") == "audio":
            specs["audio"].append({
                "codec": s.get("codec_name"), "channels": s.get("channels"),
                "sample_rate": s.get("sample_rate"),
            })
    return specs


def xxhash_file(path: str) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def build_probe_result(mount_path: str, rel_path: str) -> dict:
    full = os.path.join(mount_path, rel_path)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"non trovato: {full}")
    mime, _ = mimetypes.guess_type(rel_path)
    try:
        specs = normalize_ffprobe(run_ffprobe(full))
    except Exception as e:                      # ffprobe assente o file non-media
        specs = {"tool": "none", "errors": [str(e)[:300]]}
    return {
        "rel_path": rel_path.replace("\\", "/"),
        "file_size": os.path.getsize(full),
        "mime_type": mime or "application/octet-stream",
        "checksum_xxhash": xxhash_file(full),
        "tech_specs": specs,
    }
```

- [ ] **Step 4: Implementa `agent/config.py`, `agent/client.py`, `agent/main.py`**

`agent/config.py`:

```python
"""Config da ENV o file claqo-agent.json nella cwd.

ENV: CLAQO_URL, CLAQO_AGENT_TOKEN, CLAQO_POLL_SECONDS (default 5),
CLAQO_HEARTBEAT_SECONDS (default 30).
"""
from __future__ import annotations
import json
import os


class Config:
    def __init__(self):
        file_cfg = {}
        if os.path.isfile("claqo-agent.json"):
            with open("claqo-agent.json", encoding="utf-8") as f:
                file_cfg = json.load(f)
        self.server_url = (os.environ.get("CLAQO_URL")
                           or file_cfg.get("server_url") or "").rstrip("/")
        self.token = os.environ.get("CLAQO_AGENT_TOKEN") or file_cfg.get("token") or ""
        self.poll_seconds = int(os.environ.get("CLAQO_POLL_SECONDS")
                                or file_cfg.get("poll_seconds") or 5)
        self.heartbeat_seconds = int(os.environ.get("CLAQO_HEARTBEAT_SECONDS")
                                     or file_cfg.get("heartbeat_seconds") or 30)
        if not self.server_url or not self.token:
            raise SystemExit("Config mancante: CLAQO_URL e CLAQO_AGENT_TOKEN "
                             "(env o claqo-agent.json)")
```

`agent/client.py`:

```python
"""HTTP client verso Claqo. Solo outbound, solo JSON."""
from __future__ import annotations
import requests


class ClaqoClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url
        self.s = requests.Session()
        self.s.headers["X-Agent-Token"] = token

    def heartbeat(self, version: str, capabilities: list, volumes: list) -> dict:
        r = self.s.post(f"{self.base}/agent-api/heartbeat", json={
            "version": version, "capabilities": capabilities, "volumes": volumes,
        }, timeout=30)
        r.raise_for_status()
        return r.json()

    def claim(self) -> dict | None:
        r = self.s.post(f"{self.base}/agent-api/jobs/claim", timeout=30)
        r.raise_for_status()
        return r.json().get("job")

    def post_result(self, job_id: int, status: str,
                    result: dict | None = None, error: str | None = None):
        r = self.s.post(f"{self.base}/agent-api/jobs/{job_id}/result", json={
            "status": status, "result": result, "error": error,
        }, timeout=60)
        r.raise_for_status()
        return r.json()
```

`agent/main.py`:

```python
"""Claqo Agent v0.1 (F1) — loop: heartbeat + poll coda + probe/checksum.

Avvio:  python -m agent.main
I volumi (id → mount_path) arrivano dal server a ogni heartbeat.
"""
from __future__ import annotations
import shutil
import time
import traceback

from agent import __version__
from agent.config import Config
from agent.client import ClaqoClient
from agent.probe import build_probe_result, xxhash_file

CAPABILITIES = ["probe", "checksum"]


def volume_stats(volumes: list[dict]) -> list[dict]:
    out = []
    for v in volumes:
        try:
            du = shutil.disk_usage(v["mount_path"])
            out.append({"volume_id": v["id"],
                        "total_gb": round(du.total / 1e9, 1),
                        "free_gb": round(du.free / 1e9, 1)})
        except OSError:
            pass  # volume smontato: niente stats, il server lo vede dal gap
    return out


def handle_job(job: dict, volumes_by_id: dict) -> tuple[str, dict | None, str | None]:
    jtype, payload = job["type"], job.get("payload") or {}
    vol = volumes_by_id.get(int(payload.get("volume_id") or 0))
    if vol is None:
        return "failed", None, f"volume_id {payload.get('volume_id')} sconosciuto all'agent"
    try:
        if jtype == "probe":
            return "done", build_probe_result(vol["mount_path"], payload["rel_path"]), None
        if jtype == "checksum":
            import os
            full = os.path.join(vol["mount_path"], payload["rel_path"])
            return "done", {"checksum_xxhash": xxhash_file(full)}, None
        return "failed", None, f"tipo job non supportato da agent v{__version__}: {jtype}"
    except Exception as e:
        return "failed", None, f"{type(e).__name__}: {e}"


def run():
    cfg = Config()
    client = ClaqoClient(cfg.server_url, cfg.token)
    volumes: list[dict] = []
    last_hb = 0.0
    print(f"[agent] v{__version__} → {cfg.server_url}")
    while True:
        try:
            now = time.monotonic()
            if now - last_hb >= cfg.heartbeat_seconds or not volumes:
                resp = client.heartbeat(__version__, CAPABILITIES,
                                        volume_stats(volumes))
                volumes = resp.get("volumes") or []
                last_hb = now
            vols_by_id = {v["id"]: v for v in volumes}
            job = client.claim()
            if job:
                print(f"[agent] job #{job['id']} {job['type']}")
                status, result, error = handle_job(job, vols_by_id)
                client.post_result(job["id"], status, result, error)
                continue  # coda non vuota: ripolla subito
        except Exception:
            traceback.print_exc()
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    run()
```

`agent/requirements.txt`:

```
requests>=2.31
xxhash>=3.4
```

`agent/README.md`: istruzioni installazione (venv, `pip install -r agent/requirements.txt`, ffprobe nel PATH, creare agent in `/storage` UI → copiare token → `claqo-agent.json` con `{"server_url": "...", "token": "..."}` → `python -m agent.main`).

Aggiungi `xxhash` anche al `requirements.txt` principale (serve ai test).

- [ ] **Step 5: Esegui — deve passare**

Run: `.venv\Scripts\pip.exe install xxhash` poi `.venv\Scripts\python.exe -m pytest tests/test_agent_probe.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add agent/ tests/test_agent_probe.py requirements.txt
git commit -m "feat(agent): demone facility v0.1 - heartbeat/poll/probe/checksum (F1)"
```

---### Task 10: E2E locale + smoke browser

**Files:**
- Create: `docs/qc/f1-e2e-checklist.md` (esiti)

- [ ] **Step 1: E2E loop completo in locale**

1. Riavvia server (no-reload). Crea cartella finta `C:\temp\san01\OUT\P001\` con dentro un file `.mov` piccolo (anche finto: ffprobe fallisce gentile, specs tool=none).
2. UI `/storage` → tab Volumi → crea volume "SAN-01-test" mount `C:\temp\san01`.
3. Tab Agent → crea agent → copia token.
4. `claqo-agent.json` con url `http://localhost:8000` + token → `.venv\Scripts\python.exe -m agent.main`.
5. Verifica heartbeat: tab Agent mostra "online".
6. Tab Proposte → "Registra file per percorso" → volume SAN-01-test, path `OUT/P001/test.mov`.
7. Entro ~5s: job done, proposta appare con checksum + size.
8. Conferma → asset visibile in /dam con badge metadata-only (file_path `agent://...`).
9. Upload `.mov` da /dam → 422 bloccato. Upload `.pdf` → ok.

- [ ] **Step 2: Documenta esiti nella checklist + fix eventuali**

- [ ] **Step 3: Commit**

```bash
git add docs/qc/f1-e2e-checklist.md
git commit -m "test(agent): checklist E2E F1 server+agent loop completo"
```

---

### Task 11: Versione + CHANGELOG + STATO + push

**Files:**
- Modify: `app/main.py` (version bump → `3.5.0-alpha.172.210`)
- Modify: `CHANGELOG.md`
- Modify: `docs/STATO.md` (sezione "in corso" + prossimo step = F2 watch)

- [ ] **Step 1: Bump + CHANGELOG + STATO**
- [ ] **Step 2: Suite completa**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: tutti PASS

- [ ] **Step 3: Export ZIP DB in docs/ (policy pre-push) + commit + push**

```bash
git add -A
git commit -m "chore: bump 3.5.0-alpha.172.210 - F1 asset registry metadata-only + agent"
git push
```

---

## Self-review (fatto in scrittura)

- **Spec coverage F1**: modelli ✓(T1) migrazione ✓(T2, default server-side = backfill legacy) coda ✓(T3) proposta/conferma ✓(T4) blocco upload ✓(T5) agent api ✓(T6) admin+register-path ✓(T7) UI ✓(T8) demone ✓(T9) E2E ✓(T10).
- **Fuori F1 (esplicito)**: watch dirs (F2), match JobDeliverable (F2), preview (F3), LTO/MHL parse (F4), TransferOrder (F5), distruzione (F6). `watch_dirs` campo già nel modello: lo usa F2.
- **Type consistency**: `AgentJobType.probe` ovunque; `claim_next_job(db, agent)` firma uniforme; `create_proposal_from_probe(db, tenant_id, volume_id, probe, user_id, registered_via)` uniforme tra T4/T6.
- **Rischi noti per l'esecutore**: (1) import auth/templates in T7 da verificare su dam.py reale; (2) `xxhash` da aggiungere al venv; (3) riavvio server obbligatorio per template nuovi (OneDrive); (4) cache-buster `?v=` non serve (niente js statico nuovo).
