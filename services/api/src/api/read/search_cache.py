"""Redis cache for ``GET /api/v1/search`` (PR #17 Group A, plan D11).

Cache key shape: ``search:{sha1(normalized_q | date_from | date_to | limit)}``.
The SHA1 lets the key length stay bounded regardless of query text;
the inputs are structurally separated by ``|`` so a caller can never
build a colliding key by embedding a pipe in ``q`` (``q`` is first
normalized to lower + trimmed — see ``normalize_q`` — and FastAPI
sanitizes query-string encodings before this module sees the value).

TTL: 60 seconds (plan D11). Short enough to stay honest with new
ingest; long enough to absorb ⌘K palette debounce tails where the
user retypes the same query within a minute.

Plan D11 — **empty results are cached too** (OI6 = A). Palette-
keystroke bursts against a no-match query would otherwise fire N
DB queries at 250ms debounce intervals; caching the empty envelope
collapses that to one DB touch per minute.

Graceful degradation:
    Redis hiccups degrade to miss + compute, NEVER to 500. Plan
    D10 forbids 500 on /search (empty is the only allowed honest
    signal); a cache blip is nowhere near 500-worthy.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from typing import Any

from redis import asyncio as redis_asyncio
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError


logger = logging.getLogger(__name__)


_CACHE_KEY_PREFIX = "search"


def normalize_q(q: str) -> str:
    """Lowercase + strip surrounding whitespace.

    The router rejects empty / whitespace-only ``q`` at the 422 gate
    BEFORE this function runs (plan D5). Normalization here only
    collapses equivalent user inputs (``"  LazArUs "`` and
    ``"lazarus"``) onto the same cache slot.

    Kept pure so unit tests can assert key stability without a
    Redis client — the normalization is the contract, not the
    storage.
    """
    return q.strip().lower()


def cache_key(
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> str:
    """Deterministic cache key for a ``(q, filters, limit)`` tuple.

    Key shape: ``search:{sha1_hex[:16]}``. The SHA1 is computed over
    the pipe-joined canonical form::

        normalized_q | date_from_iso_or_NONE | date_to_iso_or_NONE | limit

    The first 16 hex chars of the digest keep the key short (matching
    Redis-friendly key-length conventions) while keeping collision
    probability negligible for corpus-scale inputs (~2^64 namespace;
    /search receives O(10^3) unique queries per day at steady state).

    Validation:
        * ``q`` MUST be non-empty post-normalization (router gate).
          A caller that bypasses the gate and passes ``""`` raises
          ``ValueError`` here so the test rig catches the bypass.
        * ``limit`` MUST be in ``[SEARCH_LIMIT_MIN, SEARCH_LIMIT_MAX]``
          — same router-enforced bound; defensive check here.
    """
    norm_q = normalize_q(q)
    if not norm_q:
        raise ValueError("q must not be empty after normalization")
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValueError(f"limit out of range (1..50): {limit!r}")

    df = date_from.isoformat() if date_from is not None else "NONE"
    dt = date_to.isoformat() if date_to is not None else "NONE"
    raw = f"{norm_q}|{df}|{dt}|{limit}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    return f"{_CACHE_KEY_PREFIX}:{digest}"


async def get_cached(
    redis: redis_asyncio.Redis | None,
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> dict[str, Any] | None:
    """Return the cached response payload, or ``None`` on miss.

    ``redis=None`` is a supported mode — unit tests and offline
    environments receive a deterministic ``None``. Redis errors
    degrade to a miss + log.
    """
    if redis is None:
        return None
    key = cache_key(q=q, date_from=date_from, date_to=date_to, limit=limit)
    try:
        raw = await redis.get(key)
    except (RedisError, RedisTimeoutError) as exc:
        logger.warning("search_cache.get failed for %s: %s", key, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning("search_cache.get decode failed for %s: %s", key, exc)
        return None


async def set_cached(
    redis: redis_asyncio.Redis | None,
    *,
    q: str,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    payload: dict[str, Any],
    ttl_seconds: int = 60,
) -> None:
    """Write the response payload under the D11 key shape.

    Empty results ARE cached (OI6 = A) — no special-case for
    ``payload['items'] == []``. Redis errors log + swallow; caller
    already has the answer.
    """
    if redis is None:
        return
    key = cache_key(q=q, date_from=date_from, date_to=date_to, limit=limit)
    try:
        await redis.set(key, json.dumps(payload, default=str), ex=ttl_seconds)
    except (RedisError, RedisTimeoutError) as exc:
        logger.warning("search_cache.set failed for %s: %s", key, exc)


def get_redis_for_search_cache() -> redis_asyncio.Redis | None:
    """FastAPI dependency getter — returns the Redis client the
    search cache uses, or ``None`` in test/offline mode.

    Reuses the session Redis client (same connection pool as
    ``similar_cache``) so the two read-caches share one connection
    budget. Inline import avoids the module-load cycle with
    ``api.config`` that ``api.auth.session`` owns.
    """
    from ..auth.session import _get_redis

    return _get_redis()


__all__ = [
    "cache_key",
    "get_cached",
    "get_redis_for_search_cache",
    "normalize_q",
    "set_cached",
]
