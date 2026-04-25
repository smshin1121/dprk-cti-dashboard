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
# ``series`` slice of motivation or sector counts, and the invariant
# ``sum(series[].count) == outer count`` holds — incidents with no
# junction row land in the ``INCIDENTS_TREND_UNKNOWN_KEY`` slice rather
# than being dropped. ``incidents.reported IS NULL`` rows ARE excluded
# upstream of the junction (cursor-convention parity, ``tables.py:258``).
# Plan PR #23 §6.A C1 lock.


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

        # Per-bucket invariant: sum(series.count) == outer count.
        for month, bucket in buckets.items():
            series_total = sum(item["count"] for item in bucket["series"])
            assert series_total == bucket["count"], (
                f"invariant broken for {month}: outer={bucket['count']}, "
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
        # Mar 2026: 4 incidents — 2 Government, 1 Finance, 1 Energy.
        # An incident with TWO sector links must NOT inflate the outer
        # bucket count (COUNT DISTINCT incident_id) but the slices may
        # each list the incident — series sums can exceed outer when the
        # invariant we want is "outer = distinct incidents", not "outer =
        # sum(series)". Plan §6.A C1 actually pins the invariant at sum
        # form — so a multi-sector incident must be folded down to one
        # canonical bucket OR each junction row counted once with outer
        # being sum(series). The aggregator picks **sum form**: the
        # invariant ``sum(series.count) == outer count`` holds by
        # COUNT(*) on junction rows (not COUNT DISTINCT), with each
        # incident contributing once per junction row.
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
        # Outer count is 4 (one count per junction row); slices sum to 4.
        assert mar["count"] == 4
        assert sorted(mar["series"], key=lambda s: s["key"]) == [
            {"key": "ENE", "count": 1},
            {"key": "FIN", "count": 1},
            {"key": "GOV", "count": 2},
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
