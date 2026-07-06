from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, CalendarEvent
from app.services.ai_assistant import _ACTION_HANDLERS


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.commit()
    return s


def test_capability_registered():
    assert "propose_calendar_event" in _ACTION_HANDLERS


def test_acquisition_handlers_registered():
    # α.172.240: lo snapshot _ACTION_HANDLERS deve includere anche gli handler
    # definiti dopo la posizione storica dello snapshot (regressione α.236).
    for name in ("propose_acquisition", "propose_activity", "propose_contact",
                 "propose_acquisition_stage"):
        assert name in _ACTION_HANDLERS, name


def test_apply_creates_event():
    s = _session()
    fn = _ACTION_HANDLERS["propose_calendar_event"]
    res = fn(s, {"title": "Kickoff", "start_at": "2026-07-15T10:00:00",
                 "end_at": "2026-07-15T11:00:00", "client_id": 1})
    s.commit()
    assert res["created"] is True
    ev = s.query(CalendarEvent).filter_by(id=res["calendar_event_id"]).first()
    assert ev.title == "Kickoff" and ev.client_id == 1
