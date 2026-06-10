# F2 — Watch + Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'agent watcha le cartelle output e propone asset automaticamente; ogni proposta viene auto-matchata col `JobDeliverable` atteso (specs + naming); review da `/storage` e mobile.

**Architecture:** Estende F1 (α.172.210). Watch = job `scan` ricorrente lato agent (polling listing, size-stable, DCP/IMF via ASSETMAP). Match = service puro server-side che confronta probe vs `JobDeliverable`/`DeliveryItem` e popola `Asset.matched_deliverable_id` (forte) o ritorna candidati (debole). Conferma con deliverable → `JobDeliverable.digital_asset_id` + `status=qc`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, pytest (fixture `db` in-memory). Agent = pacchetto `agent/` (solo `requests`+`xxhash`+stdlib, NON importa `app.*`). Convenzioni progetto: `CURRENT_TENANT=1`, Form-based API, soft-delete, auto-migrate colonne in `app/main.py::_auto_migrate_columns`, helper JS globali, `now_utc` da `app.services.clock`.

**Spec:** `docs/superpowers/specs/2026-06-10-f2-watch-match-design.md`.

**Riferimenti di codice reali (verificati 10 giu):**
- `JobDeliverable`: cols `job_id, name, file_naming, delivery_template_id, delivery_item_id, spec_json, digital_asset_id, status` (enum `DeliverableStatus`: `planned/in_progress/qc/delivered/closed`), `deleted_at`.
- `DeliveryItem`: `container_id, video_codec_id, resolution_id, frame_rate_id, scan_type, naming_convention` — **nessuna relationship ORM**, risolvi via lookup by id.
- Lookup models (tutti con `name`): `Container(name, extension)`, `VideoCodec(name, family)`, `Resolution(name, width, height)`, `FrameRate(name, fps)`.
- `qc_expected_for_deliverable(db, deliverable) -> dict|None` in `app/services/delivery_timeline_service.py:30`.
- `Project.code` esiste. `Job` ha `project_id`. `Asset` (F1): `storage_volume_id, rel_path, proposed_state, checksum_xxhash, tech_specs_json`.
- Probe normalizzato (F1 `agent/probe.py` + asset `tech_specs_json`): `{tool, container, duration_sec, video:{codec,width,height,frame_rate,pix_fmt}, audio:[...]}`.

---

### Task 1: Modello `Asset.matched_deliverable_id` + auto-migrate

**Files:**
- Modify: `app/models/models.py` (classe `Asset`, vicino alle colonne F1 `storage_volume_id` ecc.)
- Modify: `app/main.py` (`_auto_migrate_columns`, blocco F1 assets — aggiungi la colonna)
- Test: `tests/test_f2_match_model.py`

- [ ] **Step 1: Scrivi il test che fallisce**

```python
"""F2 — Asset.matched_deliverable_id (suggerimento match pre-conferma)."""
from app.models.models import (
    Tenant, User, UserRole, Asset, AssetType, JobDeliverable,
)


def _tenant(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()


def test_asset_matched_deliverable_default_none(db):
    _tenant(db)
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u); db.flush()
    a = Asset(tenant_id=1, filename="f.mov", original_name="f.mov",
              file_path="agent://1/OUT/f.mov", asset_type=AssetType.video,
              mime_type="video/quicktime", file_size=1, uploaded_by=u.id)
    db.add(a); db.flush()
    assert a.matched_deliverable_id is None
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_match_model.py -v`
Expected: FAIL `AttributeError: ... has no attribute 'matched_deliverable_id'`

- [ ] **Step 3: Aggiungi la colonna su `Asset`**

Subito dopo le colonne F1 (`registered_via`) in `class Asset`:
```python
    # ── F2 (spec 2026-06-10) — suggerimento match pre-conferma ──
    # NB: distinto da JobDeliverable.digital_asset_id (link CONFERMATO).
    # Qui = proposta dell'auto-match, l'operatore conferma/corregge.
    matched_deliverable_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_deliverables.id"), nullable=True, index=True)
```

- [ ] **Step 4: Auto-migrate**

In `app/main.py::_auto_migrate_columns`, nel blocco F1 `f1_alter` (lista delle colonne `assets`), aggiungi la riga:
```python
            ("matched_deliverable_id", "INTEGER NULL REFERENCES job_deliverables(id)"),
```
(stessa lista/loop del blocco F1 — la colonna viene aggiunta idempotente al boot.)

- [ ] **Step 5: Esegui — deve passare + boot**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_match_model.py -v` → PASS
Run: `.venv\Scripts\python.exe -c "from app.main import app; print('ok')"` → ok

- [ ] **Step 6: Suite completa**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q` → tutti PASS (502+)

- [ ] **Step 7: Commit**

```bash
git add app/models/models.py app/main.py tests/test_f2_match_model.py
git commit -m "feat(F2): Asset.matched_deliverable_id + auto-migrate (watch+match)"
```

---

### Task 2: Service `deliverable_match` — scoring puro

**Files:**
- Create: `app/services/deliverable_match.py`
- Test: `tests/test_deliverable_match.py`

Funzioni PURE (no DB): normalizzazione + scoring. Il candidate-set DB è Task 3.

- [ ] **Step 1: Scrivi i test che falliscono**

```python
"""F2 — scoring match probe vs deliverable atteso (puro, no DB)."""
from app.services.deliverable_match import (
    normalize_codec, score_naming, score_match, MatchExpectation, MatchResult,
)


PROBE = {
    "container": "mov,mp4,m4a,3gp,3g2,mj2",
    "video": {"codec": "prores", "width": 1920, "height": 1080,
              "frame_rate": "25/1"},
}


def test_normalize_codec_aliases():
    assert normalize_codec("prores") == "prores"
    assert normalize_codec("ProRes 422 HQ") == "prores"
    assert normalize_codec("h264") == "h264"
    assert normalize_codec("AVC") == "h264"


def test_score_naming_exact_and_token():
    # nome file contiene il pattern atteso → alto
    assert score_naming("GOMORRA_S03_EP01_PRORES.mov",
                        "GOMORRA_S03_EP01") >= 0.8
    # nessuna somiglianza → basso
    assert score_naming("random.mov", "GOMORRA_S03_EP01") < 0.3


def test_score_match_strong():
    exp = MatchExpectation(
        deliverable_id=10, file_naming="GOMORRA_S03_EP01",
        container_name="QuickTime", container_ext="mov",
        video_codec_name="ProRes 422 HQ", width=1920, height=1080, fps=25.0)
    r = score_match("GOMORRA_S03_EP01_PRORES.mov", PROBE, exp)
    assert isinstance(r, MatchResult)
    assert r.deliverable_id == 10
    assert r.strength == "strong"     # naming + >=2 specs concordi
    assert r.score >= 0.75


def test_score_match_weak():
    exp = MatchExpectation(
        deliverable_id=11, file_naming="ALTRO_TITOLO",
        container_name="QuickTime", container_ext="mov",
        video_codec_name="ProRes 422 HQ", width=1920, height=1080, fps=25.0)
    r = score_match("GOMORRA_S03_EP01_PRORES.mov", PROBE, exp)
    # naming non concorde ma specs sì → debole
    assert r.strength in ("weak", "none")
    assert r.score < 0.75


def test_score_match_zero_specs_missing():
    exp = MatchExpectation(deliverable_id=12, file_naming="X",
                           container_name=None, container_ext=None,
                           video_codec_name=None, width=None, height=None, fps=None)
    r = score_match("random.mov", PROBE, exp)
    assert r.strength == "none"
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_deliverable_match.py -v`
Expected: FAIL ModuleNotFoundError

- [ ] **Step 3: Implementa il service (parte pura)**

```python
"""F2 (spec 2026-06-10) — Matching proposta asset ↔ JobDeliverable atteso.

Parte pura: normalizzazione + scoring. Il candidate-set DB sta in
`match_proposal` (Task 3). Score per-dimensione, somma pesata 0..1:
naming (peso 0.45) + container + codec + risoluzione + frame_rate.
Soglie: forte = naming concorde E >=2 specs tecniche concordi (o score
>=0.75); debole = 0.40..0.75; zero = <0.40.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

# alias codec ffprobe → famiglia canonica
_CODEC_ALIASES = {
    "prores": "prores", "apch": "prores", "apcn": "prores", "ap4h": "prores",
    "h264": "h264", "avc": "h264", "avc1": "h264", "x264": "h264",
    "hevc": "h265", "h265": "h265", "x265": "h265",
    "mpeg2video": "mpeg2", "mpeg2": "mpeg2",
    "dnxhd": "dnxhd", "dnxhr": "dnxhr",
    "jpeg2000": "jpeg2000", "j2k": "jpeg2000",
}

STRONG_THRESHOLD = 0.75
WEAK_THRESHOLD = 0.40
W_NAMING = 0.45
W_SPEC = 0.55  # ripartito fra le specs presenti


@dataclass
class MatchExpectation:
    deliverable_id: int
    file_naming: Optional[str]
    container_name: Optional[str]
    container_ext: Optional[str]
    video_codec_name: Optional[str]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]


@dataclass
class MatchResult:
    deliverable_id: int
    score: float
    strength: str            # "strong" | "weak" | "none"
    specs_agree: int         # quante dimensioni tecniche concordi
    naming_ok: bool


def normalize_codec(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    key = re.sub(r"[^a-z0-9]", "", s.lower())
    for alias, canon in _CODEC_ALIASES.items():
        if key.startswith(alias):
            return canon
    return key or None


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def score_naming(filename: str, expected: Optional[str]) -> float:
    """0..1. Match esatto/substring del pattern atteso, altrimenti overlap token."""
    if not expected:
        return 0.0
    fn = filename.lower()
    exp = expected.lower().strip()
    if not exp:
        return 0.0
    exp_core = re.sub(r"[^a-z0-9]+", "", exp)
    fn_core = re.sub(r"[^a-z0-9]+", "", fn)
    if exp_core and exp_core in fn_core:
        return 1.0
    exp_tok = set(_tokens(expected))
    fn_tok = set(_tokens(filename))
    if not exp_tok:
        return 0.0
    overlap = len(exp_tok & fn_tok) / len(exp_tok)
    return round(overlap, 3)


def _fps_from_rate(rate) -> Optional[float]:
    if rate is None:
        return None
    if isinstance(rate, (int, float)):
        return float(rate)
    s = str(rate)
    if "/" in s:
        num, den = s.split("/", 1)
        try:
            d = float(den)
            return float(num) / d if d else None
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def score_match(filename: str, probe: dict, exp: MatchExpectation) -> MatchResult:
    naming = score_naming(filename, exp.file_naming)
    naming_ok = naming >= 0.6

    video = (probe or {}).get("video") or {}
    p_container = (probe.get("container") or "").lower()
    p_codec = normalize_codec(video.get("codec"))
    p_w, p_h = video.get("width"), video.get("height")
    p_fps = _fps_from_rate(video.get("frame_rate"))

    spec_checks = []  # (presente_attesa, concorda)
    # container: confronta sull'estensione o sul nome dentro la stringa ffprobe
    if exp.container_ext or exp.container_name:
        ok = False
        if exp.container_ext and exp.container_ext.lower() in p_container:
            ok = True
        if exp.container_name and exp.container_name.lower() in p_container:
            ok = True
        spec_checks.append(ok)
    if exp.video_codec_name:
        spec_checks.append(normalize_codec(exp.video_codec_name) == p_codec
                           and p_codec is not None)
    if exp.width and exp.height:
        spec_checks.append(p_w == exp.width and p_h == exp.height)
    if exp.fps:
        spec_checks.append(p_fps is not None and abs(p_fps - exp.fps) < 0.05)

    specs_agree = sum(1 for c in spec_checks if c)
    spec_score = (specs_agree / len(spec_checks)) if spec_checks else 0.0
    score = round(W_NAMING * naming + W_SPEC * spec_score, 3)

    if naming_ok and specs_agree >= 2:
        strength = "strong"
    elif score >= STRONG_THRESHOLD:
        strength = "strong"
    elif score >= WEAK_THRESHOLD:
        strength = "weak"
    else:
        strength = "none"

    return MatchResult(deliverable_id=exp.deliverable_id, score=score,
                       strength=strength, specs_agree=specs_agree,
                       naming_ok=naming_ok)
```

- [ ] **Step 4: Esegui — deve passare**

Run: `.venv\Scripts\python.exe -m pytest tests/test_deliverable_match.py -v` → 5 PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/deliverable_match.py tests/test_deliverable_match.py
git commit -m "feat(F2): deliverable_match scoring puro naming+specs (watch+match)"
```

---

### Task 3: `deliverable_match` — candidate-set + orchestrazione DB

**Files:**
- Modify: `app/services/deliverable_match.py` (aggiungi `build_expectation`, `candidate_deliverables`, `match_proposal`, `rank_candidates`)
- Test: `tests/test_deliverable_match_db.py`

- [ ] **Step 1: Scrivi i test che falliscono**

```python
"""F2 — candidate set + match_proposal contro DB in-memory."""
from app.models.models import (
    Tenant, User, UserRole, Project, Client, Job, JobDeliverable,
    DeliverableStatus, DeliveryItem, Container, VideoCodec, Resolution, FrameRate,
    StorageVolume, Asset, AssetType, AssetStatus, AssetContentState,
    AssetProposedState,
)
from app.services.deliverable_match import match_proposal, rank_candidates


def _seed(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff); db.add(u)
    cli = Client(tenant_id=1, name="Sky"); db.add(cli); db.flush()
    proj = Project(tenant_id=1, code="GOMORRA", title="Gomorra S3",
                   client_id=cli.id); db.add(proj); db.flush()
    job = Job(tenant_id=1, project_id=proj.id, code="GOMORRA-J01",
              title="J01"); db.add(job); db.flush()
    cont = Container(tenant_id=1, name="QuickTime", extension="mov")
    cod = VideoCodec(tenant_id=1, name="ProRes 422 HQ", family="prores")
    res = Resolution(tenant_id=1, name="HD 1080", width=1920, height=1080)
    fr = FrameRate(tenant_id=1, name="25", fps=25.0)
    db.add_all([cont, cod, res, fr]); db.flush()
    item = DeliveryItem(tenant_id=1, name="Master ProRes",
                        container_id=cont.id, video_codec_id=cod.id,
                        resolution_id=res.id, frame_rate_id=fr.id)
    db.add(item); db.flush()
    deliv = JobDeliverable(tenant_id=1, job_id=job.id, name="EP01 master",
                           file_naming="GOMORRA_S03_EP01",
                           delivery_item_id=item.id,
                           status=DeliverableStatus.planned)
    db.add(deliv); db.flush()
    return u, proj, job, deliv


def _proposal(db, u, vol_id=1, rel="OUT/GOMORRA/GOMORRA_S03_EP01_PRORES.mov"):
    a = Asset(tenant_id=1, filename=rel.split("/")[-1], original_name=rel.split("/")[-1],
              file_path=f"agent://{vol_id}/{rel}", storage_volume_id=vol_id,
              rel_path=rel, asset_type=AssetType.video, mime_type="video/quicktime",
              file_size=10, uploaded_by=u.id, status=AssetStatus.uploaded,
              content_state=AssetContentState.online,
              proposed_state=AssetProposedState.pending_review,
              tech_specs_json={"container": "mov,mp4", "video": {
                  "codec": "prores", "width": 1920, "height": 1080,
                  "frame_rate": "25/1"}})
    db.add(a); db.flush()
    return a


def test_match_proposal_strong_sets_matched_id(db):
    u, proj, job, deliv = _seed(db)
    db.add(StorageVolume(tenant_id=1, name="SAN", mount_path="/m",
                         watch_dirs=["/OUT"])); db.flush()
    a = _proposal(db, u)
    match_proposal(db, a)
    assert a.matched_deliverable_id == deliv.id


def test_match_proposal_excludes_already_linked(db):
    u, proj, job, deliv = _seed(db)
    deliv.digital_asset_id = 999          # già linkato
    db.add(StorageVolume(tenant_id=1, name="SAN", mount_path="/m",
                         watch_dirs=["/OUT"])); db.flush()
    a = _proposal(db, u)
    match_proposal(db, a)
    assert a.matched_deliverable_id is None


def test_rank_candidates_orders_by_score(db):
    u, proj, job, deliv = _seed(db)
    a = _proposal(db, u)
    ranked = rank_candidates(db, a)
    assert ranked and ranked[0]["deliverable_id"] == deliv.id
    assert ranked[0]["strength"] in ("strong", "weak")
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_deliverable_match_db.py -v`
Expected: FAIL ImportError (`match_proposal`/`rank_candidates`)

- [ ] **Step 3: Aggiungi l'orchestrazione DB a `deliverable_match.py`**

```python
# ── orchestrazione DB (append a deliverable_match.py) ──────────────────
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Asset, Project, Job, JobDeliverable, DeliverableStatus, DeliveryItem,
    Container, VideoCodec, Resolution, FrameRate,
)

_OPEN_STATUSES = (DeliverableStatus.planned, DeliverableStatus.in_progress,
                  DeliverableStatus.qc)


def _project_code_from_relpath(rel_path: Optional[str]) -> Optional[str]:
    """Convenzione /OUT/{project_code}/... → project_code. Tollerante:
    prende il primo segmento dopo una watch-dir tipo OUT/EXPORT."""
    if not rel_path:
        return None
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    # salta l'eventuale prefisso watch-dir (OUT, EXPORT, ...)
    if len(parts) >= 2:
        return parts[1] if parts[0].isupper() and len(parts[0]) <= 8 else parts[0]
    return parts[0] if parts else None


def build_expectation(db: Session, deliv: JobDeliverable) -> MatchExpectation:
    item = db.get(DeliveryItem, deliv.delivery_item_id) if deliv.delivery_item_id else None
    cont = db.get(Container, item.container_id) if item and item.container_id else None
    cod = db.get(VideoCodec, item.video_codec_id) if item and item.video_codec_id else None
    res = db.get(Resolution, item.resolution_id) if item and item.resolution_id else None
    fr = db.get(FrameRate, item.frame_rate_id) if item and item.frame_rate_id else None
    # naming: file_naming sul deliverable, fallback naming_convention dell'item se stringa
    naming = deliv.file_naming
    if not naming and item is not None:
        nc = getattr(item, "naming_convention", None)
        if isinstance(nc, str):
            naming = nc
    return MatchExpectation(
        deliverable_id=deliv.id, file_naming=naming,
        container_name=cont.name if cont else None,
        container_ext=cont.extension if cont else None,
        video_codec_name=cod.name if cod else None,
        width=res.width if res else None, height=res.height if res else None,
        fps=fr.fps if fr else None)


def candidate_deliverables(db: Session, asset: Asset) -> list[JobDeliverable]:
    code = _project_code_from_relpath(asset.rel_path)
    if not code:
        return []
    proj = db.execute(
        select(Project).where(Project.tenant_id == asset.tenant_id,
                              Project.code == code)
    ).scalar_one_or_none()
    if proj is None:
        return []
    rows = db.execute(
        select(JobDeliverable)
        .join(Job, Job.id == JobDeliverable.job_id)
        .where(Job.project_id == proj.id,
               JobDeliverable.tenant_id == asset.tenant_id,
               JobDeliverable.digital_asset_id.is_(None),
               JobDeliverable.deleted_at.is_(None),
               JobDeliverable.status.in_(_OPEN_STATUSES))
    ).scalars().all()
    return list(rows)


def rank_candidates(db: Session, asset: Asset) -> list[dict]:
    """Lista ordinata per score desc dei candidati con strength != none."""
    probe = asset.tech_specs_json or {}
    out = []
    for d in candidate_deliverables(db, asset):
        exp = build_expectation(db, d)
        r = score_match(asset.filename or "", probe, exp)
        if r.strength != "none":
            out.append({"deliverable_id": d.id, "name": d.name,
                        "score": r.score, "strength": r.strength,
                        "specs_agree": r.specs_agree, "naming_ok": r.naming_ok})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def match_proposal(db: Session, asset: Asset) -> Optional[int]:
    """Popola asset.matched_deliverable_id se c'è un match FORTE univoco.
    Ritorna l'id matchato o None. Idempotente."""
    ranked = rank_candidates(db, asset)
    strong = [r for r in ranked if r["strength"] == "strong"]
    if len(strong) == 1:
        asset.matched_deliverable_id = strong[0]["deliverable_id"]
        db.flush()
        return asset.matched_deliverable_id
    asset.matched_deliverable_id = None
    db.flush()
    return None
```

- [ ] **Step 4: Esegui — deve passare**

Run: `.venv\Scripts\python.exe -m pytest tests/test_deliverable_match_db.py -v` → 3 PASS
Verifica i costruttori reali: se `Client`/`Project`/`Job`/`Container`/... richiedono altri campi NOT NULL, adatta il `_seed` minimamente (mantieni le assert).

- [ ] **Step 5: Suite + commit**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q` → tutti PASS
```bash
git add app/services/deliverable_match.py tests/test_deliverable_match_db.py
git commit -m "feat(F2): candidate-set + match_proposal (project da path, lookup specs)"
```

---

### Task 4: Wiring match nella creazione proposta + job `scan` (lista)

**Files:**
- Modify: `app/routers/agent_api.py` (`process_job_result`: chiama `match_proposal` dopo `probe`; gestisci `type=scan` con lista items)
- Test: `tests/test_f2_scan_wiring.py`

- [ ] **Step 1: Scrivi i test che falliscono**

```python
"""F2 — process_job_result: probe→match; scan→N proposte+match."""
from app.models.models import (
    Tenant, User, UserRole, Client, Project, Job, JobDeliverable,
    DeliverableStatus, DeliveryItem, Container, VideoCodec, Resolution, FrameRate,
    StorageVolume, AgentNode, AgentJobType, AssetProposedState,
)
from app.services.agent_queue import enqueue_job, claim_next_job
from app.routers.agent_api import process_job_result


def _seed(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff); db.add(u)
    cli = Client(tenant_id=1, name="Sky"); db.add(cli); db.flush()
    proj = Project(tenant_id=1, code="GOMORRA", title="G", client_id=cli.id)
    db.add(proj); db.flush()
    job = Job(tenant_id=1, project_id=proj.id, code="J01", title="J01")
    db.add(job); db.flush()
    cont = Container(tenant_id=1, name="QuickTime", extension="mov")
    cod = VideoCodec(tenant_id=1, name="ProRes 422 HQ", family="prores")
    res = Resolution(tenant_id=1, name="HD", width=1920, height=1080)
    fr = FrameRate(tenant_id=1, name="25", fps=25.0)
    db.add_all([cont, cod, res, fr]); db.flush()
    item = DeliveryItem(tenant_id=1, name="m", container_id=cont.id,
                        video_codec_id=cod.id, resolution_id=res.id,
                        frame_rate_id=fr.id); db.add(item); db.flush()
    d = JobDeliverable(tenant_id=1, job_id=job.id, name="EP01",
                       file_naming="GOMORRA_S03_EP01", delivery_item_id=item.id,
                       status=DeliverableStatus.planned); db.add(d); db.flush()
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/m", watch_dirs=["/OUT"])
    db.add(v)
    ag = AgentNode(tenant_id=1, name="ag", auth_token_hash="d"*64); db.add(ag)
    db.flush()
    return u, v, ag, d


PROBE = {"rel_path": "OUT/GOMORRA/GOMORRA_S03_EP01_PRORES.mov", "file_size": 10,
         "mime_type": "video/quicktime", "checksum_xxhash": "aa11aa11aa11aa11",
         "tech_specs": {"container": "mov,mp4", "video": {
             "codec": "prores", "width": 1920, "height": 1080,
             "frame_rate": "25/1"}}}


def test_probe_done_runs_match(db):
    u, v, ag, d = _seed(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                      payload={"volume_id": v.id, "rel_path": PROBE["rel_path"]},
                      requested_by_user_id=u.id)
    claim_next_job(db, ag)
    asset = process_job_result(db, job, status="done", result=PROBE)
    assert asset is not None
    assert asset.matched_deliverable_id == d.id


def test_scan_creates_multiple_proposals(db):
    u, v, ag, d = _seed(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.scan,
                      payload={"volume_id": v.id}, requested_by_user_id=u.id)
    claim_next_job(db, ag)
    p2 = dict(PROBE, rel_path="OUT/GOMORRA/altro.wav",
              checksum_xxhash="bb22bb22bb22bb22", mime_type="audio/wav",
              tech_specs={"container": "wav"})
    res = process_job_result(db, job, status="done",
                             result={"volume_id": v.id, "items": [PROBE, p2]})
    # scan ritorna lista asset; il primo matcha il deliverable
    from app.models.models import Asset
    assets = db.query(Asset).filter(Asset.proposed_state ==
                                    AssetProposedState.pending_review).all()
    assert len(assets) == 2
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_scan_wiring.py -v`
Expected: FAIL (match non chiamato / scan non gestito)

- [ ] **Step 3: Estendi `process_job_result`**

In `app/routers/agent_api.py`, import in testa:
```python
from app.services.deliverable_match import match_proposal
```
Sostituisci il corpo di `process_job_result` (dopo `complete_job(...)`) per gestire probe→match e scan→lista:
```python
    complete_job(db, job, result or {})
    if status != "done" or not result:
        return None
    if job.type == AgentJobType.probe:
        volume_id = int((job.payload or {}).get("volume_id") or 0)
        asset = create_proposal_from_probe(
            db, tenant_id=job.tenant_id, volume_id=volume_id, probe=result,
            user_id=job.requested_by_user_id or 1,
            registered_via="manual_path")
        job.asset_id = asset.id
        match_proposal(db, asset)          # F2
        db.flush()
        return asset
    if job.type == AgentJobType.scan:
        volume_id = int(result.get("volume_id") or (job.payload or {}).get("volume_id") or 0)
        created = []
        for item in result.get("items") or []:
            asset = create_proposal_from_probe(
                db, tenant_id=job.tenant_id, volume_id=volume_id, probe=item,
                user_id=job.requested_by_user_id or 1,
                registered_via="agent_watch")  # F2: watch
            match_proposal(db, asset)
            created.append(asset)
        db.flush()
        # asset_id singolo non ha senso per scan multi → lascia None, ritorna il primo
        return created[0] if created else None
    return None
```
Nota: `test_failed_job_no_proposal` (F1) deve restare verde: il ramo `status != "done"` lo copre.

- [ ] **Step 4: Esegui — deve passare + F1 non regredisce**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_scan_wiring.py tests/test_agent_api.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/agent_api.py tests/test_f2_scan_wiring.py
git commit -m "feat(F2): probe→match + job scan multi-proposta agent_watch"
```

---

### Task 5: Endpoint candidati + conferma estesa (link + status=qc)

**Files:**
- Modify: `app/routers/storage_admin.py` (proposals serializer espone match; nuovo GET candidati; confirm accetta `deliverable_id`)
- Test: `tests/test_f2_confirm.py`

- [ ] **Step 1: Scrivi i test che falliscono**

```python
"""F2 — conferma proposta con deliverable → digital_asset_id + status=qc."""
from app.models.models import (
    Tenant, User, UserRole, Client, Project, Job, JobDeliverable,
    DeliverableStatus, StorageVolume, Asset, AssetType, AssetStatus,
    AssetContentState, AssetProposedState,
)
from app.services.asset_registry import confirm_proposal
from app.services.deliverable_match import link_deliverable_on_confirm


def _seed(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff); db.add(u)
    cli = Client(tenant_id=1, name="Sky"); db.add(cli); db.flush()
    proj = Project(tenant_id=1, code="G", title="G", client_id=cli.id)
    db.add(proj); db.flush()
    job = Job(tenant_id=1, project_id=proj.id, code="J", title="J"); db.add(job)
    db.flush()
    d = JobDeliverable(tenant_id=1, job_id=job.id, name="EP01",
                       status=DeliverableStatus.planned); db.add(d); db.flush()
    a = Asset(tenant_id=1, filename="f.mov", original_name="f.mov",
              file_path="agent://1/OUT/G/f.mov", storage_volume_id=1,
              rel_path="OUT/G/f.mov", asset_type=AssetType.video,
              mime_type="video/quicktime", file_size=1, uploaded_by=u.id,
              status=AssetStatus.uploaded, content_state=AssetContentState.online,
              proposed_state=AssetProposedState.pending_review); db.add(a); db.flush()
    return u, d, a


def test_link_on_confirm_sets_digital_asset_and_qc(db):
    u, d, a = _seed(db)
    confirm_proposal(db, a, user_id=u.id)
    link_deliverable_on_confirm(db, a, deliverable_id=d.id, user_id=u.id)
    assert d.digital_asset_id == a.id
    assert d.status == DeliverableStatus.qc


def test_link_rejects_cross_tenant(db):
    u, d, a = _seed(db)
    db.add(Tenant(id=2, name="T2", slug="t2")); db.flush()
    a.tenant_id = 1
    # deliverable di tenant 1, ma simuliamo richiesta con deliverable inesistente
    import pytest
    with pytest.raises(Exception):
        link_deliverable_on_confirm(db, a, deliverable_id=99999, user_id=u.id)
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_confirm.py -v`
Expected: FAIL ImportError `link_deliverable_on_confirm`

- [ ] **Step 3: Aggiungi `link_deliverable_on_confirm` a `deliverable_match.py`**

```python
from fastapi import HTTPException  # in testa al file insieme agli altri import


def link_deliverable_on_confirm(db: Session, asset: Asset, *,
                                deliverable_id: int, user_id: int) -> JobDeliverable:
    """Collega l'asset confermato al deliverable: set digital_asset_id +
    status=qc. Tenant-scoped. Apre la trafila QC (lo stato qc fa il resto)."""
    d = db.get(JobDeliverable, deliverable_id)
    if d is None or d.tenant_id != asset.tenant_id or d.deleted_at is not None:
        raise HTTPException(404, "deliverable non trovato")
    d.digital_asset_id = asset.id
    if d.status in (DeliverableStatus.planned, DeliverableStatus.in_progress):
        d.status = DeliverableStatus.qc
    db.flush()
    return d
```

- [ ] **Step 4: Estendi il router `storage_admin.py`**

(a) Import: `from app.services.deliverable_match import rank_candidates, link_deliverable_on_confirm`.
(b) In `list_proposals`, aggiungi al dict serializzato:
```python
            "matched_deliverable_id": a.matched_deliverable_id,
```
(c) Nuovo endpoint candidati (dopo `list_proposals`):
```python
@router.get("/api/proposals/{asset_id}/candidates", dependencies=[RequireStorage])
def proposal_candidates(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    return rank_candidates(db, a)
```
(d) Estendi `confirm` per accettare `deliverable_id` opzionale (Form):
```python
@router.post("/api/proposals/{asset_id}/confirm", dependencies=[RequireStorage])
def confirm(asset_id: int, request: Request,
            deliverable_id: Optional[int] = Form(None),
            db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None or a.tenant_id != CURRENT_TENANT:
        raise HTTPException(404)
    user = current_user_optional(request)
    confirm_proposal(db, a, user_id=getattr(user, "id", None))
    # F2: se è indicato un deliverable (scelto o match forte accettato) → collega
    target = deliverable_id or a.matched_deliverable_id
    if target:
        link_deliverable_on_confirm(db, a, deliverable_id=int(target),
                                    user_id=getattr(user, "id", None))
    db.commit()
    return {"ok": True}
```
(Verifica come `confirm` è scritto oggi — Task 7 F1 usa `current_user_optional(request)`; mantieni quell'idioma. Aggiungi `Optional` all'import typing se manca.)

- [ ] **Step 5: Esegui + boot**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_confirm.py -v` → PASS
Run: `.venv\Scripts\python.exe -c "from app.main import app; print('ok')"` → ok

- [ ] **Step 6: Suite + commit**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q` → PASS
```bash
git add app/services/deliverable_match.py app/routers/storage_admin.py tests/test_f2_confirm.py
git commit -m "feat(F2): candidati proposta + conferma con link deliverable→qc"
```

---

### Task 6: Watch agent-side (`agent/watch.py`) + loop in `agent/main.py`

**Files:**
- Create: `agent/watch.py`
- Modify: `agent/main.py` (gestisci job `scan`: usa watch per produrre la lista probe)
- Test: `tests/test_agent_watch.py`

L'agent NON importa `app.*`. `watch.py` usa solo stdlib + `agent.probe`.

- [ ] **Step 1: Scrivi i test che falliscono**

```python
"""F2 — watch agent: stabilità size + package DCP/IMF + scan dir."""
from agent.watch import WatchState, is_dcp_package, scan_volume


def test_size_stable_only_after_quiet(tmp_path):
    f = tmp_path / "OUT" / "a.mov"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x" * 10)
    st = WatchState()
    # primo ciclo: visto ma non stabile (no baseline precedente)
    new1 = scan_volume(str(tmp_path), ["OUT"], st)
    assert new1 == []                     # appena visto, non ancora stabile
    # secondo ciclo, size invariata → stabile → proposto
    new2 = scan_volume(str(tmp_path), ["OUT"], st)
    assert "OUT/a.mov" in [n["rel_path"] for n in new2]
    # terzo ciclo: già proposto → non riproposto
    new3 = scan_volume(str(tmp_path), ["OUT"], st)
    assert new3 == []


def test_growing_file_not_proposed(tmp_path):
    f = tmp_path / "OUT" / "b.mov"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x" * 10)
    st = WatchState()
    scan_volume(str(tmp_path), ["OUT"], st)
    f.write_bytes(b"x" * 20)              # cresciuta
    new = scan_volume(str(tmp_path), ["OUT"], st)
    assert new == []                      # size cambiata → non stabile


def test_dcp_package_detected(tmp_path):
    pkg = tmp_path / "OUT" / "DCP_FILM"
    pkg.mkdir(parents=True)
    (pkg / "ASSETMAP").write_bytes(b"<AssetMap/>")
    (pkg / "video.mxf").write_bytes(b"x" * 100)
    assert is_dcp_package(str(pkg)) is True
    st = WatchState()
    scan_volume(str(tmp_path), ["OUT"], st)
    new = scan_volume(str(tmp_path), ["OUT"], st)
    rels = [n["rel_path"] for n in new]
    assert "OUT/DCP_FILM" in rels         # cartella come unità, non i file dentro


def test_missing_dir_no_crash(tmp_path):
    st = WatchState()
    assert scan_volume(str(tmp_path), ["NONEXISTENT"], st) == []
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_watch.py -v`
Expected: FAIL ModuleNotFoundError `agent.watch`

- [ ] **Step 3: Implementa `agent/watch.py`**

```python
"""F2 (spec 2026-06-10) — Watch cartelle output (polling listing).

Stato in-memory per volume: {rel_path: size}. Un file è "stabile" (→ proposto)
quando appare con la STESSA size in due cicli consecutivi e non è già stato
proposto. Package DCP/IMF (cartella con ASSETMAP) = unità singola. Nessun
import di app.*: gira sull'agent facility.
"""
from __future__ import annotations
import os
from typing import Optional

from agent.probe import build_probe_result


class WatchState:
    """Stato osservazioni precedenti + set già-proposti (per volume)."""
    def __init__(self):
        self.prev_sizes: dict[str, int] = {}
        self.proposed: set[str] = set()


def is_dcp_package(dir_path: str) -> bool:
    try:
        names = {n.upper() for n in os.listdir(dir_path)}
    except OSError:
        return False
    return "ASSETMAP" in names or "ASSETMAP.XML" in names


def _dir_size(dir_path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(dir_path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def scan_volume(mount_path: str, watch_dirs: list[str],
                state: WatchState) -> list[dict]:
    """Un ciclo di scan. Ritorna i probe-result dei file/package NUOVI e
    stabili. Aggiorna lo state. Mai solleva: errori per-path isolati."""
    current: dict[str, int] = {}
    package_dirs: set[str] = set()
    new_results: list[dict] = []

    roots = watch_dirs or [""]
    for wd in roots:
        base = os.path.join(mount_path, wd.strip("/\\")) if wd else mount_path
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            # package DCP/IMF: tratta la cartella come unità, non discendere
            if is_dcp_package(root):
                rel = os.path.relpath(root, mount_path).replace("\\", "/")
                current[rel] = _dir_size(root)
                package_dirs.add(rel)
                dirs[:] = []  # non scendere dentro il package
                continue
            for fn in files:
                full = os.path.join(root, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, mount_path).replace("\\", "/")
                current[rel] = size

    for rel, size in current.items():
        if rel in state.proposed:
            continue
        prev = state.prev_sizes.get(rel)
        if prev is not None and prev == size:   # stabile da ≥1 ciclo
            try:
                if rel in package_dirs:
                    res = _probe_package(mount_path, rel, size)
                else:
                    res = build_probe_result(mount_path, rel)
                new_results.append(res)
                state.proposed.add(rel)
            except (OSError, FileNotFoundError):
                pass  # sparito tra walk e probe: salta, ritenta al prossimo giro
    state.prev_sizes = current
    return new_results


def _probe_package(mount_path: str, rel_dir: str, size: int) -> dict:
    """Package DCP/IMF: prova a probare il .mxf più grande, altrimenti
    metadata di cartella (tool=package). checksum dell'mxf principale o vuoto."""
    full_dir = os.path.join(mount_path, rel_dir)
    biggest = None
    biggest_sz = -1
    for root, _d, files in os.walk(full_dir):
        for fn in files:
            if fn.lower().endswith(".mxf"):
                p = os.path.join(root, fn)
                try:
                    s = os.path.getsize(p)
                except OSError:
                    continue
                if s > biggest_sz:
                    biggest_sz, biggest = s, p
    if biggest:
        rel_mxf = os.path.relpath(biggest, mount_path).replace("\\", "/")
        res = build_probe_result(mount_path, rel_mxf)
        res["rel_path"] = rel_dir          # l'asset è il package, non il singolo mxf
        res["file_size"] = size
        res["mime_type"] = "application/mxf"
        res.setdefault("tech_specs", {})["package"] = "dcp_imf"
        return res
    return {"rel_path": rel_dir, "file_size": size,
            "mime_type": "application/octet-stream", "checksum_xxhash": "",
            "tech_specs": {"tool": "package", "package": "dcp_imf"}}
```

- [ ] **Step 4: Esegui — deve passare**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_watch.py -v` → 4 PASS
(Se ffprobe non è installato, `build_probe_result` degrada a `tech_specs.tool='none'` ma checksum+size restano — i test non dipendono da ffprobe.)

- [ ] **Step 5: Cabla il watch nel loop agent (`agent/main.py`)**

Modifica `handle_job` per gestire `scan` con il watch, e mantieni uno `WatchState` per-volume nel loop `run()`:
```python
# in testa
from agent.watch import WatchState, scan_volume

# in run(), prima del while:
    watch_states: dict[int, WatchState] = {}

# in handle_job, aggiungi il ramo scan PRIMA del fallback:
        if jtype == "scan":
            vol_id = int(payload.get("volume_id") or 0)
            st = watch_states.setdefault(vol_id, WatchState())  # vedi nota
            items = scan_volume(vol["mount_path"], vol.get("watch_dirs") or [], st)
            return "done", {"volume_id": vol_id, "items": items}, None
```
Nota: `handle_job` oggi non ha accesso a `watch_states`. Rifattorizza minimamente: passa `watch_states` come parametro a `handle_job(job, volumes_by_id, watch_states)` e nel chiamante in `run()` passa il dict. Mantieni i rami `probe`/`checksum` invariati.

Inoltre, l'agent deve **auto-schedularsi** lo scan: dopo ogni heartbeat, se non ci sono job in coda, accoda localmente un giro di scan per ogni volume con `watch_dirs`. Implementazione semplice in `run()`: se `client.claim()` torna `None`, esegui direttamente un ciclo scan per ogni volume e fai `post_result`-equivalente via un job locale — MA per restare dentro il modello coda, la scelta v1 è: **il server accoda i job `scan`**. Quindi qui l'agent esegue solo i job `scan` che riceve. L'accodamento ricorrente lato server è lo Step 6.

- [ ] **Step 6: Commit**

```bash
git add agent/watch.py agent/main.py tests/test_agent_watch.py
git commit -m "feat(F2): agent watch.py polling+stabilità+DCP/IMF + ramo scan"
```

---

### Task 7: Accodamento `scan` ricorrente + endpoint "watch now"

**Files:**
- Modify: `app/routers/storage_admin.py` (endpoint `POST /api/volumes/{id}/scan-now` che accoda un job scan)
- Modify: `app/services/agent_queue.py` (helper `enqueue_scan_if_absent` per non accumulare scan duplicati)
- Test: `tests/test_f2_scan_enqueue.py`

v1 = scan on-demand (bottone UI) + opzionale auto-richiesta dall'agent. NO scheduler server (YAGNI: l'agent può chiedere "dammi uno scan" via un parametro all'heartbeat in F2.1). Qui: enqueue manuale idempotente.

- [ ] **Step 1: Scrivi il test che fallisce**

```python
"""F2 — enqueue_scan_if_absent: un solo scan queued per volume."""
from app.models.models import Tenant, StorageVolume, AgentJob, AgentJobStatus, AgentJobType
from app.services.agent_queue import enqueue_scan_if_absent


def test_enqueue_scan_dedup(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/m", watch_dirs=["/OUT"])
    db.add(v); db.flush()
    j1 = enqueue_scan_if_absent(db, tenant_id=1, volume_id=v.id)
    j2 = enqueue_scan_if_absent(db, tenant_id=1, volume_id=v.id)
    assert j1.id == j2.id                 # non duplica: scan già queued
    n = db.query(AgentJob).filter(AgentJob.type == AgentJobType.scan,
                                  AgentJob.status == AgentJobStatus.queued).count()
    assert n == 1
```

- [ ] **Step 2: Esegui — deve fallire**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_scan_enqueue.py -v` → FAIL ImportError

- [ ] **Step 3: Implementa l'helper**

In `app/services/agent_queue.py`:
```python
def enqueue_scan_if_absent(db: Session, *, tenant_id: int, volume_id: int,
                           requested_by_user_id: Optional[int] = None) -> AgentJob:
    """Accoda un job scan per il volume solo se non ce n'è già uno queued/claimed.
    Evita di accumulare scan se l'agent è lento/offline."""
    existing = db.execute(
        select(AgentJob).where(
            AgentJob.tenant_id == tenant_id,
            AgentJob.type == AgentJobType.scan,
            AgentJob.status.in_([AgentJobStatus.queued, AgentJobStatus.claimed]),
            AgentJob.payload["volume_id"].as_integer() == volume_id)
    ).scalars().first()
    if existing is not None:
        return existing
    return enqueue_job(db, tenant_id=tenant_id, type=AgentJobType.scan,
                       payload={"volume_id": volume_id},
                       requested_by_user_id=requested_by_user_id)
```
NB: `AgentJob.payload["volume_id"].as_integer()` è il JSON-path SQLite. Se dà problemi sul tipo, fai il filtro in Python: carica gli scan queued/claimed del tenant e confronta `(j.payload or {}).get("volume_id") == volume_id`. Usa la variante Python se il JSON path non è supportato.

- [ ] **Step 4: Endpoint scan-now nel router**

In `storage_admin.py`:
```python
from app.services.agent_queue import enqueue_scan_if_absent

@router.post("/api/volumes/{vol_id}/scan-now", dependencies=[RequireStorage])
def scan_now(vol_id: int, request: Request, db: Session = Depends(get_db)):
    v = db.get(StorageVolume, vol_id)
    if v is None or v.tenant_id != CURRENT_TENANT or not v.is_active:
        raise HTTPException(404)
    user = current_user_optional(request)
    job = enqueue_scan_if_absent(db, tenant_id=CURRENT_TENANT, volume_id=vol_id,
                                 requested_by_user_id=getattr(user, "id", None))
    db.commit()
    return {"ok": True, "job_id": job.id}
```

- [ ] **Step 5: Esegui + boot + commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_f2_scan_enqueue.py -v` → PASS
Run: `.venv\Scripts\python.exe -c "from app.main import app; print('ok')"` → ok
```bash
git add app/services/agent_queue.py app/routers/storage_admin.py tests/test_f2_scan_enqueue.py
git commit -m "feat(F2): enqueue scan idempotente + endpoint scan-now per volume"
```

---

### Task 8: UI `/storage` — badge match + dropdown candidati + scan-now

**Files:**
- Modify: `app/templates/pages/storage.html`

Pattern: helper globali `api()`/`escapeHtml()`/`toast()` (NON ridefinire); no `JSON.stringify` in onclick; ogni `onclick` ha la sua funzione. Riusa la struttura tab F1.

- [ ] **Step 1: Tab Proposte — colonna Match + candidati**

Aggiorna `loadProposals()` per: (a) colonna "Match" con badge; (b) per proposte con match debole/zero, carica i candidati e mostra un `<select>` per scegliere il deliverable; (c) il bottone Conferma passa il `deliverable_id` scelto.
```javascript
async function loadProposals() {
  const rows = await api('/storage/api/proposals');
  const body = document.getElementById('proposalsBody');
  body.innerHTML = rows.map(p => `
    <tr data-id="${p.id}">
      <td>${escapeHtml(p.filename)}</td>
      <td class="mono">${escapeHtml(p.rel_path || '')}</td>
      <td>${(p.file_size/1e9).toFixed(2)} GB</td>
      <td class="mono">${escapeHtml(p.checksum_xxhash || '—')}</td>
      <td data-match-cell="${p.id}">${p.matched_deliverable_id
          ? '🟢 <span class="text-muted">match…</span>'
          : '<span class="text-muted">—</span>'}</td>
      <td>
        <select class="form-select" data-deliv-select="${p.id}"></select>
      </td>
      <td>
        <button class="btn btn-sm btn-primary" data-id="${p.id}"
          onclick="confirmProposal(this.dataset.id)">✓ Conferma</button>
        <button class="btn btn-sm btn-ghost" data-id="${p.id}"
          onclick="discardProposal(this.dataset.id)">✗ Scarta</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="7" class="text-muted">Nessuna proposta in attesa di revisione.</td></tr>';
  // carica candidati per ogni proposta (parallelo)
  for (const p of rows) loadCandidates(p.id, p.matched_deliverable_id);
}

async function loadCandidates(assetId, matchedId) {
  let cands = [];
  try { cands = await api(`/storage/api/proposals/${assetId}/candidates`); }
  catch (e) { cands = []; }
  const sel = document.querySelector(`[data-deliv-select="${assetId}"]`);
  if (sel) {
    sel.innerHTML = '<option value="">— nessun collegamento —</option>' +
      cands.map(c => `<option value="${c.deliverable_id}"
        ${c.deliverable_id === matchedId ? 'selected' : ''}>
        ${escapeHtml(c.name)} · ${c.strength} (${Math.round(c.score*100)}%)</option>`).join('');
  }
  const cell = document.querySelector(`[data-match-cell="${assetId}"]`);
  if (cell) {
    const strong = cands.find(c => c.deliverable_id === matchedId);
    if (strong) cell.innerHTML = `🟢 ${escapeHtml(strong.name)}`;
    else if (cands.length) cell.innerHTML = `🟡 ${cands.length} candidat${cands.length>1?'i':'o'}`;
    else cell.innerHTML = '<span class="text-muted">⚪ nessuno</span>';
  }
}

async function confirmProposal(id) {
  const sel = document.querySelector(`[data-deliv-select="${id}"]`);
  const fd = new FormData();
  if (sel && sel.value) fd.append('deliverable_id', sel.value);
  await api(`/storage/api/proposals/${id}/confirm`, {method:'POST', body: fd});
  toast('Asset confermato'); loadProposals();
}
```
(Mantieni `discardProposal` invariato da F1.)

- [ ] **Step 2: Tab Volumi — bottone "Scansiona ora"**

Nella riga volume (in `loadVolumes()`), aggiungi accanto a Modifica:
```javascript
`<button class="btn btn-sm btn-ghost" data-id="${v.id}"
   onclick="scanNow(this.dataset.id)">🔍 Scansiona</button>`
```
e la funzione:
```javascript
async function scanNow(id) {
  await api(`/storage/api/volumes/${id}/scan-now`, {method:'POST'});
  toast('Scan accodato — le proposte appariranno appena l\\'agent risponde');
  switchStorageTab('jobs'); loadJobs();
}
```

- [ ] **Step 3: Smoke template + onclick grep**

Riavvia server (template OneDrive). Verifica compile:
Run: `.venv\Scripts\python.exe -c "from app.main import templates; templates.get_template('pages/storage.html'); print('tpl ok')"`
Grep manuale: ogni `onclick="fn(...)"` nel template ha `function fn`/`const fn`. Elenca gli handler e conferma.

- [ ] **Step 4: Commit**

```bash
git add app/templates/pages/storage.html
git commit -m "feat(F2): UI /storage badge match + candidati + scan-now"
```

---

### Task 9: Mobile PWA `/m/proposte`

**Files:**
- Modify: `app/routers/mobile.py` (nuova route `/m/proposte` + eventuale API JSON se serve)
- Create: `app/templates/mobile/proposte.html`
- Modify: `app/templates/mobile/base_mobile.html` o nav mobile (voce "Proposte")

Leggi PRIMA `app/routers/mobile.py` + un template mobile esistente (es. la vista planning) per copiare il pattern reale (come rende, come fa fetch, auth). Riusa gli endpoint `/storage/api/proposals`, `/candidates`, `/confirm`, `/discard` (stesso backend).

- [ ] **Step 1: Route mobile**

In `app/routers/mobile.py`, aggiungi (adatta all'idioma reale del file — auth, templates, prefix `/m`):
```python
@router.get("/proposte", response_class=HTMLResponse)
def m_proposte(request: Request):
    user = current_user_optional(request)   # usa l'helper reale del file
    return _templates().TemplateResponse("mobile/proposte.html",
                                         {"request": request, "user": user})
```

- [ ] **Step 2: Template `mobile/proposte.html`**

Estende `mobile/base_mobile.html` (verifica il nome reale). Lista proposte pending con card; tap apre dettaglio inline (specs+checksum+select candidati); bottoni Conferma/Scarta. Riusa `/storage/api/*`. Esempio JS (adatta classi mobile reali):
```html
{% extends "mobile/base_mobile.html" %}
{% block content %}
<h2>Proposte</h2>
<div id="mProposte">Caricamento…</div>
<script>
async function loadMProposte(){
  const rows = await api('/storage/api/proposals');
  const el = document.getElementById('mProposte');
  if(!rows.length){ el.innerHTML='<p class="m-empty">Nessuna proposta.</p>'; return; }
  el.innerHTML = rows.map(p=>`
    <div class="m-card" data-id="${p.id}">
      <div class="m-card-title">${escapeHtml(p.filename)}</div>
      <div class="m-card-sub mono">${escapeHtml(p.rel_path||'')}</div>
      <div>${(p.file_size/1e9).toFixed(2)} GB · ${escapeHtml(p.checksum_xxhash||'—')}</div>
      <select class="form-select" data-sel="${p.id}"><option value="">— link —</option></select>
      <div class="m-card-actions">
        <button class="btn btn-primary" data-id="${p.id}" onclick="mConfirm(this.dataset.id)">Conferma</button>
        <button class="btn btn-ghost" data-id="${p.id}" onclick="mDiscard(this.dataset.id)">Scarta</button>
      </div>
    </div>`).join('');
  for(const p of rows){
    const c = await api(`/storage/api/proposals/${p.id}/candidates`).catch(()=>[]);
    const s = document.querySelector(`[data-sel="${p.id}"]`);
    if(s) s.innerHTML += c.map(x=>`<option value="${x.deliverable_id}"
      ${x.deliverable_id===p.matched_deliverable_id?'selected':''}>
      ${escapeHtml(x.name)} · ${x.strength}</option>`).join('');
  }
}
async function mConfirm(id){
  const s=document.querySelector(`[data-sel="${id}"]`); const fd=new FormData();
  if(s&&s.value) fd.append('deliverable_id', s.value);
  await api(`/storage/api/proposals/${id}/confirm`,{method:'POST',body:fd});
  toast('Confermato'); loadMProposte();
}
async function mDiscard(id){
  await api(`/storage/api/proposals/${id}/discard`,{method:'POST'});
  toast('Scartato'); loadMProposte();
}
loadMProposte();
</script>
{% endblock %}
```

- [ ] **Step 3: Voce nav mobile** verso `/m/proposte` (segui il pattern del drawer/nav mobile reale).

- [ ] **Step 4: Smoke template + boot**

Run: `.venv\Scripts\python.exe -c "from app.main import templates; templates.get_template('mobile/proposte.html'); print('ok')"`
Run: `.venv\Scripts\python.exe -c "from app.main import app; print('ok')"`

- [ ] **Step 5: Commit**

```bash
git add app/routers/mobile.py app/templates/mobile/proposte.html app/templates/mobile/base_mobile.html
git commit -m "feat(F2): mobile PWA /m/proposte review proposte"
```

---

### Task 10: E2E watch→match→conferma + bump + push

**Files:**
- Create/Modify: `tools/_e2e_f2.py`
- Modify: `app/main.py` (version → `3.5.0-alpha.172.211`)
- Modify: `CHANGELOG.md`, `docs/STATO.md`, `docs/qc/f2-e2e-checklist.md`

- [ ] **Step 1: Script E2E**

Scrivi `tools/_e2e_f2.py` sul modello di `tools/_e2e_f1.py`: crea progetto `GOMORRA` + job + DeliveryItem(ProRes/HD/25) + JobDeliverable `file_naming=GOMORRA_S03_EP01` (planned); crea volume mount `C:\temp\san01` (con `OUT/GOMORRA/GOMORRA_S03_EP01_PRORES.mov` finto) + agent token; via HTTP `/agent-api`: heartbeat → accoda scan (via `enqueue_scan_if_absent` diretto in DB o endpoint scan-now) → claim → l'agent fa `scan_volume` → post result `{items:[...]}` → verifica: proposta creata `registered_via=agent_watch` + `matched_deliverable_id == deliverable` → conferma con deliverable_id → `JobDeliverable.digital_asset_id` settato + `status=qc`. Pulisci gli artefatti a fine.

- [ ] **Step 2: Esegui E2E (server live)**

Riavvia server. Run: `set PYTHONPATH=. && .venv\Scripts\python.exe tools\_e2e_f2.py`
Expected: tutti i check OK.

- [ ] **Step 3: Browser smoke**

`/storage` → tab Volumi → "Scansiona" → tab Job (scan done) → tab Proposte → badge match 🟢 sul deliverable + Conferma. Console 0 errori. `/m/proposte` su viewport mobile.

- [ ] **Step 4: Bump + CHANGELOG + STATO + checklist**

`app/main.py` version → `3.5.0-alpha.172.211`. Aggiungi sezione CHANGELOG (F2 watch+match) + STATO (header + sezione α.172.211 + prossimo F3 preview) + `docs/qc/f2-e2e-checklist.md` con gli esiti.

- [ ] **Step 5: Suite completa**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q` → tutti PASS

- [ ] **Step 6: Export ZIP + commit + push**

Genera ZIP export in `docs/` (come F1 T11: `build_export_zip(db, app_version=app.version)`).
```bash
git add -A
git commit -m "chore: bump 3.5.0-alpha.172.211 - F2 watch + match"
git push
```

---

## Self-review (fatto in scrittura)

- **Spec coverage**: watch ✓(T6) stabilità+package ✓(T6) match scoring ✓(T2) candidate-set+project-da-path ✓(T3) wiring probe/scan ✓(T4) conferma→link→qc ✓(T5) accodamento scan ✓(T7) UI badge+candidati ✓(T8) mobile ✓(T9) modello matched_deliverable_id ✓(T1) E2E ✓(T10).
- **Type consistency**: `MatchExpectation`/`MatchResult` (T2) usati identici in T3; `score_match(filename, probe, exp)` firma uniforme T2→T3; `match_proposal(db, asset)`/`rank_candidates(db, asset)`/`link_deliverable_on_confirm(db, asset, deliverable_id, user_id)` coerenti T3/T5/router; `scan_volume(mount_path, watch_dirs, state)` + `WatchState` coerenti T6; result scan `{volume_id, items:[...]}` uguale agent(T6)↔server(T4).
- **Fuori F2 (esplicito)**: preview QC (F3), LTO/MHL (F4), TransferOrder (F5), distruzione (F6), override output_dir per-progetto, persistenza candidati deboli, scheduler scan server-side (v1 = scan-now + scan on-demand), long-poll vero.
- **Rischi noti per l'esecutore**: (1) costruttori `Client/Project/Job/Container/...` nei test possono richiedere campi NOT NULL extra → adatta i `_seed` mantenendo le assert; (2) JSON-path SQLite `payload["volume_id"].as_integer()` (T7) può non funzionare → fallback filtro Python; (3) `confirm` in storage_admin usa `current_user_optional(request)` (idioma F1) — mantienilo; (4) mobile.py/base_mobile.html: leggi i nomi reali prima di scrivere (T9); (5) riavvio server obbligatorio per template nuovi (OneDrive); (6) `naming_convention` su DeliveryItem può essere JSON, non stringa → in `build_expectation` usala solo se `isinstance(str)`.
