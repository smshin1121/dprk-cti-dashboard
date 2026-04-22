"""Integration tests for PR #17 Group B ``GET /api/v1/search``.

HTTP-layer priorities:
1. q empty / whitespace / malformed params reject with 422.
2. RBAC matches the five read roles; 401 / 403 are distinct.
3. sqlite path returns the D10 empty envelope when not patched.
4. Rate-limit bucket is independent from `/actors`.
5. OpenAPI response blocks + examples stay aligned.
"""

from __future__ import annotations

import datetime as dt
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

from api.tables import metadata, reports_table, sources_table

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def search_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def search_client(
    search_engine: AsyncEngine, session_store, fake_redis
) -> AsyncIterator[AsyncClient]:
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app
    from api.read.search_cache import get_redis_for_search_cache

    sessionmaker = async_sessionmaker(search_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_redis_for_search_cache] = lambda: fake_redis
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


async def _cookie(make_session_cookie, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


async def _seed_source(engine: AsyncEngine, name: str = "Vendor") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        source_id = row.scalar_one()
        await s.commit()
        return source_id


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    summary: str,
    source_id: int,
    published: dt.date,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(reports_table)
            .values(
                title=title,
                summary=summary,
                url=f"https://ex.test/{title}",
                url_canonical=f"https://ex.test/{title}",
                sha256_title=f"sha-{title}",
                source_id=source_id,
                published=published,
                tlp="WHITE",
                lang="en",
            )
            .returning(reports_table.c.id)
        )
        report_id = row.scalar_one()
        await s.commit()
        return report_id


class TestHappyAndEmpty:
    async def test_happy_path_with_stubbed_fts_result(
        self,
        search_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
        search_engine: AsyncEngine,
    ) -> None:
        from api.read.search_service import SearchServiceResult
        import api.read.search_service as search_service

        src = await _seed_source(search_engine)
        report_id = await _seed_report(
            search_engine,
            title="Lazarus search hit",
            summary="crypto exchange targeting",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )

        async def _fake_get_search_results(
            session, redis, *, q, date_from, date_to, limit,
            embedding_client=None,
        ):
            return SearchServiceResult(
                payload={
                    "items": [
                        {
                            "report": {
                                "id": report_id,
                                "title": "Lazarus search hit",
                                "url": "https://ex.test/Lazarus search hit",
                                "url_canonical": "https://ex.test/Lazarus search hit",
                                "published": "2026-03-15",
                                "source_id": src,
                                "source_name": "Vendor",
                                "lang": "en",
                                "tlp": "WHITE",
                            },
                            "fts_rank": 0.42,
                            "vector_rank": None,
                        }
                    ],
                    "total_hits": 1,
                    "latency_ms": 7,
                },
                cache_hit=False,
                fts_ms=4,
            )

        monkeypatch.setattr(search_service, "get_search_results", _fake_get_search_results)

        cookie = await _cookie(make_session_cookie)
        resp = await search_client.get(
            "/api/v1/search?q=lazarus",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"items", "total_hits", "latency_ms"}
        assert body["total_hits"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["fts_rank"] == 0.42
        assert body["items"][0]["vector_rank"] is None

    async def test_sqlite_dialect_returns_d10_empty_envelope(
        self,
        search_client: AsyncClient,
        make_session_cookie,
        search_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(search_engine)
        await _seed_report(
            search_engine,
            title="Lazarus sqlite row",
            summary="still empty because sqlite has no PG FTS",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )
        cookie = await _cookie(make_session_cookie)
        resp = await search_client.get(
            "/api/v1/search?q=lazarus",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total_hits"] == 0
        assert isinstance(body["latency_ms"], int)
        assert body["latency_ms"] >= 0


class Test422:
    async def test_missing_q_is_422(
        self, search_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await search_client.get(
            "/api/v1/search",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_whitespace_only_q_is_422(
        self, search_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await search_client.get(
            "/api/v1/search?q=%20%20%20",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"][0]["loc"] == ["query", "q"]
        assert body["detail"][0]["type"] == "value_error.blank_query"

    @pytest.mark.parametrize("bad_limit", ["0", "51"])
    async def test_limit_out_of_range_is_422(
        self,
        search_client: AsyncClient,
        make_session_cookie,
        bad_limit: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await search_client.get(
            f"/api/v1/search?q=lazarus&limit={bad_limit}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_malformed_date_is_422(
        self, search_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await search_client.get(
            "/api/v1/search?q=lazarus&date_from=2026-13-01",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


class TestRBAC:
    async def test_no_cookie_returns_401(
        self, search_client: AsyncClient
    ) -> None:
        resp = await search_client.get("/api/v1/search?q=lazarus")
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role", ["analyst", "researcher", "policy", "soc", "admin"]
    )
    async def test_authorized_roles(
        self,
        search_client: AsyncClient,
        make_session_cookie,
        role: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie, role=role)
        resp = await search_client.get(
            "/api/v1/search?q=lazarus",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200

    async def test_unknown_role_403(
        self, search_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie, role="unknown_role")
        resp = await search_client.get(
            "/api/v1/search?q=lazarus",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 403


class TestRateLimitIndependence:
    async def test_search_bucket_is_independent_from_actors_bucket(
        self, search_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        for _ in range(60):
            resp = await search_client.get(
                "/api/v1/search?q=lazarus",
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200

        over = await search_client.get(
            "/api/v1/search?q=lazarus",
            cookies={"dprk_cti_session": cookie},
        )
        assert over.status_code == 429
        assert over.json() == {
            "error": "rate_limit_exceeded",
            "message": "60 per 1 minute",
        }

        actors_resp = await search_client.get(
            "/api/v1/actors",
            cookies={"dprk_cti_session": cookie},
        )
        assert actors_resp.status_code == 200


class TestOpenAPISurface:
    async def test_openapi_includes_search_examples_and_responses(self) -> None:
        from api.main import app

        spec = app.openapi()
        path = spec["paths"]["/api/v1/search"]["get"]
        assert "200" in path["responses"]
        assert "401" in path["responses"]
        assert "403" in path["responses"]
        assert "422" in path["responses"]
        assert "429" in path["responses"]
        examples = path["responses"]["200"]["content"]["application/json"]["examples"]
        assert "happy" in examples
        assert "empty" in examples
        assert set(examples["empty"]["value"].keys()) == {
            "items",
            "total_hits",
            "latency_ms",
        }
