"""HTTP-level integration tests for PR #19b hybrid ``/search`` — Group C.

Pins the `docs/plans/pr19b-search-hybrid-upgrade.md` §9.2 C1-C4
criteria at the HTTP surface (the place a reviewer verifies the
service contract, not just the pure-function behaviour Group B
already locked at the unit layer).

C1 — **Envelope shape invariant.** Populated / empty / degraded
     response field sets match the PR #17 lock exactly. Only the
     value stored inside ``vector_rank`` changes — never the key
     set, never a new top-level field (OI5 = A body-level no-op).

C3 — **Dialect guard.** sqlite requests never call the vector
     leg; `_run_vector_query` spy asserts zero invocations.

C4 — **Four-branch pin** (HTTP layer — complements Group B's
     service-layer unit pins):

  - Degraded transient → 200 + envelope shape preserved +
    ``vector_rank: null`` everywhere.
  - Degraded coverage  → same as above, via the coverage cache
    short-circuit.
  - Permanent 500      → HTTP 500 with fixed body; upstream error
    detail does NOT leak.
  - Happy hybrid       → deferred to ``test_search_hybrid_real_pg``
    (needs pgvector — not runnable on sqlite).

Envelope-no-expansion regression: the happy / degraded / empty
responses all expose exactly ``{items, total_hits, latency_ms}``
at the top level. A future attempt to add ``degraded: bool`` to
the body (OI5 = B) would break these assertions — that's the
regression guard.
"""

from __future__ import annotations

import datetime as dt
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.embedding_client import (
    EmbeddingResult,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from api.read import search_service
from api.tables import metadata, reports_table, sources_table

pytestmark = pytest.mark.asyncio


# Full envelope key set locked by PR #17 D9 + PR #19b §0 invariant 1.
_ENVELOPE_KEYS = {"items", "total_hits", "latency_ms"}
_HIT_KEYS = {"report", "fts_rank", "vector_rank"}


@pytest.fixture(autouse=True)
def _reset_coverage_cache_between_tests() -> None:
    search_service.reset_coverage_cache()


@pytest_asyncio.fixture
async def hybrid_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def hybrid_client(
    hybrid_engine: AsyncEngine,
    session_store,
    fake_redis,
) -> AsyncIterator[AsyncClient]:
    """AsyncClient + FastAPI app wired to sqlite + fake Redis.

    Tests set ``app.dependency_overrides[get_embedding_client]`` per
    case to inject a stub client (returning vector, raising transient,
    raising permanent).
    """
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app
    from api.read.search_cache import get_redis_for_search_cache

    sessionmaker = async_sessionmaker(hybrid_engine, expire_on_commit=False)

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


async def _cookie(make_session_cookie, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


async def _seed_source(engine: AsyncEngine) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name="Vendor", type="vendor")
            .returning(sources_table.c.id)
        )
        source_id = row.scalar_one()
        await s.commit()
        return source_id


async def _seed_report(
    engine: AsyncEngine,
    *,
    report_id: int,
    title: str,
    summary: str,
    source_id: int,
    published: dt.date,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(
            sa.insert(reports_table).values(
                id=report_id,
                title=title,
                summary=summary,
                url=f"https://ex.test/{report_id}",
                url_canonical=f"https://ex.test/{report_id}",
                sha256_title=f"sha-{report_id}",
                source_id=source_id,
                published=published,
                tlp="WHITE",
            )
        )
        await s.commit()


def _install_hybrid_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fts_rows: list[dict],
    fts_total: int | None = None,
    vec_rows: list[dict],
    coverage_ratio: float,
) -> MagicMock:
    """Force the dispatcher onto the hybrid branch on sqlite.

    Returns a ``MagicMock`` spy attached to ``_run_vector_query`` so
    tests can assert on call count (e.g. C3 dialect guard expects
    zero calls when hybrid is not reachable).
    """
    total = fts_total if fts_total is not None else len(fts_rows)

    async def _fake_run_fts(
        session, *, q, date_from, date_to, limit
    ):  # noqa: ANN001
        return list(fts_rows), total

    vec_spy = MagicMock()

    async def _fake_run_vec(
        session, *, q_vec, date_from, date_to, limit_k
    ):
        vec_spy(q=q_vec, limit_k=limit_k)
        return list(vec_rows)

    async def _fake_coverage(session, *, refresh_seconds):
        return coverage_ratio

    monkeypatch.setattr(search_service, "_dialect_is_postgres", lambda s: True)
    monkeypatch.setattr(search_service, "_run_fts", _fake_run_fts)
    monkeypatch.setattr(search_service, "_run_vector_query", _fake_run_vec)
    monkeypatch.setattr(
        search_service, "_get_coverage_ratio", _fake_coverage
    )
    return vec_spy


def _override_embedding_client(client_stub) -> None:
    """Swap ``get_embedding_client`` for this test's stub."""
    from api.deps import get_embedding_client
    from api.main import app

    app.dependency_overrides[get_embedding_client] = lambda: client_stub


def _row(
    *, rid: int, title: str = "report", fts_rank: float = 0.0,
    published: dt.date = dt.date(2026, 1, 1),
) -> dict:
    return {
        "id": rid,
        "title": title,
        "url": f"https://ex.test/{rid}",
        "url_canonical": f"https://ex.test/{rid}",
        "published": published,
        "source_id": 1,
        "source_name": "Vendor",
        "lang": "en",
        "tlp": "WHITE",
        "fts_rank": fts_rank,
    }


class _StubClient:
    """Minimal ``LlmProxyEmbeddingClient`` stub — result OR exception."""

    def __init__(
        self,
        *,
        result: EmbeddingResult | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, model=None):
        self.calls.append(list(texts))
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        return self.result


def _ok_embed_result() -> EmbeddingResult:
    return EmbeddingResult(
        vectors=[[0.1] * 1536],
        model_returned="text-embedding-3-small",
        cache_hit=False,
        upstream_latency_ms=7,
    )


# ===========================================================================
# C1 — Envelope shape invariant
# ===========================================================================


class TestEnvelopeShapeInvariantC1:
    async def test_empty_response_keys_exact_match(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        """sqlite → D10 empty envelope; top-level keys locked to PR #17 set."""
        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "nomatch"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == _ENVELOPE_KEYS
        assert body["items"] == []
        assert body["total_hits"] == 0

    async def test_degraded_transient_envelope_keys_exact_match(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Degraded-transient response is shape-identical to PR #17 FTS-only."""
        _install_hybrid_seams(
            monkeypatch,
            fts_rows=[_row(rid=100, title="report-100", fts_rank=0.5)],
            fts_total=1,
            vec_rows=[],
            coverage_ratio=0.95,
        )
        stub = _StubClient(
            exc=TransientEmbeddingError(
                upstream_status=503, reason="upstream_503"
            )
        )
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Top-level key set identical to PR #17 FTS-only envelope —
        # no new ``degraded`` / ``degraded_reason`` at body level.
        assert set(body.keys()) == _ENVELOPE_KEYS
        assert "degraded" not in body
        assert "degraded_reason" not in body
        assert len(body["items"]) == 1
        # Per-hit shape also unchanged.
        assert set(body["items"][0].keys()) == _HIT_KEYS
        assert body["items"][0]["vector_rank"] is None

    async def test_degraded_coverage_envelope_keys_exact_match(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Coverage-gate degraded response — same envelope shape."""
        vec_spy = _install_hybrid_seams(
            monkeypatch,
            fts_rows=[_row(rid=100, title="report-100", fts_rank=0.5)],
            fts_total=1,
            vec_rows=[],
            coverage_ratio=0.1,  # below default threshold 0.5
        )
        stub = _StubClient(result=_ok_embed_result())
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == _ENVELOPE_KEYS
        assert "degraded" not in body
        # Coverage-gate degraded: embedder NEVER called, vector query
        # NEVER run — the short-circuit is structural.
        assert stub.calls == []
        assert vec_spy.call_count == 0

    async def test_hybrid_success_envelope_keys_exact_match(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hybrid success keeps the same envelope keys; only vector_rank flips."""
        _install_hybrid_seams(
            monkeypatch,
            fts_rows=[_row(rid=100, title="report-100", fts_rank=0.5)],
            vec_rows=[_row(rid=100, title="report-100")],
            coverage_ratio=0.95,
        )
        stub = _StubClient(result=_ok_embed_result())
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == _ENVELOPE_KEYS
        assert len(body["items"]) == 1
        assert set(body["items"][0].keys()) == _HIT_KEYS
        assert isinstance(body["items"][0]["vector_rank"], int)
        assert body["items"][0]["vector_rank"] == 1


# ===========================================================================
# C3 — Dialect guard (sqlite never runs the vector leg)
# ===========================================================================


class TestDialectGuardC3:
    async def test_sqlite_never_calls_vector_query(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        """Real sqlite dialect + client present → hybrid unreachable.

        The spy asserts ``_run_vector_query`` was not called. This is
        the structural guard behind "non-PG = FTS-only" — stronger
        than an assertion on the response body alone because it
        proves the vector query compile path never ran.
        """
        from api.read import search_service as ss

        vec_spy = MagicMock()
        original_fn = ss._run_vector_query

        async def _spy_wrapper(*args, **kwargs):
            vec_spy(*args, **kwargs)
            return await original_fn(*args, **kwargs)

        # Monkey-patch via app-scope (not pytest's monkeypatch because
        # the fixture has already yielded; apply directly).
        ss._run_vector_query = _spy_wrapper  # type: ignore[assignment]
        try:
            stub = _StubClient(result=_ok_embed_result())
            _override_embedding_client(stub)

            cookie = await _cookie(make_session_cookie)
            resp = await hybrid_client.get(
                "/api/v1/search",
                params={"q": "x"},
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200
            assert vec_spy.call_count == 0
            # Embedder also not called — the ``hybrid_reachable`` gate
            # fails before any hybrid work begins.
            assert stub.calls == []
        finally:
            ss._run_vector_query = original_fn  # type: ignore[assignment]


# ===========================================================================
# C4 — 4-branch pin at the HTTP layer
# ===========================================================================


class TestC4DegradedTransient:
    async def test_transient_embedding_error_http_returns_200_fts_only(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Transient → HTTP 200, items from FTS, all vector_rank null."""
        _install_hybrid_seams(
            monkeypatch,
            fts_rows=[
                _row(rid=100, title="hit-100", fts_rank=0.9),
                _row(rid=200, title="hit-200", fts_rank=0.4),
            ],
            fts_total=2,
            vec_rows=[_row(rid=300, title="hit-300")],  # ignored on transient
            coverage_ratio=0.95,
        )
        stub = _StubClient(
            exc=TransientEmbeddingError(
                upstream_status=504, reason="upstream_504"
            )
        )
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = [item["report"]["id"] for item in body["items"]]
        assert ids == [100, 200]
        assert all(item["vector_rank"] is None for item in body["items"])
        # total_hits uses the FTS-only semantic on degraded (no union).
        assert body["total_hits"] == 2


class TestC4DegradedCoverage:
    async def test_coverage_below_threshold_http_returns_200_fts_only(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Coverage-low → HTTP 200, FTS-only body, embedder never called."""
        vec_spy = _install_hybrid_seams(
            monkeypatch,
            fts_rows=[_row(rid=100, title="hit-100", fts_rank=0.5)],
            fts_total=1,
            vec_rows=[],
            coverage_ratio=0.2,
        )
        stub = _StubClient(result=_ok_embed_result())
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"][0]["vector_rank"] is None
        # Structural short-circuit: neither embedder nor vector query
        # ran. This is what keeps coverage-low cheaper than happy path.
        assert stub.calls == []
        assert vec_spy.call_count == 0


class TestC4PermanentReturnsHttp500:
    async def test_permanent_embedding_error_maps_to_http_500(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Permanent → HTTP 500 with fixed body; no upstream detail leak."""
        _install_hybrid_seams(
            monkeypatch,
            fts_rows=[_row(rid=100, title="hit-100", fts_rank=0.9)],
            fts_total=1,
            vec_rows=[],
            coverage_ratio=0.95,
        )
        stub = _StubClient(
            exc=PermanentEmbeddingError(
                upstream_status=422,
                reason="invalid_input_DO_NOT_LEAK_THIS",
            )
        )
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 500
        body = resp.json()
        assert body == {"detail": "search temporarily unavailable"}
        # Reason string from the raised error MUST NOT appear in the
        # response — upstream detail-leak guard.
        assert "invalid_input_DO_NOT_LEAK_THIS" not in resp.text


# ===========================================================================
# OI5 = A — envelope body never grows a ``degraded`` field
# ===========================================================================


class TestEnvelopeDoesNotGrowDegradedField:
    """OI5 = A lock — ``degraded`` is log-only, never a body field.

    Group B tests assert this on the SearchServiceResult payload; this
    test asserts it on the wire representation the FE actually parses.
    """

    async def test_transient_does_not_inject_degraded_field(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_hybrid_seams(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.5)],
            fts_total=1,
            vec_rows=[],
            coverage_ratio=0.95,
        )
        stub = _StubClient(
            exc=TransientEmbeddingError(
                upstream_status=429, reason="rate_limited"
            )
        )
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        for forbidden in ("degraded", "degraded_reason", "fallback"):
            assert forbidden not in body, (
                f"{forbidden!r} leaked into search envelope — OI5 = A "
                "locked observability to log fields only"
            )

    async def test_coverage_gate_does_not_inject_degraded_field(
        self,
        hybrid_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_hybrid_seams(
            monkeypatch,
            fts_rows=[_row(rid=100, fts_rank=0.5)],
            fts_total=1,
            vec_rows=[],
            coverage_ratio=0.2,
        )
        stub = _StubClient(result=_ok_embed_result())
        _override_embedding_client(stub)

        cookie = await _cookie(make_session_cookie)
        resp = await hybrid_client.get(
            "/api/v1/search",
            params={"q": "x"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        for forbidden in ("degraded", "degraded_reason", "fallback"):
            assert forbidden not in body
