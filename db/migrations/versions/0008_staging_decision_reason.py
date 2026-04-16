"""staging.decision_reason column

Revision ID: 0008_staging_decision_reason
Revises: 0007_taxii_collection_state
Create Date: 2026-04-17

Adds a single TEXT NULL column `decision_reason` to the `staging` table for
PR #10 Phase 2.1 Review/Promote API.

See docs/plans/pr10-review-promote-api.md §2.1 D1 / §2.2 C / §3 In scope
for the decision that `decision_reason` is persisted as a staging column
(REJECT-only, required) while reviewer `notes` are kept out of the schema
and land only in `audit_log.diff_jsonb.reviewer_notes`. This migration
therefore adds EXACTLY one column — no `notes` column, no CHECK constraint
changes, no other index changes.

The `status` CHECK constraint ('pending','approved','rejected','promoted',
'error') and the `reviewed_by` / `reviewed_at` / `promoted_report_id`
columns already exist from migration 0002 and are reused as-is.

Reversibility: downgrade drops the `decision_reason` column.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_staging_decision_reason"
down_revision = "0007_taxii_collection_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "staging",
        sa.Column("decision_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("staging", "decision_reason")
