"""Integration tests for GET /api/v1/dashboard/summary (PR #11 Group E).

Runs on in-memory aiosqlite via dependency override. Real-PG
scenario 4 in ``test_read_real_pg.py`` covers PG-specific EXTRACT
behavior and the top_groups JOIN chain under the PG planner.

Review checklist from the Group E lock:

1. ``total_*`` exactly match the row counts a plain ``COUNT(*)``
   would return under the same filter predicate. No inflation from
   joins.
2. Three aggregate arrays (``reports_by_year`` / ``incidents_by_
   motivation`` / ``top_groups``) match plan D6 shape verbatim.
3. ``top_n`` is bounded at 1..20 by the router Query layer; max
   boundary is asserted with ``top_n=21`` → 422.
4. Aggregation queries do not inflate counts:
   - ``incidents_by_motivation`` dedupes per incident_id
   - ``top_groups`` dedupes per report_id
5. Empty DB returns zero totals and empty arrays without shape drift.
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

from api.tables import (
    codenames_table,
    groups_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    metadata,
    report_codenames_table,
    reports_table,
    sources_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def dashboard_client(
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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_source(engine: AsyncEngine, name: str) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        src_id = result.scalar_one()
        await s.commit()
        return src_id


async def _seed_group(engine: AsyncEngine, name: str) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(groups_table).values(name=name).returning(groups_table.c.id)
        )
        gid = result.scalar_one()
        await s.commit()
        return gid


async def _seed_codename(engine: AsyncEngine, name: str, group_id: int) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(codenames_table)
            .values(name=name, group_id=group_id)
            .returning(codenames_table.c.id)
        )
        cid = result.scalar_one()
        await s.commit()
        return cid


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    url: str,
    source_id: int,
    published: dt.date,
    codename_ids: list[int] | None = None,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
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
        for cid in codename_ids or []:
            await s.execute(
                sa.insert(report_codenames_table).values(
                    report_id=rid, codename_id=cid
                )
            )
        await s.commit()
        return rid


async def _seed_incident(
    engine: AsyncEngine,
    *,
    title: str,
    reported: dt.date,
    motivations: list[str] | None = None,
    sectors: list[str] | None = None,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(incidents_table)
            .values(title=title, reported=reported)
            .returning(incidents_table.c.id)
        )
        iid = result.scalar_one()
        for m in motivations or []:
            await s.execute(
                sa.insert(incident_motivations_table).values(
                    incident_id=iid, motivation=m
                )
            )
        for sc in sectors or []:
            await s.execute(
                sa.insert(incident_sectors_table).values(
                    incident_id=iid, sector_code=sc
                )
            )
        await s.commit()
        return iid


async def _cookie(make_session_cookie, *, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# Review priority #5 — empty DB zero/empty shape
# ---------------------------------------------------------------------------


class TestEmptyDB:
    async def test_empty_db_returns_zeros_and_empty_arrays(
        self, dashboard_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "total_reports": 0,
            "total_incidents": 0,
            "total_actors": 0,
            "reports_by_year": [],
            "incidents_by_motivation": [],
            "top_groups": [],
            "top_sectors": [],
            "top_sources": [],
        }


# ---------------------------------------------------------------------------
# Review priority #1 — total_* exactness
# ---------------------------------------------------------------------------


class TestTotalsExact:
    async def test_totals_match_row_counts(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        for i in range(3):
            await _seed_report(
                real_engine,
                title=f"r-{i}",
                url=f"https://ex/{i}",
                source_id=src,
                published=dt.date(2024, 1, 1),
            )
        for i in range(2):
            await _seed_incident(
                real_engine, title=f"inc-{i}", reported=dt.date(2024, 1, 1)
            )
        for i in range(4):
            await _seed_group(real_engine, f"group-{i}")

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        body = resp.json()
        assert body["total_reports"] == 3
        assert body["total_incidents"] == 2
        assert body["total_actors"] == 4

    async def test_date_filter_narrows_totals_but_not_actors(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        await _seed_report(
            real_engine,
            title="in range",
            url="https://ex/1",
            source_id=src,
            published=dt.date(2024, 3, 15),
        )
        await _seed_report(
            real_engine,
            title="out range",
            url="https://ex/2",
            source_id=src,
            published=dt.date(2022, 1, 1),
        )
        await _seed_incident(real_engine, title="in", reported=dt.date(2024, 3, 15))
        await _seed_incident(real_engine, title="out", reported=dt.date(2022, 1, 1))
        await _seed_group(real_engine, "g-always")

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary?date_from=2024-01-01&date_to=2024-12-31",
            cookies={"dprk_cti_session": cookie},
        )
        body = resp.json()
        assert body["total_reports"] == 1  # date-filtered
        assert body["total_incidents"] == 1  # date-filtered
        assert body["total_actors"] == 1  # NOT date-filtered — inventory


# ---------------------------------------------------------------------------
# Review priority #2 — aggregate shapes
# ---------------------------------------------------------------------------


class TestReportsByYear:
    async def test_groups_and_sorts_by_year_desc(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        for d in [
            dt.date(2024, 1, 1),
            dt.date(2024, 6, 1),  # two 2024
            dt.date(2023, 3, 1),
        ]:
            await _seed_report(
                real_engine,
                title=f"r-{d}",
                url=f"https://ex/{d}",
                source_id=src,
                published=d,
            )
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        assert resp.json()["reports_by_year"] == [
            {"year": 2024, "count": 2},
            {"year": 2023, "count": 1},
        ]


class TestIncidentsByMotivation:
    async def test_incident_with_two_motivations_contributes_to_each(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """One incident with motivations=[financial, espionage] adds
        +1 to financial AND +1 to espionage — the natural "incidents
        by motivation" reading."""
        await _seed_incident(
            real_engine,
            title="dual",
            reported=dt.date(2024, 1, 1),
            motivations=["financial", "espionage"],
        )
        await _seed_incident(
            real_engine,
            title="single",
            reported=dt.date(2024, 1, 1),
            motivations=["financial"],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        # Sorted alphabetically; counts: espionage=1, financial=2.
        assert resp.json()["incidents_by_motivation"] == [
            {"motivation": "espionage", "count": 1},
            {"motivation": "financial", "count": 2},
        ]


class TestTopGroups:
    async def _setup(self, engine: AsyncEngine) -> dict[str, int]:
        src = await _seed_source(engine, "src-a")
        g_laz = await _seed_group(engine, "Lazarus Group")
        g_kim = await _seed_group(engine, "Kimsuky")
        g_and = await _seed_group(engine, "Andariel")

        c_laz = await _seed_codename(engine, "Bluenoroff", g_laz)
        c_kim = await _seed_codename(engine, "Velvet Chollima", g_kim)
        # Andariel has no codename / no reports → should not appear in top.

        # 3 reports attributed to Lazarus, 1 to Kimsuky, 0 to Andariel.
        for i in range(3):
            await _seed_report(
                engine,
                title=f"laz-{i}",
                url=f"https://ex/laz-{i}",
                source_id=src,
                published=dt.date(2024, 1, 1),
                codename_ids=[c_laz],
            )
        await _seed_report(
            engine,
            title="kim-0",
            url="https://ex/kim-0",
            source_id=src,
            published=dt.date(2024, 1, 1),
            codename_ids=[c_kim],
        )
        return {"laz": g_laz, "kim": g_kim, "and": g_and}

    async def test_top_groups_sorted_by_report_count_desc(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        ids = await self._setup(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        top = resp.json()["top_groups"]
        # Only 2 groups have reports. Andariel absent.
        assert len(top) == 2
        assert top[0]["name"] == "Lazarus Group"
        assert top[0]["report_count"] == 3
        assert top[1]["name"] == "Kimsuky"
        assert top[1]["report_count"] == 1
        group_ids_in_response = {entry["group_id"] for entry in top}
        assert ids["and"] not in group_ids_in_response

    async def test_top_n_default_5(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        # 7 groups with 1 report each → default top_n=5 trims to 5.
        for i in range(7):
            g = await _seed_group(real_engine, f"group-{i}")
            c = await _seed_codename(real_engine, f"codename-{i}", g)
            await _seed_report(
                real_engine,
                title=f"r-{i}",
                url=f"https://ex/{i}",
                source_id=src,
                published=dt.date(2024, 1, 1),
                codename_ids=[c],
            )
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        assert len(resp.json()["top_groups"]) == 5

    async def test_top_n_custom_respects_max(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        # 25 groups; top_n=20 (max) returns 20.
        for i in range(25):
            g = await _seed_group(real_engine, f"g-{i:02d}")
            c = await _seed_codename(real_engine, f"c-{i:02d}", g)
            await _seed_report(
                real_engine,
                title=f"r-{i}",
                url=f"https://ex/{i}",
                source_id=src,
                published=dt.date(2024, 1, 1),
                codename_ids=[c],
            )
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary?top_n=20",
            cookies={"dprk_cti_session": cookie},
        )
        assert len(resp.json()["top_groups"]) == 20


# ---------------------------------------------------------------------------
# Review priority #3 — top_n max + stable order
# ---------------------------------------------------------------------------


class TestTopNBound:
    async def test_top_n_above_max_returns_422(
        self, dashboard_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary?top_n=21", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 422

    async def test_top_n_zero_returns_422(
        self, dashboard_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary?top_n=0", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 422

    async def test_tie_break_by_group_id_asc_stable(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Groups with the same report_count must sort by group_id ASC
        so repeated calls return identical order (review priority #3)."""
        src = await _seed_source(real_engine, "src-a")
        # 3 groups, each with exactly 1 report.
        for i in range(3):
            g = await _seed_group(real_engine, f"tie-{i}")
            c = await _seed_codename(real_engine, f"codename-{i}", g)
            await _seed_report(
                real_engine,
                title=f"r-{i}",
                url=f"https://ex/{i}",
                source_id=src,
                published=dt.date(2024, 1, 1),
                codename_ids=[c],
            )
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        top = resp.json()["top_groups"]
        ids_in_order = [entry["group_id"] for entry in top]
        assert ids_in_order == sorted(ids_in_order)


# ---------------------------------------------------------------------------
# Review priority #4 — dedup in aggregate
# ---------------------------------------------------------------------------


class TestDedup:
    async def test_top_groups_dedupes_report_with_multiple_codenames_in_same_group(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """One report linked to TWO codenames that both belong to the
        SAME group must contribute +1 (not +2) to the group's count.
        ``COUNT(DISTINCT report_id)`` enforces this."""
        src = await _seed_source(real_engine, "src-a")
        g = await _seed_group(real_engine, "Lazarus Group")
        c1 = await _seed_codename(real_engine, "Bluenoroff", g)
        c2 = await _seed_codename(real_engine, "Andariel", g)
        await _seed_report(
            real_engine,
            title="dual codename",
            url="https://ex/dual",
            source_id=src,
            published=dt.date(2024, 1, 1),
            codename_ids=[c1, c2],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        top = resp.json()["top_groups"]
        assert len(top) == 1
        assert top[0]["name"] == "Lazarus Group"
        assert top[0]["report_count"] == 1  # not 2

    async def test_incidents_by_motivation_dedupes_per_incident(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """One incident with a single motivation row should contribute
        +1 to its bucket (baseline), not multiplied by anything."""
        await _seed_incident(
            real_engine,
            title="solo",
            reported=dt.date(2024, 1, 1),
            motivations=["financial"],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        assert resp.json()["incidents_by_motivation"] == [
            {"motivation": "financial", "count": 1}
        ]


# ---------------------------------------------------------------------------
# group_id filter scoping
# ---------------------------------------------------------------------------


class TestGroupIdsFilter:
    async def test_group_id_filters_top_groups_only(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """group_id filter narrows top_groups but does NOT affect
        total_reports or reports_by_year (documented MVP scope)."""
        src = await _seed_source(real_engine, "src-a")
        g_laz = await _seed_group(real_engine, "Lazarus Group")
        g_kim = await _seed_group(real_engine, "Kimsuky")
        c_laz = await _seed_codename(real_engine, "Bluenoroff", g_laz)
        c_kim = await _seed_codename(real_engine, "Velvet Chollima", g_kim)
        await _seed_report(
            real_engine,
            title="laz-1",
            url="https://ex/laz",
            source_id=src,
            published=dt.date(2024, 1, 1),
            codename_ids=[c_laz],
        )
        await _seed_report(
            real_engine,
            title="kim-1",
            url="https://ex/kim",
            source_id=src,
            published=dt.date(2024, 1, 1),
            codename_ids=[c_kim],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            f"/api/v1/dashboard/summary?group_id={g_laz}",
            cookies={"dprk_cti_session": cookie},
        )
        body = resp.json()
        # Top groups scoped to Lazarus only.
        assert len(body["top_groups"]) == 1
        assert body["top_groups"][0]["name"] == "Lazarus Group"
        # Totals unchanged — both reports still count toward total.
        assert body["total_reports"] == 2


# ---------------------------------------------------------------------------
# Invalid inputs — plan D12 uniform 422
# ---------------------------------------------------------------------------


class TestInvalid422:
    @pytest.mark.parametrize(
        "bad_qs",
        [
            "?date_from=not-a-date",
            "?date_to=2024-13-01",
            "?top_n=0",
            "?top_n=21",
            "?top_n=abc",
            "?group_id=0",  # ge=1 violation
            "?group_id=abc",
        ],
    )
    async def test_invalid_query_422(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        bad_qs: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            f"/api/v1/dashboard/summary{bad_qs}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422, (
            f"{bad_qs} expected 422, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# RBAC + OpenAPI
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_no_cookie_401(self, dashboard_client: AsyncClient) -> None:
        resp = await dashboard_client.get("/api/v1/dashboard/summary")
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role", ["analyst", "researcher", "policy", "soc", "admin"]
    )
    async def test_authorized_roles(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        role: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie, role=role)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200

    async def test_unknown_role_403(
        self, dashboard_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie, role="some_role")
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PR #23 §6.A C2 — top_sectors + top_sources parity
# ---------------------------------------------------------------------------


class TestTopSectors:
    async def test_top_sectors_sorted_by_count_desc_then_code_asc(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # 3 incidents in GOV (count=3), 2 in FIN (count=2), 1 in ENE
        # (count=1). Order on the wire is count DESC, sector_code ASC.
        for i in range(3):
            await _seed_incident(
                real_engine,
                title=f"i-gov-{i}",
                reported=dt.date(2026, 3, 1),
                sectors=["GOV"],
            )
        for i in range(2):
            await _seed_incident(
                real_engine,
                title=f"i-fin-{i}",
                reported=dt.date(2026, 3, 2),
                sectors=["FIN"],
            )
        await _seed_incident(
            real_engine,
            title="i-ene-0",
            reported=dt.date(2026, 3, 3),
            sectors=["ENE"],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["top_sectors"] == [
            {"sector_code": "GOV", "count": 3},
            {"sector_code": "FIN", "count": 2},
            {"sector_code": "ENE", "count": 1},
        ]

    async def test_top_sectors_dedupes_per_incident(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # One incident tagged with two sectors must contribute +1 to
        # EACH sector's bucket but never double-count its own row in a
        # single bucket. Mirrors `incidents_by_motivation` review
        # priority #4 invariant.
        await _seed_incident(
            real_engine,
            title="i-cross",
            reported=dt.date(2026, 3, 1),
            sectors=["GOV", "FIN"],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["top_sectors"] == [
            # Tied at count=1 → sector_code ASC (FIN before GOV).
            {"sector_code": "FIN", "count": 1},
            {"sector_code": "GOV", "count": 1},
        ]

    async def test_top_sectors_respects_date_filter(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_incident(
            real_engine,
            title="i-old",
            reported=dt.date(2024, 1, 1),
            sectors=["GOV"],
        )
        await _seed_incident(
            real_engine,
            title="i-in",
            reported=dt.date(2026, 3, 1),
            sectors=["FIN"],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary"
            "?date_from=2026-01-01&date_to=2026-12-31",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Only the in-window FIN incident surfaces.
        assert body["top_sectors"] == [{"sector_code": "FIN", "count": 1}]

    async def test_top_sectors_is_noop_for_group_ids_filter(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # Plan §6.A C2.b — top_sectors mirrors incidents_by_motivation
        # on group_ids: schema has no incident → group path, so
        # passing group_id is accepted but does NOT filter.
        g = await _seed_group(real_engine, "Lazarus Group")
        await _seed_incident(
            real_engine,
            title="i-gov",
            reported=dt.date(2026, 3, 1),
            sectors=["GOV"],
        )

        cookie = await _cookie(make_session_cookie)
        no_filter = (
            await dashboard_client.get(
                "/api/v1/dashboard/summary",
                cookies={"dprk_cti_session": cookie},
            )
        ).json()
        with_filter = (
            await dashboard_client.get(
                f"/api/v1/dashboard/summary?group_id={g}",
                cookies={"dprk_cti_session": cookie},
            )
        ).json()
        assert no_filter["top_sectors"] == with_filter["top_sectors"]
        assert with_filter["top_sectors"] == [
            {"sector_code": "GOV", "count": 1}
        ]

    async def test_top_sectors_respects_top_n(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # 6 distinct sectors, each with one incident. top_n=3 caps to
        # the highest-count three; ties resolved alphabetically.
        for sec in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"):
            await _seed_incident(
                real_engine,
                title=f"i-{sec}",
                reported=dt.date(2026, 3, 1),
                sectors=[sec],
            )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary?top_n=3",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert [row["sector_code"] for row in body["top_sectors"]] == [
            "AAA",
            "BBB",
            "CCC",
        ]


class TestTopSources:
    async def test_top_sources_sorted_by_report_count_desc(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src_mandiant = await _seed_source(real_engine, "Mandiant")
        src_chain = await _seed_source(real_engine, "Chainalysis")
        src_anyrun = await _seed_source(real_engine, "AnyRun")

        for i in range(3):
            await _seed_report(
                real_engine,
                title=f"r-mand-{i}",
                url=f"https://ex/m{i}",
                source_id=src_mandiant,
                published=dt.date(2026, 3, 10 + i),
            )
        for i in range(2):
            await _seed_report(
                real_engine,
                title=f"r-chain-{i}",
                url=f"https://ex/c{i}",
                source_id=src_chain,
                published=dt.date(2026, 3, 5 + i),
            )
        await _seed_report(
            real_engine,
            title="r-anyrun-0",
            url="https://ex/a0",
            source_id=src_anyrun,
            published=dt.date(2026, 3, 1),
        )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["top_sources"] == [
            {
                "source_id": src_mandiant,
                "source_name": "Mandiant",
                "report_count": 3,
                "latest_report_date": "2026-03-12",
            },
            {
                "source_id": src_chain,
                "source_name": "Chainalysis",
                "report_count": 2,
                "latest_report_date": "2026-03-06",
            },
            {
                "source_id": src_anyrun,
                "source_name": "AnyRun",
                "report_count": 1,
                "latest_report_date": "2026-03-01",
            },
        ]

    async def test_top_sources_tie_broken_by_source_id_asc(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # Two sources tied at report_count=1. id ASC tiebreaker keeps
        # repeat calls stable (mirror of top_groups review priority #3).
        src_first = await _seed_source(real_engine, "FirstAlphabetically")
        src_second = await _seed_source(real_engine, "AnotherSource")
        # Insert order is id-ascending: FirstAlphabetically(id=N) before
        # AnotherSource(id=N+1) regardless of name.
        await _seed_report(
            real_engine,
            title="r-first",
            url="https://ex/f",
            source_id=src_first,
            published=dt.date(2026, 3, 1),
        )
        await _seed_report(
            real_engine,
            title="r-second",
            url="https://ex/s",
            source_id=src_second,
            published=dt.date(2026, 3, 1),
        )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        ids_in_response = [row["source_id"] for row in body["top_sources"]]
        assert ids_in_response == [src_first, src_second], (
            "tied-count rows must order by source_id ASC for stability "
            "across repeated calls"
        )

    async def test_top_sources_respects_date_filter(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # latest_report_date is MAX(reports.published) within the
        # filter window — verify both filtering AND the latest-date
        # field's filter-awareness.
        src = await _seed_source(real_engine, "Vendor")
        await _seed_report(
            real_engine,
            title="r-old",
            url="https://ex/old",
            source_id=src,
            published=dt.date(2024, 1, 15),
        )
        await _seed_report(
            real_engine,
            title="r-in1",
            url="https://ex/in1",
            source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _seed_report(
            real_engine,
            title="r-in2",
            url="https://ex/in2",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary"
            "?date_from=2026-01-01&date_to=2026-12-31",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["top_sources"] == [
            {
                "source_id": src,
                "source_name": "Vendor",
                "report_count": 2,
                "latest_report_date": "2026-03-15",
            }
        ]

    async def test_top_sources_respects_top_n(
        self,
        dashboard_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # 6 distinct sources, top_n=2 caps to the top two by report
        # count (here all tied at 1, so id-ASC selects the first two).
        srcs = [
            await _seed_source(real_engine, f"src-{i}") for i in range(6)
        ]
        for i, src in enumerate(srcs):
            await _seed_report(
                real_engine,
                title=f"r-{i}",
                url=f"https://ex/r{i}",
                source_id=src,
                published=dt.date(2026, 3, 1),
            )

        cookie = await _cookie(make_session_cookie)
        resp = await dashboard_client.get(
            "/api/v1/dashboard/summary?top_n=2",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert [row["source_id"] for row in body["top_sources"]] == srcs[:2]


class TestOpenAPIRouterExamples:
    async def test_openapi_includes_dashboard_examples(self) -> None:
        from api.main import app

        spec = app.openapi()
        path = spec["paths"]["/api/v1/dashboard/summary"]["get"]
        examples = path["responses"]["200"]["content"]["application/json"]["examples"]
        assert "happy" in examples
        assert "empty" in examples
        # Empty example uses the zero/empty shape for FE to mock.
        assert examples["empty"]["value"]["total_reports"] == 0
        assert examples["empty"]["value"]["reports_by_year"] == []
