"""Write normalized feed entries to the ``staging`` table.

Uses ``INSERT ... ON CONFLICT (url_canonical) DO NOTHING RETURNING id``
so duplicate entries from re-polled feeds are silently skipped and
the caller receives a clear count of inserted vs skipped rows.

Per D2, this is the ONLY production table the RSS worker writes to.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import staging_table
from worker.ingest.normalize import StagingRowDraft


__all__ = [
    "WriteOutcome",
    "write_staging_rows",
]


_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """Result of a staging write batch."""

    inserted_ids: tuple[int, ...]
    skipped_duplicate_count: int


async def write_staging_rows(
    session: AsyncSession,
    drafts: list[StagingRowDraft],
) -> WriteOutcome:
    """Insert drafts into staging with ON CONFLICT DO NOTHING.

    Returns the IDs of successfully inserted rows and the count
    of duplicates that were skipped.
    """
    if not drafts:
        return WriteOutcome(inserted_ids=(), skipped_duplicate_count=0)

    bind = session.get_bind()
    dialect_name = bind.dialect.name

    all_inserted: list[int] = []
    total_attempted = 0

    for start in range(0, len(drafts), _BATCH_SIZE):
        chunk = drafts[start:start + _BATCH_SIZE]
        total_attempted += len(chunk)

        values_list = [
            {
                "url": d.url,
                "url_canonical": d.url_canonical,
                "sha256_title": d.sha256_title,
                "title": d.title,
                "published": d.published,
                "summary": d.summary,
                "source_id": None,
                "raw_text": d.raw_text,
                "lang": None,
                "tags_jsonb": None,
                "confidence": None,
                "reviewed_by": None,
                "reviewed_at": None,
                "promoted_report_id": None,
                "error": None,
            }
            for d in chunk
        ]

        inserted_ids = await _insert_batch(
            session, values_list, dialect_name
        )
        all_inserted.extend(inserted_ids)

    skipped = total_attempted - len(all_inserted)
    return WriteOutcome(
        inserted_ids=tuple(all_inserted),
        skipped_duplicate_count=skipped,
    )


async def _insert_batch(
    session: AsyncSession,
    values_list: list[dict],
    dialect_name: str,
) -> list[int]:
    """Execute a single batch insert with ON CONFLICT DO NOTHING."""
    if dialect_name == "sqlite":
        return await _insert_batch_sqlite(session, values_list)
    return await _insert_batch_pg(session, values_list)


async def _insert_batch_pg(
    session: AsyncSession,
    values_list: list[dict],
) -> list[int]:
    """Postgres path: ON CONFLICT DO NOTHING RETURNING id."""
    inserted_ids: list[int] = []
    for values in values_list:
        stmt = (
            pg_dialect.insert(staging_table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["url_canonical"])
            .returning(staging_table.c.id)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row is not None:
            inserted_ids.append(row[0])
    return inserted_ids


async def _insert_batch_sqlite(
    session: AsyncSession,
    values_list: list[dict],
) -> list[int]:
    """sqlite path: ON CONFLICT DO NOTHING + check rowcount."""
    inserted_ids: list[int] = []
    for values in values_list:
        stmt = (
            sqlite_dialect.insert(staging_table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["url_canonical"])
        )
        result = await session.execute(stmt)
        if result.rowcount > 0:
            pk_result = await session.execute(
                sa.select(staging_table.c.id).where(
                    staging_table.c.url_canonical == values["url_canonical"]
                )
            )
            row = pk_result.first()
            if row is not None:
                inserted_ids.append(row[0])
    return inserted_ids
