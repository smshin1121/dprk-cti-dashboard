"""Unit tests for api.rate_limit infrastructure (PR #11 Group F).

Scope: verify the environment policy, key function dispatch, and
limiter construction. Actual per-route 429 behavior lands with
Groups G/H decoration — this suite only covers what Group F ships.

Group F reviewer priorities are mapped 1:1 to test classes below:

- TestEnvPolicy — prod fails-closed on non-Redis; test forced to
  memory; dev honors env with redis_url fallback.
- TestKeyFunction — authenticated vs anonymous dispatch.
- TestAppStartup — app starts with limiter wired; healthz / docs /
  undecorated routes remain unrestricted. fakeredis not required
  because test env uses slowapi's built-in ``memory://`` backend.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Request
from slowapi import Limiter

from api import rate_limit as rate_limit_mod
from api.config import Settings
from api.rate_limit import (
    _resolve_storage_uri,
    build_limiter,
    session_or_ip_key,
)


# ---------------------------------------------------------------------------
# Helpers — stub Settings without touching real env vars
# ---------------------------------------------------------------------------


def _stub_settings(
    *,
    app_env: str = "dev",
    rate_limit_storage_url: str = "",
    redis_url: str = "redis://localhost:6379/0",
    rate_limit_enabled: bool = True,
) -> Settings:
    """Bypass pydantic-settings env loading to test policy branches
    in isolation. ``model_construct`` skips validators that would
    otherwise pull from the real process env."""
    return Settings.model_construct(
        app_name="test",
        app_env=app_env,
        cors_origins=[],
        oidc_trusted_issuers=[],
        database_url="postgresql+psycopg://x",
        redis_url=redis_url,
        jwt_secret="x" * 32,
        oidc_client_id="x",
        oidc_client_secret="x",
        oidc_issuer_url="http://x",
        oidc_redirect_base_url="http://x",
        session_cookie_name="dprk_cti_session",
        session_cookie_secure=False,
        session_cookie_samesite="lax",
        session_signing_key="x" * 32,
        session_ttl_seconds=3600,
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_storage_url=rate_limit_storage_url,
    )


# ---------------------------------------------------------------------------
# TestEnvPolicy
# ---------------------------------------------------------------------------


class TestEnvPolicy:
    """Priority #2 — Redis unavailable path is env-specific.

    prod fails-closed at startup; test forces memory://; dev honors
    the env value with redis_url fallback. No fallthrough between
    branches — adding a new env must be an explicit decision.
    """

    # ---- prod ----------------------------------------------------
    def test_prod_accepts_redis_url(self) -> None:
        settings = _stub_settings(
            app_env="prod", rate_limit_storage_url="redis://prod-redis:6379/0"
        )
        assert _resolve_storage_uri(settings) == "redis://prod-redis:6379/0"

    def test_prod_accepts_rediss_tls_url(self) -> None:
        settings = _stub_settings(
            app_env="prod", rate_limit_storage_url="rediss://tls-redis:6380/0"
        )
        assert _resolve_storage_uri(settings) == "rediss://tls-redis:6380/0"

    def test_prod_rejects_memory_url(self) -> None:
        settings = _stub_settings(app_env="prod", rate_limit_storage_url="memory://")
        with pytest.raises(ValueError, match="cannot fail-closed without Redis"):
            _resolve_storage_uri(settings)

    def test_prod_rejects_empty_url(self) -> None:
        settings = _stub_settings(app_env="prod", rate_limit_storage_url="")
        with pytest.raises(ValueError, match="cannot fail-closed without Redis"):
            _resolve_storage_uri(settings)

    def test_prod_rejects_random_scheme(self) -> None:
        settings = _stub_settings(
            app_env="prod", rate_limit_storage_url="postgresql://x"
        )
        with pytest.raises(ValueError, match="cannot fail-closed without Redis"):
            _resolve_storage_uri(settings)

    # ---- test forced to memory:// -------------------------------
    def test_test_env_forces_memory_even_if_env_says_redis(self) -> None:
        """CI lock — RATE_LIMIT_STORAGE_URL from the env must NOT
        accidentally point tests at a real Redis instance."""
        settings = _stub_settings(
            app_env="test", rate_limit_storage_url="redis://real-redis:6379/0"
        )
        assert _resolve_storage_uri(settings) == "memory://"

    def test_test_env_with_empty_url_uses_memory(self) -> None:
        settings = _stub_settings(app_env="test", rate_limit_storage_url="")
        assert _resolve_storage_uri(settings) == "memory://"

    # ---- dev honors env with fallback ---------------------------
    def test_dev_honors_explicit_env(self) -> None:
        settings = _stub_settings(
            app_env="dev",
            rate_limit_storage_url="redis://dev:6379/0",
        )
        assert _resolve_storage_uri(settings) == "redis://dev:6379/0"

    def test_dev_allows_memory_if_developer_asks(self) -> None:
        settings = _stub_settings(
            app_env="dev", rate_limit_storage_url="memory://"
        )
        assert _resolve_storage_uri(settings) == "memory://"

    def test_dev_empty_falls_back_to_redis_url(self) -> None:
        """If RATE_LIMIT_STORAGE_URL is not set, the same Redis that
        serves sessions is reused. Dev compose stacks do not need a
        second broker just for the rate limiter."""
        settings = _stub_settings(
            app_env="dev",
            rate_limit_storage_url="",
            redis_url="redis://compose-redis:6379/0",
        )
        assert _resolve_storage_uri(settings) == "redis://compose-redis:6379/0"


# ---------------------------------------------------------------------------
# TestKeyFunction
# ---------------------------------------------------------------------------


class TestKeyFunction:
    """Priority #3 — key function maps authenticated vs anonymous
    requests to distinct buckets per plan D2."""

    def _make_request(
        self, *, cookie: str | None = None, client_host: str = "203.0.113.5"
    ) -> Request:
        """Build a minimal ASGI-style Request for key_func.

        Goes through the real ASGI ``scope["headers"]`` path so the
        native ``Request.cookies`` property parses correctly. Avoids
        monkey-patching the Request class (which leaks into
        concurrent tests)."""
        headers = [(b"host", b"test")]
        if cookie is not None:
            headers.append(
                (b"cookie", f"dprk_cti_session={cookie}".encode("utf-8"))
            )
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (client_host, 12345),
        }
        return Request(scope)

    def test_anonymous_uses_ip_key(self) -> None:
        req = self._make_request(cookie=None, client_host="198.51.100.42")
        key = session_or_ip_key(req)
        assert key.startswith("ip:")
        assert "198.51.100.42" in key

    def test_authenticated_uses_session_key(self) -> None:
        # Cookie body is the signed session string — 24-char prefix
        # goes into the bucket name.
        req = self._make_request(
            cookie="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.abc123"
        )
        key = session_or_ip_key(req)
        assert key.startswith("session:")
        # Exactly 24 chars of the cookie (prefix lock).
        expected_prefix = "eyJ0eXAiOiJKV1QiLCJhbGci"
        assert key == f"session:{expected_prefix}"

    def test_different_cookies_yield_different_keys(self) -> None:
        """Two authenticated users must land in different buckets."""
        req_a = self._make_request(cookie="user-a-cookie-" + "x" * 30)
        req_b = self._make_request(cookie="user-b-cookie-" + "y" * 30)
        assert session_or_ip_key(req_a) != session_or_ip_key(req_b)

    def test_same_cookie_is_stable_across_calls(self) -> None:
        """Same user calling twice must hit the same bucket — no
        clock-dependence, no randomness."""
        cookie = "stable-cookie-" + "z" * 40
        req1 = self._make_request(cookie=cookie)
        req2 = self._make_request(cookie=cookie)
        assert session_or_ip_key(req1) == session_or_ip_key(req2)


# ---------------------------------------------------------------------------
# TestBuildLimiter
# ---------------------------------------------------------------------------


class TestBuildLimiter:
    def test_build_limiter_returns_slowapi_limiter(self) -> None:
        settings = _stub_settings(
            app_env="test", rate_limit_storage_url="memory://"
        )
        limiter = build_limiter(settings)
        assert isinstance(limiter, Limiter)

    def test_default_limits_empty_so_opt_in_only(self) -> None:
        """Priority #4 — un-decorated routes (healthz, docs, openapi)
        must stay unrestricted. Empty default_limits is the switch."""
        settings = _stub_settings(
            app_env="test", rate_limit_storage_url="memory://"
        )
        limiter = build_limiter(settings)
        assert limiter._default_limits == []

    def test_disabled_returns_disabled_limiter(self) -> None:
        settings = _stub_settings(
            app_env="test",
            rate_limit_storage_url="memory://",
            rate_limit_enabled=False,
        )
        limiter = build_limiter(settings)
        assert limiter.enabled is False

    def test_prod_failure_raises_at_build_time(self) -> None:
        settings = _stub_settings(app_env="prod", rate_limit_storage_url="memory://")
        with pytest.raises(ValueError):
            build_limiter(settings)


# ---------------------------------------------------------------------------
# TestAppStartup — end-to-end infrastructure smoke
# ---------------------------------------------------------------------------


class TestAppStartup:
    """Priority #1 + #4 — app boots with limiter wired; /healthz and
    /openapi.json (when enabled) stay unrestricted because no route
    carries a @limiter.limit decorator yet."""

    async def test_app_has_limiter_in_state(self) -> None:
        from api.main import app

        assert hasattr(app.state, "limiter")
        assert isinstance(app.state.limiter, Limiter)

    async def test_healthz_remains_open(self, client) -> None:
        """Priority #4 — healthz must never be rate-limited. No
        decorator attached → no enforcement. This test also proves
        the middleware does not silently apply a default limit."""
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "api"}

    async def test_healthz_safe_under_burst(self, client) -> None:
        """100 requests in a row must all pass — proves default
        limits stay empty after SlowAPIMiddleware attaches."""
        for _ in range(100):
            resp = await client.get("/healthz")
            assert resp.status_code == 200

    async def test_rate_limit_exception_handler_registered(self) -> None:
        from slowapi.errors import RateLimitExceeded

        from api.main import app

        assert RateLimitExceeded in app.exception_handlers
