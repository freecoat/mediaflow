from app.services.rbac import ALL_PERMISSION_KEYS, PRESET_PERMISSIONS


def test_calendar_permissions_exist():
    assert "view_calendar" in ALL_PERMISSION_KEYS
    assert "manage_calendar" in ALL_PERMISSION_KEYS


def test_calendar_permissions_in_presets():
    for role in ("manager", "producer", "accounting"):
        assert "view_calendar" in PRESET_PERMISSIONS[role], role
    for role in ("manager", "producer"):
        assert "manage_calendar" in PRESET_PERMISSIONS[role], role


def test_admin_has_calendar_via_all():
    assert "view_calendar" in PRESET_PERMISSIONS["admin"]
    assert "manage_calendar" in PRESET_PERMISSIONS["admin"]
