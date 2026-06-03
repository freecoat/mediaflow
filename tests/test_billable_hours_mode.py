"""Policy ore fatturabili per-booking (v3.5.0-alpha.172.179).

`compute_billable_hours` è la single source of truth: la usa sia il cost report
(via _booking_billable_hours) sia l'endpoint preview. Le opzioni impattano SOLO
le ore-cliente; il costo interno (non testato qui) somma sempre tutti.
"""
from app.services import cost_line_sync as cls

HUM = "person_internal"
FRE = "person_freelance"
ROOM = "studio"


def test_single_human_default_max():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0


def test_two_humans_max():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0


def test_two_humans_sum():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "sum") == 14.0


def test_two_humans_specific():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "specific", specific_rid=2) == 6.0


def test_specific_resource_absent_returns_zero():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "specific", specific_rid=99) == 0.0


def test_manual_overrides_everything():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "manual", manual=5.0) == 5.0


def test_manual_none_is_zero():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "manual", manual=None) == 0.0


def test_human_plus_room_ignores_room():
    items = [(1, HUM, 8.0), (10, ROOM, 8.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0  # 1 sola umana


def test_smart_split_same_human_aggregated_before_max():
    items = [(1, HUM, 4.0), (1, HUM, 4.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0


def test_only_rooms_max_mode_ignored():
    items = [(10, ROOM, 8.0), (11, ROOM, 4.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0


def test_empty_items_zero():
    assert cls.compute_billable_hours([], "max") == 0.0


def test_mixed_freelance_and_internal_sum():
    items = [(1, HUM, 8.0), (2, FRE, 6.0)]
    assert cls.compute_billable_hours(items, "sum") == 14.0
