import pytest
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Department, Acquisition, AcquisitionStage, Activity, ActivityType,
)
from app.services.acquisition_service import pipeline_summary, upcoming_actions


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="X")); s.flush()
    di = Department(id=1, tenant_id=1, name="DI", code="DI", sort_order=1); s.add(di); s.flush()
    a1 = Acquisition(tenant_id=1, title="A", client_id=1, stage=AcquisitionStage.lead,
                     estimated_value=100000)  # weighted 10000
    a1.departments.append(di)
    a2 = Acquisition(tenant_id=1, title="B", client_id=1, stage=AcquisitionStage.won,
                     estimated_value=50000)   # weighted 50000, non "open"
    s.add_all([a1, a2]); s.commit()
    yield s, a1
    s.close()


def test_pipeline_summary(db):
    s, _ = db
    out = pipeline_summary(s, 1)
    assert out["open_count"] == 1  # won non è open
    assert out["total_weighted"] == Decimal("60000.00")
    assert out["by_department"]["DI"] == Decimal("10000.00")


def test_upcoming_actions(db):
    s, a1 = db
    a1.next_action = "Call regista"; a1.next_action_date = date.today() + timedelta(days=2)
    s.commit()
    out = upcoming_actions(s, 1, days=30)
    assert any(x["acquisition_id"] == a1.id for x in out)


def test_upcoming_actions_owner_filter():
    """owner_id filter must exclude activities belonging to other owners' acquisitions."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="X")); s.flush()

    acq1 = Acquisition(tenant_id=1, title="Owner1 deal", client_id=1,
                       stage=AcquisitionStage.lead, owner_user_id=1)
    acq2 = Acquisition(tenant_id=1, title="Owner2 deal", client_id=1,
                       stage=AcquisitionStage.lead, owner_user_id=2)
    s.add_all([acq1, acq2]); s.flush()

    act1 = Activity(tenant_id=1, acquisition_id=acq1.id, subject="Remind owner1",
                    next_action_date=date.today() + timedelta(days=3),
                    type=ActivityType.task)
    act2 = Activity(tenant_id=1, acquisition_id=acq2.id, subject="Remind owner2",
                    next_action_date=date.today() + timedelta(days=4),
                    type=ActivityType.task)
    s.add_all([act1, act2]); s.commit()

    out = upcoming_actions(s, 1, owner_id=1, days=30)
    activity_items = [x for x in out if x["kind"] == "activity"]
    ids = [x["id"] for x in activity_items]
    assert act1.id in ids, "act1 (owner1) should appear"
    assert act2.id not in ids, "act2 (owner2) must be excluded"
    s.close()
