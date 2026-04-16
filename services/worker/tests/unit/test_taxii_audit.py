"""Tests for worker.ingest.taxii.audit — TAXII audit trail writers.

Verifies independence from RSS/bootstrap audit modules and correct
actor/entity/action shapes.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.tables import audit_log_table, metadata
from worker.ingest.taxii.audit import (
    STAGING_INSERT,
    TAXII_INGEST_ACTOR,
    TAXII_RUN_COMPLETED,
    TAXII_RUN_FAILED,
    TAXII_RUN_STARTED,
    TaxiiRunMeta,
    new_taxii_meta,
    write_staging_insert_audit,
    write_taxii_run_audit,
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


def _meta(**overrides) -> TaxiiRunMeta:
    base = {
        "run_id": uuid.uuid4(),
        "collections_path": "data/dictionaries/taxii_collections.yml",
        "started_at": dt.datetime.now(dt.timezone.utc),
    }
    base.update(overrides)
    return TaxiiRunMeta(**base)


# ---------------------------------------------------------------------------
# TaxiiRunMeta
# ---------------------------------------------------------------------------


def test_taxii_run_meta_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TaxiiRunMeta(
            run_id=uuid.uuid4(),
            collections_path="test.yml",
            started_at=dt.datetime(2026, 4, 16, 12, 0, 0),  # naive
        )


def test_taxii_run_meta_as_dict() -> None:
    meta = _meta()
    d = meta.as_dict()
    assert "run_id" in d
    assert "collections_path" in d
    assert "started_at" in d


def test_new_taxii_meta_creates_valid_instance() -> None:
    meta = new_taxii_meta("test.yml")
    assert meta.collections_path == "test.yml"
    assert meta.started_at.tzinfo is not None
    assert isinstance(meta.run_id, uuid.UUID)


# ---------------------------------------------------------------------------
# Actor/entity constants are independent from RSS
# ---------------------------------------------------------------------------


def test_actor_is_taxii_ingest() -> None:
    assert TAXII_INGEST_ACTOR == "taxii_ingest"
    # Must differ from RSS
    from worker.ingest.audit import INGEST_ACTOR
    assert TAXII_INGEST_ACTOR != INGEST_ACTOR


def test_action_constants_differ_from_rss() -> None:
    from worker.ingest.audit import RSS_RUN_STARTED, RSS_RUN_COMPLETED, RSS_RUN_FAILED
    assert TAXII_RUN_STARTED != RSS_RUN_STARTED
    assert TAXII_RUN_COMPLETED != RSS_RUN_COMPLETED
    assert TAXII_RUN_FAILED != RSS_RUN_FAILED


# ---------------------------------------------------------------------------
# write_taxii_run_audit — run-level events
# ---------------------------------------------------------------------------


async def test_run_started_writes_correct_shape(session: AsyncSession) -> None:
    meta = _meta()
    await write_taxii_run_audit(session, action=TAXII_RUN_STARTED, meta=meta)

    rows = (await session.execute(select(audit_log_table))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == "taxii_ingest"
    assert row.action == "taxii_run_started"
    assert row.entity == "taxii_run"
    assert row.entity_id is None


async def test_run_completed_with_detail(session: AsyncSession) -> None:
    meta = _meta()
    detail = {"total_inserted": 42, "total_collections": 3}
    await write_taxii_run_audit(
        session, action=TAXII_RUN_COMPLETED, meta=meta, detail=detail,
    )

    rows = (await session.execute(select(audit_log_table))).all()
    assert len(rows) == 1
    assert rows[0].action == "taxii_run_completed"
    assert rows[0].diff_jsonb["detail"]["total_inserted"] == 42


async def test_run_failed_writes_correctly(session: AsyncSession) -> None:
    meta = _meta()
    await write_taxii_run_audit(
        session, action=TAXII_RUN_FAILED, meta=meta,
        detail={"all_collections_failed": True},
    )

    rows = (await session.execute(select(audit_log_table))).all()
    assert len(rows) == 1
    assert rows[0].action == "taxii_run_failed"


async def test_run_audit_rejects_invalid_action(session: AsyncSession) -> None:
    meta = _meta()
    with pytest.raises(ValueError, match="unknown"):
        await write_taxii_run_audit(
            session, action="invalid_action", meta=meta,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# write_staging_insert_audit — row-level events
# ---------------------------------------------------------------------------


async def test_staging_insert_writes_correct_shape(
    session: AsyncSession,
) -> None:
    meta = _meta()
    await write_staging_insert_audit(
        session, meta=meta, staging_id=123,
        url_canonical="urn:stix:intrusion-set--abc",
    )

    rows = (await session.execute(select(audit_log_table))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == "taxii_ingest"
    assert row.action == "staging_insert"
    assert row.entity == "staging"
    assert row.entity_id == "123"
    assert row.diff_jsonb["url_canonical"] == "urn:stix:intrusion-set--abc"
    assert row.diff_jsonb["op"] == "insert"


# ---------------------------------------------------------------------------
# Multiple events — isolation
# ---------------------------------------------------------------------------


async def test_multiple_events_coexist(session: AsyncSession) -> None:
    meta = _meta()
    await write_taxii_run_audit(session, action=TAXII_RUN_STARTED, meta=meta)
    await write_staging_insert_audit(
        session, meta=meta, staging_id=1, url_canonical="urn:stix:x--1",
    )
    await write_staging_insert_audit(
        session, meta=meta, staging_id=2, url_canonical="urn:stix:x--2",
    )
    await write_taxii_run_audit(
        session, action=TAXII_RUN_COMPLETED, meta=meta,
    )

    rows = (await session.execute(select(audit_log_table))).all()
    assert len(rows) == 4
    actions = [r.action for r in rows]
    assert actions.count("taxii_run_started") == 1
    assert actions.count("staging_insert") == 2
    assert actions.count("taxii_run_completed") == 1
