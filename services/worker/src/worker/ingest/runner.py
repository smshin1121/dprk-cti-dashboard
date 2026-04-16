"""RSS ingest orchestrator — per-feed failure isolation.

Runs through the feed catalog, fetches + parses + normalizes +
writes each feed independently. A failure in one feed does not
abort the run or prevent other feeds from being processed.

After all feeds are processed, computes the 4 D10 feed-level DQ
metrics and emits them through the standard DQ sink fan-out.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import AliasDictionary
from worker.data_quality.expectations.feed_metrics import (
    check_empty_title_rate,
    check_fetch_failure_rate,
    check_parse_error_rate,
    check_unknown_tag_rate,
)
from worker.data_quality.results import ExpectationResult, Sink
from worker.ingest.audit import (
    IngestRunMeta,
    RSS_RUN_COMPLETED,
    RSS_RUN_FAILED,
    RSS_RUN_STARTED,
    write_ingest_run_audit,
    write_staging_insert_audit,
)
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
    audit_meta: IngestRunMeta | None = None,
    sinks: list[Sink] | None = None,
) -> RunOutcome:
    """Run the full RSS ingest pipeline with per-feed isolation."""
    enabled = catalog.enabled

    # Audit: rss_run_started (savepoint-wrapped)
    if audit_meta is not None:
        try:
            async with session.begin_nested():
                await write_ingest_run_audit(
                    session, action=RSS_RUN_STARTED, meta=audit_meta,
                )
        except Exception:
            pass

    feed_results_final: list[FeedResult] = []
    all_inserted_ids_final: list[int] = []
    tag_total = 0
    tag_unknown = 0
    empty_title_count = 0
    total_entries = 0

    for feed_cfg in enabled:
        fr, inserted_ids, entries_count, empty_titles, tag_t, tag_u = (
            await _process_feed_full(
                session, feed_cfg, fetcher, aliases, audit_meta,
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
    total_not_modified = sum(1 for fr in feed_results_final if fr.not_modified)

    n_enabled = len(enabled)
    n_actually_parsed = n_enabled - total_fetch_failures - total_not_modified
    all_failed = n_enabled > 0 and total_fetch_failures == n_enabled

    # D10 feed-level DQ metrics via feed_metrics module
    dq_results = (
        check_fetch_failure_rate(n_enabled, total_fetch_failures),
        check_parse_error_rate(n_actually_parsed, total_parse_errors),
        check_empty_title_rate(total_entries, empty_title_count),
        check_unknown_tag_rate(tag_total, tag_unknown),
    )

    # Emit through sinks
    if sinks and dq_results:
        for sink in sinks:
            try:
                await sink.write(list(dq_results))
            except Exception:
                pass

    # Audit: rss_run_completed or rss_run_failed
    if audit_meta is not None:
        detail = {
            "total_inserted": total_inserted,
            "total_skipped_duplicate": total_skipped,
            "total_fetch_failures": total_fetch_failures,
            "total_parse_errors": total_parse_errors,
        }
        action = RSS_RUN_FAILED if all_failed else RSS_RUN_COMPLETED
        if all_failed:
            detail["all_feeds_failed"] = True
        try:
            async with session.begin_nested():
                await write_ingest_run_audit(
                    session, action=action, meta=audit_meta, detail=detail,
                )
        except Exception:
            pass

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
    audit_meta: IngestRunMeta | None = None,
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
        try:
            draft = normalize_entry(entry)
        except Exception:
            draft = None
        if draft is not None:
            drafts.append(draft)

    # Write to staging
    write_outcome = WriteOutcome(inserted_ids=(), skipped_duplicate_count=0)
    if drafts:
        write_outcome = await write_staging_rows(session, drafts)
        inserted_ids = list(write_outcome.inserted_ids)

        # Audit: staging_insert per inserted row (savepoint-wrapped)
        if audit_meta is not None and write_outcome.inserted_ids:
            from worker.bootstrap.tables import staging_table
            id_to_url = {}
            if write_outcome.inserted_ids:
                result = await session.execute(
                    sa.select(
                        staging_table.c.id, staging_table.c.url_canonical
                    ).where(
                        staging_table.c.id.in_(list(write_outcome.inserted_ids))
                    )
                )
                id_to_url = {row.id: row.url_canonical for row in result.all()}

            for sid in write_outcome.inserted_ids:
                url_c = id_to_url.get(sid, "")
                try:
                    async with session.begin_nested():
                        await write_staging_insert_audit(
                            session,
                            meta=audit_meta,
                            staging_id=sid,
                            url_canonical=url_c,
                        )
                except Exception:
                    pass

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


