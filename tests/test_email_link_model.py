from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, EmailLink


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False, future=True)()


def test_email_link_columns():
    cols = {c.name for c in EmailLink.__table__.columns}
    assert {"id", "tenant_id", "provider", "thread_id", "message_id", "from_addr",
            "subject", "snippet", "email_date", "acquisition_id", "added_by",
            "created_at", "is_active"} <= cols


def test_email_link_defaults():
    s = _session()
    e = EmailLink(tenant_id=1, thread_id="T1", subject="Oggetto", acquisition_id=5)
    s.add(e); s.commit(); s.refresh(e)
    assert e.provider == "google"
    assert e.is_active is True
    assert e.created_at is not None
