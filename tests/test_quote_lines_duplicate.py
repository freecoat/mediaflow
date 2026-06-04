"""v3.5.0-alpha.172.186 — duplica righe quote IN-PLACE con suffisso "(copia)"."""
import asyncio
import pytest
from fastapi import HTTPException
from app.models import models as m
from app.routers import quotes as q
from tests.test_quote_lines_transfer import _seed_quote, _call


def test_duplicate_single_after(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-200", n_lines=3)
    orig = lines[1]
    res = _call(q.lines_duplicate(quote_id=src.id, line_ids=str(orig.id), after=True, db=db))
    assert res["duplicated"] == 1
    rows = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == src.id).all()
    assert len(rows) == 4
    dup = [r for r in rows if r.description.endswith("(copia)")][0]
    assert dup.description == orig.description + " (copia)"
    # ordinata subito dopo l'originale
    assert orig.sort_order < dup.sort_order < orig.sort_order + 10


def test_duplicate_bulk_append(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-210", n_lines=3)
    ids = ",".join(str(l.id) for l in lines)
    res = _call(q.lines_duplicate(quote_id=src.id, line_ids=ids, after=False, db=db))
    assert res["duplicated"] == 3
    rows = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == src.id).all()
    assert len(rows) == 6
    dups = [r for r in rows if r.description.endswith("(copia)")]
    assert len(dups) == 3
    # niente collisione su sort_order/position tra le copie
    assert len({d.sort_order for d in dups}) == 3
    assert len({d.position for d in dups}) == 3


def test_duplicate_preserves_section_and_link(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-220", n_lines=1)
    lines[0].section_label = "Sky"; lines[0].delivery_item_id = 99; db.flush()
    _call(q.lines_duplicate(quote_id=src.id, line_ids=str(lines[0].id), after=True, db=db))
    dup = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == src.id,
                                       m.QuoteLine.description.like("%(copia)")).first()
    assert dup.section_label == "Sky"
    assert dup.delivery_item_id == 99


def test_duplicate_no_valid_lines_400(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-230", n_lines=1)
    other, olines = _seed_quote(db, number="Q-2026-231", n_lines=1)
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_duplicate(quote_id=src.id, line_ids=str(olines[0].id), after=False, db=db))
    assert ei.value.status_code == 400
