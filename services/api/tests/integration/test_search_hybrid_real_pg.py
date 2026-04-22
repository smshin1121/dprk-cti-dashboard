"""Real-PostgreSQL integration tests for PR #19b hybrid ``/search`` — Group C C4.

Pins the happy-hybrid branch end-to-end against a live Postgres
instance with pgvector, so reviewers (human + Codex) can verify
that ``reports.embedding <=> CAST(:q AS vector)`` + ``1-indexed
vector_rank`` + RRF fusion all flow correctly on the production
shape of the DB — not just on monkey-patched seams.

The other 3 Group C C4 branches (degraded-transient, degraded-
coverage, permanent-500) are covered by
``test_search_hybrid_integration.py`` on sqlite because they never
exercise pgvector; only happy-hybrid needs a real PG + pgvector
engine to validate.

Skipped when ``POSTGRES_TEST_URL`` is unset — matches the pattern
established by ``test_read_real_pg.py`` / ``test_promote_real_pg.py``.
CI sets the env var; local dev can run the sqlite-only suite and
rely on CI for the PG slice.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# Windows fix: psycopg async driver requires SelectorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


pytestmark = pytest.mark.integration


_PG_URL = os.environ.get("POSTGRES_TEST_URL")

if not _PG_URL:
    pytest.skip(
        "POSTGRES_TEST_URL not set — real-PG hybrid /search tests skipped.",
        allow_module_level=True,
    )


from api.embedding_client import EmbeddingResult  # noqa: E402
from api.read import search_service  # noqa: E402


# Full envelope key set — matches PR #17 D9 lock.
_ENVELOPE_KEYS = {"items", "total_hits", "latency_ms"}
_HIT_KEYS = {"report", "fts_rank", "vector_rank"}


@pytest.fixture(autouse=True)
def _reset_coverage_cache_between_tests() -> None:
    search_service.reset_coverage_cache()


@pytest_asyncio.fixture(scope="module")
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_PG_URL, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_sessionmaker(
    pg_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def clean_pg(pg_engine: AsyncEngine) -> None:
    """Truncate reports + sources between tests.

    CASCADE covers the FK chain that ties search-related tables
    together. RESTART IDENTITY keeps ids deterministic for the
    pinned 999xxx range this test uses.
    """
    async with pg_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE reports, sources RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def hybrid_client_pg(
    pg_engine: AsyncEngine,
    session_store,
    fake_redis,
    clean_pg,  # runs first, so each test starts clean
) -> AsyncIterator[AsyncClient]:
    """AsyncClient wired to the real PG engine + fake Redis + fake session."""
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app
    from api.read.search_cache import get_redis_for_search_cache

    sessionmaker = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_redis_for_search_cache] = lambda: fake_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


def _pgvector_literal(vec: list[float]) -> str:
    """Build a pgvector text-literal from a float list.

    Format: ``[a,b,c,...]``. Safe to interpolate — caller input is
    constrained to trusted float lists in this fixture.
    """
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


async def _seed_corpus_with_embeddings(
    session: AsyncSession,
) -> tuple[int, int, int]:
    """Seed 3 Lazarus reports with distinct 1536-dim embeddings.

    Returns (id1, id2, id3). Embeddings are orthogonal unit-ish
    vectors so cosine distance produces a stable kNN ordering
    that matches the report insertion order. This lets the test
    assert a deterministic ``vector_rank`` value per row.
    """
    src_row = await session.execute(
        text(
            "INSERT INTO sources (name, type) VALUES ('Vendor', 'vendor') "
            "RETURNING id"
        )
    )
    source_id = src_row.scalar_one()

    # Orthogonal stub vectors — first-position spike per row.
    def _one_hot(pos: int, dim: int = 1536) -> list[float]:
        vec = [0.0] * dim
        vec[pos] = 1.0
        return vec

    seed_data = [
        (999060, "Lazarus targets SK crypto exchanges",
         "Credential-harvest operation.", _one_hot(0)),
        (999061, "Lazarus phishing campaign",
         "OAuth consent phishing.", _one_hot(1)),
        (999062, "Lazarus loader profiled",
         "New loader variant.", _one_hot(2)),
    ]

    for rid, title, summary, vec in seed_data:
        await session.execute(
            text(
                "INSERT INTO reports "
                "(id, source_id, title, url, url_canonical, sha256_title, "
                "published, lang, tlp, summary, embedding) "
                "VALUES (:id, :s, :t, :u, :uc, :sh, '2026-03-15', 'en', "
                "'WHITE', :sm, CAST(:v AS vector))"
            ),
            {
                "id": rid,
                "s": source_id,
                "t": title,
                "u": f"https://ex.test/r/{rid}",
                "uc": f"https://ex.test/r/{rid}",
                "sh": f"sha-{rid}",
                "sm": summary,
                "v": _pgvector_literal(vec),
            },
        )
    await session.commit()
    return (999060, 999061, 999062)


async def _cookie(make_session_cookie, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


class _StubClientReturningOneHotVector:
    """llm-proxy stub that returns a deterministic embedding.

    The embedding aligns with ``_one_hot(0)`` so row 999060 is the
    closest cosine neighbour (distance 0), followed by 999061 and
    999062 (roughly equal non-zero distance). This makes vector_rank
    assertions deterministic.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, model=None):
        self.calls.append(list(texts))
        vec = [0.0] * 1536
        vec[0] = 1.0
        return EmbeddingResult(
            vectors=[vec],
            model_returned="text-embedding-3-small",
            cache_hit=False,
            upstream_latency_ms=7,
        )


class TestC4HappyHybridRealPg:
    async def test_hybrid_populates_vector_rank_and_keeps_envelope(
        self,
        hybrid_client_pg: AsyncClient,
        pg_sessionmaker: async_sessionmaker[AsyncSession],
        make_session_cookie,
    ) -> None:
        """End-to-end: real PG + pgvector kNN + RRF fusion.

        Verifies:
        - envelope key set matches PR #17 lock
        - per-hit key set matches PR #17 lock
        - ``vector_rank`` populated with a 1-indexed integer on the
          top hit (closest neighbour to the query embedding)
        - ``fts_rank`` present as a float (``ts_rank_cd`` value)
        - degraded / degraded_reason / fallback NOT in body (OI5 = A)
        """
        async with pg_sessionmaker() as s:
            ids = await _seed_corpus_with_embeddings(s)

        stub = _StubClientReturningOneHotVector()
        from api.deps import get_embedding_client
        from api.main import app

        app.dependency_overrides[get_embedding_client] = lambda: stub

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client_pg.get(
            "/api/v1/search",
            params={"q": "lazarus"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()

        # Envelope shape invariant (C1 on live PG).
        assert set(body.keys()) == _ENVELOPE_KEYS
        for forbidden in ("degraded", "degraded_reason", "fallback"):
            assert forbidden not in body

        # At least one hit; each hit has the full PR #17 key set.
        assert len(body["items"]) >= 1
        for hit in body["items"]:
            assert set(hit.keys()) == _HIT_KEYS
            assert isinstance(hit["fts_rank"], (int, float))

        # The row that matches the stub embedding exactly should have
        # vector_rank == 1 (closest cosine neighbour).
        top_matches = [
            hit for hit in body["items"]
            if hit["report"]["id"] == ids[0]
        ]
        assert len(top_matches) == 1
        assert top_matches[0]["vector_rank"] == 1

        # Stub was invoked exactly once for the single query text.
        assert len(stub.calls) == 1
        assert stub.calls[0] == ["lazarus"]

    async def test_hybrid_vector_rank_is_1_indexed_int(
        self,
        hybrid_client_pg: AsyncClient,
        pg_sessionmaker: async_sessionmaker[AsyncSession],
        make_session_cookie,
    ) -> None:
        """Every hit's ``vector_rank`` is a positive int when present
        (never 0-indexed, never a float)."""
        async with pg_sessionmaker() as s:
            await _seed_corpus_with_embeddings(s)

        stub = _StubClientReturningOneHotVector()
        from api.deps import get_embedding_client
        from api.main import app

        app.dependency_overrides[get_embedding_client] = lambda: stub

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client_pg.get(
            "/api/v1/search",
            params={"q": "lazarus"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()

        for hit in body["items"]:
            vr = hit["vector_rank"]
            # vector_rank is either a positive int (in kNN top-N) or
            # None (FTS-only hit outside kNN top-N). NO 0, NO float.
            assert vr is None or (isinstance(vr, int) and vr >= 1), (
                f"vector_rank malformed on hit {hit['report']['id']}: {vr!r}"
            )
