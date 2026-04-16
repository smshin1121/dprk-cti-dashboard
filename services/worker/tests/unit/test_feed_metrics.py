"""Tests for worker.data_quality.expectations.feed_metrics — D10 metrics."""

from __future__ import annotations

from decimal import Decimal

from worker.data_quality.expectations.feed_metrics import (
    check_empty_title_rate,
    check_fetch_failure_rate,
    check_parse_error_rate,
    check_unknown_tag_rate,
)


# ---------------------------------------------------------------------------
# feed.fetch_failure_rate
# ---------------------------------------------------------------------------


def test_fetch_failure_rate_pass() -> None:
    r = check_fetch_failure_rate(total_feeds=5, failed_feeds=0)
    assert r.name == "feed.fetch_failure_rate"
    assert r.severity == "pass"
    assert r.observed == Decimal("0")


def test_fetch_failure_rate_warn() -> None:
    r = check_fetch_failure_rate(total_feeds=5, failed_feeds=2)
    assert r.severity == "warn"
    assert float(r.observed) > 0.20


def test_fetch_failure_rate_all_failed() -> None:
    r = check_fetch_failure_rate(total_feeds=5, failed_feeds=5)
    assert r.severity == "warn"
    assert float(r.observed) == 1.0


def test_fetch_failure_rate_zero_feeds() -> None:
    r = check_fetch_failure_rate(total_feeds=0, failed_feeds=0)
    assert r.severity == "pass"
    assert r.observed == Decimal("0")


# ---------------------------------------------------------------------------
# feed.parse_error_rate
# ---------------------------------------------------------------------------


def test_parse_error_rate_pass() -> None:
    r = check_parse_error_rate(fetched_feeds=5, parse_errors=0)
    assert r.name == "feed.parse_error_rate"
    assert r.severity == "pass"


def test_parse_error_rate_warn() -> None:
    r = check_parse_error_rate(fetched_feeds=5, parse_errors=1)
    assert r.severity == "warn"


def test_parse_error_rate_zero_fetched() -> None:
    r = check_parse_error_rate(fetched_feeds=0, parse_errors=0)
    assert r.severity == "pass"


# ---------------------------------------------------------------------------
# feed.empty_title_rate
# ---------------------------------------------------------------------------


def test_empty_title_rate_pass() -> None:
    r = check_empty_title_rate(total_entries=100, empty_titles=3)
    assert r.name == "feed.empty_title_rate"
    assert r.severity == "pass"


def test_empty_title_rate_warn() -> None:
    r = check_empty_title_rate(total_entries=100, empty_titles=10)
    assert r.severity == "warn"


def test_empty_title_rate_zero_entries() -> None:
    r = check_empty_title_rate(total_entries=0, empty_titles=0)
    assert r.severity == "pass"


# ---------------------------------------------------------------------------
# rss.tags.unknown_rate
# ---------------------------------------------------------------------------


def test_unknown_tag_rate_pass() -> None:
    r = check_unknown_tag_rate(total_tags=10, unknown_tags=2)
    assert r.name == "rss.tags.unknown_rate"
    assert r.severity == "pass"


def test_unknown_tag_rate_deprecated_always_passes() -> None:
    """D6 deprecation (PR #9): threshold raised to 1.0, always passes."""
    r = check_unknown_tag_rate(total_tags=10, unknown_tags=5)
    assert r.severity == "pass"  # Was "warn" at 0.30 threshold, now 1.0


def test_unknown_tag_rate_zero_tags() -> None:
    r = check_unknown_tag_rate(total_tags=0, unknown_tags=0)
    assert r.severity == "pass"


# ---------------------------------------------------------------------------
# Name prefix assertions
# ---------------------------------------------------------------------------


def test_all_names_prefixed() -> None:
    results = [
        check_fetch_failure_rate(5, 0),
        check_parse_error_rate(5, 0),
        check_empty_title_rate(100, 0),
        check_unknown_tag_rate(10, 0),
    ]
    for r in results:
        assert r.name.startswith("feed.") or r.name.startswith("rss."), \
            f"{r.name} has wrong prefix"


# ---------------------------------------------------------------------------
# Severity assertions — all warn-only, never error
# ---------------------------------------------------------------------------


def test_all_severities_are_pass_or_warn() -> None:
    results = [
        check_fetch_failure_rate(1, 1),
        check_parse_error_rate(1, 1),
        check_empty_title_rate(1, 1),
        check_unknown_tag_rate(1, 1),
    ]
    for r in results:
        assert r.severity in ("pass", "warn"), \
            f"{r.name} has severity {r.severity}, expected pass or warn"
