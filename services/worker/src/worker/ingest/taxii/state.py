"""Read/write helpers for the ``taxii_collection_state`` table.

Each collection's runtime state (last_added_after, failure counters) is
tracked so successive polls can send the ``added_after`` parameter for
incremental STIX object retrieval.

All writes use ``INSERT ... ON CONFLICT (collection_key) DO UPDATE`` so
the same function handles both first-poll creation and subsequent
updates. This is safe under the D3 single-writer assumption (one
CLI process at a time).

Unlike ``worker.ingest.feed_state`` (RSS), this module tracks
``last_added_after`` (TAXII-native timestamp) instead of
ETag/Last-Modified (HTTP conditional GET). The two state tables have
different schemas reflecting their different polling protocols.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import taxii_collection_state_table


__all__ = [
    "CollectionStateRow",
    "load_state",
    "upsert_state",
]


@dataclass(frozen=True, slots=True)
class CollectionStateRow:
    """Immutable snapshot of one TAXII collection's runtime state."""

    collection_key: str
    server_url: str
    collection_id: str
    last_added_after: str | None
    last_fetched_at: dt.datetime | None
    last_object_count: int | None
    last_error: str | None
    consecutive_failures: int


async def load_state(
    session: AsyncSession,
    collection_key: str,
) -> CollectionStateRow | None:
    """Load the current state for ``collection_key``, or ``None`` on first poll."""
    result = await session.execute(
        sa.select(taxii_collection_state_table).where(
            taxii_collection_state_table.c.collection_key == collection_key
        )
    )
    row = result.first()
    if row is None:
        return None
    return CollectionStateRow(
        collection_key=row.collection_key,
        server_url=row.server_url,
        collection_id=row.collection_id,
        last_added_after=row.last_added_after,
        last_fetched_at=row.last_fetched_at,
        last_object_count=row.last_object_count,
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
    tbl = taxii_collection_state_table
    if dialect_name == "sqlite":
        stmt = sqlite_dialect.insert(tbl).values(**values)
    else:
        stmt = pg_dialect.insert(tbl).values(**values)

    update_cols: dict[str, Any] = {
        "server_url": stmt.excluded.server_url,
        "collection_id": stmt.excluded.collection_id,
        "last_added_after": stmt.excluded.last_added_after,
        "last_fetched_at": stmt.excluded.last_fetched_at,
        "last_object_count": stmt.excluded.last_object_count,
        "last_error": stmt.excluded.last_error,
        "updated_at": stmt.excluded.updated_at,
    }
    if reset_failures:
        update_cols["consecutive_failures"] = 0
    else:
        update_cols["consecutive_failures"] = (
            tbl.c.consecutive_failures + 1
        )

    return stmt.on_conflict_do_update(
        index_elements=["collection_key"],
        set_=update_cols,
    )


async def upsert_state(
    session: AsyncSession,
    *,
    collection_key: str,
    server_url: str,
    collection_id: str,
    last_added_after: str | None = None,
    last_fetched_at: dt.datetime | None = None,
    last_object_count: int | None = None,
    last_error: str | None = None,
    reset_failures: bool = False,
) -> None:
    """Insert or update the runtime state for ``collection_key``.

    On success, caller should pass ``reset_failures=True`` to zero the
    consecutive counter. On failure, omit ``reset_failures`` so the
    counter increments.
    """
    now = dt.datetime.now(dt.timezone.utc)

    values: dict[str, Any] = {
        "collection_key": collection_key,
        "server_url": server_url,
        "collection_id": collection_id,
        "last_added_after": last_added_after,
        "last_fetched_at": last_fetched_at or now,
        "last_object_count": last_object_count,
        "last_error": last_error,
        "updated_at": now,
        "consecutive_failures": 0 if reset_failures else 1,
    }

    bind = session.get_bind()
    dialect_name = bind.dialect.name

    await session.execute(
        _build_upsert(
            values, reset_failures=reset_failures, dialect_name=dialect_name,
        )
    )
