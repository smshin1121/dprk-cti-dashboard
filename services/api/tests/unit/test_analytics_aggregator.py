"""Unit tests for ``api.read.analytics_aggregator`` (PR #13 Group A).

Runs against in-memory aiosqlite via ``metadata.create_all``. This
matches the existing dashboard aggregator approach — real-PG
behaviour (``to_char`` vs sqlite ``strftime``, EXISTS planner) is
covered by the integration test on real-PG in the Group A integration
tests (plus the Group H contract-verify live job).

Scope:
- empty DB returns empty-but-well-formed payloads for all three
  aggregators (plan D2 invariant #4);
- ``compute_attack_matrix`` groups rows by tactic, drops null-tactic
  rows, respects ``top_n`` clamp, handles the group-chain filter,
  counts DISTINCT reports (no JOIN inflation when one report is
  tagged with two techniques in the same tactic);
- ``compute_trend`` buckets by ``YYYY-MM``, omits zero-count months,
  respects date + group filters;
- ``compute_geo`` aggregates incidents by ``country_iso2``, respects
  date filter, treats ``group_ids`` as a no-op (schema-level — there
  is no incident→group path).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from api.read.analytics_aggregator import (
    compute_actor_network,
    compute_attack_matrix,
    compute_geo,
    compute_incidents_trend,
    compute_trend,
)
from api.schemas.read import INCIDENTS_TREND_UNKNOWN_KEY
from api.tables import (
    codenames_table,
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incident_sources_table,
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
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_source(session: AsyncSession, name: str = "src-a") -> int:
    result = await session.execute(
        sa.insert(sources_table)
        .values(name=name, type="vendor")
        .returning(sources_table.c.id)
    )
    src_id = int(result.scalar_one())
    await session.commit()
    return src_id


async def _seed_report(
    session: AsyncSession,
    *,
    title: str,
    url: str,
    source_id: int,
    published: dt.date,
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
    rid = int(result.scalar_one())
    await session.commit()
    return rid


async def _seed_group(session: AsyncSession, name: str) -> int:
    result = await session.execute(
        sa.insert(groups_table).values(name=name).returning(groups_table.c.id)
    )
    gid = int(result.scalar_one())
    await session.commit()
    return gid


async def _seed_codename(session: AsyncSession, name: str, group_id: int) -> int:
    result = await session.execute(
        sa.insert(codenames_table)
        .values(name=name, group_id=group_id)
        .returning(codenames_table.c.id)
    )
    cid = int(result.scalar_one())
    await session.commit()
    return cid


async def _link_report_codename(
    session: AsyncSession, report_id: int, codename_id: int
) -> None:
    await session.execute(
        sa.insert(report_codenames_table).values(
            report_id=report_id, codename_id=codename_id
        )
    )
    await session.commit()


async def _seed_technique(
    session: AsyncSession, *, mitre_id: str, name: str, tactic: str | None
) -> int:
    result = await session.execute(
        sa.insert(techniques_table)
        .values(mitre_id=mitre_id, name=name, tactic=tactic)
        .returning(techniques_table.c.id)
    )
    tid = int(result.scalar_one())
    await session.commit()
    return tid


async def _link_report_technique(
    session: AsyncSession, report_id: int, technique_id: int
) -> None:
    await session.execute(
        sa.insert(report_techniques_table).values(
            report_id=report_id, technique_id=technique_id
        )
    )
    await session.commit()


async def _seed_incident(
    session: AsyncSession, *, title: str, reported: dt.date | None
) -> int:
    result = await session.execute(
        sa.insert(incidents_table)
        .values(title=title, reported=reported)
        .returning(incidents_table.c.id)
    )
    iid = int(result.scalar_one())
    await session.commit()
    return iid


async def _link_incident_country(
    session: AsyncSession, incident_id: int, country_iso2: str
) -> None:
    await session.execute(
        sa.insert(incident_countries_table).values(
            incident_id=incident_id, country_iso2=country_iso2
        )
    )
    await session.commit()


async def _link_incident_motivation(
    session: AsyncSession, incident_id: int, motivation: str
) -> None:
    await session.execute(
        sa.insert(incident_motivations_table).values(
            incident_id=incident_id, motivation=motivation
        )
    )
    await session.commit()


async def _link_incident_sector(
    session: AsyncSession, incident_id: int, sector_code: str
) -> None:
    await session.execute(
        sa.insert(incident_sectors_table).values(
            incident_id=incident_id, sector_code=sector_code
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# compute_attack_matrix
# ---------------------------------------------------------------------------


class TestAttackMatrixEmpty:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_payload(
        self, session: AsyncSession
    ) -> None:
        result = await compute_attack_matrix(session)
        assert result == {"tactics": [], "rows": []}


class TestAttackMatrixPopulated:
    @pytest.mark.asyncio
    async def test_groups_by_tactic_and_orders_by_count(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        t_1566 = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        t_1190 = await _seed_technique(
            session,
            mitre_id="T1190",
            name="Exploit Public-Facing Application",
            tactic="TA0001",
        )
        t_1059 = await _seed_technique(
            session,
            mitre_id="T1059",
            name="Command and Scripting Interpreter",
            tactic="TA0002",
        )

        # 3 reports tagged T1566 (TA0001), 2 tagged T1059 (TA0002), 1
        # tagged T1190 (TA0001) → rows in TA0001 are [T1566:3, T1190:1];
        # TA0001 total (4) > TA0002 total (2), so TA0001 comes first.
        for i in range(3):
            rid = await _seed_report(
                session,
                title=f"p-{i}",
                url=f"https://ex/p{i}",
                source_id=src,
                published=dt.date(2026, 3, 1),
            )
            await _link_report_technique(session, rid, t_1566)
        for i in range(2):
            rid = await _seed_report(
                session,
                title=f"c-{i}",
                url=f"https://ex/c{i}",
                source_id=src,
                published=dt.date(2026, 3, 1),
            )
            await _link_report_technique(session, rid, t_1059)
        rid_ep = await _seed_report(
            session,
            title="ep-0",
            url="https://ex/ep0",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        await _link_report_technique(session, rid_ep, t_1190)

        result = await compute_attack_matrix(session)
        assert result["tactics"] == [
            {"id": "TA0001", "name": "TA0001"},
            {"id": "TA0002", "name": "TA0002"},
        ]
        assert result["rows"] == [
            {
                "tactic_id": "TA0001",
                "techniques": [
                    {"technique_id": "T1566", "count": 3},
                    {"technique_id": "T1190", "count": 1},
                ],
            },
            {
                "tactic_id": "TA0002",
                "techniques": [
                    {"technique_id": "T1059", "count": 2},
                ],
            },
        ]

    @pytest.mark.asyncio
    async def test_null_tactic_rows_filtered_out(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        t_good = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        t_null = await _seed_technique(
            session,
            mitre_id="T0000",
            name="Unclassified Technique",
            tactic=None,
        )
        rid_good = await _seed_report(
            session,
            title="good",
            url="https://ex/good",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        rid_null = await _seed_report(
            session,
            title="null",
            url="https://ex/null",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        await _link_report_technique(session, rid_good, t_good)
        await _link_report_technique(session, rid_null, t_null)

        result = await compute_attack_matrix(session)
        # T0000 must not appear anywhere — either in rows or in tactics.
        assert all(row["tactic_id"] == "TA0001" for row in result["rows"])
        technique_ids = [
            t["technique_id"] for row in result["rows"] for t in row["techniques"]
        ]
        assert "T0000" not in technique_ids

    @pytest.mark.asyncio
    async def test_top_n_limits_total_techniques(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        t_a = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        t_b = await _seed_technique(
            session, mitre_id="T1059", name="Cmd", tactic="TA0002"
        )
        for i in range(4):
            rid = await _seed_report(
                session,
                title=f"a-{i}",
                url=f"https://ex/a{i}",
                source_id=src,
                published=dt.date(2026, 3, 1),
            )
            await _link_report_technique(session, rid, t_a)
        rid_b = await _seed_report(
            session,
            title="b-0",
            url="https://ex/b0",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        await _link_report_technique(session, rid_b, t_b)

        result = await compute_attack_matrix(session, top_n=1)
        # Only the top technique (T1566 count=4) should appear.
        assert len(result["rows"]) == 1
        assert result["rows"][0]["techniques"] == [
            {"technique_id": "T1566", "count": 4}
        ]

    @pytest.mark.asyncio
    async def test_top_n_clamped_to_upper_bound(
        self, session: AsyncSession
    ) -> None:
        # Aggregator defensively clamps top_n to 200 when called with
        # a higher value — router Query(le=200) already enforces this
        # on the HTTP layer, but the unit-level invariant is tested
        # at the function boundary.
        result = await compute_attack_matrix(session, top_n=10_000)
        assert result == {"tactics": [], "rows": []}

    @pytest.mark.asyncio
    async def test_date_filter_restricts_matrix(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        t_in = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        t_out = await _seed_technique(
            session, mitre_id="T1190", name="Exploit", tactic="TA0001"
        )
        rid_in = await _seed_report(
            session,
            title="inside",
            url="https://ex/in",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )
        rid_out = await _seed_report(
            session,
            title="outside",
            url="https://ex/out",
            source_id=src,
            published=dt.date(2024, 1, 1),
        )
        await _link_report_technique(session, rid_in, t_in)
        await _link_report_technique(session, rid_out, t_out)

        result = await compute_attack_matrix(
            session,
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 12, 31),
        )
        technique_ids = [
            t["technique_id"] for row in result["rows"] for t in row["techniques"]
        ]
        assert technique_ids == ["T1566"]

    @pytest.mark.asyncio
    async def test_group_ids_filter_via_codename_chain(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        t = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        g_lazarus = await _seed_group(session, "Lazarus Group")
        g_kimsuky = await _seed_group(session, "Kimsuky")
        c_lazarus = await _seed_codename(session, "Lazarus", g_lazarus)
        c_kimsuky = await _seed_codename(session, "Kimsuky-a", g_kimsuky)

        rid_l = await _seed_report(
            session,
            title="lazarus-r",
            url="https://ex/laz",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        rid_k = await _seed_report(
            session,
            title="kimsuky-r",
            url="https://ex/kim",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        await _link_report_technique(session, rid_l, t)
        await _link_report_technique(session, rid_k, t)
        await _link_report_codename(session, rid_l, c_lazarus)
        await _link_report_codename(session, rid_k, c_kimsuky)

        # Filter to Lazarus — only the Lazarus-linked report counts.
        result = await compute_attack_matrix(session, group_ids=[g_lazarus])
        assert result["rows"] == [
            {
                "tactic_id": "TA0001",
                "techniques": [{"technique_id": "T1566", "count": 1}],
            }
        ]

    @pytest.mark.asyncio
    async def test_no_join_inflation_on_duplicate_codenames(
        self, session: AsyncSession
    ) -> None:
        # A report attributed to two codenames of the SAME group must
        # still count as 1 toward that group's attack_matrix. The
        # EXISTS-subquery approach in the aggregator guarantees this;
        # this test pins the invariant against future refactors that
        # might swap it for a plain JOIN.
        src = await _seed_source(session)
        t = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        g = await _seed_group(session, "Lazarus Group")
        c1 = await _seed_codename(session, "Lazarus", g)
        c2 = await _seed_codename(session, "Hidden Cobra", g)
        rid = await _seed_report(
            session,
            title="r",
            url="https://ex/r",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        await _link_report_technique(session, rid, t)
        await _link_report_codename(session, rid, c1)
        await _link_report_codename(session, rid, c2)

        result = await compute_attack_matrix(session, group_ids=[g])
        assert result["rows"][0]["techniques"] == [
            {"technique_id": "T1566", "count": 1}
        ]


# ---------------------------------------------------------------------------
# compute_trend
# ---------------------------------------------------------------------------


class TestTrendEmpty:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_buckets(
        self, session: AsyncSession
    ) -> None:
        result = await compute_trend(session)
        assert result == {"buckets": []}


class TestTrendPopulated:
    @pytest.mark.asyncio
    async def test_monthly_bucket_aggregation(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        # Feb 2026: 2 reports. Mar 2026: 3 reports. Apr 2026: 1 report.
        for d in [
            dt.date(2026, 2, 1),
            dt.date(2026, 2, 15),
            dt.date(2026, 3, 1),
            dt.date(2026, 3, 10),
            dt.date(2026, 3, 20),
            dt.date(2026, 4, 5),
        ]:
            await _seed_report(
                session,
                title=f"r-{d.isoformat()}",
                url=f"https://ex/{d.isoformat()}",
                source_id=src,
                published=d,
            )

        result = await compute_trend(session)
        assert result == {
            "buckets": [
                {"month": "2026-02", "count": 2},
                {"month": "2026-03", "count": 3},
                {"month": "2026-04", "count": 1},
            ]
        }

    @pytest.mark.asyncio
    async def test_date_filter_narrows_buckets(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        for d in [
            dt.date(2024, 1, 1),
            dt.date(2026, 3, 1),
            dt.date(2026, 4, 1),
        ]:
            await _seed_report(
                session,
                title=f"r-{d.isoformat()}",
                url=f"https://ex/{d.isoformat()}",
                source_id=src,
                published=d,
            )

        result = await compute_trend(
            session,
            date_from=dt.date(2026, 3, 1),
            date_to=dt.date(2026, 12, 31),
        )
        assert [b["month"] for b in result["buckets"]] == ["2026-03", "2026-04"]

    @pytest.mark.asyncio
    async def test_group_filter_applies_to_trend(
        self, session: AsyncSession
    ) -> None:
        src = await _seed_source(session)
        g = await _seed_group(session, "Lazarus Group")
        c = await _seed_codename(session, "Lazarus", g)

        rid_in = await _seed_report(
            session,
            title="in",
            url="https://ex/in",
            source_id=src,
            published=dt.date(2026, 3, 10),
        )
        await _link_report_codename(session, rid_in, c)
        await _seed_report(
            session,
            title="out",
            url="https://ex/out",
            source_id=src,
            published=dt.date(2026, 3, 20),
        )

        result = await compute_trend(session, group_ids=[g])
        assert result == {"buckets": [{"month": "2026-03", "count": 1}]}


# ---------------------------------------------------------------------------
# compute_geo
# ---------------------------------------------------------------------------


class TestGeoEmpty:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_countries(
        self, session: AsyncSession
    ) -> None:
        result = await compute_geo(session)
        assert result == {"countries": []}


class TestGeoPopulated:
    @pytest.mark.asyncio
    async def test_country_aggregation_with_kp_as_plain_row(
        self, session: AsyncSession
    ) -> None:
        # 2 incidents in KR, 1 in US, 1 in KP. Plan D2 lock: KP must
        # appear as a plain row, no special-case field.
        iid_1 = await _seed_incident(
            session, title="inc-1", reported=dt.date(2026, 3, 1)
        )
        iid_2 = await _seed_incident(
            session, title="inc-2", reported=dt.date(2026, 3, 2)
        )
        iid_3 = await _seed_incident(
            session, title="inc-3", reported=dt.date(2026, 3, 3)
        )
        iid_4 = await _seed_incident(
            session, title="inc-4", reported=dt.date(2026, 3, 4)
        )
        await _link_incident_country(session, iid_1, "KR")
        await _link_incident_country(session, iid_2, "KR")
        await _link_incident_country(session, iid_3, "US")
        await _link_incident_country(session, iid_4, "KP")

        result = await compute_geo(session)
        assert result == {
            "countries": [
                {"iso2": "KR", "count": 2},
                {"iso2": "KP", "count": 1},
                {"iso2": "US", "count": 1},
            ]
        }

    @pytest.mark.asyncio
    async def test_date_filter_narrows_geo(
        self, session: AsyncSession
    ) -> None:
        iid_in = await _seed_incident(
            session, title="in", reported=dt.date(2026, 3, 1)
        )
        iid_out = await _seed_incident(
            session, title="out", reported=dt.date(2024, 1, 1)
        )
        await _link_incident_country(session, iid_in, "KR")
        await _link_incident_country(session, iid_out, "US")

        result = await compute_geo(
            session,
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 12, 31),
        )
        assert result == {"countries": [{"iso2": "KR", "count": 1}]}

    @pytest.mark.asyncio
    async def test_group_ids_is_noop_for_geo(
        self, session: AsyncSession
    ) -> None:
        # Plan D2 + schema constraint: incidents have no path to groups.
        # Passing group_ids should not filter the response.
        iid = await _seed_incident(
            session, title="inc", reported=dt.date(2026, 3, 1)
        )
        await _link_incident_country(session, iid, "KR")

        result_no_group = await compute_geo(session)
        result_with_group = await compute_geo(session, group_ids=[999])
        assert result_no_group == result_with_group
        assert result_with_group == {
            "countries": [{"iso2": "KR", "count": 1}]
        }


# ---------------------------------------------------------------------------
# compute_incidents_trend (PR #23 Group A C1 — lazarus.day parity)
# ---------------------------------------------------------------------------
#
# Distinct from ``compute_trend``: fact table is ``incidents`` (not
# ``reports``), bucketed by ``incidents.reported``. Each bucket carries a
# ``series`` slice of motivation or sector membership counts. Outer
# ``count`` is the distinct incident total; multi-category incidents can
# make ``sum(series[].count)`` exceed the outer count. Incidents with no
# junction row land in the ``INCIDENTS_TREND_UNKNOWN_KEY`` slice rather
# than being dropped. ``incidents.reported IS NULL`` rows ARE excluded
# upstream of the junction (cursor-convention parity, ``tables.py:258``).
# Plan PR #23 C1 lock.


class TestIncidentsTrendMotivation:
    @pytest.mark.asyncio
    async def test_motivation_invariant_holds_per_bucket(
        self, session: AsyncSession
    ) -> None:
        # Feb 2026: 3 incidents — 2 Espionage, 1 Finance.
        # Mar 2026: 2 incidents — 2 Espionage.
        i_feb_e1 = await _seed_incident(
            session, title="i-feb-e1", reported=dt.date(2026, 2, 5)
        )
        i_feb_e2 = await _seed_incident(
            session, title="i-feb-e2", reported=dt.date(2026, 2, 18)
        )
        i_feb_f1 = await _seed_incident(
            session, title="i-feb-f1", reported=dt.date(2026, 2, 25)
        )
        i_mar_e1 = await _seed_incident(
            session, title="i-mar-e1", reported=dt.date(2026, 3, 1)
        )
        i_mar_e2 = await _seed_incident(
            session, title="i-mar-e2", reported=dt.date(2026, 3, 15)
        )
        for iid in (i_feb_e1, i_feb_e2, i_mar_e1, i_mar_e2):
            await _link_incident_motivation(session, iid, "Espionage")
        await _link_incident_motivation(session, i_feb_f1, "Finance")

        result = await compute_incidents_trend(session, group_by="motivation")

        assert result["group_by"] == "motivation"
        buckets = {b["month"]: b for b in result["buckets"]}
        assert set(buckets.keys()) == {"2026-02", "2026-03"}

        # This single-motivation fixture has series sum equal the distinct
        # outer count; multi-category divergence is pinned separately.
        for month, bucket in buckets.items():
            series_total = sum(item["count"] for item in bucket["series"])
            assert series_total == bucket["count"], (
                f"single-category fixture mismatch for {month}: outer={bucket['count']}, "
                f"series sum={series_total}, series={bucket['series']}"
            )

        # Concrete shape pinned to catch unintended surface change.
        feb = buckets["2026-02"]
        assert feb["count"] == 3
        assert sorted(feb["series"], key=lambda s: s["key"]) == [
            {"key": "Espionage", "count": 2},
            {"key": "Finance", "count": 1},
        ]
        mar = buckets["2026-03"]
        assert mar["count"] == 2
        assert mar["series"] == [{"key": "Espionage", "count": 2}]


class TestIncidentsTrendSector:
    @pytest.mark.asyncio
    async def test_sector_invariant_holds_per_bucket(
        self, session: AsyncSession
    ) -> None:
        # Mar 2026: 4 incidents - 2 Government, 1 Finance, 1 Energy.
        # All incidents have one sector in this fixture, so series sum
        # equals the distinct incident total. Multi-sector behavior is
        # pinned separately below.
        i_gov_a = await _seed_incident(
            session, title="i-gov-a", reported=dt.date(2026, 3, 2)
        )
        i_gov_b = await _seed_incident(
            session, title="i-gov-b", reported=dt.date(2026, 3, 8)
        )
        i_fin = await _seed_incident(
            session, title="i-fin", reported=dt.date(2026, 3, 12)
        )
        i_eng = await _seed_incident(
            session, title="i-eng", reported=dt.date(2026, 3, 20)
        )
        await _link_incident_sector(session, i_gov_a, "GOV")
        await _link_incident_sector(session, i_gov_b, "GOV")
        await _link_incident_sector(session, i_fin, "FIN")
        await _link_incident_sector(session, i_eng, "ENE")

        result = await compute_incidents_trend(session, group_by="sector")

        assert result["group_by"] == "sector"
        buckets = {b["month"]: b for b in result["buckets"]}
        assert set(buckets.keys()) == {"2026-03"}

        mar = buckets["2026-03"]
        series_total = sum(item["count"] for item in mar["series"])
        assert series_total == mar["count"], (
            f"sum(series.count)={series_total} != outer={mar['count']}; "
            f"series={mar['series']}"
        )
        # Outer count is 4 distinct incidents; this fixture has one sector
        # per incident, so slices also sum to 4.
        assert mar["count"] == 4
        assert sorted(mar["series"], key=lambda s: s["key"]) == [
            {"key": "ENE", "count": 1},
            {"key": "FIN", "count": 1},
            {"key": "GOV", "count": 2},
        ]

    @pytest.mark.asyncio
    async def test_sector_invariant_two_links(
        self, session: AsyncSession
    ) -> None:
        # Pin the multi-junction contract: ONE incident linked to TWO
        # sectors contributes +1 to the outer distinct incident count
        # and +1 to each series key. Series sum can exceed outer count.
        i_dual = await _seed_incident(
            session, title="i-dual", reported=dt.date(2026, 3, 5)
        )
        await _link_incident_sector(session, i_dual, "GOV")
        await _link_incident_sector(session, i_dual, "FIN")

        result = await compute_incidents_trend(session, group_by="sector")
        buckets = {b["month"]: b for b in result["buckets"]}
        mar = buckets["2026-03"]

        # ONE incident, so outer count is 1. It appears in two sector
        # slices, so sum(series) is 2.
        assert mar["count"] == 1
        series_total = sum(item["count"] for item in mar["series"])
        assert series_total == 2
        assert sorted(mar["series"], key=lambda s: s["key"]) == [
            {"key": "FIN", "count": 1},
            {"key": "GOV", "count": 1},
        ]


class TestIncidentsTrendUnknownBucket:
    @pytest.mark.asyncio
    async def test_unknown_bucket_absorbs_unjuncted_and_excludes_null_reported(
        self, session: AsyncSession
    ) -> None:
        # Mar 2026:
        #   - 1 incident with motivation "Espionage" (juncted)
        #   - 1 incident with NO motivation row (must land in "unknown")
        #   - 1 incident with reported=NULL (must NOT appear at all —
        #     date_trunc on NULL drops the row before bucketing)
        i_juncted = await _seed_incident(
            session, title="i-juncted", reported=dt.date(2026, 3, 1)
        )
        await _link_incident_motivation(session, i_juncted, "Espionage")

        await _seed_incident(
            session, title="i-unknown", reported=dt.date(2026, 3, 15)
        )  # no motivation link → "unknown"

        await _seed_incident(
            session, title="i-null-date", reported=None
        )  # reported IS NULL → excluded from aggregation entirely

        result = await compute_incidents_trend(session, group_by="motivation")

        # Only one bucket — the reported=None incident did NOT create
        # a NULL-month bucket.
        buckets = {b["month"]: b for b in result["buckets"]}
        assert set(buckets.keys()) == {"2026-03"}
        mar = buckets["2026-03"]

        # Outer count = 2 (juncted + unknown). The reported=None row is
        # excluded — if it were included, outer would be 3.
        assert mar["count"] == 2

        # Invariant: unknown slice carries the unjuncted incident.
        series_by_key = {item["key"]: item["count"] for item in mar["series"]}
        assert series_by_key == {
            "Espionage": 1,
            INCIDENTS_TREND_UNKNOWN_KEY: 1,
        }
        assert sum(series_by_key.values()) == mar["count"]


class TestIncidentsTrendDateFilters:
    @pytest.mark.asyncio
    async def test_date_filters_propagate_through_junction(
        self, session: AsyncSession
    ) -> None:
        # 3 incidents across 3 different months, each motivation-linked.
        # date_from/date_to should narrow the bucket set and carry through
        # the junction join — a filter dropped on the wrong side of the
        # JOIN here would silently leak rows.
        i_old = await _seed_incident(
            session, title="i-old", reported=dt.date(2024, 1, 15)
        )
        i_in = await _seed_incident(
            session, title="i-in", reported=dt.date(2026, 3, 10)
        )
        i_future = await _seed_incident(
            session, title="i-future", reported=dt.date(2027, 6, 5)
        )
        await _link_incident_motivation(session, i_old, "Espionage")
        await _link_incident_motivation(session, i_in, "Finance")
        await _link_incident_motivation(session, i_future, "Espionage")

        result = await compute_incidents_trend(
            session,
            group_by="motivation",
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 12, 31),
        )

        buckets = {b["month"]: b for b in result["buckets"]}
        assert set(buckets.keys()) == {"2026-03"}
        mar = buckets["2026-03"]
        assert mar["count"] == 1
        assert mar["series"] == [{"key": "Finance", "count": 1}]


# ===========================================================================
# compute_actor_network — PR 3 SNA co-occurrence (RED batch, T2 of plan v1.3)
# ===========================================================================
#
# All tests in this section currently fail because compute_actor_network is a
# stub (raises NotImplementedError). They become GREEN at T7 when the
# aggregator lands.
#
# References (docs/plans/actor-network-data.md):
#   L2  — wire shape {nodes, edges, cap_breached}
#   L3  — 3 edge classes (actor↔tool, actor↔sector, actor↔actor) with
#         COUNT(DISTINCT report_id|incidents.id) per pair
#   L4  — Step A (eligible set) → Step B (cap-aware) → Step C (tool/sector
#         cuts) → Step D (first-pass edges) → Step E (high-weight rescue
#         within eligible set) → Step F (final response)
#   L6  — empty contract: {nodes:[], edges:[], cap_breached:false}
#   L7  — group filter precedence onto L4 Steps; selected actors always
#         count toward top_n_actor; cap_breached = (len(S) > top_n_actor)
#   L13 — node ID kind-prefixed (actor:<group_id> / tool:<technique_id> /
#         sector:<sector_code>)


# ---------------------------------------------------------------------------
# Local helpers (incident_sources is required for the actor↔sector path
# (L3 path b chain: incident_sectors → incidents → incident_sources →
# reports → report_codenames → codenames → groups). The unit test file
# does not have a sibling helper for this junction, so we add one here.)
# ---------------------------------------------------------------------------


async def _link_incident_source(
    session: AsyncSession, incident_id: int, report_id: int
) -> None:
    await session.execute(
        sa.insert(incident_sources_table).values(
            incident_id=incident_id, report_id=report_id
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# TestActorNetworkEmpty — L6 empty contract
# ---------------------------------------------------------------------------


class TestActorNetworkEmpty:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_payload(
        self, session: AsyncSession
    ) -> None:
        # Plan L6: empty filter result returns the empty-but-well-formed
        # shape, not 404 / not exception. cap_breached defaults False.
        result = await compute_actor_network(session)
        assert result == {"nodes": [], "edges": [], "cap_breached": False}


# ---------------------------------------------------------------------------
# TestActorNetworkPopulated — L2 wire shape + L3 three edge classes
# + L13 kind-prefixed node IDs
# ---------------------------------------------------------------------------


class TestActorNetworkPopulated:
    @pytest.mark.asyncio
    async def test_actor_tool_edges_via_shared_report(
        self, session: AsyncSession
    ) -> None:
        # L3 path (a): actor↔tool through shared report_id.
        src = await _seed_source(session)
        g_lazarus = await _seed_group(session, "Lazarus")
        cn_lazarus = await _seed_codename(session, "Lazarus", g_lazarus)
        t_phishing = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )

        r1 = await _seed_report(
            session, title="r1", url="u1", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r1, cn_lazarus)
        await _link_report_technique(session, r1, t_phishing)

        result = await compute_actor_network(session)
        nodes = result["nodes"]
        edges = result["edges"]

        # Two nodes: Lazarus (actor) + Phishing (tool). Kind-prefixed IDs
        # per L13.
        assert {n["id"] for n in nodes} == {
            f"actor:{g_lazarus}",
            f"tool:{t_phishing}",
        }
        assert {(n["id"], n["kind"]) for n in nodes} == {
            (f"actor:{g_lazarus}", "actor"),
            (f"tool:{t_phishing}", "tool"),
        }

        # One edge between them, weight=1 (single shared report).
        assert len(edges) == 1
        edge = edges[0]
        assert {edge["source_id"], edge["target_id"]} == {
            f"actor:{g_lazarus}",
            f"tool:{t_phishing}",
        }
        assert edge["weight"] == 1
        assert result["cap_breached"] is False

    @pytest.mark.asyncio
    async def test_actor_sector_edges_via_full_chain(
        self, session: AsyncSession
    ) -> None:
        # L3 path (b): actor↔sector through the 5-table chain
        # (incident_sectors → incidents → incident_sources → reports →
        # report_codenames → codenames → groups).
        src = await _seed_source(session)
        g_lazarus = await _seed_group(session, "Lazarus")
        cn_lazarus = await _seed_codename(session, "Lazarus", g_lazarus)

        r1 = await _seed_report(
            session, title="r1", url="u1", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r1, cn_lazarus)
        i1 = await _seed_incident(
            session, title="i1", reported=dt.date(2026, 3, 6)
        )
        await _link_incident_source(session, i1, r1)
        await _link_incident_sector(session, i1, "GOV")

        result = await compute_actor_network(session)
        nodes = {n["id"]: n for n in result["nodes"]}
        edges = result["edges"]

        assert f"actor:{g_lazarus}" in nodes
        assert "sector:GOV" in nodes
        # Exactly one actor↔sector edge, weight=1 (single incident).
        sector_edges = [
            e for e in edges if "sector:" in (e["source_id"] + e["target_id"])
        ]
        assert len(sector_edges) == 1
        assert sector_edges[0]["weight"] == 1

    @pytest.mark.asyncio
    async def test_actor_actor_edges_via_self_join_unordered(
        self, session: AsyncSession
    ) -> None:
        # L3 path (c): two distinct groups co-mentioned on the same
        # report. Edges are unordered (ca.group_id < cb.group_id) so the
        # response has no (A,B)+(B,A) duplicates.
        src = await _seed_source(session)
        g_lazarus = await _seed_group(session, "Lazarus")
        g_kimsuky = await _seed_group(session, "Kimsuky")
        cn_lazarus = await _seed_codename(session, "Lazarus", g_lazarus)
        cn_kimsuky = await _seed_codename(session, "Kimsuky", g_kimsuky)

        r1 = await _seed_report(
            session, title="r1", url="u1", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r1, cn_lazarus)
        await _link_report_codename(session, r1, cn_kimsuky)

        result = await compute_actor_network(session)
        actor_actor_edges = [
            e for e in result["edges"]
            if e["source_id"].startswith("actor:")
            and e["target_id"].startswith("actor:")
        ]
        # Exactly one unordered edge, NOT two (A,B) + (B,A).
        assert len(actor_actor_edges) == 1
        ids = {actor_actor_edges[0]["source_id"], actor_actor_edges[0]["target_id"]}
        assert ids == {f"actor:{g_lazarus}", f"actor:{g_kimsuky}"}
        assert actor_actor_edges[0]["weight"] == 1

    @pytest.mark.asyncio
    async def test_degree_centrality_matches_eligible_edge_count(
        self, session: AsyncSession
    ) -> None:
        # Plan L2: degree is the count of incident edges per node.
        src = await _seed_source(session)
        g = await _seed_group(session, "Lazarus")
        cn = await _seed_codename(session, "Lazarus", g)
        t1 = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        t2 = await _seed_technique(
            session, mitre_id="T1059", name="Cmd", tactic="TA0002"
        )

        # Two reports, each linking the actor to one tool.
        r1 = await _seed_report(
            session, title="r1", url="u1", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        r2 = await _seed_report(
            session, title="r2", url="u2", source_id=src,
            published=dt.date(2026, 3, 6),
        )
        await _link_report_codename(session, r1, cn)
        await _link_report_codename(session, r2, cn)
        await _link_report_technique(session, r1, t1)
        await _link_report_technique(session, r2, t2)

        result = await compute_actor_network(session)
        nodes = {n["id"]: n for n in result["nodes"]}
        # Actor connects to BOTH tools → degree 2. Each tool connects to
        # the actor only → degree 1.
        assert nodes[f"actor:{g}"]["degree"] == 2
        assert nodes[f"tool:{t1}"]["degree"] == 1
        assert nodes[f"tool:{t2}"]["degree"] == 1


# ---------------------------------------------------------------------------
# TestActorNetworkSelfJoinInflation — L3 COUNT(DISTINCT) regression
# ---------------------------------------------------------------------------


class TestActorNetworkSelfJoinInflation:
    @pytest.mark.asyncio
    async def test_actor_tool_same_group_two_codenames_same_report_weight_one(
        self, session: AsyncSession
    ) -> None:
        # Codex r4 HIGH (L3-DISTINCT-COVERAGE) fold: prior actor↔tool
        # test used 1 codename + 1 technique on 1 report, so COUNT(*) ==
        # COUNT(DISTINCT report_id) == 1 — non-discriminating.
        #
        # This test specifically pins the COUNT(DISTINCT report_id) rule
        # for actor↔tool (L3 path a). Two codenames for the same group
        # are linked to the SAME report + SAME technique. Naive grouped
        # COUNT(*) over `report_codenames JOIN report_techniques`
        # yields 2 join rows (cn_a×t + cn_b×t). COUNT(DISTINCT
        # report_id) collapses to 1.
        src = await _seed_source(session)
        g_lazarus = await _seed_group(session, "Lazarus")
        cn_l1 = await _seed_codename(session, "Lazarus", g_lazarus)
        cn_l2 = await _seed_codename(session, "APT38", g_lazarus)
        t = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        r = await _seed_report(
            session, title="r1", url="u1", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        # Both codenames + the technique on the same report.
        await _link_report_codename(session, r, cn_l1)
        await _link_report_codename(session, r, cn_l2)
        await _link_report_technique(session, r, t)

        result = await compute_actor_network(session)
        actor_tool_edges = [
            e for e in result["edges"]
            if (e["source_id"].startswith("actor:") and
                e["target_id"].startswith("tool:"))
            or (e["source_id"].startswith("tool:") and
                e["target_id"].startswith("actor:"))
        ]
        # Exactly ONE edge (Lazarus↔Phishing), weight=1 (single report).
        # Naive COUNT(*) would give 2 (one per codename row).
        assert len(actor_tool_edges) == 1
        assert actor_tool_edges[0]["weight"] == 1

    @pytest.mark.asyncio
    async def test_actor_sector_one_incident_two_sources_weight_one(
        self, session: AsyncSession
    ) -> None:
        # Codex r4 HIGH (L3-DISTINCT-COVERAGE) fold: prior actor↔sector
        # test used 1 incident + 1 incident_source, so COUNT(*) ==
        # COUNT(DISTINCT incidents.id) == 1 — non-discriminating.
        #
        # This test pins COUNT(DISTINCT incidents.id) for actor↔sector
        # (L3 path b). One incident has TWO sources (two different
        # reports), both reports carry the SAME group's codename, the
        # incident has ONE sector. Naive COUNT(*) along the 5-table
        # chain yields 2 (incident paired with each source separately).
        # COUNT(DISTINCT incidents.id) collapses to 1.
        src = await _seed_source(session)
        g = await _seed_group(session, "Lazarus")
        cn = await _seed_codename(session, "Lazarus", g)

        r1 = await _seed_report(
            session, title="r1", url="u1", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        r2 = await _seed_report(
            session, title="r2", url="u2", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r1, cn)
        await _link_report_codename(session, r2, cn)

        i = await _seed_incident(
            session, title="i", reported=dt.date(2026, 3, 6)
        )
        # Same incident sourced by both reports.
        await _link_incident_source(session, i, r1)
        await _link_incident_source(session, i, r2)
        await _link_incident_sector(session, i, "GOV")

        result = await compute_actor_network(session)
        actor_sector_edges = [
            e for e in result["edges"]
            if (e["source_id"].startswith("actor:") and
                e["target_id"].startswith("sector:"))
            or (e["source_id"].startswith("sector:") and
                e["target_id"].startswith("actor:"))
        ]
        # Exactly ONE edge (Lazarus↔GOV), weight=1 (single incident).
        # Naive COUNT(*) would give 2 (one per incident_source row).
        assert len(actor_sector_edges) == 1
        assert actor_sector_edges[0]["weight"] == 1

    @pytest.mark.asyncio
    async def test_two_codenames_same_group_same_report_yield_weight_one(
        self, session: AsyncSession
    ) -> None:
        # Codex r1 HIGH: a self-join over report_codenames inflates the
        # weight if the same group has two codenames on the same report
        # (cartesian product = 4 rows, naive count would give 2 or 4).
        # COUNT(DISTINCT report_id) per pair must give 1.
        src = await _seed_source(session)
        g_lazarus = await _seed_group(session, "Lazarus")
        g_kimsuky = await _seed_group(session, "Kimsuky")
        # Two codenames for Lazarus + one for Kimsuky.
        cn_l1 = await _seed_codename(session, "Lazarus", g_lazarus)
        cn_l2 = await _seed_codename(session, "APT38", g_lazarus)
        cn_k = await _seed_codename(session, "Kimsuky", g_kimsuky)

        r1 = await _seed_report(
            session, title="r1", url="u1", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        # Both Lazarus codenames + the Kimsuky codename on r1.
        await _link_report_codename(session, r1, cn_l1)
        await _link_report_codename(session, r1, cn_l2)
        await _link_report_codename(session, r1, cn_k)

        result = await compute_actor_network(session)
        actor_actor_edges = [
            e for e in result["edges"]
            if e["source_id"].startswith("actor:")
            and e["target_id"].startswith("actor:")
        ]
        # Exactly ONE edge (Lazarus↔Kimsuky), weight=1 (single report).
        # Naive cartesian would yield 2 edges (one per Lazarus codename)
        # or weight=2/4. COUNT(DISTINCT) collapses to 1.
        assert len(actor_actor_edges) == 1
        assert actor_actor_edges[0]["weight"] == 1


# ---------------------------------------------------------------------------
# TestActorNetworkNullGroupId — L3 codenames.group_id IS NOT NULL filter
# ---------------------------------------------------------------------------


class TestActorNetworkNullGroupId:
    @pytest.mark.asyncio
    async def test_codenames_with_null_group_id_excluded(
        self, session: AsyncSession
    ) -> None:
        # Plan L3: codenames.group_id is nullable (codenames may exist
        # before being attributed to a group). The aggregator MUST
        # exclude null-group codenames so the actor node-id never points
        # at a non-existent group.
        src = await _seed_source(session)
        # No groups seeded: orphan codename.
        result_orphan = await session.execute(
            sa.insert(codenames_table)
            .values(name="OrphanCodename", group_id=None)
            .returning(codenames_table.c.id)
        )
        cn_orphan = int(result_orphan.scalar_one())
        await session.commit()

        t = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        r = await _seed_report(
            session, title="r", url="u", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r, cn_orphan)
        await _link_report_technique(session, r, t)

        result = await compute_actor_network(session)
        # Codex r4 MEDIUM fold (L3-NULL-GROUP): assert the FULL empty
        # contract, not just the absence of actor nodes. Per L3, an
        # actor↔tool edge requires a non-null codenames.group_id, so
        # this fixture has zero eligible edges. Per L7(c), tools/sectors
        # are only included when they have eligible edges. Therefore
        # the response must be the canonical empty contract — no actor
        # nodes, no orphan tool nodes, no edges.
        assert result == {
            "nodes": [],
            "edges": [],
            "cap_breached": False,
        }


# ---------------------------------------------------------------------------
# TestActorNetworkFilters — date filter + group filter pass-through
# ---------------------------------------------------------------------------


class TestActorNetworkFilters:
    @pytest.mark.asyncio
    async def test_date_filter_applies_to_reports_published(
        self, session: AsyncSession
    ) -> None:
        # Plan L3: filter window applies on reports.published for paths
        # (a) actor↔tool and (c) actor↔actor.
        src = await _seed_source(session)
        g = await _seed_group(session, "Lazarus")
        cn = await _seed_codename(session, "Lazarus", g)
        t = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        r_old = await _seed_report(
            session, title="r-old", url="u-old", source_id=src,
            published=dt.date(2024, 1, 15),
        )
        r_in = await _seed_report(
            session, title="r-in", url="u-in", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r_old, cn)
        await _link_report_codename(session, r_in, cn)
        await _link_report_technique(session, r_old, t)
        await _link_report_technique(session, r_in, t)

        result = await compute_actor_network(
            session,
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 12, 31),
        )
        # Only the in-window report should contribute → weight=1.
        edges = result["edges"]
        assert len(edges) == 1
        assert edges[0]["weight"] == 1

    @pytest.mark.asyncio
    async def test_date_filter_applies_to_incidents_reported(
        self, session: AsyncSession
    ) -> None:
        # Plan L3: filter window applies on incidents.reported for path
        # (b) actor↔sector.
        src = await _seed_source(session)
        g = await _seed_group(session, "Lazarus")
        cn = await _seed_codename(session, "Lazarus", g)

        r = await _seed_report(
            session, title="r", url="u", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r, cn)
        # Two incidents reporting on the same actor — one in-window, one
        # out-of-window. Sector edge weight should reflect only in-window.
        i_old = await _seed_incident(
            session, title="i-old", reported=dt.date(2024, 1, 15)
        )
        i_in = await _seed_incident(
            session, title="i-in", reported=dt.date(2026, 3, 6)
        )
        await _link_incident_source(session, i_old, r)
        await _link_incident_source(session, i_in, r)
        await _link_incident_sector(session, i_old, "FIN")
        await _link_incident_sector(session, i_in, "GOV")

        result = await compute_actor_network(
            session,
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 12, 31),
        )
        sector_edges = [
            e for e in result["edges"]
            if "sector:" in (e["source_id"] + e["target_id"])
        ]
        sector_targets = {
            e["source_id"] for e in sector_edges
        } | {e["target_id"] for e in sector_edges}
        # Only GOV (in-window) survives; FIN (out-of-window) dropped.
        assert "sector:GOV" in sector_targets
        assert "sector:FIN" not in sector_targets

    @pytest.mark.asyncio
    async def test_vacuous_window_returns_empty_no_exception(
        self, session: AsyncSession
    ) -> None:
        # Plan L6 + L10 + Codex r2 fold: date_from > date_to is NOT a
        # validator-enforced 422 (matches existing analytics convention);
        # it produces empty-200. The aggregator must not raise on an
        # inverted window.
        src = await _seed_source(session)
        g = await _seed_group(session, "Lazarus")
        cn = await _seed_codename(session, "Lazarus", g)
        t = await _seed_technique(
            session, mitre_id="T1566", name="Phishing", tactic="TA0001"
        )
        r = await _seed_report(
            session, title="r", url="u", source_id=src,
            published=dt.date(2026, 3, 5),
        )
        await _link_report_codename(session, r, cn)
        await _link_report_technique(session, r, t)

        result = await compute_actor_network(
            session,
            date_from=dt.date(2026, 12, 31),
            date_to=dt.date(2026, 1, 1),
        )
        assert result == {"nodes": [], "edges": [], "cap_breached": False}


# ---------------------------------------------------------------------------
# TestActorNetworkGroupCap — L4 Step B + L7(b) cap-aware semantics
# ---------------------------------------------------------------------------


class TestActorNetworkGroupCap:
    """L4 Step B: selected actors always count toward top_n_actor.

    Three scenarios pinned by the plan AC #12:
      A — group_id=[rank-30 actor] + top_n_actor=25 → 25 actors
          (rank-30 selected + top 24 by degree, displacing rank-25).
          cap_breached = false.
      B — group_id=[all 30 actors] + top_n_actor=25 → 30 actors
          (all selected, zero non-selected). cap_breached = true.
      C — group_id=[] + top_n_actor=25 → top 25 by degree.
          cap_breached = false.
    """

    @staticmethod
    async def _seed_30_actors_with_descending_degree(
        session: AsyncSession,
    ) -> list[int]:
        """Seed 30 actors with truly distinct degrees (Codex r4 CRITICAL fold).

        Actor i (1-indexed) connects to ``31 - i`` DISTINCT techniques on a
        single report. So actor i has degree ``31 - i`` (count of distinct
        connected nodes), not weighted-degree:

            actor 1  → degree 30 (techniques[0..29])
            actor 2  → degree 29 (techniques[0..28])
            ...
            actor 30 → degree 1  (techniques[0])

        Rationale: an earlier draft used a SHARED tool with N reports per
        actor — Codex r4 flagged that as "weight, not degree", which would
        green-light an incorrect weighted-degree implementation. Distinct
        tools make the per-actor degree count unambiguous.

        Returns the list of group_ids in degree-descending order
        (group_ids[0] = highest degree, group_ids[29] = lowest).
        """
        src = await _seed_source(session)
        # 30 distinct techniques pre-seeded so actor i can connect to a
        # progressively shrinking subset.
        techniques: list[int] = []
        for k in range(1, 31):
            t = await _seed_technique(
                session,
                mitre_id=f"T{k:04d}",
                name=f"tool-{k:02d}",
                tactic="TA0001",
            )
            techniques.append(t)

        group_ids: list[int] = []
        for i in range(1, 31):
            g = await _seed_group(session, f"actor-{i:02d}")
            cn = await _seed_codename(session, f"cn-{i:02d}", g)
            r = await _seed_report(
                session,
                title=f"r-{i:02d}",
                url=f"u-{i:02d}",
                source_id=src,
                published=dt.date(2026, 3, 5),
            )
            await _link_report_codename(session, r, cn)
            # Actor i connects to techniques[0..(30 - i)] = (31 - i) tools.
            for k in range(31 - i):
                await _link_report_technique(session, r, techniques[k])
            group_ids.append(g)
        return group_ids

    @pytest.mark.asyncio
    async def test_scenario_a_one_selected_displaces_one_non_selected(
        self, session: AsyncSession
    ) -> None:
        # Scenario A (L4 Step B + L7(b)): group_id=[rank-30] +
        # top_n_actor=25 → 25 actors, cap_breached=false. The selected
        # actor counts toward the cap and displaces rank-25 — which
        # is the lowest-degree non-selected actor that would otherwise
        # have made the cut.
        #
        # Filler-ranking interpretation pinned here: when filling the
        # non-selected slots, the aggregator ranks candidates by
        # **GLOBAL degree** (not eligible-edge-set degree). Rationale:
        # "show the selected actor in context of the most active
        # overall actors" makes more analyst sense than "show only
        # actors with eligible edges to the selection". L4 Step B's
        # "by degree desc" without qualifier resolves to global degree
        # here; eligible-only is reserved for the explicit S filter.
        group_ids = await self._seed_30_actors_with_descending_degree(
            session
        )
        rank_30_group = group_ids[29]  # 0-indexed; rank 30 by degree

        result = await compute_actor_network(
            session, group_ids=[rank_30_group], top_n_actor=25
        )
        actor_nodes = [
            n for n in result["nodes"] if n["kind"] == "actor"
        ]
        actor_ids = {n["id"] for n in actor_nodes}
        # Exactly 25 actors total. Selected MUST be present.
        assert len(actor_nodes) == 25
        assert f"actor:{rank_30_group}" in actor_ids
        # rank-25 (the displaced one) MUST be absent. Top 1..24 + the
        # selected rank-30 = 25 total.
        rank_25_group = group_ids[24]
        assert f"actor:{rank_25_group}" not in actor_ids
        assert result["cap_breached"] is False

    @pytest.mark.asyncio
    async def test_scenario_b_all_selected_breaches_cap(
        self, session: AsyncSession
    ) -> None:
        # Scenario B: all 30 selected + top_n_actor=25 → 30 actors,
        # cap_breached=true. No non-selected appear (zero filling slots).
        group_ids = await self._seed_30_actors_with_descending_degree(
            session
        )

        result = await compute_actor_network(
            session, group_ids=list(group_ids), top_n_actor=25
        )
        actor_nodes = [
            n for n in result["nodes"] if n["kind"] == "actor"
        ]
        assert len(actor_nodes) == 30
        actor_ids = {n["id"] for n in actor_nodes}
        for gid in group_ids:
            assert f"actor:{gid}" in actor_ids
        assert result["cap_breached"] is True

    @pytest.mark.asyncio
    async def test_scenario_c_no_selection_uses_pure_degree_cut(
        self, session: AsyncSession
    ) -> None:
        # Scenario C: group_id=[] + top_n_actor=25 → top 25 by degree,
        # cap_breached=false.
        group_ids = await self._seed_30_actors_with_descending_degree(
            session
        )

        result = await compute_actor_network(session, top_n_actor=25)
        actor_nodes = [
            n for n in result["nodes"] if n["kind"] == "actor"
        ]
        actor_ids = {n["id"] for n in actor_nodes}
        assert len(actor_nodes) == 25
        # Top 25 by degree (group_ids[0..24]) present; bottom 5 absent.
        for gid in group_ids[:25]:
            assert f"actor:{gid}" in actor_ids
        for gid in group_ids[25:]:
            assert f"actor:{gid}" not in actor_ids
        assert result["cap_breached"] is False


# ---------------------------------------------------------------------------
# TestActorNetworkRescue — L4 Step E high-weight rescue within eligible set
# ---------------------------------------------------------------------------


class TestActorNetworkRescue:
    @pytest.mark.asyncio
    async def test_high_weight_edge_rescues_endpoint_that_missed_cut(
        self, session: AsyncSession
    ) -> None:
        # L4 Step E: top 5 edges by weight in the eligible edge set are
        # always retained. If one endpoint missed the per-kind cut, it
        # is added back as a rescued node.
        #
        # Codex r4 CRITICAL fold: prior fixture used a SHARED tool with
        # repeated reports per actor — that produces weight, not degree.
        # Redesigned fixture uses DISTINCT tools per strong actor so
        # degree counts (count of distinct connected nodes) are unambiguous.
        #
        # Fixture: top_n_actor=2, top_n_tool=1.
        #   strong-1: connects to 5 DISTINCT tools (T0001..T0005) →
        #             degree 5, each edge weight 1.
        #   strong-2: connects to 5 DIFFERENT distinct tools
        #             (T0006..T0010) → degree 5, each edge weight 1.
        #   weak:     connects to 1 tool (T9999, the rescue target),
        #             via 10 reports → degree 1, edge weight 10.
        #   All 11 tools have degree 1 (each connects to one actor).
        #
        # Expected algorithm result:
        #   Step B (top_n_actor=2): strong-1 + strong-2 win (degree 5
        #     each). weak (degree 1) misses.
        #   Step C (top_n_tool=1): all tools tied at degree 1; tiebreak
        #     by label asc → T0001 wins. T9999 (rescue) misses.
        #   Step D first-pass: only strong-1↔T0001 (both in cut) → 1 edge.
        #   Step E rescue: top 5 by weight. weak↔T9999 has weight 10
        #     (uniquely highest); next 4 are weight-1 edges (any 4 of
        #     the 10 strong↔tool weight-1 edges). Each top-5 edge with
        #     an out-of-cut endpoint rescues that endpoint.
        #     - weak↔T9999 rescues both weak AND T9999.
        #     - 4 weight-1 strong↔tool edges rescue 4 tools (their
        #       strong-actor endpoint is already in cut).
        #
        # Test asserts only the rescue contract for weak + T9999 + the
        # high-weight edge — additional rescued tools are allowed
        # (response may carry up to 5 extra rescued nodes per L4 hard
        # upper bound).
        src = await _seed_source(session)
        g_strong_1 = await _seed_group(session, "strong-1")
        g_strong_2 = await _seed_group(session, "strong-2")
        g_weak = await _seed_group(session, "weak")
        cn_s1 = await _seed_codename(session, "cn-s1", g_strong_1)
        cn_s2 = await _seed_codename(session, "cn-s2", g_strong_2)
        cn_w = await _seed_codename(session, "cn-w", g_weak)

        # Distinct tools so degree (= distinct connected nodes) varies.
        t_s1_tools = []
        for k in range(5):
            tid = await _seed_technique(
                session,
                mitre_id=f"T{k + 1:04d}",  # T0001..T0005
                name=f"main-s1-{k}",
                tactic="TA0001",
            )
            t_s1_tools.append(tid)
        t_s2_tools = []
        for k in range(5):
            tid = await _seed_technique(
                session,
                mitre_id=f"T{k + 6:04d}",  # T0006..T0010
                name=f"main-s2-{k}",
                tactic="TA0001",
            )
            t_s2_tools.append(tid)
        # T9999 is alphabetically last so the tiebreak rule for
        # top_n_tool=1 (label asc) keeps it OUT of the cut.
        t_rescue = await _seed_technique(
            session, mitre_id="T9999", name="rescue", tactic="TA0002"
        )

        # strong-1: 5 distinct tools, one report per (cn_s1, tool) pair.
        for k, tid in enumerate(t_s1_tools):
            r = await _seed_report(
                session, title=f"r-s1-{k}", url=f"u-s1-{k}",
                source_id=src, published=dt.date(2026, 3, 5),
            )
            await _link_report_codename(session, r, cn_s1)
            await _link_report_technique(session, r, tid)

        # strong-2: 5 different distinct tools.
        for k, tid in enumerate(t_s2_tools):
            r = await _seed_report(
                session, title=f"r-s2-{k}", url=f"u-s2-{k}",
                source_id=src, published=dt.date(2026, 3, 5),
            )
            await _link_report_codename(session, r, cn_s2)
            await _link_report_technique(session, r, tid)

        # weak: 1 tool (T9999) via 10 reports → weight=10 on a single
        # actor-tool pair.
        for i in range(10):
            r = await _seed_report(
                session, title=f"r-w-{i}", url=f"u-w-{i}",
                source_id=src, published=dt.date(2026, 3, 5),
            )
            await _link_report_codename(session, r, cn_w)
            await _link_report_technique(session, r, t_rescue)

        result = await compute_actor_network(
            session, top_n_actor=2, top_n_tool=1
        )
        nodes_by_id = {n["id"]: n for n in result["nodes"]}
        node_ids = set(nodes_by_id.keys())

        # Strong actors made the per-kind cut (top_n_actor=2 + degree 5
        # each beats weak's degree 1).
        assert f"actor:{g_strong_1}" in node_ids
        assert f"actor:{g_strong_2}" in node_ids
        # Strong actor degrees match the seed (5 distinct connected tools).
        assert nodes_by_id[f"actor:{g_strong_1}"]["degree"] == 5
        assert nodes_by_id[f"actor:{g_strong_2}"]["degree"] == 5
        # Weak actor was NOT in the top-2 by degree (degree 1 vs 5), but
        # the weight-10 edge rescued it via L4 Step E.
        assert f"actor:{g_weak}" in node_ids
        assert nodes_by_id[f"actor:{g_weak}"]["degree"] == 1
        # T9999 (rescue tool) didn't win top_n_tool=1 (alphabetical
        # tiebreak puts T0001 first), but its high-weight edge rescues it.
        assert f"tool:{t_rescue}" in node_ids
        # The rescue edge between weak and T9999 survives, weight=10.
        rescue_edges = [
            e for e in result["edges"]
            if {e["source_id"], e["target_id"]}
            == {f"actor:{g_weak}", f"tool:{t_rescue}"}
        ]
        assert len(rescue_edges) == 1
        assert rescue_edges[0]["weight"] == 10
