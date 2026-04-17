"""Review workflow DQ metrics (PR #10 Phase 2.1 Group G).

Two SQL-based expectations measuring the operational health of the
staging → production promote queue:

  - ``review.backlog_size`` — count of rows stuck in ``status='pending'``.
    Warn at > 500. Operational signal for "reviewers are falling
    behind"; not a correctness check. High backlog means the ingest
    pipeline is faster than review capacity, not that any data is
    wrong.

  - ``review.avg_latency_hours`` — average wall-clock gap between
    ``created_at`` and ``reviewed_at`` across decided rows
    (``approved`` / ``rejected`` / ``promoted``). Warn at > 72 hours.
    Complements backlog_size: backlog shows current queue depth,
    latency shows how long the in-flight rows typically wait.

Plan §2.1 D4 lock — MANUAL/CI RUN ONLY.

These metrics are **never computed per-request** inside the API
review endpoint. The review/promote handler does not import this
module. Invocation is exclusively via
``python -m worker.data_quality check`` (stdout + ``dq_events`` +
optional JSONL mirror sinks). Per-request emit would add a COUNT
query and an AVG query to every approve/reject call, and the
resulting latency hit is visible to reviewers. The 72-hour signal
does not need second-level freshness.

``review.approval_rate`` is DELIBERATELY NOT included (plan §2.1
D4). It is an operational KPI that requires accumulated decision
history to be statistically meaningful — shipping it in this PR
would surface a metric that reads 0.00 for the first few days and
confuse reviewers. Deferred to a later PR once decision volume is
real.

Both expectations are ``warn``-severity only. Neither blocks the
ingest pipeline, neither fails CI by default. Raising to ``error``
requires a new decision ID — operational observability should not
be a hard gate.

Tuning note: thresholds (500 / 72h) are starting points. Adjust
after first-real-run operational data accumulates, following the
same pattern used for ``dedup_rate``'s 0.15 (D12).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import staging_table
from worker.data_quality.results import Expectation, ExpectationResult


__all__ = [
    "REVIEW_AVG_LATENCY_HOURS_WARN_THRESHOLD",
    "REVIEW_BACKLOG_SIZE_WARN_THRESHOLD",
    "compute_backlog_severity",
    "compute_latency_severity",
    "review_avg_latency_hours",
    "review_backlog_size",
]


#: Warn when the pending queue exceeds this row count.
REVIEW_BACKLOG_SIZE_WARN_THRESHOLD: int = 500


#: Warn when the average decision latency exceeds this many hours.
REVIEW_AVG_LATENCY_HOURS_WARN_THRESHOLD: Decimal = Decimal("72")


#: staging.status values that represent a completed review decision.
#: ``approved`` is included because the CHECK enum reserves it for
#: future auto-promote paths; when those ship, the rows they write
#: carry ``reviewed_at`` like the manual paths do and should count
#: toward the latency metric.
_DECIDED_STATUSES: frozenset[str] = frozenset(
    {"approved", "rejected", "promoted"}
)


# ---------------------------------------------------------------------------
# Pure severity computation — separated from SQL for direct unit tests
# ---------------------------------------------------------------------------


def compute_backlog_severity(pending_count: int) -> str:
    """Decide severity for a pending-queue count.

    ``pending_count`` is an integer (not a ratio), so this doesn't
    round-trip through Decimal. Returns ``"warn"`` when the queue is
    strictly above the threshold, otherwise ``"pass"``.
    """
    return "warn" if pending_count > REVIEW_BACKLOG_SIZE_WARN_THRESHOLD else "pass"


def compute_latency_severity(avg_hours: Decimal) -> str:
    """Decide severity for an average decision latency in hours."""
    return (
        "warn"
        if avg_hours > REVIEW_AVG_LATENCY_HOURS_WARN_THRESHOLD
        else "pass"
    )


# ---------------------------------------------------------------------------
# Datetime helper — normalize aware/naive to UTC-aware so subtraction
# works uniformly across PG (tz-aware) and sqlite (often naive)
# ---------------------------------------------------------------------------


def _to_utc_aware(ts: dt.datetime) -> dt.datetime:
    """Coerce a datetime to UTC-aware.

    PostgreSQL's TIMESTAMPTZ surfaces as tz-aware through psycopg.
    SQLite's DATETIME has no timezone — aiosqlite returns naive
    datetimes. Subtraction across a naive/aware pair raises TypeError,
    so we normalize both sides before the delta.
    """
    if ts.tzinfo is None:
        return ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc)


# ---------------------------------------------------------------------------
# review.backlog_size
# ---------------------------------------------------------------------------


async def _check_review_backlog_size(
    session: AsyncSession,
) -> ExpectationResult:
    """Count staging rows whose ``status='pending'``.

    The count query is the entire SQL surface — no JOINs, no
    filtering beyond status, no DATE math. Cheap enough that the CI
    DQ run cost is negligible even when staging grows to six figures.
    """
    pending_count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(staging_table)
            .where(staging_table.c.status == "pending")
        )
    ).scalar_one()
    pending_count = int(pending_count)
    severity = compute_backlog_severity(pending_count)
    return ExpectationResult(
        name="review.backlog_size",
        severity=severity,
        observed=Decimal(pending_count),
        threshold=Decimal(REVIEW_BACKLOG_SIZE_WARN_THRESHOLD),
        observed_rows=pending_count,
        detail={
            "pending_count": pending_count,
            "threshold_rationale": (
                "initial 500-row warn threshold; tune after real "
                "reviewer-capacity data accumulates"
            ),
        },
    )


review_backlog_size = Expectation(
    name="review.backlog_size",
    check=_check_review_backlog_size,
)


# ---------------------------------------------------------------------------
# review.avg_latency_hours
# ---------------------------------------------------------------------------


async def _check_review_avg_latency_hours(
    session: AsyncSession,
) -> ExpectationResult:
    """Average decision latency across decided rows, in hours.

    Fetches ``(created_at, reviewed_at)`` for rows with a decided
    status and non-null ``reviewed_at``, then computes the average
    in Python. Cross-dialect portable (PG has ``EXTRACT(EPOCH...)``,
    SQLite has ``julianday()`` — neither is a clean shared path, and
    the row volume is bounded by the decision history, so fetching
    the columns and averaging in Python is simpler than a
    dialect-aware CASE in the SQL).

    Empty-history case returns ``pass`` with ``observed=0`` so the
    metric appears in ``dq_events`` from day one — no missing-row
    gap in the trend series when the queue is freshly deployed.
    """
    rows = (
        await session.execute(
            sa.select(
                staging_table.c.created_at,
                staging_table.c.reviewed_at,
            )
            .where(staging_table.c.status.in_(_DECIDED_STATUSES))
            .where(staging_table.c.reviewed_at.isnot(None))
        )
    ).all()

    if not rows:
        return ExpectationResult(
            name="review.avg_latency_hours",
            severity="pass",
            observed=Decimal(0),
            threshold=REVIEW_AVG_LATENCY_HOURS_WARN_THRESHOLD,
            observed_rows=0,
            detail={
                "decided_rows": 0,
                "note": "no decided staging rows yet — baseline reading",
            },
        )

    total_seconds = Decimal(0)
    for row in rows:
        created_utc = _to_utc_aware(row.created_at)
        reviewed_utc = _to_utc_aware(row.reviewed_at)
        delta = reviewed_utc - created_utc
        total_seconds += Decimal(str(delta.total_seconds()))

    decided_rows = len(rows)
    avg_hours = total_seconds / (Decimal(decided_rows) * Decimal(3600))
    severity = compute_latency_severity(avg_hours)

    return ExpectationResult(
        name="review.avg_latency_hours",
        severity=severity,
        observed=avg_hours,
        threshold=REVIEW_AVG_LATENCY_HOURS_WARN_THRESHOLD,
        # ``observed_rows`` follows the Group D convention. For
        # latency the violating count is "decided rows included in
        # the average" — not a violation count per se, but the
        # sample size that produced ``observed``. Full detail lives
        # under ``detail``.
        observed_rows=decided_rows,
        detail={
            "decided_rows": decided_rows,
            "threshold_rationale": (
                "initial 72-hour warn threshold; tune after real "
                "reviewer-capacity data accumulates"
            ),
        },
    )


review_avg_latency_hours = Expectation(
    name="review.avg_latency_hours",
    check=_check_review_avg_latency_hours,
)
