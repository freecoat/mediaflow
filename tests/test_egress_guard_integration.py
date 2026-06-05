"""Integration egress_guard — risoluzione CURRENT_TENANT da DB + handler copilot.

Usa la fixture `db` (SQLite in-memory). Crea Tenant id=1 con vari stati di
lockdown e verifica i wrapper *_current + il capability handler web_search.
"""
import pytest

from app.models.models import Tenant
from app.services import egress_guard


def _mk_tenant(db, **kw):
    t = Tenant(id=1, name="Default", slug="default", **kw)
    db.add(t)
    db.commit()
    return t


def test_current_helpers_open(db):
    _mk_tenant(db, lockdown_master="OPEN", cloud_ai_enabled=True,
               web_search_enabled=True, enrichment_enabled=True)
    assert egress_guard.web_search_allowed_current(db) is True
    assert egress_guard.enrichment_allowed_current(db) is True


def test_current_helpers_master_lockdown(db):
    _mk_tenant(db, lockdown_master="LOCKDOWN", cloud_ai_enabled=True,
               web_search_enabled=True, enrichment_enabled=True)
    assert egress_guard.web_search_allowed_current(db) is False
    assert egress_guard.enrichment_allowed_current(db) is False
    with pytest.raises(egress_guard.EgressLocked):
        egress_guard.assert_enrichment_allowed_current(db)


def test_current_helpers_sub_off(db):
    _mk_tenant(db, lockdown_master="OPEN", cloud_ai_enabled=True,
               web_search_enabled=False, enrichment_enabled=True)
    assert egress_guard.web_search_allowed_current(db) is False
    assert egress_guard.enrichment_allowed_current(db) is True


def test_no_tenant_fail_closed(db):
    # Nessun tenant in DB → fail-closed.
    assert egress_guard.web_search_allowed_current(db) is False


def test_web_search_handler_blocked_message(db):
    """Il capability handler web_search restituisce errore lockdown chiaro."""
    _mk_tenant(db, lockdown_master="LOCKDOWN")
    from app.services.ai_assistant import _h_web_search
    out = _h_web_search(db, {"query": "Gomorra S4 delivery specs"})
    assert out["results"] is None
    assert "Lockdown" in out["error"] or "lockdown" in out["error"].lower()


def test_web_search_handler_allowed_passes_gate(db, monkeypatch):
    """Con OPEN il gate passa e si arriva a tavily_search (qui mockato None)."""
    _mk_tenant(db, lockdown_master="OPEN", web_search_enabled=True)
    import app.services.web_search as ws
    monkeypatch.setattr(ws, "tavily_search", lambda *a, **k: None)
    from app.services.ai_assistant import _h_web_search
    out = _h_web_search(db, {"query": "x"})
    # Gate superato → messaggio è quello "Tavily non disponibile", non lockdown.
    assert out["results"] is None
    assert "Lockdown" not in out["error"]
