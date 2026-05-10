"""Integration tests for the three /api/v1/analytics endpoints (PR #13 Group A).

Runs on in-memory aiosqlite via dependency override — same pattern as
``test_dashboard_route.py``. Real-PG specifics (``to_char`` month
expression, the EXISTS planner) are covered by the contract-verify
live job and by exercising the BE stack during Group I / contract
extension.

Scope:
- Empty DB returns the plan D2 empty-shape for all three endpoints
  (``{tactics: [], rows: []}`` / ``{buckets: []}`` / ``{countries: []}``).
- Happy-path populated seed exercises the aggregation + wire shape.
- Query-param plumbing (``date_from`` / ``date_to`` / ``group_id`` /
  ``top_n``) survives the HTTP layer.
- Auth: 401 without cookie, 403 with a role not in the read allow-list.
- 422 on invalid ``group_id`` (< 1) — same contract as ``dashboard/summary``.
- Rate-limit path: 429 after 60 requests on a single endpoint within
  the same minute bucket.
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

from api.schemas.read import INCIDENTS_TREND_UNKNOWN_KEY
from api.tables import (
    codenames_table,
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    metadata,
    report_codenames_table,
    report_techniques_table,
    reports_table,
    sources_table,
    techniques_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def analytics_client(
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
# Seed helpers (mirror test_dashboard_route.py style for consistency)
# ---------------------------------------------------------------------------


async def _seed_source(engine: AsyncEngine, name: str = "src-a") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        src_id = int(result.scalar_one())
        await s.commit()
        return src_id


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    url: str,
    source_id: int,
    published: dt.date,
    codename_ids: list[int] | None = None,
    technique_ids: list[int] | None = None,
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
        rid = int(result.scalar_one())
        for cid in codename_ids or []:
            await s.execute(
                sa.insert(report_codenames_table).values(
                    report_id=rid, codename_id=cid
                )
            )
        for tid in technique_ids or []:
            await s.execute(
                sa.insert(report_techniques_table).values(
                    report_id=rid, technique_id=tid
                )
            )
        await s.commit()
        return rid


async def _seed_group(engine: AsyncEngine, name: str) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(groups_table).values(name=name).returning(groups_table.c.id)
        )
        gid = int(result.scalar_one())
        await s.commit()
        return gid


async def _seed_codename(engine: AsyncEngine, name: str, group_id: int) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(codenames_table)
            .values(name=name, group_id=group_id)
            .returning(codenames_table.c.id)
        )
        cid = int(result.scalar_one())
        await s.commit()
        return cid


async def _seed_technique(
    engine: AsyncEngine, *, mitre_id: str, name: str, tactic: str
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(techniques_table)
            .values(mitre_id=mitre_id, name=name, tactic=tactic)
            .returning(techniques_table.c.id)
        )
        tid = int(result.scalar_one())
        await s.commit()
        return tid


async def _seed_incident(
    engine: AsyncEngine,
    *,
    title: str,
    reported: dt.date | None,
    countries: list[str] | None = None,
    motivations: list[str] | None = None,
    sectors: list[str] | None = None,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(incidents_table)
            .values(title=title, reported=reported)
            .returning(incidents_table.c.id)
        )
        iid = int(result.scalar_one())
        for c in countries or []:
            await s.execute(
                sa.insert(incident_countries_table).values(
                    incident_id=iid, country_iso2=c
                )
            )
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
# Empty DB — all three endpoints return well-formed empty shape
# ---------------------------------------------------------------------------


class TestEmptyDB:
    async def test_attack_matrix_empty(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/attack_matrix",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {"tactics": [], "rows": []}

    async def test_trend_empty(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/trend", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        assert resp.json() == {"buckets": []}

    async def test_geo_empty(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/geo", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        assert resp.json() == {"countries": []}


# ---------------------------------------------------------------------------
# Happy-path — populated seeds produce the expected shape
# ---------------------------------------------------------------------------


class TestAttackMatrixHappy:
    async def test_populated_matrix_shape(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine)
        t_1566 = await _seed_technique(
            real_engine, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        t_1059 = await _seed_technique(
            real_engine, mitre_id="T1059", name="Cmd", tactic="TA0002"
        )
        for i in range(3):
            await _seed_report(
                real_engine,
                title=f"p-{i}",
                url=f"https://ex/p{i}",
                source_id=src,
                published=dt.date(2026, 3, 1),
                technique_ids=[t_1566],
            )
        await _seed_report(
            real_engine,
            title="c-0",
            url="https://ex/c0",
            source_id=src,
            published=dt.date(2026, 3, 1),
            technique_ids=[t_1059],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/attack_matrix",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tactics"] == [
            {"id": "TA0001", "name": "TA0001"},
            {"id": "TA0002", "name": "TA0002"},
        ]
        assert body["rows"][0] == {
            "tactic_id": "TA0001",
            "techniques": [{"technique_id": "T1566", "count": 3}],
        }
        assert body["rows"][1] == {
            "tactic_id": "TA0002",
            "techniques": [{"technique_id": "T1059", "count": 1}],
        }

    async def test_top_n_query_param_respected(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine)
        t_a = await _seed_technique(
            real_engine, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        t_b = await _seed_technique(
            real_engine, mitre_id="T1059", name="Cmd", tactic="TA0002"
        )
        for i in range(4):
            await _seed_report(
                real_engine,
                title=f"a-{i}",
                url=f"https://ex/a{i}",
                source_id=src,
                published=dt.date(2026, 3, 1),
                technique_ids=[t_a],
            )
        await _seed_report(
            real_engine,
            title="b-0",
            url="https://ex/b0",
            source_id=src,
            published=dt.date(2026, 3, 1),
            technique_ids=[t_b],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/attack_matrix?top_n=1",
            cookies={"dprk_cti_session": cookie},
        )
        body = resp.json()
        assert len(body["rows"]) == 1
        assert body["rows"][0]["techniques"] == [
            {"technique_id": "T1566", "count": 4}
        ]


class TestTrendHappy:
    async def test_monthly_buckets_wire_shape(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine)
        for d in [
            dt.date(2026, 2, 5),
            dt.date(2026, 2, 20),
            dt.date(2026, 3, 1),
        ]:
            await _seed_report(
                real_engine,
                title=f"r-{d.isoformat()}",
                url=f"https://ex/{d.isoformat()}",
                source_id=src,
                published=d,
            )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/trend", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "buckets": [
                {"month": "2026-02", "count": 2},
                {"month": "2026-03", "count": 1},
            ]
        }


class TestGeoHappy:
    async def test_country_aggregate_wire_shape(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_incident(
            real_engine,
            title="inc-1",
            reported=dt.date(2026, 3, 1),
            countries=["KR"],
        )
        await _seed_incident(
            real_engine,
            title="inc-2",
            reported=dt.date(2026, 3, 2),
            countries=["KR"],
        )
        await _seed_incident(
            real_engine,
            title="inc-3",
            reported=dt.date(2026, 3, 3),
            countries=["KP"],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/geo", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "countries": [
                {"iso2": "KR", "count": 2},
                {"iso2": "KP", "count": 1},
            ]
        }


# ---------------------------------------------------------------------------
# Filter plumbing — date_from/date_to/group_id survive the HTTP layer
# ---------------------------------------------------------------------------


class TestFilterPlumbing:
    async def test_date_filter_survives_query_params(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine)
        await _seed_report(
            real_engine,
            title="in",
            url="https://ex/in",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        await _seed_report(
            real_engine,
            title="out",
            url="https://ex/out",
            source_id=src,
            published=dt.date(2024, 1, 1),
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/trend?date_from=2026-01-01&date_to=2026-12-31",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert [b["month"] for b in resp.json()["buckets"]] == ["2026-03"]

    async def test_group_id_repeatable_survives_query_params(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine)
        t = await _seed_technique(
            real_engine, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        g = await _seed_group(real_engine, "Lazarus Group")
        c = await _seed_codename(real_engine, "Lazarus", g)
        await _seed_report(
            real_engine,
            title="in",
            url="https://ex/in",
            source_id=src,
            published=dt.date(2026, 3, 1),
            codename_ids=[c],
            technique_ids=[t],
        )
        await _seed_report(
            real_engine,
            title="orphan",
            url="https://ex/orphan",
            source_id=src,
            published=dt.date(2026, 3, 1),
            technique_ids=[t],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            f"/api/v1/analytics/attack_matrix?group_id={g}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        # Only the codename-linked report passes the group filter.
        assert resp.json()["rows"] == [
            {
                "tactic_id": "TA0001",
                "techniques": [{"technique_id": "T1566", "count": 1}],
            }
        ]


# ---------------------------------------------------------------------------
# Auth + validation contracts (uniform with /dashboard/summary)
# ---------------------------------------------------------------------------


class TestAuthAndValidation:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/analytics/attack_matrix",
            "/api/v1/analytics/trend",
            "/api/v1/analytics/geo",
            "/api/v1/analytics/incidents_trend?group_by=motivation",
        ],
    )
    async def test_missing_cookie_returns_401(
        self, analytics_client: AsyncClient, path: str
    ) -> None:
        resp = await analytics_client.get(path)
        assert resp.status_code == 401

    # NOTE: A parametrized "unprivileged role → 403" suite across the
    # 4 analytics paths was removed when the Phase 0 deferral on
    # ``SessionData.roles: list[KnownRole]`` was closed. Unknown roles
    # now fail pydantic validation at session construction
    # (see ``tests/unit/test_auth_schemas.py``).

    async def test_negative_group_id_returns_422(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/attack_matrix?group_id=0",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_top_n_out_of_bound_returns_422(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/attack_matrix?top_n=500",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_incidents_trend_missing_group_by_returns_422(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        # ``group_by`` is required (no default) — request without it must
        # 422, never silently fall back to a flat shape. PR #23 §6.A C1.d.
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/incidents_trend",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("invalid", ["foo", "Motivation", "", "all"])
    async def test_incidents_trend_invalid_group_by_returns_422(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        invalid: str,
    ) -> None:
        # Literal["motivation","sector"] — anything else is 422. Common
        # drift: capital-M, plural form, or "all". PR #23 §6.A C1.d.
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            f"/api/v1/analytics/incidents_trend?group_by={invalid}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /incidents_trend — PR #23 Group A C1 (lazarus.day parity)
# ---------------------------------------------------------------------------


class TestIncidentsTrendEmpty:
    async def test_empty_db_motivation(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/incidents_trend?group_by=motivation",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {"buckets": [], "group_by": "motivation"}

    async def test_empty_db_sector(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/incidents_trend?group_by=sector",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {"buckets": [], "group_by": "sector"}


class TestIncidentsTrendHappy:
    async def test_motivation_populated_invariant_holds(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # Feb 2026: 2 Espionage + 1 Finance.
        # Mar 2026: 1 Espionage + 1 unjuncted (lands in "unknown").
        await _seed_incident(
            real_engine,
            title="i-feb-1",
            reported=dt.date(2026, 2, 5),
            motivations=["Espionage"],
        )
        await _seed_incident(
            real_engine,
            title="i-feb-2",
            reported=dt.date(2026, 2, 18),
            motivations=["Espionage"],
        )
        await _seed_incident(
            real_engine,
            title="i-feb-3",
            reported=dt.date(2026, 2, 25),
            motivations=["Finance"],
        )
        await _seed_incident(
            real_engine,
            title="i-mar-1",
            reported=dt.date(2026, 3, 4),
            motivations=["Espionage"],
        )
        await _seed_incident(
            real_engine,
            title="i-mar-unknown",
            reported=dt.date(2026, 3, 20),
            motivations=[],  # no junction row → unknown bucket
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/incidents_trend?group_by=motivation",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["group_by"] == "motivation"

        buckets = {b["month"]: b for b in body["buckets"]}
        assert set(buckets.keys()) == {"2026-02", "2026-03"}

        # This single-motivation fixture has series sum equal the distinct
        # outer count; multi-category divergence is pinned separately.
        for month, bucket in buckets.items():
            series_total = sum(item["count"] for item in bucket["series"])
            assert series_total == bucket["count"], (
                f"single-category fixture mismatch for {month}: outer={bucket['count']}, "
                f"sum(series)={series_total}, series={bucket['series']}"
            )

        feb = buckets["2026-02"]
        assert feb["count"] == 3
        assert sorted(feb["series"], key=lambda s: s["key"]) == [
            {"key": "Espionage", "count": 2},
            {"key": "Finance", "count": 1},
        ]
        mar = buckets["2026-03"]
        assert mar["count"] == 2
        assert sorted(mar["series"], key=lambda s: s["key"]) == [
            {"key": "Espionage", "count": 1},
            {"key": INCIDENTS_TREND_UNKNOWN_KEY, "count": 1},
        ]

    async def test_sector_populated_invariant_holds(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # Mar 2026: 2 GOV, 1 FIN, 1 ENE.
        await _seed_incident(
            real_engine,
            title="i-gov-a",
            reported=dt.date(2026, 3, 2),
            sectors=["GOV"],
        )
        await _seed_incident(
            real_engine,
            title="i-gov-b",
            reported=dt.date(2026, 3, 8),
            sectors=["GOV"],
        )
        await _seed_incident(
            real_engine,
            title="i-fin",
            reported=dt.date(2026, 3, 12),
            sectors=["FIN"],
        )
        await _seed_incident(
            real_engine,
            title="i-eng",
            reported=dt.date(2026, 3, 20),
            sectors=["ENE"],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/incidents_trend?group_by=sector",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["group_by"] == "sector"

        buckets = {b["month"]: b for b in body["buckets"]}
        assert set(buckets.keys()) == {"2026-03"}
        mar = buckets["2026-03"]
        assert mar["count"] == 4
        assert sorted(mar["series"], key=lambda s: s["key"]) == [
            {"key": "ENE", "count": 1},
            {"key": "FIN", "count": 1},
            {"key": "GOV", "count": 2},
        ]

    async def test_date_filters_pass_through_to_aggregator(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # 3 incidents, only the 2026-03 one should land in the response.
        await _seed_incident(
            real_engine,
            title="i-old",
            reported=dt.date(2024, 1, 15),
            motivations=["Espionage"],
        )
        await _seed_incident(
            real_engine,
            title="i-in",
            reported=dt.date(2026, 3, 10),
            motivations=["Finance"],
        )
        await _seed_incident(
            real_engine,
            title="i-future",
            reported=dt.date(2027, 6, 5),
            motivations=["Espionage"],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/incidents_trend"
            "?group_by=motivation&date_from=2026-01-01&date_to=2026-12-31",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["group_by"] == "motivation"
        assert body["buckets"] == [
            {
                "month": "2026-03",
                "count": 1,
                "series": [{"key": "Finance", "count": 1}],
            }
        ]

    async def test_sector_multi_link_keeps_outer_count_distinct(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_incident(
            real_engine,
            title="i-dual-sector",
            reported=dt.date(2026, 3, 5),
            sectors=["GOV", "FIN"],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/incidents_trend?group_by=sector",
            cookies={"dprk_cti_session": cookie},
        )

        assert resp.status_code == 200
        body = resp.json()
        buckets = {b["month"]: b for b in body["buckets"]}
        mar = buckets["2026-03"]
        assert mar["count"] == 1
        assert sum(item["count"] for item in mar["series"]) == 2
        assert sorted(mar["series"], key=lambda s: s["key"]) == [
            {"key": "FIN", "count": 1},
            {"key": "GOV", "count": 1},
        ]

# ---------------------------------------------------------------------------
# Rate limit — 60/min bucket shared with the other read routes
# ---------------------------------------------------------------------------


class TestRateLimit:
    async def test_429_after_60_calls_on_same_endpoint(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        for _ in range(60):
            ok = await analytics_client.get(
                "/api/v1/analytics/trend",
                cookies={"dprk_cti_session": cookie},
            )
            assert ok.status_code == 200

        tripped = await analytics_client.get(
            "/api/v1/analytics/trend", cookies={"dprk_cti_session": cookie}
        )
        assert tripped.status_code == 429


# ===========================================================================
# /analytics/actor_network — PR 3 SNA co-occurrence (RED batch, T1 of plan v1.3)
# ===========================================================================
#
# All tests in this section currently fail because the route is not yet
# wired (T7 lands the GREEN implementation). RED-state failures expected:
#   - 404 for happy/empty/filter cases (route does not exist).
#   - 422 cases also produce 404 (validators run inside the route handler
#     which doesn't exist yet).
#   - Rate-limit case produces 60×404 + 1×404 (slowapi never sees the
#     request since the route is missing).
#
# References: docs/plans/actor-network-data.md L1, L6, L7, L10, AC #1-#4.


# ---------------------------------------------------------------------------
# Local seed helper for the actor↔sector chain (the integration test file
# does not have an incident_sources helper; add one locally for PR 3).
# ---------------------------------------------------------------------------


async def _link_incident_source(
    engine: AsyncEngine, incident_id: int, report_id: int
) -> None:
    from api.tables import incident_sources_table

    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(
            sa.insert(incident_sources_table).values(
                incident_id=incident_id, report_id=report_id
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# TestActorNetworkEmpty — L6 empty contract through HTTP layer
# ---------------------------------------------------------------------------


class TestActorNetworkEmpty:
    async def test_empty_db_returns_empty_payload(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/actor_network",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "nodes": [],
            "edges": [],
            "cap_breached": False,
        }


# ---------------------------------------------------------------------------
# TestActorNetworkHappy — populated seed produces the expected wire shape
# ---------------------------------------------------------------------------


class TestActorNetworkHappy:
    async def test_populated_actor_network_shape(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # Minimal populated seed: one actor↔tool edge. Smoke-tests the
        # wire-shape pass-through from aggregator → DTO → JSON, including
        # node ID kind-prefixing per L13.
        src = await _seed_source(real_engine)
        g = await _seed_group(real_engine, "Lazarus")
        cn = await _seed_codename(real_engine, "Lazarus", g)
        t = await _seed_technique(
            real_engine, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        await _seed_report(
            real_engine,
            title="r1",
            url="u1",
            source_id=src,
            published=dt.date(2026, 3, 5),
            codename_ids=[cn],
            technique_ids=[t],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/actor_network",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()

        # Codex r4 HIGH (L2-WIRE-SHAPE) fold: pin the exact top-level
        # shape — no extra keys allowed. cap_breached defaults to False
        # in the unfiltered case.
        assert set(body.keys()) == {"nodes", "edges", "cap_breached"}
        assert isinstance(body["nodes"], list)
        assert isinstance(body["edges"], list)
        assert isinstance(body["cap_breached"], bool)
        assert body["cap_breached"] is False

        # Node ID kind-prefixing per L13. The seeded fixture has
        # exactly one actor↔tool edge → exactly 2 nodes, 1 edge.
        node_ids = {n["id"] for n in body["nodes"]}
        assert node_ids == {f"actor:{g}", f"tool:{t}"}

        # Pin each node to the EXACT key set per L2 (no extra fields).
        for n in body["nodes"]:
            assert set(n.keys()) == {"id", "kind", "label", "degree"}
            assert isinstance(n["id"], str)
            assert n["kind"] in {"actor", "tool", "sector"}
            assert isinstance(n["label"], str)
            assert n["label"]  # non-empty
            assert isinstance(n["degree"], int)
            assert n["degree"] >= 0

        # Pin each edge to the EXACT key set per L2.
        for e in body["edges"]:
            assert set(e.keys()) == {"source_id", "target_id", "weight"}
            assert isinstance(e["source_id"], str)
            assert isinstance(e["target_id"], str)
            assert isinstance(e["weight"], int)
            assert e["weight"] >= 1
            # Endpoint membership: every edge endpoint MUST appear in
            # the nodes array (no orphan endpoints per L4 Step F).
            assert e["source_id"] in node_ids
            assert e["target_id"] in node_ids
            # No self-loops (L3 actor-actor pair ordering excludes them).
            assert e["source_id"] != e["target_id"]


# ---------------------------------------------------------------------------
# TestActorNetworkFilters — L6 vacuous-window 200-empty + L10 422 cases
# ---------------------------------------------------------------------------


class TestActorNetworkFilters:
    async def test_vacuous_window_returns_200_empty_not_422(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # L6 + L10 + Codex r2 fold: date_from > date_to is NOT validator-
        # enforced (matches existing analytics convention — see
        # services/api/src/api/routers/analytics.py:191 docstring); it
        # produces empty-200, not 422. Even with seeded data, an inverted
        # window must drop everything.
        src = await _seed_source(real_engine)
        g = await _seed_group(real_engine, "Lazarus")
        cn = await _seed_codename(real_engine, "Lazarus", g)
        t = await _seed_technique(
            real_engine, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        await _seed_report(
            real_engine,
            title="r",
            url="u",
            source_id=src,
            published=dt.date(2026, 3, 5),
            codename_ids=[cn],
            technique_ids=[t],
        )

        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/actor_network"
            "?date_from=2026-12-31&date_to=2026-01-01",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["nodes"] == []
        assert body["edges"] == []
        assert body["cap_breached"] is False

    async def test_valid_window_no_rows_returns_200_empty(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        # Valid window that simply matches no data → empty response.
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            "/api/v1/analytics/actor_network"
            "?date_from=2099-01-01&date_to=2099-12-31",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "nodes": [],
            "edges": [],
            "cap_breached": False,
        }


# ---------------------------------------------------------------------------
# TestActorNetworkValidation — L10 422 contract on bad query params
# ---------------------------------------------------------------------------


class TestActorNetworkValidation:
    @pytest.mark.parametrize(
        "query",
        [
            "group_id=0",
            "group_id=-1",
            "top_n_actor=0",
            "top_n_actor=201",
            "top_n_tool=0",
            "top_n_tool=201",
            "top_n_sector=0",
            "top_n_sector=-1",
            "date_from=not-a-date",
            "date_to=2026/03/05",
        ],
    )
    async def test_invalid_query_param_returns_422(
        self,
        analytics_client: AsyncClient,
        make_session_cookie,
        query: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await analytics_client.get(
            f"/api/v1/analytics/actor_network?{query}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422, (
            f"query='{query}' expected 422 got {resp.status_code}: "
            f"{resp.text[:200]}"
        )


# ---------------------------------------------------------------------------
# TestActorNetworkRBAC — 401 (no cookie) + 403 (wrong role)
# ---------------------------------------------------------------------------


class TestActorNetworkRBAC:
    async def test_missing_cookie_returns_401(
        self, analytics_client: AsyncClient
    ) -> None:
        resp = await analytics_client.get("/api/v1/analytics/actor_network")
        assert resp.status_code == 401

    # NOTE: An "unprivileged role → 403" test for actor_network was
    # removed when the Phase 0 deferral on
    # ``SessionData.roles: list[KnownRole]`` was closed. Unknown roles
    # now fail pydantic validation at session construction
    # (see ``tests/unit/test_auth_schemas.py``).


# ---------------------------------------------------------------------------
# TestActorNetworkRateLimit — L8 60/min/route + AC #3 independence
# ---------------------------------------------------------------------------


class TestActorNetworkRateLimit:
    async def test_429_after_60_calls_on_actor_network(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        for _ in range(60):
            ok = await analytics_client.get(
                "/api/v1/analytics/actor_network",
                cookies={"dprk_cti_session": cookie},
            )
            assert ok.status_code == 200

        tripped = await analytics_client.get(
            "/api/v1/analytics/actor_network",
            cookies={"dprk_cti_session": cookie},
        )
        assert tripped.status_code == 429

    async def test_actor_network_429_does_not_consume_attack_matrix_budget(
        self, analytics_client: AsyncClient, make_session_cookie
    ) -> None:
        # Plan AC #3 + Codex r2 MEDIUM fold: per-route bucket isolation.
        # Drain actor_network → 429; attack_matrix's budget MUST be
        # untouched (200 OK on the very next call to the sibling route).
        cookie = await _cookie(make_session_cookie)
        for _ in range(60):
            await analytics_client.get(
                "/api/v1/analytics/actor_network",
                cookies={"dprk_cti_session": cookie},
            )
        tripped = await analytics_client.get(
            "/api/v1/analytics/actor_network",
            cookies={"dprk_cti_session": cookie},
        )
        assert tripped.status_code == 429

        sibling = await analytics_client.get(
            "/api/v1/analytics/attack_matrix",
            cookies={"dprk_cti_session": cookie},
        )
        # Sibling route's bucket is independent — must still be available.
        assert sibling.status_code == 200
