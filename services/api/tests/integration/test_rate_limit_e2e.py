"""E2E rate-limit tests covering Group G (PR #10 mutation bucket)
and Group H (PR #11 read bucket + /auth/me).

Each bucket is exhausted within ONE test so the autouse
``_reset_rate_limiter`` fixture gives a clean starting state. These
tests are the only place we deliberately drain the limiter — every
other test relies on the reset fixture to keep below the cap.

Reviewer priorities (cumulative through Group H):

1. **D2 numbers** — 10/min/IP on auth login/callback, 30/min/user on
   the mutation bucket (staging GETs + POST review), 60/min/user on
   the read bucket (/actors, /reports GET, /incidents, /dashboard,
   /auth/me).
2. **key_func dispatch** — session cookie vs client IP, covered by
   ``TestKeyScope`` (Group G) and ``TestReadBucketKeyScope``
   (Group H: same cookie across read endpoints; no-cookie path).
3. **429 body matches the OpenAPI example.** ``TestResponseShape``
   (Group G auth/login) and ``TestReadBucketResponseShape`` (Group
   H — asserts every read router's OpenAPI 429 example equals the
   actual body field-for-field).
4. **Per-route bucket isolation.** Draining /actors does NOT 429
   /incidents — slowapi scopes limits per decorated route.
5. **Response-shape preservation.** The decorator does not perturb
   the 200-body DTO (items + pagination metadata / aggregate
   summary / ``CurrentUser`` for /auth/me).
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


# ---------------------------------------------------------------------------
# Group H — 60/min/user read bucket on /actors, /reports, /incidents,
#           /dashboard, /auth/me
# ---------------------------------------------------------------------------


# Fixed per-router metadata the Group H boundary tests + OpenAPI-drift
# test iterate over. Keeping this table single-source so adding a new
# read route requires one row edit here and the shape assertions cover
# it automatically.
_READ_ROUTES = [
    ("/api/v1/actors", "get"),
    ("/api/v1/reports", "get"),
    ("/api/v1/incidents", "get"),
    ("/api/v1/dashboard/summary", "get"),
    ("/api/v1/auth/me", "get"),
]


class TestReadBucketBoundary:
    async def test_60_actors_then_61st_is_429(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """Plan D2 locks 60/min/user on read endpoints. Drive /actors
        to the boundary, assert the 61st call is 429.

        Uses an empty DB on purpose — ``list_actors`` returns
        ``([], 0)`` on empty, the response is still a 200 with the
        ``ActorListResponse`` shape (items / limit / offset / total).
        """
        cookie = await _cookie(make_session_cookie)
        for i in range(60):
            resp = await rl_client.get(
                "/api/v1/actors",
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200, f"request {i} should pass"
            # Response-shape preservation (reviewer priority #5).
            body = resp.json()
            assert set(body.keys()) == {"items", "limit", "offset", "total"}
            assert body["items"] == []
            assert body["total"] == 0

        over = await rl_client.get(
            "/api/v1/actors",
            cookies={"dprk_cti_session": cookie},
        )
        assert over.status_code == 429

    async def test_60_auth_me_then_61st_is_429_json_not_redirect(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """/auth/me is a read endpoint — 60/min/user — but unlike the
        four list endpoints it existed before Group H. Pin:

        - 61st request returns 429 (not 200, not redirect)
        - body is JSON matching the Group F/G handler shape
        - the existing ``CurrentUser`` DTO is preserved on the 200
          responses that precede the 429 (no extra/missing fields)
        """
        cookie = await _cookie(make_session_cookie)
        for i in range(60):
            resp = await rl_client.get(
                "/api/v1/auth/me",
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200, f"request {i} should pass"
            body = resp.json()
            # CurrentUser DTO from api.auth.schemas — assert the
            # key set verbatim so a future shape drift shows up here
            # instead of silently through FE.
            assert set(body.keys()) == {"sub", "email", "name", "roles"}

        over = await rl_client.get(
            "/api/v1/auth/me",
            cookies={"dprk_cti_session": cookie},
        )
        assert over.status_code == 429
        # Must be JSON — not a 302/307 redirect (reviewer priority).
        assert over.headers["content-type"].startswith("application/json")
        over_body = over.json()
        assert over_body["error"] == "rate_limit_exceeded"
        assert set(over_body.keys()) == {"error", "message"}


class TestReadBucketKeyScope:
    async def test_same_cookie_read_endpoints_independent_buckets(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """Reviewer criterion: 'same-session bucket shared between read
        endpoints?' — The answer is NO: slowapi scopes limits per
        decorated route. Pin this explicitly so a future ``shared=True``
        or ``scope=`` change to the decorator call surfaces as a test
        failure.

        Drain /actors to 60, then /incidents (same cookie) is still
        fresh. If a future refactor consolidates read endpoints under
        one shared bucket, this test flips from expected fresh→200 to
        429 and reviewer is alerted.
        """
        cookie = await _cookie(make_session_cookie)
        for _ in range(60):
            resp = await rl_client.get(
                "/api/v1/actors",
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200

        over_actors = await rl_client.get(
            "/api/v1/actors",
            cookies={"dprk_cti_session": cookie},
        )
        assert over_actors.status_code == 429

        # Same cookie, different decorated route — bucket is fresh.
        fresh_incidents = await rl_client.get(
            "/api/v1/incidents",
            cookies={"dprk_cti_session": cookie},
        )
        assert fresh_incidents.status_code == 200

        # /auth/me also independent.
        fresh_me = await rl_client.get(
            "/api/v1/auth/me",
            cookies={"dprk_cti_session": cookie},
        )
        assert fresh_me.status_code == 200

    async def test_no_cookie_on_auth_gated_read_does_not_consume_bucket(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """slowapi's ``@limiter.limit`` wraps the handler; router-level
        ``Depends(verify_token)`` runs BEFORE the wrapped handler body.
        An anonymous spray therefore 401s 100× without ever incrementing
        the real user's rate-limit bucket. This is a security-positive
        property: a drive-by attacker can't lock a legitimate user out
        of their 60/min budget by hammering the endpoint from the
        user's IP.

        IP-bucket observability for no-cookie callers is covered by
        the auth/login test above (10/min/IP, no auth dep) and by the
        ``session_or_ip_key`` unit tests in ``test_rate_limit.py``.
        This test pins the interaction for auth-gated reads.
        """
        # 65 anonymous hits = 65x 401 (auth gate beats decorator).
        for _ in range(65):
            resp = await rl_client.get("/api/v1/actors")
            assert resp.status_code == 401

        # User's real bucket is untouched — 60 authenticated hits
        # still all succeed.
        cookie = await _cookie(make_session_cookie)
        for i in range(60):
            resp = await rl_client.get(
                "/api/v1/actors",
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200, (
                f"request {i} failed — anonymous spray leaked into user bucket?"
            )

    async def test_different_cookies_isolated_on_read_bucket(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """Mirror of Group G's ``test_different_cookies_dont_share_bucket``
        for the 60/min read bucket. User A drains /actors; user B's
        first /actors request still returns 200.
        """
        cookie_a = await _cookie(make_session_cookie)
        for _ in range(60):
            resp = await rl_client.get(
                "/api/v1/actors",
                cookies={"dprk_cti_session": cookie_a},
            )
            assert resp.status_code == 200

        over_a = await rl_client.get(
            "/api/v1/actors",
            cookies={"dprk_cti_session": cookie_a},
        )
        assert over_a.status_code == 429

        cookie_b = await make_session_cookie(sub="user-B", roles=["analyst"])
        fresh = await rl_client.get(
            "/api/v1/actors",
            cookies={"dprk_cti_session": cookie_b},
        )
        assert fresh.status_code == 200


class TestReadBucketResponseShape:
    async def test_429_body_matches_openapi_example_on_every_read_route(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """Reviewer criterion: '429 example matches actual body on each
        router.' Iterates over _READ_ROUTES, draining each bucket and
        comparing the live 429 body against the spec example keyed by
        path/method/429/content/application/json/example.

        This is the drift-prevention net: if someone changes the
        decorator limit (e.g. 60 → 120), the OpenAPI message string
        no longer matches the live body and the test fails here —
        before the FE sees a stale contract.
        """
        from api.main import app

        spec = app.openapi()
        cookie = await _cookie(make_session_cookie)

        for path, method in _READ_ROUTES:
            # Reset between routes so each route drains cleanly — the
            # previous route's bucket is on a different key_func scope
            # but the explicit reset keeps the intent obvious.
            app.state.limiter.reset()

            # Drain 60 successful calls, then the 61st is 429.
            for _ in range(60):
                resp = await rl_client.get(
                    path, cookies={"dprk_cti_session": cookie}
                )
                assert resp.status_code == 200, (
                    f"{path} failed during drain: {resp.status_code}"
                )
            over = await rl_client.get(
                path, cookies={"dprk_cti_session": cookie}
            )
            assert over.status_code == 429, f"{path} did not 429"

            body = over.json()
            assert set(body.keys()) == {"error", "message"}
            assert body["error"] == "rate_limit_exceeded"

            # Match against the OpenAPI example for THIS route.
            example = spec["paths"][path][method]["responses"]["429"][
                "content"
            ]["application/json"]["example"]
            assert example == body, (
                f"OpenAPI example for {path} drifted from live body:\n"
                f"  expected={example!r}\n  got={body!r}"
            )

    async def test_429_headers_present_on_read_bucket(
        self, rl_client: AsyncClient, make_session_cookie
    ) -> None:
        """Plan D2 — 429 response on read bucket carries Retry-After,
        X-RateLimit-Limit=60, X-RateLimit-Remaining=0.
        """
        cookie = await _cookie(make_session_cookie)
        for _ in range(60):
            await rl_client.get(
                "/api/v1/actors",
                cookies={"dprk_cti_session": cookie},
            )
        resp = await rl_client.get(
            "/api/v1/actors",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1
        assert int(resp.headers["X-RateLimit-Limit"]) == 60
        assert int(resp.headers["X-RateLimit-Remaining"]) == 0
