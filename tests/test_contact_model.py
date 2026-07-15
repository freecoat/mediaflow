import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Contact, ContactAcquisition, ContactProject,
    Acquisition, Project,
)


@pytest.fixture
def session():
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
    yield s


def test_contact_client_id_is_nullable(session):
    c = Contact(tenant_id=1, client_id=None, name="Mario Rossi",
                company_text="Studio Libero", source="manual")
    session.add(c)
    session.commit()
    assert c.id is not None
    assert c.client_id is None
    assert c.company_text == "Studio Libero"
    assert c.source == "manual"


def test_contact_source_defaults_to_manual(session):
    c = Contact(tenant_id=1, client_id=1, name="Anna Bianchi")
    session.add(c)
    session.commit()
    assert c.source == "manual"


def test_contact_acquisitions_link_and_unique(session):
    c = Contact(tenant_id=1, client_id=None, name="Mario Rossi")
    session.add(c)
    session.commit()
    session.add(ContactAcquisition(tenant_id=1, contact_id=c.id, acquisition_id=1, role="referente"))
    session.commit()
    session.add(ContactAcquisition(tenant_id=1, contact_id=c.id, acquisition_id=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_contact_projects_link_and_unique(session):
    c = Contact(tenant_id=1, client_id=None, name="Mario Rossi")
    session.add(c)
    session.commit()
    session.add(ContactProject(tenant_id=1, contact_id=c.id, project_id=1, role="DIT"))
    session.commit()
    session.add(ContactProject(tenant_id=1, contact_id=c.id, project_id=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
