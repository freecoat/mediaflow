"""Test fix copilot + picker capitolato (note Matteo 30 mag) — v3.5.0-alpha.172.146.

- _coerce_price: price_list robusto (numero/stringa/€/virgola) + reject garbage.
- template_bucket_options: detail_suggestion arricchito (specs + nome capitolato
  + note), non più vuoto quando le note mancano.
"""
import pytest
from app.services.ai_assistant import _coerce_price
from app.services.delivery_bucket import template_bucket_options
from app.models import models as m


# ── _coerce_price ────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    (150, 150.0), (150.0, 150.0), ("150", 150.0), ("150,00", 150.0),
    ("€ 150", 150.0), ("  150 ", 150.0), (None, 0.0), ("", 0.0),
])
def test_coerce_price_ok(raw, expected):
    assert _coerce_price(raw) == expected


@pytest.mark.parametrize("raw", ["listino standard", "abc", "id-5"])
def test_coerce_price_rejects_non_numeric(raw):
    with pytest.raises(ValueError) as ei:
        _coerce_price(raw)
    assert "NUMERO" in str(ei.value)


def test_coerce_price_required_missing():
    with pytest.raises(ValueError):
        _coerce_price(None, required=True)


# ── template_bucket_options detail enrichment ────────────────────────
def _seed_bucket(db, *, pi_name, item_name, notes=None):
    cat = m.PriceCategory(name="Deliveries", tenant_id=1)
    db.add(cat); db.flush()
    pi = m.PriceItem(category_id=cat.id, name=pi_name, unit="pc",
                     price_list=100.0, tenant_id=1, is_active=True)
    db.add(pi); db.flush()
    tpl = m.DeliveryTemplate(tenant_id=1, code="SKY-TEST", name="Sky Test",
                             broadcaster="Sky")
    db.add(tpl); db.flush()
    it = m.DeliveryItem(
        tenant_id=1, delivery_template_id=tpl.id, name=item_name,
        is_active=True, suggested_price_item_id=pi.id, notes=notes,
    )
    db.add(it); db.flush()
    return tpl, pi, it


def test_picker_detail_includes_item_name_and_notes(db):
    # item senza package/container/audio → bucket group "other" (label=item.name)
    tpl, pi, it = _seed_bucket(
        db, pi_name="Bucket Generico", item_name="Feature M&E 5.1",
        notes="LUFS -23, layout loghi A",
    )
    opts = template_bucket_options(db, 1, tpl.id)
    assert len(opts) == 1
    detail = opts[0]["detail_suggestion"]
    assert detail, "detail_suggestion non deve essere vuoto"
    assert "Feature M&E 5.1" in detail   # nome capitolato originale
    assert "LUFS -23" in detail          # note capitolato (specs critiche)


def test_picker_detail_non_empty_even_without_notes(db):
    # caso che prima dava detail vuoto: nessuna nota → ora usa nome item/specs
    tpl, pi, it = _seed_bucket(
        db, pi_name="Bucket X", item_name="ProRes 4444 UHD", notes=None,
    )
    opts = template_bucket_options(db, 1, tpl.id)
    detail = opts[0]["detail_suggestion"]
    assert detail and "ProRes 4444 UHD" in detail
