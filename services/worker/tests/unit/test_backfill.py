"""Unit tests for worker.bootstrap.backfill — PR #19a Group C.

Verifies all four Codex Group C review criteria:

  1. **embedding IS NULL-only selection** — SQL text-match assertion
     on the SELECT statement captured by the stub session.
  2. **sleep_seconds=2 default + Retry-After honor** — constructor
     default pinned, and 429 handler delegates to an injected
     ``sleep_func`` that records durations.
  3. **Bounded batch** — batch_size > 16 raises ValueError; a
     batch_size of 16 split across a 50-row corpus produces exactly
     4 llm-proxy calls (16, 16, 16, 2).
  4. **Rerun idempotency + partial transient resume** — a run where
     row counts are pre-programmed to hit mixed success/transient/
     permanent across batches lands correct counts in
     ``BackfillCounts`` and commits only the successful batches.

sqlite cannot represent pgvector or ``embedding IS NULL`` in a
portable way, so these tests use a stub AsyncSession that answers
the candidate SELECT with a fixed row list and captures UPDATE
calls with pre-programmed rowcounts. Same pattern as
``test_embedding_writer.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy as sa

from worker.bootstrap.backfill import (
    DEFAULT_SLEEP_SECONDS,
    MAX_BATCH_SIZE,
    MAX_RETRY_AFTER_SECONDS,
    BackfillCounts,
    run_embedding_backfill,
)
from worker.bootstrap.embedding_client import (
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)


DIM = 1536


# ---------------------------------------------------------------------------
# Stub row + session
# ---------------------------------------------------------------------------


@dataclass
class _StubRow:
    id: int
    title: str
    summary: str | None


class _StubSelectResult:
    """Emulates the ``.all()`` surface of
    ``sqlalchemy.engine.Result`` for SELECT."""

    def __init__(self, rows: list[_StubRow]) -> None:
        self._rows = rows

    def all(self) -> list[_StubRow]:
        return list(self._rows)


class _StubExecResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _StubSession:
    """Minimal AsyncSession stand-in for backfill tests.

    - ``execute(SELECT...)`` returns the pre-programmed row list.
    - ``execute(UPDATE...)`` pops the next pre-programmed rowcount.
    - ``commit()`` is recorded so tests can assert commit cadence.
    """

    def __init__(
        self,
        *,
        candidates: list[_StubRow],
        update_rowcounts: list[int] | None = None,
    ) -> None:
        self._candidates = list(candidates)
        self._update_rowcounts = list(update_rowcounts or [])
        self.executed_sql: list[str] = []
        self.executed_params: list[dict[str, Any]] = []
        self.commits: int = 0
        self.rollbacks: int = 0

    async def execute(
        self,
        statement: sa.TextClause,
        params: dict[str, Any] | None = None,
    ) -> _StubSelectResult | _StubExecResult:
        text = str(statement)
        self.executed_sql.append(text)
        self.executed_params.append(dict(params or {}))
        if text.lstrip().upper().startswith("SELECT"):
            return _StubSelectResult(self._candidates)
        # UPDATE branch — pop rowcount in order. Default to 1 if the
        # test forgot to preset (matches happy path).
        if self._update_rowcounts:
            return _StubExecResult(self._update_rowcounts.pop(0))
        return _StubExecResult(rowcount=1)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _mock_client_with_handler(handler) -> LlmProxyEmbeddingClient:  # noqa: ANN001
    return LlmProxyEmbeddingClient(
        base_url="http://llm-proxy.test",
        internal_token="t",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_seconds=5.0,
    )


def _success_response_for(n: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "provider": "mock",
            "model": "text-embedding-3-small",
            "dimensions": DIM,
            "items": [
                {"index": i, "embedding": [float(i)] * DIM}
                for i in range(n)
            ],
            "usage": {"prompt_tokens": 3 * n, "total_tokens": 3 * n},
            "latency_ms": 1,
            "cache_hit": False,
        },
    )


def _all_success_client() -> LlmProxyEmbeddingClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = request.content.decode("utf-8")
        # Count occurrences of "text" JSON keys cheaply — simpler
        # than parsing; we just need the number of input texts.
        import json

        body = json.loads(payload)
        n = len(body["texts"])
        return _success_response_for(n)

    return _mock_client_with_handler(handler)


# Spy sleep function — records durations without actually sleeping.
class _RecorderSleep:
    def __init__(self) -> None:
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)


# Rows helper — produce ``n`` stub rows.
def _rows(n: int, *, with_summary: bool = True) -> list[_StubRow]:
    return [
        _StubRow(
            id=100 + i,
            title=f"Title {i}",
            summary=f"Summary {i}" if with_summary else None,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Criterion 1 — embedding IS NULL-only selection
# ---------------------------------------------------------------------------


class TestCandidateSelection:
    async def test_select_sql_filters_embedding_is_null(self) -> None:
        session = _StubSession(candidates=_rows(5))
        sleep = _RecorderSleep()

        await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_all_success_client(),
            batch_size=16,
            sleep_seconds=0,
            sleep_func=sleep,
        )

        # First execute call is the candidate SELECT.
        assert len(session.executed_sql) >= 1
        select_sql = session.executed_sql[0]
        # Text-match pins: pick-only-NULL and keyset order.
        assert "WHERE embedding IS NULL" in select_sql
        assert "ORDER BY published ASC, id ASC" in select_sql

    async def test_select_with_limit_appends_limit_clause(self) -> None:
        session = _StubSession(candidates=_rows(5))
        sleep = _RecorderSleep()

        await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_all_success_client(),
            batch_size=16,
            limit=42,
            sleep_seconds=0,
            sleep_func=sleep,
        )

        select_sql = session.executed_sql[0]
        select_params = session.executed_params[0]
        assert "LIMIT :total_limit" in select_sql
        assert select_params["total_limit"] == 42

    async def test_empty_candidate_set_returns_zero_counts(self) -> None:
        session = _StubSession(candidates=[])
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_all_success_client(),
            batch_size=16,
            sleep_seconds=0,
            sleep_func=sleep,
        )

        assert counts.scanned == 0
        assert counts.embedded == 0
        assert session.commits == 0
        # Only the SELECT fires; no UPDATEs.
        assert len(session.executed_sql) == 1


# ---------------------------------------------------------------------------
# Criterion 2 — sleep defaults + Retry-After honor
# ---------------------------------------------------------------------------


class TestSleepAndRetryAfter:
    def test_default_sleep_seconds_is_2(self) -> None:
        # Constant-level lock — used by the CLI's default --sleep-seconds.
        assert DEFAULT_SLEEP_SECONDS == 2.0

    async def test_inter_batch_sleep_uses_configured_seconds(self) -> None:
        # 20 rows / batch_size=10 => 2 batches; sleep between batches
        # once (after batch 0, before batch 1). Last batch has no
        # trailing sleep.
        session = _StubSession(candidates=_rows(20))
        sleep = _RecorderSleep()

        await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_all_success_client(),
            batch_size=10,
            sleep_seconds=2.0,
            sleep_func=sleep,
        )

        assert sleep.durations == [2.0]

    async def test_429_retry_after_overrides_sleep_seconds(self) -> None:
        # 10 rows / batch_size=5 => 2 batches. First batch returns 429
        # with Retry-After: 7. Expect: sleep(7) before next batch, NOT
        # sleep(2).
        call_count = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "7"},
                    json={"error": "rate_limit_exceeded"},
                )
            return _success_response_for(5)

        session = _StubSession(candidates=_rows(10))
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_mock_client_with_handler(handler),
            batch_size=5,
            sleep_seconds=2.0,
            sleep_func=sleep,
        )

        assert sleep.durations == [7.0]  # retry-after on batch 1, none after last
        assert counts.skipped_transient == 5
        assert counts.embedded == 5

    async def test_429_retry_after_is_capped_at_60s(self) -> None:
        # Pathological Retry-After: 3600 must be clamped to 60.
        call_count = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "3600"},
                    json={"error": "rate_limit_exceeded"},
                )
            return _success_response_for(5)

        session = _StubSession(candidates=_rows(10))
        sleep = _RecorderSleep()

        await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_mock_client_with_handler(handler),
            batch_size=5,
            sleep_seconds=2.0,
            sleep_func=sleep,
        )

        assert sleep.durations == [float(MAX_RETRY_AFTER_SECONDS)]

    async def test_429_without_retry_after_falls_back_to_sleep_seconds(self) -> None:
        call_count = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(
                    429,
                    json={"error": "rate_limit_exceeded"},
                )
            return _success_response_for(5)

        session = _StubSession(candidates=_rows(10))
        sleep = _RecorderSleep()

        await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_mock_client_with_handler(handler),
            batch_size=5,
            sleep_seconds=2.0,
            sleep_func=sleep,
        )

        assert sleep.durations == [2.0]


# ---------------------------------------------------------------------------
# Criterion 3 — bounded batch (≤ 16)
# ---------------------------------------------------------------------------


class TestBatchSize:
    def test_max_batch_size_constant_is_16(self) -> None:
        assert MAX_BATCH_SIZE == 16

    async def test_batch_size_over_16_raises(self) -> None:
        session = _StubSession(candidates=_rows(5))
        with pytest.raises(ValueError, match="batch_size must be 1..16"):
            await run_embedding_backfill(
                session,  # type: ignore[arg-type]
                client=_all_success_client(),
                batch_size=17,
                sleep_func=_RecorderSleep(),
            )

    async def test_batch_size_zero_raises(self) -> None:
        session = _StubSession(candidates=_rows(5))
        with pytest.raises(ValueError, match="batch_size must be 1..16"):
            await run_embedding_backfill(
                session,  # type: ignore[arg-type]
                client=_all_success_client(),
                batch_size=0,
                sleep_func=_RecorderSleep(),
            )

    async def test_50_rows_with_batch_16_produces_4_calls(self) -> None:
        # 50 rows / 16 => 4 batches (16, 16, 16, 2).
        call_args: list[int] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content.decode("utf-8"))
            call_args.append(len(body["texts"]))
            return _success_response_for(len(body["texts"]))

        session = _StubSession(candidates=_rows(50))
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_mock_client_with_handler(handler),
            batch_size=16,
            sleep_seconds=0.1,
            sleep_func=sleep,
        )

        assert call_args == [16, 16, 16, 2]
        assert counts.embedded == 50
        assert session.commits == 4  # one commit per successful batch
        # Sleeps: 3 between-batch sleeps; none after the last.
        assert len(sleep.durations) == 3


# ---------------------------------------------------------------------------
# Criterion 4 — rerun idempotency + partial transient resume
# ---------------------------------------------------------------------------


class TestIdempotencyAndPartialResume:
    async def test_rerun_on_empty_candidate_set_is_noop(self) -> None:
        # Simulates a rerun after a successful previous run. NULL set
        # is empty, so no UPDATE, no commit.
        session = _StubSession(candidates=[])
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_all_success_client(),
            batch_size=16,
            sleep_seconds=0,
            sleep_func=sleep,
        )

        assert counts.scanned == 0
        assert counts.embedded == 0
        assert session.commits == 0
        assert sleep.durations == []

    async def test_partial_transient_preserves_successful_batches(self) -> None:
        # 15 rows / batch_size=5 => 3 batches.
        # Batch 0: 200 -> embedded 5
        # Batch 1: 429 -> skipped_transient 5
        # Batch 2: 200 -> embedded 5
        call_count = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 2:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "1"},
                    json={"error": "rate_limit_exceeded"},
                )
            return _success_response_for(5)

        session = _StubSession(candidates=_rows(15))
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_mock_client_with_handler(handler),
            batch_size=5,
            sleep_seconds=0.5,
            sleep_func=sleep,
        )

        assert counts.scanned == 15
        assert counts.embedded == 10  # batches 0 and 2
        assert counts.skipped_transient == 5  # batch 1
        assert counts.skipped_permanent == 0
        # 2 commits (for the 2 successful batches — failed batch does
        # NOT commit).
        assert session.commits == 2

    async def test_permanent_error_skips_batch_continues(self) -> None:
        # 10 rows / batch_size=5 => 2 batches.
        # Batch 0: 422 -> skipped_permanent 5
        # Batch 1: 200 -> embedded 5
        call_count = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(
                    422,
                    json={"detail": "empty text", "retryable": False},
                )
            return _success_response_for(5)

        session = _StubSession(candidates=_rows(10))
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_mock_client_with_handler(handler),
            batch_size=5,
            sleep_seconds=0,
            sleep_func=sleep,
        )

        assert counts.skipped_permanent == 5
        assert counts.embedded == 5
        assert session.commits == 1  # only the successful batch committed

    async def test_null_guard_mismatch_counted_as_already_populated(self) -> None:
        # Simulates a concurrent writer populating the row between
        # our SELECT and UPDATE. rowcount=0 on one row, rowcount=1 on
        # the other.
        session = _StubSession(
            candidates=_rows(2),
            update_rowcounts=[1, 0],
        )
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_all_success_client(),
            batch_size=16,
            sleep_seconds=0,
            sleep_func=sleep,
        )

        assert counts.embedded == 1
        assert counts.already_populated == 1
        assert counts.skipped_transient == 0

    async def test_update_sql_uses_pinned_null_guard_text(self) -> None:
        # Same text-match as embedding_writer's UPDATE — confirms the
        # backfill and the ingest-time writer use the exact same
        # null-guarded SQL.
        session = _StubSession(candidates=_rows(2))
        sleep = _RecorderSleep()

        await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_all_success_client(),
            batch_size=16,
            sleep_seconds=0,
            sleep_func=sleep,
        )

        # First executed SQL is the SELECT; the next two are UPDATEs.
        update_sqls = [s for s in session.executed_sql if "UPDATE" in s.upper()]
        assert len(update_sqls) == 2
        for sql in update_sqls:
            assert "UPDATE reports SET embedding = CAST(:vec AS vector)" in sql
            assert "WHERE id = :id AND embedding IS NULL" in sql


# ---------------------------------------------------------------------------
# Dry-run — no client calls, no UPDATEs
# ---------------------------------------------------------------------------


class TestDryRun:
    async def test_dry_run_selects_but_does_not_write(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                "llm-proxy must not be called in dry-run mode"
            )

        session = _StubSession(candidates=_rows(30))
        sleep = _RecorderSleep()

        counts = await run_embedding_backfill(
            session,  # type: ignore[arg-type]
            client=_mock_client_with_handler(handler),
            batch_size=16,
            sleep_seconds=0,
            dry_run=True,
            sleep_func=sleep,
        )

        assert counts.scanned == 30
        assert counts.dry_run_skipped == 30
        assert counts.embedded == 0
        assert session.commits == 0
        # Only one execute — the SELECT. No UPDATEs issued.
        assert len(session.executed_sql) == 1
        # No sleeps either — dry-run short-circuits before the batch
        # loop.
        assert sleep.durations == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    async def test_limit_zero_raises(self) -> None:
        session = _StubSession(candidates=[])
        with pytest.raises(ValueError, match="limit must be positive"):
            await run_embedding_backfill(
                session,  # type: ignore[arg-type]
                client=_all_success_client(),
                batch_size=16,
                limit=0,
                sleep_func=_RecorderSleep(),
            )

    async def test_negative_sleep_raises(self) -> None:
        session = _StubSession(candidates=[])
        with pytest.raises(ValueError, match="sleep_seconds must be non-negative"):
            await run_embedding_backfill(
                session,  # type: ignore[arg-type]
                client=_all_success_client(),
                batch_size=16,
                sleep_seconds=-1.0,
                sleep_func=_RecorderSleep(),
            )
