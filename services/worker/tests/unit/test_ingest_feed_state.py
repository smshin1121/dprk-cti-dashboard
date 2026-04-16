"""Tests for worker.ingest.feed_state — rss_feed_state read/write."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.tables import metadata, rss_feed_state_table
from worker.ingest.feed_state import FeedStateRow, load_state, upsert_state


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        async with sess.begin():
            yield sess
    await engine.dispose()


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


async def test_load_state_returns_none_on_empty(session: AsyncSession) -> None:
    result = await load_state(session, "nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# upsert_state — first insert
# ---------------------------------------------------------------------------


async def test_upsert_creates_new_row(session: AsyncSession) -> None:
    await upsert_state(
        session,
        feed_slug="test-feed",
        etag='"abc"',
        last_status_code=200,
        reset_failures=True,
    )
    row = await load_state(session, "test-feed")
    assert row is not None
    assert row.feed_slug == "test-feed"
    assert row.etag == '"abc"'
    assert row.last_status_code == 200
    assert row.consecutive_failures == 0


async def test_upsert_first_failure_sets_one(session: AsyncSession) -> None:
    await upsert_state(
        session,
        feed_slug="fail-feed",
        last_status_code=500,
        last_error="HTTP 500",
        reset_failures=False,
    )
    row = await load_state(session, "fail-feed")
    assert row is not None
    assert row.consecutive_failures == 1
    assert row.last_error == "HTTP 500"


# ---------------------------------------------------------------------------
# upsert_state — update existing
# ---------------------------------------------------------------------------


async def test_upsert_updates_etag_on_second_call(session: AsyncSession) -> None:
    await upsert_state(
        session,
        feed_slug="up-feed",
        etag='"v1"',
        last_status_code=200,
        reset_failures=True,
    )
    await upsert_state(
        session,
        feed_slug="up-feed",
        etag='"v2"',
        last_status_code=200,
        reset_failures=True,
    )
    row = await load_state(session, "up-feed")
    assert row is not None
    assert row.etag == '"v2"'
    assert row.consecutive_failures == 0


async def test_upsert_increments_consecutive_failures(session: AsyncSession) -> None:
    await upsert_state(
        session,
        feed_slug="inc-feed",
        last_status_code=500,
        last_error="HTTP 500",
        reset_failures=False,
    )
    await upsert_state(
        session,
        feed_slug="inc-feed",
        last_status_code=502,
        last_error="HTTP 502",
        reset_failures=False,
    )
    row = await load_state(session, "inc-feed")
    assert row is not None
    assert row.consecutive_failures == 2
    assert row.last_error == "HTTP 502"


async def test_upsert_success_after_failure_resets_counter(session: AsyncSession) -> None:
    await upsert_state(
        session,
        feed_slug="reset-feed",
        last_status_code=500,
        last_error="HTTP 500",
        reset_failures=False,
    )
    await upsert_state(
        session,
        feed_slug="reset-feed",
        last_status_code=500,
        last_error="HTTP 500",
        reset_failures=False,
    )
    await upsert_state(
        session,
        feed_slug="reset-feed",
        etag='"ok"',
        last_status_code=200,
        reset_failures=True,
    )
    row = await load_state(session, "reset-feed")
    assert row is not None
    assert row.consecutive_failures == 0
    assert row.etag == '"ok"'
    assert row.last_error is None


# ---------------------------------------------------------------------------
# upsert_state — 304 path
# ---------------------------------------------------------------------------


async def test_upsert_304_preserves_etag_and_resets(session: AsyncSession) -> None:
    await upsert_state(
        session,
        feed_slug="cache-feed",
        etag='"cached"',
        last_modified="Tue, 15 Apr 2026 10:00:00 GMT",
        last_status_code=200,
        reset_failures=True,
    )
    await upsert_state(
        session,
        feed_slug="cache-feed",
        etag='"cached"',
        last_modified="Tue, 15 Apr 2026 10:00:00 GMT",
        last_status_code=304,
        reset_failures=True,
    )
    row = await load_state(session, "cache-feed")
    assert row is not None
    assert row.etag == '"cached"'
    assert row.last_status_code == 304
    assert row.consecutive_failures == 0


# ---------------------------------------------------------------------------
# FeedStateRow is immutable
# ---------------------------------------------------------------------------


def test_feed_state_row_is_frozen() -> None:
    row = FeedStateRow(
        feed_slug="x",
        etag=None,
        last_modified=None,
        last_fetched_at=None,
        last_status_code=None,
        last_error=None,
        consecutive_failures=0,
    )
    with pytest.raises(AttributeError):
        row.etag = "mutate"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Multiple feeds — isolation
# ---------------------------------------------------------------------------


async def test_multiple_feeds_isolated(session: AsyncSession) -> None:
    await upsert_state(session, feed_slug="feed-a", etag='"a"', last_status_code=200, reset_failures=True)
    await upsert_state(session, feed_slug="feed-b", etag='"b"', last_status_code=500, reset_failures=False)

    a = await load_state(session, "feed-a")
    b = await load_state(session, "feed-b")

    assert a is not None and a.etag == '"a"' and a.consecutive_failures == 0
    assert b is not None and b.etag == '"b"' and b.consecutive_failures == 1
