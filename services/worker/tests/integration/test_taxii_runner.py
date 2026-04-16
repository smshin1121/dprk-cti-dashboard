"""Integration tests for worker.ingest.taxii.runner.

Full pipeline: fetch → parse → normalize → write → audit → DQ
against MockTransport + sqlite-memory.

Key invariants verified:
  - state advance ONLY on full success
  - partial failure does NOT advance last_added_after
  - url_canonical = urn:stix:{type}--{uuid} in all staging rows
  - audit events match expected counts
  - dq_events have taxii.* prefix
  - idempotent second run (all duplicates)
  - zero writes to production tables
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.tables import (
    audit_log_table,
    groups_table,
    metadata,
    reports_table,
    sources_table,
    staging_table,
    tags_table,
)
from worker.ingest.taxii.audit import TaxiiRunMeta, new_taxii_meta
from worker.ingest.taxii.config import TaxiiCollectionConfig, TaxiiCatalog
from worker.ingest.taxii.fetcher import TaxiiFetcher
from worker.ingest.taxii.runner import run_taxii_ingest
from worker.ingest.taxii.state import load_state

import datetime as dt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TAXII_CT = "application/taxii+json;version=2.1"


def _stix_obj(type_: str, id_suffix: str, **extra) -> dict:
    obj = {
        "type": type_,
        "id": f"{type_}--00000000-0000-0000-0000-{id_suffix:>012}",
        "name": f"Test {type_} {id_suffix}",
        "created": "2026-01-01T00:00:00Z",
        "modified": "2026-04-15T00:00:00Z",
        "description": f"Description of {type_} {id_suffix}",
    }
    obj.update(extra)
    return obj


def _envelope(objects, more=False, next_param=None):
    env = {"objects": objects}
    if more:
        env["more"] = True
    if next_param is not None:
        env["next"] = next_param
    return env


def _make_config(**overrides) -> TaxiiCollectionConfig:
    base = {
        "slug": "test-col",
        "display_name": "Test",
        "server_url": "https://taxii.example.com",
        "api_root_path": "/api/",
        "collection_id": "col-1",
        "max_pages": 100,
    }
    base.update(overrides)
    return TaxiiCollectionConfig(**base)


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
# Happy path — full pipeline
# ---------------------------------------------------------------------------


async def test_full_pipeline_inserts_staging_rows(
    session: AsyncSession,
) -> None:
    objects = [
        _stix_obj("intrusion-set", "001"),
        _stix_obj("malware", "002"),
        _stix_obj("tool", "003"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects, more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    catalog = TaxiiCatalog(collections=(_make_config(),))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        outcome = await run_taxii_ingest(
            session,
            catalog=catalog,
            fetcher=fetcher,
            run_id=meta.run_id,
            audit_meta=meta,
        )

    assert outcome.total_inserted == 3
    assert outcome.total_skipped_duplicate == 0
    assert not outcome.all_collections_failed

    # Verify staging rows
    rows = (await session.execute(select(staging_table))).all()
    assert len(rows) == 3
    for row in rows:
        assert row.url_canonical.startswith("urn:stix:")
        assert row.source_id is None
        assert row.summary is None


async def test_state_advanced_on_full_success(
    session: AsyncSession,
) -> None:
    objects = [_stix_obj("intrusion-set", "001")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects, more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    catalog = TaxiiCatalog(collections=(_make_config(),))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        outcome = await run_taxii_ingest(
            session,
            catalog=catalog,
            fetcher=fetcher,
            run_id=meta.run_id,
            audit_meta=meta,
        )

    assert outcome.collection_results[0].state_advanced is True
    state = await load_state(session, "test-col")
    assert state is not None
    assert state.last_added_after is not None
    assert state.consecutive_failures == 0
    assert state.last_error is None


# ---------------------------------------------------------------------------
# State advance guard — critical invariant
# ---------------------------------------------------------------------------


async def test_state_not_advanced_on_fetch_failure(
    session: AsyncSession,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    catalog = TaxiiCatalog(collections=(_make_config(),))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        outcome = await run_taxii_ingest(
            session,
            catalog=catalog,
            fetcher=fetcher,
            run_id=meta.run_id,
            audit_meta=meta,
        )

    assert outcome.collection_results[0].state_advanced is False
    state = await load_state(session, "test-col")
    assert state is not None
    assert state.last_added_after is None
    assert state.consecutive_failures == 1


async def test_state_not_advanced_on_max_pages(
    session: AsyncSession,
) -> None:
    """max_pages truncation = incomplete fetch = no state advance."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json=_envelope(
                [_stix_obj("malware", str(call_count).zfill(3))],
                more=True,
                next_param=f"page{call_count + 1}",
            ),
            headers={"Content-Type": _TAXII_CT},
        )

    config = _make_config(max_pages=2)
    catalog = TaxiiCatalog(collections=(config,))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        outcome = await run_taxii_ingest(
            session,
            catalog=catalog,
            fetcher=fetcher,
            run_id=meta.run_id,
            audit_meta=meta,
        )

    # Objects still written (valid data)
    assert outcome.total_inserted == 2
    # But state NOT advanced
    assert outcome.collection_results[0].state_advanced is False
    state = await load_state(session, "test-col")
    assert state is not None
    assert state.last_added_after is None  # Never advanced


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


async def test_audit_events_correct_counts(session: AsyncSession) -> None:
    objects = [_stix_obj("intrusion-set", "001"), _stix_obj("malware", "002")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects, more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    catalog = TaxiiCatalog(collections=(_make_config(),))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        await run_taxii_ingest(
            session,
            catalog=catalog,
            fetcher=fetcher,
            run_id=meta.run_id,
            audit_meta=meta,
        )

    rows = (await session.execute(select(audit_log_table))).all()
    actions = [r.action for r in rows]
    assert actions.count("taxii_run_started") == 1
    assert actions.count("staging_insert") == 2
    assert actions.count("taxii_run_completed") == 1
    assert actions.count("taxii_run_failed") == 0
    # All with actor="taxii_ingest"
    assert all(r.actor == "taxii_ingest" for r in rows)


# ---------------------------------------------------------------------------
# DQ metrics — taxii.* namespace
# ---------------------------------------------------------------------------


async def test_dq_results_have_taxii_prefix(session: AsyncSession) -> None:
    objects = [_stix_obj("intrusion-set", "001")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects, more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    catalog = TaxiiCatalog(collections=(_make_config(),))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        outcome = await run_taxii_ingest(
            session,
            catalog=catalog,
            fetcher=fetcher,
            run_id=meta.run_id,
        )

    assert len(outcome.dq_results) == 4
    for r in outcome.dq_results:
        assert r.name.startswith("taxii.")


# ---------------------------------------------------------------------------
# Idempotent second run
# ---------------------------------------------------------------------------


async def test_idempotent_second_run_all_duplicates(
    session: AsyncSession,
) -> None:
    objects = [_stix_obj("intrusion-set", "001"), _stix_obj("malware", "002")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects, more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    catalog = TaxiiCatalog(collections=(_make_config(),))

    # First run
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta1 = new_taxii_meta("test.yml")
        outcome1 = await run_taxii_ingest(
            session, catalog=catalog, fetcher=fetcher,
            run_id=meta1.run_id, audit_meta=meta1,
        )

    assert outcome1.total_inserted == 2

    # Second run — same objects
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta2 = new_taxii_meta("test.yml")
        outcome2 = await run_taxii_ingest(
            session, catalog=catalog, fetcher=fetcher,
            run_id=meta2.run_id, audit_meta=meta2,
        )

    assert outcome2.total_inserted == 0
    assert outcome2.total_skipped_duplicate == 2
    # Still emits 4 DQ metrics
    assert len(outcome2.dq_results) == 4


# ---------------------------------------------------------------------------
# Production zero-write guarantee (D3)
# ---------------------------------------------------------------------------


async def test_zero_writes_to_production_tables(
    session: AsyncSession,
) -> None:
    """D3 invariant: zero writes to groups/sources/reports/tags."""
    objects = [_stix_obj("intrusion-set", "001")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects, more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    # Snapshot row counts before
    before = {}
    for table in (groups_table, sources_table, reports_table, tags_table):
        result = await session.execute(
            select(func.count()).select_from(table)
        )
        before[table.name] = result.scalar()

    catalog = TaxiiCatalog(collections=(_make_config(),))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        await run_taxii_ingest(
            session, catalog=catalog, fetcher=fetcher,
            run_id=meta.run_id, audit_meta=meta,
        )

    # Snapshot after
    for table in (groups_table, sources_table, reports_table, tags_table):
        result = await session.execute(
            select(func.count()).select_from(table)
        )
        after = result.scalar()
        assert after == before[table.name], (
            f"{table.name} had {before[table.name]} rows before, "
            f"{after} after — D3 zero-write violation!"
        )


# ---------------------------------------------------------------------------
# All-collections-failed
# ---------------------------------------------------------------------------


async def test_all_collections_failed_flag(session: AsyncSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    catalog = TaxiiCatalog(collections=(_make_config(),))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        fetcher = TaxiiFetcher(client=client)
        meta = new_taxii_meta("test.yml")
        outcome = await run_taxii_ingest(
            session, catalog=catalog, fetcher=fetcher,
            run_id=meta.run_id, audit_meta=meta,
        )

    assert outcome.all_collections_failed is True
    # Audit shows taxii_run_failed
    rows = (await session.execute(select(audit_log_table))).all()
    actions = [r.action for r in rows]
    assert "taxii_run_failed" in actions
