"""Test egress_guard — Content Lockdown megaswitch (v3.5.0-alpha.172.195).

Core di sicurezza: risoluzione master + sub-switch → flag effettivi.
Fail-closed: tenant None o attributi mancanti → trattato come LOCKED.
Pure functions (duck-typed tenant), nessun DB necessario.
"""
import pytest
from types import SimpleNamespace

from app.services.egress_guard import (
    OPEN, LOCKDOWN,
    EgressLocked,
    effective_flags,
    cloud_ai_allowed, web_search_allowed, enrichment_allowed,
    assert_cloud_ai_allowed, assert_web_search_allowed, assert_enrichment_allowed,
)


def _tenant(master=OPEN, cloud_ai=True, web=True, enrich=True):
    return SimpleNamespace(
        id=1,
        lockdown_master=master,
        cloud_ai_enabled=cloud_ai,
        web_search_enabled=web,
        enrichment_enabled=enrich,
    )


# ── effective_flags: master override ────────────────────────────────

def test_open_all_subs_on():
    f = effective_flags(_tenant(OPEN, True, True, True))
    assert f == {"master": OPEN, "cloud_ai": True, "web_search": True, "enrichment": True}


def test_lockdown_master_forces_all_off_even_if_subs_on():
    # Master LOCKDOWN deve sovrascrivere i sub-switch tutti True.
    f = effective_flags(_tenant(LOCKDOWN, True, True, True))
    assert f["cloud_ai"] is False
    assert f["web_search"] is False
    assert f["enrichment"] is False
    assert f["master"] == LOCKDOWN


def test_open_with_individual_sub_off():
    # Master OPEN → sub rispettati singolarmente.
    f = effective_flags(_tenant(OPEN, cloud_ai=True, web=False, enrich=True))
    assert f["cloud_ai"] is True
    assert f["web_search"] is False
    assert f["enrichment"] is True


# ── fail-closed ─────────────────────────────────────────────────────

def test_none_tenant_fail_closed():
    f = effective_flags(None)
    assert f["cloud_ai"] is False
    assert f["web_search"] is False
    assert f["enrichment"] is False
    assert f["master"] == LOCKDOWN


def test_missing_master_attr_defaults_open():
    # Tenant esistente senza colonna ancora migrata → default OPEN (retrocompat).
    t = SimpleNamespace(id=1)  # nessun attributo lockdown_*
    f = effective_flags(t)
    assert f["master"] == OPEN
    assert f["cloud_ai"] is True
    assert f["web_search"] is True
    assert f["enrichment"] is True


def test_master_none_value_defaults_open():
    f = effective_flags(_tenant(master=None))
    assert f["master"] == OPEN


# ── *_allowed booleans ──────────────────────────────────────────────

def test_allowed_helpers_open():
    t = _tenant(OPEN)
    assert cloud_ai_allowed(t) is True
    assert web_search_allowed(t) is True
    assert enrichment_allowed(t) is True


def test_allowed_helpers_lockdown():
    t = _tenant(LOCKDOWN)
    assert cloud_ai_allowed(t) is False
    assert web_search_allowed(t) is False
    assert enrichment_allowed(t) is False


# ── assert_* raise EgressLocked ─────────────────────────────────────

def test_assert_passes_when_open():
    t = _tenant(OPEN)
    assert_cloud_ai_allowed(t)
    assert_web_search_allowed(t)
    assert_enrichment_allowed(t)  # nessuna eccezione


def test_assert_web_search_raises_when_locked():
    t = _tenant(OPEN, web=False)
    with pytest.raises(EgressLocked) as ei:
        assert_web_search_allowed(t)
    assert ei.value.vector == "web_search"
    assert ei.value.tenant_id == 1


def test_assert_enrichment_raises_under_master_lockdown():
    t = _tenant(LOCKDOWN)
    with pytest.raises(EgressLocked) as ei:
        assert_enrichment_allowed(t)
    assert ei.value.vector == "enrichment"


def test_assert_cloud_ai_raises_when_sub_off():
    t = _tenant(OPEN, cloud_ai=False)
    with pytest.raises(EgressLocked) as ei:
        assert_cloud_ai_allowed(t)
    assert ei.value.vector == "cloud_ai"


def test_assert_none_tenant_raises():
    with pytest.raises(EgressLocked):
        assert_web_search_allowed(None)
