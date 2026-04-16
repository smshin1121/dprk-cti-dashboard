"""Normalize a RawFeedEntry into a StagingRowDraft.

Reuses ``canonicalize_url`` and ``sha256_title`` from the bootstrap
normalize module (PR #5) so the staging dedup key space is identical
to the production ``reports.url_canonical`` space.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from worker.bootstrap.normalize import canonicalize_url, sha256_title
from worker.ingest.parser import RawFeedEntry


__all__ = [
    "StagingRowDraft",
    "normalize_entry",
]


@dataclass(frozen=True, slots=True)
class StagingRowDraft:
    """Ready-to-insert staging row. All LLM-filled columns are None."""

    url: str | None
    url_canonical: str
    sha256_title: str | None
    title: str | None
    published: dt.datetime | None
    summary: str | None


def normalize_entry(entry: RawFeedEntry) -> StagingRowDraft | None:
    """Convert a parsed feed entry to a staging draft.

    Returns ``None`` if the entry has no usable link (url_canonical
    cannot be computed without a URL, and UNIQUE dedup depends on it).
    Entries with empty titles are kept — they count toward the
    ``feed.empty_title_rate`` DQ metric.
    """
    if not entry.link:
        return None

    url_canon = canonicalize_url(entry.link)
    title_hash = sha256_title(entry.title) if entry.title else None
    published = _parse_published(entry.published_raw)

    return StagingRowDraft(
        url=entry.link,
        url_canonical=url_canon,
        sha256_title=title_hash,
        title=entry.title,
        published=published,
        summary=None,
    )


def _parse_published(raw: str | None) -> dt.datetime | None:
    """Parse an RFC 2822 date string from RSS/Atom published field.

    Returns a tz-aware datetime. Naive datetimes (no timezone info)
    are assumed UTC per plan convention — no complex timezone inference.
    """
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed
