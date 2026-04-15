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


async def test_upsert_codename_backfills_named_by_source_id(
    db_session: AsyncSession,
) -> None:
    """Codex round 5: a codename created by a report tag has no
    `named_by_source_id`. When the Actors-sheet row later arrives
    with `named_by` populated, the source attribution must be
    backfilled instead of silently discarded."""
    group = await upsert_group(db_session, "Kimsuky")

    # Pass 1: tag-driven upsert with no source.
    first = await upsert_codename(
        db_session,
        name="Kimsuky",
        group_id=group.id,
    )
    assert first.action is UpsertAction.INSERTED

    # Pass 2: Actors sheet arrives with a source.
    source = await upsert_source(db_session, "Kaspersky")
    second = await upsert_codename(
        db_session,
        name="Kimsuky",
        group_id=group.id,
        named_by_source_id=source.id,
    )
    assert second.id == first.id
    assert second.action is UpsertAction.EXISTING

    row = (await db_session.execute(
        sa.select(codenames_table.c.named_by_source_id)
        .where(codenames_table.c.id == first.id)
    )).first()
    assert row[0] == source.id
    assert await _count(db_session, codenames_table) == 1


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


async def test_upsert_report_dedupes_by_sha256_title_fallback_same_source(
    db_session: AsyncSession, aliases
) -> None:
    """The module doc advertises `sha256_title` as the fallback
    identity when a vendor moves a report to a new URL. The upsert
    must honor that and collapse the second row onto the first — but
    only when both rows come from the same source."""
    first = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/original-url",
        tags="#lazarus",
    )
    # Same vendor, same title, totally different URL. The fallback
    # should collapse the two onto a single report.
    second = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.org/new-slug-after-redirect",
        tags="#crypto",
    )
    first_outcome = await upsert_report(db_session, first, aliases)
    second_outcome = await upsert_report(db_session, second, aliases)

    assert first_outcome.id == second_outcome.id
    assert second_outcome.action is UpsertAction.EXISTING
    assert await _count(db_session, reports_table) == 1
    assert await _count(db_session, tags_table) == 2
    assert await _count(db_session, report_tags_table) == 2


async def test_upsert_report_title_hash_dedupe_updates_stored_url(
    db_session: AsyncSession, aliases
) -> None:
    """Codex round 5: the title-hash fallback is meant for "same
    article, new URL". When it triggers, the stored `url` and
    `url_canonical` should be updated to the incoming row's values
    so subsequent lookups by the new URL still find the record."""
    first = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://old.example.com/old-slug",
        tags="#lazarus",
    )
    second = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://new.example.com/new-slug",
        tags="#crypto",
    )
    first_outcome = await upsert_report(db_session, first, aliases)
    second_outcome = await upsert_report(db_session, second, aliases)

    assert first_outcome.id == second_outcome.id
    assert second_outcome.action is UpsertAction.EXISTING

    stored = (await db_session.execute(
        sa.select(reports_table.c.url, reports_table.c.url_canonical)
        .where(reports_table.c.id == first_outcome.id)
    )).first()
    assert stored[0] == "https://new.example.com/new-slug"
    assert stored[1] == "https://new.example.com/new-slug"
    assert await _count(db_session, reports_table) == 1


async def test_upsert_report_promotes_anonymous_to_real_vendor_on_moved_url(
    db_session: AsyncSession, aliases
) -> None:
    """External review: the combination "first row anonymous, second
    row has real vendor and a different URL but the same title" must
    collapse onto the first report and promote it to the real vendor.
    Before the fix, the url_canonical branch missed the match
    (different URLs) and the source-scoped title-hash branch missed
    it too (existing row's source_id pointed at `unknown`, new row
    looked up the real vendor), so a duplicate report was inserted
    instead of a single promoted row."""
    anonymous_first = ReportRow(
        published=dt.date(2024, 3, 15),
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/anon-slug",
        tags="#lazarus",
    )
    attributed_second = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.org/mandiant-slug",
        tags="#crypto",
    )
    first = await upsert_report(db_session, anonymous_first, aliases)
    second = await upsert_report(db_session, attributed_second, aliases)

    assert first.id == second.id
    assert second.action is UpsertAction.EXISTING
    assert await _count(db_session, reports_table) == 1

    # The existing report is now attributed to Mandiant, not `unknown`.
    resolved = (await db_session.execute(
        sa.select(sources_table.c.name, reports_table.c.url_canonical)
        .select_from(reports_table.join(
            sources_table, reports_table.c.source_id == sources_table.c.id
        ))
        .where(reports_table.c.id == first.id)
    )).first()
    assert resolved[0] == "Mandiant"
    # URL was also updated to the attributed row's canonical form.
    assert resolved[1] == "https://example.org/mandiant-slug"
    # Both tag sets survive on the single report.
    assert await _count(db_session, report_tags_table) == 2


async def test_upsert_report_promotion_leaves_unrelated_vendors_alone(
    db_session: AsyncSession, aliases
) -> None:
    """Guard: the anonymous-promotion path must not pull an unrelated
    earlier anonymous report under a new vendor just because it
    shares a templated headline with a different article."""
    # Vendor A publishes first. Real vendor, not anonymous.
    await upsert_report(
        db_session,
        ReportRow(
            published=dt.date(2024, 6, 1),
            author="Vendor A",
            title="Threat Update",
            url="https://vendor-a.example/post/june",
            tags="#lazarus",
        ),
        aliases,
    )
    # Vendor B now publishes under the same headline. Vendor A's
    # record is NOT anonymous, so it must not be promoted / merged.
    await upsert_report(
        db_session,
        ReportRow(
            published=dt.date(2024, 7, 1),
            author="Vendor B",
            title="Threat Update",
            url="https://vendor-b.example/post/july",
            tags="#kimsuky",
        ),
        aliases,
    )
    # Two distinct reports survive.
    assert await _count(db_session, reports_table) == 2


async def test_upsert_report_does_not_collapse_titles_across_vendors(
    db_session: AsyncSession, aliases
) -> None:
    """Two vendors publishing the same headline must NOT be merged.
    The sha256_title fallback is scoped to the source that authored
    the first report — otherwise templated titles like "Threat
    Update" would collapse unrelated reports and corrupt
    `reports.source_id`, the URL, and the publication metadata.
    Codex raised this in the PR #5 round 4 review."""
    vendor_a = ReportRow(
        published=dt.date(2024, 6, 1),
        author="Vendor A",
        title="Threat Update",
        url="https://vendor-a.example/advisory/2024-06-threat-update",
        tags="#lazarus",
    )
    vendor_b = ReportRow(
        published=dt.date(2024, 7, 15),
        author="Vendor B",
        title="Threat Update",
        url="https://vendor-b.example/post/threat-update-july",
        tags="#kimsuky",
    )
    a_outcome = await upsert_report(db_session, vendor_a, aliases)
    b_outcome = await upsert_report(db_session, vendor_b, aliases)

    assert a_outcome.id != b_outcome.id
    assert a_outcome.action is UpsertAction.INSERTED
    assert b_outcome.action is UpsertAction.INSERTED
    # Two distinct reports, two distinct sources.
    assert await _count(db_session, reports_table) == 2
    assert await _count(db_session, sources_table) == 2
    # Each report carries its own tag set.
    assert await _count(db_session, report_tags_table) == 2


async def test_upsert_report_duplicate_url_does_not_orphan_source(
    db_session: AsyncSession, aliases
) -> None:
    """Second Codex review round: if two rows share a url_canonical
    but differ in author, the second row must not insert a new source.
    Otherwise `sources` accumulates orphaned rows for every
    inconsistent duplicate."""
    first = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    # Same URL, different author. Second row's `Other Vendor` must
    # never reach the sources table — the report row is rejected as
    # a duplicate and the author would otherwise be an orphan.
    second = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Other Vendor",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    await upsert_report(db_session, first, aliases)
    await upsert_report(db_session, second, aliases)

    source_names = (
        await db_session.execute(sa.select(sources_table.c.name))
    ).scalars().all()
    assert source_names == ["Mandiant"]
    assert await _count(db_session, sources_table) == 1
    assert await _count(db_session, reports_table) == 1


async def test_upsert_report_duplicate_url_merges_tags(
    db_session: AsyncSession, aliases
) -> None:
    """When two workbook rows share a canonical URL, the second row's
    tags must still be attached to the single surviving report row.
    Otherwise dedupe turns into silent data loss — the issue Codex
    flagged during the PR #5 review."""
    first = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    second = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#crypto #cve-2024-1234",
    )
    first_outcome = await upsert_report(db_session, first, aliases)
    second_outcome = await upsert_report(db_session, second, aliases)

    assert first_outcome.id == second_outcome.id
    assert first_outcome.action is UpsertAction.INSERTED
    assert second_outcome.action is UpsertAction.EXISTING
    # Only one reports row survives…
    assert await _count(db_session, reports_table) == 1
    # …but both rows' tags are attached to it.
    assert await _count(db_session, tags_table) == 3  # lazarus, crypto, cve-2024-1234
    assert await _count(db_session, report_tags_table) == 3


async def test_upsert_report_duplicate_url_backfills_unknown_source(
    db_session: AsyncSession, aliases
) -> None:
    """Codex round 6: if the first workbook row at a URL had no
    author (source_id -> synthetic `unknown`) and a later row at the
    same URL has the real vendor name, the report's source_id must
    be updated. Leaving the report attributed to `unknown` when we
    have better data is silent metadata loss."""
    anonymous = ReportRow(
        published=dt.date(2024, 3, 15),
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    attributed = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    first = await upsert_report(db_session, anonymous, aliases)
    second = await upsert_report(db_session, attributed, aliases)

    assert first.id == second.id
    assert second.action is UpsertAction.EXISTING
    assert await _count(db_session, reports_table) == 1

    # Report now points at the real vendor source, not `unknown`.
    resolved_source = (await db_session.execute(
        sa.select(sources_table.c.name)
        .select_from(reports_table.join(
            sources_table, reports_table.c.source_id == sources_table.c.id
        ))
        .where(reports_table.c.id == first.id)
    )).first()
    assert resolved_source[0] == "Mandiant"


async def test_upsert_report_duplicate_url_keeps_real_source(
    db_session: AsyncSession, aliases
) -> None:
    """The inverse guard: if the first row already has a real vendor
    source, a later duplicate-URL row with a different author must
    NOT overwrite it. Source backfill is only for the synthetic
    `unknown` case."""
    first = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    second = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Other Vendor",
        title="Lazarus macOS backdoor",
        url="https://example.com/threat/lazarus-macos",
        tags="#lazarus",
    )
    await upsert_report(db_session, first, aliases)
    await upsert_report(db_session, second, aliases)

    resolved_source = (await db_session.execute(
        sa.select(sources_table.c.name)
        .select_from(reports_table.join(
            sources_table, reports_table.c.source_id == sources_table.c.id
        ))
    )).first()
    assert resolved_source[0] == "Mandiant"
    assert await _count(db_session, sources_table) == 1


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


async def test_upsert_incident_duplicate_merges_mapping_rows(
    db_session: AsyncSession,
) -> None:
    """Second Codex round 3 issue: when a later workbook row resolves
    to the same `(title, reported)` incident but carries a different
    country / sector / motivation, the extra mapping values must
    still land. The mapping tables exist specifically to preserve
    multi-valued attributes, so dropping them on duplicate-key is
    silent data loss."""
    first = IncidentRow(
        reported=dt.date(2022, 3, 23),
        victims="Ronin Network",
        motivations="financial",
        sectors="crypto",
        countries="VN",
    )
    # Same incident, different country / sector / motivation.
    second = IncidentRow(
        reported=dt.date(2022, 3, 23),
        victims="Ronin Network",
        motivations="espionage",
        sectors="finance",
        countries="US",
    )
    first_outcome = await upsert_incident(db_session, first)
    second_outcome = await upsert_incident(db_session, second)

    assert first_outcome.id == second_outcome.id
    assert second_outcome.action is UpsertAction.EXISTING
    assert await _count(db_session, incidents_table) == 1

    # Each mapping table now has two rows — both from the first and
    # second pass — attached to the single incident.
    assert await _count(db_session, incident_motivations_table) == 2
    assert await _count(db_session, incident_sectors_table) == 2
    assert await _count(db_session, incident_countries_table) == 2


async def test_upsert_incident_duplicate_exact_row_is_noop(
    db_session: AsyncSession,
) -> None:
    """Loading the exact same incident row twice is a pure no-op.
    This is a stricter version of the idempotency test above, for
    the case where second row has no new mapping values."""
    row = IncidentRow(
        reported=dt.date(2022, 3, 23),
        victims="Ronin Network",
        motivations="financial",
        sectors="crypto",
        countries="VN",
    )
    await upsert_incident(db_session, row)
    await upsert_incident(db_session, row)
    assert await _count(db_session, incidents_table) == 1
    assert await _count(db_session, incident_motivations_table) == 1
    assert await _count(db_session, incident_sectors_table) == 1
    assert await _count(db_session, incident_countries_table) == 1


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


# ---------------------------------------------------------------------------
# Codex round 2 regression: EXISTING outcomes that mutate must surface
# the real changed_fields for downstream audit lineage
# ---------------------------------------------------------------------------


async def test_upsert_codename_backfill_surfaces_changed_fields(
    db_session: AsyncSession,
) -> None:
    """When ``upsert_codename`` updates an existing row (group_id /
    named_by_source_id / first_seen / last_seen backfill), the
    returned outcome must carry ``changed_fields`` with D3a's
    ``{column: {before, after}}`` contract so audit lineage can
    reconstruct both halves of the diff (Codex round 2 P2 + round
    3 P2). Without this, downstream audit lineage loses the
    "what was overwritten" half and records the update as
    ``changed: {}`` or ``changed: {col: new}`` rather than the
    canonical before/after shape."""
    group = await upsert_group(db_session, "Lazarus")
    source = await upsert_source(db_session, "Kaspersky")

    # Pass 1: no group / no source — both null.
    first = await upsert_codename(
        db_session,
        name="HIDDEN COBRA",
        group_id=None,
        first_seen=None,
        last_seen=None,
    )
    assert first.action is UpsertAction.INSERTED
    assert first.changed_fields is None

    # Pass 2: real backfill on every patch candidate.
    second = await upsert_codename(
        db_session,
        name="HIDDEN COBRA",
        group_id=group.id,
        named_by_source_id=source.id,
        first_seen=dt.date(2009, 2, 1),
        last_seen=dt.date(2025, 12, 15),
    )
    assert second.action is UpsertAction.EXISTING
    assert second.changed_fields == {
        "group_id": {"before": None, "after": group.id},
        "named_by_source_id": {"before": None, "after": source.id},
        "first_seen": {"before": None, "after": dt.date(2009, 2, 1)},
        "last_seen": {"before": None, "after": dt.date(2025, 12, 15)},
    }

    # Pass 3: nothing new to backfill — truly idempotent.
    third = await upsert_codename(
        db_session,
        name="HIDDEN COBRA",
        group_id=group.id,
        named_by_source_id=source.id,
        first_seen=dt.date(2009, 2, 1),
        last_seen=dt.date(2025, 12, 15),
    )
    assert third.action is UpsertAction.EXISTING
    assert third.changed_fields is None


async def test_upsert_report_anonymous_promotion_surfaces_changed_fields(
    db_session: AsyncSession, aliases
) -> None:
    """The anonymous→real-vendor promotion path must report both
    the before and after value for ``source_id`` + the URL columns
    so audit lineage can distinguish a no-op re-run from a real
    promotion AND reconstruct which source the row was promoted
    away from."""
    # Pass 1: landing under the synthetic `unknown` source with URL_A.
    anon_row = ReportRow(
        published=dt.date(2024, 3, 15),
        author=None,
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-a",
        tags=None,
    )
    anon_outcome = await upsert_report(db_session, anon_row, aliases)
    assert anon_outcome.action is UpsertAction.INSERTED

    # Fetch the "unknown" source id so we can assert the before
    # value on the promotion event.
    unknown_source_id = (
        await db_session.execute(
            sa.select(sources_table.c.id).where(sources_table.c.name == "unknown")
        )
    ).scalar_one()

    # Pass 2: same title, DIFFERENT URL, real vendor — must promote
    # the existing row to the new source AND update the URL fields.
    promoted_row = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-b",
        tags=None,
    )
    promoted = await upsert_report(db_session, promoted_row, aliases)

    assert promoted.id == anon_outcome.id
    assert promoted.action is UpsertAction.EXISTING
    assert promoted.changed_fields is not None
    # source_id diff carries both the `unknown` id and the new vendor id.
    source_diff = promoted.changed_fields["source_id"]
    assert source_diff["before"] == unknown_source_id
    assert source_diff["after"] != unknown_source_id
    # URL fields carry before/after for the moved URL.
    url_diff = promoted.changed_fields["url"]
    assert url_diff["before"] == "https://example.com/threat/lazarus-a"
    assert url_diff["after"] == "https://example.com/threat/lazarus-b"
    assert "url_canonical" in promoted.changed_fields


async def test_upsert_report_title_hash_moved_url_surfaces_changed_fields(
    db_session: AsyncSession, aliases
) -> None:
    """The title-hash fallback 'same article, new URL' path must
    report ``url`` / ``url_canonical`` in ``changed_fields`` with
    the D3a before/after shape so lineage can track the URL
    mutation."""
    base_row = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-v1",
        tags=None,
    )
    first = await upsert_report(db_session, base_row, aliases)
    assert first.action is UpsertAction.INSERTED

    moved_row = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-v2",
        tags=None,
    )
    second = await upsert_report(db_session, moved_row, aliases)
    assert second.id == first.id
    assert second.action is UpsertAction.EXISTING
    assert second.changed_fields is not None
    url_diff = second.changed_fields["url"]
    assert url_diff["before"] == "https://example.com/threat/lazarus-v1"
    assert url_diff["after"] == "https://example.com/threat/lazarus-v2"
    url_canonical_diff = second.changed_fields["url_canonical"]
    assert url_canonical_diff["before"] != url_canonical_diff["after"]


async def test_upsert_report_idempotent_rerun_has_no_changed_fields(
    db_session: AsyncSession, aliases
) -> None:
    """Guardrail: a truly idempotent second upsert (identical URL,
    same vendor, no backfill) must still produce EXISTING outcome
    with ``changed_fields is None`` so the audit event degrades to
    an empty-changed update."""
    row = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-v1",
        tags=None,
    )
    first = await upsert_report(db_session, row, aliases)
    second = await upsert_report(db_session, row, aliases)
    assert second.id == first.id
    assert second.action is UpsertAction.EXISTING
    assert second.changed_fields is None
