"""Similar-reports service for PR #14 Group B.

Implements the pgvector kNN query behind
``GET /api/v1/reports/{id}/similar?k=10``.

Plan D8 semantics (hard-locked):
    (a) **Self-exclusion** — the source report is never in the result.
    (b) **Stable sort** — ``score DESC, report_id ASC``. Tie-break
        by ``id ASC`` is the cheapest deterministic secondary key;
        Pact relies on this so two calls with the same input
        produce byte-identical payloads.
    (c) **Cache key includes both report_id AND k** — see
        ``similar_cache.cache_key``. This module is pure compute;
        the cache wrap happens at the router layer.
    (d) **k bounds** — ``k ∈ [1, 50]``, default 10. Router enforces
        via ``Query(ge=SIMILAR_K_MIN, le=SIMILAR_K_MAX)``.
    (e) **Score** — cosine similarity in ``[0, 1]`` (``1 - (<=>)``).

Plan D10 (empty contract — critical):
    * Source report NOT FOUND              → ``None`` (router → 404)
    * Source embedding IS NULL              → ``{items: []}`` (200)
    * kNN returned zero rows post-filter    → ``{items: []}`` (200)
    * ``500`` is forbidden on this endpoint (plan D10 explicit).
    * NO fake / heuristic fallback (no "recent N" substitute, no
      "shared-tag overlap"). Empty is the honest signal.

Portability:
    pgvector is Postgres-only. On sqlite (the API's unit-test
    engine), the ``reports.embedding`` column does not exist in the
    table mirror — plan D10 empty contract is applied by default so
    non-PG dialects return ``{items: []}`` for every existing-source
    call. This keeps the D10 code path unit-testable without
    bringing pgvector into the sqlite test rig.

    Real pgvector behavior (self-exclusion, score ordering,
    NULL-embedding handling on BOTH source and neighbors) is
    exercised by the real-PG integration tests behind
    ``POSTGRES_TEST_URL``.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import reports_table


@dataclass(frozen=True)
class SimilarReportsResult:
    """Service return envelope.

    Using a dataclass (not a dict) so callers can tell "source not
    found" apart from "source found but zero similar" at the type
    layer instead of sniffing for a sentinel in a dict shape.

    ``found=False`` ⇒ router emits 404.
    ``found=True`` ⇒ router emits 200 with ``items`` (possibly empty
    per plan D10).
    """

    found: bool
    items: list[dict[str, object]]


async def get_similar_reports(
    session: AsyncSession, *, source_report_id: int, k: int
) -> SimilarReportsResult:
    """Return up to ``k`` reports most similar to ``source_report_id``.

    Step 1 — source existence check. A dedicated SELECT so the 404
    path does not run the pgvector query uselessly. Returns
    ``SimilarReportsResult(found=False, items=[])`` on unknown id.

    Step 2 — dialect gate. pgvector is Postgres-only; any other
    dialect (notably the sqlite unit-test engine) returns the D10
    empty contract unconditionally.

    Step 3 — pgvector kNN with self-exclusion + stable sort + LIMIT.
    The SQL runs on the live session and uses raw ``text()`` because
    SQLAlchemy does not natively type ``vector(1536)`` — a scalar
    subquery fetches the source embedding inline, and the resulting
    expression uses pgvector's ``<=>`` cosine distance operator.
    Score is ``1 - distance`` so higher values mean "more similar".

    Returns (dialect, unfound, null-embedding, zero-neighbor rows):
        SimilarReportsResult(found=True, items=[]).
    Returns (populated):
        SimilarReportsResult(found=True, items=[{report, score}, ...]).
    """
    exists_stmt = sa.select(reports_table.c.id).where(
        reports_table.c.id == source_report_id
    )
    exists_result = await session.execute(exists_stmt)
    if exists_result.first() is None:
        # D10 does NOT apply to the "source does not exist" case —
        # that's a 404 per D1 (contract consistency with the other
        # detail endpoints). Router translates ``found=False``.
        return SimilarReportsResult(found=False, items=[])

    dialect = session.get_bind().dialect.name
    if dialect != "postgresql":
        # Non-PG dialect (sqlite unit-test engine). pgvector does
        # not exist here — plan D10 empty-contract covers this path.
        # No fake similarity fallback per D10's explicit prohibition.
        return SimilarReportsResult(found=True, items=[])

    # PG path — raw pgvector kNN. The ``1 - (embedding <=> src_emb)``
    # expression converts pgvector's cosine DISTANCE (0 = identical,
    # 2 = opposite) to cosine SIMILARITY (1 = identical, -1 =
    # opposite). Non-negative-only scores aren't guaranteed by
    # cosine semantics but the DTO validator clamps and any rows
    # with score < 0 (genuinely dissimilar) would have been pushed
    # to the bottom of the ORDER BY anyway — self-exclusion + LIMIT
    # k filters them out in practice.
    #
    # Both NULL-embedding branches (source + neighbor) produce NULL
    # scores under ``<=>``; we filter neighbors with
    # ``r.embedding IS NOT NULL`` explicitly so D10's "neighbors
    # with no embedding are invisible" rule is pinned.
    #
    # Source NULL embedding: the scalar subquery returns NULL, every
    # ``<=>`` against NULL is NULL, ORDER BY NULL DESC puts NULLs
    # first. To enforce D10's "source has no embedding → empty"
    # contract cleanly, we early-return before running the query
    # when the source embedding is NULL.
    src_emb_stmt = sa.text(
        "SELECT embedding IS NOT NULL AS has_embedding "
        "FROM reports WHERE id = :src_id"
    )
    src_emb_row = (
        await session.execute(src_emb_stmt, {"src_id": source_report_id})
    ).first()
    # Defensive: source existed in Step 1; this should always return
    # a row. If it did not (race w/ DELETE), treat as D10 empty.
    if src_emb_row is None or not src_emb_row[0]:
        return SimilarReportsResult(found=True, items=[])

    knn_stmt = sa.text(
        """
        SELECT
            r.id AS id,
            r.title AS title,
            r.url AS url,
            r.published AS published,
            s.name AS source_name,
            (1 - (r.embedding <=> (
                SELECT embedding FROM reports WHERE id = :src_id
            )))::float AS score
        FROM reports r
        LEFT JOIN sources s ON s.id = r.source_id
        WHERE r.id != :src_id
          AND r.embedding IS NOT NULL
        ORDER BY score DESC, r.id ASC
        LIMIT :k
        """
    )
    result = await session.execute(
        knn_stmt,
        {"src_id": source_report_id, "k": k},
    )
    rows = result.mappings().all()
    items = [
        {
            "report": {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "published": row["published"],
                "source_name": row["source_name"],
            },
            # Clamp score into [0.0, 1.0] for DTO conformance —
            # cosine similarity can dip negative when two embeddings
            # are near-orthogonal, which the DTO's Field(ge=0, le=1)
            # would reject. Clamping is safe here because rows with
            # a negative score are, by definition, not useful
            # "similar" results; presenting them as 0.0 is a fair
            # "we have nothing better" signal without violating D10
            # (no heuristic substitute, just a truthful lower bound).
            "score": max(0.0, min(1.0, float(row["score"] or 0.0))),
        }
        for row in rows
    ]
    return SimilarReportsResult(found=True, items=items)


__all__ = ["SimilarReportsResult", "get_similar_reports"]
