"""CLI-level tests for the ``backfill-embeddings`` subcommand.

These tests verify the argparse surface + dispatch + env handling.
The core backfill logic is pinned by ``tests/unit/test_backfill.py``;
here we prove:

  - ``python -m worker.bootstrap backfill-embeddings --batch-size N``
    routes to the new subcommand.
  - Existing ``python -m worker.bootstrap --workbook ...`` still
    routes to the ingest subcommand (no CI breakage).
  - ``--batch-size`` defaults to 16, ``--sleep-seconds`` to 2.0.
  - Missing ``LLM_PROXY_URL`` / ``LLM_PROXY_INTERNAL_TOKEN`` causes a
    clean exit-1 for non-dry-run; dry-run skips the requirement.
  - The subcommand prints a summary line with the six BackfillCounts
    fields.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from worker.bootstrap import backfill as backfill_module
from worker.bootstrap import cli as cli_module
from worker.bootstrap.backfill import BackfillCounts


# ---------------------------------------------------------------------------
# Dispatch + parser tests
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_backfill_subcommand_routes_to_backfill_main(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_backfill_main(args):  # noqa: ANN001
            recorded["batch_size"] = args.batch_size
            recorded["sleep_seconds"] = args.sleep_seconds
            recorded["dry_run"] = args.dry_run
            return 0

        monkeypatch.setattr(
            cli_module, "_backfill_main_async", fake_backfill_main
        )

        rc = cli_module.main([
            "backfill-embeddings",
            "--database-url",
            "postgresql+psycopg://u:p@host/db",
            "--batch-size",
            "8",
            "--sleep-seconds",
            "0.5",
            "--dry-run",
        ])

        assert rc == 0
        assert recorded == {
            "batch_size": 8,
            "sleep_seconds": 0.5,
            "dry_run": True,
        }

    def test_ingest_path_still_works_without_subcommand(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """The historical ``python -m worker.bootstrap --workbook=...``
        invocation must continue to route to the ingest CLI. No arg
        starting with ``--`` should be mistaken for a subcommand."""
        recorded: dict[str, Any] = {}

        async def fake_ingest_main(args):  # noqa: ANN001
            recorded["workbook"] = str(args.workbook)
            recorded["dry_run"] = args.dry_run
            return 0

        monkeypatch.setattr(cli_module, "_main_async", fake_ingest_main)

        wb = tmp_path / "dummy.xlsx"
        wb.write_bytes(b"")
        rc = cli_module.main([
            "--workbook",
            str(wb),
            "--dry-run",
        ])

        assert rc == 0
        assert recorded["workbook"] == str(wb)
        assert recorded["dry_run"] is True


# ---------------------------------------------------------------------------
# Parser defaults
# ---------------------------------------------------------------------------


class TestBackfillParserDefaults:
    def test_defaults(self) -> None:
        parser = cli_module.build_backfill_parser()
        args = parser.parse_args([])
        # C3 lock constants surfaced through the CLI.
        assert args.batch_size == backfill_module.MAX_BATCH_SIZE  # 16
        assert args.sleep_seconds == backfill_module.DEFAULT_SLEEP_SECONDS  # 2.0
        assert args.limit is None
        assert args.dry_run is False
        assert args.database_url is None

    def test_explicit_flags(self) -> None:
        parser = cli_module.build_backfill_parser()
        args = parser.parse_args([
            "--database-url", "sqlite+aiosqlite:///:memory:",
            "--batch-size", "10",
            "--limit", "50",
            "--sleep-seconds", "0.1",
            "--dry-run",
        ])
        assert args.database_url == "sqlite+aiosqlite:///:memory:"
        assert args.batch_size == 10
        assert args.limit == 50
        assert args.sleep_seconds == 0.1
        assert args.dry_run is True


# ---------------------------------------------------------------------------
# Env requirements
# ---------------------------------------------------------------------------


class TestEnvRequirements:
    def test_missing_llm_proxy_url_non_dry_run_exits_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        monkeypatch.delenv("LLM_PROXY_URL", raising=False)
        monkeypatch.delenv("LLM_PROXY_INTERNAL_TOKEN", raising=False)
        monkeypatch.setenv("BOOTSTRAP_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        rc = cli_module.main(["backfill-embeddings"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "LLM_PROXY_URL" in err
        assert "LLM_PROXY_INTERNAL_TOKEN" in err

    def test_missing_database_url_exits_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        monkeypatch.delenv("BOOTSTRAP_DATABASE_URL", raising=False)
        rc = cli_module.main(["backfill-embeddings", "--dry-run"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "BOOTSTRAP_DATABASE_URL" in err or "--database-url" in err

    def test_dry_run_does_not_require_llm_proxy_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Dry-run must be runnable without llm-proxy env because it
        never contacts the proxy — only exercises the candidate
        selection path."""
        monkeypatch.delenv("LLM_PROXY_URL", raising=False)
        monkeypatch.delenv("LLM_PROXY_INTERNAL_TOKEN", raising=False)
        monkeypatch.setenv(
            "BOOTSTRAP_DATABASE_URL",
            "sqlite+aiosqlite:///:memory:",
        )

        # We do NOT want to actually hit a database. Short-circuit
        # run_embedding_backfill so we can verify dry_run flow
        # without a live schema.
        async def fake_backfill(session, **kwargs):  # noqa: ANN001
            return BackfillCounts(
                scanned=0,
                embedded=0,
                already_populated=0,
                skipped_transient=0,
                skipped_permanent=0,
                dry_run_skipped=0,
            )

        monkeypatch.setattr(
            backfill_module, "run_embedding_backfill", fake_backfill
        )

        rc = cli_module.main(["backfill-embeddings", "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "backfill complete:" in out


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------


class TestSummaryOutput:
    def test_summary_includes_all_six_counts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Operational visibility: the six BackfillCounts fields must
        all appear in stdout so an operator / cron log can see
        success / failure distribution at a glance."""
        monkeypatch.setenv(
            "BOOTSTRAP_DATABASE_URL",
            "sqlite+aiosqlite:///:memory:",
        )
        monkeypatch.setenv("LLM_PROXY_URL", "http://llm-proxy.local")
        monkeypatch.setenv("LLM_PROXY_INTERNAL_TOKEN", "t")

        async def fake_backfill(session, **kwargs):  # noqa: ANN001
            return BackfillCounts(
                scanned=100,
                embedded=80,
                already_populated=5,
                skipped_transient=10,
                skipped_permanent=5,
                dry_run_skipped=0,
            )

        monkeypatch.setattr(
            backfill_module, "run_embedding_backfill", fake_backfill
        )

        rc = cli_module.main(["backfill-embeddings"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "scanned=100" in out
        assert "embedded=80" in out
        assert "already_populated=5" in out
        assert "skipped_transient=10" in out
        assert "skipped_permanent=5" in out
        assert "dry_run_skipped=0" in out
