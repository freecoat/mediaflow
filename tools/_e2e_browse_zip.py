"""E2E offline browse + installer ZIP (spec 2026-06-11).

TestClient + DB in-memory: crea volume+agent, accoda browse dalla UI-API,
l'agent VERO (agent.main.handle_job) esegue il listing su una dir reale,
posta il risultato via /agent-api, la UI-API lo legge dal job. Poi installer.
"""
import io
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base
from app.models import User, Role, Tenant
from app.models.models import UserRole
from app.services.auth import create_access_token

import app.database as database
import app.main as main_mod
from app.database import get_db

OK = []
def check(name, cond, detail=""):
    OK.append((name, bool(cond)))
    print(("  ✓ " if cond else "  ✗ ") + name + (f"  [{detail}]" if detail and not cond else ""))

engine = create_engine("sqlite:///:memory:",
                       connect_args={"check_same_thread": False},
                       poolclass=StaticPool, future=True)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
database.engine = engine
database.SessionLocal = TestSession
session = TestSession()
session.add(Tenant(id=1, name="T", slug="t1", is_active=True))
session.flush()
role = Role(tenant_id=1, code="admin", name="Admin",
            permissions=["edit_planning_all"], is_system=True, is_active=True)
session.add(role)
session.flush()
session.add(User(tenant_id=1, email="admin@test.local", full_name="Admin",
                 hashed_password="x", role=UserRole.admin, role_id=role.id,
                 is_active=True))
session.commit()

def _ovr():
    yield session
main_mod.app.dependency_overrides[get_db] = _ovr
tok = create_access_token({"sub": "admin@test.local", "tid": 1})

with tempfile.TemporaryDirectory() as san:
    os.makedirs(os.path.join(san, "OUT", "GLO"))
    open(os.path.join(san, "OUT", "GLO", "ep01.mxf"), "wb").write(b"x" * 100)
    open(os.path.join(san, "readme.txt"), "w").write("ciao")

    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"},
                    follow_redirects=False) as c:
        print("— setup volume + agent —")
        r = c.post("/storage/api/volumes",
                   data={"name": "SAN", "mount_path": san, "watch_dirs": ""})
        vol_id = r.json()["id"]
        check("crea volume", r.status_code == 200)
        r = c.post("/storage/api/agents", data={"name": "ag-e2e"})
        agent_token = r.json()["token"]
        agent_id = r.json()["id"]
        check("crea agent (token plain)", r.status_code == 200 and agent_token)

        print("— browse round-trip (handle_job vero) —")
        r = c.post(f"/storage/api/volumes/{vol_id}/browse", data={"rel_path": ""})
        job_id = r.json()["job_id"]
        check("enqueue browse root", r.status_code == 200)

        ah = {"X-Agent-Token": agent_token}
        hb = c.post("/agent-api/heartbeat", json={"version": "0.1"}, headers=ah)
        volumes = hb.json()["volumes"]
        check("heartbeat agent", hb.status_code == 200 and volumes)
        claimed = c.post("/agent-api/jobs/claim", headers=ah).json()["job"]
        check("claim job browse", claimed and claimed["type"] == "browse")

        from agent.main import handle_job
        vols_by_id = {v["id"]: v for v in volumes}
        status, result, error = handle_job(claimed, vols_by_id, {})
        check("handle_job browse done", status == "done", str(error))
        r = c.post(f"/agent-api/jobs/{claimed['id']}/result", headers=ah,
                   json={"status": status, "result": result})
        check("post result", r.status_code == 200)

        j = c.get(f"/storage/api/jobs/{job_id}").json()
        names = [e["name"] for e in (j.get("result") or {}).get("entries", [])]
        check("poll job → entries", j["status"] == "done" and names == ["OUT", "readme.txt"], str(names))

        # naviga in OUT/GLO
        r = c.post(f"/storage/api/volumes/{vol_id}/browse", data={"rel_path": "OUT/GLO"})
        job2 = r.json()["job_id"]
        claimed2 = c.post("/agent-api/jobs/claim", headers=ah).json()["job"]
        status2, result2, _ = handle_job(claimed2, vols_by_id, {})
        c.post(f"/agent-api/jobs/{claimed2['id']}/result", headers=ah,
               json={"status": status2, "result": result2})
        j2 = c.get(f"/storage/api/jobs/{job2}").json()
        e2 = (j2.get("result") or {}).get("entries", [])
        check("browse subdir OUT/GLO", [x["name"] for x in e2] == ["ep01.mxf"]
              and e2[0]["size"] == 100, str(e2))

        # traversal → failed
        r = c.post(f"/storage/api/volumes/{vol_id}/browse", data={"rel_path": "../../etc"})
        job3 = r.json()["job_id"]
        claimed3 = c.post("/agent-api/jobs/claim", headers=ah).json()["job"]
        status3, _, err3 = handle_job(claimed3, vols_by_id, {})
        check("traversal → failed", status3 == "failed" and "fuori dal volume" in (err3 or ""), str(err3))

        print("— installer ZIP —")
        r = c.get(f"/storage/api/agents/{agent_id}/installer?server_url=https://claqo.example.com")
        check("download 200 zip", r.status_code == 200 and "application/zip" in r.headers["content-type"])
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        cfg = json.loads(zf.read("claqo-agent/claqo-agent.json"))
        check("config server_url passato", cfg["server_url"] == "https://claqo.example.com")
        check("zip ha agent/browse.py", "claqo-agent/agent/browse.py" in zf.namelist())
        # vecchio token invalidato, nuovo valido
        old = c.post("/agent-api/jobs/claim", headers=ah)
        check("vecchio token 401", old.status_code == 401)
        new = c.post("/agent-api/jobs/claim", headers={"X-Agent-Token": cfg["token"]})
        check("nuovo token valido", new.status_code == 200)

main_mod.app.dependency_overrides.pop(get_db, None)
session.close()
failed = [n for n, ok in OK if not ok]
print(f"\n{len(OK) - len(failed)}/{len(OK)} check passati")
sys.exit(1 if failed else 0)
