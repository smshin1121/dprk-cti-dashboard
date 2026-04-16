"""Tests for worker.ingest.taxii.stix_parser — STIX envelope parser + type filter."""

from __future__ import annotations

from worker.ingest.taxii.config import DEFAULT_STIX_TYPES
from worker.ingest.taxii.stix_parser import parse_stix_objects


def _obj(type_: str = "intrusion-set", id_suffix: str = "001", **extra) -> dict:
    base = {
        "type": type_,
        "id": f"{type_}--00000000-0000-0000-0000-{id_suffix:>012}",
        "name": f"Test {type_} {id_suffix}",
        "created": "2026-01-01T00:00:00Z",
        "modified": "2026-04-15T00:00:00Z",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Happy path — default whitelist
# ---------------------------------------------------------------------------


def test_parse_all_default_types_accepted() -> None:
    """All 6 default types pass the filter."""
    objects = [
        _obj("intrusion-set", "001"),
        _obj("malware", "002"),
        _obj("attack-pattern", "003"),
        _obj("tool", "004"),
        _obj("campaign", "005"),
        _obj("indicator", "006"),
    ]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 6
    assert result.total_in_envelope == 6
    assert result.filtered_by_type == 0
    assert result.malformed_count == 0


# ---------------------------------------------------------------------------
# Type filtering — decision B
# ---------------------------------------------------------------------------


def test_relationship_filtered_out() -> None:
    objects = [
        _obj("intrusion-set", "001"),
        _obj("relationship", "002"),
    ]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 1
    assert result.objects[0].raw["type"] == "intrusion-set"
    assert result.filtered_by_type == 1


def test_identity_filtered_out() -> None:
    objects = [_obj("identity", "001")]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.filtered_by_type == 1


def test_marking_definition_filtered_out() -> None:
    objects = [_obj("marking-definition", "001")]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.filtered_by_type == 1


def test_x_mitre_types_filtered_out() -> None:
    objects = [
        _obj("x-mitre-tactic", "001"),
        _obj("x-mitre-matrix", "002"),
        _obj("x-mitre-data-source", "003"),
    ]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.filtered_by_type == 3


def test_course_of_action_filtered_out() -> None:
    objects = [_obj("course-of-action", "001")]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.filtered_by_type == 1


def test_indicator_explicitly_included() -> None:
    """Decision B: indicator is explicitly in the default whitelist."""
    objects = [_obj("indicator", "001")]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 1
    assert result.objects[0].raw["type"] == "indicator"


def test_custom_type_whitelist() -> None:
    """Per-collection override: only intrusion-set."""
    objects = [
        _obj("intrusion-set", "001"),
        _obj("malware", "002"),
    ]
    result = parse_stix_objects(objects, type_whitelist=["intrusion-set"])
    assert len(result.objects) == 1
    assert result.filtered_by_type == 1


# ---------------------------------------------------------------------------
# Malformed objects
# ---------------------------------------------------------------------------


def test_missing_id_is_malformed() -> None:
    objects = [{"type": "intrusion-set", "name": "No ID"}]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.malformed_count == 1


def test_missing_type_is_malformed() -> None:
    objects = [{"id": "intrusion-set--abc", "name": "No Type"}]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.malformed_count == 1


def test_empty_id_is_malformed() -> None:
    objects = [{"type": "malware", "id": "", "name": "Empty ID"}]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.malformed_count == 1


def test_non_dict_object_is_malformed() -> None:
    objects = ["not a dict", 42, None]  # type: ignore[list-item]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.malformed_count == 3


def test_mixed_valid_and_malformed() -> None:
    objects = [
        _obj("intrusion-set", "001"),
        {"type": "malware"},  # missing id
        _obj("tool", "003"),
        "garbage",
        _obj("relationship", "004"),  # filtered by type
    ]
    result = parse_stix_objects(objects, type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 2
    assert result.malformed_count == 2  # missing id + "garbage"
    assert result.filtered_by_type == 1  # relationship
    assert result.total_in_envelope == 5


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_objects_list() -> None:
    result = parse_stix_objects([], type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 0
    assert result.total_in_envelope == 0


# ---------------------------------------------------------------------------
# ParsedStixObject preserves raw dict
# ---------------------------------------------------------------------------


def test_parsed_object_preserves_all_fields() -> None:
    obj = _obj("malware", "001", description="A test malware", labels=["trojan"])
    result = parse_stix_objects([obj], type_whitelist=DEFAULT_STIX_TYPES)
    assert len(result.objects) == 1
    assert result.objects[0].raw["description"] == "A test malware"
    assert result.objects[0].raw["labels"] == ["trojan"]
