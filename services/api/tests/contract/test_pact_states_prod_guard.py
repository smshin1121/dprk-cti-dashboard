"""Pact provider-state router — production safety guard.

The ``_pact/provider_states`` endpoint mints Redis sessions and
mutates DB rows on an unauthenticated request. Exposing it in any env
other than the verifier-suite envs would be a wide-open session
minter + DB-row mutator. PR #12 Group I originally registered the
router under an ``APP_ENV != 'prod'`` guard in
``services/api/src/api/main.py``; the follow-up to PR #23 tightened
this to a fail-closed allowlist (``dev`` / ``test`` / ``ci`` only).

These tests fail loudly if a future edit drops the guard, registers
the router unconditionally, OR widens the allowlist back to the
deny-list shape. Coverage:

  - The 3 allowlisted envs all mount the router (verifier CI + local
    dev reproduction unaffected).
  - Every other value — ``prod``, ``staging``, ``uat``, ``demo``,
    ``review``, the empty string, and a typo — does NOT mount the
    router.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator
from typing import Any

import pytest


def _base_env() -> dict[str, str]:
    """Non-secret values the settings loader requires to boot."""
    return {
        "DATABASE_URL": "postgresql+psycopg://test@localhost/test",
        "REDIS_URL": "redis://localhost:6379/0",
        "OIDC_CLIENT_ID": "dprk-cti",
        "OIDC_CLIENT_SECRET": "ci-openapi-check",
        "OIDC_ISSUER_URL": "http://keycloak.test/realms/dprk",
        "OIDC_REDIRECT_BASE_URL": "http://localhost:8000",
        "SESSION_SIGNING_KEY": "ci-openapi-check-signing-key-32chars",
        "SESSION_COOKIE_NAME": "dprk_cti_session",
        "SESSION_COOKIE_SECURE": "true",
        "SESSION_COOKIE_SAMESITE": "lax",
        "CORS_ORIGINS": "http://localhost:3000",
        # Rate limiter fail-closes in prod if this is not a redis://
        # URL. Both dev and prod branches of this test need it set.
        "RATE_LIMIT_STORAGE_URL": "redis://localhost:6379/1",
    }


def _reimport_app(app_env: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("APP_ENV", app_env)
    # Fresh import so the settings cache + router registration pick
    # up the APP_ENV we just set. get_settings() uses lru_cache, so
    # purging the modules is the cleanest reset.
    for mod in list(sys.modules):
        if mod.startswith("api."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.delitem(sys.modules, "api", raising=False)
    return importlib.import_module("api.main")


def _has_pact_state_route(app: Any) -> bool:
    return any(
        hasattr(r, "path") and r.path == "/_pact/provider_states"
        for r in app.routes
    )


@pytest.mark.parametrize("app_env", ["dev", "test", "ci"])
def test_pact_state_router_is_registered_for_allowlisted_envs(
    app_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-closed allowlist must keep the contract-verify CI job
    + local dev reproductions working. ``dev`` / ``test`` / ``ci`` are
    the three envs the verifier suite is allowed to run under."""
    main = _reimport_app(app_env, monkeypatch)
    assert _has_pact_state_route(main.app), (
        f"pact_states router should be mounted in env={app_env!r} — "
        "verifier CI job relies on POST /_pact/provider_states. Check "
        "PACT_ROUTER_ENV_ALLOWLIST in services/api/src/api/main.py."
    )


@pytest.mark.parametrize(
    "app_env", ["prod", "staging", "uat", "demo", "review", "", "perd"]
)
def test_pact_state_router_is_absent_outside_allowlist(
    app_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production AND every other non-allowlisted env must not expose
    the state-setup endpoint — it mints sessions without authentication
    and mutates DB rows directly. The previous gate was
    ``app_env != "prod"`` which silently leaked the router into any
    typo or unknown value. Now the gate is an explicit allowlist:
    ``staging``, ``uat``, ``demo``, ``review``, the empty string, and
    typos like ``perd`` must all be denied."""
    main = _reimport_app(app_env, monkeypatch)
    assert not _has_pact_state_route(main.app), (
        f"pact_states router must NOT be mounted in env={app_env!r} — "
        "exposes an unauthenticated session minter + direct DB-row "
        "mutator. Check PACT_ROUTER_ENV_ALLOWLIST in "
        "services/api/src/api/main.py — only ``dev`` / ``test`` / "
        "``ci`` are accepted."
    )
