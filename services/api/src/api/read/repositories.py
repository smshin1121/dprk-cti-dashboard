"""Read-path repositories for PR #11 endpoints.

Each function here is a thin DB adapter — it runs one or two SELECT
statements and returns primitives the router can hand straight to the
DTO constructor. No business logic, no filtering beyond what the
caller passed in, no caching. Caching and materialized views are
plan §7.7 Phase 4 W4 work.

Group B lands the actors query only. Groups C–E extend this module
with reports / incidents / dashboard-summary queries. The file is
organized by endpoint so each group's diff stays localized.

Portability: all queries must work on both PG and in-memory sqlite
so the Group A/B unit tests can exercise the real SQL without a
live Postgres. Dialect-specific helpers (``array_agg``, ``ILIKE``,
``DISTINCT ON``) are swapped via ``sa.dialect.name`` checks or
via ``sa.Function`` indirection — see the codename aggregation
below for the pattern.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import (
    codenames_table,
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
)


# ---------------------------------------------------------------------------
# /actors — offset-paginated list (plan D3 / D11)
# ---------------------------------------------------------------------------


async def count_actors(session: AsyncSession) -> int:
    """Total row count for ``/actors`` offset pagination.

    A separate COUNT query rather than a window function because the
    page query already returns ordered rows with LIMIT/OFFSET —
    adding ``COUNT(*) OVER ()`` would require un-sorting to avoid
    double-sorting and complicate the SQL for a trivial optimization.
    Plan D3 accepted offset for actors precisely because the group
    count is small enough that a bare COUNT is cheap.
    """
    result = await session.execute(sa.select(sa.func.count()).select_from(groups_table))
    return int(result.scalar_one())


def _resolve_dialect(session: AsyncSession) -> str:
    """Safely extract the dialect name from an async session.

    Uses ``session.get_bind()`` rather than the deprecated
    ``session.bind`` attribute (Round 0 P2-2 flagged the latter as
    fragile: ``session.bind`` can be ``None`` on sessions created
    without an explicit bind, and pyright / mypy both want a type
    ignore). ``get_bind()`` raises ``UnboundExecutionError`` if the
    session truly has no engine, which surfaces as a 500 with a
    useful traceback instead of a silent ``AttributeError``.
    """
    return session.get_bind().dialect.name


async def list_actors(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Fetch one page of actors + total count.

    Returns ``(rows, total)`` where each row is a dict shaped for
    ``ActorItem.model_validate``. The router materializes the DTO.

    Sort lock (plan D11): ``name ASC, id ASC``. ``id`` as tiebreaker
    is defensive against duplicate names — ``groups.name`` is UNIQUE
    so ties are structurally impossible, but the sort spec stays
    explicit so an accidental name-collapse never reorders output.

    Portable codename aggregation: PG uses ``array_agg``, sqlite
    uses ``group_concat``. The dialect branch lives here (not in
    the router) so the rest of the codebase sees one return shape.
    """
    dialect = _resolve_dialect(session)

    if dialect == "postgresql":
        codenames_col = sa.func.array_agg(codenames_table.c.name).filter(
            codenames_table.c.name.isnot(None)
        )
    else:
        # sqlite + any other dialect without array_agg
        codenames_col = sa.func.group_concat(codenames_table.c.name, ",")

    stmt = (
        sa.select(
            groups_table.c.id,
            groups_table.c.name,
            groups_table.c.mitre_intrusion_set_id,
            groups_table.c.aka,
            groups_table.c.description,
            codenames_col.label("codenames_raw"),
        )
        .select_from(
            groups_table.outerjoin(
                codenames_table,
                codenames_table.c.group_id == groups_table.c.id,
            )
        )
        .group_by(
            groups_table.c.id,
            groups_table.c.name,
            groups_table.c.mitre_intrusion_set_id,
            groups_table.c.aka,
            groups_table.c.description,
        )
        .order_by(groups_table.c.name.asc(), groups_table.c.id.asc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(stmt)
    rows = result.mappings().all()

    items: list[dict[str, object]] = []
    for row in rows:
        raw = row["codenames_raw"]
        if raw is None:
            codenames: list[str] = []
        elif isinstance(raw, list):
            # PG array_agg → already a list. Filter stripped NULLs.
            codenames = [c for c in raw if c is not None]
        else:
            # sqlite group_concat → comma-joined string. Empty groups
            # produce "" here under the outer join — coerce to [].
            codenames = [s for s in str(raw).split(",") if s]

        items.append(
            {
                "id": row["id"],
                "name": row["name"],
                "mitre_intrusion_set_id": row["mitre_intrusion_set_id"],
                "aka": list(row["aka"]) if row["aka"] is not None else [],
                "description": row["description"],
                "codenames": codenames,
            }
        )

    total = await count_actors(session)
    return items, total


# ---------------------------------------------------------------------------
# /reports — keyset-paginated list (plan D3 / D5 / D11)
# ---------------------------------------------------------------------------


def _apply_report_filters(
    stmt: sa.sql.Select,
    *,
    q: str | None,
    tags: list[str] | None,
    sources: list[str] | None,
    date_from: date | None,
    date_to: date | None,
) -> sa.sql.Select:
    """Attach filter predicates to a reports SELECT.

    Filter composition (plan D5 — locked semantics):

    - **Within a repeatable param**: OR. ``?tag=a&tag=b`` returns
      reports that carry tag ``a`` **or** ``b``.
    - **Between distinct filters**: AND. ``?tag=a&source=Mandiant``
      returns reports tagged ``a`` **and** sourced from Mandiant.

    JOIN strategy: ``EXISTS (SELECT 1 FROM report_tags JOIN tags ...)``
    rather than a direct INNER JOIN. An INNER JOIN on report_tags
    would duplicate each report row once per matching tag, breaking
    the keyset cursor ordering and page-size invariants. ``DISTINCT``
    on the reports side would dedupe but then the ORDER BY needs
    to include every SELECT column, which the cursor tie-breaker
    cannot satisfy portably. ``EXISTS`` keeps one row per report by
    construction and is index-friendly on ``(report_id, tag_id)``.
    """
    if q is not None:
        stmt = stmt.where(reports_table.c.title.ilike(f"%{q}%"))

    if tags:
        # ANY-match on repeatable tag values.
        stmt = stmt.where(
            sa.exists(
                sa.select(sa.literal(1))
                .select_from(
                    report_tags_table.join(
                        tags_table, report_tags_table.c.tag_id == tags_table.c.id
                    )
                )
                .where(
                    (report_tags_table.c.report_id == reports_table.c.id)
                    & (tags_table.c.name.in_(tags))
                )
            )
        )

    if sources:
        # sources_table is already LEFT-OUTER-joined in the outer
        # SELECT for source_name, so the filter is a plain IN on
        # that joined column. No EXISTS subquery needed (an EXISTS
        # over the same already-correlated table triggers SA's
        # auto-correlation and strips the subquery's FROM clause).
        # Row count is preserved because reports.source_id → sources
        # is a 1:N→1 relationship (sources.name is UNIQUE), so the
        # outer join produces exactly one row per report. Reports
        # with NULL source_id are naturally excluded by IN being
        # FALSE on NULL — which is the desired filter semantic
        # (``?source=X`` means "report IS sourced from X").
        stmt = stmt.where(sources_table.c.name.in_(sources))

    if date_from is not None:
        stmt = stmt.where(reports_table.c.published >= date_from)
    if date_to is not None:
        stmt = stmt.where(reports_table.c.published <= date_to)

    return stmt


async def list_reports(
    session: AsyncSession,
    *,
    limit: int,
    cursor_published: date | None = None,
    cursor_id: int | None = None,
    q: str | None = None,
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[dict[str, object]], date | None, int | None]:
    """Fetch one keyset page of reports.

    Returns ``(items, next_published, next_id)``. When the result
    exhausts the table, ``next_published`` and ``next_id`` are both
    ``None``; otherwise they carry the last item's sort key for the
    router to encode into an opaque cursor.

    Sort lock (plan D11): ``published DESC, id DESC``. The cursor
    condition mirrors this:
        ``(published < cursor_published)
         OR (published = cursor_published AND id < cursor_id)``
    ``id`` tiebreaker prevents same-day reports from silently
    duplicating or skipping across pages.

    Fetching ``limit + 1`` rows lets the caller decide whether a
    next page exists without a second COUNT query. The extra row
    is dropped before returning; its sort key becomes the next
    cursor seed.
    """
    stmt = (
        sa.select(
            reports_table.c.id,
            reports_table.c.title,
            reports_table.c.url,
            reports_table.c.url_canonical,
            reports_table.c.published,
            reports_table.c.source_id,
            sources_table.c.name.label("source_name"),
            reports_table.c.lang,
            reports_table.c.tlp,
        )
        .select_from(
            reports_table.outerjoin(
                sources_table,
                reports_table.c.source_id == sources_table.c.id,
            )
        )
    )

    stmt = _apply_report_filters(
        stmt,
        q=q,
        tags=tags,
        sources=sources,
        date_from=date_from,
        date_to=date_to,
    )

    # Cursor predicate — applied AFTER filters so the cursor keyset
    # is relative to the filtered result set.
    if cursor_published is not None and cursor_id is not None:
        stmt = stmt.where(
            (reports_table.c.published < cursor_published)
            | (
                (reports_table.c.published == cursor_published)
                & (reports_table.c.id < cursor_id)
            )
        )

    stmt = (
        stmt.order_by(reports_table.c.published.desc(), reports_table.c.id.desc())
        .limit(limit + 1)
    )

    result = await session.execute(stmt)
    rows = result.mappings().all()

    has_next = len(rows) > limit
    page_rows = rows[:limit]

    items: list[dict[str, object]] = [
        {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "url_canonical": row["url_canonical"],
            "published": row["published"],
            "source_id": row["source_id"],
            "source_name": row["source_name"],
            "lang": row["lang"],
            "tlp": row["tlp"],
        }
        for row in page_rows
    ]

    if has_next and page_rows:
        last = page_rows[-1]
        return items, last["published"], int(last["id"])
    return items, None, None


# ---------------------------------------------------------------------------
# /incidents — keyset-paginated list with multi-join aggregation
# ---------------------------------------------------------------------------


def _apply_incident_filters(
    stmt: sa.sql.Select,
    *,
    date_from: date | None,
    date_to: date | None,
    motivations: list[str] | None,
    sectors: list[str] | None,
    countries: list[str] | None,
) -> sa.sql.Select:
    """Attach filter predicates to an incidents SELECT.

    Same AND/OR composition as ``_apply_report_filters`` (plan D5):
    OR within a repeatable, AND across distinct filters. Each
    M:N join (motivations / sectors / countries) goes through a
    separate ``EXISTS`` so the outer row count stays one per
    incident regardless of how many rows match on each side.
    """
    if date_from is not None:
        stmt = stmt.where(incidents_table.c.reported >= date_from)
    if date_to is not None:
        stmt = stmt.where(incidents_table.c.reported <= date_to)

    if motivations:
        stmt = stmt.where(
            sa.exists(
                sa.select(sa.literal(1))
                .select_from(incident_motivations_table)
                .where(
                    (incident_motivations_table.c.incident_id == incidents_table.c.id)
                    & (incident_motivations_table.c.motivation.in_(motivations))
                )
            )
        )

    if sectors:
        stmt = stmt.where(
            sa.exists(
                sa.select(sa.literal(1))
                .select_from(incident_sectors_table)
                .where(
                    (incident_sectors_table.c.incident_id == incidents_table.c.id)
                    & (incident_sectors_table.c.sector_code.in_(sectors))
                )
            )
        )

    if countries:
        stmt = stmt.where(
            sa.exists(
                sa.select(sa.literal(1))
                .select_from(incident_countries_table)
                .where(
                    (incident_countries_table.c.incident_id == incidents_table.c.id)
                    & (incident_countries_table.c.country_iso2.in_(countries))
                )
            )
        )

    return stmt


def _incident_aggregate_subqueries(
    dialect: str,
) -> tuple[sa.sql.Select, sa.sql.Select, sa.sql.Select]:
    """Build three correlated scalar subqueries for the motivations /
    sectors / countries aggregates.

    Correlated-subquery strategy keeps the outer row count invariant:
    each subquery returns ONE aggregated value per incident, so a
    LEFT JOIN's Cartesian multiplication across the three M:N tables
    never occurs. This is why Group D could not reuse the
    LEFT-JOIN + GROUP BY pattern — 2 motivations × 3 sectors × 2
    countries would give 12 rows per incident, and the keyset cursor
    relies on distinct ``(reported, id)`` tuples.

    Aggregation function dispatches on dialect:
    - PG: ``array_agg(col)`` returns a Python list via psycopg's
      native array decoding.
    - sqlite: ``group_concat(col, ',')`` returns a comma string; the
      caller splits on comma and also sorts for stable output.

    The caller normalizes the result to a sorted list so reports
    with the same values always see the same array order (review
    priority #3 — stable order for aggregated arrays).
    """
    if dialect == "postgresql":
        motivations = sa.func.array_agg(incident_motivations_table.c.motivation)
        sectors = sa.func.array_agg(incident_sectors_table.c.sector_code)
        countries = sa.func.array_agg(incident_countries_table.c.country_iso2)
    else:
        motivations = sa.func.group_concat(
            incident_motivations_table.c.motivation, ","
        )
        sectors = sa.func.group_concat(incident_sectors_table.c.sector_code, ",")
        countries = sa.func.group_concat(incident_countries_table.c.country_iso2, ",")

    motivations_subq = (
        sa.select(motivations)
        .where(incident_motivations_table.c.incident_id == incidents_table.c.id)
        .correlate(incidents_table)
        .scalar_subquery()
    )
    sectors_subq = (
        sa.select(sectors)
        .where(incident_sectors_table.c.incident_id == incidents_table.c.id)
        .correlate(incidents_table)
        .scalar_subquery()
    )
    countries_subq = (
        sa.select(countries)
        .where(incident_countries_table.c.incident_id == incidents_table.c.id)
        .correlate(incidents_table)
        .scalar_subquery()
    )
    return motivations_subq, sectors_subq, countries_subq


def _normalize_aggregate(raw: object | None) -> list[str]:
    """Coerce the aggregate column (PG list vs sqlite string vs
    NULL) into a sorted unique list.

    Stable output order (review priority #3): sort ascending so
    repeated calls return identical arrays for the same underlying
    rows. ``set()`` dedups any rare duplicates — a row-level primary
    key on the join table prevents duplicates, but the sort is
    applied before dedup so a regression in the schema surfaces as
    a differently-ordered array rather than a flaky test.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        values = [v for v in raw if v is not None]
    else:
        values = [v for v in str(raw).split(",") if v]
    return sorted(set(values))


async def list_incidents(
    session: AsyncSession,
    *,
    limit: int,
    cursor_reported: date | None = None,
    cursor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    motivations: list[str] | None = None,
    sectors: list[str] | None = None,
    countries: list[str] | None = None,
) -> tuple[list[dict[str, object]], date | None, int | None]:
    """Fetch one keyset page of incidents.

    Returns ``(items, next_reported, next_id)``. Null-reported
    incidents are excluded (``WHERE reported IS NOT NULL``) because
    the cursor codec only accepts a date value — surfacing null
    rows here would break cursor pagination boundaries. Detail
    endpoints (Phase 3) can expose them separately.

    Sort lock (plan D11): ``reported DESC, id DESC``. Cursor
    predicate mirrors:
        ``(reported < cursor.reported)
         OR (reported = cursor.reported AND id < cursor.id)``

    One-row-per-incident: three correlated scalar subqueries
    aggregate motivations / sectors / countries. See
    ``_incident_aggregate_subqueries`` for why LEFT JOIN + GROUP BY
    is wrong here.
    """
    dialect = _resolve_dialect(session)
    motivations_col, sectors_col, countries_col = _incident_aggregate_subqueries(
        dialect
    )

    stmt = (
        sa.select(
            incidents_table.c.id,
            incidents_table.c.reported,
            incidents_table.c.title,
            incidents_table.c.description,
            incidents_table.c.est_loss_usd,
            incidents_table.c.attribution_confidence,
            motivations_col.label("motivations_raw"),
            sectors_col.label("sectors_raw"),
            countries_col.label("countries_raw"),
        )
        .where(incidents_table.c.reported.isnot(None))
    )

    stmt = _apply_incident_filters(
        stmt,
        date_from=date_from,
        date_to=date_to,
        motivations=motivations,
        sectors=sectors,
        countries=countries,
    )

    if cursor_reported is not None and cursor_id is not None:
        stmt = stmt.where(
            (incidents_table.c.reported < cursor_reported)
            | (
                (incidents_table.c.reported == cursor_reported)
                & (incidents_table.c.id < cursor_id)
            )
        )

    stmt = (
        stmt.order_by(
            incidents_table.c.reported.desc(), incidents_table.c.id.desc()
        ).limit(limit + 1)
    )

    result = await session.execute(stmt)
    rows = result.mappings().all()

    has_next = len(rows) > limit
    page_rows = rows[:limit]

    items: list[dict[str, object]] = [
        {
            "id": row["id"],
            "reported": row["reported"],
            "title": row["title"],
            "description": row["description"],
            "est_loss_usd": row["est_loss_usd"],
            "attribution_confidence": row["attribution_confidence"],
            "motivations": _normalize_aggregate(row["motivations_raw"]),
            "sectors": _normalize_aggregate(row["sectors_raw"]),
            "countries": _normalize_aggregate(row["countries_raw"]),
        }
        for row in page_rows
    ]

    if has_next and page_rows:
        last = page_rows[-1]
        return items, last["reported"], int(last["id"])
    return items, None, None


__all__ = [
    "count_actors",
    "list_actors",
    "list_incidents",
    "list_reports",
]
