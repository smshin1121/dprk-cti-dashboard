"""Shared fixtures for llm-proxy integration tests — PR #18 Group D.

The module-level ``os.environ.setdefault`` block runs BEFORE any
test imports ``llm_proxy.main`` — this pins ``APP_ENV=test``
(forcing slowapi to ``memory://``), a stable internal token, and
the ``mock`` provider BEFORE ``main.py`` captures those values at
import time via ``_INTERNAL_TOKEN`` and ``get_settings()``.

Fixtures exported:

- ``app_under_test`` — the FastAPI ``app`` with a clean
  ``dependency_overrides`` dict between tests.
- ``test_client`` — authenticated ``TestClient`` carrying the
  fixed ``X-Internal-Token`` header by default. Tests that want
  to exercise 401 / 503 remove / empty the header on the call.
- ``integration_redis`` — a freshly-flushed
  ``fakeredis.aioredis.FakeRedis`` wired into the route via
  ``get_redis_client`` dependency override.
- ``override_provider`` / ``provider_with_handler`` — helpers
  that swap in a MockEmbeddingProvider, a counting wrapper, or
  an ``OpenAIEmbeddingProvider`` backed by
  ``httpx.MockTransport`` for 502 / 504 / 429 scenarios.
- ``reset_limiter`` (autouse) — ``get_limiter().reset()`` between
  every test so the 30/minute bucket never leaks across tests.
"""

from __future__ import annotations

import os

# NOTE: order matters. Every ``os.environ.setdefault`` here MUST
# run before the first ``from llm_proxy.main import app`` in any
# test module, so pin them at conftest load.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROXY_INTERNAL_TOKEN", "integration-test-token")
os.environ.setdefault("LLM_PROXY_EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("LLM_PROXY_EMBEDDING_MODEL", "text-embedding-3-small")

from collections.abc import Callable, Iterator  # noqa: E402

import fakeredis.aioredis  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from llm_proxy.config import get_settings  # noqa: E402
from llm_proxy.dependencies import (  # noqa: E402
    get_embedding_provider,
    get_redis_client,
)
from llm_proxy.main import app as _app  # noqa: E402
from llm_proxy.providers.base import EmbeddingProvider, ProviderResult  # noqa: E402
from llm_proxy.providers.mock import MockEmbeddingProvider  # noqa: E402
from llm_proxy.providers.openai import (  # noqa: E402
    OPENAI_EMBEDDINGS_URL,
    OpenAIEmbeddingProvider,
)
from llm_proxy.rate_limit import get_limiter  # noqa: E402


INTEGRATION_TOKEN: str = os.environ["LLM_PROXY_INTERNAL_TOKEN"]
"""Fixed X-Internal-Token value for integration tests."""


# ---------------------------------------------------------------------------
# App + client
# ---------------------------------------------------------------------------


@pytest.fixture
def app_under_test() -> Iterator[FastAPI]:
    """Yield the FastAPI ``app`` with ``dependency_overrides`` wiped
    after each test so overrides from one test cannot leak into the
    next."""
    _app.dependency_overrides.clear()
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def test_client(app_under_test: FastAPI) -> TestClient:
    """TestClient with the integration X-Internal-Token header."""
    client = TestClient(app_under_test)
    client.headers.update({"X-Internal-Token": INTEGRATION_TOKEN})
    return client


# ---------------------------------------------------------------------------
# Redis override
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def integration_redis(
    app_under_test: FastAPI,
) -> fakeredis.aioredis.FakeRedis:
    """Fresh FakeRedis wired in as the route's Redis client.

    Flushes at teardown so the next test sees a cold cache.
    """
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def _override() -> fakeredis.aioredis.FakeRedis:
        return client

    app_under_test.dependency_overrides[get_redis_client] = _override

    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


# ---------------------------------------------------------------------------
# Provider overrides
# ---------------------------------------------------------------------------


class CountingMockProvider(MockEmbeddingProvider):
    """MockEmbeddingProvider that records every batch dispatched.

    ``calls`` holds the per-call text list exactly as the route
    passed it to ``embed``. Lets cache-round-trip + partial-hit
    tests assert the provider was NOT invoked on a full hit and
    that a partial-hit dispatches only the miss subset.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[str]] = []

    async def embed(
        self, texts: list[str], model: str
    ) -> ProviderResult:
        self.calls.append(list(texts))
        return await super().embed(texts, model)


@pytest.fixture
def counting_provider(
    app_under_test: FastAPI,
) -> CountingMockProvider:
    """Inject a CountingMockProvider via dependency override."""
    provider = CountingMockProvider()

    def _override() -> EmbeddingProvider:
        return provider

    app_under_test.dependency_overrides[get_embedding_provider] = _override
    return provider


@pytest.fixture
def provider_with_handler(
    app_under_test: FastAPI,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], OpenAIEmbeddingProvider]:
    """Inject an OpenAIEmbeddingProvider backed by an httpx.MockTransport.

    Usage::

        provider = provider_with_handler(lambda req: httpx.Response(503))
        # now /api/v1/embedding dispatches through this provider

    Tests use this to drive 502 / 504 / 429 via upstream error
    responses without reaching the real OpenAI API.
    """

    def _builder(
        handler: Callable[[httpx.Request], httpx.Response],
        *,
        timeout_seconds: float = 10.0,
    ) -> OpenAIEmbeddingProvider:
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(
            transport=transport, timeout=timeout_seconds
        )
        provider = OpenAIEmbeddingProvider(
            api_key="sk-integration-test",
            client=client,
            timeout_seconds=timeout_seconds,
        )

        def _override() -> EmbeddingProvider:
            return provider

        app_under_test.dependency_overrides[get_embedding_provider] = _override
        return provider

    return _builder


# ---------------------------------------------------------------------------
# slowapi limiter reset
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_limiter() -> Iterator[None]:
    """Clear slowapi's ``memory://`` bucket between every test.

    Without this, the 30/minute bucket leaks across tests — the
    first run's requests count against the second run's budget,
    which breaks the rate-limit drain test deterministically and
    the other tests flakily (a failing run leaves counters at an
    arbitrary offset).
    """
    get_limiter().reset()
    yield
    get_limiter().reset()


# ---------------------------------------------------------------------------
# Shared helpers used by multiple test files
# ---------------------------------------------------------------------------


def openai_happy_body(
    texts: list[str],
    *,
    model_returned: str = "text-embedding-3-small",
    dim: int = 1536,
) -> dict:
    """Build an OpenAI-shaped 200 response body for ``texts``.

    Kept here (mirroring the Group B unit-test helper) so both
    layers speak the same wire shape.
    """
    return {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "embedding": [0.01 * (i + 1)] * dim,
                "index": i,
            }
            for i, _text in enumerate(texts)
        ],
        "model": model_returned,
        "usage": {
            "prompt_tokens": sum(max(1, len(t) // 4) for t in texts),
            "total_tokens": sum(max(1, len(t) // 4) for t in texts),
        },
    }


__all__ = [
    "CountingMockProvider",
    "INTEGRATION_TOKEN",
    "OPENAI_EMBEDDINGS_URL",
    "get_settings",
    "openai_happy_body",
]
