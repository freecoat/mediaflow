from tests.test_calendar_api import client  # noqa: F401


def test_acquisitions_page_has_calendar_tab(client):
    c, _ = client
    html = c.get("/acquisitions").text
    assert 'data-tab="calendar"' in html
    assert 'id="det-tab-calendar"' in html
    assert 'acq.detail.tab.calendar' in html


def test_events_filtered_by_acquisition(client):
    c, s = client
    from app.models.models import Acquisition
    s.add(Acquisition(id=5, tenant_id=1, title="Deal5", stage="lead", is_active=True)); s.commit()
    c.post("/calendar/api/events", data={"title": "Riunione deal5",
           "start_at": "2026-07-12T09:00:00", "end_at": "2026-07-12T10:00:00", "acquisition_id": "5"})
    c.post("/calendar/api/events", data={"title": "Altro",
           "start_at": "2026-07-12T11:00:00", "end_at": "2026-07-12T12:00:00"})
    r = c.get("/calendar/api/events", params={"acquisition_id": 5}).json()
    titles = [e["title"] for e in r["events"]]
    assert "Riunione deal5" in titles and "Altro" not in titles
