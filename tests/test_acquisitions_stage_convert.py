# tests/test_acquisitions_stage_convert.py
# Riusa la fixture `client` di test_acquisitions_api.py via import.
from tests.test_acquisitions_api import client  # noqa: F401


def test_stage_change(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "1000"}).json()["id"]
    r = c.post(f"/acquisitions/api/{aid}/stage", data={"stage": "negotiation"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "negotiation"
    assert r.json()["effective_probability"] == "70.0"


def test_convert_to_project(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "Film Q", "client_id": "1",
                 "stage": "won", "estimated_value": "0"}).json()["id"]
    r = c.post(f"/acquisitions/api/{aid}/convert", data={"code": "PRJ-Q", "title": "Film Q"})
    assert r.status_code == 200, r.text
    assert r.json()["project_id"]
