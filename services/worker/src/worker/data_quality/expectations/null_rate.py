"""Null-rate expectations (D10 / N1–N2).

Two expectations, both ``warn`` severity with threshold ``0.50``.
Per the D10 three-condition filter (nullable in DB, NOT pydantic
required, null carries operational meaning), exactly two columns
qualify for PR #7 scope:

  - N1 ``codenames.group_id.null_rate`` — coverage signal for the
    alias dictionary. A high null rate means many codenames did not
    resolve to a known canonical group and the dictionary needs a
    new entry.
  - N2 ``codenames.named_by_source_id.null_rate`` — coverage signal
    for vendor source attribution. A high null rate means the
    ``ActorRow.named_by`` cell was empty in most rows and the
    workbook metadata needs enrichment.

Every other nullable column in the bootstrap schema is explicitly
excluded from null-rate checking in D10 (see §7 Resolution Log for
the full list); this module does not silently add more checks.

Severity semantics:

  - ``pass`` when ratio ≤ 0.50 (including the empty-table case,
    where the ratio is conventionally 0).
  - ``warn`` when ratio > 0.50.
  - ``error`` is never produced by null-rate expectations in PR #7.
"""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import codenames_table
from worker.data_quality.results import Expectation, ExpectationResult


__all__ = [
    "NULL_RATE_WARN_THRESHOLD",
    "null_rate_codenames_group_id",
    "null_rate_codenames_named_by_source_id",
]


#: Warn threshold for both N1 and N2. Initial value per D10; revisit
#: once PR #9+ has real-data ratios to compare against.
NULL_RATE_WARN_THRESHOLD: Decimal = Decimal("0.50")


async def _null_rate(
    session: AsyncSession,
    column: sa.Column,
) -> tuple[int, int, Decimal]:
    """Compute (total_rows, null_rows, ratio) for ``column``.

    ``ratio`` is :class:`decimal.Decimal` so downstream comparisons
    against :data:`NULL_RATE_WARN_THRESHOLD` stay exact. An empty
    table returns ``(0, 0, Decimal(0))``.
    """
    total = (
        await session.execute(
            sa.select(sa.func.count()).select_from(column.table)
        )
    ).scalar_one()
    null_count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(column.table)
            .where(column.is_(None))
        )
    ).scalar_one()

    if total == 0:
        ratio = Decimal(0)
    else:
        ratio = Decimal(null_count) / Decimal(total)
    return int(total), int(null_count), ratio


def _severity_for_ratio(ratio: Decimal) -> str:
    return "warn" if ratio > NULL_RATE_WARN_THRESHOLD else "pass"


# ---------------------------------------------------------------------------
# N1 — codenames.group_id.null_rate
# ---------------------------------------------------------------------------


async def _check_codenames_group_id(
    session: AsyncSession,
) -> ExpectationResult:
    total, null_count, ratio = await _null_rate(
        session, codenames_table.c.group_id
    )
    return ExpectationResult(
        name="codenames.group_id.null_rate",
        severity=_severity_for_ratio(ratio),
        observed=ratio,
        threshold=NULL_RATE_WARN_THRESHOLD,
        observed_rows=null_count,
        detail={
            "total_rows": total,
            "null_rows": null_count,
            "interpretation": (
                "codename -> group attribution coverage; "
                "high null ratio means alias dictionary needs expansion"
            ),
        },
    )


null_rate_codenames_group_id = Expectation(
    name="codenames.group_id.null_rate",
    check=_check_codenames_group_id,
)


# ---------------------------------------------------------------------------
# N2 — codenames.named_by_source_id.null_rate
# ---------------------------------------------------------------------------


async def _check_codenames_named_by_source_id(
    session: AsyncSession,
) -> ExpectationResult:
    total, null_count, ratio = await _null_rate(
        session, codenames_table.c.named_by_source_id
    )
    return ExpectationResult(
        name="codenames.named_by_source_id.null_rate",
        severity=_severity_for_ratio(ratio),
        observed=ratio,
        threshold=NULL_RATE_WARN_THRESHOLD,
        observed_rows=null_count,
        detail={
            "total_rows": total,
            "null_rows": null_count,
            "interpretation": (
                "codename -> source attribution coverage; "
                "high null ratio means the ActorRow.named_by column "
                "was empty in most workbook rows"
            ),
        },
    )


null_rate_codenames_named_by_source_id = Expectation(
    name="codenames.named_by_source_id.null_rate",
    check=_check_codenames_named_by_source_id,
)
