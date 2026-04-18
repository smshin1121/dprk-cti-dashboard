"""Real-PostgreSQL integration tests for PR #11 read endpoints.

Plan §5.2 locks 8 scenarios as the Group K acceptance gate. All 8
are in this module to match the plan 1:1 and keep the acceptance
surface consolidated — even the ones that don't strictly require
PG (rate-limit, invalid-filter 422, OpenAPI examples) live here so
a reviewer can audit §5.2 compliance in one file.

Scenario-to-function map (plan §5.2):

- Scenario 1 → ``test_scenario_1_actors_list_and_default_sort``
- Scenario 2 → ``test_scenario_2_reports_filters_and_join_dedup``
- Scenario 3 → ``test_scenario_3_incidents_multi_country_and_dedup``
- Scenario 4 → ``test_scenario_4_dashboard_summary_totals_and_top_groups``
- Scenario 5 → ``test_scenario_5_keyset_cursor_stability_under_insert``
- Scenario 6 → ``test_scenario_6_rate_limit_429_and_headers``
- Scenario 7 → ``test_scenario_7_invalid_filter_returns_422_uniform``
- Scenario 8 → ``test_scenario_8_openapi_examples_d13_populated``

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
    report_codenames_table,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
)


ACTORS_URL = "/api/v1/actors"
REPORTS_URL = "/api/v1/reports"
INCIDENTS_URL = "/api/v1/incidents"
DASHBOARD_URL = "/api/v1/dashboard/summary"


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
                "TRUNCATE report_tags, report_codenames, reports, tags, "
                "sources, codenames, groups, "
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


# ---------------------------------------------------------------------------
# Scenario 4 — /dashboard/summary on real PG (plan §5.2)
# ---------------------------------------------------------------------------


async def test_scenario_4_dashboard_summary_totals_and_top_groups(
    read_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 4. PG-specific invariants:

    - ``EXTRACT(YEAR FROM published)`` returns a numeric (not the
      sqlite ``strftime`` string) — the aggregator's ``CAST ... AS
      INTEGER`` must still yield a clean int.
    - ``top_groups`` multi-join chain (groups ← codenames ←
      report_codenames ← reports) collapses to one row per group
      under PG's ``COUNT(DISTINCT report_id)``, including the case
      where one report has two codenames in the same group.
    """
    src = await _seed_source(pg_session, "src-a")
    g_laz = (
        await pg_session.execute(
            sa.insert(groups_table)
            .values(name="Lazarus Group")
            .returning(groups_table.c.id)
        )
    ).scalar_one()
    g_kim = (
        await pg_session.execute(
            sa.insert(groups_table).values(name="Kimsuky").returning(groups_table.c.id)
        )
    ).scalar_one()
    await pg_session.commit()

    c_laz_1 = (
        await pg_session.execute(
            sa.insert(codenames_table)
            .values(name="Bluenoroff", group_id=g_laz)
            .returning(codenames_table.c.id)
        )
    ).scalar_one()
    c_laz_2 = (
        await pg_session.execute(
            sa.insert(codenames_table)
            .values(name="Andariel-cn", group_id=g_laz)
            .returning(codenames_table.c.id)
        )
    ).scalar_one()
    c_kim = (
        await pg_session.execute(
            sa.insert(codenames_table)
            .values(name="Velvet Chollima", group_id=g_kim)
            .returning(codenames_table.c.id)
        )
    ).scalar_one()
    await pg_session.commit()

    # Three reports across two years; r_dual has TWO codenames in the
    # SAME Lazarus group so dedup via COUNT(DISTINCT report_id) must
    # count it as 1 toward Lazarus.
    async def _add_report(title: str, published, codename_ids):
        rid = (
            await pg_session.execute(
                sa.insert(reports_table)
                .values(
                    title=title,
                    url=f"https://ex/{title}",
                    url_canonical=f"https://ex/{title}",
                    sha256_title=f"sha-{title}",
                    source_id=src,
                    published=published,
                )
                .returning(reports_table.c.id)
            )
        ).scalar_one()
        for cid in codename_ids:
            await pg_session.execute(
                sa.insert(report_codenames_table).values(
                    report_id=rid, codename_id=cid
                )
            )
        await pg_session.commit()
        return rid

    await _add_report("r-dual", _dt.date(2024, 3, 1), [c_laz_1, c_laz_2])
    await _add_report("r-laz2", _dt.date(2024, 6, 1), [c_laz_1])
    await _add_report("r-kim", _dt.date(2023, 2, 1), [c_kim])

    # Incidents: two financial, one espionage (year 2024).
    for m in ["financial", "espionage"]:
        iid = (
            await pg_session.execute(
                sa.insert(incidents_table)
                .values(title=f"inc-{m}", reported=_dt.date(2024, 1, 1))
                .returning(incidents_table.c.id)
            )
        ).scalar_one()
        await pg_session.execute(
            sa.insert(incident_motivations_table).values(
                incident_id=iid, motivation=m
            )
        )
    iid = (
        await pg_session.execute(
            sa.insert(incidents_table)
            .values(title="inc-fin-2", reported=_dt.date(2024, 1, 1))
            .returning(incidents_table.c.id)
        )
    ).scalar_one()
    await pg_session.execute(
        sa.insert(incident_motivations_table).values(
            incident_id=iid, motivation="financial"
        )
    )
    await pg_session.commit()

    cookie = await _analyst_cookie(make_session_cookie)
    resp = await read_client.get(DASHBOARD_URL, cookies={"dprk_cti_session": cookie})

    assert resp.status_code == 200
    body = resp.json()

    # Totals reflect row counts.
    assert body["total_reports"] == 3
    assert body["total_incidents"] == 3
    assert body["total_actors"] == 2

    # PG EXTRACT(YEAR) returns numeric → CAST to int; 2024 has 2 reports,
    # 2023 has 1 report. DESC order.
    assert body["reports_by_year"] == [
        {"year": 2024, "count": 2},
        {"year": 2023, "count": 1},
    ]

    # Motivations alphabetized; espionage=1, financial=2.
    assert body["incidents_by_motivation"] == [
        {"motivation": "espionage", "count": 1},
        {"motivation": "financial", "count": 2},
    ]

    # top_groups: Lazarus has r_dual + r_laz2 = 2 distinct reports.
    # r_dual has two codenames in Lazarus but COUNT(DISTINCT id) = 1.
    # Kimsuky has r_kim = 1 report.
    top = body["top_groups"]
    assert len(top) == 2
    assert top[0]["name"] == "Lazarus Group"
    assert top[0]["report_count"] == 2  # not 3 (dedup proof)
    assert top[1]["name"] == "Kimsuky"
    assert top[1]["report_count"] == 1


# ---------------------------------------------------------------------------
# Scenario 5 — Keyset cursor stability under concurrent insert (plan §5.2)
# ---------------------------------------------------------------------------


async def test_scenario_5_keyset_cursor_stability_under_insert(
    read_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 5 — "동시 insert 중 next_cursor 로 페이지 넘겨도
    중복 없음 + cursor tiebreak (id DESC) 효과 검증".

    Keyset cursor `(published_at DESC, id DESC)` vs offset:

    - **Stability under insert:** after fetching page 1 with limit=3,
      inserting rows at published_at positions BEFORE the page-1
      last cursor AND AFTER it. Page 2 via next_cursor returns only
      rows that existed at page-1 time, AND only those strictly
      `<(published_at, id)` than the page-1 last item — so the
      late-inserted rows at higher dates don't shift page boundaries,
      and rows at the same date use id tiebreak rather than
      appearing twice.
    - **Tiebreak proof:** seed multiple rows at the SAME published_at
      date with distinct ids. The cursor composite (date, id) drops
      ambiguity; without the id tiebreak the page boundary would be
      either all-or-nothing for rows sharing that date.

    sqlite can't be trusted for concurrent-insert semantics — it
    serializes write transactions. PG with real psycopg_async is
    the only place this scenario is meaningful.
    """
    src = await _seed_source(pg_session, "src-cursor")

    # Seed 6 reports at distinct dates, including two sharing
    # 2026-03-13 so the id-tiebreak half of the scenario has teeth.
    seed_plan = [
        ("r-a", _dt.date(2026, 3, 20)),  # newest — page 1 position 1
        ("r-b", _dt.date(2026, 3, 18)),  # page 1 position 2
        ("r-c", _dt.date(2026, 3, 15)),  # page 1 position 3 — last
        ("r-d", _dt.date(2026, 3, 13)),  # page 2 position 1 (same date)
        ("r-e", _dt.date(2026, 3, 13)),  # page 2 position 2 (same date, id tiebreak)
        ("r-f", _dt.date(2026, 3, 10)),  # page 2 position 3 — oldest
    ]
    seeded_ids: dict[str, int] = {}
    for title, date in seed_plan:
        seeded_ids[title] = await _seed_report(
            pg_session,
            title=title,
            url=f"https://ex/{title}",
            source_id=src,
            published=date,
        )

    cookie = await _analyst_cookie(make_session_cookie)

    # Page 1 — limit 3. Expect the newest three: r-a, r-b, r-c.
    p1 = await read_client.get(
        f"{REPORTS_URL}?limit=3", cookies={"dprk_cti_session": cookie}
    )
    assert p1.status_code == 200
    p1_body = p1.json()
    p1_ids = [it["id"] for it in p1_body["items"]]
    assert p1_ids == [seeded_ids["r-a"], seeded_ids["r-b"], seeded_ids["r-c"]]
    assert p1_body["next_cursor"] is not None

    # Concurrent insert simulation: commit new rows BEFORE reading
    # page 2 via the cursor. One row at a date newer than page 1
    # (would crash into page 2 under offset pagination), one at a
    # date older than the cursor (always below the fold anyway).
    late_new = await _seed_report(
        pg_session,
        title="r-late-new",
        url="https://ex/late-new",
        source_id=src,
        published=_dt.date(2026, 3, 25),
    )
    late_old = await _seed_report(
        pg_session,
        title="r-late-old",
        url="https://ex/late-old",
        source_id=src,
        published=_dt.date(2026, 3, 5),
    )

    # Page 2 via the cursor. Must return:
    # - r-d and r-e (same date 2026-03-13, id tiebreak DESC order)
    # - r-f (oldest pre-insert)
    # - r-late-old (new but older than cursor → included)
    # Must NOT include:
    # - r-late-new (newer than cursor → filtered by keyset)
    # - r-a/r-b/r-c (already returned on page 1 — no dup)
    p2 = await read_client.get(
        f"{REPORTS_URL}?limit=10&cursor={p1_body['next_cursor']}",
        cookies={"dprk_cti_session": cookie},
    )
    assert p2.status_code == 200
    p2_ids = [it["id"] for it in p2.json()["items"]]

    # No duplicates across pages — the core stability invariant.
    assert set(p1_ids).isdisjoint(set(p2_ids))

    # Late-inserted row at NEWER date must NOT leak into page 2.
    assert late_new not in p2_ids

    # Late-inserted row at OLDER date shows up below the cursor.
    assert late_old in p2_ids

    # Tiebreak order proof: the two rows sharing 2026-03-13 appear
    # in id-DESC order (newer insert first). r-e was inserted after
    # r-d so r-e.id > r-d.id → r-e first.
    r_d = seeded_ids["r-d"]
    r_e = seeded_ids["r-e"]
    assert r_e > r_d, "fixture assumption — ids monotonically increase"
    p2_idx = {iid: idx for idx, iid in enumerate(p2_ids)}
    assert p2_idx[r_e] < p2_idx[r_d], (
        "id tiebreak DESC failed — r-e (higher id) should precede r-d"
    )


# ---------------------------------------------------------------------------
# Scenario 6 — Rate-limit 429 + headers on real-PG stack (plan §5.2)
# ---------------------------------------------------------------------------


async def test_scenario_6_rate_limit_429_and_headers(
    read_client: AsyncClient,
    make_session_cookie,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 6 — "60/min/route 초과 시 429 + Retry-After +
    X-RateLimit-Remaining. /auth/login 10/min 경계도 별도 케이스로 검증
    (IP 기반). Per-route 독립 버킷 pin".

    Re-runs the boundary + IP-bucket + per-route scoping checks
    through the real-PG client fixture so the switch from
    sqlite-aiosqlite to psycopg_async driver doesn't perturb the
    rate-limit middleware path. The slowapi storage stays
    ``memory://`` (conftest forces it) regardless of DB backend,
    but the decorator wrapping still runs on real requests and
    this test is the guard against a future decorator/driver
    interaction that breaks only on PG.
    """
    cookie = await _analyst_cookie(make_session_cookie)

    # 60/min/route boundary on /reports (read bucket).
    for i in range(60):
        resp = await read_client.get(
            REPORTS_URL, cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200, (
            f"request {i} should pass under real-PG path"
        )

    over = await read_client.get(
        REPORTS_URL, cookies={"dprk_cti_session": cookie}
    )
    assert over.status_code == 429
    body = over.json()
    assert body == {"error": "rate_limit_exceeded", "message": "60 per 1 minute"}

    # Headers pin — plan D2.
    assert int(over.headers["Retry-After"]) >= 1
    assert int(over.headers["X-RateLimit-Limit"]) == 60
    assert int(over.headers["X-RateLimit-Remaining"]) == 0

    # Per-route bucket scope on real-PG: /incidents is a separate
    # bucket for the same cookie — fresh 200 even though /reports
    # is exhausted.
    fresh = await read_client.get(
        INCIDENTS_URL, cookies={"dprk_cti_session": cookie}
    )
    assert fresh.status_code == 200

    # /auth/login IP bucket — 10/min. No cookie → key_func falls to
    # IP bucket. 11th call 429 without consulting PG at all (auth
    # endpoints don't touch the DB until after rate check).
    for _ in range(10):
        resp = await read_client.get("/api/v1/auth/login")
        # 302/307 on success (redirect to keycloak stub) — both acceptable.
        assert resp.status_code in (302, 307, 500), (
            f"/auth/login unexpected status {resp.status_code}"
        )

    over_login = await read_client.get("/api/v1/auth/login")
    assert over_login.status_code == 429


# ---------------------------------------------------------------------------
# Scenario 7 — Invalid filter → 422 uniform (plan §5.2 / D12)
# ---------------------------------------------------------------------------


async def test_scenario_7_invalid_filter_returns_422_uniform(
    read_client: AsyncClient,
    make_session_cookie,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 7 — "빈 tag, invalid date, invalid country
    code, limit=0, limit=201, malformed cursor 각각 422 + FastAPI
    HTTPValidationError shape".

    All 6 invalid inputs must short-circuit to 422 BEFORE touching
    PG. The empty real-PG fixture acts as the witness: if any
    case accidentally ran the query, the response would be 200
    with an empty list — so any non-422 here is a D12 regression.

    Response body shape uniformity: all must carry a ``detail``
    array of validation-error dicts (FastAPI's
    ``HTTPValidationError``). The error handler's
    ``malformed_cursor`` branch in routers/reports.py hand-crafts
    the same ``detail[].loc/msg/type`` shape so clients branch on
    one 422 schema regardless of source.
    """
    cookie = await _analyst_cookie(make_session_cookie)

    invalid_cases: list[tuple[str, str]] = [
        ("empty tag value", f"{REPORTS_URL}?tag="),
        ("invalid ISO date", f"{REPORTS_URL}?date_from=not-a-date"),
        ("non-alpha-2 country", f"{INCIDENTS_URL}?country=korea"),
        ("limit=0 below min", f"{ACTORS_URL}?limit=0"),
        ("limit=201 above max", f"{ACTORS_URL}?limit=201"),
        ("malformed cursor", f"{REPORTS_URL}?cursor=!!!invalid!!!"),
    ]

    for label, url in invalid_cases:
        resp = await read_client.get(url, cookies={"dprk_cti_session": cookie})
        assert resp.status_code == 422, f"{label}: {resp.status_code} ({url})"
        body = resp.json()
        assert "detail" in body, f"{label}: missing 'detail' key"
        assert isinstance(body["detail"], list), (
            f"{label}: 'detail' must be a list"
        )
        assert body["detail"], f"{label}: 'detail' must be non-empty"
        # FastAPI HTTPValidationError uniform shape — every entry has
        # loc/msg/type. Reports' malformed-cursor hand-crafted path
        # mirrors this exactly so the client contract is one-schema.
        for entry in body["detail"]:
            assert "loc" in entry, f"{label}: detail entry missing 'loc'"
            assert "msg" in entry, f"{label}: detail entry missing 'msg'"
            assert "type" in entry, f"{label}: detail entry missing 'type'"


# ---------------------------------------------------------------------------
# Scenario 8 — OpenAPI surface + examples D13 populated (plan §5.2)
# ---------------------------------------------------------------------------


async def test_scenario_8_openapi_examples_d13_populated() -> None:
    """Plan §5.2 scenario 8 — "5개 endpoint + DTO 가 /openapi.json 에
    존재 + 각 endpoint 의 response examples (happy/429/422/empty) 4종
    populate".

    Acceptance for D13 lock. Assertions:

    1. 5 read endpoints present in spec.
    2. Each of the 4 list endpoints carries response examples for
       200 (multi-example: happy + empty/last_page), 429 (single
       example with rate_limit_exceeded body), 422 (single example
       with FastAPI HTTPValidationError detail shape).
    3. /auth/me has 200 example (CurrentUser DTO) + 429 example.
       No 422 — endpoint has no query params or body, FastAPI
       wouldn't emit one and D13 filter-example set doesn't apply.

    No DB — pure schema assertion. Lives in this file to keep
    §5.2 1:1 consolidation (plan Group K reviewer ask: all 8
    scenarios in one place for audit ease).
    """
    from api.main import app

    spec = app.openapi()
    paths = spec["paths"]

    # (1) surface presence
    required_paths = [
        "/api/v1/actors",
        "/api/v1/reports",
        "/api/v1/incidents",
        "/api/v1/dashboard/summary",
        "/api/v1/auth/me",
    ]
    for p in required_paths:
        assert p in paths, f"OpenAPI missing path: {p}"

    # (2) list-endpoint example coverage (happy/429/422, + empty via
    # the 200 multi-example set).
    list_endpoints = required_paths[:4]
    for p in list_endpoints:
        responses = paths[p]["get"]["responses"]

        # 200 — multi-example (happy + empty or last_page).
        ok_json = responses["200"]["content"]["application/json"]
        assert "examples" in ok_json, f"{p} 200: missing multi 'examples'"
        assert len(ok_json["examples"]) >= 2, (
            f"{p} 200: D13 requires both happy + empty/last_page examples"
        )

        # 429 — single example, rate_limit_exceeded body.
        r429 = responses["429"]["content"]["application/json"]
        assert "example" in r429, f"{p} 429: missing example"
        assert r429["example"]["error"] == "rate_limit_exceeded", (
            f"{p} 429 example wrong 'error' field"
        )

        # 422 — FastAPI HTTPValidationError shape.
        r422 = responses["422"]["content"]["application/json"]
        assert "example" in r422, f"{p} 422: missing example (D13 requires)"
        example422 = r422["example"]
        assert "detail" in example422 and isinstance(
            example422["detail"], list
        ), f"{p} 422 example must carry a 'detail' list"
        assert example422["detail"], f"{p} 422 example 'detail' must be non-empty"
        entry = example422["detail"][0]
        for field in ("loc", "msg", "type"):
            assert field in entry, f"{p} 422 example missing detail.{field}"

    # (3) /auth/me — DTO and rate-limit examples, no 422 (no filter set).
    me_responses = paths["/api/v1/auth/me"]["get"]["responses"]
    me_200 = me_responses["200"]["content"]["application/json"]
    assert "example" in me_200, "/auth/me 200 missing CurrentUser example"
    for field in ("sub", "email", "roles"):
        assert field in me_200["example"], (
            f"/auth/me 200 example missing CurrentUser.{field}"
        )
    me_429 = me_responses["429"]["content"]["application/json"]
    assert me_429["example"]["error"] == "rate_limit_exceeded"
