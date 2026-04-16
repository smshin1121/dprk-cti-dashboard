"""Pre-ingest feed-level DQ metrics (D10).

These 4 expectations are computed from run-level counters (not SQL
queries) and are invoked directly by ``worker.ingest.runner``. They
are NOT registered in ``ALL_EXPECTATION_NAMES`` / ``build_all_expectations``
— that registry is for post-load production checks only (D9).

All 4 are warn-severity only. Name prefix ``feed.*`` / ``rss.*``
prevents collision with PR #7 production expectations.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from worker.data_quality.results import ExpectationResult


__all__ = [
    "check_fetch_failure_rate",
    "check_parse_error_rate",
    "check_empty_title_rate",
    "check_unknown_tag_rate",
]

_FETCH_FAILURE_THRESHOLD = Decimal("0.20")
_PARSE_ERROR_THRESHOLD = Decimal("0.10")
_EMPTY_TITLE_THRESHOLD = Decimal("0.05")
# DEPRECATED — observational only (decision D6, PR #9). Hashtag extraction
# is not meaningful against real vendor feeds. Threshold raised to 1.0 so
# the metric always passes. Real tag coverage lands with Phase 4 LLM
# enrichment. The TAXII replacement is taxii.label_unmapped_rate in
# worker.data_quality.expectations.taxii_metrics.
_UNKNOWN_TAG_THRESHOLD = Decimal("1.0")


def check_fetch_failure_rate(
    total_feeds: int,
    failed_feeds: int,
) -> ExpectationResult:
    rate = Decimal(str(failed_feeds / total_feeds)) if total_feeds > 0 else Decimal("0")
    return ExpectationResult(
        name="feed.fetch_failure_rate",
        severity="warn" if rate > _FETCH_FAILURE_THRESHOLD else "pass",
        observed=rate,
        threshold=_FETCH_FAILURE_THRESHOLD,
        observed_rows=failed_feeds,
        detail={"total_feeds": total_feeds, "failed_feeds": failed_feeds},
    )


def check_parse_error_rate(
    fetched_feeds: int,
    parse_errors: int,
) -> ExpectationResult:
    rate = Decimal(str(parse_errors / fetched_feeds)) if fetched_feeds > 0 else Decimal("0")
    return ExpectationResult(
        name="feed.parse_error_rate",
        severity="warn" if rate > _PARSE_ERROR_THRESHOLD else "pass",
        observed=rate,
        threshold=_PARSE_ERROR_THRESHOLD,
        observed_rows=parse_errors,
        detail={"fetched_feeds": fetched_feeds, "parse_errors": parse_errors},
    )


def check_empty_title_rate(
    total_entries: int,
    empty_titles: int,
) -> ExpectationResult:
    rate = Decimal(str(empty_titles / total_entries)) if total_entries > 0 else Decimal("0")
    return ExpectationResult(
        name="feed.empty_title_rate",
        severity="warn" if rate > _EMPTY_TITLE_THRESHOLD else "pass",
        observed=rate,
        threshold=_EMPTY_TITLE_THRESHOLD,
        observed_rows=empty_titles,
        detail={"total_entries": total_entries, "empty_titles": empty_titles},
    )


def check_unknown_tag_rate(
    total_tags: int,
    unknown_tags: int,
) -> ExpectationResult:
    """DEPRECATED — observational only (decision D6, PR #9).

    Hashtag extraction is not meaningful against real vendor feeds.
    Threshold is 1.0 (always-pass). This metric is kept for backward-
    compatible dq_events queries but is no longer a signal — only a
    smoke detector for metric computation failures.

    Real tag coverage for TAXII: ``taxii.label_unmapped_rate``.
    Real tag coverage for RSS: deferred to Phase 4 LLM enrichment.
    """
    rate = Decimal(str(unknown_tags / total_tags)) if total_tags > 0 else Decimal("0")
    return ExpectationResult(
        name="rss.tags.unknown_rate",
        severity="warn" if rate > _UNKNOWN_TAG_THRESHOLD else "pass",
        observed=rate,
        threshold=_UNKNOWN_TAG_THRESHOLD,
        observed_rows=unknown_tags,
        detail={"total_tags": total_tags, "unknown_tags": unknown_tags},
    )
