"""v3.5.0-alpha.172.175 — _copy_quote_lines deve preservare l'etichetta capitolato.

Bug: creando una nuova versione da quote approvata, le label del picker capitolato
(`section_label`) sparivano + si perdeva il link item (`delivery_item_id`) e il flag
`is_optional`. Il copy ora li propaga.
"""
from app.models.models import QuoteLine
from app.routers.quotes import _copy_quote_lines


def _line(**kw):
    ln = QuoteLine()
    ln.sort_order = kw.get("sort_order", 0)
    ln.section = "A"; ln.position = "A.1"; ln.description = kw.get("description", "x")
    ln.detail = kw.get("detail")
    ln.quantity = 1.0; ln.unit = "pc"; ln.unit_price = 100.0
    ln.allowance = 0.0; ln.line_discount_pct = 0.0; ln.total = 100.0; ln.hardcosts = 0.0
    ln.price_item_id = kw.get("price_item_id")
    ln.category_override = None; ln.source_hint = None; ln.price_level = None
    ln.section_label = kw.get("section_label")
    ln.delivery_item_id = kw.get("delivery_item_id")
    ln.is_optional = kw.get("is_optional", False)
    ln.id = kw.get("id")
    return ln


def test_copy_preserves_capitolato_label_and_link():
    src = [
        _line(id=10, sort_order=0, section_label="Sky Italia", delivery_item_id=107, is_optional=False),
        _line(id=11, sort_order=1, section_label="NBCUniversal", delivery_item_id=None, is_optional=True),
    ]
    out = _copy_quote_lines(src, dest_quote_id=99, track_parent=True)
    assert len(out) == 2
    assert out[0].section_label == "Sky Italia"
    assert out[0].delivery_item_id == 107
    assert out[0].is_optional is False
    assert out[0].parent_line_id == 10          # track_parent
    assert out[1].section_label == "NBCUniversal"
    assert out[1].is_optional is True
    assert out[1].parent_line_id == 11
    # quote_id riassegnato
    assert all(l.quote_id == 99 for l in out)


def test_copy_no_parent_tracking():
    src = [_line(id=5, section_label="RAI")]
    out = _copy_quote_lines(src, dest_quote_id=42, track_parent=False)
    assert out[0].parent_line_id is None
    assert out[0].section_label == "RAI"
