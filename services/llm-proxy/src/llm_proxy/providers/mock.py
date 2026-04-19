"""Deterministic mock embedding provider — PR #18 Group A (plan OI3=A).

Returns 1536-dim float vectors derived from ``sha256(text)``. Used
in CI / dev / test so the suite runs offline without an OpenAI API
key. Production use is blocked by the D3 Draft v2 ``mock + prod``
startup guard in ``config.py``.

Determinism contract (criterion #3 of Group A review):

  1. Same text in → same vector out, across processes, across
     machines, across Python versions.
  2. Different texts give different vectors (sha256 collision
     probability is negligible).
  3. Exactly 1536 float values per vector, matching the
     ``reports.embedding vector(1536)`` column on the consumer
     side.
  4. Each float is in ``[-1.0, 1.0]`` (unnormalized — callers
     requiring unit vectors should normalize themselves; the
     `/search` hybrid follow-up normalizes as part of cosine
     kNN setup).

Construction: sha256 produces 32 bytes. We expand to 1536 floats by
hashing (text || chunk_index) 48 times (48 × 32 = 1536) and mapping
each byte to the ``[-1.0, 1.0]`` range via ``(byte / 127.5) - 1.0``.
"""

from __future__ import annotations

import hashlib
import time
from typing import Final

from .base import EmbeddingProvider, ProviderResult

EMBEDDING_DIM: Final[int] = 1536
"""Embedding dimensionality — pinned to match reports.embedding vector(1536)."""

_BYTES_PER_CHUNK: Final[int] = 32  # sha256 output size
_CHUNKS_PER_VECTOR: Final[int] = EMBEDDING_DIM // _BYTES_PER_CHUNK


def _make_vector(text: str) -> list[float]:
    """Expand sha256(text) to a 1536-dim deterministic vector."""
    vector: list[float] = []
    payload = text.encode("utf-8")
    for chunk_index in range(_CHUNKS_PER_VECTOR):
        h = hashlib.sha256(
            payload + b"\x00" + chunk_index.to_bytes(2, "big")
        ).digest()
        for byte in h:
            vector.append((byte / 127.5) - 1.0)
    # Defensive assertion — the arithmetic above SHOULD always yield
    # exactly EMBEDDING_DIM floats, but a future edit that changes
    # the chunk math must flip this loud rather than silently
    # emitting an off-dim vector into Redis.
    assert len(vector) == EMBEDDING_DIM, (
        f"mock provider produced {len(vector)}-dim vector, "
        f"expected {EMBEDDING_DIM}"
    )
    return vector


def _approx_prompt_tokens(texts: list[str]) -> int:
    """Rough token count — 4 chars ≈ 1 token heuristic.

    Matches the usage-signal spirit of the OpenAI provider without
    pulling in tiktoken as a dependency. Mock-only; production
    accuracy comes from OpenAI's own returned ``usage`` block.
    """
    return sum(max(1, len(t) // 4) for t in texts)


class MockEmbeddingProvider(EmbeddingProvider):
    """Offline-safe ``EmbeddingProvider`` for dev / test / CI."""

    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> ProviderResult:
        """Return deterministic 1536-dim vectors + approximate usage.

        Never raises — mock does not fail. Timeouts / errors must be
        exercised via the real OpenAI provider with httpx-mock
        (Group B) because that is where those paths actually live.
        """
        start = time.perf_counter()
        vectors = [_make_vector(t) for t in texts]
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        tokens = _approx_prompt_tokens(texts)
        return ProviderResult(
            vectors=vectors,
            # Prefix with ``mock/`` so logs make the mock origin
            # unambiguous — D8 observability (a reviewer staring at
            # a prod log can tell at a glance that this line was NOT
            # a real provider call).
            model_returned=f"mock/{model}",
            prompt_tokens=tokens,
            total_tokens=tokens,
            upstream_latency_ms=elapsed_ms,
        )
