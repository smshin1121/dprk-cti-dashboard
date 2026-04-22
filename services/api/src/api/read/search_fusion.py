"""Reciprocal Rank Fusion (RRF) for PR #19b hybrid ``/search``.

Pure module — no IO, no logging, no side effects at module load or
call time. This separation is a Group C C2 criterion (`docs/plans/
pr19b-search-hybrid-upgrade.md` §9.2) and is unit-tested by a purity
regression guard.

Algorithm (plan D3, locked 2026-04-22):

    rrf_score(d) = 1 / (k + rank_fts(d)) + 1 / (k + rank_vec(d))

    where each rank is 1-indexed inside its own list and a missing
    rank contributes 0 to the sum. ``k = 60`` is the RRF constant
    locked in D3.

Input contract:

- ``fts_hits``   — pre-sorted list of ``(id, fts_rank_score)`` where
                   position 0 is the best FTS hit. The ``fts_rank_score``
                   is the raw ``ts_rank_cd`` float (PR #17 D9 envelope
                   field); it is preserved verbatim on the output for
                   the envelope and does NOT participate in the RRF
                   score (fusion uses 1-indexed rank from list
                   position, not the raw ``ts_rank_cd`` value).
- ``vector_hits`` — pre-sorted list of ``id`` values where position 0
                   is the closest cosine-distance neighbor.

Output contract (plan D4, OI2 = A locked):

- One ``FusedHit`` per unique id across both lists.
- ``fts_rank`` = the raw ``ts_rank_cd`` score when the hit was in
  ``fts_hits``; otherwise literal ``0.0`` (OI2 = A — "not in FTS
  top-N" sentinel; envelope field stays non-null ``float`` per PR
  #17 D9 to preserve "zero FE churn").
- ``vector_rank`` = the 1-indexed rank when the hit was in
  ``vector_hits``; otherwise ``None``.
- ``rrf_score`` = the fusion score (used for sort; not emitted in
  the HTTP envelope).

Sort (plan D3):

- Primary:   ``rrf_score DESC``
- Tie-break: ``id DESC`` (matches PR #17 D2's secondary sort so
  cache replay stays byte-stable).
"""

from __future__ import annotations

from dataclasses import dataclass


RRF_K_DEFAULT = 60
"""RRF smoothing constant locked by plan D3 (2026-04-22).

Keeps `1/(k+rank)` bounded even for rank=1 (→ 1/61 ≈ 0.0164) and
dampens the contribution of deep-tail hits so a top-3 item in one
list cannot be swamped by dozens of mid-tier items in the other.
60 is the classical RRF value from Cormack / Clarke / Büttcher (2009).
"""


@dataclass(frozen=True, slots=True)
class FusedHit:
    """One fused hit with envelope-ready rank fields.

    ``fts_rank`` and ``vector_rank`` are the envelope-shape values
    that flow into ``SearchHit`` unchanged (`schemas/read.py`).
    ``rrf_score`` is internal — used for sorting, not emitted on the
    wire.
    """

    id: int
    fts_rank: float
    vector_rank: int | None
    rrf_score: float


def rrf_fuse(
    *,
    fts_hits: list[tuple[int, float]],
    vector_hits: list[int],
    k: int = RRF_K_DEFAULT,
) -> list[FusedHit]:
    """Fuse two rank lists via Reciprocal Rank Fusion.

    See module docstring for full input / output / sort contract.
    """
    fts_rank_by_id: dict[int, int] = {}
    fts_score_by_id: dict[int, float] = {}
    for position, (hit_id, score) in enumerate(fts_hits, start=1):
        # A repeated id in ``fts_hits`` keeps the earliest (best)
        # rank — defensive, since PR #17 FTS query is ORDER BY + LIMIT
        # and cannot produce duplicates, but fusion shouldn't rely on
        # upstream purity.
        if hit_id not in fts_rank_by_id:
            fts_rank_by_id[hit_id] = position
            fts_score_by_id[hit_id] = score

    vector_rank_by_id: dict[int, int] = {}
    for position, hit_id in enumerate(vector_hits, start=1):
        if hit_id not in vector_rank_by_id:
            vector_rank_by_id[hit_id] = position

    all_ids = set(fts_rank_by_id) | set(vector_rank_by_id)

    fused: list[FusedHit] = []
    for hit_id in all_ids:
        fts_rank_pos = fts_rank_by_id.get(hit_id)
        vec_rank_pos = vector_rank_by_id.get(hit_id)

        fts_term = 1.0 / (k + fts_rank_pos) if fts_rank_pos is not None else 0.0
        vec_term = 1.0 / (k + vec_rank_pos) if vec_rank_pos is not None else 0.0

        fused.append(
            FusedHit(
                id=hit_id,
                # OI2 = A — literal 0.0 sentinel for vector-only hits
                # (not in FTS top-N). Envelope field stays non-null
                # ``float`` per PR #17 D9 lock.
                fts_rank=fts_score_by_id.get(hit_id, 0.0),
                vector_rank=vec_rank_pos,
                rrf_score=fts_term + vec_term,
            )
        )

    # D3 sort: rrf_score DESC, id DESC. Python's sort is stable, so
    # the double sort ``(−rrf_score, −id)`` gives the deterministic
    # order PR #17's D2 documented for FTS-only (carried into hybrid).
    fused.sort(key=lambda h: (-h.rrf_score, -h.id))
    return fused


__all__ = [
    "FusedHit",
    "RRF_K_DEFAULT",
    "rrf_fuse",
]
