import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Acquisition, Project, Contact, ContactAcquisition, ContactProject,
)
from app.context import current_tenant_id  # noqa: F401 (ensures context module loaded)


@pytest.fixture
def db_session(monkeypatch):
    import app.context as ctx
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", client_id=1))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.commit()
    monkeypatch.setattr(ctx, "current_tenant_id", lambda: 1)
    yield s


def test_propose_contact_standalone_no_client_id(db_session):
    from app.services.ai_assistant import _h_propose_contact
    res = _h_propose_contact(db_session, {"name": "Mario Rossi"})
    assert res["created"] is True
    c = db_session.query(Contact).filter_by(id=res["contact_id"]).first()
    assert c.client_id is None
    assert c.source == "ai"


def test_propose_contact_with_acquisition_and_project_links(db_session):
    from app.services.ai_assistant import _h_propose_contact
    res = _h_propose_contact(db_session, {
        "name": "Anna Bianchi", "acquisition_id": 1, "project_id": 1, "role": "Producer"})
    assert res["created"] is True
    cid = res["contact_id"]
    assert db_session.query(ContactAcquisition).filter_by(contact_id=cid, acquisition_id=1).count() == 1
    assert db_session.query(ContactProject).filter_by(contact_id=cid, project_id=1).count() == 1


def test_propose_contact_unknown_acquisition_raises(db_session):
    from app.services.ai_assistant import _h_propose_contact
    with pytest.raises(ValueError):
        _h_propose_contact(db_session, {"name": "X", "acquisition_id": 999})


def test_propose_contact_missing_name_raises(db_session):
    from app.services.ai_assistant import _h_propose_contact
    with pytest.raises(ValueError):
        _h_propose_contact(db_session, {})
