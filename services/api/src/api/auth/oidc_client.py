"""Authlib-based async OIDC client for Keycloak.

This module wraps :class:`authlib.integrations.httpx_client.AsyncOAuth2Client`
and the OpenID Connect discovery document so that the rest of the auth
package never has to talk to httpx directly.

Discovery metadata is cached for 5 minutes so we do not hit Keycloak's
``/.well-known/openid-configuration`` on every login or callback.
"""

from __future__ import annotations

import base64
import hashlib
import time
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client

from ..config import get_settings


def _pkce_s256_challenge(verifier: str) -> str:
    """Compute the PKCE S256 code_challenge for a given verifier.

    We compute this ourselves rather than relying on Authlib's per-call
    auto-derivation, which only fires when ``code_challenge_method`` is set
    at constructor time. Doing it explicitly keeps the behavior version-
    independent and makes the value testable.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

# How long to cache the discovery document, in seconds.
_DISCOVERY_TTL_SECONDS = 300

_discovery_cache: dict[str, Any] | None = None
_discovery_cached_at: float = 0.0


class OIDCDiscoveryError(RuntimeError):
    """Raised when the OpenID Connect discovery document cannot be fetched."""


async def discover_metadata() -> dict[str, Any]:
    """Return the cached discovery document, refreshing it on TTL expiry."""
    global _discovery_cache, _discovery_cached_at

    now = time.monotonic()
    if _discovery_cache is not None and (now - _discovery_cached_at) < _DISCOVERY_TTL_SECONDS:
        return _discovery_cache

    settings = get_settings()
    url = f"{settings.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            metadata = resp.json()
    except httpx.HTTPError as exc:
        raise OIDCDiscoveryError(f"failed to fetch OIDC metadata from {url}: {exc}") from exc

    _discovery_cache = metadata
    _discovery_cached_at = now
    return metadata


@lru_cache(maxsize=1)
def get_oidc_client() -> AsyncOAuth2Client:
    """Singleton Authlib async OAuth2 client for the API service."""
    settings = get_settings()
    return AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        scope="openid email profile",
        token_endpoint_auth_method="client_secret_post",
    )


async def build_authorization_url(
    redirect_uri: str,
    state: str,
    code_verifier: str,
) -> str:
    """Build the Keycloak authorization URL with PKCE S256 challenge.

    The challenge is computed explicitly via :func:`_pkce_s256_challenge`
    and passed as ``code_challenge``, so the resulting URL always carries
    both ``code_challenge`` and ``code_challenge_method=S256``. Keycloak
    will then enforce verifier-challenge matching at the token endpoint.
    """
    metadata = await discover_metadata()
    auth_endpoint = metadata["authorization_endpoint"]
    challenge = _pkce_s256_challenge(code_verifier)

    client = get_oidc_client()
    url, _ = client.create_authorization_url(
        auth_endpoint,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return url


async def exchange_code(
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens at the token endpoint."""
    metadata = await discover_metadata()
    token_endpoint = metadata["token_endpoint"]

    client = get_oidc_client()
    token = await client.fetch_token(
        token_endpoint,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        grant_type="authorization_code",
    )
    return dict(token)


async def build_logout_url(redirect_uri: str) -> str:
    """Build the Keycloak end-session URL for RP-initiated logout."""
    metadata = await discover_metadata()
    end_session = metadata.get("end_session_endpoint")
    if not end_session:
        # Fall back to the canonical Keycloak path.
        settings = get_settings()
        end_session = (
            f"{settings.oidc_issuer_url.rstrip('/')}/protocol/openid-connect/logout"
        )
    sep = "&" if "?" in end_session else "?"
    return f"{end_session}{sep}{urlencode({'post_logout_redirect_uri': redirect_uri})}"
