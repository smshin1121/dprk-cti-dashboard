"""Dedup-rate expectation (prior decision from discuss-phase round 1).

One expectation, ``warn`` severity only. The rule is pinned as
"initial threshold" in D12 because first-real-run data will inform
whether the 0.15 starting point is too strict or too loose:

  ``reports.url_canonical.dedup_rate`` — the fraction of report rows
  that share a URL with another row. Computed as
  ``1 - (count(distinct url_canonical) / count(*))`` against the
  populated ``reports`` table.

D8 established that dedup is a warning-only signal (not a hard
fail) because the bootstrap workbook legitimately re-references the
same public reports through different vendor re-coverage. A warn
means "the dedup rate is above the initial threshold and should be
reviewed"; an error would block legitimate operational data.

**Tautology note.** Migration 0001 declares
``CREATE UNIQUE INDEX uq_reports_url_canonical`` on the column, so
``count(distinct url_canonical) == count(*)`` holds by construction
and the post-load ratio is always ``0``. The check still earns its
slot in the registry because:

  1. It is a **regression guard** for the UNIQUE index itself. If a
     future migration drops or weakens the unique constraint (e.g.,
     PR #8+ multi-writer ingest relaxing it for a partitioning
     scheme) the ratio immediately becomes observable again.
  2. It keeps the DQ gate's "duplicate detection" concern visible in
     the stdout summary even when the count is zero — a reviewer
     expecting "5 DQ checks" sees all five instead of wondering
     whether dedup coverage was dropped.

When the UNIQUE index is in place, tests exercise the ratio math by
dropping the index for a single session so duplicates can be
inserted; that path is NOT reachable in production and exists only
to verify the algorithm.

Severity semantics:

  - ``pass`` when ratio ≤ 0.15 (including the empty-table case).
  - ``warn`` when ratio > 0.15.
  - ``error`` is never produced.
"""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import reports_table
from worker.data_quality.results import Expectation, ExpectationResult


__all__ = [
    "DEDUP_RATE_WARN_THRESHOLD",
    "compute_dedup_severity",
    "dedup_rate_reports_url_canonical",
]


#: Initial warn threshold. Revisit post-first-real-run per D12.
DEDUP_RATE_WARN_THRESHOLD: Decimal = Decimal("0.15")


def compute_dedup_severity(
    total: int, distinct: int
) -> tuple[str, Decimal]:
    """Pure function: compute the dedup ratio and decide severity.

    Extracted from the expectation body so unit tests can exercise
    the warn threshold with synthetic counts without having to
    bypass the production UNIQUE index on ``reports.url_canonical``
    (which sqlite refuses to drop at runtime because it is attached
    to a table constraint). The expectation below calls this helper
    directly.

    Returns:
      Tuple of ``(severity, ratio)`` where ``severity`` is either
      ``"pass"`` or ``"warn"``. Empty-table case returns
      ``("pass", Decimal(0))``.
    """
    if total <= 0:
        return ("pass", Decimal(0))
    ratio = Decimal(1) - (Decimal(distinct) / Decimal(total))
    severity = "warn" if ratio > DEDUP_RATE_WARN_THRESHOLD else "pass"
    return (severity, ratio)


async def _check_reports_url_canonical_dedup(
    session: AsyncSession,
) -> ExpectationResult:
    """Compute the ``reports.url_canonical`` dedup ratio and decide
    severity against :data:`DEDUP_RATE_WARN_THRESHOLD`.

    See module docstring for the tautology rationale — under the
    production UNIQUE index the observed ratio is always 0.
    """
    total = (
        await session.execute(
            sa.select(sa.func.count()).select_from(reports_table)
        )
    ).scalar_one()
    distinct = (
        await session.execute(
            sa.select(sa.func.count(sa.distinct(reports_table.c.url_canonical)))
        )
    ).scalar_one()

    severity, ratio = compute_dedup_severity(int(total), int(distinct))
    duplicate_rows = int(total) - int(distinct)

    return ExpectationResult(
        name="reports.url_canonical.dedup_rate",
        severity=severity,
        observed=ratio,
        threshold=DEDUP_RATE_WARN_THRESHOLD,
        # ``observed_rows`` follows the Group D convention of
        # "violating/affected row count", which for dedup_rate is
        # the number of rows that were NOT the first unique
        # occurrence of their ``url_canonical``. Total scan size
        # lives under ``detail.total_rows``.
        observed_rows=duplicate_rows,
        detail={
            "total_rows": int(total),
            "distinct_urls": int(distinct),
            "duplicate_rows": duplicate_rows,
            "threshold_rationale": (
                "initial 0.15 warn threshold per D12; revisit after "
                "first real-data bootstrap run"
            ),
        },
    )


dedup_rate_reports_url_canonical = Expectation(
    name="reports.url_canonical.dedup_rate",
    check=_check_reports_url_canonical_dedup,
)
