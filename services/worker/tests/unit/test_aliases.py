"""Tests for worker.bootstrap.aliases."""

from __future__ import annotations

from pathlib import Path

import pytest

from worker.bootstrap.aliases import (
    AliasDictionary,
    AliasDictionaryError,
    load_aliases,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REAL_DICTIONARY = REPO_ROOT / "data/dictionaries/aliases.yml"


# ---------------------------------------------------------------------------
# Happy path against the real committed dictionary
# ---------------------------------------------------------------------------


def test_real_dictionary_loads_without_error() -> None:
    aliases = load_aliases(REAL_DICTIONARY)
    assert "groups" in aliases.types()
    assert "Lazarus" in aliases.canonicals("groups")


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("Lazarus", "Lazarus"),
        ("APT38", "Lazarus"),
        ("Hidden Cobra", "Lazarus"),
        ("HIDDEN COBRA", "Lazarus"),
        ("hidden cobra", "Lazarus"),  # case-insensitive
        ("  APT38  ", "Lazarus"),  # whitespace trim
        ("APT43", "Kimsuky"),
        ("Velvet Chollima", "Kimsuky"),
        ("APT37", "ScarCruft"),
        ("Onyx Sleet", "Andariel"),
    ],
)
def test_normalize_known_group_aliases(alias: str, expected: str) -> None:
    aliases = load_aliases(REAL_DICTIONARY)
    assert aliases.normalize("groups", alias) == expected


def test_normalize_unknown_alias_returns_none() -> None:
    aliases = load_aliases(REAL_DICTIONARY)
    assert aliases.normalize("groups", "NonExistentGroup") is None


def test_normalize_unknown_type_returns_none() -> None:
    aliases = load_aliases(REAL_DICTIONARY)
    assert aliases.normalize("nonexistent_type", "Lazarus") is None


def test_normalize_empty_string_returns_none() -> None:
    aliases = load_aliases(REAL_DICTIONARY)
    assert aliases.normalize("groups", "") is None


def test_empty_type_section_tolerated() -> None:
    """The `cve: {}` entry in the real file exercises this path."""
    aliases = load_aliases(REAL_DICTIONARY)
    assert "cve" in aliases.types()
    assert aliases.canonicals("cve") == ()
    assert aliases.normalize("cve", "CVE-2024-0001") is None


# ---------------------------------------------------------------------------
# Bijection lint: reject alias claimed by two canonicals
# ---------------------------------------------------------------------------


def test_bijection_violation_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  Lazarus:
    - APT38
  BlueNoroff:
    - APT38
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="bijection violated"):
        load_aliases(bad)


def test_same_alias_listed_twice_under_same_canonical_tolerated(tmp_path: Path) -> None:
    """A duplicate alias within one canonical's list is redundant but
    not a correctness problem. The loader tolerates it silently."""
    doc = tmp_path / "aliases.yml"
    doc.write_text(
        """
groups:
  Lazarus:
    - APT38
    - APT38
""".strip(),
        encoding="utf-8",
    )
    aliases = load_aliases(doc)
    assert aliases.normalize("groups", "APT38") == "Lazarus"


# ---------------------------------------------------------------------------
# Self-reference lint: canonical must not appear in its own alias list
# ---------------------------------------------------------------------------


def test_canonical_self_reference_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  Lazarus:
    - Lazarus
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="lists itself as an alias"):
        load_aliases(bad)


def test_canonical_self_reference_case_insensitive(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  Lazarus:
    - LAZARUS
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="lists itself as an alias"):
        load_aliases(bad)


# ---------------------------------------------------------------------------
# Empty-string rejection for canonicals and aliases
# ---------------------------------------------------------------------------


def test_empty_canonical_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  "":
    - SomeAlias
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="canonical name must be a non-empty"):
        load_aliases(bad)


def test_empty_alias_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  Lazarus:
    - ""
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="must be a non-empty string"):
        load_aliases(bad)


def test_whitespace_only_alias_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  Lazarus:
    - "   "
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="must be a non-empty string"):
        load_aliases(bad)


# ---------------------------------------------------------------------------
# Schema-level errors
# ---------------------------------------------------------------------------


def test_non_mapping_top_level_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(AliasDictionaryError, match="top-level YAML must be a mapping"):
        load_aliases(bad)


def test_alias_list_must_be_a_list(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  Lazarus: APT38
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="must be a list"):
        load_aliases(bad)


def test_section_must_be_a_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yml"
    bad.write_text(
        """
groups:
  - Lazarus
  - Kimsuky
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AliasDictionaryError, match="must be a mapping"):
        load_aliases(bad)


def test_empty_file_tolerated(tmp_path: Path) -> None:
    doc = tmp_path / "aliases.yml"
    doc.write_text("", encoding="utf-8")
    aliases = load_aliases(doc)
    assert aliases.types() == ()


# ---------------------------------------------------------------------------
# Return-type assertions
# ---------------------------------------------------------------------------


def test_load_returns_alias_dictionary_instance() -> None:
    aliases = load_aliases(REAL_DICTIONARY)
    assert isinstance(aliases, AliasDictionary)


def test_canonicals_are_sorted_and_unique() -> None:
    aliases = load_aliases(REAL_DICTIONARY)
    groups = aliases.canonicals("groups")
    assert list(groups) == sorted(groups)
    assert len(groups) == len(set(groups))
