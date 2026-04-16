"""RSS ingest orchestrator — per-feed failure isolation.

Runs through the feed catalog, fetches + parses + normalizes +
writes each feed independently. A failure in one feed does not
abort the run or prevent other feeds from being processed.

After all feeds are processed, computes the 4 D10 feed-level DQ
metrics and emits them through the standard DQ sink fan-out.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import AliasDictionary
from worker.data_quality.results import ExpectationResult, Sink
from worker.ingest.config import FeedCatalog, FeedConfig
from worker.ingest.feed_state import FeedStateRow, load_state, upsert_state
from worker.ingest.fetcher import FetchOutcome, RssFetcher
from worker.ingest.normalize import StagingRowDraft, normalize_entry
from worker.ingest.parser import parse_feed
from worker.ingest.staging_writer import WriteOutcome, write_staging_rows
from worker.ingest.tag_preview import preview_tags


__all__ = [
    "RunOutcome",
    "run_rss_ingest",
]


@dataclass(frozen=True, slots=True)
class FeedResult:
    """Outcome for a single feed within a run."""

    slug: str
    fetched: bool
    parsed_entries: int
    inserted: int
    skipped_duplicate: int
    parse_error: bool
    fetch_error: str | None
    not_modified: bool


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Aggregate outcome for the entire ingest run."""

    run_id: uuid.UUID
    feed_results: tuple[FeedResult, ...]
    total_inserted: int
    total_skipped_duplicate: int
    total_parse_errors: int
    total_fetch_failures: int
    all_feeds_failed: bool
    inserted_ids: tuple[int, ...]
    dq_results: tuple[ExpectationResult, ...] = ()


async def run_rss_ingest(
    session: AsyncSession,
    *,
    catalog: FeedCatalog,
    fetcher: RssFetcher,
    aliases: AliasDictionary,
    run_id: uuid.UUID,
    sinks: list[Sink] | None = None,
) -> RunOutcome:
    """Run the full RSS ingest pipeline with per-feed isolation."""
    enabled = catalog.enabled
    feed_results_final: list[FeedResult] = []
    all_inserted_ids_final: list[int] = []
    tag_total = 0
    tag_unknown = 0
    empty_title_count = 0
    total_entries = 0

    for feed_cfg in enabled:
        fr, inserted_ids, entries_count, empty_titles, tag_t, tag_u = (
            await _process_feed_full(
                session, feed_cfg, fetcher, aliases
            )
        )
        feed_results_final.append(fr)
        all_inserted_ids_final.extend(inserted_ids)
        total_entries += entries_count
        empty_title_count += empty_titles
        tag_total += tag_t
        tag_unknown += tag_u

    total_inserted = sum(fr.inserted for fr in feed_results_final)
    total_skipped = sum(fr.skipped_duplicate for fr in feed_results_final)
    total_parse_errors = sum(1 for fr in feed_results_final if fr.parse_error)
    total_fetch_failures = sum(
        1 for fr in feed_results_final
        if fr.fetch_error is not None and not fr.not_modified
    )

    n_enabled = len(enabled)
    all_failed = n_enabled > 0 and total_fetch_failures == n_enabled

    # Compute D10 feed-level DQ metrics
    dq_results = _compute_dq_metrics(
        n_feeds=n_enabled,
        n_fetch_failures=total_fetch_failures,
        n_parse_errors=total_parse_errors,
        n_entries=total_entries,
        n_empty_titles=empty_title_count,
        n_tag_total=tag_total,
        n_tag_unknown=tag_unknown,
    )

    # Emit through sinks
    if sinks and dq_results:
        for sink in sinks:
            try:
                await sink.write(list(dq_results))
            except Exception:
                pass  # sink failures don't abort the run

    return RunOutcome(
        run_id=run_id,
        feed_results=tuple(feed_results_final),
        total_inserted=total_inserted,
        total_skipped_duplicate=total_skipped,
        total_parse_errors=total_parse_errors,
        total_fetch_failures=total_fetch_failures,
        all_feeds_failed=all_failed,
        inserted_ids=tuple(all_inserted_ids_final),
        dq_results=dq_results,
    )


async def _process_feed_full(
    session: AsyncSession,
    feed: FeedConfig,
    fetcher: RssFetcher,
    aliases: AliasDictionary,
) -> tuple[FeedResult, list[int], int, int, int, int]:
    """Process one feed. Returns (FeedResult, inserted_ids, entries_count,
    empty_title_count, tag_total, tag_unknown).

    Per-feed failure isolation: exceptions are caught and recorded,
    never propagated.
    """
    state = await load_state(session, feed.slug)
    inserted_ids: list[int] = []
    entries_count = 0
    empty_titles = 0
    tag_t = 0
    tag_u = 0

    try:
        outcome = await fetcher.fetch(feed, state=state)
    except Exception as exc:
        await _update_state_failure(session, feed.slug, str(exc))
        return (
            FeedResult(
                slug=feed.slug, fetched=False, parsed_entries=0,
                inserted=0, skipped_duplicate=0, parse_error=False,
                fetch_error=str(exc), not_modified=False,
            ),
            [], 0, 0, 0, 0,
        )

    # Update feed state based on outcome
    if outcome.is_ok:
        await upsert_state(
            session,
            feed_slug=feed.slug,
            etag=outcome.etag,
            last_modified=outcome.last_modified,
            last_status_code=outcome.status_code,
            last_error=None,
            reset_failures=True,
        )
    else:
        await upsert_state(
            session,
            feed_slug=feed.slug,
            etag=outcome.etag,
            last_modified=outcome.last_modified,
            last_status_code=outcome.status_code,
            last_error=outcome.error,
            reset_failures=False,
        )
        return (
            FeedResult(
                slug=feed.slug, fetched=False, parsed_entries=0,
                inserted=0, skipped_duplicate=0, parse_error=False,
                fetch_error=outcome.error, not_modified=False,
            ),
            [], 0, 0, 0, 0,
        )

    if outcome.is_not_modified:
        return (
            FeedResult(
                slug=feed.slug, fetched=True, parsed_entries=0,
                inserted=0, skipped_duplicate=0, parse_error=False,
                fetch_error=None, not_modified=True,
            ),
            [], 0, 0, 0, 0,
        )

    # Parse
    parsed = parse_feed(outcome.content, feed.kind)  # type: ignore[arg-type]
    has_parse_error = parsed.parse_error is not None
    entries_count = len(parsed.entries)

    # Normalize + tag preview
    drafts: list[StagingRowDraft] = []
    for entry in parsed.entries:
        if entry.title is None:
            empty_titles += 1
        tp = preview_tags(entry.title, entry.summary, aliases)
        tag_t += tp.total
        tag_u += tp.unknown
        draft = normalize_entry(entry)
        if draft is not None:
            drafts.append(draft)

    # Write to staging
    write_outcome = WriteOutcome(inserted_ids=(), skipped_duplicate_count=0)
    if drafts:
        write_outcome = await write_staging_rows(session, drafts)
        inserted_ids = list(write_outcome.inserted_ids)

    return (
        FeedResult(
            slug=feed.slug,
            fetched=True,
            parsed_entries=entries_count,
            inserted=len(write_outcome.inserted_ids),
            skipped_duplicate=write_outcome.skipped_duplicate_count,
            parse_error=has_parse_error,
            fetch_error=None,
            not_modified=False,
        ),
        inserted_ids, entries_count, empty_titles, tag_t, tag_u,
    )


async def _update_state_failure(
    session: AsyncSession,
    feed_slug: str,
    error: str,
) -> None:
    try:
        await upsert_state(
            session,
            feed_slug=feed_slug,
            last_error=error,
            reset_failures=False,
        )
    except Exception:
        pass


def _compute_dq_metrics(
    *,
    n_feeds: int,
    n_fetch_failures: int,
    n_parse_errors: int,
    n_entries: int,
    n_empty_titles: int,
    n_tag_total: int,
    n_tag_unknown: int,
) -> tuple[ExpectationResult, ...]:
    """Compute the 4 D10 feed-level DQ metrics."""
    results: list[ExpectationResult] = []

    # 1. feed.fetch_failure_rate
    fetch_rate = Decimal(str(n_fetch_failures / n_feeds)) if n_feeds > 0 else Decimal("0")
    fetch_threshold = Decimal("0.20")
    results.append(ExpectationResult(
        name="feed.fetch_failure_rate",
        severity="warn" if fetch_rate > fetch_threshold else "pass",
        observed=fetch_rate,
        threshold=fetch_threshold,
        observed_rows=n_fetch_failures,
        detail={"total_feeds": n_feeds, "failed_feeds": n_fetch_failures},
    ))

    # 2. feed.parse_error_rate
    n_fetched = n_feeds - n_fetch_failures
    parse_rate = Decimal(str(n_parse_errors / n_fetched)) if n_fetched > 0 else Decimal("0")
    parse_threshold = Decimal("0.10")
    results.append(ExpectationResult(
        name="feed.parse_error_rate",
        severity="warn" if parse_rate > parse_threshold else "pass",
        observed=parse_rate,
        threshold=parse_threshold,
        observed_rows=n_parse_errors,
        detail={"fetched_feeds": n_fetched, "parse_errors": n_parse_errors},
    ))

    # 3. feed.empty_title_rate
    empty_rate = Decimal(str(n_empty_titles / n_entries)) if n_entries > 0 else Decimal("0")
    empty_threshold = Decimal("0.05")
    results.append(ExpectationResult(
        name="feed.empty_title_rate",
        severity="warn" if empty_rate > empty_threshold else "pass",
        observed=empty_rate,
        threshold=empty_threshold,
        observed_rows=n_empty_titles,
        detail={"total_entries": n_entries, "empty_titles": n_empty_titles},
    ))

    # 4. rss.tags.unknown_rate
    unknown_rate = Decimal(str(n_tag_unknown / n_tag_total)) if n_tag_total > 0 else Decimal("0")
    unknown_threshold = Decimal("0.30")
    results.append(ExpectationResult(
        name="rss.tags.unknown_rate",
        severity="warn" if unknown_rate > unknown_threshold else "pass",
        observed=unknown_rate,
        threshold=unknown_threshold,
        observed_rows=n_tag_unknown,
        detail={"total_tags": n_tag_total, "unknown_tags": n_tag_unknown},
    ))

    return tuple(results)
