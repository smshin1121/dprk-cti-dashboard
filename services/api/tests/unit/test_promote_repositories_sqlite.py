"""Unit tests for ``api.promote.repositories`` against in-memory SQLite.

These tests exercise the ``ON CONFLICT DO NOTHING RETURNING id`` +
SELECT-fallback contract on the SQLite dialect. They are NOT a
substitute for the Group H real-PG integration job — they verify the
API surface of each helper and the dialect dispatcher, but cannot
verify PG-specific guarantees like SERIALIZABLE isolation, per-row
locks under concurrent writers, or JSONB behavior. Group H is the
authoritative semantic check.

Scope covered here:
- happy-path INSERT returns new id;
- ON CONFLICT fires on natural-key duplicate, helper returns the
  pre-existing id via SELECT fallback;
- ``upsert_report`` returns ``attached_existing=True`` on conflict;
- link tables (``report_tags`` / ``report_codenames``) are idempotent
  on composite PK;
- input validation rejects empty natural keys.
"""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from api.promote.repositories import (
    link_report_codename,
    link_report_tag,
    upsert_codename,
    upsert_group,
    upsert_report,
    upsert_source,
    upsert_tag,
)
from api.tables import (
    metadata,
    report_codenames_table,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
)


# ---------------------------------------------------------------------------
# In-memory SQLite fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    """Fresh in-memory async SQLite engine with the full api.tables schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncSession:
    """One async session per test; commits within the test body so
    the FK link-table tests see committed rows on subsequent reads."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


# Helper: minimal report values so we can insert one easily.
async def _make_source(session: AsyncSession, name: str = "vendor-a") -> int:
    source_id = await upsert_source(session=session, name=name)
    await session.commit()
    return source_id


# ---------------------------------------------------------------------------
# upsert_source
# ---------------------------------------------------------------------------


class TestUpsertSource:
    async def test_insert_new_returns_id(self, session: AsyncSession) -> None:
        sid = await upsert_source(session=session, name="vendor-a")
        await session.commit()
        # Row actually committed.
        row = (
            await session.execute(
                sa.select(sources_table.c.id, sources_table.c.name).where(
                    sources_table.c.name == "vendor-a"
                )
            )
        ).one()
        assert row.id == sid
        assert row.name == "vendor-a"

    async def test_conflict_returns_existing_id(
        self, session: AsyncSession
    ) -> None:
        first = await upsert_source(session=session, name="dup-vendor")
        await session.commit()
        second = await upsert_source(session=session, name="dup-vendor")
        await session.commit()
        assert first == second

    async def test_empty_name_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(ValueError):
            await upsert_source(session=session, name="")

    async def test_type_persists_on_insert(self, session: AsyncSession) -> None:
        await upsert_source(session=session, name="blog-x", type_="blog")
        await session.commit()
        row_type = (
            await session.execute(
                sa.select(sources_table.c.type).where(
                    sources_table.c.name == "blog-x"
                )
            )
        ).scalar_one()
        assert row_type == "blog"

    async def test_type_not_overwritten_on_conflict(
        self, session: AsyncSession
    ) -> None:
        """ON CONFLICT DO NOTHING — an existing row's ``type`` stays put
        even when the caller passes a different value. Matches plan
        §2.3 'no surprise updates'."""
        await upsert_source(session=session, name="stable", type_="vendor")
        await session.commit()
        await upsert_source(session=session, name="stable", type_="blog")
        await session.commit()
        row_type = (
            await session.execute(
                sa.select(sources_table.c.type).where(
                    sources_table.c.name == "stable"
                )
            )
        ).scalar_one()
        assert row_type == "vendor"


# ---------------------------------------------------------------------------
# upsert_report
# ---------------------------------------------------------------------------


class TestUpsertReport:
    async def test_insert_new(self, session: AsyncSession) -> None:
        source_id = await _make_source(session)
        rid, attached = await upsert_report(
            session=session,
            published=dt.date(2026, 4, 17),
            source_id=source_id,
            title="t",
            url="http://e.com/a",
            url_canonical="http://e.com/a",
            sha256_title="a" * 64,
        )
        await session.commit()
        assert attached is False
        assert isinstance(rid, int)

    async def test_conflict_attaches_existing(
        self, session: AsyncSession
    ) -> None:
        source_id = await _make_source(session)
        first_id, first_attached = await upsert_report(
            session=session,
            published=dt.date(2026, 4, 17),
            source_id=source_id,
            title="first title",
            url="http://e.com/dup",
            url_canonical="http://e.com/dup",
            sha256_title="a" * 64,
        )
        await session.commit()
        assert first_attached is False

        # Second call with the same url_canonical hits ON CONFLICT.
        # A DIFFERENT title proves the existing row is NOT updated —
        # DO NOTHING is the invariant.
        second_id, second_attached = await upsert_report(
            session=session,
            published=dt.date(2026, 4, 18),
            source_id=source_id,
            title="different title",
            url="http://e.com/dup",
            url_canonical="http://e.com/dup",
            sha256_title="b" * 64,
        )
        await session.commit()
        assert second_id == first_id
        assert second_attached is True

        # Confirm no overwrite of title.
        title_now = (
            await session.execute(
                sa.select(reports_table.c.title).where(
                    reports_table.c.id == first_id
                )
            )
        ).scalar_one()
        assert title_now == "first title"

    async def test_empty_url_canonical_rejected(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(ValueError):
            await upsert_report(
                session=session,
                published=dt.date(2026, 4, 17),
                source_id=1,
                title="t",
                url="http://x",
                url_canonical="",
                sha256_title="a" * 64,
            )

    async def test_empty_sha256_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(ValueError):
            await upsert_report(
                session=session,
                published=dt.date(2026, 4, 17),
                source_id=1,
                title="t",
                url="http://x",
                url_canonical="http://x",
                sha256_title="",
            )


# ---------------------------------------------------------------------------
# upsert_tag
# ---------------------------------------------------------------------------


class TestUpsertTag:
    async def test_insert_new(self, session: AsyncSession) -> None:
        tid = await upsert_tag(session=session, name="APT-X", type_="actor")
        await session.commit()
        assert isinstance(tid, int)

    async def test_conflict_returns_existing(self, session: AsyncSession) -> None:
        first = await upsert_tag(session=session, name="dup-tag", type_="actor")
        await session.commit()
        second = await upsert_tag(session=session, name="dup-tag", type_="actor")
        await session.commit()
        assert first == second

    async def test_empty_name_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(ValueError):
            await upsert_tag(session=session, name="", type_="actor")

    async def test_empty_type_rejected(self, session: AsyncSession) -> None:
        with pytest.raises(ValueError):
            await upsert_tag(session=session, name="x", type_="")

    async def test_type_not_overwritten_on_conflict(
        self, session: AsyncSession
    ) -> None:
        await upsert_tag(session=session, name="dupe", type_="actor")
        await session.commit()
        await upsert_tag(session=session, name="dupe", type_="technique")
        await session.commit()
        row_type = (
            await session.execute(
                sa.select(tags_table.c.type).where(tags_table.c.name == "dupe")
            )
        ).scalar_one()
        assert row_type == "actor"


# ---------------------------------------------------------------------------
# upsert_group / upsert_codename (skeleton — Phase 4 trigger)
# ---------------------------------------------------------------------------


class TestUpsertGroupAndCodename:
    async def test_group_roundtrip(self, session: AsyncSession) -> None:
        a = await upsert_group(session=session, name="Lazarus")
        await session.commit()
        b = await upsert_group(session=session, name="Lazarus")
        await session.commit()
        assert a == b

    async def test_codename_roundtrip(self, session: AsyncSession) -> None:
        # Create a group first so the FK target exists.
        group_id = await upsert_group(session=session, name="APT38")
        await session.commit()
        a = await upsert_codename(
            session=session, name="HIDDEN_COBRA", group_id=group_id
        )
        await session.commit()
        b = await upsert_codename(
            session=session, name="HIDDEN_COBRA", group_id=None
        )
        await session.commit()
        # Plan §2.3 lock: DO NOTHING on conflict — the second call must
        # NOT overwrite group_id to NULL.
        assert a == b

    async def test_group_empty_name_rejected(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(ValueError):
            await upsert_group(session=session, name="")

    async def test_codename_empty_name_rejected(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(ValueError):
            await upsert_codename(session=session, name="")


# ---------------------------------------------------------------------------
# link_report_tag / link_report_codename — composite-PK idempotency
# ---------------------------------------------------------------------------


class TestLinkTables:
    async def _seed_report(self, session: AsyncSession) -> int:
        source_id = await _make_source(session)
        rid, _ = await upsert_report(
            session=session,
            published=dt.date(2026, 4, 17),
            source_id=source_id,
            title="t",
            url="http://e.com/link",
            url_canonical="http://e.com/link",
            sha256_title="c" * 64,
        )
        await session.commit()
        return rid

    async def test_link_report_tag_is_idempotent(
        self, session: AsyncSession
    ) -> None:
        report_id = await self._seed_report(session)
        tag_id = await upsert_tag(
            session=session, name="actor:Lazarus", type_="actor"
        )
        await session.commit()

        await link_report_tag(
            session=session, report_id=report_id, tag_id=tag_id, confidence=0.9
        )
        await session.commit()
        # Second call must NOT raise and must NOT duplicate rows.
        await link_report_tag(
            session=session, report_id=report_id, tag_id=tag_id, confidence=0.1
        )
        await session.commit()

        rows = (
            await session.execute(
                sa.select(report_tags_table.c.confidence).where(
                    (report_tags_table.c.report_id == report_id)
                    & (report_tags_table.c.tag_id == tag_id)
                )
            )
        ).all()
        assert len(rows) == 1
        # Confidence from first call preserved (DO NOTHING doesn't update).
        assert rows[0].confidence == 0.9

    async def test_link_report_codename_is_idempotent(
        self, session: AsyncSession
    ) -> None:
        report_id = await self._seed_report(session)
        group_id = await upsert_group(session=session, name="Lazarus")
        codename_id = await upsert_codename(
            session=session, name="HIDDEN_COBRA", group_id=group_id
        )
        await session.commit()

        await link_report_codename(
            session=session,
            report_id=report_id,
            codename_id=codename_id,
            confidence=0.85,
        )
        await session.commit()
        await link_report_codename(
            session=session,
            report_id=report_id,
            codename_id=codename_id,
        )
        await session.commit()

        rows = (
            await session.execute(
                sa.select(report_codenames_table.c.confidence).where(
                    (report_codenames_table.c.report_id == report_id)
                    & (report_codenames_table.c.codename_id == codename_id)
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].confidence == 0.85


# ---------------------------------------------------------------------------
# Dialect dispatch negative path
# ---------------------------------------------------------------------------


class TestDialectDispatch:
    async def test_unsupported_dialect_raises(
        self, engine: AsyncEngine
    ) -> None:
        """If a new dialect appears without explicit handling, the
        dispatcher must raise so no silent ON CONFLICT wrong-emit
        happens. Exercised via a tiny stub that fakes the dialect name
        on an otherwise valid AsyncSession — we never actually reach
        the DB."""
        from unittest.mock import MagicMock

        fake_session = MagicMock(spec=AsyncSession)
        fake_session.bind = MagicMock()
        fake_session.bind.dialect = MagicMock()
        fake_session.bind.dialect.name = "mysql"

        with pytest.raises(RuntimeError, match="dialect 'mysql'"):
            await upsert_source(session=fake_session, name="x")
