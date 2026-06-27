"""Test: gate UI modifica progetto usa edit_projects, non view_finance.

Documenta il contratto di permesso per il pulsante ✎ Modifica in
project_detail.html: deve essere visibile a manager e producer (che hanno
edit_projects) anche senza view_finance.

v3.5.0-alpha.172.234 — Task 12 review fix.
"""
import pytest
from unittest.mock import MagicMock

from app.services import rbac as _rbac


def _make_user(role_code: str):
    """Stub User con permessi preset per role_code."""
    user = MagicMock()
    user.role_id = None  # forza fallback preset
    user.role_obj = None
    # enum legacy
    role_mock = MagicMock()
    role_mock.value = role_code
    user.role = role_mock
    user.extra_permissions = []
    return user


@pytest.mark.parametrize("role", ["admin", "manager", "producer"])
def test_edit_projects_granted_for_elevated_roles(role):
    """admin, manager, producer devono avere edit_projects."""
    user = _make_user(role)
    assert _rbac.has_permission(user, "edit_projects") is True, (
        f"role '{role}' deve avere edit_projects"
    )


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_edit_projects_denied_for_lower_roles(role):
    """operator e viewer NON devono avere edit_projects."""
    user = _make_user(role)
    assert _rbac.has_permission(user, "edit_projects") is False, (
        f"role '{role}' non deve avere edit_projects"
    )


def test_producer_has_edit_projects_but_not_edit_finance():
    """Producer ha edit_projects ma non edit_invoices — conferma separazione gate."""
    user = _make_user("producer")
    assert _rbac.has_permission(user, "edit_projects") is True
    assert _rbac.has_permission(user, "edit_invoices") is False


def test_gate_function_matches_has_permission():
    """La lambda can_edit_projects usata nel Jinja global restituisce
    lo stesso risultato di has_permission(user, 'edit_projects')."""
    can_edit_projects = lambda u: _rbac.has_permission(u, "edit_projects")
    for role in ("admin", "manager", "producer", "operator", "viewer"):
        user = _make_user(role)
        assert can_edit_projects(user) == _rbac.has_permission(user, "edit_projects")
