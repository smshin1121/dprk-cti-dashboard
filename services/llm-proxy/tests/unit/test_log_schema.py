"""Unit tests for ``llm_proxy.log_schema`` — PR #18 Group A.

Review criterion #4 pinned at the logger layer: raw-text field
names are structurally forbidden from every log record. A forbidden
field raises at helper call time — a careless future edit that adds
``payload=req.texts`` to a log call surfaces here, not in production.

The test layer of criterion #4 (sentinel-canary in request body
must not appear in captured log output) lives in the Group D
integration suite — this test covers the logger-config layer.
"""

from __future__ import annotations

import pytest

from llm_proxy.log_schema import (
    ALLOWED_LOG_FIELDS,
    FORBIDDEN_LOG_FIELDS,
    make_log_extra,
    validate_log_fields,
)


# ---------------------------------------------------------------------------
# Criterion #4 — logger-layer raw-text lock
# ---------------------------------------------------------------------------


class TestForbiddenFieldsAreRejected:
    """Every forbidden-list entry must trigger a raise."""

    @pytest.mark.parametrize(
        "forbidden_field",
        sorted(FORBIDDEN_LOG_FIELDS),
    )
    def test_forbidden_field_raises(self, forbidden_field: str) -> None:
        with pytest.raises(ValueError, match="[Ff]orbidden log fields"):
            validate_log_fields({forbidden_field: "any value"})

    def test_error_message_mentions_the_field(self) -> None:
        with pytest.raises(ValueError, match="text") as exc_info:
            validate_log_fields({"text": "leaking raw content"})
        # Error surface must make it easy to find the offending
        # call-site during debugging.
        assert "text" in str(exc_info.value)

    def test_error_message_points_to_plan_doc(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            validate_log_fields({"texts": "bad"})
        assert "D8" in str(exc_info.value)


class TestForbiddenListContainsKnownRawFields:
    """Regression guard — if someone removes a raw-text field name
    from FORBIDDEN_LOG_FIELDS, this test explodes."""

    @pytest.mark.parametrize(
        "field",
        # Not parametrized against the constant — enumerated
        # explicitly so a future edit that shrinks the constant
        # can't make this test pass vacuously.
        [
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
            "request",
            "response",
            "embedding",
            "embeddings",
            "vector",
            "vectors",
        ],
    )
    def test_field_is_forbidden(self, field: str) -> None:
        assert field in FORBIDDEN_LOG_FIELDS


class TestAllowedFieldsPass:
    """Every allowed field name validates without raising."""

    @pytest.mark.parametrize("allowed_field", sorted(ALLOWED_LOG_FIELDS))
    def test_allowed_field_passes(self, allowed_field: str) -> None:
        # Should not raise.
        validate_log_fields({allowed_field: "any value"})

    def test_full_legitimate_log_record_passes(self) -> None:
        """Shape of an actual ``embedding.generate`` log record."""
        validate_log_fields(
            {
                "event": "embedding.generate",
                "provider": "openai",
                "model_requested": "text-embedding-3-small",
                "model_returned": "text-embedding-3-small",
                "n_texts": 3,
                "total_text_chars": 142,
                "cache_hits_count": 1,
                "cache_misses_count": 2,
                "upstream_latency_ms": 87,
                "total_latency_ms": 95,
                "redis_ok": True,
                "rate_limited": False,
            }
        )


class TestUnknownFieldsAreRejected:
    """Opt-in allowlist — not a blocklist. Any field not in
    ALLOWED_LOG_FIELDS and not in FORBIDDEN_LOG_FIELDS still raises.
    """

    def test_unknown_field_raises(self) -> None:
        with pytest.raises(ValueError, match="[Uu]nknown log fields"):
            validate_log_fields({"some_future_metric": 42})

    def test_error_suggests_widening_allowlist(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            validate_log_fields({"new_thing": "x"})
        assert "ALLOWED_LOG_FIELDS" in str(exc_info.value)


class TestMakeLogExtraHelper:
    """The helper route code will use must reject bad fields
    identically to the underlying validator."""

    def test_forbidden_field_via_kwargs_raises(self) -> None:
        with pytest.raises(ValueError, match="[Ff]orbidden"):
            make_log_extra(texts="oops")

    def test_allowed_kwargs_returns_dict(self) -> None:
        extra = make_log_extra(
            event="embedding.generate",
            provider="mock",
            n_texts=1,
        )
        assert extra == {
            "event": "embedding.generate",
            "provider": "mock",
            "n_texts": 1,
        }

    def test_allowed_and_forbidden_mixed_raises(self) -> None:
        """Forbidden fields take precedence over allowed ones when
        mixed — the error message must call out the forbidden one
        specifically."""
        with pytest.raises(ValueError, match="[Ff]orbidden"):
            make_log_extra(event="x", texts="oops")


class TestAllowedAndForbiddenAreDisjoint:
    """Sanity — a field cannot be both on the allowlist and the
    forbidden list simultaneously."""

    def test_no_overlap(self) -> None:
        overlap = ALLOWED_LOG_FIELDS & FORBIDDEN_LOG_FIELDS
        assert overlap == set(), (
            f"ALLOWED_LOG_FIELDS and FORBIDDEN_LOG_FIELDS overlap "
            f"on {overlap} — the semantics become ambiguous"
        )
