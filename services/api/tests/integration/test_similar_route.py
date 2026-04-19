"""Integration tests for PR #14 Group B ``GET /api/v1/reports/{id}/similar``.

HTTP-layer contract:
- 404 when the source report id is unknown.
- 422 on non-integer report_id OR on k outside ``[1, 50]`` (plan D8).
- 200 + ``{items: []}`` on the D10 empty-contract path (sqlite dialect
  means no pgvector — the service returns empty by design; the real-PG
  NULL-embedding + zero-neighbor paths live in the real-PG
  integration suite).
- Default ``k`` is 10 when the query param is omitted (plan D8 lock).

Cache interaction is covered by the unit tests in
``tests/unit/test_similar_service_and_cache.py``; here we verify the
router's dependency-override hook works (dependency is ``get_redis_for_similar_cache``;
the override returns ``None`` so the cache is a no-op in the test
rig — no Redis container needed).
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
async def similar_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def similar_client(
    similar_engine: AsyncEngine, session_store, fake_redis
) -> AsyncIterator[AsyncClient]:
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app
    from api.read.similar_cache import get_redis_for_similar_cache

    sessionmaker = async_sessionmaker(similar_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    # No-op cache for the test rig — the production getter returns
    # a real redis_asyncio client; here None lets the cache helpers
    # deterministically short-circuit.
    app.dependency_overrides[get_redis_for_similar_cache] = lambda: None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


async def _cookie(make_session_cookie, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


async def _seed_source(engine: AsyncEngine) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name="Mandiant", type="vendor")
            .returning(sources_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


async def _seed_report(engine: AsyncEngine, *, title: str, source_id: int) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(reports_table)
            .values(
                title=title,
                url=f"https://ex.test/{title}",
                url_canonical=f"https://ex.test/{title}",
                sha256_title=f"sha-{title}",
                source_id=source_id,
                published=dt.date(2026, 3, 15),
                tlp="WHITE",
            )
            .returning(reports_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


# ---------------------------------------------------------------------------
# 404 — unknown source id (D1 + D8 found=False path)
# ---------------------------------------------------------------------------


class Test404:
    async def test_unknown_source_is_404(
        self, similar_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await similar_client.get(
            "/api/v1/reports/99999/similar",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "report not found"}


# ---------------------------------------------------------------------------
# 422 — k bounds + non-integer path param (D8 + D12)
# ---------------------------------------------------------------------------


class TestKBoundsAnd422:
    async def test_k_below_min_is_422(
        self,
        similar_client: AsyncClient,
        make_session_cookie,
        similar_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(similar_engine)
        r_id = await _seed_report(
            similar_engine, title="src", source_id=src
        )
        cookie = await _cookie(make_session_cookie)
        resp = await similar_client.get(
            f"/api/v1/reports/{r_id}/similar?k=0",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_k_above_max_is_422(
        self,
        similar_client: AsyncClient,
        make_session_cookie,
        similar_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(similar_engine)
        r_id = await _seed_report(
            similar_engine, title="src", source_id=src
        )
        cookie = await _cookie(make_session_cookie)
        resp = await similar_client.get(
            f"/api/v1/reports/{r_id}/similar?k=51",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_non_integer_report_id_is_422(
        self, similar_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await similar_client.get(
            "/api/v1/reports/not-a-number/similar",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# D10 empty contract — 200 + {items: []}
# ---------------------------------------------------------------------------


class TestD10EmptyContract:
    async def test_sqlite_dialect_returns_200_empty(
        self,
        similar_client: AsyncClient,
        make_session_cookie,
        similar_engine: AsyncEngine,
    ) -> None:
        """On sqlite there's no pgvector column — D10 contract
        kicks in. ``200 + {items: []}`` per plan D10 lock. A
        heuristic-fallback regression would surface as non-empty
        items here (neighbors seeded below would be picked up by
        a "most recent N" substitute).
        """
        src = await _seed_source(similar_engine)
        r_id = await _seed_report(
            similar_engine, title="anchor", source_id=src
        )
        # Seed potential "fake" neighbors — D10 forbids a heuristic
        # that would return these as substitutes.
        for name in ["neighbor-a", "neighbor-b", "neighbor-c"]:
            await _seed_report(
                similar_engine, title=name, source_id=src
            )
        cookie = await _cookie(make_session_cookie)
        resp = await similar_client.get(
            f"/api/v1/reports/{r_id}/similar",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"items": []}

    async def test_omitted_k_defaults_to_10(
        self,
        similar_client: AsyncClient,
        make_session_cookie,
        similar_engine: AsyncEngine,
    ) -> None:
        """Plan D8 default = 10. Test: omitted query param still
        produces 200 (not 422), confirming the Query default
        survives. Actual 10-neighbor ordering lives in the real-PG
        suite because sqlite's D10 empty contract produces []
        regardless of k.
        """
        src = await _seed_source(similar_engine)
        r_id = await _seed_report(
            similar_engine, title="anchor", source_id=src
        )
        cookie = await _cookie(make_session_cookie)
        resp = await similar_client.get(
            f"/api/v1/reports/{r_id}/similar",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
