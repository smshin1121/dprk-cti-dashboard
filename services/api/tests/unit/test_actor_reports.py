"""Unit tests for PR #15 Group A read module ``api.read.actor_reports``.

Runs against in-memory aiosqlite — same pattern as
``test_detail_aggregator.py``. The EXISTS subquery (D17) and the
tuple-cursor predicate (D16) are both standard SQL so the sqlite
bed fully exercises the production query.

Review priorities locked at the Group A ask:

1. **D15 four empty branches** — each of ``(a) missing actor, (b)
   actor with no codenames, (c) codenames without report_codenames,
   (d) filter excludes all`` is explicitly tested. Branch (a) returns
   ``None`` (router → 404). Branches (b), (c), (d) collapse to
   ``([], None, None)``.

2. **D17 EXISTS dedup (not DISTINCT)** — seed one report linked via 3
   codenames of the same group; expect exactly 1 row in the response,
   not 3. A DISTINCT-over-JOIN regression would still produce the
   right row count but can duplicate mid-page under keyset cursor.

3. **D16 cursor advance** — same-date reports tiebreak on
   ``reports.id DESC``. Seed two reports with identical published
   dates and verify the cursor pair produced from page 1 drives page 2
   to the other report without dup or skip.

4. **D12 regression guard in this module** — this test file does NOT
   import or mutate ``api.read.detail_aggregator``. ``ActorDetail``
   shape regression is covered separately in
   ``test_detail_aggregator.py::TestActorDetailD11``; this file
   asserts only the new surface.

5. **Cap enforcement** — ``limit + 1`` over-fetch pattern returns at
   most ``limit`` items. Router-layer Query(ge=1, le=200) bounds are
   exercised in the integration test, not here.
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

from api.read import actor_reports
from api.tables import (
    codenames_table,
    groups_table,
    metadata,
    report_codenames_table,
    reports_table,
    sources_table,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


async def _seed_group(
    engine: AsyncEngine, *, name: str = "Lazarus Group"
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(groups_table)
            .values(
                name=name,
                mitre_intrusion_set_id="G0032",
                aka=["APT38"],
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


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    source_id: int,
    published: dt.date,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(reports_table)
            .values(
                title=title,
                url=f"https://ex.test/{title}",
                url_canonical=f"https://ex.test/{title}",
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


async def _link_report_codename(
    engine: AsyncEngine, *, report_id: int, codename_id: int
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(
            sa.insert(report_codenames_table).values(
                report_id=report_id, codename_id=codename_id
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# D15(a) — missing actor returns None (router → 404)
# ---------------------------------------------------------------------------


class TestD15MissingActor:
    async def test_unknown_actor_id_returns_none(
        self, engine: AsyncEngine
    ) -> None:
        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=999_999, limit=50
            )
        assert result is None, (
            "Missing actor must return None so the router can map "
            "to 404 (D15(a)). Returning ([], None, None) would "
            "erase the 200-empty-vs-404 distinction."
        )


# ---------------------------------------------------------------------------
# D15(b) — actor exists but has NO codenames → 200 empty envelope
# ---------------------------------------------------------------------------


class TestD15ActorNoCodenames:
    async def test_actor_with_no_codenames_returns_empty_page(
        self, engine: AsyncEngine
    ) -> None:
        g_id = await _seed_group(engine, name="Empty Group")
        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=50
            )
        assert result is not None, "Actor exists — must NOT be None"
        items, nxt_published, nxt_id = result
        assert items == []
        assert nxt_published is None
        assert nxt_id is None


# ---------------------------------------------------------------------------
# D15(c) — actor has codenames but zero report_codenames rows → 200 empty
# ---------------------------------------------------------------------------


class TestD15CodenamesButNoLinks:
    async def test_codenames_without_links_returns_empty_page(
        self, engine: AsyncEngine
    ) -> None:
        g_id = await _seed_group(engine, name="Dormant Group")
        await _seed_codename(engine, name="dormant-alias", group_id=g_id)
        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=50
            )
        assert result is not None
        items, _, _ = result
        assert items == []


# ---------------------------------------------------------------------------
# D15(d) — date filter excludes all candidate reports → 200 empty
# ---------------------------------------------------------------------------


class TestD15DateFilterExcludesAll:
    async def test_date_filter_excludes_all_returns_empty_page(
        self, engine: AsyncEngine
    ) -> None:
        src = await _seed_source(engine)
        g_id = await _seed_group(engine)
        c_id = await _seed_codename(engine, name="alias-1", group_id=g_id)
        r_id = await _seed_report(
            engine,
            title="old-report",
            source_id=src,
            published=dt.date(2020, 1, 1),
        )
        await _link_report_codename(engine, report_id=r_id, codename_id=c_id)

        # Ask for reports published in 2026 — the seeded 2020 row
        # should not appear.
        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s,
                actor_id=g_id,
                date_from=dt.date(2026, 1, 1),
                date_to=dt.date(2026, 12, 31),
                limit=50,
            )
        assert result is not None
        items, _, _ = result
        assert items == []


# ---------------------------------------------------------------------------
# Happy path — 3 reports linked via one codename each
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_three_reports_one_codename_each(
        self, engine: AsyncEngine
    ) -> None:
        src = await _seed_source(engine, name="Vendor A")
        g_id = await _seed_group(engine, name="Test Group")
        c_id = await _seed_codename(engine, name="alias-A", group_id=g_id)

        r_ids: list[int] = []
        for i in range(3):
            r_id = await _seed_report(
                engine,
                title=f"rep-{i:02d}",
                source_id=src,
                published=dt.date(2026, 3, 1) + dt.timedelta(days=i),
            )
            await _link_report_codename(
                engine, report_id=r_id, codename_id=c_id
            )
            r_ids.append(r_id)

        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=50
            )
        assert result is not None
        items, nxt_p, nxt_i = result
        assert len(items) == 3
        # Newest first per D16 (published DESC).
        titles = [row["title"] for row in items]
        assert titles == ["rep-02", "rep-01", "rep-00"]
        # All items have the ReportItem shape per D9.
        row = items[0]
        for key in (
            "id",
            "title",
            "url",
            "url_canonical",
            "published",
            "source_id",
            "source_name",
            "lang",
            "tlp",
        ):
            assert key in row, f"missing ReportItem key {key!r}"
        assert row["source_name"] == "Vendor A"
        assert row["tlp"] == "WHITE"
        # Final page — no cursor.
        assert nxt_p is None
        assert nxt_i is None


# ---------------------------------------------------------------------------
# D17 — EXISTS dedup (one report, multiple codenames → 1 row)
# ---------------------------------------------------------------------------


class TestD17ExistsDedup:
    async def test_report_linked_via_three_codenames_appears_once(
        self, engine: AsyncEngine
    ) -> None:
        """Seed one report linked via THREE distinct codenames of the
        same group. EXISTS dedup (D17) must produce exactly one row
        in the response. A DISTINCT-over-JOIN regression could still
        pass this test at the row-count level but would fail the
        keyset-cursor invariant — the cursor pair of page 1 might
        match the duplicate row on page 2.
        """
        src = await _seed_source(engine)
        g_id = await _seed_group(engine, name="Multi-Alias Group")
        # Three codenames, all pointing at the same group.
        c1 = await _seed_codename(engine, name="alias-1", group_id=g_id)
        c2 = await _seed_codename(engine, name="alias-2", group_id=g_id)
        c3 = await _seed_codename(engine, name="alias-3", group_id=g_id)
        r_id = await _seed_report(
            engine,
            title="popular-report",
            source_id=src,
            published=dt.date(2026, 4, 1),
        )
        # Link the same report via all three codenames.
        await _link_report_codename(engine, report_id=r_id, codename_id=c1)
        await _link_report_codename(engine, report_id=r_id, codename_id=c2)
        await _link_report_codename(engine, report_id=r_id, codename_id=c3)

        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=50
            )
        assert result is not None
        items, _, _ = result
        assert len(items) == 1, (
            f"EXISTS dedup (D17) failed — expected 1 row, got {len(items)}"
        )
        assert items[0]["title"] == "popular-report"

    async def test_mixed_single_and_triple_linked(
        self, engine: AsyncEngine
    ) -> None:
        """One report linked via 3 codenames, a second report linked
        via 1 codename. Expect 2 rows total — the triple-link must
        not inflate to 3+1.
        """
        src = await _seed_source(engine)
        g_id = await _seed_group(engine, name="Mixed Group")
        c1 = await _seed_codename(engine, name="a1", group_id=g_id)
        c2 = await _seed_codename(engine, name="a2", group_id=g_id)
        c3 = await _seed_codename(engine, name="a3", group_id=g_id)

        triple_r = await _seed_report(
            engine,
            title="triple",
            source_id=src,
            published=dt.date(2026, 2, 2),
        )
        solo_r = await _seed_report(
            engine,
            title="solo",
            source_id=src,
            published=dt.date(2026, 3, 3),
        )
        for c in (c1, c2, c3):
            await _link_report_codename(
                engine, report_id=triple_r, codename_id=c
            )
        await _link_report_codename(
            engine, report_id=solo_r, codename_id=c1
        )

        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=50
            )
        assert result is not None
        items, _, _ = result
        titles = sorted(row["title"] for row in items)
        assert titles == ["solo", "triple"], (
            f"expected one row per DISTINCT report, got {titles}"
        )


# ---------------------------------------------------------------------------
# D16 — keyset cursor advance + same-date tiebreak
# ---------------------------------------------------------------------------


class TestD16KeysetCursor:
    async def test_cursor_advance_same_date_tiebreaks_on_id(
        self, engine: AsyncEngine
    ) -> None:
        """Two reports with the same published date — cursor pair
        ``(published, id)`` must drive page 2 to the other row
        without dup or skip.
        """
        src = await _seed_source(engine)
        g_id = await _seed_group(engine, name="Cursor Group")
        c_id = await _seed_codename(engine, name="alias", group_id=g_id)
        same_day = dt.date(2026, 5, 10)
        r_newer = await _seed_report(
            engine, title="same-day-B", source_id=src, published=same_day
        )
        r_older = await _seed_report(
            engine, title="same-day-A", source_id=src, published=same_day
        )
        for r in (r_newer, r_older):
            await _link_report_codename(
                engine, report_id=r, codename_id=c_id
            )

        # Page 1 with limit=1.
        async with AsyncSession(engine) as s:
            page1 = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=1
            )
        assert page1 is not None
        items1, nxt_p, nxt_i = page1
        assert len(items1) == 1
        # DESC on id means the LARGER id (r_older, inserted second)
        # actually — wait: r_newer is inserted first above, so its
        # id is SMALLER. Seed order is r_newer (id=X), then r_older
        # (id=X+1). DESC id puts id=X+1 first. Its title is
        # ``same-day-A``. Compute from what's actually seeded:
        assert items1[0]["id"] == max(r_newer, r_older)
        assert nxt_p == same_day
        assert nxt_i == max(r_newer, r_older)

        # Page 2 uses the cursor — tuple predicate should yield the
        # OTHER row, not duplicate the first.
        async with AsyncSession(engine) as s:
            page2 = await actor_reports.get_actor_reports(
                s,
                actor_id=g_id,
                cursor_published=nxt_p,
                cursor_id=nxt_i,
                limit=1,
            )
        assert page2 is not None
        items2, tail_p, tail_i = page2
        assert len(items2) == 1
        assert items2[0]["id"] == min(r_newer, r_older)
        # Final page — no further cursor.
        assert tail_p is None
        assert tail_i is None

    async def test_cursor_advance_across_different_dates(
        self, engine: AsyncEngine
    ) -> None:
        src = await _seed_source(engine)
        g_id = await _seed_group(engine)
        c_id = await _seed_codename(engine, name="alias", group_id=g_id)
        dates = [dt.date(2026, 1, i + 1) for i in range(3)]
        r_ids: list[int] = []
        for i, d in enumerate(dates):
            r_id = await _seed_report(
                engine,
                title=f"r{i}",
                source_id=src,
                published=d,
            )
            await _link_report_codename(
                engine, report_id=r_id, codename_id=c_id
            )
            r_ids.append(r_id)

        # Page 1 — limit=2 newest first → dates[2], dates[1].
        async with AsyncSession(engine) as s:
            p1 = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=2
            )
        assert p1 is not None
        items1, nxt_p, nxt_i = p1
        assert [row["title"] for row in items1] == ["r2", "r1"]
        assert nxt_p == dates[1]
        assert nxt_i == r_ids[1]

        # Page 2 — final page with dates[0].
        async with AsyncSession(engine) as s:
            p2 = await actor_reports.get_actor_reports(
                s,
                actor_id=g_id,
                cursor_published=nxt_p,
                cursor_id=nxt_i,
                limit=2,
            )
        assert p2 is not None
        items2, tail_p, tail_i = p2
        assert [row["title"] for row in items2] == ["r0"]
        assert tail_p is None
        assert tail_i is None


# ---------------------------------------------------------------------------
# Over-fetch: more rows than `limit` triggers next_cursor
# ---------------------------------------------------------------------------


class TestLimitOverFetch:
    async def test_limit_plus_one_overfetch_signals_next_page(
        self, engine: AsyncEngine
    ) -> None:
        src = await _seed_source(engine)
        g_id = await _seed_group(engine)
        c_id = await _seed_codename(engine, name="alias", group_id=g_id)
        for i in range(5):
            r = await _seed_report(
                engine,
                title=f"r{i:02d}",
                source_id=src,
                published=dt.date(2026, 6, i + 1),
            )
            await _link_report_codename(engine, report_id=r, codename_id=c_id)

        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=g_id, limit=3
            )
        assert result is not None
        items, nxt_p, nxt_i = result
        assert len(items) == 3
        # Next cursor carries the LAST item on the page (a future
        # page 2 will see the remaining 2 rows).
        assert nxt_p == items[-1]["published"]
        assert nxt_i == items[-1]["id"]


# ---------------------------------------------------------------------------
# Date filter inclusivity
# ---------------------------------------------------------------------------


class TestDateFilterInclusive:
    async def test_boundary_dates_included(
        self, engine: AsyncEngine
    ) -> None:
        src = await _seed_source(engine)
        g_id = await _seed_group(engine)
        c_id = await _seed_codename(engine, name="alias", group_id=g_id)
        boundary_from = dt.date(2026, 2, 1)
        boundary_to = dt.date(2026, 2, 28)
        # Seed rows at the two boundaries and one outside on each side.
        for d in (
            dt.date(2026, 1, 31),
            boundary_from,
            dt.date(2026, 2, 14),
            boundary_to,
            dt.date(2026, 3, 1),
        ):
            r = await _seed_report(
                engine,
                title=f"r-{d.isoformat()}",
                source_id=src,
                published=d,
            )
            await _link_report_codename(engine, report_id=r, codename_id=c_id)

        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s,
                actor_id=g_id,
                date_from=boundary_from,
                date_to=boundary_to,
                limit=50,
            )
        assert result is not None
        items, _, _ = result
        returned_dates = sorted(row["published"] for row in items)
        assert returned_dates == [boundary_from, dt.date(2026, 2, 14), boundary_to]


# ---------------------------------------------------------------------------
# Codename belonging to a DIFFERENT group must not leak
# ---------------------------------------------------------------------------


class TestActorIsolation:
    async def test_other_group_codename_does_not_leak(
        self, engine: AsyncEngine
    ) -> None:
        """A report linked only via a codename of group B must not
        appear when we ask for group A's reports. EXISTS predicate
        filters on ``codenames.group_id == :actor_id`` — this test
        pins that the filter is actually present.
        """
        src = await _seed_source(engine)
        group_a = await _seed_group(engine, name="Group-A")
        group_b = await _seed_group(engine, name="Group-B")
        codename_b = await _seed_codename(
            engine, name="b-alias", group_id=group_b
        )
        r = await _seed_report(
            engine,
            title="only-in-B",
            source_id=src,
            published=dt.date(2026, 7, 1),
        )
        await _link_report_codename(
            engine, report_id=r, codename_id=codename_b
        )

        async with AsyncSession(engine) as s:
            result = await actor_reports.get_actor_reports(
                s, actor_id=group_a, limit=50
            )
        assert result is not None
        items, _, _ = result
        assert items == [], "Group A must not see Group B's reports"
