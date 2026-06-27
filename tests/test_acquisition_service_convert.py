# tests/test_acquisition_service_convert.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Project, ProjectStatus, Acquisition, AcquisitionStage,
)
from app.services.acquisition_service import apply_stage_change, convert_to_project


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="X")); s.commit()
    yield s
    s.close()


def test_convert_creates_project_and_links(db):
    acq = Acquisition(tenant_id=1, title="Film Y", client_id=1,
                      stage=AcquisitionStage.won, estimated_value=10000)
    db.add(acq); db.commit()
    p = convert_to_project(db, acq, code="PRJ-Y", title="Film Y")
    assert p.id and acq.project_id == p.id
    assert p.status == ProjectStatus.active  # won → active
    assert p.client_id == 1


def test_convert_prospect_creates_client(db):
    acq = Acquisition(tenant_id=1, title="Lead Z", client_id=None,
                      prospect_name="Nuova Casa SRL", stage=AcquisitionStage.qualified,
                      estimated_value=0)
    db.add(acq); db.commit()
    p = convert_to_project(db, acq, code="PRJ-Z")
    assert acq.client_id is not None
    cl = db.query(Client).get(acq.client_id)
    assert cl.name == "Nuova Casa SRL"
    assert p.status == ProjectStatus.quoting  # qualified→quoting per default mapper


def test_apply_stage_change_syncs_project(db):
    p = Project(tenant_id=1, code="P1", title="P1", client_id=1, status=ProjectStatus.prospect)
    db.add(p); db.commit()
    acq = Acquisition(tenant_id=1, title="A", client_id=1, project_id=p.id,
                      stage=AcquisitionStage.lead, estimated_value=0)
    db.add(acq); db.commit()
    apply_stage_change(db, acq, AcquisitionStage.won)
    assert acq.stage == AcquisitionStage.won
    assert db.query(Project).get(p.id).status == ProjectStatus.active
