"""Unit tests for ``worker.data_quality.expectations.review_metrics``
(PR #10 Phase 2.1 Group G).

Reviewer-pinned invariants:

1. ``review.backlog_size`` + ``review.avg_latency_hours`` are
   **manual/CI DQ run only**. No API route imports this module —
   per-request computation was explicitly rejected in plan §2.1 D4
   (handler latency cost, metric freshness not needed at that
   resolution).
2. Both expectations produce ``pass`` on the empty-table path so
   the metrics appear in ``dq_events`` from day one.
3. Thresholds are locked: 500 rows (backlog) and 72 hours (avg
   latency). Warn strictly above threshold, pass at/below.
4. ``review.approval_rate`` is NOT in the registry (deferred).
"""

from __future__ import annotations

import datetime as dt
import pathlib
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import staging_table
from worker.data_quality.expectations import ALL_EXPECTATION_NAMES
from worker.data_quality.expectations.review_metrics import (
    REVIEW_AVG_LATENCY_HOURS_WARN_THRESHOLD,
    REVIEW_BACKLOG_SIZE_WARN_THRESHOLD,
    compute_backlog_severity,
    compute_latency_severity,
    review_avg_latency_hours,
    review_backlog_size,
)


# ---------------------------------------------------------------------------
# Constants — thresholds pinned by plan §2.1 D4 lock
# ---------------------------------------------------------------------------


class TestThresholdConstants:
    def test_backlog_threshold_is_500(self) -> None:
        assert REVIEW_BACKLOG_SIZE_WARN_THRESHOLD == 500

    def test_avg_latency_threshold_is_72_hours(self) -> None:
        assert REVIEW_AVG_LATENCY_HOURS_WARN_THRESHOLD == Decimal("72")


# ---------------------------------------------------------------------------
# Pure severity functions
# ---------------------------------------------------------------------------


class TestComputeBacklogSeverity:
    def test_zero_is_pass(self) -> None:
        assert compute_backlog_severity(0) == "pass"

    def test_exactly_at_threshold_is_pass(self) -> None:
        """Threshold is 'strictly greater than' — 500 is still pass."""
        assert compute_backlog_severity(500) == "pass"

    def test_one_above_is_warn(self) -> None:
        assert compute_backlog_severity(501) == "warn"

    def test_large_count_is_warn(self) -> None:
        assert compute_backlog_severity(10_000) == "warn"


class TestComputeLatencySeverity:
    def test_zero_is_pass(self) -> None:
        assert compute_latency_severity(Decimal("0")) == "pass"

    def test_exactly_at_threshold_is_pass(self) -> None:
        assert compute_latency_severity(Decimal("72")) == "pass"

    def test_just_above_is_warn(self) -> None:
        assert compute_latency_severity(Decimal("72.01")) == "warn"

    def test_many_days_is_warn(self) -> None:
        assert compute_latency_severity(Decimal("240")) == "warn"  # 10 days


# ---------------------------------------------------------------------------
# Registry presence + deferred approval_rate
# ---------------------------------------------------------------------------


class TestRegistryPresence:
    def test_both_expectations_registered(self) -> None:
        assert "review.backlog_size" in ALL_EXPECTATION_NAMES
        assert "review.avg_latency_hours" in ALL_EXPECTATION_NAMES

    def test_approval_rate_not_registered_in_pr10(self) -> None:
        """Plan §2.1 D4 deferred approval_rate — reading it too early
        (low decision volume) misleads reviewers. Keep it out of the
        registry until enough decisions accumulate."""
        assert "review.approval_rate" not in ALL_EXPECTATION_NAMES

    def test_expectation_name_attribute_matches_registry(self) -> None:
        """Wrapper name must equal the dotted identifier — the runner
        uses it to synthesize error results when the check raises."""
        assert review_backlog_size.name == "review.backlog_size"
        assert review_avg_latency_hours.name == "review.avg_latency_hours"


# ---------------------------------------------------------------------------
# SQL checks — backlog_size
# ---------------------------------------------------------------------------


async def _seed_pending(
    session: AsyncSession, count: int, *, base_url: str = "http://e/"
) -> None:
    for i in range(count):
        await session.execute(
            sa.insert(staging_table).values(
                url_canonical=f"{base_url}{i}",
                url=f"{base_url}{i}",
                title=f"t{i}",
                published=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc),
                status="pending",
            )
        )
    await session.commit()


async def _seed_decided(
    session: AsyncSession,
    *,
    status: str,
    created_at: dt.datetime,
    reviewed_at: dt.datetime,
    url: str,
) -> None:
    await session.execute(
        sa.insert(staging_table).values(
            url_canonical=url,
            url=url,
            title="t",
            published=created_at,
            created_at=created_at,
            reviewed_at=reviewed_at,
            reviewed_by="tester",
            status=status,
        )
    )
    await session.commit()


class TestBacklogSize:
    async def test_empty_returns_pass_zero(
        self, db_session: AsyncSession
    ) -> None:
        result = await review_backlog_size.check(db_session)
        assert result.name == "review.backlog_size"
        assert result.severity == "pass"
        assert result.observed == Decimal(0)
        assert result.observed_rows == 0
        assert result.threshold == Decimal(500)

    async def test_below_threshold_is_pass(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_pending(db_session, count=100)
        result = await review_backlog_size.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal(100)
        assert result.observed_rows == 100

    async def test_at_threshold_is_pass(
        self, db_session: AsyncSession
    ) -> None:
        # Plan boundary: "warn when strictly above threshold".
        # Seeding 500 rows in SQLite-memory is fast enough.
        await _seed_pending(db_session, count=500)
        result = await review_backlog_size.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal(500)

    async def test_above_threshold_is_warn(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_pending(db_session, count=501)
        result = await review_backlog_size.check(db_session)
        assert result.severity == "warn"
        assert result.observed == Decimal(501)

    async def test_decided_rows_not_counted(
        self, db_session: AsyncSession
    ) -> None:
        """Only pending rows go into backlog — decided rows are not
        part of the queue-depth signal."""
        await _seed_pending(db_session, count=10)
        t = dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc)
        for i, status in enumerate(("approved", "rejected", "promoted", "error")):
            await _seed_decided(
                db_session,
                status=status,
                created_at=t,
                reviewed_at=t + dt.timedelta(hours=1),
                url=f"http://decided/{status}",
            )
        result = await review_backlog_size.check(db_session)
        # Only the 10 pending rows counted.
        assert result.observed_rows == 10


# ---------------------------------------------------------------------------
# SQL checks — avg_latency_hours
# ---------------------------------------------------------------------------


class TestAvgLatencyHours:
    async def test_empty_history_returns_pass_zero_with_note(
        self, db_session: AsyncSession
    ) -> None:
        result = await review_avg_latency_hours.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal(0)
        assert result.observed_rows == 0
        assert result.detail["decided_rows"] == 0
        assert "baseline" in result.detail["note"]

    async def test_single_decided_row_computes_latency(
        self, db_session: AsyncSession
    ) -> None:
        created = dt.datetime(2026, 4, 1, 0, 0, tzinfo=dt.timezone.utc)
        reviewed = created + dt.timedelta(hours=5)
        await _seed_decided(
            db_session,
            status="promoted",
            created_at=created,
            reviewed_at=reviewed,
            url="http://e/single",
        )
        result = await review_avg_latency_hours.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal("5.0")
        assert result.observed_rows == 1

    async def test_average_across_multiple_rows(
        self, db_session: AsyncSession
    ) -> None:
        """3 rows with latencies 2h, 4h, 6h → avg = 4h."""
        created = dt.datetime(2026, 4, 1, 0, 0, tzinfo=dt.timezone.utc)
        for hours, status in ((2, "approved"), (4, "rejected"), (6, "promoted")):
            await _seed_decided(
                db_session,
                status=status,
                created_at=created,
                reviewed_at=created + dt.timedelta(hours=hours),
                url=f"http://e/{hours}h",
            )
        result = await review_avg_latency_hours.check(db_session)
        assert result.observed == Decimal("4.0")
        assert result.observed_rows == 3
        assert result.severity == "pass"

    async def test_above_threshold_warns(
        self, db_session: AsyncSession
    ) -> None:
        """Single row with 100h latency → warn (> 72h threshold)."""
        created = dt.datetime(2026, 4, 1, 0, 0, tzinfo=dt.timezone.utc)
        await _seed_decided(
            db_session,
            status="promoted",
            created_at=created,
            reviewed_at=created + dt.timedelta(hours=100),
            url="http://e/slow",
        )
        result = await review_avg_latency_hours.check(db_session)
        assert result.severity == "warn"
        assert result.observed == Decimal("100.0")

    async def test_pending_rows_not_included(
        self, db_session: AsyncSession
    ) -> None:
        """Pending rows have NULL reviewed_at — excluded from the
        average so the queue-waiting-time doesn't pollute the
        decision-latency signal."""
        await _seed_pending(db_session, count=5)
        # One decided row with 10h latency.
        created = dt.datetime(2026, 4, 1, 0, 0, tzinfo=dt.timezone.utc)
        await _seed_decided(
            db_session,
            status="promoted",
            created_at=created,
            reviewed_at=created + dt.timedelta(hours=10),
            url="http://e/decided",
        )
        result = await review_avg_latency_hours.check(db_session)
        assert result.observed_rows == 1  # only the decided row
        assert result.observed == Decimal("10.0")

    async def test_error_status_excluded_from_average(
        self, db_session: AsyncSession
    ) -> None:
        """status='error' is an ingest failure flag, not a review
        decision — excluded from the latency metric even if
        reviewed_at somehow ends up populated."""
        created = dt.datetime(2026, 4, 1, 0, 0, tzinfo=dt.timezone.utc)
        await _seed_decided(
            db_session,
            status="error",
            created_at=created,
            reviewed_at=created + dt.timedelta(hours=200),
            url="http://e/errored",
        )
        # One legitimate decided row.
        await _seed_decided(
            db_session,
            status="approved",
            created_at=created,
            reviewed_at=created + dt.timedelta(hours=3),
            url="http://e/legit",
        )
        result = await review_avg_latency_hours.check(db_session)
        assert result.observed_rows == 1
        assert result.observed == Decimal("3.0")


# ---------------------------------------------------------------------------
# CRITICAL: api.* must NOT import review_metrics (per-request ban)
# ---------------------------------------------------------------------------


class TestApiDoesNotImportDq:
    """Plan §2.1 D4 lock: review.* metrics are manual/CI DQ run only.
    The API review endpoint must not trigger a COUNT/AVG query on
    every approve/reject — static source scan keeps the contract
    enforceable in CI without needing a runtime import-graph probe."""

    @staticmethod
    def _api_src_dir() -> pathlib.Path:
        # services/worker/tests/unit/test_review_metrics.py
        # parents[0]=unit, [1]=tests, [2]=worker, [3]=services, [4]=repo.
        repo_root = pathlib.Path(__file__).resolve().parents[4]
        return repo_root / "services" / "api" / "src"

    def test_api_src_directory_exists(self) -> None:
        """Guard: if the project layout moves, this test must fail
        loud, not silently pass by finding zero files."""
        assert self._api_src_dir().exists(), (
            f"api src dir not found — test path assumption broken"
        )

    @pytest.mark.parametrize(
        "forbidden",
        [
            "review_metrics",
            "worker.data_quality",
            "from worker.",
        ],
    )
    def test_no_api_file_imports_dq_review_metrics(
        self, forbidden: str
    ) -> None:
        """Static grep: no file under services/api/src/ may reference
        the review_metrics module or any worker.data_quality path.
        Per-request DQ emit is explicitly rejected — the handler
        latency cost is visible to reviewers and the 72-hour /
        500-row signal does not need second-level freshness."""
        api_src = self._api_src_dir()
        offending = []
        for py in api_src.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if forbidden in text:
                offending.append(py.relative_to(api_src))
        assert not offending, (
            f"api source files import DQ ({forbidden!r} found): "
            f"{offending}. Plan §2.1 D4 locks review.* metrics to "
            f"manual/CI DQ run only — per-request emit is forbidden."
        )
