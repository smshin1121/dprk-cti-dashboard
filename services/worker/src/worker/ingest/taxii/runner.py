"""TAXII ingest orchestrator — per-collection failure isolation.

Runs through the collection catalog, fetches + parses + normalizes +
writes each collection independently. A failure in one collection does
not abort the run or prevent other collections from being processed.

After all collections are processed, computes the 4 D5 TAXII DQ
metrics and emits them through the standard DQ sink fan-out.

**State advance invariant** (critical):
  ``last_added_after`` is advanced ONLY when ALL of the following hold:
    1. ``fetch_outcome.is_complete`` — no HTTP error AND no max_pages
    2. Normalize succeeded (no uncaught exceptions)
    3. Staging writer succeeded (no uncaught exceptions)
  If any condition fails, state records the error but does NOT advance
  the timestamp. The next run re-fetches from the same point, and
  ``ON CONFLICT DO NOTHING`` deduplicates silently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import AliasDictionary
from worker.bootstrap.normalize import (
    DEFAULT_SECTOR_CODES,
    TAG_TYPE_UNKNOWN,
    _classify_single,
)
from worker.data_quality.expectations.taxii_metrics import (
    check_taxii_empty_description_rate,
    check_taxii_fetch_failure_rate,
    check_taxii_label_unmapped_rate,
    check_taxii_stix_parse_error_rate,
)
from worker.data_quality.results import ExpectationResult, Sink
from worker.ingest.normalize import StagingRowDraft
from worker.ingest.staging_writer import WriteOutcome, write_staging_rows
from worker.ingest.taxii.audit import (
    STAGING_INSERT,
    TAXII_RUN_COMPLETED,
    TAXII_RUN_FAILED,
    TAXII_RUN_STARTED,
    TaxiiRunMeta,
    write_staging_insert_audit,
    write_taxii_run_audit,
)
from worker.ingest.taxii.config import TaxiiCatalog, TaxiiCollectionConfig
from worker.ingest.taxii.fetcher import CollectionFetchOutcome, TaxiiFetcher
from worker.ingest.taxii.normalize import normalize_stix_object
from worker.ingest.taxii.state import load_state, upsert_state
from worker.ingest.taxii.stix_parser import parse_stix_objects


__all__ = [
    "CollectionResult",
    "TaxiiRunOutcome",
    "run_taxii_ingest",
]


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Outcome for a single collection within a run."""

    slug: str
    fetched: bool
    fetch_complete: bool
    objects_in_envelope: int
    objects_after_filter: int
    malformed_objects: int
    inserted: int
    skipped_duplicate: int
    state_advanced: bool
    fetch_error: str | None
    total_labels: int
    unmapped_labels: int
    empty_descriptions: int


@dataclass(frozen=True, slots=True)
class TaxiiRunOutcome:
    """Aggregate outcome for the entire TAXII ingest run."""

    run_id: uuid.UUID
    collection_results: tuple[CollectionResult, ...]
    total_inserted: int
    total_skipped_duplicate: int
    total_fetch_failures: int
    total_malformed: int
    all_collections_failed: bool
    inserted_ids: tuple[int, ...]
    dq_results: tuple[ExpectationResult, ...] = ()


def _check_label_mapped(label: str, aliases: AliasDictionary) -> bool:
    """Return True if ``label`` maps to a known tag type.

    P3 Codex R5: uses ``_classify_single`` directly instead of
    ``classify_tags`` with a synthetic ``#`` prefix. This handles
    multi-word labels (e.g. "north korea") correctly — ``classify_tags``
    would split on whitespace and only check the first token.
    """
    classified = _classify_single(label, aliases, DEFAULT_SECTOR_CODES)
    return classified.type_ != TAG_TYPE_UNKNOWN


async def run_taxii_ingest(
    session: AsyncSession,
    *,
    catalog: TaxiiCatalog,
    fetcher: TaxiiFetcher,
    aliases: AliasDictionary | None = None,
    run_id: uuid.UUID,
    audit_meta: TaxiiRunMeta | None = None,
    sinks: list[Sink] | None = None,
) -> TaxiiRunOutcome:
    """Run the full TAXII ingest pipeline with per-collection isolation."""
    enabled = catalog.enabled

    # Audit: taxii_run_started
    if audit_meta is not None:
        try:
            async with session.begin_nested():
                await write_taxii_run_audit(
                    session, action=TAXII_RUN_STARTED, meta=audit_meta,
                )
        except Exception:
            pass

    collection_results: list[CollectionResult] = []
    all_inserted_ids: list[int] = []

    # Aggregate DQ counters
    total_labels = 0
    total_unmapped_labels = 0
    total_empty_descriptions = 0
    total_objects_in_envelope = 0
    total_malformed = 0
    total_objects_ingested = 0

    for col_cfg in enabled:
        cr, inserted_ids = await _process_collection(
            session, col_cfg, fetcher, aliases, audit_meta,
        )
        collection_results.append(cr)
        all_inserted_ids.extend(inserted_ids)
        total_labels += cr.total_labels
        total_unmapped_labels += cr.unmapped_labels
        total_empty_descriptions += cr.empty_descriptions
        total_objects_in_envelope += cr.objects_in_envelope
        total_malformed += cr.malformed_objects
        total_objects_ingested += cr.inserted + cr.skipped_duplicate

    total_inserted = sum(cr.inserted for cr in collection_results)
    total_skipped = sum(cr.skipped_duplicate for cr in collection_results)
    total_fetch_failures = sum(
        1 for cr in collection_results if cr.fetch_error is not None
    )
    n_enabled = len(enabled)
    # P1 Codex R3: a run is "all failed" when no collection advanced state,
    # not just when all fetches failed. A run where every fetch succeeds but
    # every write/normalize fails is equally useless to operators.
    any_advanced = any(cr.state_advanced for cr in collection_results)
    all_failed = n_enabled > 0 and not any_advanced

    # D5 TAXII DQ metrics
    dq_results = (
        check_taxii_fetch_failure_rate(n_enabled, total_fetch_failures),
        check_taxii_stix_parse_error_rate(
            total_objects_in_envelope, total_malformed,
        ),
        check_taxii_empty_description_rate(
            total_objects_ingested, total_empty_descriptions,
        ),
        check_taxii_label_unmapped_rate(
            total_labels, total_unmapped_labels,
        ),
    )

    # Emit through sinks
    if sinks and dq_results:
        for sink in sinks:
            try:
                await sink.write(list(dq_results))
            except Exception:
                pass

    # Audit: taxii_run_completed or taxii_run_failed
    if audit_meta is not None:
        detail: dict[str, Any] = {
            "total_inserted": total_inserted,
            "total_skipped_duplicate": total_skipped,
            "total_fetch_failures": total_fetch_failures,
            "total_malformed": total_malformed,
        }
        action = TAXII_RUN_FAILED if all_failed else TAXII_RUN_COMPLETED
        if all_failed:
            detail["all_collections_failed"] = True
        try:
            async with session.begin_nested():
                await write_taxii_run_audit(
                    session, action=action, meta=audit_meta, detail=detail,
                )
        except Exception:
            pass

    return TaxiiRunOutcome(
        run_id=run_id,
        collection_results=tuple(collection_results),
        total_inserted=total_inserted,
        total_skipped_duplicate=total_skipped,
        total_fetch_failures=total_fetch_failures,
        total_malformed=total_malformed,
        all_collections_failed=all_failed,
        inserted_ids=tuple(all_inserted_ids),
        dq_results=dq_results,
    )


async def _process_collection(
    session: AsyncSession,
    col: TaxiiCollectionConfig,
    fetcher: TaxiiFetcher,
    aliases: AliasDictionary | None,
    audit_meta: TaxiiRunMeta | None,
) -> tuple[CollectionResult, list[int]]:
    """Process one collection end-to-end with state advance guard.

    Returns (CollectionResult, inserted_ids).
    Per-collection failure isolation: exceptions are caught and recorded.
    """
    state = await load_state(session, col.slug)
    inserted_ids: list[int] = []
    col_labels = 0
    col_unmapped = 0
    col_empty_desc = 0

    # --- 1. Fetch ---
    try:
        fetch_outcome = await fetcher.fetch_collection(col, state=state)
    except Exception as exc:
        await _update_state_failure(session, col, str(exc))
        return (
            CollectionResult(
                slug=col.slug, fetched=False, fetch_complete=False,
                objects_in_envelope=0, objects_after_filter=0,
                malformed_objects=0, inserted=0, skipped_duplicate=0,
                state_advanced=False, fetch_error=str(exc),
                total_labels=0, unmapped_labels=0, empty_descriptions=0,
            ),
            [],
        )

    if not fetch_outcome.is_success and not fetch_outcome.objects:
        # Total fetch failure with no usable objects — bail early.
        await _update_state_failure(
            session, col, fetch_outcome.error or "fetch failed",
        )
        return (
            CollectionResult(
                slug=col.slug, fetched=False, fetch_complete=False,
                objects_in_envelope=0, objects_after_filter=0,
                malformed_objects=0, inserted=0, skipped_duplicate=0,
                state_advanced=False, fetch_error=fetch_outcome.error,
                total_labels=0, unmapped_labels=0, empty_descriptions=0,
            ),
            [],
        )

    # P2 Codex R1: even on mid-pagination error, process the objects we
    # did get. They are valid STIX data. State will NOT advance because
    # fetch_outcome.is_complete is False.

    # --- 2. Parse (type filter) ---
    parsed = parse_stix_objects(
        fetch_outcome.objects, type_whitelist=col.stix_types,
    )

    # --- 3. Normalize ---
    drafts: list[StagingRowDraft] = []
    normalize_failed = False
    for pobj in parsed.objects:
        # Count labels (denominator = objects that HAVE labels array)
        raw = pobj.raw
        labels = raw.get("labels")
        if isinstance(labels, list) and labels:
            for label in labels:
                if isinstance(label, str) and label.strip():
                    col_labels += 1
                    if aliases and not _check_label_mapped(label, aliases):
                        col_unmapped += 1

        try:
            draft = normalize_stix_object(pobj)
        except Exception:
            normalize_failed = True
            draft = None

        if draft is not None:
            # Count empty descriptions
            if draft.raw_text is None:
                col_empty_desc += 1
            drafts.append(draft)

    # --- 4. Write to staging ---
    # P1 Codex R3: wrap in savepoint so a write error doesn't poison the
    # session for subsequent collections (per-collection isolation).
    write_outcome = WriteOutcome(inserted_ids=(), skipped_duplicate_count=0)
    write_failed = False
    if drafts:
        try:
            async with session.begin_nested():
                write_outcome = await write_staging_rows(session, drafts)
                inserted_ids = list(write_outcome.inserted_ids)
        except Exception:
            write_failed = True

        # Audit: staging_insert per inserted row
        if (
            audit_meta is not None
            and write_outcome.inserted_ids
            and not write_failed
        ):
            from worker.bootstrap.tables import staging_table
            id_to_url: dict[int, str] = {}
            if write_outcome.inserted_ids:
                result = await session.execute(
                    sa.select(
                        staging_table.c.id, staging_table.c.url_canonical,
                    ).where(
                        staging_table.c.id.in_(
                            list(write_outcome.inserted_ids)
                        )
                    )
                )
                id_to_url = {
                    row.id: row.url_canonical for row in result.all()
                }

            for sid in write_outcome.inserted_ids:
                url_c = id_to_url.get(sid, "")
                try:
                    async with session.begin_nested():
                        await write_staging_insert_audit(
                            session, meta=audit_meta,
                            staging_id=sid, url_canonical=url_c,
                        )
                except Exception:
                    pass

    # --- 5. State advance (CRITICAL: conservative condition) ---
    #
    # Advance last_added_after ONLY when:
    #   - fetch_outcome.is_complete (no error AND no max_pages truncation)
    #   - normalize did not fail
    #   - write did not fail
    #
    # If ANY condition fails, record error but do NOT advance.
    should_advance = (
        fetch_outcome.is_complete
        and not normalize_failed
        and not write_failed
    )

    if should_advance:
        await upsert_state(
            session,
            collection_key=col.slug,
            server_url=col.server_url,
            collection_id=col.collection_id,
            last_added_after=fetch_outcome.fetch_timestamp,
            # P3 Codex R5: record fetched object count (not inserted) so
            # incremental runs with overlap dedup don't show misleading 0.
            last_object_count=len(fetch_outcome.objects),
            reset_failures=True,
        )
    else:
        # Partial success or failure — don't advance, record error
        error_detail = fetch_outcome.error or ""
        if normalize_failed:
            error_detail += " [normalize failed]"
        if write_failed:
            error_detail += " [write failed]"
        if fetch_outcome.max_pages_reached:
            error_detail += " [max_pages reached — incomplete]"
        await upsert_state(
            session,
            collection_key=col.slug,
            server_url=col.server_url,
            collection_id=col.collection_id,
            last_error=error_detail.strip() or None,
            reset_failures=False,
        )

    return (
        CollectionResult(
            slug=col.slug,
            fetched=True,
            fetch_complete=fetch_outcome.is_complete,
            objects_in_envelope=len(fetch_outcome.objects),
            objects_after_filter=len(parsed.objects),
            malformed_objects=parsed.malformed_count,
            inserted=len(write_outcome.inserted_ids),
            skipped_duplicate=write_outcome.skipped_duplicate_count,
            state_advanced=should_advance,
            fetch_error=fetch_outcome.error,
            total_labels=col_labels,
            unmapped_labels=col_unmapped,
            empty_descriptions=col_empty_desc,
        ),
        inserted_ids,
    )


async def _update_state_failure(
    session: AsyncSession,
    col: TaxiiCollectionConfig,
    error: str,
) -> None:
    """Record a fetch failure in state without advancing."""
    try:
        await upsert_state(
            session,
            collection_key=col.slug,
            server_url=col.server_url,
            collection_id=col.collection_id,
            last_error=error,
            reset_failures=False,
        )
    except Exception:
        pass
