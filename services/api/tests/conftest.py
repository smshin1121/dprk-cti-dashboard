"""Shared pytest fixtures for the DPRK CTI API test suite.

All external dependencies (Redis, Keycloak, PostgreSQL) are replaced by
fakes/mocks so these tests run in CI without any infrastructure.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from itsdangerous import URLSafeTimedSerializer


# ---------------------------------------------------------------------------
# Env-var injection — MUST happen before any `from api...` import
# ---------------------------------------------------------------------------

def _inject_env_vars() -> None:
    """Set all required env vars to test-safe values."""
    defaults = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/testdb",
        "REDIS_URL": "redis://localhost:6379/0",
        "OIDC_CLIENT_ID": "dprk-cti",
        "OIDC_CLIENT_SECRET": "test-oidc-secret",
        "OIDC_ISSUER_URL": "http://keycloak.test/realms/dprk",
        "OIDC_REDIRECT_BASE_URL": "http://localhost:8000",
        "SESSION_SIGNING_KEY": "test-signing-key-at-least-32-chars!",
        "SESSION_COOKIE_NAME": "dprk_cti_session",
        "SESSION_COOKIE_SECURE": "false",
        "SESSION_COOKIE_SAMESITE": "lax",
        "CORS_ORIGINS": "http://localhost:3000",
        # PR #11 Group F env lock — test env is forced to memory://
        # inside _resolve_storage_uri regardless of this value, but
        # setting it here keeps the intent visible in the fixture
        # setup and future-proofs against a policy change.
        "RATE_LIMIT_STORAGE_URL": "memory://",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


# Inject before any test module can trigger a lazy import of api.*
_inject_env_vars()


# Now we can import from the application safely
from api.auth.schemas import CurrentUser, SessionData  # noqa: E402
from api.auth.session import SessionStore  # noqa: E402
from api.config import get_settings  # noqa: E402

# Clear the settings cache so it re-reads the env vars we set
get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Redis fake
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Return a fresh in-memory async Redis instance per test."""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


# ---------------------------------------------------------------------------
# Rate-limit isolation — reset slowapi memory:// storage between tests
# ---------------------------------------------------------------------------
#
# PR #11 Group G attaches @limiter.limit(...) to several routes. With
# default_limits=[] the middleware is a no-op on undecorated routes,
# but decorated routes accumulate bucket state across tests within
# the same process. Without reset: a test that makes 30 staging
# requests trips the 30/min/user bucket for every subsequent test
# that reuses the same session cookie. This fixture is autouse so
# every test starts with a clean slate.
#
# E2E rate-limit tests (tests/integration/test_rate_limit_e2e.py)
# deliberately exhaust a bucket within a single test — they run
# BETWEEN two reset calls so they never leak limit state.


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from api.main import app

    app.state.limiter.reset()
    yield
    app.state.limiter.reset()


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

_TEST_SIGNING_KEY = "test-signing-key-at-least-32-chars!"
_TEST_SIGNER_SALT = "dprk-cti-session-v1"


@pytest.fixture
def test_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_TEST_SIGNING_KEY, salt=_TEST_SIGNER_SALT)


@pytest_asyncio.fixture
async def session_store(fake_redis, test_signer) -> SessionStore:
    """SessionStore wired to the fake Redis and a deterministic signer."""
    return SessionStore(
        redis=fake_redis,
        signer=test_signer,
        ttl_seconds=3600,
    )


# ---------------------------------------------------------------------------
# HTTP client (ASGI transport — no real network)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(override_session_store):
    """AsyncClient attached to the FastAPI app via ASGI transport."""
    # Import here so settings are already patched
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Dependency override: swap real SessionStore for test SessionStore
# ---------------------------------------------------------------------------

@pytest.fixture
def override_session_store(session_store, fake_redis):
    """Override get_session_store + get_db in the FastAPI dependency graph.

    Also patches store_oidc_state / pop_oidc_state to use the fake Redis
    so no real Redis connection is attempted.
    """
    from unittest.mock import AsyncMock as _AsyncMock, patch as _patch

    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    # Mock DB session — audit log calls go to a no-op mock
    async def _fake_get_db():
        mock_session = _AsyncMock()
        mock_session.execute = _AsyncMock()
        mock_session.commit = _AsyncMock()
        yield mock_session

    _OIDC_STATE_PREFIX = "oidc_state:"
    _OIDC_STATE_TTL = 60

    async def _fake_store_oidc_state(state: str, payload: str) -> None:
        await fake_redis.set(f"{_OIDC_STATE_PREFIX}{state}", payload, ex=_OIDC_STATE_TTL)

    async def _fake_pop_oidc_state(state: str):
        key = f"{_OIDC_STATE_PREFIX}{state}"
        pipe = fake_redis.pipeline()
        pipe.get(key)
        pipe.delete(key)
        raw, _ = await pipe.execute()
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    import api.auth.session as _session_mod
    import api.routers.auth as _auth_router

    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_db] = _fake_get_db

    with _patch.object(_session_mod, "store_oidc_state", side_effect=_fake_store_oidc_state), \
         _patch.object(_session_mod, "pop_oidc_state", side_effect=_fake_pop_oidc_state), \
         _patch.object(_auth_router, "store_oidc_state", side_effect=_fake_store_oidc_state), \
         _patch.object(_auth_router, "pop_oidc_state", side_effect=_fake_pop_oidc_state):
        yield session_store

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper: create a session cookie the test client can use
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
def make_session_cookie(session_store, test_signer):
    """Factory fixture: given session fields, persists to fake Redis and
    returns the signed cookie value ready to pass to client.cookies."""

    async def _factory(
        sub: str = "user-123",
        email: str = "analyst@example.com",
        name: str = "Test User",
        roles: list[str] | None = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        data = SessionData(
            sub=sub,
            email=email,
            name=name,
            roles=roles or ["analyst"],
            created_at=now,
            last_activity=now,
        )
        cookie_value = await session_store.create(data)
        return cookie_value

    return _factory


# ---------------------------------------------------------------------------
# Canonical JWT claims for jwt_verifier tests
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_jwt_claims() -> dict:
    """A canonical set of decoded Keycloak JWT claims used in jwt_verifier tests."""
    return {
        "sub": "abc-123",
        "email": "analyst@dprk.test",
        "preferred_username": "analyst",
        "name": "Real Name",
        "realm_access": {"roles": ["analyst", "admin", "unknown_role"]},
        "iss": "http://keycloak.test/realms/dprk",
        "aud": "dprk-cti",
        "exp": 9999999999,
        "iat": 1700000000,
        "nbf": 1700000000,
    }
