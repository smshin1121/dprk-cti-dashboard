"""Tests for worker.ingest.tag_preview — hashtag extraction + classify_tags reuse."""

from __future__ import annotations

from pathlib import Path

from worker.bootstrap.aliases import load_aliases
from worker.ingest.tag_preview import TagPreviewResult, preview_tags


REPO_ROOT = Path(__file__).resolve().parents[4]
ALIASES = load_aliases(REPO_ROOT / "data/dictionaries/aliases.yml")


# ---------------------------------------------------------------------------
# Known aliases produce non-unknown results
# ---------------------------------------------------------------------------


def test_known_actor_tag_not_unknown() -> None:
    result = preview_tags("#Lazarus #APT38", None, ALIASES)
    assert result.total >= 2
    assert result.unknown == 0


def test_known_cve_tag_not_unknown() -> None:
    result = preview_tags("#CVE-2024-1234", None, ALIASES)
    assert result.total == 1
    assert result.unknown == 0


# ---------------------------------------------------------------------------
# Unknown fallback — bare #malware → TAG_TYPE_UNKNOWN
# ---------------------------------------------------------------------------


def test_bare_malware_tag_is_unknown() -> None:
    result = preview_tags("#malware report overview", None, ALIASES)
    assert result.total >= 1
    assert result.unknown >= 1


# ---------------------------------------------------------------------------
# No hashtag tokens → (0, 0)
# ---------------------------------------------------------------------------


def test_no_hashtags_returns_zero() -> None:
    result = preview_tags("Plain text without tags", "Also plain", ALIASES)
    assert result == TagPreviewResult(total=0, unknown=0)


def test_empty_input_returns_zero() -> None:
    result = preview_tags(None, None, ALIASES)
    assert result == TagPreviewResult(total=0, unknown=0)


# ---------------------------------------------------------------------------
# Title + summary combined
# ---------------------------------------------------------------------------


def test_tags_from_both_title_and_summary() -> None:
    result = preview_tags("#Lazarus", "#Kimsuky", ALIASES)
    assert result.total >= 2
    assert result.unknown == 0


# ---------------------------------------------------------------------------
# Mixed known and unknown
# ---------------------------------------------------------------------------


def test_mixed_known_and_unknown() -> None:
    result = preview_tags("#Lazarus #unknownvendortag", None, ALIASES)
    assert result.total >= 2
    assert result.unknown >= 1


# ---------------------------------------------------------------------------
# Result is frozen
# ---------------------------------------------------------------------------


def test_tag_preview_result_is_frozen() -> None:
    import pytest
    result = TagPreviewResult(total=1, unknown=0)
    with pytest.raises(AttributeError):
        result.total = 99  # type: ignore[misc]
