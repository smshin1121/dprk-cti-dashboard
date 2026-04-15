"""Year-range expectations (D12 / Y1–Y2).

Both expectations bound the date column to
``[2000-01-01, 2030-12-31]`` and are ``error`` severity at threshold
0 violating rows. Rationale for the bounds is captured in D12:

  - 2000-01-01 covers the full known DPRK APT public reporting
    window (earliest Lazarus / GoP attribution ~2009, looser
    pre-attribution material as early as 2000).
  - 2030-12-31 provides ~5 years of forward buffer from the current
    2026-04-15 plan-lock date to absorb near-future-dated reports
    while still catching typos outside that window.

Y2 excludes NULL ``incidents.reported`` from the count because the
NULL is a coverage concern, not a range concern — null-rate for
that column is out of PR #7 scope per D10's "not pydantic-required"
filter (``IncidentRow.reported`` IS pydantic-required, so the null
would only occur via a non-bootstrap write path that PR #7 does
not yet have).
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import incidents_table, reports_table
from worker.data_quality.results import Expectation, ExpectationResult


__all__ = [
    "YEAR_RANGE_LOWER",
    "YEAR_RANGE_UPPER",
    "year_range_incidents_reported",
    "year_range_reports_published",
]


#: Lower bound (inclusive). Any date strictly less than this is
#: considered out-of-range for PR #7.
YEAR_RANGE_LOWER: dt.date = dt.date(2000, 1, 1)

#: Upper bound (inclusive). Any date strictly greater than this is
#: considered out-of-range for PR #7.
YEAR_RANGE_UPPER: dt.date = dt.date(2030, 12, 31)


# ---------------------------------------------------------------------------
# Y1 — reports.published.year_range
# ---------------------------------------------------------------------------


async def _check_reports_published(
    session: AsyncSession,
) -> ExpectationResult:
    """Count ``reports`` rows whose ``published`` is outside
    :data:`YEAR_RANGE_LOWER` .. :data:`YEAR_RANGE_UPPER`.

    The column is NOT NULL (0001 schema) so no null guard needed.
    """
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(reports_table)
            .where(
                (reports_table.c.published < YEAR_RANGE_LOWER)
                | (reports_table.c.published > YEAR_RANGE_UPPER)
            )
        )
    ).scalar_one()

    return ExpectationResult(
        name="reports.published.year_range",
        severity="error" if count > 0 else "pass",
        observed_rows=int(count),
        threshold=0,
        detail={
            "lower_bound": YEAR_RANGE_LOWER.isoformat(),
            "upper_bound": YEAR_RANGE_UPPER.isoformat(),
        },
    )


year_range_reports_published = Expectation(
    name="reports.published.year_range",
    check=_check_reports_published,
)


# ---------------------------------------------------------------------------
# Y2 — incidents.reported.year_range
# ---------------------------------------------------------------------------


async def _check_incidents_reported(
    session: AsyncSession,
) -> ExpectationResult:
    """Count ``incidents`` rows whose ``reported`` is outside the
    year range. NULL rows are excluded from the count — see module
    docstring for the D10 rationale on why null-rate for this
    column is out of PR #7 scope."""
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(incidents_table)
            .where(
                incidents_table.c.reported.is_not(None)
                & (
                    (incidents_table.c.reported < YEAR_RANGE_LOWER)
                    | (incidents_table.c.reported > YEAR_RANGE_UPPER)
                )
            )
        )
    ).scalar_one()

    return ExpectationResult(
        name="incidents.reported.year_range",
        severity="error" if count > 0 else "pass",
        observed_rows=int(count),
        threshold=0,
        detail={
            "lower_bound": YEAR_RANGE_LOWER.isoformat(),
            "upper_bound": YEAR_RANGE_UPPER.isoformat(),
            "note": "NULL rows are excluded from the violation count",
        },
    )


year_range_incidents_reported = Expectation(
    name="incidents.reported.year_range",
    check=_check_incidents_reported,
)
