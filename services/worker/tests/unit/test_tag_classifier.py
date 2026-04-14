"""Tests for worker.bootstrap.normalize.classify_tags."""

from __future__ import annotations

from pathlib import Path

import pytest

from worker.bootstrap.aliases import load_aliases
from worker.bootstrap.normalize import (
    DEFAULT_SECTOR_CODES,
    TAG_TYPE_ACTOR,
    TAG_TYPE_CVE,
    TAG_TYPE_MALWARE,
    TAG_TYPE_OPERATION,
    TAG_TYPE_SECTOR,
    TAG_TYPE_UNKNOWN,
    classify_tags,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def aliases():
    return load_aliases(REPO_ROOT / "data/dictionaries/aliases.yml")


# ---------------------------------------------------------------------------
# Empty input handling
# ---------------------------------------------------------------------------


def test_classify_none_returns_empty_list(aliases) -> None:
    assert classify_tags(None, aliases) == []


def test_classify_empty_string_returns_empty_list(aliases) -> None:
    assert classify_tags("", aliases) == []


def test_classify_whitespace_only_returns_empty_list(aliases) -> None:
    assert classify_tags("   ", aliases) == []


def test_classify_no_hashtag_tokens_returns_empty(aliases) -> None:
    """Fixture failure case `no-parseable-tags` — cell contains no
    `#` tokens at all, classifier returns []."""
    result = classify_tags("notahashtag lazarus also-not-a-tag", aliases)
    assert result == []


# ---------------------------------------------------------------------------
# CVE classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag_cell", "expected"),
    [
        ("#cve-2024-1234", "CVE-2024-1234"),
        ("#CVE-2024-1234", "CVE-2024-1234"),
        ("#cve-2024-9876", "CVE-2024-9876"),
        ("#cve-1999-0001", "CVE-1999-0001"),
        ("#cve-2024-1234567", "CVE-2024-1234567"),
    ],
)
def test_classify_cve_tag(aliases, tag_cell: str, expected: str) -> None:
    result = classify_tags(tag_cell, aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_CVE
    assert result[0].canonical == expected


def test_classify_malformed_cve_falls_through_to_unknown(aliases) -> None:
    """3-digit year or 3-digit number is not a valid CVE; it must not
    be classified as CVE but may end up as unknown_type."""
    result = classify_tags("#cve-999-1234", aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_UNKNOWN


# ---------------------------------------------------------------------------
# Actor classification via alias dictionary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_canonical"),
    [
        ("#lazarus", "Lazarus"),
        ("#Lazarus", "Lazarus"),
        ("#LAZARUS", "Lazarus"),
        ("#apt38", "Lazarus"),
        ("#APT38", "Lazarus"),
        ("#kimsuky", "Kimsuky"),
        ("#apt43", "Kimsuky"),
        ("#apt37", "ScarCruft"),
        ("#onyx sleet", "Andariel"),
    ],
)
def test_classify_actor_tag(aliases, raw: str, expected_canonical: str) -> None:
    # The "#onyx sleet" case has an internal space which splits into
    # two tokens — skip via parametrize filter for that one form.
    if " " in raw:
        pytest.skip("space-separated aliases don't round-trip as single hashtag")
    result = classify_tags(raw, aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_ACTOR
    assert result[0].canonical == expected_canonical


# ---------------------------------------------------------------------------
# Malware classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#appleseed", "AppleSeed"),
        ("#AppleSeed", "AppleSeed"),
        ("#bluelight", "BlueLight"),
        ("#rokrat", "RokRat"),
    ],
)
def test_classify_malware_tag(aliases, raw: str, expected: str) -> None:
    result = classify_tags(raw, aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_MALWARE
    assert result[0].canonical == expected


# ---------------------------------------------------------------------------
# Operation / campaign classification
# ---------------------------------------------------------------------------


def test_classify_operation_tag(aliases) -> None:
    result = classify_tags("#operation-stealthy-tiger", aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_OPERATION
    assert result[0].canonical == "Operation Stealthy Tiger"


def test_classify_operation_tag_ghost_scribe(aliases) -> None:
    result = classify_tags("#operation-ghost-scribe", aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_OPERATION
    assert result[0].canonical == "Operation Ghost Scribe"


# ---------------------------------------------------------------------------
# Sector classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sector",
    ["#crypto", "#finance", "#defense", "#healthcare", "#media", "#technology"],
)
def test_classify_sector_tag(aliases, sector: str) -> None:
    result = classify_tags(sector, aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_SECTOR
    assert result[0].canonical == sector[1:].lower()


def test_classify_sector_is_case_insensitive(aliases) -> None:
    result = classify_tags("#CRYPTO", aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_SECTOR
    assert result[0].canonical == "crypto"


def test_sector_codes_constant_is_nonempty() -> None:
    assert "crypto" in DEFAULT_SECTOR_CODES
    assert "finance" in DEFAULT_SECTOR_CODES


# ---------------------------------------------------------------------------
# Unknown-type fallback
# ---------------------------------------------------------------------------


def test_classify_unknown_tag_preserves_raw(aliases) -> None:
    result = classify_tags("#something-nobody-has-heard-of", aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_UNKNOWN
    assert result[0].canonical is None
    assert result[0].raw == "something-nobody-has-heard-of"


def test_classify_bare_malware_meta_tag_is_unknown(aliases) -> None:
    """`#malware` is a generic meta-tag in vendor feeds, not a specific
    canonical. The fixture mixes it with actual malware names."""
    result = classify_tags("#malware", aliases)
    assert len(result) == 1
    assert result[0].type_ == TAG_TYPE_UNKNOWN


# ---------------------------------------------------------------------------
# Multi-tag parsing — the fixture's real cells
# ---------------------------------------------------------------------------


def test_classify_fixture_lazarus_report_row(aliases) -> None:
    cell = "#lazarus #malware #appleseed #cve-2024-1234 #crypto"
    result = classify_tags(cell, aliases)
    assert len(result) == 5
    types = [t.type_ for t in result]
    canonicals = [t.canonical for t in result]
    assert types == [
        TAG_TYPE_ACTOR,
        TAG_TYPE_UNKNOWN,
        TAG_TYPE_MALWARE,
        TAG_TYPE_CVE,
        TAG_TYPE_SECTOR,
    ]
    assert canonicals == ["Lazarus", None, "AppleSeed", "CVE-2024-1234", "crypto"]


def test_classify_fixture_kimsuky_report_row(aliases) -> None:
    cell = "#kimsuky #operation-stealthy-tiger #finance"
    result = classify_tags(cell, aliases)
    assert len(result) == 3
    assert result[0].canonical == "Kimsuky"
    assert result[1].canonical == "Operation Stealthy Tiger"
    assert result[2].canonical == "finance"


def test_classify_adjacent_tags_without_space(aliases) -> None:
    """`#a#b` is how some vendor feeds concatenate tags when editing
    by hand. The tokenizer must split on `#` as well as whitespace."""
    result = classify_tags("#lazarus#crypto", aliases)
    assert len(result) == 2
    assert result[0].type_ == TAG_TYPE_ACTOR
    assert result[1].type_ == TAG_TYPE_SECTOR


def test_classify_preserves_order(aliases) -> None:
    cell = "#crypto #lazarus #cve-2024-1234"
    result = classify_tags(cell, aliases)
    assert [t.type_ for t in result] == [
        TAG_TYPE_SECTOR,
        TAG_TYPE_ACTOR,
        TAG_TYPE_CVE,
    ]


def test_classify_custom_sector_codes_override(aliases) -> None:
    """A caller may pass a narrower sector set to reject unknown
    vocabulary rather than silently classifying it."""
    result = classify_tags(
        "#finance #crypto",
        aliases,
        sector_codes=frozenset({"finance"}),
    )
    assert result[0].type_ == TAG_TYPE_SECTOR
    assert result[1].type_ == TAG_TYPE_UNKNOWN


# ---------------------------------------------------------------------------
# Never-raises guarantee
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cell",
    [
        "#",  # just a hash
        "# #",  # empty tags
        "##",  # double hash
        "#\t\t\t",  # hash followed by whitespace
        "###lazarus",  # multiple leading hashes
    ],
)
def test_classify_never_raises_on_edge_input(aliases, cell: str) -> None:
    # result may be empty or may contain unknown_type entries, but the
    # classifier must not raise.
    classify_tags(cell, aliases)
