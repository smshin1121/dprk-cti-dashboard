"""Regression test: ``worker.bootstrap.tables`` docstring claims the canonical migration range.

Catches the silent-drift class where a new migration lands in
``db/migrations/versions/``, the mirror module picks up new columns,
but the module-level docstring's migration list doesn't move in
lock-step. A reader scanning the docstring to understand which
migrations the worker mirror covers would otherwise see a stale claim.

The test is intentionally lenient about the EXACT phrasing — it
extracts the highest 4-digit migration number from the docstring and
asserts it is >= the actual max in ``db/migrations/versions/``. This
allows the docstring to either:

  - Mirror the migration explicitly (e.g. "0010 adds new column X")
  - Note it as out-of-scope (e.g. "0010 is API-only — NOT mirrored")

Either way the migration must be mentioned. Forgetting it entirely is
what this test prevents.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from worker.bootstrap import tables as worker_tables


def _migrations_dir() -> Path:
    """Locate ``db/migrations/versions`` from this test file.

    Layout: ``<repo>/services/worker/tests/unit/test_tables_docstring.py``
    so ``parents[4]`` is ``<repo>``.
    """
    return Path(__file__).resolve().parents[4] / "db" / "migrations" / "versions"


def _max_migration_number(migrations: Path) -> int:
    """Return the highest 4-digit prefix among ``NNNN_*.py`` files."""
    return max(
        int(p.stem.split("_", 1)[0])
        for p in migrations.glob("[0-9][0-9][0-9][0-9]_*.py")
    )


def _max_migration_in_docstring(doc: str) -> int:
    """Return the highest 4-digit number mentioned in ``doc``."""
    matches = re.findall(r"\b(\d{4})\b", doc)
    assert matches, f"docstring must mention migration version numbers; got: {doc!r}"
    return max(int(m) for m in matches)


def test_migrations_dir_exists() -> None:
    """Sanity check the test's path-resolution logic still finds the migrations."""
    migrations = _migrations_dir()
    assert migrations.is_dir(), (
        f"expected migrations dir at {migrations}; the relative-path math in "
        f"_migrations_dir() may be wrong if the repo was restructured."
    )


def test_worker_tables_docstring_covers_current_migration_head() -> None:
    """The ``worker.bootstrap.tables`` docstring must reference up to the max migration.

    Fails when a new migration is added under ``db/migrations/versions/``
    and the contributor forgets to update this docstring. Either mention
    the new migration as in-scope or out-of-scope — both satisfy the test.
    """
    doc = worker_tables.__doc__
    assert doc is not None, "worker.bootstrap.tables module must have a docstring"

    actual_max = _max_migration_number(_migrations_dir())
    claimed_max = _max_migration_in_docstring(doc)

    assert claimed_max >= actual_max, (
        f"worker/bootstrap/tables.py docstring's highest migration number is "
        f"{claimed_max:04d}, but db/migrations/versions/ has "
        f"{actual_max:04d}. Either mirror the new migration's columns "
        f"here or note it as out-of-scope in the docstring."
    )
