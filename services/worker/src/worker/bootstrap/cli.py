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
) -> None:
    """Dispatch one loader row to the matching upsert path.

    Raises whatever the schema / upsert layer raises so the caller
    can decide whether to count it as a dead-letter failure.
    """
    if row_sheet == "Actors":
        validated = ActorRow(**row_data)
        await upsert_actor(session, validated, aliases)
    elif row_sheet == "Reports":
        validated = ReportRow(**row_data)
        await upsert_report(session, validated, aliases)
    elif row_sheet == "Incidents":
        validated = IncidentRow(**row_data)
        await upsert_incident(session, validated)
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
) -> ExitDecision:
    """Run the full Bootstrap ETL pipeline against ``session``.

    This is the test-facing entry point. Tests pass in their own
    session (backed by sqlite-memory via conftest) and inspect the
    returned :class:`ExitDecision` directly. The ``main()`` wrapper
    opens a real engine for production invocations.
    """
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be a positive integer")

    loader = WorkbookLoader(workbook)
    aliases = load_aliases(aliases_path)

    total = 0
    failures = 0

    # Transaction boundary: we MUST NOT commit or roll back any
    # outer transaction the caller already started. Everything we
    # do goes inside a SAVEPOINT so our commit or rollback releases
    # or discards only our own changes.
    #
    # If the caller did NOT own an outer transaction, ``begin_nested``
    # autobegins one for us (we "own" it). In that case we also
    # commit or roll back the autobegun outer so no ETL state leaks
    # into the session after the function returns. If the caller
    # DID own the outer, we leave it completely alone.
    caller_owns_outer = session.in_transaction()
    etl_savepoint = await session.begin_nested()

    try:
        with DeadLetterWriter(errors_path) as dead_letter:
            for wb_row in loader.iter_all():
                if limit is not None and total >= limit:
                    break
                total += 1

                # Per-row SAVEPOINT so one bad row does not poison
                # the enclosing transaction.
                try:
                    async with session.begin_nested():
                        await _process_one_row(
                            session, wb_row.sheet, wb_row.data, aliases
                        )
                except (RowValidationError, ValueError) as exc:
                    failures += 1
                    dead_letter.write(
                        DeadLetterEntry(
                            sheet=wb_row.sheet,
                            row_index=wb_row.index,
                            raw_payload=dict(wb_row.data),
                            error_class=type(exc).__name__,
                            message=str(exc),
                        )
                    )

        if dry_run:
            await etl_savepoint.rollback()
            # Also close out any autobegin transaction WE started so
            # released savepoint state from earlier rows does not
            # stay visible on the session after this function
            # returns. Only do this when the outer was ours — if
            # the caller owned it, leave it untouched.
            if not caller_owns_outer and session.in_transaction():
                await session.rollback()
        else:
            await etl_savepoint.commit()
            if not caller_owns_outer and session.in_transaction():
                await session.commit()
    except BaseException:
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

        async with session_factory() as session:
            decision = await run_bootstrap(
                session,
                workbook=args.workbook,
                aliases_path=args.aliases_path,
                errors_path=_resolve_dead_letter_path(args.errors_path),
                dry_run=args.dry_run,
                limit=args.limit,
                stdout=sys.stdout,
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
