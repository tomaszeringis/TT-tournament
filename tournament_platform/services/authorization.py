"""
Authorization Service

Provides role-based access control helpers for the Streamlit frontend
and FastAPI backend. Works with existing auth roles without changing
the auth flow.
"""

from typing import Optional, Set

from tournament_platform.config import settings

# Supported roles
ROLES = {"admin", "operator", "user"}

# Permission definitions
PERMISSIONS = {
    "tournament.create": {"admin", "operator"},
    "tournament.read": {"admin", "operator", "user"},
    "tournament.update": {"admin", "operator"},
    "tournament.delete": {"admin"},
    "match.call": {"admin", "operator"},
    "match.start": {"admin", "operator"},
    "match.complete": {"admin", "operator"},
    "match.report": {"admin", "operator"},
    "match.reset": {"admin"},
    "player.merge": {"admin"},
    "player.import": {"admin", "operator"},
    "settings.change": {"admin"},
    "audit.read": {"admin", "operator"},
}


def require_role(role: str, allowed_roles: Set[str]) -> bool:
    """
    Check if a role is in the allowed set.

    Args:
        role: The user's role
        allowed_roles: Set of allowed roles

    Returns:
        True if role is allowed
    """
    return role in allowed_roles


def check_permission(role: str, permission: str) -> bool:
    """
    Check if a role has a specific permission.

    Args:
        role: The user's role
        permission: Permission key (e.g., "match.report")

    Returns:
        True if role has permission
    """
    allowed = PERMISSIONS.get(permission, set())
    return role in allowed


def get_user_permissions(role: str) -> Set[str]:
    """
    Get all permissions for a role.

    Args:
        role: The user's role

    Returns:
        Set of permission keys
    """
    return {perm for perm, roles in PERMISSIONS.items() if role in roles}
