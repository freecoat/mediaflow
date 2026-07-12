from app.services.rbac import PERMISSIONS, has_permission
from app.models.models import User, UserRole, Role


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


def test_gate_via_planning_fallback_only():
    # Ruolo custom con SOLO edit_planning_all (niente manage_assets): deve
    # comunque superare il gate grazie alla clausola `or` di retrocompat.
    # Se quella clausola venisse rimossa, questo test fallisce (a differenza
    # di test_manage_assets_gate_accepts_planning_fallback sopra, dove
    # manager ha già manage_assets nel preset e quindi non esercita davvero
    # il fallback).
    from app.services.media_gate import user_can_media
    role = Role(id=901, tenant_id=1, code="planner_only", name="Planner Only",
                permissions=["edit_planning_all"], is_system=False, is_active=True)
    u = User(id=2, tenant_id=1, email="b@t.local", full_name="B",
             hashed_password="x", role=UserRole.viewer, role_id=901, role_obj=role,
             is_active=True)
    assert "manage_assets" not in (u.role_obj.permissions or [])
    assert has_permission(u, "edit_planning_all") is True
    assert has_permission(u, "manage_assets") is False
    assert user_can_media(u) is True


def test_gate_denies_without_permissions():
    # Ruolo custom senza manage_assets né edit_planning_all: gate deve negare.
    from app.services.media_gate import user_can_media
    role = Role(id=902, tenant_id=1, code="empty_role", name="Empty Role",
                permissions=[], is_system=False, is_active=True)
    u = User(id=3, tenant_id=1, email="c@t.local", full_name="C",
             hashed_password="x", role=UserRole.viewer, role_id=902, role_obj=role,
             is_active=True)
    assert user_can_media(u) is False
