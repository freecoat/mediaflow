from tests.test_acquisitions_api import client  # noqa: F401


def test_add_list_activity(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    r = c.post(f"/acquisitions/api/{aid}/activities", data={
        "type": "email", "subject": "Primo contatto", "body": "Ciao",
        "direction": "outbound"})
    assert r.status_code in (200, 201), r.text
    lst = c.get(f"/acquisitions/api/{aid}/activities").json()
    assert lst["items"][0]["subject"] == "Primo contatto"
    assert lst["items"][0]["type"] == "email"


def test_delete_activity(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    act_id = c.post(f"/acquisitions/api/{aid}/activities",
                    data={"type": "note", "subject": "x"}).json()["id"]
    assert c.delete(f"/activities/api/{act_id}").status_code == 200
    assert c.get(f"/acquisitions/api/{aid}/activities").json()["items"] == []


def test_update_activity(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    act_id = c.post(f"/acquisitions/api/{aid}/activities",
                    data={"type": "note", "subject": "Oggetto originale"}).json()["id"]
    r = c.put(f"/activities/api/{act_id}", data={"subject": "Oggetto aggiornato"})
    assert r.status_code == 200, r.text
    assert r.json()["subject"] == "Oggetto aggiornato"


def test_add_activity_invalid_type_422(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    r = c.post(f"/acquisitions/api/{aid}/activities",
               data={"type": "invalid", "subject": "test"})
    assert r.status_code == 422, r.text
