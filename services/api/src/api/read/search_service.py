"""Search service for ``GET /api/v1/search`` — FTS (PR #17) + hybrid (PR #19b).

Two dispatch paths now coexist:

- **Hybrid** (PR #19b): PG dialect + embedding client available + coverage
  ≥ threshold. Runs FTS and query-time llm-proxy embedding in parallel via
  ``asyncio.gather`` (OI3 = B), then pgvector kNN, then RRF fusion (plan
  D3). Each ``SearchHit`` carries both its ``fts_rank`` float and a
  1-indexed ``vector_rank`` int (PR #17 D9 forward-compat slot filled).

- **FTS-only** (PR #17 behavior): triggered when the dispatch preconditions
  fail — non-PG dialect, embedding client disabled, or coverage < threshold.
  Every hit has ``vector_rank: null`` (PR #17 semantic). Both coverage-low
  and transient-embedding cases also set ``degraded=true`` + a
  ``degraded_reason`` field in the log line (plan D5 / D8 / OI5 = A).

Design contract (hard-locked by `docs/plans/pr19b-search-hybrid-upgrade.md`
plus PR #17 baseline):

- **D2 / D3 / D4 RRF fusion** — `rrf_fuse` in ``search_fusion``. Pure,
  tested separately. k=60 default.

- **D5 / OI4 = B degraded trigger** — two-source OR: (a) transient
  embedding failure, (b) coverage cache below ``settings.hybrid_search_
  coverage_threshold``. Composition is a simple OR — both paths emit
  the same D10 envelope shape with ``vector_rank: null`` throughout and
  ``degraded=true`` in the log.

- **D7 / OI3 = B latency budget** — FTS + embedding run in parallel so
  effective p95 ≈ max(leg) rather than sum(leg). ``asyncio.gather``
  with ``return_exceptions=True`` so one leg's failure does not cancel
  the other — we always want the FTS result available as the degraded
  fallback.

- **D8 / OI5 = A log fields** — extended from PR #17 D16 with
  ``{embedding_ms, vector_ms, fusion_ms, degraded, degraded_reason,
  llm_proxy_cache_hit}``. Existing D16 aggregators keep parsing (purely
  additive). NO envelope field for ``degraded`` (OI5 = A — log-only).

- **D9 error taxonomy** — transient embedding errors swallowed inside
  this module (→ degraded FTS-only). Permanent embedding errors
  (llm-proxy 422 / dimensions drift / malformed 2xx) propagate to the
  router, which converts them to HTTP 500.

- **D10 null-embedding exclusion** — vector query hard-filters
  ``reports.embedding IS NOT NULL``. Null rows stay FTS-eligible
  (never "zero-vector distorts fusion").

- **D11 cache** — Redis-backed, 60s TTL. Cache key unchanged from
  PR #17 (no new axes). Hybrid responses reuse the cache; a degraded
  response caches its FTS-only envelope. Stale cache may outlive the
  trigger that produced it — this is acceptable per the 60s TTL bound.

Portability / non-PG dialects:

- Coverage query + vector kNN query are PG-only. On sqlite the
  dispatcher falls back to FTS-only unconditionally (FTS path's
  dialect gate returns an empty envelope — plan D10 is the full
  behavior on sqlite).

Coverage cache (plan D5 / OI4 = B, `HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS`):

- Process-local. First call (or stale read) refreshes via a single
  ``SELECT COUNT(*) FILTER (WHERE embedding IS NOT NULL) / COUNT(*)``
  round-trip. Concurrent stale reads may refresh redundantly — harmless
  (result is deterministic) and cheaper than an asyncio.Lock for the
  rate this runs at.
- Tests call ``reset_coverage_cache()`` between cases so one test's
  fetch doesn't poison the next.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import sqlalchemy as sa
from redis import asyncio as redis_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..embedding_client import (
    EmbeddingResult,
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from ..tables import reports_table, sources_table
from . import search_cache, search_fusion


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchServiceResult:
    """Service return envelope.

    ``payload`` matches ``SearchResponse`` before Pydantic validation
    — the router wraps the dict into ``SearchResponse(**result.
    payload)``. Observability fields (``cache_hit`` / ``fts_ms`` /
    ``degraded`` / ``embedding_ms`` / ``vector_ms`` / ``fusion_ms`` /
    ``llm_proxy_cache_hit``) live on this dataclass for unit-test
    assertions and are NOT serialized into the HTTP response
    (D8 / OI5 = A keeps them in logs / test-only surface).
    """

    payload: dict[str, Any]
    cache_hit: bool
    fts_ms: int
    degraded: bool = False
    degraded_reason: str | None = None
    embedding_ms: int = 0
    vector_ms: int = 0
    fusion_ms: int = 0
    llm_proxy_cache_hit: bool = False


# ---------------------------------------------------------------------------
# Coverage cache (plan D5(b) / OI4 = B)
# ---------------------------------------------------------------------------

# Process-local cache. Updated lazily from ``_get_coverage_ratio``.
# Tests call ``reset_coverage_cache()`` between cases.
_COVERAGE_CACHE: dict[str, float | None] = {
    "ratio": None,
    "fetched_at_monotonic": 0.0,
}


def reset_coverage_cache() -> None:
    """Clear the process-local coverage cache.

    Used by tests between cases so a prior test's ratio does not
    shadow the next test's expectation. Production code does not
    call this function.
    """
    _COVERAGE_CACHE["ratio"] = None
    _COVERAGE_CACHE["fetched_at_monotonic"] = 0.0


def _dialect_is_postgres(session: AsyncSession) -> bool:
    """Return ``True`` when the session's dialect is PostgreSQL.

    Isolated as a module-level function so unit tests can
    monkey-patch the hybrid dispatch into the PG branch on a live
    sqlite engine without constructing a real pgvector-enabled
    test database. Production call sites use the real
    ``session.get_bind().dialect.name`` check under the hood.
    """
    return session.get_bind().dialect.name == "postgresql"


async def _get_coverage_ratio(
    session: AsyncSession,
    *,
    refresh_seconds: int,
) -> float:
    """Return the ``reports.embedding IS NOT NULL`` ratio, cached.

    Refreshes on stale read via a single count query. Non-PG dialects
    return ``0.0`` — sqlite has no ``reports.embedding`` column and
    the dispatcher treats 0.0 coverage as "hybrid unreachable" (same
    effect as configured-off).
    """
    now = time.monotonic()
    cached_ratio = _COVERAGE_CACHE["ratio"]
    fetched_at = _COVERAGE_CACHE["fetched_at_monotonic"]
    assert isinstance(fetched_at, float)  # mypy — dict[str, float | None]
    if cached_ratio is not None and (now - fetched_at) < refresh_seconds:
        return cached_ratio

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        _COVERAGE_CACHE["ratio"] = 0.0
        _COVERAGE_CACHE["fetched_at_monotonic"] = now
        return 0.0

    # ``NULLIF`` guards the zero-report edge case (empty table →
    # ratio 0.0 rather than a ZeroDivisionError-style NULL).
    stmt = sa.text(
        "SELECT "
        "  COALESCE("
        "    COUNT(*) FILTER (WHERE embedding IS NOT NULL)::float "
        "    / NULLIF(COUNT(*), 0), "
        "    0.0"
        "  ) AS ratio "
        "FROM reports"
    )
    result = await session.execute(stmt)
    ratio = float(result.scalar_one())
    _COVERAGE_CACHE["ratio"] = ratio
    _COVERAGE_CACHE["fetched_at_monotonic"] = now
    return ratio


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


async def get_search_results(
    session: AsyncSession,
    redis: redis_asyncio.Redis | None,
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    embedding_client: LlmProxyEmbeddingClient | None = None,
) -> SearchServiceResult:
    """Return the search response for ``q`` (hybrid or FTS-only).

    The router validated ``q`` non-empty and ``limit`` bounds already;
    this function assumes valid input. A defensive ``ValueError`` in
    ``search_cache.cache_key`` catches bypass attempts.

    Dispatch rules (plan §3 dispatcher):

    1. Cache lookup — serve cached envelope on hit (observability
       fields reset to cache-hit-appropriate zeros).
    2. Non-PG dialect OR embedding client ``None`` → FTS-only, NOT
       flagged as ``degraded`` (those are infrastructure conditions,
       not runtime degradation).
    3. PG + embedding available → check coverage cache. Below
       threshold → FTS-only with ``degraded=True`` +
       ``degraded_reason="coverage"``.
    4. PG + embedding + coverage OK → hybrid path (``_run_hybrid``).
       Transient embedding failure inside that path degrades to
       FTS-only + ``degraded_reason="transient"``. Permanent error
       propagates to the router (→ HTTP 500).
    """
    settings = get_settings()
    coverage_threshold = settings.hybrid_search_coverage_threshold
    vector_k = settings.hybrid_search_vector_k
    coverage_refresh_seconds = settings.hybrid_search_coverage_refresh_seconds

    t_start = time.perf_counter()

    cached = await search_cache.get_cached(
        redis, q=q, date_from=date_from, date_to=date_to, limit=limit
    )
    if cached is not None:
        return _build_cache_hit_result(cached, q=q, t_start=t_start)

    dialect_is_pg = _dialect_is_postgres(session)
    hybrid_reachable = dialect_is_pg and embedding_client is not None

    coverage_low = False
    if hybrid_reachable:
        coverage = await _get_coverage_ratio(
            session, refresh_seconds=coverage_refresh_seconds
        )
        coverage_low = coverage < coverage_threshold

    if not hybrid_reachable or coverage_low:
        return await _run_fts_only_and_cache(
            session,
            redis,
            q=q,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            t_start=t_start,
            degraded=coverage_low,
            degraded_reason="coverage" if coverage_low else None,
            embedding_ms=0,
            vector_ms=0,
            fusion_ms=0,
            llm_proxy_cache_hit=False,
        )

    # Hybrid path — at this point embedding_client is not None.
    assert embedding_client is not None  # mypy narrowing
    return await _run_hybrid(
        session,
        redis,
        embedding_client,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        vector_k=vector_k,
        t_start=t_start,
    )


# ---------------------------------------------------------------------------
# Cache-hit response
# ---------------------------------------------------------------------------


def _build_cache_hit_result(
    cached: dict[str, Any],
    *,
    q: str,
    t_start: float,
) -> SearchServiceResult:
    """Serve a cached envelope with a fresh ``latency_ms`` and log.

    Cache-hits do not know whether the cached envelope was produced
    by a hybrid run, a degraded run, or a native FTS-only run — so
    ``degraded`` is reported as ``False`` on cache hit (not a lie:
    no degradation happened on THIS request). Operational telemetry
    for the original degraded event already fired at the cache-miss
    request that populated this slot.
    """
    total_ms = int((time.perf_counter() - t_start) * 1000)
    cached_payload = dict(cached)
    cached_payload["latency_ms"] = total_ms

    logger.info(
        "search.query",
        extra={
            "event": "search.query",
            "q_len": len(q),
            "hits": len(cached_payload.get("items", [])),
            "latency_ms": total_ms,
            "fts_ms": 0,
            "cache_hit": True,
            "embedding_ms": 0,
            "vector_ms": 0,
            "fusion_ms": 0,
            "degraded": False,
            "degraded_reason": None,
            "llm_proxy_cache_hit": False,
        },
    )
    return SearchServiceResult(
        payload=cached_payload,
        cache_hit=True,
        fts_ms=0,
    )


# ---------------------------------------------------------------------------
# FTS-only branch (native + coverage-degraded + sqlite dialect)
# ---------------------------------------------------------------------------


async def _run_fts_only_and_cache(
    session: AsyncSession,
    redis: redis_asyncio.Redis | None,
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    t_start: float,
    degraded: bool,
    degraded_reason: str | None,
    embedding_ms: int,
    vector_ms: int,
    fusion_ms: int,
    llm_proxy_cache_hit: bool,
) -> SearchServiceResult:
    """FTS-only envelope build + cache write + structured log."""
    t_fts_start = time.perf_counter()
    items, total_hits = await _run_fts(
        session,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    fts_ms = int((time.perf_counter() - t_fts_start) * 1000)

    hits = [_fts_row_to_hit(row, vector_rank=None) for row in items]

    total_ms = int((time.perf_counter() - t_start) * 1000)
    payload: dict[str, Any] = {
        "items": hits,
        "total_hits": total_hits,
        "latency_ms": total_ms,
    }

    await search_cache.set_cached(
        redis,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        payload={"items": hits, "total_hits": total_hits},
    )

    logger.info(
        "search.query",
        extra={
            "event": "search.query",
            "q_len": len(q),
            "hits": len(hits),
            "latency_ms": total_ms,
            "fts_ms": fts_ms,
            "cache_hit": False,
            "embedding_ms": embedding_ms,
            "vector_ms": vector_ms,
            "fusion_ms": fusion_ms,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "llm_proxy_cache_hit": llm_proxy_cache_hit,
        },
    )
    return SearchServiceResult(
        payload=payload,
        cache_hit=False,
        fts_ms=fts_ms,
        degraded=degraded,
        degraded_reason=degraded_reason,
        embedding_ms=embedding_ms,
        vector_ms=vector_ms,
        fusion_ms=fusion_ms,
        llm_proxy_cache_hit=llm_proxy_cache_hit,
    )


# ---------------------------------------------------------------------------
# Hybrid branch
# ---------------------------------------------------------------------------


async def _run_hybrid(
    session: AsyncSession,
    redis: redis_asyncio.Redis | None,
    embedding_client: LlmProxyEmbeddingClient,
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    vector_k: int,
    t_start: float,
) -> SearchServiceResult:
    """Run FTS + query-embedding concurrently, then vector kNN, then RRF.

    Transient embedding failure falls back to FTS-only with
    ``degraded=True`` / ``degraded_reason="transient"``. Permanent
    embedding failure propagates (router converts to HTTP 500).
    """
    t_fts_start = time.perf_counter()
    fts_coro = _run_fts(
        session, q=q, date_from=date_from, date_to=date_to, limit=limit
    )
    t_emb_start = time.perf_counter()
    emb_coro = _embed_query(embedding_client, q)

    # return_exceptions=True so one leg's failure doesn't cancel the
    # other — we always want the FTS result as the degraded fallback.
    fts_raw, emb_raw = await asyncio.gather(
        fts_coro, emb_coro, return_exceptions=True
    )
    fts_ms = int((time.perf_counter() - t_fts_start) * 1000)
    embedding_ms = int((time.perf_counter() - t_emb_start) * 1000)

    # Unexpected FTS failure propagates — FTS is the base signal and
    # should not transparently degrade to an empty envelope when the
    # database itself is in trouble.
    if isinstance(fts_raw, BaseException):
        raise fts_raw

    fts_items, fts_total_hits = fts_raw

    # Permanent embedding error → router → HTTP 500 (D9).
    if isinstance(emb_raw, PermanentEmbeddingError):
        raise emb_raw

    # Transient embedding error → degraded FTS-only.
    if isinstance(emb_raw, BaseException):
        # Defensive: any other exception class from the embedding
        # call is treated as transient (caller signalled fail-open
        # is preferable to a surprise 500 from an unknown class).
        if not isinstance(emb_raw, TransientEmbeddingError):
            logger.warning(
                "search.embedding.unexpected_exception",
                extra={
                    "event": "search.embedding.unexpected_exception",
                    "error_class": type(emb_raw).__name__,
                },
            )
        return await _finalize_degraded_transient(
            session,
            redis,
            fts_items=fts_items,
            fts_total_hits=fts_total_hits,
            fts_ms=fts_ms,
            embedding_ms=embedding_ms,
            q=q,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            t_start=t_start,
        )

    assert isinstance(emb_raw, EmbeddingResult)  # narrowing
    q_vec = emb_raw.vectors[0]
    llm_proxy_cache_hit = emb_raw.cache_hit

    # Vector kNN (PG-only; dialect gate inside _run_vector_query).
    t_vec_start = time.perf_counter()
    vec_rows = await _run_vector_query(
        session,
        q_vec=q_vec,
        date_from=date_from,
        date_to=date_to,
        limit_k=vector_k,
    )
    vector_ms = int((time.perf_counter() - t_vec_start) * 1000)

    # Fusion (pure).
    t_fuse_start = time.perf_counter()
    fused = search_fusion.rrf_fuse(
        fts_hits=[(row["id"], float(row["fts_rank"])) for row in fts_items],
        vector_hits=[row["id"] for row in vec_rows],
    )
    fusion_ms = int((time.perf_counter() - t_fuse_start) * 1000)

    # Reconstruct hits in fused order. Look-up by id prefers FTS rows
    # (they carry the full ``fts_rank`` float). Vector-only hits fall
    # back to the vector row (which also carries the full report
    # columns — the query selects them all).
    fts_by_id = {row["id"]: row for row in fts_items}
    vec_by_id = {row["id"]: row for row in vec_rows}

    hits: list[dict[str, Any]] = []
    for fused_hit in fused[:limit]:
        source_row = fts_by_id.get(fused_hit.id) or vec_by_id.get(fused_hit.id)
        # source_row cannot be None — fused_hit.id comes from the union
        # of the two input lists. Defensive continue for type-narrowing.
        if source_row is None:  # pragma: no cover
            continue
        hits.append(
            _fts_row_to_hit(
                source_row,
                # Envelope ``fts_rank`` uses the fused value (0.0 for
                # vector-only per OI2 = A); `_fts_row_to_hit` accepts
                # an override.
                vector_rank=fused_hit.vector_rank,
                fts_rank_override=fused_hit.fts_rank,
            )
        )

    # D10-compatible total_hits semantic: size of the unique-id set
    # across FTS + vector (pre-limit). Keeps the envelope honest about
    # "how many distinct candidates did fusion see" without a second
    # COUNT round-trip. On a pure-FTS match (vector contributes 0 new
    # ids) this reduces to the PR #17 semantic (fts_total_hits) once
    # the FTS count isn't capped by the LIMIT — for tiny corpora where
    # FTS already returned < limit rows, len(fused) and fts_total_hits
    # agree.
    total_hits_hybrid = len(fused)

    total_ms = int((time.perf_counter() - t_start) * 1000)
    payload: dict[str, Any] = {
        "items": hits,
        "total_hits": total_hits_hybrid,
        "latency_ms": total_ms,
    }

    await search_cache.set_cached(
        redis,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        payload={"items": hits, "total_hits": total_hits_hybrid},
    )

    logger.info(
        "search.query",
        extra={
            "event": "search.query",
            "q_len": len(q),
            "hits": len(hits),
            "latency_ms": total_ms,
            "fts_ms": fts_ms,
            "cache_hit": False,
            "embedding_ms": embedding_ms,
            "vector_ms": vector_ms,
            "fusion_ms": fusion_ms,
            "degraded": False,
            "degraded_reason": None,
            "llm_proxy_cache_hit": llm_proxy_cache_hit,
        },
    )
    return SearchServiceResult(
        payload=payload,
        cache_hit=False,
        fts_ms=fts_ms,
        degraded=False,
        degraded_reason=None,
        embedding_ms=embedding_ms,
        vector_ms=vector_ms,
        fusion_ms=fusion_ms,
        llm_proxy_cache_hit=llm_proxy_cache_hit,
    )


async def _finalize_degraded_transient(
    session: AsyncSession,
    redis: redis_asyncio.Redis | None,
    *,
    fts_items: list[dict[str, Any]],
    fts_total_hits: int,
    fts_ms: int,
    embedding_ms: int,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    t_start: float,
) -> SearchServiceResult:
    """Build degraded-transient envelope using the ALREADY-fetched FTS rows.

    Unlike ``_run_fts_only_and_cache`` this does NOT re-run FTS —
    ``asyncio.gather`` already paid that round-trip. Reusing the result
    keeps the degraded path strictly cheaper than the native FTS-only
    path (transient is a bad day; let's not pile another query on).
    """
    hits = [_fts_row_to_hit(row, vector_rank=None) for row in fts_items]

    total_ms = int((time.perf_counter() - t_start) * 1000)
    payload: dict[str, Any] = {
        "items": hits,
        "total_hits": fts_total_hits,
        "latency_ms": total_ms,
    }

    await search_cache.set_cached(
        redis,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        payload={"items": hits, "total_hits": fts_total_hits},
    )

    logger.info(
        "search.query",
        extra={
            "event": "search.query",
            "q_len": len(q),
            "hits": len(hits),
            "latency_ms": total_ms,
            "fts_ms": fts_ms,
            "cache_hit": False,
            "embedding_ms": embedding_ms,
            "vector_ms": 0,
            "fusion_ms": 0,
            "degraded": True,
            "degraded_reason": "transient",
            "llm_proxy_cache_hit": False,
        },
    )
    return SearchServiceResult(
        payload=payload,
        cache_hit=False,
        fts_ms=fts_ms,
        degraded=True,
        degraded_reason="transient",
        embedding_ms=embedding_ms,
        vector_ms=0,
        fusion_ms=0,
        llm_proxy_cache_hit=False,
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def _fts_row_to_hit(
    row: dict[str, Any],
    *,
    vector_rank: int | None,
    fts_rank_override: float | None = None,
) -> dict[str, Any]:
    """Convert an FTS/vector row dict to the ``SearchHit`` shape.

    ``fts_rank_override`` lets the hybrid path inject the fused rank
    value (e.g. 0.0 for a vector-only hit per OI2 = A) while keeping
    the rest of the column mapping in one place.
    """
    fts_rank = (
        fts_rank_override
        if fts_rank_override is not None
        else float(row.get("fts_rank", 0.0))
    )
    return {
        "report": {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "url_canonical": row["url_canonical"],
            "published": row["published"],
            "source_id": row["source_id"],
            "source_name": row["source_name"],
            "lang": row["lang"],
            "tlp": row["tlp"],
        },
        "fts_rank": fts_rank,
        "vector_rank": vector_rank,
    }


async def _embed_query(
    client: LlmProxyEmbeddingClient, q: str
) -> EmbeddingResult:
    """Single-text embed wrapper for the hybrid search path.

    Keeping this in its own async function makes the ``asyncio.gather``
    call site read naturally (two peer coroutines) and pins the single-
    text batching choice that ``search_service`` uses (versus the
    multi-text batching the promote route uses).
    """
    return await client.embed([q])


async def _run_fts(
    session: AsyncSession,
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Run the PG FTS query. Returns ``(items, total_hits)``.

    Dialect gate: non-Postgres dialects (sqlite unit-test engine)
    return an empty list + 0 unconditionally (plan D10 applies).
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return [], 0

    # See PR #17 comments for the ``::regconfig`` literal_column
    # rationale; carrying it verbatim.
    config = sa.literal_column("'simple'::regconfig")
    tsquery = sa.func.plainto_tsquery(config, sa.bindparam("q"))
    document = sa.func.to_tsvector(
        config,
        sa.func.coalesce(reports_table.c.title, sa.literal(""))
        + sa.literal(" ")
        + sa.func.coalesce(reports_table.c.summary, sa.literal("")),
    )
    match_expr = document.op("@@")(tsquery)
    rank_expr = sa.cast(
        sa.func.ts_rank_cd(document, tsquery), sa.Float
    ).label("fts_rank")

    base_stmt = (
        sa.select(
            reports_table.c.id,
            reports_table.c.title,
            reports_table.c.url,
            reports_table.c.url_canonical,
            reports_table.c.published,
            reports_table.c.source_id,
            sources_table.c.name.label("source_name"),
            reports_table.c.lang,
            reports_table.c.tlp,
            rank_expr,
        )
        .select_from(
            reports_table.outerjoin(
                sources_table,
                sources_table.c.id == reports_table.c.source_id,
            )
        )
        .where(match_expr)
    )
    if date_from is not None:
        base_stmt = base_stmt.where(reports_table.c.published >= date_from)
    if date_to is not None:
        base_stmt = base_stmt.where(reports_table.c.published <= date_to)

    ordered_stmt = base_stmt.order_by(
        sa.text("fts_rank DESC"),
        reports_table.c.id.desc(),
    ).limit(limit)

    result = await session.execute(ordered_stmt, {"q": q})
    rows = result.mappings().all()

    count_stmt = sa.select(sa.func.count()).select_from(base_stmt.subquery())
    total_hits = (await session.execute(count_stmt, {"q": q})).scalar_one()

    items = [dict(row) for row in rows]
    return items, int(total_hits)


async def _run_vector_query(
    session: AsyncSession,
    *,
    q_vec: list[float],
    date_from: date | None,
    date_to: date | None,
    limit_k: int,
) -> list[dict[str, Any]]:
    """Run the pgvector cosine-kNN query against ``reports.embedding``.

    Dialect gate: non-PG returns ``[]`` (sqlite has no pgvector).

    Returns ``limit_k`` rows with the same column set as ``_run_fts``
    so the service can reconstruct hits uniformly regardless of which
    rank list surfaced an id.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return []

    # pgvector text-literal coercion shape — matches the PR #19a §9.2
    # C2 pinned UPDATE form. ``[a,b,c,...]`` string is safe to build
    # from a trusted float list (no SQL injection surface; SQLAlchemy
    # still round-trips it as a bound parameter of type text).
    q_vec_literal = "[" + ",".join(repr(float(x)) for x in q_vec) + "]"

    # Raw SQL because SQLAlchemy does not natively type ``vector``.
    # Using ``sa.text`` with named binds for q_vec / date filters /
    # limit keeps injection surface zero.
    sql_parts = [
        "SELECT",
        "  r.id AS id,",
        "  r.title AS title,",
        "  r.url AS url,",
        "  r.url_canonical AS url_canonical,",
        "  r.published AS published,",
        "  r.source_id AS source_id,",
        "  s.name AS source_name,",
        "  r.lang AS lang,",
        "  r.tlp AS tlp",
        "FROM reports r",
        "LEFT JOIN sources s ON s.id = r.source_id",
        "WHERE r.embedding IS NOT NULL",
    ]
    params: dict[str, Any] = {
        "q_vec": q_vec_literal,
        "limit_k": limit_k,
    }
    if date_from is not None:
        sql_parts.append("  AND r.published >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        sql_parts.append("  AND r.published <= :date_to")
        params["date_to"] = date_to
    sql_parts.extend(
        [
            "ORDER BY r.embedding <=> CAST(:q_vec AS vector) ASC, r.id DESC",
            "LIMIT :limit_k",
        ]
    )

    stmt = sa.text("\n".join(sql_parts))
    result = await session.execute(stmt, params)
    rows = result.mappings().all()
    return [dict(row) for row in rows]


__all__ = [
    "SearchServiceResult",
    "get_search_results",
    "reset_coverage_cache",
]
