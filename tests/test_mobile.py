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


import json, pathlib


def test_manifest_valid():
    m = json.loads(pathlib.Path("app/static/manifest.json").read_text(encoding="utf-8"))
    assert m["start_url"] == "/m"
    assert m["display"] == "standalone"
    assert any(i["sizes"] == "512x512" for i in m["icons"])


def test_base_mobile_has_drawer_markup():
    html = open("app/templates/mobile/base_mobile.html", encoding="utf-8").read()
    # header con hamburger che apre il drawer
    assert "m-drawer" in html
    assert "m-drawer-overlay" in html
    assert "mDrawerToggle" in html or "mDrawerOpen" in html
    # le 5 voci operative nel drawer
    for label in ("Oggi", "Timbr", "Assegnazion", "Ferie", "Notifich"):
        assert label in html
    # lucide caricato + init
    assert "lucide" in html
    # bottom tab bar v1 rimossa
    assert "m-tabbar" not in html


def test_mobile_js_has_drawer_helpers():
    js = open("app/static/js/mobile.js", encoding="utf-8").read()
    assert "mDrawerToggle" in js or "mDrawerOpen" in js
