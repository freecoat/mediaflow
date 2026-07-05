from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from app.models.models import Base, CalendarEvent, CalendarEventStatus


def _engine():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return e


def test_calendar_events_table_columns():
    cols = {c["name"] for c in inspect(_engine()).get_columns("calendar_events")}
    expected = {
        "id", "tenant_id", "title", "description", "start_at", "end_at", "all_day",
        "location", "meeting_url", "status", "owner_user_id",
        "acquisition_id", "project_id", "activity_id", "client_id",
        "attendees", "source", "external_calendar_id", "external_event_id",
        "sync_state", "last_synced_at", "sync_error",
        "is_active", "created_by", "created_at", "updated_at",
    }
    assert expected <= cols


def test_status_enum_values():
    assert {s.value for s in CalendarEventStatus} == {"confirmed", "tentative", "cancelled"}


def test_defaults():
    ev = CalendarEvent(title="X")
    assert CalendarEvent.__table__.c.all_day.default.arg is False
    assert CalendarEvent.__table__.c.is_active.default.arg is True
    assert CalendarEvent.__table__.c.source.default.arg == "claqo"
    assert CalendarEvent.__table__.c.sync_state.default.arg == "local"
