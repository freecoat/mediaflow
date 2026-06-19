"""TDD tests for KDM router skeleton (Task 9).
v3.5.0-alpha.172.226
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_kdm_page_loads():
    r = client.get("/kdm")
    # Auth middleware may redirect; accept 200 or auth redirect, never 404/500.
    assert r.status_code in (200, 302, 303, 401)


def test_requests_api_shape():
    r = client.get("/kdm/api/requests")
    assert r.status_code in (200, 401, 403)
