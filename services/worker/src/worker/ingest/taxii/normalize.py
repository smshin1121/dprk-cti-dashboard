"""Normalize a parsed STIX object into a StagingRowDraft.

Mapping (decision G):
  name           → title
  STIX URN       → url_canonical  (always ``urn:stix:{type}--{uuid}``, decision C)
  ATT&CK URL     → url            (from external_references, fallback = url_canonical)
  description    → raw_text       (None if absent — never empty string)
  modified       → published      (semantic mismatch acknowledged, decision G)
  sha256(title)  → sha256_title   (reuses bootstrap helper)
  summary        → None           (LLM-filled, Phase 4)
  source_id      → None           (decision D3, staging-only)

**Semantic mismatch acknowledged**: STIX ``modified`` is an object update
timestamp (when the STIX producer last edited the object), NOT a publication
date. It is mapped to ``staging.published`` as a pragmatic best-effort
approximation because the staging schema has no dedicated ``updated_at``
column. ``created`` is used as fallback only when ``modified`` is absent.
This is a temporary mapping — if a future migration adds ``stix_modified``
or ``ingested_at`` to staging, the mapping should be revised.
"""

from __future__ import annotations

import datetime as dt

from worker.bootstrap.normalize import sha256_title
from worker.ingest.normalize import StagingRowDraft
from worker.ingest.taxii.stix_parser import ParsedStixObject


__all__ = [
    "normalize_stix_object",
    "stix_urn",
]


def stix_urn(stix_id: str) -> str:
    """Build the canonical URN for a STIX object.

    Per decision C: ``url_canonical`` is ALWAYS the STIX URN,
    regardless of whether an ATT&CK URL exists. The STIX ID is
    globally unique (UUID v4/v5) and stable across TAXII server
    versions. Format: ``urn:stix:{type}--{uuid}``.
    """
    return f"urn:stix:{stix_id}"


def _extract_attack_url(obj: dict) -> str | None:
    """Extract the ATT&CK URL from external_references if present.

    Looks for ``source_name == "mitre-attack"`` first, then any
    reference with a ``url`` field containing ``attack.mitre.org``.
    Returns ``None`` if no ATT&CK URL is found.
    """
    refs = obj.get("external_references")
    if not isinstance(refs, list):
        return None

    # Priority 1: explicit mitre-attack source
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("source_name") == "mitre-attack" and ref.get("url"):
            return ref["url"]

    # Priority 2: any URL containing attack.mitre.org
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        url = ref.get("url", "")
        if "attack.mitre.org" in url:
            return url

    return None


def _parse_stix_timestamp(raw: str | None) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp from STIX modified/created fields.

    Returns a tz-aware datetime. Naive datetimes are assumed UTC.
    Returns None on parse failure or missing value.
    """
    if not raw:
        return None
    try:
        ts = dt.datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        # STIX timestamps may use 'Z' suffix which older Python
        # versions don't handle — normalize to +00:00
        try:
            ts = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts


def normalize_stix_object(parsed: ParsedStixObject) -> StagingRowDraft | None:
    """Convert a parsed STIX object to a staging draft.

    Returns ``None`` if the object has no ``id`` field (url_canonical
    cannot be computed). Objects with empty names are kept — they
    contribute to DQ metrics.

    Field mapping follows decision G with semantic mismatch note.
    """
    obj = parsed.raw
    stix_id = obj.get("id")
    if not stix_id:
        return None

    # url_canonical = always STIX URN (decision C)
    url_canonical = stix_urn(stix_id)

    # url = ATT&CK URL if present, else fallback to URN (decision C)
    attack_url = _extract_attack_url(obj)
    url = attack_url if attack_url else url_canonical

    # title = name field
    name = obj.get("name")
    title = name.strip() if isinstance(name, str) and name.strip() else None

    # sha256_title (reuses bootstrap helper)
    title_hash = sha256_title(title) if title else None

    # published = modified (decision G, semantic mismatch acknowledged)
    # Fallback to created if modified is absent
    published = _parse_stix_timestamp(obj.get("modified"))
    if published is None:
        published = _parse_stix_timestamp(obj.get("created"))

    # raw_text = description (None if absent — never empty string)
    description = obj.get("description")
    raw_text: str | None = None
    if isinstance(description, str) and description.strip():
        raw_text = description.strip()

    # summary = None (LLM-filled, Phase 4)
    return StagingRowDraft(
        url=url,
        url_canonical=url_canonical,
        sha256_title=title_hash,
        title=title,
        published=published,
        summary=None,
        raw_text=raw_text,
    )
