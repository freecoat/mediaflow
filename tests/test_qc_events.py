"""v3.5.0-alpha.172.101 (Bundle L Stack 2 milestone 3/3) — pytest QC event-sourced.

Copre:
- immutability QCEvent (UPDATE/DELETE bloccati salvo admin override)
- qc_number progression (1, 2, 3 per round consecutivi)
- sequence reset per nuovo round (riparte da 1)
- projection counter correctness (video/audio/text errors, recommendations,
  notes, corrections, signoffs incrementati correttamente)
- max_grade propagation (max degli error grade)
- terminal status mapping (pass→passed, fail→failed, conditional→conditional)
- Bundle I sync (JobDeliverable.qc_substatus + qc_run_at)
- reopen flow (qc_started post-reopen incrementa qc_number)
- rebuild_qc_report idempotency (chiamato 2x = stesso stato)
- guard validation (log_error/recommendation/correction richiedono QC attivo)
"""
import pytest
from datetime import datetime

from app.models.models import (
    Tenant, Client, Project, Job, JobStatus,
    JobDeliverable, DeliverableNature, DeliverableUnitNature,
    DeliverableStatus, QCSubstatus,
    QCEvent, QCEventType, QCReport,
)
from app.services import qc_events
from app.services.qc_event_listener import (
    init_qc_event_listeners, QCEventImmutabilityError, rebuild_qc_report,
)


# ── Helpers ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _ensure_listeners():
    """Registra immutability listener una volta per sessione test."""
    init_qc_event_listeners()
    yield


def _make_tenant_and_deliverable(db, tenant_id: int = 1) -> JobDeliverable:
    """Crea tenant + client + project + job + deliverable minimi."""
    t = Tenant(id=tenant_id, name="Test Tenant", slug="test-tenant",
               tech_specs_refresh_days=30)
    db.add(t)
    c = Client(tenant_id=tenant_id, name="Client X")
    db.add(c)
    db.flush()
    p = Project(tenant_id=tenant_id, code="P001", title="Proj", client_id=c.id)
    db.add(p)
    db.flush()
    j = Job(tenant_id=tenant_id, code="P001-J001", title="Job",
            project_id=p.id, client_id=c.id, status=JobStatus.approved)
    db.add(j)
    db.flush()
    d = JobDeliverable(
        tenant_id=tenant_id, job_id=j.id,
        name="DCP IT", nature=DeliverableNature.digital,
        unit="pc", unit_nature=DeliverableUnitNature.deliverable_qty,
        quantity_planned=1.0, quantity_delivered=0.0,
        unit_price=100.0, total_quoted=100.0,
        status=DeliverableStatus.planned,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


# ── Immutability tests ─────────────────────────────────────────────────────

def test_qcevent_immutability_blocks_update(db):
    d = _make_tenant_and_deliverable(db)
    ev, _ = qc_events.start_qc(db, d.id, operator_id=1)
    db.commit()
    ev.payload_json = {"tampered": True}
    with pytest.raises(QCEventImmutabilityError):
        db.commit()
    db.rollback()


def test_qcevent_immutability_blocks_delete(db):
    d = _make_tenant_and_deliverable(db)
    ev, _ = qc_events.start_qc(db, d.id, operator_id=1)
    db.commit()
    db.delete(ev)
    with pytest.raises(QCEventImmutabilityError):
        db.commit()
    db.rollback()


def test_qcevent_admin_override_allows_update(db):
    d = _make_tenant_and_deliverable(db)
    ev, _ = qc_events.start_qc(db, d.id, operator_id=1)
    db.commit()
    db.info["__qc_admin_override__"] = True
    ev.payload_json = {"admin_corrected": True}
    db.commit()  # no raise
    db.refresh(ev)
    assert ev.payload_json["admin_corrected"] is True


def test_qcevent_admin_override_allows_delete(db):
    d = _make_tenant_and_deliverable(db)
    ev, _ = qc_events.start_qc(db, d.id, operator_id=1)
    ev_id = ev.id
    db.commit()
    db.info["__qc_admin_override__"] = True
    db.delete(ev)
    db.commit()  # no raise
    remaining = db.query(QCEvent).filter(QCEvent.id == ev_id).first()
    assert remaining is None


# ── qc_number progression + sequence reset ──────────────────────────────────

def test_qc_number_progression(db):
    d = _make_tenant_and_deliverable(db)
    ev1, _ = qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.pass_qc(db, d.id, operator_id=1)
    qc_events.reopen_qc(db, d.id, reason="client review", operator_id=1)
    ev2, _ = qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.pass_qc(db, d.id, operator_id=1)
    qc_events.reopen_qc(db, d.id, reason="post-fix re-check", operator_id=1)
    ev3, _ = qc_events.start_qc(db, d.id, operator_id=1)
    db.commit()
    assert ev1.qc_number == 1
    assert ev2.qc_number == 2
    assert ev3.qc_number == 3


def test_sequence_reset_per_round(db):
    d = _make_tenant_and_deliverable(db)
    ev1, _ = qc_events.start_qc(db, d.id, operator_id=1)
    ev_err1 = qc_events.log_error(db, d.id, channel="video", grade=1, description="a")
    ev_err2 = qc_events.log_error(db, d.id, channel="video", grade=1, description="b")
    qc_events.pass_qc(db, d.id, operator_id=1)
    qc_events.reopen_qc(db, d.id, reason="round 2", operator_id=1)
    ev2, _ = qc_events.start_qc(db, d.id, operator_id=1)
    ev_err3 = qc_events.log_error(db, d.id, channel="video", grade=1, description="c")
    db.commit()

    # Round 1: ev1.seq=1, err1.seq=2, err2.seq=3, pass.seq=4, reopen.seq=5
    assert ev1.sequence == 1
    assert ev_err1.sequence == 2
    assert ev_err2.sequence == 3
    # Round 2: ev2.seq=1, err3.seq=2 (RIPARTE da 1)
    assert ev2.sequence == 1
    assert ev_err3.sequence == 2


# ── Projection counter + max_grade ──────────────────────────────────────────

def test_projection_video_error_counter(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.log_error(db, d.id, channel="video", grade=1, description="a")
    qc_events.log_error(db, d.id, channel="video", grade=2, description="b")
    qc_events.log_error(db, d.id, channel="video", grade=3, description="c")
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep is not None
    assert rep.video_errors_count == 3
    assert rep.audio_errors_count == 0


def test_projection_mixed_channels(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.log_error(db, d.id, channel="video", grade=1, description="v")
    qc_events.log_error(db, d.id, channel="audio", grade=2, description="a")
    qc_events.log_error(db, d.id, channel="audio", grade=1, description="a2")
    qc_events.log_error(db, d.id, channel="text", grade=1, description="t")
    qc_events.add_recommendation(db, d.id, "regrade", operator_id=1)
    qc_events.add_note(db, d.id, "internal note", operator_id=1)
    qc_events.request_correction(
        db, d.id, target_event_ids=[], description="fix", operator_id=1,
    )
    qc_events.signoff(db, d.id, signer_id=99, role="qc_lead", operator_id=1)
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep.video_errors_count == 1
    assert rep.audio_errors_count == 2
    assert rep.text_errors_count == 1
    assert rep.recommendations_count == 1
    assert rep.notes_count == 1
    assert rep.open_corrections_count == 1
    assert rep.signoffs_count == 1


def test_projection_max_grade(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.log_error(db, d.id, channel="video", grade=2, description="x")
    qc_events.log_error(db, d.id, channel="audio", grade=3, description="y")
    qc_events.log_error(db, d.id, channel="text", grade=1, description="z")
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep.max_grade == 3


# ── Terminal status mapping ────────────────────────────────────────────────

def test_projection_status_pass(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.pass_qc(db, d.id, overall_grade=1, operator_id=1)
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep.overall_status == "passed"


def test_projection_status_fail(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.fail_qc(db, d.id, primary_cause="audio clipping", operator_id=1)
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep.overall_status == "failed"


def test_projection_status_conditional(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.conditional_qc(
        db, d.id, conditions=["fix loudness"], pass_when="passes EBU R128",
        operator_id=1,
    )
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep.overall_status == "conditional"


def test_projection_status_reopened(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.pass_qc(db, d.id, operator_id=1)
    qc_events.reopen_qc(db, d.id, reason="client found issue", operator_id=1)
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep.overall_status == "reopened"


# ── Bundle I sync ─────────────────────────────────────────────────────────

def test_bundle_i_sync_on_start(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=42)
    db.commit()
    db.refresh(d)
    assert d.status == DeliverableStatus.qc
    assert d.qc_substatus == QCSubstatus.in_progress
    assert d.qc_run_at is not None
    assert d.qc_run_by_user_id == 42


def test_bundle_i_sync_on_pass(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.pass_qc(db, d.id, operator_id=1)
    db.commit()
    db.refresh(d)
    assert d.qc_substatus == QCSubstatus.passed


def test_bundle_i_sync_on_fail(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.fail_qc(db, d.id, primary_cause="critical", operator_id=1)
    db.commit()
    db.refresh(d)
    assert d.qc_substatus == QCSubstatus.rejected


def test_bundle_i_sync_on_conditional_is_passed(db):
    """Per back-compat Bundle I (3 valori), conditional mappa a qc_substatus=passed.
    UI rich distingue via QCReport.overall_status."""
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.conditional_qc(db, d.id, conditions=["fix"], operator_id=1)
    db.commit()
    db.refresh(d)
    assert d.qc_substatus == QCSubstatus.passed


def test_bundle_i_sync_on_reopen_back_to_in_progress(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.pass_qc(db, d.id, operator_id=1)
    qc_events.reopen_qc(db, d.id, reason="re-check", operator_id=1)
    db.commit()
    db.refresh(d)
    assert d.qc_substatus == QCSubstatus.in_progress


# ── rebuild_qc_report idempotency ─────────────────────────────────────────

def test_rebuild_qc_report_idempotent(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    qc_events.log_error(db, d.id, channel="video", grade=2, description="a")
    qc_events.log_error(db, d.id, channel="audio", grade=3, description="b")
    qc_events.add_recommendation(db, d.id, "fix", operator_id=1)
    qc_events.pass_qc(db, d.id, operator_id=1)
    db.commit()

    rep1 = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    snapshot1 = {
        "v": rep1.video_errors_count, "a": rep1.audio_errors_count,
        "t": rep1.text_errors_count, "r": rep1.recommendations_count,
        "status": rep1.overall_status, "max": rep1.max_grade,
        "last_qc": rep1.last_qc_number,
    }

    rebuild_qc_report(db, d.id)
    db.commit()
    rep2 = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    snapshot2 = {
        "v": rep2.video_errors_count, "a": rep2.audio_errors_count,
        "t": rep2.text_errors_count, "r": rep2.recommendations_count,
        "status": rep2.overall_status, "max": rep2.max_grade,
        "last_qc": rep2.last_qc_number,
    }
    assert snapshot1 == snapshot2

    # Second rebuild = same result
    rebuild_qc_report(db, d.id)
    db.commit()
    rep3 = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    snapshot3 = {
        "v": rep3.video_errors_count, "a": rep3.audio_errors_count,
        "t": rep3.text_errors_count, "r": rep3.recommendations_count,
        "status": rep3.overall_status, "max": rep3.max_grade,
        "last_qc": rep3.last_qc_number,
    }
    assert snapshot2 == snapshot3


def test_rebuild_qc_report_no_events_clears_report(db):
    """Se ci sono 0 eventi (es. dopo admin-override delete totale), rebuild
    rimuove la projection. Idempotenza: chiamato 2x non crasha."""
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    db.commit()
    # Admin override delete tutti gli eventi
    db.info["__qc_admin_override__"] = True
    for ev in db.query(QCEvent).filter(QCEvent.deliverable_id == d.id).all():
        db.delete(ev)
    db.commit()
    db.info["__qc_admin_override__"] = False

    rebuild_qc_report(db, d.id)
    db.commit()
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep is None
    # Idempotente: re-call con report già None non crasha
    rebuild_qc_report(db, d.id)
    db.commit()


# ── Guard validation ───────────────────────────────────────────────────────

def test_log_error_requires_active_qc(db):
    d = _make_tenant_and_deliverable(db)
    with pytest.raises(ValueError, match="Nessun QC attivo"):
        qc_events.log_error(db, d.id, channel="video", description="x")


def test_log_error_invalid_channel(db):
    d = _make_tenant_and_deliverable(db)
    qc_events.start_qc(db, d.id, operator_id=1)
    with pytest.raises(ValueError, match="channel non valido"):
        qc_events.log_error(db, d.id, channel="metadata", description="x")


def test_recommendation_requires_active_qc(db):
    d = _make_tenant_and_deliverable(db)
    with pytest.raises(ValueError, match="Nessun QC attivo"):
        qc_events.add_recommendation(db, d.id, "x", operator_id=1)


def test_correction_requires_active_qc(db):
    d = _make_tenant_and_deliverable(db)
    with pytest.raises(ValueError, match="Nessun QC attivo"):
        qc_events.request_correction(
            db, d.id, target_event_ids=[1], description="x", operator_id=1,
        )


def test_signoff_requires_active_qc(db):
    d = _make_tenant_and_deliverable(db)
    with pytest.raises(ValueError, match="Nessun QC attivo"):
        qc_events.signoff(db, d.id, signer_id=1, role="qc_lead", operator_id=1)


def test_pass_requires_active_qc(db):
    d = _make_tenant_and_deliverable(db)
    with pytest.raises(ValueError, match="Nessun QC attivo"):
        qc_events.pass_qc(db, d.id, operator_id=1)


def test_reopen_requires_existing_qc(db):
    d = _make_tenant_and_deliverable(db)
    with pytest.raises(ValueError, match="non ha QC pregressi"):
        qc_events.reopen_qc(db, d.id, reason="x", operator_id=1)


def test_note_works_pre_qc(db):
    """note_added e' speciale: ammesso pre-QC come container per il futuro round 1."""
    d = _make_tenant_and_deliverable(db)
    ev = qc_events.add_note(db, d.id, "pre-kickoff", operator_id=1)
    db.commit()
    assert ev.qc_number == 1
    rep = db.query(QCReport).filter(QCReport.deliverable_id == d.id).first()
    assert rep.notes_count == 1
