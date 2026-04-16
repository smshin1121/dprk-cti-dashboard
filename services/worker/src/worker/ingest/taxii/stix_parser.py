"""STIX 2.1 envelope parser with configurable type filtering.

Validates the structural integrity of STIX objects from a TAXII envelope
and filters to the configured type whitelist (decision B). Objects that
fail validation are counted but not propagated — malformed objects should
not block valid ones from reaching staging.

Per decision B, the default whitelist is 6 types:
  intrusion-set, malware, attack-pattern, tool, campaign, indicator.

Structural types (relationship, identity, marking-definition,
x-mitre-tactic, x-mitre-matrix, x-mitre-data-source, course-of-action)
are excluded by default.
"""

from __future__ import annotations

from dataclasses import dataclass


__all__ = [
    "ParsedStixObject",
    "StixParseOutcome",
    "parse_stix_objects",
]


# Required fields for a valid STIX object in our pipeline.
# We intentionally do NOT require 'name' for all types — indicators
# may not have a 'name'. But 'id' and 'type' are always required.
_REQUIRED_FIELDS = ("id", "type")


@dataclass(frozen=True, slots=True)
class ParsedStixObject:
    """A validated STIX object ready for normalization.

    This is a thin wrapper around the raw dict — no field extraction
    happens here. The normalize module handles field mapping.
    """

    raw: dict


@dataclass(frozen=True, slots=True)
class StixParseOutcome:
    """Result of parsing STIX objects from a TAXII envelope."""

    objects: tuple[ParsedStixObject, ...]
    total_in_envelope: int
    filtered_by_type: int
    malformed_count: int


def parse_stix_objects(
    raw_objects: tuple[dict, ...] | list[dict],
    *,
    type_whitelist: list[str],
) -> StixParseOutcome:
    """Filter and validate STIX objects from a TAXII envelope.

    1. Reject objects missing required fields (``id``, ``type``).
    2. Reject objects whose ``type`` is not in ``type_whitelist``.
    3. Return valid objects as ``ParsedStixObject`` wrappers.

    Objects that fail validation are counted in ``malformed_count``
    (missing fields) or ``filtered_by_type`` (wrong type) but never
    propagated — one bad object does not block valid ones.
    """
    type_set = set(type_whitelist)
    accepted: list[ParsedStixObject] = []
    filtered_by_type = 0
    malformed = 0

    for obj in raw_objects:
        if not isinstance(obj, dict):
            malformed += 1
            continue

        # Check required fields exist and are strings (P2 Codex R3:
        # reject non-string id/type to prevent bogus urn:stix: keys).
        missing = [
            f for f in _REQUIRED_FIELDS
            if f not in obj or not isinstance(obj[f], str) or not obj[f].strip()
        ]
        if missing:
            malformed += 1
            continue

        # Type filter (decision B)
        stix_type = obj["type"]
        if stix_type not in type_set:
            filtered_by_type += 1
            continue

        accepted.append(ParsedStixObject(raw=obj))

    return StixParseOutcome(
        objects=tuple(accepted),
        total_in_envelope=len(raw_objects),
        filtered_by_type=filtered_by_type,
        malformed_count=malformed,
    )
