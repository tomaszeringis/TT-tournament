"""
Tests for authorization service.
"""

import pytest

from tournament_platform.services.authorization import (
    require_role,
    check_permission,
    get_user_permissions,
    ROLES,
    PERMISSIONS,
)


def test_require_role_allows_admin():
    assert require_role("admin", {"admin", "operator"}) is True


def test_require_role_denies_user():
    assert require_role("user", {"admin", "operator"}) is False


def test_check_permission_allows_match_report_for_operator():
    assert check_permission("operator", "match.report") is True


def test_check_permission_denies_match_delete_for_operator():
    assert check_permission("operator", "match.reset") is False


def test_get_user_permissions_returns_set():
    perms = get_user_permissions("admin")
    assert isinstance(perms, set)
    assert "tournament.delete" in perms


def test_get_user_permissions_user_has_read_only():
    perms = get_user_permissions("user")
    assert "tournament.read" in perms
    assert "tournament.create" not in perms
