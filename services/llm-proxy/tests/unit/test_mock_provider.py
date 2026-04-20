"""Unit tests for ``llm_proxy.providers.mock`` — PR #18 Group A.

Review criterion #3 pinned: mock provider MUST return stably
deterministic 1536-dim vectors. Same text always yields the same
vector across processes; different texts yield different vectors;
every vector is exactly ``EMBEDDING_DIM`` (1536) floats.
"""

from __future__ import annotations

import pytest

from llm_proxy.providers.mock import EMBEDDING_DIM, MockEmbeddingProvider


# ---------------------------------------------------------------------------
# Criterion #3 — 1536-dim deterministic output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMockDeterminism:
    async def test_vectors_are_exactly_1536_dim(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed(["hello world"], model="text-embedding-3-small")
        assert len(result.vectors) == 1
        assert len(result.vectors[0]) == 1536
        assert EMBEDDING_DIM == 1536  # pin the module constant itself

    async def test_same_text_same_vector_across_invocations(self) -> None:
        """Deterministic contract — running the provider twice on the
        same text yields exact-equal vectors."""
        provider = MockEmbeddingProvider()
        r1 = await provider.embed(["lazarus"], model="m")
        r2 = await provider.embed(["lazarus"], model="m")
        assert r1.vectors == r2.vectors

    async def test_different_text_different_vectors(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed(
            ["lazarus", "kimsuky", "andariel"], model="m"
        )
        # Pairwise inequality — no two texts collide on the full
        # 1536-dim vector.
        assert result.vectors[0] != result.vectors[1]
        assert result.vectors[1] != result.vectors[2]
        assert result.vectors[0] != result.vectors[2]

    async def test_batch_preserves_order(self) -> None:
        """``vectors[i]`` corresponds to ``texts[i]`` — critical for
        caller index mapping when batch sizes > 1."""
        provider = MockEmbeddingProvider()
        texts = ["alpha", "beta", "gamma"]
        r_batch = await provider.embed(texts, model="m")
        r_single_alpha = await provider.embed(["alpha"], model="m")
        r_single_beta = await provider.embed(["beta"], model="m")
        r_single_gamma = await provider.embed(["gamma"], model="m")
        assert r_batch.vectors[0] == r_single_alpha.vectors[0]
        assert r_batch.vectors[1] == r_single_beta.vectors[0]
        assert r_batch.vectors[2] == r_single_gamma.vectors[0]

    async def test_values_are_in_unit_range(self) -> None:
        """Bytes are mapped to ``[-1.0, 1.0]`` for consumer-side
        compatibility with cosine similarity expectations."""
        provider = MockEmbeddingProvider()
        result = await provider.embed(["probe"], model="m")
        assert all(-1.0 <= v <= 1.0 for v in result.vectors[0])

    async def test_model_returned_prefixed_mock(self) -> None:
        """Log reader must be able to distinguish mock vs real
        provider output at a glance (D8 observability)."""
        provider = MockEmbeddingProvider()
        result = await provider.embed(["x"], model="text-embedding-3-small")
        assert result.model_returned == "mock/text-embedding-3-small"

    async def test_prompt_tokens_positive_on_non_empty(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed(
            ["short", "a much longer sentence for tokenization"],
            model="m",
        )
        assert result.prompt_tokens > 0
        # Token counts grow with char count (approximation).
        single_short = await provider.embed(["short"], model="m")
        single_long = await provider.embed(
            ["a much longer sentence for tokenization"], model="m"
        )
        assert single_long.prompt_tokens > single_short.prompt_tokens

    async def test_upstream_latency_is_reported(self) -> None:
        """D8 observability — even mock reports a latency value so
        callers that consume ``upstream_latency_ms`` don't need a
        None-guard branch."""
        provider = MockEmbeddingProvider()
        result = await provider.embed(["x"], model="m")
        assert isinstance(result.upstream_latency_ms, int)
        assert result.upstream_latency_ms >= 0


@pytest.mark.asyncio
class TestMockDoesNotRaise:
    """Mock provider never fails — error paths are OpenAI-only."""

    async def test_empty_batch_returns_empty_result(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed([], model="m")
        assert result.vectors == []
        assert result.prompt_tokens == 0

    async def test_single_char_text(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed(["a"], model="m")
        assert len(result.vectors[0]) == 1536

    async def test_unicode_text(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed(["한글 테스트 😀"], model="m")
        assert len(result.vectors[0]) == 1536
        # Unicode preserved through sha256 — same text, same vector.
        r2 = await provider.embed(["한글 테스트 😀"], model="m")
        assert result.vectors == r2.vectors
