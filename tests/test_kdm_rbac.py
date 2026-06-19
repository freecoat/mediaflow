from app.services.rbac import ALL_PERMISSION_KEYS, PRESET_PERMISSIONS


def test_manage_kdm_registered():
    assert "manage_kdm" in ALL_PERMISSION_KEYS
    assert "manage_kdm" in PRESET_PERMISSIONS["manager"]
