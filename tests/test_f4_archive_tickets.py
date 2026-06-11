# tests/test_f4_archive_tickets.py
"""F4 (spec 2026-06-11) — Service archive_tickets: transizioni, notifiche, content_state."""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base,
    ArchiveTicket,
    Asset, AssetType, AssetContentState,
    AssetMembership,
    PhysicalAsset, PhysicalAssetKind,
    JobDeliverable, DeliverableNature,
)
import app.services.archive_tickets as svc_mod
from app.services.archive_tickets import create_ticket, transition


# ── helpers ─────────────────────────────────────────────────────────

def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _asset(db, name="master.mxf"):
    a = Asset(
        tenant_id=1,
        filename=name,
        original_name=name,
        file_path=f"/san/{name}",
        file_size=1_000_000,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
    )
    db.add(a)
    db.flush()
    return a


def _deliverable(db, name="Mix 5.1"):
    d = JobDeliverable(
        tenant_id=1,
        job_id=1,  # FK non enforced su SQLite in-memory
        name=name,
        nature=DeliverableNature.digital,
    )
    db.add(d)
    db.flush()
    return d


def _lto(db, label="LTO #001"):
    pa = PhysicalAsset(
        tenant_id=1,
        kind=PhysicalAssetKind.lto,
        label=label,
    )
    db.add(pa)
    db.flush()
    return pa


def _membership(db, asset_id, physical_asset_id):
    m = AssetMembership(
        tenant_id=1,
        asset_id=asset_id,
        physical_asset_id=physical_asset_id,
    )
    db.add(m)
    db.flush()
    return m


# ── stub monkeypatching ─────────────────────────────────────────────

class _NotifyCalls:
    def __init__(self):
        self.notify_calls = []
        self.notify_permission_calls = []

    def stub_notify(self, db, *, user_ids, kind, title, **kwargs):
        self.notify_calls.append({"user_ids": list(user_ids), "kind": kind, "title": title, **kwargs})
        return []

    def stub_notify_permission(self, db, *, permission, kind, title, **kwargs):
        self.notify_permission_calls.append({"permission": permission, "kind": kind, "title": title, **kwargs})
        return []


@pytest.fixture
def notif():
    calls = _NotifyCalls()
    with (
        patch.object(svc_mod, "notify", calls.stub_notify),
        patch.object(svc_mod, "notify_permission", calls.stub_notify_permission),
    ):
        yield calls


# ── TESTS ───────────────────────────────────────────────────────────

def test_create_restore_with_membership_tape_and_notify_permission(notif):
    """create_ticket restore con asset+membership LTO: physical_asset_id suggerito, notify_permission chiamata."""
    db = _session()
    a = _asset(db)
    pa = _lto(db)
    _membership(db, a.id, pa.id)

    t = create_ticket(db, kind="restore", asset=a, user_id=1)

    assert t.kind == "restore"
    assert t.asset_id == a.id
    assert t.physical_asset_id == pa.id
    assert t.status == "requested"
    assert len(notif.notify_permission_calls) == 1
    np = notif.notify_permission_calls[0]
    assert np["permission"] == "edit_planning_all"
    assert np["kind"] == "archive_ticket"
    assert "restore" in np["title"]


def test_create_restore_without_membership_physical_none(notif):
    """restore senza membership LTO: physical_asset_id = None (tape non noto)."""
    db = _session()
    a = _asset(db)

    t = create_ticket(db, kind="restore", asset=a, user_id=2)

    assert t.physical_asset_id is None
    assert len(notif.notify_permission_calls) == 1


def test_create_without_target_raises(notif):
    """Almeno uno tra asset e deliverable richiesto."""
    db = _session()
    with pytest.raises(ValueError, match="Almeno uno"):
        create_ticket(db, kind="archive")


def test_create_invalid_kind_raises(notif):
    """kind diverso da archive/restore → ValueError."""
    db = _session()
    a = _asset(db)
    with pytest.raises(ValueError, match="kind"):
        create_ticket(db, kind="unknown", asset=a)


def test_transition_all_legal_from_requested(notif):
    """requested → in_progress, done, cancelled tutti legali."""
    for new_status in ("in_progress", "done", "cancelled"):
        db = _session()
        a = _asset(db)
        if new_status == "done":
            # archive done richiede membership; usiamo restore
            _lto_and_link = _lto(db)
            _membership(db, a.id, _lto_and_link.id)
            t = create_ticket(db, kind="restore", asset=a)
        else:
            t = create_ticket(db, kind="archive", asset=a)
        transition(db, t, new_status, user_id=3)
        assert t.status == new_status


def test_transition_in_progress_to_done_and_cancelled(notif):
    """in_progress → done e cancelled legali."""
    for new_status in ("done", "cancelled"):
        db = _session()
        a = _asset(db)
        if new_status == "done":
            pa = _lto(db)
            _membership(db, a.id, pa.id)
            t = create_ticket(db, kind="restore", asset=a)
        else:
            t = create_ticket(db, kind="restore", asset=a)
        transition(db, t, "in_progress", user_id=4)
        transition(db, t, new_status, user_id=4)
        assert t.status == new_status


def test_transition_done_to_any_raises(notif):
    """done → qualsiasi stato → ValueError (stato terminale)."""
    db = _session()
    a = _asset(db)
    pa = _lto(db)
    _membership(db, a.id, pa.id)
    t = create_ticket(db, kind="restore", asset=a)
    transition(db, t, "done", user_id=5)
    for bad in ("requested", "in_progress", "cancelled", "done"):
        with pytest.raises(ValueError, match="terminale|nessuna"):
            transition(db, t, bad, user_id=5)


def test_transition_cancelled_to_any_raises(notif):
    """cancelled → qualsiasi stato → ValueError."""
    db = _session()
    a = _asset(db)
    t = create_ticket(db, kind="archive", asset=a)
    transition(db, t, "cancelled", user_id=6)
    with pytest.raises(ValueError):
        transition(db, t, "in_progress", user_id=6)


def test_restore_done_sets_online_and_notifies_requester(notif):
    """restore → done: asset.content_state = online, notifica al richiedente."""
    db = _session()
    a = _asset(db)
    pa = _lto(db)
    _membership(db, a.id, pa.id)
    t = create_ticket(db, kind="restore", asset=a, user_id=7)

    transition(db, t, "done", user_id=8)

    db.expire(a)
    a2 = db.get(Asset, a.id)
    assert a2.content_state == AssetContentState.online

    notify_calls = notif.notify_calls
    assert len(notify_calls) == 1
    nc = notify_calls[0]
    assert 7 in nc["user_ids"]
    assert "Restore completato" in nc["title"]


def test_archive_done_with_membership_sets_archived_only(notif):
    """archive → done con membership LTO: asset.content_state = archived_only."""
    db = _session()
    a = _asset(db)
    pa = _lto(db)
    _membership(db, a.id, pa.id)
    t = create_ticket(db, kind="archive", asset=a, user_id=1)

    transition(db, t, "done", user_id=2)

    db.expire(a)
    a2 = db.get(Asset, a.id)
    assert a2.content_state == AssetContentState.archived_only


def test_archive_done_without_membership_raises(notif):
    """archive → done senza membership LTO: ValueError (ingest prima il catalogo)."""
    db = _session()
    a = _asset(db)
    t = create_ticket(db, kind="archive", asset=a, user_id=1)

    with pytest.raises(ValueError, match="[Ii]ngest"):
        transition(db, t, "done", user_id=2)


def test_done_sets_closed_at_and_closed_by(notif):
    """done setta closed_at (datetime) e closed_by_user_id."""
    db = _session()
    a = _asset(db)
    pa = _lto(db)
    _membership(db, a.id, pa.id)
    t = create_ticket(db, kind="restore", asset=a, user_id=1)

    transition(db, t, "done", user_id=9)

    assert t.closed_at is not None
    assert t.closed_by_user_id == 9


def test_in_progress_sets_assigned_to(notif):
    """in_progress setta assigned_to_user_id."""
    db = _session()
    a = _asset(db)
    t = create_ticket(db, kind="archive", asset=a)

    transition(db, t, "in_progress", user_id=11)

    assert t.assigned_to_user_id == 11
