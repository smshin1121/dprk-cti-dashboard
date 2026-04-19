"""Unit tests for PR #17 Group A search service + cache.

Runs against in-memory aiosqlite — the PG FTS path is dialect-gated
inside ``search_service._run_fts`` so non-PG dialects take the D10
empty branch unconditionally. Real FTS ordering semantics are
covered by the real-PG integration tests gated on POSTGRES_TEST_URL.

Review priorities locked at the Group A ask:

1. **D11 cache key stability** — ``cache_key`` is a pure function;
   identical inputs produce identical keys; ``q`` normalization
   (trim + lower) collapses equivalent inputs onto one slot.
2. **D10 empty on non-PG** — sqlite dialect returns ``{items: [],
   total_hits: 0}`` for every query. Never 500, never None.
3. **D9 ``vector_rank`` always None this slice** — every SearchHit
   built by the service has literal ``None`` in the vector_rank
   slot. Forward-compat regression guard.
4. **D11 empty-cache write** — OI6 = A says empty envelopes are
   cached too; a cache-hit test proves the empty path round-trips.
5. **cache_key bypass defense** — ``cache_key(q="")`` raises, so a
   caller that skips the router's 422 gate gets caught here.
"""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from api.read import search_cache, search_service
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


async def _seed_source(engine: AsyncEngine, name: str = "Vendor A") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        s_id = row.scalar_one()
        await s.commit()
        return s_id


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    source_id: int,
    published: dt.date,
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
                published=published,
                tlp="WHITE",
            )
            .returning(reports_table.c.id)
        )
        r_id = row.scalar_one()
        await s.commit()
        return r_id


# ---------------------------------------------------------------------------
# FakeRedis — minimal async stub. Three behaviors: get/set/pipeline none.
# Keeps the test rig PG-free AND Redis-container-free.
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        # TTL not enforced in-memory; the tests care about the round-
        # trip, not the expiry. If a test ever needs TTL semantics,
        # switch to fakeredis.aioredis like the auth-session fixtures.
        self.store[key] = value


# ---------------------------------------------------------------------------
# Cache key stability (D11 OI6 / plan D5 bypass defense)
# ---------------------------------------------------------------------------


class TestCacheKeyShape:
    def test_same_inputs_produce_identical_key(self) -> None:
        k1 = search_cache.cache_key(
            q="lazarus",
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 12, 31),
            limit=10,
        )
        k2 = search_cache.cache_key(
            q="lazarus",
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 12, 31),
            limit=10,
        )
        assert k1 == k2

    def test_q_normalization_collapses_equivalents(self) -> None:
        """"  LazArUs  " + "lazarus" MUST map to the same slot."""
        k1 = search_cache.cache_key(
            q="  LazArUs  ", date_from=None, date_to=None, limit=10
        )
        k2 = search_cache.cache_key(
            q="lazarus", date_from=None, date_to=None, limit=10
        )
        assert k1 == k2

    def test_different_filters_produce_different_keys(self) -> None:
        base = {"q": "x", "limit": 10}
        k_a = search_cache.cache_key(
            **base, date_from=None, date_to=None
        )
        k_b = search_cache.cache_key(
            **base, date_from=dt.date(2026, 1, 1), date_to=None
        )
        k_c = search_cache.cache_key(
            **base, date_from=None, date_to=dt.date(2026, 12, 31)
        )
        assert len({k_a, k_b, k_c}) == 3

    def test_different_limit_produces_different_key(self) -> None:
        assert search_cache.cache_key(
            q="x", date_from=None, date_to=None, limit=10
        ) != search_cache.cache_key(
            q="x", date_from=None, date_to=None, limit=50
        )

    def test_empty_q_bypass_raises(self) -> None:
        """Router 422 gate SHOULD catch this; defense-in-depth."""
        with pytest.raises(ValueError, match="q must not be empty"):
            search_cache.cache_key(
                q="", date_from=None, date_to=None, limit=10
            )
        with pytest.raises(ValueError, match="q must not be empty"):
            search_cache.cache_key(
                q="   ", date_from=None, date_to=None, limit=10
            )

    def test_limit_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="limit out of range"):
            search_cache.cache_key(
                q="x", date_from=None, date_to=None, limit=0
            )
        with pytest.raises(ValueError, match="limit out of range"):
            search_cache.cache_key(
                q="x", date_from=None, date_to=None, limit=51
            )

    def test_key_prefix_is_search(self) -> None:
        k = search_cache.cache_key(
            q="x", date_from=None, date_to=None, limit=10
        )
        assert k.startswith("search:")


# ---------------------------------------------------------------------------
# D10 empty on non-PG dialect (sqlite) — full behavior this slice
# ---------------------------------------------------------------------------


class TestD10EmptyOnNonPG:
    async def test_sqlite_returns_empty_envelope_for_any_query(
        self, engine: AsyncEngine
    ) -> None:
        """Dialect gate: non-PG engines return D10 empty. No 500,
        no crash on missing FTS functions."""
        src = await _seed_source(engine)
        await _seed_report(
            engine, title="lazarus report", source_id=src, published=dt.date(2026, 3, 15)
        )
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s, redis=None, q="lazarus",
                date_from=None, date_to=None, limit=10,
            )
        assert result.cache_hit is False
        assert result.fts_ms >= 0
        assert result.payload["items"] == []
        assert result.payload["total_hits"] == 0
        assert isinstance(result.payload["latency_ms"], int)
        assert result.payload["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# D11 cache round-trip — empty envelope cached per OI6
# ---------------------------------------------------------------------------


class TestD11CacheRoundTrip:
    async def test_miss_then_hit_sequences(
        self, engine: AsyncEngine
    ) -> None:
        fake = _FakeRedis()
        async with AsyncSession(engine) as s:
            first = await search_service.get_search_results(
                s, redis=fake, q="nomatchxyz",
                date_from=None, date_to=None, limit=10,
            )
        assert first.cache_hit is False
        assert first.payload["items"] == []
        assert first.payload["total_hits"] == 0

        # Second call — SAME inputs → cache hit.
        async with AsyncSession(engine) as s:
            second = await search_service.get_search_results(
                s, redis=fake, q="nomatchxyz",
                date_from=None, date_to=None, limit=10,
            )
        assert second.cache_hit is True
        assert second.fts_ms == 0
        assert second.payload["items"] == []
        assert second.payload["total_hits"] == 0

    async def test_redis_none_skips_cache(
        self, engine: AsyncEngine
    ) -> None:
        """``redis=None`` mode — no cache hit possible, every call
        is a miss."""
        async with AsyncSession(engine) as s:
            a = await search_service.get_search_results(
                s, redis=None, q="anything",
                date_from=None, date_to=None, limit=10,
            )
            b = await search_service.get_search_results(
                s, redis=None, q="anything",
                date_from=None, date_to=None, limit=10,
            )
        assert a.cache_hit is False
        assert b.cache_hit is False

    async def test_different_q_opens_fresh_cache_slot(
        self, engine: AsyncEngine
    ) -> None:
        fake = _FakeRedis()
        async with AsyncSession(engine) as s:
            await search_service.get_search_results(
                s, redis=fake, q="alpha",
                date_from=None, date_to=None, limit=10,
            )
            second = await search_service.get_search_results(
                s, redis=fake, q="beta",
                date_from=None, date_to=None, limit=10,
            )
        # "beta" was never cached → miss despite "alpha" being hot.
        assert second.cache_hit is False


# ---------------------------------------------------------------------------
# D9 envelope shape — vector_rank always None this slice
# ---------------------------------------------------------------------------


class TestD9EnvelopeShape:
    async def test_envelope_keys_are_items_total_hits_latency_ms(
        self, engine: AsyncEngine
    ) -> None:
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s, redis=None, q="x",
                date_from=None, date_to=None, limit=10,
            )
        assert set(result.payload.keys()) == {
            "items",
            "total_hits",
            "latency_ms",
        }

    async def test_empty_branch_has_no_hits_but_valid_shape(
        self, engine: AsyncEngine
    ) -> None:
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s, redis=None, q="x",
                date_from=None, date_to=None, limit=10,
            )
        # When hits exist, each must have vector_rank = None this
        # slice. Empty path has no items to check; assertion below
        # is enforced by the populated real-PG integration test.
        assert result.payload["items"] == []
        # D9 total_hits is an int (not a list / None).
        assert isinstance(result.payload["total_hits"], int)
        assert result.payload["total_hits"] >= 0


# ---------------------------------------------------------------------------
# Plan D16 — log line observability contract
# ---------------------------------------------------------------------------


class TestLogLineShape:
    async def test_log_line_fires_with_required_fields(
        self, engine: AsyncEngine, caplog
    ) -> None:
        """D16 — one log line per request with event + q_len + hits
        + latency_ms + fts_ms + cache_hit. NO raw q text."""
        caplog.set_level("INFO", logger="api.read.search_service")
        async with AsyncSession(engine) as s:
            await search_service.get_search_results(
                s, redis=None, q="secret-actor-name-PII",
                date_from=None, date_to=None, limit=10,
            )
        log_records = [
            r for r in caplog.records
            if getattr(r, "event", "") == "search.query"
        ]
        assert len(log_records) == 1
        rec = log_records[0]
        # Required fields present.
        for field in ("q_len", "hits", "latency_ms", "fts_ms", "cache_hit"):
            assert hasattr(rec, field), f"missing {field} on log record"
        # q_len not the raw q — PII guard.
        assert rec.q_len == len("secret-actor-name-PII")
        # Raw q text must NOT appear anywhere in log output.
        log_text = "\n".join(r.getMessage() for r in caplog.records)
        assert "secret-actor-name-PII" not in log_text


# ---------------------------------------------------------------------------
# FE pact path literal alignment — runs unconditionally (no POSTGRES needed)
# ---------------------------------------------------------------------------


class TestSearchFixturePactPathLiteralAlignment:
    """Constant-drift guard for PR #17 Group C pinned fixture ids.

    The FE pact consumer hardcodes ``GET /api/v1/search?q=lazarus``
    plus ``q=nomatchxyz123`` and (via Group F pinned-path discipline)
    expects the provider-state handler to seed the specific ids in
    ``SEARCH_POPULATED_FIXTURE_REPORT_IDS`` + ``SEARCH_EMPTY_FIXTURE_
    REPORT_IDS``. A BE rename without a matching FE update would
    silently fail the live pact verifier.

    Lives in the unit-test module so it runs unconditionally; the
    Postgres-gated pact-state tests cover the DB-side seed shape.
    Pattern mirrors ``test_actor_reports.TestFePactPathLiteralAlignment``.
    """

    def test_populated_fixture_ids_pinned_at_999060_62(self) -> None:
        from api.routers.pact_states import (
            SEARCH_POPULATED_FIXTURE_REPORT_IDS,
        )

        assert SEARCH_POPULATED_FIXTURE_REPORT_IDS == (
            999060,
            999061,
            999062,
        ), (
            "SEARCH_POPULATED_FIXTURE_REPORT_IDS drift — PR #17 plan "
            "pins 999060-62 for the q=lazarus pact interaction"
        )

    def test_empty_fixture_id_pinned_at_999063(self) -> None:
        from api.routers.pact_states import SEARCH_EMPTY_FIXTURE_REPORT_IDS

        assert SEARCH_EMPTY_FIXTURE_REPORT_IDS == (999063,), (
            "SEARCH_EMPTY_FIXTURE_REPORT_IDS drift — PR #17 plan "
            "pins 999063 for the q=nomatchxyz123 pact interaction"
        )

    def test_populated_fixture_seeds_three_reports(self) -> None:
        from api.routers.pact_states import (
            SEARCH_POPULATED_FIXTURE_REPORT_IDS,
        )

        # eachLike on items rejects empty — need >=1. Three rows
        # give the D2 sort a meaningful set of ranks to order and
        # keep human review of a failing verifier log readable.
        assert len(SEARCH_POPULATED_FIXTURE_REPORT_IDS) == 3

    def test_search_ids_do_not_collide_with_other_pinned_fixtures(
        self,
    ) -> None:
        from api.routers.pact_states import (
            SEARCH_EMPTY_FIXTURE_REPORT_IDS,
            SEARCH_POPULATED_FIXTURE_REPORT_IDS,
        )

        # Collision guard — these ranges are used by the existing
        # pinned-id fixtures. A future add to either tuple that
        # overlaps would cross-pollute pact state seeding.
        reserved = {
            999001,  # report detail
            999002,  # incident detail
            999003,  # actor detail (populated)
            999004,  # actor with no reports
            999011,  # similar populated neighbors
            999012,
            999013,
            999020,  # similar populated source
            999030,  # similar empty-embedding source
            999031,  # similar empty-embedding neighbor
            999050,  # actor-reports populated rows
            999051,
            999052,
        }
        all_search_ids = (
            SEARCH_POPULATED_FIXTURE_REPORT_IDS
            + SEARCH_EMPTY_FIXTURE_REPORT_IDS
        )
        for rid in all_search_ids:
            assert rid not in reserved, (
                f"search fixture id {rid} collides with another "
                f"pinned fixture — pick an id outside {reserved}"
            )

    def test_populated_and_empty_ids_are_disjoint(self) -> None:
        """Populated + empty rows share the reports table — their
        pinned ids must be disjoint. A repeat-seed via a state
        dispatch for ``populated`` followed by ``empty`` must not
        step on each other's rows.
        """
        from api.routers.pact_states import (
            SEARCH_EMPTY_FIXTURE_REPORT_IDS,
            SEARCH_POPULATED_FIXTURE_REPORT_IDS,
        )

        assert set(SEARCH_POPULATED_FIXTURE_REPORT_IDS).isdisjoint(
            set(SEARCH_EMPTY_FIXTURE_REPORT_IDS)
        ), (
            "populated and empty fixture id tuples overlap — the two "
            "seed helpers would fight over rows and state replay "
            "would leave the DB in a mixed state"
        )
