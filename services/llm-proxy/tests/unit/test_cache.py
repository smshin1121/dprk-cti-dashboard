"""Unit tests for ``llm_proxy.cache`` — PR #18 Group A.

Review criterion #2 pinned: cache key must reflect ALL THREE of
``(provider, model, text)``. Any two inputs that differ by one
segment must produce distinct keys; same inputs must produce
identical keys.
"""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest

from llm_proxy.cache import cache_key, get_many, set_many


# ---------------------------------------------------------------------------
# Criterion #2 — cache_key covers (provider, model, text) exhaustively
# ---------------------------------------------------------------------------


class TestCacheKeyCoverage:
    """Every segment must participate in the hash."""

    def test_identical_inputs_produce_identical_keys(self) -> None:
        a = cache_key(provider="openai", model="text-embedding-3-small", text="foo")
        b = cache_key(provider="openai", model="text-embedding-3-small", text="foo")
        assert a == b

    def test_different_text_produces_different_key(self) -> None:
        a = cache_key(provider="openai", model="m", text="foo")
        b = cache_key(provider="openai", model="m", text="bar")
        assert a != b

    def test_different_model_produces_different_key(self) -> None:
        a = cache_key(provider="openai", model="text-embedding-3-small", text="foo")
        b = cache_key(provider="openai", model="text-embedding-3-large", text="foo")
        assert a != b

    def test_different_provider_produces_different_key(self) -> None:
        """Draft v2 refinement — provider segment guards cross-provider collision."""
        a = cache_key(provider="openai", model="m", text="foo")
        b = cache_key(provider="mock", model="m", text="foo")
        assert a != b, (
            "provider segment must participate in the key — without "
            "it, switching providers would serve cross-provider "
            "semantic vectors from the same cache slot"
        )

    def test_key_namespace_prefix(self) -> None:
        # Prefix lets ops flush embedding cache separately from
        # rate-limit buckets / sessions / other Redis content.
        key = cache_key(provider="openai", model="m", text="foo")
        assert key.startswith("embedding:")

    def test_separator_prevents_concat_ambiguity(self) -> None:
        # If the hash simply concatenated provider+model+text with
        # no separator, then (provider="abc", model="def", text="g")
        # and (provider="ab", model="cdef", text="g") would collide.
        # The \\n separator in cache_key prevents that. Verify.
        a = cache_key(provider="abc", model="def", text="g")
        b = cache_key(provider="ab", model="cdef", text="g")
        assert a != b


class TestCacheKeyRouterBypassDefense:
    """``cache_key`` must reject empty / whitespace inputs.

    The router's 422 gate should catch these first, but a bypass
    (direct call from non-router code, or a future refactor that
    skips the validator) must NOT silently pollute Redis.
    """

    @pytest.mark.parametrize("empty", ["", " ", "   ", "\t\n"])
    def test_empty_text_raises(self, empty: str) -> None:
        with pytest.raises(ValueError, match="empty or whitespace-only text"):
            cache_key(provider="openai", model="m", text=empty)

    def test_empty_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="provider"):
            cache_key(provider="", model="m", text="foo")

    def test_empty_model_raises(self) -> None:
        with pytest.raises(ValueError, match="model"):
            cache_key(provider="openai", model="", text="foo")


# ---------------------------------------------------------------------------
# get_many / set_many round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCacheRoundTrip:
    async def test_miss_returns_empty_dict(self, fake_redis: fakeredis.aioredis.FakeRedis) -> None:
        keys = [cache_key(provider="openai", model="m", text=f"t{i}") for i in range(3)]
        hits = await get_many(fake_redis, keys)
        assert hits == {}

    async def test_set_then_get_round_trip(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        key = cache_key(provider="openai", model="m", text="foo")
        vector = [0.1, 0.2, 0.3]
        await set_many(fake_redis, {key: vector}, ttl_seconds=60)
        hits = await get_many(fake_redis, [key])
        assert hits == {key: vector}

    async def test_partial_hit(self, fake_redis: fakeredis.aioredis.FakeRedis) -> None:
        """Batch request with 2 cached + 1 uncached returns only the 2 hits."""
        key_cached = cache_key(provider="openai", model="m", text="cached_text")
        key_cached2 = cache_key(provider="openai", model="m", text="cached_text2")
        key_miss = cache_key(provider="openai", model="m", text="miss_text")

        await set_many(
            fake_redis,
            {key_cached: [0.1], key_cached2: [0.2]},
            ttl_seconds=60,
        )
        hits = await get_many(fake_redis, [key_cached, key_miss, key_cached2])
        assert hits == {key_cached: [0.1], key_cached2: [0.2]}
        assert key_miss not in hits

    async def test_ttl_expiry_wiring(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """TTL is actually passed to Redis (value reads back but TTL is set)."""
        key = cache_key(provider="openai", model="m", text="ttl_test")
        await set_many(fake_redis, {key: [1.0]}, ttl_seconds=42)
        ttl = await fake_redis.ttl(key)
        # Redis TTL is in seconds; expect ~42 (fakeredis is immediate).
        assert 0 < ttl <= 42

    async def test_set_many_with_none_redis_is_noop(self) -> None:
        # Graceful-degrade path — if Redis is unavailable the router
        # passes ``redis=None`` and cache writes are skipped cleanly.
        result = await set_many(None, {"k": [0.1]}, ttl_seconds=60)
        assert result is True

    async def test_get_many_with_none_redis_returns_empty(self) -> None:
        hits = await get_many(None, ["k1", "k2"])
        assert hits == {}

    async def test_get_many_tolerates_poison_value(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        # A human / legacy-tool wrote non-JSON into the cache slot.
        # get_many should log and treat as miss, NOT raise.
        key = cache_key(provider="openai", model="m", text="poison")
        await fake_redis.set(key, "not valid json {")
        hits = await get_many(fake_redis, [key])
        assert hits == {}

    async def test_json_encodes_full_1536_dim_vector(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """Round-trips a full-dim vector (regression for 1536-element
        JSON encoding cost — fails if someone swaps json for a fixed-
        size msgpack without checking dim)."""
        key = cache_key(provider="openai", model="m", text="big")
        vector = [float(i) * 0.0001 for i in range(1536)]
        await set_many(fake_redis, {key: vector}, ttl_seconds=60)
        hits = await get_many(fake_redis, [key])
        assert len(hits[key]) == 1536
        assert hits[key][0] == 0.0
        assert hits[key][1535] == pytest.approx(0.1535, abs=1e-9)
