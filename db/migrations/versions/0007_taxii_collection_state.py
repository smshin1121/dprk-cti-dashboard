"""taxii_collection_state table

Revision ID: 0007_taxii_collection_state
Revises: 0006_rss_feed_state
Create Date: 2026-04-16

Creates the taxii_collection_state table for PR #9 Phase 1.3b TAXII ingest.
See docs/plans/pr9-taxii-ingest.md D4 for schema rationale.

TAXII collection runtime state (last_added_after, failure tracking) is kept
in a separate table from rss_feed_state because the polling semantics differ:
RSS uses ETag/Last-Modified (HTTP conditional GET), while TAXII uses the
`added_after` timestamp parameter for incremental polling.

Schema:
    collection_key      TEXT PK         -- matches taxii_collections.yml slug
    server_url          TEXT NOT NULL   -- TAXII server base URL (operational debug)
    collection_id       TEXT NOT NULL   -- TAXII collection identifier
    last_added_after    TEXT NULL       -- ISO-8601 timestamp for incremental poll
    last_fetched_at     TIMESTAMPTZ NULL
    last_object_count   INTEGER NULL    -- objects returned in last successful poll
    last_error          TEXT NULL       -- error message if last fetch failed
    consecutive_failures INTEGER NOT NULL DEFAULT 0
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()

Reversibility: downgrade drops the table.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_taxii_collection_state"
down_revision = "0006_rss_feed_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxii_collection_state",
        sa.Column(
            "collection_key", sa.Text(), primary_key=True, nullable=False,
        ),
        sa.Column("server_url", sa.Text(), nullable=False),
        sa.Column("collection_id", sa.Text(), nullable=False),
        sa.Column("last_added_after", sa.Text(), nullable=True),
        sa.Column(
            "last_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_object_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("taxii_collection_state")
