"""RSS / Atom feed parser — feedparser.parse(bytes) only.

Per D5, the network-embedded form ``feedparser.parse(url)`` is
forbidden. This module accepts raw bytes from the fetcher and
returns parsed entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import feedparser


__all__ = [
    "ParseError",
    "ParseOutcome",
    "RawFeedEntry",
    "parse_feed",
]


_BENIGN_BOZO_TYPES = (
    feedparser.CharacterEncodingOverride,
)


@dataclass(frozen=True, slots=True)
class RawFeedEntry:
    """One entry extracted from a parsed feed."""

    title: str | None
    link: str | None
    published_raw: str | None
    summary: str | None


@dataclass(frozen=True, slots=True)
class ParseError:
    """Captures a hard parse failure (bozo=1 with a non-benign exception)."""

    message: str
    exception_type: str


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """Result of parsing feed content bytes."""

    entries: tuple[RawFeedEntry, ...]
    parse_error: ParseError | None = None
    detected_kind: str | None = None


def parse_feed(
    content: bytes,
    kind: Literal["rss", "atom"],
) -> ParseOutcome:
    """Parse raw feed bytes via ``feedparser.parse(content)``.

    ``kind`` is advisory — feedparser auto-detects the format. We
    record the detected kind in the outcome for logging but do not
    reject on mismatch (real-world feeds frequently mis-declare).

    Bozo handling: feedparser sets ``bozo=1`` on any parse anomaly.
    We classify the bozo_exception type:
      - Benign (CharacterEncodingOverride, NonXMLContentType): ignored,
        entries are still usable.
      - Hard error (everything else): recorded as ``parse_error``,
        entries may still be partially populated.
    """
    parsed = feedparser.parse(content)

    detected_kind = _detect_kind(parsed)
    parse_error: ParseError | None = None

    if parsed.bozo:
        exc = parsed.bozo_exception
        if not isinstance(exc, _BENIGN_BOZO_TYPES):
            parse_error = ParseError(
                message=str(exc),
                exception_type=type(exc).__name__,
            )

    entries = tuple(
        RawFeedEntry(
            title=_clean_str(e.get("title")),
            link=_clean_str(e.get("link")),
            published_raw=_clean_str(e.get("published") or e.get("updated")),
            summary=_clean_str(e.get("summary")),
        )
        for e in parsed.entries
    )

    return ParseOutcome(
        entries=entries,
        parse_error=parse_error,
        detected_kind=detected_kind,
    )


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _detect_kind(parsed: Any) -> str | None:
    version = getattr(parsed, "version", "") or ""
    if version.startswith("rss"):
        return "rss"
    if version.startswith("atom"):
        return "atom"
    return version or None
