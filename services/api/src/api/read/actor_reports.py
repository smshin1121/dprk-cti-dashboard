"""Reports-that-mention-an-actor read service — PR #15 Phase 3 slice 2.

Plan `docs/plans/pr15-actor-reports.md` (Status: Locked 2026-04-19).

One public entry point::

    get_actor_reports(
        session,
        *,
        actor_id,
        date_from=None,
        date_to=None,
        cursor_published=None,
        cursor_id=None,
        limit,
    ) -> tuple[list[dict], date | None, int | None] | None

Returns the same ``(items, next_published, next_id)`` triple that
``api.read.repositories.list_reports`` returns so the router can
encode the cursor the same way. Returns ``None`` when the actor id
is unknown — per D15(a) the router maps that to HTTP 404, not to a
200 empty envelope. All other empty cases (D15 b/c/d) collapse to
``([], None, None)`` — the analyst distinguishes "unknown actor" from
"known actor with no evidence yet" via the status code.

Design contract (plan D15-D17 / D9):

- **D17 Dedup via EXISTS subquery**, NOT DISTINCT over a multi-JOIN
  result. The base query is ``SELECT <ReportItem cols> FROM reports
  WHERE EXISTS (SELECT 1 FROM report_codenames rc JOIN codenames c ON
  c.id = rc.codename_id WHERE rc.report_id = reports.id AND
  c.group_id = :actor_id) ...``. No join fan-out, no DISTINCT, one
  row per report regardless of how many codenames a report links to.
  Portable across PG and sqlite (standard SQL).

- **D16 Keyset cursor** reuses the same ``(published, id)`` shape as
  ``list_reports``. The seek predicate is a tuple comparison:
  ``(reports.published, reports.id) < (:cursor_published, :cursor_id)``.
  Written as the two-part disjunction SQLAlchemy emits for both PG
  and sqlite — row-value syntax isn't portable to sqlite without an
  explicit feature check.

- **D15 Empty branches**:
    * (a) unknown actor id → return ``None`` (router → 404)
    * (b) actor with no codenames → ``([], None, None)``
    * (c) actor with codenames but no report_codenames rows
          → ``([], None, None)``
    * (d) filter excludes every candidate report → ``([], None, None)``
  Branches b/c/d fall out naturally from the EXISTS predicate + the
  filter conditions — no special-case code required. Branch (a)
  requires the explicit pre-check below.

- **D9 Envelope** — the ``items`` dict shape matches ``ReportItem``
  exactly (``id, title, url, url_canonical, published, source_id,
  source_name, lang, tlp``). The router wraps as ``ReportListResponse``
  — same envelope as ``/reports``. NO ``total``, NO ``limit`` echo.

- **D12 Regression** — this module does NOT touch ``ActorDetail``
  shape. Unit tests in ``test_actor_reports.py`` include an explicit
  "actor detail response has no linked_reports key" assertion so the
  two surfaces stay structurally separate.

Portability: queries run on both PG and in-memory sqlite; unit tests
exercise real SQL without a live Postgres. No dialect-specific SQL
functions are used — EXISTS, IN, tuple-comparison via boolean
disjunction, and OUTER JOIN are all ANSI SQL common to both.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import (
    codenames_table,
    groups_table,
    report_codenames_table,
    reports_table,
    sources_table,
)


async def _actor_exists(session: AsyncSession, *, actor_id: int) -> bool:
    """Return ``True`` when ``groups.id == actor_id`` is present.

    A separate short query avoids conflating "no reports" with
    "actor missing" — per D15(a) these two states map to different
    HTTP statuses (200 empty vs 404). The alternative (inferring
    from empty results) would erase the distinction and silently
    200-empty every typo'd url.

    Portable across PG and sqlite. ``SELECT 1 LIMIT 1`` is a cheap
    primary-key probe.
    """
    stmt = (
        sa.select(sa.literal(1))
        .select_from(groups_table)
        .where(groups_table.c.id == actor_id)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_actor_reports(
    session: AsyncSession,
    *,
    actor_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    cursor_published: date | None = None,
    cursor_id: int | None = None,
    limit: int,
) -> tuple[list[dict[str, object]], date | None, int | None] | None:
    """Fetch one keyset page of reports that mention this actor.

    Returns ``None`` when ``actor_id`` is unknown (D15(a) — router
    maps to 404). Otherwise returns ``(items, next_published,
    next_id)`` where the trailing two are ``None`` on the final page.

    The join path is ``groups.id → codenames.group_id →
    report_codenames.codename_id → reports.id``. Dedup is via EXISTS
    (D17) so a report linked through multiple codenames appears
    once. Sort is ``reports.published DESC, reports.id DESC`` (D16)
    with the tuple-cursor seek predicate applied after filters.

    The ``limit + 1`` over-fetch pattern matches ``list_reports``: we
    need one look-ahead row to decide whether a next page exists,
    without a second ``COUNT(*)``.
    """
    if not await _actor_exists(session, actor_id=actor_id):
        return None

    # EXISTS subquery — D17. The correlated reference
    # ``report_codenames.report_id == reports.id`` keeps row count at
    # one per report regardless of codename fan-out.
    actor_link_exists = sa.exists(
        sa.select(sa.literal(1))
        .select_from(
            report_codenames_table.join(
                codenames_table,
                codenames_table.c.id == report_codenames_table.c.codename_id,
            )
        )
        .where(
            sa.and_(
                report_codenames_table.c.report_id == reports_table.c.id,
                codenames_table.c.group_id == actor_id,
            )
        )
    )

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
        .where(actor_link_exists)
    )

    if date_from is not None:
        stmt = stmt.where(reports_table.c.published >= date_from)
    if date_to is not None:
        stmt = stmt.where(reports_table.c.published <= date_to)

    # D16 cursor predicate — tuple comparison expressed as the two-
    # part disjunction that's portable across PG and sqlite. Applied
    # AFTER filters so the cursor keyset is relative to the filtered
    # result set (same discipline as ``list_reports``).
    if cursor_published is not None and cursor_id is not None:
        stmt = stmt.where(
            (reports_table.c.published < cursor_published)
            | (
                (reports_table.c.published == cursor_published)
                & (reports_table.c.id < cursor_id)
            )
        )

    stmt = (
        stmt.order_by(
            reports_table.c.published.desc(), reports_table.c.id.desc()
        )
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
    "get_actor_reports",
]
