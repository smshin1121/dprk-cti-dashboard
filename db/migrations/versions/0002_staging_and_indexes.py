"""staging table, FK indexes, JSONB type fixes, hnsw indexes, materialized view stubs

Revision ID: 0002_staging_and_indexes
Revises: 0001_initial_schema
Create Date: 2026-04-13

# TODO: Follow-up — migrate Integer PKs to BigInteger on groups, sources,
#       techniques, malware, vulnerabilities, codenames, reports, tags,
#       incidents, alerts, audit_log before production data lands.
#       That dedicated migration MUST also atomically widen the two FK
#       columns declared below (`staging.source_id`, `staging.promoted_report_id`)
#       because PostgreSQL FKs require the referencing column type to match
#       the referenced PK. They are declared as `Integer` here to match the
#       current `sources.id` / `reports.id` types from 0001.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_staging_and_indexes"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. New `staging` table  (§3.4 LLM enrichment queue, §6.1 F-7)
    # ------------------------------------------------------------------
    op.create_table(
        "staging",
        # Primary key — BIGINT GENERATED ALWAYS AS IDENTITY
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Source FK (nullable — item may arrive before source record exists)
        # Type must match sources.id (Integer in 0001_initial_schema).
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=True),
        # Deduplication key — enforces one staging row per canonical URL
        sa.Column("url_canonical", sa.Text(), nullable=False, unique=True),
        sa.Column("sha256_title", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("lang", sa.Text(), nullable=True),
        sa.Column("published", sa.DateTime(timezone=True), nullable=True),
        # LLM-filled fields
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tags_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Review workflow
        sa.Column(
            "confidence",
            sa.Numeric(precision=4, scale=3),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        # Populated when status = 'promoted'.
        # Type must match reports.id (Integer in 0001_initial_schema).
        sa.Column(
            "promoted_report_id",
            sa.Integer(),
            sa.ForeignKey("reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Populated when status = 'error'
        sa.Column("error", sa.Text(), nullable=True),
        # CHECK constraint on status enum
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','promoted','error')",
            name="ck_staging_status",
        ),
    )

    # embedding column uses the pgvector type — must be added via raw SQL
    # because SQLAlchemy core does not natively model the vector type.
    op.execute("ALTER TABLE staging ADD COLUMN embedding vector(1536)")

    # Index: status (low-cardinality; partial indexes per-status would also
    # work but a plain B-tree covers the polling query pattern well)
    op.create_index("ix_staging_status", "staging", ["status"], unique=False)

    # Index: source_id FK
    op.create_index("ix_staging_source_id", "staging", ["source_id"], unique=False)

    # Index: GIN on tags_jsonb for JSON path / containment queries
    op.execute(
        "CREATE INDEX ix_staging_tags_gin ON staging USING gin (tags_jsonb)"
    )

    # Index: hnsw on embedding for ANN similarity search
    # m=16 / ef_construction=64 are pgvector defaults and a reasonable
    # starting point; tune m and ef_construction after profiling recall vs.
    # latency with real data.
    op.execute(
        "CREATE INDEX ix_staging_embedding_hnsw "
        "ON staging USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------
    # 2. hnsw index on reports.embedding  (§2.5 / §7.7)
    # ------------------------------------------------------------------
    op.execute(
        "CREATE INDEX reports_embedding_hnsw "
        "ON reports USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------
    # 3. Missing FK indexes on existing tables
    # ------------------------------------------------------------------

    # codenames
    op.create_index("ix_codenames_group_id", "codenames", ["group_id"], unique=False)
    op.create_index(
        "ix_codenames_named_by_source_id",
        "codenames",
        ["named_by_source_id"],
        unique=False,
    )

    # reports
    op.create_index("ix_reports_source_id", "reports", ["source_id"], unique=False)

    # report_tags
    op.create_index("ix_report_tags_tag_id", "report_tags", ["tag_id"], unique=False)

    # report_techniques
    op.create_index(
        "ix_report_techniques_technique_id",
        "report_techniques",
        ["technique_id"],
        unique=False,
    )

    # report_codenames
    op.create_index(
        "ix_report_codenames_codename_id",
        "report_codenames",
        ["codename_id"],
        unique=False,
    )

    # incident_sources
    op.create_index(
        "ix_incident_sources_report_id",
        "incident_sources",
        ["report_id"],
        unique=False,
    )

    # tags.name lookup index (§2.5 — tag name lookups during ingest)
    op.create_index("ix_tags_name", "tags", ["name"], unique=False)

    # ------------------------------------------------------------------
    # 4. JSONB type fixes on existing tables
    # ------------------------------------------------------------------

    # alerts.payload_jsonb: JSON -> JSONB
    op.execute(
        "ALTER TABLE alerts "
        "ALTER COLUMN payload_jsonb TYPE JSONB "
        "USING payload_jsonb::jsonb"
    )

    # audit_log.diff_jsonb: JSON -> JSONB
    op.execute(
        "ALTER TABLE audit_log "
        "ALTER COLUMN diff_jsonb TYPE JSONB "
        "USING diff_jsonb::jsonb"
    )

    # GIN indexes on the now-JSONB columns
    op.execute(
        "CREATE INDEX ix_alerts_payload_gin ON alerts USING gin (payload_jsonb)"
    )
    op.execute(
        "CREATE INDEX ix_audit_log_diff_gin ON audit_log USING gin (diff_jsonb)"
    )

    # ------------------------------------------------------------------
    # 5. Materialized view stubs  (§7.7)
    # Each view is created empty (WHERE false) so it exists and can be
    # REFRESH MATERIALIZED VIEW'd by Prefect without needing real data.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_year_group_sector AS
        SELECT
            NULL::int       AS year,
            NULL::bigint    AS group_id,
            NULL::text      AS sector_code,
            0::bigint       AS cnt
        WHERE false
        """
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_country_motivation_year AS
        SELECT
            NULL::text      AS country_iso2,
            NULL::text      AS motivation,
            NULL::int       AS year,
            0::bigint       AS cnt
        WHERE false
        """
    )


# ---------------------------------------------------------------------------
# downgrade — reverse order of upgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # 5. Materialized views
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_country_motivation_year")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_year_group_sector")

    # 4. JSONB type fixes — revert JSONB back to JSON; GIN indexes first
    op.execute("DROP INDEX IF EXISTS ix_audit_log_diff_gin")
    op.execute("DROP INDEX IF EXISTS ix_alerts_payload_gin")
    op.execute(
        "ALTER TABLE audit_log "
        "ALTER COLUMN diff_jsonb TYPE JSON "
        "USING diff_jsonb::text::json"
    )
    op.execute(
        "ALTER TABLE alerts "
        "ALTER COLUMN payload_jsonb TYPE JSON "
        "USING payload_jsonb::text::json"
    )

    # 3. FK indexes on existing tables
    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_index("ix_incident_sources_report_id", table_name="incident_sources")
    op.drop_index("ix_report_codenames_codename_id", table_name="report_codenames")
    op.drop_index("ix_report_techniques_technique_id", table_name="report_techniques")
    op.drop_index("ix_report_tags_tag_id", table_name="report_tags")
    op.drop_index("ix_reports_source_id", table_name="reports")
    op.drop_index("ix_codenames_named_by_source_id", table_name="codenames")
    op.drop_index("ix_codenames_group_id", table_name="codenames")

    # 2. reports.embedding hnsw
    op.execute("DROP INDEX IF EXISTS reports_embedding_hnsw")

    # 1. staging table (indexes dropped implicitly with the table)
    op.execute("DROP INDEX IF EXISTS ix_staging_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_staging_tags_gin")
    op.drop_index("ix_staging_source_id", table_name="staging")
    op.drop_index("ix_staging_status", table_name="staging")
    op.drop_table("staging")
