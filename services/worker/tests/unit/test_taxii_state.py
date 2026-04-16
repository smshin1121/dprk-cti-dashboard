"""Tests for worker.ingest.taxii.state — taxii_collection_state read/write.

Follows the same pattern as test_ingest_feed_state.py (PR #8 Group B).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.tables import metadata
from worker.ingest.taxii.state import CollectionStateRow, load_state, upsert_state


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
# load_state — empty table
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
        collection_key="mitre-enterprise",
        server_url="https://cti-taxii.mitre.org",
        collection_id="enterprise-attack",
        last_added_after="2026-04-15T00:00:00Z",
        last_object_count=150,
        reset_failures=True,
    )
    row = await load_state(session, "mitre-enterprise")
    assert row is not None
    assert row.collection_key == "mitre-enterprise"
    assert row.server_url == "https://cti-taxii.mitre.org"
    assert row.collection_id == "enterprise-attack"
    assert row.last_added_after == "2026-04-15T00:00:00Z"
    assert row.last_object_count == 150
    assert row.consecutive_failures == 0
    assert row.last_error is None


async def test_upsert_first_failure_sets_one(session: AsyncSession) -> None:
    await upsert_state(
        session,
        collection_key="fail-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_error="HTTP 500",
        reset_failures=False,
    )
    row = await load_state(session, "fail-col")
    assert row is not None
    assert row.consecutive_failures == 1
    assert row.last_error == "HTTP 500"


# ---------------------------------------------------------------------------
# upsert_state — update existing
# ---------------------------------------------------------------------------


async def test_upsert_updates_added_after_on_second_call(
    session: AsyncSession,
) -> None:
    await upsert_state(
        session,
        collection_key="upd-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_added_after="2026-04-15T00:00:00Z",
        last_object_count=100,
        reset_failures=True,
    )
    await upsert_state(
        session,
        collection_key="upd-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_added_after="2026-04-16T00:00:00Z",
        last_object_count=5,
        reset_failures=True,
    )
    row = await load_state(session, "upd-col")
    assert row is not None
    assert row.last_added_after == "2026-04-16T00:00:00Z"
    assert row.last_object_count == 5
    assert row.consecutive_failures == 0


async def test_upsert_increments_consecutive_failures(
    session: AsyncSession,
) -> None:
    await upsert_state(
        session,
        collection_key="inc-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_error="HTTP 500",
        reset_failures=False,
    )
    await upsert_state(
        session,
        collection_key="inc-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_error="HTTP 502",
        reset_failures=False,
    )
    row = await load_state(session, "inc-col")
    assert row is not None
    assert row.consecutive_failures == 2
    assert row.last_error == "HTTP 502"


async def test_upsert_success_after_failure_resets_counter(
    session: AsyncSession,
) -> None:
    await upsert_state(
        session,
        collection_key="reset-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_error="HTTP 500",
        reset_failures=False,
    )
    await upsert_state(
        session,
        collection_key="reset-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_error="HTTP 500",
        reset_failures=False,
    )
    # Now succeed
    await upsert_state(
        session,
        collection_key="reset-col",
        server_url="https://example.com",
        collection_id="col-1",
        last_added_after="2026-04-16T10:00:00Z",
        last_object_count=42,
        reset_failures=True,
    )
    row = await load_state(session, "reset-col")
    assert row is not None
    assert row.consecutive_failures == 0
    assert row.last_added_after == "2026-04-16T10:00:00Z"
    assert row.last_error is None


# ---------------------------------------------------------------------------
# upsert_state — server_url and collection_id update on upsert
# ---------------------------------------------------------------------------


async def test_upsert_updates_server_metadata(session: AsyncSession) -> None:
    """Verify server_url and collection_id are updated on conflict."""
    await upsert_state(
        session,
        collection_key="meta-col",
        server_url="https://old-server.com",
        collection_id="old-col",
        reset_failures=True,
    )
    await upsert_state(
        session,
        collection_key="meta-col",
        server_url="https://new-server.com",
        collection_id="new-col",
        reset_failures=True,
    )
    row = await load_state(session, "meta-col")
    assert row is not None
    assert row.server_url == "https://new-server.com"
    assert row.collection_id == "new-col"


# ---------------------------------------------------------------------------
# Multiple collections — isolation
# ---------------------------------------------------------------------------


async def test_multiple_collections_isolated(session: AsyncSession) -> None:
    await upsert_state(
        session,
        collection_key="col-a",
        server_url="https://a.com",
        collection_id="a",
        last_added_after="2026-04-15T00:00:00Z",
        reset_failures=True,
    )
    await upsert_state(
        session,
        collection_key="col-b",
        server_url="https://b.com",
        collection_id="b",
        last_error="timeout",
        reset_failures=False,
    )

    a = await load_state(session, "col-a")
    b = await load_state(session, "col-b")

    assert a is not None
    assert a.last_added_after == "2026-04-15T00:00:00Z"
    assert a.consecutive_failures == 0

    assert b is not None
    assert b.last_error == "timeout"
    assert b.consecutive_failures == 1


# ---------------------------------------------------------------------------
# CollectionStateRow is immutable
# ---------------------------------------------------------------------------


def test_collection_state_row_is_frozen() -> None:
    row = CollectionStateRow(
        collection_key="x",
        server_url="https://x.com",
        collection_id="x",
        last_added_after=None,
        last_fetched_at=None,
        last_object_count=None,
        last_error=None,
        consecutive_failures=0,
    )
    with pytest.raises(AttributeError):
        row.last_added_after = "mutate"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Null last_added_after on first poll (full pull)
# ---------------------------------------------------------------------------


async def test_first_poll_no_added_after(session: AsyncSession) -> None:
    """First poll has no last_added_after — triggers full pull (decision D)."""
    await upsert_state(
        session,
        collection_key="fresh-col",
        server_url="https://example.com",
        collection_id="fresh",
        last_added_after=None,
        last_object_count=1700,
        reset_failures=True,
    )
    row = await load_state(session, "fresh-col")
    assert row is not None
    assert row.last_added_after is None
    assert row.last_object_count == 1700
