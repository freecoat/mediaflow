# tests/test_f5_transfer_service.py
"""F5 (spec 2026-06-12) — Service transfer_orders: create, close, FSM, esiti job.

10 casi TDD coperti:
  1. create manual con 2 asset → requested, nessun AgentJob
  2. create aspera → AgentJob type=transfer accodato, payload files corretto
  3. create aspera con asset senza rel_path → ValueError
  4. tool ignoto / asset_ids vuoti / destination vuota / asset esterno tenant → ValueError
  5. close ok=True manual+link → done, 2 AssetMovement outgest, campi corretti
  6. close ok=False → failed, notifica, nessun movimento
  7. transition: requested→cancelled ok; done→* ValueError; requested→in_progress ok
  8. apply_transfer_result (job done) → ordine done con movimenti
  9. apply_transfer_failure → ordine failed + notifica
  10. ordine già chiuso: close/apply_result → ValueError
"""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base,
    AgentJob, AgentJobType, AgentJobStatus,
    Asset, AssetType,
    AssetMovement, AssetMovementType,
    TransferOrder,
)
import app.services.transfer_orders as svc_mod
from app.services.transfer_orders import (
    create_order,
    close_order,
    transition,
    apply_transfer_result,
    apply_transfer_failure,
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _asset(db, *, name="master.mxf", volume_id=None, rel_path=None, tenant_id=1):
    """Helper: crea Asset con i campi minimi richiesti dal service e dal DB."""
    a = Asset(
        tenant_id=tenant_id,
        filename=name,
        original_name=name,
        file_path=f"/san/{name}",
        mime_type="application/mxf",
        file_size=1_000_000,
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=volume_id,
        rel_path=rel_path,
    )
    db.add(a)
    db.flush()
    return a


def _fake_job(db, *, tenant_id=1) -> AgentJob:
    """Helper: crea AgentJob finto per test apply_transfer_*."""
    j = AgentJob(
        tenant_id=tenant_id,
        type=AgentJobType.transfer,
        payload={},
        status=AgentJobStatus.done,
    )
    db.add(j)
    db.flush()
    return j


# ── notify_permission stub ───────────────────────────────────────────────────

class _NotifyCalls:
    def __init__(self):
        self.calls: list[dict] = []

    def stub(self, db, *, permission, kind, title, **kwargs):
        self.calls.append({"permission": permission, "kind": kind, "title": title, **kwargs})
        return []


@pytest.fixture
def notif():
    calls = _NotifyCalls()
    with patch.object(svc_mod, "notify_permission", calls.stub):
        yield calls


# ── CASO 1: create manual con 2 asset ────────────────────────────────────────

def test_create_manual_two_assets_no_job(notif):
    """create_order manual → status requested, agent_job_id None, nessun AgentJob."""
    db = _session()
    a1 = _asset(db, name="reel1.mxf")
    a2 = _asset(db, name="reel2.mxf")

    order = create_order(
        db,
        tool="manual",
        asset_ids=[a1.id, a2.id],
        destination="Share: WeTransfer link XYZ",
        user_id=1,
    )

    assert order.status == "requested"
    assert order.tool == "manual"
    assert set(order.asset_ids) == {a1.id, a2.id}
    assert order.agent_job_id is None

    # Nessun AgentJob deve essere stato creato
    jobs = db.query(AgentJob).filter(AgentJob.type == AgentJobType.transfer).all()
    assert len(jobs) == 0


# ── CASO 2: create aspera → AgentJob accodato ────────────────────────────────

def test_create_aspera_enqueues_agent_job(notif):
    """create_order aspera con asset registrati → AgentJob type=transfer, payload corretto."""
    db = _session()
    a1 = _asset(db, name="master.mxf", volume_id=10, rel_path="projects/gomorra/master.mxf")
    a2 = _asset(db, name="mix.wav", volume_id=10, rel_path="projects/gomorra/mix.wav")

    order = create_order(
        db,
        tool="aspera",
        asset_ids=[a1.id, a2.id],
        destination="user@aspera.example.com:/inbox",
        recipient_email="post@client.com",
        user_id=2,
    )

    assert order.status == "requested"
    assert order.agent_job_id is not None

    job = db.get(AgentJob, order.agent_job_id)
    assert job is not None
    assert job.type == AgentJobType.transfer
    assert job.status == AgentJobStatus.queued
    assert job.payload["tool"] == "aspera"
    assert job.payload["destination"] == "user@aspera.example.com:/inbox"
    files = job.payload["files"]
    assert len(files) == 2
    assert {"volume_id": 10, "rel_path": "projects/gomorra/master.mxf"} in files
    assert {"volume_id": 10, "rel_path": "projects/gomorra/mix.wav"} in files


# ── CASO 3: create aspera con asset senza rel_path ───────────────────────────

def test_create_aspera_asset_no_rel_path_raises(notif):
    """create_order aspera con asset senza rel_path → ValueError esplicito."""
    db = _session()
    a1 = _asset(db, name="nopath.mxf", volume_id=5, rel_path=None)  # manca rel_path

    with pytest.raises(ValueError, match="rel_path|volume"):
        create_order(
            db,
            tool="aspera",
            asset_ids=[a1.id],
            destination="user@aspera.example.com:/inbox",
        )


def test_create_aspera_asset_no_volume_raises(notif):
    """create_order aspera con asset senza storage_volume_id → ValueError."""
    db = _session()
    a1 = _asset(db, name="novol.mxf", volume_id=None, rel_path="projects/a.mxf")

    with pytest.raises(ValueError, match="rel_path|volume"):
        create_order(
            db,
            tool="aspera",
            asset_ids=[a1.id],
            destination="user@aspera.example.com:/inbox",
        )


# ── CASO 4: validazioni create ───────────────────────────────────────────────

def test_create_unknown_tool_raises(notif):
    """Tool sconosciuto → ValueError."""
    db = _session()
    a = _asset(db)
    with pytest.raises(ValueError, match="[Tt]ool|sconosciuto"):
        create_order(db, tool="shuttle", asset_ids=[a.id], destination="dest")


def test_create_empty_asset_ids_raises(notif):
    """asset_ids vuoti → ValueError."""
    db = _session()
    with pytest.raises(ValueError, match="asset_ids|vuoto|almeno"):
        create_order(db, tool="manual", asset_ids=[], destination="dest")


def test_create_empty_destination_raises(notif):
    """destination vuota → ValueError."""
    db = _session()
    a = _asset(db)
    with pytest.raises(ValueError, match="destination"):
        create_order(db, tool="manual", asset_ids=[a.id], destination="")


def test_create_asset_wrong_tenant_raises(notif):
    """Asset di un altro tenant → ValueError."""
    db = _session()
    a = _asset(db, tenant_id=99)  # tenant diverso
    with pytest.raises(ValueError, match="tenant|trovato"):
        create_order(db, tool="manual", asset_ids=[a.id], destination="dest", tenant_id=1)


# ── CASO 5: close ok=True → done + movimenti outgest ─────────────────────────

def test_close_ok_true_creates_movements(notif):
    """close_order ok=True → status done, 2 movimenti outgest con campi corretti."""
    db = _session()
    a1 = _asset(db, name="reel1.mxf")
    a2 = _asset(db, name="reel2.mxf")

    order = create_order(
        db,
        tool="manual",
        asset_ids=[a1.id, a2.id],
        destination="Share: Aspera ftp.client.com",
        recipient_email="delivery@client.com",
        user_id=1,
    )

    link = "https://aspera.client.com/download/abc123xyz"
    close_order(
        db,
        order,
        ok=True,
        method="manual",
        details="Verificato a video",
        link_url=link,
        user_id=3,
    )

    assert order.status == "done"
    assert order.closed_at is not None
    assert order.closed_by_user_id == 3
    assert order.link_url == link
    assert order.verification == {
        "method": "manual",
        "ok": True,
        "details": "Verificato a video",
    }

    # Movimenti outgest
    movements = (
        db.query(AssetMovement)
        .filter(AssetMovement.movement_type == AssetMovementType.outgest)
        .all()
    )
    assert len(movements) == 2
    asset_ids_moved = {m.asset_id for m in movements}
    assert asset_ids_moved == {a1.id, a2.id}

    for mv in movements:
        assert mv.movement_type == AssetMovementType.outgest
        assert mv.tenant_id == 1
        assert mv.to_party == "Share: Aspera ftp.client.com"
        assert mv.to_contact == "delivery@client.com"
        assert mv.carrier == "manual"
        assert mv.tracking_number == link[:120]
        assert "TransferOrder #" in mv.contents_description
        assert str(order.id) in mv.contents_description


def test_close_ok_true_no_link_no_tracking(notif):
    """close_order ok=True senza link → tracking_number None."""
    db = _session()
    a = _asset(db)
    order = create_order(db, tool="manual", asset_ids=[a.id], destination="FTP manual")
    close_order(db, order, ok=True, method="size")

    mv = db.query(AssetMovement).filter(
        AssetMovement.movement_type == AssetMovementType.outgest
    ).first()
    assert mv is not None
    assert mv.tracking_number is None


# ── CASO 6: close ok=False → failed + notifica ──────────────────────────────

def test_close_ok_false_failed_and_notify(notif):
    """close_order ok=False → status failed, notify_permission chiamata, nessun movimento."""
    db = _session()
    a = _asset(db)
    order = create_order(db, tool="manual", asset_ids=[a.id], destination="FTP")

    close_order(db, order, ok=False, method="manual", details="Connessione rifiutata", user_id=5)

    assert order.status == "failed"
    assert order.closed_at is not None

    # Nessun movimento
    movements = db.query(AssetMovement).filter(
        AssetMovement.movement_type == AssetMovementType.outgest
    ).all()
    assert len(movements) == 0

    # Notifica inviata
    assert len(notif.calls) == 1
    call = notif.calls[0]
    assert call["permission"] == "edit_planning_all"
    assert "fallito" in call["title"].lower() or "Transfer" in call["title"]


# ── CASO 7: FSM transition ───────────────────────────────────────────────────

def test_transition_requested_to_cancelled_ok(notif):
    """requested → cancelled: legale."""
    db = _session()
    a = _asset(db)
    order = create_order(db, tool="manual", asset_ids=[a.id], destination="X")

    transition(db, order, "cancelled", user_id=1)
    assert order.status == "cancelled"
    assert order.closed_at is not None


def test_transition_requested_to_in_progress_ok(notif):
    """requested → in_progress: legale (manuale preso in carico)."""
    db = _session()
    a = _asset(db)
    order = create_order(db, tool="manual", asset_ids=[a.id], destination="X")

    transition(db, order, "in_progress", user_id=2)
    assert order.status == "in_progress"


def test_transition_done_to_any_raises(notif):
    """done → qualsiasi stato → ValueError (terminale)."""
    db = _session()
    a = _asset(db)
    order = create_order(db, tool="manual", asset_ids=[a.id], destination="X")
    close_order(db, order, ok=True, method="manual")

    assert order.status == "done"
    for bad in ("requested", "in_progress", "cancelled", "failed", "done"):
        with pytest.raises(ValueError, match="terminale|nessuna|ammess"):
            transition(db, order, bad, user_id=1)


def test_transition_in_progress_to_done_and_cancelled(notif):
    """in_progress → done e cancelled entrambi legali."""
    for target in ("done", "cancelled"):
        db = _session()
        a = _asset(db)
        order = create_order(db, tool="manual", asset_ids=[a.id], destination="X")
        transition(db, order, "in_progress", user_id=1)
        transition(db, order, target, user_id=1)
        assert order.status == target


# ── CASO 8: apply_transfer_result ────────────────────────────────────────────

def test_apply_transfer_result_closes_done_with_movements(notif):
    """apply_transfer_result con job done → ordine done, movimenti outgest."""
    db = _session()
    a = _asset(db, name="film.mxf", volume_id=1, rel_path="proj/film.mxf")
    order = create_order(
        db,
        tool="aspera",
        asset_ids=[a.id],
        destination="user@aspera.example.com:/out",
        user_id=1,
    )
    # Simula job completato
    job = db.get(AgentJob, order.agent_job_id)
    job.status = AgentJobStatus.done

    result = {"ok": True, "files": 1, "log_tail": "Transfer OK"}
    apply_transfer_result(db, job, result)

    assert order.status == "done"
    assert order.verification["method"] == "tool_rc"
    assert order.verification["ok"] is True

    movements = db.query(AssetMovement).filter(
        AssetMovement.asset_id == a.id,
        AssetMovement.movement_type == AssetMovementType.outgest,
    ).all()
    assert len(movements) == 1
    assert movements[0].carrier == "aspera"


# ── CASO 9: apply_transfer_failure ───────────────────────────────────────────

def test_apply_transfer_failure_closes_failed_and_notifies(notif):
    """apply_transfer_failure → ordine failed + notify_permission."""
    db = _session()
    a = _asset(db, name="film.mxf", volume_id=1, rel_path="proj/film.mxf")
    order = create_order(
        db,
        tool="aspera",
        asset_ids=[a.id],
        destination="user@aspera.example.com:/out",
        user_id=1,
    )
    job = db.get(AgentJob, order.agent_job_id)
    job.status = AgentJobStatus.failed

    apply_transfer_failure(db, job, "ascp exit code 1: connection refused")

    assert order.status == "failed"
    assert order.verification["ok"] is False
    assert len(notif.calls) >= 1  # notify_permission chiamata


# ── CASO 10: ordine già chiuso → ValueError ──────────────────────────────────

def test_close_already_done_raises(notif):
    """close_order su ordine già done → ValueError."""
    db = _session()
    a = _asset(db)
    order = create_order(db, tool="manual", asset_ids=[a.id], destination="X")
    close_order(db, order, ok=True, method="manual")
    assert order.status == "done"

    with pytest.raises(ValueError, match="già chiuso|terminale|done"):
        close_order(db, order, ok=False, method="manual")


def test_apply_result_already_closed_raises(notif):
    """apply_transfer_result su ordine già chiuso → ValueError."""
    db = _session()
    a = _asset(db, name="f.mxf", volume_id=1, rel_path="p/f.mxf")
    order = create_order(
        db,
        tool="aspera",
        asset_ids=[a.id],
        destination="user@host:/p",
        user_id=1,
    )
    job = db.get(AgentJob, order.agent_job_id)

    # Prima chiamata: chiude l'ordine
    apply_transfer_result(db, job, {"ok": True, "files": 1, "log_tail": ""})
    assert order.status == "done"

    # Seconda chiamata: deve sollevare ValueError
    with pytest.raises(ValueError, match="già chiuso|terminale|done"):
        apply_transfer_result(db, job, {"ok": True, "files": 1, "log_tail": ""})


def test_apply_failure_already_closed_raises(notif):
    """apply_transfer_failure su ordine già failed → ValueError."""
    db = _session()
    a = _asset(db, name="f.mxf", volume_id=1, rel_path="p/f.mxf")
    order = create_order(
        db,
        tool="aspera",
        asset_ids=[a.id],
        destination="user@host:/p",
        user_id=1,
    )
    job = db.get(AgentJob, order.agent_job_id)

    apply_transfer_failure(db, job, "errore 1")
    assert order.status == "failed"

    with pytest.raises(ValueError, match="già chiuso|terminale|failed"):
        apply_transfer_failure(db, job, "errore 2")
