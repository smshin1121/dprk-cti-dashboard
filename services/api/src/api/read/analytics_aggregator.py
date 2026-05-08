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
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incident_sources_table,
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


_RESCUE_EDGE_CAP = 5


def _kind_of(node_id: str) -> str:
    """Extract the kind prefix from a kind-prefixed node id."""

    return node_id.split(":", 1)[0]


_KIND_ORDER = {"actor": 0, "tool": 1, "sector": 2}


async def compute_actor_network(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    group_ids: list[int] | None = None,
    top_n_actor: int = 25,
    top_n_tool: int = 25,
    top_n_sector: int = 25,
) -> dict[str, object]:
    """``/api/v1/analytics/actor_network`` SNA co-occurrence aggregator.

    Plan ``docs/plans/actor-network-data.md`` v1.4 — L1, L2 wire shape,
    L3 three edge classes, L4 ordered Steps A-F, L6 empty contract,
    L7 group filter precedence, L13 kind-prefixed node IDs.

    Algorithm:
        Step A — compute the 3 edge classes (a) actor↔tool, (b)
                 actor↔sector, (c) actor↔actor with COUNT(DISTINCT)
                 weights; apply date filter; apply ``group_ids[]``
                 eligibility filter.
        Step B — actor slate cap-aware: ``S = selected eligible
                 actors``; selected always count toward ``top_n_actor``;
                 fillers from non-selected by **GLOBAL** degree.
        Step C — tool/sector cuts within eligible edge set.
        Step D — first-pass edges (both endpoints in cut).
        Step E — high-weight rescue within eligible edge set; top 5
                 by weight; rescued endpoints exempt from per-kind cap.
        Step F — assemble response with stable ordering.

    Returns the bare dict shape that ``ActorNetworkResponse`` parses.
    """

    # =========================================================================
    # Step A — compute the three edge classes
    # =========================================================================
    #
    # All three classes share the date filter on a "fact" table:
    #   (a) actor↔tool   — filter on reports.published
    #   (b) actor↔sector — filter on incidents.reported
    #   (c) actor↔actor  — filter on reports.published
    #
    # ``COUNT(DISTINCT report_id|incidents.id)`` collapses self-join
    # inflation when one fact row is multi-named (multiple codenames
    # for the same group on the same report) or multi-sourced
    # (one incident with multiple incident_sources).

    actor_tool_query = (
        sa.select(
            codenames_table.c.group_id.label("group_id"),
            report_techniques_table.c.technique_id.label("technique_id"),
            sa.func.count(
                sa.distinct(report_codenames_table.c.report_id)
            ).label("weight"),
        )
        .select_from(report_codenames_table)
        .join(
            codenames_table,
            codenames_table.c.id == report_codenames_table.c.codename_id,
        )
        .join(
            report_techniques_table,
            report_techniques_table.c.report_id
            == report_codenames_table.c.report_id,
        )
        .join(
            reports_table,
            reports_table.c.id == report_codenames_table.c.report_id,
        )
        .where(codenames_table.c.group_id.is_not(None))
    )
    if date_from is not None:
        actor_tool_query = actor_tool_query.where(
            reports_table.c.published >= date_from
        )
    if date_to is not None:
        actor_tool_query = actor_tool_query.where(
            reports_table.c.published <= date_to
        )
    actor_tool_query = actor_tool_query.group_by(
        codenames_table.c.group_id, report_techniques_table.c.technique_id
    )

    actor_tool_rows = (await session.execute(actor_tool_query)).all()

    # ----- (b) actor↔sector via the 5-table chain -----
    actor_sector_query = (
        sa.select(
            codenames_table.c.group_id.label("group_id"),
            incident_sectors_table.c.sector_code.label("sector_code"),
            sa.func.count(sa.distinct(incidents_table.c.id)).label("weight"),
        )
        .select_from(incident_sectors_table)
        .join(
            incidents_table,
            incidents_table.c.id == incident_sectors_table.c.incident_id,
        )
        .join(
            incident_sources_table,
            incident_sources_table.c.incident_id == incidents_table.c.id,
        )
        .join(
            reports_table,
            reports_table.c.id == incident_sources_table.c.report_id,
        )
        .join(
            report_codenames_table,
            report_codenames_table.c.report_id == reports_table.c.id,
        )
        .join(
            codenames_table,
            codenames_table.c.id == report_codenames_table.c.codename_id,
        )
        .where(codenames_table.c.group_id.is_not(None))
    )
    if date_from is not None:
        actor_sector_query = actor_sector_query.where(
            incidents_table.c.reported >= date_from
        )
    if date_to is not None:
        actor_sector_query = actor_sector_query.where(
            incidents_table.c.reported <= date_to
        )
    actor_sector_query = actor_sector_query.group_by(
        codenames_table.c.group_id,
        incident_sectors_table.c.sector_code,
    )

    actor_sector_rows = (await session.execute(actor_sector_query)).all()

    # ----- (c) actor↔actor self-join, unordered pairs -----
    rc_a = report_codenames_table.alias("rc_a")
    rc_b = report_codenames_table.alias("rc_b")
    cn_a = codenames_table.alias("cn_a")
    cn_b = codenames_table.alias("cn_b")

    actor_actor_query = (
        sa.select(
            cn_a.c.group_id.label("group_a"),
            cn_b.c.group_id.label("group_b"),
            sa.func.count(sa.distinct(rc_a.c.report_id)).label("weight"),
        )
        .select_from(rc_a)
        .join(rc_b, rc_b.c.report_id == rc_a.c.report_id)
        .join(cn_a, cn_a.c.id == rc_a.c.codename_id)
        .join(cn_b, cn_b.c.id == rc_b.c.codename_id)
        .join(reports_table, reports_table.c.id == rc_a.c.report_id)
        .where(cn_a.c.group_id.is_not(None))
        .where(cn_b.c.group_id.is_not(None))
        .where(cn_a.c.group_id < cn_b.c.group_id)
    )
    if date_from is not None:
        actor_actor_query = actor_actor_query.where(
            reports_table.c.published >= date_from
        )
    if date_to is not None:
        actor_actor_query = actor_actor_query.where(
            reports_table.c.published <= date_to
        )
    actor_actor_query = actor_actor_query.group_by(
        cn_a.c.group_id, cn_b.c.group_id
    )

    actor_actor_rows = (await session.execute(actor_actor_query)).all()

    # ----- Normalize edges to (source_id, target_id, weight) tuples -----
    # Sectors use ``sector_code`` itself as both id and label, so no
    # ``sectors_referenced`` set is needed for label lookup.
    all_edges: list[tuple[str, str, int]] = []
    actors_referenced: set[int] = set()
    tools_referenced: set[int] = set()

    for row in actor_tool_rows:
        all_edges.append(
            (f"actor:{row.group_id}", f"tool:{row.technique_id}", int(row.weight))
        )
        actors_referenced.add(row.group_id)
        tools_referenced.add(row.technique_id)

    for row in actor_sector_rows:
        all_edges.append(
            (
                f"actor:{row.group_id}",
                f"sector:{row.sector_code}",
                int(row.weight),
            )
        )
        actors_referenced.add(row.group_id)

    for row in actor_actor_rows:
        all_edges.append(
            (f"actor:{row.group_a}", f"actor:{row.group_b}", int(row.weight))
        )
        actors_referenced.add(row.group_a)
        actors_referenced.add(row.group_b)

    # L6 empty-contract early return: no edges at all.
    if not all_edges:
        return {"nodes": [], "edges": [], "cap_breached": False}

    # ----- Apply group_ids[] eligibility filter (L7(a)) -----
    if group_ids:
        gid_set = set(group_ids)

        def _is_eligible(edge: tuple[str, str, int]) -> bool:
            src, tgt, _ = edge
            if src.startswith("actor:") and int(src.split(":", 1)[1]) in gid_set:
                return True
            if tgt.startswith("actor:") and int(tgt.split(":", 1)[1]) in gid_set:
                return True
            return False

        eligible_edges = [e for e in all_edges if _is_eligible(e)]
    else:
        eligible_edges = list(all_edges)

    # =========================================================================
    # Compute degrees (global + eligible) for downstream cuts
    # =========================================================================
    #
    # Degree = count of distinct connected nodes (NOT count of edges,
    # NOT sum of weights). For one node with N distinct neighbors, degree = N.
    # See plan L2 + Codex r4 CRITICAL fold.

    def _degree_map(
        edges: list[tuple[str, str, int]],
    ) -> tuple[dict[str, set[str]], dict[str, int]]:
        neighbors: dict[str, set[str]] = {}
        for src, tgt, _ in edges:
            neighbors.setdefault(src, set()).add(tgt)
            neighbors.setdefault(tgt, set()).add(src)
        return neighbors, {nid: len(ns) for nid, ns in neighbors.items()}

    _global_neighbors, global_degree = _degree_map(all_edges)
    _eligible_neighbors, eligible_degree = _degree_map(eligible_edges)

    # =========================================================================
    # Fetch labels for every referenced actor + tool (sectors use sector_code
    # itself as the label).
    # =========================================================================

    actor_labels: dict[int, str] = {}
    if actors_referenced:
        actor_label_rows = (
            await session.execute(
                sa.select(groups_table.c.id, groups_table.c.name).where(
                    groups_table.c.id.in_(actors_referenced)
                )
            )
        ).all()
        actor_labels = {r.id: r.name for r in actor_label_rows}

    tool_labels: dict[int, str] = {}
    if tools_referenced:
        tool_label_rows = (
            await session.execute(
                sa.select(
                    techniques_table.c.id, techniques_table.c.name
                ).where(techniques_table.c.id.in_(tools_referenced))
            )
        ).all()
        tool_labels = {r.id: r.name for r in tool_label_rows}

    def _label_for(node_id: str) -> str:
        kind, raw = node_id.split(":", 1)
        if kind == "actor":
            return actor_labels.get(int(raw), f"actor-{raw}")
        if kind == "tool":
            return tool_labels.get(int(raw), f"tool-{raw}")
        return raw  # sector — sector_code is the canonical label

    # =========================================================================
    # Step B — actor cut (cap-aware)
    # =========================================================================

    all_actor_ids = {nid for nid in global_degree if nid.startswith("actor:")}

    if group_ids:
        S_candidate = {f"actor:{gid}" for gid in group_ids}
        # An actor is "selected and present" iff it has at least one
        # eligible edge (per L4 Step B definition).
        S = {nid for nid in S_candidate if eligible_degree.get(nid, 0) >= 1}
    else:
        S = set()

    # L7(e): group_id[] containing only non-existent / no-edge group IDs
    # returns the empty contract. Detect this here so we don't surface
    # isolated non-selected actors as "context".
    if group_ids and not S:
        return {"nodes": [], "edges": [], "cap_breached": False}

    if len(S) >= top_n_actor:
        actor_slate_set = set(S)
        # ``cap_breached`` is True iff strictly more selected than the
        # cap allows. Equality-at-cap is NOT a breach.
        cap_breached = len(S) > top_n_actor
    else:
        # Fill remaining slots with non-selected by **GLOBAL** degree
        # (L7(b) clarification — pinned by
        # ``TestActorNetworkGroupCap::test_scenario_a_one_selected_displaces_one_non_selected``).
        non_selected = [
            nid
            for nid in all_actor_ids
            if nid not in S and global_degree.get(nid, 0) >= 1
        ]
        non_selected_sorted = sorted(
            non_selected,
            key=lambda nid: (-global_degree[nid], _label_for(nid)),
        )
        slots_remaining = top_n_actor - len(S)
        actor_slate_set = S | set(non_selected_sorted[:slots_remaining])
        cap_breached = False

    # =========================================================================
    # Step C — tool / sector cuts within the eligible edge set
    # =========================================================================

    def _cut_within(prefix: str, top_n: int) -> set[str]:
        candidates = [nid for nid in eligible_degree if nid.startswith(prefix)]
        return set(
            sorted(
                candidates,
                key=lambda nid: (-eligible_degree[nid], _label_for(nid)),
            )[:top_n]
        )

    tool_cut_set = _cut_within("tool:", top_n_tool)
    sector_cut_set = _cut_within("sector:", top_n_sector)

    cut_set = actor_slate_set | tool_cut_set | sector_cut_set

    # =========================================================================
    # Step D — first-pass edges (both endpoints in cut)
    # =========================================================================

    first_pass_edges: list[tuple[str, str, int]] = [
        e for e in eligible_edges if e[0] in cut_set and e[1] in cut_set
    ]
    first_pass_keys: set[tuple[str, str]] = {(e[0], e[1]) for e in first_pass_edges}

    # =========================================================================
    # Step E — high-weight rescue within the eligible edge set
    # =========================================================================
    #
    # Top ``_RESCUE_EDGE_CAP`` edges by weight in the eligible set are
    # always retained. Rescued endpoints (those that didn't survive the
    # per-kind cut) are added to the final node set. Tie-break by
    # (source_id, target_id) for determinism.

    eligible_sorted = sorted(
        eligible_edges, key=lambda e: (-e[2], e[0], e[1])
    )
    rescue_candidates = eligible_sorted[:_RESCUE_EDGE_CAP]

    rescued_node_ids: set[str] = set()
    rescue_edges: list[tuple[str, str, int]] = []
    for edge in rescue_candidates:
        src, tgt, _ = edge
        # Only "rescue" an edge whose endpoint(s) missed the cut.
        if src in cut_set and tgt in cut_set:
            continue
        if src not in cut_set:
            rescued_node_ids.add(src)
        if tgt not in cut_set:
            rescued_node_ids.add(tgt)
        if (src, tgt) not in first_pass_keys:
            rescue_edges.append(edge)

    # =========================================================================
    # Step F — assemble final response
    # =========================================================================

    final_node_ids = cut_set | rescued_node_ids

    def _node_sort_key(node_id: str) -> tuple[int, int, str]:
        return (
            _KIND_ORDER[_kind_of(node_id)],
            -global_degree.get(node_id, 0),
            _label_for(node_id),
        )

    nodes: list[dict[str, object]] = []
    for nid in sorted(final_node_ids, key=_node_sort_key):
        nodes.append(
            {
                "id": nid,
                "kind": _kind_of(nid),
                "label": _label_for(nid),
                "degree": global_degree.get(nid, 0),
            }
        )

    # Edges: combine first-pass + rescue then sort GLOBALLY by weight
    # desc + (source, target) lexicographic for stability. Codex r6
    # MEDIUM fold: bucket-then-concat could place a high-weight rescue
    # edge after lower-weight first-pass edges, which surprises FE
    # consumers expecting a single weight-desc ordering.
    combined_edges = sorted(
        first_pass_edges + rescue_edges, key=lambda e: (-e[2], e[0], e[1])
    )

    edges: list[dict[str, object]] = []
    for src, tgt, weight in combined_edges:
        edges.append(
            {"source_id": src, "target_id": tgt, "weight": int(weight)}
        )

    return {"nodes": nodes, "edges": edges, "cap_breached": cap_breached}


__all__ = [
    "compute_actor_network",
    "compute_attack_matrix",
    "compute_geo",
    "compute_incidents_trend",
    "compute_trend",
]
