"""Async SQLAlchemy engine + session factory.

A single engine is built lazily from :func:`get_settings` and reused for
the lifetime of the process. ``get_db`` is a FastAPI dependency that yields
an ``AsyncSession`` and ensures it is closed afterwards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings


def _to_async_url(url: str) -> str:
    """Coerce a sync psycopg URL into the async psycopg driver form."""
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg_async://", 1)
    return url


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        _to_async_url(settings.database_url),
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_get_engine(), expire_on_commit=False)


def __getattr__(name: str):
    """Lazily expose the cached async engine as ``db.engine``.

    Module-level attribute access is used (PEP 562) so that simply importing
    ``api.db`` does not eagerly construct the engine — only callers that touch
    ``engine`` (e.g. telemetry setup) trigger creation.
    """
    if name == "engine":
        return _get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Public alias matching the spec.
def AsyncSessionLocal() -> AsyncSession:  # noqa: N802 — historical name
    return _get_sessionmaker()()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a single async session per request."""
    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            await session.close()
