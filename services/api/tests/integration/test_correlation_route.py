"""Integration tests for /api/v1/analytics/correlation router (PR #28).

Mirrors the test_analytics_route.py pattern — full app pipeline,
get_db + get_session_store overrides, cookie-based auth via
make_session_cookie fixture from conftest.

Covers (Codex r1 + r2 fixes):
- 422 identical_series envelope shape (R-15)
- 422 caller-supplied date_to < date_from
- 422 unknown series id (catalog existence check)
- 401 without cookie
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator

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

from api.tables import (
    incidents_table,
    metadata,
    reports_table,
    sources_table,
)


@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def correlation_client(
    real_engine: AsyncEngine, session_store, fake_redis
) -> AsyncIterator[AsyncClient]:
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    sessionmaker = async_sessionmaker(real_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def _seed_minimal(real_engine: AsyncEngine) -> None:
    """Seed enough data for an N=40 month range across both source roots."""
    async with AsyncSession(real_engine, expire_on_commit=False) as s:
        src_result = await s.execute(
            sa.insert(sources_table)
            .values(name="src-test", type="vendor")
            .returning(sources_table.c.id)
        )
        source_id = src_result.scalar_one()
        await s.execute(
            sa.insert(reports_table),
            [
                {
                    "source_id": source_id,
                    "published": dt.date(2020 + (i // 12), (i % 12) + 1, 1),
                    "title": f"r{i}",
                    "url": f"https://example.test/r{i}",
                    "url_canonical": f"https://example.test/r{i}",
                    "sha256_title": f"{i:064x}",
                    "lang": "en",
                    "tlp": "white",
                }
                for i in range(40)
            ],
        )
        await s.execute(
            sa.insert(incidents_table),
            [
                {
                    "reported": dt.date(2020 + (i // 12), (i % 12) + 1, 1),
                    "title": f"i{i}",
                    "description": "test",
                }
                for i in range(40)
            ],
        )
        await s.commit()


@pytest.mark.asyncio
async def test_correlation_route_401_without_cookie(
    correlation_client: AsyncClient,
) -> None:
    response = await correlation_client.get(
        "/api/v1/analytics/correlation",
        params={"x": "reports.total", "y": "incidents.total"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_correlation_route_422_identical_series(
    correlation_client: AsyncClient, make_session_cookie
) -> None:
    """Pin EXACT 422 envelope shape per spec §7.3 (Codex r3 M2)."""
    cookie = await make_session_cookie(roles=["analyst"])
    response = await correlation_client.get(
        "/api/v1/analytics/correlation",
        params={"x": "reports.total", "y": "reports.total"},
        cookies={"dprk_cti_session": cookie},
    )
    assert response.status_code == 422
    body = response.json()
    # Envelope is exactly { "detail": [single-entry] } — no extra entries
    assert body == {
        "detail": [
            {
                "loc": ["query", "y"],
                "msg": "x and y must be different series IDs",
                "type": "value_error.identical_series",
                "ctx": {"x": "reports.total", "y": "reports.total"},
            }
        ]
    }


@pytest.mark.asyncio
async def test_correlation_route_422_date_to_before_date_from(
    correlation_client: AsyncClient, make_session_cookie
) -> None:
    """Pin EXACT 422 envelope shape (Codex r3 M2)."""
    cookie = await make_session_cookie(roles=["analyst"])
    response = await correlation_client.get(
        "/api/v1/analytics/correlation",
        params={
            "x": "reports.total",
            "y": "incidents.total",
            "date_from": "2024-12-31",
            "date_to": "2020-01-01",
        },
        cookies={"dprk_cti_session": cookie},
    )
    assert response.status_code == 422
    body = response.json()
    assert body == {
        "detail": [
            {
                "loc": ["query", "date_to"],
                "msg": "date_to must be on or after date_from",
                "type": "value_error",
                "ctx": {
                    "date_from": "2024-12-31",
                    "date_to": "2020-01-01",
                },
            }
        ]
    }


@pytest.mark.asyncio
async def test_correlation_route_422_unknown_series(
    correlation_client: AsyncClient,
    real_engine: AsyncEngine,
    make_session_cookie,
) -> None:
    """Pin EXACT 422 envelope shape for unknown series (Codex r3 M2)."""
    await _seed_minimal(real_engine)
    cookie = await make_session_cookie(roles=["analyst"])
    response = await correlation_client.get(
        "/api/v1/analytics/correlation",
        params={
            "x": "reports.total",
            "y": "incidents.by_country.NOT_REAL",
            "date_from": "2020-01-01",
            "date_to": "2024-12-31",
        },
        cookies={"dprk_cti_session": cookie},
    )
    assert response.status_code == 422
    body = response.json()
    assert body == {
        "detail": [
            {
                "loc": ["query", "y"],
                "msg": "series id 'incidents.by_country.NOT_REAL' not in catalog",
                "type": "value_error",
            }
        ]
    }


@pytest.mark.asyncio
async def test_correlation_route_happy_smoke(
    correlation_client: AsyncClient,
    real_engine: AsyncEngine,
    make_session_cookie,
) -> None:
    """Full happy path — populated DB + valid catalog series → 200 with
    locked 49-cell lag_grid + interpretation contract."""
    await _seed_minimal(real_engine)
    cookie = await make_session_cookie(roles=["analyst"])
    response = await correlation_client.get(
        "/api/v1/analytics/correlation",
        params={
            "x": "reports.total",
            "y": "incidents.total",
            "date_from": "2020-01-01",
            "date_to": "2024-12-31",
        },
        cookies={"dprk_cti_session": cookie},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["x"] == "reports.total"
    assert body["y"] == "incidents.total"
    assert body["alpha"] == 0.05
    assert len(body["lag_grid"]) == 49
    assert body["interpretation"]["caveat"]
    assert body["interpretation"]["methodology_url"]


@pytest.mark.asyncio
async def test_correlation_series_catalog_route(
    correlation_client: AsyncClient,
    real_engine: AsyncEngine,
    make_session_cookie,
) -> None:
    """Catalog endpoint returns the curated baseline + dimension-derived series."""
    await _seed_minimal(real_engine)
    cookie = await make_session_cookie(roles=["analyst"])
    response = await correlation_client.get(
        "/api/v1/analytics/correlation/series",
        cookies={"dprk_cti_session": cookie},
    )
    assert response.status_code == 200
    body = response.json()
    ids = {entry["id"] for entry in body["series"]}
    assert "reports.total" in ids
    assert "incidents.total" in ids
