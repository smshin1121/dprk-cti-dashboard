"""rss_feed_state table

Revision ID: 0006_rss_feed_state
Revises: 0005_dq_events
Create Date: 2026-04-16

Creates the rss_feed_state table for PR #8 Phase 1.3a RSS ingest.
See docs/plans/pr8-rss-ingest.md D7 for schema rationale.

Feed runtime state (ETag, Last-Modified, failure tracking) is kept
separate from the CTI `sources` table because feed state has a
different lifecycle and semantics from a source entity. A feed can
be retired or broken without affecting the `sources` row that
represents the vendor's downstream CTI provenance.

Schema:
    feed_slug           TEXT PK      -- matches feeds.yml slug
    etag                TEXT NULL    -- last ETag header from vendor
    last_modified       TEXT NULL    -- last Last-Modified header
    last_fetched_at     TIMESTAMPTZ NULL
    last_status_code    INTEGER NULL -- HTTP status from last fetch
    last_error          TEXT NULL    -- error message if last fetch failed
    consecutive_failures INTEGER NOT NULL DEFAULT 0
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()

Reversibility: downgrade drops the table.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_rss_feed_state"
down_revision = "0005_dq_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_feed_state",
        sa.Column("feed_slug", sa.Text(), primary_key=True, nullable=False),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column(
            "last_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
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
    op.drop_table("rss_feed_state")
