"""E2E offline SAL — Stato Avanzamento Lavori: projects + detail + timeline.

TestClient + DB in-memory, utente admin con view_finance.

Seed:
  - Cliente + Progetto (deleted_at None) + 2 Job.
  - Job1: JCL unit="hr" qty=10 + unit="day" qty=1 (→+8h = 18h quotate) + unit="pc" qty=5 (esclusa).
  - Job2: JCL unit="hr" qty=4 (quotate).
  - Booking Job1: done 09-17 (8h) + non-done 09-13 (4h); entrambi gen-2026.
  - Booking Job2: done 09-19 (10h) → SFORA su 4h quotate → alarm red.
  - Invoice non-draft (TD01, marzo 2026) subtotal=5000.

Aspettative:
  - GET /finance/api/sal/projects:
      quoted = 18+4 = 22, worked = 8+10 = 18, planned = 8+4+10 = 22,
      pct = 18/22, alarm = "red" (Job2 worked 10>4 quoted).
  - Filtri alarm_only / client_id / q.
  - GET /finance/api/sal/projects/{id}/detail: 2 job, breakdown reparto DI/Video + Altro.
  - GET /finance/api/sal/timeline?year=2026&granularity=month: mese-gen worked/planned presenti,
    mese-mar invoiced 5000; granularity=quarter aggrega.
  - 404 su project inesistente.
"""
import os
import sys
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base,
    Booking, BookingStatus, BookingExecutionStatus,
    Client,
    Department,
    Invoice, InvoiceStatus,
    Job, JobCostLine,
    PriceCategory, PriceItem,
    Project,
    Quote,
    Tenant,
    User, UserRole,
)
from app.models import Role
from app.services.auth import create_access_token

import app.database as database
import app.main as main_mod
from app.database import get_db

# ── Contatori check ────────────────────────────────────────────────────────────

OK = []


def check(name, cond, detail=""):
    OK.append((name, bool(cond)))
    marker = "  OK " if cond else "  FAIL "
    line = marker + name
    if detail and not cond:
        line += f"  [{detail}]"
    print(line)


# ── DB in-memory ───────────────────────────────────────────────────────────────

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

# Tenant
session.add(Tenant(id=1, name="TestCo", slug="testco", is_active=True))
session.flush()

# Ruolo con view_finance
role = Role(
    tenant_id=1,
    code="admin",
    name="Admin",
    permissions=["view_finance"],
    is_system=True,
    is_active=True,
)
session.add(role)
session.flush()

# Utente admin
admin = User(
    tenant_id=1,
    email="admin@test.local",
    full_name="Admin SAL",
    hashed_password="x",
    role=UserRole.admin,
    role_id=role.id,
    is_active=True,
)
session.add(admin)
session.commit()
session.refresh(admin)
uid = admin.id

# Reparto DI/Video (quotato della JCL DI)
dep_di = Department(tenant_id=1, code="DI-VIDEO", name="DI/Video")
session.add(dep_di)
session.flush()

# PriceCategory + PriceItem per le JCL
cat = PriceCategory(tenant_id=1, name="Lavorazione")
session.add(cat)
session.flush()

pi_di = PriceItem(tenant_id=1, category_id=cat.id, name="Color",
                  unit="hr", department_id=dep_di.id)
pi_daily = PriceItem(tenant_id=1, category_id=cat.id, name="Giornata Sala",
                     unit="day", department_id=dep_di.id)
pi_audio = PriceItem(tenant_id=1, category_id=cat.id, name="Mix Audio",
                     unit="hr", department_id=None)   # no dept → "Altro"
session.add_all([pi_di, pi_daily, pi_audio])
session.flush()

# Cliente + Progetto + Quote
cli = Client(tenant_id=1, name="ClienteSAL-E2E")
session.add(cli)
session.flush()
cli_id = cli.id

proj = Project(tenant_id=1, code="ESAL-001", title="Progetto SAL E2E",
               client_id=cli_id)
session.add(proj)
session.flush()
proj_id = proj.id

quote = Quote(tenant_id=1, number="Q-2026-E01", title="Quote SAL E2E",
              project_id=proj_id, client_id=cli_id, issue_date=date(2026, 1, 1))
session.add(quote)
session.flush()

# Job1: quotato 10h (hr) + 1 giorno (day, →8h) + 5 pezzi (pc, esclusa) = 18h totali
job1 = Job(tenant_id=1, code="E-SAL-1", title="Job Color",
           project_id=proj_id, client_id=cli_id, quote_id=quote.id)
session.add(job1)
session.flush()
job1_id = job1.id

session.add(JobCostLine(tenant_id=1, job_id=job1_id, description="Color ore",
                        unit="hr", quantity_quoted=10.0, unit_price=100.0,
                        price_item_id=pi_di.id))
session.add(JobCostLine(tenant_id=1, job_id=job1_id, description="Giornata sala",
                        unit="day", quantity_quoted=1.0, unit_price=800.0,
                        price_item_id=pi_daily.id))
session.add(JobCostLine(tenant_id=1, job_id=job1_id, description="Hard cost forfait",
                        unit="pc", quantity_quoted=5.0, unit_price=50.0,
                        price_item_id=None))
session.flush()

# Job2: quotato 4h (hr) — sarà in sforamento (lavorato 10h → alarm red)
job2 = Job(tenant_id=1, code="E-SAL-2", title="Job Mix Audio",
           project_id=proj_id, client_id=cli_id, quote_id=None)
session.add(job2)
session.flush()
job2_id = job2.id

session.add(JobCostLine(tenant_id=1, job_id=job2_id, description="Mix audio",
                        unit="hr", quantity_quoted=4.0, unit_price=120.0,
                        price_item_id=pi_audio.id))
session.flush()

# Booking Job1: done 09-17 (8h) in gennaio — shell-duration, no assignment
session.add(Booking(
    tenant_id=1, job_id=job1_id,
    start_datetime=datetime(2026, 1, 10, 9, 0),
    end_datetime=datetime(2026, 1, 10, 17, 0),
    status=BookingStatus.confirmed,
    execution_status=BookingExecutionStatus.done,
))
# Booking Job1: non-done 09-13 (4h) in gennaio
session.add(Booking(
    tenant_id=1, job_id=job1_id,
    start_datetime=datetime(2026, 1, 11, 9, 0),
    end_datetime=datetime(2026, 1, 11, 13, 0),
    status=BookingStatus.confirmed,
    execution_status=BookingExecutionStatus.planned,
))
# Booking Job2: done 09-19 (10h) — SFORA su 4h quotate → alarm red
session.add(Booking(
    tenant_id=1, job_id=job2_id,
    start_datetime=datetime(2026, 1, 15, 9, 0),
    end_datetime=datetime(2026, 1, 15, 19, 0),
    status=BookingStatus.confirmed,
    execution_status=BookingExecutionStatus.done,
))
session.flush()

# Invoice non-draft (marzo 2026) subtotal=5000
session.add(Invoice(
    tenant_id=1, number="2026-E001", client_id=cli_id, job_id=job1_id,
    status=InvoiceStatus.sent, issue_date=date(2026, 3, 20),
    subtotal=5000.0, doc_type="TD01",
))
session.commit()


def _ovr():
    yield session


main_mod.app.dependency_overrides[get_db] = _ovr
tok = create_access_token({"sub": "admin@test.local", "tid": 1})

# Imposta tenant context (richiesto da timeline_metrics via current_tenant_id())
from app.context import set_tenant_id
set_tenant_id(1)

# ── Valori attesi ──────────────────────────────────────────────────────────────
# quoted:  Job1 = 10h (hr) + 1*8h (day) = 18; Job2 = 4h → totale 22
# planned: Job1 = 8+4 = 12; Job2 = 10 → totale 22
# worked:  Job1 = 8;  Job2 = 10 → totale 18
# pct:     18/22
# alarm:   red (Job2: worked 10 > quoted 4)

EXP_QUOTED = 22.0
EXP_PLANNED = 22.0
EXP_WORKED = 18.0
EXP_PCT = 18.0 / 22.0

with TestClient(
    main_mod.app,
    headers={"Cookie": f"access_token={tok}"},
    follow_redirects=False,
) as c:

    # ── A. GET /finance/api/sal/projects (lista) ───────────────────────────────

    print("-- A. GET /finance/api/sal/projects --")
    r = c.get("/finance/api/sal/projects")
    check("A1: 200 OK", r.status_code == 200, str(r.text)[:300])
    rows = r.json() if r.status_code == 200 else []
    check("A2: 1 progetto (tenant scope)", len(rows) == 1, f"len={len(rows)}")

    if rows:
        row = rows[0]
        check("A3: client name corretto", row.get("client") == "ClienteSAL-E2E",
              f"client={row.get('client')}")
        check("A4: code ESAL-001", row.get("code") == "ESAL-001",
              f"code={row.get('code')}")
        check("A5: quoted=22", abs(row.get("quoted", -1) - EXP_QUOTED) < 0.01,
              f"quoted={row.get('quoted')}")
        check("A6: planned=22", abs(row.get("planned", -1) - EXP_PLANNED) < 0.01,
              f"planned={row.get('planned')}")
        check("A7: worked=18", abs(row.get("worked", -1) - EXP_WORKED) < 0.01,
              f"worked={row.get('worked')}")
        check("A8: pct ≈ 18/22", abs(row.get("pct", -1) - EXP_PCT) < 0.001,
              f"pct={row.get('pct')}")
        check("A9: alarm==red", row.get("alarm") == "red",
              f"alarm={row.get('alarm')}")
        check("A10: job_count==2", row.get("job_count") == 2,
              f"job_count={row.get('job_count')}")
        quotes_list = row.get("quotes", [])
        check("A11: quotazione Q-2026-E01 presente",
              any(q.get("number") == "Q-2026-E01" for q in quotes_list),
              f"quotes={quotes_list}")

    # ── B. Filtri ──────────────────────────────────────────────────────────────

    print("-- B. Filtri --")
    r_alarm = c.get("/finance/api/sal/projects?alarm_only=true")
    check("B1: alarm_only=true → 200", r_alarm.status_code == 200, r_alarm.text[:200])
    check("B2: alarm_only include red", len(r_alarm.json()) >= 1,
          f"len={len(r_alarm.json())}")

    r_cli = c.get(f"/finance/api/sal/projects?client_id={cli_id}")
    check("B3: client_id match → 1 riga", len(r_cli.json()) == 1,
          f"len={len(r_cli.json())}")
    r_cli_no = c.get("/finance/api/sal/projects?client_id=99999")
    check("B4: client_id inesistente → vuoto", r_cli_no.json() == [],
          f"body={r_cli_no.json()}")

    r_q = c.get("/finance/api/sal/projects?q=ESAL")
    check("B5: q=ESAL → match", len(r_q.json()) == 1,
          f"len={len(r_q.json())}")
    r_q_no = c.get("/finance/api/sal/projects?q=zzznomatch")
    check("B6: q=zzznomatch → vuoto", r_q_no.json() == [],
          f"body={r_q_no.json()}")

    # ── C. GET /finance/api/sal/projects/{id}/detail ───────────────────────────

    print("-- C. GET /finance/api/sal/projects/{id}/detail --")
    r_det = c.get(f"/finance/api/sal/projects/{proj_id}/detail")
    check("C1: detail 200", r_det.status_code == 200, r_det.text[:300])
    if r_det.status_code == 200:
        det = r_det.json()
        jobs_list = det.get("jobs", [])
        depts_list = det.get("departments", [])
        check("C2: 2 job", len(jobs_list) == 2, f"jobs={[j.get('code') for j in jobs_list]}")
        codes = {j.get("code") for j in jobs_list}
        check("C3: codici E-SAL-1 e E-SAL-2", codes == {"E-SAL-1", "E-SAL-2"},
              f"codes={codes}")
        # Job2 deve essere red
        j2 = next((j for j in jobs_list if j.get("code") == "E-SAL-2"), None)
        check("C4: Job2 alarm==red", j2 and j2.get("alarm") == "red",
              f"j2={j2}")
        check("C5: Job2 worked=10", j2 and abs(j2.get("worked", -1) - 10.0) < 0.01,
              f"worked={j2.get('worked') if j2 else 'n/a'}")
        # Breakdown reparto: DI/Video quotato = 10+8 = 18; Altro (audio JCL dept=None) = 4
        dept_by_name = {d.get("name"): d for d in depts_list}
        check("C6: DI/Video presente", "DI/Video" in dept_by_name,
              f"depts={list(dept_by_name.keys())}")
        if "DI/Video" in dept_by_name:
            check("C7: DI/Video quoted=18",
                  abs(dept_by_name["DI/Video"].get("quoted", -1) - 18.0) < 0.01,
                  f"quoted={dept_by_name['DI/Video'].get('quoted')}")
        check("C8: Altro presente (no-dept fallback)", "Altro" in dept_by_name,
              f"depts={list(dept_by_name.keys())}")
        if "Altro" in dept_by_name:
            check("C9: Altro quoted=4",
                  abs(dept_by_name["Altro"].get("quoted", -1) - 4.0) < 0.01,
                  f"quoted={dept_by_name['Altro'].get('quoted')}")

    # ── D. 404 su project inesistente ─────────────────────────────────────────

    print("-- D. 404 project inesistente --")
    r_404 = c.get("/finance/api/sal/projects/99999/detail")
    check("D1: 404 not found", r_404.status_code == 404,
          f"status={r_404.status_code}")

    # ── E. GET /finance/api/sal/timeline ──────────────────────────────────────

    print("-- E. GET /finance/api/sal/timeline?year=2026&granularity=month --")
    r_tl = c.get("/finance/api/sal/timeline?year=2026&granularity=month")
    check("E1: timeline 200", r_tl.status_code == 200, r_tl.text[:300])
    if r_tl.status_code == 200:
        tl = r_tl.json()
        check("E2: year=2026", tl.get("year") == 2026, f"year={tl.get('year')}")
        check("E3: 12 periodi (month)", len(tl.get("periods", [])) == 12,
              f"len={len(tl.get('periods', []))}")
        by_label = {p["label"]: p for p in tl.get("periods", [])}
        # Gennaio: Job1 done 8h + Job1 non-done 4h + Job2 done 10h → planned=22, worked=18
        jan = by_label.get("2026-01", {})
        check("E4: gen planned=22",
              abs(jan.get("planned", -1) - 22.0) < 0.01,
              f"planned_jan={jan.get('planned')}")
        check("E5: gen worked=18",
              abs(jan.get("worked", -1) - 18.0) < 0.01,
              f"worked_jan={jan.get('worked')}")
        # Marzo: fatturato 5000
        mar = by_label.get("2026-03", {})
        check("E6: mar invoiced=5000",
              abs(mar.get("invoiced", -1) - 5000.0) < 0.01,
              f"invoiced_mar={mar.get('invoiced')}")
        # Totale anno: worked=18, planned=22, invoiced=5000
        tot = tl.get("total", {})
        check("E7: total worked=18",
              abs(tot.get("worked", -1) - 18.0) < 0.01,
              f"total_worked={tot.get('worked')}")
        check("E8: total planned=22",
              abs(tot.get("planned", -1) - 22.0) < 0.01,
              f"total_planned={tot.get('planned')}")
        check("E9: total invoiced=5000",
              abs(tot.get("invoiced", -1) - 5000.0) < 0.01,
              f"total_invoiced={tot.get('invoiced')}")

    print("-- E. GET /finance/api/sal/timeline?year=2026&granularity=quarter --")
    r_tq = c.get("/finance/api/sal/timeline?year=2026&granularity=quarter")
    check("E10: quarter 200", r_tq.status_code == 200, r_tq.text[:200])
    if r_tq.status_code == 200:
        tq = r_tq.json()
        check("E11: 4 periodi (quarter)", len(tq.get("periods", [])) == 4,
              f"len={len(tq.get('periods', []))}")
        by_q = {p["label"]: p for p in tq.get("periods", [])}
        # Q1 = gen+feb+mar: worked=18, planned=22, invoiced=5000
        q1 = by_q.get("Q1", {})
        check("E12: Q1 worked=18",
              abs(q1.get("worked", -1) - 18.0) < 0.01,
              f"q1_worked={q1.get('worked')}")
        check("E13: Q1 planned=22",
              abs(q1.get("planned", -1) - 22.0) < 0.01,
              f"q1_planned={q1.get('planned')}")
        check("E14: Q1 invoiced=5000",
              abs(q1.get("invoiced", -1) - 5000.0) < 0.01,
              f"q1_invoiced={q1.get('invoiced')}")

# ── Cleanup ────────────────────────────────────────────────────────────────────

main_mod.app.dependency_overrides.pop(get_db, None)
session.close()

# ── Report finale ──────────────────────────────────────────────────────────────

failed = [n for n, ok in OK if not ok]
print(f"\n{len(OK) - len(failed)}/{len(OK)} check passati")
if failed:
    print("FALLITI:")
    for n in failed:
        print(f"  - {n}")
sys.exit(1 if failed else 0)
