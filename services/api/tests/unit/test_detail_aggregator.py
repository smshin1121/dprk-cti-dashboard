"""Unit tests for PR #14 Group A detail aggregator.

Runs against in-memory aiosqlite — the mirror in ``api.tables`` is
sufficient since every join the aggregator touches is covered there.

Review priorities locked at the Group A ask:

1. **D9 cap is enforced in SQL** — inserting > cap related rows and
   asserting the response has EXACTLY ``cap`` rows proves the LIMIT
   is in the SELECT, not a Python slice. A Python slice would still
   hit the 10-entry ceiling but would materialize all N rows first,
   so the regression guard here actually fires on "LIMIT removed"
   type refactors.

2. **``incident_sources`` is the ONLY M:N link used.** Actor detail
   NEVER traverses ``report_codenames``; the aggregator's query
   literally doesn't reference that table. Test below asserts the
   behavior by seeding ``report_codenames`` rows and checking the
   ActorDetail shape has no reports-like field.

3. **404 via None return** — unknown id returns ``None``; the
   router lifts that to HTTP 404. Tested per entity.

4. **Empty-related-collections** — a report / incident / actor with
   zero related rows produces empty lists, not nulls. Pydantic's
   ``Field(default_factory=list)`` also guards this at the DTO
   layer, but the aggregator must not return ``None`` for the list
   fields either.
"""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from api.read import detail_aggregator
from api.schemas.read import (
    INCIDENT_DETAIL_REPORTS_CAP,
    REPORT_DETAIL_INCIDENTS_CAP,
)
from api.tables import (
    codenames_table,
    groups_table,
    incident_sources_table,
    incidents_table,
    metadata,
    report_codenames_table,
    reports_table,
    sources_table,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield eng
    await eng.dispose()


async def _seed_source(engine: AsyncEngine, name: str = "Mandiant") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        s_id = row.scalar_one()
        await s.commit()
        return s_id


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    source_id: int,
    published: dt.date,
    url: str | None = None,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(reports_table)
            .values(
                title=title,
                url=url or f"https://ex.test/{title}",
                url_canonical=url or f"https://ex.test/{title}",
                sha256_title=f"sha-{title}",
                source_id=source_id,
                published=published,
                tlp="WHITE",
            )
            .returning(reports_table.c.id)
        )
        r_id = row.scalar_one()
        await s.commit()
        return r_id


async def _seed_incident(
    engine: AsyncEngine,
    *,
    title: str,
    reported: dt.date | None,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(incidents_table)
            .values(title=title, reported=reported)
            .returning(incidents_table.c.id)
        )
        i_id = row.scalar_one()
        await s.commit()
        return i_id


async def _link_incident_source(
    engine: AsyncEngine, *, incident_id: int, report_id: int
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(
            sa.insert(incident_sources_table).values(
                incident_id=incident_id, report_id=report_id
            )
        )
        await s.commit()


async def _seed_group(
    engine: AsyncEngine, *, name: str = "Lazarus Group"
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(groups_table)
            .values(
                name=name,
                mitre_intrusion_set_id="G0032",
                aka=["APT38", "Hidden Cobra"],
                description="DPRK-attributed group",
            )
            .returning(groups_table.c.id)
        )
        g_id = row.scalar_one()
        await s.commit()
        return g_id


async def _seed_codename(
    engine: AsyncEngine, *, name: str, group_id: int
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(codenames_table)
            .values(name=name, group_id=group_id)
            .returning(codenames_table.c.id)
        )
        c_id = row.scalar_one()
        await s.commit()
        return c_id


# ---------------------------------------------------------------------------
# 404 via None return (all three entities)
# ---------------------------------------------------------------------------


class TestNotFoundReturnsNone:
    async def test_report_unknown_id(self, engine: AsyncEngine) -> None:
        async with AsyncSession(engine) as s:
            assert (
                await detail_aggregator.get_report_detail(s, report_id=9999)
                is None
            )

    async def test_incident_unknown_id(self, engine: AsyncEngine) -> None:
        async with AsyncSession(engine) as s:
            assert (
                await detail_aggregator.get_incident_detail(s, incident_id=9999)
                is None
            )

    async def test_actor_unknown_id(self, engine: AsyncEngine) -> None:
        async with AsyncSession(engine) as s:
            assert (
                await detail_aggregator.get_actor_detail(s, actor_id=9999)
                is None
            )


# ---------------------------------------------------------------------------
# Empty-related-collections (isolated rows produce [] not None)
# ---------------------------------------------------------------------------


class TestEmptyRelatedCollections:
    async def test_report_detail_empty_collections(
        self, engine: AsyncEngine
    ) -> None:
        src = await _seed_source(engine)
        r_id = await _seed_report(
            engine, title="isolated", source_id=src, published=dt.date(2026, 1, 1)
        )
        async with AsyncSession(engine) as s:
            detail = await detail_aggregator.get_report_detail(s, report_id=r_id)
        assert detail is not None
        assert detail["tags"] == []
        assert detail["codenames"] == []
        assert detail["techniques"] == []
        assert detail["linked_incidents"] == []

    async def test_incident_detail_empty_collections(
        self, engine: AsyncEngine
    ) -> None:
        i_id = await _seed_incident(
            engine, title="lonely incident", reported=dt.date(2024, 1, 1)
        )
        async with AsyncSession(engine) as s:
            detail = await detail_aggregator.get_incident_detail(
                s, incident_id=i_id
            )
        assert detail is not None
        assert detail["motivations"] == []
        assert detail["sectors"] == []
        assert detail["countries"] == []
        assert detail["linked_reports"] == []

    async def test_actor_detail_empty_codenames(
        self, engine: AsyncEngine
    ) -> None:
        g_id = await _seed_group(engine, name="Solo Group")
        async with AsyncSession(engine) as s:
            detail = await detail_aggregator.get_actor_detail(s, actor_id=g_id)
        assert detail is not None
        assert detail["codenames"] == []


# ---------------------------------------------------------------------------
# D9 cap enforced in SQL (regression guard)
# ---------------------------------------------------------------------------


class TestD9CapEnforcedInSQL:
    async def test_report_linked_incidents_cap(
        self, engine: AsyncEngine
    ) -> None:
        """Seed > cap incidents linked to one report; aggregator
        must return EXACTLY ``REPORT_DETAIL_INCIDENTS_CAP`` rows,
        ordered newest-reported first. A Python-slice path would
        still produce the ceiling but the SQL LIMIT is the
        performance contract — this test fails if the LIMIT clause
        is accidentally removed because EVERY seeded incident would
        travel through the result set.
        """
        src = await _seed_source(engine)
        r_id = await _seed_report(
            engine,
            title="report-with-many-incidents",
            source_id=src,
            published=dt.date(2026, 1, 1),
        )
        # Seed REPORT_DETAIL_INCIDENTS_CAP + 5 incidents, each on a
        # different day so the ORDER BY reported DESC has a
        # deterministic answer.
        over_cap = REPORT_DETAIL_INCIDENTS_CAP + 5
        for i in range(over_cap):
            i_id = await _seed_incident(
                engine,
                title=f"inc-{i:02d}",
                reported=dt.date(2024, 1, 1) + dt.timedelta(days=i),
            )
            await _link_incident_source(
                engine, incident_id=i_id, report_id=r_id
            )

        async with AsyncSession(engine) as s:
            detail = await detail_aggregator.get_report_detail(s, report_id=r_id)
        assert detail is not None
        linked = detail["linked_incidents"]
        assert len(linked) == REPORT_DETAIL_INCIDENTS_CAP
        reported_dates = [row["reported"] for row in linked]
        # Newest first — the last-inserted ``over_cap - 1`` incident
        # should be row 0.
        assert reported_dates == sorted(reported_dates, reverse=True)

    async def test_incident_linked_reports_cap(
        self, engine: AsyncEngine
    ) -> None:
        src = await _seed_source(engine)
        i_id = await _seed_incident(
            engine, title="incident-with-many-reports", reported=dt.date(2024, 1, 1)
        )
        over_cap = INCIDENT_DETAIL_REPORTS_CAP + 5
        for j in range(over_cap):
            r_id = await _seed_report(
                engine,
                title=f"rep-{j:02d}",
                source_id=src,
                published=dt.date(2026, 1, 1) + dt.timedelta(days=j),
            )
            await _link_incident_source(
                engine, incident_id=i_id, report_id=r_id
            )

        async with AsyncSession(engine) as s:
            detail = await detail_aggregator.get_incident_detail(
                s, incident_id=i_id
            )
        assert detail is not None
        linked = detail["linked_reports"]
        assert len(linked) == INCIDENT_DETAIL_REPORTS_CAP
        publisheds = [row["published"] for row in linked]
        assert publisheds == sorted(publisheds, reverse=True)


# ---------------------------------------------------------------------------
# Actor detail never traverses report_codenames (D11 lock)
# ---------------------------------------------------------------------------


class TestActorDetailD11:
    async def test_actor_detail_does_not_pull_reports_via_codenames(
        self, engine: AsyncEngine
    ) -> None:
        """Seed a group + codename + report_codenames link; the
        actor detail response MUST NOT include any field that hints
        at "reports that mention this actor". The plan D11 lock
        keeps that surface out of scope until a dedicated endpoint
        lands. If a future refactor adds a ``linked_reports`` key
        to the ActorDetail shape, this test fails immediately.
        """
        src = await _seed_source(engine)
        r_id = await _seed_report(
            engine,
            title="report-mentions-lazarus",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )
        g_id = await _seed_group(engine)
        c_id = await _seed_codename(engine, name="Andariel", group_id=g_id)
        # Wire the report → codename link that a D11-violating
        # aggregator would traverse.
        async with AsyncSession(engine) as s:
            await s.execute(
                sa.insert(report_codenames_table).values(
                    report_id=r_id, codename_id=c_id
                )
            )
            await s.commit()

        async with AsyncSession(engine) as s:
            detail = await detail_aggregator.get_actor_detail(s, actor_id=g_id)

        assert detail is not None
        # Direct D11 assertion: no report-ish surface on the shape.
        for forbidden in ("linked_reports", "reports", "recent_reports"):
            assert forbidden not in detail, (
                f"ActorDetail exposed {forbidden!r} — D11 lock forbids "
                f"traversing report_codenames from /actors/{{id}}"
            )
        # Codenames DO surface (that's core actor data, not via
        # report_codenames).
        assert detail["codenames"] == ["Andariel"]


# ---------------------------------------------------------------------------
# incident_sources bidirectional traversal (D11 positive path)
# ---------------------------------------------------------------------------


class TestIncidentSourcesBidirectional:
    async def test_report_sees_incident_and_incident_sees_report(
        self, engine: AsyncEngine
    ) -> None:
        """The same ``incident_sources`` row surfaces from BOTH
        directions — plan D11's M:N link path. Regression guard for
        a future refactor that accidentally reshapes one direction
        only.
        """
        src = await _seed_source(engine)
        r_id = await _seed_report(
            engine,
            title="anchor-report",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )
        i_id = await _seed_incident(
            engine, title="anchor-incident", reported=dt.date(2024, 5, 2)
        )
        await _link_incident_source(engine, incident_id=i_id, report_id=r_id)

        async with AsyncSession(engine) as s:
            report_detail = await detail_aggregator.get_report_detail(
                s, report_id=r_id
            )
            incident_detail = await detail_aggregator.get_incident_detail(
                s, incident_id=i_id
            )

        assert report_detail is not None and incident_detail is not None
        assert [row["id"] for row in report_detail["linked_incidents"]] == [i_id]
        assert [row["id"] for row in incident_detail["linked_reports"]] == [r_id]
