"""Unit tests for ``llm_proxy.rate_limit`` — PR #18 Group A.

Draft v2 D5 Draft: key function SHA-256-hashes the X-Internal-Token
header so the raw secret never reaches slowapi's Redis keys or
logs. These tests pin that invariant — a regression that writes the
raw token to the key flips them red at CI time.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest

from llm_proxy.config import Settings
from llm_proxy.rate_limit import (
    _resolve_storage_uri,
    build_limiter,
    token_principal_key,
)


def _make_request(token: str | None) -> MagicMock:
    """Minimal Request stub — slowapi's key function only reads
    ``request.headers.get("X-Internal-Token", "")``."""
    req = MagicMock()
    req.headers = {"X-Internal-Token": token} if token is not None else {}
    return req


class TestTokenPrincipalKeyHashesBeforeStorage:
    """Raw token value must NEVER appear in the key."""

    def test_key_is_sha256_prefix_of_token(self) -> None:
        token = "secret-shared-token-abc123"
        expected = "token:" + hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()[:16]
        assert token_principal_key(_make_request(token)) == expected

    def test_raw_token_not_in_key(self) -> None:
        """Regression guard — raw token string never appears in the
        returned key. A future edit that accidentally uses
        ``f"token:{token[:16]}"`` would flip this red."""
        token = "SECRET-CANARY-DO-NOT-LEAK-0xFEED"
        key = token_principal_key(_make_request(token))
        assert "SECRET" not in key
        assert "CANARY" not in key
        assert "FEED" not in key

    def test_same_token_same_key(self) -> None:
        k1 = token_principal_key(_make_request("my-token"))
        k2 = token_principal_key(_make_request("my-token"))
        assert k1 == k2

    def test_different_tokens_different_keys(self) -> None:
        k1 = token_principal_key(_make_request("token-a"))
        k2 = token_principal_key(_make_request("token-b"))
        assert k1 != k2

    def test_missing_token_header_returns_anonymous(self) -> None:
        # The X-Internal-Token middleware rejects unauthed requests
        # with 401 before slowapi even runs, so this branch is
        # defense-only. Still must not crash.
        assert token_principal_key(_make_request(None)) == "anonymous"

    def test_empty_token_header_returns_anonymous(self) -> None:
        assert token_principal_key(_make_request("")) == "anonymous"


class TestStorageUriEnvBranches:
    """Storage URI is branched per APP_ENV (test = forced memory,
    dev / prod = settings.redis_url)."""

    def test_test_env_forces_memory(self) -> None:
        settings = Settings(
            app_env="test",
            llm_proxy_embedding_provider="mock",
            redis_url="redis://localhost:6379/0",
        )
        assert _resolve_storage_uri(settings) == "memory://"

    def test_dev_env_uses_redis_url(self) -> None:
        settings = Settings(
            app_env="dev",
            llm_proxy_embedding_provider="mock",
            redis_url="redis://example:6379/1",
        )
        assert _resolve_storage_uri(settings) == "redis://example:6379/1"

    def test_prod_env_uses_redis_url(self) -> None:
        settings = Settings(
            app_env="prod",
            llm_proxy_embedding_provider="openai",
            openai_api_key="sk-test",
            redis_url="redis://prod-redis:6379/0",
        )
        assert _resolve_storage_uri(settings) == "redis://prod-redis:6379/0"


class TestBuildLimiter:
    """Limiter construction glues key_func + storage together."""

    def test_returns_slowapi_limiter_in_test_env(self) -> None:
        from slowapi import Limiter

        settings = Settings(
            app_env="test",
            llm_proxy_embedding_provider="mock",
        )
        limiter = build_limiter(settings)
        assert isinstance(limiter, Limiter)

    def test_default_limits_is_empty(self) -> None:
        """No global default — each route opts in. This means the
        existing /healthz and /provider/meta endpoints stay
        unrated when the new embedding route lands."""
        settings = Settings(
            app_env="test",
            llm_proxy_embedding_provider="mock",
        )
        limiter = build_limiter(settings)
        assert limiter._default_limits == []

    def test_key_func_is_our_token_hasher(self) -> None:
        settings = Settings(
            app_env="test",
            llm_proxy_embedding_provider="mock",
        )
        limiter = build_limiter(settings)
        # Pin the identity — a regression that swaps our key_func
        # for ``get_remote_address`` (which would bucket by IP and
        # defeat per-caller accounting) flips this red.
        assert limiter._key_func is token_principal_key
