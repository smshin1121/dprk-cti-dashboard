"""Unit tests for worker.data_quality.expectations (PR #7 Group D).

Pins the five user review points for Group D:

  1. TLP_VALUES matches D11 / V1 exactly.
  2. ISO3166_ALPHA2_CODES public re-export shares identity with the
     pre-existing private name so no internal caller breaks.
  3. The ALL_EXPECTATION_NAMES tuple has exactly 11 entries and
     matches the D13 severity map 1:1.
  4. Every expectation's ``name`` matches the plan-locked dotted
     identifier.
  5. No expectation ever produces a severity outside pass/warn/error.

Plus the D8 source-of-truth check: the referential-integrity
forward/reverse pair read from aliases.yml (not the DB) as the
authoritative source.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap import schemas
from worker.bootstrap.aliases import AliasDictionary
from worker.bootstrap.schemas import ISO3166_ALPHA2_CODES
from worker.bootstrap.tables import (
    codenames_table,
    groups_table,
    incident_countries_table,
    incidents_table,
    reports_table,
    sources_table,
    tags_table,
)
from worker.data_quality.constants import TLP_VALUES
from worker.data_quality.expectations import (
    ALL_EXPECTATION_NAMES,
    build_all_expectations,
)
from worker.data_quality.expectations.dedup_rate import (
    DEDUP_RATE_WARN_THRESHOLD,
    compute_dedup_severity,
    dedup_rate_reports_url_canonical,
)
from worker.data_quality.expectations.null_rate import (
    NULL_RATE_WARN_THRESHOLD,
    null_rate_codenames_group_id,
    null_rate_codenames_named_by_source_id,
)
from worker.data_quality.expectations.referential_integrity import (
    build_groups_canonical_forward_check,
    build_groups_canonical_reverse_check,
)
from worker.data_quality.expectations.value_domain import (
    VALID_TAG_TYPES,
    value_domain_incident_countries_iso2,
    value_domain_reports_tlp,
    value_domain_sources_country_iso2,
    value_domain_tags_type,
)
from worker.data_quality.expectations.year_range import (
    YEAR_RANGE_LOWER,
    YEAR_RANGE_UPPER,
    year_range_incidents_reported,
    year_range_reports_published,
)
from worker.data_quality.results import ExpectationResult


# ---------------------------------------------------------------------------
# Constants and re-exports
# ---------------------------------------------------------------------------


class TestConstantsAndReExports:
    def test_tlp_values_matches_d11_v1(self) -> None:
        """Review point 1 — TLP_VALUES exactly equals D11/V1 spec."""
        assert TLP_VALUES == frozenset({"WHITE", "GREEN", "AMBER", "RED"})
        assert len(TLP_VALUES) == 4
        # frozenset ensures hashability and immutability
        assert isinstance(TLP_VALUES, frozenset)

    def test_iso3166_public_reexport_identity(self) -> None:
        """Review point 2 — public and private names resolve to the
        same frozenset instance (identity, not just equality)."""
        assert schemas._ISO3166_ALPHA2_CODES is schemas.ISO3166_ALPHA2_CODES
        assert ISO3166_ALPHA2_CODES is schemas.ISO3166_ALPHA2_CODES

    def test_iso3166_retains_249_codes(self) -> None:
        """Vendored list should still contain 249 codes after the
        public re-export edit — sanity guard against accidental
        truncation during the rename."""
        assert len(ISO3166_ALPHA2_CODES) == 249
        # Spot-check a handful of high-importance codes for DPRK CTI
        for code in ("KP", "KR", "US", "CN", "RU", "JP"):
            assert code in ISO3166_ALPHA2_CODES

    def test_valid_tag_types_is_six_classifier_constants(self) -> None:
        """D11/V4 enum domain is the full set of TAG_TYPE_* constants
        exported by worker.bootstrap.normalize, INCLUDING
        ``unknown_type`` — the classifier's documented fallback for
        generic vendor meta-tags. Excluding unknown_type would make
        the gate fail at error severity on any real load that
        contains a novel tag (Codex round 2 P2)."""
        assert VALID_TAG_TYPES == frozenset({
            "actor", "malware", "cve", "operation", "sector", "unknown_type",
        })

    def test_year_range_bounds_match_d12(self) -> None:
        assert YEAR_RANGE_LOWER == dt.date(2000, 1, 1)
        assert YEAR_RANGE_UPPER == dt.date(2030, 12, 31)

    def test_null_rate_threshold_matches_d10(self) -> None:
        assert NULL_RATE_WARN_THRESHOLD == Decimal("0.50")

    def test_dedup_rate_threshold_matches_d12(self) -> None:
        assert DEDUP_RATE_WARN_THRESHOLD == Decimal("0.15")


# ---------------------------------------------------------------------------
# Registry shape — D13 contract
# ---------------------------------------------------------------------------


class TestRegistryContract:
    def test_exactly_eleven_expectations(self) -> None:
        """Review point 3 — D13 locks 11 expectations total."""
        assert len(ALL_EXPECTATION_NAMES) == 11

    def test_names_match_d13_registry(self) -> None:
        """Review point 4 — every name matches the plan-locked
        dotted identifier."""
        assert ALL_EXPECTATION_NAMES == (
            "reports.tlp.value_domain",
            "sources.country.iso2_conformance",
            "incident_countries.country_iso2.iso2_conformance",
            "tags.type.enum_conformance",
            "reports.published.year_range",
            "incidents.reported.year_range",
            "groups.canonical_name.forward_check",
            "groups.canonical_name.reverse_check",
            "codenames.group_id.null_rate",
            "codenames.named_by_source_id.null_rate",
            "reports.url_canonical.dedup_rate",
        )

    def test_build_all_expectations_returns_11_items_in_registry_order(
        self,
    ) -> None:
        aliases = AliasDictionary(_by_type={"groups": {"lazarus": "Lazarus"}})
        built = build_all_expectations(aliases)
        assert len(built) == 11
        assert [e.name for e in built] == list(ALL_EXPECTATION_NAMES)

    def test_no_duplicate_names(self) -> None:
        assert len(set(ALL_EXPECTATION_NAMES)) == 11


# ---------------------------------------------------------------------------
# Severity mapping D13 — load-bearing contract
# ---------------------------------------------------------------------------
#
# Maps from ALL_EXPECTATION_NAMES to the severity each expectation is
# designed to produce on its "clean" path (no violations). For error-
# severity expectations, the clean path is "pass"; for warn-severity
# expectations, the clean path is also "pass" (warn is reserved for
# above-threshold cases). The reverse-check is a special case — it
# never produces error, but also emits "pass" on a clean set.
#
# This table IS the D13 severity compliance contract the runner
# ultimately enforces at exit-code time. If a future edit changes the
# severity shape of any expectation, the corresponding test fails.


#: Per-expectation severity on the "no violations" path.
_CLEAN_SEVERITY: dict[str, str] = {
    "reports.tlp.value_domain": "pass",
    "sources.country.iso2_conformance": "pass",
    "incident_countries.country_iso2.iso2_conformance": "pass",
    "tags.type.enum_conformance": "pass",
    "reports.published.year_range": "pass",
    "incidents.reported.year_range": "pass",
    "groups.canonical_name.forward_check": "pass",
    "groups.canonical_name.reverse_check": "pass",
    "codenames.group_id.null_rate": "pass",
    "codenames.named_by_source_id.null_rate": "pass",
    "reports.url_canonical.dedup_rate": "pass",
}

#: Per-expectation maximum severity when violated. This is the
#: D13 error/warn mapping — if an expectation is "error", it
#: produces error on violation; if "warn", max is warn.
_MAX_VIOLATION_SEVERITY: dict[str, str] = {
    "reports.tlp.value_domain": "error",
    "sources.country.iso2_conformance": "error",
    "incident_countries.country_iso2.iso2_conformance": "error",
    "tags.type.enum_conformance": "error",
    "reports.published.year_range": "error",
    "incidents.reported.year_range": "error",
    "groups.canonical_name.forward_check": "error",
    "groups.canonical_name.reverse_check": "warn",
    "codenames.group_id.null_rate": "warn",
    "codenames.named_by_source_id.null_rate": "warn",
    "reports.url_canonical.dedup_rate": "warn",
}


class TestSeverityMapCoverage:
    def test_clean_severity_map_covers_every_expectation(self) -> None:
        assert set(_CLEAN_SEVERITY.keys()) == set(ALL_EXPECTATION_NAMES)

    def test_max_violation_severity_map_covers_every_expectation(self) -> None:
        assert set(_MAX_VIOLATION_SEVERITY.keys()) == set(ALL_EXPECTATION_NAMES)

    def test_severity_map_uses_only_pass_warn_error(self) -> None:
        """Review point 5 — no third band introduced."""
        all_severities = (
            set(_CLEAN_SEVERITY.values())
            | set(_MAX_VIOLATION_SEVERITY.values())
        )
        assert all_severities <= {"pass", "warn", "error"}

    def test_d13_error_count_is_seven(self) -> None:
        error_names = [
            n for n, s in _MAX_VIOLATION_SEVERITY.items() if s == "error"
        ]
        assert len(error_names) == 7

    def test_d13_warn_count_is_four(self) -> None:
        warn_names = [
            n for n, s in _MAX_VIOLATION_SEVERITY.items() if s == "warn"
        ]
        assert len(warn_names) == 4


# ---------------------------------------------------------------------------
# Value-domain expectations — clean + violation paths
# ---------------------------------------------------------------------------


async def _seed_reports(session: AsyncSession, rows: list[dict]) -> None:
    """Insert minimal reports rows (title/url/url_canonical/sha256_title
    are NOT NULL)."""
    await session.execute(sa.insert(reports_table), rows)


async def _insert_source(
    session: AsyncSession, name: str, country: str | None = None
) -> int:
    result = await session.execute(
        sa.insert(sources_table)
        .values(name=name, type="vendor", country=country)
        .returning(sources_table.c.id)
    )
    return result.scalar_one()


@pytest.mark.asyncio
class TestValueDomainReportsTlp:
    async def test_pass_when_all_tlp_are_valid(
        self, db_session: AsyncSession
    ) -> None:
        source_id = await _insert_source(db_session, "Mandiant")
        await _seed_reports(db_session, [
            {
                "published": dt.date(2026, 1, 1),
                "source_id": source_id,
                "title": "t",
                "url": "https://example.com/a",
                "url_canonical": "https://example.com/a",
                "sha256_title": "a" * 64,
                "tlp": "WHITE",
            },
            {
                "published": dt.date(2026, 1, 2),
                "source_id": source_id,
                "title": "t2",
                "url": "https://example.com/b",
                "url_canonical": "https://example.com/b",
                "sha256_title": "b" * 64,
                "tlp": "AMBER",
            },
        ])
        result = await value_domain_reports_tlp.check(db_session)
        assert result.name == "reports.tlp.value_domain"
        assert result.severity == "pass"
        assert result.observed_rows == 0

    async def test_error_when_invalid_tlp_present(
        self, db_session: AsyncSession
    ) -> None:
        source_id = await _insert_source(db_session, "Kaspersky")
        await _seed_reports(db_session, [
            {
                "published": dt.date(2026, 1, 1),
                "source_id": source_id,
                "title": "t",
                "url": "https://example.com/bad",
                "url_canonical": "https://example.com/bad",
                "sha256_title": "c" * 64,
                "tlp": "BLACK",  # not in TLP_VALUES
            },
        ])
        result = await value_domain_reports_tlp.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1
        assert result.detail["allowed_values"] == sorted(TLP_VALUES)

    async def test_pass_on_empty_table(
        self, db_session: AsyncSession
    ) -> None:
        result = await value_domain_reports_tlp.check(db_session)
        assert result.severity == "pass"
        assert result.observed_rows == 0


@pytest.mark.asyncio
class TestValueDomainSourcesCountry:
    async def test_pass_when_all_countries_valid(
        self, db_session: AsyncSession
    ) -> None:
        await _insert_source(db_session, "VendorA", country="US")
        await _insert_source(db_session, "VendorB", country="KR")
        await _insert_source(db_session, "VendorC", country=None)  # null OK
        result = await value_domain_sources_country_iso2.check(db_session)
        assert result.severity == "pass"

    async def test_error_when_invalid_country_present(
        self, db_session: AsyncSession
    ) -> None:
        await _insert_source(db_session, "VendorA", country="US")
        await _insert_source(db_session, "VendorBad", country="ZZ")  # not real
        result = await value_domain_sources_country_iso2.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1
        assert result.detail["invalid_codes"] == ["ZZ"]


@pytest.mark.asyncio
class TestValueDomainIncidentCountries:
    async def test_pass_when_all_iso_valid(
        self, db_session: AsyncSession
    ) -> None:
        result = await db_session.execute(
            sa.insert(incidents_table)
            .values(title="Incident A", reported=dt.date(2026, 1, 1))
            .returning(incidents_table.c.id)
        )
        incident_id = result.scalar_one()
        await db_session.execute(
            sa.insert(incident_countries_table).values(
                incident_id=incident_id, country_iso2="KP"
            )
        )
        result = await value_domain_incident_countries_iso2.check(db_session)
        assert result.severity == "pass"

    async def test_error_when_invalid_iso_present(
        self, db_session: AsyncSession
    ) -> None:
        result = await db_session.execute(
            sa.insert(incidents_table)
            .values(title="Incident B", reported=dt.date(2026, 1, 2))
            .returning(incidents_table.c.id)
        )
        incident_id = result.scalar_one()
        await db_session.execute(
            sa.insert(incident_countries_table).values(
                incident_id=incident_id, country_iso2="XX"  # not real
            )
        )
        result = await value_domain_incident_countries_iso2.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1


@pytest.mark.asyncio
class TestValueDomainTagsType:
    async def test_pass_when_all_types_valid(
        self, db_session: AsyncSession
    ) -> None:
        await db_session.execute(sa.insert(tags_table), [
            {"name": "t1", "type": "actor"},
            {"name": "t2", "type": "malware"},
            {"name": "t3", "type": "cve"},
            {"name": "t4", "type": "operation"},
            {"name": "t5", "type": "sector"},
        ])
        result = await value_domain_tags_type.check(db_session)
        assert result.severity == "pass"

    async def test_error_when_invalid_type_present(
        self, db_session: AsyncSession
    ) -> None:
        await db_session.execute(sa.insert(tags_table), [
            {"name": "t1", "type": "actor"},
            {"name": "t2", "type": "garbage"},  # not in VALID_TAG_TYPES
        ])
        result = await value_domain_tags_type.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1

    async def test_pass_when_classifier_unknown_type_present(
        self, db_session: AsyncSession
    ) -> None:
        """Codex round 2 P2 regression: the classifier intentionally
        emits ``unknown_type`` as a documented fallback for generic
        vendor meta-tags. That value must be accepted by
        ``tags.type.enum_conformance`` — otherwise any real load
        with a novel tag fails the DQ gate at error severity."""
        await db_session.execute(sa.insert(tags_table), [
            {"name": "t1", "type": "actor"},
            {"name": "t2", "type": "unknown_type"},
        ])
        result = await value_domain_tags_type.check(db_session)
        assert result.severity == "pass"
        assert result.observed_rows == 0


# ---------------------------------------------------------------------------
# Year-range expectations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestYearRangeReportsPublished:
    async def test_pass_when_all_dates_in_range(
        self, db_session: AsyncSession
    ) -> None:
        source_id = await _insert_source(db_session, "VA")
        await _seed_reports(db_session, [
            {
                "published": dt.date(2005, 6, 1),
                "source_id": source_id,
                "title": "t1",
                "url": "https://example.com/1",
                "url_canonical": "https://example.com/1",
                "sha256_title": "a" * 64,
                "tlp": "WHITE",
            },
            {
                "published": dt.date(2030, 12, 31),
                "source_id": source_id,
                "title": "t2",
                "url": "https://example.com/2",
                "url_canonical": "https://example.com/2",
                "sha256_title": "b" * 64,
                "tlp": "WHITE",
            },
        ])
        result = await year_range_reports_published.check(db_session)
        assert result.severity == "pass"
        assert result.observed_rows == 0

    async def test_error_when_date_below_lower_bound(
        self, db_session: AsyncSession
    ) -> None:
        source_id = await _insert_source(db_session, "VA")
        await _seed_reports(db_session, [
            {
                "published": dt.date(1999, 12, 31),  # below 2000-01-01
                "source_id": source_id,
                "title": "old",
                "url": "https://example.com/old",
                "url_canonical": "https://example.com/old",
                "sha256_title": "c" * 64,
                "tlp": "WHITE",
            },
        ])
        result = await year_range_reports_published.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1

    async def test_error_when_date_above_upper_bound(
        self, db_session: AsyncSession
    ) -> None:
        source_id = await _insert_source(db_session, "VA")
        await _seed_reports(db_session, [
            {
                "published": dt.date(2031, 1, 1),  # above 2030-12-31
                "source_id": source_id,
                "title": "future",
                "url": "https://example.com/future",
                "url_canonical": "https://example.com/future",
                "sha256_title": "d" * 64,
                "tlp": "WHITE",
            },
        ])
        result = await year_range_reports_published.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1


@pytest.mark.asyncio
class TestYearRangeIncidentsReported:
    async def test_null_rows_are_excluded_from_count(
        self, db_session: AsyncSession
    ) -> None:
        await db_session.execute(sa.insert(incidents_table), [
            {"title": "A", "reported": None},
            {"title": "B", "reported": dt.date(2026, 1, 1)},
        ])
        result = await year_range_incidents_reported.check(db_session)
        assert result.severity == "pass"
        assert result.observed_rows == 0

    async def test_error_when_reported_out_of_range(
        self, db_session: AsyncSession
    ) -> None:
        await db_session.execute(sa.insert(incidents_table), [
            {"title": "B", "reported": dt.date(1995, 1, 1)},  # below
        ])
        result = await year_range_incidents_reported.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1


# ---------------------------------------------------------------------------
# Referential-integrity expectations — D8 source of truth
# ---------------------------------------------------------------------------


def _test_alias_dict() -> AliasDictionary:
    """Hand-built alias dict matching a minimal DPRK groups set."""
    return AliasDictionary(
        _by_type={
            "groups": {
                "lazarus": "Lazarus",
                "apt38": "Lazarus",
                "kimsuky": "Kimsuky",
                "scarcruft": "ScarCruft",
            },
        }
    )


@pytest.mark.asyncio
class TestReferentialIntegrityForward:
    async def test_pass_when_db_subset_of_yaml(
        self, db_session: AsyncSession
    ) -> None:
        aliases = _test_alias_dict()
        await db_session.execute(
            sa.insert(groups_table), [
                {"name": "Lazarus"},
                {"name": "Kimsuky"},
            ]
        )
        expectation = build_groups_canonical_forward_check(aliases)
        result = await expectation.check(db_session)
        assert result.severity == "pass"
        assert result.detail["source_of_truth"] == "aliases.yml"
        assert result.detail["db_canonical_count"] == 2
        assert result.detail["yaml_canonical_count"] == 3

    async def test_error_when_db_has_unknown_canonical(
        self, db_session: AsyncSession
    ) -> None:
        aliases = _test_alias_dict()
        await db_session.execute(
            sa.insert(groups_table), [
                {"name": "Lazarus"},
                {"name": "UNKNOWN_GROUP"},  # not in YAML
            ]
        )
        expectation = build_groups_canonical_forward_check(aliases)
        result = await expectation.check(db_session)
        assert result.severity == "error"
        assert result.observed_rows == 1
        assert result.detail["offending_db_canonicals"] == ["UNKNOWN_GROUP"]

    async def test_pass_on_empty_db(
        self, db_session: AsyncSession
    ) -> None:
        aliases = _test_alias_dict()
        expectation = build_groups_canonical_forward_check(aliases)
        result = await expectation.check(db_session)
        assert result.severity == "pass"


@pytest.mark.asyncio
class TestReferentialIntegrityReverse:
    async def test_pass_when_all_yaml_canonicals_materialized(
        self, db_session: AsyncSession
    ) -> None:
        aliases = _test_alias_dict()
        # yaml canonicals = {Lazarus, Kimsuky, ScarCruft}
        await db_session.execute(
            sa.insert(groups_table), [
                {"name": "Lazarus"},
                {"name": "Kimsuky"},
                {"name": "ScarCruft"},
            ]
        )
        expectation = build_groups_canonical_reverse_check(aliases)
        result = await expectation.check(db_session)
        assert result.severity == "pass"
        assert result.observed_rows == 0

    async def test_warn_when_yaml_has_unused_canonicals(
        self, db_session: AsyncSession
    ) -> None:
        aliases = _test_alias_dict()
        # Only Lazarus in DB; Kimsuky and ScarCruft unused.
        await db_session.execute(
            sa.insert(groups_table).values(name="Lazarus")
        )
        expectation = build_groups_canonical_reverse_check(aliases)
        result = await expectation.check(db_session)
        assert result.severity == "warn"
        assert result.observed_rows == 2
        assert result.detail["unused_yaml_canonicals"] == ["Kimsuky", "ScarCruft"]

    async def test_reverse_never_produces_error_even_on_worst_case(
        self, db_session: AsyncSession
    ) -> None:
        """Pins D8 rule: reverse check never escalates past warn.
        Even an empty DB + large YAML produces warn, not error."""
        aliases = _test_alias_dict()
        expectation = build_groups_canonical_reverse_check(aliases)
        result = await expectation.check(db_session)
        assert result.severity == "warn"
        assert result.severity != "error"


# ---------------------------------------------------------------------------
# Null-rate expectations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNullRateCodenamesGroupId:
    async def test_pass_on_empty_table(
        self, db_session: AsyncSession
    ) -> None:
        result = await null_rate_codenames_group_id.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal(0)

    async def test_pass_when_ratio_below_threshold(
        self, db_session: AsyncSession
    ) -> None:
        # Insert a group first so some codenames can reference it.
        group_result = await db_session.execute(
            sa.insert(groups_table).values(name="Lazarus").returning(
                groups_table.c.id
            )
        )
        group_id = group_result.scalar_one()
        # 1 null out of 4 = 25% <= 50%
        await db_session.execute(sa.insert(codenames_table), [
            {"name": "c1", "group_id": group_id},
            {"name": "c2", "group_id": group_id},
            {"name": "c3", "group_id": group_id},
            {"name": "c4", "group_id": None},
        ])
        result = await null_rate_codenames_group_id.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal("0.25")

    async def test_warn_when_ratio_above_threshold(
        self, db_session: AsyncSession
    ) -> None:
        # 3 null out of 4 = 75% > 50%
        await db_session.execute(sa.insert(codenames_table), [
            {"name": "c1", "group_id": None},
            {"name": "c2", "group_id": None},
            {"name": "c3", "group_id": None},
            {"name": "c4", "group_id": None},
        ])
        result = await null_rate_codenames_group_id.check(db_session)
        assert result.severity == "warn"
        assert result.observed == Decimal(1)  # 4/4
        assert result.observed_rows == 4


@pytest.mark.asyncio
class TestNullRateCodenamesNamedBySource:
    async def test_warn_above_threshold(
        self, db_session: AsyncSession
    ) -> None:
        await db_session.execute(sa.insert(codenames_table), [
            {"name": "c1", "group_id": None, "named_by_source_id": None},
            {"name": "c2", "group_id": None, "named_by_source_id": None},
        ])
        result = await null_rate_codenames_named_by_source_id.check(db_session)
        assert result.severity == "warn"


# ---------------------------------------------------------------------------
# Dedup-rate expectation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDedupRateUrlCanonical:
    async def test_pass_on_empty_table(
        self, db_session: AsyncSession
    ) -> None:
        result = await dedup_rate_reports_url_canonical.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal(0)

    async def test_pass_when_no_duplicates(
        self, db_session: AsyncSession
    ) -> None:
        source_id = await _insert_source(db_session, "V")
        await _seed_reports(db_session, [
            {
                "published": dt.date(2026, 1, i + 1),
                "source_id": source_id,
                "title": f"t{i}",
                "url": f"https://example.com/{i}",
                "url_canonical": f"https://example.com/{i}",
                "sha256_title": f"{i}" * 64,
                "tlp": "WHITE",
            }
            for i in range(5)
        ])
        result = await dedup_rate_reports_url_canonical.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal(0)
        assert result.detail["distinct_urls"] == 5
        assert result.detail["duplicate_rows"] == 0

    async def test_always_pass_under_unique_constraint(
        self, db_session: AsyncSession
    ) -> None:
        """Production path: with the UNIQUE index on url_canonical in
        place, the ratio is always 0 and the severity is always pass.
        This is the tautology documented in dedup_rate.py's module
        docstring — the check acts as a regression guard for the
        unique constraint itself."""
        source_id = await _insert_source(db_session, "V")
        await _seed_reports(db_session, [
            {
                "published": dt.date(2026, 1, i + 1),
                "source_id": source_id,
                "title": f"t{i}",
                "url": f"https://example.com/u{i}",
                "url_canonical": f"https://example.com/u{i}",
                "sha256_title": f"{i}" * 64,
                "tlp": "WHITE",
            }
            for i in range(10)
        ])
        result = await dedup_rate_reports_url_canonical.check(db_session)
        assert result.severity == "pass"
        assert result.observed == Decimal(0)
        assert result.detail["distinct_urls"] == 10
        assert result.detail["duplicate_rows"] == 0

    # NOTE: the warn path cannot be exercised end-to-end against the
    # sqlite test DB because ``reports.url_canonical`` has a UNIQUE
    # constraint that sqlite refuses to drop at runtime ("index
    # associated with UNIQUE or PRIMARY KEY constraint cannot be
    # dropped"). The algorithm's threshold logic is instead pinned
    # by the pure-function tests in :class:`TestComputeDedupSeverity`
    # below. See dedup_rate.py module docstring for the tautology
    # rationale.


class TestComputeDedupSeverity:
    """Pure-function tests for the dedup ratio + severity helper.

    Exercises the warn path that the DB-backed test cannot reach
    under the production UNIQUE constraint.
    """

    def test_empty_table_is_pass(self) -> None:
        severity, ratio = compute_dedup_severity(total=0, distinct=0)
        assert severity == "pass"
        assert ratio == Decimal(0)

    def test_negative_total_is_pass(self) -> None:
        """Defensive: negative should never happen, but must not
        crash the ratio math."""
        severity, ratio = compute_dedup_severity(total=-1, distinct=0)
        assert severity == "pass"
        assert ratio == Decimal(0)

    def test_all_distinct_is_pass(self) -> None:
        severity, ratio = compute_dedup_severity(total=10, distinct=10)
        assert severity == "pass"
        assert ratio == Decimal(0)

    def test_ratio_equal_to_threshold_is_pass(self) -> None:
        """Ratio == threshold should NOT trigger warn (strict > only)."""
        # 100 rows, 85 distinct → ratio = 0.15 exactly
        severity, ratio = compute_dedup_severity(total=100, distinct=85)
        assert ratio == Decimal("0.15")
        assert severity == "pass"

    def test_ratio_just_above_threshold_is_warn(self) -> None:
        # 100 rows, 84 distinct → ratio = 0.16 > 0.15
        severity, ratio = compute_dedup_severity(total=100, distinct=84)
        assert ratio == Decimal("0.16")
        assert severity == "warn"

    def test_high_dedup_rate_is_warn(self) -> None:
        # 5 rows, 3 distinct → ratio = 0.4 > 0.15
        severity, ratio = compute_dedup_severity(total=5, distinct=3)
        assert ratio == Decimal("0.4")
        assert severity == "warn"

    def test_full_dedup_rate_is_warn(self) -> None:
        # 10 rows, 1 distinct → ratio = 0.9 > 0.15
        severity, ratio = compute_dedup_severity(total=10, distinct=1)
        assert ratio == Decimal("0.9")
        assert severity == "warn"

    def test_zero_distinct_with_rows_is_warn(self) -> None:
        """Edge case: distinct < total is the normal warn path."""
        severity, ratio = compute_dedup_severity(total=10, distinct=0)
        assert ratio == Decimal(1)  # 100% dedup
        assert severity == "warn"
