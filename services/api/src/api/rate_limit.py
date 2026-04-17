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
  at request time, slowapi's own Redis driver raises and the
  exception handler returns 503 (see ``handle_storage_unavailable``).
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
from functools import lru_cache

from fastapi import Request
from slowapi import Limiter
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
        headers_enabled=True,  # X-RateLimit-Remaining / Retry-After
    )


@lru_cache(maxsize=1)
def get_limiter() -> Limiter:
    """Cached accessor matching the ``get_settings`` pattern.

    ``main.py`` wires ``app.state.limiter`` to this at import time.
    Tests can ``get_limiter.cache_clear()`` between runs if they
    need a fresh instance under a mutated env.
    """
    return build_limiter()


__all__ = [
    "build_limiter",
    "get_limiter",
    "session_or_ip_key",
]
