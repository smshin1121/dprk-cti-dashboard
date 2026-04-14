"""FastAPI dependencies.

``verify_token`` is the single auth gate used by every protected router.
It loads the server-side session keyed by the signed cookie, refreshes
its TTL (sliding expiration), and returns a :class:`CurrentUser`.

``require_role`` is a dependency factory for endpoint-level RBAC checks.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, Request

from .auth.schemas import CurrentUser
from .auth.session import SessionStore, get_session_store
from .config import get_settings


async def verify_token(
    request: Request,
    session_store: SessionStore = Depends(get_session_store),
) -> CurrentUser:
    """Authenticate the request via the signed session cookie."""
    settings = get_settings()
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        raise HTTPException(status_code=401, detail="not authenticated")

    data = await session_store.load(cookie)
    if data is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")

    # Sliding expiration: every authenticated hit pushes the TTL forward.
    await session_store.touch(cookie)

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

    Known realm roles (see §9.3): ``analyst``, ``admin``, ``policy``.

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
