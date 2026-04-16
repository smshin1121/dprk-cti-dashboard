"""Read/write helpers for the ``rss_feed_state`` table.

Each feed's runtime state (ETag, Last-Modified, failure counters) is
tracked so successive polls can send conditional-GET headers and
operators can see which feeds are healthy.

All writes use ``INSERT ... ON CONFLICT (feed_slug) DO UPDATE`` so
the same function handles both first-poll creation and subsequent
updates. This is safe under the D2 single-writer assumption (one
CLI process at a time).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import rss_feed_state_table


__all__ = [
    "FeedStateRow",
    "load_state",
    "upsert_state",
]


@dataclass(frozen=True, slots=True)
class FeedStateRow:
    """Immutable snapshot of one feed's runtime state."""

    feed_slug: str
    etag: str | None
    last_modified: str | None
    last_fetched_at: dt.datetime | None
    last_status_code: int | None
    last_error: str | None
    consecutive_failures: int


async def load_state(
    session: AsyncSession,
    feed_slug: str,
) -> FeedStateRow | None:
    """Load the current state for ``feed_slug``, or ``None`` on first poll."""
    result = await session.execute(
        sa.select(rss_feed_state_table).where(
            rss_feed_state_table.c.feed_slug == feed_slug
        )
    )
    row = result.first()
    if row is None:
        return None
    return FeedStateRow(
        feed_slug=row.feed_slug,
        etag=row.etag,
        last_modified=row.last_modified,
        last_fetched_at=row.last_fetched_at,
        last_status_code=row.last_status_code,
        last_error=row.last_error,
        consecutive_failures=row.consecutive_failures,
    )


def _build_upsert(
    values: dict[str, Any],
    *,
    reset_failures: bool,
    dialect_name: str,
) -> sa.sql.expression.Insert:
    """Build a dialect-appropriate ON CONFLICT upsert statement."""
    if dialect_name == "sqlite":
        stmt = sqlite_dialect.insert(rss_feed_state_table).values(**values)
    else:
        stmt = pg_dialect.insert(rss_feed_state_table).values(**values)

    update_cols: dict[str, Any] = {
        "etag": stmt.excluded.etag,
        "last_modified": stmt.excluded.last_modified,
        "last_fetched_at": stmt.excluded.last_fetched_at,
        "last_status_code": stmt.excluded.last_status_code,
        "last_error": stmt.excluded.last_error,
        "updated_at": stmt.excluded.updated_at,
    }
    if reset_failures:
        update_cols["consecutive_failures"] = 0
    else:
        update_cols["consecutive_failures"] = (
            rss_feed_state_table.c.consecutive_failures + 1
        )

    return stmt.on_conflict_do_update(
        index_elements=["feed_slug"],
        set_=update_cols,
    )


async def upsert_state(
    session: AsyncSession,
    *,
    feed_slug: str,
    etag: str | None = None,
    last_modified: str | None = None,
    last_fetched_at: dt.datetime | None = None,
    last_status_code: int | None = None,
    last_error: str | None = None,
    reset_failures: bool = False,
) -> None:
    """Insert or update the runtime state for ``feed_slug``.

    On success (2xx / 304), caller should pass ``reset_failures=True``
    to zero the consecutive counter. On failure, omit ``reset_failures``
    so the counter increments.
    """
    now = dt.datetime.now(dt.timezone.utc)

    values: dict[str, Any] = {
        "feed_slug": feed_slug,
        "etag": etag,
        "last_modified": last_modified,
        "last_fetched_at": last_fetched_at or now,
        "last_status_code": last_status_code,
        "last_error": last_error,
        "updated_at": now,
        "consecutive_failures": 0 if reset_failures else 1,
    }

    bind = session.get_bind()
    dialect_name = bind.dialect.name

    await session.execute(_build_upsert(values, reset_failures=reset_failures, dialect_name=dialect_name))
