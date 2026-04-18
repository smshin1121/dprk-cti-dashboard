"""slowapi + Redis rate-limit infrastructure (PR #11 Group F).

Plan §2.1 D1/D2 lock the wire-format contract (60/min/user on read,
30/min/user on mutation, 10/min/IP on auth endpoints, 429 + headers)
and D8 locks the observability path (structured log only — no
audit_log, no dedicated table). The actual decoration of routes with
``@limiter.limit(...)`` lives in Groups G (existing routers) and H
(new PR #11 read routers); this module lands the infrastructure
they consume.

**Environment-policy lock (Group F reviewer priority).**

The rate-limit backend is picked at process start based on
``APP_ENV`` and ``RATE_LIMIT_STORAGE_URL``. The three environments
have DIFFERENT, non-overlapping policies — CI stability depends on
test + dev never silently inheriting the prod enforcement path:

- **prod** — fail-closed. Startup raises ``ValueError`` unless the
  storage URL begins with ``redis://`` (or ``rediss://``). A
  non-Redis backend means rate-limit state is per-process, which is
  operationally equivalent to "no rate limit" when the API runs
  behind a load balancer. Per plan §9.2 STRIDE "DoS" mitigation,
  prod cannot ship without it. When Redis is genuinely unreachable
  at request time, slowapi's Redis driver raises
  ``redis.exceptions.ConnectionError`` / ``TimeoutError`` (or
  ``limits.errors.StorageError`` if wrapped upstream); the
  exception handler ``handle_storage_unavailable`` converts those
  to HTTP 503 JSON so the client gets a typed, non-500 error and
  ops tooling can page on the storage dependency cleanly. The
  handler is registered in ``main.py`` alongside the
  ``RateLimitExceeded`` → 429 one.
- **test** — forced to ``memory://`` regardless of what the env
  variable says. The goal is deterministic window semantics in CI
  without an external Redis container. ``RATE_LIMIT_STORAGE_URL``
  in the test env can be left unset; this module overrides it.
- **dev** — honors ``RATE_LIMIT_STORAGE_URL`` verbatim. Empty / unset
  falls back to ``redis_url`` (the same Redis that already backs
  sessions), so a local ``docker compose up`` gives rate-limit
  against real Redis without extra config. A developer can also set
  ``RATE_LIMIT_STORAGE_URL=memory://`` for fast local iteration.

The policy table lives in :func:`_resolve_storage_uri` — any future
env gets a new branch, never a fallthrough.

**Key function.**

``slowapi``'s ``key_func`` is synchronous and receives a bare
``Request`` — it cannot ``await`` a Redis lookup or hit the SQL
session. Plan D2 says "authenticated = ``CurrentUser.sub``", but the
only thing available at middleware time is the signed session cookie
value. We use a stable **prefix of that cookie** as the user's key:

- Same authenticated user → same signed cookie → same rate-limit key
- A rotated session cookie creates a fresh bucket (acceptable — user
  had to re-authenticate)
- No cookie → falls back to client IP (``get_remote_address``)

This is equivalent to a ``sub``-based key in effect, without the
sync/async impedance mismatch of decoding the cookie inside a
non-async key_func. Tested in ``test_rate_limit.py``.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

from fastapi import Request
from fastapi.responses import JSONResponse
from limits.errors import StorageError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


# Key prefix carved off the signed session cookie for the rate-limit
# bucket name. 24 characters is a good trade-off:
#   - short enough to keep Redis key size predictable
#   - long enough that two users' cookies never collide in practice
#     (the URLSafeTimedSerializer body is base64url, so 24 chars =
#     ~144 bits of entropy from the signer payload)
_COOKIE_KEY_PREFIX_LEN = 24


def session_or_ip_key(request: Request) -> str:
    """slowapi key function — plan D2 user/IP split.

    Uses the session cookie's first ``_COOKIE_KEY_PREFIX_LEN`` chars
    as a stable per-user key, falling back to the client IP when
    the cookie is absent (anonymous endpoints like ``/auth/login``
    and ``/auth/callback``).

    Sync-only — slowapi middleware runs before FastAPI dependencies,
    so the cookie is the only thing we can see without an async
    lookup. See module docstring for why this is equivalent to a
    sub-based key in practice.
    """
    settings = get_settings()
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        return f"session:{cookie[:_COOKIE_KEY_PREFIX_LEN]}"
    return f"ip:{get_remote_address(request)}"


def _resolve_storage_uri(settings: Settings) -> str:
    """Return the slowapi storage URI for the current environment.

    Policy branches are explicit — no fallthrough — so a future env
    (staging, preview, etc.) is forced to declare its posture rather
    than silently inheriting prod's fail-closed or test's in-memory.
    """
    raw = (settings.rate_limit_storage_url or "").strip()

    if settings.app_env == "test":
        # Forced regardless of the env value. CI stability lock.
        return "memory://"

    if settings.app_env == "dev":
        if raw:
            return raw
        # Fall back to the same Redis that serves sessions so the
        # dev compose stack does not need a second broker.
        return settings.redis_url

    # prod / anything non-test / non-dev: fail-closed on non-Redis.
    if not raw.startswith(("redis://", "rediss://")):
        raise ValueError(
            "RATE_LIMIT_STORAGE_URL must be a redis:// or rediss:// URL "
            f"in app_env={settings.app_env!r}; got {raw!r}. Rate limiting "
            "cannot fail-closed without Redis — refusing to start."
        )
    return raw


def build_limiter(settings: Settings | None = None) -> Limiter:
    """Construct the slowapi ``Limiter`` for this process.

    Called once by ``main.py`` at import time. Unit tests call this
    directly with a stubbed ``Settings`` to exercise each env branch
    without toggling the real process env.

    When ``rate_limit_enabled`` is False, returns a Limiter with
    ``enabled=False`` so decorators attach cleanly but do not fire.
    Lets operators toggle rate-limit off in an incident without
    redeploying the code.
    """
    settings = settings or get_settings()
    storage_uri = _resolve_storage_uri(settings)
    logger.info(
        "rate_limit.build",
        extra={
            "app_env": settings.app_env,
            "storage": storage_uri.split("://", 1)[0] + "://",
            "enabled": settings.rate_limit_enabled,
        },
    )
    return Limiter(
        key_func=session_or_ip_key,
        storage_uri=storage_uri,
        enabled=settings.rate_limit_enabled,
        default_limits=[],  # No global default — each route opts in.
        # ``headers_enabled=False`` here and manual injection only in
        # the 429 path (see ``rate_limit_exceeded_handler``). Reason:
        # slowapi's success-path header injection requires the handler
        # to return a ``starlette.responses.Response`` subclass, but
        # many of our handlers return Pydantic models and let FastAPI
        # serialize. slowapi would raise on every successful request
        # otherwise. Plan D2 only requires headers on the 429 response
        # anyway ("초과 시 429 + Retry-After + X-RateLimit-Remaining"),
        # so success-path headers are out of scope.
        headers_enabled=False,
    )


@lru_cache(maxsize=1)
def get_limiter() -> Limiter:
    """Cached accessor matching the ``get_settings`` pattern.

    ``main.py`` wires ``app.state.limiter`` to this at import time.
    Tests can ``get_limiter.cache_clear()`` between runs if they
    need a fresh instance under a mutated env.
    """
    return build_limiter()


def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Custom 429 response — JSON body consistently.

    Replaces slowapi's default text response so the contract is the
    same regardless of entry point:

    - **API clients** (JSON consumers) see a structured error body
      they can branch on without parsing free-form strings.
    - **Browser redirect flows** (``/auth/login`` / ``/auth/callback``):
      a redirect-safe plain body was considered (Group G reviewer
      note). Rejected because 429 on those endpoints is already a
      terminal error state — the user cannot continue the OIDC
      flow until the window resets. JSON is rendered as-is by the
      browser, same as any other API error, so no extra handling
      is needed. Keeping one body shape everywhere also lets the
      frontend error interceptor handle 429 uniformly.

    Rate-limit headers (``X-RateLimit-Remaining`` /
    ``X-RateLimit-Limit`` / ``Retry-After``) are injected by
    slowapi's existing ``_inject_headers`` hook — we reuse that so
    the per-route ``@limiter.limit`` metadata still flows through.
    """
    detail_str = str(exc.detail) if exc.detail else "rate limit exceeded"
    response = JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": detail_str,
        },
    )
    # Manual header injection — ``headers_enabled=False`` on the
    # Limiter (see ``build_limiter`` comment). We compute headers
    # here on the 429 path only, which is the only path plan D2
    # requires them on.
    #
    # ``request.state.view_rate_limit`` is the canonical source —
    # a tuple of ``(RateLimitItem, list[key_component])``. Using
    # ``exc.limit`` here is the wrong shape (``Limit`` namedtuple
    # wrapping the RateLimitItem) and raises AttributeError inside
    # limits.strategies.get_window_stats.
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit is not None:
        limit_item, key = view_limit
        try:
            stats = request.app.state.limiter.limiter.get_window_stats(
                limit_item, *key
            )
            now = int(time.time())
            response.headers["Retry-After"] = str(max(1, int(stats.reset_time) - now))
            response.headers["X-RateLimit-Limit"] = str(limit_item.amount)
            response.headers["X-RateLimit-Remaining"] = str(max(0, stats.remaining))
            response.headers["X-RateLimit-Reset"] = str(int(stats.reset_time))
        except Exception:
            # Best-effort — an exception handler must never raise
            # again or the client receives a 500 for a rate-limit
            # situation. Missing headers are a degraded but valid
            # 429 response.
            logger.warning("rate_limit.header_injection_failed", exc_info=True)
    return response


def handle_storage_unavailable(
    request: Request,
    exc: StorageError | RedisConnectionError | RedisTimeoutError,
) -> JSONResponse:
    """Convert rate-limit storage backend failure into HTTP 503 JSON.

    When slowapi's Redis driver cannot reach the storage backend
    (network partition, Redis process down, slow DNS, TLS handshake
    failure), the underlying exception propagates up through the
    decorator wrapper. Without this handler, FastAPI's default
    behavior is to bubble it into a 500 with the stack trace in
    the response — wrong for three reasons:

    - **Semantics.** 500 means "the API is broken". A Redis blip
      means "rate-limit state is temporarily unknown". Clients
      (and upstream gateways) should retry, not mark the API dead.
    - **Observability.** A typed 503 with a stable ``error`` field
      lets ops dashboards alert on the storage dependency separately
      from app bugs.
    - **Security.** Default FastAPI 500 body may leak the exception
      class name / details in dev, which can hint at the storage
      backend topology. The 503 body here is intentionally terse.

    The plan D8 lock says storage-block events should be structured
    logs only; this handler logs a warning for ops visibility but
    does not write an audit row (audit is for domain mutations,
    not operational incidents).
    """
    logger.warning(
        "rate_limit.storage_unavailable",
        extra={
            "exc_type": type(exc).__name__,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": "rate_limit_storage_unavailable",
            "message": (
                "Rate-limit storage backend is temporarily unreachable. "
                "Retry after a short delay."
            ),
        },
        headers={"Retry-After": "5"},
    )


__all__ = [
    "build_limiter",
    "get_limiter",
    "handle_storage_unavailable",
    "rate_limit_exceeded_handler",
    "session_or_ip_key",
]
