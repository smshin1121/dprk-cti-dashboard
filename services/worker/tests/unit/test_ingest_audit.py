"""Tests for worker.ingest.audit — RSS ingest audit trail writers."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.tables import audit_log_table, metadata
from worker.ingest.audit import (
    INGEST_ACTOR,
    RSS_RUN_COMPLETED,
    RSS_RUN_FAILED,
    RSS_RUN_STARTED,
    STAGING_INSERT,
    IngestRunMeta,
    write_ingest_run_audit,
    write_staging_insert_audit,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        async with sess.begin():
            yield sess
    await engine.dispose()


def _meta(run_id: uuid.UUID | None = None) -> IngestRunMeta:
    return IngestRunMeta(
        run_id=run_id or uuid.uuid4(),
        feeds_path="data/dictionaries/feeds.yml",
        started_at=dt.datetime.now(dt.timezone.utc),
    )


async def _count_audit(session: AsyncSession, **filters) -> int:
    stmt = sa.select(sa.func.count()).select_from(audit_log_table)
    for col, val in filters.items():
        stmt = stmt.where(audit_log_table.c[col] == val)
    result = await session.execute(stmt)
    return result.scalar_one()


async def _get_audit_row(session: AsyncSession, action: str):
    result = await session.execute(
        sa.select(audit_log_table).where(
            audit_log_table.c.action == action
        )
    )
    return result.first()


# ---------------------------------------------------------------------------
# IngestRunMeta
# ---------------------------------------------------------------------------


def test_ingest_run_meta_rejects_naive_started_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        IngestRunMeta(
            run_id=uuid.uuid4(),
            feeds_path="feeds.yml",
            started_at=dt.datetime(2026, 4, 16, 12, 0, 0),
        )


def test_ingest_run_meta_as_dict() -> None:
    meta = _meta()
    d = meta.as_dict()
    assert "run_id" in d
    assert "feeds_path" in d
    assert "started_at" in d
    assert d["feeds_path"] == "data/dictionaries/feeds.yml"


def test_ingest_run_meta_is_frozen() -> None:
    meta = _meta()
    with pytest.raises(AttributeError):
        meta.feeds_path = "mutate"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# write_ingest_run_audit — run-level events
# ---------------------------------------------------------------------------


async def test_run_started_shape(session: AsyncSession) -> None:
    meta = _meta()
    await write_ingest_run_audit(session, action=RSS_RUN_STARTED, meta=meta)

    row = await _get_audit_row(session, RSS_RUN_STARTED)
    assert row is not None
    assert row.actor == INGEST_ACTOR
    assert row.entity == "rss_run"
    assert row.entity_id is None
    assert row.diff_jsonb["meta"]["run_id"] == str(meta.run_id)
    assert row.diff_jsonb["meta"]["feeds_path"] == "data/dictionaries/feeds.yml"


async def test_run_completed_shape(session: AsyncSession) -> None:
    meta = _meta()
    detail = {"total_inserted": 5, "total_skipped": 2}
    await write_ingest_run_audit(
        session, action=RSS_RUN_COMPLETED, meta=meta, detail=detail,
    )

    row = await _get_audit_row(session, RSS_RUN_COMPLETED)
    assert row is not None
    assert row.actor == INGEST_ACTOR
    assert row.diff_jsonb["detail"]["total_inserted"] == 5


async def test_run_failed_shape(session: AsyncSession) -> None:
    meta = _meta()
    detail = {"all_feeds_failed": True, "error": "all 500"}
    await write_ingest_run_audit(
        session, action=RSS_RUN_FAILED, meta=meta, detail=detail,
    )

    row = await _get_audit_row(session, RSS_RUN_FAILED)
    assert row is not None
    assert row.actor == INGEST_ACTOR
    assert row.diff_jsonb["detail"]["all_feeds_failed"] is True


async def test_run_audit_rejects_unknown_action(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="unknown"):
        await write_ingest_run_audit(
            session, action="bogus_action", meta=_meta(),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# write_staging_insert_audit — row-level events
# ---------------------------------------------------------------------------


async def test_staging_insert_shape(session: AsyncSession) -> None:
    meta = _meta()
    await write_staging_insert_audit(
        session, meta=meta, staging_id=42, url_canonical="example.com/report",
    )

    row = await _get_audit_row(session, STAGING_INSERT)
    assert row is not None
    assert row.actor == INGEST_ACTOR
    assert row.entity == "staging"
    assert row.entity_id == "42"
    assert row.diff_jsonb["op"] == "insert"
    assert row.diff_jsonb["url_canonical"] == "example.com/report"
    assert row.diff_jsonb["meta"]["run_id"] == str(meta.run_id)


async def test_staging_insert_multiple_rows(session: AsyncSession) -> None:
    meta = _meta()
    for i in range(3):
        await write_staging_insert_audit(
            session, meta=meta, staging_id=i + 1, url_canonical=f"url-{i}",
        )

    count = await _count_audit(session, action=STAGING_INSERT)
    assert count == 3


# ---------------------------------------------------------------------------
# Actor consistency
# ---------------------------------------------------------------------------


async def test_all_events_use_rss_ingest_actor(session: AsyncSession) -> None:
    meta = _meta()
    await write_ingest_run_audit(session, action=RSS_RUN_STARTED, meta=meta)
    await write_staging_insert_audit(
        session, meta=meta, staging_id=1, url_canonical="x",
    )
    await write_ingest_run_audit(session, action=RSS_RUN_COMPLETED, meta=meta)

    result = await session.execute(
        sa.select(audit_log_table.c.actor).distinct()
    )
    actors = [row[0] for row in result.all()]
    assert actors == [INGEST_ACTOR]


# ---------------------------------------------------------------------------
# Meta consistency — same run_id across all event types
# ---------------------------------------------------------------------------


async def test_shared_run_id_across_events(session: AsyncSession) -> None:
    run_id = uuid.uuid4()
    meta = _meta(run_id=run_id)

    await write_ingest_run_audit(session, action=RSS_RUN_STARTED, meta=meta)
    await write_staging_insert_audit(
        session, meta=meta, staging_id=1, url_canonical="x",
    )
    await write_ingest_run_audit(session, action=RSS_RUN_COMPLETED, meta=meta)

    result = await session.execute(sa.select(audit_log_table.c.diff_jsonb))
    rows = result.all()

    run_ids = {row[0]["meta"]["run_id"] for row in rows}
    assert run_ids == {str(run_id)}


# ---------------------------------------------------------------------------
# worker.bootstrap.audit is NOT modified (D8 guarantee)
# ---------------------------------------------------------------------------


def test_bootstrap_audit_constants_unchanged() -> None:
    from worker.bootstrap.audit import (
        AUDIT_ACTOR,
        ENTITY_TABLES_AUDITED,
        RUN_ENTITY,
        RUN_STARTED,
        RUN_COMPLETED,
        RUN_FAILED,
    )
    assert AUDIT_ACTOR == "bootstrap_etl"
    assert RUN_ENTITY == "etl_run"
    assert RUN_STARTED == "etl_run_started"
    assert RUN_COMPLETED == "etl_run_completed"
    assert RUN_FAILED == "etl_run_failed"
    assert "staging" not in ENTITY_TABLES_AUDITED
