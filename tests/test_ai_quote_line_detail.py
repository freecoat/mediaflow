"""Test fix: detail riga quote popolato/ereditato anche via AI copilot.

Verifica che i handler propose_quote_line e propose_quote (con lines)
- persistano detail quando esplicitamente fornito nel payload;
- ereditino PriceItem.description quando il payload omette detail ma esiste
  un price_item_id collegato (stesso comportamento del picker manuale α.172.146).
"""
import pytest
from datetime import date

from app.models import models as m
from app.services.ai_assistant import _h_propose_quote_line, _h_propose_quote


# ── fixtures minime ──────────────────────────────────────────────────────────

def _seed(db):
    """Crea Tenant/Client/Project/Quote/PriceItem di base; ritorna un dict con le istanze."""
    t = m.Tenant(id=1, name="Test", slug="test", default_currency="EUR")
    db.add(t)
    c = m.Client(tenant_id=1, name="Client Test")
    db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="PRJ-1", title="Progetto Test", client_id=c.id)
    db.add(p); db.flush()
    q = m.Quote(
        tenant_id=1, number="Q-2026-001", title="Quote Test",
        project_id=p.id, client_id=c.id,
        issue_date=date.today(), valid_until=date.today(),
    )
    db.add(q); db.flush()

    cat = m.PriceCategory(name="Mastering", tenant_id=1)
    db.add(cat); db.flush()
    pi = m.PriceItem(
        tenant_id=1, category_id=cat.id,
        name="DCP Mastering",
        description="Creazione DCP 2K/4K con chiavi KDM",
        unit="flat", price_list=1200.0, is_active=True,
    )
    db.add(pi); db.flush()
    return {"tenant": t, "client": c, "project": p, "quote": q, "price_item": pi}


# ── propose_quote_line ───────────────────────────────────────────────────────

class TestProposeQuoteLineDetail:
    def test_explicit_detail_persisted(self, db):
        """Quando il payload fornisce detail, la riga deve averlo."""
        seed = _seed(db)
        q = seed["quote"]
        result = _h_propose_quote_line(db, {
            "quote_id": q.id,
            "description": "Voce libera",
            "unit_price": 500.0,
            "quantity": 1,
            "detail": "Specifica esplicita dall'AI",
        })
        line = db.query(m.QuoteLine).filter(m.QuoteLine.id == result["quote_line_id"]).first()
        assert line is not None
        assert line.detail == "Specifica esplicita dall'AI"

    def test_detail_inherited_from_price_item_description(self, db):
        """Quando detail è omesso nel payload ma esiste price_item, eredita description."""
        seed = _seed(db)
        q = seed["quote"]
        pi = seed["price_item"]
        result = _h_propose_quote_line(db, {
            "quote_id": q.id,
            "price_item_id": pi.id,
            "quantity": 1,
            # nessun 'detail' esplicito
        })
        line = db.query(m.QuoteLine).filter(m.QuoteLine.id == result["quote_line_id"]).first()
        assert line is not None
        assert line.detail == "Creazione DCP 2K/4K con chiavi KDM"

    def test_explicit_detail_wins_over_price_item_description(self, db):
        """detail esplicito nel payload prevale su PriceItem.description."""
        seed = _seed(db)
        q = seed["quote"]
        pi = seed["price_item"]
        result = _h_propose_quote_line(db, {
            "quote_id": q.id,
            "price_item_id": pi.id,
            "quantity": 1,
            "detail": "Override esplicito",
        })
        line = db.query(m.QuoteLine).filter(m.QuoteLine.id == result["quote_line_id"]).first()
        assert line is not None
        assert line.detail == "Override esplicito"

    def test_no_detail_no_price_item_description_gives_none(self, db):
        """Nessun detail e nessun price_item → detail rimane None (non crash)."""
        seed = _seed(db)
        q = seed["quote"]
        pi = seed["price_item"]
        # Rimuovi description dalla price_item per simulare voce senza descrizione
        pi.description = None
        db.flush()
        result = _h_propose_quote_line(db, {
            "quote_id": q.id,
            "price_item_id": pi.id,
            "quantity": 1,
        })
        line = db.query(m.QuoteLine).filter(m.QuoteLine.id == result["quote_line_id"]).first()
        assert line is not None
        assert line.detail is None

    def test_blank_detail_falls_back_to_price_item_description(self, db):
        """detail="" (stringa vuota) deve essere trattato come assente → eredita."""
        seed = _seed(db)
        q = seed["quote"]
        pi = seed["price_item"]
        result = _h_propose_quote_line(db, {
            "quote_id": q.id,
            "price_item_id": pi.id,
            "quantity": 1,
            "detail": "",  # stringa vuota = assente
        })
        line = db.query(m.QuoteLine).filter(m.QuoteLine.id == result["quote_line_id"]).first()
        assert line is not None
        assert line.detail == "Creazione DCP 2K/4K con chiavi KDM"


# ── propose_quote (con lines) ────────────────────────────────────────────────

class TestProposeQuoteWithLinesDetail:
    def test_lines_explicit_detail_persisted(self, db):
        """propose_quote con lines: detail esplicito nella riga viene salvato."""
        seed = _seed(db)
        p = seed["project"]
        result = _h_propose_quote(db, {
            "project_id": p.id,
            "title": "Quote inline",
            "lines": [
                {
                    "description": "Voce con detail",
                    "unit_price": 300.0,
                    "quantity": 2,
                    "detail": "Note esplicite inline",
                }
            ],
        })
        lines = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == result["quote_id"]).all()
        assert len(lines) == 1
        assert lines[0].detail == "Note esplicite inline"

    def test_lines_detail_inherited_from_price_item(self, db):
        """propose_quote con lines: detail ereditato da PriceItem.description quando omesso."""
        seed = _seed(db)
        p = seed["project"]
        pi = seed["price_item"]
        result = _h_propose_quote(db, {
            "project_id": p.id,
            "title": "Quote con listino",
            "lines": [
                {
                    "price_item_id": pi.id,
                    "quantity": 1,
                    # nessun 'detail'
                }
            ],
        })
        lines = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == result["quote_id"]).all()
        assert len(lines) == 1
        assert lines[0].detail == "Creazione DCP 2K/4K con chiavi KDM"

    def test_lines_explicit_detail_wins_over_price_item(self, db):
        """propose_quote con lines: detail esplicito prevale su PriceItem.description."""
        seed = _seed(db)
        p = seed["project"]
        pi = seed["price_item"]
        result = _h_propose_quote(db, {
            "project_id": p.id,
            "title": "Quote override",
            "lines": [
                {
                    "price_item_id": pi.id,
                    "quantity": 1,
                    "detail": "Override riga inline",
                }
            ],
        })
        lines = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == result["quote_id"]).all()
        assert len(lines) == 1
        assert lines[0].detail == "Override riga inline"
