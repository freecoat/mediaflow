"""tests/test_booking_respond.py — Task 8 mobile PWA.

Verifica endpoint POST /planning/api/my-bookings/{booking_id}/respond:
- staff accetta la propria assegnazione → response_status == "accepted"
- staff rifiuta la propria assegnazione → response_status == "rejected"
- booking assegnato ad ALTRA risorsa → HTTPException 403
- action non valida → HTTPException 400
- utente non loggato (None) → HTTPException 401
"""
import asyncio
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models import models as m
from app.routers import planning as planning_router


# ── Fake request (auth già monkeypatchata) ────────────────────

class _FakeRequest:
    pass


# ── Shared setup helper ───────────────────────────────────────

def _setup_world(db, *, user_email="staff@mediaflow.it"):
    """Crea Tenant / Client / Project per le FK obbligatorie."""
    t = m.Tenant(id=1, name="T", slug="t", default_currency="EUR")
    db.add(t)
    db.flush()

    user = m.User(
        tenant_id=1,
        email=user_email,
        full_name="Staff Test",
        hashed_password="x",
        role=m.UserRole.staff,
    )
    db.add(user)
    db.flush()

    client = m.Client(tenant_id=1, name="Cliente Test")
    db.add(client)
    db.flush()

    project = m.Project(
        tenant_id=1,
        code="P-TEST",
        title="Progetto Test",
        client_id=client.id,
    )
    db.add(project)
    db.flush()

    return user, client, project


def _make_resource(db, user, name="Risorsa"):
    r = m.Resource(
        tenant_id=1,
        name=name,
        type=m.ResourceType.person_internal,
        user_id=user.id,
    )
    db.add(r)
    db.flush()
    return r


def _make_job(db, client, project, code="JOB-001"):
    j = m.Job(
        tenant_id=1,
        code=code,
        title="Job Test",
        project_id=project.id,
        client_id=client.id,
        status=m.JobStatus.active,
    )
    db.add(j)
    db.flush()
    return j


def _make_booking(db, job):
    b = m.Booking(
        tenant_id=1,
        job_id=job.id,
        start_datetime=datetime(2026, 6, 1, 9, 0),
        end_datetime=datetime(2026, 6, 1, 17, 0),
        status=m.BookingStatus.confirmed,
        kind=m.BookingKind.project,
        state=m.BookingState.confirmed,
    )
    db.add(b)
    db.flush()
    return b


def _make_assignment(db, booking, resource):
    a = m.BookingAssignment(
        booking_id=booking.id,
        resource_id=resource.id,
        start_datetime=booking.start_datetime,
        end_datetime=booking.end_datetime,
    )
    db.add(a)
    db.flush()
    return a


def _patch_planning(monkeypatch, user, tenant_id=1):
    monkeypatch.setattr(planning_router, "current_user_optional", lambda req: user)
    monkeypatch.setattr(planning_router, "current_tenant_id", lambda: tenant_id)


# ── Tests ─────────────────────────────────────────────────────

def test_respond_accept_own_booking(db, monkeypatch):
    """Staff accetta la propria assegnazione → response_status == 'accepted'."""
    user, client, project = _setup_world(db)
    resource = _make_resource(db, user)
    job = _make_job(db, client, project, code="JOB-A1")
    booking = _make_booking(db, job)
    assignment = _make_assignment(db, booking, resource)

    _patch_planning(monkeypatch, user)

    result = asyncio.run(
        planning_router.respond_my_booking(
            booking_id=booking.id,
            request=_FakeRequest(),
            action="accept",
            db=db,
        )
    )

    assert result == {"ok": True, "status": "accepted"}
    db.refresh(assignment)
    assert assignment.response_status == "accepted"


def test_respond_reject_own_booking(db, monkeypatch):
    """Staff rifiuta la propria assegnazione → response_status == 'rejected'."""
    user, client, project = _setup_world(db, user_email="staff2@mediaflow.it")
    resource = _make_resource(db, user, name="Risorsa B")
    job = _make_job(db, client, project, code="JOB-B1")
    booking = _make_booking(db, job)
    assignment = _make_assignment(db, booking, resource)

    _patch_planning(monkeypatch, user)

    result = asyncio.run(
        planning_router.respond_my_booking(
            booking_id=booking.id,
            request=_FakeRequest(),
            action="reject",
            db=db,
        )
    )

    assert result == {"ok": True, "status": "rejected"}
    db.refresh(assignment)
    assert assignment.response_status == "rejected"


def test_respond_other_resource_raises_403(db, monkeypatch):
    """Booking assegnato ad altra risorsa → HTTPException 403."""
    # user_a crea il booking
    user_a, client, project = _setup_world(db, user_email="staffa@mediaflow.it")
    resource_a = _make_resource(db, user_a, name="Risorsa A")
    job = _make_job(db, client, project, code="JOB-C1")
    booking = _make_booking(db, job)
    _make_assignment(db, booking, resource_a)

    # user_b tenta di rispondere — non è assegnato al booking
    user_b = m.User(
        tenant_id=1,
        email="staffb@mediaflow.it",
        full_name="Staff B",
        hashed_password="x",
        role=m.UserRole.staff,
    )
    db.add(user_b)
    db.flush()
    _make_resource(db, user_b, name="Risorsa B")

    _patch_planning(monkeypatch, user_b)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            planning_router.respond_my_booking(
                booking_id=booking.id,
                request=_FakeRequest(),
                action="accept",
                db=db,
            )
        )

    assert exc_info.value.status_code == 403


def test_respond_invalid_action_raises_400(db, monkeypatch):
    """action non valida → HTTPException 400."""
    user, client, project = _setup_world(db, user_email="staff3@mediaflow.it")
    resource = _make_resource(db, user, name="Risorsa C")
    job = _make_job(db, client, project, code="JOB-D1")
    booking = _make_booking(db, job)
    _make_assignment(db, booking, resource)

    _patch_planning(monkeypatch, user)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            planning_router.respond_my_booking(
                booking_id=booking.id,
                request=_FakeRequest(),
                action="maybe",
                db=db,
            )
        )

    assert exc_info.value.status_code == 400


def test_respond_unauthenticated_raises_401(db, monkeypatch):
    """Utente non loggato (None) → HTTPException 401."""
    # Non serve setup dati: il check è prima di qualsiasi query
    _patch_planning(monkeypatch, None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            planning_router.respond_my_booking(
                booking_id=999,
                request=_FakeRequest(),
                action="accept",
                db=db,
            )
        )

    assert exc_info.value.status_code == 401
