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


from api.tables import (  # noqa: E402
    codenames_table,
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
)


ACTORS_URL = "/api/v1/actors"
REPORTS_URL = "/api/v1/reports"
INCIDENTS_URL = "/api/v1/incidents"


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

    CASCADE covers the FK chain (report_tags → reports,
    codenames → groups). RESTART IDENTITY keeps test-local ids
    deterministic so assertions on ``id`` do not drift across runs.
    """
    async with pg_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "TRUNCATE report_tags, reports, tags, sources, "
                "codenames, groups, "
                "incident_motivations, incident_sectors, "
                "incident_countries, incidents "
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


async def _seed_source(session: AsyncSession, name: str) -> int:
    result = await session.execute(
        sa.insert(sources_table)
        .values(name=name, type="vendor")
        .returning(sources_table.c.id)
    )
    src_id = result.scalar_one()
    await session.commit()
    return src_id


async def _seed_tag(session: AsyncSession, name: str) -> int:
    result = await session.execute(
        sa.insert(tags_table)
        .values(name=name, type="actor")
        .returning(tags_table.c.id)
    )
    tag_id = result.scalar_one()
    await session.commit()
    return tag_id


async def _seed_report(
    session: AsyncSession,
    *,
    title: str,
    url: str,
    source_id: int,
    published,
    tag_ids: list[int] | None = None,
) -> int:
    result = await session.execute(
        sa.insert(reports_table)
        .values(
            title=title,
            url=url,
            url_canonical=url,
            sha256_title=f"sha-{title[:16]}",
            source_id=source_id,
            published=published,
        )
        .returning(reports_table.c.id)
    )
    rid = result.scalar_one()
    if tag_ids:
        for tid in tag_ids:
            await session.execute(
                sa.insert(report_tags_table).values(report_id=rid, tag_id=tid)
            )
    await session.commit()
    return rid


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


# ---------------------------------------------------------------------------
# Scenario 2 — /reports filter combinations + JOIN dedup (plan §5.2)
# ---------------------------------------------------------------------------


import datetime as _dt  # noqa: E402 — scoped usage below


async def test_scenario_2_reports_filters_and_join_dedup(
    read_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 2. Exercises the invariants that sqlite
    cannot fully prove:

    - ``ILIKE`` is case-insensitive across all characters on PG
      (sqlite's LIKE is case-insensitive only on ASCII by default
      and diverges on non-ASCII).
    - EXISTS-based tag filter keeps row count invariant when a
      report carries MULTIPLE matching tags (would multiply rows
      under a naive INNER JOIN).
    - ``?tag=a&tag=b`` OR semantics inside a repeatable + ``?tag=a&
      source=X`` AND semantics across distinct filters, on a real
      PG planner.
    """
    src_a = await _seed_source(pg_session, "src-A")
    src_b = await _seed_source(pg_session, "src-B")
    tag_rans = await _seed_tag(pg_session, "ransomware")
    tag_esp = await _seed_tag(pg_session, "espionage")

    # r_both carries BOTH tags + src_A → the dedup-regression case.
    r_both = await _seed_report(
        pg_session,
        title="LAZARUS Finance Playbook",  # uppercase for ILIKE case test
        url="https://ex/both",
        source_id=src_a,
        published=_dt.date(2026, 3, 15),
        tag_ids=[tag_rans, tag_esp],
    )
    r_rans = await _seed_report(
        pg_session,
        title="ransomware operator activity",
        url="https://ex/rans",
        source_id=src_a,
        published=_dt.date(2026, 3, 14),
        tag_ids=[tag_rans],
    )
    r_esp = await _seed_report(
        pg_session,
        title="spy operation update",
        url="https://ex/esp",
        source_id=src_b,
        published=_dt.date(2026, 3, 13),
        tag_ids=[tag_esp],
    )

    cookie = await _analyst_cookie(make_session_cookie)

    # Dedup: r_both carries both tags; ?tag=ransomware&tag=espionage
    # must still return it ONCE.
    resp = await read_client.get(
        f"{REPORTS_URL}?tag=ransomware&tag=espionage",
        cookies={"dprk_cti_session": cookie},
    )
    assert resp.status_code == 200
    ids = [it["id"] for it in resp.json()["items"]]
    assert ids.count(r_both) == 1, "EXISTS must not multiply rows"
    assert set(ids) == {r_both, r_rans, r_esp}

    # AND across filters — tag=ransomware + source=src-A drops r_esp.
    resp = await read_client.get(
        f"{REPORTS_URL}?tag=ransomware&source=src-A",
        cookies={"dprk_cti_session": cookie},
    )
    ids = {it["id"] for it in resp.json()["items"]}
    assert ids == {r_both, r_rans}

    # ILIKE case-insensitive on PG — uppercase seed matches lowercase query.
    resp = await read_client.get(
        f"{REPORTS_URL}?q=lazarus", cookies={"dprk_cti_session": cookie}
    )
    titles = [it["title"] for it in resp.json()["items"]]
    assert titles == ["LAZARUS Finance Playbook"]

    # Default sort published DESC + tie-break id DESC — r_both is newest,
    # then r_rans, then r_esp.
    resp = await read_client.get(REPORTS_URL, cookies={"dprk_cti_session": cookie})
    id_order = [it["id"] for it in resp.json()["items"]]
    assert id_order == [r_both, r_rans, r_esp]


# ---------------------------------------------------------------------------
# Scenario 3 — /incidents multi-country + aggregate dedup (plan §5.2)
# ---------------------------------------------------------------------------


async def _seed_incident_pg(
    session: AsyncSession,
    *,
    title: str,
    reported: _dt.date | None,
    motivations: list[str] | None = None,
    sectors: list[str] | None = None,
    countries: list[str] | None = None,
) -> int:
    result = await session.execute(
        sa.insert(incidents_table)
        .values(title=title, reported=reported)
        .returning(incidents_table.c.id)
    )
    iid = result.scalar_one()
    for m in motivations or []:
        await session.execute(
            sa.insert(incident_motivations_table).values(
                incident_id=iid, motivation=m
            )
        )
    for sec in sectors or []:
        await session.execute(
            sa.insert(incident_sectors_table).values(
                incident_id=iid, sector_code=sec
            )
        )
    for c in countries or []:
        await session.execute(
            sa.insert(incident_countries_table).values(
                incident_id=iid, country_iso2=c
            )
        )
    await session.commit()
    return iid


async def test_scenario_3_incidents_multi_country_and_dedup(
    read_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 3. Exercises what sqlite cannot:

    - PG ``array_agg`` aggregate across the correlated scalar
      subquery pattern — proves the subquery returns a Python list,
      not a comma string (sqlite fallback).
    - Multi-country OR semantics under the real PG planner:
      ``?country=KR&country=US`` unions two sets, de-duped by the
      incident primary key (outer row count stays one).
    - Correlated subquery pattern does NOT Cartesian-multiply when
      an incident has multiple rows on all three join tables.
    """
    i_kr = await _seed_incident_pg(
        pg_session,
        title="KR incident",
        reported=_dt.date(2024, 5, 2),
        motivations=["financial"],
        countries=["KR"],
    )
    i_us = await _seed_incident_pg(
        pg_session,
        title="US incident",
        reported=_dt.date(2024, 3, 15),
        motivations=["espionage"],
        countries=["US"],
    )
    i_jp = await _seed_incident_pg(
        pg_session,
        title="JP incident",
        reported=_dt.date(2024, 1, 1),
        motivations=["disruption"],
        countries=["JP"],
    )
    i_multi = await _seed_incident_pg(
        pg_session,
        title="Multi-row incident",
        reported=_dt.date(2024, 6, 1),
        motivations=["financial", "espionage"],
        sectors=["crypto", "gov", "finance"],
        countries=["KR", "US"],
    )

    cookie = await _analyst_cookie(make_session_cookie)

    # Multi-country OR — KR and US both included; JP excluded. i_multi
    # (KR+US) appears exactly once despite matching BOTH countries —
    # the dedup invariant.
    resp = await read_client.get(
        f"{INCIDENTS_URL}?country=KR&country=US",
        cookies={"dprk_cti_session": cookie},
    )
    assert resp.status_code == 200
    ids = [it["id"] for it in resp.json()["items"]]
    assert ids.count(i_multi) == 1
    assert set(ids) == {i_kr, i_us, i_multi}

    # Aggregated arrays on PG use array_agg → real Python lists,
    # sorted alphabetically by _normalize_aggregate.
    items_by_id = {it["id"]: it for it in resp.json()["items"]}
    assert items_by_id[i_multi]["motivations"] == ["espionage", "financial"]
    assert items_by_id[i_multi]["sectors"] == ["crypto", "finance", "gov"]
    assert items_by_id[i_multi]["countries"] == ["KR", "US"]

    # AND across filters: motivation=financial + country=KR
    # matches i_kr (financial+KR) AND i_multi (financial+KR) — but
    # NOT i_us (espionage) and NOT i_jp (disruption).
    resp = await read_client.get(
        f"{INCIDENTS_URL}?motivation=financial&country=KR",
        cookies={"dprk_cti_session": cookie},
    )
    got = {it["id"] for it in resp.json()["items"]}
    assert got == {i_kr, i_multi}
