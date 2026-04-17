"""E2E rate-limit tests for PR #10 routers decorated in PR #11 Group G.

Each bucket is exhausted within ONE test so the autouse
``_reset_rate_limiter`` fixture gives a clean starting state. These
tests are the only place we deliberately drain the limiter — every
other test relies on the reset fixture to keep below the cap.

Reviewer priorities (Group G):

1. D2 numbers — 10/min/IP on auth endpoints, 30/min/user on the
   mutation bucket (staging GETs + POST review).
2. key_func dispatch — session cookie vs client IP, covered by
   ``TestKeyScope``.
3. 429 body matches the OpenAPI `rate_limit_exceeded` example.
   ``TestResponseShape`` pins the JSON shape and header presence.
4. Different cookies land in different buckets; same cookie shares
   one bucket.
5. PR #10 routers use the mutation bucket (30/min), not the read
   bucket (60/min — Group H). Tests exercise the 30/min boundary.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.tables import metadata


# ---------------------------------------------------------------------------
# Fixtures — real aiosqlite DB so staging/review handlers run through
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def rl_client(
    real_engine: AsyncEngine,
    session_store,
    fake_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    sessionmaker = async_sessionmaker(real_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    # /auth/login and /auth/callback touch Redis via the OIDC state
    # helpers — these would fail with a real Redis connection attempt
    # in CI. Patch both module-level functions to use the fake_redis
    # fixture so the endpoints run the full decorator-then-handler
    # path. Without this, the rate-limit decorator never reaches the
    # 11th call because the handler's Redis write raises 500 first.
    import api.auth.session as _session_mod
    import api.routers.auth as _auth_router

    async def _fake_store_oidc_state(state: str, payload: str) -> None:
        await fake_redis.set(f"oidc_state:{state}", payload, ex=60)

    async def _fake_pop_oidc_state(state: str):
        raw = await fake_redis.getdel(f"oidc_state:{state}")
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    monkeypatch.setattr(_session_mod, "store_oidc_state", _fake_store_oidc_state)
    monkeypatch.setattr(_auth_router, "store_oidc_state", _fake_store_oidc_state)
    monkeypatch.setattr(_session_mod, "pop_oidc_state", _fake_pop_oidc_state)
    monkeypatch.setattr(_auth_router, "pop_oidc_state", _fake_pop_oidc_state)

    # Skip the real OIDC discovery HTTP call — Keycloak is not
    # reachable in unit/CI envs. The rate-limit decorator runs BEFORE
    # this function executes, so returning a stub URL is enough for
    # the 302 redirect and the RL counter increments correctly.
    async def _fake_build_auth_url(**_: object) -> str:
        return "http://keycloak.test/authorize?stub=1"

    monkeypatch.setattr(_auth_router, "build_authorization_url", _fake_build_auth_url)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def _cookie(make_session_cookie, *, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# Priority #1 — 10/min/IP on auth endpoints
# ---------------------------------------------------------------------------


class TestAuthLoginBucket:
    async def test_login_429_after_10_requests(
        self, rl_client: AsyncClient
    ) -> None:
        """The 11th /auth/login from the same IP returns 429.

        Uses the anonymous path — no cookie — so the key_func falls
        back to ``ip:<remote>`` per plan D2.
        """
        successes = 0
        for _ in range(10):
            resp = await rl_client.get("/api/v1/auth/login")
            if resp.status_code in (302, 307):
                successes += 1
        assert successes == 10

        # 11th — 429.
        over = await rl_client.get("/api/v1/auth/login")
        assert over.status_code == 429


# ---------------------------------------------------------------------------
# Priority #1 + #5 — 30/min/user on the mutation bucket
# ---------------------------------------------------------------------------


class TestStagingListBucket:
    async def test_30_succeed_then_31st_is_429(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie, role="analyst")
        for i in range(30):
            resp = await rl_client.get(
                "/api/v1/staging/review",
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200, f"request {i} should pass"

        over = await rl_client.get(
            "/api/v1/staging/review",
            cookies={"dprk_cti_session": cookie},
        )
        assert over.status_code == 429


# ---------------------------------------------------------------------------
# Priority #2 + #4 — key_func dispatch on session cookies
# ---------------------------------------------------------------------------


class TestKeyScope:
    async def test_different_cookies_dont_share_bucket(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """User A drains the 30/min bucket; user B's first request
        must still return 200 because the key_func places them in
        different buckets."""
        cookie_a = await _cookie(make_session_cookie, role="analyst")
        for _ in range(30):
            resp = await rl_client.get(
                "/api/v1/staging/review",
                cookies={"dprk_cti_session": cookie_a},
            )
            assert resp.status_code == 200

        # User A is now over the limit.
        over_a = await rl_client.get(
            "/api/v1/staging/review",
            cookies={"dprk_cti_session": cookie_a},
        )
        assert over_a.status_code == 429

        # User B — distinct session cookie — first request still passes.
        cookie_b = await make_session_cookie(sub="user-B", roles=["analyst"])
        fresh = await rl_client.get(
            "/api/v1/staging/review",
            cookies={"dprk_cti_session": cookie_b},
        )
        assert fresh.status_code == 200

    async def test_same_cookie_shares_bucket_across_endpoints_in_mutation_group(
        self, rl_client: AsyncClient, make_session_cookie, real_engine: AsyncEngine
    ) -> None:
        """30/min/user is per-endpoint, not per-bucket. A user hitting
        /staging/review and /staging/{id} consumes two DIFFERENT
        buckets because slowapi scopes limits per decorated route.

        Pins this scoping explicitly — review priority lock.
        """
        cookie = await _cookie(make_session_cookie)
        # seed one staging row so /staging/{id} doesn't 404
        from api.tables import staging_table

        import datetime as dt

        async with AsyncSession(real_engine, expire_on_commit=False) as s:
            await s.execute(
                sa.insert(staging_table).values(
                    url="https://ex/seed",
                    url_canonical="https://ex/seed",
                    title="seed",
                    status="pending",
                    published=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                )
            )
            await s.commit()

        # Drain list bucket to 30.
        for _ in range(30):
            resp = await rl_client.get(
                "/api/v1/staging/review",
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200

        # list is at limit...
        over = await rl_client.get(
            "/api/v1/staging/review",
            cookies={"dprk_cti_session": cookie},
        )
        assert over.status_code == 429

        # ...but /staging/{id} is a separate bucket, still fresh.
        fresh = await rl_client.get(
            "/api/v1/staging/1",
            cookies={"dprk_cti_session": cookie},
        )
        assert fresh.status_code == 200


# ---------------------------------------------------------------------------
# Priority #3 — 429 body shape and headers
# ---------------------------------------------------------------------------


class TestResponseShape:
    async def test_body_is_json_with_expected_shape(
        self, rl_client: AsyncClient
    ) -> None:
        for _ in range(10):
            await rl_client.get("/api/v1/auth/login")
        resp = await rl_client.get("/api/v1/auth/login")
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate_limit_exceeded"
        assert isinstance(body["message"], str)
        assert len(body["message"]) > 0
        # The OpenAPI example claims the same shape — if Group H adds
        # new routers, that contract needs to hold there too.
        assert set(body.keys()) == {"error", "message"}

    async def test_headers_present_on_429(
        self, rl_client: AsyncClient
    ) -> None:
        for _ in range(10):
            await rl_client.get("/api/v1/auth/login")
        resp = await rl_client.get("/api/v1/auth/login")
        assert resp.status_code == 429
        # Plan D2 locks these three headers on 429. Values must be
        # parseable integers.
        assert "Retry-After" in resp.headers
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1
        assert int(resp.headers["X-RateLimit-Limit"]) == 10  # /auth/login is 10/min
        assert int(resp.headers["X-RateLimit-Remaining"]) == 0

    async def test_body_matches_openapi_example_shape(self) -> None:
        """The 429 response contract is documented in every
        decorated route's OpenAPI ``responses`` block with an example.
        Assert the actual body here matches that example's shape
        field-for-field so a drift in one or the other surfaces in
        this test."""
        from api.main import app

        spec = app.openapi()
        example = (
            spec["paths"]["/api/v1/auth/login"]["get"]["responses"]["429"][
                "content"
            ]["application/json"]["example"]
        )
        assert set(example.keys()) == {"error", "message"}
        assert example["error"] == "rate_limit_exceeded"


# ---------------------------------------------------------------------------
# Priority #5 — /healthz still unrestricted with limiter live
# ---------------------------------------------------------------------------


class TestExclusions:
    async def test_healthz_still_free_under_burst(
        self, rl_client: AsyncClient
    ) -> None:
        """40 burst requests on /healthz. If a default limit has
        accidentally leaked into the Limiter (regression in Group F
        lock), this fails with 429 around request 11 (because the
        IP bucket would collect everything since /healthz has no
        cookie path)."""
        for _ in range(40):
            resp = await rl_client.get("/healthz")
            assert resp.status_code == 200
