"""Integration tests for PR #7 Group B audit wiring.

These drive the full ``run_bootstrap`` pipeline end-to-end against a
sqlite-memory session with the committed fixture, and assert the
audit_log state after each run matches the D3/D4 contract:

  - First run: exactly one etl_run_started + one etl_run_completed at
    the run-level, and one etl_insert per audited entity insertion.
  - Idempotent second run on the same data: one etl_run_started + one
    etl_run_completed + zero etl_insert + many etl_update (empty
    changed) per re-touched entity.
  - Catastrophic failure (unhandled exception mid-loop): exactly one
    etl_run_started + one etl_run_failed with structured detail,
    zero leaked row-level events, zero leaked entity rows.
  - Caller-owned outer transaction: audit rows participate in the
    caller's tx, caller decides persistence.

The user's Group B review brief asked specifically about:
  (a) run_id generated exactly once at CLI entry
  (b) workbook_sha256 shared across row and run events
  (c) etl_run_failed never dropped on the exception path
  (d) audit writes not breaking the outer tx
  (e) 500-row batch behavior under partial failure

(a) and (b) are pinned by ``test_run_id_and_workbook_hash_shared_across_all_events``.
(c) is pinned by ``test_catastrophic_failure_emits_run_failed``.
(d) is pinned by ``test_caller_owned_outer_transaction_is_preserved``.
(e) is covered at the unit level in test_audit.py; this file drives
    the realistic full-fixture scenario under which the buffer's
    mark/rollback_to pattern must not leak any row-level state.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap import cli as cli_module
from worker.bootstrap.audit import (
    AUDIT_ACTOR,
    ROW_INSERT,
    ROW_UPDATE,
    RUN_COMPLETED,
    RUN_ENTITY,
    RUN_FAILED,
    RUN_STARTED,
    new_audit_meta,
)
from worker.bootstrap.cli import run_bootstrap
from worker.bootstrap.tables import (
    audit_log_table,
    codenames_table,
    groups_table,
    incidents_table,
    reports_table,
    sources_table,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
_STRESS_FIXTURE_XLSX = REPO_ROOT / "services/worker/tests/fixtures/bootstrap_sample.xlsx"
_STRESS_FIXTURE_YAML = REPO_ROOT / "services/worker/tests/fixtures/bootstrap_sample.yaml"
ALIASES = REPO_ROOT / "data/dictionaries/aliases.yml"


def _build_happy_fixture_path() -> Path:
    """Generate a happy-subset xlsx at module import time.

    Prior to Codex round 3 P2, run-level audit writes ignored the D5
    failure threshold and always emitted etl_run_completed on the
    body-success path. These audit-shape tests were implicitly
    relying on that, feeding the committed stress fixture (7 of 32
    rows tagged _tag: failure_case, 21.9% > the 5% gate) into
    run_bootstrap and expecting RUN_COMPLETED to land. After the fix,
    threshold-exceeded runs correctly emit RUN_FAILED instead, which
    is the right lineage semantics but breaks the shape tests.

    Rather than duplicate the fixture to disk, generate a happy
    subset once at module import via scripts/generate_bootstrap_
    fixture.py's build_workbook + strip_failure_cases helpers. The
    stress fixture stays reachable via _STRESS_FIXTURE_XLSX for the
    threshold-regression test below.
    """
    import importlib.util
    import tempfile

    import yaml  # type: ignore[import-not-found]

    spec = importlib.util.spec_from_file_location(
        "_audit_happy_fixture_generator",
        REPO_ROOT / "scripts" / "generate_bootstrap_fixture.py",
    )
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    with _STRESS_FIXTURE_YAML.open("r", encoding="utf-8") as handle:
        src = yaml.safe_load(handle)
    src = gen.strip_failure_cases(src)
    wb = gen.build_workbook(src)

    out_dir = Path(tempfile.mkdtemp(prefix="dprk_cti_audit_fixture_"))
    out = out_dir / "bootstrap_happy.xlsx"
    wb.save(out)
    return out


#: Happy-subset workbook used by every audit-shape test in this file.
#: Generated at import time so FIXTURE behaves like a static file path
#: for the existing tests. The committed stress fixture is still
#: reachable via _STRESS_FIXTURE_XLSX for the threshold-branch test.
FIXTURE = _build_happy_fixture_path()


async def _select_audit_rows(session: AsyncSession) -> list[dict]:
    """Return every audit_log row as a plain dict, ordered by id."""
    result = await session.execute(
        sa.select(audit_log_table).order_by(audit_log_table.c.id)
    )
    return [dict(r) for r in result.mappings().all()]


async def _count_by_action(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        sa.select(
            audit_log_table.c.action,
            sa.func.count().label("n"),
        ).group_by(audit_log_table.c.action)
    )
    return {row.action: row.n for row in result}


# ---------------------------------------------------------------------------
# Happy-path first run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFirstRunAuditShape:
    async def test_first_run_emits_exactly_one_start_and_one_complete(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        meta = new_audit_meta(FIXTURE)

        stdout = io.StringIO()
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=stdout,
            audit_meta=meta,
        )

        counts = await _count_by_action(db_session)
        assert counts.get(RUN_STARTED) == 1
        assert counts.get(RUN_COMPLETED) == 1
        assert RUN_FAILED not in counts  # no failures on clean fixture

    async def test_first_run_emits_row_level_events(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """First run must produce row-level events. Note that BOTH
        etl_insert AND etl_update are expected even on a "first run"
        because the same entity can be touched by multiple workbook
        rows within a single run (e.g. Actors row inserts group
        "Lazarus", then a later Reports row with a `#lazarus` tag
        re-touches it and gets an empty-changed update). The
        first-vs-idempotent distinction is pinned by
        :class:`TestIdempotentSecondRun` instead."""
        meta = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )
        counts = await _count_by_action(db_session)
        assert counts.get(ROW_INSERT, 0) > 0

        # etl_insert count must equal the count of distinct
        # (entity, entity_id) first-touches within the run. Equivalent
        # invariant: total entity rows across the 5 audited tables
        # equals count(etl_insert).
        entity_row_total = 0
        for table in (
            groups_table, sources_table, codenames_table,
            reports_table, incidents_table,
        ):
            n = (await db_session.execute(
                sa.select(sa.func.count()).select_from(table)
            )).scalar_one()
            entity_row_total += n
        assert counts[ROW_INSERT] == entity_row_total

    async def test_row_level_events_cover_exactly_the_five_audited_entities(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        meta = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )

        # Collect distinct entity values from row-level events (exclude
        # the run-level events, which use the "etl_run" literal).
        result = await db_session.execute(
            sa.select(audit_log_table.c.entity)
            .where(audit_log_table.c.action.in_([ROW_INSERT, ROW_UPDATE]))
            .distinct()
        )
        entities = {row[0] for row in result}
        assert entities <= {
            "groups", "sources", "codenames", "reports", "incidents",
        }

    async def test_actor_is_always_bootstrap_etl_literal(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        meta = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )
        result = await db_session.execute(
            sa.select(audit_log_table.c.actor).distinct()
        )
        actors = {row[0] for row in result}
        assert actors == {AUDIT_ACTOR}

    async def test_run_level_rows_use_etl_run_entity_and_null_entity_id(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        meta = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )
        result = await db_session.execute(
            sa.select(audit_log_table).where(
                audit_log_table.c.action.in_([RUN_STARTED, RUN_COMPLETED, RUN_FAILED])
            )
        )
        for row in result.mappings():
            assert row["entity"] == RUN_ENTITY
            assert row["entity_id"] is None

    async def test_run_id_and_workbook_hash_shared_across_all_events(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Pins user review point (a) + (b): every audit row from a
        single invocation must carry the identical run_id AND the
        identical workbook_sha256. A review query `WHERE run_id = X`
        must return the entire run as a coherent timeline."""
        meta = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )

        rows = await _select_audit_rows(db_session)
        assert len(rows) >= 3  # 1 started + >=1 insert + 1 completed

        run_ids = {r["diff_jsonb"]["meta"]["run_id"] for r in rows}
        wb_hashes = {r["diff_jsonb"]["meta"]["workbook_sha256"] for r in rows}
        started_ats = {r["diff_jsonb"]["meta"]["started_at"] for r in rows}

        assert run_ids == {str(meta.run_id)}
        assert wb_hashes == {meta.workbook_sha256}
        assert started_ats == {meta.started_at.isoformat()}

        # And the run-level timeline ordering is exact: first row is
        # etl_run_started, last row is etl_run_completed.
        assert rows[0]["action"] == RUN_STARTED
        assert rows[-1]["action"] == RUN_COMPLETED

    async def test_completed_detail_carries_row_counts(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        meta = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )
        completed = (
            await db_session.execute(
                sa.select(audit_log_table).where(
                    audit_log_table.c.action == RUN_COMPLETED
                )
            )
        ).mappings().one()
        detail = completed["diff_jsonb"]["detail"]
        assert "rows_attempted" in detail
        assert "rows_failed" in detail
        assert detail["dry_run"] is False
        assert detail["rows_attempted"] > 0


# ---------------------------------------------------------------------------
# Idempotent second run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIdempotentSecondRun:
    async def test_second_run_emits_only_updates(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        # First run
        meta1 = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors1.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta1,
        )

        # Snapshot: count the entity rows so we can prove the second
        # run does not insert new rows.
        def _count_all_entities() -> sa.Select:
            return sa.select(
                sa.func.count().label("n")
            )

        reports_before = (await db_session.execute(
            _count_all_entities().select_from(reports_table)
        )).scalar_one()
        groups_before = (await db_session.execute(
            _count_all_entities().select_from(groups_table)
        )).scalar_one()

        # Second run with a DIFFERENT AuditMeta (new run_id, same hash).
        meta2 = new_audit_meta(FIXTURE)
        assert meta2.run_id != meta1.run_id
        assert meta2.workbook_sha256 == meta1.workbook_sha256  # same file

        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors2.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta2,
        )

        # Entity tables unchanged in size
        reports_after = (await db_session.execute(
            _count_all_entities().select_from(reports_table)
        )).scalar_one()
        groups_after = (await db_session.execute(
            _count_all_entities().select_from(groups_table)
        )).scalar_one()
        assert reports_after == reports_before
        assert groups_after == groups_before

        # Second run's row-level events are all etl_update with empty
        # changed payload.
        result = await db_session.execute(
            sa.select(audit_log_table).where(
                sa.func.json_extract(
                    audit_log_table.c.diff_jsonb,
                    "$.meta.run_id",
                ) == str(meta2.run_id)
            )
        )
        second_run_rows = list(result.mappings())
        assert len(second_run_rows) > 0

        row_events = [
            r for r in second_run_rows
            if r["action"] in (ROW_INSERT, ROW_UPDATE)
        ]
        assert len(row_events) > 0
        assert all(r["action"] == ROW_UPDATE for r in row_events)
        for r in row_events:
            assert r["diff_jsonb"]["op"] == "update"
            assert r["diff_jsonb"]["changed"] == {}

        # Exactly one started + one completed for run 2.
        run_level_actions = [
            r["action"] for r in second_run_rows
            if r["action"] in (RUN_STARTED, RUN_COMPLETED, RUN_FAILED)
        ]
        assert run_level_actions == [RUN_STARTED, RUN_COMPLETED]


# ---------------------------------------------------------------------------
# Catastrophic failure — the user review point (c)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCatastrophicFailure:
    async def test_catastrophic_failure_emits_run_failed(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Monkeypatch ``upsert_report`` to raise a RuntimeError on
        every call so the bootstrap body fails mid-loop with an
        exception that the per-row RowValidationError/ValueError
        handler does NOT catch.

        Expected: body is fully rolled back (no entity rows, no
        row-level audit events), but audit_log still contains exactly
        1 etl_run_started + 1 etl_run_failed with the error detail.
        """

        async def failing_upsert_report(*args, **kwargs):
            raise RuntimeError("simulated upsert_report crash")

        # Patch at the call site inside cli module (imported symbol).
        monkeypatch.setattr(
            cli_module, "upsert_report", failing_upsert_report
        )

        meta = new_audit_meta(FIXTURE)
        with pytest.raises(RuntimeError, match="simulated upsert_report crash"):
            await run_bootstrap(
                db_session,
                workbook=FIXTURE,
                aliases_path=ALIASES,
                errors_path=tmp_path / "errors.jsonl",
                dry_run=False,
                limit=None,
                stdout=io.StringIO(),
                audit_meta=meta,
            )

        # After the exception propagates, the session's outer tx
        # should have been committed by run_bootstrap so the run-level
        # audit rows survive.
        counts = await _count_by_action(db_session)
        assert counts.get(RUN_STARTED) == 1
        assert counts.get(RUN_FAILED) == 1
        assert RUN_COMPLETED not in counts

        # Zero row-level events: flush() was never reached (body
        # raised mid-loop), so no buffered events touched audit_log.
        # Equivalently, etl_savepoint.rollback() would have swept any
        # already-flushed rows if they existed.
        assert counts.get(ROW_INSERT, 0) == 0
        assert counts.get(ROW_UPDATE, 0) == 0

        # And no entity rows leaked — the Actors rows that processed
        # successfully BEFORE the first Reports row crashed are
        # reverted along with the savepoint. The entity tables are
        # all empty.
        for table in (
            groups_table, sources_table, codenames_table,
            reports_table, incidents_table,
        ):
            count = (await db_session.execute(
                sa.select(sa.func.count()).select_from(table)
            )).scalar_one()
            assert count == 0, f"{table.name} leaked {count} rows on failure"

    async def test_failed_detail_carries_error_type_and_message(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def failing_upsert_report(*args, **kwargs):
            raise RuntimeError("descriptive failure reason")

        monkeypatch.setattr(
            cli_module, "upsert_report", failing_upsert_report
        )

        meta = new_audit_meta(FIXTURE)
        with pytest.raises(RuntimeError):
            await run_bootstrap(
                db_session,
                workbook=FIXTURE,
                aliases_path=ALIASES,
                errors_path=tmp_path / "errors.jsonl",
                dry_run=False,
                limit=None,
                stdout=io.StringIO(),
                audit_meta=meta,
            )

        failed = (
            await db_session.execute(
                sa.select(audit_log_table).where(
                    audit_log_table.c.action == RUN_FAILED
                )
            )
        ).mappings().one()
        detail = failed["diff_jsonb"]["detail"]
        assert detail["error_type"] == "RuntimeError"
        assert detail["error_message"] == "descriptive failure reason"
        assert "rows_attempted" in detail
        assert "rows_failed" in detail


# ---------------------------------------------------------------------------
# Caller-owned outer transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCallerOwnedOuterTransaction:
    async def test_caller_owned_outer_transaction_is_preserved(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Pins user review point (d): audit writes must not break the
        outer transaction owned by the caller. The caller's sentinel
        write must still be visible after run_bootstrap returns and
        the caller commits."""
        # Caller pre-begins the outer tx and inserts a sentinel group.
        await db_session.begin()
        await db_session.execute(
            sa.insert(groups_table).values(name="CallerSentinelGroup")
        )
        assert db_session.in_transaction()

        meta = new_audit_meta(FIXTURE)
        await run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )

        # Caller's tx is still active (we did NOT commit or rollback
        # it from inside run_bootstrap because the caller owned it).
        assert db_session.in_transaction()

        # Sentinel is still visible through the caller's tx.
        sentinel = (
            await db_session.execute(
                sa.select(groups_table.c.name).where(
                    groups_table.c.name == "CallerSentinelGroup"
                )
            )
        ).first()
        assert sentinel is not None

        # Audit rows for this run landed in the caller's tx too — a
        # pre-commit query finds them.
        counts = await _count_by_action(db_session)
        assert counts.get(RUN_STARTED) == 1
        assert counts.get(RUN_COMPLETED) == 1

        # Caller commits and the whole thing persists.
        await db_session.commit()
        assert not db_session.in_transaction()

        # After caller commits, sentinel + audit rows are still there.
        sentinel_after = (
            await db_session.execute(
                sa.select(groups_table.c.name).where(
                    groups_table.c.name == "CallerSentinelGroup"
                )
            )
        ).first()
        assert sentinel_after is not None


# ---------------------------------------------------------------------------
# Codex round 1 regression: audit write failure must stay isolated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAuditWriteFailureIsolation:
    """A run-level audit INSERT that fails (e.g. pg rejects due to
    schema drift or permissions) must not corrupt the outer
    transaction. Each ``write_run_audit`` call is wrapped in its own
    savepoint so its failure leaves the outer tx alive and the ETL
    body proceeds. Without the savepoint wrapper, pg would put the
    session in an aborted state and the subsequent ``begin_nested()``
    for the etl_savepoint would raise."""

    async def test_run_started_audit_failure_does_not_abort_etl_body(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import worker.bootstrap.cli as cli_mod

        original = cli_mod.write_run_audit
        call_log: list[str] = []

        async def _selective_failing_audit(
            session: AsyncSession, *, action: str, meta, detail=None
        ) -> None:
            call_log.append(action)
            if action == RUN_STARTED:
                raise RuntimeError("simulated audit INSERT rejection")
            return await original(session, action=action, meta=meta, detail=detail)

        monkeypatch.setattr(cli_mod, "write_run_audit", _selective_failing_audit)

        meta = new_audit_meta(FIXTURE)
        await cli_mod.run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )

        # RUN_STARTED was attempted and raised; RUN_COMPLETED must
        # still have been attempted, which proves the ETL body reached
        # the post-savepoint-commit audit emission and therefore the
        # outer transaction survived the RUN_STARTED failure.
        assert RUN_STARTED in call_log
        assert RUN_COMPLETED in call_log

        # Zero RUN_STARTED rows persisted (savepoint rolled back);
        # exactly one RUN_COMPLETED row landed (savepoint committed).
        counts = await _count_by_action(db_session)
        assert counts.get(RUN_STARTED, 0) == 0
        assert counts.get(RUN_COMPLETED) == 1

        # Entity rows must have persisted — the ETL body was not
        # aborted by the RUN_STARTED savepoint rollback. Pick one of
        # the five audited entity tables as a sentinel.
        group_count = (
            await db_session.execute(sa.select(sa.func.count()).select_from(groups_table))
        ).scalar_one()
        assert group_count > 0

    async def test_run_completed_audit_failure_does_not_break_commit(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the RUN_COMPLETED audit INSERT fails, the final
        ``session.commit()`` path in ``run_bootstrap`` must still
        succeed. The savepoint wrapper guarantees the outer tx is
        clean at commit time."""
        import worker.bootstrap.cli as cli_mod

        original = cli_mod.write_run_audit

        async def _fail_on_completed(
            session: AsyncSession, *, action: str, meta, detail=None
        ) -> None:
            if action == RUN_COMPLETED:
                raise RuntimeError("simulated RUN_COMPLETED rejection")
            return await original(session, action=action, meta=meta, detail=detail)

        monkeypatch.setattr(cli_mod, "write_run_audit", _fail_on_completed)

        meta = new_audit_meta(FIXTURE)
        await cli_mod.run_bootstrap(
            db_session,
            workbook=FIXTURE,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )

        # Outer commit happened (session left no active tx) and the
        # RUN_STARTED row from the happy path persisted. RUN_COMPLETED
        # row is absent because its savepoint rolled back.
        counts = await _count_by_action(db_session)
        assert counts.get(RUN_STARTED) == 1
        assert counts.get(RUN_COMPLETED, 0) == 0

        # Entity rows must have persisted — the outer commit was not
        # aborted by the failed RUN_COMPLETED write.
        group_count = (
            await db_session.execute(sa.select(sa.func.count()).select_from(groups_table))
        ).scalar_one()
        assert group_count > 0


# ---------------------------------------------------------------------------
# Codex round 3 regression: threshold-exceeded body must emit RUN_FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestThresholdExceededAuditShape:
    """A bootstrap run whose body reached loop completion but
    exceeded the D5 5% failure threshold must record the run as
    ``etl_run_failed``, not ``etl_run_completed`` (Codex round 3
    P2). Lineage consumers query ``audit_log`` by action and must
    see the same verdict the CLI's exit code prints, otherwise
    dashboards will misclassify failed loads as successful."""

    async def test_stress_fixture_run_emits_run_failed(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        meta = new_audit_meta(_STRESS_FIXTURE_XLSX)
        await run_bootstrap(
            db_session,
            workbook=_STRESS_FIXTURE_XLSX,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )

        counts = await _count_by_action(db_session)
        assert counts.get(RUN_STARTED) == 1
        assert counts.get(RUN_FAILED) == 1
        assert RUN_COMPLETED not in counts

    async def test_stress_fixture_run_failed_detail_carries_threshold_flag(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """The etl_run_failed detail must make it obvious that the
        failure was threshold-exceeded (not an exception), so a
        lineage query can distinguish ``decide_exit_code`` failures
        from catastrophic mid-loop crashes without re-reading the
        source workbook."""
        meta = new_audit_meta(_STRESS_FIXTURE_XLSX)
        await run_bootstrap(
            db_session,
            workbook=_STRESS_FIXTURE_XLSX,
            aliases_path=ALIASES,
            errors_path=tmp_path / "errors.jsonl",
            dry_run=False,
            limit=None,
            stdout=io.StringIO(),
            audit_meta=meta,
        )

        failed = (
            await db_session.execute(
                sa.select(audit_log_table).where(
                    audit_log_table.c.action == RUN_FAILED
                )
            )
        ).mappings().one()
        detail = failed["diff_jsonb"]["detail"]

        assert detail.get("threshold_exceeded") is True
        assert detail["rows_attempted"] > 0
        assert detail["rows_failed"] > 0
        # The failure-rate is well above 5% on the committed stress
        # fixture (7 / 32 = 21.9%) so the decision must be non-OK.
        assert detail.get("exit_code", 0) != 0
        assert "summary" in detail
