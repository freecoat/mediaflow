"""tests/test_mobile.py — Task 1 smoke: router prefix + routes + app registration."""
from app.routers import mobile as mob


def test_mobile_router_prefix_and_routes():
    paths = {r.path for r in mob.router.routes}
    assert "/m" in paths or "/m/" in paths
    # le route principali esistono
    for p in ("/m/timbra", "/m/assegnazioni", "/m/ferie", "/m/notifiche"):
        assert p in paths


def test_mobile_router_registered_in_app():
    import app.main as m
    app_paths = {r.path for r in m.app.routes}
    assert any(p.startswith("/m") for p in app_paths)
