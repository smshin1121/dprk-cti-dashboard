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

import os
import sys

from alembic import op
import sqlalchemy as sa

# env.py adds db/migrations/ to sys.path so the helper module sitting at
# db/migrations/correlation_seed.py is importable directly. The helper
# lives OUTSIDE versions/ deliberately: Alembic scans every .py file in
# versions/ as a candidate revision, and a non-revision file there
# breaks `alembic upgrade head` (Codex r3 H1).
_MIGRATIONS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _MIGRATIONS_DIR not in sys.path:
    sys.path.insert(0, _MIGRATIONS_DIR)

from correlation_seed import seed_correlation_no_data  # noqa: E402


revision = "0009_correlation_coverage"
down_revision = "0008_staging_decision_reason"
branch_labels = None
depends_on = None


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

    seed_correlation_no_data(
        bind,
        series_root="reports.published",
        source_table="reports",
        source_column="published",
    )
    seed_correlation_no_data(
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
