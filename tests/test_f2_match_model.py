"""F2 — Asset.matched_deliverable_id (suggerimento match pre-conferma)."""
from app.models.models import (
    Tenant, User, UserRole, Asset, AssetType, JobDeliverable,
)


def _tenant(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()


def test_asset_matched_deliverable_default_none(db):
    _tenant(db)
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u); db.flush()
    a = Asset(tenant_id=1, filename="f.mov", original_name="f.mov",
              file_path="agent://1/OUT/f.mov", asset_type=AssetType.video,
              mime_type="video/quicktime", file_size=1, uploaded_by=u.id)
    db.add(a); db.flush()
    assert a.matched_deliverable_id is None
