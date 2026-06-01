"""v3.5.0-alpha.172.161 — Link strutturato deliverable ↔ item capitolato.

Copre:
- `template_bucket_options` ora espone `items:[{id,name}]` (punto-di-partenza
  selezionabile nel picker quote).
- backfill retroattivo `backfill_deliverable_capitolato_link`:
    * mono-item bucket           -> link automatico
    * multi-item disambiguato    -> link via match nome in detail
    * multi-item ambiguo         -> skip (resta NULL)
    * idempotente                -> non ritocca righe già linkate
- propagazione FK QuoteLine -> JobDeliverable (model-level).
"""
import pytest
from app.models.models import (
    Tenant, PriceCategory, PriceItem,
    DeliveryTemplate, DeliveryItem,
    Quote, QuoteLine, JobDeliverable,
)
from app.services.delivery_bucket import template_bucket_options
from scripts.backfill_deliverable_capitolato_link import backfill


@pytest.fixture
def base(db, tenant_id):
    db.add(Tenant(id=tenant_id, name="T", slug="t"))
    db.add(PriceCategory(id=1, tenant_id=tenant_id, name="Deliveries"))
    # due voci-listino bucket
    db.add(PriceItem(id=10, tenant_id=tenant_id, category_id=1,
                     name="MXF OP1a", unit="pc", price_list=100.0, is_active=True))
    db.add(PriceItem(id=11, tenant_id=tenant_id, category_id=1,
                     name="ProRes Master", unit="pc", price_list=200.0, is_active=True))
    # template capitolato Sky
    db.add(DeliveryTemplate(id=1, tenant_id=tenant_id, code="SKY",
                            name="Sky Spec", broadcaster="Sky Italia"))
    db.commit()
    return db


def _item(db, tenant_id, iid, name, pid):
    it = DeliveryItem(id=iid, tenant_id=tenant_id, delivery_template_id=1,
                      name=name, suggested_price_item_id=pid, is_active=True)
    db.add(it)
    db.commit()
    return it


# ───────── template_bucket_options expose items ─────────

def test_bucket_options_include_items(base, tenant_id):
    _item(base, tenant_id, 100, "UHD XAVC Intra MXF", 10)
    _item(base, tenant_id, 101, "HD XDCam MXF", 10)
    opts = template_bucket_options(base, tenant_id, 1)
    bucket = next(o for o in opts if o["price_item_id"] == 10)
    assert "items" in bucket
    ids = {i["id"] for i in bucket["items"]}
    assert ids == {100, 101}
    names = {i["name"] for i in bucket["items"]}
    assert "UHD XAVC Intra MXF" in names
    # ordine stabile per id
    assert [i["id"] for i in bucket["items"]] == [100, 101]


# ───────── backfill: mono-item ─────────

def _deliverable(db, tenant_id, did, line_id, pid, name):
    d = JobDeliverable(id=did, tenant_id=tenant_id, job_id=1, name=name,
                       quote_line_id=line_id, price_item_id=pid)
    db.add(d)
    db.commit()
    return d


def _line(db, tenant_id, line_id, pid, detail, label="Sky Italia"):
    q = db.get(Quote, 1)
    if not q:
        from app.models.models import QuoteStatus
        from datetime import date
        db.add(Quote(id=1, tenant_id=tenant_id, project_id=1, client_id=1,
                     number="Q-1", title="Q", status=QuoteStatus.draft,
                     issue_date=date(2026, 1, 1), valid_until=date(2026, 2, 1)))
        db.commit()
    ln = QuoteLine(id=line_id, quote_id=1, price_item_id=pid, description="x",
                   detail=detail, section_label=label)
    db.add(ln)
    db.commit()
    return ln


def test_backfill_mono_item_autolink(base, tenant_id):
    it = _item(base, tenant_id, 100, "UHD XAVC Intra MXF", 10)
    _line(base, tenant_id, 50, 10, "UHD XAVC Intra MXF")
    d = _deliverable(base, tenant_id, 1, 50, 10, "MXF OP1a")
    stats = backfill(db=base)
    base.refresh(d)
    assert d.delivery_item_id == it.id
    assert stats["linked"] == 1


def test_backfill_multi_item_disambiguate_by_detail(base, tenant_id):
    a = _item(base, tenant_id, 100, "UHD XAVC Intra MXF", 10)
    b = _item(base, tenant_id, 101, "HD XDCam MXF", 10)
    # detail nomina SOLO il secondo → disambigua
    _line(base, tenant_id, 50, 10, "HD XDCam MXF")
    d = _deliverable(base, tenant_id, 1, 50, 10, "MXF OP1a")
    backfill(db=base)
    base.refresh(d)
    assert d.delivery_item_id == b.id


def test_backfill_multi_item_ambiguous_skip(base, tenant_id):
    _item(base, tenant_id, 100, "UHD XAVC Intra MXF", 10)
    _item(base, tenant_id, 101, "HD XDCam MXF", 10)
    # detail non nomina nessuno (o entrambi) → ambiguo → skip
    _line(base, tenant_id, 50, 10, "qualcosa di generico")
    d = _deliverable(base, tenant_id, 1, 50, 10, "MXF OP1a")
    stats = backfill(db=base)
    base.refresh(d)
    assert d.delivery_item_id is None
    assert stats["skip_ambiguous"] == 1


def test_backfill_idempotent(base, tenant_id):
    it = _item(base, tenant_id, 100, "UHD XAVC Intra MXF", 10)
    _line(base, tenant_id, 50, 10, "UHD XAVC Intra MXF")
    d = _deliverable(base, tenant_id, 1, 50, 10, "MXF OP1a")
    backfill(db=base)
    # seconda passata: nessun nuovo link
    stats2 = backfill(db=base)
    assert stats2["linked"] == 0
    base.refresh(d)
    assert d.delivery_item_id == it.id


def test_backfill_no_label_skip(base, tenant_id):
    _item(base, tenant_id, 100, "UHD XAVC Intra MXF", 10)
    _line(base, tenant_id, 50, 10, "UHD XAVC Intra MXF", label=None)
    d = _deliverable(base, tenant_id, 1, 50, 10, "MXF OP1a")
    stats = backfill(db=base)
    base.refresh(d)
    assert d.delivery_item_id is None
    assert stats["skip_no_label"] == 1


# ───────── model-level: FK column exists & assignable ─────────

def test_quoteline_and_deliverable_have_fk(base, tenant_id):
    it = _item(base, tenant_id, 100, "X", 10)
    ln = _line(base, tenant_id, 50, 10, "X")
    ln.delivery_item_id = it.id
    base.commit()
    d = JobDeliverable(id=1, tenant_id=tenant_id, job_id=1, name="d",
                       quote_line_id=50, price_item_id=10,
                       delivery_item_id=ln.delivery_item_id)
    base.add(d)
    base.commit()
    base.refresh(d)
    assert d.delivery_item_id == it.id
