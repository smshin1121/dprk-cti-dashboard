"""Unit tests for PR #14 Group B similar-reports service + cache.

Three concerns covered here (all dialect-portable, sqlite-only):

1. **Cache key shape (plan D8(c))** — ``(report_id, k)`` is the ONLY
   input to the cache key. A pure-function test locks the shape so
   a future refactor that accidentally includes user id, locale, or
   filter state breaks the contract immediately.

2. **Service D10 empty-contract paths** — the three paths that must
   return ``found=True, items=[]`` without running pgvector:
     (a) non-PG dialect (sqlite test engine)
     (b) source report has NULL embedding  — not testable on
         sqlite without the column; deferred to real-PG integration
     (c) kNN returned zero rows — same, real-PG only

   The sqlite test rig covers path (a) fully. Paths (b) and (c)
   live in ``tests/integration/test_similar_real_pg.py`` (skipped
   locally without ``POSTGRES_TEST_URL``).

3. **404 via ``found=False``** — unknown source report id. The
   router lifts ``found=False`` to HTTP 404 with
   ``{"detail": "report not found"}``.

Redis integration is tested at the router / integration layer. The
cache module's graceful-degrade (Redis error → None / swallow)
behavior is verified via a stub that raises RedisError.
"""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from api.read import similar_cache, similar_service
from api.tables import metadata, reports_table, sources_table

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield eng
    await eng.dispose()


async def _seed_source(engine: AsyncEngine) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name="Mandiant", type="vendor")
            .returning(sources_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


async def _seed_report(
    engine: AsyncEngine, *, title: str, source_id: int
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(reports_table)
            .values(
                title=title,
                url=f"https://ex.test/{title}",
                url_canonical=f"https://ex.test/{title}",
                sha256_title=f"sha-{title}",
                source_id=source_id,
                published=dt.date(2026, 3, 15),
                tlp="WHITE",
            )
            .returning(reports_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


# ---------------------------------------------------------------------------
# Cache key shape — plan D8(c)
# ---------------------------------------------------------------------------


class TestCacheKeyShape:
    def test_key_format_is_prefix_report_id_k(self) -> None:
        assert similar_cache.cache_key(report_id=42, k=10) == "similar_reports:42:10"

    def test_different_k_produces_different_keys(self) -> None:
        """Plan D8(c): two k values for the same report are
        separate cache slots. A k=10 response never leaks into a
        k=20 call.
        """
        k10 = similar_cache.cache_key(report_id=42, k=10)
        k20 = similar_cache.cache_key(report_id=42, k=20)
        assert k10 != k20

    def test_different_report_produces_different_keys(self) -> None:
        assert similar_cache.cache_key(
            report_id=42, k=10
        ) != similar_cache.cache_key(report_id=43, k=10)

    def test_same_inputs_produce_identical_key(self) -> None:
        """Idempotent — two calls with the same (report_id, k) hash
        to the same slot. If this breaks, every cache read misses."""
        assert similar_cache.cache_key(
            report_id=42, k=10
        ) == similar_cache.cache_key(report_id=42, k=10)

    def test_key_has_no_user_or_locale_or_filter(self) -> None:
        """Plan D8(c) lock: the cache key depends ONLY on
        (report_id, k). The signature has no other positional or
        keyword arguments — a regression that adds user / locale /
        filter would either break the import (signature change) or
        leave the key unchanged (drift).
        """
        import inspect

        sig = inspect.signature(similar_cache.cache_key)
        assert set(sig.parameters.keys()) == {"report_id", "k"}

    def test_invalid_report_id_raises(self) -> None:
        with pytest.raises(ValueError):
            similar_cache.cache_key(report_id=0, k=10)
        with pytest.raises(ValueError):
            similar_cache.cache_key(report_id=-1, k=10)

    def test_invalid_k_raises(self) -> None:
        with pytest.raises(ValueError):
            similar_cache.cache_key(report_id=42, k=0)


# ---------------------------------------------------------------------------
# Cache get/set — graceful degrade on Redis error
# ---------------------------------------------------------------------------


class _RaisingRedis:
    """Stub client that raises ``RedisError`` on every operation —
    pins graceful-degrade behavior (the cache helpers must never
    propagate the exception; D10 forbids 500 on the endpoint).
    """

    async def get(self, key: str) -> bytes | None:
        raise RedisError("simulated outage")

    async def set(
        self, key: str, value: str, ex: int | None = None
    ) -> bool:
        raise RedisError("simulated outage")


class TestCacheGracefulDegrade:
    async def test_get_cached_returns_none_on_redis_error(self) -> None:
        r = _RaisingRedis()
        assert (
            await similar_cache.get_cached(r, report_id=42, k=10)
            is None
        )

    async def test_set_cached_swallows_redis_error(self) -> None:
        r = _RaisingRedis()
        # Should NOT raise.
        await similar_cache.set_cached(
            r, report_id=42, k=10, payload={"items": []}
        )

    async def test_none_redis_is_supported_noop(self) -> None:
        """Passing ``redis=None`` is the test-env / no-cache mode."""
        assert (
            await similar_cache.get_cached(None, report_id=42, k=10)
            is None
        )
        await similar_cache.set_cached(
            None, report_id=42, k=10, payload={"items": []}
        )


# ---------------------------------------------------------------------------
# Service — 404 / D10 non-PG empty / k bound precondition
# ---------------------------------------------------------------------------


class TestSimilarServiceD10AndFoundFalse:
    async def test_unknown_source_returns_found_false(
        self, engine: AsyncEngine
    ) -> None:
        """Source report does not exist → ``found=False``. The
        router maps that to 404. items stays empty by construction.
        """
        async with AsyncSession(engine) as s:
            result = await similar_service.get_similar_reports(
                s, source_report_id=99999, k=10
            )
        assert result.found is False
        assert result.items == []

    async def test_non_pg_dialect_returns_empty_D10_contract(
        self, engine: AsyncEngine
    ) -> None:
        """Plan D10 lock: on sqlite (the unit-test dialect), the
        service returns ``found=True, items=[]`` without running a
        pgvector query. This is the honest "no similarity infra
        here" signal — no fake fallback, no 500.
        """
        src = await _seed_source(engine)
        source_id = await _seed_report(
            engine, title="source", source_id=src
        )
        # Seed two more reports that a heuristic substitute could
        # have picked up ("most recent N"). D10 forbids heuristic
        # fallbacks — the result must stay empty on sqlite.
        await _seed_report(engine, title="neighbor-a", source_id=src)
        await _seed_report(engine, title="neighbor-b", source_id=src)

        async with AsyncSession(engine) as s:
            result = await similar_service.get_similar_reports(
                s, source_report_id=source_id, k=10
            )
        assert result.found is True
        # The regression guard for "no heuristic fallback":
        # seeding siblings does NOT produce fake similar entries.
        assert result.items == []
