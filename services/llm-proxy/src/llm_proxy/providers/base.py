"""Embedding provider protocol — PR #18 Group A (plan §3).

Every concrete provider (OpenAI, mock, future additions) implements
``EmbeddingProvider`` and returns a ``ProviderResult``. The route
layer depends only on this protocol — swapping providers is a
one-line dispatch in ``main.py`` (Group C).

``model_returned`` is the model string the upstream actually used,
which may be more specific than ``model_requested`` (OpenAI
sometimes returns a versioned suffix). D8 observability logs both
so forensic cache flushes can target drift without touching caller
code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderResult:
    """Return value shape of every ``EmbeddingProvider.embed`` call."""

    vectors: list[list[float]]
    """Per-text embedding vectors. Same length as the request's texts."""

    model_returned: str
    """Model string the upstream identified itself with in the response."""

    prompt_tokens: int
    """Token count across all texts (usage counter)."""

    total_tokens: int
    """Total tokens including any request-side overhead (usage counter)."""

    upstream_latency_ms: int
    """Wall-clock time from provider call to response, milliseconds."""


class EmbeddingProvider(Protocol):
    """Every provider fulfills this async callable surface.

    Implementations are free to be stateful (connection pool, rate-
    limit token bucket, etc.); the route layer treats each instance
    as a black box.
    """

    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> ProviderResult:
        """Generate embeddings for ``texts`` using ``model``.

        Raises:
            UpstreamError: upstream returned 5xx.
            UpstreamTimeoutError: local deadline hit without response.
            UpstreamRateLimitError: upstream returned 429.
            ConfigurationError: provider not ready to serve
                (e.g. missing credentials discovered at runtime).
        """
        ...
