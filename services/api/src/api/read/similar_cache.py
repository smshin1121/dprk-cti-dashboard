# noqa: E501  — docstring width for clarity
"""Redis cache for ``GET /api/v1/reports/{id}/similar`` (PR #14 Group B).

Plan D8(c) locks the cache key on ``(report_id, k)`` — no other
inputs participate (no user, no filter, no locale). Two separate
``k`` values for the same source report occupy separate slots so a
``k=10`` response never leaks into a ``k=20`` call.

TTL per design doc §7.7: 5 minutes. Short enough that embedding
backfill latency is never held stale; long enough to absorb the
typical analyst browsing pattern (open detail → read → come back).

Graceful degradation:
    Redis hiccups are non-fatal — this feature is a read-path
    optimization, not a correctness requirement. Cache errors
    (``RedisError``, ``TimeoutError``) are logged and the caller
    proceeds as if the cache missed. D10 empty-contract semantics
    are enforced by the service layer independently of the cache,
    so a Redis outage never forces a 500 here (plan D10 forbids 500
    on this endpoint).

Scope boundary:
    This module handles ONLY the cache-key shape and the serialize
    / deserialize round-trip. The pgvector kNN query, self-exclusion,
    and D10 empty contract all live in ``similar_service.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis import asyncio as redis_asyncio
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError


logger = logging.getLogger(__name__)

# Plan D8(c) — 5-minute TTL mirrors design doc §7.7 cache policy.
SIMILAR_CACHE_TTL_SECONDS = 300

# Key prefix — keeps similar-reports slots grouped and prevents
# collisions with session / rate-limit keys in the same Redis.
_CACHE_KEY_PREFIX = "similar_reports"


def cache_key(*, report_id: int, k: int) -> str:
    """Deterministic cache key for a (report_id, k) pair.

    The shape ``similar_reports:{report_id}:{k}`` is the D8 lock:
    two different k values never alias, two calls with the same
    (report_id, k) always hit the same slot. No user / locale /
    filter participates — the similar-reports contract is
    user-agnostic (the BE response depends only on the DB state
    and the two inputs, never on the caller).

    Kept as a module-level pure function so unit tests can verify
    the shape without a Redis client — the key is the contract, not
    the storage.
    """
    if not isinstance(report_id, int) or report_id < 1:
        raise ValueError(f"report_id must be a positive int, got {report_id!r}")
    if not isinstance(k, int) or k < 1:
        raise ValueError(f"k must be a positive int, got {k!r}")
    return f"{_CACHE_KEY_PREFIX}:{report_id}:{k}"


async def get_cached(
    redis: redis_asyncio.Redis | None,
    *,
    report_id: int,
    k: int,
) -> dict[str, Any] | None:
    """Return the cached response payload, or ``None`` on miss.

    ``redis=None`` is a supported mode — callers that don't want to
    hit Redis (unit tests, test environments without the container)
    pass ``None`` and receive ``None`` deterministically. Production
    paths always pass a real client.

    Redis errors degrade to a miss. The caller proceeds with a DB
    query. No exception propagates — D10 forbids 500 on this
    endpoint, and a cache blip is not a 500-worthy condition.
    """
    if redis is None:
        return None
    key = cache_key(report_id=report_id, k=k)
    try:
        raw = await redis.get(key)
    except (RedisError, RedisTimeoutError) as exc:
        logger.warning("similar_cache.get failed for %s: %s", key, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning("similar_cache.get decode failed for %s: %s", key, exc)
        return None


async def set_cached(
    redis: redis_asyncio.Redis | None,
    *,
    report_id: int,
    k: int,
    payload: dict[str, Any],
    ttl_seconds: int = SIMILAR_CACHE_TTL_SECONDS,
) -> None:
    """Write the response payload under the D8 key shape.

    Same graceful-degrade semantics as ``get_cached``: a Redis error
    logs and returns without re-raising. Caching is opportunistic;
    the caller already has the answer.
    """
    if redis is None:
        return
    key = cache_key(report_id=report_id, k=k)
    try:
        await redis.set(key, json.dumps(payload, default=str), ex=ttl_seconds)
    except (RedisError, RedisTimeoutError) as exc:
        logger.warning("similar_cache.set failed for %s: %s", key, exc)


def get_redis_for_similar_cache() -> redis_asyncio.Redis | None:
    """FastAPI dependency getter — returns the Redis client used for
    the similar-reports cache, or ``None`` when the caller is in a
    test / offline mode.

    Production default is to reuse the session Redis client from
    ``api.auth.session._get_redis`` so the similar-cache and the
    session store share one connection pool. Tests override this
    dependency to ``lambda: None`` (no-op cache) or to a fakeredis
    instance via ``app.dependency_overrides``.

    Import is inline to avoid a module-load cycle with the session
    module (which itself imports from ``api.config``).
    """
    from ..auth.session import _get_redis

    return _get_redis()


__all__ = [
    "SIMILAR_CACHE_TTL_SECONDS",
    "cache_key",
    "get_cached",
    "get_redis_for_similar_cache",
    "set_cached",
]
