"""Tests for the CLI wrapper layer in worker.bootstrap.cli.

The heavy end-to-end work is in
``services/worker/tests/integration/test_bootstrap_cli.py``. This
module covers the thin argparse / flag-resolution surface so
coverage on ``cli.py`` stays meaningful even though production's
``main()`` path opens a real async engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worker.bootstrap.cli import (
    _DEFAULT_ALIASES_PATH,
    _DEFAULT_ERRORS_PATH,
    _resolve_dead_letter_path,
    build_parser,
    main,
)


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def test_build_parser_requires_workbook() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_minimal_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["--workbook", "sample.xlsx"])
    assert args.workbook == Path("sample.xlsx")
    assert args.aliases_path == _DEFAULT_ALIASES_PATH
    assert args.errors_path == str(_DEFAULT_ERRORS_PATH)
    assert args.dry_run is False
    assert args.limit is None
    assert args.database_url is None


def test_build_parser_full_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--workbook",
            "sample.xlsx",
            "--aliases-path",
            "custom/aliases.yml",
            "--errors-path",
            "out/errors.jsonl",
            "--dry-run",
            "--limit",
            "100",
            "--database-url",
            "postgresql+psycopg://localhost/x",
        ]
    )
    assert args.workbook == Path("sample.xlsx")
    assert args.aliases_path == Path("custom/aliases.yml")
    assert args.errors_path == "out/errors.jsonl"
    assert args.dry_run is True
    assert args.limit == 100
    assert args.database_url == "postgresql+psycopg://localhost/x"


def test_build_parser_limit_must_be_int() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--workbook", "x.xlsx", "--limit", "not-a-number"])


# ---------------------------------------------------------------------------
# _resolve_dead_letter_path
# ---------------------------------------------------------------------------


def test_resolve_dead_letter_path_empty_string_is_none() -> None:
    assert _resolve_dead_letter_path("") is None


def test_resolve_dead_letter_path_wraps_string_as_path() -> None:
    resolved = _resolve_dead_letter_path("artifacts/errors.jsonl")
    assert resolved == Path("artifacts/errors.jsonl")


# ---------------------------------------------------------------------------
# main() error paths
# ---------------------------------------------------------------------------


def test_main_without_database_url_on_real_run_returns_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A NON-dry-run without --database-url or $BOOTSTRAP_DATABASE_URL
    must exit 1 with a stderr diagnostic, not silently exit 0 or
    hang on a connection attempt."""
    monkeypatch.delenv("BOOTSTRAP_DATABASE_URL", raising=False)

    # Create a placeholder workbook so argparse's existence check
    # does not short-circuit; the loader itself is never invoked
    # because the DB URL resolution fails first.
    fake_workbook = tmp_path / "placeholder.xlsx"
    fake_workbook.write_bytes(b"")

    exit_code = main(
        [
            "--workbook",
            str(fake_workbook),
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "BOOTSTRAP_DATABASE_URL" in captured.err or "--database-url" in captured.err


def test_main_dry_run_without_database_url_uses_in_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Codex round-1 finding: dry-run must not require a
    database URL. With --dry-run set and no DB configured, the CLI
    falls back to an in-memory sqlite engine, provisions the schema
    on the fly, and runs the pipeline end-to-end."""
    monkeypatch.delenv("BOOTSTRAP_DATABASE_URL", raising=False)

    repo_root = Path(__file__).resolve().parents[4]
    fixture = repo_root / "services/worker/tests/fixtures/bootstrap_sample.xlsx"

    exit_code = main(
        [
            "--workbook",
            str(fixture),
            "--dry-run",
            "--errors-path",
            "",
        ]
    )

    # The committed stress fixture trips the 5% threshold, so the
    # exit code reflects that (2), NOT 1. 1 would indicate the CLI
    # refused to run, which is exactly the regression this test
    # prevents.
    assert exit_code in (0, 2)
