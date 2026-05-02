"""correlation_coverage table

Revision ID: 0009_correlation_coverage
Revises: 0008_staging_decision_reason
Create Date: 2026-05-03

Creates the correlation_coverage table for Phase 3 Slice 3 D-1 correlation
analysis. See docs/plans/phase-3-slice-3-correlation.md §4.2 + §11 PR A
and docs/plans/pr28-correlation-be.md §4 for the full design rationale.

Per-month coverage classification keyed on (series_root, bucket). The
correlation aggregator queries this table during dense-grid construction
to mark months as 'no_data' (vs the default 'valid' for any month not in
the table). This is the no_data vs zero_count distinction locked in the
umbrella spec — zero-fill is mathematically convenient but lies when
data is structurally absent (pre-bootstrap windows, vendor outages).

Schema:
    series_root  TEXT NOT NULL  -- one of: 'reports.published', 'incidents.reported'
    bucket       TEXT NOT NULL  -- 'YYYY-MM'
    status       TEXT NOT NULL  -- 'valid' | 'no_data' (CHECK)
    PRIMARY KEY (series_root, bucket)

Index:
    ix_correlation_coverage_series_root  -- per-root sweep on aggregator path

Status CHECK constraint matches dq_events convention (explicit DB-level
rejection of unknown severity bands). Adding a third status value
('un_normalized', 'partial', etc.) is a deliberate future-slice
migration, not a silent absorb.

Seed strategy (§4.2 of PR A plan):
    - reports.published: months strictly before min(reports.published)
      get status='no_data'. Bounded below by 1900-01 for safety.
    - incidents.reported: same, strictly before min(incidents.reported).
    - Internal no_data periods (vendor outages, etc.) are NOT seeded
      here; they live in a follow-up extension once the DQ ledger
      evolves (LC-7 future).

For sqlite test environments where min() over an empty table returns
NULL, the migration falls back to a hardcoded earliest-month (2009-01)
to keep the seed deterministic. The table's primary purpose in tests
is to exercise the no_data branch; deterministic seed > realistic seed.

Reversibility: downgrade drops the index then the table. Empty DBs
round-trip cleanly through the CI reversibility step.
"""

from __future__ import annotations

import datetime as dt

from alembic import op
import sqlalchemy as sa


revision = "0009_correlation_coverage"
down_revision = "0008_staging_decision_reason"
branch_labels = None
depends_on = None


_BASELINE_FLOOR_MONTH = "1900-01"
_FALLBACK_EARLIEST_MONTH = "2009-01"  # used when source tables are empty


def _coerce_to_year_month(value: object) -> tuple[int, int] | None:
    """Coerce a ``MIN(<date>)`` query result into ``(year, month)``.

    PG returns a ``date``/``datetime`` object; sqlite typically returns a
    string in ISO-8601 format because raw ``sa.text`` queries do not
    bind to a typed column. Handle both — and ``None`` for empty tables.
    """
    if value is None:
        return None
    if isinstance(value, (dt.datetime, dt.date)):
        return (value.year, value.month)
    if isinstance(value, str):
        try:
            parsed = dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
        return (parsed.year, parsed.month)
    return None


def _seed_no_data_for_root(
    bind: sa.engine.Connection,
    *,
    series_root: str,
    source_table: str,
    source_column: str,
) -> None:
    """Compute earliest source-table date and insert no_data rows for
    months strictly before that earliest month. The earliest month is
    inclusive; we mark only the prior months as no_data.

    Dialect-portable: PG and sqlite both support the date arithmetic via
    a Python-side bucket generator, so the migration computes the month
    range in Python and issues parameterized INSERTs. This avoids
    Postgres-only generate_series. The earliest-date result type
    differs between dialects (PG returns date, sqlite returns string)
    so ``_coerce_to_year_month`` normalizes both shapes.
    """
    earliest_row = bind.execute(
        sa.text(
            f"SELECT MIN({source_column}) AS earliest FROM {source_table}"  # noqa: S608
        )
    ).fetchone()
    earliest_value = earliest_row.earliest if earliest_row else None

    coerced = _coerce_to_year_month(earliest_value)
    if coerced is None:
        earliest_year, earliest_month = (
            int(part) for part in _FALLBACK_EARLIEST_MONTH.split("-")
        )
    else:
        earliest_year, earliest_month = coerced

    floor_year, floor_month = (
        int(part) for part in _BASELINE_FLOOR_MONTH.split("-")
    )

    rows: list[dict[str, str]] = []
    year, month = floor_year, floor_month
    while (year, month) < (earliest_year, earliest_month):
        rows.append(
            {
                "series_root": series_root,
                "bucket": f"{year:04d}-{month:02d}",
                "status": "no_data",
            }
        )
        month += 1
        if month > 12:
            year += 1
            month = 1

    if not rows:
        return

    bind.execute(
        sa.text(
            "INSERT INTO correlation_coverage (series_root, bucket, status) "
            "VALUES (:series_root, :bucket, :status)"
        ),
        rows,
    )


def upgrade() -> None:
    op.create_table(
        "correlation_coverage",
        sa.Column("series_root", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "series_root", "bucket", name="pk_correlation_coverage"
        ),
        sa.CheckConstraint(
            "status IN ('valid', 'no_data')",
            name="correlation_coverage_status_allowed",
        ),
    )

    op.create_index(
        "ix_correlation_coverage_series_root",
        "correlation_coverage",
        ["series_root"],
        unique=False,
    )

    bind = op.get_bind()

    _seed_no_data_for_root(
        bind,
        series_root="reports.published",
        source_table="reports",
        source_column="published",
    )
    _seed_no_data_for_root(
        bind,
        series_root="incidents.reported",
        source_table="incidents",
        source_column="reported",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_correlation_coverage_series_root",
        table_name="correlation_coverage",
    )
    op.drop_table("correlation_coverage")
