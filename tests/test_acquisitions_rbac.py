from app.services.rbac import ALL_PERMISSION_KEYS, PRESET_PERMISSIONS


def test_acquisition_permissions_registered():
    assert "view_acquisitions" in ALL_PERMISSION_KEYS
    assert "manage_acquisitions" in ALL_PERMISSION_KEYS


def test_acquisition_permissions_on_presets():
    for role in ("manager", "producer", "accounting"):
        assert "manage_acquisitions" in PRESET_PERMISSIONS[role]
        assert "view_acquisitions" in PRESET_PERMISSIONS[role]
    # operator/viewer NON gestiscono
    assert "manage_acquisitions" not in PRESET_PERMISSIONS.get("viewer", [])
