"""Pact provider-state router — production safety guard.

The ``_pact/provider_states`` endpoint mints Redis sessions and
(optionally) mutates DB rows on an unauthenticated request. Exposing
it in production would be a wide-open session minter. PR #12 Group I
registers the router under an ``APP_ENV != 'prod'`` guard in
``services/api/src/api/main.py``.

This test fails loudly if a future edit drops the guard or registers
the router unconditionally. It reimports the app module with
``APP_ENV=prod`` and asserts the route is absent.
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
        "JWT_SECRET": "ci-openapi-check-secret-at-least-32-chars",
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


def test_pact_state_router_is_registered_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = _reimport_app("dev", monkeypatch)
    assert _has_pact_state_route(main.app), (
        "pact_states router should be mounted in dev env — verifier "
        "CI job relies on POST /_pact/provider_states."
    )


def test_pact_state_router_is_absent_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production must not expose the state-setup endpoint — it
    mints sessions without authentication."""
    main = _reimport_app("prod", monkeypatch)
    assert not _has_pact_state_route(main.app), (
        "pact_states router must NOT be mounted in prod — exposes an "
        "unauthenticated session minter. Check the APP_ENV != 'prod' "
        "guard in services/api/src/api/main.py."
    )
