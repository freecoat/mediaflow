# F3 Preview QC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proxy di preview 1080p (TC burn-in + watermark) generato dall'agent in facility, caricato sul server (o S3 presigned), riprodotto nel modal QC di job_detail con bottone "📍 TC" che compila il timecode degli errori.

**Architecture:** Riusa la coda AgentJob (type `preview` già nell'enum). Il server decide la destinazione upload nel payload del job (server streaming PUT oppure S3 presigned PUT). Asset tiene stato+path+meta del preview (auto-migrate). Player servito da `app/routers/qc.py` (stesso modello auth degli endpoint QC). Spec: `docs/superpowers/specs/2026-06-11-f3-preview-qc-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + SQLite, agent stdlib+requests (ffmpeg via subprocess), starlette 0.52 (FileResponse con Range nativo), boto3 OPZIONALE (solo se S3 configurato), vanilla JS.

**Convenzioni progetto (vincolanti):** tenant filter su ogni query (`CURRENT_TENANT`/`current_tenant_id()`), POST/PUT Form-based (no JSON) per gli endpoint UI, soft-delete, migrazioni = auto-migrate colonne al boot in `app/main.py`, niente framework JS, helper in `static/js/global.js` (`api()`, `toast()`, `escapeHtml()`). Test: pattern fixture `client_admin` di `tests/test_storage_browse.py` (DB in-memory StaticPool + cookie JWT). Python: `.venv/Scripts/python` su Windows. NON importare `app.*` dentro `agent/`.

---

### Task 1: Modello — campi preview su Asset + auto_preview su StorageVolume

**Files:**
- Modify: `app/models/models.py` (Asset ~L3132, StorageVolume ~L3430)
- Modify: `app/main.py` (blocco auto-migrate: grep `matched_deliverable_id` per trovarlo)
- Test: `tests/test_f3_preview_model.py`

- [ ] **Step 1: Test failing**

```python
# tests/test_f3_preview_model.py
"""F3 (spec 2026-06-11) — campi preview su Asset + auto_preview su StorageVolume."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, Asset, StorageVolume


def _session():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_asset_preview_fields_default():
    db = _session()
    a = Asset(tenant_id=1, filename="x.mxf", original_filename="x.mxf",
              file_path="", file_size=1, mime_type="application/mxf")
    db.add(a); db.flush()
    assert a.preview_status == "none"
    assert a.preview_path is None
    assert a.preview_storage is None
    assert a.preview_error is None
    assert a.preview_meta is None
    assert a.preview_generated_at is None


def test_volume_auto_preview_default_false():
    db = _session()
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    db.add(v); db.flush()
    assert v.auto_preview is False
```

Nota: verificare i kwargs minimi richiesti da `Asset` leggendo il modello (alcuni campi
sono nullable, altri no) — adattare il costruttore del test ai NOT NULL reali.

- [ ] **Step 2: Run → FAIL** — `.venv/Scripts/python -m pytest tests/test_f3_preview_model.py -q` → AttributeError/TypeError.

- [ ] **Step 3: Implementazione**

In `Asset` (dopo i campi F2 `matched_deliverable_id` ecc.):

```python
    # F3 (spec 2026-06-11) — preview QC proxy
    preview_status: Mapped[str] = mapped_column(String(20), default="none",
                                                server_default="none")
    # none|queued|generating|ready|failed
    preview_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    preview_storage: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # local|s3
    preview_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preview_meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # {start_tc, fps, duration_sec, burned_tc: bool}
    preview_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

In `StorageVolume`:

```python
    auto_preview: Mapped[bool] = mapped_column(Boolean, default=False,
                                               server_default="0")
```

In `app/main.py`, nel blocco auto-migrate dove sono registrate le colonne F1/F2 di
`assets` (grep `matched_deliverable_id`), aggiungere con lo stesso pattern esistente:

```python
    ("assets", "preview_status", "VARCHAR(20) NOT NULL DEFAULT 'none'"),
    ("assets", "preview_path", "VARCHAR(500)"),
    ("assets", "preview_storage", "VARCHAR(10)"),
    ("assets", "preview_error", "TEXT"),
    ("assets", "preview_meta", "JSON"),
    ("assets", "preview_generated_at", "DATETIME"),
    ("storage_volumes", "auto_preview", "BOOLEAN NOT NULL DEFAULT 0"),
```

(adattare alla forma esatta del registry auto-migrate esistente — è una lista di tuple
o chiamate `_ensure_column`; copiare la forma delle righe F2 adiacenti).

- [ ] **Step 4: Run → PASS** — stesso comando.

- [ ] **Step 5: Commit** — `git add app/models/models.py app/main.py tests/test_f3_preview_model.py && git commit -m "feat(F3): campi preview su Asset + auto_preview su StorageVolume"`

---

### Task 2: Service server `asset_preview.py` — enqueue idempotente + esito job

**Files:**
- Create: `app/services/asset_preview.py`
- Test: `tests/test_f3_preview_service.py`

- [ ] **Step 1: Test failing**

```python
# tests/test_f3_preview_service.py
"""F3 — enqueue_preview idempotente + apply_preview_result."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (Base, Asset, StorageVolume, Tenant,
                               AgentJob, AgentJobType, AgentJobStatus)
from app.services.asset_preview import (enqueue_preview, apply_preview_result,
                                        s3_preview_config)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.flush()
    yield s
    s.close()


def _asset(db, **kw):
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    db.add(v); db.flush()
    a = Asset(tenant_id=1, filename="ep01.mxf", original_filename="ep01.mxf",
              file_path="", file_size=1, mime_type="application/mxf",
              storage_volume_id=v.id, rel_path="OUT/GLO/ep01.mxf", **kw)
    db.add(a); db.flush()
    return a


def test_enqueue_creates_job_and_sets_status(db, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _asset(db)
    job = enqueue_preview(db, a, requested_by_user_id=7)
    assert job.type == AgentJobType.preview
    assert job.payload["asset_id"] == a.id
    assert job.payload["rel_path"] == "OUT/GLO/ep01.mxf"
    assert job.payload["volume_id"] == a.storage_volume_id
    assert job.payload["upload"]["mode"] == "server"
    assert a.preview_status == "queued"


def test_enqueue_idempotent_while_pending(db, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _asset(db)
    j1 = enqueue_preview(db, a)
    j2 = enqueue_preview(db, a)
    assert j1.id == j2.id


def test_enqueue_again_after_failed(db, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _asset(db)
    j1 = enqueue_preview(db, a)
    j1.status = AgentJobStatus.failed
    a.preview_status = "failed"
    db.flush()
    j2 = enqueue_preview(db, a)
    assert j2.id != j1.id


def test_enqueue_requires_volume_and_relpath(db):
    a = _asset(db)
    a.rel_path = None
    with pytest.raises(ValueError):
        enqueue_preview(db, a)


def test_s3_config_none_without_env(monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    assert s3_preview_config() is None


def test_apply_result_ready(db, monkeypatch, tmp_path):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _asset(db)
    job = enqueue_preview(db, a)
    # simula upload già avvenuto: file locale presente
    f = tmp_path / "p.mp4"; f.write_bytes(b"00")
    a.preview_path = str(f); a.preview_storage = "local"
    apply_preview_result(db, job, {"start_tc": "10:00:00:00", "fps": 25.0,
                                   "duration_sec": 2.0, "burned_tc": True,
                                   "uploaded": "server"})
    assert a.preview_status == "ready"
    assert a.preview_meta["start_tc"] == "10:00:00:00"
    assert a.preview_generated_at is not None


def test_apply_result_failure_path(db, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _asset(db)
    job = enqueue_preview(db, a)
    apply_preview_failure(db, job, "ffmpeg non trovato")
    assert a.preview_status == "failed"
    assert "ffmpeg" in a.preview_error
```

(aggiungere `apply_preview_failure` all'import; adattare i NOT NULL di Asset come Task 1).

- [ ] **Step 2: Run → FAIL** (modulo inesistente).

- [ ] **Step 3: Implementazione**

```python
# app/services/asset_preview.py
"""F3 (spec 2026-06-11) — Preview QC: enqueue job agent + esiti.

Il server decide la destinazione upload nel payload del job:
- S3 configurato via env (PREVIEW_S3_BUCKET, PREVIEW_S3_REGION,
  PREVIEW_S3_ACCESS_KEY, PREVIEW_S3_SECRET_KEY, opz. PREVIEW_S3_ENDPOINT)
  → presigned PUT, l'agent carica diretto, il server non vede i byte.
- Altrimenti → l'agent streama il file a PUT /agent-api/jobs/{id}/preview-upload.

I byte del preview NON sono il master: proxy 1080p watermarked, accettato
dal design (decisione Matteo 11 giu 2026).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Asset, AgentJob, AgentJobStatus, AgentJobType
from app.services.agent_queue import enqueue_job
from app.services.clock import now_utc

PREVIEW_DIR = Path("./uploads/previews")


def s3_preview_config() -> Optional[dict]:
    bucket = os.environ.get("PREVIEW_S3_BUCKET")
    if not bucket:
        return None
    return {
        "bucket": bucket,
        "region": os.environ.get("PREVIEW_S3_REGION", "eu-south-1"),
        "access_key": os.environ.get("PREVIEW_S3_ACCESS_KEY", ""),
        "secret_key": os.environ.get("PREVIEW_S3_SECRET_KEY", ""),
        "endpoint": os.environ.get("PREVIEW_S3_ENDPOINT") or None,
    }


def _s3_client(cfg: dict):
    import boto3  # lazy: dipendenza opzionale
    return boto3.client(
        "s3", region_name=cfg["region"],
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        endpoint_url=cfg["endpoint"],
    )


def s3_key_for(asset: Asset) -> str:
    return f"previews/{asset.tenant_id}/{asset.id}.mp4"


def local_path_for(asset: Asset) -> Path:
    return PREVIEW_DIR / str(asset.tenant_id) / f"{asset.id}.mp4"


def _pending_preview_job(db: Session, asset: Asset) -> Optional[AgentJob]:
    jobs = db.execute(
        select(AgentJob).where(
            AgentJob.tenant_id == asset.tenant_id,
            AgentJob.type == AgentJobType.preview,
            AgentJob.status.in_([AgentJobStatus.queued, AgentJobStatus.claimed,
                                 AgentJobStatus.running]))
    ).scalars().all()
    for j in jobs:
        if (j.payload or {}).get("asset_id") == asset.id:
            return j
    return None


def enqueue_preview(db: Session, asset: Asset, *,
                    requested_by_user_id: Optional[int] = None) -> AgentJob:
    """Accoda la generazione preview. Idempotente finché un job è pending."""
    if not asset.storage_volume_id or not asset.rel_path:
        raise ValueError("asset senza volume/rel_path: serve un asset registrato via agent")
    existing = _pending_preview_job(db, asset)
    if existing is not None:
        return existing

    upload: dict = {"mode": "server"}
    cfg = s3_preview_config()
    if cfg is not None:
        try:
            key = s3_key_for(asset)
            put_url = _s3_client(cfg).generate_presigned_url(
                "put_object",
                Params={"Bucket": cfg["bucket"], "Key": key,
                        "ContentType": "video/mp4"},
                ExpiresIn=3600)
            upload = {"mode": "s3", "put_url": put_url, "key": key}
        except ImportError:
            # boto3 assente: degrada a upload server (config S3 ignorata)
            upload = {"mode": "server"}

    tenant_name = getattr(getattr(asset, "tenant", None), "name", None) or "Claqo"
    job = enqueue_job(db, tenant_id=asset.tenant_id, type=AgentJobType.preview,
                      payload={"volume_id": asset.storage_volume_id,
                               "rel_path": asset.rel_path,
                               "asset_id": asset.id,
                               "tenant_name": tenant_name,
                               "upload": upload},
                      requested_by_user_id=requested_by_user_id,
                      asset_id=asset.id)
    asset.preview_status = "queued"
    asset.preview_error = None
    db.flush()
    return job


def apply_preview_result(db: Session, job: AgentJob, result: dict) -> Asset:
    """Job preview done → aggiorna l'Asset (chiamato da process_job_result)."""
    asset = db.get(Asset, int((job.payload or {}).get("asset_id") or 0))
    if asset is None or asset.tenant_id != job.tenant_id:
        return None
    uploaded = (result or {}).get("uploaded")
    if uploaded == "s3":
        asset.preview_storage = "s3"
        asset.preview_path = (job.payload or {}).get("upload", {}).get("key")
    else:
        # upload server: il PUT preview-upload ha già scritto file+path
        asset.preview_storage = "local"
        if not asset.preview_path or not Path(asset.preview_path).is_file():
            asset.preview_status = "failed"
            asset.preview_error = "result done ma file preview non presente sul server"
            db.flush()
            return asset
    asset.preview_status = "ready"
    asset.preview_error = None
    asset.preview_meta = {k: result.get(k) for k in
                          ("start_tc", "fps", "duration_sec", "burned_tc")}
    asset.preview_generated_at = now_utc()
    db.flush()
    return asset


def apply_preview_failure(db: Session, job: AgentJob, error: str) -> Optional[Asset]:
    asset = db.get(Asset, int((job.payload or {}).get("asset_id") or 0))
    if asset is None:
        return None
    asset.preview_status = "failed"
    asset.preview_error = (error or "errore sconosciuto")[:2000]
    db.flush()
    return asset


def presigned_get_url(asset: Asset, *, expires: int = 900) -> str:
    cfg = s3_preview_config()
    if cfg is None:
        raise ValueError("S3 non configurato")
    return _s3_client(cfg).generate_presigned_url(
        "get_object",
        Params={"Bucket": cfg["bucket"], "Key": asset.preview_path},
        ExpiresIn=expires)
```

- [ ] **Step 4: Run → PASS** — `pytest tests/test_f3_preview_service.py -q`.

- [ ] **Step 5: Commit** — `feat(F3): service asset_preview — enqueue idempotente + esiti job`

---

### Task 3: Agent — `agent/preview.py` (ffmpeg) + branch in main.py + client.put_preview

**Files:**
- Create: `agent/preview.py`
- Modify: `agent/main.py` (branch job + CAPABILITIES)
- Modify: `agent/client.py` (put_preview streaming)
- Test: `tests/test_f3_agent_preview.py`

- [ ] **Step 1: Test failing** (solo parti pure: builder comando, TC, escaping)

```python
# tests/test_f3_agent_preview.py
"""F3 — builder ffmpeg agent-side (puro, nessuna esecuzione)."""
from agent.preview import build_ffmpeg_cmd, probe_start_tc


def test_probe_start_tc_from_format_tags():
    probe = {"format": {"tags": {"timecode": "09:59:50:00"}},
             "streams": [{"codec_type": "video", "r_frame_rate": "25/1"}]}
    tc, rate = probe_start_tc(probe)
    assert tc == "09:59:50:00"
    assert rate == "25/1"


def test_probe_start_tc_fallback():
    probe = {"format": {}, "streams": [{"codec_type": "video",
                                        "r_frame_rate": "24000/1001"}]}
    tc, rate = probe_start_tc(probe)
    assert tc == "00:00:00:00"
    assert rate == "24000/1001"


def test_build_cmd_has_scale_codec_faststart():
    cmd = build_ffmpeg_cmd("/in.mxf", "/out.mp4", start_tc="10:00:00:00",
                           rate="25/1", tenant_name="TPR", burn=True)
    s = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "/in.mxf" in cmd and "/out.mp4" in cmd
    assert "scale=-2:1080" in s
    assert "libx264" in s and "aac" in s and "+faststart" in s
    assert "-ac" in cmd  # stereo downmix


def test_build_cmd_tc_escaped_and_watermark():
    cmd = build_ffmpeg_cmd("/i", "/o", start_tc="10:00:00:00", rate="25/1",
                           tenant_name="TPR Berlin", burn=True)
    vf = cmd[cmd.index("-vf") + 1]
    assert r"10\:00\:00\:00" in vf
    assert "timecode_rate=25/1" in vf
    assert "PREVIEW" in vf and "TPR Berlin" in vf


def test_build_cmd_no_burn_has_no_drawtext():
    cmd = build_ffmpeg_cmd("/i", "/o", start_tc="00:00:00:00", rate="25/1",
                           tenant_name="X", burn=False)
    vf = cmd[cmd.index("-vf") + 1]
    assert "drawtext" not in vf
    assert "scale=-2:1080" in vf
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Implementazione**

```python
# agent/preview.py
"""Generazione proxy preview QC: ffmpeg 1080p + TC burn-in + watermark.

Nessun byte del master lascia la facility: esce solo il proxy watermarked,
verso il server Claqo o S3 (presigned), come deciso dal payload del job.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

from agent.probe import run_ffprobe


def probe_start_tc(probe: dict) -> tuple[str, str]:
    """(start_tc, rate) dal JSON ffprobe. Fallback 00:00:00:00 / 25/1."""
    tags = (probe.get("format") or {}).get("tags") or {}
    tc = tags.get("timecode")
    rate = "25/1"
    for s in probe.get("streams") or []:
        if s.get("codec_type") == "video":
            if not tc:
                tc = ((s.get("tags") or {}).get("timecode"))
            rate = s.get("r_frame_rate") or rate
            break
    return (tc or "00:00:00:00"), rate


def build_ffmpeg_cmd(src: str, dst: str, *, start_tc: str, rate: str,
                     tenant_name: str, burn: bool) -> list[str]:
    filters = ["scale=-2:1080"]
    if burn:
        tc_esc = start_tc.replace(":", r"\:")
        filters.append(
            f"drawtext=timecode='{tc_esc}':timecode_rate={rate}"
            ":fontsize=h/28:fontcolor=white:box=1:boxcolor=black@0.45"
            ":x=(w-tw)/2:y=h*0.03")
        wm = f"PREVIEW - QC ONLY - {tenant_name}".replace(":", r"\:").replace("'", "")
        filters.append(
            f"drawtext=text='{wm}'"
            ":fontsize=h/16:fontcolor=white@0.18:x=(w-tw)/2:y=(h-th)/2")
    return [
        "ffmpeg", "-y", "-i", src,
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-maxrate", "6M", "-bufsize", "12M",
        "-c:a", "aac", "-b:a", "192k", "-ac", "2",
        "-movflags", "+faststart",
        dst,
    ]


def generate_preview(mount_path: str, rel_path: str, tenant_name: str,
                     workdir: str) -> tuple[str, dict]:
    """Genera il proxy. Ritorna (path_mp4, meta). Solleva su errore ffmpeg."""
    src = os.path.join(mount_path, rel_path)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"sorgente non trovata: {src}")
    probe = run_ffprobe(src)
    start_tc, rate = probe_start_tc(probe)
    duration = None
    try:
        duration = float((probe.get("format") or {}).get("duration") or 0) or None
    except (TypeError, ValueError):
        pass
    dst = os.path.join(workdir, "preview.mp4")

    def _run(burn: bool):
        cmd = build_ffmpeg_cmd(src, dst, start_tc=start_tc, rate=rate,
                               tenant_name=tenant_name, burn=burn)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3600 * 4)

    out = _run(burn=True)
    burned = True
    if out.returncode != 0 and "drawtext" in (out.stderr or ""):
        # build ffmpeg senza fontconfig/freetype: riprova senza burn-in
        out = _run(burn=False)
        burned = False
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg rc={out.returncode}: {(out.stderr or '')[-800:]}")
    try:
        fps = eval_rate(rate)
    except Exception:
        fps = 25.0
    return dst, {"start_tc": start_tc, "fps": fps,
                 "duration_sec": duration, "burned_tc": burned}


def eval_rate(rate: str) -> float:
    num, _, den = rate.partition("/")
    return round(float(num) / float(den or 1), 3)


def upload_preview(path: str, *, job_id: int, upload_cfg: dict, client) -> str:
    """Carica il proxy. Ritorna 'server' o 's3' (per il result del job)."""
    mode = (upload_cfg or {}).get("mode") or "server"
    if mode == "s3":
        import requests
        with open(path, "rb") as fh:
            r = requests.put(upload_cfg["put_url"], data=fh,
                             headers={"Content-Type": "video/mp4"}, timeout=3600)
        r.raise_for_status()
        return "s3"
    client.put_preview(job_id, path)
    return "server"
```

In `agent/client.py` aggiungere (stesso stile dei metodi esistenti):

```python
    def put_preview(self, job_id: int, path: str):
        import os
        with open(path, "rb") as fh:
            r = self._s.put(
                f"{self.base}/agent-api/jobs/{job_id}/preview-upload",
                data=fh,
                headers={"X-Agent-Token": self.token,
                         "Content-Type": "video/mp4",
                         "Content-Length": str(os.path.getsize(path))},
                timeout=3600)
        r.raise_for_status()
        return r.json()
```

(verificare gli attributi reali del client leggendo `agent/client.py` — sessione/headers
potrebbero chiamarsi diversamente; replicare il pattern di `post_result`).

In `agent/main.py`:
- `CAPABILITIES = ["probe", "checksum", "scan", "browse", "preview"]`
- import: `from agent.preview import generate_preview, upload_preview`
- in `handle_job`, prima del ramo `scan` (serve `client` → cambiare firma:
  `handle_job(job, volumes_by_id, watch_states, client=None)` e aggiornare il call-site
  in `run()` passando `client`):

```python
        if jtype == "preview":
            import tempfile
            with tempfile.TemporaryDirectory() as wd:
                path, meta = generate_preview(vol["mount_path"], payload["rel_path"],
                                              payload.get("tenant_name") or "Claqo", wd)
                uploaded = upload_preview(path, job_id=job["id"],
                                          upload_cfg=payload.get("upload") or {},
                                          client=client)
            return "done", {**meta, "uploaded": uploaded}, None
```

ATTENZIONE retrocompat test esistenti: `handle_job` è chiamato nei test F2/E2E con 3
argomenti posizionali → il nuovo parametro DEVE essere keyword con default `None`.

- [ ] **Step 4: Run → PASS** — `pytest tests/test_f3_agent_preview.py tests/test_agent_watch.py -q` (verificare anche nessuna regressione agent).

- [ ] **Step 5: Commit** — `feat(F3): agent preview.py — ffmpeg 1080p TC burn-in + watermark + upload`

---

### Task 4: Endpoint upload streaming `PUT /agent-api/jobs/{id}/preview-upload`

**Files:**
- Modify: `app/routers/agent_api.py`
- Test: `tests/test_f3_preview_upload.py`

- [ ] **Step 1: Test failing**

```python
# tests/test_f3_preview_upload.py
"""F3 — upload streaming preview dall'agent."""
import pytest
from pathlib import Path

# riusare ESATTAMENTE la fixture client_admin di tests/test_storage_browse.py
# (copiarla qui; vedi quel file) + helper che crea volume+asset+agent+job preview.

from app.models.models import (AgentJob, AgentJobStatus, AgentJobType,
                               AgentNode, Asset, StorageVolume)
from app.services.agent_queue import generate_agent_token, hash_agent_token


def _setup(session):
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    session.add(v); session.flush()
    a = Asset(tenant_id=1, filename="e.mxf", original_filename="e.mxf",
              file_path="", file_size=1, mime_type="application/mxf",
              storage_volume_id=v.id, rel_path="OUT/e.mxf")
    session.add(a); session.flush()
    plain, h = generate_agent_token()
    ag = AgentNode(tenant_id=1, name="ag", auth_token_hash=h, is_active=True)
    session.add(ag); session.flush()
    job = AgentJob(tenant_id=1, type=AgentJobType.preview,
                   status=AgentJobStatus.claimed, agent_id=ag.id,
                   payload={"asset_id": a.id, "volume_id": v.id,
                            "rel_path": "OUT/e.mxf", "upload": {"mode": "server"}})
    session.add(job); session.commit()
    return plain, ag, job, a


def test_upload_writes_file_and_sets_path(client_admin, tmp_path, monkeypatch):
    import app.services.asset_preview as ap
    monkeypatch.setattr(ap, "PREVIEW_DIR", tmp_path)
    plain, ag, job, a = _setup(client_admin.session)
    r = client_admin.put(f"/agent-api/jobs/{job.id}/preview-upload",
                         content=b"FAKEMP4" * 100,
                         headers={"X-Agent-Token": plain})
    assert r.status_code == 200, r.text
    dest = tmp_path / "1" / f"{a.id}.mp4"
    assert dest.is_file() and dest.read_bytes().startswith(b"FAKEMP4")
    client_admin.session.expire_all()
    assert client_admin.session.get(Asset, a.id).preview_path == str(dest)


def test_upload_wrong_agent_404(client_admin, monkeypatch, tmp_path):
    import app.services.asset_preview as ap
    monkeypatch.setattr(ap, "PREVIEW_DIR", tmp_path)
    plain, ag, job, a = _setup(client_admin.session)
    plain2, h2 = generate_agent_token()
    other = AgentNode(tenant_id=1, name="ag2", auth_token_hash=h2, is_active=True)
    client_admin.session.add(other); client_admin.session.commit()
    r = client_admin.put(f"/agent-api/jobs/{job.id}/preview-upload",
                         content=b"x", headers={"X-Agent-Token": plain2})
    assert r.status_code == 404


def test_upload_cap_413(client_admin, monkeypatch, tmp_path):
    import app.services.asset_preview as ap
    monkeypatch.setattr(ap, "PREVIEW_DIR", tmp_path)
    monkeypatch.setenv("PREVIEW_MAX_GB", "0")  # cap zero → qualsiasi body sfora
    plain, ag, job, a = _setup(client_admin.session)
    r = client_admin.put(f"/agent-api/jobs/{job.id}/preview-upload",
                         content=b"x" * 1024,
                         headers={"X-Agent-Token": plain})
    assert r.status_code == 413
```

- [ ] **Step 2: Run → FAIL** (405/404).

- [ ] **Step 3: Implementazione** in `app/routers/agent_api.py`:

```python
import os
from pathlib import Path
from fastapi import Request

from app.models.models import Asset  # aggiungere all'import esistente
import app.services.asset_preview as asset_preview


@router.put("/jobs/{job_id}/preview-upload")
async def preview_upload(job_id: int, request: Request,
                         agent: AgentNode = Depends(get_agent),
                         db: Session = Depends(get_db)):
    """Riceve il proxy preview dall'agent in streaming (body raw).
    Scrittura atomica: .part poi rename. Cap PREVIEW_MAX_GB (default 20)."""
    job = db.get(AgentJob, job_id)
    if (job is None or job.tenant_id != agent.tenant_id
            or job.agent_id != agent.id or job.type != AgentJobType.preview):
        raise HTTPException(404, "job non trovato")
    asset = db.get(Asset, int((job.payload or {}).get("asset_id") or 0))
    if asset is None or asset.tenant_id != agent.tenant_id:
        raise HTTPException(404, "asset non trovato")

    cap = float(os.environ.get("PREVIEW_MAX_GB", "20")) * 1024 ** 3
    dest = asset_preview.local_path_for(asset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".mp4.part")
    written = 0
    try:
        with open(part, "wb") as fh:
            async for chunk in request.stream():
                written += len(chunk)
                if written > cap:
                    raise HTTPException(413, "preview oltre il limite PREVIEW_MAX_GB")
                fh.write(chunk)
        part.replace(dest)
    except HTTPException:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:
        part.unlink(missing_ok=True)
        raise HTTPException(500, f"scrittura preview fallita: {e}")

    asset.preview_path = str(dest)
    asset.preview_storage = "local"
    db.commit()
    return {"ok": True, "bytes": written}
```

NOTA `local_path_for` usa `PREVIEW_DIR` modulo-level: i test la monkeypatchano —
accedere SEMPRE via `asset_preview.local_path_for(...)` (mai import della costante).

- [ ] **Step 4: Run → PASS**.

- [ ] **Step 5: Commit** — `feat(F3): upload streaming preview da agent (atomico + cap)`

---

### Task 5: Esito job preview + endpoint player/status/generate in `qc.py`

**Files:**
- Modify: `app/routers/agent_api.py` (`process_job_result`: ramo preview)
- Modify: `app/routers/qc.py` (3 endpoint nuovi)
- Test: `tests/test_f3_preview_endpoints.py`

- [ ] **Step 1: Test failing**

```python
# tests/test_f3_preview_endpoints.py
"""F3 — process_job_result(preview) + player/status/generate."""
# fixture client_admin come Task 4 (admin ha edit_planning_all → copre il write gate
# di qc.py; aggiungere anche "view_finance" e "assign_resources" alle permissions
# della Role di fixture per coprire i read gate).

from app.models.models import Asset, AgentJob, AgentJobStatus, AgentJobType


def test_result_done_marks_ready(client_admin, monkeypatch, tmp_path):
    import app.services.asset_preview as ap
    monkeypatch.setattr(ap, "PREVIEW_DIR", tmp_path)
    plain, ag, job, a = _setup(client_admin.session)  # helper Task 4
    # upload prima del result (flusso reale)
    client_admin.put(f"/agent-api/jobs/{job.id}/preview-upload",
                     content=b"MP4", headers={"X-Agent-Token": plain})
    r = client_admin.post(f"/agent-api/jobs/{job.id}/result",
                          headers={"X-Agent-Token": plain},
                          json={"status": "done",
                                "result": {"start_tc": "10:00:00:00", "fps": 25.0,
                                           "duration_sec": 2.0, "burned_tc": True,
                                           "uploaded": "server"}})
    assert r.status_code == 200
    client_admin.session.expire_all()
    a2 = client_admin.session.get(Asset, a.id)
    assert a2.preview_status == "ready"
    assert a2.preview_meta["fps"] == 25.0


def test_result_failed_marks_failed(client_admin, monkeypatch, tmp_path):
    import app.services.asset_preview as ap
    monkeypatch.setattr(ap, "PREVIEW_DIR", tmp_path)
    plain, ag, job, a = _setup(client_admin.session)
    r = client_admin.post(f"/agent-api/jobs/{job.id}/result",
                          headers={"X-Agent-Token": plain},
                          json={"status": "failed", "error": "ffmpeg rc=1"})
    assert r.status_code == 200
    client_admin.session.expire_all()
    a2 = client_admin.session.get(Asset, a.id)
    assert a2.preview_status == "failed"
    assert "ffmpeg" in a2.preview_error


def test_player_serves_local_file_with_range(client_admin, monkeypatch, tmp_path):
    import app.services.asset_preview as ap
    monkeypatch.setattr(ap, "PREVIEW_DIR", tmp_path)
    plain, ag, job, a = _setup(client_admin.session)
    f = tmp_path / "1" / f"{a.id}.mp4"
    f.parent.mkdir(parents=True); f.write_bytes(b"0123456789")
    a.preview_status = "ready"; a.preview_path = str(f); a.preview_storage = "local"
    client_admin.session.commit()
    r = client_admin.get(f"/qc/api/assets/{a.id}/preview")
    assert r.status_code == 200
    r2 = client_admin.get(f"/qc/api/assets/{a.id}/preview",
                          headers={"Range": "bytes=2-5"})
    assert r2.status_code == 206
    assert r2.content == b"2345"


def test_player_404_when_not_ready(client_admin):
    plain, ag, job, a = _setup(client_admin.session)
    assert client_admin.get(f"/qc/api/assets/{a.id}/preview").status_code == 404


def test_status_and_generate(client_admin, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    plain, ag, job, a = _setup(client_admin.session)
    # _setup crea già un job claimed → generate è idempotente su quello
    r = client_admin.post(f"/qc/api/assets/{a.id}/preview/generate")
    assert r.status_code == 200
    assert r.json()["job_id"] == job.id
    s = client_admin.get(f"/qc/api/assets/{a.id}/preview/status").json()
    assert s["status"] in ("queued", "none")  # _setup non setta queued sull'asset
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Implementazione**

`agent_api.process_job_result` — dentro il ramo `status == "failed"` e dopo i rami probe/scan:

```python
    # in testa al ramo failed (prima del return None):
    if status == "failed":
        fail_job(db, job, error or "errore agent non specificato")
        if job.type == AgentJobType.preview:
            from app.services.asset_preview import apply_preview_failure
            apply_preview_failure(db, job, error or "")
        return None
    ...
    if job.type == AgentJobType.preview:
        from app.services.asset_preview import apply_preview_result
        return apply_preview_result(db, job, result)
```

`app/routers/qc.py` — replicare i gate esistenti del file (usare gli stessi helper
RBAC già usati dagli endpoint `/qc/api/deliverables/...`; leggerli nel file):

```python
from pathlib import Path
from fastapi.responses import FileResponse, RedirectResponse

from app.models.models import Asset
from app.services.asset_preview import (enqueue_preview, presigned_get_url,
                                        s3_preview_config)


def _asset_or_404(db: Session, asset_id: int) -> Asset:
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != current_tenant_id():
        raise HTTPException(404, "Asset non trovato")
    return a


@router.get("/api/assets/{asset_id}/preview/status")
def preview_status(asset_id: int, request: Request, db: Session = Depends(get_db)):
    # stesso gate read degli endpoint /qc/api/deliverables/{id}/events
    a = _asset_or_404(db, asset_id)
    return {"status": a.preview_status or "none",
            "error": a.preview_error,
            "meta": a.preview_meta,
            "generated_at": (a.preview_generated_at.isoformat()
                             if a.preview_generated_at else None)}


@router.post("/api/assets/{asset_id}/preview/generate")
def preview_generate(asset_id: int, request: Request, db: Session = Depends(get_db)):
    # stesso gate write degli endpoint /qc/api/deliverables/{id}/log-event
    a = _asset_or_404(db, asset_id)
    try:
        job = enqueue_preview(db, a, requested_by_user_id=None)  # user da request come gli altri endpoint qc.py
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"ok": True, "job_id": job.id, "status": a.preview_status}


@router.get("/api/assets/{asset_id}/preview")
def preview_bytes(asset_id: int, request: Request, db: Session = Depends(get_db)):
    a = _asset_or_404(db, asset_id)
    if a.preview_status != "ready" or not a.preview_path:
        raise HTTPException(404, "preview non disponibile")
    if a.preview_storage == "s3":
        return RedirectResponse(presigned_get_url(a), status_code=302)
    p = Path(a.preview_path)
    if not p.is_file():
        raise HTTPException(404, "file preview mancante sul server")
    return FileResponse(p, media_type="video/mp4")  # starlette ≥0.41: Range nativo
```

(passare `requested_by_user_id` reale usando lo stesso meccanismo user degli altri
endpoint di qc.py — leggere il file e replicare.)

- [ ] **Step 4: Run → PASS** + suite agent: `pytest tests/test_f3_preview_endpoints.py tests/test_agent_api.py -q`.

- [ ] **Step 5: Commit** — `feat(F3): esito job preview + player/status/generate in /qc`

---

### Task 6: auto_preview — Form volume + auto-trigger alla conferma

**Files:**
- Modify: `app/routers/storage_admin.py` (create_volume, update_volume, list_volumes, confirm ~L317)
- Modify: `app/templates/pages/storage.html` (checkbox nv/ev + dataset)
- Test: `tests/test_f3_auto_preview.py`

- [ ] **Step 1: Test failing**

```python
# tests/test_f3_auto_preview.py
"""F3 — auto-trigger preview alla conferma proposta (volume.auto_preview)."""
# fixture client_admin come Task 4.
from sqlalchemy import select
from app.models.models import (AgentJob, AgentJobType, Asset,
                               AssetProposedState, StorageVolume)


def _proposal(session, auto: bool):
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san",
                      auto_preview=auto)
    session.add(v); session.flush()
    a = Asset(tenant_id=1, filename="e.mxf", original_filename="e.mxf",
              file_path="", file_size=1, mime_type="application/mxf",
              storage_volume_id=v.id, rel_path="OUT/e.mxf",
              proposed_state=AssetProposedState.pending_review)
    session.add(a); session.commit()
    return a


def test_confirm_enqueues_preview_when_auto(client_admin, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _proposal(client_admin.session, auto=True)
    r = client_admin.post(f"/storage/api/proposals/{a.id}/confirm", data={})
    assert r.status_code == 200
    jobs = client_admin.session.execute(
        select(AgentJob).where(AgentJob.type == AgentJobType.preview)
    ).scalars().all()
    assert len(jobs) == 1 and jobs[0].payload["asset_id"] == a.id


def test_confirm_no_preview_when_flag_off(client_admin, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _proposal(client_admin.session, auto=False)
    client_admin.post(f"/storage/api/proposals/{a.id}/confirm", data={})
    jobs = client_admin.session.execute(
        select(AgentJob).where(AgentJob.type == AgentJobType.preview)
    ).scalars().all()
    assert jobs == []


def test_volume_form_roundtrip_auto_preview(client_admin):
    r = client_admin.post("/storage/api/volumes",
                          data={"name": "V", "mount_path": "/m",
                                "auto_preview": "true"})
    vid = r.json()["id"]
    vols = client_admin.get("/storage/api/volumes").json()
    me = [v for v in vols if v["id"] == vid][0]
    assert me["auto_preview"] is True
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Implementazione**

`storage_admin.py`:
- `create_volume`/`update_volume`: param `auto_preview: bool = Form(False)` → set su modello.
- `list_volumes` serializer: `"auto_preview": v.auto_preview,`.
- `confirm` (dopo `link_deliverable_on_confirm`):

```python
    vol = db.get(StorageVolume, a.storage_volume_id) if a.storage_volume_id else None
    if vol is not None and vol.auto_preview:
        from app.services.asset_preview import enqueue_preview
        try:
            enqueue_preview(db, a, requested_by_user_id=getattr(user, "id", None))
        except ValueError:
            pass  # asset senza rel_path (upload manuale): nessun preview possibile
```

`storage.html`: checkbox "Auto-preview alla conferma" in modal nuovo/modifica volume
(stesso markup dei checkbox `nv-readonly`/`ev-readonly`, id `nv-autopreview`/`ev-autopreview`),
append nei FormData di `createVolume()`/`saveVolume()`
(`fd.append('auto_preview', el.checked ? 'true' : 'false')`), dataset
`data-vol-autopreview` in `loadVolumes()` + ripristino in `editVolumeFromBtn()`,
reset checkbox in `createVolume()` post-successo.

- [ ] **Step 4: Run → PASS** + `pytest tests/test_f2_confirm.py -q` (no regressioni confirm).

- [ ] **Step 5: Commit** — `feat(F3): auto_preview per-volume + trigger alla conferma proposta`

---

### Task 7: UI — player nel modal QC + bottone 📍 TC

**Files:**
- Modify: `app/templates/pages/job_detail.html` (modal QC: grep `jdOpenQcModal` ~L1107 e il markup del modal che apre)
- Test: smoke browser (Task 8) — niente pytest per JS

- [ ] **Step 1: Leggere il modal QC** in job_detail.html: individuare (a) il div del modal
  aperto da `jdOpenQcModal`, (b) il punto dove il JS ha il deliverable corrente
  (serializer espone `digital_asset_id`, jobs.py L605), (c) il campo timecode del form
  log-errore (grep `timecode` dentro il blocco QC).

- [ ] **Step 2: Markup player** — in testa al body del modal QC:

```html
<div id="jdqc-preview-wrap" style="display:none;margin-bottom:12px;">
  <video id="jdqc-player" controls preload="metadata"
         style="width:100%;max-height:420px;background:#000;border-radius:8px;"></video>
  <div id="jdqc-preview-meta" class="form-hint" style="margin-top:4px;"></div>
</div>
<div id="jdqc-preview-cta" style="display:none;margin-bottom:12px;">
  <button class="btn btn-secondary btn-sm" id="jdqc-preview-btn"
          onclick="jdQcGeneratePreview()">🎬 Genera preview</button>
  <span id="jdqc-preview-status" class="form-hint"></span>
</div>
```

- [ ] **Step 3: JS** — nello script di job_detail.html:

```javascript
let _jdQcAssetId = null, _jdQcPreviewMeta = null, _jdQcPreviewPoll = null;

async function jdQcInitPreview(deliverable) {
  _jdQcAssetId = deliverable.digital_asset_id || null;
  _jdQcPreviewMeta = null;
  if (_jdQcPreviewPoll) { clearTimeout(_jdQcPreviewPoll); _jdQcPreviewPoll = null; }
  const wrap = document.getElementById('jdqc-preview-wrap');
  const cta = document.getElementById('jdqc-preview-cta');
  wrap.style.display = 'none'; cta.style.display = 'none';
  if (!_jdQcAssetId) return;   // nessun asset digitale linkato: niente preview
  await jdQcRefreshPreview();
}

async function jdQcRefreshPreview() {
  if (!_jdQcAssetId) return;
  let s;
  try { s = await api('GET', '/qc/api/assets/' + _jdQcAssetId + '/preview/status'); }
  catch (e) { return; }
  const wrap = document.getElementById('jdqc-preview-wrap');
  const cta = document.getElementById('jdqc-preview-cta');
  const lbl = document.getElementById('jdqc-preview-status');
  const btn = document.getElementById('jdqc-preview-btn');
  if (s.status === 'ready') {
    _jdQcPreviewMeta = s.meta || {};
    wrap.style.display = ''; cta.style.display = '';
    btn.textContent = '🔁 Rigenera preview';
    lbl.textContent = '';
    const player = document.getElementById('jdqc-player');
    const src = '/qc/api/assets/' + _jdQcAssetId + '/preview';
    if (!player.src || player.src.indexOf(src) === -1) player.src = src;
    document.getElementById('jdqc-preview-meta').innerHTML =
      (_jdQcPreviewMeta.start_tc ? 'TC start ' + escapeHtml(_jdQcPreviewMeta.start_tc) + ' · ' : '')
      + (_jdQcPreviewMeta.fps ? escapeHtml(String(_jdQcPreviewMeta.fps)) + ' fps · ' : '')
      + (_jdQcPreviewMeta.burned_tc === false ? '⚠ TC non bruciato (ffmpeg senza drawtext) · ' : '')
      + 'proxy 1080p watermarked';
  } else if (s.status === 'queued' || s.status === 'generating') {
    cta.style.display = '';
    btn.disabled = true;
    lbl.textContent = '⏳ Generazione in corso (agent)…';
    _jdQcPreviewPoll = setTimeout(jdQcRefreshPreview, 4000);
  } else {
    cta.style.display = '';
    btn.disabled = false;
    btn.textContent = '🎬 Genera preview';
    lbl.textContent = s.status === 'failed'
      ? '❌ ' + (s.error || 'generazione fallita') : '';
  }
}

async function jdQcGeneratePreview() {
  if (!_jdQcAssetId) return;
  try {
    await api('POST', '/qc/api/assets/' + _jdQcAssetId + '/preview/generate');
    toast('Preview accodata — la genera l\'agent in facility', 'success');
    jdQcRefreshPreview();
  } catch (e) { toast('Errore: ' + e.message, 'error'); }
}

function jdQcTcFromPlayer() {
  const player = document.getElementById('jdqc-player');
  if (!player || !player.duration) { toast('Player non attivo', 'error'); return; }
  const fps = (_jdQcPreviewMeta && _jdQcPreviewMeta.fps) || 25;
  const fpsInt = Math.round(fps);
  const startTc = (_jdQcPreviewMeta && _jdQcPreviewMeta.start_tc) || '00:00:00:00';
  const p = startTc.split(/[:;]/).map(Number);
  const startFrames = ((p[0] * 60 + p[1]) * 60 + p[2]) * fpsInt + (p[3] || 0);
  const total = startFrames + Math.round(player.currentTime * fps);
  const ff = total % fpsInt;
  const ss = Math.floor(total / fpsInt) % 60;
  const mm = Math.floor(total / (fpsInt * 60)) % 60;
  const hh = Math.floor(total / (fpsInt * 3600)) % 24;
  const pad = n => String(n).padStart(2, '0');
  const tc = pad(hh) + ':' + pad(mm) + ':' + pad(ss) + ':' + pad(ff);
  const field = document.getElementById('<ID-CAMPO-TC-ERRORI>');  // sostituire con l'id reale trovato allo Step 1
  if (field) { field.value = tc; field.dispatchEvent(new Event('input')); }
  toast('TC ' + tc, 'success', 1500);
}
```

Bottone accanto al campo timecode del form errori:
`<button class="btn btn-ghost btn-sm" type="button" onclick="jdQcTcFromPlayer()" title="Prendi il TC corrente dal player">📍 TC</button>`

Chiamare `jdQcInitPreview(deliverable)` dentro `jdOpenQcModal` appena il deliverable
è disponibile (il modal carica i dati via api — agganciarsi lì). Alla chiusura del
modal: `clearTimeout(_jdQcPreviewPoll)` + `player.pause()` (agganciare alla close
esistente del modal QC).

VINCOLI (memorie progetto): niente Jinja literal nei commenti JS; usare escapeHtml
di global.js (mai ridefinirlo); niente JSON.stringify in onclick (usare data-* o
variabili modulo come sopra).

- [ ] **Step 4: Verifica render** — `python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('pages/job_detail.html'); print('OK')"` + grep che ogni funzione `jdQc*` referenziata sia definita.

- [ ] **Step 5: Commit** — `feat(F3): player preview + 📍 TC nel modal QC`

---

### Task 8: E2E + bump versione + docs

**Files:**
- Create: `tools/_e2e_f3.py`
- Modify: `app/main.py` (version → `3.5.0-alpha.172.213`), `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: E2E** — `tools/_e2e_f3.py` sul modello di `tools/_e2e_browse_zip.py`
  (stesso harness TestClient + agent vero):
  1. Se `shutil.which('ffmpeg')` è None → print "SKIP (no ffmpeg)" ed exit 0.
  2. Genera clip sintetica in tmp: `ffmpeg -y -f lavfi -i testsrc=duration=2:size=640x360:rate=25 -f lavfi -i sine=frequency=440:duration=2 -c:v libx264 -c:a aac -timecode 10:00:00:00 clip.mp4`.
  3. Setup volume (mount=tmp) + agent + Asset row con rel_path=clip.mp4 (insert diretto in session come nei test).
  4. monkeypatch `asset_preview.PREVIEW_DIR` su tmp (o env) — N.B. nello script basta assegnare `ap.PREVIEW_DIR = Path(tmp)/'previews'`.
  5. `POST /qc/api/assets/{id}/preview/generate` → claim → `handle_job` vero (con client wrapper che fa PUT preview-upload via TestClient: passare un piccolo adapter `client` con metodo `put_preview` che usa TestClient) → post result.
  6. Check: asset ready, file mp4 esistente >0 byte, `GET /qc/api/assets/{id}/preview` 200 + Range 206, status JSON meta.start_tc == "10:00:00:00" (ffprobe della clip riporta il timecode).
  7. Check negativo: secondo generate dopo ready → nuovo job (rigenerazione consentita).
- [ ] **Step 2: Run E2E** — `PYTHONIOENCODING=utf-8 .venv/Scripts/python tools/_e2e_f3.py` → tutti i check verdi (su questa macchina ffmpeg c'è? verificare; se assente, lo script skippa e lo smoke si fa con mock — segnalarlo nel report).
- [ ] **Step 3: Suite completa** — `.venv/Scripts/python -m pytest tests/ -q` → 0 failed.
- [ ] **Step 4: Bump** — `app/main.py` version `3.5.0-alpha.172.213`; CHANGELOG entry F3 (formato delle entry precedenti); STATO.md sezione α.172.213 + "Prossimo".
- [ ] **Step 5: Commit + push** — commit bump, `graphify update .`, export DB ZIP in docs/ (pattern: `build_export_zip` come fatto per α.172.212), push origin main.

---

## Self-review (fatto)

- Spec coverage: storage local+S3 (T2/T4/T5), proxy 1080p TC+watermark (T3), trigger manuale+auto (T5/T6), player solo modal QC (T7), sicurezza upload/player (T4/T5), E2E (T8). ✔
- Tipi coerenti: `preview_status` stringa semplice (no enum DB — coerente con altri stati F1), `preview_meta` JSON, `apply_preview_result/failure` firme uniformi. ✔
- Niente placeholder salvo `<ID-CAMPO-TC-ERRORI>` che è una RICERCA OBBLIGATORIA dello Step 1 del Task 7 (il campo esiste già nel form QC).
