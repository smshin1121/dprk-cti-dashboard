"""One-shot backfill of ``reports.embedding`` — PR #19a Group C.

Populates ``reports.embedding`` for rows where it is currently NULL.
Used once after PR #19a merges to bring existing reports up to date
with PR #18's embedding endpoint, and then optionally again after
any extended llm-proxy outage.

Contract locks (plan §0 + §2.1 + §9.2):

  - **Selection is strictly ``embedding IS NULL``.** Rows already
    populated are never re-embedded — no overwrite, no silent cost.
    Ordered ``published ASC, id ASC`` (D10) so progress is
    deterministic and restart-safe.

  - **Bounded batch size** — caller may request up to ``16`` texts
    per llm-proxy request. Values above that are rejected at
    argument validation time (ValueError). Matches PR #18
    ``EmbeddingRequest.texts`` ``max=16``.

  - **Idempotent rerun.** A second run over the same DB state is a
    no-op: all candidates are already populated, selection returns
    zero rows. Partial-progress is preserved because each successful
    batch commits on its own.

  - **Partial transient resume.** Within a single run, a batch that
    hits llm-proxy ``429 / 5xx / timeout`` does not abort the
    backfill — it logs WARN, honors ``Retry-After`` (capped), and
    moves on to the next batch. The failed batch's rows remain
    ``embedding IS NULL`` and are picked up by a subsequent rerun.

  - **Pacing:**
    - Default ``sleep_seconds = 2.0`` between batches — roughly
      ``30 req/min`` ceiling matching PR #18's locked bucket.
    - On 429 with ``Retry-After: N``, sleep for ``min(N, 60)``
      seconds before continuing. Caps prevent a pathological upstream
      header from pausing the backfill for an hour.

  - **Permanent errors** (llm-proxy ``422`` / dimension mismatch /
    malformed 2xx): logged ERROR per batch with metric, batch is
    skipped, backfill continues. The ``422`` case indicates caller-
    bug / protocol drift; the rows will re-surface on subsequent
    runs (and keep 422-ing until the upstream cause is fixed — the
    ERROR log is the loud signal, not a run-abort).

Unlike ``upsert_report``, this function **owns its transaction
boundaries**. Each successful batch is committed before the next
batch starts so an interrupt (Ctrl-C, process kill) only loses the
in-flight batch, not the preceding ones.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.embedding_client import (
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from worker.bootstrap.embedding_writer import (
    _UPDATE_SQL,
    _serialize_vector,
    compose_embed_text,
)


__all__ = [
    "BackfillCounts",
    "MAX_BATCH_SIZE",
    "DEFAULT_SLEEP_SECONDS",
    "MAX_RETRY_AFTER_SECONDS",
    "run_embedding_backfill",
]


logger = logging.getLogger(__name__)


MAX_BATCH_SIZE = 16
DEFAULT_SLEEP_SECONDS = 2.0
# Cap on Retry-After honor: prevents an upstream sending
# ``Retry-After: 3600`` from pausing the whole backfill for an hour.
MAX_RETRY_AFTER_SECONDS = 60

# Candidate selection SQL pinned for review criterion #1.
_CANDIDATE_SELECT_SQL = (
    "SELECT id, title, summary FROM reports "
    "WHERE embedding IS NULL "
    "ORDER BY published ASC, id ASC"
)


@dataclass(frozen=True, slots=True)
class BackfillCounts:
    """Summary of one backfill run — printed by the CLI, inspected by
    tests. All counts are row-level, not batch-level."""

    scanned: int
    embedded: int
    already_populated: int
    skipped_transient: int
    skipped_permanent: int
    dry_run_skipped: int

    def total_attempted(self) -> int:
        """Rows that were actually selected and (in non-dry-run mode)
        passed to llm-proxy at least once. Excludes dry-run rows."""
        return (
            self.embedded
            + self.already_populated
            + self.skipped_transient
            + self.skipped_permanent
        )


async def run_embedding_backfill(
    session: AsyncSession,
    *,
    client: LlmProxyEmbeddingClient,
    batch_size: int = MAX_BATCH_SIZE,
    limit: int | None = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    dry_run: bool = False,
    sleep_func=asyncio.sleep,
) -> BackfillCounts:
    """Populate ``reports.embedding`` for NULL rows in bounded batches.

    Args:
        session: async SQLAlchemy session. Function owns transaction
            boundaries and commits per-batch.
        client: configured llm-proxy embedding client.
        batch_size: texts per llm-proxy request. Must be 1..16.
        limit: optional total-row cap across all batches.
        sleep_seconds: delay between batches. Default 2s ≈ 30 req/min
            ceiling matching PR #18's bucket.
        dry_run: when True, selects candidates and returns scanned
            count without calling llm-proxy or issuing UPDATEs.
        sleep_func: injectable async sleep (``asyncio.sleep`` by
            default). Tests supply a recorder so they do not stall on
            real time.

    Raises:
        ValueError: if ``batch_size`` or ``limit`` is out of range.
    """
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size must be 1..{MAX_BATCH_SIZE}, got {batch_size}"
        )
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be positive or None, got {limit}")
    if sleep_seconds < 0:
        raise ValueError(
            f"sleep_seconds must be non-negative, got {sleep_seconds}"
        )

    candidates = await _select_candidates(session, limit=limit)
    scanned = len(candidates)

    if dry_run:
        logger.info(
            "embedding.backfill.dry_run",
            extra={
                "event": "embedding.backfill.dry_run",
                "scanned": scanned,
            },
        )
        return BackfillCounts(
            scanned=scanned,
            embedded=0,
            already_populated=0,
            skipped_transient=0,
            skipped_permanent=0,
            dry_run_skipped=scanned,
        )

    embedded = 0
    already_populated = 0
    skipped_transient = 0
    skipped_permanent = 0

    # Chunk the candidate list in-memory. For the expected DPRK-CTI
    # corpus (<100k reports) this is fine; if the corpus grows we can
    # swap to keyset pagination without changing the caller contract.
    batches = [
        candidates[i : i + batch_size]
        for i in range(0, scanned, batch_size)
    ]

    for batch_index, batch in enumerate(batches):
        is_last_batch = batch_index == len(batches) - 1

        texts = [compose_embed_text(r.title, r.summary) for r in batch]
        ids = [r.id for r in batch]

        try:
            result = await client.embed(texts)
        except TransientEmbeddingError as exc:
            skipped_transient += len(batch)
            logger.warning(
                "embedding.backfill.transient",
                extra={
                    "event": "embedding.backfill.transient",
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "upstream_status": exc.upstream_status,
                    "retry_after_seconds": exc.retry_after_seconds,
                    "reason": exc.reason,
                },
            )
            # OI4 refinement: honor Retry-After when provided, else
            # use the configured sleep_seconds. Capped regardless to
            # avoid a pathological upstream value.
            transient_sleep = min(
                exc.retry_after_seconds or sleep_seconds,
                MAX_RETRY_AFTER_SECONDS,
            )
            if transient_sleep > 0 and not is_last_batch:
                await sleep_func(transient_sleep)
            continue
        except PermanentEmbeddingError as exc:
            skipped_permanent += len(batch)
            logger.error(
                "embedding.backfill.permanent",
                extra={
                    "event": "embedding.backfill.permanent",
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "upstream_status": exc.upstream_status,
                    "reason": exc.reason,
                },
            )
            if sleep_seconds > 0 and not is_last_batch:
                await sleep_func(sleep_seconds)
            continue

        for report_id, vector in zip(ids, result.vectors, strict=True):
            vec_literal = _serialize_vector(vector)
            exec_result = await session.execute(
                sa.text(_UPDATE_SQL),
                {"vec": vec_literal, "id": report_id},
            )
            if exec_result.rowcount == 1:
                embedded += 1
            else:
                # rowcount == 0 — null-guard matched nothing. Another
                # writer (ingest embed) may have populated the row
                # between our SELECT and our UPDATE. Not an error.
                already_populated += 1

        await session.commit()

        logger.info(
            "embedding.backfill.batch_committed",
            extra={
                "event": "embedding.backfill.batch_committed",
                "batch_index": batch_index,
                "batch_size": len(batch),
                "cache_hit": result.cache_hit,
            },
        )

        if sleep_seconds > 0 and not is_last_batch:
            await sleep_func(sleep_seconds)

    counts = BackfillCounts(
        scanned=scanned,
        embedded=embedded,
        already_populated=already_populated,
        skipped_transient=skipped_transient,
        skipped_permanent=skipped_permanent,
        dry_run_skipped=0,
    )
    logger.info(
        "embedding.backfill.completed",
        extra={
            "event": "embedding.backfill.completed",
            "scanned": counts.scanned,
            "embedded": counts.embedded,
            "already_populated": counts.already_populated,
            "skipped_transient": counts.skipped_transient,
            "skipped_permanent": counts.skipped_permanent,
        },
    )
    return counts


async def _select_candidates(
    session: AsyncSession,
    *,
    limit: int | None,
) -> list:
    """Fetch candidate rows (``embedding IS NULL``) in
    ``(published, id)`` keyset order.

    Uses raw SQL text because the ``embedding`` column is pgvector-
    only and is intentionally omitted from the SQLAlchemy metadata
    in ``tables.py`` (sqlite unit tests cannot model the type).
    """
    sql = _CANDIDATE_SELECT_SQL
    params: dict[str, object] = {}
    if limit is not None:
        sql = f"{sql} LIMIT :total_limit"
        params["total_limit"] = limit
    result = await session.execute(sa.text(sql), params)
    return list(result.all())
