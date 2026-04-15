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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import AliasDictionary
from worker.bootstrap.audit import (
    ROW_INSERT,
    ROW_UPDATE,
    AuditBuffer,
    RowAuditEvent,
)
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
    """Result of an upsert call.

    ``row_snapshot`` is populated only on ``INSERTED`` outcomes and
    carries the values dict that was written to the DB (plus the
    assigned PK). Row-level audit uses it as the ``"row"`` payload for
    ``etl_insert`` events. On ``EXISTING`` outcomes ``row_snapshot``
    stays ``None`` because Group B emits empty-changed ``etl_update``
    rows (genuine field-level diffs wait for PR #8+ ON CONFLICT).
    """

    id: int
    action: UpsertAction
    row_snapshot: dict[str, Any] | None = None


def _emit_row_audit(
    buffer: AuditBuffer,
    entity: str,
    outcome: UpsertOutcome,
) -> None:
    """Append a :class:`RowAuditEvent` for an upsert outcome.

    ``INSERTED`` → ``etl_insert`` with ``diff_payload.row = row_snapshot``.
    ``EXISTING``  → ``etl_update`` with ``diff_payload.changed = {}``.

    Called from every audited upsert helper when the caller provides
    an :class:`AuditBuffer`. Silent no-op is not an option: a caller
    passing a buffer means they want provenance, and dropping the
    event would create a gap the ``audit_log`` reviewer cannot detect
    after the fact.
    """
    if outcome.action is UpsertAction.INSERTED:
        buffer.append(RowAuditEvent(
            entity=entity,
            entity_id=outcome.id,
            action=ROW_INSERT,
            diff_payload={
                "op": "insert",
                "row": outcome.row_snapshot or {"id": outcome.id},
            },
        ))
    else:  # EXISTING
        buffer.append(RowAuditEvent(
            entity=entity,
            entity_id=outcome.id,
            action=ROW_UPDATE,
            diff_payload={"op": "update", "changed": {}},
        ))


# ---------------------------------------------------------------------------
# Leaf upserts — groups, sources, tags
# ---------------------------------------------------------------------------


async def upsert_group(
    session: AsyncSession,
    name: str,
    *,
    audit_buffer: AuditBuffer | None = None,
) -> UpsertOutcome:
    """Resolve a group by canonical name, inserting if missing.

    When ``audit_buffer`` is provided, emits an ``etl_insert`` event
    with the full row snapshot on first insert and an empty-changed
    ``etl_update`` event on idempotent re-run.
    """
    if not name:
        raise ValueError("group name is required")

    existing = await session.execute(
        sa.select(groups_table.c.id).where(groups_table.c.name == name)
    )
    row = existing.first()
    if row is not None:
        outcome = UpsertOutcome(id=row[0], action=UpsertAction.EXISTING)
    else:
        values = {"name": name}
        result = await session.execute(
            sa.insert(groups_table).values(**values).returning(groups_table.c.id)
        )
        new_id = result.scalar_one()
        outcome = UpsertOutcome(
            id=new_id,
            action=UpsertAction.INSERTED,
            row_snapshot={"id": new_id, **values},
        )

    if audit_buffer is not None:
        _emit_row_audit(audit_buffer, "groups", outcome)
    return outcome


async def upsert_source(
    session: AsyncSession,
    name: str,
    *,
    type_: str = "vendor",
    audit_buffer: AuditBuffer | None = None,
) -> UpsertOutcome:
    """Resolve a source by name, inserting if missing.

    When ``audit_buffer`` is provided, emits a row-level audit event
    (``etl_insert`` + snapshot on first write, empty-changed
    ``etl_update`` on idempotent re-run).
    """
    if not name:
        raise ValueError("source name is required")

    existing = await session.execute(
        sa.select(sources_table.c.id).where(sources_table.c.name == name)
    )
    row = existing.first()
    if row is not None:
        outcome = UpsertOutcome(id=row[0], action=UpsertAction.EXISTING)
    else:
        values = {"name": name, "type": type_}
        result = await session.execute(
            sa.insert(sources_table)
            .values(**values)
            .returning(sources_table.c.id)
        )
        new_id = result.scalar_one()
        outcome = UpsertOutcome(
            id=new_id,
            action=UpsertAction.INSERTED,
            row_snapshot={"id": new_id, **values},
        )

    if audit_buffer is not None:
        _emit_row_audit(audit_buffer, "sources", outcome)
    return outcome


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
    audit_buffer: AuditBuffer | None = None,
) -> UpsertOutcome:
    """Resolve a codename by its unique name, inserting if missing.

    If a codename already exists but its ``group_id`` was previously
    unset, a subsequent call with a known ``group_id`` updates it in
    place. This lets a later pass through the workbook resolve
    previously-unclassified codenames without duplicating rows.

    When ``audit_buffer`` is provided, emits a row-level audit event
    per D3. In-place patches on EXISTING rows are recorded as
    empty-changed ``etl_update`` events in PR #7 scope; genuine
    before/after field diffs wait for PR #8+ ON CONFLICT semantics.
    """
    if not name:
        raise ValueError("codename is required")

    existing = await session.execute(
        sa.select(
            codenames_table.c.id,
            codenames_table.c.group_id,
            codenames_table.c.named_by_source_id,
            codenames_table.c.first_seen,
            codenames_table.c.last_seen,
        ).where(codenames_table.c.name == name)
    )
    row = existing.first()
    if row is not None:
        (
            codename_id,
            current_group_id,
            current_source_id,
            current_first,
            current_last,
        ) = row
        patches: dict[str, object] = {}
        if current_group_id is None and group_id is not None:
            patches["group_id"] = group_id
        if current_source_id is None and named_by_source_id is not None:
            # Report tags create codenames without a source; the
            # Actors sheet is the authoritative origin for the
            # "named by" attribution. Backfill it the first time the
            # Actors row for this codename arrives.
            patches["named_by_source_id"] = named_by_source_id
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
        outcome = UpsertOutcome(id=codename_id, action=UpsertAction.EXISTING)
    else:
        values = {
            "name": name,
            "group_id": group_id,
            "named_by_source_id": named_by_source_id,
            "first_seen": first_seen,
            "last_seen": last_seen,
        }
        result = await session.execute(
            sa.insert(codenames_table)
            .values(**values)
            .returning(codenames_table.c.id)
        )
        new_id = result.scalar_one()
        outcome = UpsertOutcome(
            id=new_id,
            action=UpsertAction.INSERTED,
            row_snapshot={"id": new_id, **values},
        )

    if audit_buffer is not None:
        _emit_row_audit(audit_buffer, "codenames", outcome)
    return outcome


# ---------------------------------------------------------------------------
# Actor row — composes group + source + codename
# ---------------------------------------------------------------------------


async def upsert_actor(
    session: AsyncSession,
    row: ActorRow,
    aliases: AliasDictionary,
    *,
    audit_buffer: AuditBuffer | None = None,
) -> UpsertOutcome:
    """Handle one Actors-sheet row end-to-end.

    The ``associated_group`` value is resolved through the alias
    dictionary. Unknown aliases are treated as an error so the row
    lands in the dead-letter file — the fixture's "alias-not-in-
    dictionary" failure case asserts this behavior.

    ``audit_buffer`` is threaded down to every nested upsert call so
    each entity (groups / sources / codenames) gets its own row-level
    audit event. The caller owns the buffer's mark/rollback_to cut
    points; this function only appends.
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
        group = await upsert_group(
            session, canonical_group, audit_buffer=audit_buffer
        )
        group_id = group.id

    source_id: int | None = None
    if row.named_by:
        source = await upsert_source(
            session, row.named_by, audit_buffer=audit_buffer
        )
        source_id = source.id

    codename = await upsert_codename(
        session,
        name=row.name,
        group_id=group_id,
        named_by_source_id=source_id,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        audit_buffer=audit_buffer,
    )
    return codename


# ---------------------------------------------------------------------------
# Report row — composes source + tags + codenames
# ---------------------------------------------------------------------------


async def upsert_report(
    session: AsyncSession,
    row: ReportRow,
    aliases: AliasDictionary,
    *,
    audit_buffer: AuditBuffer | None = None,
) -> UpsertOutcome:
    """Handle one Reports-sheet row end-to-end.

    Upserts the source, canonicalizes the URL, hashes the title,
    inserts or finds the report row, then attaches all classified
    tags via the ``tags`` / ``report_tags`` tables and any actor tags
    via ``report_codenames``.

    When ``audit_buffer`` is provided, row-level events are appended
    for every audited nested upsert (source, report, any actor-tag
    derived group/codename) at each of the four return paths (url
    match, title-hash match, anonymous promotion, fresh insert).
    """
    url_canonical = canonicalize_url(row.url)
    title_hash = sha256_title(row.title)

    # First pass: look up by `url_canonical` alone — it is a global
    # unique key, no source context needed. This also runs BEFORE
    # `upsert_source` so that a duplicate URL arriving from a new
    # vendor does not insert an orphan sources row that the report
    # never references.
    existing = await session.execute(
        sa.select(
            reports_table.c.id,
            reports_table.c.source_id,
        ).where(reports_table.c.url_canonical == url_canonical)
    )
    row_id_tuple = existing.first()
    if row_id_tuple is not None:
        report_id, existing_source_id = row_id_tuple

        # Backfill source attribution if the existing row was
        # attributed to the synthetic `unknown` source (because an
        # earlier duplicate had no author) and this row carries a
        # real vendor name. Leaving the report attributed to
        # `unknown` when we have better data would be silent
        # metadata loss, and the rest of the duplicate-merge path
        # already preserves the richer version of the row.
        if row.author and row.author.strip() and row.author.strip() != "unknown":
            existing_source_name = await session.execute(
                sa.select(sources_table.c.name).where(
                    sources_table.c.id == existing_source_id
                )
            )
            name_row = existing_source_name.first()
            if name_row is not None and name_row[0] == "unknown":
                new_source = await upsert_source(
                    session, row.author.strip(), audit_buffer=audit_buffer
                )
                await session.execute(
                    sa.update(reports_table)
                    .where(reports_table.c.id == report_id)
                    .values(source_id=new_source.id)
                )

        report_outcome = UpsertOutcome(id=report_id, action=UpsertAction.EXISTING)
        if audit_buffer is not None:
            _emit_row_audit(audit_buffer, "reports", report_outcome)
        await _attach_report_tags(
            session, report_id, row.tags, aliases, audit_buffer=audit_buffer
        )
        return report_outcome

    # Second pass: resolve the source for this row, then look up by
    # the title-hash fallback scoped to that source. `sha256_title`
    # exists so a vendor moving an article to a new URL still
    # collapses onto the existing report, but matching it globally
    # would also collapse unrelated reports across vendors that share
    # a templated headline (e.g. "Threat Update" — the exact example
    # Codex flagged in PR #5 round 4). Scoping the match to
    # `source_id` keeps the intended fallback while rejecting
    # cross-vendor collisions.
    #
    # Orphan-sources note: if the scoped lookup finds a hit, it means
    # the existing report already references THIS source, so the
    # source was necessarily pre-existing — `upsert_source` returned
    # EXISTING, not INSERTED, so nothing we just wrote is left
    # dangling. If the lookup misses, the report insert below
    # consumes the source immediately.
    source = await upsert_source(
        session,
        row.author or "unknown",
        audit_buffer=audit_buffer,
    )

    title_existing = await session.execute(
        sa.select(
            reports_table.c.id,
            reports_table.c.url_canonical,
        ).where(
            (reports_table.c.sha256_title == title_hash)
            & (reports_table.c.source_id == source.id)
        )
    )
    title_row = title_existing.first()
    if title_row is not None:
        report_id, existing_url_canonical = title_row
        # The whole point of the title-hash fallback is "same article,
        # new URL": the existing row is the earlier URL, the incoming
        # row carries the current one. Update the stored URL and
        # `url_canonical` to reflect the latest known location so
        # later lookups by the new URL still find the record.
        if existing_url_canonical != url_canonical:
            await session.execute(
                sa.update(reports_table)
                .where(reports_table.c.id == report_id)
                .values(url=row.url, url_canonical=url_canonical)
            )
        report_outcome = UpsertOutcome(id=report_id, action=UpsertAction.EXISTING)
        if audit_buffer is not None:
            _emit_row_audit(audit_buffer, "reports", report_outcome)
        await _attach_report_tags(
            session, report_id, row.tags, aliases, audit_buffer=audit_buffer
        )
        return report_outcome

    # Anonymous-promotion path: if the incoming row has a real vendor
    # name and an earlier row for the same title landed under the
    # synthetic `unknown` source (because it arrived without an
    # author), promote the existing row to this vendor. This is the
    # superset of the url_canonical-based backfill above — it also
    # catches the "anonymous first load, moved URL, attributed
    # later" case that neither the URL branch nor the source-scoped
    # title-hash branch handles on its own.
    real_author = (row.author or "").strip()
    if real_author and real_author != "unknown":
        unknown_source_row = await session.execute(
            sa.select(sources_table.c.id).where(
                sources_table.c.name == "unknown"
            )
        )
        unknown_source_id_tuple = unknown_source_row.first()
        if unknown_source_id_tuple is not None:
            unknown_source_id = unknown_source_id_tuple[0]
            promote_row = await session.execute(
                sa.select(
                    reports_table.c.id,
                    reports_table.c.url_canonical,
                ).where(
                    (reports_table.c.sha256_title == title_hash)
                    & (reports_table.c.source_id == unknown_source_id)
                )
            )
            promote_tuple = promote_row.first()
            if promote_tuple is not None:
                report_id, existing_url_canonical = promote_tuple
                update_values: dict[str, object] = {"source_id": source.id}
                if existing_url_canonical != url_canonical:
                    update_values["url"] = row.url
                    update_values["url_canonical"] = url_canonical
                await session.execute(
                    sa.update(reports_table)
                    .where(reports_table.c.id == report_id)
                    .values(**update_values)
                )
                report_outcome = UpsertOutcome(
                    id=report_id, action=UpsertAction.EXISTING
                )
                if audit_buffer is not None:
                    _emit_row_audit(audit_buffer, "reports", report_outcome)
                await _attach_report_tags(
                    session,
                    report_id,
                    row.tags,
                    aliases,
                    audit_buffer=audit_buffer,
                )
                return report_outcome

    insert_values = {
        "published": row.published,
        "source_id": source.id,
        "title": row.title,
        "url": row.url,
        "url_canonical": url_canonical,
        "sha256_title": title_hash,
    }
    insert_result = await session.execute(
        sa.insert(reports_table)
        .values(**insert_values)
        .returning(reports_table.c.id)
    )
    report_id = insert_result.scalar_one()

    report_outcome = UpsertOutcome(
        id=report_id,
        action=UpsertAction.INSERTED,
        row_snapshot={"id": report_id, **insert_values},
    )
    if audit_buffer is not None:
        _emit_row_audit(audit_buffer, "reports", report_outcome)

    await _attach_report_tags(
        session, report_id, row.tags, aliases, audit_buffer=audit_buffer
    )

    return report_outcome


async def _attach_report_tags(
    session: AsyncSession,
    report_id: int,
    tags_cell: str | None,
    aliases: AliasDictionary,
    *,
    audit_buffer: AuditBuffer | None = None,
) -> None:
    """Classify + upsert all tags in a report's tag cell and link them.

    Thread-through of ``audit_buffer`` covers the two audited entities
    this helper touches indirectly: ``groups`` and ``codenames``,
    created when an actor-type tag surfaces as a ``report_codenames``
    link. The ``tags`` table itself is NOT in :data:`ENTITY_TABLES_AUDITED`
    (D3 scope) so ``upsert_tag`` runs without the buffer kwarg.
    ``report_tags`` and ``report_codenames`` are mapping tables and
    also excluded from row-level audit by design.
    """
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
            group = await upsert_group(
                session, tag.canonical, audit_buffer=audit_buffer
            )
            codename = await upsert_codename(
                session,
                name=tag.canonical,
                group_id=group.id,
                audit_buffer=audit_buffer,
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


async def _ensure_incident_mapping(
    session: AsyncSession,
    table: sa.Table,
    incident_id: int,
    value_column: str,
    value: str,
) -> None:
    """Idempotent insert into one of the incident_* mapping tables.

    Each mapping table has a composite PK of
    ``(incident_id, <value_column>)``, so a simple check-then-insert
    guarantees a duplicate row is a no-op instead of an
    IntegrityError.
    """
    col = table.c[value_column]
    existing = await session.execute(
        sa.select(col).where(
            (table.c.incident_id == incident_id) & (col == value)
        )
    )
    if existing.first() is None:
        await session.execute(
            sa.insert(table).values(
                **{"incident_id": incident_id, value_column: value}
            )
        )


async def upsert_incident(
    session: AsyncSession,
    row: IncidentRow,
    *,
    audit_buffer: AuditBuffer | None = None,
) -> UpsertOutcome:
    """Handle one Incidents-sheet row end-to-end.

    Natural key is ``(title, reported)`` since v1.0 does not carry a
    stable incident ID. Title is derived from the ``victims`` cell
    because the v1.0 workbook reuses "Victims" as the headline text.

    When a second workbook row resolves to the same incident but
    carries a different motivation / sector / country, the extra
    mapping rows are still merged onto the existing incident. That
    is what the multi-valued mapping tables exist for, and dropping
    them on duplicate-key would be silent data loss.

    Row-level audit emits exactly one event per call (for the
    incident entity). The mapping tables ``incident_motivations`` /
    ``incident_sectors`` / ``incident_countries`` are deliberately
    excluded from the audit set per D3.
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
        incident_id = row_tuple[0]
        outcome = UpsertOutcome(id=incident_id, action=UpsertAction.EXISTING)
    else:
        insert_values = {
            "reported": row.reported,
            "title": title,
        }
        insert_result = await session.execute(
            sa.insert(incidents_table)
            .values(**insert_values)
            .returning(incidents_table.c.id)
        )
        incident_id = insert_result.scalar_one()
        outcome = UpsertOutcome(
            id=incident_id,
            action=UpsertAction.INSERTED,
            row_snapshot={"id": incident_id, **insert_values},
        )

    if audit_buffer is not None:
        _emit_row_audit(audit_buffer, "incidents", outcome)

    if row.motivations:
        await _ensure_incident_mapping(
            session,
            incident_motivations_table,
            incident_id,
            "motivation",
            row.motivations.strip(),
        )
    if row.sectors:
        await _ensure_incident_mapping(
            session,
            incident_sectors_table,
            incident_id,
            "sector_code",
            row.sectors.strip(),
        )
    if row.countries:
        await _ensure_incident_mapping(
            session,
            incident_countries_table,
            incident_id,
            "country_iso2",
            row.countries,
        )

    return outcome
