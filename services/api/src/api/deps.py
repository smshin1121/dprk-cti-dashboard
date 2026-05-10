"""FastAPI dependencies.

``verify_token`` is the single auth gate used by every protected router.
It loads the server-side session keyed by the signed cookie, slides
both sides of the session forward (Redis TTL + re-signed cookie), and
returns a :class:`CurrentUser`.

``require_role`` is a dependency factory for endpoint-level RBAC checks.

``get_embedding_client`` returns the process-scoped llm-proxy embedding
client when ``LLM_PROXY_URL`` + ``LLM_PROXY_INTERNAL_TOKEN`` env vars
are both populated, or ``None`` when either is empty (embedding
disabled — the promote route skips the embed step entirely).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request, Response

from .auth.schemas import CurrentUser
from .auth.session import SessionStore, get_session_store, set_session_cookie
from .config import get_settings
from .embedding_client import LlmProxyEmbeddingClient


async def verify_token(
    request: Request,
    response: Response,
    session_store: SessionStore = Depends(get_session_store),
) -> CurrentUser:
    """Authenticate the request via the signed session cookie.

    Sliding expiration is enforced on *both* sides on every authenticated
    call: the Redis TTL is extended and the cookie is re-signed with a
    fresh timestamp, then attached to the outgoing response. Without the
    re-sign, the cookie would expire at ``first_sign + ttl`` even while
    the Redis session stays alive.
    """
    settings = get_settings()
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        raise HTTPException(status_code=401, detail="not authenticated")

    data = await session_store.load(cookie)
    if data is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")

    new_cookie = await session_store.touch(cookie)
    if new_cookie is None:
        # touch() failed after load() succeeded — the session was evicted
        # between the two reads. Treat as unauthenticated rather than
        # silently continuing with a stale identity.
        raise HTTPException(status_code=401, detail="session expired or invalid")
    set_session_cookie(response, new_cookie)

    return CurrentUser(
        sub=data.sub,
        email=data.email,
        name=data.name,
        roles=data.roles,
    )


def require_role(
    *allowed_roles: str,
) -> Callable[[CurrentUser], Coroutine[Any, Any, CurrentUser]]:
    """Dependency factory enforcing that the current user holds at least one
    of ``allowed_roles``. Used at the endpoint level for RBAC checks.

    The returned dependency delegates auth to :func:`verify_token` and then
    checks role membership. Because FastAPI deduplicates deps within a
    request scope, pairing this with a router-level ``verify_token`` is
    safe — ``verify_token`` runs exactly once per request.

    Known realm roles (see ``KnownRole`` in ``api.auth.schemas`` for the
    canonical literal): ``analyst``, ``admin``, ``policy``, ``researcher``,
    ``soc``. Adding a role to that ``Literal`` automatically extends the
    runtime ``KNOWN_ROLES`` filter via ``typing.get_args``.

        @router.post("/rules", dependencies=[Depends(require_role("admin"))])
        async def create_rule(...): ...
    """
    if not allowed_roles:
        raise ValueError("require_role() requires at least one role name")

    allowed = frozenset(allowed_roles)

    async def _dependency(
        user: CurrentUser = Depends(verify_token),
    ) -> CurrentUser:
        if not (allowed & set(user.roles)):
            raise HTTPException(
                status_code=403,
                detail=f"requires one of roles: {sorted(allowed)}",
            )
        return user

    return _dependency


# ---------------------------------------------------------------------------
# Embedding client (PR #19a Group B)
# ---------------------------------------------------------------------------
#
# The embedding client has a per-process httpx.AsyncClient that the
# ``get_embedding_client`` dependency returns on every request. The
# transport client is cached via ``lru_cache`` so connection pooling
# works across requests. Unit tests override the dep via
# ``app.dependency_overrides[get_embedding_client] = ...`` without
# touching this cache.
#
# When ``LLM_PROXY_URL`` or ``LLM_PROXY_INTERNAL_TOKEN`` is empty,
# the dependency returns ``None`` — the promote router then skips the
# embed step entirely. This is the "feature disabled" default and
# keeps existing dev / test setups (where llm-proxy isn't wired) from
# needing config changes.


@lru_cache(maxsize=1)
def _embedding_http_client() -> httpx.AsyncClient:
    """Lazily build the shared httpx.AsyncClient for the embedding path.

    Lifetime is process-scoped. FastAPI lifespan teardown will close
    it indirectly when the process exits; we do not rely on explicit
    shutdown because an ``AsyncClient`` with an httpx transport closes
    cleanly on GC in practice.
    """
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.llm_proxy_embedding_timeout_seconds),
    )


def get_embedding_client() -> LlmProxyEmbeddingClient | None:
    """Return the llm-proxy embedding client, or ``None`` if disabled.

    Enabled when BOTH ``LLM_PROXY_URL`` and
    ``LLM_PROXY_INTERNAL_TOKEN`` are non-empty. The promote router
    reads the return value and skips embedding on ``None`` without
    error (C4 — enrichment never blocks promote).
    """
    settings = get_settings()
    if not settings.llm_proxy_url or not settings.llm_proxy_internal_token:
        return None
    return LlmProxyEmbeddingClient(
        base_url=settings.llm_proxy_url,
        internal_token=settings.llm_proxy_internal_token,
        client=_embedding_http_client(),
        timeout_seconds=settings.llm_proxy_embedding_timeout_seconds,
    )
