"""Shared pytest fixtures for llm-proxy — PR #18 Group A."""

from __future__ import annotations

import os

import fakeredis.aioredis
import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _test_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force APP_ENV=test unless the test explicitly overrides.

    Matches services/api's conftest posture: most unit tests don't
    care about env, and the few that do (test_config's mock-in-prod
    guard) override inside the test body with monkeypatch.
    """
    monkeypatch.setenv("APP_ENV", "test")


@pytest_asyncio.fixture
async def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """In-memory Redis for cache + rate-limit tests.

    Lifted from services/api's fake_redis fixture — same behavior,
    same cleanup semantics. Each test gets an isolated instance so
    no cross-test key pollution.
    """
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()
