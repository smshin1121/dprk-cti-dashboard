"""Tests for worker.ingest.taxii.normalize — STIX → StagingRowDraft.

Covers decisions C (url_canonical = URN), G (field mapping + semantic mismatch),
and the user requirement that missing description → raw_text=None (never empty string).
"""

from __future__ import annotations

import datetime as dt

import pytest

from worker.ingest.taxii.normalize import (
    normalize_stix_object,
    stix_urn,
)
from worker.ingest.taxii.stix_parser import ParsedStixObject


def _parsed(obj: dict) -> ParsedStixObject:
    return ParsedStixObject(raw=obj)


def _base_stix(
    type_: str = "intrusion-set",
    id_suffix: str = "001",
    **overrides,
) -> dict:
    obj = {
        "type": type_,
        "id": f"{type_}--00000000-0000-0000-0000-{id_suffix:>012}",
        "name": f"Test {type_} {id_suffix}",
        "created": "2026-01-01T00:00:00Z",
        "modified": "2026-04-15T00:00:00Z",
        "description": "A test description.",
    }
    obj.update(overrides)
    return obj


# ---------------------------------------------------------------------------
# stix_urn — decision C
# ---------------------------------------------------------------------------


def test_stix_urn_format() -> None:
    urn = stix_urn("intrusion-set--c93fccb1-e8e8-42cf-ae33-2ad1d9ba0f03")
    assert urn == "urn:stix:intrusion-set--c93fccb1-e8e8-42cf-ae33-2ad1d9ba0f03"


def test_stix_urn_preserves_full_id() -> None:
    urn = stix_urn("malware--0a3ead4e-1234-5678-9abc-def012345678")
    assert urn.startswith("urn:stix:")
    assert "malware--0a3ead4e-1234-5678-9abc-def012345678" in urn


# ---------------------------------------------------------------------------
# url_canonical = always URN — decision C
# ---------------------------------------------------------------------------


def test_url_canonical_is_always_urn() -> None:
    """url_canonical must be the STIX URN regardless of ATT&CK URL."""
    obj = _base_stix(external_references=[
        {"source_name": "mitre-attack", "url": "https://attack.mitre.org/groups/G0032/"},
    ])
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url_canonical.startswith("urn:stix:")
    assert "intrusion-set--" in draft.url_canonical


def test_url_canonical_without_attack_url() -> None:
    """When no ATT&CK URL, url_canonical is still the URN."""
    obj = _base_stix()
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url_canonical.startswith("urn:stix:")


# ---------------------------------------------------------------------------
# url = ATT&CK URL if present, else URN — decision C
# ---------------------------------------------------------------------------


def test_url_is_attack_url_when_present() -> None:
    obj = _base_stix(external_references=[
        {"source_name": "mitre-attack", "url": "https://attack.mitre.org/groups/G0032/"},
    ])
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url == "https://attack.mitre.org/groups/G0032/"


def test_url_fallback_to_urn_when_no_attack_url() -> None:
    obj = _base_stix()
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url == draft.url_canonical


def test_url_finds_attack_url_without_source_name() -> None:
    """Fallback: any reference containing attack.mitre.org."""
    obj = _base_stix(external_references=[
        {"source_name": "other", "url": "https://attack.mitre.org/software/S0001/"},
    ])
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url == "https://attack.mitre.org/software/S0001/"


def test_url_prefers_mitre_attack_source_name() -> None:
    """If both mitre-attack and another attack.mitre.org URL exist, prefer mitre-attack."""
    obj = _base_stix(external_references=[
        {"source_name": "other", "url": "https://attack.mitre.org/wrong/"},
        {"source_name": "mitre-attack", "url": "https://attack.mitre.org/groups/G0032/"},
    ])
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url == "https://attack.mitre.org/groups/G0032/"


def test_url_with_non_list_external_references() -> None:
    obj = _base_stix(external_references="not a list")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url == draft.url_canonical


# ---------------------------------------------------------------------------
# modified → published — decision G (semantic mismatch)
# ---------------------------------------------------------------------------


def test_published_from_modified() -> None:
    """modified is the primary source for published (decision G)."""
    obj = _base_stix(modified="2026-04-15T12:00:00Z", created="2026-01-01T00:00:00Z")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.published is not None
    assert draft.published.year == 2026
    assert draft.published.month == 4
    assert draft.published.day == 15


def test_published_fallback_to_created() -> None:
    """When modified is absent, fall back to created."""
    obj = _base_stix(created="2026-01-01T00:00:00Z")
    del obj["modified"]
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.published is not None
    assert draft.published.month == 1


def test_published_none_when_both_absent() -> None:
    obj = _base_stix()
    del obj["modified"]
    del obj["created"]
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.published is None


def test_published_handles_z_suffix() -> None:
    """STIX often uses 'Z' suffix for UTC."""
    obj = _base_stix(modified="2026-04-15T12:00:00.000Z")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.published is not None
    assert draft.published.tzinfo is not None


def test_published_is_tz_aware() -> None:
    obj = _base_stix(modified="2026-04-15T12:00:00")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.published is not None
    assert draft.published.tzinfo is not None  # Naive → UTC


def test_modified_not_confused_with_created() -> None:
    """modified and created are different — only modified maps to published."""
    obj = _base_stix(
        modified="2026-04-15T00:00:00Z",
        created="2020-01-01T00:00:00Z",
    )
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.published is not None
    assert draft.published.year == 2026  # modified, not created


# ---------------------------------------------------------------------------
# description → raw_text — user requirement: None if absent, never ""
# ---------------------------------------------------------------------------


def test_raw_text_from_description() -> None:
    obj = _base_stix(description="Lazarus Group is a North Korean APT.")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.raw_text == "Lazarus Group is a North Korean APT."


def test_raw_text_none_when_no_description() -> None:
    """Missing description → raw_text=None (not empty string)."""
    obj = _base_stix()
    del obj["description"]
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.raw_text is None


def test_raw_text_none_when_empty_description() -> None:
    """Empty string description → raw_text=None (not empty string)."""
    obj = _base_stix(description="")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.raw_text is None


def test_raw_text_none_when_whitespace_description() -> None:
    """Whitespace-only description → raw_text=None."""
    obj = _base_stix(description="   \n\t  ")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.raw_text is None


def test_raw_text_strips_whitespace() -> None:
    obj = _base_stix(description="  Some text  \n")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.raw_text == "Some text"


# ---------------------------------------------------------------------------
# summary is always None (LLM-filled, Phase 4)
# ---------------------------------------------------------------------------


def test_summary_always_none() -> None:
    obj = _base_stix(description="Long description here...")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.summary is None


# ---------------------------------------------------------------------------
# title / sha256_title
# ---------------------------------------------------------------------------


def test_title_from_name() -> None:
    obj = _base_stix(name="Lazarus Group")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.title == "Lazarus Group"


def test_title_none_when_no_name() -> None:
    obj = _base_stix()
    del obj["name"]
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.title is None
    assert draft.sha256_title is None


def test_title_none_when_empty_name() -> None:
    obj = _base_stix(name="  ")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.title is None


def test_sha256_title_consistent_with_bootstrap() -> None:
    """sha256_title should use the same helper as bootstrap."""
    from worker.bootstrap.normalize import sha256_title
    obj = _base_stix(name="Lazarus Group")
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.sha256_title == sha256_title("Lazarus Group")


# ---------------------------------------------------------------------------
# Missing id → returns None
# ---------------------------------------------------------------------------


def test_returns_none_when_no_id() -> None:
    obj = {"type": "intrusion-set", "name": "No ID"}
    draft = normalize_stix_object(_parsed(obj))
    assert draft is None


# ---------------------------------------------------------------------------
# Indicator type (decision B inclusion)
# ---------------------------------------------------------------------------


def test_indicator_normalizes_correctly() -> None:
    """Indicators may have different field patterns — verify normalize works."""
    obj = {
        "type": "indicator",
        "id": "indicator--abc-123",
        "name": "Malicious URL Pattern",
        "created": "2026-03-01T00:00:00Z",
        "modified": "2026-04-01T00:00:00Z",
        "description": "Detects known DPRK C2 URLs.",
        "pattern": "[url:value LIKE 'http://evil.example.com/%']",
        "pattern_type": "stix",
    }
    draft = normalize_stix_object(_parsed(obj))
    assert draft is not None
    assert draft.url_canonical == "urn:stix:indicator--abc-123"
    assert draft.title == "Malicious URL Pattern"
    assert draft.raw_text == "Detects known DPRK C2 URLs."
