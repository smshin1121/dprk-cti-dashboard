"""Detail-view aggregators for PR #14 Phase 3 slice 1.

Three read-only functions — one per detail endpoint:

    get_report_detail(session, report_id)   -> dict | None
    get_incident_detail(session, incident_id) -> dict | None
    get_actor_detail(session, actor_id)       -> dict | None

Each returns a dict shaped for the corresponding Pydantic DTO
(``ReportDetail`` / ``IncidentDetail`` / ``ActorDetail`` in
``api.schemas.read``), or ``None`` when the entity is not found.
The router maps ``None`` to an HTTP 404.

Design contract (``docs/plans/pr14-detail-views.md``):

- **D9 Payload depth** — caps are enforced in SQL via ``LIMIT``.
  Python slicing would materialize the full N rows before trimming,
  which defeats the performance argument for capping. Module-level
  constants ``REPORT_DETAIL_INCIDENTS_CAP=10`` and
  ``INCIDENT_DETAIL_REPORTS_CAP=20`` live in ``api.schemas.read`` so
  the DTO and the aggregator share one source of truth.

- **D11 Navigation contract** — report ↔ incident linking uses the
  existing ``incident_sources`` M:N table (migration 0001). Both
  directions benefit from indexes:
    * incident → reports via PK ``(incident_id, report_id)``
    * report → incidents via ``ix_incident_sources_report_id``
      (migration 0002 line 175).
  ``ActorDetail`` deliberately does NOT traverse ``report_codenames``
  — surfacing "reports mentioning this actor" needs its own endpoint
  with a locked filter contract; carried to a later Phase 3 slice.

Portability: queries work on both PG and in-memory sqlite so unit
tests exercise real SQL without a live Postgres. Dialect-specific
aggregators (``array_agg`` on PG, ``group_concat`` on sqlite) are
selected via ``session.get_bind().dialect.name`` — the same pattern
``api.read.repositories.list_actors`` already uses.

Sorting: every capped collection is ordered by a deterministic key
so the client sees stable output across runs. Linked_incidents:
``incidents.reported DESC NULLS LAST, incidents.id DESC``. Linked_
reports: ``reports.published DESC, reports.id DESC``. The secondary
``id DESC`` tiebreaks rows with equal dates so two callers with
identical cache keys never see reordered entries.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.read import (
    INCIDENT_DETAIL_REPORTS_CAP,
    REPORT_DETAIL_INCIDENTS_CAP,
)
from ..tables import (
    codenames_table,
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incident_sources_table,
    incidents_table,
    report_codenames_table,
    report_tags_table,
    report_techniques_table,
    reports_table,
    sources_table,
    tags_table,
    techniques_table,
)


def _resolve_dialect(session: AsyncSession) -> str:
    """Match ``api.read.repositories._resolve_dialect`` exactly.

    Kept locally rather than imported to avoid a reverse dependency
    from the new aggregator module back into the existing
    repositories module. Both call ``session.get_bind()`` which is
    the non-deprecated access pattern.
    """
    return session.get_bind().dialect.name


# ---------------------------------------------------------------------------
# Report detail
# ---------------------------------------------------------------------------


async def get_report_detail(
    session: AsyncSession, *, report_id: int
) -> dict[str, object] | None:
    """Fetch one report with related tags, codenames, techniques, and
    the capped linked-incidents summary list.

    Returns ``None`` when the report id is not found — the caller
    maps that to an HTTP 404. A report without any related rows
    returns a dict whose list fields are all ``[]`` (plan D9 empty-
    related-collections contract).

    Cap enforcement for linked_incidents:
        SELECT ... FROM incidents JOIN incident_sources ...
        ORDER BY reported DESC NULLS LAST, id DESC
        LIMIT REPORT_DETAIL_INCIDENTS_CAP
    The DTO's ``Field(max_length=...)`` is the redundant upper guard.
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
            reports_table.c.summary,
            reports_table.c.reliability,
            reports_table.c.credibility,
        )
        .select_from(
            reports_table.outerjoin(
                sources_table, sources_table.c.id == reports_table.c.source_id
            )
        )
        .where(reports_table.c.id == report_id)
    )
    result = await session.execute(stmt)
    core = result.mappings().first()
    if core is None:
        return None

    tags = await _fetch_report_tags(session, report_id=report_id)
    codenames = await _fetch_report_codenames(session, report_id=report_id)
    techniques = await _fetch_report_techniques(session, report_id=report_id)
    linked_incidents = await _fetch_linked_incidents(
        session, report_id=report_id
    )

    return {
        "id": core["id"],
        "title": core["title"],
        "url": core["url"],
        "url_canonical": core["url_canonical"],
        "published": core["published"],
        "source_id": core["source_id"],
        "source_name": core["source_name"],
        "lang": core["lang"],
        "tlp": core["tlp"],
        "summary": core["summary"],
        "reliability": core["reliability"],
        "credibility": core["credibility"],
        "tags": tags,
        "codenames": codenames,
        "techniques": techniques,
        "linked_incidents": linked_incidents,
    }


async def _fetch_report_tags(
    session: AsyncSession, *, report_id: int
) -> list[str]:
    stmt = (
        sa.select(tags_table.c.name)
        .select_from(
            report_tags_table.join(
                tags_table, tags_table.c.id == report_tags_table.c.tag_id
            )
        )
        .where(report_tags_table.c.report_id == report_id)
        .order_by(tags_table.c.name.asc())
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _fetch_report_codenames(
    session: AsyncSession, *, report_id: int
) -> list[str]:
    stmt = (
        sa.select(codenames_table.c.name)
        .select_from(
            report_codenames_table.join(
                codenames_table,
                codenames_table.c.id == report_codenames_table.c.codename_id,
            )
        )
        .where(report_codenames_table.c.report_id == report_id)
        .order_by(codenames_table.c.name.asc())
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _fetch_report_techniques(
    session: AsyncSession, *, report_id: int
) -> list[str]:
    """Return the MITRE public ids (``techniques.mitre_id``), not the
    internal DB ids — FE renders the public id directly as the link
    label and doesn't need a lookup table.
    """
    stmt = (
        sa.select(techniques_table.c.mitre_id)
        .select_from(
            report_techniques_table.join(
                techniques_table,
                techniques_table.c.id == report_techniques_table.c.technique_id,
            )
        )
        .where(report_techniques_table.c.report_id == report_id)
        .order_by(techniques_table.c.mitre_id.asc())
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _fetch_linked_incidents(
    session: AsyncSession, *, report_id: int
) -> list[dict[str, object]]:
    """Capped list of incidents this report is a source of.

    ORDER BY ``reported DESC NULLS LAST, id DESC`` — newest-reported
    first. LIMIT is ``REPORT_DETAIL_INCIDENTS_CAP``; enforcement is
    SQL-side per plan D9 (Python slicing would fetch the full row set
    before trimming). Rows with ``reported IS NULL`` sort last so the
    top slots always carry chronology when it's known.
    """
    stmt = (
        sa.select(
            incidents_table.c.id,
            incidents_table.c.title,
            incidents_table.c.reported,
        )
        .select_from(
            incident_sources_table.join(
                incidents_table,
                incidents_table.c.id == incident_sources_table.c.incident_id,
            )
        )
        .where(incident_sources_table.c.report_id == report_id)
        # NULLS LAST is a PG idiom; sqlite ordering puts NULLs first
        # by default. Wrap with a CASE to make both dialects agree:
        # ``CASE WHEN reported IS NULL THEN 1 ELSE 0 END ASC,
        #  reported DESC, id DESC``.
        .order_by(
            sa.case(
                (incidents_table.c.reported.is_(None), 1),
                else_=0,
            ).asc(),
            incidents_table.c.reported.desc(),
            incidents_table.c.id.desc(),
        )
        .limit(REPORT_DETAIL_INCIDENTS_CAP)
    )
    result = await session.execute(stmt)
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "reported": row["reported"],
        }
        for row in result.mappings().all()
    ]


# ---------------------------------------------------------------------------
# Incident detail
# ---------------------------------------------------------------------------


async def get_incident_detail(
    session: AsyncSession, *, incident_id: int
) -> dict[str, object] | None:
    """Fetch one incident with flat motivations/sectors/countries and
    the capped linked-reports summary list.

    Unlike ``list_incidents`` (which filters ``reported IS NOT NULL``
    because the cursor needs a date), this detail endpoint surfaces
    rows with ``reported=NULL`` — plan D9 allows it since detail
    views do not paginate. The DTO's ``reported: date | None``
    already accommodates nulls.

    Cap enforcement for linked_reports:
        SELECT ... FROM reports JOIN incident_sources ...
        ORDER BY published DESC, id DESC
        LIMIT INCIDENT_DETAIL_REPORTS_CAP
    """
    stmt = sa.select(
        incidents_table.c.id,
        incidents_table.c.reported,
        incidents_table.c.title,
        incidents_table.c.description,
        incidents_table.c.est_loss_usd,
        incidents_table.c.attribution_confidence,
    ).where(incidents_table.c.id == incident_id)
    result = await session.execute(stmt)
    core = result.mappings().first()
    if core is None:
        return None

    motivations = await _fetch_incident_motivations(
        session, incident_id=incident_id
    )
    sectors = await _fetch_incident_sectors(session, incident_id=incident_id)
    countries = await _fetch_incident_countries(
        session, incident_id=incident_id
    )
    linked_reports = await _fetch_linked_reports(
        session, incident_id=incident_id
    )

    return {
        "id": core["id"],
        "reported": core["reported"],
        "title": core["title"],
        "description": core["description"],
        "est_loss_usd": core["est_loss_usd"],
        "attribution_confidence": core["attribution_confidence"],
        "motivations": motivations,
        "sectors": sectors,
        "countries": countries,
        "linked_reports": linked_reports,
    }


async def _fetch_incident_motivations(
    session: AsyncSession, *, incident_id: int
) -> list[str]:
    stmt = (
        sa.select(incident_motivations_table.c.motivation)
        .where(incident_motivations_table.c.incident_id == incident_id)
        .order_by(incident_motivations_table.c.motivation.asc())
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _fetch_incident_sectors(
    session: AsyncSession, *, incident_id: int
) -> list[str]:
    stmt = (
        sa.select(incident_sectors_table.c.sector_code)
        .where(incident_sectors_table.c.incident_id == incident_id)
        .order_by(incident_sectors_table.c.sector_code.asc())
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _fetch_incident_countries(
    session: AsyncSession, *, incident_id: int
) -> list[str]:
    stmt = (
        sa.select(incident_countries_table.c.country_iso2)
        .where(incident_countries_table.c.incident_id == incident_id)
        .order_by(incident_countries_table.c.country_iso2.asc())
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _fetch_linked_reports(
    session: AsyncSession, *, incident_id: int
) -> list[dict[str, object]]:
    """Capped list of reports that source this incident.

    ORDER BY ``published DESC, id DESC`` — newest first; reports have
    a NOT NULL ``published`` column per migration 0001 so no NULL
    handling is needed here. LIMIT is ``INCIDENT_DETAIL_REPORTS_CAP``.
    """
    stmt = (
        sa.select(
            reports_table.c.id,
            reports_table.c.title,
            reports_table.c.url,
            reports_table.c.published,
            sources_table.c.name.label("source_name"),
        )
        .select_from(
            incident_sources_table.join(
                reports_table,
                reports_table.c.id == incident_sources_table.c.report_id,
            ).outerjoin(
                sources_table,
                sources_table.c.id == reports_table.c.source_id,
            )
        )
        .where(incident_sources_table.c.incident_id == incident_id)
        .order_by(
            reports_table.c.published.desc(),
            reports_table.c.id.desc(),
        )
        .limit(INCIDENT_DETAIL_REPORTS_CAP)
    )
    result = await session.execute(stmt)
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "published": row["published"],
            "source_name": row["source_name"],
        }
        for row in result.mappings().all()
    ]


# ---------------------------------------------------------------------------
# Actor detail
# ---------------------------------------------------------------------------


async def get_actor_detail(
    session: AsyncSession, *, actor_id: int
) -> dict[str, object] | None:
    """Fetch one group (actor) with its codenames.

    Plan D11 explicitly keeps "reports mentioning this actor via
    ``report_codenames``" out of scope. This function therefore does
    NOT traverse ``report_codenames`` — the DTO carries only the core
    group fields plus the flat codenames list. A later Phase 3 slice
    will surface linked reports behind its own endpoint with a
    locked pagination + filter contract.
    """
    stmt = sa.select(
        groups_table.c.id,
        groups_table.c.name,
        groups_table.c.mitre_intrusion_set_id,
        groups_table.c.aka,
        groups_table.c.description,
    ).where(groups_table.c.id == actor_id)
    result = await session.execute(stmt)
    core = result.mappings().first()
    if core is None:
        return None

    codename_stmt = (
        sa.select(codenames_table.c.name)
        .where(codenames_table.c.group_id == actor_id)
        .order_by(codenames_table.c.name.asc())
    )
    codename_result = await session.execute(codename_stmt)
    codenames = [row[0] for row in codename_result.all()]

    aka_raw = core["aka"]
    if aka_raw is None:
        aka: list[str] = []
    elif isinstance(aka_raw, list):
        aka = [str(v) for v in aka_raw if v is not None]
    else:
        # sqlite JSON-variant path — aka stored as JSON string or list.
        aka = [str(v) for v in list(aka_raw) if v is not None]

    return {
        "id": core["id"],
        "name": core["name"],
        "mitre_intrusion_set_id": core["mitre_intrusion_set_id"],
        "aka": aka,
        "description": core["description"],
        "codenames": codenames,
    }


__all__ = [
    "get_actor_detail",
    "get_incident_detail",
    "get_report_detail",
]
