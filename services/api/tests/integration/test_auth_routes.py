"""Integration tests for auth routes (/api/v1/auth/*).

All external dependencies (Keycloak, Redis, PostgreSQL) are mocked:
- fakeredis for session + OIDC state storage
- respx / AsyncMock for Keycloak token endpoint and JWKS
- AsyncMock for DB session (audit log)

Tests run the full FastAPI request→response cycle via httpx AsyncClient +
ASGI transport.
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
import respx
from authlib.jose import JsonWebKey, jwt as authlib_jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import Response

from api.auth.schemas import SessionData
from api.auth import jwt_verifier as jv
from api.auth import oidc_client as oidc_mod


# ---------------------------------------------------------------------------
# Auth-specific key pair (module-scoped so we don't regenerate on each test)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def auth_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def auth_jwks(auth_rsa_key):
    pub_pem = auth_rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = JsonWebKey.import_key(pub_pem, {"kty": "RSA", "kid": "auth-kid-1"})
    key_dict = jwk.as_dict()
    key_dict["kid"] = "auth-kid-1"
    key_dict["use"] = "sig"
    key_dict["alg"] = "RS256"
    return {"keys": [key_dict]}


def _mint_id_token(rsa_key, *, roles=None, exp_offset=3600, aud="dprk-cti") -> str:
    now = int(time.time())
    header = {"alg": "RS256", "kid": "auth-kid-1"}
    payload = {
        "iss": "http://keycloak.test/realms/dprk",
        "aud": aud,
        "sub": "test-sub-001",
        "email": "testuser@dprk.test",
        "name": "Test User",
        "preferred_username": "testuser",
        "realm_access": {"roles": roles or ["analyst"]},
        "exp": now + exp_offset,
        "iat": now,
        "nbf": now,
    }
    priv_pem = rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    jwk = JsonWebKey.import_key(priv_pem, {"kty": "RSA", "kid": "auth-kid-1"})
    token_bytes = authlib_jwt.encode(header, payload, jwk)
    return token_bytes.decode("utf-8") if isinstance(token_bytes, bytes) else token_bytes


def _fake_discovery() -> dict:
    return {
        "issuer": "http://keycloak.test/realms/dprk",
        "authorization_endpoint": "http://keycloak.test/realms/dprk/protocol/openid-connect/auth",
        "token_endpoint": "http://keycloak.test/realms/dprk/protocol/openid-connect/token",
        "jwks_uri": "http://keycloak.test/realms/dprk/protocol/openid-connect/certs",
        "end_session_endpoint": "http://keycloak.test/realms/dprk/protocol/openid-connect/logout",
    }


# ---------------------------------------------------------------------------
# Test: GET /api/v1/auth/login
# ---------------------------------------------------------------------------

async def test_login_redirects_to_keycloak(client):
    """GET /login produces a 302 redirect to the Keycloak authorization endpoint
    carrying a CSRF state and a fully-formed PKCE S256 challenge.

    Regression: the original Step 2 impl relied on Authlib auto-deriving the
    code_challenge from the verifier, which only fires when
    code_challenge_method is set on the client constructor. The fix computes
    the S256 challenge explicitly and passes it as code_challenge alongside
    code_challenge_method=S256 — this test pins that behavior.
    """
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get("/api/v1/auth/login", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("http://keycloak.test/realms/dprk/protocol/openid-connect/auth")

    parsed = urlparse(location)
    qs = parse_qs(parsed.query)
    assert "state" in qs, "state param must be present for CSRF protection"
    assert qs.get("code_challenge_method", [""])[0] == "S256", "Must declare S256 PKCE method"
    challenge = qs.get("code_challenge", [""])[0]
    assert challenge, "code_challenge must be present (PKCE enforcement)"
    # Base64url-encoded SHA-256 = 43 chars (256 bits / 6 bits per char, no padding)
    assert len(challenge) == 43, f"S256 challenge must be 43 chars, got {len(challenge)}"
    assert "=" not in challenge, "code_challenge must be unpadded base64url"


async def test_login_stores_state_in_redis(client, fake_redis):
    """After /login, the OIDC state is stored in Redis under oidc_state:<state>."""
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get("/api/v1/auth/login", follow_redirects=False)

    location = resp.headers["location"]
    qs = parse_qs(urlparse(location).query)
    state = qs["state"][0]

    raw = await fake_redis.get(f"oidc_state:{state}")
    assert raw is not None, "oidc_state:<state> key should exist in Redis"

    payload = json.loads(raw)
    assert "verifier" in payload


# ---------------------------------------------------------------------------
# Test: GET /api/v1/auth/callback
# ---------------------------------------------------------------------------

async def test_callback_with_invalid_state_returns_400(client):
    """Callback with a state not in Redis returns 400."""
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get(
            "/api/v1/auth/callback",
            params={"state": "bogus-state-xyz", "code": "any-code"},
            follow_redirects=False,
        )

    assert resp.status_code in (400, 401)


async def test_callback_happy_path_creates_session_and_sets_cookie(
    client, fake_redis, auth_rsa_key, auth_jwks
):
    """Successful callback creates a session cookie and redirects."""
    # 1. Pre-populate the OIDC state in Redis (simulating /login)
    state = "test-state-abc123"
    verifier = "test-code-verifier-at-least-43-characters-long-xyz"
    state_payload = json.dumps({"verifier": verifier, "redirect": "/"})
    await fake_redis.set(f"oidc_state:{state}", state_payload, ex=60)

    id_token = _mint_id_token(auth_rsa_key, roles=["analyst"])

    # 2. Mock Keycloak token exchange
    fake_token_response = {
        "access_token": "fake-access-token",
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    jv._jwks_cache.clear()

    # Patch discover_metadata in BOTH the oidc_client module and jwt_verifier module,
    # because jwt_verifier.py imports discover_metadata at import time and holds
    # its own reference.
    fake_discovery = _fake_discovery()
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=fake_discovery)):
        with patch.object(jv, "discover_metadata", new=AsyncMock(return_value=fake_discovery)):
            with patch("api.routers.auth.exchange_code", new=AsyncMock(return_value=fake_token_response)):
                with patch.object(jv, "_fetch_jwks", new=AsyncMock(return_value=auth_jwks)):
                    resp = await client.get(
                        "/api/v1/auth/callback",
                        params={"state": state, "code": "auth-code-xyz"},
                        follow_redirects=False,
                    )

    assert resp.status_code == 302, f"Expected 302 redirect, got {resp.status_code}: {resp.text}"
    # Session cookie must be set
    cookie_name = "dprk_cti_session"
    assert cookie_name in resp.cookies or any(
        cookie_name in h for h in resp.headers.get_list("set-cookie")
    ), "Session cookie must be set in response"


# ---------------------------------------------------------------------------
# Test: GET /api/v1/auth/me
# ---------------------------------------------------------------------------

async def test_me_without_cookie_returns_401(client):
    """GET /me without a session cookie returns 401."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_valid_cookie_returns_user(client, make_session_cookie):
    """GET /me with a valid signed cookie returns 200 with user data."""
    cookie_value = await make_session_cookie(
        sub="me-user-001",
        email="me@test.com",
        name="Me User",
        roles=["analyst"],
    )

    resp = await client.get(
        "/api/v1/auth/me",
        cookies={"dprk_cti_session": cookie_value},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["sub"] == "me-user-001"
    assert body["email"] == "me@test.com"
    assert "analyst" in body["roles"]


# ---------------------------------------------------------------------------
# Test: POST /api/v1/auth/logout
# ---------------------------------------------------------------------------

async def test_logout_clears_cookie_and_destroys_session(
    client, make_session_cookie, fake_redis, test_signer
):
    """POST /logout destroys the Redis session and instructs browser to clear cookie."""
    cookie_value = await make_session_cookie(
        sub="logout-user-001",
        email="logout@test.com",
        roles=["analyst"],
    )

    # Confirm session exists
    sid = test_signer.loads(cookie_value, max_age=3600)
    assert await fake_redis.get(f"session:{sid}") is not None

    resp = await client.post(
        "/api/v1/auth/logout",
        cookies={"dprk_cti_session": cookie_value},
    )

    assert resp.status_code == 204

    # Session key must be deleted from Redis
    assert await fake_redis.get(f"session:{sid}") is None

    # Response should clear the cookie (max-age=0 or expires in the past)
    set_cookie_headers = resp.headers.get_list("set-cookie")
    has_cleared_cookie = any(
        "dprk_cti_session" in h and ("max-age=0" in h.lower() or "expires" in h.lower())
        for h in set_cookie_headers
    )
    assert has_cleared_cookie, f"Cookie should be cleared. set-cookie: {set_cookie_headers}"


# ---------------------------------------------------------------------------
# Test: audit log called on successful callback
# ---------------------------------------------------------------------------

async def _state_and_redirect(client, fake_redis):
    """Run /login, return (state, stored redirect from Redis)."""
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get("/api/v1/auth/login", follow_redirects=False)
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    state = qs["state"][0]
    raw = await fake_redis.get(f"oidc_state:{state}")
    return state, json.loads(raw)["redirect"]


# ---------------------------------------------------------------------------
# Open-redirect protection — /login query param sanitization (C-1)
# ---------------------------------------------------------------------------

async def test_login_with_relative_path_redirect_preserved(client, fake_redis):
    """?redirect=/dashboard is preserved into the Redis state payload."""
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get(
            "/api/v1/auth/login?redirect=/dashboard", follow_redirects=False
        )
    assert resp.status_code == 302
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    state = qs["state"][0]
    raw = await fake_redis.get(f"oidc_state:{state}")
    assert json.loads(raw)["redirect"] == "/dashboard"


async def test_login_with_protocol_relative_redirect_rejected(client, fake_redis):
    """?redirect=//evil.com must fall back to '/' (browsers read // as scheme)."""
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get(
            "/api/v1/auth/login?redirect=//evil.com", follow_redirects=False
        )
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    state = qs["state"][0]
    raw = await fake_redis.get(f"oidc_state:{state}")
    assert json.loads(raw)["redirect"] == "/"


async def test_login_with_absolute_url_redirect_rejected(client, fake_redis):
    """?redirect=https://evil.com must fall back to '/'."""
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get(
            "/api/v1/auth/login?redirect=https://evil.com", follow_redirects=False
        )
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    state = qs["state"][0]
    raw = await fake_redis.get(f"oidc_state:{state}")
    assert json.loads(raw)["redirect"] == "/"


async def test_login_with_backslash_redirect_rejected(client, fake_redis):
    r"""?redirect=/\evil.com must fall back to '/' (backslash sanitization)."""
    with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=_fake_discovery())):
        resp = await client.get(
            "/api/v1/auth/login", params={"redirect": "/\\evil.com"},
            follow_redirects=False,
        )
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    state = qs["state"][0]
    raw = await fake_redis.get(f"oidc_state:{state}")
    assert json.loads(raw)["redirect"] == "/"


async def test_audit_log_called_on_callback_success(
    client, fake_redis, auth_rsa_key, auth_jwks
):
    """write_audit is called with action='login_success' during successful callback."""
    state = "audit-test-state-789"
    verifier = "audit-code-verifier-at-least-43-characters-long-xyz"
    state_payload = json.dumps({"verifier": verifier, "redirect": "/"})
    await fake_redis.set(f"oidc_state:{state}", state_payload, ex=60)

    id_token = _mint_id_token(auth_rsa_key, roles=["analyst"])
    fake_token_response = {
        "access_token": "fake-access",
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    jv._jwks_cache.clear()
    fake_discovery = _fake_discovery()

    # Patch write_audit in the routers.auth namespace (where the router imported it).
    with patch("api.routers.auth.write_audit", new=AsyncMock()) as mock_write_audit:
        with patch.object(oidc_mod, "discover_metadata", new=AsyncMock(return_value=fake_discovery)):
            with patch.object(jv, "discover_metadata", new=AsyncMock(return_value=fake_discovery)):
                with patch("api.routers.auth.exchange_code", new=AsyncMock(return_value=fake_token_response)):
                    with patch.object(jv, "_fetch_jwks", new=AsyncMock(return_value=auth_jwks)):
                        resp = await client.get(
                            "/api/v1/auth/callback",
                            params={"state": state, "code": "audit-code"},
                            follow_redirects=False,
                        )

    assert resp.status_code == 302

    # Verify write_audit was called with login_success
    calls_with_success = [
        c for c in mock_write_audit.call_args_list
        if c.kwargs.get("action") == "login_success"
    ]
    assert len(calls_with_success) >= 1, (
        f"write_audit should have been called with action='login_success'. "
        f"Calls: {mock_write_audit.call_args_list}"
    )
