"""E2E offline F3 — preview QC round-trip con agent vero + clip sintetica.

TestClient + DB in-memory: genera clip mp4 reale con ffmpeg, accoda job preview,
l'agent VERO (agent.main.handle_job) genera il proxy e lo carica via TestClient,
la UI-API espone streaming + status.
"""
import os
import shutil
import subprocess
import sys
import tempfile

# Guard ffmpeg/ffprobe PRIMA di qualsiasi altra cosa
if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
    print("SKIP: ffmpeg/ffprobe non disponibili su questa macchina")
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, AssetType
from app.models import User, Role, Tenant
from app.models.models import UserRole
from app.services.auth import create_access_token

import app.database as database
import app.main as main_mod
from app.database import get_db

# ── Contatori check ──────────────────────────────────────────────────────────

OK = []


def check(name, cond, detail=""):
    OK.append((name, bool(cond)))
    marker = "  OK " if cond else "  FAIL "
    line = marker + name
    if detail and not cond:
        line += f"  [{detail}]"
    print(line)


# ── DB in-memory ─────────────────────────────────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
database.engine = engine
database.SessionLocal = TestSession
session = TestSession()

session.add(Tenant(id=1, name="T", slug="t1", is_active=True))
session.flush()
role = Role(
    tenant_id=1,
    code="admin",
    name="Admin",
    permissions=["edit_planning_all", "view_finance", "assign_resources"],
    is_system=True,
    is_active=True,
)
session.add(role)
session.flush()
session.add(
    User(
        tenant_id=1,
        email="admin@test.local",
        full_name="Admin",
        hashed_password="x",
        role=UserRole.admin,
        role_id=role.id,
        is_active=True,
    )
)
session.commit()


def _ovr():
    yield session


main_mod.app.dependency_overrides[get_db] = _ovr
tok = create_access_token({"sub": "admin@test.local", "tid": 1})

# ── Monkeypatch PREVIEW_DIR prima dell'import del modulo ────────────────────
import app.services.asset_preview as ap

tmp_previews = tempfile.mkdtemp(prefix="claqo_prev_")
ap.PREVIEW_DIR = Path(tmp_previews)

# ── Temporary directories ────────────────────────────────────────────────────

with (
    tempfile.TemporaryDirectory() as tmp_volume,
    TestClient(
        main_mod.app,
        headers={"Cookie": f"access_token={tok}"},
        follow_redirects=False,
    ) as c,
):
    print("-- genera clip sintetica con ffmpeg --")
    clip_path = os.path.join(tmp_volume, "clip.mp4")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        "-timecode", "10:00:00:00",
        clip_path,
    ]
    proc = subprocess.run(
        ffmpeg_cmd, capture_output=True, encoding="utf-8",
        errors="replace", timeout=60,
    )
    check("ffmpeg genera clip", proc.returncode == 0,
          f"rc={proc.returncode} stderr={proc.stderr[-300:]}")

    print("-- setup volume + agent --")
    r = c.post(
        "/storage/api/volumes",
        data={"name": "VOL-E2E", "mount_path": tmp_volume, "watch_dirs": ""},
    )
    vol_id = r.json()["id"]
    check("crea volume", r.status_code == 200)

    r = c.post("/storage/api/agents", data={"name": "ag-e2e-f3"})
    agent_token = r.json()["token"]
    agent_id = r.json()["id"]
    check("crea agent (token plain)", r.status_code == 200 and bool(agent_token))

    print("-- crea Asset direttamente in session --")
    from app.models.models import Asset as AssetModel

    asset = AssetModel(
        tenant_id=1,
        filename="clip.mp4",
        original_name="clip.mp4",
        file_path="",
        file_size=1,
        mime_type="video/mp4",
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=vol_id,
        rel_path="clip.mp4",
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    asset_id = asset.id
    check("asset creato in DB", asset_id is not None)

    print("-- POST generate: enqueue preview job --")
    r = c.post(f"/qc/api/assets/{asset_id}/preview/generate")
    check("generate 200", r.status_code == 200, str(r.text))
    job_id = r.json().get("job_id")
    check("job_id presente", job_id is not None, str(r.json()))

    # Rileggi asset dalla session per vedere preview_status aggiornato
    session.expire(asset)
    session.refresh(asset)
    check(
        "asset.preview_status == queued",
        asset.preview_status == "queued",
        f"got={asset.preview_status}",
    )

    print("-- agent: heartbeat + claim --")
    ah = {"X-Agent-Token": agent_token}
    hb = c.post("/agent-api/heartbeat", json={"version": "0.1"}, headers=ah)
    volumes = hb.json()["volumes"]
    check("heartbeat 200", hb.status_code == 200 and bool(volumes))

    claimed = c.post("/agent-api/jobs/claim", headers=ah).json()["job"]
    check("claim job preview", claimed is not None and claimed["type"] == "preview",
          str(claimed))

    print("-- handle_job (agent vero) --")

    # Adapter minimo: put_preview via TestClient (no streaming reale su TestClient,
    # ma la clip da 2s e' piccola e i byte vengono letti tutti in memoria).
    class _TestClientAdapter:
        def put_preview(self, jid: int, path: str) -> dict:
            with open(path, "rb") as fh:
                data = fh.read()
            resp = c.put(
                f"/agent-api/jobs/{jid}/preview-upload",
                content=data,
                headers={**ah, "Content-Type": "video/mp4"},
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"preview-upload fallito: {resp.status_code} {resp.text}"
                )
            return resp.json()

    from agent.main import handle_job

    vols_by_id = {v["id"]: v for v in volumes}
    status, result, error = handle_job(
        claimed, vols_by_id, {}, client=_TestClientAdapter()
    )
    check("handle_job status==done", status == "done", f"status={status} error={error}")
    check(
        "result start_tc==10:00:00:00",
        (result or {}).get("start_tc") == "10:00:00:00",
        str(result),
    )
    check(
        "result uploaded==server",
        (result or {}).get("uploaded") == "server",
        str(result),
    )
    burned = (result or {}).get("burned_tc")
    # burned_tc puo' essere True o False a seconda della build ffmpeg (fontconfig)
    check(
        "result burned_tc e' bool",
        burned in (True, False),
        f"burned_tc={burned}",
    )
    print(f"  (burned_tc={burned} — dipende dalla build ffmpeg locale)")

    print("-- POST result al server --")
    r = c.post(
        f"/agent-api/jobs/{job_id}/result",
        headers=ah,
        json={"status": status, "result": result},
    )
    check("post result 200", r.status_code == 200, str(r.text))

    # Rileggi asset
    session.expire(asset)
    session.refresh(asset)
    check(
        "asset.preview_status==ready",
        asset.preview_status == "ready",
        f"got={asset.preview_status} error={asset.preview_error}",
    )
    check(
        "asset.preview_storage==local",
        asset.preview_storage == "local",
        f"got={asset.preview_storage}",
    )

    preview_file = Path(asset.preview_path) if asset.preview_path else None
    check(
        "file preview esiste",
        preview_file is not None and preview_file.is_file(),
        str(preview_file),
    )
    check(
        "file preview >10KB",
        preview_file is not None and preview_file.is_file()
        and preview_file.stat().st_size > 10_000,
        f"size={preview_file.stat().st_size if preview_file and preview_file.is_file() else 0}",
    )
    check(
        "preview_meta fps==25.0",
        (asset.preview_meta or {}).get("fps") == 25.0,
        f"meta={asset.preview_meta}",
    )

    print("-- GET /qc/api/assets/{id}/preview (streaming) --")
    r = c.get(f"/qc/api/assets/{asset_id}/preview")
    check(
        "preview GET 200 video/mp4",
        r.status_code == 200 and "video/mp4" in r.headers.get("content-type", ""),
        f"status={r.status_code} ct={r.headers.get('content-type')}",
    )

    print("-- GET preview con Range header --")
    r_range = c.get(
        f"/qc/api/assets/{asset_id}/preview",
        headers={"Range": "bytes=0-99"},
    )
    check(
        "Range bytes=0-99 → 206",
        r_range.status_code == 206,
        f"status={r_range.status_code}",
    )
    check(
        "content len==100",
        len(r_range.content) == 100,
        f"got={len(r_range.content)}",
    )

    print("-- GET /qc/api/assets/{id}/preview/status --")
    r = c.get(f"/qc/api/assets/{asset_id}/preview/status")
    check("status endpoint 200", r.status_code == 200, str(r.text))
    data = r.json()
    check("status==ready", data.get("status") == "ready", str(data))
    check(
        "meta.start_tc==10:00:00:00",
        (data.get("meta") or {}).get("start_tc") == "10:00:00:00",
        str(data),
    )

    print("-- rigenerazione: secondo POST generate → job NUOVO --")
    r2 = c.post(f"/qc/api/assets/{asset_id}/preview/generate")
    check("rigenera 200", r2.status_code == 200, str(r2.text))
    job_id_2 = r2.json().get("job_id")
    # Il primo job e' done, il secondo deve essere un job NUOVO (id diverso)
    check(
        "secondo job_id diverso dal primo",
        job_id_2 is not None and job_id_2 != job_id,
        f"first={job_id} second={job_id_2}",
    )

    print("-- check negativo: GET preview asset inesistente → 404 --")
    r_neg = c.get("/qc/api/assets/999999/preview")
    check("asset inesistente → 404", r_neg.status_code == 404, str(r_neg.status_code))

# ── Cleanup ──────────────────────────────────────────────────────────────────

main_mod.app.dependency_overrides.pop(get_db, None)
session.close()
shutil.rmtree(tmp_previews, ignore_errors=True)

# ── Report finale ─────────────────────────────────────────────────────────────
failed = [n for n, ok in OK if not ok]
print(f"\n{len(OK) - len(failed)}/{len(OK)} check passati")
sys.exit(1 if failed else 0)
