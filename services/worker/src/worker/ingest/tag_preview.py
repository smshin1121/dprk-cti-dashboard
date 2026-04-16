"""Pre-classification tag preview for the rss.tags.unknown_rate metric.

Extracts hashtag-like tokens from entry title + summary and runs them
through the bootstrap classifier. The result is a count pair used ONLY
for the D10 ``rss.tags.unknown_rate`` feed-level DQ metric — no
classified tags are persisted to staging (LLM enrichment is Phase 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from worker.bootstrap.aliases import AliasDictionary
from worker.bootstrap.normalize import TAG_TYPE_UNKNOWN, classify_tags


__all__ = [
    "TagPreviewResult",
    "preview_tags",
]


_HASHTAG_RE = re.compile(r"#[^\s#]+")


@dataclass(frozen=True, slots=True)
class TagPreviewResult:
    """Counts for the rss.tags.unknown_rate metric."""

    total: int
    unknown: int


def preview_tags(
    title: str | None,
    summary: str | None,
    aliases: AliasDictionary,
) -> TagPreviewResult:
    """Extract hashtags from title + summary and classify them.

    Returns (0, 0) when no hashtag tokens are present.
    """
    combined = " ".join(filter(None, [title, summary]))
    if not combined:
        return TagPreviewResult(total=0, unknown=0)

    tokens = _HASHTAG_RE.findall(combined)
    if not tokens:
        return TagPreviewResult(total=0, unknown=0)

    tags_cell = " ".join(tokens)
    classified = classify_tags(tags_cell, aliases)

    unknown = sum(1 for t in classified if t.type_ == TAG_TYPE_UNKNOWN)
    return TagPreviewResult(total=len(classified), unknown=unknown)
