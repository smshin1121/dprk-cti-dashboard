"""Feed catalog loader with bijection lint.

Loads ``data/dictionaries/feeds.yml`` and validates structural
invariants at load time. Pattern follows
``worker.bootstrap.aliases.load_aliases``.

Resolution order for the default path:
  1. Repo checkout — ``<repo>/data/dictionaries/feeds.yml``.
  2. Packaged wheel — ``worker/ingest/data/feeds.yml`` (force-included
     via hatch; same mechanism as ``aliases.yml``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, field_validator


__all__ = [
    "FeedCatalogError",
    "FeedConfig",
    "FeedCatalog",
    "load_feeds",
    "default_feeds_path",
]


_PACKAGE_DIR = Path(__file__).resolve().parent


class FeedCatalogError(ValueError):
    """Raised when the YAML feed catalog violates a load-time invariant."""


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class FeedConfig(BaseModel, frozen=True):
    """Single feed entry from ``feeds.yml``."""

    slug: str
    display_name: str
    url: str
    kind: Literal["rss", "atom"]
    enabled: bool = True
    poll_interval_minutes: int = 15

    @field_validator("slug")
    @classmethod
    def _slug_format(cls, v: str) -> str:
        v = v.strip()
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase, hyphen-separated alphanumeric "
                f"(e.g. 'kaspersky-securelist'), got {v!r}"
            )
        return v

    @field_validator("display_name")
    @classmethod
    def _display_name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must be a non-empty string")
        return v

    @field_validator("url")
    @classmethod
    def _url_valid_http(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                f"url must be an absolute http/https URL, got {v!r}"
            )
        return v

    @field_validator("poll_interval_minutes")
    @classmethod
    def _poll_interval_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("poll_interval_minutes must be >= 1")
        return v


@dataclass(frozen=True, slots=True)
class FeedCatalog:
    """Validated, immutable catalog of feed configurations."""

    feeds: tuple[FeedConfig, ...]

    @property
    def enabled(self) -> tuple[FeedConfig, ...]:
        return tuple(f for f in self.feeds if f.enabled)

    def __len__(self) -> int:
        return len(self.feeds)


def _validate_bijection(feeds: Sequence[FeedConfig], source: Path) -> None:
    """Enforce unique slug and unique url across all entries."""
    seen_slugs: dict[str, int] = {}
    seen_urls: dict[str, str] = {}

    for idx, feed in enumerate(feeds):
        if feed.slug in seen_slugs:
            prev = seen_slugs[feed.slug]
            raise FeedCatalogError(
                f"{source}: duplicate slug {feed.slug!r} "
                f"at entries {prev} and {idx}"
            )
        seen_slugs[feed.slug] = idx

        if feed.url in seen_urls:
            owner = seen_urls[feed.url]
            raise FeedCatalogError(
                f"{source}: duplicate url {feed.url!r} "
                f"claimed by slugs {owner!r} and {feed.slug!r}"
            )
        seen_urls[feed.url] = feed.slug


def load_feeds(path: Path | str) -> FeedCatalog:
    """Load and validate the feed catalog at ``path``.

    Raises :class:`FeedCatalogError` on structural violations
    (duplicate slug, duplicate url, malformed YAML, missing fields).
    """
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        try:
            raw = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise FeedCatalogError(f"{source}: invalid YAML — {exc}") from exc

    if raw is None:
        raise FeedCatalogError(f"{source}: file is empty")
    if not isinstance(raw, list):
        raise FeedCatalogError(
            f"{source}: top-level YAML must be a list of feed entries"
        )

    feeds: list[FeedConfig] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise FeedCatalogError(
                f"{source}: entry {idx} must be a mapping, "
                f"got {type(entry).__name__}"
            )
        try:
            feeds.append(FeedConfig(**entry))
        except Exception as exc:
            raise FeedCatalogError(
                f"{source}: entry {idx} (slug={entry.get('slug', '?')}): {exc}"
            ) from exc

    _validate_bijection(feeds, source)
    return FeedCatalog(feeds=tuple(feeds))


def default_feeds_path() -> Path:
    """Resolve the default feed catalog path.

    Resolution order: repo checkout -> packaged wheel data.
    Same dual-resolution pattern as ``worker.bootstrap.cli._default_aliases_path``.
    """
    checkout_candidate = _PACKAGE_DIR.parents[4] / "data/dictionaries/feeds.yml"
    if checkout_candidate.exists():
        return checkout_candidate
    return _PACKAGE_DIR / "data/feeds.yml"
