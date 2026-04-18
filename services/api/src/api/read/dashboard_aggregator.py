"""Dashboard summary aggregator (PR #11 Group E).

Plan D6 locks the shape returned by ``GET /api/v1/dashboard/summary``:

    total_reports, total_incidents, total_actors,
    reports_by_year: [{year, count}],
    incidents_by_motivation: [{motivation, count}],
    top_groups: [{group_id, name, report_count}]

Filter scope (plan D5/D6 + MVP tightening documented here):

- ``date_from`` / ``date_to`` apply to **reports.published** AND
  **incidents.reported** — the "KPI over time window" reading of
  §5.4. ``total_actors`` intentionally ignores the date filter
  because "groups known" is an inventory count, not a per-window
  metric.
- ``group_ids`` applies to **top_groups only**. The reports table
  has no direct ``group_id`` FK (connection is
  ``reports → report_codenames → codenames → groups``), and the
  ``incidents`` table has no connection to groups at all. Surfacing
  a group-filtered ``total_reports`` here would require a
  correlated EXISTS chain that is valuable only when the user opens
  a group-scoped drill-down view, which lives on Phase 3 analytics.
  Documented in the router docstring so the FE does not assume
  wider filter semantics.
- ``top_n`` bounded at 1..20 by the router Query layer; the
  aggregator defensively clamps the value regardless so a bypass
  via direct function call cannot return 100 rows.

Invariants enforced here:

1. ``total_*`` returns exactly the number of rows that a plain
   ``SELECT COUNT(*) FROM <table>`` would return under the same
   filters (review priority #1). No distinct JOINs that could
   inflate the count.
2. ``incidents_by_motivation.count`` dedupes per ``incident_id`` so
   a single incident that carries two motivations contributes +1 to
   EACH motivation bucket but never multiplies its own count within
   a single bucket (review priority #4).
3. ``top_groups.report_count`` uses ``COUNT(DISTINCT report_id)`` so
   a report with two codenames in the same group surfaces as one
   toward that group's bucket (review priority #4).
4. ``top_groups`` ordering is ``report_count DESC, group_id ASC``
   — the id tiebreaker keeps repeat calls stable when multiple
   groups share the same count (review priority #3).
5. Empty tables return totals of 0 and empty arrays (review
   priority #5). ``DashboardSummary`` has ``default_factory=list``
   on all three aggregate fields so this holds at the DTO layer
   too; the aggregator explicitly emits ``[]`` rather than
   ``None`` to keep the contract identical across layers.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import (
    codenames_table,
    groups_table,
    incident_motivations_table,
    incidents_table,
    report_codenames_table,
    reports_table,
)
from .repositories import _resolve_dialect


_TOP_N_MAX = 20


def _year_expr(col: sa.sql.ColumnElement[date], dialect: str) -> sa.sql.ColumnElement[int]:
    """Portable ``YEAR(col)`` expression.

    PG exposes ``EXTRACT(YEAR FROM col)`` returning a numeric;
    sqlite uses ``strftime('%Y', col)`` returning a string. The
    caller coerces to int.
    """
    if dialect == "postgresql":
        return sa.cast(sa.extract("year", col), sa.Integer)
    return sa.cast(sa.func.strftime("%Y", col), sa.Integer)


async def compute_dashboard_summary(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    group_ids: list[int] | None = None,
    top_n: int = 5,
) -> dict[str, object]:
    """Compute the six numbers that feed ``DashboardSummary``.

    Returns a dict the router hands straight to
    ``DashboardSummary.model_validate``. Each field is computed in
    its own statement — PR #11 accepts the 6-query cost because:

    - The numbers are independent (no cross-field derivations).
    - Plan §7.7 defers both materialized views and Redis response
      caching to Phase 4. Under light traffic the latency is
      dominated by network + serialize, not by query count.
    - Splitting avoids cross-aggregation CTE complexity that would
      make dialect dispatch (PG vs sqlite) harder.

    If the endpoint becomes hot, the refactor is a single CTE
    combining totals + year/motivation groups (top_groups stays
    separate due to its JOIN chain); the DTO shape does not change.
    """
    dialect = _resolve_dialect(session)
    bounded_top_n = max(1, min(top_n, _TOP_N_MAX))

    # ---- total_reports (date-filtered) -------------------------------
    reports_count_stmt = sa.select(sa.func.count()).select_from(reports_table)
    if date_from is not None:
        reports_count_stmt = reports_count_stmt.where(
            reports_table.c.published >= date_from
        )
    if date_to is not None:
        reports_count_stmt = reports_count_stmt.where(
            reports_table.c.published <= date_to
        )
    total_reports = int((await session.execute(reports_count_stmt)).scalar_one())

    # ---- total_incidents (date-filtered) -----------------------------
    incidents_count_stmt = sa.select(sa.func.count()).select_from(incidents_table)
    if date_from is not None:
        incidents_count_stmt = incidents_count_stmt.where(
            incidents_table.c.reported >= date_from
        )
    if date_to is not None:
        incidents_count_stmt = incidents_count_stmt.where(
            incidents_table.c.reported <= date_to
        )
    total_incidents = int((await session.execute(incidents_count_stmt)).scalar_one())

    # ---- total_actors (filter-agnostic inventory) --------------------
    total_actors = int(
        (
            await session.execute(
                sa.select(sa.func.count()).select_from(groups_table)
            )
        ).scalar_one()
    )

    # ---- reports_by_year (GROUP BY year, ORDER BY year DESC) ---------
    year_col = _year_expr(reports_table.c.published, dialect).label("year")
    by_year_stmt = (
        sa.select(year_col, sa.func.count().label("count"))
        .select_from(reports_table)
        .group_by(year_col)
        .order_by(year_col.desc())
    )
    if date_from is not None:
        by_year_stmt = by_year_stmt.where(reports_table.c.published >= date_from)
    if date_to is not None:
        by_year_stmt = by_year_stmt.where(reports_table.c.published <= date_to)
    by_year_rows = (await session.execute(by_year_stmt)).all()
    reports_by_year = [
        {"year": int(row.year), "count": int(row.count)}
        for row in by_year_rows
        if row.year is not None
    ]

    # ---- incidents_by_motivation -------------------------------------
    # COUNT(DISTINCT incident_id) per motivation. Per review priority
    # #4, this keeps "one incident with two motivations" contributing
    # +1 to each bucket (design intent — the natural reading of
    # "incidents by motivation"), without silently multiplying a
    # single row within a bucket. Future DQ / schema regressions on
    # the join table's PK still surface as the correct count rather
    # than a Cartesian-inflated one.
    motivation_stmt = (
        sa.select(
            incident_motivations_table.c.motivation,
            sa.func.count(
                sa.distinct(incident_motivations_table.c.incident_id)
            ).label("count"),
        )
        .select_from(
            incident_motivations_table.join(
                incidents_table,
                incident_motivations_table.c.incident_id == incidents_table.c.id,
            )
        )
        .group_by(incident_motivations_table.c.motivation)
        .order_by(incident_motivations_table.c.motivation.asc())
    )
    if date_from is not None:
        motivation_stmt = motivation_stmt.where(
            incidents_table.c.reported >= date_from
        )
    if date_to is not None:
        motivation_stmt = motivation_stmt.where(
            incidents_table.c.reported <= date_to
        )
    motivation_rows = (await session.execute(motivation_stmt)).all()
    incidents_by_motivation = [
        {"motivation": row.motivation, "count": int(row.count)}
        for row in motivation_rows
    ]

    # ---- top_groups --------------------------------------------------
    # Join chain: groups ← codenames ← report_codenames ← reports.
    # COUNT(DISTINCT report_id) dedupes the "one report → two
    # codenames in the same group" case so the report contributes +1
    # to that group's bucket exactly. Order by count DESC then
    # group_id ASC — the id tiebreaker keeps repeat calls stable
    # when multiple groups share a report count (review priority #3).
    top_groups_stmt = (
        sa.select(
            groups_table.c.id.label("group_id"),
            groups_table.c.name,
            sa.func.count(sa.distinct(reports_table.c.id)).label("report_count"),
        )
        .select_from(
            groups_table.join(
                codenames_table, codenames_table.c.group_id == groups_table.c.id
            )
            .join(
                report_codenames_table,
                report_codenames_table.c.codename_id == codenames_table.c.id,
            )
            .join(
                reports_table,
                reports_table.c.id == report_codenames_table.c.report_id,
            )
        )
        .group_by(groups_table.c.id, groups_table.c.name)
        .order_by(sa.desc("report_count"), groups_table.c.id.asc())
        .limit(bounded_top_n)
    )
    if date_from is not None:
        top_groups_stmt = top_groups_stmt.where(
            reports_table.c.published >= date_from
        )
    if date_to is not None:
        top_groups_stmt = top_groups_stmt.where(
            reports_table.c.published <= date_to
        )
    if group_ids:
        top_groups_stmt = top_groups_stmt.where(groups_table.c.id.in_(group_ids))
    top_rows = (await session.execute(top_groups_stmt)).all()
    top_groups = [
        {
            "group_id": int(row.group_id),
            "name": row.name,
            "report_count": int(row.report_count),
        }
        for row in top_rows
    ]

    return {
        "total_reports": total_reports,
        "total_incidents": total_incidents,
        "total_actors": total_actors,
        "reports_by_year": reports_by_year,
        "incidents_by_motivation": incidents_by_motivation,
        "top_groups": top_groups,
    }


__all__ = ["compute_dashboard_summary"]
