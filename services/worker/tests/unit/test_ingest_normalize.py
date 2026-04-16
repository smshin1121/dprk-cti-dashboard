"""Tests for worker.ingest.normalize — RawFeedEntry -> StagingRowDraft."""

from __future__ import annotations

import datetime as dt

from worker.bootstrap.normalize import canonicalize_url, sha256_title
from worker.ingest.normalize import StagingRowDraft, normalize_entry
from worker.ingest.parser import RawFeedEntry


# ---------------------------------------------------------------------------
# canonicalize_url reuse
# ---------------------------------------------------------------------------


def test_url_canonical_matches_bootstrap() -> None:
    entry = RawFeedEntry(
        title="Test",
        link="https://EXAMPLE.COM:443/reports/test?utm_source=twitter&page=1",
        published_raw=None,
        summary=None,
    )
    draft = normalize_entry(entry)

    assert draft is not None
    expected = canonicalize_url(entry.link)
    assert draft.url_canonical == expected


# ---------------------------------------------------------------------------
# sha256_title reuse
# ---------------------------------------------------------------------------


def test_sha256_title_matches_bootstrap() -> None:
    entry = RawFeedEntry(
        title="Lazarus Group Report",
        link="https://example.com/report",
        published_raw=None,
        summary=None,
    )
    draft = normalize_entry(entry)

    assert draft is not None
    expected = sha256_title("Lazarus Group Report")
    assert draft.sha256_title == expected


# ---------------------------------------------------------------------------
# Empty title — kept, not dropped
# ---------------------------------------------------------------------------


def test_empty_title_produces_draft_with_none_title() -> None:
    entry = RawFeedEntry(
        title=None,
        link="https://example.com/no-title",
        published_raw=None,
        summary="some summary",
    )
    draft = normalize_entry(entry)

    assert draft is not None
    assert draft.title is None
    assert draft.sha256_title is None
    assert draft.url_canonical is not None


# ---------------------------------------------------------------------------
# No link — returns None (cannot compute url_canonical)
# ---------------------------------------------------------------------------


def test_no_link_returns_none() -> None:
    entry = RawFeedEntry(title="Has title", link=None, published_raw=None, summary=None)
    assert normalize_entry(entry) is None


# ---------------------------------------------------------------------------
# Published date parsing
# ---------------------------------------------------------------------------


def test_published_rfc2822_with_tz() -> None:
    entry = RawFeedEntry(
        title="X",
        link="https://example.com/1",
        published_raw="Mon, 14 Apr 2026 09:00:00 GMT",
        summary=None,
    )
    draft = normalize_entry(entry)

    assert draft is not None
    assert draft.published is not None
    assert draft.published.tzinfo is not None
    assert draft.published.year == 2026
    assert draft.published.month == 4
    assert draft.published.day == 14


def test_published_rfc2822_with_offset() -> None:
    entry = RawFeedEntry(
        title="X",
        link="https://example.com/2",
        published_raw="Sun, 13 Apr 2026 15:30:00 +0900",
        summary=None,
    )
    draft = normalize_entry(entry)

    assert draft is not None
    assert draft.published is not None
    assert draft.published.tzinfo is not None


def test_published_naive_assumed_utc() -> None:
    entry = RawFeedEntry(
        title="X",
        link="https://example.com/3",
        published_raw="14 Apr 2026 09:00:00",
        summary=None,
    )
    draft = normalize_entry(entry)

    assert draft is not None
    if draft.published is not None:
        assert draft.published.tzinfo is not None


def test_published_missing_is_none() -> None:
    entry = RawFeedEntry(title="X", link="https://example.com/4", published_raw=None, summary=None)
    draft = normalize_entry(entry)

    assert draft is not None
    assert draft.published is None


def test_published_unparseable_is_none() -> None:
    entry = RawFeedEntry(title="X", link="https://example.com/5", published_raw="not-a-date", summary=None)
    draft = normalize_entry(entry)

    assert draft is not None
    assert draft.published is None


# ---------------------------------------------------------------------------
# StagingRowDraft is frozen
# ---------------------------------------------------------------------------


def test_staging_row_draft_is_frozen() -> None:
    draft = StagingRowDraft(
        url="https://example.com/x",
        url_canonical="example.com/x",
        sha256_title=None,
        title=None,
        published=None,
        summary=None,
    )
    import pytest
    with pytest.raises(AttributeError):
        draft.title = "mutate"  # type: ignore[misc]
