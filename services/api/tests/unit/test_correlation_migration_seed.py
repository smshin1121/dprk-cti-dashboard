"""Migration 0009 seed-logic regression tests (Codex r1 HIGH 4 + r2 M2).

Pins the sqlite portability fix: ``MIN(date)`` returns a string under
sqlite (raw ``sa.text`` query) but a ``date`` under PG. The seed helper
must coerce both shapes into ``(year, month)`` and produce no_data rows
strictly before the source table's earliest date.

Tests run against a synchronous sqlite connection (the migration helper
takes ``op.get_bind()`` semantics) — close to the actual migration
environment without bootstrapping the full alembic harness.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

# Migration helper lives at db/migrations/correlation_seed.py (NOT under
# versions/, because Alembic scans every .py in versions/ as a revision —
# Codex r3 H1). env.py adds db/migrations/ to sys.path at runtime;
# for unit tests we mirror that injection.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATIONS_DIR = _REPO_ROOT / "db" / "migrations"
if str(_MIGRATIONS_DIR) not in sys.path:
    sys.path.insert(0, str(_MIGRATIONS_DIR))

from correlation_seed import seed_correlation_no_data  # noqa: E402


@pytest.fixture
def populated_engine() -> Engine:
    """Sync sqlite engine with reports and incidents tables seeded."""
    engine = sa.create_engine("sqlite:///:memory:", future=True)
    metadata = sa.MetaData()
    reports = sa.Table(
        "reports",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("published", sa.Date(), nullable=False),
    )
    incidents = sa.Table(
        "incidents",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reported", sa.Date(), nullable=False),
    )
    coverage = sa.Table(
        "correlation_coverage",
        metadata,
        sa.Column("series_root", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("series_root", "bucket"),
    )
    metadata.create_all(engine)

    with engine.begin() as conn:
        # Seed reports starting at 2015-03; incidents starting at 2018-07
        conn.execute(
            reports.insert(),
            [
                {"published": dt.date(2015, 3, 5)},
                {"published": dt.date(2020, 1, 1)},
            ],
        )
        conn.execute(
            incidents.insert(),
            [
                {"reported": dt.date(2018, 7, 15)},
                {"reported": dt.date(2024, 6, 1)},
            ],
        )
    return engine


def test_sqlite_seed_pre_bootstrap_window_for_reports(
    populated_engine: Engine,
) -> None:
    """no_data rows should cover months strictly before 2015-03."""
    with populated_engine.begin() as conn:
        seed_correlation_no_data(
            conn,
            series_root="reports.published",
            source_table="reports",
            source_column="published",
        )
        rows = conn.execute(
            sa.text(
                "SELECT bucket FROM correlation_coverage "
                "WHERE series_root='reports.published' "
                "ORDER BY bucket DESC LIMIT 3"
            )
        ).all()

    assert rows[0].bucket == "2015-02"  # last no_data month
    # 2015-03 (the earliest source month) is NOT in coverage — defaults to valid


def test_sqlite_seed_pre_bootstrap_window_for_incidents(
    populated_engine: Engine,
) -> None:
    with populated_engine.begin() as conn:
        seed_correlation_no_data(
            conn,
            series_root="incidents.reported",
            source_table="incidents",
            source_column="reported",
        )
        rows = conn.execute(
            sa.text(
                "SELECT bucket FROM correlation_coverage "
                "WHERE series_root='incidents.reported' "
                "ORDER BY bucket DESC LIMIT 3"
            )
        ).all()

    assert rows[0].bucket == "2018-06"  # last no_data month before incidents start


def test_empty_table_falls_back_to_hardcoded_earliest() -> None:
    """When source table has no rows, use 2009-01 fallback per migration."""
    engine = sa.create_engine("sqlite:///:memory:", future=True)
    metadata = sa.MetaData()
    sa.Table(
        "reports",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("published", sa.Date(), nullable=False),
    )
    sa.Table(
        "correlation_coverage",
        metadata,
        sa.Column("series_root", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("series_root", "bucket"),
    )
    metadata.create_all(engine)

    with engine.begin() as conn:
        seed_correlation_no_data(
            conn,
            series_root="reports.published",
            source_table="reports",
            source_column="published",
        )
        rows = conn.execute(
            sa.text(
                "SELECT bucket FROM correlation_coverage "
                "ORDER BY bucket DESC LIMIT 1"
            )
        ).all()

    # Fallback earliest = 2009-01, so last no_data = 2008-12
    assert rows[0].bucket == "2008-12"
