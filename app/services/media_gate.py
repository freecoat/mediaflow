"""Gate RBAC Media Library. manage_assets è il permesso dedicato; per
retrocompatibilità (il DAM usava edit_planning_all) il gate accetta anche
edit_planning_all finché la migrazione ruoli non è diffusa."""
from typing import Optional
from fastapi import HTTPException, Request
from app.models.models import User
from app.services.rbac import has_permission, current_user_optional


def user_can_media(user: Optional[User]) -> bool:
    return bool(user) and (has_permission(user, "manage_assets")
                           or has_permission(user, "edit_planning_all"))


def requires_manage_assets():
    def _dep(request: Request) -> User:
        user = current_user_optional(request)
        if not user_can_media(user):
            raise HTTPException(403, "Permesso Media Library mancante")
        return user
    return _dep
