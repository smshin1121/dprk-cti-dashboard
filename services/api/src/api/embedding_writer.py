"""Embed-on-ingest orchestrator for api promote path — PR #19a Group B.

Service-local mirror of
``services/worker/src/worker/bootstrap/embedding_writer.py``. The
duplication is intentional per plan §9.1 (service-local writers,
not shared) — session factory, logging conventions, and config
resolution differ between worker and api.

Composes three steps in order:

1. **Compose embed text** per OI1 (plan §2.1 lock):
   ``title + "\n\n" + summary`` when ``summary`` is non-null and
   ``summary.strip() != ""``; else ``title`` alone. Whitespace-only
   input would trigger llm-proxy 422 (PR #18 D7 input validator) —
   we guard caller-side so that path stays impossible.

2. **Call llm-proxy** via the injected
   :class:`~api.embedding_client.LlmProxyEmbeddingClient`. Transient
   errors (429 / 5xx / timeout) are caught here, logged WARN, and
   turned into a ``SKIPPED_TRANSIENT`` return. Permanent errors
   (422 / dimension mismatch / malformed 2xx) propagate for the
   caller to log at ERROR and swallow — enrichment never blocks the
   promote gate (plan C4).

3. **PostgreSQL-only UPDATE** of ``reports.embedding`` guarded by
   ``WHERE id = :id AND embedding IS NULL`` so a concurrent writer
   (e.g. the backfill CLI) cannot be overwritten, and so a re-run
   on the same ``report_id`` returns ``ALREADY_POPULATED`` rather
   than duplicating work. On sqlite, this step is skipped
   (``SKIPPED_SQLITE``) — the sqlite test schema intentionally omits
   the ``embedding`` column.

``promote_staging_row`` stays pgvector-free; this module is the
only place in the api codebase that references the pgvector column.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.embedding_client import (
    EmbeddingResult,
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)


__all__ = [
    "EmbedWriteOutcome",
    "EmbedReportResult",
    "embed_report",
]


logger = logging.getLogger(__name__)


# Pinned SQL fragments for Group B criterion C2 text-match assertions.
# The caller-facing test captures the executed SQL and asserts these
# fragments are present verbatim. Keep them as module-level constants
# so the production path and the test share one source of truth.
_UPDATE_SQL = (
    "UPDATE reports SET embedding = CAST(:vec AS vector) "
    "WHERE id = :id AND embedding IS NULL"
)


class EmbedWriteOutcome(str, Enum):
    """Terminal status of a single ``embed_report`` call.

    - ``EMBEDDED``: client returned vectors and the PG UPDATE affected
      exactly one row.
    - ``ALREADY_POPULATED``: client returned vectors but the null-guard
      matched zero rows (another writer populated the vector first).
      Not an error — existing vector is preserved.
    - ``SKIPPED_TRANSIENT``: client raised ``TransientEmbeddingError``.
      Row stays with ``embedding IS NULL`` and becomes a backfill
      candidate.
    - ``SKIPPED_SQLITE``: session dialect is not PostgreSQL, so the
      UPDATE would fail. The client is not invoked on this path —
      saves an HTTP round-trip during unit tests.
    """

    EMBEDDED = "embedded"
    ALREADY_POPULATED = "already_populated"
    SKIPPED_TRANSIENT = "skipped_transient"
    SKIPPED_SQLITE = "skipped_sqlite"


@dataclass(frozen=True, slots=True)
class EmbedReportResult:
    """Structured outcome of ``embed_report``.

    Carrying the client's response metadata alongside the DB outcome
    keeps metrics / observability wiring (Group D) trivially
    composable — callers get one object rather than a tuple.
    """

    outcome: EmbedWriteOutcome
    rowcount: int
    cache_hit: bool | None
    upstream_latency_ms: int | None


def compose_embed_text(title: str, summary: str | None) -> str:
    """OI1 text composition — pure function, unit-testable in isolation.

    Whitespace-only summary collapses to title-only to avoid a
    guaranteed llm-proxy 422.
    """
    if summary is None:
        return title
    if summary.strip() == "":
        return title
    return f"{title}\n\n{summary}"


def _serialize_vector(vector: list[float]) -> str:
    """Render a float list as the pgvector text literal ``[x,y,z]``.

    We cast the string to ``vector`` inside the SQL (``CAST(:vec AS vector)``)
    so this module avoids taking a runtime dependency on the
    ``pgvector`` Python package. Ten decimal places is enough to
    represent float32 without loss for the range OpenAI emits.
    """
    return "[" + ",".join(f"{x:.10f}" for x in vector) + "]"


async def embed_report(
    session: AsyncSession,
    *,
    report_id: int,
    title: str,
    summary: str | None,
    client: LlmProxyEmbeddingClient,
) -> EmbedReportResult:
    """Embed one report and write the vector to ``reports.embedding``.

    Contract:
      - On sqlite: returns ``SKIPPED_SQLITE`` without calling ``client``.
      - On PostgreSQL happy path: returns ``EMBEDDED`` with ``rowcount=1``.
      - On PostgreSQL with row already populated (null-guard mismatch):
        returns ``ALREADY_POPULATED`` with ``rowcount=0``.
      - On transient client failure: returns ``SKIPPED_TRANSIENT``.
      - On permanent client failure: propagates
        :class:`PermanentEmbeddingError` to the caller for ERROR-level
        logging + metric increment + swallow.

    This function performs zero commit/rollback — the caller owns the
    transaction, matching the existing ``upsert_*`` contract.
    """
    bind = session.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name != "postgresql":
        # sqlite-memory tests use this path. No HTTP, no DB write.
        logger.debug(
            "embedding.skipped_sqlite",
            extra={
                "event": "embedding.skipped_sqlite",
                "report_id": report_id,
                "dialect": dialect_name,
            },
        )
        return EmbedReportResult(
            outcome=EmbedWriteOutcome.SKIPPED_SQLITE,
            rowcount=0,
            cache_hit=None,
            upstream_latency_ms=None,
        )

    text = compose_embed_text(title, summary)

    try:
        result: EmbeddingResult = await client.embed([text])
    except TransientEmbeddingError as exc:
        logger.warning(
            "embedding.transient",
            extra={
                "event": "embedding.transient",
                "report_id": report_id,
                "upstream_status": exc.upstream_status,
                "retry_after_seconds": exc.retry_after_seconds,
                "reason": exc.reason,
            },
        )
        return EmbedReportResult(
            outcome=EmbedWriteOutcome.SKIPPED_TRANSIENT,
            rowcount=0,
            cache_hit=None,
            upstream_latency_ms=None,
        )
    # PermanentEmbeddingError propagates — caller handles (C4 lock).

    vec_literal = _serialize_vector(result.vectors[0])
    exec_result = await session.execute(
        sa.text(_UPDATE_SQL),
        {"vec": vec_literal, "id": report_id},
    )
    rowcount = exec_result.rowcount

    if rowcount == 1:
        outcome = EmbedWriteOutcome.EMBEDDED
    else:
        # rowcount == 0 — null-guard matched nothing. Either the row
        # was populated by a concurrent writer (backfill CLI racing
        # with ingest) or — pathological — the row id does not exist.
        # Both cases are safe: no overwrite happens. We log at INFO
        # because this is an expected outcome of the null-guard, not
        # a failure.
        outcome = EmbedWriteOutcome.ALREADY_POPULATED
        logger.info(
            "embedding.already_populated",
            extra={
                "event": "embedding.already_populated",
                "report_id": report_id,
                "rowcount": rowcount,
            },
        )

    return EmbedReportResult(
        outcome=outcome,
        rowcount=rowcount,
        cache_hit=result.cache_hit,
        upstream_latency_ms=result.upstream_latency_ms,
    )
