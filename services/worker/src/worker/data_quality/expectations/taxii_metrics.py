"""TAXII-specific pre-ingest DQ metrics (D5).

These 4 expectations are computed from run-level counters (not SQL
queries) and are invoked directly by ``worker.ingest.taxii.runner``.
They are NOT registered in ``ALL_EXPECTATION_NAMES`` /
``build_all_expectations`` — that registry is for post-load production
checks only (D9, carried from PR #8).

All 4 are warn-severity only — TAXII collections are exogenous.
Name prefix ``taxii.*`` prevents collision with PR #8 ``feed.*`` /
``rss.*`` and PR #7 production expectations.

Metric design notes:

  - ``taxii.empty_description_rate``: warn-only, tuning expected (D5).
    STIX objects (especially attack-pattern) frequently lack descriptions;
    threshold is a starting point, not a contract.

  - ``taxii.label_unmapped_rate``: primary tag coverage metric (D6).
    Denominator = total labels from objects that HAVE a ``labels`` array.
    Objects without ``labels`` are excluded from the denominator to avoid
    metric distortion for collections where most objects lack labels.
"""

from __future__ import annotations

from decimal import Decimal

from worker.data_quality.results import ExpectationResult


__all__ = [
    "check_taxii_fetch_failure_rate",
    "check_taxii_stix_parse_error_rate",
    "check_taxii_empty_description_rate",
    "check_taxii_label_unmapped_rate",
]


_FETCH_FAILURE_THRESHOLD = Decimal("0.20")
_STIX_PARSE_ERROR_THRESHOLD = Decimal("0.10")
_EMPTY_DESCRIPTION_THRESHOLD = Decimal("0.30")
_LABEL_UNMAPPED_THRESHOLD = Decimal("0.50")


def check_taxii_fetch_failure_rate(
    total_collections: int,
    failed_collections: int,
) -> ExpectationResult:
    """Ratio of collections whose GET returned non-2xx or exception."""
    rate = (
        Decimal(str(failed_collections / total_collections))
        if total_collections > 0
        else Decimal("0")
    )
    return ExpectationResult(
        name="taxii.fetch_failure_rate",
        severity="warn" if rate > _FETCH_FAILURE_THRESHOLD else "pass",
        observed=rate,
        threshold=_FETCH_FAILURE_THRESHOLD,
        observed_rows=failed_collections,
        detail={
            "total_collections": total_collections,
            "failed_collections": failed_collections,
        },
    )


def check_taxii_stix_parse_error_rate(
    total_objects: int,
    malformed_objects: int,
) -> ExpectationResult:
    """Ratio of fetched STIX objects that fail structure validation."""
    rate = (
        Decimal(str(malformed_objects / total_objects))
        if total_objects > 0
        else Decimal("0")
    )
    return ExpectationResult(
        name="taxii.stix_parse_error_rate",
        severity="warn" if rate > _STIX_PARSE_ERROR_THRESHOLD else "pass",
        observed=rate,
        threshold=_STIX_PARSE_ERROR_THRESHOLD,
        observed_rows=malformed_objects,
        detail={
            "total_objects": total_objects,
            "malformed_objects": malformed_objects,
        },
    )


def check_taxii_empty_description_rate(
    total_ingested: int,
    empty_descriptions: int,
) -> ExpectationResult:
    """Ratio of ingested STIX objects with no ``description``.

    Warn-only, tuning expected: STIX objects (especially attack-pattern)
    frequently lack descriptions. Threshold is a starting point.
    """
    rate = (
        Decimal(str(empty_descriptions / total_ingested))
        if total_ingested > 0
        else Decimal("0")
    )
    return ExpectationResult(
        name="taxii.empty_description_rate",
        severity="warn" if rate > _EMPTY_DESCRIPTION_THRESHOLD else "pass",
        observed=rate,
        threshold=_EMPTY_DESCRIPTION_THRESHOLD,
        observed_rows=empty_descriptions,
        detail={
            "total_ingested": total_ingested,
            "empty_descriptions": empty_descriptions,
        },
    )


def check_taxii_label_unmapped_rate(
    total_labels: int,
    unmapped_labels: int,
) -> ExpectationResult:
    """Ratio of STIX ``labels[]`` values that don't map to known tag types.

    **Denominator**: total label strings from objects that HAVE a
    ``labels`` array. Objects without ``labels`` are excluded from
    the denominator to avoid metric distortion for collections where
    most objects lack labels.

    This is the primary tag coverage metric for TAXII (decision D6),
    replacing the concept ``rss.tags.unknown_rate`` was trying to capture.
    """
    rate = (
        Decimal(str(unmapped_labels / total_labels))
        if total_labels > 0
        else Decimal("0")
    )
    return ExpectationResult(
        name="taxii.label_unmapped_rate",
        severity="warn" if rate > _LABEL_UNMAPPED_THRESHOLD else "pass",
        observed=rate,
        threshold=_LABEL_UNMAPPED_THRESHOLD,
        observed_rows=unmapped_labels,
        detail={
            "total_labels": total_labels,
            "unmapped_labels": unmapped_labels,
        },
    )
