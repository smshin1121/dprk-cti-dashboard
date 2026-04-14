"""Unit tests for the require_role() dependency factory in api.deps.

The inner _dependency async function is called directly — no HTTP request
cycle is needed.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.auth.schemas import CurrentUser
from api.deps import require_role


# ---------------------------------------------------------------------------
# Factory-level validation
# ---------------------------------------------------------------------------

def test_require_role_factory_validates_args():
    """require_role() with zero arguments must raise ValueError immediately."""
    with pytest.raises(ValueError, match="at least one role"):
        require_role()


# ---------------------------------------------------------------------------
# Dependency execution — call the returned coroutine directly
# ---------------------------------------------------------------------------

async def test_dependency_allows_matching_role():
    """User with the required role passes through without exception."""
    dep = require_role("admin")
    user = CurrentUser(sub="u1", email="admin@test.com", roles=["admin"])
    result = await dep(user=user)
    assert result.sub == "u1"


async def test_dependency_rejects_missing_role():
    """User without any of the required roles receives HTTP 403."""
    dep = require_role("admin")
    user = CurrentUser(sub="u2", email="analyst@test.com", roles=["analyst"])
    with pytest.raises(HTTPException) as exc_info:
        await dep(user=user)
    assert exc_info.value.status_code == 403


async def test_dependency_allows_when_user_has_any_listed_role():
    """require_role('admin', 'analyst') accepts a user with only 'analyst'."""
    dep = require_role("admin", "analyst")
    user = CurrentUser(sub="u3", email="analyst@test.com", roles=["analyst"])
    result = await dep(user=user)
    assert result.sub == "u3"


async def test_dependency_rejects_when_user_has_zero_listed_roles():
    """User with roles=['policy'] is rejected by require_role('admin', 'analyst')."""
    dep = require_role("admin", "analyst")
    user = CurrentUser(sub="u4", email="policy@test.com", roles=["policy"])
    with pytest.raises(HTTPException) as exc_info:
        await dep(user=user)
    assert exc_info.value.status_code == 403


async def test_dependency_allows_exact_match_from_multiple():
    """User with exactly one matching role from a list of three passes."""
    dep = require_role("admin", "analyst", "policy")
    user = CurrentUser(sub="u5", email="policy@test.com", roles=["policy"])
    result = await dep(user=user)
    assert result.sub == "u5"


async def test_dependency_rejects_empty_roles_list():
    """User with an empty roles list is always rejected."""
    dep = require_role("admin")
    user = CurrentUser(sub="u6", email="nobody@test.com", roles=[])
    with pytest.raises(HTTPException) as exc_info:
        await dep(user=user)
    assert exc_info.value.status_code == 403
