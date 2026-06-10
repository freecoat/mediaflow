"""F1 — proposta asset da probe, dedup checksum, conferma/scarto, guard contenuti."""
import pytest

from app.models.models import (
    Tenant, User, UserRole, StorageVolume,
    Asset, AssetType, AssetStatus, AssetContentState, AssetProposedState,
)
from app.services.asset_registry import (
    create_proposal_from_probe, confirm_proposal, discard_proposal,
    is_content_file,
)


def _setup(db):
    db.add(Tenant(id=1, name="T", slug="t1"))
    db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u)
    v = StorageVolume(tenant_id=1, name="SAN-01", mount_path="/Volumes/SAN01")
    db.add(v)
    db.flush()
    return u, v


PROBE = {
    "rel_path": "OUT/P001/master_v3.mov",
    "file_size": 123456789,
    "mime_type": "video/quicktime",
    "checksum_xxhash": "abcd1234abcd1234",
    "tech_specs": {"tool": "ffprobe", "video": {"codec": "prores"}},
}


def test_create_proposal(db):
    u, v = _setup(db)
    a = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                   probe=PROBE, user_id=u.id)
    assert a.proposed_state == AssetProposedState.pending_review
    assert a.status == AssetStatus.uploaded
    assert a.content_state == AssetContentState.online
    assert a.asset_type == AssetType.video
    assert a.filename == "master_v3.mov"
    assert a.rel_path == "OUT/P001/master_v3.mov"
    assert a.file_path == f"agent://{v.id}/OUT/P001/master_v3.mov"
    assert a.checksum_xxhash == "abcd1234abcd1234"
    assert a.tech_specs_json["tool"] == "ffprobe"
    assert a.registered_via == "manual_path"


def test_proposal_dedup_same_checksum_same_volume(db):
    u, v = _setup(db)
    a1 = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                    probe=PROBE, user_id=u.id)
    a2 = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                    probe=PROBE, user_id=u.id)
    assert a1.id == a2.id


def test_confirm_and_discard(db):
    u, v = _setup(db)
    a = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                   probe=PROBE, user_id=u.id)
    confirm_proposal(db, a, user_id=u.id)
    assert a.proposed_state == AssetProposedState.confirmed

    probe2 = dict(PROBE, checksum_xxhash="ffff0000ffff0000",
                  rel_path="OUT/P001/altro.wav", mime_type="audio/wav")
    b = create_proposal_from_probe(db, tenant_id=1, volume_id=v.id,
                                   probe=probe2, user_id=u.id)
    discard_proposal(db, b)
    assert b.proposed_state == AssetProposedState.discarded


def test_is_content_file_guard():
    assert is_content_file("master.mov", "video/quicktime") is True
    assert is_content_file("mix_51.wav", "audio/wav") is True
    assert is_content_file("frame.dpx", None) is True
    assert is_content_file("capitolato.pdf", "application/pdf") is False
    assert is_content_file("bolla_firmata.jpg", "image/jpeg") is False
    assert is_content_file("note.txt", "text/plain") is False
