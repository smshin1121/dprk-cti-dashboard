"""URL canonicalization, title hashing, and tag classification.

Three responsibilities split across this module:

1. **Deterministic identity** for reports
   :func:`canonicalize_url` produces the key used by
   ``reports.url_canonical`` for idempotent upserts, and
   :func:`sha256_title` produces the secondary fingerprint stored in
   ``reports.sha256_title`` so a report whose URL changes after
   publication can still be deduplicated by title.

2. **Tag classification**
   The ``tags`` cell in the v1.0 workbook is a free-form whitespace-
   separated list of hashtags. :func:`classify_tags` turns them into
   typed :class:`ClassifiedTag` records suitable for the ``tags`` +
   ``report_tags`` upsert.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import ParseResult, parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from worker.bootstrap.aliases import AliasDictionary


__all__ = [
    "ClassifiedTag",
    "DEFAULT_SECTOR_CODES",
    "TAG_TYPE_ACTOR",
    "TAG_TYPE_CVE",
    "TAG_TYPE_MALWARE",
    "TAG_TYPE_OPERATION",
    "TAG_TYPE_SECTOR",
    "TAG_TYPE_UNKNOWN",
    "canonicalize_url",
    "classify_tags",
    "sha256_title",
]


# ---------------------------------------------------------------------------
# Tracking-parameter whitelist
# ---------------------------------------------------------------------------
#
# Strip rules are **whitelisted** (only these names are dropped) rather
# than blacklisted (keep only a known-good set). A blacklist approach
# would be tempting but would eventually drop a query param that
# actually changes the response and two semantically distinct URLs
# would collapse to the same canonical. Add a new entry here only when
# the param is known-noise across every vendor that uses it.
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        # Google Analytics / Urchin
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        # Google Ads
        "gclid",
        "dclid",
        "gbraid",
        "wbraid",
        # Facebook
        "fbclid",
        # Mailchimp
        "mc_eid",
        "mc_cid",
        # Instagram
        "igshid",
        # Microsoft / Bing
        "msclkid",
        # Yahoo
        "yclid",
    }
)


# ---------------------------------------------------------------------------
# canonicalize_url
# ---------------------------------------------------------------------------


def _drop_tracking_params(query: str) -> str:
    """Return ``query`` with every tracking parameter removed.

    Parameters are re-serialized in **sorted order** so two URLs that
    differ only in query-param ordering collapse to the same canonical.
    Ordering is deterministic by key + value.
    """
    if not query:
        return ""
    kept: list[tuple[str, str]] = [
        (k, v) for k, v in parse_qsl(query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    if not kept:
        return ""
    kept.sort()
    return urlencode(kept, doseq=False)


def _normalize_path(path: str) -> str:
    """Collapse adjacent slashes, drop a single trailing slash (except root).

    Path casing is preserved — many origins serve case-sensitive paths.
    """
    if not path:
        return "/"
    # Collapse double slashes without touching the leading one.
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # Re-encode any already-decoded characters so the canonical form is
    # a valid URL path. ``unquote`` → ``quote`` round-trip ensures that
    # ``%2F`` and ``/`` do not both appear in the output.
    return quote(unquote(path), safe="/-._~!$&'()*+,;=:@")


def canonicalize_url(url: str) -> str:
    """Return the canonical form of ``url`` suitable for dedupe keys.

    Rules:
      - scheme and host lowercased
      - default ports (``:80``/``:443``) dropped
      - path collapsed, re-encoded, trailing slash dropped
      - tracking params (see ``_TRACKING_PARAMS``) removed
      - remaining query params sorted for ordering stability
      - fragment dropped (client-side only; never affects origin)
      - surrounding whitespace stripped

    Raises ``ValueError`` if the scheme is missing or not http(s).
    """
    if url is None:
        raise ValueError("url is required")
    trimmed = url.strip()
    if not trimmed:
        raise ValueError("url must be non-empty")

    parts: ParseResult | tuple = urlsplit(trimmed)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(
            f"url scheme must be http or https; got {parts.scheme!r} in {url!r}"
        )

    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"url must have a host; got {url!r}")

    # Drop default ports.
    port = parts.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    # Strip userinfo — unusual in feed data but would defeat dedupe.
    path = _normalize_path(parts.path)
    query = _drop_tracking_params(parts.query)

    return urlunsplit((scheme, netloc, path, query, ""))


# ---------------------------------------------------------------------------
# sha256_title
# ---------------------------------------------------------------------------

_WHITESPACE_RUN = re.compile(r"\s+", re.UNICODE)


def sha256_title(title: str) -> str:
    """Return a stable SHA-256 fingerprint of ``title``.

    The input is normalized before hashing so that titles that differ
    only in casing or whitespace collapse to the same digest:

      - strip surrounding whitespace
      - casefold (stronger than ``lower`` for Unicode)
      - collapse internal whitespace runs to a single space

    Returns a 64-char lowercase hex digest.
    Raises ``ValueError`` on an empty or whitespace-only title.
    """
    if title is None:
        raise ValueError("title is required")
    trimmed = title.strip()
    if not trimmed:
        raise ValueError("title must be non-empty")
    collapsed = _WHITESPACE_RUN.sub(" ", trimmed)
    normalized = collapsed.casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# classify_tags
# ---------------------------------------------------------------------------
#
# Precedence order (most specific first):
#   1. CVE   — strict regex ``cve-YYYY-N{4,7}`` is unambiguous.
#   2. actor — any groups-type canonical in the alias dictionary.
#   3. malware — any malware-type canonical in the alias dictionary.
#   4. operation — any campaigns-type canonical in the alias dictionary.
#   5. sector — any entry in the sector-code set.
#   6. unknown_type — fallback, preserves the raw tag for later LLM
#      cleanup rather than silently dropping.
#
# The classifier never raises; unparseable input becomes a zero-length
# list so a report with no tags is indistinguishable from a report with
# a ``None`` tags cell.

TAG_TYPE_ACTOR = "actor"
TAG_TYPE_MALWARE = "malware"
TAG_TYPE_CVE = "cve"
TAG_TYPE_OPERATION = "operation"
TAG_TYPE_SECTOR = "sector"
TAG_TYPE_UNKNOWN = "unknown_type"


# Sector vocabulary. Kept small and stable; expand only when a new
# sector shows up in real data AND the dashboard's sector filter learns
# to render it.
DEFAULT_SECTOR_CODES: frozenset[str] = frozenset(
    {
        "crypto",
        "finance",
        "healthcare",
        "defense",
        "energy",
        "government",
        "media",
        "technology",
        "telecom",
        "transportation",
        "retail",
        "manufacturing",
        "education",
        "critical_infrastructure",
    }
)


_CVE_PATTERN = re.compile(r"^cve-(\d{4})-(\d{4,7})$", re.IGNORECASE)
_TAG_TOKEN_PATTERN = re.compile(r"#[^\s#]+")


@dataclass(frozen=True)
class ClassifiedTag:
    """One tag parsed out of a workbook ``tags`` cell.

    Attributes:
      raw: the original token with the leading ``#`` stripped, but
           otherwise untouched (case, punctuation). Suitable for
           storage in ``tags.name`` when type is ``unknown_type``.
      type_: one of the ``TAG_TYPE_*`` constants.
      canonical: the canonical form resolved from the alias dictionary
           or the sector set. ``None`` when type is ``unknown_type``.
           For CVE tags, always uppercased ``CVE-YYYY-N``.
    """

    raw: str
    type_: str
    canonical: str | None


def _classify_single(
    token: str,
    aliases: AliasDictionary,
    sector_codes: frozenset[str],
) -> ClassifiedTag:
    """Resolve one already-stripped token (no leading ``#``)."""

    # 1. CVE — unambiguous format match.
    cve_match = _CVE_PATTERN.match(token)
    if cve_match:
        year, number = cve_match.groups()
        return ClassifiedTag(
            raw=token,
            type_=TAG_TYPE_CVE,
            canonical=f"CVE-{year}-{number}",
        )

    # 2–4. Alias-dictionary lookups. Order matters when a single tag
    # legitimately resolves under multiple types (rare in practice but
    # possible). Groups before malware before campaigns is an editorial
    # choice — actor attribution is the load-bearing dimension.
    for tag_type, alias_type in (
        (TAG_TYPE_ACTOR, "groups"),
        (TAG_TYPE_MALWARE, "malware"),
        (TAG_TYPE_OPERATION, "campaigns"),
    ):
        canonical = aliases.normalize(alias_type, token)
        if canonical is not None:
            return ClassifiedTag(raw=token, type_=tag_type, canonical=canonical)

    # 5. Sector vocabulary.
    lowered = token.lower()
    if lowered in sector_codes:
        return ClassifiedTag(
            raw=token,
            type_=TAG_TYPE_SECTOR,
            canonical=lowered,
        )

    # 6. Fallback — preserve the raw token so upstream audit can see
    # what the pipeline rejected.
    return ClassifiedTag(raw=token, type_=TAG_TYPE_UNKNOWN, canonical=None)


def classify_tags(
    tags_cell: str | None,
    aliases: AliasDictionary,
    *,
    sector_codes: frozenset[str] = DEFAULT_SECTOR_CODES,
) -> list[ClassifiedTag]:
    """Parse ``tags_cell`` and classify each ``#``-prefixed token.

    Accepts ``None`` or an empty string (returns ``[]``). A cell that
    contains no ``#`` tokens at all returns ``[]`` — this is the
    "no-parseable-tags" failure case in the fixture and is surfaced at
    the pipeline level, not here.

    Tokens are split on any whitespace OR any subsequent ``#``. This
    means ``"#a#b"`` and ``"#a #b"`` both produce two tags, which
    matches how the v1.0 workbook author entered them in practice.
    """
    if not tags_cell:
        return []

    matches: Iterable[str] = _TAG_TOKEN_PATTERN.findall(tags_cell)
    results: list[ClassifiedTag] = []
    for match in matches:
        stripped = match[1:]  # drop leading '#'
        if not stripped:
            continue
        results.append(_classify_single(stripped, aliases, sector_codes))
    return results
