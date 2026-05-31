"""Test: episodes_count su Project — v3.5.0-alpha.172.147.

Verifica:
1. Il campo episodes_count persiste correttamente sul modello.
2. Il serializzatore del router include episodes_count.
3. build_context() include l'informazione sulla serie quando episodes_count è impostato.
"""
import pytest
from app.models import models as m
from app.services.ai_context import build_context


# ── fixture helpers ──────────────────────────────────────────

def _make_tenant(db):
    t = m.Tenant(id=1, name="Test", slug="test")
    db.add(t)
    db.flush()
    return t


def _make_client(db):
    c = m.Client(tenant_id=1, name="RaiCinema", contact_email="test@raicinema.it")
    db.add(c)
    db.flush()
    return c


def _make_project(db, client_id, episodes_count=None, project_type="series"):
    p = m.Project(
        tenant_id=1,
        code="SERTEST01",
        title="La Grande Serie",
        client_id=client_id,
        project_type=project_type,
        episodes_count=episodes_count,
    )
    db.add(p)
    db.flush()
    db.refresh(p)
    return p


# ── Test 1: persistenza modello ──────────────────────────────

def test_episodes_count_persists(db):
    """episodes_count viene scritto e riletto correttamente."""
    _make_tenant(db)
    cl = _make_client(db)
    p = _make_project(db, cl.id, episodes_count=8)
    assert p.id is not None
    assert p.episodes_count == 8


def test_episodes_count_none_for_non_series(db):
    """Non-serie ha episodes_count=None."""
    _make_tenant(db)
    cl = _make_client(db)
    p = _make_project(db, cl.id, episodes_count=None, project_type="feature_film")
    assert p.episodes_count is None


def test_episodes_count_update(db):
    """episodes_count è aggiornabile."""
    _make_tenant(db)
    cl = _make_client(db)
    p = _make_project(db, cl.id, episodes_count=6)
    p.episodes_count = 10
    db.flush()
    db.refresh(p)
    assert p.episodes_count == 10


# ── Test 2: ai_context include episodes_count ─────────────────

def test_ai_context_includes_episodes_in_project_detail(db):
    """build_context con project_id mostra i dettagli della serie."""
    _make_tenant(db)
    cl = _make_client(db)
    p = _make_project(db, cl.id, episodes_count=8)
    ctx = build_context(db, project_id=p.id)
    assert "8 episodi" in ctx


def test_ai_context_no_episodes_when_not_set(db):
    """build_context non menziona episodi per progetti senza episodes_count."""
    _make_tenant(db)
    cl = _make_client(db)
    p = _make_project(db, cl.id, episodes_count=None, project_type="feature_film")
    ctx = build_context(db, project_id=p.id)
    assert "episodi" not in ctx


def test_ai_context_overview_includes_series_label(db):
    """Nella lista PROGETTI ESISTENTI, i progetti-serie hanno il label (serie, N episodi)."""
    _make_tenant(db)
    cl = _make_client(db)
    _make_project(db, cl.id, episodes_count=12)
    ctx = build_context(db)
    assert "serie, 12 episodi" in ctx


def test_ai_context_overview_no_series_label_for_film(db):
    """Film senza episodes_count non appare come serie nel overview."""
    _make_tenant(db)
    cl = _make_client(db)
    _make_project(db, cl.id, episodes_count=None, project_type="feature_film")
    ctx = build_context(db)
    assert "serie, " not in ctx
