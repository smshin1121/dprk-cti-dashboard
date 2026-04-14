"""Signed-cookie + Redis session store.

The browser only ever sees a signed opaque session id (``itsdangerous``
URL-safe timed serializer). The server-side payload — including the user's
sub, email, name and Keycloak realm roles — lives in Redis under the key
``session:<sid>``.

Sliding expiration is implemented on *both* sides:

* :meth:`SessionStore.touch` extends the Redis TTL by another
  ``ttl_seconds`` window.
* :meth:`SessionStore.touch` also returns a freshly-signed cookie value
  (the same sid re-wrapped with the current timestamp). The caller is
  expected to set this new value on the response so that the browser's
  cookie freshness window moves forward in lock-step with Redis.

Without the cookie re-signing step, the session would expire
cryptographically at ``first_sign + ttl`` regardless of activity, leaving
a live Redis session that can no longer be reached from the browser.

Refresh tokens are intentionally *not* persisted in P1.1: the user re-logs
in when the session expires.
"""

from __future__ import annotations

import secrets
from functools import lru_cache

import redis.asyncio as redis_asyncio
from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import get_settings
from .schemas import SessionData

_SESSION_KEY_PREFIX = "session:"
_SIGNER_SALT = "dprk-cti-session-v1"


class SessionStore:
    """Encapsulates Redis I/O and signed-cookie (de)serialization."""

    def __init__(
        self,
        redis: redis_asyncio.Redis,
        signer: URLSafeTimedSerializer,
        ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis
        self._signer = signer
        self._ttl = ttl_seconds

    @staticmethod
    def _redis_key(sid: str) -> str:
        return f"{_SESSION_KEY_PREFIX}{sid}"

    def _unwrap_cookie(self, signed_cookie: str) -> str | None:
        """Verify the cookie signature + age and return the raw sid."""
        try:
            return self._signer.loads(signed_cookie, max_age=self._ttl)
        except (BadSignature, SignatureExpired):
            return None

    async def create(self, data: SessionData) -> str:
        """Persist a session and return the signed cookie value."""
        sid = secrets.token_urlsafe(32)
        await self._redis.set(
            self._redis_key(sid),
            data.model_dump_json(),
            ex=self._ttl,
        )
        return self._signer.dumps(sid)

    async def load(self, signed_cookie: str) -> SessionData | None:
        """Verify the cookie, fetch the Redis blob, and return SessionData."""
        sid = self._unwrap_cookie(signed_cookie)
        if sid is None:
            return None

        raw = await self._redis.get(self._redis_key(sid))
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return SessionData.model_validate_json(raw)
        except Exception:  # noqa: BLE001 — defensive: malformed payload
            return None

    async def touch(self, signed_cookie: str) -> str | None:
        """Slide the session expiration forward on both sides.

        1. Re-set the Redis key's TTL to ``ttl_seconds`` (via ``EXPIRE``).
        2. Re-wrap the same sid through the timed signer so the returned
           cookie value carries a fresh timestamp.

        Returns the new cookie value on success, or ``None`` if the
        incoming cookie is invalid/expired or no Redis session exists.
        The caller MUST persist the returned value via
        :func:`set_session_cookie` for sliding expiration to take effect
        — otherwise the cookie will still expire at its original
        signing time + TTL, even though Redis state is refreshed.
        """
        sid = self._unwrap_cookie(signed_cookie)
        if sid is None:
            return None

        key = self._redis_key(sid)
        # Use EXPIRE rather than re-serializing and re-writing the whole
        # payload: the record itself is immutable after creation, only
        # its TTL needs to move. EXPIRE returns 0 if the key no longer
        # exists, which is the same "session gone" signal as load().
        extended = await self._redis.expire(key, self._ttl)
        if not extended:
            return None
        return self._signer.dumps(sid)

    async def destroy(self, signed_cookie: str) -> None:
        """Delete the session from Redis. Bad cookies are silently ignored."""
        sid = self._unwrap_cookie(signed_cookie)
        if sid is None:
            return
        await self._redis.delete(self._redis_key(sid))


def set_session_cookie(response: Response, value: str) -> None:
    """Attach the session cookie to ``response`` using the configured flags.

    Centralized so both the OIDC callback handler (which mints a fresh
    session) and :func:`api.deps.verify_token` (which slides an existing
    session) produce identical Set-Cookie headers.
    """
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=value,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie by setting max-age=0 with matching flags."""
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
    )


@lru_cache(maxsize=1)
def get_signer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.session_signing_key, salt=_SIGNER_SALT)


@lru_cache(maxsize=1)
def _get_redis() -> redis_asyncio.Redis:
    settings = get_settings()
    # ``from_url`` constructs an internal connection pool; reusing the same
    # client instance across requests keeps that pool warm.
    return redis_asyncio.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,
    )


@lru_cache(maxsize=1)
def get_session_store() -> SessionStore:
    settings = get_settings()
    return SessionStore(
        redis=_get_redis(),
        signer=get_signer(),
        ttl_seconds=settings.session_ttl_seconds,
    )


# Short-lived OIDC state store (state -> {verifier, redirect_uri}). Kept here
# rather than in oidc_client.py because it shares the same Redis pool and the
# 60-second TTL ensures the value is always cleaned up.
_OIDC_STATE_PREFIX = "oidc_state:"
_OIDC_STATE_TTL_SECONDS = 60


async def store_oidc_state(state: str, payload: str) -> None:
    redis = _get_redis()
    await redis.set(f"{_OIDC_STATE_PREFIX}{state}", payload, ex=_OIDC_STATE_TTL_SECONDS)


async def pop_oidc_state(state: str) -> str | None:
    """Atomically fetch and delete the stored OIDC state payload."""
    redis = _get_redis()
    key = f"{_OIDC_STATE_PREFIX}{state}"
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)
