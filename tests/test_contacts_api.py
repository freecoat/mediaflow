# tests/test_contacts_api.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from tests.test_acquisitions_api import client  # riusa fixture (role manager ha edit_clients? aggiungi)
from app.models.models import Base, User, Role, Tenant, UserRole, Client


def _ensure_client_perms(s):
    """Garantisce che la role della fixture abbia view_clients + edit_clients."""
    role = s.query(__import__("app.models.models", fromlist=["Role"]).Role).first()
    for p in ("view_clients", "edit_clients"):
        if p not in (role.permissions or []):
            role.permissions = (role.permissions or []) + [p]
    s.commit()


def test_contact_crud_and_primary_sync(client):
    c, s = client
    _ensure_client_perms(s)
    r = c.post("/clients/api/1/contacts", data={"name": "Mario Rossi",
               "email": "m@x.it", "role": "Producer", "is_primary": "true"})
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    lst = c.get("/clients/api/1/contacts").json()
    assert any(x["id"] == cid for x in lst["items"])
    # primary sync su Client
    cl = s.query(Client).get(1)
    assert cl.contact_name == "Mario Rossi"
    assert cl.contact_email == "m@x.it"
    assert c.delete(f"/contacts/api/{cid}").status_code == 200


def test_list_contacts_unknown_client_404(client):
    """GET su cliente inesistente deve restituire 404."""
    c, s = client
    _ensure_client_perms(s)
    r = c.get("/clients/api/99999/contacts")
    assert r.status_code == 404, r.text


def test_view_clients_permission_allows_contacts_api(client):
    """Utente con view_clients (senza view_finance) può accedere a /clients/api/{id}/contacts."""
    c, s = client
    _ensure_client_perms(s)
    # Il fixture non ha view_finance, ma ha view_clients — deve ottenere 200
    r = c.get("/clients/api/1/contacts")
    assert r.status_code == 200, r.text
    assert "items" in r.json()


def test_view_clients_only_cannot_reach_client_mutators(client):
    """Utente con view_clients (senza view_finance) NON può creare/aggiornare clienti.

    Fix 1 (security): il middleware apre SOLO /clients/api/<id>/contacts per
    chi ha view_clients. Tutti gli altri /clients/api/* restano dietro la finance gate.
    """
    c, s = client
    # Aggiunge solo view_clients — NO view_finance, NO edit_clients
    role = s.query(__import__("app.models.models", fromlist=["Role"]).Role).first()
    if "view_clients" not in (role.permissions or []):
        role.permissions = (role.permissions or []) + ["view_clients"]
    s.commit()
    # POST /clients/api (create client) → bloccato dal middleware → 403
    r = c.post("/clients/api", data={"name": "Hacker Client"})
    assert r.status_code == 403, (
        f"POST /clients/api doveva essere 403, ottenuto {r.status_code}: {r.text}"
    )
    # PUT /clients/api/1 (update client) → bloccato dal middleware → 403
    r2 = c.put("/clients/api/1", data={"name": "Hacked Name"})
    assert r2.status_code == 403, (
        f"PUT /clients/api/1 doveva essere 403, ottenuto {r2.status_code}: {r2.text}"
    )
