"""Data-quality expectation registry (PR #7 Group D).

This package exposes the 11-item expectation set locked by D13. The
full registry is assembled by :func:`build_all_expectations` because
the referential-integrity pair depends on a loaded
:class:`worker.bootstrap.aliases.AliasDictionary` (which the CLI
resolves from the shared ``data/dictionaries/aliases.yml`` path).

Every expectation in the registry is a pre-built
:class:`worker.data_quality.results.Expectation` whose ``name``
matches the plan-locked dotted identifier exactly. A lint test at
:mod:`services.worker.tests.unit.test_dq_expectations` verifies both
the 11-item count and the name-to-severity mapping against D13.
"""

from __future__ import annotations

from worker.bootstrap.aliases import AliasDictionary
from worker.data_quality.expectations.dedup_rate import (
    dedup_rate_reports_url_canonical,
)
from worker.data_quality.expectations.null_rate import (
    null_rate_codenames_group_id,
    null_rate_codenames_named_by_source_id,
)
from worker.data_quality.expectations.referential_integrity import (
    build_groups_canonical_forward_check,
    build_groups_canonical_reverse_check,
)
from worker.data_quality.expectations.value_domain import (
    value_domain_incident_countries_iso2,
    value_domain_reports_tlp,
    value_domain_sources_country_iso2,
    value_domain_tags_type,
)
from worker.data_quality.expectations.year_range import (
    year_range_incidents_reported,
    year_range_reports_published,
)
from worker.data_quality.results import Expectation


__all__ = [
    "ALL_EXPECTATION_NAMES",
    "build_all_expectations",
]


#: Flat tuple of every expectation name shipped in PR #7, in the
#: same order :func:`build_all_expectations` returns them. The order
#: is fixed so stdout summaries are reproducible and Codex can
#: verify the D13 severity map by reading a single source.
ALL_EXPECTATION_NAMES: tuple[str, ...] = (
    # D11/V1–V4 — value_domain (4 error)
    "reports.tlp.value_domain",
    "sources.country.iso2_conformance",
    "incident_countries.country_iso2.iso2_conformance",
    "tags.type.enum_conformance",
    # D12/Y1–Y2 — year_range (2 error)
    "reports.published.year_range",
    "incidents.reported.year_range",
    # D8 — referential_integrity (1 error + 1 warn)
    "groups.canonical_name.forward_check",
    "groups.canonical_name.reverse_check",
    # D10/N1–N2 — null_rate (2 warn)
    "codenames.group_id.null_rate",
    "codenames.named_by_source_id.null_rate",
    # prior-decision — dedup_rate (1 warn)
    "reports.url_canonical.dedup_rate",
)


def build_all_expectations(aliases: AliasDictionary) -> list[Expectation]:
    """Assemble the 11-item expectation registry for a DQ run.

    The :class:`AliasDictionary` is injected because the two
    referential-integrity expectations (forward / reverse) close over
    it at construction time — the YAML is the source of truth per
    D8 and must be the same dictionary the bootstrap pipeline
    normalized against. Every other expectation is stateless and
    referenced as a module-level constant.

    The returned order is identical to :data:`ALL_EXPECTATION_NAMES`.
    """
    return [
        value_domain_reports_tlp,
        value_domain_sources_country_iso2,
        value_domain_incident_countries_iso2,
        value_domain_tags_type,
        year_range_reports_published,
        year_range_incidents_reported,
        build_groups_canonical_forward_check(aliases),
        build_groups_canonical_reverse_check(aliases),
        null_rate_codenames_group_id,
        null_rate_codenames_named_by_source_id,
        dedup_rate_reports_url_canonical,
    ]
