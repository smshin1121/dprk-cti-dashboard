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
import logging
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from api.embedding_client import (
    EmbeddingResult,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from api.read import search_cache, search_service
from api.tables import metadata, reports_table, sources_table

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_coverage_cache_between_tests() -> None:
    """PR #19b — prevent coverage-cache leak across tests.

    The coverage ratio is process-local (plan OI4 = B). Without this
    reset, a test that primed the cache with 0.8 would fool a later
    test that expected the sqlite-dialect 0.0 ratio to force degraded.
    """
    search_service.reset_coverage_cache()


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


# ===========================================================================
# PR #19b Group B — hybrid path tests
# ===========================================================================


def _row(
    *,
    rid: int,
    title: str = "report",
    fts_rank: float = 0.0,
    published: dt.date = dt.date(2026, 1, 1),
    source_id: int = 1,
) -> dict[str, Any]:
    """Build a seeded FTS/vector row dict matching service helper shape."""
    return {
        "id": rid,
        "title": title,
        "url": f"https://ex.test/{rid}",
        "url_canonical": f"https://ex.test/{rid}",
        "published": published,
        "source_id": source_id,
        "source_name": "Vendor",
        "lang": "en",
        "tlp": "WHITE",
        "fts_rank": fts_rank,
    }


@dataclass
class _FakeEmbedClient:
    """Stub for ``LlmProxyEmbeddingClient`` — records calls + returns fixed outcome.

    Accepts either ``result`` (EmbeddingResult) OR ``exc`` (Exception)
    via mutually-exclusive construction. Calls are recorded on
    ``.calls`` so tests can assert "client was / was not invoked".
    """

    result: EmbeddingResult | None = None
    exc: BaseException | None = None

    def __post_init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(
        self, texts: list[str], *, model: str | None = None
    ) -> EmbeddingResult:
        self.calls.append(list(texts))
        if self.exc is not None:
            raise self.exc
        assert self.result is not None, "_FakeEmbedClient needs result or exc"
        return self.result


def _ok_embed_result(vec_length: int = 1536) -> EmbeddingResult:
    return EmbeddingResult(
        vectors=[[0.1] * vec_length],
        model_returned="text-embedding-3-small",
        cache_hit=False,
        upstream_latency_ms=42,
    )


def _force_hybrid_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fts_rows: list[dict[str, Any]],
    fts_total: int | None = None,
    vec_rows: list[dict[str, Any]],
    coverage_ratio: float = 0.95,
) -> None:
    """Patch the dispatcher's boundary seams so hybrid runs on sqlite.

    - ``_dialect_is_postgres`` → True (dispatcher takes hybrid branch)
    - ``_run_fts`` → returns seeded rows + total
    - ``_run_vector_query`` → returns seeded rows
    - ``_get_coverage_ratio`` → returns the supplied ratio
    """
    total = fts_total if fts_total is not None else len(fts_rows)

    async def _fake_run_fts(
        session, *, q, date_from, date_to, limit
    ):  # noqa: ANN001 — stubs mirror helper signatures loosely
        return list(fts_rows), total

    async def _fake_run_vec(
        session, *, q_vec, date_from, date_to, limit_k
    ):
        return list(vec_rows)

    async def _fake_coverage(session, *, refresh_seconds):
        return coverage_ratio

    monkeypatch.setattr(search_service, "_dialect_is_postgres", lambda s: True)
    monkeypatch.setattr(search_service, "_run_fts", _fake_run_fts)
    monkeypatch.setattr(search_service, "_run_vector_query", _fake_run_vec)
    monkeypatch.setattr(
        search_service, "_get_coverage_ratio", _fake_coverage
    )


# ---------------------------------------------------------------------------
# TestHybridPathDispatching — who gets to run the hybrid path
# ---------------------------------------------------------------------------


class TestHybridPathDispatching:
    async def test_embedding_client_none_on_sqlite_stays_fts_only_not_degraded(
        self, engine: AsyncEngine
    ) -> None:
        """client=None + sqlite → FTS-only path, degraded=False.

        Feature-disabled is not 'degraded' — plan D5 reserves that
        flag for runtime failure (transient / coverage gate).
        """
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=None,
            )
        assert result.degraded is False
        assert result.degraded_reason is None
        assert result.embedding_ms == 0
        assert result.vector_ms == 0
        assert result.fusion_ms == 0
        assert result.payload["items"] == []

    async def test_embedding_client_present_on_sqlite_still_takes_fts_only(
        self, engine: AsyncEngine
    ) -> None:
        """client=mock + sqlite (real dialect) → hybrid NOT reachable.

        Non-PG dialect is an infrastructure gate, not a degradation
        signal. Embedder must never be invoked here.
        """
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        assert fake.calls == []
        assert result.degraded is False
        assert result.embedding_ms == 0

    async def test_pg_plus_client_runs_hybrid_path(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dialect forced PG + client present + coverage OK → hybrid runs."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.9)],
            vec_rows=[_row(rid=100, fts_rank=0.0)],
            coverage_ratio=0.95,
        )
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        assert len(fake.calls) == 1
        assert fake.calls[0] == ["x"]
        assert result.degraded is False
        # embedding_ms is measured by asyncio.gather wall clock — even
        # for a sub-ms stub call it should be a non-negative int.
        assert result.embedding_ms >= 0

    async def test_coverage_below_threshold_triggers_degraded_coverage(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """coverage < threshold → FTS-only, degraded=True, reason=coverage.

        The embedder must NOT be called — the coverage gate short-
        circuits before the hybrid branch.
        """
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[],
            vec_rows=[],
            coverage_ratio=0.3,  # below default threshold 0.5
        )
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        assert fake.calls == []
        assert result.degraded is True
        assert result.degraded_reason == "coverage"
        assert result.embedding_ms == 0


# ---------------------------------------------------------------------------
# TestHybridPathFusion — envelope shape after hybrid dispatch
# ---------------------------------------------------------------------------


class TestHybridPathFusion:
    async def test_vector_rank_populated_on_shared_hit(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """id in both FTS + vector lists → envelope has vector_rank int."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.9)],
            vec_rows=[_row(rid=100, fts_rank=0.0)],
        )
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        items = result.payload["items"]
        assert len(items) == 1
        assert items[0]["report"]["id"] == 100
        assert items[0]["fts_rank"] == pytest.approx(0.9)
        assert items[0]["vector_rank"] == 1  # 1-indexed rank

    async def test_vector_only_hit_has_fts_rank_zero_sentinel(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OI2 = A — vector-only hit's envelope fts_rank is literal 0.0."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[],  # FTS returned nothing
            vec_rows=[_row(rid=300, fts_rank=0.0)],
        )
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        items = result.payload["items"]
        assert len(items) == 1
        assert items[0]["report"]["id"] == 300
        assert items[0]["fts_rank"] == 0.0
        assert items[0]["vector_rank"] == 1

    async def test_items_ordered_by_rrf_descending(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fused order: shared hits (both rank 1) > single-list rank-1 > rank-2.

        Inputs:
          FTS: [100 (rank 1), 200 (rank 2)]
          vec: [100 (rank 1), 300 (rank 2)]
        Fused scores:
          100: 1/61 + 1/61  = 2/61
          200: 1/62         = 1/62
          300: 1/62         = 1/62
        Order: [100, 300, 200] — ties break on id DESC.
        """
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[
                _row(rid=100, fts_rank=0.9),
                _row(rid=200, fts_rank=0.5),
            ],
            vec_rows=[
                _row(rid=100, fts_rank=0.0),
                _row(rid=300, fts_rank=0.0),
            ],
        )
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        ids = [item["report"]["id"] for item in result.payload["items"]]
        assert ids == [100, 300, 200]

    async def test_total_hits_equals_unique_union_count(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """total_hits = |set(fts_ids) ∪ set(vec_ids)| for hybrid path."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=i, fts_rank=0.5) for i in [1, 2, 3]],
            vec_rows=[_row(rid=i, fts_rank=0.0) for i in [3, 4, 5]],
        )
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        # Union cardinality: {1,2,3,4,5} = 5.
        assert result.payload["total_hits"] == 5

    async def test_limit_caps_returned_items_not_total_hits(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """limit caps items length but not total_hits."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=i, fts_rank=0.5) for i in range(10, 20)],
            vec_rows=[],
        )
        fake = _FakeEmbedClient(result=_ok_embed_result())
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=3,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        assert len(result.payload["items"]) == 3
        assert result.payload["total_hits"] == 10


# ---------------------------------------------------------------------------
# TestDegradedModeBranches — transient, permanent, unexpected
# ---------------------------------------------------------------------------


class TestDegradedModeBranches:
    async def test_transient_embedding_error_degrades_to_fts_only(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Transient exception → FTS-only items, degraded=True, transient reason."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.9)],
            fts_total=1,
            vec_rows=[_row(rid=200, fts_rank=0.0)],  # will be IGNORED on transient
        )
        fake = _FakeEmbedClient(
            exc=TransientEmbeddingError(
                upstream_status=503, reason="upstream_503"
            )
        )
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        assert result.degraded is True
        assert result.degraded_reason == "transient"
        # Items are the already-gathered FTS rows; vector row 200 is
        # NOT in the envelope (degraded path skips vector query).
        ids = [item["report"]["id"] for item in result.payload["items"]]
        assert ids == [100]
        # All envelope vector_rank values are null on degraded.
        assert all(
            item["vector_rank"] is None
            for item in result.payload["items"]
        )

    async def test_permanent_embedding_error_propagates(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Permanent exception → propagated to caller (router → HTTP 500)."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.9)],
            vec_rows=[],
        )
        fake = _FakeEmbedClient(
            exc=PermanentEmbeddingError(
                upstream_status=422, reason="invalid_input"
            )
        )
        async with AsyncSession(engine) as s:
            with pytest.raises(PermanentEmbeddingError):
                await search_service.get_search_results(
                    s,
                    redis=None,
                    q="x",
                    date_from=None,
                    date_to=None,
                    limit=10,
                    embedding_client=fake,  # type: ignore[arg-type]
                )

    async def test_unexpected_exception_treated_as_transient(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Unknown exception class from embed() → fail-open + WARN log.

        Protects against a future exception class surfacing without
        the service knowing whether it's transient or permanent.
        Default is fail-open (degraded) rather than surprise 500.
        """
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.9)],
            fts_total=1,
            vec_rows=[],
        )
        fake = _FakeEmbedClient(exc=RuntimeError("surprise!"))
        caplog.set_level("WARNING", logger="api.read.search_service")
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        assert result.degraded is True
        assert result.degraded_reason == "transient"
        warn_records = [
            r for r in caplog.records
            if getattr(r, "event", "")
            == "search.embedding.unexpected_exception"
        ]
        assert len(warn_records) == 1
        assert warn_records[0].error_class == "RuntimeError"


# ---------------------------------------------------------------------------
# TestCoverageCacheBehavior — process-local cache with refresh + reset
# ---------------------------------------------------------------------------


class TestCoverageCacheBehavior:
    async def test_sqlite_dialect_returns_zero_coverage(
        self, engine: AsyncEngine
    ) -> None:
        """Non-PG dialect always returns 0.0 coverage (cacheable)."""
        async with AsyncSession(engine) as s:
            ratio = await search_service._get_coverage_ratio(
                s, refresh_seconds=600
            )
        assert ratio == 0.0

    async def test_cache_hit_avoids_reissuing_sql(
        self, engine: AsyncEngine
    ) -> None:
        """Second call within refresh window uses cached ratio.

        We check it indirectly by asserting the cached value persists
        across calls WITHOUT waiting and WITHOUT the second call
        re-hitting the DB. The dialect-gate path sets ratio=0.0
        cheaply; the assertion here is the cache dict persists it.
        """
        async with AsyncSession(engine) as s:
            first = await search_service._get_coverage_ratio(
                s, refresh_seconds=600
            )
            # Peek at module state — this is a test-only coupling and
            # acceptable since the test is pinning THAT module state.
            assert search_service._COVERAGE_CACHE["ratio"] == 0.0
            second = await search_service._get_coverage_ratio(
                s, refresh_seconds=600
            )
        assert first == second == 0.0

    async def test_reset_coverage_cache_forces_refresh(
        self, engine: AsyncEngine
    ) -> None:
        """After reset, the cache is cleared and next call re-fetches."""
        async with AsyncSession(engine) as s:
            await search_service._get_coverage_ratio(s, refresh_seconds=600)
        assert search_service._COVERAGE_CACHE["ratio"] is not None

        search_service.reset_coverage_cache()
        assert search_service._COVERAGE_CACHE["ratio"] is None
        assert search_service._COVERAGE_CACHE["fetched_at_monotonic"] == 0.0


# ---------------------------------------------------------------------------
# TestHybridLogFields — D8 additive observability surface
# ---------------------------------------------------------------------------


class TestHybridLogFields:
    async def test_hybrid_log_has_all_new_fields(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """D8 — hybrid success log carries new fields with non-zero ms."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.9)],
            vec_rows=[_row(rid=100, fts_rank=0.0)],
        )
        fake = _FakeEmbedClient(
            result=EmbeddingResult(
                vectors=[[0.1] * 1536],
                model_returned="text-embedding-3-small",
                cache_hit=True,  # exercise llm_proxy_cache_hit=True path
                upstream_latency_ms=12,
            )
        )
        caplog.set_level(logging.INFO, logger="api.read.search_service")
        async with AsyncSession(engine) as s:
            await search_service.get_search_results(
                s,
                redis=None,
                q="lazarus",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        records = [
            r for r in caplog.records
            if getattr(r, "event", "") == "search.query"
        ]
        assert len(records) == 1
        rec = records[0]
        for field in (
            "q_len", "hits", "latency_ms", "fts_ms", "cache_hit",
            "embedding_ms", "vector_ms", "fusion_ms", "degraded",
            "degraded_reason", "llm_proxy_cache_hit",
        ):
            assert hasattr(rec, field), f"missing log field {field}"
        assert rec.degraded is False
        assert rec.degraded_reason is None
        assert rec.llm_proxy_cache_hit is True
        assert "lazarus" not in "\n".join(
            r.getMessage() for r in caplog.records
        )

    async def test_degraded_transient_log_has_transient_reason(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Degraded path log shows reason="transient" on TransientEmbeddingError."""
        _force_hybrid_environment(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.9)],
            fts_total=1,
            vec_rows=[],
        )
        fake = _FakeEmbedClient(
            exc=TransientEmbeddingError(
                upstream_status=429, reason="rate_limited"
            )
        )
        caplog.set_level(logging.INFO, logger="api.read.search_service")
        async with AsyncSession(engine) as s:
            await search_service.get_search_results(
                s,
                redis=None,
                q="x",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=fake,  # type: ignore[arg-type]
            )
        records = [
            r for r in caplog.records
            if getattr(r, "event", "") == "search.query"
        ]
        assert len(records) == 1
        assert records[0].degraded is True
        assert records[0].degraded_reason == "transient"

    async def test_cache_hit_log_has_zeroed_hybrid_fields(
        self, engine: AsyncEngine
    ) -> None:
        """Cache-hit path reports 0 for every new D8 hybrid field."""

        class _Fake:
            def __init__(self) -> None:
                self.store: dict[str, str] = {}

            async def get(self, key: str):
                return self.store.get(key)

            async def set(self, key: str, value: str, ex: int | None = None):
                self.store[key] = value

        fake_redis = _Fake()
        # Prime cache with a miss on sqlite → FTS-only empty envelope
        async with AsyncSession(engine) as s:
            await search_service.get_search_results(
                s,
                redis=fake_redis,  # type: ignore[arg-type]
                q="prime",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=None,
            )
        # Second call — cache hit
        async with AsyncSession(engine) as s:
            result = await search_service.get_search_results(
                s,
                redis=fake_redis,  # type: ignore[arg-type]
                q="prime",
                date_from=None,
                date_to=None,
                limit=10,
                embedding_client=None,
            )
        assert result.cache_hit is True
        # SearchServiceResult surface reflects the log fields
        assert result.embedding_ms == 0
        assert result.vector_ms == 0
        assert result.fusion_ms == 0
        assert result.degraded is False
        assert result.degraded_reason is None
        assert result.llm_proxy_cache_hit is False
