# tests/test_kdm_links_list_fields.py
# Riusa la fixture `client` di test_kdm_link_edit.py
from tests.test_kdm_link_edit import client  # noqa: F401


def test_list_includes_revoked_and_derived_fields(client):
    c, s = client
    data = c.get("/kdm/api/links").json()
    by_id = {x["id"]: x for x in data}
    # link 2 è revocato (is_active=False) → ora presente con revoked=True
    assert 2 in by_id and by_id[2]["revoked"] is True
    assert by_id[1]["revoked"] is False
    # client_name e requested_title presenti come chiavi
    assert "client_name" in by_id[1]
    assert "requested_title" in by_id[1]


def test_list_client_name_from_project(client):
    c, s = client
    from app.models.models import KdmRequestLink
    s.get(KdmRequestLink, 1).project_id = 1
    s.commit()
    data = {x["id"]: x for x in c.get("/kdm/api/links").json()}
    assert data[1]["client_name"] == "Arcadia"
