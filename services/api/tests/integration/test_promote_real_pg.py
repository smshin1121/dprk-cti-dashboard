"""Real-PostgreSQL integration tests — PR #10 Phase 2.1 Group H acceptance.

Plan §5.2 locks 5 scenarios the PR cannot ship without. These run
against a real Postgres+pgvector instance (alembic-upgraded head)
so PG-specific behavior — SERIALIZABLE-ish row locking via
``SELECT ... FOR UPDATE``, ``INSERT ... ON CONFLICT`` semantics
against unique indexes and constraints, JSONB serialization of
``audit_log.diff_jsonb`` — is actually exercised. Sqlite-backed
tests cannot verify these properties and must not be treated as
sufficient evidence.

Mapping to plan §5.2 (1:1):

  1. test_scenario_1_approve_happy_path
     — Approve a pending row → reports=1, sources=1, staging
     promoted, audit_log=1 (action=REPORT_PROMOTED,
     attached_existing=false). STAGING_APPROVED NEVER emitted.

  2. test_scenario_2_reject_with_decision_reason
     — Reject a pending row with a reason → staging=rejected,
     decision_reason stored, audit_log=1
     (action=STAGING_REJECTED, diff.reviewer_notes=<given>).
     Empty/whitespace-only decision_reason surfaces 422.

  3. test_scenario_3_duplicate_url_canonical
     — Pre-existing reports row with matching url_canonical →
     approve attaches to existing (no new INSERT), staging
     promoted with existing report_id, audit_log=1 with
     attached_existing=TRUE.

  4. test_scenario_4_concurrent_approve_race
     — Two asyncio.gather'd POSTs on the same staging id → exactly
     one 200 ('promoted'), exactly one 409 Conflict with
     current_status='promoted'. PG FOR UPDATE lock + conditional
     UPDATE deliver single-winner.

  5. test_scenario_5_mid_txn_failure_rolls_back_all
     — upsert_report monkeypatched to raise AFTER the 'unknown'
     source has been INSERTed → handler returns 500, but reports,
     sources, audit_log are ALL empty and staging stays pending.
     Proves production writes AND audit are atomic with the
     transaction boundary.

Skipped when ``POSTGRES_TEST_URL`` is unset so developers can still
run ``pytest tests/`` without spinning up Postgres. CI sets the env
var for the api-integration job.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
from typing import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# Windows fix: psycopg async driver requires SelectorEventLoop.
# On Linux CI runners this is a no-op.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


pytestmark = pytest.mark.integration


_PG_URL = os.environ.get("POSTGRES_TEST_URL")

if not _PG_URL:
    pytest.skip(
        "POSTGRES_TEST_URL not set — real-PG integration tests skipped. "
        "Set the env var to a SQLAlchemy async URL pointing at an "
        "alembic-upgraded-head Postgres instance to run this module.",
        allow_module_level=True,
    )


from api.promote import service as promote_service  # noqa: E402
from api.promote.service import ACTION_REPORT_PROMOTED, ACTION_STAGING_REJECTED  # noqa: E402
from api.tables import (  # noqa: E402
    audit_log_table,
    reports_table,
    sources_table,
    staging_table,
)


REVIEW_URL = "/api/v1/reports/review/{staging_id}"


# ---------------------------------------------------------------------------
# Engine / session fixtures — shared module-level engine for speed.
# Between tests we TRUNCATE the mutable tables so each test sees an empty DB.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_PG_URL, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_pg(pg_engine: AsyncEngine) -> None:
    """Truncate mutable tables between tests.

    CASCADE covers the FK chain from reports → incident_sources /
    report_tags / report_codenames. RESTART IDENTITY resets BIGINT
    sequences so each test sees deterministic IDs starting at 1 —
    that matters for test_scenario_1 which asserts on
    ``report_snapshot.id == 1`` etc.
    """
    async with pg_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "TRUNCATE staging, reports, sources, audit_log "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def pg_sessionmaker(
    pg_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def pg_session(
    pg_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Standalone session for seed/assert queries in tests. Not used
    by the handler — that path goes through the ASGI dep override."""
    async with pg_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def review_client(
    pg_sessionmaker: async_sessionmaker[AsyncSession],
    session_store,
    fake_redis,
) -> AsyncIterator[AsyncClient]:
    """ASGI client with get_db overridden to hand out sessions bound
    to the real-PG engine (not the conftest AsyncMock). Each request
    gets its own session, which is necessary for the concurrent-race
    scenario to run two independent transactions."""
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with pg_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store

    # raise_app_exceptions=False lets scenario 5 observe the 500
    # response instead of having httpx re-raise the RuntimeError back
    # to the test. The other scenarios do not trigger uncaught
    # exceptions so the flag is irrelevant to them.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_pending_staging(
    session: AsyncSession,
    *,
    url_canonical: str = "http://integration.test/a",
    title: str = "Integration Test Title",
) -> int:
    """Insert one pending staging row and commit. Returns its id."""
    result = await session.execute(
        sa.insert(staging_table)
        .values(
            url_canonical=url_canonical,
            url=url_canonical,
            title=title,
            published=dt.datetime(2026, 4, 17, tzinfo=dt.timezone.utc),
            status="pending",
        )
        .returning(staging_table.c.id)
    )
    staging_id = result.scalar_one()
    await session.commit()
    return staging_id


async def _count(session: AsyncSession, table: sa.Table) -> int:
    return (
        await session.execute(sa.select(sa.func.count()).select_from(table))
    ).scalar_one()


async def _approve_cookie(make_session_cookie, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# Scenario 1 — approve happy path
# ---------------------------------------------------------------------------


async def test_scenario_1_approve_happy_path(
    review_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 1. Approve creates exactly the locked
    production-side footprint: 1 reports row, 1 'unknown' source
    (staging.source_id was NULL), staging promoted, exactly ONE
    audit row with REPORT_PROMOTED + attached_existing=false.
    STAGING_APPROVED must NEVER be emitted (plan §2.1 D4 drop)."""
    staging_id = await _seed_pending_staging(pg_session)
    cookie = await _approve_cookie(make_session_cookie)

    resp = await review_client.post(
        REVIEW_URL.format(staging_id=staging_id),
        cookies={"dprk_cti_session": cookie},
        json={"decision": "approve", "notes": "scenario 1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["staging_id"] == staging_id
    assert body["status"] == "promoted"
    assert isinstance(body["report_id"], int)

    # Production footprint
    assert await _count(pg_session, reports_table) == 1
    assert await _count(pg_session, sources_table) == 1
    audit_rows = (
        await pg_session.execute(
            sa.select(audit_log_table.c.action, audit_log_table.c.diff_jsonb)
        )
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == ACTION_REPORT_PROMOTED
    diff = audit_rows[0].diff_jsonb
    assert diff["attached_existing"] is False
    assert diff["reviewer_notes"] == "scenario 1"
    assert diff["from_staging_id"] == staging_id

    # STAGING_APPROVED must not exist anywhere in audit_log.
    approved_rows = (
        await pg_session.execute(
            sa.select(sa.func.count())
            .select_from(audit_log_table)
            .where(audit_log_table.c.action == "STAGING_APPROVED")
        )
    ).scalar_one()
    assert approved_rows == 0

    # Staging row state
    staging_now = (
        await pg_session.execute(
            sa.select(
                staging_table.c.status,
                staging_table.c.reviewed_by,
                staging_table.c.promoted_report_id,
                staging_table.c.decision_reason,
            ).where(staging_table.c.id == staging_id)
        )
    ).one()
    assert staging_now.status == "promoted"
    assert staging_now.reviewed_by is not None
    assert staging_now.promoted_report_id == body["report_id"]
    assert staging_now.decision_reason is None


# ---------------------------------------------------------------------------
# Scenario 2 — reject with decision_reason
# ---------------------------------------------------------------------------


async def test_scenario_2_reject_with_decision_reason(
    review_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 2. Reject stores decision_reason on the
    row, notes only in the audit diff. No production writes."""
    staging_id = await _seed_pending_staging(pg_session)
    cookie = await _approve_cookie(make_session_cookie)

    resp = await review_client.post(
        REVIEW_URL.format(staging_id=staging_id),
        cookies={"dprk_cti_session": cookie},
        json={
            "decision": "reject",
            "decision_reason": "duplicate of report #42",
            "notes": "discussed in #ops",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["report_id"] is None

    staging_now = (
        await pg_session.execute(
            sa.select(
                staging_table.c.status,
                staging_table.c.decision_reason,
                staging_table.c.promoted_report_id,
            ).where(staging_table.c.id == staging_id)
        )
    ).one()
    assert staging_now.status == "rejected"
    assert staging_now.decision_reason == "duplicate of report #42"
    assert staging_now.promoted_report_id is None

    # No production-table writes.
    assert await _count(pg_session, reports_table) == 0
    assert await _count(pg_session, sources_table) == 0

    # Audit: exactly 1 row, STAGING_REJECTED, reviewer_notes in diff.
    audit_rows = (
        await pg_session.execute(
            sa.select(
                audit_log_table.c.action,
                audit_log_table.c.entity,
                audit_log_table.c.diff_jsonb,
            )
        )
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == ACTION_STAGING_REJECTED
    assert audit_rows[0].entity == "staging"
    assert audit_rows[0].diff_jsonb["decision_reason"] == "duplicate of report #42"
    assert audit_rows[0].diff_jsonb["reviewer_notes"] == "discussed in #ops"


async def test_scenario_2_reject_empty_reason_returns_422(
    review_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Completes plan §5.2 scenario 2's validation assertion —
    empty / whitespace-only decision_reason must surface as 422,
    not 500, and must leave the staging row untouched."""
    staging_id = await _seed_pending_staging(pg_session)
    cookie = await _approve_cookie(make_session_cookie)

    resp = await review_client.post(
        REVIEW_URL.format(staging_id=staging_id),
        cookies={"dprk_cti_session": cookie},
        json={"decision": "reject", "decision_reason": "   \t  "},
    )
    assert resp.status_code == 422

    status_now = (
        await pg_session.execute(
            sa.select(staging_table.c.status).where(
                staging_table.c.id == staging_id
            )
        )
    ).scalar_one()
    assert status_now == "pending"


# ---------------------------------------------------------------------------
# Scenario 3 — duplicate url_canonical (attached_existing=true)
# ---------------------------------------------------------------------------


async def test_scenario_3_duplicate_url_canonical(
    review_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 3. Pre-existing reports row with matching
    url_canonical → approve attaches, no INSERT, staging promoted
    with the existing report_id. diff.attached_existing=TRUE."""
    # Pre-seed a source + report under url_canonical that the
    # staging row will collide with. Use a non-'unknown' source so
    # we can assert 'unknown' was never created for this promote
    # (staging.source_id is reused — the existing report's source
    # stays unchanged by ON CONFLICT DO NOTHING semantics).
    src_result = await pg_session.execute(
        sa.insert(sources_table)
        .values(name="original-vendor", type="vendor")
        .returning(sources_table.c.id)
    )
    existing_source_id = src_result.scalar_one()
    rep_result = await pg_session.execute(
        sa.insert(reports_table)
        .values(
            published=dt.date(2026, 1, 1),
            source_id=existing_source_id,
            title="original title",
            url="http://original.example/a",
            url_canonical="http://dup.example/same",
            sha256_title="a" * 64,
        )
        .returning(reports_table.c.id)
    )
    existing_report_id = rep_result.scalar_one()
    await pg_session.commit()

    # Stage a row hitting the same url_canonical — different title,
    # different staging source_id (NULL triggers 'unknown' upsert).
    staging_id = await _seed_pending_staging(
        pg_session,
        url_canonical="http://dup.example/same",
        title="staging title that must NOT overwrite",
    )
    cookie = await _approve_cookie(make_session_cookie)

    resp = await review_client.post(
        REVIEW_URL.format(staging_id=staging_id),
        cookies={"dprk_cti_session": cookie},
        json={"decision": "approve"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_id"] == existing_report_id

    # No new report inserted.
    assert await _count(pg_session, reports_table) == 1
    # Original title preserved — DO NOTHING invariant.
    title_now = (
        await pg_session.execute(
            sa.select(reports_table.c.title).where(
                reports_table.c.id == existing_report_id
            )
        )
    ).scalar_one()
    assert title_now == "original title"

    # Staging points at the existing report id.
    promoted_id = (
        await pg_session.execute(
            sa.select(staging_table.c.promoted_report_id).where(
                staging_table.c.id == staging_id
            )
        )
    ).scalar_one()
    assert promoted_id == existing_report_id

    # Audit diff records the attach.
    audit_diff = (
        await pg_session.execute(sa.select(audit_log_table.c.diff_jsonb))
    ).scalar_one()
    assert audit_diff["attached_existing"] is True
    assert audit_diff["from_staging_id"] == staging_id


# ---------------------------------------------------------------------------
# Scenario 4 — concurrent approve race (single-winner proof)
# ---------------------------------------------------------------------------


async def test_scenario_4_concurrent_approve_race(
    review_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
) -> None:
    """Plan §5.2 scenario 4. Two asyncio.gather'd POSTs on the same
    staging id. The winner commits status='promoted' under its
    FOR UPDATE lock; the loser sees status!='pending' after the
    lock releases and raises StagingAlreadyDecidedError → 409 with
    current_status='promoted'.

    This is the ONE invariant the sqlite-based Group D tests cannot
    verify — SQLite silently drops FOR UPDATE. Real-PG proves the
    row lock + conditional UPDATE deliver single-winner under
    actual concurrency."""
    staging_id = await _seed_pending_staging(pg_session)
    cookie = await _approve_cookie(make_session_cookie)

    async def _post() -> tuple[int, dict]:
        r = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        return r.status_code, r.json()

    results = await asyncio.gather(_post(), _post(), _post())
    status_codes = sorted(code for code, _ in results)

    # Exactly one 200 and the rest are 409 — no 500s, no duplicates.
    assert status_codes.count(200) == 1
    assert status_codes.count(409) == len(results) - 1
    assert 500 not in status_codes

    # The 409 body must use the narrowed DecidedStatus enum.
    conflict_bodies = [body for code, body in results if code == 409]
    for body in conflict_bodies:
        assert body["current_status"] == "promoted"
        assert body["error"] == "already_decided"
        # The forbidden enum value must not leak here — plan §2.2 B
        # lock verified under actual concurrency.
        assert body["current_status"] != "approved"

    # Exactly one reports row + one audit row — the LOSERS rolled back.
    assert await _count(pg_session, reports_table) == 1
    assert await _count(pg_session, audit_log_table) == 1

    status_now = (
        await pg_session.execute(
            sa.select(staging_table.c.status).where(
                staging_table.c.id == staging_id
            )
        )
    ).scalar_one()
    assert status_now == "promoted"


# ---------------------------------------------------------------------------
# Scenario 5 — mid-transaction failure rolls back EVERYTHING
# ---------------------------------------------------------------------------


async def test_scenario_5_mid_txn_failure_rolls_back_all(
    review_client: AsyncClient,
    make_session_cookie,
    pg_session: AsyncSession,
    clean_pg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan §5.2 scenario 5. Inject a failure during upsert_report
    (AFTER the 'unknown' source has been INSERTed). The handler's
    async with session.begin() must roll back the ENTIRE batch:
    zero reports, zero sources, zero audit rows, staging still
    pending.

    Proves both:
      (a) production writes (sources INSERT) roll back even when
          they succeeded at the SQL level; and
      (b) audit_log writes are INSIDE the same transaction — so a
          pre-audit failure means audit_log NEVER lands. PR #7/8/9's
          worker-side 'savepoint + swallow audit error' pattern is
          explicitly rejected here (plan §2.2 A)."""
    staging_id = await _seed_pending_staging(pg_session)
    cookie = await _approve_cookie(make_session_cookie)

    async def _boom(*, session, **kwargs):
        raise RuntimeError("scenario 5 — upsert_report injected failure")

    monkeypatch.setattr(promote_service, "upsert_report", _boom)

    resp = await review_client.post(
        REVIEW_URL.format(staging_id=staging_id),
        cookies={"dprk_cti_session": cookie},
        json={"decision": "approve"},
    )
    # FastAPI's default handler serializes the uncaught RuntimeError as 500.
    assert resp.status_code == 500

    # Full rollback proof — nothing leaked.
    assert await _count(pg_session, reports_table) == 0
    assert await _count(pg_session, sources_table) == 0
    assert await _count(pg_session, audit_log_table) == 0

    staging_now = (
        await pg_session.execute(
            sa.select(
                staging_table.c.status,
                staging_table.c.reviewed_by,
                staging_table.c.reviewed_at,
                staging_table.c.promoted_report_id,
                staging_table.c.decision_reason,
            ).where(staging_table.c.id == staging_id)
        )
    ).one()
    assert staging_now.status == "pending"
    assert staging_now.reviewed_by is None
    assert staging_now.reviewed_at is None
    assert staging_now.promoted_report_id is None
    assert staging_now.decision_reason is None
