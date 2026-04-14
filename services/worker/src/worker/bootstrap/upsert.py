"""Idempotent upsert repositories for the Bootstrap ETL.

Each ``upsert_*`` function follows the same contract:

  - Resolve the target row by its natural key (``name``, ``url_canonical``,
    ``(report_id, tag_id)``, etc.).
  - If a row already exists, return its primary key without modification.
  - Otherwise insert a new row and return the generated primary key.
  - Return an :class:`UpsertOutcome` so callers can tell "inserted"
    from "already existed" when they need to (e.g. to count duplicates
    for the D5 fail-rate summary).

This check-then-insert pattern is portable between PostgreSQL (production)
and SQLite (unit tests). It has a race condition under real concurrent
writes — fine for bootstrap, which is single-threaded and one-shot, but
RSS/TAXII ingest (PR #8) must move to ``INSERT ... ON CONFLICT`` for
multi-worker safety.

All functions are async and take an ``AsyncSession``. The caller owns
transaction boundaries: commit once per row, per sheet, or per workbook
depending on how strict the atomic-commit story should be. The bootstrap
CLI (PR #6) will choose.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import AliasDictionary
from worker.bootstrap.normalize import (
    TAG_TYPE_ACTOR,
    TAG_TYPE_UNKNOWN,
    ClassifiedTag,
    canonicalize_url,
    classify_tags,
    sha256_title,
)
from worker.bootstrap.schemas import ActorRow, IncidentRow, ReportRow
from worker.bootstrap.tables import (
    codenames_table,
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incident_sources_table,
    incidents_table,
    report_codenames_table,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
)


__all__ = [
    "UpsertAction",
    "UpsertOutcome",
    "upsert_actor",
    "upsert_codename",
    "upsert_group",
    "upsert_incident",
    "upsert_report",
    "upsert_source",
    "upsert_tag",
]


class UpsertAction(str, Enum):
    INSERTED = "inserted"
    EXISTING = "existing"


@dataclass(frozen=True)
class UpsertOutcome:
    """Result of an upsert call."""

    id: int
    action: UpsertAction


# ---------------------------------------------------------------------------
# Leaf upserts — groups, sources, tags
# ---------------------------------------------------------------------------


async def upsert_group(session: AsyncSession, name: str) -> UpsertOutcome:
    """Resolve a group by canonical name, inserting if missing."""
    if not name:
        raise ValueError("group name is required")

    existing = await session.execute(
        sa.select(groups_table.c.id).where(groups_table.c.name == name)
    )
    row = existing.first()
    if row is not None:
        return UpsertOutcome(id=row[0], action=UpsertAction.EXISTING)

    result = await session.execute(
        sa.insert(groups_table).values(name=name).returning(groups_table.c.id)
    )
    new_id = result.scalar_one()
    return UpsertOutcome(id=new_id, action=UpsertAction.INSERTED)


async def upsert_source(
    session: AsyncSession,
    name: str,
    *,
    type_: str = "vendor",
) -> UpsertOutcome:
    """Resolve a source by name, inserting if missing."""
    if not name:
        raise ValueError("source name is required")

    existing = await session.execute(
        sa.select(sources_table.c.id).where(sources_table.c.name == name)
    )
    row = existing.first()
    if row is not None:
        return UpsertOutcome(id=row[0], action=UpsertAction.EXISTING)

    result = await session.execute(
        sa.insert(sources_table)
        .values(name=name, type=type_)
        .returning(sources_table.c.id)
    )
    new_id = result.scalar_one()
    return UpsertOutcome(id=new_id, action=UpsertAction.INSERTED)


async def upsert_tag(
    session: AsyncSession,
    name: str,
    type_: str,
) -> UpsertOutcome:
    """Resolve a tag by its unique name, inserting if missing."""
    if not name:
        raise ValueError("tag name is required")
    if not type_:
        raise ValueError("tag type is required")

    existing = await session.execute(
        sa.select(tags_table.c.id).where(tags_table.c.name == name)
    )
    row = existing.first()
    if row is not None:
        return UpsertOutcome(id=row[0], action=UpsertAction.EXISTING)

    result = await session.execute(
        sa.insert(tags_table)
        .values(name=name, type=type_)
        .returning(tags_table.c.id)
    )
    new_id = result.scalar_one()
    return UpsertOutcome(id=new_id, action=UpsertAction.INSERTED)


# ---------------------------------------------------------------------------
# Codename upsert (depends on group + optional source)
# ---------------------------------------------------------------------------


async def upsert_codename(
    session: AsyncSession,
    *,
    name: str,
    group_id: int | None,
    named_by_source_id: int | None = None,
    first_seen: dt.date | None = None,
    last_seen: dt.date | None = None,
) -> UpsertOutcome:
    """Resolve a codename by its unique name, inserting if missing.

    If a codename already exists but its ``group_id`` was previously
    unset, a subsequent call with a known ``group_id`` updates it in
    place. This lets a later pass through the workbook resolve
    previously-unclassified codenames without duplicating rows.
    """
    if not name:
        raise ValueError("codename is required")

    existing = await session.execute(
        sa.select(
            codenames_table.c.id,
            codenames_table.c.group_id,
            codenames_table.c.first_seen,
            codenames_table.c.last_seen,
        ).where(codenames_table.c.name == name)
    )
    row = existing.first()
    if row is not None:
        codename_id, current_group_id, current_first, current_last = row
        patches: dict[str, object] = {}
        if current_group_id is None and group_id is not None:
            patches["group_id"] = group_id
        if current_first is None and first_seen is not None:
            patches["first_seen"] = first_seen
        if current_last is None and last_seen is not None:
            patches["last_seen"] = last_seen
        if patches:
            await session.execute(
                sa.update(codenames_table)
                .where(codenames_table.c.id == codename_id)
                .values(**patches)
            )
        return UpsertOutcome(id=codename_id, action=UpsertAction.EXISTING)

    result = await session.execute(
        sa.insert(codenames_table)
        .values(
            name=name,
            group_id=group_id,
            named_by_source_id=named_by_source_id,
            first_seen=first_seen,
            last_seen=last_seen,
        )
        .returning(codenames_table.c.id)
    )
    new_id = result.scalar_one()
    return UpsertOutcome(id=new_id, action=UpsertAction.INSERTED)


# ---------------------------------------------------------------------------
# Actor row — composes group + source + codename
# ---------------------------------------------------------------------------


async def upsert_actor(
    session: AsyncSession,
    row: ActorRow,
    aliases: AliasDictionary,
) -> UpsertOutcome:
    """Handle one Actors-sheet row end-to-end.

    The ``associated_group`` value is resolved through the alias
    dictionary. Unknown aliases are treated as an error so the row
    lands in the dead-letter file — the fixture's "alias-not-in-
    dictionary" failure case asserts this behavior.
    """
    canonical_group: str | None = None
    if row.associated_group:
        canonical_group = aliases.normalize("groups", row.associated_group)
        if canonical_group is None:
            raise ValueError(
                f"associated_group {row.associated_group!r} has no canonical "
                f"mapping in the alias dictionary"
            )

    group_id: int | None = None
    if canonical_group is not None:
        group = await upsert_group(session, canonical_group)
        group_id = group.id

    source_id: int | None = None
    if row.named_by:
        source = await upsert_source(session, row.named_by)
        source_id = source.id

    codename = await upsert_codename(
        session,
        name=row.name,
        group_id=group_id,
        named_by_source_id=source_id,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
    )
    return codename


# ---------------------------------------------------------------------------
# Report row — composes source + tags + codenames
# ---------------------------------------------------------------------------


async def upsert_report(
    session: AsyncSession,
    row: ReportRow,
    aliases: AliasDictionary,
) -> UpsertOutcome:
    """Handle one Reports-sheet row end-to-end.

    Upserts the source, canonicalizes the URL, hashes the title,
    inserts or finds the report row, then attaches all classified
    tags via the ``tags`` / ``report_tags`` tables and any actor tags
    via ``report_codenames``.
    """
    source = await upsert_source(
        session,
        row.author or "unknown",
    )
    url_canonical = canonicalize_url(row.url)
    title_hash = sha256_title(row.title)

    existing = await session.execute(
        sa.select(reports_table.c.id).where(
            reports_table.c.url_canonical == url_canonical
        )
    )
    row_id_tuple = existing.first()
    if row_id_tuple is not None:
        return UpsertOutcome(id=row_id_tuple[0], action=UpsertAction.EXISTING)

    insert_result = await session.execute(
        sa.insert(reports_table)
        .values(
            published=row.published,
            source_id=source.id,
            title=row.title,
            url=row.url,
            url_canonical=url_canonical,
            sha256_title=title_hash,
        )
        .returning(reports_table.c.id)
    )
    report_id = insert_result.scalar_one()

    await _attach_report_tags(session, report_id, row.tags, aliases)

    return UpsertOutcome(id=report_id, action=UpsertAction.INSERTED)


async def _attach_report_tags(
    session: AsyncSession,
    report_id: int,
    tags_cell: str | None,
    aliases: AliasDictionary,
) -> None:
    """Classify + upsert all tags in a report's tag cell and link them."""
    if not tags_cell:
        return

    classified: list[ClassifiedTag] = classify_tags(tags_cell, aliases)
    for tag in classified:
        tag_name = tag.canonical or tag.raw
        if not tag_name:
            continue
        tag_outcome = await upsert_tag(session, name=tag_name, type_=tag.type_)

        # Link via report_tags; primary-key collision means already
        # linked, which is the idempotent no-op we want.
        already_linked = await session.execute(
            sa.select(report_tags_table.c.report_id).where(
                (report_tags_table.c.report_id == report_id)
                & (report_tags_table.c.tag_id == tag_outcome.id)
            )
        )
        if already_linked.first() is None:
            await session.execute(
                sa.insert(report_tags_table).values(
                    report_id=report_id,
                    tag_id=tag_outcome.id,
                )
            )

        # Actor tags also surface in report_codenames so the analytics
        # views can pivot by group without re-parsing tags.
        if tag.type_ == TAG_TYPE_ACTOR and tag.canonical:
            group = await upsert_group(session, tag.canonical)
            codename = await upsert_codename(
                session,
                name=tag.canonical,
                group_id=group.id,
            )
            link_existing = await session.execute(
                sa.select(report_codenames_table.c.report_id).where(
                    (report_codenames_table.c.report_id == report_id)
                    & (report_codenames_table.c.codename_id == codename.id)
                )
            )
            if link_existing.first() is None:
                await session.execute(
                    sa.insert(report_codenames_table).values(
                        report_id=report_id,
                        codename_id=codename.id,
                    )
                )


# ---------------------------------------------------------------------------
# Incident row
# ---------------------------------------------------------------------------


async def upsert_incident(
    session: AsyncSession,
    row: IncidentRow,
) -> UpsertOutcome:
    """Handle one Incidents-sheet row end-to-end.

    Natural key is ``(title, reported)`` since v1.0 does not carry a
    stable incident ID. Title is derived from the ``victims`` cell
    because the v1.0 workbook reuses "Victims" as the headline text.
    """
    title = row.victims
    existing = await session.execute(
        sa.select(incidents_table.c.id).where(
            (incidents_table.c.title == title)
            & (incidents_table.c.reported == row.reported)
        )
    )
    row_tuple = existing.first()
    if row_tuple is not None:
        return UpsertOutcome(id=row_tuple[0], action=UpsertAction.EXISTING)

    insert_result = await session.execute(
        sa.insert(incidents_table)
        .values(
            reported=row.reported,
            title=title,
        )
        .returning(incidents_table.c.id)
    )
    incident_id = insert_result.scalar_one()

    if row.motivations:
        await session.execute(
            sa.insert(incident_motivations_table).values(
                incident_id=incident_id,
                motivation=row.motivations.strip(),
            )
        )
    if row.sectors:
        await session.execute(
            sa.insert(incident_sectors_table).values(
                incident_id=incident_id,
                sector_code=row.sectors.strip(),
            )
        )
    if row.countries:
        await session.execute(
            sa.insert(incident_countries_table).values(
                incident_id=incident_id,
                country_iso2=row.countries,
            )
        )

    return UpsertOutcome(id=incident_id, action=UpsertAction.INSERTED)
