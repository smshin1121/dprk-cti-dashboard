"""Integration tests for worker.ingest.runner — full pipeline."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.aliases import load_aliases
from worker.bootstrap.tables import (
    metadata,
    staging_table,
    groups_table,
    sources_table,
    reports_table,
    tags_table,
    codenames_table,
    incidents_table,
)
from worker.ingest.config import FeedCatalog, FeedConfig
from worker.ingest.fetcher import RssFetcher
from worker.ingest.runner import run_rss_ingest


REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = REPO_ROOT / "services/worker/tests/fixtures/rss"
ALIASES = load_aliases(REPO_ROOT / "data/dictionaries/aliases.yml")

RSS_CONTENT = (FIXTURES / "sample_rss.xml").read_bytes()


def _catalog(*feeds: FeedConfig) -> FeedCatalog:
    return FeedCatalog(feeds=feeds)


FEED_A = FeedConfig(
    slug="feed-a",
    display_name="Feed A",
    url="https://feed-a.example.com/rss",
    kind="rss",
)
FEED_B = FeedConfig(
    slug="feed-b",
    display_name="Feed B",
    url="https://feed-b.example.com/rss",
    kind="rss",
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


def _mock_client_ok(content: bytes = RSS_CONTENT):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _mock_client_mixed():
    """Feed A returns 200, Feed B returns 500."""
    async def handler(request: httpx.Request) -> httpx.Response:
        if "feed-a" in str(request.url):
            return httpx.Response(200, content=RSS_CONTENT)
        return httpx.Response(500)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _mock_client_all_fail():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Happy path — all feeds succeed
# ---------------------------------------------------------------------------


async def test_run_inserts_staging_rows(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_ok())
    catalog = _catalog(FEED_A)
    run_id = uuid.uuid4()

    outcome = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=run_id,
    )

    assert outcome.total_inserted >= 2
    assert outcome.total_skipped_duplicate == 0
    assert not outcome.all_feeds_failed
    await fetcher.close()


async def test_run_emits_4_dq_metrics(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_ok())
    catalog = _catalog(FEED_A)

    outcome = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )

    assert len(outcome.dq_results) == 4
    names = {r.name for r in outcome.dq_results}
    assert names == {
        "feed.fetch_failure_rate",
        "feed.parse_error_rate",
        "feed.empty_title_rate",
        "rss.tags.unknown_rate",
    }
    await fetcher.close()


async def test_dq_metric_names_prefixed(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_ok())
    catalog = _catalog(FEED_A)

    outcome = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )

    for r in outcome.dq_results:
        assert r.name.startswith("feed.") or r.name.startswith("rss.")
    await fetcher.close()


# ---------------------------------------------------------------------------
# Idempotent second run — all skipped
# ---------------------------------------------------------------------------


async def test_idempotent_second_run(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_ok())
    catalog = _catalog(FEED_A)

    first = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )
    second = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )

    assert first.total_inserted >= 2
    assert second.total_inserted == 0
    assert second.total_skipped_duplicate >= 2
    assert len(second.dq_results) == 4
    await fetcher.close()


# ---------------------------------------------------------------------------
# Per-feed failure isolation
# ---------------------------------------------------------------------------


async def test_one_feed_failure_does_not_abort_run(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_mixed())
    catalog = _catalog(FEED_A, FEED_B)

    outcome = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )

    assert outcome.total_inserted >= 2
    assert outcome.total_fetch_failures == 1
    assert not outcome.all_feeds_failed

    a_result = next(r for r in outcome.feed_results if r.slug == "feed-a")
    b_result = next(r for r in outcome.feed_results if r.slug == "feed-b")
    assert a_result.fetched
    assert not b_result.fetched
    assert b_result.fetch_error is not None
    await fetcher.close()


# ---------------------------------------------------------------------------
# All feeds fail — all_feeds_failed=True
# ---------------------------------------------------------------------------


async def test_all_feeds_fail(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_all_fail())
    catalog = _catalog(FEED_A, FEED_B)

    outcome = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )

    assert outcome.all_feeds_failed
    assert outcome.total_inserted == 0
    assert outcome.total_fetch_failures == 2
    await fetcher.close()


async def test_all_feeds_fail_fetch_failure_rate_is_1(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_all_fail())
    catalog = _catalog(FEED_A, FEED_B)

    outcome = await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )

    ffr = next(r for r in outcome.dq_results if r.name == "feed.fetch_failure_rate")
    assert float(ffr.observed) == 1.0
    assert ffr.severity == "warn"
    await fetcher.close()


# ---------------------------------------------------------------------------
# D2 invariant — zero writes to production tables
# ---------------------------------------------------------------------------


async def test_d2_invariant_zero_production_writes(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_ok())
    catalog = _catalog(FEED_A)

    # Snapshot production table counts before
    tables = [groups_table, sources_table, codenames_table, reports_table, tags_table, incidents_table]
    before = {}
    for t in tables:
        result = await session.execute(select(func.count()).select_from(t))
        before[t.name] = result.scalar_one()

    await run_rss_ingest(
        session, catalog=catalog, fetcher=fetcher,
        aliases=ALIASES, run_id=uuid.uuid4(),
    )

    for t in tables:
        result = await session.execute(select(func.count()).select_from(t))
        after = result.scalar_one()
        assert after == before[t.name], f"production table {t.name} was modified"

    await fetcher.close()


# ---------------------------------------------------------------------------
# Run ID propagation
# ---------------------------------------------------------------------------


async def test_run_id_propagated_to_outcome(session: AsyncSession) -> None:
    fetcher = RssFetcher(client=_mock_client_ok())
    run_id = uuid.uuid4()

    outcome = await run_rss_ingest(
        session, catalog=_catalog(FEED_A), fetcher=fetcher,
        aliases=ALIASES, run_id=run_id,
    )

    assert outcome.run_id == run_id
    await fetcher.close()
