"""Redis-backed embedding cache — PR #18 Group A (plan D6 Draft v2).

Per-text cache so a batch request with partial hits works cleanly:
a 16-text batch where 10 are cached results in one upstream call
carrying the remaining 6, not a full-batch upstream or a 16-call
fan-out.

Cache key includes ``provider + model + text`` — all three segments
load-bearing:

- ``text`` obviously changes the vector.
- ``model`` changes the vector (different models are different
  semantic spaces; cross-model keys would collide destructively).
- ``provider`` changes the vector even for the SAME model string —
  a future second provider could mint a name collision (e.g.,
  "text-embedding-3-small" is an OpenAI convention but providers
  are free to reuse common model names). Partitioning by provider
  blocks cross-provider semantic collisions by construction.

Graceful ``RedisError`` degrade: cache failures never 5xx the
endpoint — the router continues to call upstream + return fresh
results. Cache is an optimization, not a correctness requirement.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Mapping, Sequence

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_CACHE_NAMESPACE = "embedding"


def cache_key(*, provider: str, model: str, text: str) -> str:
    """Return the Redis key for a single ``(provider, model, text)`` tuple.

    Pure function — same inputs always yield the same key; no env
    lookups, no Redis calls. Tested exhaustively for collision
    resistance across provider / model drift.

    Raises ``ValueError`` on empty / whitespace-only text so a router
    that bypasses the 422 input validator still gets caught here
    before a garbage cache entry lands.

    Hash construction: `sha256(provider + "\\n" + model + "\\n" + text)`.
    The explicit ``\\n`` separator prevents the (provider, model, text)
    = (``openai\\ntext-embedding-3-small``, ``""``, ``"foo"``) kind
    of concat-ambiguity attack. All three segments are hashed
    together so a change in any one opens a fresh slot.
    """
    if not text or not text.strip():
        raise ValueError(
            "cache_key called with empty or whitespace-only text — "
            "router-side 422 gate bypassed"
        )
    if not provider.strip():
        raise ValueError("cache_key: provider must be non-empty")
    if not model.strip():
        raise ValueError("cache_key: model must be non-empty")

    payload = f"{provider}\n{model}\n{text}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"{_CACHE_NAMESPACE}:{digest}"


async def get_many(
    redis: Redis | None,
    keys: Sequence[str],
) -> dict[str, list[float]]:
    """Look up ``keys`` in Redis; return a dict of the hits.

    Misses are absent from the returned dict — callers iterate the
    request's text list and dispatch cache-miss indices to the
    upstream provider.

    ``RedisError`` downgrades to "all miss" — the router will serve
    from upstream. Logged at WARNING so ops can see cache unavail
    without paging.
    """
    if redis is None or not keys:
        return {}

    try:
        raw_values = await redis.mget(list(keys))
    except RedisError as exc:  # pragma: no cover - tested via fake error
        logger.warning(
            "cache.get_many.redis_error",
            extra={"event": "cache.get_many.redis_error", "error": str(exc)},
        )
        return {}

    hits: dict[str, list[float]] = {}
    for key, raw in zip(keys, raw_values):
        if raw is None:
            continue
        try:
            vector = json.loads(raw)
        except (ValueError, TypeError):
            # Poison value — log and skip, treat as miss.
            logger.warning(
                "cache.get_many.decode_error",
                extra={"event": "cache.get_many.decode_error"},
            )
            continue
        if isinstance(vector, list):
            hits[key] = vector
    return hits


async def set_many(
    redis: Redis | None,
    values: Mapping[str, list[float]],
    ttl_seconds: int,
) -> bool:
    """Write every ``{key: vector}`` with ``ttl_seconds`` TTL.

    Returns ``True`` on full success, ``False`` if Redis refused
    (``RedisError``). Never raises — cache writes are best-effort.
    """
    if redis is None or not values:
        return True

    try:
        pipe = redis.pipeline()
        for key, vector in values.items():
            pipe.set(key, json.dumps(vector), ex=ttl_seconds)
        await pipe.execute()
        return True
    except RedisError as exc:  # pragma: no cover - tested via fake error
        logger.warning(
            "cache.set_many.redis_error",
            extra={"event": "cache.set_many.redis_error", "error": str(exc)},
        )
        return False
