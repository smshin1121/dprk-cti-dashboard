"""URL canonicalization, title hashing, and tag classification.

Two responsibilities split across this module:

1. **Deterministic identity** for reports
   :func:`canonicalize_url` produces the key used by
   ``reports.url_canonical`` for idempotent upserts, and
   :func:`sha256_title` produces the secondary fingerprint stored in
   ``reports.sha256_title`` so a report whose URL changes after
   publication can still be deduplicated by title.

2. **Tag classification** (T5 — lands in the next commit)
   The ``tags`` cell in the v1.0 workbook is a free-form whitespace-
   separated list of hashtags. :func:`classify_tags` turns them into
   typed ``(type, canonical_name)`` tuples.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Sequence
from urllib.parse import ParseResult, parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit


__all__ = [
    "canonicalize_url",
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
