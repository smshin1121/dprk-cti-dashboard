"""Unit tests for ``api.promote.service`` against in-memory SQLite.

Covers the five reviewer-checklist invariants locked in plan §2.2:

1. Single-transaction boundary (rollback on mid-step failure leaves
   staging at pending, zero production writes, zero audit rows).
2. FOR UPDATE + conditional UPDATE — structurally present; full
   single-winner proof is Group H real-PG (sqlite ignores FOR UPDATE).
3. Approve emits EXACTLY one ``REPORT_PROMOTED`` audit event — no
   ``STAGING_APPROVED`` ghost event.
4. Reject writes ``decision_reason`` to the staging column and routes
   ``notes`` only to ``audit_log.diff_jsonb.reviewer_notes``.
5. Mid-transaction failure restores the row to ``pending`` status
   with no audit footprint.

Transaction boundary: the service assumes the CALLER has wrapped the
call in ``async with session.begin():``. Tests here use the
``run_promote`` / ``run_reject`` helpers (below) to honor that
contract — direct service calls without the wrapper would break the
single-transaction invariant.

Tests use in-memory aiosqlite so they cannot verify PG-specific
concurrency guarantees (FOR UPDATE row locking, SERIALIZABLE
isolation). Group H's real-PG integration job is the authoritative
check for concurrent writers.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from api.promote import service as promote_service
from api.promote.errors import (
    PromoteValidationError,
    StagingAlreadyDecidedError,
    StagingInvalidStateError,
    StagingNotFoundError,
)
from api.promote.service import (
    ACTION_REPORT_PROMOTED,
    ACTION_STAGING_REJECTED,
    ENTITY_REPORTS,
    ENTITY_STAGING,
    UNKNOWN_SOURCE_NAME,
    promote_staging_row,
    reject_staging_row,
)
from api.tables import (
    audit_log_table,
    metadata,
    reports_table,
    sources_table,
    staging_table,
)


# ---------------------------------------------------------------------------
# Fixtures — per-test fresh schema
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncSession:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers — run the service inside a caller-owned transaction
# ---------------------------------------------------------------------------


async def run_promote(session: AsyncSession, **kwargs):
    """Wrap the service call the way the router will: caller owns
    ``async with session.begin()``. Any read queries the test ran
    before this call must be followed by ``session.commit()`` so
    SA's auto-begin transaction is closed before a fresh one opens
    here — tests enforce this via ``_reset`` below."""
    async with session.begin():
        return await promote_staging_row(session, **kwargs)


async def run_reject(session: AsyncSession, **kwargs):
    async with session.begin():
        return await reject_staging_row(session, **kwargs)


async def _reset(session: AsyncSession) -> None:
    """Close any auto-begun transaction from prior reads so the next
    ``async with session.begin()`` can open a fresh outer transaction.
    Idempotent on a session with no active transaction."""
    if session.in_transaction():
        await session.commit()


async def _insert_staging(
    session: AsyncSession,
    *,
    url_canonical: str = "http://e.com/a",
    url: str | None = "http://e.com/a",
    title: str | None = "seed title",
    source_id: int | None = None,
    sha256_title: str | None = None,
    published: dt.datetime | None = None,
    status: str = "pending",
    reviewed_by: str | None = None,
    reviewed_at: dt.datetime | None = None,
    lang: str | None = "en",
) -> int:
    values = {
        "url_canonical": url_canonical,
        "url": url,
        "title": title,
        "source_id": source_id,
        "sha256_title": sha256_title,
        "published": published or dt.datetime(2026, 4, 17, tzinfo=dt.timezone.utc),
        "status": status,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "lang": lang,
    }
    result = await session.execute(
        sa.insert(staging_table).values(**values).returning(staging_table.c.id)
    )
    staging_id = result.scalar_one()
    await session.commit()
    return staging_id


async def _count(session: AsyncSession, table: sa.Table) -> int:
    return (
        await session.execute(sa.select(sa.func.count()).select_from(table))
    ).scalar_one()


# ---------------------------------------------------------------------------
# Approve — happy path
# ---------------------------------------------------------------------------


class TestApproveHappyPath:
    async def test_promotes_staging_and_returns_outcome(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        outcome = await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        assert outcome.staging_id == staging_id
        assert outcome.attached_existing is False
        assert outcome.reviewer_sub == "user-a"
        assert outcome.report_id > 0

    async def test_staging_row_transitions_to_promoted(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes="ok",
        )
        row = (
            await session.execute(
                sa.select(
                    staging_table.c.status,
                    staging_table.c.reviewed_by,
                    staging_table.c.reviewed_at,
                    staging_table.c.promoted_report_id,
                    staging_table.c.decision_reason,
                ).where(staging_table.c.id == staging_id)
            )
        ).one()
        assert row.status == "promoted"
        assert row.reviewed_by == "user-a"
        assert row.reviewed_at is not None
        assert row.promoted_report_id is not None
        assert row.decision_reason is None  # approve doesn't set it

    async def test_reports_row_inserted_with_expected_fields(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(
            session,
            url_canonical="http://e.com/r1",
            url="http://e.com/r1?utm=x",
            title="Case-Sensitive Title",
            sha256_title="d" * 64,
            lang="ko",
        )
        outcome = await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        row = (
            await session.execute(
                sa.select(
                    reports_table.c.title,
                    reports_table.c.url,
                    reports_table.c.url_canonical,
                    reports_table.c.sha256_title,
                    reports_table.c.lang,
                    reports_table.c.published,
                ).where(reports_table.c.id == outcome.report_id)
            )
        ).one()
        assert row.title == "Case-Sensitive Title"
        assert row.url == "http://e.com/r1?utm=x"
        assert row.url_canonical == "http://e.com/r1"
        assert row.sha256_title == "d" * 64
        assert row.lang == "ko"
        assert row.published == dt.date(2026, 4, 17)


# ---------------------------------------------------------------------------
# Approve — attached_existing path
# ---------------------------------------------------------------------------


class TestApproveAttachedExisting:
    async def test_returns_attached_existing_when_report_already_exists(
        self, session: AsyncSession
    ) -> None:
        src = await session.execute(
            sa.insert(sources_table)
            .values(name="seeded-vendor", type="vendor")
            .returning(sources_table.c.id)
        )
        source_id = src.scalar_one()
        rep = await session.execute(
            sa.insert(reports_table)
            .values(
                published=dt.date(2026, 1, 1),
                source_id=source_id,
                title="original title",
                url="http://old.example/r",
                url_canonical="http://dup.example/r",
                sha256_title="a" * 64,
            )
            .returning(reports_table.c.id)
        )
        existing_report_id = rep.scalar_one()
        await session.commit()

        staging_id = await _insert_staging(
            session,
            url_canonical="http://dup.example/r",
            url="http://new.example/r",
            title="new title",
            source_id=source_id,
            sha256_title="b" * 64,
        )

        outcome = await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        assert outcome.attached_existing is True
        assert outcome.report_id == existing_report_id

        title_now = (
            await session.execute(
                sa.select(reports_table.c.title).where(
                    reports_table.c.id == existing_report_id
                )
            )
        ).scalar_one()
        assert title_now == "original title"

        prid = (
            await session.execute(
                sa.select(staging_table.c.promoted_report_id).where(
                    staging_table.c.id == staging_id
                )
            )
        ).scalar_one()
        assert prid == existing_report_id


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


class TestSourceResolution:
    async def test_null_source_id_upserts_unknown_source(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session, source_id=None)
        outcome = await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        report_source = (
            await session.execute(
                sa.select(reports_table.c.source_id).where(
                    reports_table.c.id == outcome.report_id
                )
            )
        ).scalar_one()
        source_name = (
            await session.execute(
                sa.select(sources_table.c.name).where(
                    sources_table.c.id == report_source
                )
            )
        ).scalar_one()
        assert source_name == UNKNOWN_SOURCE_NAME

    async def test_existing_source_id_reused(
        self, session: AsyncSession
    ) -> None:
        src = await session.execute(
            sa.insert(sources_table)
            .values(name="vendor-x", type="vendor")
            .returning(sources_table.c.id)
        )
        source_id = src.scalar_one()
        await session.commit()

        staging_id = await _insert_staging(session, source_id=source_id)
        outcome = await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        report_source = (
            await session.execute(
                sa.select(reports_table.c.source_id).where(
                    reports_table.c.id == outcome.report_id
                )
            )
        ).scalar_one()
        assert report_source == source_id
        await _reset(session)
        assert await _count(session, sources_table) == 1


# ---------------------------------------------------------------------------
# Approve — audit semantics (invariant #3)
# ---------------------------------------------------------------------------


class TestApproveAuditSemantics:
    async def test_emits_exactly_one_audit_row(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        assert await _count(session, audit_log_table) == 1

    async def test_audit_action_is_report_promoted(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="alice-sub",
            reviewer_notes=None,
        )
        row = (
            await session.execute(
                sa.select(
                    audit_log_table.c.actor,
                    audit_log_table.c.action,
                    audit_log_table.c.entity,
                )
            )
        ).one()
        assert row.action == ACTION_REPORT_PROMOTED
        assert row.entity == ENTITY_REPORTS
        assert row.actor == "alice-sub"

    async def test_audit_diff_includes_reviewer_notes(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes="spot-checked in kibana",
        )
        diff_raw = (
            await session.execute(
                sa.select(audit_log_table.c.diff_jsonb)
            )
        ).scalar_one()
        diff = diff_raw if isinstance(diff_raw, dict) else json.loads(diff_raw)
        assert diff["reviewer_notes"] == "spot-checked in kibana"
        assert diff["from_staging_id"] == staging_id
        assert diff["attached_existing"] is False
        assert diff["report_snapshot"]["url_canonical"] == "http://e.com/a"
        assert diff["report_snapshot"]["title"] == "seed title"

    async def test_audit_diff_reviewer_notes_null_when_absent(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        diff_raw = (
            await session.execute(
                sa.select(audit_log_table.c.diff_jsonb)
            )
        ).scalar_one()
        diff = diff_raw if isinstance(diff_raw, dict) else json.loads(diff_raw)
        assert diff["reviewer_notes"] is None

    async def test_no_staging_approved_event_ever_emitted(
        self, session: AsyncSession
    ) -> None:
        """Plan §2.1 D4 drop: approve must NOT emit STAGING_APPROVED."""
        staging_id = await _insert_staging(session)
        await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        rows = (
            await session.execute(sa.select(audit_log_table.c.action))
        ).scalars().all()
        assert rows == [ACTION_REPORT_PROMOTED]
        assert "STAGING_APPROVED" not in rows


# ---------------------------------------------------------------------------
# Reject — semantics (invariant #4)
# ---------------------------------------------------------------------------


class TestReject:
    async def test_happy_path_transitions_to_rejected(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        outcome = await run_reject(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            decision_reason="duplicate of report #42",
            reviewer_notes=None,
        )
        assert outcome.decision_reason == "duplicate of report #42"

        row = (
            await session.execute(
                sa.select(
                    staging_table.c.status,
                    staging_table.c.decision_reason,
                    staging_table.c.reviewed_by,
                    staging_table.c.reviewed_at,
                    staging_table.c.promoted_report_id,
                ).where(staging_table.c.id == staging_id)
            )
        ).one()
        assert row.status == "rejected"
        assert row.decision_reason == "duplicate of report #42"
        assert row.reviewed_by == "user-a"
        assert row.reviewed_at is not None
        assert row.promoted_report_id is None  # reject does NOT promote

    async def test_emits_exactly_one_audit_with_action_rejected(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_reject(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            decision_reason="irrelevant",
            reviewer_notes="discussed in #ops",
        )
        rows = (
            await session.execute(
                sa.select(
                    audit_log_table.c.action,
                    audit_log_table.c.entity,
                    audit_log_table.c.entity_id,
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].action == ACTION_STAGING_REJECTED
        assert rows[0].entity == ENTITY_STAGING
        assert rows[0].entity_id == str(staging_id)

    async def test_reviewer_notes_live_only_in_audit_diff(
        self, session: AsyncSession
    ) -> None:
        """Plan §2.1 D1 lock — notes never hit a staging column."""
        # Sanity: the mirror table has no 'notes' column.
        assert "notes" not in staging_table.c

        staging_id = await _insert_staging(session)
        await run_reject(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            decision_reason="spam",
            reviewer_notes="first-pass heuristic triggered",
        )
        row = (
            await session.execute(
                sa.select(staging_table).where(
                    staging_table.c.id == staging_id
                )
            )
        ).one()
        assert "first-pass heuristic triggered" not in str(row)

        diff_raw = (
            await session.execute(
                sa.select(audit_log_table.c.diff_jsonb)
            )
        ).scalar_one()
        diff = diff_raw if isinstance(diff_raw, dict) else json.loads(diff_raw)
        assert diff["decision_reason"] == "spam"
        assert diff["reviewer_notes"] == "first-pass heuristic triggered"

    async def test_reject_does_not_touch_reports_or_sources(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_reject(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            decision_reason="x",
            reviewer_notes=None,
        )
        assert await _count(session, reports_table) == 0
        assert await _count(session, sources_table) == 0


class TestRejectAuditSemantics:
    async def test_emits_exactly_one_audit_row(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session)
        await run_reject(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            decision_reason="x",
            reviewer_notes=None,
        )
        assert await _count(session, audit_log_table) == 1


# ---------------------------------------------------------------------------
# Already-decided preconditions
# ---------------------------------------------------------------------------


class TestAlreadyDecided:
    async def test_approve_already_promoted_raises(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(
            session,
            status="promoted",
            reviewed_by="prior-user",
            reviewed_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )
        with pytest.raises(StagingAlreadyDecidedError) as exc_info:
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )
        err = exc_info.value
        assert err.staging_id == staging_id
        assert err.current_status == "promoted"
        assert err.decided_by == "prior-user"

    async def test_approve_already_rejected_raises(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(
            session,
            status="rejected",
            reviewed_by="prior-user",
            reviewed_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        )
        with pytest.raises(StagingAlreadyDecidedError):
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )

    async def test_reject_already_decided_raises(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session, status="rejected")
        with pytest.raises(StagingAlreadyDecidedError):
            await run_reject(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                decision_reason="x",
                reviewer_notes=None,
            )

    async def test_not_found_raises(self, session: AsyncSession) -> None:
        with pytest.raises(StagingNotFoundError):
            await run_promote(
                session,
                staging_id=99999,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )


class TestInvalidStagingState:
    """CHECK enum values 'approved' / 'error' are reserved for future
    or operational flows (plan §2.2 B narrowing) — the review endpoint
    must NOT wrap them in the 409 AlreadyDecidedError envelope because
    the DTO's current_status Literal does not include them. Service
    raises StagingInvalidStateError; router will map to 422."""

    async def test_approve_on_staging_in_approved_state_raises_invalid(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session, status="approved")
        with pytest.raises(StagingInvalidStateError) as exc_info:
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )
        assert exc_info.value.staging_id == staging_id
        assert exc_info.value.current_status == "approved"

    async def test_approve_on_staging_in_error_state_raises_invalid(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session, status="error")
        with pytest.raises(StagingInvalidStateError) as exc_info:
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )
        assert exc_info.value.current_status == "error"

    async def test_reject_on_staging_in_approved_state_raises_invalid(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session, status="approved")
        with pytest.raises(StagingInvalidStateError):
            await run_reject(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                decision_reason="x",
                reviewer_notes=None,
            )

    async def test_reject_on_staging_in_error_state_raises_invalid(
        self, session: AsyncSession
    ) -> None:
        staging_id = await _insert_staging(session, status="error")
        with pytest.raises(StagingInvalidStateError):
            await run_reject(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                decision_reason="x",
                reviewer_notes=None,
            )

    async def test_invalid_state_is_not_already_decided_error(
        self, session: AsyncSession
    ) -> None:
        """Guards against a regression that collapses the two error
        classes back into one. If someone 'simplifies' the service
        by re-unifying, this test fails loudly."""
        staging_id = await _insert_staging(session, status="approved")
        with pytest.raises(StagingInvalidStateError) as exc_info:
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )
        # Explicitly assert the type — not just 'some exception',
        # and not StagingAlreadyDecidedError.
        assert not isinstance(exc_info.value, StagingAlreadyDecidedError)


# ---------------------------------------------------------------------------
# Race-lost re-fetch (Codex R1 P2)
# ---------------------------------------------------------------------------


class TestRaceLostRefetch:
    """The conditional UPDATE ... WHERE status='pending' RETURNING id
    returns empty when another transaction already decided the row.
    Under PG + FOR UPDATE this branch is effectively unreachable
    because ``_raise_if_not_pending`` fires first, but Codex R1 P2
    flagged that when it DOES fire the 409 body must carry the
    ACTUAL winner's state, not a hardcoded guess derived from the
    caller's own intent (promote → "promoted" / reject → "rejected").
    A cross-decision race would otherwise mislead the client.

    These tests force the race-lost branch by monkeypatching
    ``_raise_if_not_pending`` to no-op, seeding the staging row in a
    non-pending state (with distinct reviewed_by / reviewed_at), and
    asserting the error surfaces the re-fetched values — including
    the opposite-intent status in the cross-decision case.
    """

    async def test_promote_race_lost_to_reject_reports_real_status(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Approve caller loses to a concurrent reject — 409 body must
        carry current_status='rejected' (the winner's), not 'promoted'
        (the caller's intent)."""
        monkeypatch.setattr(promote_service, "_raise_if_not_pending", lambda *_a, **_k: None)
        prior_ts = dt.datetime(2026, 2, 1, 12, 0, tzinfo=dt.timezone.utc)
        staging_id = await _insert_staging(
            session,
            status="rejected",
            reviewed_by="reject-winner",
            reviewed_at=prior_ts,
        )
        with pytest.raises(StagingAlreadyDecidedError) as exc_info:
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="promote-loser",
                reviewer_notes=None,
            )
        err = exc_info.value
        assert err.current_status == "rejected"
        assert err.decided_by == "reject-winner"
        # aiosqlite strips tzinfo on DATETIME round-trip — comparing
        # the naive forms proves the value came from the staging row
        # rather than a fresh now(). Real-PG preserves tzinfo; the
        # Group H integration scenarios cover the tz-aware assertion.
        assert err.decided_at.replace(tzinfo=None) == prior_ts.replace(tzinfo=None)

    async def test_reject_race_lost_to_promote_reports_real_status(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reject caller loses to a concurrent promote — 409 body must
        carry current_status='promoted' (the winner's), not 'rejected'
        (the caller's intent)."""
        monkeypatch.setattr(promote_service, "_raise_if_not_pending", lambda *_a, **_k: None)
        prior_ts = dt.datetime(2026, 2, 1, 12, 0, tzinfo=dt.timezone.utc)
        staging_id = await _insert_staging(
            session,
            status="promoted",
            reviewed_by="promote-winner",
            reviewed_at=prior_ts,
        )
        with pytest.raises(StagingAlreadyDecidedError) as exc_info:
            await run_reject(
                session,
                staging_id=staging_id,
                reviewer_sub="reject-loser",
                decision_reason="would-be-reject-reason",
                reviewer_notes=None,
            )
        err = exc_info.value
        assert err.current_status == "promoted"
        assert err.decided_by == "promote-winner"
        # aiosqlite strips tzinfo on DATETIME round-trip — comparing
        # the naive forms proves the value came from the staging row
        # rather than a fresh now(). Real-PG preserves tzinfo; the
        # Group H integration scenarios cover the tz-aware assertion.
        assert err.decided_at.replace(tzinfo=None) == prior_ts.replace(tzinfo=None)

    async def test_promote_race_lost_same_direction_reports_real_fields(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Approve caller loses to another concurrent approve — 409
        body still needs the real decided_by / decided_at, not ``""``
        / ``now()`` (prior behavior had lost those too)."""
        monkeypatch.setattr(promote_service, "_raise_if_not_pending", lambda *_a, **_k: None)
        prior_ts = dt.datetime(2026, 3, 15, 8, 30, tzinfo=dt.timezone.utc)
        staging_id = await _insert_staging(
            session,
            status="promoted",
            reviewed_by="promote-winner",
            reviewed_at=prior_ts,
        )
        with pytest.raises(StagingAlreadyDecidedError) as exc_info:
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="promote-loser",
                reviewer_notes=None,
            )
        err = exc_info.value
        assert err.current_status == "promoted"
        # Previously these were always "" and datetime.now(...) — the
        # fix recovers them from the real winner's staging row.
        assert err.decided_by == "promote-winner"
        # aiosqlite strips tzinfo on DATETIME round-trip — comparing
        # the naive forms proves the value came from the staging row
        # rather than a fresh now(). Real-PG preserves tzinfo; the
        # Group H integration scenarios cover the tz-aware assertion.
        assert err.decided_at.replace(tzinfo=None) == prior_ts.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Validation — reports NOT NULL projection
# ---------------------------------------------------------------------------


class TestValidation:
    async def test_missing_title_raises(self, session: AsyncSession) -> None:
        staging_id = await _insert_staging(session, title=None)
        with pytest.raises(PromoteValidationError, match="title"):
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )

    async def test_missing_url_raises(self, session: AsyncSession) -> None:
        staging_id = await _insert_staging(session, url=None)
        with pytest.raises(PromoteValidationError, match="url"):
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )

    async def test_missing_published_raises(
        self, session: AsyncSession
    ) -> None:
        result = await session.execute(
            sa.insert(staging_table)
            .values(
                url_canonical="http://noone/",
                url="http://noone/",
                title="t",
                published=None,
                status="pending",
            )
            .returning(staging_table.c.id)
        )
        staging_id = result.scalar_one()
        await session.commit()

        with pytest.raises(PromoteValidationError, match="published"):
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )

    async def test_sha256_computed_when_staging_has_none(
        self, session: AsyncSession
    ) -> None:
        """Reports.sha256_title is NOT NULL; staging.sha256_title
        nullable. When absent we compute from title at promote time."""
        staging_id = await _insert_staging(
            session, title="hello world", sha256_title=None
        )
        outcome = await run_promote(
            session,
            staging_id=staging_id,
            reviewer_sub="user-a",
            reviewer_notes=None,
        )
        sha = (
            await session.execute(
                sa.select(reports_table.c.sha256_title).where(
                    reports_table.c.id == outcome.report_id
                )
            )
        ).scalar_one()
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert sha == expected


# ---------------------------------------------------------------------------
# Mid-transaction failure rollback (invariant #5)
# ---------------------------------------------------------------------------


class TestMidTransactionRollback:
    async def test_failure_after_source_upsert_rolls_back(
        self,
        session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulate DB failure during reports INSERT. The caller's
        ``async with session.begin()`` must rollback the entire
        transaction — zero production-table writes, zero audit rows,
        staging back to its pre-call pending status."""
        staging_id = await _insert_staging(session, source_id=None)

        async def _boom(*args, **kwargs):
            raise RuntimeError("injected failure after source upsert")

        monkeypatch.setattr(promote_service, "upsert_report", _boom)

        with pytest.raises(RuntimeError, match="injected failure"):
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )

        await _reset(session)

        row = (
            await session.execute(
                sa.select(
                    staging_table.c.status,
                    staging_table.c.reviewed_by,
                    staging_table.c.reviewed_at,
                    staging_table.c.promoted_report_id,
                    staging_table.c.decision_reason,
                ).where(staging_table.c.id == staging_id)
            )
        ).one()
        assert row.status == "pending"
        assert row.reviewed_by is None
        assert row.reviewed_at is None
        assert row.promoted_report_id is None
        assert row.decision_reason is None

        assert await _count(session, sources_table) == 0
        assert await _count(session, reports_table) == 0
        assert await _count(session, audit_log_table) == 0

    async def test_failure_during_audit_rolls_back_reports(
        self,
        session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An audit write failure AFTER the reports INSERT must still
        rollback the production write. Plan explicitly rejects the
        PR #7/8/9 worker-side pattern of swallowing audit errors —
        the promote path is a first-class production write whose
        provenance loss cannot be silently ignored."""
        staging_id = await _insert_staging(session)

        async def _boom(*args, **kwargs):
            raise RuntimeError("audit emit exploded")

        monkeypatch.setattr(promote_service, "_emit_audit", _boom)

        with pytest.raises(RuntimeError, match="audit emit exploded"):
            await run_promote(
                session,
                staging_id=staging_id,
                reviewer_sub="user-a",
                reviewer_notes=None,
            )

        await _reset(session)

        assert await _count(session, reports_table) == 0
        assert await _count(session, sources_table) == 0
        assert await _count(session, audit_log_table) == 0
        status = (
            await session.execute(
                sa.select(staging_table.c.status).where(
                    staging_table.c.id == staging_id
                )
            )
        ).scalar_one()
        assert status == "pending"
