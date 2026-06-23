"""Test robustezza parse_delivery_items_v2: no 30k truncation + chunk PASS1 + merge."""
import pytest
from app.services import delivery_items_parser as dip
from app.services.delivery_items_parser import _merge_items_by_name


def test_merge_items_dedupe_by_name():
    a = [{"name": "ProRes 4444 Master"}, {"name": "Stereo M&E"}]
    b = [{"name": "prores 4444 master"}, {"name": "5.1 Printmaster"}]  # case-diff dup
    out = _merge_items_by_name([a, b])
    names = [i["name"] for i in out]
    assert names == ["ProRes 4444 Master", "Stereo M&E", "5.1 Printmaster"]


class _FakeProv:
    def __init__(self):
        self.pass1 = 0
        self.pass2 = 0

    def extract_json(self, system, user, max_tokens=3000):
        # distinguish pass1 vs pass2 by a marker in the system prompt
        if "MAPPARE" in system or "taxonomy" in system.lower():
            self.pass2 += 1
            return {"items": [{"name": "X"}]}
        self.pass1 += 1
        return {"items": [{"name": "Item%d" % self.pass1, "category": "MASTERING"}],
                "terms": {}}


def test_single_pass_under_limit(db):
    prov = _FakeProv()
    out = dip.parse_delivery_items_v2("capitolato breve " * 20, db, tenant_id=1, provider=prov)
    assert prov.pass1 == 1
    assert out["parse_meta"]["chunked"] is False
    assert prov.pass2 == 1


def test_oversized_chunks_pass1(db):
    prov = _FakeProv()
    out = dip.parse_delivery_items_v2("A" * 200_000, db, tenant_id=1, provider=prov)
    assert prov.pass1 >= 2          # chunked PASS1
    assert out["parse_meta"]["chunked"] is True
    assert prov.pass2 == 1          # PASS2 still single
