"""Value-domain expectations (D11 / V1–V4).

Four expectations, all ``error`` severity at threshold 0 violating
rows. Every expectation sources its allowed-values set from an
existing code-level constant rather than re-declaring the set
locally, so a change to the canonical constant automatically
propagates into the DQ gate without a second edit.

Sources of truth:

  - V1 ``reports.tlp.value_domain``
      → :data:`worker.data_quality.constants.TLP_VALUES`
  - V2 ``sources.country.iso2_conformance``
      → :data:`worker.bootstrap.schemas.ISO3166_ALPHA2_CODES`
        (public re-export per D11 / T15b)
  - V3 ``incident_countries.country_iso2.iso2_conformance``
      → same frozenset as V2
  - V4 ``tags.type.enum_conformance``
      → the five ``TAG_TYPE_*`` constants from
        :mod:`worker.bootstrap.normalize`, wrapped in a local
        frozenset for O(1) lookup
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.normalize import (
    TAG_TYPE_ACTOR,
    TAG_TYPE_CVE,
    TAG_TYPE_MALWARE,
    TAG_TYPE_OPERATION,
    TAG_TYPE_SECTOR,
    TAG_TYPE_UNKNOWN,
)
from worker.bootstrap.schemas import ISO3166_ALPHA2_CODES
from worker.bootstrap.tables import (
    incident_countries_table,
    reports_table,
    sources_table,
    tags_table,
)
from worker.data_quality.constants import TLP_VALUES
from worker.data_quality.results import Expectation, ExpectationResult


__all__ = [
    "VALID_TAG_TYPES",
    "value_domain_incident_countries_iso2",
    "value_domain_reports_tlp",
    "value_domain_sources_country_iso2",
    "value_domain_tags_type",
]


#: The six tag type values the PR #5 classifier can produce. This
#: set is the D11/V4 ``tags.type.enum_conformance`` allowed domain:
#: any row whose ``type`` column holds one of these is considered
#: well-formed, and any row holding a novel string is flagged.
#:
#: ``TAG_TYPE_UNKNOWN`` is INCLUDED here because the classifier
#: intentionally exports it as a documented fallback (Codex round 2
#: P2): when a vendor feed contains a generic meta-tag like
#: ``#malware`` that does not resolve through the aliases dictionary
#: or the sector vocabulary, ``_classify_single`` emits a
#: ``TAG_TYPE_UNKNOWN`` ClassifiedTag rather than raising. That value
#: is a supported enum member and must not make the DQ gate fail at
#: error severity. Monitoring how often the classifier falls back is
#: a separate concern — the future ``tags.type.unknown_rate`` warn-
#: level expectation (followup_todos) is the right signal for that.
#:
#: Wrapped in a frozenset so the expectation can do O(1) membership
#: checks without depending on the string imports being in any
#: particular order.
VALID_TAG_TYPES: frozenset[str] = frozenset({
    TAG_TYPE_ACTOR,
    TAG_TYPE_MALWARE,
    TAG_TYPE_CVE,
    TAG_TYPE_OPERATION,
    TAG_TYPE_SECTOR,
    TAG_TYPE_UNKNOWN,
})


# ---------------------------------------------------------------------------
# V1 — reports.tlp.value_domain
# ---------------------------------------------------------------------------


async def _check_reports_tlp(session: AsyncSession) -> ExpectationResult:
    """Count ``reports`` rows whose ``tlp`` is not in :data:`TLP_VALUES`."""
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(reports_table)
            .where(~reports_table.c.tlp.in_(sorted(TLP_VALUES)))
        )
    ).scalar_one()

    return ExpectationResult(
        name="reports.tlp.value_domain",
        severity="error" if count > 0 else "pass",
        observed_rows=int(count),
        threshold=0,
        detail={"allowed_values": sorted(TLP_VALUES)},
    )


value_domain_reports_tlp = Expectation(
    name="reports.tlp.value_domain",
    check=_check_reports_tlp,
)


# ---------------------------------------------------------------------------
# V2 — sources.country.iso2_conformance
# ---------------------------------------------------------------------------


async def _check_sources_country(session: AsyncSession) -> ExpectationResult:
    """Load non-null ``sources.country`` values and check each against
    :data:`ISO3166_ALPHA2_CODES`. Python-side filtering keeps the
    query simple regardless of set cardinality (249)."""
    result = await session.execute(
        sa.select(sources_table.c.country).where(
            sources_table.c.country.is_not(None)
        )
    )
    values = [row[0] for row in result if row[0] is not None]
    invalid = [v for v in values if v not in ISO3166_ALPHA2_CODES]

    return ExpectationResult(
        name="sources.country.iso2_conformance",
        severity="error" if invalid else "pass",
        observed_rows=len(invalid),
        threshold=0,
        detail={
            "total_non_null": len(values),
            "invalid_codes": sorted(set(invalid)),
        } if invalid else {
            "total_non_null": len(values),
        },
    )


value_domain_sources_country_iso2 = Expectation(
    name="sources.country.iso2_conformance",
    check=_check_sources_country,
)


# ---------------------------------------------------------------------------
# V3 — incident_countries.country_iso2.iso2_conformance
# ---------------------------------------------------------------------------


async def _check_incident_countries_iso2(
    session: AsyncSession,
) -> ExpectationResult:
    """Load every ``incident_countries.country_iso2`` (PK, non-null)
    and check membership in the same vendored list V2 uses."""
    result = await session.execute(
        sa.select(incident_countries_table.c.country_iso2)
    )
    values = [row[0] for row in result]
    invalid = [v for v in values if v not in ISO3166_ALPHA2_CODES]

    return ExpectationResult(
        name="incident_countries.country_iso2.iso2_conformance",
        severity="error" if invalid else "pass",
        observed_rows=len(invalid),
        threshold=0,
        detail={
            "total_rows": len(values),
            "invalid_codes": sorted(set(invalid)),
        } if invalid else {
            "total_rows": len(values),
        },
    )


value_domain_incident_countries_iso2 = Expectation(
    name="incident_countries.country_iso2.iso2_conformance",
    check=_check_incident_countries_iso2,
)


# ---------------------------------------------------------------------------
# V4 — tags.type.enum_conformance
# ---------------------------------------------------------------------------


async def _check_tags_type(session: AsyncSession) -> ExpectationResult:
    """Count ``tags`` rows whose ``type`` is not one of the five
    classifier constants in :mod:`worker.bootstrap.normalize`."""
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(tags_table)
            .where(~tags_table.c.type.in_(sorted(VALID_TAG_TYPES)))
        )
    ).scalar_one()

    return ExpectationResult(
        name="tags.type.enum_conformance",
        severity="error" if count > 0 else "pass",
        observed_rows=int(count),
        threshold=0,
        detail={"allowed_types": sorted(VALID_TAG_TYPES)},
    )


value_domain_tags_type = Expectation(
    name="tags.type.enum_conformance",
    check=_check_tags_type,
)
