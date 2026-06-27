# tests/test_kdm_facility_bulk_delete.py
from tests.test_kdm_link_edit import client  # riusa fixture
from app.models.models import CinemaFacility, CinemaServer


def _seed_facilities(s):
    s.add(CinemaFacility(id=1, tenant_id=1, name="Cinema A", is_active=True))
    s.add(CinemaFacility(id=2, tenant_id=1, name="Cinema B", is_active=True))
    s.add(CinemaServer(id=1, tenant_id=1, facility_id=1, serial="S1", is_active=True))
    s.add(CinemaServer(id=2, tenant_id=1, facility_id=1, serial="S2", is_active=True))
    s.commit()


def test_bulk_delete_facilities_and_servers(client):
    c, s = client
    _seed_facilities(s)
    r = c.post("/kdm/api/facilities/bulk-delete", data={"ids": "1,999"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 1
    assert body["servers_deleted"] == 2
    s.expire_all()
    assert s.get(CinemaFacility, 1).is_active is False
    assert s.get(CinemaServer, 1).is_active is False
    assert s.get(CinemaFacility, 2).is_active is True  # non toccato


def test_bulk_delete_empty_ids_400(client):
    c, _ = client
    assert c.post("/kdm/api/facilities/bulk-delete", data={"ids": ""}).status_code == 400
