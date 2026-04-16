"""CLI for the RSS ingest worker.

Usage::

    python -m worker.ingest run --database-url <url>
    python -m worker.ingest list-pending --database-url <url> [--limit 20] [--json]

Subcommands:
  run           Fetch all enabled feeds and write to staging.
  list-pending  Read-only: show staging rows with status='pending'.

Exit codes:
  0   Success (or warn-only under default --fail-on none)
  2   Run-level failure (all feeds failed) OR warn triggered
      with --fail-on warn
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from worker.bootstrap.aliases import load_aliases
from worker.bootstrap.audit import new_uuid7
from worker.bootstrap.tables import staging_table
from worker.data_quality.sinks.db import DbSink
from worker.data_quality.sinks.stdout import StdoutSink
from worker.ingest.audit import IngestRunMeta
from worker.ingest.config import default_feeds_path, load_feeds
from worker.ingest.fetcher import RssFetcher
from worker.ingest.runner import run_rss_ingest


__all__ = ["main"]


EXIT_OK = 0
EXIT_FAILURE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m worker.ingest",
        description="RSS ingest worker for DPRK CTI staging pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    run_p = sub.add_parser("run", help="Fetch feeds and write to staging")
    run_p.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy database URL (async driver)",
    )
    run_p.add_argument(
        "--feeds-path",
        type=Path,
        default=None,
        help=f"Path to feeds.yml. Defaults to {default_feeds_path()}.",
    )
    run_p.add_argument(
        "--aliases-path",
        type=Path,
        default=None,
        help="Path to aliases.yml for tag preview.",
    )
    run_p.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Override run_id (uuid). Defaults to a fresh uuid7.",
    )
    run_p.add_argument(
        "--dq-report-path",
        type=Path,
        default=None,
        help="Optional JSONL path for DQ metric mirror.",
    )
    run_p.add_argument(
        "--fail-on",
        choices=("error", "warn", "none"),
        default="none",
        help="Exit 2 when DQ severity meets this level. Default: none.",
    )

    # --- list-pending ---
    lp = sub.add_parser("list-pending", help="Show pending staging rows (read-only)")
    lp.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy database URL (async driver)",
    )
    lp.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max rows to return. Default: 20.",
    )
    lp.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output as JSON array.",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        code = asyncio.run(_run_command(args))
    elif args.command == "list-pending":
        code = asyncio.run(_list_pending_command(args))
    else:
        code = EXIT_FAILURE
    sys.exit(code)


async def _run_command(args: argparse.Namespace) -> int:
    feeds_path = args.feeds_path or default_feeds_path()
    catalog = load_feeds(feeds_path)

    aliases_path = args.aliases_path
    if aliases_path is None:
        from worker.bootstrap.cli import _default_aliases_path
        aliases_path = _default_aliases_path()
    aliases = load_aliases(aliases_path)

    run_id = uuid.UUID(args.run_id) if args.run_id else new_uuid7()

    audit_meta = IngestRunMeta(
        run_id=run_id,
        feeds_path=str(feeds_path),
        started_at=dt.datetime.now(dt.timezone.utc),
    )

    engine = create_async_engine(args.database_url, echo=False)

    sinks: list = [StdoutSink()]
    if args.dq_report_path:
        from worker.data_quality.sinks.jsonl import JsonlSink
        sinks.append(JsonlSink(path=args.dq_report_path))

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                sinks.append(DbSink(session=session, run_id=run_id))
                fetcher = RssFetcher()
                try:
                    outcome = await run_rss_ingest(
                        session,
                        catalog=catalog,
                        fetcher=fetcher,
                        aliases=aliases,
                        run_id=run_id,
                        audit_meta=audit_meta,
                        sinks=sinks,
                    )
                finally:
                    await fetcher.close()
    finally:
        await engine.dispose()

    _print_summary(outcome)

    if outcome.all_feeds_failed:
        return EXIT_FAILURE

    return _decide_exit_code(outcome, args.fail_on)


def _decide_exit_code(outcome: object, fail_on: str) -> int:
    """Check DQ results against --fail-on threshold."""
    from worker.ingest.runner import RunOutcome
    assert isinstance(outcome, RunOutcome)

    if fail_on == "none":
        return EXIT_OK

    for r in outcome.dq_results:
        if fail_on == "warn" and r.severity in ("warn", "error"):
            return EXIT_FAILURE
        if fail_on == "error" and r.severity == "error":
            return EXIT_FAILURE

    return EXIT_OK


def _print_summary(outcome: object) -> None:
    from worker.ingest.runner import RunOutcome
    assert isinstance(outcome, RunOutcome)

    print(f"RSS Ingest - run_id={outcome.run_id}")
    print("-" * 60)
    print(f"  Feeds processed:    {len(outcome.feed_results)}")
    print(f"  Inserted:           {outcome.total_inserted}")
    print(f"  Skipped (dup):      {outcome.total_skipped_duplicate}")
    print(f"  Fetch failures:     {outcome.total_fetch_failures}")
    print(f"  Parse errors:       {outcome.total_parse_errors}")
    if outcome.all_feeds_failed:
        print("  STATUS: ALL FEEDS FAILED")
    print("-" * 60)


# ---------------------------------------------------------------------------
# list-pending — completely separate read-only path
# ---------------------------------------------------------------------------


async def _list_pending_command(args: argparse.Namespace) -> int:
    engine = create_async_engine(args.database_url, echo=False)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await session.execute(
                sa.select(
                    staging_table.c.id,
                    staging_table.c.url_canonical,
                    staging_table.c.title,
                    staging_table.c.published,
                    staging_table.c.created_at,
                )
                .where(staging_table.c.status == "pending")
                .order_by(staging_table.c.created_at.desc())
                .limit(args.limit)
            )
            rows = result.all()
    finally:
        await engine.dispose()

    if args.as_json:
        data = [
            {
                "id": row.id,
                "url_canonical": row.url_canonical,
                "title": row.title,
                "published": str(row.published) if row.published else None,
                "created_at": str(row.created_at) if row.created_at else None,
            }
            for row in rows
        ]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Pending staging rows (limit {args.limit}):")
        print("-" * 60)
        for row in rows:
            title_short = (row.title or "(no title)")[:50]
            print(f"  [{row.id}] {title_short}")
            print(f"        {row.url_canonical}")
        print(f"\n{len(rows)} row(s) returned.")

    return EXIT_OK
