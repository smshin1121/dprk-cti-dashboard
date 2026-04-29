"""Command-line entry point for the data-quality gate.

Usage::

    python -m worker.data_quality check \\
        --database-url postgresql+psycopg://postgres:postgres@localhost:5432/dprk_cti \\
        [--run-id 01JGXXX...] \\
        [--workbook-sha256 a9b3c...] \\
        [--aliases-path data/dictionaries/aliases.yml] \\
        [--report-path artifacts/dq_report.jsonl] \\
        [--fail-on error|warn|none]

    python -m worker.data_quality report --since 1d   # stub, not implemented

Exit codes:

  0   Check passed per ``--fail-on`` (default: worst severity is
      either ``pass`` or ``warn``) AND every sink wrote successfully.
  1   CLI configuration error (missing ``--database-url``, bad
      argparse input, engine creation failure, aliases load failure).
  2   Check failed: either the DQ registry produced at least one
      expectation whose severity exceeded the ``--fail-on`` threshold,
      OR at least one sink raised during fan-out. These two failure
      modes share an exit code because both require operator
      intervention and the ``dq_events`` / JSONL / stdout records
      carry enough detail to distinguish them post-hoc.
  3   ``report`` subcommand invoked — PR #7 ships the argparse
      surface only; real implementation lands in a later PR.

Flag semantics:

  ``--database-url``
    Required. SQLAlchemy async URL pointed at a Postgres instance
    the Bootstrap ETL has already populated. The DQ gate does NOT
    provision the schema; the caller is responsible for running
    ``alembic upgrade head`` and the bootstrap CLI beforehand.

  ``--run-id``
    Optional UUID (any version) used to tag every ``dq_events`` row
    written during this invocation. When omitted, a fresh uuid7 is
    generated at CLI entry. Matching a specific bootstrap run's
    ``audit_log.diff_jsonb.meta.run_id`` lets a reviewer join
    lineage and quality events in a single SQL query.

  ``--workbook-sha256``
    Optional SHA-256 hex digest of the workbook used in the
    preceding bootstrap run. Printed in the pre-run header but NOT
    stored in ``dq_events`` (the table has no such column). Use it
    as a human-readable sanity check when chaining bootstrap and
    DQ invocations.

  ``--aliases-path``
    YAML alias dictionary path. Defaults to the repo-checkout
    location; packaged-wheel installations fall back to the
    hatch-included copy in ``worker/bootstrap/data/aliases.yml``.

  ``--report-path``
    Optional path for the JSONL mirror artifact. Omitting the flag
    disables the JSONL sink entirely; the stdout and DB sinks always
    run.

  ``--fail-on``
    Threshold for non-zero exit code. ``error`` (default): exit 2
    if any result has severity ``error``. ``warn``: exit 2 on warn
    or error. ``none``: never fail on severity (still fails on sink
    errors — infrastructure failure is independent of data quality).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys
import uuid
from pathlib import Path
from typing import Literal, Sequence, TextIO

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from worker.bootstrap.aliases import AliasDictionary, load_aliases
from worker.bootstrap.audit import new_uuid7
from worker.data_quality.expectations import build_all_expectations
from worker.data_quality.results import RunnerOutcome
from worker.data_quality.runner import run_expectations
from worker.data_quality.sinks import DbSink, JsonlSink, StdoutSink


__all__ = [
    "build_parser",
    "main",
    "run_check",
    "run_check_on_session",
    "run_report",
]


_PACKAGE_DIR = Path(__file__).resolve().parents[0]
_DATABASE_URL_ENV_VAR = "DQ_DATABASE_URL"

_FailOn = Literal["error", "warn", "none"]
_VALID_FAIL_ON: frozenset[str] = frozenset({"error", "warn", "none"})


# Exit code constants — matches the matrix documented at module top.
EXIT_OK: int = 0
EXIT_CONFIG_ERROR: int = 1
EXIT_CHECK_FAILED: int = 2
EXIT_REPORT_STUB: int = 3


# ---------------------------------------------------------------------------
# Default aliases path resolution (mirrors worker.bootstrap.cli pattern)
# ---------------------------------------------------------------------------


def _default_aliases_path() -> Path:
    """Resolve the default alias-dictionary path.

    Repo checkout: ``<repo>/data/dictionaries/aliases.yml``
    Installed wheel: ``<package>/worker/bootstrap/data/aliases.yml``
    """
    # worker/data_quality/cli.py is five parents below the repo root
    # (services/worker/src/worker/data_quality/cli.py → repo).
    checkout_candidate = _PACKAGE_DIR.parents[4] / "data/dictionaries/aliases.yml"
    if checkout_candidate.exists():
        return checkout_candidate
    packaged_candidate = _PACKAGE_DIR.parents[0] / "bootstrap/data/aliases.yml"
    return packaged_candidate


_DEFAULT_ALIASES_PATH = _default_aliases_path()


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI's argparse parser.

    Exposed as a module-level function so tests can instantiate the
    parser without touching ``sys.argv``.
    """
    parser = argparse.ArgumentParser(
        prog="python -m worker.data_quality",
        description=(
            "Run the Phase 1.2 data quality gate against a populated "
            "bootstrap schema."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ---- check subcommand ------------------------------------------------
    check = subparsers.add_parser(
        "check",
        help="Run the 11-item expectation registry and write results "
        "to stdout / dq_events / optional JSONL mirror.",
    )
    check.add_argument(
        "--database-url",
        type=str,
        default=None,
        help=(
            f"SQLAlchemy async URL for the populated bootstrap schema. "
            f"Falls back to the ${_DATABASE_URL_ENV_VAR} env var. "
            f"Required."
        ),
    )
    check.add_argument(
        "--run-id",
        type=str,
        default=None,
        help=(
            "Optional UUID tag for every dq_events row written "
            "during this run. A fresh uuid7 is generated when omitted."
        ),
    )
    check.add_argument(
        "--workbook-sha256",
        type=str,
        default=None,
        help=(
            "Optional SHA-256 of the workbook used in the preceding "
            "bootstrap run. Printed in the pre-run header only; not "
            "stored in dq_events."
        ),
    )
    check.add_argument(
        "--aliases-path",
        type=Path,
        default=_DEFAULT_ALIASES_PATH,
        help=(
            f"YAML alias dictionary. Defaults to {_DEFAULT_ALIASES_PATH}."
        ),
    )
    check.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help=(
            "Optional path for the JSONL mirror artifact. Omitting "
            "disables the JSONL sink entirely."
        ),
    )
    check.add_argument(
        "--fail-on",
        choices=sorted(_VALID_FAIL_ON),
        default="error",
        help=(
            "Severity threshold that triggers exit code 2. Default "
            "``error`` matches CI expectations; ``warn`` tightens for "
            "local review; ``none`` disables severity-based failure "
            "(sink errors still fail)."
        ),
    )

    # ---- report subcommand (stub) ---------------------------------------
    report = subparsers.add_parser(
        "report",
        help="Aggregate recent dq_events rows (NOT IMPLEMENTED in PR #7).",
    )
    report.add_argument(
        "--since",
        type=str,
        default="1d",
        help=(
            "Aggregation window for the report. Accepted as a stub "
            "for forward compatibility; implementation lands in a "
            "later PR."
        ),
    )

    return parser


# ---------------------------------------------------------------------------
# Exit-code decision
# ---------------------------------------------------------------------------


def decide_exit_code(outcome: RunnerOutcome, fail_on: _FailOn) -> int:
    """Map a :class:`RunnerOutcome` + ``fail_on`` policy to an exit code.

    Sink failures ALWAYS produce :data:`EXIT_CHECK_FAILED` regardless
    of ``fail_on``, because a sink write raising is an
    infrastructure issue the DQ suite cannot silently ignore.
    """
    if outcome.had_sink_failure:
        return EXIT_CHECK_FAILED
    if fail_on == "none":
        return EXIT_OK
    if fail_on == "error":
        return (
            EXIT_CHECK_FAILED
            if outcome.worst_severity == "error"
            else EXIT_OK
        )
    if fail_on == "warn":
        return (
            EXIT_CHECK_FAILED
            if outcome.worst_severity in ("warn", "error")
            else EXIT_OK
        )
    raise ValueError(f"unknown --fail-on value: {fail_on!r}")


# ---------------------------------------------------------------------------
# run_check_on_session — test-facing entry point
# ---------------------------------------------------------------------------


async def run_check_on_session(
    session: AsyncSession,
    *,
    aliases: AliasDictionary,
    run_id: uuid.UUID,
    workbook_sha256: str | None = None,
    report_path: Path | None = None,
    fail_on: _FailOn = "error",
    stdout: TextIO | None = None,
) -> tuple[RunnerOutcome, int]:
    """Run the DQ gate against an already-open :class:`AsyncSession`.

    Tests pass in their own session (backed by sqlite-memory via
    ``conftest.db_session``) and inspect the returned
    :class:`RunnerOutcome` + exit code directly. The :func:`main`
    wrapper opens a real engine for production invocations and
    calls this function under the hood.

    Commit semantics: this function does NOT call
    ``session.commit()`` or ``session.rollback()``. The caller is
    responsible for durability. Tests can skip the commit; the
    production CLI commits right after run_check_on_session returns.
    """
    stream = stdout if stdout is not None else sys.stdout

    # Pre-run header — human-readable context that does NOT get
    # persisted to dq_events.
    stream.write("Data Quality Gate\n")
    stream.write(f"  run_id: {run_id}\n")
    if workbook_sha256:
        stream.write(f"  workbook_sha256: {workbook_sha256}\n")
    stream.write("\n")

    expectations = build_all_expectations(aliases)

    sinks: list = [StdoutSink(stream), DbSink(session, run_id)]
    if report_path is not None:
        sinks.append(JsonlSink(report_path, run_id))

    outcome = await run_expectations(session, expectations, sinks)

    # Emit a sink-error summary so operators see which sinks failed
    # without having to grep the exit code alone.
    if outcome.had_sink_failure:
        stream.write("\nSink errors:\n")
        for err in outcome.sink_errors:
            stream.write(
                f"  [{err.sink_name}] {err.error_type}: "
                f"{err.error_message}\n"
            )

    exit_code = decide_exit_code(outcome, fail_on)
    return outcome, exit_code


# ---------------------------------------------------------------------------
# run_check — high-level entry (opens engine + session + commits)
# ---------------------------------------------------------------------------


async def run_check(
    *,
    database_url: str,
    run_id: uuid.UUID | None = None,
    workbook_sha256: str | None = None,
    aliases_path: Path | None = None,
    report_path: Path | None = None,
    fail_on: _FailOn = "error",
    stdout: TextIO | None = None,
) -> int:
    """Open a fresh engine, run the DQ gate, commit, return exit code.

    This is the function the CLI's ``check`` subcommand invokes.
    Tests that want to skip engine setup call
    :func:`run_check_on_session` with their own session instead.
    """
    effective_run_id = run_id or new_uuid7()
    effective_aliases_path = aliases_path or _DEFAULT_ALIASES_PATH

    aliases = load_aliases(effective_aliases_path)

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            outcome, exit_code = await run_check_on_session(
                session,
                aliases=aliases,
                run_id=effective_run_id,
                workbook_sha256=workbook_sha256,
                report_path=report_path,
                fail_on=fail_on,
                stdout=stdout,
            )
            # Sink failures typically leave the pg transaction in an
            # aborted state (Codex review P2). Committing would then
            # raise and bubble up as EXIT_CONFIG_ERROR from
            # _main_async, masking the documented EXIT_CHECK_FAILED
            # exit code for sink failures. Roll back on the failure
            # path and commit only on the clean path.
            if outcome.had_sink_failure:
                await session.rollback()
            else:
                await session.commit()
            return exit_code
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# run_report — stub
# ---------------------------------------------------------------------------


def run_report(
    *,
    since: str = "1d",
    stdout: TextIO | None = None,
) -> int:
    """Stub implementation of the ``report`` subcommand.

    PR #7 ships only the argparse surface so the CLI shape is
    stable. Actual aggregation against ``dq_events`` lands in a
    later PR once real trend data accumulates.
    """
    stream = stdout if stdout is not None else sys.stdout
    stream.write(
        f"report --since {since}: not implemented in PR #7. "
        f"Track the follow-up in docs/plans/pr7-data-quality.md "
        f"section 7 (Open Items).\n"
    )
    return EXIT_REPORT_STUB


# ---------------------------------------------------------------------------
# main — argparse dispatcher
# ---------------------------------------------------------------------------


async def _main_async(args: argparse.Namespace) -> int:
    if args.command == "check":
        database_url = args.database_url or os.environ.get(_DATABASE_URL_ENV_VAR)
        if not database_url:
            sys.stderr.write(
                f"error: --database-url or ${_DATABASE_URL_ENV_VAR} is "
                f"required for the check subcommand\n"
            )
            return EXIT_CONFIG_ERROR

        run_id: uuid.UUID | None = None
        if args.run_id is not None:
            try:
                run_id = uuid.UUID(args.run_id)
            except ValueError as exc:
                sys.stderr.write(
                    f"error: --run-id must be a valid UUID string: {exc}\n"
                )
                return EXIT_CONFIG_ERROR

        try:
            return await run_check(
                database_url=database_url,
                run_id=run_id,
                workbook_sha256=args.workbook_sha256,
                aliases_path=args.aliases_path,
                report_path=args.report_path,
                fail_on=args.fail_on,
                stdout=sys.stdout,
            )
        except Exception as exc:
            sys.stderr.write(f"error: {type(exc).__name__}: {exc}\n")
            return EXIT_CONFIG_ERROR

    if args.command == "report":
        return run_report(since=args.since, stdout=sys.stdout)

    # argparse with ``required=True`` should already have rejected
    # this case, but keep the branch for defensive completeness.
    sys.stderr.write(f"error: unknown subcommand {args.command!r}\n")
    return EXIT_CONFIG_ERROR


def _run_async(coro):  # noqa: ANN001
    """Run an async coroutine, using SelectorEventLoop on Windows."""
    if platform.system() == "Windows":
        loop_factory = asyncio.SelectorEventLoop
        return asyncio.run(coro, loop_factory=loop_factory)
    return asyncio.run(coro)


def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous CLI entry point.

    Returns the process exit code instead of calling ``sys.exit`` so
    tests can assert on the return value directly.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run_async(_main_async(args))


if __name__ == "__main__":  # pragma: no cover — module entry path
    raise SystemExit(main())
