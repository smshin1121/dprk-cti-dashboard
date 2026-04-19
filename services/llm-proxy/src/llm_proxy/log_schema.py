"""Structured log schema — PR #18 Group A (plan D8 LOCKED).

Load-bearing module for the "no raw text in logs" invariant.
``embedding.generate`` log lines MUST only carry fields from
``ALLOWED_LOG_FIELDS``. Any attempt to emit a forbidden field
(``text``, ``texts``, ``input``, ``prompt``, ``content``, etc.)
raises at call time — a careless future edit that adds
``payload=req.texts`` to a log call breaks here, NOT in production.

Two layers of protection (both locked at commit time):

  1. **Logger layer** (this module): ``validate_log_fields``
     rejects forbidden field names at the helper boundary. Route
     code calls ``make_log_extra(...)`` which type-narrows to the
     safe subset.

  2. **Test layer** (Group D integration): a sentinel-canary
     string in request ``texts`` is asserted to NOT appear in
     captured log output, catching any emit path that bypasses
     the helper.

Both must hold simultaneously — defense in depth. Attempting to
log a forbidden field raises in dev / test / prod alike.
"""

from __future__ import annotations

from typing import Any, Mapping

ALLOWED_LOG_FIELDS: frozenset[str] = frozenset(
    {
        # Event identity
        "event",
        # Provider + model observability
        "provider",
        "model_requested",
        "model_returned",
        # Aggregated counts (NO per-text content)
        "n_texts",
        "total_text_chars",
        "cache_hits_count",
        "cache_misses_count",
        # Timing
        "upstream_latency_ms",
        "total_latency_ms",
        # Ops signals
        "redis_ok",
        "rate_limited",
        "error",
        "upstream_status",
        "timeout_seconds",
        "retry_after_seconds",
        # Generic infra telemetry already emitted by cache.py /
        # rate_limit.py (kept here so the allowlist is exhaustive
        # across the whole service).
        "app_env",
        "storage_scheme",
        "limit",
    }
)
"""Fields permitted in structured log records.

Exhaustive — NOT an open-ended allowlist. Adding a field means
explicitly widening the set here, which forces a reviewer to
confirm the addition carries no raw user content.
"""

FORBIDDEN_LOG_FIELDS: frozenset[str] = frozenset(
    {
        # Direct raw-text names
        "text",
        "texts",
        "input",
        "inputs",
        "prompt",
        "prompts",
        "content",
        "body",
        "raw",
        "query",
        "q",
        "payload",
        # Request / response shells (usually carry raw text)
        "request",
        "response",
        # Individual embedding vectors are 1536-dim arrays — never
        # log them; they're reconstructable back to semantic content
        # in principle and they blow up log line size.
        "embedding",
        "embeddings",
        "vector",
        "vectors",
    }
)
"""Field names explicitly forbidden.

Subset check runs before the allowlist check — a forbidden field
raises a more specific error message than an unknown-field rejection.
"""


def validate_log_fields(fields: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` if ``fields`` contains a forbidden or
    unknown key.

    Called by ``make_log_extra`` at emit time. Tests also call it
    directly to pin the allowlist / forbidden-list invariants.
    """
    names = set(fields.keys())

    forbidden = names & FORBIDDEN_LOG_FIELDS
    if forbidden:
        raise ValueError(
            f"Forbidden log fields (raw user content must NEVER be "
            f"logged; see D8 in docs/plans/pr18-llm-proxy-embedding.md): "
            f"{sorted(forbidden)}"
        )

    unknown = names - ALLOWED_LOG_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown log fields (add to ALLOWED_LOG_FIELDS in "
            f"log_schema.py only if the new field carries NO raw "
            f"user content): {sorted(unknown)}"
        )


def make_log_extra(**fields: Any) -> dict[str, Any]:
    """Return a validated ``extra=`` dict for ``logger.info(...)``.

    Convenience wrapper: the route call site writes
    ``logger.info("embedding.generate", extra=make_log_extra(...))``
    and gets a clear, early failure on any forbidden / unknown
    field — before the LogRecord object reaches the handler.
    """
    validate_log_fields(fields)
    return dict(fields)
