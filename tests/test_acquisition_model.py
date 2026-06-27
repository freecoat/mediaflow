# tests/test_acquisition_model.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Department, User, UserRole,
    Acquisition, AcquisitionStage, Contact, Activity, ActivityType,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky Red")); s.flush()
    s.add(Department(id=1, tenant_id=1, code="DI", name="DI", sort_order=1)); s.flush()
    s.add(User(id=1, tenant_id=1, email="c@t.local", full_name="Commerciale",
               hashed_password="x", role=UserRole.manager, is_active=True))
    s.commit()
    yield s
    s.close()


def test_acquisition_defaults_and_relationships(db):
    acq = Acquisition(tenant_id=1, title="Nuovo film", client_id=1,
                      stage=AcquisitionStage.lead, estimated_value=80000,
                      owner_user_id=1, created_by=1)
    dep = db.query(Department).get(1)
    acq.departments.append(dep)
    db.add(acq); db.commit(); db.refresh(acq)
    assert acq.is_active is True
    assert acq.stage == AcquisitionStage.lead
    assert [d.name for d in acq.departments] == ["DI"]


def test_contact_and_activity_link(db):
    c = Contact(tenant_id=1, client_id=1, name="Mario Rossi", email="m@x.it")
    db.add(c); db.commit(); db.refresh(c)
    assert c.is_primary is False and c.is_active is True
    a = Activity(tenant_id=1, client_id=1, contact_id=c.id,
                 type=ActivityType.email, subject="Primo contatto", created_by=1)
    db.add(a); db.commit(); db.refresh(a)
    assert a.type == ActivityType.email
