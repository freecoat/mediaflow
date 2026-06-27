# tests/test_acquisition_capabilities.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, Client, Acquisition, AcquisitionStage
from app.services.ai_capability_registry import get_handler


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky")); s.commit()
    yield s
    s.close()


def test_propose_acquisition_registered_and_creates(db):
    import app.services.ai_assistant  # noqa: F401  (forza registrazione)
    h = get_handler("propose_acquisition")
    assert h is not None
    out = h(db, {"title": "Film X", "client_id": 1, "stage": "lead",
                 "estimated_value": 50000})
    db.commit()
    assert "acquisition_id" in out
    acq = db.query(Acquisition).get(out["acquisition_id"])
    assert acq.title == "Film X" and acq.stage == AcquisitionStage.lead


def test_propose_activity_and_stage(db):
    import app.services.ai_assistant  # noqa: F401
    acq = Acquisition(tenant_id=1, title="A", client_id=1, stage=AcquisitionStage.lead,
                      estimated_value=0)
    db.add(acq); db.commit()
    get_handler("propose_activity")(db, {"acquisition_id": acq.id, "type": "call",
                                         "subject": "Chiamata"})
    db.commit()
    get_handler("propose_acquisition_stage")(db, {"acquisition_id": acq.id, "stage": "quoting"})
    db.commit()
    db.refresh(acq)
    assert acq.stage == AcquisitionStage.quoting
