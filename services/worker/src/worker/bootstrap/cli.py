"""Command-line entry point for the Bootstrap ETL.

Usage (from an environment that has ``services/worker`` installed):

    python -m worker.bootstrap \\
        --workbook services/worker/tests/fixtures/bootstrap_sample.xlsx \\
        [--aliases-path data/dictionaries/aliases.yml] \\
        [--errors-path artifacts/bootstrap_errors.jsonl] \\
        [--dry-run] \\
        [--limit N] \\
        [--database-url postgresql+psycopg://...]

Flags:

  ``--workbook``      Required. Path to the v1.0 workbook to ingest.
  ``--aliases-path``  YAML alias dictionary. Defaults to the committed
                      copy at ``data/dictionaries/aliases.yml``.
  ``--errors-path``   JSONL path for row-level dead letters. The file is
                      NOT created unless at least one row fails; an
                      operator finding the file on disk can therefore
                      treat its existence as a definite signal that
                      something went wrong. Set to empty string to
                      disable the writer entirely.
  ``--dry-run``       Process every row through validation,
                      normalization, and upsert — but roll back the
                      transaction at the end. Proves the schema and
                      rules compile without persisting anything.
  ``--limit N``       Stop after ``N`` rows have been **attempted**
                      across all three sheets, in sheet-declaration
                      order (Actors → Reports → Incidents). The limit
                      is a global cap, not per-sheet.
  ``--database-url``  SQLAlchemy async URL. Falls back to the
                      ``BOOTSTRAP_DATABASE_URL`` env var. Required for
                      non-dry-run runs.

Exit codes (see :data:`worker.bootstrap.errors.DEAD_LETTER_WARNING_RATE`):

  0   Either no failures at all, or a failure rate <= 5% with a
      warning summary printed to stdout.
  2   Failure rate > 5% — trips CI and any caller that checks $?.
  1   Reserved for argparse / unexpected errors in the CLI layer
      itself (bad flag, missing workbook, unreachable database, etc.).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Sequence, TextIO

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from worker.bootstrap.aliases import AliasDictionary, load_aliases
from worker.bootstrap.audit import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    AuditBuffer,
    AuditMeta,
    new_audit_meta,
    write_run_audit,
)
from worker.bootstrap.errors import (
    DeadLetterEntry,
    DeadLetterWriter,
    ExitCode,
    ExitDecision,
    decide_exit_code,
)
from worker.bootstrap.loader import WorkbookLoader, WorkbookLoaderError
from worker.bootstrap.schemas import (
    ActorRow,
    IncidentRow,
    ReportRow,
    RowValidationError,
)
from worker.bootstrap.upsert import upsert_actor, upsert_incident, upsert_report


__all__ = [
    "build_parser",
    "main",
    "run_bootstrap",
]


_PACKAGE_DIR = Path(__file__).resolve().parents[0]
_DEFAULT_ERRORS_PATH = Path("artifacts/bootstrap_errors.jsonl")
_DATABASE_URL_ENV_VAR = "BOOTSTRAP_DATABASE_URL"


def _default_aliases_path() -> Path:
    """Resolve the default alias-dictionary path across both
    deployment modes.

    1. **Repo checkout.** cli.py lives five parents below the repo
       root (``services/worker/src/worker/bootstrap/cli.py``), so
       walking up to ``<repo>/data/dictionaries/aliases.yml`` hits
       the canonical shared copy.
    2. **Installed wheel.** The shared copy is mirrored into the
       worker package via the hatch ``force-include`` rule in
       ``services/worker/pyproject.toml``, landing at
       ``worker/bootstrap/data/aliases.yml``. We resolve it next to
       ``cli.py`` so the CLI default works even for users who never
       check out the repository.

    The resolution order is checkout -> package data so a developer
    editing the YAML in the repo still sees their edits without
    needing to reinstall the wheel.
    """
    checkout_candidate = _PACKAGE_DIR.parents[4] / "data/dictionaries/aliases.yml"
    if checkout_candidate.exists():
        return checkout_candidate
    packaged_candidate = _PACKAGE_DIR / "data/aliases.yml"
    return packaged_candidate


_DEFAULT_ALIASES_PATH = _default_aliases_path()


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI's argparse.ArgumentParser.

    Exposed as a module-level function so tests can instantiate the
    parser without touching sys.argv.
    """
    parser = argparse.ArgumentParser(
        prog="python -m worker.bootstrap",
        description="Load the v1.0 workbook into the Phase 0 schema.",
    )
    parser.add_argument(
        "--workbook",
        type=Path,
        required=True,
        help="Path to the v1.0 workbook to ingest.",
    )
    parser.add_argument(
        "--aliases-path",
        type=Path,
        default=_DEFAULT_ALIASES_PATH,
        help=(
            "YAML alias dictionary. "
            f"Defaults to {_DEFAULT_ALIASES_PATH}."
        ),
    )
    parser.add_argument(
        "--errors-path",
        type=str,
        default=str(_DEFAULT_ERRORS_PATH),
        help=(
            "JSONL path for row-level dead letters. The file is not "
            "created unless at least one row fails. Pass an empty "
            "string to disable the writer entirely."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate/normalize/upsert every row but roll back the "
            "transaction at the end. Nothing is persisted."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Global cap on rows attempted across all sheets. Applied "
            "in sheet-declaration order (Actors then Reports then "
            "Incidents). No limit by default."
        ),
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help=(
            f"SQLAlchemy async URL. Falls back to the "
            f"${_DATABASE_URL_ENV_VAR} env var. Required for non-dry-"
            f"run runs."
        ),
    )
    return parser


def _resolve_dead_letter_path(errors_path_arg: str) -> Path | None:
    """Empty string means "disable the writer". Any other string is
    interpreted as a filesystem path relative to cwd."""
    if errors_path_arg == "":
        return None
    return Path(errors_path_arg)


async def _process_one_row(
    session: AsyncSession,
    row_sheet: str,
    row_data: dict[str, object],
    aliases: AliasDictionary,
    *,
    audit_buffer: AuditBuffer | None = None,
) -> None:
    """Dispatch one loader row to the matching upsert path.

    Raises whatever the schema / upsert layer raises so the caller
    can decide whether to count it as a dead-letter failure.

    When ``audit_buffer`` is provided, the composite upsert functions
    append row-level audit events for each nested audited entity they
    touch (D3 scope: groups, sources, codenames, reports, incidents).
    """
    if row_sheet == "Actors":
        validated = ActorRow(**row_data)
        await upsert_actor(session, validated, aliases, audit_buffer=audit_buffer)
    elif row_sheet == "Reports":
        validated = ReportRow(**row_data)
        await upsert_report(session, validated, aliases, audit_buffer=audit_buffer)
    elif row_sheet == "Incidents":
        validated = IncidentRow(**row_data)
        await upsert_incident(session, validated, audit_buffer=audit_buffer)
    else:
        raise WorkbookLoaderError(f"unknown sheet {row_sheet!r}")


async def run_bootstrap(
    session: AsyncSession,
    *,
    workbook: Path,
    aliases_path: Path,
    errors_path: Path | None,
    dry_run: bool,
    limit: int | None,
    stdout: TextIO,
    audit_meta: AuditMeta | None = None,
) -> ExitDecision:
    """Run the full Bootstrap ETL pipeline against ``session``.

    This is the test-facing entry point. Tests pass in their own
    session (backed by sqlite-memory via conftest) and inspect the
    returned :class:`ExitDecision` directly. The ``main()`` wrapper
    opens a real engine for production invocations.

    ``audit_meta`` controls whether row-level and run-level audit
    records are emitted. **None** (the default, and the PR #6
    backward-compat path) leaves the transaction flow exactly as
    landed in PR #6: no audit writes, non-caller-owned outer rolls
    back on any failure. **Set** (the production path, always supplied
    by the CLI for non-dry-run invocations) activates the D3 / D4
    layout:

    1. Before the ETL savepoint is opened, ``etl_run_started`` is
       written into the outer transaction directly.
    2. Inside the savepoint, an :class:`AuditBuffer` collects row-
       level events through the upsert loop. Each workbook row
       captures a :meth:`AuditBuffer.mark` cut-point, and a per-row
       savepoint failure calls :meth:`AuditBuffer.rollback_to` so
       ONLY that row's buffered events are discarded — prior
       successful rows are preserved.
    3. After the body completes successfully, the buffer is flushed
       (still inside the ETL savepoint) and the savepoint is
       committed.
    4. On success, ``etl_run_completed`` is written into the outer
       transaction; on failure, ``etl_run_failed`` is written instead
       (both land AFTER the savepoint is resolved so they are never
       swept away by body rollback).
    5. When the outer transaction is owned by us (the caller did not
       pre-begin it), we commit it at the end of the audit flow even
       on exception — that is how ``etl_run_started`` + ``etl_run_failed``
       survive a body that rolled back. On the no-audit path we keep
       the PR #6 behavior of rolling the outer back on exception.

    ``dry_run`` and ``audit_meta`` are mutually exclusive: dry-run
    means "validate without persisting anything", and audit records
    are a persistence side-effect, so the combination is rejected to
    make the expectation explicit at the call site.
    """
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be a positive integer")
    if dry_run and audit_meta is not None:
        raise ValueError(
            "dry_run and audit_meta are mutually exclusive: dry-run persists "
            "nothing and audit trails are a persistence side-effect"
        )

    loader = WorkbookLoader(workbook)
    aliases = load_aliases(aliases_path)

    total = 0
    failures = 0

    # Transaction boundary: we MUST NOT commit or roll back any
    # outer transaction the caller already started. Everything ETL-
    # scoped goes inside a SAVEPOINT so our commit or rollback
    # releases or discards only the body's changes. Run-level audit
    # events live in the outer transaction (above the savepoint) so
    # they survive savepoint rollback on failure.
    caller_owns_outer = session.in_transaction()
    if audit_meta is not None and not caller_owns_outer:
        # Explicitly autobegin the outer before writing etl_run_started
        # so the RUN_STARTED insert has a transaction to land in.
        await session.begin()

    if audit_meta is not None:
        # Isolate the audit write in a savepoint so a pg INSERT
        # rejection (schema drift, permissions, etc.) does NOT leave
        # the outer transaction in an aborted state that would abort
        # the ETL body on its first begin_nested() call (Codex P2).
        try:
            async with session.begin_nested():
                await write_run_audit(
                    session, action=RUN_STARTED, meta=audit_meta
                )
        except Exception:
            # An audit-write failure at this point must not abort the
            # entire ETL. The savepoint above has rolled back so the
            # outer transaction is clean. Continue without the
            # etl_run_started record; later run-level writes may or
            # may not succeed but the body will proceed either way.
            pass

    etl_savepoint = await session.begin_nested()
    audit_buffer: AuditBuffer | None = (
        AuditBuffer(session, audit_meta) if audit_meta is not None else None
    )

    try:
        with DeadLetterWriter(errors_path) as dead_letter:
            for wb_row in loader.iter_all():
                if limit is not None and total >= limit:
                    break
                total += 1

                # Per-row cut-point: capture the audit buffer's state
                # BEFORE we enter the per-row savepoint, so that a bad
                # row can be truncated out of the buffer without
                # losing the events from prior successful rows.
                buffer_mark = (
                    audit_buffer.mark() if audit_buffer is not None else None
                )

                try:
                    async with session.begin_nested():
                        await _process_one_row(
                            session,
                            wb_row.sheet,
                            wb_row.data,
                            aliases,
                            audit_buffer=audit_buffer,
                        )
                except (RowValidationError, ValueError) as exc:
                    failures += 1
                    if audit_buffer is not None and buffer_mark is not None:
                        audit_buffer.rollback_to(buffer_mark)
                    dead_letter.write(
                        DeadLetterEntry(
                            sheet=wb_row.sheet,
                            row_index=wb_row.index,
                            raw_payload=dict(wb_row.data),
                            error_class=type(exc).__name__,
                            message=str(exc),
                        )
                    )

            # Flush the row-level buffer BEFORE resolving the savepoint
            # so the audit_log INSERTs participate in the same
            # rollback unit as the entity rows they describe.
            if audit_buffer is not None:
                await audit_buffer.flush()

        if dry_run:
            await etl_savepoint.rollback()
            # dry_run + audit_meta is rejected above; this branch
            # runs in the no-audit case only. Close out any autobegin
            # transaction WE started so released savepoint state from
            # earlier rows does not stay visible after we return.
            if not caller_owns_outer and session.in_transaction():
                await session.rollback()
        else:
            await etl_savepoint.commit()
            if audit_meta is not None:
                # Compute the CLI decision BEFORE emitting the run-
                # level audit so a run that tripped the D5 failure
                # threshold lands in audit_log as etl_run_failed and
                # not etl_run_completed (Codex round 3 P2). A body
                # that reached this branch ran to loop completion,
                # but the decision function may still reject it on
                # failure-rate grounds. Lineage consumers and dash-
                # boards MUST see the same verdict the CLI prints.
                preview_decision = decide_exit_code(total, failures)
                if preview_decision.code == ExitCode.OK:
                    completion_action = RUN_COMPLETED
                    completion_detail: dict[str, object] = {
                        "rows_attempted": total,
                        "rows_failed": failures,
                        "dry_run": False,
                    }
                else:
                    completion_action = RUN_FAILED
                    completion_detail = {
                        "rows_attempted": total,
                        "rows_failed": failures,
                        "dry_run": False,
                        "threshold_exceeded": True,
                        "exit_code": int(preview_decision.code),
                        "summary": preview_decision.summary,
                    }
                # Same savepoint isolation as RUN_STARTED: on pg a
                # failed audit INSERT would leave the outer tx in an
                # aborted state and the final session.commit() below
                # would raise (Codex round 1 P2).
                try:
                    async with session.begin_nested():
                        await write_run_audit(
                            session,
                            action=completion_action,
                            meta=audit_meta,
                            detail=completion_detail,
                        )
                except Exception:
                    pass
            if not caller_owns_outer and session.in_transaction():
                await session.commit()
    except Exception as exc:
        if etl_savepoint.is_active:
            await etl_savepoint.rollback()

        if audit_meta is not None:
            # Emit etl_run_failed after the savepoint has been reversed
            # so this insert lands in the outer transaction and survives
            # the body rollback. Savepoint isolation (Codex P2): a
            # failed audit INSERT here must not re-aborts the outer
            # transaction before we try to commit etl_run_started +
            # etl_run_failed below. Defensive outer try/except still
            # prevents a failed audit write from masking the original
            # ETL exception — the caller needs to see the real error.
            try:
                async with session.begin_nested():
                    await write_run_audit(
                        session,
                        action=RUN_FAILED,
                        meta=audit_meta,
                        detail={
                            "error_type": type(exc).__name__,
                            "error_message": str(exc)[:1024],
                            "rows_attempted": total,
                            "rows_failed": failures,
                        },
                    )
            except Exception:
                pass
            if not caller_owns_outer:
                # Commit the outer so etl_run_started + etl_run_failed
                # persist even though the body was rolled back. This
                # is the ONLY place the audit path diverges from the
                # PR #6 backward-compat flow.
                try:
                    if session.in_transaction():
                        await session.commit()
                except Exception:
                    if session.in_transaction():
                        await session.rollback()
        else:
            # No-audit backward-compat path: roll back the outer if
            # we autobegan it, matching PR #6 behavior exactly.
            if not caller_owns_outer and session.in_transaction():
                await session.rollback()
        raise
    except BaseException:
        # KeyboardInterrupt / SystemExit: roll back savepoint and
        # outer without attempting audit writes. Audit on a
        # BaseException path is too risky (the session may be in an
        # unrecoverable state and adding writes could mask the
        # original signal).
        if etl_savepoint.is_active:
            await etl_savepoint.rollback()
        if not caller_owns_outer and session.in_transaction():
            await session.rollback()
        raise

    decision = decide_exit_code(total, failures)
    stdout.write(decision.summary + "\n")
    if dry_run:
        stdout.write("(dry-run: transaction rolled back; no rows persisted)\n")
    if dead_letter.count > 0 and errors_path is not None:
        stdout.write(f"dead-letter log: {errors_path}\n")
    return decision


_DRY_RUN_FALLBACK_URL = "sqlite+aiosqlite:///:memory:"


def _is_sqlite_memory_url(database_url: str) -> bool:
    """Return True if ``database_url`` points at an in-memory sqlite DB.

    Covers every form SQLAlchemy accepts:
      - ``sqlite:///:memory:``
      - ``sqlite+aiosqlite:///:memory:``
      - ``sqlite+pysqlite:///:memory:``
      - ``sqlite+aiosqlite://`` (no path = in-memory)
      - URLs with the ``?cache=shared`` query suffix
    """
    try:
        from sqlalchemy.engine.url import make_url

        url = make_url(database_url)
    except Exception:  # pragma: no cover — defensive
        return False
    if not url.drivername.startswith("sqlite"):
        return False
    database = url.database or ""
    return database in ("", ":memory:")


async def _main_async(args: argparse.Namespace) -> int:
    database_url = args.database_url or os.environ.get(_DATABASE_URL_ENV_VAR)

    if not database_url:
        if not args.dry_run:
            sys.stderr.write(
                f"error: --database-url or ${_DATABASE_URL_ENV_VAR} is "
                f"required for non-dry-run invocations\n"
            )
            return 1
        # Dry-run with no configured database. Fall back to an
        # in-memory sqlite engine and provision the bootstrap schema
        # on the fly so the pipeline can still exercise validation,
        # normalization, and upsert logic without any external
        # infrastructure. No data is ever persisted.
        database_url = _DRY_RUN_FALLBACK_URL

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # Provision the schema on the fly for ANY sqlite-memory URL,
        # not just the implicit fallback. An operator who passes
        # ``--database-url sqlite+aiosqlite:///:memory:`` explicitly
        # should get the same behavior as the implicit fallback —
        # anything else would make the explicit form mysteriously
        # fail with "no such table" and the two paths diverge for
        # no functional reason.
        if args.dry_run and _is_sqlite_memory_url(database_url):
            # Import locally to keep the hot path import-light for
            # production invocations that already have a real schema.
            from worker.bootstrap.tables import metadata

            async with engine.begin() as conn:
                await conn.run_sync(metadata.create_all)

        # Generate the audit meta exactly once here, at CLI entry,
        # BEFORE the first session operation. This is the load-bearing
        # "run_id exists once per invocation" invariant the user flagged
        # in review — downstream writers must not generate their own.
        # dry-run skips audit entirely because audit records are a
        # persistence side-effect (see run_bootstrap docstring).
        audit_meta: AuditMeta | None = None
        if not args.dry_run:
            audit_meta = new_audit_meta(args.workbook)

        async with session_factory() as session:
            decision = await run_bootstrap(
                session,
                workbook=args.workbook,
                aliases_path=args.aliases_path,
                errors_path=_resolve_dead_letter_path(args.errors_path),
                dry_run=args.dry_run,
                limit=args.limit,
                stdout=sys.stdout,
                audit_meta=audit_meta,
            )
            return decision.code
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous CLI entry point.

    Returns the process exit code instead of calling ``sys.exit`` so
    tests can assert on the return value directly.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":  # pragma: no cover — module entry path
    raise SystemExit(main())
