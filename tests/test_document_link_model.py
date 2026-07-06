from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, DocumentLink


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False, future=True)()


def test_document_link_columns():
    cols = {c.name for c in DocumentLink.__table__.columns}
    assert {"id", "tenant_id", "provider", "external_file_id", "name", "mime_type",
            "web_url", "icon_url", "owner_email", "project_id", "acquisition_id",
            "activity_id", "client_id", "added_by", "created_at", "is_active"} <= cols


def test_document_link_defaults():
    s = _session()
    d = DocumentLink(tenant_id=1, external_file_id="abc", name="Doc",
                     web_url="https://drive.google.com/file/d/abc/view", project_id=5)
    s.add(d); s.commit(); s.refresh(d)
    assert d.provider == "google"
    assert d.is_active is True
    assert d.created_at is not None
