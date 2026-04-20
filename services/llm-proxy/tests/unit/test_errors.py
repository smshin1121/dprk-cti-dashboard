"""Unit tests for ``llm_proxy.errors`` — PR #18 Group A.

Locks D7 Draft v2 error taxonomy: every exception carries the
correct HTTP status + retryable bit. Groups C/D wire this up to
the route; this test pins the surface those handlers depend on.
"""

from __future__ import annotations

import pytest

from llm_proxy.errors import (
    ConfigurationError,
    InvalidInputError,
    LlmProxyError,
    UpstreamError,
    UpstreamRateLimitError,
    UpstreamTimeoutError,
)


class TestUpstreamErrorIs502:
    def test_status_code_502(self) -> None:
        err = UpstreamError(upstream_status=503)
        assert err.status_code == 502

    def test_retryable_true(self) -> None:
        assert UpstreamError(upstream_status=502).retryable is True

    def test_carries_upstream_status(self) -> None:
        err = UpstreamError(upstream_status=504)
        assert err.upstream_status == 504

    def test_is_llm_proxy_error(self) -> None:
        # Base-class catch must work.
        with pytest.raises(LlmProxyError):
            raise UpstreamError(upstream_status=500)


class TestUpstreamTimeoutErrorIs504:
    """504 split from 502 per D7 Draft v2 — callers differentiate
    'server failed to respond' from 'server too slow'."""

    def test_status_code_504(self) -> None:
        err = UpstreamTimeoutError(timeout_seconds=10.0)
        assert err.status_code == 504

    def test_distinct_from_upstream_error(self) -> None:
        """Distinct type AND distinct status — callers should be
        able to catch either separately."""
        assert UpstreamTimeoutError(timeout_seconds=10).status_code != UpstreamError(
            upstream_status=500
        ).status_code

    def test_retryable_true(self) -> None:
        assert UpstreamTimeoutError(timeout_seconds=5).retryable is True

    def test_carries_timeout_seconds(self) -> None:
        err = UpstreamTimeoutError(timeout_seconds=7.5)
        assert err.timeout_seconds == 7.5


class TestUpstreamRateLimitErrorIs429:
    def test_status_code_429(self) -> None:
        assert UpstreamRateLimitError().status_code == 429

    def test_retry_after_seconds_optional(self) -> None:
        assert UpstreamRateLimitError().retry_after_seconds is None
        assert UpstreamRateLimitError(retry_after_seconds=30).retry_after_seconds == 30

    def test_retryable_true(self) -> None:
        assert UpstreamRateLimitError().retryable is True


class TestInvalidInputErrorIs422:
    def test_status_code_422(self) -> None:
        assert InvalidInputError(detail="texts must not be empty").status_code == 422

    def test_retryable_false(self) -> None:
        """Client-side error — same exact input will fail again."""
        assert InvalidInputError(detail="").retryable is False

    def test_detail_is_human_readable(self) -> None:
        err = InvalidInputError(detail="texts[0] is whitespace-only")
        assert "whitespace-only" in err.detail


class TestConfigurationErrorIs503:
    def test_status_code_503(self) -> None:
        assert ConfigurationError(detail="missing API key").status_code == 503

    def test_retryable_false(self) -> None:
        """Config errors don't resolve by retrying — they resolve by
        fixing config."""
        assert ConfigurationError(detail="").retryable is False
