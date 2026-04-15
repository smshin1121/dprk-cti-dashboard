"""Unit tests for worker.data_quality.cli (PR #7 Group E).

Covers the CLI contract:

  - argparse surface: check + report subcommands, flags, defaults.
  - ``decide_exit_code`` matrix across pass/warn/error × --fail-on
    {error, warn, none} × sink-failure yes/no.
  - ``run_check_on_session`` drives the full 11-item registry
    against a sqlite-memory fixture and writes to dq_events.
  - ``run_check_on_session`` emits the pre-run header with run_id
    and optional workbook_sha256 to stdout.
  - ``run_report`` prints the stub message and returns EXIT_REPORT_STUB.
  - ``main()`` returns EXIT_CONFIG_ERROR when --database-url is
    missing or --run-id is a malformed UUID.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.aliases import AliasDictionary
from worker.data_quality.cli import (
    EXIT_CHECK_FAILED,
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_REPORT_STUB,
    build_parser,
    decide_exit_code,
    main,
    run_check_on_session,
    run_report,
)
from worker.data_quality.results import (
    ExpectationResult,
    RunnerOutcome,
    SinkError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _test_aliases() -> AliasDictionary:
    return AliasDictionary(
        _by_type={
            "groups": {
                "lazarus": "Lazarus",
                "kimsuky": "Kimsuky",
            },
        }
    )


def _result(
    name: str = "x",
    severity: str = "pass",
) -> ExpectationResult:
    return ExpectationResult(name=name, severity=severity)


# ---------------------------------------------------------------------------
# argparse surface
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_check_subcommand_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "check", "--database-url", "postgresql+psycopg://x/y",
        ])
        assert args.command == "check"
        assert args.database_url == "postgresql+psycopg://x/y"
        assert args.run_id is None
        assert args.workbook_sha256 is None
        assert args.fail_on == "error"
        assert args.report_path is None

    def test_check_accepts_all_optional_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "check",
            "--database-url", "postgresql+psycopg://x/y",
            "--run-id", "01JGABCD000000000000000000",
            "--workbook-sha256", "a" * 64,
            "--aliases-path", "/tmp/aliases.yml",
            "--report-path", "/tmp/report.jsonl",
            "--fail-on", "warn",
        ])
        assert args.run_id == "01JGABCD000000000000000000"
        assert args.workbook_sha256 == "a" * 64
        assert args.aliases_path == Path("/tmp/aliases.yml")
        assert args.report_path == Path("/tmp/report.jsonl")
        assert args.fail_on == "warn"

    def test_fail_on_rejects_invalid_values(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "check",
                "--database-url", "x",
                "--fail-on", "catastrophic",
            ])

    def test_report_subcommand_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["report"])
        assert args.command == "report"
        assert args.since == "1d"

    def test_report_accepts_since_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["report", "--since", "7d"])
        assert args.since == "7d"

    def test_missing_subcommand_rejected(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


# ---------------------------------------------------------------------------
# decide_exit_code — pure matrix
# ---------------------------------------------------------------------------


class TestDecideExitCode:
    def test_all_pass_error_policy_is_ok(self) -> None:
        outcome = RunnerOutcome(
            results=[_result(severity="pass"), _result(severity="pass")],
            sink_errors=[],
        )
        assert decide_exit_code(outcome, "error") == EXIT_OK

    def test_warn_under_error_policy_is_ok(self) -> None:
        outcome = RunnerOutcome(
            results=[_result(severity="warn")],
            sink_errors=[],
        )
        assert decide_exit_code(outcome, "error") == EXIT_OK

    def test_error_under_error_policy_is_failure(self) -> None:
        outcome = RunnerOutcome(
            results=[_result(severity="error")],
            sink_errors=[],
        )
        assert decide_exit_code(outcome, "error") == EXIT_CHECK_FAILED

    def test_warn_under_warn_policy_is_failure(self) -> None:
        outcome = RunnerOutcome(
            results=[_result(severity="warn")],
            sink_errors=[],
        )
        assert decide_exit_code(outcome, "warn") == EXIT_CHECK_FAILED

    def test_pass_under_warn_policy_is_ok(self) -> None:
        outcome = RunnerOutcome(
            results=[_result(severity="pass")],
            sink_errors=[],
        )
        assert decide_exit_code(outcome, "warn") == EXIT_OK

    def test_error_under_none_policy_is_ok(self) -> None:
        """``--fail-on none`` disables severity-based failure but
        still fails on sink errors (tested separately)."""
        outcome = RunnerOutcome(
            results=[_result(severity="error"), _result(severity="warn")],
            sink_errors=[],
        )
        assert decide_exit_code(outcome, "none") == EXIT_OK

    def test_sink_failure_dominates_every_policy(self) -> None:
        """Sink errors always produce EXIT_CHECK_FAILED regardless of
        --fail-on. Infrastructure failure must not be suppressed by
        a lenient severity policy."""
        sink_err = SinkError(
            sink_name="db",
            error_type="OperationalError",
            error_message="connection refused",
        )
        outcome = RunnerOutcome(
            results=[_result(severity="pass")],
            sink_errors=[sink_err],
        )
        for policy in ("error", "warn", "none"):
            assert decide_exit_code(outcome, policy) == EXIT_CHECK_FAILED

    def test_unknown_fail_on_raises(self) -> None:
        outcome = RunnerOutcome(
            results=[_result(severity="pass")],
            sink_errors=[],
        )
        with pytest.raises(ValueError, match="unknown --fail-on"):
            decide_exit_code(outcome, "catastrophic")  # type: ignore[arg-type]

    def test_empty_results_pass_under_every_policy(self) -> None:
        outcome = RunnerOutcome(results=[], sink_errors=[])
        for policy in ("error", "warn", "none"):
            assert decide_exit_code(outcome, policy) == EXIT_OK


# ---------------------------------------------------------------------------
# run_check_on_session — end-to-end against sqlite-memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunCheckOnSession:
    async def test_clean_empty_db_is_ok(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        run_id = uuid.uuid4()
        stream = io.StringIO()
        outcome, exit_code = await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=run_id,
            stdout=stream,
        )
        assert exit_code == EXIT_OK
        assert outcome.had_sink_failure is False
        # 11 expectations ran
        assert len(outcome.results) == 11

    async def test_stdout_header_contains_run_id(
        self, db_session: AsyncSession
    ) -> None:
        run_id = uuid.uuid4()
        stream = io.StringIO()
        await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=run_id,
            stdout=stream,
        )
        output = stream.getvalue()
        assert "Data Quality Gate" in output
        assert str(run_id) in output

    async def test_stdout_includes_workbook_sha256_when_provided(
        self, db_session: AsyncSession
    ) -> None:
        run_id = uuid.uuid4()
        stream = io.StringIO()
        await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=run_id,
            workbook_sha256="a" * 64,
            stdout=stream,
        )
        output = stream.getvalue()
        assert "workbook_sha256" in output
        assert "a" * 64 in output

    async def test_stdout_omits_workbook_sha256_when_not_provided(
        self, db_session: AsyncSession
    ) -> None:
        run_id = uuid.uuid4()
        stream = io.StringIO()
        await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=run_id,
            stdout=stream,
        )
        assert "workbook_sha256" not in stream.getvalue()

    async def test_jsonl_mirror_created_when_report_path_set(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        run_id = uuid.uuid4()
        report_path = tmp_path / "dq_report.jsonl"
        await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=run_id,
            report_path=report_path,
            stdout=io.StringIO(),
        )
        assert report_path.exists()
        # 11 expectations → 11 JSONL lines
        lines = report_path.read_text("utf-8").splitlines()
        assert len(lines) == 11

    async def test_db_rows_share_run_id(
        self, db_session: AsyncSession
    ) -> None:
        import sqlalchemy as sa

        from worker.bootstrap.tables import dq_events_table

        run_id = uuid.uuid4()
        await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=run_id,
            stdout=io.StringIO(),
        )
        rows = (
            await db_session.execute(sa.select(dq_events_table.c.run_id))
        ).all()
        assert len(rows) == 11
        for (row_run_id,) in rows:
            assert str(row_run_id) == str(run_id)

    async def test_exit_code_follows_worst_severity(
        self, db_session: AsyncSession
    ) -> None:
        """Against an empty DB all 11 expectations pass, so exit code
        is OK. This pins the happy path; severity-specific failure
        tests live in :class:`TestDecideExitCode`."""
        _outcome, exit_code = await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=uuid.uuid4(),
            stdout=io.StringIO(),
        )
        assert exit_code == EXIT_OK

    async def test_sink_failure_summary_printed_to_stdout(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When a sink raises, the runner captures the error and the
        CLI layer prints a sink-error summary before returning."""
        import worker.data_quality.cli as cli_mod
        from worker.data_quality.sinks.db import DbSink

        async def _boom(self, results):
            raise RuntimeError("sink boom")

        monkeypatch.setattr(DbSink, "write", _boom)

        stream = io.StringIO()
        _outcome, exit_code = await run_check_on_session(
            db_session,
            aliases=_test_aliases(),
            run_id=uuid.uuid4(),
            stdout=stream,
        )
        output = stream.getvalue()
        assert exit_code == EXIT_CHECK_FAILED
        assert "Sink errors" in output
        assert "sink boom" in output


# ---------------------------------------------------------------------------
# run_report — stub
# ---------------------------------------------------------------------------


class TestRunReport:
    def test_returns_exit_report_stub(self) -> None:
        stream = io.StringIO()
        assert run_report(since="1d", stdout=stream) == EXIT_REPORT_STUB

    def test_stdout_mentions_not_implemented(self) -> None:
        stream = io.StringIO()
        run_report(since="1d", stdout=stream)
        assert "not implemented" in stream.getvalue()

    def test_stdout_echoes_since_flag(self) -> None:
        stream = io.StringIO()
        run_report(since="7d", stdout=stream)
        assert "7d" in stream.getvalue()

    def test_run_report_stdout_is_ascii_only(self) -> None:
        """The CLI surface must stay ASCII-safe so Windows consoles
        under cp949 (and other legacy code pages) do not crash on
        emit. Mirrors the same invariant StdoutSink enforces."""
        stream = io.StringIO()
        run_report(since="1d", stdout=stream)
        output = stream.getvalue()
        output.encode("ascii")  # raises UnicodeEncodeError on non-ASCII
        assert all(ord(c) < 128 for c in output)


# ---------------------------------------------------------------------------
# main() dispatcher — CLI contract
# ---------------------------------------------------------------------------


class TestMainDispatcher:
    def test_check_without_database_url_returns_config_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        # Ensure no env var pollutes the test.
        monkeypatch.delenv("DQ_DATABASE_URL", raising=False)
        assert main(["check"]) == EXIT_CONFIG_ERROR
        err = capsys.readouterr().err
        assert "--database-url" in err

    def test_check_with_invalid_run_id_returns_config_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.delenv("DQ_DATABASE_URL", raising=False)
        assert main([
            "check",
            "--database-url", "postgresql+psycopg://x/y",
            "--run-id", "not-a-uuid",
        ]) == EXIT_CONFIG_ERROR
        err = capsys.readouterr().err
        assert "run-id" in err

    def test_check_via_env_var_passes_required_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """``DQ_DATABASE_URL`` env var satisfies the required
        --database-url check. We monkeypatch ``run_check`` so the test
        pins the argparse + env-var plumbing only and never touches
        the network / engine / event-loop path.
        """
        import worker.data_quality.cli as cli_mod

        captured: dict[str, object] = {}

        async def _fake_run_check(**kwargs: object) -> int:
            captured.update(kwargs)
            return EXIT_CHECK_FAILED

        monkeypatch.setattr(cli_mod, "run_check", _fake_run_check)
        monkeypatch.setenv(
            "DQ_DATABASE_URL",
            "postgresql+psycopg://from-env:5432/x",
        )

        exit_code = main(["check"])

        assert exit_code == EXIT_CHECK_FAILED
        assert (
            captured["database_url"]
            == "postgresql+psycopg://from-env:5432/x"
        )
        err = capsys.readouterr().err
        assert "--database-url or $DQ_DATABASE_URL is required" not in err

    def test_report_subcommand_returns_stub_exit(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        assert main(["report", "--since", "2d"]) == EXIT_REPORT_STUB
        out = capsys.readouterr().out
        assert "not implemented" in out
        assert "2d" in out


# ---------------------------------------------------------------------------
# Codex round 1 regression: run_check must rollback on sink failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunCheckSinkFailureRollback:
    """When DbSink fails mid-run, run_check must call rollback — NOT
    commit — on the surrounding session. Committing an aborted pg
    transaction raises, and the raise propagates up through
    _main_async's outer try/except, getting mis-mapped to
    EXIT_CONFIG_ERROR instead of the documented EXIT_CHECK_FAILED
    exit code for sink failures (Codex P2).

    The test simulates pg's aborted-tx behaviour on sqlite-memory by
    monkeypatching ``AsyncSession.commit`` so it raises whenever it
    is called. With the fix, commit is never called on the sink-
    failure branch and the simulated pg behaviour is observed only
    if the fix regresses."""

    async def test_run_check_rolls_back_when_db_sink_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import worker.data_quality.cli as cli_mod
        from sqlalchemy.ext.asyncio import AsyncSession
        from worker.data_quality.sinks.db import DbSink

        async def _db_sink_boom(self, results):  # noqa: ANN001
            raise RuntimeError("simulated aborted-tx-producing sink failure")

        monkeypatch.setattr(DbSink, "write", _db_sink_boom)

        call_log: list[str] = []
        orig_commit = AsyncSession.commit
        orig_rollback = AsyncSession.rollback

        async def _simulated_pg_commit(self) -> None:
            call_log.append("commit")
            # Mimic pg raising on commit of an aborted transaction so
            # the test detects the pre-fix regression even on sqlite.
            raise RuntimeError(
                "simulated pg: current transaction is aborted"
            )

        async def _tracking_rollback(self) -> None:
            call_log.append("rollback")
            return await orig_rollback(self)

        monkeypatch.setattr(AsyncSession, "commit", _simulated_pg_commit)
        monkeypatch.setattr(AsyncSession, "rollback", _tracking_rollback)

        exit_code = await cli_mod.run_check(
            database_url="sqlite+aiosqlite:///:memory:",
            stdout=io.StringIO(),
        )

        assert exit_code == EXIT_CHECK_FAILED
        assert "rollback" in call_log
        assert "commit" not in call_log

    async def test_run_check_still_commits_on_clean_happy_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Guardrail: the rollback-on-sink-failure fix must NOT
        regress the happy path. When no sink fails, run_check still
        commits so any dq_events rows that landed survive."""
        import worker.data_quality.cli as cli_mod
        from sqlalchemy.ext.asyncio import AsyncSession
        from worker.bootstrap.tables import metadata
        from sqlalchemy.ext.asyncio import create_async_engine

        # Pre-create the schema on a file-backed sqlite so run_check's
        # engine (which opens its own connection) can see the tables.
        db_path = tmp_path / "dq_happy.sqlite"
        setup_engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}", future=True
        )
        async with setup_engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        await setup_engine.dispose()

        call_log: list[str] = []
        orig_commit = AsyncSession.commit
        orig_rollback = AsyncSession.rollback

        async def _tracking_commit(self) -> None:
            call_log.append("commit")
            return await orig_commit(self)

        async def _tracking_rollback(self) -> None:
            call_log.append("rollback")
            return await orig_rollback(self)

        monkeypatch.setattr(AsyncSession, "commit", _tracking_commit)
        monkeypatch.setattr(AsyncSession, "rollback", _tracking_rollback)

        exit_code = await cli_mod.run_check(
            database_url=f"sqlite+aiosqlite:///{db_path}",
            stdout=io.StringIO(),
        )

        assert exit_code == EXIT_OK
        assert "commit" in call_log
        assert "rollback" not in call_log
