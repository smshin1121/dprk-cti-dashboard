"""FastAPI dependency providers — PR #18 Group C.

Factories that resolve at request time from :class:`Settings`. Kept
in a dedicated module (instead of inside ``routers/embedding.py``)
so tests can override them via ``app.dependency_overrides[...]``
without importing the route module's internals.

- :func:`get_redis_client` returns a module-cached ``Redis`` bound
  to ``settings.redis_url``. Returns ``None`` in tests that
  explicitly override this dependency with a fake or ``None``.
- :func:`get_http_client` returns a module-cached ``httpx.AsyncClient``
  with the configured upstream timeout. Used by
  :func:`get_embedding_provider` to build ``OpenAIEmbeddingProvider``.
- :func:`get_embedding_provider` picks Mock vs OpenAI per
  ``settings.llm_proxy_embedding_provider``. Shipped as a dependency
  so Group D integration tests can swap a deterministic mock or
  httpx-mock-backed OpenAI provider in without env gymnastics.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends
from redis.asyncio import Redis

from .config import Settings, get_settings
from .providers.base import EmbeddingProvider
from .providers.mock import MockEmbeddingProvider
from .providers.openai import OpenAIEmbeddingProvider


@lru_cache(maxsize=1)
def _shared_redis_client() -> Redis:
    """Process-wide Redis client. Created lazily on first use.

    ``Redis.from_url`` does not connect eagerly; the first command
    opens the connection. ``decode_responses=True`` matches what
    ``cache.py`` expects (``json.loads`` on string values).
    """
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Redis | None:
    """FastAPI dependency: return the shared Redis client or ``None``.

    Tests override this via ``app.dependency_overrides[get_redis_client]``
    to inject ``fakeredis.aioredis.FakeRedis`` or ``None`` to exercise
    the graceful-degrade path in the route body.
    """
    _ = settings  # kept in signature so the override surface is stable
    return _shared_redis_client()


@lru_cache(maxsize=1)
def _shared_http_client() -> httpx.AsyncClient:
    """Process-wide ``httpx.AsyncClient`` with the configured timeout.

    Connection pooling across requests amortizes TLS setup cost.
    """
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.llm_proxy_embedding_timeout_seconds),
    )


def get_http_client() -> httpx.AsyncClient:
    """Return the shared ``httpx.AsyncClient``. Overridable in tests."""
    return _shared_http_client()


def get_embedding_provider(
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> EmbeddingProvider:
    """Pick Mock vs OpenAI per ``LLM_PROXY_EMBEDDING_PROVIDER``.

    ``config.Settings`` startup validators guarantee the OpenAI
    branch has a non-empty ``OPENAI_API_KEY`` and that ``mock`` is
    not selected under ``APP_ENV=prod`` — so no runtime branch here
    needs to re-check those invariants.
    """
    if settings.llm_proxy_embedding_provider == "mock":
        return MockEmbeddingProvider()
    return OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        client=client,
        timeout_seconds=settings.llm_proxy_embedding_timeout_seconds,
    )


__all__ = [
    "get_embedding_provider",
    "get_http_client",
    "get_redis_client",
]
