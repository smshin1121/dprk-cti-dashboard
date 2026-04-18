"""OIDC authentication router (Keycloak).

Flow:

1. ``GET /login`` — generate state + PKCE verifier, stash them in Redis
   under ``oidc_state:<state>`` (60s TTL), redirect to Keycloak.
2. ``GET /callback`` — pop the state, exchange the code for tokens, verify
   the ID token via JWKS, create a Redis session, set the signed cookie,
   redirect back to the user's original target.
3. ``GET /me`` — return the current ``CurrentUser`` based on the cookie.
4. ``POST /logout`` — destroy the session and clear the cookie.

Refresh tokens are intentionally not persisted in P1.1; users re-log in
when their session expires.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from authlib.common.security import generate_token
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.audit import write_audit
from ..auth.jwt_verifier import (
    KidNotFoundError,
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
    extract_identity,
    extract_roles,
    verify_token as verify_jwt_token,
)
from ..auth.oidc_client import (
    build_authorization_url,
    build_logout_url,
    exchange_code,
)
from ..auth.schemas import CurrentUser, SessionData
from ..auth.session import (
    SessionStore,
    clear_session_cookie,
    get_session_store,
    pop_oidc_state,
    set_session_cookie,
    store_oidc_state,
)
from ..config import get_settings
from ..db import get_db
from ..deps import verify_token
from ..rate_limit import get_limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# PR #11 Group G — anti-bruteforce rate limit on OIDC endpoints.
# Plan D2: 10/min/IP for anonymous endpoints. Key function falls
# back to client IP because no session cookie exists yet at this
# point in the OIDC flow. See api.rate_limit.session_or_ip_key.
_limiter = get_limiter()


# ---------------------------------------------------------------------------
# Redirect sanitization helpers (open-redirect protection — C-1 / C-2)
# ---------------------------------------------------------------------------
def _safe_redirect_target(value: str | None) -> str:
    """Sanitize a post-login redirect target to prevent open-redirect.

    Only relative paths starting with a single ``/`` are allowed; ``//`` is
    rejected because browsers interpret it as a protocol-relative URL. Any
    absolute URL is rejected. The default is ``/``.
    """
    if not value:
        return "/"
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    # Defensive: reject any value containing a scheme separator or backslash
    # (Windows path / browser normalization quirks).
    if "://" in value or "\\" in value:
        return "/"
    return value


def _safe_logout_redirect(value: str | None, allowed_origins: list[str]) -> str:
    """Validate a post-logout redirect URI against the CORS allowlist.

    Allows either:
      * An absolute URL whose ``scheme://netloc`` is in ``allowed_origins``, or
      * A relative path that passes :func:`_safe_redirect_target`.

    Falls back to the first allowed origin (or ``/`` if none) on rejection.
    """
    default = allowed_origins[0] if allowed_origins else "/"
    if not value:
        return default
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in allowed_origins:
            return value
        return default
    sanitized = _safe_redirect_target(value)
    # If it degraded to "/" but we have a configured default, prefer that.
    if sanitized == "/" and default != "/":
        return default
    return sanitized


def _callback_url() -> str:
    settings = get_settings()
    return f"{settings.oidc_redirect_base_url.rstrip('/')}/api/v1/auth/callback"


@router.get(
    "/login",
    responses={
        429: {
            "description": (
                "Rate limit exceeded — 10/min/IP (plan D2 anti-bruteforce). "
                "Response body is the standard `{error, message}` shape; "
                "`Retry-After` and `X-RateLimit-Remaining` headers follow."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "10 per 1 minute",
                    }
                }
            },
        }
    },
)
@_limiter.limit("10/minute")
async def login(
    request: Request,
    redirect: str | None = Query(default=None),
) -> RedirectResponse:
    """Begin the OIDC login dance — generate state + PKCE, redirect to Keycloak."""
    state = secrets.token_urlsafe(32)
    # PKCE: use Authlib's helper so the verifier conforms to RFC 7636.
    code_verifier = generate_token(48)

    # Sanitize the redirect target BEFORE persisting it in Redis (defense in
    # depth — even if /callback forgot to re-sanitize, the stored value is
    # already safe).
    safe_redirect = _safe_redirect_target(redirect)
    payload = json.dumps({"verifier": code_verifier, "redirect": safe_redirect})
    await store_oidc_state(state, payload)

    url = await build_authorization_url(
        redirect_uri=_callback_url(),
        state=state,
        code_verifier=code_verifier,
    )
    return RedirectResponse(url=url, status_code=302)


@router.get(
    "/callback",
    responses={
        429: {
            "description": (
                "Rate limit exceeded — 10/min/IP. Response body stays JSON "
                "even on this browser-redirect endpoint (Group G lock — "
                "one body shape for all decorated routes)."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "10 per 1 minute",
                    }
                }
            },
        }
    },
)
@_limiter.limit("10/minute")
async def callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    session_store: SessionStore = Depends(get_session_store),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle Keycloak's redirect: validate state, exchange code, build session."""
    raw_state = await pop_oidc_state(state)
    if raw_state is None:
        await _audit_failure(db, request, "invalid_state")
        raise HTTPException(status_code=400, detail="invalid or expired state")

    try:
        state_payload = json.loads(raw_state)
        verifier = state_payload["verifier"]
        target_redirect = state_payload.get("redirect") or "/"
    except (ValueError, KeyError):
        await _audit_failure(db, request, "malformed_state_payload")
        raise HTTPException(status_code=400, detail="malformed state payload") from None

    # Defense in depth: re-sanitize on the way out, so a tainted Redis value
    # (injected by a future bug or attacker with Redis access) cannot become
    # an open redirect.
    target_redirect = _safe_redirect_target(target_redirect)

    try:
        token = await exchange_code(
            code=code,
            redirect_uri=_callback_url(),
            code_verifier=verifier,
        )
    except Exception as exc:  # noqa: BLE001 — authlib raises a wide range
        logger.exception("token exchange failed")
        await _audit_failure(
            db, request, "token_exchange_failed", exc_type=type(exc).__name__
        )
        raise HTTPException(status_code=401, detail="token exchange failed") from exc

    # OIDC separates "who" from "what you can do": the id_token carries
    # the stable subject identifier (``sub``) and identity fields, while
    # Keycloak puts the role claim set (``realm_access.roles``) into the
    # access_token. Verify both, merging identity from id_token with
    # roles from access_token. If the provider omits one of the two,
    # fall back to whatever we got.
    id_token_raw = token.get("id_token")
    access_token_raw = token.get("access_token")
    if not id_token_raw and not access_token_raw:
        await _audit_failure(db, request, "missing_tokens")
        raise HTTPException(
            status_code=401, detail="no tokens in OIDC response"
        )

    try:
        id_claims: dict = {}
        access_claims: dict = {}
        if id_token_raw:
            id_claims = dict(await verify_jwt_token(id_token_raw))
        if access_token_raw:
            access_claims = dict(await verify_jwt_token(access_token_raw))
    except TokenExpiredError as exc:
        await _audit_failure(db, request, "token_expired")
        raise HTTPException(status_code=401, detail="token expired") from exc
    except (TokenInvalidError, KidNotFoundError, TokenError) as exc:
        logger.exception("token validation failed")
        await _audit_failure(
            db, request, "token_invalid", exc_type=type(exc).__name__
        )
        raise HTTPException(status_code=401, detail="invalid token") from exc

    # Identity: prefer the id_token (OIDC guarantees sub); fall back to
    # access_token if the provider only returned one of the two.
    identity_claims = id_claims or access_claims
    sub, email, name = extract_identity(identity_claims)

    # Roles: Keycloak ships them in the access_token's ``realm_access``.
    # Fall back to id_token (which some custom mappers may populate too).
    roles = extract_roles(access_claims) or extract_roles(id_claims)
    now = datetime.now(timezone.utc)

    session = SessionData(
        sub=sub,
        email=email,
        name=name or None,
        roles=roles,
        created_at=now,
        last_activity=now,
    )
    cookie_value = await session_store.create(session)

    await write_audit(
        db,
        actor=email or sub or "unknown",
        action="login_success",
        entity="auth",
        entity_id=sub or None,
        extra={
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "roles": roles,
        },
    )

    response = RedirectResponse(url=target_redirect, status_code=302)
    set_session_cookie(response, cookie_value)
    return response


@router.get(
    "/me",
    response_model=CurrentUser,
    responses={
        200: {
            "description": "Current authenticated user identity + roles.",
            "content": {
                "application/json": {
                    "example": {
                        "sub": "abc-123",
                        "email": "analyst@dprk.test",
                        "name": "Jane Analyst",
                        "roles": ["analyst"],
                    }
                }
            },
        },
        401: {"description": "Missing or expired session cookie"},
        429: {
            "description": (
                "Rate limit exceeded — 60/min/user read bucket (plan D2 / "
                "Group H). /auth/me shares the read-bucket policy with "
                "the four list endpoints but keeps its own per-route "
                "counter. Body stays JSON (not redirect) so the FE "
                "session-probe loop can branch on 429 the same way as "
                "any other read call."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "60 per 1 minute",
                    }
                }
            },
        },
    },
)
@_limiter.limit("60/minute")
async def me(
    request: Request,
    user: CurrentUser = Depends(verify_token),
) -> CurrentUser:
    """Return the current authenticated user (401 if no/expired session).

    The DTO (``CurrentUser``) is unchanged by Group H — only the
    60/min decorator is added. slowapi's middleware runs BEFORE
    FastAPI resolves ``verify_token``, so:

    - Authenticated caller → session-cookie bucket
    - No cookie → client-IP bucket (still rate-limited, then 401)
    - Over limit → 429 without re-running ``verify_token``

    Behaviour is consistent with the four read endpoints; same
    bucket policy, same 429 body shape.
    """
    return user


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    session_store: SessionStore = Depends(get_session_store),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Destroy the session, write an audit row, and clear the cookie."""
    settings = get_settings()
    cookie = request.cookies.get(settings.session_cookie_name)

    actor = "anonymous"
    if cookie:
        data = await session_store.load(cookie)
        if data is not None:
            actor = data.email or data.sub or "unknown"
        await session_store.destroy(cookie)

    await write_audit(
        db,
        actor=actor,
        action="logout",
        entity="auth",
        extra={
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        },
    )

    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/logout-url")
async def logout_url(redirect: str | None = Query(default=None)) -> dict[str, str]:
    """Return the Keycloak end-session URL for browser-initiated logout.

    Useful when the SPA wants to fully log the user out of Keycloak after
    calling ``POST /logout``.
    """
    settings = get_settings()
    # Validate the inbound redirect against the CORS allowlist to prevent
    # open-redirect via the Keycloak ``post_logout_redirect_uri`` parameter.
    target = _safe_logout_redirect(redirect, settings.cors_origins)
    if target == "/":
        # Keycloak requires an absolute URL for post_logout_redirect_uri; fall
        # back to the API's public base URL when no allowlist entry exists.
        target = settings.oidc_redirect_base_url
    return {"url": await build_logout_url(target)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _audit_failure(
    db: AsyncSession,
    request: Request,
    reason: str,
    *,
    exc_type: str | None = None,
) -> None:
    """Record a login failure. Best-effort — never raises.

    Only accepts a stable ``reason`` enum-like string plus an optional
    exception class name. Raw exception messages are intentionally excluded
    from the audit log to prevent leaking tokens, URLs, or PII.
    """
    try:
        extra: dict[str, object | None] = {
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "reason": reason,
        }
        if exc_type:
            extra["exc_type"] = exc_type
        await write_audit(
            db,
            actor="anonymous",
            action="login_failure",
            entity="auth",
            extra=extra,
        )
    except Exception:  # noqa: BLE001
        # Never let an audit failure mask the real auth failure.
        pass
