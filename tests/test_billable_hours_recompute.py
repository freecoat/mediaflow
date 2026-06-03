"""Integrazione: billable_hours_mode su Booking -> quantity_actual nel cost report.
Costo interno (total_cost_accrued) invariato dal mode."""
import pytest
from datetime import datetime
from app.services.cost_line_sync import recompute_cost_line_actual


@pytest.fixture
def done_booking_two_humans(db):
    from app.models import (
        Resource, ResourceType, Client, Project, Job, JobCostLine,
        Booking, BookingAssignment,
        BookingStatus, BookingExecutionStatus, BookingState,
    )
    r1 = Resource(tenant_id=1, name="Carlo", type=ResourceType.person_internal, is_active=True)
    r2 = Resource(tenant_id=1, name="Mario", type=ResourceType.person_internal, is_active=True)
    db.add_all([r1, r2]); db.flush()
    # Job richiede project_id + client_id NOT NULL → costruisco la gerarchia.
    cli = Client(tenant_id=1, name="ACME")
    db.add(cli); db.flush()
    prj = Project(tenant_id=1, code="P-TEST", title="Test Project", client_id=cli.id)
    db.add(prj); db.flush()
    job = Job(tenant_id=1, code="J-TEST", title="Test",
              project_id=prj.id, client_id=cli.id)
    db.add(job); db.flush()
    jcl = JobCostLine(tenant_id=1, job_id=job.id, description="Color", unit="hr", unit_price=100.0)
    db.add(jcl); db.flush()
    b = Booking(
        tenant_id=1, job_id=job.id, job_cost_line_id=jcl.id,
        start_datetime=datetime(2026, 6, 10, 9, 0), end_datetime=datetime(2026, 6, 10, 17, 0),
        status=BookingStatus.confirmed, state=BookingState.done,
        execution_status=BookingExecutionStatus.done, billable_hours_mode="max",
    )
    db.add(b); db.flush()
    db.add_all([
        BookingAssignment(booking_id=b.id, resource_id=r1.id,
            start_datetime=datetime(2026,6,10,9,0), end_datetime=datetime(2026,6,10,17,0)),  # 8h
        BookingAssignment(booking_id=b.id, resource_id=r2.id,
            start_datetime=datetime(2026,6,10,9,0), end_datetime=datetime(2026,6,10,15,0)),  # 6h
    ])
    db.commit(); db.refresh(jcl); db.refresh(b)
    return jcl, b


def test_mode_max_quantity_is_8(db, done_booking_two_humans):
    jcl, b = done_booking_two_humans
    recompute_cost_line_actual(db, jcl)
    assert jcl.quantity_actual == 8.0


def test_mode_sum_quantity_is_14(db, done_booking_two_humans):
    jcl, b = done_booking_two_humans
    b.billable_hours_mode = "sum"; db.commit()
    recompute_cost_line_actual(db, jcl)
    assert jcl.quantity_actual == 14.0


def test_internal_cost_invariant_across_modes(db, done_booking_two_humans):
    jcl, b = done_booking_two_humans
    recompute_cost_line_actual(db, jcl)
    cost_max = jcl.total_cost_accrued
    b.billable_hours_mode = "sum"; db.commit()
    recompute_cost_line_actual(db, jcl)
    assert jcl.total_cost_accrued == cost_max
