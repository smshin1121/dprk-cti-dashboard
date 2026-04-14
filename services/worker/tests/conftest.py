"""Shared pytest fixtures for the worker test suite."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from worker.bootstrap.tables import metadata


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Fresh in-memory SQLite database with the bootstrap schema applied.

    Each test gets its own engine (and therefore its own isolated
    database) so upsert idempotency tests can't interfere with each
    other. The FK pragma is enabled so stray bad inserts fail loud
    instead of silently orphaning rows — sqlite's default is to treat
    FOREIGN KEY clauses as comments.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_connection, _connection_record) -> None:
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Open a session, commit at the end so transient state is visible
    for cross-call idempotency assertions."""
    session_factory = async_sessionmaker(
        db_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as session:
        yield session
        await session.commit()
