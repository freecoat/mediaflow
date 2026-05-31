"""Unità "turno" = 3 ore (richiesta Matteo, α.172.151).

Verifica la propagazione su tutti i punti di conversione tempo↔quantità che
ora condividono la mappa canonica cost_line_sync.HOURS_PER_UNIT.
"""
import pytest

from app.services import cost_line_sync as cls
from app.services.reverse_quote import compute_quantity_from_hours


def test_hours_per_unit_turno_is_3():
    assert cls.HOURS_PER_UNIT["turno"] == 3.0
    assert cls.HOURS_PER_SHIFT == 3.0


@pytest.mark.parametrize("unit,expected", [
    ("turno", 3.0), ("turni", 3.0), ("trn", 3.0), ("shift", 3.0),
    ("TURNO", 3.0), (" turno ", 3.0),   # case/space insensitive
    ("day", 8.0), ("hr", 1.0), ("ore", 1.0),
    ("pc", None), ("TB", None), ("", None), (None, None),
])
def test_hours_per_unit(unit, expected):
    assert cls.hours_per_unit(unit) == expected


def test_turno_is_time_based():
    assert cls.is_time_based_unit("turno") is True
    assert cls.is_time_based_unit("trn") is True
    assert cls.is_time_based_unit("pc") is False


def test_unit_nature_turno():
    assert cls.unit_nature_for("turno") == "time_based"
    assert cls.unit_nature_for("trn") == "time_based"
    assert cls.unit_nature_for("shift") == "time_based"


@pytest.mark.parametrize("unit,hours,expected", [
    ("turno", 6.0, 2.0),    # 6h = 2 turni
    ("turno", 9.0, 3.0),
    ("turno", 4.5, 1.5),
    ("day", 8.0, 1.0),
    ("hr", 7.5, 7.5),
    ("pc", 6.0, 5.0),       # non-time: usa n_bookings (qui 5)
])
def test_qty_from_hours_turno(unit, hours, expected):
    assert cls._qty_from_hours(unit, hours, 5) == expected


@pytest.mark.parametrize("unit,hours,expected", [
    ("turno", 6.0, 2.0),
    ("trn", 9.0, 3.0),
    ("day", 8.0, 1.0),
    ("hr", 5.0, 5.0),
    ("pc", 6.0, 1.0),       # non-time → 1.0 (one-shot)
])
def test_reverse_quote_quantity_turno(unit, hours, expected):
    assert compute_quantity_from_hours(hours, unit) == expected
