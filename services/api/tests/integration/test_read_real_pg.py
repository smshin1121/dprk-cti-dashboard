"""Real-PostgreSQL integration tests for PR #11 read endpoints.

Plan §5.2 locks 8 scenarios for Group K acceptance. Group B lands
scenario 1 (`/actors` list) only; scenarios 2–8 (reports filters,
incidents multi-country, /dashboard/summary, keyset cursor
stability, rate-limit 429, invalid-filter 422, OpenAPI example
drift) are added by Groups C–K.

Skipped when ``POSTGRES_TEST_URL`` is unset — matches the PR #10
pattern so developers can still run ``pytest tests/`` without
spinning up Postgres. CI sets the env var for ``api-integration``.
"""

from __future__ import annotations

import asyncio
import os
import sys
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


# Windows fix: psycopg async driver requires SelectorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


pytestmark = pytest.mark.integration


_PG_URL = os.environ.get("POSTGRES_TEST_URL")

if not _PG_URL:
    pytest.skip(
        "POSTGRES_TEST_URL not set — real-PG read integration tests skipped. "
        "Set the env var to a SQLAlchemy async URL pointing at an "
        "alembic-upgraded-head Postgres instance to run this module.",
        allow_module_level=True,
    )


from api.tables import codenames_table, groups_table  # noqa: E402


ACTORS_URL = "/api/v1/actors"


# ---------------------------------------------------------------------------
# Engine / session fixtures — module-scope engine for speed.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_PG_URL, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_sessionmaker(
    pg_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def pg_session(
    pg_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with pg_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def clean_pg(pg_engine: AsyncEngine) -> None:
    """Truncate the read-surface tables between tests.

    CASCADE covers codenames → groups FK. RESTART IDENTITY keeps
    test-local ids deterministic so assertions on ``id`` do not
    drift across runs.
    """
    async with pg_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "TRUNCATE codenames, groups "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def read_client(
    pg_sessionmaker: async_sessionmaker[AsyncSession],
    session_store,
    fake_redis,
) -> AsyncIterator[AsyncClient]:
    """ASGI client with ``get_db`` overridden to yield real-PG
    sessions. Matches the PR #10 ``review_client`` fixture pattern."""
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with pg_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_groups(session: AsyncSession, groups: list[dict]) -> list[int]:
    ids: list[int] = []
    for g in groups:
        result = await session.execute(
            sa.insert(groups_table).values(**g).returning(groups_table.c.id)
        )
        ids.append(result.scalar_one())
    await session.commit()
    return ids


async def _seed_codenames(session: AsyncSession, codenames: list[dict]) -> None:
    for c in codenames:
        await session.execute(sa.insert(codenames_table).values(**c))
    await session.commit()


async def _analyst_cookie(make_session_cookie) -> str:
    return await make_session_cookie(roles=["analyst"])


# ---------------------------------------------------------------------------
# Scenario 1 — /actors normal response (plan §5.2)
# ---------------------------------------------------------------------------


async def test_scenario_1_actors_list_and_default_sort(
    read_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 1 for read surface — 3 groups + codenames
    seeded, `/actors` returns items sorted ``name ASC`` (D11), total
    reflects the full count, codenames flatten per group.

    PG-specific invariants covered here that sqlite cannot:
    - ``array_agg`` codename aggregation returns Python list via
      psycopg's native array decoding (no ``group_concat`` comma
      splitting).
    - ``aka`` column round-trips as an actual ARRAY type.
    """
    group_ids = await _seed_groups(
        pg_session,
        [
            # Seed in non-alphabetical order so the ORDER BY proof
            # is meaningful.
            {"name": "Lazarus Group", "mitre_intrusion_set_id": "G0032", "aka": ["APT38", "Hidden Cobra"]},
            {"name": "Andariel", "mitre_intrusion_set_id": "G0138", "aka": []},
            {"name": "Kimsuky", "mitre_intrusion_set_id": "G0094", "aka": ["Velvet Chollima"]},
        ],
    )
    await _seed_codenames(
        pg_session,
        [
            {"name": "Bluenoroff", "group_id": group_ids[0]},
            # Andariel (group_ids[1]) has no codenames — empty list case.
            {"name": "Thallium", "group_id": group_ids[2]},
        ],
    )

    cookie = await _analyst_cookie(make_session_cookie)
    resp = await read_client.get(ACTORS_URL, cookies={"dprk_cti_session": cookie})

    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] == 3

    # Default sort name ASC — plan D11.
    names = [item["name"] for item in body["items"]]
    assert names == ["Andariel", "Kimsuky", "Lazarus Group"]

    # Codenames aggregated via array_agg — real list, not comma string.
    items_by_name = {item["name"]: item for item in body["items"]}
    assert items_by_name["Andariel"]["codenames"] == []
    assert items_by_name["Kimsuky"]["codenames"] == ["Thallium"]
    assert items_by_name["Lazarus Group"]["codenames"] == ["Bluenoroff"]

    # aka round-trips as an actual array — PG ARRAY not sqlite JSON.
    assert items_by_name["Lazarus Group"]["aka"] == ["APT38", "Hidden Cobra"]
    assert items_by_name["Andariel"]["aka"] == []
