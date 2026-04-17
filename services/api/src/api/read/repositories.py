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


__all__ = [
    "count_actors",
    "list_actors",
    "list_reports",
]
