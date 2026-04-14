"""Tests for worker.bootstrap.upsert against an in-memory sqlite database."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import load_aliases
from worker.bootstrap.schemas import ActorRow, IncidentRow, ReportRow
from worker.bootstrap.tables import (
    codenames_table,
    groups_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    report_codenames_table,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
)
from worker.bootstrap.upsert import (
    UpsertAction,
    upsert_actor,
    upsert_codename,
    upsert_group,
    upsert_incident,
    upsert_report,
    upsert_source,
    upsert_tag,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def aliases():
    return load_aliases(REPO_ROOT / "data/dictionaries/aliases.yml")


async def _count(session: AsyncSession, table) -> int:
    result = await session.execute(sa.select(sa.func.count()).select_from(table))
    return result.scalar_one()


# ---------------------------------------------------------------------------
# upsert_group
# ---------------------------------------------------------------------------


async def test_upsert_group_inserts_new_row(db_session: AsyncSession) -> None:
    outcome = await upsert_group(db_session, "Lazarus")
    assert outcome.action is UpsertAction.INSERTED
    assert outcome.id > 0
    assert await _count(db_session, groups_table) == 1


async def test_upsert_group_is_idempotent(db_session: AsyncSession) -> None:
    first = await upsert_group(db_session, "Lazarus")
    second = await upsert_group(db_session, "Lazarus")
    assert first.id == second.id
    assert second.action is UpsertAction.EXISTING
    assert await _count(db_session, groups_table) == 1


async def test_upsert_group_rejects_empty_name(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await upsert_group(db_session, "")


async def test_upsert_group_distinguishes_different_names(db_session: AsyncSession) -> None:
    a = await upsert_group(db_session, "Lazarus")
    b = await upsert_group(db_session, "Kimsuky")
    assert a.id != b.id
    assert await _count(db_session, groups_table) == 2


# ---------------------------------------------------------------------------
# upsert_source
# ---------------------------------------------------------------------------


async def test_upsert_source_inserts(db_session: AsyncSession) -> None:
    outcome = await upsert_source(db_session, "Mandiant")
    assert outcome.action is UpsertAction.INSERTED


async def test_upsert_source_is_idempotent(db_session: AsyncSession) -> None:
    a = await upsert_source(db_session, "Kaspersky")
    b = await upsert_source(db_session, "Kaspersky")
    assert a.id == b.id


# ---------------------------------------------------------------------------
# upsert_tag
# ---------------------------------------------------------------------------


async def test_upsert_tag_inserts_and_is_idempotent(db_session: AsyncSession) -> None:
    a = await upsert_tag(db_session, "Lazarus", "actor")
    b = await upsert_tag(db_session, "Lazarus", "actor")
    assert a.id == b.id
    assert a.action is UpsertAction.INSERTED
    assert b.action is UpsertAction.EXISTING
    assert await _count(db_session, tags_table) == 1


# ---------------------------------------------------------------------------
# upsert_codename
# ---------------------------------------------------------------------------


async def test_upsert_codename_inserts(db_session: AsyncSession) -> None:
    group = await upsert_group(db_session, "Lazarus")
    outcome = await upsert_codename(
        db_session,
        name="Lazarus Group",
        group_id=group.id,
        first_seen=dt.date(2009, 2, 1),
    )
    assert outcome.action is UpsertAction.INSERTED
    row = (await db_session.execute(
        sa.select(codenames_table.c.group_id, codenames_table.c.first_seen)
        .where(codenames_table.c.id == outcome.id)
    )).first()
    assert row is not None
    assert row[0] == group.id
    assert row[1] == dt.date(2009, 2, 1)


async def test_upsert_codename_fills_in_null_group_id(db_session: AsyncSession) -> None:
    # First insert codename with no group_id (unclassified).
    first = await upsert_codename(db_session, name="HIDDEN COBRA", group_id=None)
    assert first.action is UpsertAction.INSERTED

    # Later pass learns the canonical group; the same codename now gets
    # its group_id filled in without a new row being inserted.
    group = await upsert_group(db_session, "Lazarus")
    second = await upsert_codename(
        db_session, name="HIDDEN COBRA", group_id=group.id
    )
    assert second.id == first.id
    assert second.action is UpsertAction.EXISTING
    row = (await db_session.execute(
        sa.select(codenames_table.c.group_id)
        .where(codenames_table.c.id == first.id)
    )).first()
    assert row[0] == group.id
    assert await _count(db_session, codenames_table) == 1


# ---------------------------------------------------------------------------
# upsert_actor — end-to-end row
# ---------------------------------------------------------------------------


async def test_upsert_actor_full_row(db_session: AsyncSession, aliases) -> None:
    row = ActorRow(
        name="APT38",
        named_by="FireEye",
        associated_group="Lazarus",
        first_seen=dt.date(2014, 5, 1),
        last_seen=dt.date(2024, 11, 20),
    )
    outcome = await upsert_actor(db_session, row, aliases)
    assert outcome.action is UpsertAction.INSERTED

    assert await _count(db_session, groups_table) == 1  # Lazarus
    assert await _count(db_session, sources_table) == 1  # FireEye
    assert await _count(db_session, codenames_table) == 1  # APT38


async def test_upsert_actor_normalizes_alias_to_canonical(db_session: AsyncSession, aliases) -> None:
    """APT38 and Hidden Cobra both map to Lazarus — only one groups row
    should exist after loading both codenames."""
    await upsert_actor(
        db_session,
        ActorRow(name="APT38", named_by="FireEye", associated_group="APT38"),
        aliases,
    )
    await upsert_actor(
        db_session,
        ActorRow(name="HIDDEN COBRA", named_by="US-CERT", associated_group="Hidden Cobra"),
        aliases,
    )
    assert await _count(db_session, groups_table) == 1
    assert await _count(db_session, codenames_table) == 2


async def test_upsert_actor_rejects_unknown_alias(db_session: AsyncSession, aliases) -> None:
    row = ActorRow(
        name="UnknownActor",
        named_by="Acme Intel",
        associated_group="NonExistentGroup",
    )
    with pytest.raises(ValueError, match="no canonical mapping"):
        await upsert_actor(db_session, row, aliases)


async def test_upsert_actor_is_idempotent(db_session: AsyncSession, aliases) -> None:
    row = ActorRow(name="Lazarus Group", associated_group="Lazarus")
    first = await upsert_actor(db_session, row, aliases)
    second = await upsert_actor(db_session, row, aliases)
    assert first.id == second.id
    assert second.action is UpsertAction.EXISTING
    assert await _count(db_session, codenames_table) == 1


# ---------------------------------------------------------------------------
# upsert_report
# ---------------------------------------------------------------------------


async def test_upsert_report_full_row(db_session: AsyncSession, aliases) -> None:
    row = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-macos-2024",
        tags="#lazarus #appleseed #cve-2024-1234 #crypto",
    )
    outcome = await upsert_report(db_session, row, aliases)
    assert outcome.action is UpsertAction.INSERTED
    assert await _count(db_session, reports_table) == 1
    assert await _count(db_session, sources_table) == 1
    # Four classified tags -> four rows in tags + four rows in report_tags
    assert await _count(db_session, tags_table) == 4
    assert await _count(db_session, report_tags_table) == 4
    # Lazarus actor tag also surfaces in report_codenames
    assert await _count(db_session, report_codenames_table) == 1


async def test_upsert_report_is_idempotent_by_url_canonical(db_session: AsyncSession, aliases) -> None:
    row = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-macos-2024",
        tags="#lazarus",
    )
    first = await upsert_report(db_session, row, aliases)
    second = await upsert_report(db_session, row, aliases)
    assert first.id == second.id
    assert second.action is UpsertAction.EXISTING
    assert await _count(db_session, reports_table) == 1
    assert await _count(db_session, tags_table) == 1
    assert await _count(db_session, report_tags_table) == 1


async def test_upsert_report_url_canonical_collapses_tracking_params(
    db_session: AsyncSession, aliases
) -> None:
    """Two reports with the same URL modulo utm_* params must collapse
    into one row — the key guarantee url_canonical provides."""
    base = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    with_utm = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos?utm_source=newsletter",
        tags="#lazarus",
    )
    first = await upsert_report(db_session, base, aliases)
    second = await upsert_report(db_session, with_utm, aliases)
    assert first.id == second.id
    assert await _count(db_session, reports_table) == 1


async def test_upsert_report_with_no_tags(db_session: AsyncSession, aliases) -> None:
    row = ReportRow(
        published=dt.date(2024, 5, 10),
        title="Report with no tags",
        url="https://example.com/no-tags",
    )
    outcome = await upsert_report(db_session, row, aliases)
    assert outcome.action is UpsertAction.INSERTED
    assert await _count(db_session, reports_table) == 1
    assert await _count(db_session, report_tags_table) == 0


async def test_upsert_report_default_author_is_unknown_source(
    db_session: AsyncSession, aliases
) -> None:
    row = ReportRow(
        published=dt.date(2024, 5, 10),
        title="Anonymous report",
        url="https://example.com/anon",
    )
    await upsert_report(db_session, row, aliases)
    source_rows = (
        await db_session.execute(sa.select(sources_table.c.name))
    ).scalars().all()
    assert "unknown" in source_rows


# ---------------------------------------------------------------------------
# upsert_incident
# ---------------------------------------------------------------------------


async def test_upsert_incident_full_row(db_session: AsyncSession) -> None:
    row = IncidentRow(
        reported=dt.date(2022, 3, 23),
        victims="Ronin Network",
        motivations="financial",
        sectors="crypto",
        countries="VN",
    )
    outcome = await upsert_incident(db_session, row)
    assert outcome.action is UpsertAction.INSERTED
    assert await _count(db_session, incidents_table) == 1
    assert await _count(db_session, incident_motivations_table) == 1
    assert await _count(db_session, incident_sectors_table) == 1
    assert await _count(db_session, incident_countries_table) == 1

    country_row = (await db_session.execute(
        sa.select(incident_countries_table.c.country_iso2)
    )).first()
    assert country_row[0] == "VN"


async def test_upsert_incident_is_idempotent_by_title_and_date(
    db_session: AsyncSession,
) -> None:
    row = IncidentRow(
        reported=dt.date(2022, 3, 23),
        victims="Ronin Network",
        motivations="financial",
        sectors="crypto",
        countries="VN",
    )
    first = await upsert_incident(db_session, row)
    second = await upsert_incident(db_session, row)
    assert first.id == second.id
    assert second.action is UpsertAction.EXISTING
    assert await _count(db_session, incidents_table) == 1
    # Mapping rows are inserted once on the first call and not duplicated.
    assert await _count(db_session, incident_motivations_table) == 1


async def test_upsert_incident_with_no_optional_fields(db_session: AsyncSession) -> None:
    row = IncidentRow(reported=dt.date(2022, 3, 23), victims="Minimal Incident")
    outcome = await upsert_incident(db_session, row)
    assert outcome.action is UpsertAction.INSERTED
    assert await _count(db_session, incident_motivations_table) == 0
    assert await _count(db_session, incident_sectors_table) == 0
    assert await _count(db_session, incident_countries_table) == 0


# ---------------------------------------------------------------------------
# Fixture-driven idempotency smoke test
# ---------------------------------------------------------------------------


async def test_full_happy_fixture_idempotent_second_run(
    db_session: AsyncSession, aliases
) -> None:
    """Loading every happy-path row from the fixture twice must produce
    the same row counts as loading it once — the T6 exit criterion."""
    from worker.bootstrap.loader import WorkbookLoader
    from worker.bootstrap.schemas import RowValidationError

    workbook = WorkbookLoader(REPO_ROOT / "services/worker/tests/fixtures/bootstrap_sample.xlsx")

    async def run_once() -> None:
        for wb_row in workbook.iter_rows("Actors"):
            try:
                row = ActorRow(**wb_row.data)
            except RowValidationError:
                continue
            try:
                await upsert_actor(db_session, row, aliases)
            except ValueError:
                # unknown alias — fixture's failure case
                continue
        for wb_row in workbook.iter_rows("Reports"):
            try:
                row = ReportRow(**wb_row.data)
            except RowValidationError:
                continue
            await upsert_report(db_session, row, aliases)
        for wb_row in workbook.iter_rows("Incidents"):
            try:
                row = IncidentRow(**wb_row.data)
            except RowValidationError:
                continue
            await upsert_incident(db_session, row)

    await run_once()
    await db_session.commit()

    counts_after_first = {
        "groups": await _count(db_session, groups_table),
        "codenames": await _count(db_session, codenames_table),
        "sources": await _count(db_session, sources_table),
        "reports": await _count(db_session, reports_table),
        "tags": await _count(db_session, tags_table),
        "report_tags": await _count(db_session, report_tags_table),
        "incidents": await _count(db_session, incidents_table),
    }
    assert counts_after_first["groups"] >= 1
    assert counts_after_first["codenames"] >= 1
    assert counts_after_first["reports"] >= 1
    assert counts_after_first["incidents"] >= 1

    await run_once()
    await db_session.commit()

    counts_after_second = {
        "groups": await _count(db_session, groups_table),
        "codenames": await _count(db_session, codenames_table),
        "sources": await _count(db_session, sources_table),
        "reports": await _count(db_session, reports_table),
        "tags": await _count(db_session, tags_table),
        "report_tags": await _count(db_session, report_tags_table),
        "incidents": await _count(db_session, incidents_table),
    }
    assert counts_after_second == counts_after_first, (
        f"second run was not idempotent: {counts_after_first} vs {counts_after_second}"
    )
