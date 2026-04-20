"""POST /api/v1/embedding — PR #18 Group C.

Thin orchestrator over Group A / B primitives:

  DTO validation (D2)
    → per-text cache lookup (D6: provider+model+text key)
    → provider dispatch for misses only (D3)
    → cache write for misses (24h TTL)
    → envelope assembly with ``dimensions`` (D2 Draft v2 field)
    → structured log via ``make_log_extra`` (D8 LOCKED no-raw-text)

The rate-limit decorator (D5: ``30/minute`` per X-Internal-Token
principal, hashed key) wraps the handler. The limit expression is
resolved at each request from ``Settings`` so ops can tune
``LLM_PROXY_EMBEDDING_RATE_LIMIT`` without redeploying.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis

from ..cache import cache_key, get_many, set_many
from ..config import Settings, get_settings
from ..dependencies import get_embedding_provider, get_redis_client
from ..errors import InvalidInputError
from ..log_schema import make_log_extra
from ..providers.base import EmbeddingProvider
from ..providers.mock import EMBEDDING_DIM
from ..rate_limit import get_limiter

logger = logging.getLogger(__name__)

router = APIRouter()
_limiter = get_limiter()

CACHE_TTL_SECONDS: int = 24 * 60 * 60
"""Embedding cache TTL (plan D6). Embeddings are deterministic per
``(provider, model, text)``, so long TTL is safe — drift surfaces
via the D8 ``model_returned`` field for forensic invalidation."""


# ---------------------------------------------------------------------------
# DTOs (plan D2 Draft v2)
# ---------------------------------------------------------------------------


class EmbeddingRequest(BaseModel):
    """``POST /api/v1/embedding`` request body.

    Plan D2 locks: 1..16 texts, each non-empty after strip, no null.
    Model is optional — server default applied when absent.
    """

    texts: list[str] = Field(
        min_length=1,
        max_length=16,
        description="Input texts to embed. 1..16 per request.",
    )
    model: str | None = Field(
        default=None,
        description=(
            "Model override. When omitted, server uses "
            "LLM_PROXY_EMBEDDING_MODEL from settings."
        ),
    )

    @field_validator("texts")
    @classmethod
    def _validate_each_text(cls, value: list[str]) -> list[str]:
        """Reject empty / whitespace-only / null strings.

        Raises :class:`InvalidInputError` so the 422 body shape is
        consistent with every other D7 error (``{detail, retryable}``
        via :func:`error_handlers.invalid_input_handler`), rather
        than Pydantic's default envelope.
        """
        for i, text in enumerate(value):
            if text is None:
                raise InvalidInputError(detail=f"texts[{i}] must not be null")
            if not isinstance(text, str):
                raise InvalidInputError(detail=f"texts[{i}] must be a string")
            if not text or not text.strip():
                raise InvalidInputError(
                    detail=f"texts[{i}] must not be empty or whitespace-only"
                )
        return value


class EmbeddingItem(BaseModel):
    """One per-text result. ``index`` maps back to the request's
    ``texts[index]`` so partial-cache-hit batches align."""

    embedding: list[float] = Field(description="Embedding vector.")
    index: int = Field(description="Position in the request's texts array.")


class UsageStats(BaseModel):
    """Upstream usage counters (OpenAI's ``usage`` block or mock's
    approximation)."""

    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    """Response envelope — plan D2 Draft v2.

    The top-level ``dimensions`` field is the new Draft v2 addition:
    always 1536 this PR but exposed explicitly so downstream Zod
    schemas (``z.literal(1536)``) can pin the value without hardcoding
    it separately from the actual vector length. A future OI7 widening
    to variable-dim is additive rather than re-shape.
    """

    provider: str
    model: str
    dimensions: int
    items: list[EmbeddingItem]
    usage: UsageStats
    latency_ms: int
    cache_hit: bool


# ---------------------------------------------------------------------------
# Rate-limit expression resolver (D5)
# ---------------------------------------------------------------------------


def _rate_limit_expression() -> str:
    """slowapi-compatible callable form of the rate-limit string.

    Called by slowapi on every request. ``get_settings`` is
    lru-cached, so this is effectively constant per-process but
    honors ``LLM_PROXY_EMBEDDING_RATE_LIMIT`` at app boot.
    """
    return get_settings().llm_proxy_embedding_rate_limit


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

# Literal int codes so this dict does not drag in a starlette-
# version-coupled ``status.HTTP_*`` attribute (several of which are
# deprecated on newer starlette). The wire format is what matters.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {
        "description": (
            "Invalid request — empty texts list, empty / whitespace-only "
            "text, null text, or batch over the max."
        )
    },
    429: {
        "description": (
            "Rate limit exceeded. Either local bucket "
            "(``rate_limit_exceeded`` body) or upstream-bubbled "
            "(``upstream rate limit`` body)."
        )
    },
    502: {
        "description": "Upstream provider returned 5xx or a malformed response."
    },
    503: {
        "description": "Service configuration gap discovered at runtime."
    },
    504: {
        "description": "Local client deadline hit; upstream never responded."
    },
}


@router.post(
    "",
    response_model=EmbeddingResponse,
    status_code=200,
    responses=_ERROR_RESPONSES,
    summary="Generate embeddings for 1..N texts.",
)
@_limiter.limit(_rate_limit_expression)
async def embed(
    request: Request,
    body: EmbeddingRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    redis: Annotated[Redis | None, Depends(get_redis_client)],
) -> EmbeddingResponse:
    """Orchestrate cache lookup → provider dispatch → envelope emit.

    ``request`` is required by slowapi's decorator to compute the
    token-principal bucket key — the route body does not otherwise
    touch it.
    """
    _ = request  # consumed by @_limiter.limit via the decorator chain

    start = time.perf_counter()

    model_requested = body.model or settings.llm_proxy_embedding_model
    provider_name = settings.llm_proxy_embedding_provider

    # Build per-text cache keys. cache_key raises on empty text —
    # the DTO validator already rejected those cases, so this is
    # a defense-in-depth guard.
    keys = [
        cache_key(provider=provider_name, model=model_requested, text=text)
        for text in body.texts
    ]

    hits = await get_many(redis, keys)  # {key: vector}

    miss_indices: list[int] = []
    miss_texts: list[str] = []
    vectors_by_index: dict[int, list[float]] = {}
    for i, (text, key) in enumerate(zip(body.texts, keys)):
        cached = hits.get(key)
        if cached is not None:
            vectors_by_index[i] = cached
        else:
            miss_indices.append(i)
            miss_texts.append(text)

    cache_hits_count = len(vectors_by_index)
    cache_misses_count = len(miss_texts)

    if miss_texts:
        result = await provider.embed(miss_texts, model_requested)
        model_returned = result.model_returned
        prompt_tokens = result.prompt_tokens
        total_tokens = result.total_tokens
        upstream_latency_ms: int | None = result.upstream_latency_ms

        new_entries: dict[str, list[float]] = {}
        for miss_i, vector in zip(miss_indices, result.vectors):
            vectors_by_index[miss_i] = vector
            new_entries[keys[miss_i]] = vector

        redis_ok = await set_many(
            redis, new_entries, ttl_seconds=CACHE_TTL_SECONDS
        )
    else:
        # Full cache hit — no upstream call.
        model_returned = model_requested
        prompt_tokens = 0
        total_tokens = 0
        upstream_latency_ms = None
        redis_ok = True

    total_latency_ms = int((time.perf_counter() - start) * 1000)
    total_text_chars = sum(len(text) for text in body.texts)
    cache_hit_all = cache_misses_count == 0

    items = [
        EmbeddingItem(embedding=vectors_by_index[i], index=i)
        for i in range(len(body.texts))
    ]

    # D8 LOCKED structured log. make_log_extra enforces the no-raw-
    # text allowlist at call time — adding ``texts=body.texts`` here
    # would raise ValueError before the log record is built.
    log_fields: dict[str, Any] = {
        "event": "embedding.generate",
        "provider": provider_name,
        "model_requested": model_requested,
        "model_returned": model_returned,
        "n_texts": len(body.texts),
        "total_text_chars": total_text_chars,
        "cache_hits_count": cache_hits_count,
        "cache_misses_count": cache_misses_count,
        "total_latency_ms": total_latency_ms,
        "redis_ok": redis_ok,
        "rate_limited": False,
    }
    if upstream_latency_ms is not None:
        log_fields["upstream_latency_ms"] = upstream_latency_ms

    logger.info("embedding.generate", extra=make_log_extra(**log_fields))

    return EmbeddingResponse(
        provider=provider_name,
        model=model_returned,
        dimensions=EMBEDDING_DIM,
        items=items,
        usage=UsageStats(
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
        ),
        latency_ms=total_latency_ms,
        cache_hit=cache_hit_all,
    )
