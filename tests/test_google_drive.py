from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc
from app.services import google_drive as gd


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, is_active=True))
    s.commit()
    return s


def _connect(s):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()


def test_parse_file_url():
    assert gd.parse_drive_file_id("https://drive.google.com/file/d/ABC123/view?usp=sharing") == "ABC123"


def test_parse_docs_url():
    assert gd.parse_drive_file_id("https://docs.google.com/document/d/XYZ_9/edit") == "XYZ_9"


def test_parse_sheets_url():
    assert gd.parse_drive_file_id("https://docs.google.com/spreadsheets/d/SHEET1/edit#gid=0") == "SHEET1"


def test_parse_open_id_url():
    assert gd.parse_drive_file_id("https://drive.google.com/open?id=OID42") == "OID42"


def test_parse_uc_id_url():
    assert gd.parse_drive_file_id("https://drive.google.com/uc?id=UC7&export=download") == "UC7"


def test_parse_non_drive_url_none():
    assert gd.parse_drive_file_id("https://example.com/foo") is None


def test_fetch_metadata_ok(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gd, "_drive_request", lambda m, u, t, params=None: {
        "id": "ABC", "name": "Contratto.pdf", "mimeType": "application/pdf",
        "webViewLink": "https://drive.google.com/file/d/ABC/view",
        "iconLink": "https://ssl.gstatic.com/pdf.png",
        "owners": [{"emailAddress": "owner@x.com"}]})
    md = gd.fetch_file_metadata(s, 1, "ABC")
    assert md["file_id"] == "ABC"
    assert md["name"] == "Contratto.pdf"
    assert md["mime_type"] == "application/pdf"
    assert md["web_url"].endswith("/view")
    assert md["owner_email"] == "owner@x.com"


def test_fetch_metadata_none_without_token():
    s = _session()  # nessun token
    assert gd.fetch_file_metadata(s, 1, "ABC") is None


def test_fetch_metadata_best_effort_on_error(monkeypatch):
    s = _session(); _connect(s)
    def boom(*a, **k): raise RuntimeError("HTTP 403: Forbidden")
    monkeypatch.setattr(gd, "_drive_request", boom)
    assert gd.fetch_file_metadata(s, 1, "ABC") is None
