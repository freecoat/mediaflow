"""Test di regressione per i fix dell'audit TPN/DAM P1 (31 mag 2026).

Copre i 5 gap chiusi in v3.5.0-alpha.172.147:
  #1 metadata/delivery-info no-auth-check → ora gated da user_can_access_asset
  #2 MFA required vale anche su upload/delete (non solo download)
  #3 secure-delete è il DEFAULT (secure=1)
  #4 watermark anche su PDF (apply_watermark_pdf)
  #5 uploaded_by deriva dall'utente autenticato (anti-spoof), non dal form

Approccio: i gate auth sono testati chiamando direttamente la coroutine
del router con Request fittizia + helper monkeypatchati (testa che la rotta
ONORI l'helper, che è la regressione che vogliamo bloccare). Le funzioni
dam_security sono unit-testabili direttamente.
"""
import asyncio
import inspect
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import models as m
from app.models import AssetType, AssetAccessAction
from app.routers import dam as dam_router
from app.services import dam_security


# ── Helpers ──────────────────────────────────────────────────────────
class _FakeRequest:
    """Request minimale: il router usa solo request per current_user_optional
    (monkeypatchato) e log_asset_access (monkeypatchato)."""
    client = SimpleNamespace(host="127.0.0.1")
    headers = {}


class _FakeUpload:
    """UploadFile stub: .size, .filename, await .read()."""
    def __init__(self, data: bytes, filename: str):
        self._data = data
        self.size = len(data)
        self.filename = filename

    async def read(self):
        return self._data


def _mk_client(db):
    c = m.Client(tenant_id=1, name="C-Test")
    db.add(c)
    db.flush()
    return c


def _mk_project(db, *, mfa_required=False):
    c = _mk_client(db)
    p = m.Project(tenant_id=1, code="PRJ-T", title="Test", client_id=c.id,
                  mfa_required=mfa_required)
    db.add(p)
    db.flush()
    return p


def _mk_asset(db, *, project_id=None, file_path="s3://b/k.png"):
    # file_path NOT NULL; "s3://" fa short-circuitare l'estrazione metadata
    # nella rotta (ritorna dict skip prima di toccare il filesystem).
    a = m.Asset(
        tenant_id=1, filename="f.png", original_name="f.png",
        file_path=file_path, asset_type=AssetType.image,
        mime_type="image/png", file_size=10, project_id=project_id,
        uploaded_by=1,
    )
    db.add(a)
    db.flush()
    return a


def _patch_common(monkeypatch, *, user):
    monkeypatch.setattr(dam_router, "current_tenant_id", lambda: 1)
    monkeypatch.setattr(dam_router, "current_user_optional", lambda req: user)
    monkeypatch.setattr(dam_router, "log_asset_access", lambda *a, **k: None)


# ── #1 metadata / delivery-info auth gate ────────────────────────────
def test_metadata_denied_when_no_access(db, monkeypatch):
    a = _mk_asset(db, project_id=None)
    user = SimpleNamespace(id=5, email="u@x.it")
    _patch_common(monkeypatch, user=user)
    monkeypatch.setattr(dam_router, "user_can_access_asset", lambda u, asset, d: False)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(dam_router.get_asset_metadata(a.id, _FakeRequest(), db))
    assert ei.value.status_code == 403


def test_metadata_allowed_when_access(db, monkeypatch):
    a = _mk_asset(db, project_id=None)  # no file_path → early dict
    user = SimpleNamespace(id=5, email="u@x.it")
    _patch_common(monkeypatch, user=user)
    monkeypatch.setattr(dam_router, "user_can_access_asset", lambda u, asset, d: True)
    out = asyncio.run(dam_router.get_asset_metadata(a.id, _FakeRequest(), db))
    assert out["asset_id"] == a.id  # passa il gate, ritorna dict (s3 skip)


def test_delivery_info_denied_when_no_access(db, monkeypatch):
    a = _mk_asset(db, project_id=None)
    user = SimpleNamespace(id=5, email="u@x.it")
    _patch_common(monkeypatch, user=user)
    monkeypatch.setattr(dam_router, "user_can_access_asset", lambda u, asset, d: False)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(dam_router.get_asset_delivery_info(a.id, _FakeRequest(), db))
    assert ei.value.status_code == 403


def test_metadata_signature_has_request():
    # Regressione: senza Request non c'è modo di risolvere l'utente → no gate.
    sig = inspect.signature(dam_router.get_asset_metadata)
    assert "request" in sig.parameters
    sig2 = inspect.signature(dam_router.get_asset_delivery_info)
    assert "request" in sig2.parameters


# ── #5 uploaded_by anti-spoof ────────────────────────────────────────
def _patch_upload_io(monkeypatch):
    monkeypatch.setattr(dam_router, "save_upload",
                        lambda b, name: (name, f"/tmp/{name}", "image/png"))
    monkeypatch.setattr(dam_router, "generate_thumbnail", lambda p, mt: None)
    monkeypatch.setattr(dam_router, "resolve_asset_type", lambda mt: AssetType.image)


def test_uploaded_by_uses_authenticated_user_not_form(db, monkeypatch):
    user = SimpleNamespace(id=7, email="real@x.it")
    _patch_common(monkeypatch, user=user)
    _patch_upload_io(monkeypatch)
    res = asyncio.run(dam_router.upload_asset(
        _FakeRequest(), file=_FakeUpload(b"x" * 10, "f.png"),
        job_id=None, project_id=None, uploaded_by=999,  # spoof attempt
        description=None, tags=None, db=db,
    ))
    asset = db.query(m.Asset).filter(m.Asset.id == res["id"]).first()
    assert asset.uploaded_by == 7  # autenticato, NON 999


def test_uploaded_by_falls_back_to_form_when_unauthenticated(db, monkeypatch):
    _patch_common(monkeypatch, user=None)  # no sessione
    _patch_upload_io(monkeypatch)
    res = asyncio.run(dam_router.upload_asset(
        _FakeRequest(), file=_FakeUpload(b"x" * 10, "f.png"),
        job_id=None, project_id=None, uploaded_by=42,
        description=None, tags=None, db=db,
    ))
    asset = db.query(m.Asset).filter(m.Asset.id == res["id"]).first()
    assert asset.uploaded_by == 42  # fallback al form (script/seed)


# ── #2 MFA required su upload/delete ─────────────────────────────────
def test_upload_blocked_when_project_requires_mfa(db, monkeypatch):
    p = _mk_project(db, mfa_required=True)
    user = SimpleNamespace(id=7, email="real@x.it", mfa_enabled=False)
    _patch_common(monkeypatch, user=user)
    _patch_upload_io(monkeypatch)
    monkeypatch.setattr(dam_router, "is_admin", lambda u: False)
    monkeypatch.setattr(dam_router, "user_can_access_project", lambda u, pid, d: True)
    # check_project_mfa_required reale: project.mfa_required=True + user no mfa → False
    with pytest.raises(HTTPException) as ei:
        asyncio.run(dam_router.upload_asset(
            _FakeRequest(), file=_FakeUpload(b"x" * 10, "f.png"),
            job_id=None, project_id=p.id, uploaded_by=None,
            description=None, tags=None, db=db,
        ))
    assert ei.value.status_code == 403
    assert "MFA" in ei.value.detail


def test_delete_blocked_when_project_requires_mfa(db, monkeypatch):
    p = _mk_project(db, mfa_required=True)
    a = _mk_asset(db, project_id=p.id)
    user = SimpleNamespace(id=7, email="real@x.it", mfa_enabled=False)
    _patch_common(monkeypatch, user=user)
    monkeypatch.setattr(dam_router, "user_can_access_asset", lambda u, asset, d: True)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(dam_router.delete_asset(a.id, _FakeRequest(), secure=1, db=db))
    assert ei.value.status_code == 403
    assert "MFA" in ei.value.detail


# ── #3 secure-delete default ─────────────────────────────────────────
def test_delete_default_is_secure():
    sig = inspect.signature(dam_router.delete_asset)
    assert sig.parameters["secure"].default == 1


# ── #4 watermark PDF + helper mime ───────────────────────────────────
def test_is_pdf_mime():
    assert dam_security.is_pdf_mime("application/pdf") is True
    assert dam_security.is_pdf_mime("image/png") is False
    assert dam_security.is_pdf_mime(None) is False


def test_apply_watermark_pdf_returns_valid_pdf():
    import fitz
    # Crea un PDF minimo 2 pagine → bytes (no file handle aperto su Windows)
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 72), "Contenuto riservato capitolato")
    src_bytes = doc.tobytes()
    doc.close()
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(src_bytes)
    try:
        out = dam_security.apply_watermark_pdf(path, user_email="u@x.it", extra="asset:1")
        assert out is not None
        assert out[:4] == b"%PDF"
        # Riapribile + stesso numero pagine
        re = fitz.open(stream=out, filetype="pdf")
        assert re.page_count == 2
        re.close()
    finally:
        os.unlink(path)


def test_apply_watermark_pdf_none_on_bad_file():
    assert dam_security.apply_watermark_pdf("/nonexistent/x.pdf") is None
