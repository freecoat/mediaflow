"""TDD Task 20 — materialize_produced_kdm.

Guard test (RED→GREEN): ValueError se req non ha job_deliverable_id.
Happy-path test: crea JobDeliverable con status=delivered + price_item_id + emissione.
Idempotency test: doppia chiamata non crea duplicati.
"""
import pytest
from datetime import datetime

from app.models.models import (
    Tenant, Client, Project, Job, JobDeliverable,
    KdmRequest, DeliverableStatus,
)
from app.services.kdm_materialize import materialize_produced_kdm


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _make_tenant(db):
    t = Tenant(id=1, name="Test Tenant", slug="test")
    db.add(t)
    db.flush()
    return t


def _make_job(db):
    """Costruisce la gerarchia minima Tenant→Client→Project→Job."""
    _make_tenant(db)
    cli = Client(tenant_id=1, name="Cinema SRL")
    db.add(cli)
    db.flush()
    proj = Project(tenant_id=1, code="FILM-2026", title="Test Film", client_id=cli.id)
    db.add(proj)
    db.flush()
    job = Job(tenant_id=1, code="J-KDM-01", title="KDM Job",
              project_id=proj.id, client_id=cli.id)
    db.add(job)
    db.flush()
    return job


def _make_source_deliverable(db, job):
    """DCP sorgente — il JobDeliverable di origine che la KdmRequest referenzia."""
    src = JobDeliverable(
        tenant_id=1, job_id=job.id,
        name="DCP INTEROP 2K — Feature",
        status=DeliverableStatus.delivered,
    )
    db.add(src)
    db.flush()
    return src


# ── Guard test (TDD RED→GREEN) ───────────────────────────────────────────────

def test_generate_without_job_raises(db):
    """req senza job_deliverable_id → ValueError (no job risolubile)."""
    _make_tenant(db)
    req = KdmRequest(tenant_id=1, request_type="kdm", status="keys_pending")
    db.add(req)
    db.flush()

    with pytest.raises(ValueError, match="Richiesta senza job"):
        materialize_produced_kdm(db, req)


# ── Happy-path test ──────────────────────────────────────────────────────────

def test_materialize_creates_deliverable_with_correct_fields(db):
    """Happy path: crea JobDeliverable con status delivered, price_item_id e data."""
    job = _make_job(db)
    src = _make_source_deliverable(db, job)

    gen_at = datetime(2026, 6, 19, 14, 30, 0)
    req = KdmRequest(
        tenant_id=1,
        request_type="kdm",
        status="keys_pending",
        job_deliverable_id=src.id,
        requested_title="Queer FTR 2K IT",
        generated_at=gen_at,
    )
    db.add(req)
    db.flush()

    jd = materialize_produced_kdm(db, req)

    assert jd is not None
    assert jd.id is not None
    assert jd.job_id == job.id
    assert jd.status == DeliverableStatus.delivered
    assert jd.tenant_id == 1
    # Nome contiene il tipo (uppercase) e il titolo richiesto
    assert "KDM" in jd.name
    assert "Queer FTR 2K IT" in jd.name
    # Data emissione = data della generazione
    assert jd.delivered_date == gen_at.date()
    # price_item_id settato (voce listino KDM creata da ensure_kdm_price_items)
    assert jd.price_item_id is not None
    # req aggiornato con il link al deliverable prodotto
    assert req.job_deliverable_produced_id == jd.id


def test_materialize_dkdm_type(db):
    """request_type='dkdm' → nome contiene DKDM."""
    job = _make_job(db)
    src = _make_source_deliverable(db, job)

    req = KdmRequest(
        tenant_id=1,
        request_type="dkdm",
        status="keys_pending",
        job_deliverable_id=src.id,
        requested_title="Queer DKDM",
    )
    db.add(req)
    db.flush()

    jd = materialize_produced_kdm(db, req)

    assert "DKDM" in jd.name


# ── Idempotency test ─────────────────────────────────────────────────────────

def test_materialize_idempotent(db):
    """Doppia chiamata non crea un secondo JobDeliverable."""
    job = _make_job(db)
    src = _make_source_deliverable(db, job)

    req = KdmRequest(
        tenant_id=1,
        request_type="kdm",
        status="keys_pending",
        job_deliverable_id=src.id,
        requested_title="Idempotency Test",
    )
    db.add(req)
    db.flush()

    jd1 = materialize_produced_kdm(db, req)
    jd2 = materialize_produced_kdm(db, req)

    assert jd1.id == jd2.id
    count = db.query(JobDeliverable).filter(
        JobDeliverable.job_id == job.id,
        JobDeliverable.status == DeliverableStatus.delivered,
    ).count()
    # Solo 1 KDM deliverable prodotto (+ il src DCP che è anch'esso delivered)
    assert count == 2  # src + il KDM prodotto
