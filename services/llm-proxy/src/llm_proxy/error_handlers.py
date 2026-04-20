"""D7 / D5 exception handlers for llm-proxy — PR #18 Group C.

Each domain exception maps to a **distinct HTTP status AND a
distinct body shape** so callers can branch their retry logic on
type alone (no string sniffing). The mapping mirrors D7 Draft v2
in ``docs/plans/pr18-llm-proxy-embedding.md``:

  UpstreamError              → 502 Bad Gateway
  UpstreamTimeoutError       → 504 Gateway Timeout
  UpstreamRateLimitError     → 429 Too Many Requests (bubbled)
  InvalidInputError          → 422 Unprocessable Entity
  ConfigurationError         → 503 Service Unavailable
  slowapi RateLimitExceeded  → 429 Too Many Requests (local bucket)

Every handler logs via ``make_log_extra`` — the schema validator
rejects any forbidden field at call time, so no raw text / payload
can reach a log line even through an error path (D8 LOCKED).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from .config import get_settings
from .errors import (
    ConfigurationError,
    InvalidInputError,
    UpstreamError,
    UpstreamRateLimitError,
    UpstreamTimeoutError,
)
from .log_schema import make_log_extra

logger = logging.getLogger(__name__)


async def upstream_error_handler(
    request: Request, exc: UpstreamError
) -> JSONResponse:
    """Upstream provider returned 5xx (or an otherwise unrecoverable
    response). D7: 502 Bad Gateway."""
    logger.warning(
        "embedding.error.upstream",
        extra=make_log_extra(
            event="embedding.error.upstream",
            error=type(exc).__name__,
            upstream_status=exc.upstream_status,
        ),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "upstream_status": exc.upstream_status,
            "retryable": exc.retryable,
        },
    )


async def upstream_timeout_handler(
    request: Request, exc: UpstreamTimeoutError
) -> JSONResponse:
    """Local httpx deadline hit before upstream responded.
    D7: 504 Gateway Timeout — distinct from 502 so callers can tell
    "server never responded" from "server failed"."""
    logger.warning(
        "embedding.error.timeout",
        extra=make_log_extra(
            event="embedding.error.timeout",
            error=type(exc).__name__,
            timeout_seconds=exc.timeout_seconds,
        ),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "timeout_seconds": exc.timeout_seconds,
            "retryable": exc.retryable,
        },
    )


async def upstream_rate_limit_handler(
    request: Request, exc: UpstreamRateLimitError
) -> JSONResponse:
    """Upstream returned 429 — bubble through with Retry-After when
    the provider included one."""
    log_fields: dict[str, Any] = {
        "event": "embedding.error.upstream_rate_limited",
        "error": type(exc).__name__,
        "upstream_status": exc.upstream_status,
    }
    if exc.retry_after_seconds is not None:
        log_fields["retry_after_seconds"] = exc.retry_after_seconds
    logger.warning(
        "embedding.error.upstream_rate_limited",
        extra=make_log_extra(**log_fields),
    )

    body: dict[str, Any] = {
        "detail": exc.detail,
        "upstream_status": exc.upstream_status,
        "retryable": exc.retryable,
    }
    headers: dict[str, str] = {}
    if exc.retry_after_seconds is not None:
        body["retry_after_seconds"] = exc.retry_after_seconds
        headers["Retry-After"] = str(exc.retry_after_seconds)

    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=headers or None,
    )


async def invalid_input_handler(
    request: Request, exc: InvalidInputError
) -> JSONResponse:
    """Caller-side contract violation (empty texts, batch > max,
    etc.). D7: 422 Unprocessable Entity."""
    logger.info(
        "embedding.error.invalid_input",
        extra=make_log_extra(
            event="embedding.error.invalid_input",
            error=type(exc).__name__,
        ),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "retryable": exc.retryable,
        },
    )


async def configuration_error_handler(
    request: Request, exc: ConfigurationError
) -> JSONResponse:
    """Runtime configuration gap (should not happen — startup
    validators catch the expected cases). D7: 503 Service Unavailable."""
    logger.error(
        "embedding.error.configuration",
        extra=make_log_extra(
            event="embedding.error.configuration",
            error=type(exc).__name__,
        ),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "retryable": exc.retryable,
        },
    )


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """slowapi local bucket exhausted. D5 Draft v2: locked body shape
    ``{error, message, retry_after_seconds}`` + ``Retry-After`` header.

    Distinct from :func:`upstream_rate_limit_handler` — this fires
    when our own 30/minute bucket drains, not when the upstream
    rate-limited us. Body shape differs on purpose so callers can
    tell the two apart."""
    detail_str = str(exc.detail) if getattr(exc, "detail", None) else ""
    limit_expression = get_settings().llm_proxy_embedding_rate_limit
    message = detail_str or limit_expression

    retry_after = _compute_retry_after_seconds(request, limit_expression)

    logger.warning(
        "embedding.error.rate_limited",
        extra=make_log_extra(
            event="embedding.error.rate_limited",
            rate_limited=True,
            retry_after_seconds=retry_after,
        ),
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": message,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


def _compute_retry_after_seconds(request: Request, limit_expression: str) -> int:
    """Best-effort Retry-After in seconds.

    Prefers slowapi's ``view_rate_limit`` window-stats when
    available — that gives the actual bucket reset. Falls back to a
    conservative value derived from the limit expression's unit
    (e.g. ``30/minute`` → 60s) when slowapi has not populated
    ``request.state.view_rate_limit`` (header injection is disabled
    on the limiter, so the attribute is sometimes absent on the
    error path).

    Never raises — the handler must always produce a 429 or the
    client sees a 500 for a rate-limit event, which is worse than
    a slightly-off Retry-After value.
    """
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit is not None:
        try:
            limit_item, key = view_limit
            stats = request.app.state.limiter.limiter.get_window_stats(
                limit_item, *key
            )
            now = int(time.time())
            return max(1, int(stats.reset_time) - now)
        except Exception:  # pragma: no cover - defensive
            logger.warning(
                "embedding.error.rate_limit_header_degraded",
                extra=make_log_extra(
                    event="embedding.error.rate_limit_header_degraded",
                    rate_limited=True,
                ),
            )

    return _fallback_retry_after(limit_expression)


def _fallback_retry_after(limit_expression: str) -> int:
    """Derive a coarse Retry-After seconds from a slowapi expression.

    ``30/minute`` → 60 (one full window).  Unparseable → 60.
    """
    try:
        _, unit = limit_expression.strip().split("/", 1)
        unit = unit.strip().lower()
    except (ValueError, AttributeError):
        return 60
    if unit.startswith("second"):
        return 1
    if unit.startswith("minute"):
        return 60
    if unit.startswith("hour"):
        return 3600
    if unit.startswith("day"):
        return 86400
    return 60


def register_exception_handlers(app: FastAPI) -> None:
    """Register every domain → HTTP mapping on ``app``.

    Called once from ``main.py`` at import time. Keeps ``main.py``
    focused on app construction and routing — the error surface
    lives in one dedicated module.
    """
    app.add_exception_handler(UpstreamError, upstream_error_handler)
    app.add_exception_handler(UpstreamTimeoutError, upstream_timeout_handler)
    app.add_exception_handler(UpstreamRateLimitError, upstream_rate_limit_handler)
    app.add_exception_handler(InvalidInputError, invalid_input_handler)
    app.add_exception_handler(ConfigurationError, configuration_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


__all__ = [
    "configuration_error_handler",
    "invalid_input_handler",
    "rate_limit_exceeded_handler",
    "register_exception_handlers",
    "upstream_error_handler",
    "upstream_rate_limit_handler",
    "upstream_timeout_handler",
]
