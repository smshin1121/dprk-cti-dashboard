"""Integration tests for embed-on-promote wiring in the review route.

PR #19a Group B criteria C1 + C4 verification for the api promote path:

  - **C1 (no signature drift / existing tests unchanged):** the default
    dependency (``get_embedding_client`` returns ``None`` unless both
    ``LLM_PROXY_URL`` and ``LLM_PROXY_INTERNAL_TOKEN`` are configured)
    preserves pre-PR-#19a promote semantics. Every existing
    ``test_review_route.py`` test passes unchanged — verified by the
    ``allowed_roles_reach_handler`` and ``TestHappyPath.test_approve``
    tests in that file (they ran green with this PR's router edits).

  - **C4 (enrichment never blocks promote):**
    - With a mock client injected: the promote route returns 200,
      reports row is inserted, dialect guard inside ``embed_report``
      short-circuits (sqlite), no HTTP is made, no exception surfaces.
    - With ``embed_report`` monkeypatched to raise
      ``PermanentEmbeddingError``: the promote route STILL returns 200,
      report row persists — the router's try/except inside
      ``async with session.begin()`` catches the raise so the
      transaction commits normally.
    - With ``embed_report`` monkeypatched to return
      ``SKIPPED_TRANSIENT`` (the contract for how transient failures
      present to the caller): promote returns 200, row persists.

The sqlite test schema omits the pgvector ``embedding`` column so
these tests verify only promote-level semantics (200 status code,
staging→reports row persisted). PG-only UPDATE mechanics are covered
by ``test_embedding_writer.py``.
"""

from __future__ import annotations

import datetime as dt
from typing import AsyncIterator

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

from api.deps import get_embedding_client
from api.embedding_client import (
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
)
from api.embedding_writer import EmbedReportResult, EmbedWriteOutcome
from api.routers import reports as reports_router
from api.tables import metadata, reports_table, staging_table


REVIEW_URL = "/api/v1/reports/review/{staging_id}"


# ---------------------------------------------------------------------------
# Fixtures — real sqlite engine + ASGI client with overrides
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def review_client(
    real_engine: AsyncEngine, session_store, fake_redis
) -> AsyncIterator[AsyncClient]:
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    sessionmaker = async_sessionmaker(real_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def _seed_pending_staging(
    engine: AsyncEngine,
    *,
    title: str = "Lazarus targets SK",
    summary: str | None = "APT-38 phishing operations in 2026 Q1",
) -> int:
    """Seed a pending staging row including ``summary`` so the
    promote path has non-null text for the OI1 composition rule.
    """
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(staging_table)
            .values(
                url_canonical=f"http://e.com/embed-{title.replace(' ', '-')}",
                url=f"http://e.com/embed-{title.replace(' ', '-')}",
                title=title,
                summary=summary,
                published=dt.datetime(2026, 4, 17, tzinfo=dt.timezone.utc),
                status="pending",
            )
            .returning(staging_table.c.id)
        )
        staging_id = result.scalar_one()
        await s.commit()
        return staging_id


def _build_mock_embedding_client() -> LlmProxyEmbeddingClient:
    """A client whose transport would succeed if it were called.

    On sqlite, ``embed_report``'s dialect guard short-circuits before
    the client is invoked, so this client's mock transport never
    actually fires — it only exists so the dependency returns a
    non-None object and the router enters the embed branch.
    """
    import httpx

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            "httpx transport must not be hit on sqlite — "
            "dialect guard should short-circuit first"
        )

    return LlmProxyEmbeddingClient(
        base_url="http://llm-proxy.test",
        internal_token="test-token",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_seconds=5.0,
    )


async def _count_reports(engine: AsyncEngine) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.select(sa.func.count()).select_from(reports_table)
        )
        return result.scalar_one()


# ---------------------------------------------------------------------------
# C1 default dependency — no client configured
# ---------------------------------------------------------------------------


class TestDefaultNoClient:
    async def test_promote_succeeds_when_embedding_dep_returns_none(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Override the dep to return None (simulating
        ``LLM_PROXY_URL`` unset). Promote returns 200; reports row
        exists. This is the default shape when the feature is
        not configured — matches pre-PR-#19a behavior.
        """
        from api.main import app

        app.dependency_overrides[get_embedding_client] = lambda: None

        staging_id = await _seed_pending_staging(real_engine)
        cookie = await make_session_cookie(roles=["analyst"])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve", "notes": "no client path"},
        )
        assert resp.status_code == 200, resp.text
        assert await _count_reports(real_engine) == 1


# ---------------------------------------------------------------------------
# C4 sqlite path — live client injected, dialect guard short-circuits
# ---------------------------------------------------------------------------


class TestLiveClientSqliteShortCircuit:
    async def test_promote_succeeds_with_client_on_sqlite(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Inject a non-None mock client. On sqlite, ``embed_report``
        returns SKIPPED_SQLITE before the client is called. Promote
        returns 200 and the reports row is durable.
        """
        from api.main import app

        mock = _build_mock_embedding_client()
        app.dependency_overrides[get_embedding_client] = lambda: mock

        staging_id = await _seed_pending_staging(
            real_engine, title="Sqlite live-client test"
        )
        cookie = await make_session_cookie(roles=["analyst"])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve", "notes": "live client"},
        )
        assert resp.status_code == 200, resp.text
        assert await _count_reports(real_engine) == 1


# ---------------------------------------------------------------------------
# C4 permanent error — caught in router, promote still succeeds
# ---------------------------------------------------------------------------


class TestPermanentEmbeddingDoesNotBlockPromote:
    async def test_422_permanent_error_is_swallowed_promote_returns_200(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Monkeypatch ``embed_report`` to raise
        ``PermanentEmbeddingError``. The router must catch it, the
        ``async with session.begin()`` block must commit normally,
        and the reports row must persist.

        Simulates the llm-proxy contract drift / 422 case — the
        analyst approve UX MUST NOT regress because of it.
        """
        from api.main import app

        async def raising_embed_report(
            session,  # noqa: ANN001
            *,
            report_id: int,
            title: str,
            summary: str | None,
            client,  # noqa: ANN001
        ):
            raise PermanentEmbeddingError(
                upstream_status=422,
                reason="invalid_input",
            )

        monkeypatch.setattr(reports_router, "embed_report", raising_embed_report)

        mock = _build_mock_embedding_client()
        app.dependency_overrides[get_embedding_client] = lambda: mock

        staging_id = await _seed_pending_staging(
            real_engine, title="Permanent 422 test"
        )
        cookie = await make_session_cookie(roles=["analyst"])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve", "notes": "permanent error test"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "promoted"
        assert body["staging_id"] == staging_id
        # Report row exists — transaction committed despite embed raise.
        assert await _count_reports(real_engine) == 1

    async def test_dimension_mismatch_permanent_error_is_swallowed(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Second permanent-error flavor — dimension mismatch.

        This is a contract-drift signal (llm-proxy returning something
        other than 1536-dim). Must still not block the promote."""
        from api.main import app

        async def raising_embed_report(
            session,  # noqa: ANN001
            *,
            report_id: int,
            title: str,
            summary: str | None,
            client,  # noqa: ANN001
        ):
            raise PermanentEmbeddingError(
                upstream_status=200,
                reason="dimension_mismatch_512",
            )

        monkeypatch.setattr(reports_router, "embed_report", raising_embed_report)

        mock = _build_mock_embedding_client()
        app.dependency_overrides[get_embedding_client] = lambda: mock

        staging_id = await _seed_pending_staging(
            real_engine, title="Dimension mismatch test"
        )
        cookie = await make_session_cookie(roles=["analyst"])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 200, resp.text
        assert await _count_reports(real_engine) == 1


# ---------------------------------------------------------------------------
# C4 transient error — defensive guard; embed_report returns SKIPPED
# ---------------------------------------------------------------------------


class TestTransientEmbeddingIsHandledInWriter:
    async def test_transient_returns_skipped_promote_succeeds(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Transient failures are normally swallowed inside
        ``embed_report`` and surface as ``SKIPPED_TRANSIENT`` — this
        test pins that contract by replacing ``embed_report`` with one
        that returns the skip outcome directly, and asserts the
        promote flow completes unchanged.
        """
        from api.main import app

        calls: list[int] = []

        async def skipping_embed_report(
            session,  # noqa: ANN001
            *,
            report_id: int,
            title: str,
            summary: str | None,
            client,  # noqa: ANN001
        ) -> EmbedReportResult:
            calls.append(report_id)
            return EmbedReportResult(
                outcome=EmbedWriteOutcome.SKIPPED_TRANSIENT,
                rowcount=0,
                cache_hit=None,
                upstream_latency_ms=None,
            )

        monkeypatch.setattr(reports_router, "embed_report", skipping_embed_report)

        mock = _build_mock_embedding_client()
        app.dependency_overrides[get_embedding_client] = lambda: mock

        staging_id = await _seed_pending_staging(
            real_engine, title="Transient skip test"
        )
        cookie = await make_session_cookie(roles=["analyst"])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 200, resp.text
        assert await _count_reports(real_engine) == 1
        # Exactly one promote -> exactly one embed call.
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# C1 signal — reject path never reaches embed_report
# ---------------------------------------------------------------------------


class TestRejectPathHasNoEmbed:
    async def test_reject_does_not_invoke_embed_report(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reject path has no reports row to embed. The trip-wire
        embed_report MUST NOT be called — if this fails, someone
        accidentally added an embed dispatch to the reject branch."""
        from api.main import app

        async def tripwire_embed_report(
            session,  # noqa: ANN001
            *,
            report_id: int,
            title: str,
            summary: str | None,
            client,  # noqa: ANN001
        ):
            raise AssertionError(
                "embed_report must not be called on reject path"
            )

        monkeypatch.setattr(reports_router, "embed_report", tripwire_embed_report)

        mock = _build_mock_embedding_client()
        app.dependency_overrides[get_embedding_client] = lambda: mock

        staging_id = await _seed_pending_staging(
            real_engine, title="Reject tripwire test"
        )
        cookie = await make_session_cookie(roles=["analyst"])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={
                "decision": "reject",
                "decision_reason": "duplicate",
            },
        )
        assert resp.status_code == 200, resp.text
        # No report row for rejected staging.
        assert await _count_reports(real_engine) == 0
