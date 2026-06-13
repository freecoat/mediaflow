"""SAL — endpoint /finance/sal (spec 2026-06-12, Task 2).

Copertura:
  - timeline_metrics: 2 booking in mesi diversi (done/non) + 1 Invoice
    non-draft → periodi mese, aggregazione trimestre, totale.
  - GET /finance/api/sal/projects → shape + filtri status/client_id/q/alarm_only
    + tenant scope (progetto altro tenant escluso).
  - GET /finance/api/sal/projects/{id}/detail → breakdown reparto + jobs + 404.
  - GET /finance/sal → 200 (pagina).

Fixture client_admin con permesso view_finance (pattern test_f6_endpoints).
Booking ore via shell-duration (start/end, no assignment) per determinismo.
"""
from datetime import datetime, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

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


# ── Fixture client_admin (view_finance) ───────────────────────────────────────

@pytest.fixture
def client_admin(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    from app.services.auth import create_access_token

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    session = TestSession()

    session.add(Tenant(id=1, name="TestCo", slug="testco", is_active=True))
    session.add(Tenant(id=2, name="OtherCo", slug="otherco", is_active=True))
    session.flush()

    role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["view_finance"],
        is_system=True, is_active=True,
    )
    session.add(role)
    session.flush()

    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin User",
        hashed_password="x", role=UserRole.admin, role_id=role.id,
        is_active=True,
    )
    session.add(admin)
    session.flush()

    # ── Reparti ─────────────────────────────────────────────────────
    dep_di = Department(tenant_id=1, code="DI-VIDEO", name="DI/Video")
    dep_audio = Department(tenant_id=1, code="AUDIO", name="Audio")
    session.add_all([dep_di, dep_audio]); session.flush()

    cat = PriceCategory(tenant_id=1, name="Cat")
    session.add(cat); session.flush()
    pi_di = PriceItem(tenant_id=1, category_id=cat.id, name="Color",
                      unit="hr", department_id=dep_di.id)
    pi_audio = PriceItem(tenant_id=1, category_id=cat.id, name="Mix",
                         unit="hr", department_id=dep_audio.id)
    session.add_all([pi_di, pi_audio]); session.flush()

    # ── Cliente + progetto + 2 job ──────────────────────────────────
    cli = Client(tenant_id=1, name="ClienteSAL")
    session.add(cli); session.flush()
    proj = Project(tenant_id=1, code="PSAL", title="Progetto SAL",
                   client_id=cli.id)
    session.add(proj); session.flush()

    quote = Quote(tenant_id=1, number="Q-2026-001", title="Quote SAL",
                  project_id=proj.id, client_id=cli.id, issue_date=date(2026, 1, 1))
    session.add(quote); session.flush()

    # Job 1: quotato 10h DI, lavorato 8h done → none/amber? 8/10=80% → none.
    job1 = Job(tenant_id=1, code="J-SAL-1", title="Job 1",
               project_id=proj.id, client_id=cli.id, quote_id=quote.id)
    session.add(job1); session.flush()
    session.add(JobCostLine(tenant_id=1, job_id=job1.id, description="Color",
                            unit="hr", quantity_quoted=10.0, unit_price=100.0,
                            price_item_id=pi_di.id))
    # Job 2: quotato 4h Audio, lavorato 8h done → red (sforamento).
    job2 = Job(tenant_id=1, code="J-SAL-2", title="Job 2",
               project_id=proj.id, client_id=cli.id)
    session.add(job2); session.flush()
    session.add(JobCostLine(tenant_id=1, job_id=job2.id, description="Mix",
                            unit="hr", quantity_quoted=4.0, unit_price=100.0,
                            price_item_id=pi_audio.id))
    session.flush()

    # ── Booking (shell-duration, no assignment) ─────────────────────
    # job1: 8h done (gennaio)
    session.add(Booking(
        tenant_id=1, job_id=job1.id,
        start_datetime=datetime(2026, 1, 10, 9, 0),
        end_datetime=datetime(2026, 1, 10, 17, 0),
        status=BookingStatus.confirmed,
        execution_status=BookingExecutionStatus.done,
    ))
    # job2: 8h done (aprile) → sforamento su quotato 4h
    session.add(Booking(
        tenant_id=1, job_id=job2.id,
        start_datetime=datetime(2026, 4, 5, 9, 0),
        end_datetime=datetime(2026, 4, 5, 17, 0),
        status=BookingStatus.confirmed,
        execution_status=BookingExecutionStatus.done,
    ))
    # booking planned (non-done) job1 in aprile, 4h
    session.add(Booking(
        tenant_id=1, job_id=job1.id,
        start_datetime=datetime(2026, 4, 6, 9, 0),
        end_datetime=datetime(2026, 4, 6, 13, 0),
        status=BookingStatus.confirmed,
        execution_status=BookingExecutionStatus.planned,
    ))
    session.flush()

    # ── Fattura non-draft (marzo) ───────────────────────────────────
    session.add(Invoice(
        tenant_id=1, number="2026-0001", client_id=cli.id, job_id=job1.id,
        status=InvoiceStatus.sent, issue_date=date(2026, 3, 15),
        subtotal=5000.0, doc_type="TD01",
    ))
    # Nota di credito TD04 (aprile) → segno -1
    session.add(Invoice(
        tenant_id=1, number="2026-0002", client_id=cli.id, job_id=job1.id,
        status=InvoiceStatus.sent, issue_date=date(2026, 4, 20),
        subtotal=1000.0, doc_type="TD04",
    ))
    # Bozza → esclusa
    session.add(Invoice(
        tenant_id=1, number="2026-0003", client_id=cli.id, job_id=job1.id,
        status=InvoiceStatus.draft, issue_date=date(2026, 3, 1),
        subtotal=9999.0, doc_type="TD01",
    ))

    # ── Progetto di altro tenant (NON deve apparire) ────────────────
    cli2 = Client(tenant_id=2, name="ClienteAltro")
    session.add(cli2); session.flush()
    proj2 = Project(tenant_id=2, code="POTHER", title="Progetto Altro",
                    client_id=cli2.id)
    session.add(proj2); session.flush()

    session.commit()

    session._proj_id = proj.id
    session._cli_id = cli.id
    session._job1_id = job1.id
    session._job2_id = job2.id
    session._dep_di_id = dep_di.id
    session._dep_audio_id = dep_audio.id

    def _override():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override
    token = create_access_token({"sub": "admin@test.local", "tid": 1})
    try:
        with TestClient(main_mod.app,
                        headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


# ── timeline_metrics (service, via DB della fixture) ──────────────────────────

def test_timeline_month_and_quarter(client_admin):
    """2 booking done (gen 8h + apr 8h) + 1 planned (apr 4h) + fattura 5000 (mar)
    − NC 1000 (apr). Verifica righe mese, aggregazione trimestre, totale."""
    session = client_admin.session
    from app.services import sal_metrics
    from app.context import set_tenant_id
    set_tenant_id(1)

    m = sal_metrics.timeline_metrics(session, year=2026, granularity="month")
    assert m["granularity"] == "month"
    assert len(m["periods"]) == 12
    by_label = {p["label"]: p for p in m["periods"]}
    # Gennaio: 8h worked, 8h planned
    assert by_label["2026-01"]["worked"] == 8.0
    assert by_label["2026-01"]["planned"] == 8.0
    # Marzo: fatturato 5000
    assert by_label["2026-03"]["invoiced"] == 5000.0
    # Aprile: planned = 8 (job2 done) + 4 (job1 planned) = 12; worked = 8;
    #         fatturato = -1000 (NC)
    assert by_label["2026-04"]["planned"] == 12.0
    assert by_label["2026-04"]["worked"] == 8.0
    assert by_label["2026-04"]["invoiced"] == -1000.0

    # Totale anno
    assert m["total"]["worked"] == 16.0
    assert m["total"]["planned"] == 20.0
    assert m["total"]["invoiced"] == 4000.0
    assert m["total"]["pct"] == pytest.approx(16.0 / 20.0)

    # Trimestre
    mq = sal_metrics.timeline_metrics(session, year=2026, granularity="quarter")
    assert mq["granularity"] == "quarter"
    assert len(mq["periods"]) == 4
    q = {p["label"]: p for p in mq["periods"]}
    # Q1 = gen+feb+mar: worked 8, invoiced 5000
    assert q["Q1"]["worked"] == 8.0
    assert q["Q1"]["invoiced"] == 5000.0
    # Q2 = apr+mag+giu: worked 8, planned 12, invoiced -1000
    assert q["Q2"]["worked"] == 8.0
    assert q["Q2"]["planned"] == 12.0
    assert q["Q2"]["invoiced"] == -1000.0


# ── GET /finance/api/sal/projects ─────────────────────────────────────────────

def test_projects_shape_and_metrics(client_admin):
    r = client_admin.get("/finance/api/sal/projects")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1            # solo tenant 1 (proj2 tenant 2 escluso)
    row = rows[0]
    assert row["client"] == "ClienteSAL"
    assert row["code"] == "PSAL"
    # quotato = 10 (DI) + 4 (Audio) = 14; worked = 8 + 8 = 16; planned = 8+8+4=20
    assert row["quoted"] == 14.0
    assert row["worked"] == 16.0
    assert row["planned"] == 20.0
    assert row["pct"] == pytest.approx(16.0 / 14.0)
    assert row["alarm"] == "red"     # job2 sfora (8>4)
    assert row["job_count"] == 2
    # quotazioni distinte (solo job1 ha quote)
    assert {"number": "Q-2026-001", "title": "Quote SAL"} in row["quotes"]


def test_projects_filter_client_id(client_admin):
    session = client_admin.session
    r = client_admin.get(f"/finance/api/sal/projects?client_id={session._cli_id}")
    assert r.status_code == 200
    assert len(r.json()) == 1
    # client_id inesistente → vuoto
    r2 = client_admin.get("/finance/api/sal/projects?client_id=99999")
    assert r2.json() == []


def test_projects_filter_q(client_admin):
    r = client_admin.get("/finance/api/sal/projects?q=PSAL")
    assert len(r.json()) == 1
    r2 = client_admin.get("/finance/api/sal/projects?q=nonesiste")
    assert r2.json() == []


def test_projects_filter_status(client_admin):
    # default status = prospect → match
    r = client_admin.get("/finance/api/sal/projects?status=prospect")
    assert len(r.json()) == 1
    r2 = client_admin.get("/finance/api/sal/projects?status=completed")
    assert r2.json() == []


def test_projects_filter_alarm_only(client_admin):
    r = client_admin.get("/finance/api/sal/projects?alarm_only=true")
    assert len(r.json()) == 1        # progetto è red
    assert r.json()[0]["alarm"] == "red"


# ── GET /finance/api/sal/projects — euro/year fields + filtri dept/cat/proj ───

def test_sal_projects_returns_eur_and_year_fields(client_admin):
    r = client_admin.get("/finance/api/sal/projects")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 1
    row = rows[0]
    for k in ("quoted_eur", "accrued_eur", "pct_eur",
              "prev_year", "next_year", "prev_year_eur", "next_year_eur"):
        assert k in row, f"manca chiave {k}"


def test_sal_projects_filter_by_department(client_admin):
    session = client_admin.session
    # JCL del progetto sono nei reparti DI + Audio. Filtra per un dep_id
    # che il progetto NON ha.
    other_dep_id = max(session._dep_di_id, session._dep_audio_id) + 1000
    r = client_admin.get(
        f"/finance/api/sal/projects?department_id={other_dep_id}")
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_sal_projects_filter_by_category(client_admin):
    session = client_admin.session
    from app.models import PriceCategory
    cat = session.query(PriceCategory).filter(PriceCategory.tenant_id == 1).first()
    # Categoria inesistente → nessun progetto.
    other_cat_id = cat.id + 1000
    r = client_admin.get(
        f"/finance/api/sal/projects?category_id={other_cat_id}")
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_sal_projects_filter_by_project_id(client_admin):
    session = client_admin.session
    from app.models import Project, Client
    # Secondo progetto stesso tenant per garantire ≥2 progetti tenant 1.
    proj2 = Project(tenant_id=1, code="PSAL2", title="Progetto SAL 2",
                    client_id=session._cli_id)
    session.add(proj2)
    session.commit()

    r = client_admin.get(
        f"/finance/api/sal/projects?project_id={session._proj_id}")
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()]
    assert ids == [session._proj_id]


# ── GET /finance/api/sal/projects/{id}/detail ─────────────────────────────────

def test_detail_breakdown_and_jobs(client_admin):
    session = client_admin.session
    r = client_admin.get(f"/finance/api/sal/projects/{session._proj_id}/detail")
    assert r.status_code == 200, r.text
    body = r.json()
    # 2 job
    assert len(body["jobs"]) == 2
    codes = {j["code"] for j in body["jobs"]}
    assert codes == {"J-SAL-1", "J-SAL-2"}
    # breakdown reparto: DI quotato 10, Audio quotato 4
    depts = {d["name"]: d for d in body["departments"]}
    assert depts["DI/Video"]["quoted"] == 10.0
    assert depts["Audio"]["quoted"] == 4.0
    # job2 in allarme red
    j2 = next(j for j in body["jobs"] if j["code"] == "J-SAL-2")
    assert j2["alarm"] == "red"


def test_detail_404_not_found(client_admin):
    r = client_admin.get("/finance/api/sal/projects/99999/detail")
    assert r.status_code == 404


def test_detail_404_cross_tenant(client_admin):
    """Progetto del tenant 2 → 404 (non visibile al tenant 1)."""
    session = client_admin.session
    from app.models import Project
    other = session.query(Project).filter(Project.tenant_id == 2).first()
    r = client_admin.get(f"/finance/api/sal/projects/{other.id}/detail")
    assert r.status_code == 404


# ── GET /finance/api/sal/timeline (endpoint) ──────────────────────────────────

def test_timeline_endpoint(client_admin):
    r = client_admin.get("/finance/api/sal/timeline?year=2026&granularity=month")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year"] == 2026
    assert len(body["periods"]) == 12


# ── GET /finance/api/sal/matrix (calendario progetti × periodi) ──────────────

def test_matrix_endpoint(client_admin):
    r = client_admin.get("/finance/api/sal/matrix?year=2026&granularity=month")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year"] == 2026
    assert len(body["labels"]) == 12
    assert "projects" in body and "total" in body
    r2 = client_admin.get("/finance/api/sal/matrix?year=2026&granularity=quarter")
    assert len(r2.json()["labels"]) == 4


# ── GET /finance/sal (pagina) ─────────────────────────────────────────────────

def test_sal_page_200(client_admin):
    r = client_admin.get("/finance/sal")
    assert r.status_code == 200, r.text
