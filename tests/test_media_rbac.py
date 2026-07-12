from app.services.rbac import PERMISSIONS, has_permission
from app.models.models import User, UserRole


def _all_perm_keys():
    keys = set()
    for cat in PERMISSIONS.values():
        keys.update(cat.keys())
    return keys


def test_manage_assets_permission_exists():
    assert "manage_assets" in _all_perm_keys()


def test_manage_assets_gate_accepts_planning_fallback():
    # un utente con edit_planning_all deve superare il gate media (retrocompat)
    from app.services.media_gate import user_can_media
    u = User(id=1, tenant_id=1, email="a@t.local", full_name="A",
             hashed_password="x", role=UserRole.manager, is_active=True)
    # manager ha edit_planning_all nei default → gate ok anche senza manage_assets
    assert user_can_media(u) is True
