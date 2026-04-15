"""dq_events table

Revision ID: 0005_dq_events
Revises: 0004_bigint_pk_migration
Create Date: 2026-04-15

Creates the dq_events table for PR #7 Phase 1.2 Data Quality Gate.
See docs/plans/pr7-data-quality.md D5 for schema rationale.

The dq_events table records every outcome of a data-quality expectation
run, including pass rows (so trend aggregations need not infer absence).
run_id is a uuid7 generated at bootstrap entry and shared with the
lineage trail in audit_log.diff_jsonb.meta.run_id, so "what was loaded"
(audit_log) and "what quality issues occurred" (dq_events) can be
joined by a single run_id per D3/D4/D5.

Schema:
    id              BIGSERIAL PK
    run_id          UUID NOT NULL       -- shared uuid7 with audit_log meta
    expectation     TEXT NOT NULL       -- e.g. "reports.tlp.value_domain"
    severity        TEXT NOT NULL       -- 'warn' | 'error' | 'pass' (CHECK)
    observed        NUMERIC NULL        -- observed metric (e.g. 0.17)
    threshold       NUMERIC NULL        -- threshold tested against (e.g. 0.15)
    observed_rows   BIGINT  NULL        -- row count the expectation scanned
    detail_jsonb    JSONB   NOT NULL    -- per-expectation extras
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()

Indexes (per D5):
    ix_dq_events_run_id        -- per-run lookup (hot path for check CLI)
    ix_dq_events_observed_at   -- DESC, timestamp-ordered trend queries
    ix_dq_events_expectation   -- per-expectation historical trend

Severity CHECK constraint is explicit so Postgres rejects any new
severity band at the DB level. If the severity model ever grows beyond
warn/error/pass (out of scope for PR #7 — see D9), the constraint must
be altered in a future migration, which is the exact signal we want.

Reversibility: downgrade drops indexes then the table. All objects are
explicit so the CI db-migrations reversibility step (downgrade -1 ->
upgrade head) can round-trip 0005 cleanly against an empty database.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_dq_events"
down_revision = "0004_bigint_pk_migration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dq_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expectation", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("observed", sa.Numeric(), nullable=True),
        sa.Column("threshold", sa.Numeric(), nullable=True),
        sa.Column("observed_rows", sa.BigInteger(), nullable=True),
        sa.Column(
            "detail_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "severity IN ('warn', 'error', 'pass')",
            name="severity_allowed",
        ),
    )

    op.create_index(
        "ix_dq_events_run_id",
        "dq_events",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_dq_events_observed_at",
        "dq_events",
        [sa.text("observed_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_dq_events_expectation",
        "dq_events",
        ["expectation"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dq_events_expectation", table_name="dq_events")
    op.drop_index("ix_dq_events_observed_at", table_name="dq_events")
    op.drop_index("ix_dq_events_run_id", table_name="dq_events")
    op.drop_table("dq_events")
