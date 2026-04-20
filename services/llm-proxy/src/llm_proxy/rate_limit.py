"""slowapi rate-limit infrastructure — PR #18 Group A (plan D5 Draft v2).

Embedding is a cost-surface endpoint. A runaway caller (bug loop,
retry storm, misconfigured backfill) could burn thousands of OpenAI
dollars in minutes, so a conservative 30/minute ceiling is in place
from day one. The value is configurable via
``LLM_PROXY_EMBEDDING_RATE_LIMIT`` so ops can loosen without a
code change.

Key function: SHA-256 of the ``X-Internal-Token`` header value,
truncated to 16 hex chars. Raw token value never reaches the
slowapi storage key or log line — a leak in either surface would
expose the shared secret.

Storage: same Redis URL as the embedding cache (one connection,
two logical keyspaces). In ``APP_ENV=test`` the storage is forced
to ``memory://`` for deterministic CI behavior — matches the
services/api precedent.
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache

from fastapi import Request
from slowapi import Limiter

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

_TOKEN_KEY_PREFIX_LEN = 16
"""Length of the hashed-token prefix used as the slowapi key.

16 hex chars = 64 bits of entropy. SHA-256 collision at 64 bits is
negligible for our caller cardinality (single-digit principals in
practice), and keeping the key short reduces Redis key size.
"""


def token_principal_key(request: Request) -> str:
    """slowapi key function — SHA-256 prefix of X-Internal-Token.

    Raw token value never appears in the key or the log. Absent
    header → ``anonymous`` sentinel (which the middleware will
    have already rejected with 401 before slowapi runs, so in
    practice this branch is unreachable — included for defense).

    Sync-only because slowapi middleware runs before FastAPI
    dependencies; we inspect the request headers directly.
    """
    token = request.headers.get("X-Internal-Token", "")
    if not token:
        return "anonymous"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"token:{digest[:_TOKEN_KEY_PREFIX_LEN]}"


def _resolve_storage_uri(settings: Settings) -> str:
    """Return the slowapi storage URI for the current environment.

    Explicit branches per env — no fallthrough — so a future env
    (staging, preview) is forced to declare its posture.
    """
    if settings.app_env == "test":
        # Forced in-memory regardless of REDIS_URL — CI determinism
        # + no Redis dependency for unit tests.
        return "memory://"
    # dev / prod: use the configured Redis.
    return settings.redis_url


def build_limiter(settings: Settings | None = None) -> Limiter:
    """Construct the slowapi ``Limiter`` for this process.

    Called once at import time from ``main.py`` (Group C).
    Unit tests call it directly with an explicit Settings to
    exercise each branch.
    """
    settings = settings or get_settings()
    storage_uri = _resolve_storage_uri(settings)
    logger.info(
        "rate_limit.build",
        extra={
            "event": "rate_limit.build",
            "app_env": settings.app_env,
            "storage_scheme": storage_uri.split("://", 1)[0] + "://",
            "limit": settings.llm_proxy_embedding_rate_limit,
        },
    )
    return Limiter(
        key_func=token_principal_key,
        storage_uri=storage_uri,
        # No global default — the route opts in via decorator so
        # /healthz and /provider/meta are NOT rate-limited.
        default_limits=[],
        # Manual 429 header injection in the exception handler
        # (Group C) — slowapi's success-path header injection
        # requires ALL routes to return a dict-compatible body,
        # which we don't guarantee.
        headers_enabled=False,
    )


@lru_cache(maxsize=1)
def get_limiter() -> Limiter:
    """Return the process-wide ``Limiter`` singleton."""
    return build_limiter()
