"""Unit tests for ``api.auth.schemas`` — KnownRole narrowing contract.

Pins the type-narrowing change introduced when the Phase 0 deferral
on ``SessionData.roles`` / ``CurrentUser.roles`` was closed. The fields
are now ``list[KnownRole]`` (a ``Literal["analyst","admin","policy"]``)
instead of plain ``list[str]``, so pydantic rejects any unknown role
at construction.

These tests pin three contracts:

1. Every ``KnownRole`` value is accepted by both schemas.
2. Unknown roles raise ``ValidationError`` at construction.
3. ``KNOWN_ROLES`` (runtime filter in ``api.auth.jwt_verifier``) and
   ``typing.get_args(KnownRole)`` are in lockstep — adding a role to
   the literal automatically extends the runtime filter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from api.auth.jwt_verifier import KNOWN_ROLES
from api.auth.schemas import CurrentUser, KnownRole, SessionData


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Contract 1: every KnownRole is accepted by both schemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", get_args(KnownRole))
def test_session_data_accepts_every_known_role(role: str) -> None:
    """``SessionData.roles`` accepts each value in the ``KnownRole`` literal."""
    data = SessionData(
        sub="u",
        email="u@test.com",
        roles=[role],
        created_at=_now(),
        last_activity=_now(),
    )

    assert data.roles == [role]


@pytest.mark.parametrize("role", get_args(KnownRole))
def test_current_user_accepts_every_known_role(role: str) -> None:
    """``CurrentUser.roles`` accepts each value in the ``KnownRole`` literal."""
    user = CurrentUser(sub="u", email="u@test.com", roles=[role])

    assert user.roles == [role]


def test_session_data_accepts_multiple_known_roles() -> None:
    """A user holding multiple known roles round-trips intact."""
    data = SessionData(
        sub="u",
        email="u@test.com",
        roles=["analyst", "admin"],
        created_at=_now(),
        last_activity=_now(),
    )

    assert set(data.roles) == {"analyst", "admin"}


# ---------------------------------------------------------------------------
# Contract 2: unknown roles fail validation at construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unknown_role", ["viewer", "default-roles-dprk-cti", "", "ANALYST", "tester"]
)
def test_session_data_rejects_unknown_role(unknown_role: str) -> None:
    """``SessionData(roles=[<unknown>])`` must raise ``ValidationError``.

    Includes:
      - common Keycloak default roles (``default-roles-dprk-cti``)
      - empty string (a misconfigured token)
      - case-sensitive uppercase variant (``ANALYST``) — Literal is
        case-sensitive, so the upper-case form is correctly unknown
      - other plausible-looking-but-not-defined roles
    """
    with pytest.raises(ValidationError):
        SessionData(
            sub="u",
            email="u@test.com",
            roles=[unknown_role],
            created_at=_now(),
            last_activity=_now(),
        )


@pytest.mark.parametrize(
    "unknown_role", ["viewer", "default-roles-dprk-cti", "", "ANALYST", "tester"]
)
def test_current_user_rejects_unknown_role(unknown_role: str) -> None:
    """``CurrentUser(roles=[<unknown>])`` must raise ``ValidationError``."""
    with pytest.raises(ValidationError):
        CurrentUser(sub="u", email="u@test.com", roles=[unknown_role])


def test_session_data_rejects_mixed_known_and_unknown() -> None:
    """A list containing one unknown role poisons the whole construction."""
    with pytest.raises(ValidationError):
        SessionData(
            sub="u",
            email="u@test.com",
            roles=["analyst", "viewer"],
            created_at=_now(),
            last_activity=_now(),
        )


# ---------------------------------------------------------------------------
# Contract 3: KNOWN_ROLES (runtime filter) is derived from KnownRole
# ---------------------------------------------------------------------------


def test_known_roles_matches_literal_args() -> None:
    """``KNOWN_ROLES`` and ``typing.get_args(KnownRole)`` must be in lockstep.

    Adding a role to the ``KnownRole`` literal in ``schemas.py`` should
    automatically extend the runtime filter — there must NOT be a second
    hand-maintained constant. This test catches the drift at CI time.
    """
    assert KNOWN_ROLES == frozenset(get_args(KnownRole))


def test_known_roles_matches_router_rbac_constants() -> None:
    """Pin the canonical set against the router-level RBAC allowlists.

    If the realm gains a new role (e.g. ``reviewer``), this test fails
    — forcing the contributor to update the literal here AND the
    router constants in lockstep.

    Pre-PR ``KNOWN_ROLES`` was ``{"analyst","admin","policy"}`` while
    routers used 5 roles (including ``researcher`` and ``soc``). That
    inconsistency was the bug the Phase 0 deferral closure resolved.
    """
    assert KNOWN_ROLES == frozenset(
        {"analyst", "admin", "policy", "researcher", "soc"}
    )
