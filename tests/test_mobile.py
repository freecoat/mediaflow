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


IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def test_mail_and_acquisitions_are_redirect_exempt():
    import app.main as m
    assert "/mail" in m._MOBILE_REDIR_EXEMPT
    assert "/acquisitions" in m._MOBILE_REDIR_EXEMPT


def _client_with_auth(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.models import Base, Tenant, User, UserRole
    from app.services.auth import create_access_token
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    c = TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"})
    return c, main_mod, get_db


def test_mail_not_redirected_for_mobile_ua(monkeypatch):
    c, main_mod, get_db = _client_with_auth(monkeypatch)
    try:
        r = c.get("/mail", headers={"User-Agent": IPHONE_UA, "Accept": "text/html"},
                  follow_redirects=False)
        assert not (r.status_code == 302 and r.headers.get("location", "").startswith("/m"))
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


def test_dashboard_still_redirected_for_mobile_ua(monkeypatch):
    c, main_mod, get_db = _client_with_auth(monkeypatch)
    try:
        r = c.get("/dashboard", headers={"User-Agent": IPHONE_UA, "Accept": "text/html"},
                  follow_redirects=False)
        assert r.status_code == 302 and r.headers.get("location", "").startswith("/m")
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


def test_drawer_has_commerciale_links():
    html = open("app/templates/mobile/base_mobile.html", encoding="utf-8").read()
    assert 'href="/mail"' in html
    assert 'href="/acquisitions"' in html
    assert "Commerciale" in html


def test_base_has_sidebar_backdrop():
    html = open("app/templates/base.html", encoding="utf-8").read()
    assert 'id="mf-sidebar-backdrop"' in html


def test_global_toggle_is_viewport_aware():
    js = open("app/static/js/global.js", encoding="utf-8").read()
    assert "mfCloseSidebarMobile" in js
    assert "max-width:768px" in js.replace(" ", "")
