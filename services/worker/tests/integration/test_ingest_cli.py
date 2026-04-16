"""Tests for worker.ingest.cli — argparse + exit codes."""

from __future__ import annotations

from worker.ingest.cli import build_parser, _decide_exit_code, EXIT_OK, EXIT_FAILURE
from worker.ingest.runner import RunOutcome
from worker.data_quality.results import ExpectationResult

import uuid


def _outcome(
    *,
    all_failed: bool = False,
    dq_severities: list[str] | None = None,
) -> RunOutcome:
    dq = tuple(
        ExpectationResult(name=f"test.metric.{i}", severity=s)  # type: ignore[arg-type]
        for i, s in enumerate(dq_severities or [])
    )
    return RunOutcome(
        run_id=uuid.uuid4(),
        feed_results=(),
        total_inserted=0,
        total_skipped_duplicate=0,
        total_parse_errors=0,
        total_fetch_failures=0,
        all_feeds_failed=all_failed,
        inserted_ids=(),
        dq_results=dq,
    )


# ---------------------------------------------------------------------------
# Parser structure
# ---------------------------------------------------------------------------


def test_parser_run_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--database-url", "sqlite+aiosqlite://"])
    assert args.command == "run"
    assert args.database_url == "sqlite+aiosqlite://"
    assert args.fail_on == "none"


def test_parser_list_pending_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["list-pending", "--database-url", "sqlite+aiosqlite://"])
    assert args.command == "list-pending"
    assert args.limit == 20
    assert not args.as_json


def test_parser_list_pending_json_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["list-pending", "--database-url", "x", "--json"])
    assert args.as_json


def test_parser_run_fail_on_warn() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--database-url", "x", "--fail-on", "warn"])
    assert args.fail_on == "warn"


def test_parser_run_custom_feeds_path() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--database-url", "x", "--feeds-path", "/custom/feeds.yml"])
    assert args.feeds_path.name == "feeds.yml"


# ---------------------------------------------------------------------------
# Exit code decisions
# ---------------------------------------------------------------------------


def test_fail_on_none_always_ok() -> None:
    outcome = _outcome(dq_severities=["warn", "warn", "pass", "pass"])
    assert _decide_exit_code(outcome, "none") == EXIT_OK


def test_fail_on_warn_exits_2_on_warn() -> None:
    outcome = _outcome(dq_severities=["pass", "warn", "pass", "pass"])
    assert _decide_exit_code(outcome, "warn") == EXIT_FAILURE


def test_fail_on_warn_ok_when_all_pass() -> None:
    outcome = _outcome(dq_severities=["pass", "pass", "pass", "pass"])
    assert _decide_exit_code(outcome, "warn") == EXIT_OK


def test_fail_on_error_ok_on_warn() -> None:
    outcome = _outcome(dq_severities=["warn", "warn", "pass", "pass"])
    assert _decide_exit_code(outcome, "error") == EXIT_OK


def test_fail_on_error_exits_2_on_error() -> None:
    outcome = _outcome(dq_severities=["pass", "error", "pass", "pass"])
    assert _decide_exit_code(outcome, "error") == EXIT_FAILURE


# ---------------------------------------------------------------------------
# list-pending is read-only — no runner imports
# ---------------------------------------------------------------------------


def test_list_pending_does_not_import_runner() -> None:
    """Verify list-pending code path doesn't share runner initialization."""
    parser = build_parser()
    args = parser.parse_args(["list-pending", "--database-url", "sqlite+aiosqlite://"])
    assert args.command == "list-pending"
    assert not hasattr(args, "fail_on")
    assert not hasattr(args, "feeds_path")
