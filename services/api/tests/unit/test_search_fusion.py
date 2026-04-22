"""Unit tests for api.read.search_fusion — PR #19b Group B.

Pins the RRF fusion contract declared in ``docs/plans/pr19b-search-
hybrid-upgrade.md`` §2 D3 / §9.2 C2:

- **C2 Purity**  — pure function, deterministic, zero side effects.
- **D3 Algorithm** — ``1/(k+rank_fts) + 1/(k+rank_vec)`` with k=60
  default; missing rank contributes 0.
- **D4 / OI2 = A** — vector-only hit carries ``fts_rank: 0.0`` sentinel
  on the output (envelope non-null float lock).
- **D3 Sort** — ``rrf_score DESC, id DESC``; stable tie-break matches
  PR #17 D2 semantics.

The tests are structured so a failure in any single expectation
surfaces a localized error message rather than being absorbed into
a parametrize row.
"""

from __future__ import annotations

import pytest

from api.read.search_fusion import RRF_K_DEFAULT, FusedHit, rrf_fuse


class TestRrfBasicAlgorithm:
    def test_both_hit_rrf_score_equals_sum_of_reciprocals(self) -> None:
        """id=100 appears rank 1 in both lists → score = 2/(60+1)."""
        fused = rrf_fuse(
            fts_hits=[(100, 0.75)],
            vector_hits=[100],
        )
        assert len(fused) == 1
        hit = fused[0]
        assert hit.id == 100
        assert hit.fts_rank == pytest.approx(0.75)
        assert hit.vector_rank == 1
        assert hit.rrf_score == pytest.approx(2.0 / 61.0)

    def test_fts_only_hit_contributes_fts_term_only(self) -> None:
        """id=200 is FTS-only → score = 1/(60+1), vector_rank None."""
        fused = rrf_fuse(
            fts_hits=[(200, 0.5)],
            vector_hits=[],
        )
        assert len(fused) == 1
        hit = fused[0]
        assert hit.id == 200
        assert hit.fts_rank == pytest.approx(0.5)
        assert hit.vector_rank is None
        assert hit.rrf_score == pytest.approx(1.0 / 61.0)

    def test_vector_only_hit_has_fts_rank_zero_sentinel(self) -> None:
        """id=300 is vector-only (OI2 = A) → fts_rank = 0.0 literal."""
        fused = rrf_fuse(
            fts_hits=[],
            vector_hits=[300],
        )
        assert len(fused) == 1
        hit = fused[0]
        assert hit.id == 300
        # OI2 = A — vector-only hit's envelope ``fts_rank`` stays
        # non-null float; 0.0 is the "not in FTS top-N" sentinel.
        assert hit.fts_rank == 0.0
        assert hit.vector_rank == 1
        assert hit.rrf_score == pytest.approx(1.0 / 61.0)

    def test_both_empty_returns_empty_list(self) -> None:
        assert rrf_fuse(fts_hits=[], vector_hits=[]) == []

    def test_rrf_k_default_is_60(self) -> None:
        """RRF constant default pin per plan D3 lock."""
        assert RRF_K_DEFAULT == 60

    def test_custom_k_changes_score(self) -> None:
        """Explicit ``k`` param overrides the default smoothing constant."""
        fused_k60 = rrf_fuse(
            fts_hits=[(1, 0.1)], vector_hits=[1], k=60
        )
        fused_k10 = rrf_fuse(
            fts_hits=[(1, 0.1)], vector_hits=[1], k=10
        )
        assert fused_k60[0].rrf_score == pytest.approx(2.0 / 61.0)
        assert fused_k10[0].rrf_score == pytest.approx(2.0 / 11.0)


class TestRrfSortContract:
    def test_both_hit_beats_single_hit(self) -> None:
        """id present in both lists ranks above a single-list rank-1 hit."""
        fused = rrf_fuse(
            fts_hits=[(100, 0.9), (200, 0.5)],
            vector_hits=[100, 300],
        )
        # id=100: 1/61 (FTS rank 1) + 1/61 (vec rank 1) = 2/61
        # id=300: 1/62 (vec rank 2)
        # id=200: 1/62 (FTS rank 2)
        # Expected order: [100, 300, 200] — 300 vs 200 tie-breaks on id DESC.
        ids_in_order = [h.id for h in fused]
        assert ids_in_order == [100, 300, 200]

    def test_tie_breaks_on_id_descending(self) -> None:
        """Two ids at identical rrf_score → higher id wins (D3 tie-break)."""
        # Both ids: FTS rank 1 only (same score 1/61). id=999 > id=100.
        fused = rrf_fuse(
            fts_hits=[(100, 0.5)],
            vector_hits=[999],
        )
        # id=100: 1/61; id=999: 1/61. Same rrf_score → id DESC.
        assert [h.id for h in fused] == [999, 100]

    def test_ascending_fts_rank_still_sorts_by_rrf_score_desc(self) -> None:
        """FTS list ordering reflects ts_rank_cd DESC from the DB.

        position 0 = best (rank 1). Deeper positions get smaller RRF
        contributions (1/61 > 1/62 > ...).
        """
        fused = rrf_fuse(
            fts_hits=[(10, 0.9), (20, 0.5), (30, 0.1)],
            vector_hits=[],
        )
        assert [h.id for h in fused] == [10, 20, 30]
        assert fused[0].rrf_score > fused[1].rrf_score > fused[2].rrf_score


class TestRrfUnionCardinalityInvariant:
    """Property-based invariant: len(output) == |set(fts_ids) ∪ set(vec_ids)|."""

    @pytest.mark.parametrize(
        ("fts_ids", "vec_ids"),
        [
            ([], []),
            ([1], []),
            ([], [1]),
            ([1, 2, 3], [4, 5, 6]),          # disjoint
            ([1, 2, 3], [1, 2, 3]),          # identical
            ([1, 2, 3, 4], [3, 4, 5, 6]),    # overlapping
            ([1], [1, 2, 3, 4, 5]),          # asymmetric sizes
            ([10, 20, 30, 40, 50, 60], [5]),
        ],
    )
    def test_output_length_equals_union_cardinality(
        self, fts_ids: list[int], vec_ids: list[int]
    ) -> None:
        fts_hits = [(i, 0.5) for i in fts_ids]
        fused = rrf_fuse(fts_hits=fts_hits, vector_hits=vec_ids)
        expected_size = len(set(fts_ids) | set(vec_ids))
        assert len(fused) == expected_size

    def test_no_duplicate_ids_in_output(self) -> None:
        """Even when an id is in BOTH input lists, it appears once on output."""
        fused = rrf_fuse(
            fts_hits=[(1, 0.5), (2, 0.3)],
            vector_hits=[1, 2, 3],
        )
        ids = [h.id for h in fused]
        assert len(ids) == len(set(ids)) == 3


class TestRrfDuplicateIdInOneList:
    """Defensive: if an upstream list mistakenly contains duplicate ids,
    fusion keeps the first (best-rank) occurrence only."""

    def test_duplicate_id_in_fts_keeps_best_rank(self) -> None:
        fused = rrf_fuse(
            fts_hits=[(1, 0.9), (1, 0.1)],  # duplicate id with worse rank
            vector_hits=[],
        )
        assert len(fused) == 1
        # ``fts_rank`` on output is the score from the first occurrence.
        assert fused[0].fts_rank == pytest.approx(0.9)
        # RRF score uses rank 1 (first occurrence wins).
        assert fused[0].rrf_score == pytest.approx(1.0 / 61.0)

    def test_duplicate_id_in_vector_keeps_best_rank(self) -> None:
        fused = rrf_fuse(
            fts_hits=[],
            vector_hits=[1, 2, 1],  # id=1 at position 0 AND position 2
        )
        # Expect 2 distinct ids; id=1 ranked 1 (best), id=2 ranked 2.
        # Sort by rrf_score DESC, id DESC: 1/61 (id=1) > 1/62 (id=2).
        assert [h.id for h in fused] == [1, 2]
        assert fused[0].vector_rank == 1


class TestRrfPurity:
    """C2 Purity — no IO, no logging, no side effects, deterministic."""

    def test_two_calls_with_same_inputs_produce_equal_outputs(self) -> None:
        fts_hits = [(10, 0.9), (20, 0.5)]
        vector_hits = [20, 30]
        a = rrf_fuse(fts_hits=fts_hits, vector_hits=vector_hits)
        b = rrf_fuse(fts_hits=fts_hits, vector_hits=vector_hits)
        assert a == b

    def test_does_not_mutate_inputs(self) -> None:
        fts_hits = [(10, 0.9), (20, 0.5)]
        vector_hits = [20, 30]
        fts_copy = list(fts_hits)
        vector_copy = list(vector_hits)
        rrf_fuse(fts_hits=fts_hits, vector_hits=vector_hits)
        assert fts_hits == fts_copy
        assert vector_hits == vector_copy

    def test_fused_hit_is_frozen(self) -> None:
        """``FusedHit`` is frozen — downstream consumers can safely
        pass references without worrying about mutation."""
        hit = FusedHit(id=1, fts_rank=0.5, vector_rank=1, rrf_score=0.033)
        with pytest.raises(AttributeError):
            hit.id = 2  # type: ignore[misc]
