"""Unit tests for api.embedding_writer — PR #19a Group B (api-side).

Mirror of ``services/worker/tests/unit/test_embedding_writer.py``.
The two writers have identical contract semantics; the duplication
is intentional per plan §9.1 (service-local, not shared).

Layout:

  - TestComposeEmbedText: OI1 text composition rule (3 cases).
  - TestSerializeVector: pgvector text literal shape.
  - TestSqliteSkip: dialect guard — client never invoked on sqlite
    (criterion C2 dialect guard).
  - TestTransientFailures: all 4 transient classes become
    SKIPPED_TRANSIENT with no DB write attempt (criterion C4).
  - TestPermanentPropagation: 422 + dimension mismatch propagate
    (criterion C4 loud branch).
  - TestPgUpdate: when dialect reports postgresql, the session
    captures the pinned SQL text (criterion C2 text-match)
    and rowcount semantics drive EMBEDDED vs ALREADY_POPULATED
    (criterion C3).

sqlite-memory is the primary dialect under unit tests. To exercise
the PostgreSQL-only UPDATE path without a live PG connection, we use
a minimal ``AsyncSession`` stand-in whose ``get_bind().dialect.name``
reports ``"postgresql"`` and whose ``execute()`` returns a
pre-programmed ``rowcount``. This is the same pattern used by PR #18
unit tests to simulate httpx response codes without a live service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy as sa

from api.embedding_client import (
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from api.embedding_writer import (
    EmbedReportResult,
    EmbedWriteOutcome,
    compose_embed_text,
    embed_report,
)


SAMPLE_TITLE = "Lazarus targets SK crypto exchanges"
SAMPLE_SUMMARY = "APT-38 subgroup phishing operations observed in 2026 Q1."
DIM = 1536


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class _StubDialect:
    name: str


@dataclass
class _StubBind:
    dialect: _StubDialect


class _StubExecResult:
    """Minimal stand-in for ``sqlalchemy.engine.Result``."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _StubSession:
    """Minimal AsyncSession stand-in for dialect guard + exec capture.

    The real ``AsyncSession`` machinery is out of scope for unit
    tests — this shim covers the two attributes ``embed_report``
    reaches for: ``get_bind()`` and ``execute()``.
    """

    def __init__(
        self,
        *,
        dialect_name: str,
        rowcounts: list[int] | None = None,
    ) -> None:
        self._bind = _StubBind(dialect=_StubDialect(name=dialect_name))
        self._rowcounts = list(rowcounts) if rowcounts is not None else [1]
        self.captured_statements: list[tuple[str, dict[str, Any]]] = []

    def get_bind(self) -> _StubBind:
        return self._bind

    async def execute(
        self,
        statement: sa.TextClause,
        params: dict[str, Any] | None = None,
    ) -> _StubExecResult:
        self.captured_statements.append((str(statement), dict(params or {})))
        if not self._rowcounts:
            return _StubExecResult(rowcount=1)
        return _StubExecResult(rowcount=self._rowcounts.pop(0))


def _mock_client(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _build_client_with_response(
    *,
    status: int = 200,
    body: dict[str, Any] | None = None,
    raise_on_send: Exception | None = None,
    retry_after: str | None = None,
) -> LlmProxyEmbeddingClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        if raise_on_send is not None:
            raise raise_on_send
        headers: dict[str, str] = {}
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        payload = body or {
            "provider": "mock",
            "model": "text-embedding-3-small",
            "dimensions": DIM,
            "items": [{"index": 0, "embedding": [0.5] * DIM}],
            "usage": {"prompt_tokens": 3, "total_tokens": 3},
            "latency_ms": 5,
            "cache_hit": False,
        }
        return httpx.Response(status, headers=headers, json=payload)

    return LlmProxyEmbeddingClient(
        base_url="http://llm-proxy.test",
        internal_token="t",
        client=_mock_client(handler),
        timeout_seconds=5.0,
    )


# ---------------------------------------------------------------------------
# TestComposeEmbedText — OI1 rule
# ---------------------------------------------------------------------------


class TestComposeEmbedText:
    def test_summary_present(self) -> None:
        assert compose_embed_text(SAMPLE_TITLE, SAMPLE_SUMMARY) == (
            f"{SAMPLE_TITLE}\n\n{SAMPLE_SUMMARY}"
        )

    def test_summary_none(self) -> None:
        assert compose_embed_text(SAMPLE_TITLE, None) == SAMPLE_TITLE

    def test_summary_whitespace_only(self) -> None:
        # Space, tab, newline all collapse to title-only.
        assert compose_embed_text(SAMPLE_TITLE, "") == SAMPLE_TITLE
        assert compose_embed_text(SAMPLE_TITLE, "   ") == SAMPLE_TITLE
        assert compose_embed_text(SAMPLE_TITLE, "\n\t ") == SAMPLE_TITLE


# ---------------------------------------------------------------------------
# TestSqliteSkip
# ---------------------------------------------------------------------------


class TestSqliteSkip:
    async def test_sqlite_dialect_returns_skipped_without_http_call(self) -> None:
        # If the client were invoked, this handler would panic — it
        # asserts the test DID NOT hit the transport layer.
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("client must not be invoked on sqlite path")

        client = LlmProxyEmbeddingClient(
            base_url="http://llm-proxy.test",
            internal_token="t",
            client=_mock_client(handler),
            timeout_seconds=5.0,
        )
        session = _StubSession(dialect_name="sqlite")

        result = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=42,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert isinstance(result, EmbedReportResult)
        assert result.outcome is EmbedWriteOutcome.SKIPPED_SQLITE
        assert result.rowcount == 0
        assert result.cache_hit is None
        assert result.upstream_latency_ms is None
        # No UPDATE issued on sqlite.
        assert session.captured_statements == []


# ---------------------------------------------------------------------------
# TestTransientFailures
# ---------------------------------------------------------------------------


class TestTransientFailures:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    async def test_status_class_is_transient(self, status: int) -> None:
        client = _build_client_with_response(
            status=status,
            body={"detail": "upstream failure"},
            retry_after="5" if status == 429 else None,
        )
        session = _StubSession(dialect_name="postgresql")

        result = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=1,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert result.outcome is EmbedWriteOutcome.SKIPPED_TRANSIENT
        # No UPDATE attempted when client raises Transient.
        assert session.captured_statements == []

    async def test_timeout_is_transient(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("deadline hit", request=request)

        client = LlmProxyEmbeddingClient(
            base_url="http://llm-proxy.test",
            internal_token="t",
            client=_mock_client(handler),
            timeout_seconds=5.0,
        )
        session = _StubSession(dialect_name="postgresql")

        result = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=1,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert result.outcome is EmbedWriteOutcome.SKIPPED_TRANSIENT
        assert session.captured_statements == []


# ---------------------------------------------------------------------------
# TestPermanentPropagation
# ---------------------------------------------------------------------------


class TestPermanentPropagation:
    async def test_422_propagates(self) -> None:
        client = _build_client_with_response(
            status=422,
            body={"detail": "empty text", "retryable": False},
        )
        session = _StubSession(dialect_name="postgresql")

        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await embed_report(
                session,  # type: ignore[arg-type]
                report_id=1,
                title=SAMPLE_TITLE,
                summary=SAMPLE_SUMMARY,
                client=client,
            )

        assert exc_info.value.upstream_status == 422
        assert exc_info.value.reason == "invalid_input"
        # No UPDATE attempted when client raises Permanent.
        assert session.captured_statements == []

    async def test_dimension_mismatch_propagates(self) -> None:
        client = _build_client_with_response(
            status=200,
            body={
                "provider": "mock",
                "model": "text-embedding-3-small",
                "dimensions": 512,  # mismatch
                "items": [{"index": 0, "embedding": [0.5] * 512}],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
                "latency_ms": 5,
                "cache_hit": False,
            },
        )
        session = _StubSession(dialect_name="postgresql")

        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await embed_report(
                session,  # type: ignore[arg-type]
                report_id=1,
                title=SAMPLE_TITLE,
                summary=SAMPLE_SUMMARY,
                client=client,
            )

        assert "dimension_mismatch" in exc_info.value.reason
        assert session.captured_statements == []


# ---------------------------------------------------------------------------
# TestPgUpdate — criterion C2 text-match + C3 rowcount pins
# ---------------------------------------------------------------------------


class TestPgUpdate:
    async def test_happy_path_rowcount_1_returns_embedded(self) -> None:
        client = _build_client_with_response(status=200)
        session = _StubSession(dialect_name="postgresql", rowcounts=[1])

        result = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=999,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert result.outcome is EmbedWriteOutcome.EMBEDDED
        assert result.rowcount == 1
        assert result.cache_hit is False
        assert result.upstream_latency_ms is not None
        assert result.upstream_latency_ms >= 0

    async def test_rowcount_0_returns_already_populated(self) -> None:
        client = _build_client_with_response(status=200)
        session = _StubSession(dialect_name="postgresql", rowcounts=[0])

        result = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=999,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert result.outcome is EmbedWriteOutcome.ALREADY_POPULATED
        assert result.rowcount == 0

    async def test_update_sql_text_is_pinned(self) -> None:
        """C2 assertion: the SQL fragment MUST contain
        ``WHERE id = :id AND embedding IS NULL`` and
        ``CAST(:vec AS vector)``. Any drift from this exact shape
        would either defeat the null-guard or change the type
        coercion strategy — both are load-bearing.
        """
        client = _build_client_with_response(status=200)
        session = _StubSession(dialect_name="postgresql", rowcounts=[1])

        await embed_report(
            session,  # type: ignore[arg-type]
            report_id=999,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert len(session.captured_statements) == 1
        sql_text, params = session.captured_statements[0]
        assert "UPDATE reports SET embedding = CAST(:vec AS vector)" in sql_text
        assert "WHERE id = :id AND embedding IS NULL" in sql_text
        assert params["id"] == 999
        # Vector is serialized as the pgvector text literal.
        assert params["vec"].startswith("[")
        assert params["vec"].endswith("]")
        # 1536 floats comma-separated — quick sanity count.
        assert params["vec"].count(",") == DIM - 1

    async def test_rerun_sequence_embedded_then_already_populated(self) -> None:
        """C3 end-to-end: first call lands EMBEDDED; a later call on
        the same ``report_id`` with a different vector hits the null-
        guard and lands ALREADY_POPULATED — no overwrite."""
        client = _build_client_with_response(status=200)
        # Two UPDATE calls: first rowcount=1 (fresh), second rowcount=0
        # (null-guard already satisfied by prior call).
        session = _StubSession(dialect_name="postgresql", rowcounts=[1, 0])

        first = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=999,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )
        second = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=999,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert first.outcome is EmbedWriteOutcome.EMBEDDED
        assert second.outcome is EmbedWriteOutcome.ALREADY_POPULATED
        assert len(session.captured_statements) == 2

    async def test_cache_hit_propagates_into_result(self) -> None:
        client = _build_client_with_response(
            status=200,
            body={
                "provider": "mock",
                "model": "text-embedding-3-small",
                "dimensions": DIM,
                "items": [{"index": 0, "embedding": [0.5] * DIM}],
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
                "latency_ms": 1,
                "cache_hit": True,
            },
        )
        session = _StubSession(dialect_name="postgresql", rowcounts=[1])

        result = await embed_report(
            session,  # type: ignore[arg-type]
            report_id=999,
            title=SAMPLE_TITLE,
            summary=SAMPLE_SUMMARY,
            client=client,
        )

        assert result.outcome is EmbedWriteOutcome.EMBEDDED
        assert result.cache_hit is True
