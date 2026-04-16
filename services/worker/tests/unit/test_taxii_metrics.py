"""Tests for worker.data_quality.expectations.taxii_metrics — TAXII DQ.

Verifies taxii.* namespace isolation, threshold behavior, and the
label_unmapped_rate denominator semantics (only objects with labels).
"""

from __future__ import annotations

from decimal import Decimal

from worker.data_quality.expectations.taxii_metrics import (
    check_taxii_empty_description_rate,
    check_taxii_fetch_failure_rate,
    check_taxii_label_unmapped_rate,
    check_taxii_stix_parse_error_rate,
)


# ---------------------------------------------------------------------------
# Namespace isolation — all names start with "taxii."
# ---------------------------------------------------------------------------


def test_all_metric_names_use_taxii_prefix() -> None:
    """taxii.* namespace must not collide with feed.*/rss.*/production."""
    results = [
        check_taxii_fetch_failure_rate(5, 0),
        check_taxii_stix_parse_error_rate(100, 0),
        check_taxii_empty_description_rate(100, 0),
        check_taxii_label_unmapped_rate(50, 0),
    ]
    for r in results:
        assert r.name.startswith("taxii."), f"{r.name} missing taxii. prefix"


def test_no_collision_with_rss_metrics() -> None:
    """Verify names don't match any PR #8 feed.*/rss.* metric."""
    from worker.data_quality.expectations.feed_metrics import (
        check_empty_title_rate,
        check_fetch_failure_rate,
        check_parse_error_rate,
        check_unknown_tag_rate,
    )
    rss_names = {
        check_fetch_failure_rate(1, 0).name,
        check_parse_error_rate(1, 0).name,
        check_empty_title_rate(1, 0).name,
        check_unknown_tag_rate(1, 0).name,
    }
    taxii_names = {
        check_taxii_fetch_failure_rate(1, 0).name,
        check_taxii_stix_parse_error_rate(1, 0).name,
        check_taxii_empty_description_rate(1, 0).name,
        check_taxii_label_unmapped_rate(1, 0).name,
    }
    assert rss_names.isdisjoint(taxii_names)


# ---------------------------------------------------------------------------
# taxii.fetch_failure_rate
# ---------------------------------------------------------------------------


def test_fetch_failure_rate_pass() -> None:
    r = check_taxii_fetch_failure_rate(total_collections=5, failed_collections=0)
    assert r.severity == "pass"
    assert r.name == "taxii.fetch_failure_rate"
    assert r.observed == Decimal("0")


def test_fetch_failure_rate_warn() -> None:
    r = check_taxii_fetch_failure_rate(total_collections=3, failed_collections=1)
    assert r.severity == "warn"  # 0.333 > 0.20


def test_fetch_failure_rate_zero_collections() -> None:
    r = check_taxii_fetch_failure_rate(total_collections=0, failed_collections=0)
    assert r.severity == "pass"
    assert r.observed == Decimal("0")


# ---------------------------------------------------------------------------
# taxii.stix_parse_error_rate
# ---------------------------------------------------------------------------


def test_stix_parse_error_rate_pass() -> None:
    r = check_taxii_stix_parse_error_rate(total_objects=100, malformed_objects=5)
    assert r.severity == "pass"  # 0.05 < 0.10


def test_stix_parse_error_rate_warn() -> None:
    r = check_taxii_stix_parse_error_rate(total_objects=100, malformed_objects=15)
    assert r.severity == "warn"  # 0.15 > 0.10


def test_stix_parse_error_rate_zero_objects() -> None:
    r = check_taxii_stix_parse_error_rate(total_objects=0, malformed_objects=0)
    assert r.severity == "pass"


# ---------------------------------------------------------------------------
# taxii.empty_description_rate
# ---------------------------------------------------------------------------


def test_empty_description_rate_pass() -> None:
    r = check_taxii_empty_description_rate(total_ingested=100, empty_descriptions=20)
    assert r.severity == "pass"  # 0.20 < 0.30


def test_empty_description_rate_warn() -> None:
    r = check_taxii_empty_description_rate(total_ingested=100, empty_descriptions=40)
    assert r.severity == "warn"  # 0.40 > 0.30


def test_empty_description_rate_zero_ingested() -> None:
    r = check_taxii_empty_description_rate(total_ingested=0, empty_descriptions=0)
    assert r.severity == "pass"


# ---------------------------------------------------------------------------
# taxii.label_unmapped_rate — primary coverage metric (D6)
# ---------------------------------------------------------------------------


def test_label_unmapped_rate_pass() -> None:
    r = check_taxii_label_unmapped_rate(total_labels=100, unmapped_labels=30)
    assert r.severity == "pass"  # 0.30 < 0.50


def test_label_unmapped_rate_warn() -> None:
    r = check_taxii_label_unmapped_rate(total_labels=100, unmapped_labels=60)
    assert r.severity == "warn"  # 0.60 > 0.50


def test_label_unmapped_rate_zero_labels() -> None:
    """When no objects have labels, rate is 0 (denominator-safe)."""
    r = check_taxii_label_unmapped_rate(total_labels=0, unmapped_labels=0)
    assert r.severity == "pass"
    assert r.observed == Decimal("0")


def test_label_unmapped_rate_all_unmapped() -> None:
    r = check_taxii_label_unmapped_rate(total_labels=10, unmapped_labels=10)
    assert r.severity == "warn"  # 1.0 > 0.50


def test_label_unmapped_rate_name() -> None:
    r = check_taxii_label_unmapped_rate(total_labels=10, unmapped_labels=0)
    assert r.name == "taxii.label_unmapped_rate"


# ---------------------------------------------------------------------------
# All metrics are warn-severity only (never error)
# ---------------------------------------------------------------------------


def test_all_metrics_are_warn_or_pass() -> None:
    """TAXII metrics should never produce 'error' severity (exogenous data)."""
    worst_cases = [
        check_taxii_fetch_failure_rate(1, 1),         # 100% failure
        check_taxii_stix_parse_error_rate(1, 1),      # 100% malformed
        check_taxii_empty_description_rate(1, 1),      # 100% empty
        check_taxii_label_unmapped_rate(1, 1),          # 100% unmapped
    ]
    for r in worst_cases:
        assert r.severity in ("pass", "warn"), (
            f"{r.name} produced severity={r.severity!r} (expected pass or warn)"
        )


# ---------------------------------------------------------------------------
# D6 deprecation — rss.tags.unknown_rate threshold is now 1.0
# ---------------------------------------------------------------------------


def test_rss_unknown_rate_deprecated_always_passes() -> None:
    """After D6 deprecation, rss.tags.unknown_rate always passes (threshold=1.0)."""
    from worker.data_quality.expectations.feed_metrics import check_unknown_tag_rate
    r = check_unknown_tag_rate(total_tags=100, unknown_tags=100)
    assert r.severity == "pass"  # 1.0 is NOT > 1.0
    assert r.name == "rss.tags.unknown_rate"
