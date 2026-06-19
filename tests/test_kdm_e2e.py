"""E2E integration test — KDM/DKDM full chain (Task 21).

Catena completa in-process via TestClient (niente Playwright, niente server vero):
  1. Seed DcpCpl → source JobDeliverable → Job (gerarchia minima Tenant→Client→Project→Job)
  2. Operatore crea link pubblico: POST /kdm/api/links → token
  3. Cliente invia form pubblico: POST /public/kdm/{token} → richiesta creata + auto-matched
     (UUID esatto → confidence 100 ≥ soglia 95)
  4. Transizione matched → keys_pending → generated:
     - a "generated" viene creato un JobDeliverable con price_item e delivered_date = generated_at.date()
     - req.job_deliverable_produced_id aggiornato
  5. Transizione generated → delivered → confirmed; stato persiste ad ogni step.

Pattern fixture: identico a test_kdm_router.py (monkeypatch engine/SessionLocal in-memory).
"""
import pytest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base
from app.models import (
    User, Role, Tenant, Client, Project, Job,
    JobDeliverable, KdmRequest, DcpCpl, DeliverableStatus,
)
from app.models.models import UserRole
from app.services.auth import create_access_token


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def e2e_client(monkeypatch):
    """TestClient autenticato (admin) su DB in-memory con gerarchia Job già seedata.

    Restituisce un namedtuple-like oggetto con:
      .client  – TestClient autenticato
      .session – sessione SQLAlchemy condivisa
      .cpl_uuid – UUID del DcpCpl seedato
      .src_jd_id – id del JobDeliverable sorgente (DCP)
      .job_id    – id del Job
    """
    import app.database as database
    import app.main as main_mod
    from app.database import get_db

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

    # ── Tenant + Role + User ──────────────────────────────────────────────
    tenant = Tenant(id=1, name="Tenant Test E2E", slug="e2e", is_active=True)
    session.add(tenant)
    session.flush()

    admin_role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["manage_kdm", "manage_roles", "edit_planning_all"],
        is_system=True, is_active=True,
    )
    session.add(admin_role)
    session.flush()

    admin = User(
        tenant_id=1, email="admin@e2e.local", full_name="Admin E2E",
        hashed_password="x", role=UserRole.admin, role_id=admin_role.id,
        is_active=True,
    )
    session.add(admin)
    session.flush()

    # ── Gerarchia Job ─────────────────────────────────────────────────────
    cli = Client(tenant_id=1, name="Cinema E2E SRL")
    session.add(cli)
    session.flush()

    proj = Project(tenant_id=1, code="E2E-2026", title="Queer FTR",
                   client_id=cli.id)
    session.add(proj)
    session.flush()

    job = Job(tenant_id=1, code="J-KDM-E2E", title="KDM E2E Job",
              project_id=proj.id, client_id=cli.id)
    session.add(job)
    session.flush()

    # ── DCP sorgente (CPL) ────────────────────────────────────────────────
    cpl_uuid = "urn:uuid:e2e-queer-ftr-cpl-001"
    cpl = DcpCpl(tenant_id=1, cpl_uuid=cpl_uuid, source="manual",
                 content_title_text="QUEER FTR 2K IT")
    session.add(cpl)
    session.flush()

    # ── JobDeliverable sorgente (DCP prodotto nel job) ────────────────────
    src_jd = JobDeliverable(
        tenant_id=1, job_id=job.id,
        name="DCP SMPTE 2K — Feature",
        status=DeliverableStatus.delivered,
    )
    session.add(src_jd)
    session.commit()

    # Conserva ID per gli assert
    _cpl_uuid = cpl_uuid
    _src_jd_id = src_jd.id
    _job_id = job.id

    def _override_get_db():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override_get_db
    token = create_access_token({"sub": admin.email, "tid": 1})

    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as tc:
            tc.session = session
            tc.cpl_uuid = _cpl_uuid
            tc.src_jd_id = _src_jd_id
            tc.job_id = _job_id
            yield tc
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test E2E
# ---------------------------------------------------------------------------

def test_kdm_e2e_full_chain(e2e_client, monkeypatch):
    """Catena completa KDM: link → form pubblico → matched → generata → consegnata → confermata."""
    tc = e2e_client
    session = tc.session

    # Neutralizza notifica (SMTP/in-app) nel form pubblico
    import app.routers.kdm_public as pub
    monkeypatch.setattr(pub, "_notify_finishing", lambda db, req: None)

    # ── Step 2: operatore crea link pubblico ──────────────────────────────
    r = tc.post("/kdm/api/links", data={
        "request_type": "kdm",
        "prefill_title": "QUEER FTR 2K IT",
    })
    assert r.status_code == 200, f"[step2] POST /kdm/api/links → {r.status_code}: {r.text}"
    link_body = r.json()
    assert "token" in link_body, f"[step2] risposta senza token: {link_body}"
    assert "/public/kdm/" in link_body.get("url", ""), f"[step2] url malformato: {link_body}"
    token_pub = link_body["token"]

    # ── Step 3: cliente compila form pubblico con UUID esatto ─────────────
    # UUID esatto → auto-link con confidence=100 ≥ AUTO_LINK_THRESHOLD=95 → matched
    r = tc.post(f"/public/kdm/{token_pub}", data={
        "request_type": "kdm",
        "requested_title": "Queer FTR 2K IT E2E",
        "requested_cpl_uuid": tc.cpl_uuid,
        "valid_from": "2026-09-01T20:00",
        "valid_to": "2026-09-30T23:00",
        "cinema_contact_email": "boxoffice@arcadia.it",
        "production_contact_name": "Mario Rossi",
    })
    assert r.status_code in (200, 303), f"[step3] POST form pubblico → {r.status_code}: {r.text}"

    # Verifica KdmRequest creata e auto-matched nel DB
    req_db = (session.query(KdmRequest)
              .filter(KdmRequest.requested_title == "Queer FTR 2K IT E2E")
              .first())
    assert req_db is not None, "[step3] KdmRequest non trovata nel DB"
    assert req_db.status == "matched", (
        f"[step3] atteso status='matched', ottenuto '{req_db.status}' "
        f"(dcp_cpl_id={req_db.dcp_cpl_id}, confidence={req_db.matched_confidence})")
    assert req_db.dcp_cpl_id is not None, "[step3] dcp_cpl_id non settato dopo auto-match"
    req_id = req_db.id

    # ── Pre-step 4: aggancia il DCP sorgente alla richiesta ───────────────
    # La KdmRequest creata dal form pubblico non ha job_deliverable_id (viene dal form,
    # non da un operatore che collega il DCP). La materializazione richiede il link
    # job_deliverable_id → Job. Lo settiamo qui come farebbe l'operatore in UI.
    req_db.job_deliverable_id = tc.src_jd_id
    session.commit()
    session.expire(req_db)

    # ── Step 4a: matched → keys_pending ───────────────────────────────────
    r = tc.post(f"/kdm/api/requests/{req_id}/transition",
                data={"to_status": "keys_pending"})
    assert r.status_code == 200, (
        f"[step4a] transition matched→keys_pending → {r.status_code}: {r.text}")
    assert r.json()["status"] == "keys_pending", f"[step4a] status atteso 'keys_pending': {r.json()}"

    # ── Step 4b: keys_pending → generated ────────────────────────────────
    r = tc.post(f"/kdm/api/requests/{req_id}/transition",
                data={"to_status": "generated"})
    assert r.status_code == 200, (
        f"[step4b] transition keys_pending→generated → {r.status_code}: {r.text}")
    body_gen = r.json()
    assert body_gen["status"] == "generated", f"[step4b] status atteso 'generated': {body_gen}"

    # Verifica materializazione: JobDeliverable creato + req.job_deliverable_produced_id settato
    session.expire(req_db)
    req_db = session.get(KdmRequest, req_id)
    assert req_db.job_deliverable_produced_id is not None, (
        "[step4b] req.job_deliverable_produced_id non settato dopo 'generated'")

    produced_jd = session.get(JobDeliverable, req_db.job_deliverable_produced_id)
    assert produced_jd is not None, "[step4b] JobDeliverable prodotto non trovato nel DB"
    assert produced_jd.job_id == tc.job_id, (
        f"[step4b] JobDeliverable nel job sbagliato: {produced_jd.job_id} != {tc.job_id}")
    assert produced_jd.status == DeliverableStatus.delivered, (
        f"[step4b] status deliverable atteso 'delivered': {produced_jd.status}")
    assert produced_jd.price_item_id is not None, (
        "[step4b] price_item_id non settato (voce listino KDM mancante)")
    assert "KDM" in produced_jd.name, f"[step4b] 'KDM' non nel nome deliverable: {produced_jd.name}"

    # La delivered_date deve essere impostata (da generated_at)
    assert produced_jd.delivered_date is not None, (
        "[step4b] delivered_date None (generated_at non propagato)")
    assert isinstance(produced_jd.delivered_date, date), (
        f"[step4b] delivered_date tipo inatteso: {type(produced_jd.delivered_date)}")

    # ── Step 5: generated → delivered ────────────────────────────────────
    r = tc.post(f"/kdm/api/requests/{req_id}/transition",
                data={"to_status": "delivered"})
    assert r.status_code == 200, (
        f"[step5] transition generated→delivered → {r.status_code}: {r.text}")
    assert r.json()["status"] == "delivered", f"[step5] status atteso 'delivered': {r.json()}"

    # Verifica persistenza
    session.expire(req_db)
    req_db = session.get(KdmRequest, req_id)
    assert req_db.status == "delivered", f"[step5] DB status: {req_db.status}"
    assert req_db.delivered_at is not None, "[step5] delivered_at non settato"

    # ── Step 6: delivered → confirmed ────────────────────────────────────
    r = tc.post(f"/kdm/api/requests/{req_id}/transition",
                data={"to_status": "confirmed"})
    assert r.status_code == 200, (
        f"[step6] transition delivered→confirmed → {r.status_code}: {r.text}")
    assert r.json()["status"] == "confirmed", f"[step6] status atteso 'confirmed': {r.json()}"

    # Verifica persistenza finale
    session.expire(req_db)
    req_db = session.get(KdmRequest, req_id)
    assert req_db.status == "confirmed", f"[step6] DB status finale: {req_db.status}"
    assert req_db.confirmed_at is not None, "[step6] confirmed_at non settato"
