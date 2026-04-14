"""JWT verification against Keycloak's JWKS endpoint.

The verifier:

* fetches the JWKS once and caches it for 5 minutes (cachetools TTLCache),
* validates ``iss``/``aud``/``exp``/``nbf``/``iat`` and the RS256 signature
  using ``authlib.jose``,
* exposes helpers to extract the user identity and the realm roles we care
  about (``analyst``, ``admin``, ``policy``).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import (
    BadSignatureError,
    DecodeError,
    ExpiredTokenError,
    InvalidClaimError,
    JoseError,
)
from cachetools import TTLCache

from ..config import get_settings
from .oidc_client import discover_metadata

# Roles defined in the Keycloak realm import. Anything else is ignored.
KNOWN_ROLES: frozenset[str] = frozenset({"analyst", "admin", "policy"})

# JWKS cache: a single key ("jwks") with a 5-minute TTL.
_jwks_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=1, ttl=300)


class TokenError(Exception):
    """Base class for token verification failures."""


class TokenExpiredError(TokenError):
    """The token's ``exp`` claim is in the past."""


class TokenInvalidError(TokenError):
    """The token's signature, claims, or structure are invalid."""


class KidNotFoundError(TokenError):
    """The token's ``kid`` does not match any current JWKS key."""


async def _fetch_jwks() -> dict[str, Any]:
    cached = _jwks_cache.get("jwks")
    if cached is not None:
        return cached

    metadata = await discover_metadata()
    jwks_uri = metadata["jwks_uri"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(jwks_uri)
            resp.raise_for_status()
            jwks = resp.json()
    except httpx.HTTPError as exc:
        raise TokenInvalidError(f"failed to fetch JWKS: {exc}") from exc

    _jwks_cache["jwks"] = jwks
    return jwks


def _select_key(jwks: dict[str, Any], kid: str | None) -> dict[str, Any]:
    keys = jwks.get("keys", [])
    if not keys:
        raise TokenInvalidError("JWKS document has no keys")
    if kid is None:
        # If the token has no kid, fall back to the first signing key.
        return keys[0]
    for key in keys:
        if key.get("kid") == kid:
            return key
    raise KidNotFoundError(f"kid {kid!r} not found in JWKS")


async def verify_token(token: str) -> dict[str, Any]:
    """Verify a Keycloak-issued JWT and return its claims dict.

    Raises :class:`TokenExpiredError`, :class:`KidNotFoundError`, or
    :class:`TokenInvalidError` on any failure. Callers should map these to
    HTTP 401 in the router layer.
    """
    settings = get_settings()
    metadata = await discover_metadata()
    discovery_issuer = metadata.get("issuer", settings.oidc_issuer_url)
    allowed_issuers = {discovery_issuer}
    if settings.oidc_trusted_issuers:
        allowed_issuers.update(settings.oidc_trusted_issuers)

    # Read the unverified header to find the kid.
    try:
        header_segment = token.split(".")[0]
    except Exception as exc:  # noqa: BLE001
        raise TokenInvalidError("malformed JWT") from exc

    import base64
    import json as _json

    try:
        padded = header_segment + "=" * (-len(header_segment) % 4)
        header = _json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception as exc:  # noqa: BLE001
        raise TokenInvalidError("invalid JWT header") from exc

    kid = header.get("kid")
    jwks = await _fetch_jwks()
    try:
        key_dict = _select_key(jwks, kid)
    except KidNotFoundError:
        # Force a refresh once in case Keycloak rotated keys mid-flight.
        _jwks_cache.pop("jwks", None)
        jwks = await _fetch_jwks()
        key_dict = _select_key(jwks, kid)

    key = JsonWebKey.import_key(key_dict)

    # Audience / authorized-party validation.
    #
    # OIDC id_tokens carry the client_id in ``aud``. Keycloak access_tokens
    # by default have ``aud: ["account"]`` and put the requesting client id
    # in ``azp`` (authorized party — RFC 7519 + OIDC Core 1.0 §2). Accept
    # either form so the verifier works for both token types without
    # Keycloak-side audience-mapper configuration.
    #
    # ``aud`` is declared non-essential so the decode step does not reject
    # Keycloak access tokens that ship without an ``aud`` at all (default
    # Keycloak config emits ``azp`` and omits ``aud`` for confidential
    # clients unless an explicit audience mapper is added). The real
    # audience/authorized-party check runs after ``decode``.
    claims_options = {
        "iss": {"essential": True, "values": sorted(allowed_issuers)},
        "exp": {"essential": True},
    }

    try:
        claims = jwt.decode(token, key, claims_options=claims_options)
        claims.validate(now=int(time.time()), leeway=10)
    except ExpiredTokenError as exc:
        raise TokenExpiredError(str(exc)) from exc
    except (BadSignatureError, DecodeError, InvalidClaimError, JoseError) as exc:
        raise TokenInvalidError(str(exc)) from exc

    # Audience / authorized-party manual check.
    client_id = settings.oidc_client_id
    aud = claims.get("aud")
    azp = claims.get("azp")
    aud_list = [aud] if isinstance(aud, str) else (aud or [])
    if client_id not in aud_list and azp != client_id:
        raise TokenInvalidError(
            f"token not intended for this client: aud={aud_list!r} azp={azp!r}"
        )

    return dict(claims)


def extract_roles(claims: dict[str, Any]) -> list[str]:
    """Return the subset of realm roles we recognise."""
    realm_access = claims.get("realm_access") or {}
    raw_roles = realm_access.get("roles") or []
    return [r for r in raw_roles if r in KNOWN_ROLES]


def extract_identity(claims: dict[str, Any]) -> tuple[str, str, str]:
    """Return ``(sub, email, name)`` from a Keycloak token's claims."""
    sub = str(claims.get("sub", ""))
    email = str(claims.get("email", ""))
    name = claims.get("name") or claims.get("preferred_username") or ""
    return sub, email, str(name)
