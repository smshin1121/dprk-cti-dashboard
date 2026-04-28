"""Analytics aggregators (PR #13 Group A).

Three read-only aggregations feed the Phase 2.4 dashboard visualizations:

    compute_attack_matrix(session, ...)  → AttackMatrixResponse payload
    compute_trend(session, ...)          → TrendResponse payload
    compute_geo(session, ...)            → GeoResponse payload

Plan D2 locks the wire shape, the filter contract, and the semantics
below. Each function returns a plain ``dict`` the router hands to the
corresponding Pydantic response model (``model_validate``).

Filter contract (shared with ``/dashboard/summary`` where meaningful):

- ``date_from`` / ``date_to`` filter the primary date column of each
  aggregation's root table — ``reports.published`` for
  ``attack_matrix`` and ``trend``, ``incidents.reported`` for ``geo``.
- ``group_ids`` applies to report-rooted aggregations via the chain
  ``reports ← report_codenames ← codenames → groups``. For ``geo`` the
  filter is a **documented no-op** — the schema has no path from
  ``incidents`` to ``groups`` (same constraint as the dashboard
  ``incidents_by_motivation`` aggregate). Passing the param is allowed
  for API uniformity but does not change the ``geo`` response.

Invariants enforced here (review priorities carried from PR #11):

1. No JOIN inflation. All counts that live above a join use
   ``COUNT(DISTINCT <pk>)`` so a report with two techniques in the
   same tactic contributes +1 per (tactic, technique), never squared.
2. Null ``techniques.tactic`` rows are filtered out of the matrix.
   Treating a null tactic as a sentinel bucket would let DQ rot leak
   into the chart; making it a hard filter keeps the response
   predictable.
3. ``top_n`` in ``compute_attack_matrix`` is defensively clamped to
   ``[1, _TOP_N_MAX]`` even though the router ``Query`` layer already
   bounds it — direct function calls (unit tests, future reuse) cannot
   bypass the limit.
4. Empty input returns empty-but-well-formed dicts, not None / missing
   keys. The Pydantic DTOs carry ``default_factory=list`` but the
   aggregator emits ``[]`` explicitly so both sides of the contract
   agree when the next layer (pact verification, FE Zod parse) runs.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.read import INCIDENTS_TREND_UNKNOWN_KEY
from ..tables import (
    codenames_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    report_codenames_table,
    report_techniques_table,
    reports_table,
    techniques_table,
)
from .repositories import _resolve_dialect


_TOP_N_MAX = 200
_DEFAULT_TOP_N = 30


def _month_expr(
    col: sa.sql.ColumnElement[date], dialect: str
) -> sa.sql.ColumnElement[str]:
    """Portable ``YYYY-MM`` month-bucket expression.

    PG uses ``to_char(col, 'YYYY-MM')``; sqlite uses
    ``strftime('%Y-%m', col)``. Both return a zero-padded string the
    ``TrendBucket.month`` pattern accepts.
    """
    if dialect == "postgresql":
        return sa.func.to_char(col, "YYYY-MM")
    return sa.func.strftime("%Y-%m", col)


def _reports_group_exists_clause(
    group_ids: list[int],
) -> sa.sql.ColumnElement[bool]:
    """EXISTS subquery filtering reports by attributed group.

    The reports table has no direct ``group_id`` column; attribution
    runs through ``reports ← report_codenames → codenames → groups``.
    An EXISTS subquery avoids double-counting reports that belong to
    multiple codenames in the same group, which an INNER JOIN would
    need a DISTINCT to undo.
    """
    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(
            report_codenames_table.join(
                codenames_table,
                codenames_table.c.id == report_codenames_table.c.codename_id,
            )
        )
        .where(
            report_codenames_table.c.report_id == reports_table.c.id,
            codenames_table.c.group_id.in_(group_ids),
        )
    )


async def compute_attack_matrix(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    group_ids: list[int] | None = None,
    top_n: int = _DEFAULT_TOP_N,
) -> dict[str, object]:
    """Build the tactic × technique matrix payload.

    Query plan (single statement, grouped in SQL, re-grouped in Python
    for the two-level response shape):

    1. Join ``report_techniques → techniques → reports``.
    2. Filter: non-null tactic, date window, optional group chain.
    3. Aggregate: ``COUNT(DISTINCT report_id)`` per
       ``(tactic, mitre_id)`` pair.
    4. Order by count desc, mitre_id asc; LIMIT ``top_n``.
    5. Bucket the returned rows by tactic; build the rows list and the
       tactics list (ordered by total count within that tactic desc,
       tactic_id asc for stability).
    """
    bounded_top_n = max(1, min(top_n, _TOP_N_MAX))

    count_col = sa.func.count(
        sa.distinct(report_techniques_table.c.report_id)
    ).label("count")

    stmt = (
        sa.select(
            techniques_table.c.tactic.label("tactic"),
            techniques_table.c.mitre_id.label("technique_id"),
            count_col,
        )
        .select_from(
            report_techniques_table.join(
                techniques_table,
                techniques_table.c.id == report_techniques_table.c.technique_id,
            ).join(
                reports_table,
                reports_table.c.id == report_techniques_table.c.report_id,
            )
        )
        .where(techniques_table.c.tactic.is_not(None))
        .group_by(techniques_table.c.tactic, techniques_table.c.mitre_id)
        .order_by(sa.desc("count"), techniques_table.c.mitre_id.asc())
        .limit(bounded_top_n)
    )
    if date_from is not None:
        stmt = stmt.where(reports_table.c.published >= date_from)
    if date_to is not None:
        stmt = stmt.where(reports_table.c.published <= date_to)
    if group_ids:
        stmt = stmt.where(_reports_group_exists_clause(group_ids))

    rows = (await session.execute(stmt)).all()

    # Bucket rows by tactic, preserving (count desc, mitre_id asc)
    # inside each bucket because that was the SQL-level sort.
    by_tactic: dict[str, list[dict[str, object]]] = {}
    totals: dict[str, int] = {}
    for row in rows:
        tactic_id = row.tactic
        technique_id = row.technique_id
        count = int(row.count)
        by_tactic.setdefault(tactic_id, []).append(
            {"technique_id": technique_id, "count": count}
        )
        totals[tactic_id] = totals.get(tactic_id, 0) + count

    # Tactics ordered by total count desc, tactic_id asc tiebreaker.
    ordered_tactics = sorted(
        by_tactic.keys(), key=lambda tid: (-totals[tid], tid)
    )

    tactics = [{"id": tid, "name": tid} for tid in ordered_tactics]
    response_rows = [
        {"tactic_id": tid, "techniques": by_tactic[tid]}
        for tid in ordered_tactics
    ]

    return {"tactics": tactics, "rows": response_rows}


async def compute_trend(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    group_ids: list[int] | None = None,
) -> dict[str, object]:
    """Build the monthly report-volume trend payload.

    ``count`` is ``COUNT(DISTINCT reports.id)`` per calendar month of
    ``reports.published`` (date-only column — no TZ ambiguity). Zero-
    count months are omitted, not zero-filled; the FE decides cadence.
    Buckets are sorted ascending by ``month``.
    """
    dialect = _resolve_dialect(session)
    month_col = _month_expr(reports_table.c.published, dialect).label("month")

    stmt = (
        sa.select(
            month_col,
            sa.func.count(sa.distinct(reports_table.c.id)).label("count"),
        )
        .select_from(reports_table)
        .group_by(month_col)
        .order_by(month_col.asc())
    )
    if date_from is not None:
        stmt = stmt.where(reports_table.c.published >= date_from)
    if date_to is not None:
        stmt = stmt.where(reports_table.c.published <= date_to)
    if group_ids:
        stmt = stmt.where(_reports_group_exists_clause(group_ids))

    rows = (await session.execute(stmt)).all()
    buckets = [
        {"month": row.month, "count": int(row.count)}
        for row in rows
        if row.month is not None
    ]
    return {"buckets": buckets}


async def compute_geo(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    group_ids: list[int] | None = None,  # accepted for uniformity, no-op here
) -> dict[str, object]:
    """Build the country-aggregated incident count payload.

    ``count`` is ``COUNT(DISTINCT incident_id)`` per ``country_iso2``.
    DPRK (``KP``) appears as a plain row when present — no special-case
    field (plan D2 + D7 locks; FE owns the highlight).

    The ``group_ids`` parameter is accepted for API uniformity with the
    other analytics endpoints but does not filter the response — the
    schema has no path from ``incidents`` to ``groups``. Same constraint
    as ``compute_dashboard_summary``'s ``incidents_by_motivation``
    aggregate (documented there too).
    """
    # Silence the unused argument without letting it drift — we
    # accept it at the API layer and explicitly drop it here.
    del group_ids

    stmt = (
        sa.select(
            incident_countries_table.c.country_iso2.label("iso2"),
            sa.func.count(
                sa.distinct(incident_countries_table.c.incident_id)
            ).label("count"),
        )
        .select_from(
            incident_countries_table.join(
                incidents_table,
                incidents_table.c.id == incident_countries_table.c.incident_id,
            )
        )
        .group_by(incident_countries_table.c.country_iso2)
        .order_by(sa.desc("count"), incident_countries_table.c.country_iso2.asc())
    )
    if date_from is not None:
        stmt = stmt.where(incidents_table.c.reported >= date_from)
    if date_to is not None:
        stmt = stmt.where(incidents_table.c.reported <= date_to)

    rows = (await session.execute(stmt)).all()
    countries = [
        {"iso2": row.iso2, "count": int(row.count)} for row in rows
    ]
    return {"countries": countries}


async def compute_incidents_trend(
    session: AsyncSession,
    *,
    group_by: Literal["motivation", "sector"],
    date_from: date | None = None,
    date_to: date | None = None,
    group_ids: list[int] | None = None,  # accepted for uniformity, no-op
) -> dict[str, object]:
    """Build the monthly incidents trend payload, sliced by motivation or sector.

    Distinct from ``compute_trend``: fact table is ``incidents`` (not
    ``reports``), bucketed by ``incidents.reported`` (NOT NULL only --
    same upstream filter as the list-endpoint cursor convention; see
    ``tables.py:258-261``). Each bucket carries a ``series`` slice of
    motivation or sector membership counts. PR #23 C1 lock.

    Outer ``count`` semantics: it is the **number of distinct
    incidents** in the month. An incident linked to N motivations (or
    N sectors) contributes +1 to the outer monthly count and +1 to
    each relevant series key, so ``sum(series[].count)`` may exceed
    the outer count for multi-category incidents. Incidents with no
    junction row still contribute to the outer count and land in the
    ``INCIDENTS_TREND_UNKNOWN_KEY`` slice via COALESCE.

    ``group_ids`` is accepted for API uniformity with the other
    analytics endpoints but is a documented no-op -- the schema has no
    path from ``incidents`` to ``groups`` (same constraint as
    ``compute_geo`` and ``compute_dashboard_summary``'s
    ``incidents_by_motivation`` aggregate).
    """
    del group_ids  # accepted-for-uniformity sink

    dialect = _resolve_dialect(session)
    month_col = _month_expr(incidents_table.c.reported, dialect).label("month")

    if group_by == "motivation":
        junction = incident_motivations_table
        key_source = junction.c.motivation
    else:
        junction = incident_sectors_table
        key_source = junction.c.sector_code

    series_key = sa.func.coalesce(
        key_source, sa.literal(INCIDENTS_TREND_UNKNOWN_KEY)
    ).label("key")

    monthly_stmt = (
        sa.select(
            month_col,
            sa.func.count(sa.distinct(incidents_table.c.id)).label("count"),
        )
        .where(incidents_table.c.reported.is_not(None))
        .group_by(month_col)
        .order_by(month_col.asc())
    )

    series_stmt = (
        sa.select(
            month_col,
            series_key,
            sa.func.count(sa.distinct(incidents_table.c.id)).label("count"),
        )
        .select_from(
            incidents_table.outerjoin(
                junction, junction.c.incident_id == incidents_table.c.id
            )
        )
        .where(incidents_table.c.reported.is_not(None))
        .group_by(month_col, series_key)
        .order_by(month_col.asc(), series_key.asc())
    )
    if date_from is not None:
        monthly_stmt = monthly_stmt.where(incidents_table.c.reported >= date_from)
        series_stmt = series_stmt.where(incidents_table.c.reported >= date_from)
    if date_to is not None:
        monthly_stmt = monthly_stmt.where(incidents_table.c.reported <= date_to)
        series_stmt = series_stmt.where(incidents_table.c.reported <= date_to)

    monthly_rows = (await session.execute(monthly_stmt)).all()
    series_rows = (await session.execute(series_stmt)).all()

    # Fold flat (month, key, count) tuples into nested buckets. The
    # SQL ORDER BY ascending pins month order; series order is
    # likewise stable but the test surface re-sorts by key for
    # readability so the aggregator does not promise series order.
    buckets: dict[str, dict[str, object]] = {}
    for row in monthly_rows:
        if row.month is None:
            # Defensive -- `IS NOT NULL` filter should already exclude
            # this. Belt-and-braces in case a dialect returns NULL for
            # the month expression itself.
            continue
        buckets[row.month] = {
            "month": row.month,
            "count": int(row.count),
            "series": [],
        }

    for row in series_rows:
        if row.month is None:
            continue
        bucket = buckets.setdefault(
            row.month,
            {"month": row.month, "count": 0, "series": []},
        )
        slice_count = int(row.count)
        series_list: list[dict[str, object]] = bucket["series"]  # type: ignore[assignment]
        series_list.append({"key": row.key, "count": slice_count})

    return {
        "buckets": list(buckets.values()),
        "group_by": group_by,
    }


__all__ = [
    "compute_attack_matrix",
    "compute_geo",
    "compute_incidents_trend",
    "compute_trend",
]
