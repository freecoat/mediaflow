"""E2E offline F4 — Catalogo LTO + ticket archivio/restore end-to-end.

TestClient + DB in-memory: ingest MHL sintetico, membership, re-ingest
idempotente, memberships GET, ticket restore → in_progress → done,
ticket archive → done, archive senza membership → 400, CSV terza entry,
lista ticket done.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, AssetType, AssetContentState
from app.models import User, Role, Tenant
from app.models.models import UserRole
from app.services.auth import create_access_token

import app.database as database
import app.main as main_mod
from app.database import get_db

# ── Contatori check ───────────────────────────────────────────────────────────

OK = []


def check(name, cond, detail=""):
    OK.append((name, bool(cond)))
    marker = "  OK " if cond else "  FAIL "
    line = marker + name
    if detail and not cond:
        line += f"  [{detail}]"
    print(line)


# ── DB in-memory ──────────────────────────────────────────────────────────────

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
    permissions=["edit_planning_all", "view_finance", "assign_resources",
                 "edit_deliverables"],
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

# ── Seed: Client → Project → Job + Asset nel registry ────────────────────────

from app.models.models import Client, Project, Job, Asset

client = Client(tenant_id=1, name="TestClient")
session.add(client)
session.flush()

project = Project(
    tenant_id=1,
    code="PRJ-E2E-F4",
    title="E2E F4 Progetto",
    client_id=client.id,
)
session.add(project)
session.flush()

job = Job(
    tenant_id=1,
    code="JOB-E2E-F4",
    title="E2E F4 Job",
    project_id=project.id,
    client_id=client.id,
)
session.add(job)
session.flush()

# Asset nel registry con checksum noto
asset = Asset(
    tenant_id=1,
    filename="ep01.mxf",
    original_name="ep01.mxf",
    file_path="",
    file_size=1000,
    mime_type="video/mxf",
    asset_type=AssetType.video,
    uploaded_by=1,
    checksum_xxhash="aabbccdd11223344",
)
session.add(asset)
session.commit()
session.refresh(asset)
asset_id = asset.id

# Asset senza membership (per test check 8)
asset_no_memb = Asset(
    tenant_id=1,
    filename="nomembership.mxf",
    original_name="nomembership.mxf",
    file_path="",
    file_size=500,
    mime_type="video/mxf",
    asset_type=AssetType.video,
    uploaded_by=1,
)
session.add(asset_no_memb)
session.commit()
session.refresh(asset_no_memb)
asset_no_memb_id = asset_no_memb.id

# ── MHL sintetico: 2 entry (ep01.mxf match + unknown.wav orfano) ─────────────

MHL_2_ENTRIES = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<hashlist version="1">
  <creatorinfo>
    <tool>Yoyotta</tool>
  </creatorinfo>
  <hash>
    <file>ep01.mxf</file>
    <size>1000</size>
    <xxhash64>aabbccdd11223344</xxhash64>
  </hash>
  <hash>
    <file>unknown.wav</file>
    <size>200</size>
    <xxhash64>ffffffff00000000</xxhash64>
  </hash>
</hashlist>
"""

TAPE_LABEL = "LTO-E2E-042"

with TestClient(
    main_mod.app,
    headers={"Cookie": f"access_token={tok}"},
    follow_redirects=False,
) as c:

    print("-- Step 1-2: POST /ingest/yoyotta-mhl (2 entry) --")
    r = c.post(
        "/ingest/yoyotta-mhl",
        files={"file": ("ep01_tape.mhl", io.BytesIO(MHL_2_ENTRIES), "application/xml")},
        data={"job_id": str(job.id), "tape_label": TAPE_LABEL},
    )
    check("ingest MHL 200", r.status_code == 200, str(r.text))
    body = r.json()
    tape_id = body.get("physical_asset_id")
    check("physical_asset_id presente", tape_id is not None, str(body))
    memb = body.get("membership", {})
    check("membership matched==1", memb.get("matched") == 1, str(memb))
    check("membership orphan==1", memb.get("orphan") == 1, str(memb))
    check("membership skipped==0", memb.get("skipped") == 0, str(memb))

    print("-- Step 3: re-ingest stesso MHL → skipped==2 --")
    r2 = c.post(
        "/ingest/yoyotta-mhl",
        files={"file": ("ep01_tape.mhl", io.BytesIO(MHL_2_ENTRIES), "application/xml")},
        data={"job_id": str(job.id), "tape_label": TAPE_LABEL + "-B"},
    )
    check("re-ingest 200", r2.status_code == 200, str(r2.text))
    # Questo crea un NUOVO tape — verifica che le membership del tape2 abbiano skipped=2
    # (perché ingest_catalog_entries è idempotente per checksum per tape, MA ogni tape è
    # un nuovo PhysicalAsset, quindi skipped=0 per il tape2. Lo step è:
    # stessa cassetta: usa catalog-csv sullo stesso tape per testare idempotenza)
    # Usiamo il tape originale via catalog-csv con lo stesso contenuto
    CSV_SAME = b"filename,size_bytes,checksum\nep01.mxf,1000,aabbccdd11223344\nunknown.wav,200,ffffffff00000000\n"
    r_csv_idem = c.post(
        f"/physical-assets/api/{tape_id}/catalog-csv",
        files={"file": ("catalog.csv", io.BytesIO(CSV_SAME), "text/csv")},
    )
    check("catalog-csv re-ingest 200", r_csv_idem.status_code == 200,
          str(r_csv_idem.text))
    memb2 = r_csv_idem.json()
    check("re-ingest via CSV skipped==2", memb2.get("skipped") == 2,
          str(memb2))

    print("-- Step 4: GET /physical-assets/api/{tape_id}/memberships → 2 righe --")
    r3 = c.get(f"/physical-assets/api/{tape_id}/memberships")
    check("memberships 200", r3.status_code == 200, str(r3.text))
    rows = r3.json()
    check("memberships == 2 righe", len(rows) == 2, f"got={len(rows)}")
    filenames_on_tape = {m.get("path_on_media") or m.get("filename") for m in rows}
    check("ep01.mxf presente", "ep01.mxf" in filenames_on_tape, str(filenames_on_tape))
    orphan_rows = [m for m in rows if m.get("asset_id") is None]
    matched_rows = [m for m in rows if m.get("asset_id") is not None]
    check("1 orfana (asset_id None)", len(orphan_rows) == 1, str(orphan_rows))
    check("1 matched (asset_id not None)", len(matched_rows) == 1, str(matched_rows))

    print("-- Step 5: ticket restore via POST /storage/api/tickets --")
    r_restore = c.post(
        "/storage/api/tickets",
        data={"kind": "restore", "asset_id": str(asset_id)},
    )
    check("crea ticket restore 200", r_restore.status_code == 200,
          str(r_restore.text))
    ticket_restore_id = r_restore.json().get("id")
    check("ticket_restore_id presente", ticket_restore_id is not None,
          str(r_restore.json()))

    # GET ticket → tape suggerito è un LTO (quello con membership più recente sull'asset)
    r_list = c.get("/storage/api/tickets", params={"kind": "restore"})
    check("lista ticket 200", r_list.status_code == 200, str(r_list.text))
    tlist = r_list.json()
    t_found = next((t for t in tlist if t["id"] == ticket_restore_id), None)
    check("ticket restore presente nella lista", t_found is not None, str(tlist))
    tape_suggested = (t_found or {}).get("tape")
    # Il service suggerisce il tape con membership attiva più recente sull'asset.
    # Dopo il re-ingest MHL (Step 3) un secondo tape ha membership su ep01.mxf:
    # il servizio restituisce quello più recente — è comportamento corretto.
    check(
        "tape suggerito presente (LTO con membership sull'asset)",
        tape_suggested is not None and tape_suggested.get("id") is not None,
        f"tape_suggested={tape_suggested}",
    )

    print("-- Step 6: transition requested → in_progress → done --")
    r_prog = c.post(
        f"/storage/api/tickets/{ticket_restore_id}/transition",
        data={"status": "in_progress"},
    )
    check("→ in_progress 200", r_prog.status_code == 200, str(r_prog.text))
    check("status==in_progress", r_prog.json().get("status") == "in_progress",
          str(r_prog.json()))

    r_done = c.post(
        f"/storage/api/tickets/{ticket_restore_id}/transition",
        data={"status": "done"},
    )
    check("→ done 200", r_done.status_code == 200, str(r_done.text))
    check("status==done (restore)", r_done.json().get("status") == "done",
          str(r_done.json()))

    # Verifica content_state == online + notifica al richiedente
    session.expire(asset)
    session.refresh(asset)
    check(
        "Asset.content_state==online dopo restore done",
        asset.content_state == AssetContentState.online,
        f"got={asset.content_state}",
    )
    from app.models.models import Notification
    notifs = session.query(Notification).filter(
        Notification.tenant_id == 1,
        Notification.user_id == 1,
        Notification.kind == "archive_ticket",
    ).all()
    check("notifica al richiedente presente", len(notifs) >= 1, f"notifs={len(notifs)}")

    print("-- Step 7: ticket archive stesso asset → done --")
    r_arc = c.post(
        "/storage/api/tickets",
        data={"kind": "archive", "asset_id": str(asset_id)},
    )
    check("crea ticket archive 200", r_arc.status_code == 200, str(r_arc.text))
    ticket_archive_id = r_arc.json().get("id")
    check("ticket_archive_id presente", ticket_archive_id is not None,
          str(r_arc.json()))

    r_arc_done = c.post(
        f"/storage/api/tickets/{ticket_archive_id}/transition",
        data={"status": "done"},
    )
    check("archive → done 200", r_arc_done.status_code == 200, str(r_arc_done.text))
    check("status==done (archive)", r_arc_done.json().get("status") == "done",
          str(r_arc_done.json()))

    session.expire(asset)
    session.refresh(asset)
    check(
        "Asset.content_state==archived_only dopo archive done",
        asset.content_state == AssetContentState.archived_only,
        f"got={asset.content_state}",
    )

    print("-- Step 8: archive su asset SENZA membership → transition done → 400 --")
    r_arc2 = c.post(
        "/storage/api/tickets",
        data={"kind": "archive", "asset_id": str(asset_no_memb_id)},
    )
    check("crea ticket archive (no memb) 200", r_arc2.status_code == 200,
          str(r_arc2.text))
    ticket_no_memb_id = r_arc2.json().get("id")

    r_no_memb_done = c.post(
        f"/storage/api/tickets/{ticket_no_memb_id}/transition",
        data={"status": "done"},
    )
    check(
        "archive senza membership → 400",
        r_no_memb_done.status_code == 400,
        f"status={r_no_memb_done.status_code} body={r_no_memb_done.text}",
    )

    print("-- Step 9: CSV upload con 1 file nuovo sul tape → orphan==1 --")
    CSV_NEW = b"filename,size_bytes,checksum\nthird_file.dcp,9999,1234567890abcdef\n"
    r_csv3 = c.post(
        f"/physical-assets/api/{tape_id}/catalog-csv",
        files={"file": ("new.csv", io.BytesIO(CSV_NEW), "text/csv")},
    )
    check("CSV nuova entry 200", r_csv3.status_code == 200, str(r_csv3.text))
    stats3 = r_csv3.json()
    # third_file.dcp: non è nel registry → orfana
    check("CSV nuovo file → orphan==1", stats3.get("orphan") == 1, str(stats3))
    check("CSV nuovo file → matched==0", stats3.get("matched") == 0, str(stats3))
    check("CSV nuovo file → skipped==0", stats3.get("skipped") == 0, str(stats3))

    print("-- Step 10: GET /storage/api/tickets?status=done → contiene i 2 chiusi --")
    r_done_list = c.get("/storage/api/tickets", params={"status": "done"})
    check("lista done 200", r_done_list.status_code == 200, str(r_done_list.text))
    done_tickets = r_done_list.json()
    done_ids = {t["id"] for t in done_tickets}
    check(
        "ticket restore done presente",
        ticket_restore_id in done_ids,
        f"done_ids={done_ids}",
    )
    check(
        "ticket archive done presente",
        ticket_archive_id in done_ids,
        f"done_ids={done_ids}",
    )

# ── Cleanup ───────────────────────────────────────────────────────────────────

main_mod.app.dependency_overrides.pop(get_db, None)
session.close()

# ── Report finale ─────────────────────────────────────────────────────────────

failed = [n for n, ok in OK if not ok]
print(f"\n{len(OK) - len(failed)}/{len(OK)} check passati")
sys.exit(1 if failed else 0)
