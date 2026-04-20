"""Error taxonomy for llm-proxy — PR #18 Group A (plan D7 Draft v2).

Callers need to differentiate "upstream failed to respond" from
"upstream too slow" from "upstream rate-limited" in their retry
logic, so each branch carries a distinct HTTP status AND a distinct
body shape. The router / exception-handler wiring lives in Group C;
this module defines the exception surface those handlers map from.

  UpstreamError              → 502 Bad Gateway
  UpstreamTimeoutError       → 504 Gateway Timeout
  UpstreamRateLimitError     → 429 Too Many Requests (bubbled)
  InvalidInputError          → 422 Unprocessable Entity
  ConfigurationError         → 503 Service Unavailable (at startup
                               boot fails; at runtime a 503 with a
                               minimal body)

No automatic retry lives inside the proxy (plan D7). Callers own
their retry budget.
"""

from __future__ import annotations

from dataclasses import dataclass


class LlmProxyError(Exception):
    """Base class — makes `except LlmProxyError` a safe catch-all."""

    status_code: int = 500
    """HTTP status the exception handler should return."""

    retryable: bool = False
    """Whether callers should consider retrying after a backoff."""


@dataclass
class UpstreamError(LlmProxyError):
    """Upstream provider returned a 5xx (server-side failure).

    Distinct from ``UpstreamTimeoutError`` — here the upstream DID
    respond, just with a failure status. Callers should consider
    provider-side outage handling (fallback provider, shed load).
    """

    upstream_status: int
    detail: str = "upstream error"
    status_code: int = 502
    retryable: bool = True

    def __post_init__(self) -> None:
        LlmProxyError.__init__(self, self.detail)


@dataclass
class UpstreamTimeoutError(LlmProxyError):
    """Local httpx client-side deadline hit; upstream never responded.

    Distinct from ``UpstreamError`` (which means the upstream DID
    respond but with 5xx). Callers seeing 504 repeatedly should
    either extend their own timeout budget or shed load upstream of
    this call.
    """

    timeout_seconds: float
    detail: str = "upstream timeout"
    status_code: int = 504
    retryable: bool = True

    def __post_init__(self) -> None:
        LlmProxyError.__init__(self, self.detail)


@dataclass
class UpstreamRateLimitError(LlmProxyError):
    """Upstream provider rate-limited us (429 bubbled through).

    Carries ``retry_after_seconds`` when the upstream response
    included a ``Retry-After`` header. Callers should honor it.
    """

    retry_after_seconds: int | None = None
    upstream_status: int = 429
    detail: str = "upstream rate limit"
    status_code: int = 429
    retryable: bool = True

    def __post_init__(self) -> None:
        LlmProxyError.__init__(self, self.detail)


@dataclass
class InvalidInputError(LlmProxyError):
    """Caller-side input violated the request contract.

    Empty texts list, empty / whitespace-only string within texts,
    batch > max_batch, null fields, etc. All 422. Mirrors the
    services/api D12 uniform-422 posture.
    """

    detail: str
    status_code: int = 422
    retryable: bool = False

    def __post_init__(self) -> None:
        LlmProxyError.__init__(self, self.detail)


@dataclass
class ConfigurationError(LlmProxyError):
    """Service configuration is incomplete at runtime.

    Raised when the router detects a config state the startup
    validators let through (should not happen — startup validators
    catch the missing-API-key and mock-in-prod cases). Runtime
    surfacing is 503.
    """

    detail: str
    status_code: int = 503
    retryable: bool = False

    def __post_init__(self) -> None:
        LlmProxyError.__init__(self, self.detail)
