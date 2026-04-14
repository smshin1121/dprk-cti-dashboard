"""audit_log.entity_id -> nullable

Revision ID: 0003_audit_log_entity_id_nullable
Revises: 0002_staging_and_indexes
Create Date: 2026-04-14

The OIDC audit trail (§9) needs to log events that legitimately have no
entity_id — most importantly anonymous logout (cookie present but no
matching Redis session) and pre-auth failures like ``invalid_state`` or
``token_exchange_failed``. The original 0001 schema declared
``audit_log.entity_id`` as NOT NULL, so these writes failed with a
constraint violation. Drop the NOT NULL constraint; successful
login/logout events still populate it with the user's sub.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_audit_entity_nullable"
down_revision = "0002_staging_and_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_log",
        "entity_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill NULLs before re-applying NOT NULL so the downgrade is safe
    # on a populated database.
    op.execute(
        "UPDATE audit_log SET entity_id = '' WHERE entity_id IS NULL"
    )
    op.alter_column(
        "audit_log",
        "entity_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
