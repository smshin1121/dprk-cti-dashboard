"""Tests for worker.ingest.config — feed catalog loader + bijection lint."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from worker.ingest.config import (
    FeedCatalog,
    FeedCatalogError,
    FeedConfig,
    default_feeds_path,
    load_feeds,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REAL_FEEDS = REPO_ROOT / "data/dictionaries/feeds.yml"


# ---------------------------------------------------------------------------
# Happy path against the real committed feeds.yml
# ---------------------------------------------------------------------------


def test_real_feeds_loads_without_error() -> None:
    catalog = load_feeds(REAL_FEEDS)
    assert len(catalog) >= 5


def test_real_feeds_all_have_unique_slugs() -> None:
    catalog = load_feeds(REAL_FEEDS)
    slugs = [f.slug for f in catalog.feeds]
    assert len(slugs) == len(set(slugs))


def test_real_feeds_all_have_unique_urls() -> None:
    catalog = load_feeds(REAL_FEEDS)
    urls = [f.url for f in catalog.feeds]
    assert len(urls) == len(set(urls))


def test_real_feeds_kind_is_rss_or_atom() -> None:
    catalog = load_feeds(REAL_FEEDS)
    for feed in catalog.feeds:
        assert feed.kind in ("rss", "atom")


def test_real_feeds_at_least_one_enabled() -> None:
    catalog = load_feeds(REAL_FEEDS)
    assert len(catalog.enabled) >= 1


def test_real_feeds_poll_interval_positive() -> None:
    catalog = load_feeds(REAL_FEEDS)
    for feed in catalog.feeds:
        assert feed.poll_interval_minutes >= 1


# ---------------------------------------------------------------------------
# FeedConfig pydantic model
# ---------------------------------------------------------------------------


def test_feed_config_accepts_valid_entry() -> None:
    fc = FeedConfig(
        slug="test-feed",
        display_name="Test Feed",
        url="https://example.com/feed.xml",
        kind="rss",
    )
    assert fc.slug == "test-feed"
    assert fc.enabled is True
    assert fc.poll_interval_minutes == 15


def test_feed_config_accepts_atom_kind() -> None:
    fc = FeedConfig(
        slug="atom-feed",
        display_name="Atom Feed",
        url="https://example.com/atom.xml",
        kind="atom",
    )
    assert fc.kind == "atom"


def test_feed_config_rejects_invalid_kind() -> None:
    with pytest.raises(Exception):
        FeedConfig(
            slug="bad",
            display_name="Bad",
            url="https://example.com/feed",
            kind="json",  # type: ignore[arg-type]
        )


def test_feed_config_rejects_blank_slug() -> None:
    with pytest.raises(Exception, match="slug"):
        FeedConfig(
            slug="  ",
            display_name="X",
            url="https://example.com/feed",
            kind="rss",
        )


def test_feed_config_rejects_uppercase_slug() -> None:
    with pytest.raises(Exception, match="slug"):
        FeedConfig(
            slug="AhnLab-ASEC",
            display_name="X",
            url="https://example.com/feed",
            kind="rss",
        )


def test_feed_config_rejects_slug_with_spaces() -> None:
    with pytest.raises(Exception, match="slug"):
        FeedConfig(
            slug="has spaces",
            display_name="X",
            url="https://example.com/feed",
            kind="rss",
        )


def test_feed_config_rejects_blank_url() -> None:
    with pytest.raises(Exception, match="url"):
        FeedConfig(
            slug="s",
            display_name="X",
            url="",
            kind="rss",
        )


def test_feed_config_rejects_non_http_url() -> None:
    with pytest.raises(Exception, match="http"):
        FeedConfig(
            slug="s",
            display_name="X",
            url="ftp://example.com/feed",
            kind="rss",
        )


def test_feed_config_rejects_relative_url() -> None:
    with pytest.raises(Exception, match="url"):
        FeedConfig(
            slug="s",
            display_name="X",
            url="/feed.xml",
            kind="rss",
        )


def test_feed_config_rejects_zero_poll_interval() -> None:
    with pytest.raises(Exception):
        FeedConfig(
            slug="s",
            display_name="X",
            url="https://example.com/feed",
            kind="rss",
            poll_interval_minutes=0,
        )


def test_feed_config_rejects_negative_poll_interval() -> None:
    with pytest.raises(Exception):
        FeedConfig(
            slug="s",
            display_name="X",
            url="https://example.com/feed",
            kind="rss",
            poll_interval_minutes=-1,
        )


def test_feed_config_disabled_feed() -> None:
    fc = FeedConfig(
        slug="off",
        display_name="Disabled",
        url="https://example.com/off",
        kind="rss",
        enabled=False,
    )
    assert fc.enabled is False


# ---------------------------------------------------------------------------
# FeedCatalog — enabled filter
# ---------------------------------------------------------------------------


def test_catalog_enabled_filter() -> None:
    feeds = (
        FeedConfig(slug="a", display_name="A", url="https://a.com/feed", kind="rss", enabled=True),
        FeedConfig(slug="b", display_name="B", url="https://b.com/feed", kind="rss", enabled=False),
        FeedConfig(slug="c", display_name="C", url="https://c.com/feed", kind="atom", enabled=True),
    )
    catalog = FeedCatalog(feeds=feeds)
    assert len(catalog.enabled) == 2
    assert all(f.enabled for f in catalog.enabled)


# ---------------------------------------------------------------------------
# Loader failure modes
# ---------------------------------------------------------------------------


def test_load_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.yml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(FeedCatalogError, match="empty"):
        load_feeds(p)


def test_load_non_list_top_level(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("feeds:\n  - slug: x\n", encoding="utf-8")
    with pytest.raises(FeedCatalogError, match="list"):
        load_feeds(p)


def test_load_non_mapping_entry(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("- just a string\n", encoding="utf-8")
    with pytest.raises(FeedCatalogError, match="mapping"):
        load_feeds(p)


def test_load_missing_required_field(tmp_path: Path) -> None:
    entries = [{"slug": "x", "display_name": "X", "kind": "rss"}]
    p = tmp_path / "missing.yml"
    p.write_text(yaml.dump(entries), encoding="utf-8")
    with pytest.raises(FeedCatalogError, match="Field required"):
        load_feeds(p)


def test_load_duplicate_slug(tmp_path: Path) -> None:
    entries = [
        {"slug": "dup", "display_name": "A", "url": "https://a.com/feed", "kind": "rss"},
        {"slug": "dup", "display_name": "B", "url": "https://b.com/feed", "kind": "rss"},
    ]
    p = tmp_path / "dup_slug.yml"
    p.write_text(yaml.dump(entries), encoding="utf-8")
    with pytest.raises(FeedCatalogError, match="duplicate slug"):
        load_feeds(p)


def test_load_duplicate_url(tmp_path: Path) -> None:
    entries = [
        {"slug": "a", "display_name": "A", "url": "https://same.com/feed", "kind": "rss"},
        {"slug": "b", "display_name": "B", "url": "https://same.com/feed", "kind": "atom"},
    ]
    p = tmp_path / "dup_url.yml"
    p.write_text(yaml.dump(entries), encoding="utf-8")
    with pytest.raises(FeedCatalogError, match="duplicate url"):
        load_feeds(p)


def test_load_malformed_yaml(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("- slug: x\n  url: [broken\n", encoding="utf-8")
    with pytest.raises(FeedCatalogError, match="invalid YAML"):
        load_feeds(p)


# ---------------------------------------------------------------------------
# Default path resolution
# ---------------------------------------------------------------------------


def test_default_feeds_path_resolves_to_existing_file() -> None:
    p = default_feeds_path()
    assert p.exists(), f"default feeds path {p} does not exist"
    assert p.name == "feeds.yml"


def test_default_feeds_path_loadable() -> None:
    catalog = load_feeds(default_feeds_path())
    assert len(catalog) >= 1
