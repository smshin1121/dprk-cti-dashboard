"""Tests for worker.ingest.staging_writer — ON CONFLICT DO NOTHING."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.tables import metadata, staging_table
from worker.ingest.normalize import StagingRowDraft
from worker.ingest.staging_writer import WriteOutcome, write_staging_rows


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        async with sess.begin():
            yield sess
    await engine.dispose()


def _draft(url_canonical: str, title: str | None = "Test") -> StagingRowDraft:
    return StagingRowDraft(
        url=f"https://example.com/{url_canonical}",
        url_canonical=url_canonical,
        sha256_title="abc123" if title else None,
        title=title,
        published=None,
        summary=None,
    )


# ---------------------------------------------------------------------------
# New row — returns id
# ---------------------------------------------------------------------------


async def test_insert_new_row_returns_id(session: AsyncSession) -> None:
    outcome = await write_staging_rows(session, [_draft("new-1")])

    assert len(outcome.inserted_ids) == 1
    assert outcome.skipped_duplicate_count == 0


async def test_inserted_row_has_pending_status(session: AsyncSession) -> None:
    await write_staging_rows(session, [_draft("pending-1")])

    result = await session.execute(
        sa.select(staging_table.c.status).where(
            staging_table.c.url_canonical == "pending-1"
        )
    )
    assert result.scalar_one() == "pending"


async def test_inserted_row_has_null_source_id(session: AsyncSession) -> None:
    await write_staging_rows(session, [_draft("src-null")])

    result = await session.execute(
        sa.select(staging_table.c.source_id).where(
            staging_table.c.url_canonical == "src-null"
        )
    )
    assert result.scalar_one() is None


# ---------------------------------------------------------------------------
# Duplicate url_canonical — skipped
# ---------------------------------------------------------------------------


async def test_duplicate_skipped_no_id_returned(session: AsyncSession) -> None:
    await write_staging_rows(session, [_draft("dup-1")])
    outcome = await write_staging_rows(session, [_draft("dup-1")])

    assert len(outcome.inserted_ids) == 0
    assert outcome.skipped_duplicate_count == 1


# ---------------------------------------------------------------------------
# Mixed batch — partial insert
# ---------------------------------------------------------------------------


async def test_mixed_batch_partial_insert(session: AsyncSession) -> None:
    await write_staging_rows(session, [_draft("existing")])

    batch = [_draft("existing"), _draft("new-a"), _draft("new-b")]
    outcome = await write_staging_rows(session, batch)

    assert len(outcome.inserted_ids) == 2
    assert outcome.skipped_duplicate_count == 1


# ---------------------------------------------------------------------------
# Empty batch
# ---------------------------------------------------------------------------


async def test_empty_batch_returns_zero(session: AsyncSession) -> None:
    outcome = await write_staging_rows(session, [])
    assert outcome.inserted_ids == ()
    assert outcome.skipped_duplicate_count == 0


# ---------------------------------------------------------------------------
# Large batch chunking (> BATCH_SIZE)
# ---------------------------------------------------------------------------


async def test_large_batch_chunks_correctly(session: AsyncSession) -> None:
    drafts = [_draft(f"row-{i}") for i in range(600)]
    outcome = await write_staging_rows(session, drafts)

    assert len(outcome.inserted_ids) == 600
    assert outcome.skipped_duplicate_count == 0


# ---------------------------------------------------------------------------
# LLM-filled columns are NULL (D2 compliance)
# ---------------------------------------------------------------------------


async def test_llm_columns_are_null(session: AsyncSession) -> None:
    await write_staging_rows(session, [_draft("llm-null")])

    result = await session.execute(
        sa.select(
            staging_table.c.summary,
            staging_table.c.tags_jsonb,
            staging_table.c.confidence,
        ).where(staging_table.c.url_canonical == "llm-null")
    )
    row = result.first()
    assert row is not None
    assert row.summary is None
    assert row.tags_jsonb is None
    assert row.confidence is None


# ---------------------------------------------------------------------------
# WriteOutcome is frozen
# ---------------------------------------------------------------------------


def test_write_outcome_is_frozen() -> None:
    outcome = WriteOutcome(inserted_ids=(1,), skipped_duplicate_count=0)
    with pytest.raises(AttributeError):
        outcome.skipped_duplicate_count = 99  # type: ignore[misc]
