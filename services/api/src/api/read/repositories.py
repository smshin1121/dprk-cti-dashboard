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

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import codenames_table, groups_table


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


__all__ = [
    "count_actors",
    "list_actors",
]
