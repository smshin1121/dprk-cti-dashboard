"""Signed-cookie + Redis session store.

The browser only ever sees a signed opaque session id (``itsdangerous``
URL-safe timed serializer). The server-side payload — including the user's
sub, email, name and Keycloak realm roles — lives in Redis under the key
``session:<sid>`` with sliding TTL.

Refresh tokens are intentionally *not* persisted in P1.1: the user re-logs
in when the session expires.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from functools import lru_cache

import redis.asyncio as redis_asyncio
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
        try:
            sid = self._signer.loads(signed_cookie, max_age=self._ttl)
        except (BadSignature, SignatureExpired):
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

    async def touch(self, signed_cookie: str) -> None:
        """Update last_activity and extend the Redis TTL (sliding session)."""
        try:
            sid = self._signer.loads(signed_cookie, max_age=self._ttl)
        except (BadSignature, SignatureExpired):
            return

        key = self._redis_key(sid)
        raw = await self._redis.get(key)
        if raw is None:
            return
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = SessionData.model_validate_json(raw)
        except Exception:  # noqa: BLE001
            return

        refreshed = data.model_copy(
            update={"last_activity": datetime.now(timezone.utc)}
        )
        await self._redis.set(key, refreshed.model_dump_json(), ex=self._ttl)

    async def destroy(self, signed_cookie: str) -> None:
        """Delete the session from Redis. Bad cookies are silently ignored."""
        try:
            sid = self._signer.loads(signed_cookie, max_age=self._ttl)
        except (BadSignature, SignatureExpired):
            return
        await self._redis.delete(self._redis_key(sid))


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
