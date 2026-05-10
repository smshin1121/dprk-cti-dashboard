"""Unit tests for api.auth.session.SessionStore.

All tests use fakeredis — no real Redis connection required.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from freezegun import freeze_time
from itsdangerous import BadSignature, URLSafeTimedSerializer

from api.auth.schemas import SessionData
from api.auth.session import SessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_data(
    sub: str = "user-001",
    email: str = "user@test.com",
    name: str = "Test User",
    roles: list[str] | None = None,
) -> SessionData:
    now = datetime.now(timezone.utc)
    return SessionData(
        sub=sub,
        email=email,
        name=name,
        roles=roles or ["analyst"],
        created_at=now,
        last_activity=now,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_create_returns_signed_cookie(session_store, test_signer):
    """create() returns a string the signer can decode back to a session ID."""
    data = _make_session_data()
    cookie = await session_store.create(data)

    assert isinstance(cookie, str)
    assert len(cookie) > 0

    # The cookie must be decodable by the same signer (no exception = valid)
    sid = test_signer.loads(cookie, max_age=3600)
    assert isinstance(sid, str)
    assert len(sid) > 0


async def test_create_persists_to_redis(session_store, fake_redis, test_signer):
    """After create(), the Redis key session:<sid> exists and contains JSON."""
    data = _make_session_data()
    cookie = await session_store.create(data)

    sid = test_signer.loads(cookie, max_age=3600)
    raw = await fake_redis.get(f"session:{sid}")

    assert raw is not None, "Redis key should exist after create()"
    parsed = json.loads(raw)
    assert parsed["sub"] == data.sub
    assert parsed["email"] == data.email
    assert set(parsed["roles"]) == set(data.roles)


async def test_load_valid_cookie_returns_data(session_store):
    """Round-trip: create() then load() returns the original SessionData."""
    data = _make_session_data(sub="roundtrip-001", email="rt@test.com")
    cookie = await session_store.create(data)

    loaded = await session_store.load(cookie)

    assert loaded is not None
    assert loaded.sub == data.sub
    assert loaded.email == data.email
    assert loaded.roles == data.roles


async def test_load_returns_none_for_garbage_cookie(session_store):
    """load() returns None when given a completely invalid cookie string."""
    result = await session_store.load("not.a.valid.cookie.at.all")
    assert result is None


async def test_load_returns_none_when_redis_payload_has_unknown_role(
    session_store, fake_redis, test_signer
):
    """A Redis blob with an unknown role fails ``SessionData`` validation.

    Defense-in-depth check after the P1.1 deferral closure that narrowed
    ``SessionData.roles`` to ``list[KnownRole]``: if an attacker (or
    bit-rot) injects a session blob carrying an unknown role into Redis,
    ``model_validate_json`` raises ``ValidationError``. The
    ``except Exception`` branch in ``SessionStore.load`` then returns
    None, which the ``verify_token`` dependency translates to 401.

    Pins the gate-moved-up contract: unknown roles can never reach
    ``require_role`` at the route layer, regardless of how they got
    into Redis.
    """
    # Mint a valid signed cookie pointing at an sid we control.
    valid_data = _make_session_data()
    cookie = await session_store.create(valid_data)
    sid = test_signer.loads(cookie, max_age=3600)

    # Overwrite the Redis payload with a JSON document that satisfies
    # SessionData's STRUCTURE but carries an unknown role. The signed
    # cookie remains valid (sid hasn't changed); only the stored blob
    # is corrupt-by-injection.
    poisoned_payload = json.dumps(
        {
            "sub": "u",
            "email": "u@test.com",
            "name": "U",
            "roles": ["sudo"],  # unknown — fails Literal validation
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_activity": datetime.now(timezone.utc).isoformat(),
        }
    )
    await fake_redis.set(f"session:{sid}", poisoned_payload)

    result = await session_store.load(cookie)

    assert result is None, (
        "load() must return None when the Redis payload fails pydantic "
        "validation — the verify_token dependency then issues 401, "
        "not 403, and unknown roles never reach require_role."
    )


async def test_load_returns_none_for_expired_cookie(fake_redis, test_signer):
    """load() returns None when the cookie signature has exceeded max_age."""
    # Build a store with a very short TTL (1 second) so we can expire it
    short_store = SessionStore(redis=fake_redis, signer=test_signer, ttl_seconds=1)
    data = _make_session_data()

    with freeze_time("2024-01-01 12:00:00"):
        cookie = await short_store.create(data)

    # Advance time by 2 seconds — signature max_age=1 should be violated
    with freeze_time("2024-01-01 12:00:02"):
        result = await short_store.load(cookie)

    assert result is None


async def test_load_returns_none_when_redis_key_missing(session_store, fake_redis, test_signer):
    """load() returns None when Redis key is gone (evicted) even with valid cookie."""
    data = _make_session_data()
    cookie = await session_store.create(data)

    # Manually delete the Redis key to simulate eviction
    sid = test_signer.loads(cookie, max_age=3600)
    await fake_redis.delete(f"session:{sid}")

    result = await session_store.load(cookie)
    assert result is None


async def test_destroy_removes_redis_key(session_store, fake_redis, test_signer):
    """destroy() deletes the Redis key associated with the cookie."""
    data = _make_session_data()
    cookie = await session_store.create(data)

    sid = test_signer.loads(cookie, max_age=3600)
    # Confirm the key exists before destroy
    assert await fake_redis.get(f"session:{sid}") is not None

    await session_store.destroy(cookie)

    assert await fake_redis.get(f"session:{sid}") is None


async def test_touch_extends_ttl(session_store, fake_redis, test_signer):
    """touch() resets the Redis key TTL back to the full session TTL."""
    data = _make_session_data()
    cookie = await session_store.create(data)

    sid = test_signer.loads(cookie, max_age=3600)
    key = f"session:{sid}"

    # Manually set a short TTL to simulate partial expiry
    await fake_redis.expire(key, 10)
    ttl_before = await fake_redis.ttl(key)
    assert ttl_before <= 10

    await session_store.touch(cookie)

    ttl_after = await fake_redis.ttl(key)
    # After touch(), TTL should be back near session_store._ttl (3600)
    assert ttl_after > 10, f"TTL should have been extended; got {ttl_after}"


async def test_touch_returns_resigned_cookie_with_same_sid(
    session_store, test_signer
):
    """touch() returns a freshly-signed cookie that unwraps to the SAME sid.

    This is the sliding-expiration contract: the caller uses the returned
    value to update the browser cookie so its cryptographic freshness
    window moves forward in lock-step with the Redis TTL. Without this,
    the cookie would expire at first_sign + ttl even while Redis is
    alive, producing a zombie session.
    """
    data = _make_session_data()
    original_cookie = await session_store.create(data)
    original_sid = test_signer.loads(original_cookie, max_age=3600)

    new_cookie = await session_store.touch(original_cookie)

    assert new_cookie is not None, "touch() must return a cookie on success"
    assert isinstance(new_cookie, str)
    new_sid = test_signer.loads(new_cookie, max_age=3600)
    assert new_sid == original_sid, "the underlying sid must not change"


async def test_touch_returns_none_when_session_missing(
    session_store, fake_redis, test_signer
):
    """touch() returns None when the Redis session key is gone.

    Simulates a session evicted between the ``load()`` and ``touch()``
    calls inside ``verify_token``. The dependency must treat this as a
    401 rather than silently continuing with a stale identity.
    """
    data = _make_session_data()
    cookie = await session_store.create(data)
    sid = test_signer.loads(cookie, max_age=3600)

    # Eject the Redis session out from under the cookie
    await fake_redis.delete(f"session:{sid}")

    assert await session_store.touch(cookie) is None


async def test_touch_returns_none_for_invalid_cookie(session_store):
    """touch() returns None when the incoming cookie fails signature/age check."""
    assert await session_store.touch("garbage-not-signed") is None
