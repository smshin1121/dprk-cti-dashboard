"""Search service for PR #17 Group A (plan D2 / D9 / D10 / D12 / D16).

Implements the FTS-only MVP behind ``GET /api/v1/search?q=...``.

Design contract (hard-locked by `docs/plans/pr17-search-hybrid.md`):

- **D2 FTS-only ranking** (this slice). PostgreSQL
  ``to_tsvector('simple', title || ' ' || summary)`` matched against
  ``plainto_tsquery('simple', :q)`` and sorted by ``ts_rank_cd DESC,
  reports.id DESC``. Hybrid (RRF with vector rank) is deferred — the
  ``vector_rank`` slot in every SearchHit is literal ``None`` this
  slice so the follow-up PR can fill it additively.

- **D9 envelope** — ``SearchResponse(items, total_hits, latency_ms)``.
  Rank metadata on each hit (``fts_rank`` float; ``vector_rank``
  reserved-None).

- **D10 empty contract** — zero FTS matches → ``{items: [],
  total_hits: 0, latency_ms: N}``. NOT 404, NOT 500, NO fake
  fallback. Applies to the dialect gate below too (sqlite has no FTS
  — unit tests see empty envelope unconditionally).

- **D11 cache** — Redis-backed, 60s TTL, key = SHA1 of
  ``(normalized_q | date_from | date_to | limit)`` (see
  ``search_cache.cache_key``). Miss → compute + store. Hit → serve +
  log. Empty results are cached too (OI6 = A).

- **D12 latency budget** — p95 ≤ 250ms. Sub-stage accounting via
  ``_timed`` helper; envelope ``latency_ms`` is the total server-side
  wall clock; log line (D16) carries ``fts_ms`` + ``cache_hit`` for
  observability.

- **D16 log line** — one line per request, NO raw ``q`` text (PII-
  adjacent). Fields: ``event, q_len, hits, latency_ms, fts_ms,
  cache_hit``.

Portability:
    PG FTS (``plainto_tsquery``, ``ts_rank_cd``) is Postgres-specific.
    On sqlite (the API's unit-test engine), the ``ix_reports_title_
    summary_fts`` GIN index doesn't exist and the tsquery functions
    aren't available. The dialect gate returns the D10 empty envelope
    unconditionally — plan D10 IS the full behavior on non-PG
    dialects, so unit tests exercise the empty path without a real
    Postgres instance. Real FTS ordering + ``ts_rank_cd`` semantics
    are covered by the real-PG integration tests gated on
    ``POSTGRES_TEST_URL``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import sqlalchemy as sa
from redis import asyncio as redis_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import reports_table, sources_table
from . import search_cache


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchServiceResult:
    """Service return envelope.

    Shape matches ``SearchResponse`` before Pydantic validation — the
    router wraps the dict into ``SearchResponse(**result.payload)``.
    Using a dataclass so unit tests can assert on ``cache_hit`` +
    ``fts_ms`` without parsing a log line; observability fields are
    NOT serialized into the HTTP response (D16 keeps them in logs).
    """

    payload: dict[str, Any]
    cache_hit: bool
    fts_ms: int


async def get_search_results(
    session: AsyncSession,
    redis: redis_asyncio.Redis | None,
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> SearchServiceResult:
    """Return the search response for ``q`` (FTS-only, plan D2).

    The router validated ``q`` non-empty and ``limit`` bounds already;
    this function assumes valid input. A defensive ``ValueError`` in
    ``search_cache.cache_key`` catches bypass attempts.

    Flow:
        1. Check Redis (``get_cached``). Hit → return cached payload
           with ``cache_hit=True`` and ``fts_ms=0``.
        2. Miss → run FTS query (dialect-gated).
        3. Build envelope with per-hit ``fts_rank`` + null
           ``vector_rank`` + ``total_hits`` + ``latency_ms``.
        4. Write cache (``set_cached`` — empty envelopes cached too).
    """
    t_start = time.perf_counter()

    cached = await search_cache.get_cached(
        redis, q=q, date_from=date_from, date_to=date_to, limit=limit
    )
    if cached is not None:
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
            },
        )
        return SearchServiceResult(
            payload=cached_payload, cache_hit=True, fts_ms=0
        )

    t_fts_start = time.perf_counter()
    items, total_hits = await _run_fts(
        session,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    fts_ms = int((time.perf_counter() - t_fts_start) * 1000)

    hits = [
        {
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
            "fts_rank": float(row["fts_rank"]),
            # D9 forward-compat slot — literal None until the follow-
            # up hybrid PR fills it with a 1-indexed vector-kNN rank.
            "vector_rank": None,
        }
        for row in items
    ]

    total_ms = int((time.perf_counter() - t_start) * 1000)
    payload: dict[str, Any] = {
        "items": hits,
        "total_hits": total_hits,
        "latency_ms": total_ms,
    }

    # OI6 = A — cache every outcome, including empty results, so a
    # palette-keystroke burst on a no-match query doesn't re-hit PG
    # once per 250ms debounce tail.
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
        },
    )
    return SearchServiceResult(
        payload=payload, cache_hit=False, fts_ms=fts_ms
    )


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
    return an empty list + 0 unconditionally (plan D10 applies — see
    module docstring).
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        # D10 full behavior on non-PG — no tsquery / GIN available.
        return [], 0

    # ``plainto_tsquery`` sanitizes user input (punctuation stripped;
    # no boolean operators), which is the safe default for MVP. The
    # ``websearch_to_tsquery`` dialect-variant would support ANDs/ORs
    # but isn't worth the UX-explanation cost until analysts ask.
    #
    # The FTS config must arrive as ``regconfig``, not ``text`` /
    # ``varchar``. PostgreSQL's function resolver applies AT MOST
    # one implicit cast per argument, and the casts ``varchar →
    # regconfig`` + ``text → regconfig`` are NOT marked implicit in
    # a parameterized-query context: sending the config as a bind
    # parameter typed to VARCHAR or TEXT fails with
    # ``function to_tsvector(character varying|text, text) does not
    # exist`` (seen on api-integration + contract-verify CI runs).
    #
    # Using ``sa.literal_column("'simple'::regconfig")`` injects the
    # PG-specific ``::regconfig`` cast directly into the compiled
    # SQL as a literal, side-stepping SQLAlchemy's bind-param type
    # inference. Safe because 'simple' is a hardcoded constant —
    # no user input flows into this fragment. The non-PG path never
    # compiles this expression (see dialect gate above), so sqlite
    # portability is not affected.
    config = sa.literal_column("'simple'::regconfig")
    tsquery = sa.func.plainto_tsquery(config, sa.bindparam("q"))
    document = sa.func.to_tsvector(
        config,
        sa.func.coalesce(reports_table.c.title, sa.literal(""))
        + sa.literal(" ")
        + sa.func.coalesce(reports_table.c.summary, sa.literal("")),
    )
    # ``@@`` match predicate — literal op because SQLAlchemy doesn't
    # model the FTS operator directly.
    match_expr = document.op("@@")(tsquery)
    # ``ts_rank_cd`` over the same document+tsquery; ``Float`` cast so
    # the Python layer receives a float, not a Decimal from psycopg.
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

    # Plan D2 — ``ts_rank_cd DESC, reports.id DESC`` as stable sort
    # (deterministic order across identical inputs — pact relies on
    # this for byte-identical payloads on replay).
    ordered_stmt = base_stmt.order_by(
        sa.text("fts_rank DESC"),
        reports_table.c.id.desc(),
    ).limit(limit)

    result = await session.execute(ordered_stmt, {"q": q})
    rows = result.mappings().all()

    # ``total_hits`` = count of matching rows BEFORE the LIMIT.
    # Wrapping the base_stmt (without ORDER BY / LIMIT) in a subquery
    # + COUNT(*) keeps one round-trip's worth of latency — a second
    # statement but on the same connection. Correlating the count
    # into the main query via a window function would be faster but
    # complicates the sqlite dialect gate above; this shape stays
    # portable and within the D12 FTS ≤ 150ms sub-budget with the
    # GIN index in play.
    count_stmt = sa.select(sa.func.count()).select_from(base_stmt.subquery())
    total_hits = (
        await session.execute(count_stmt, {"q": q})
    ).scalar_one()

    items = [dict(row) for row in rows]
    return items, int(total_hits)


__all__ = [
    "SearchServiceResult",
    "get_search_results",
]
