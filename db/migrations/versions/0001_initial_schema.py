"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("mitre_intrusion_set_id", sa.String(length=64), nullable=True),
        sa.Column("aka", sa.ARRAY(sa.String(length=128)), nullable=False, server_default="{}"),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("reliability_default", sa.String(length=2), nullable=True),
    )

    op.create_table(
        "techniques",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mitre_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tactic", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )

    op.create_table(
        "malware",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("type", sa.String(length=64), nullable=True),
        sa.Column("mitre_id", sa.String(length=64), nullable=True, unique=True),
        sa.Column("aliases", sa.ARRAY(sa.String(length=128)), nullable=False, server_default="{}"),
    )

    op.create_table(
        "vulnerabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cve_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("cvss", sa.Float(), nullable=True),
        sa.Column("published", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )

    op.create_table(
        "codenames",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=True),
        sa.Column("named_by_source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_seen", sa.Date(), nullable=True),
        sa.Column("aliases", sa.ARRAY(sa.String(length=128)), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("stix_id", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("published", sa.Date(), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("url_canonical", sa.String(length=1024), nullable=False),
        sa.Column("sha256_title", sa.String(length=64), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=True),
        sa.Column("tlp", sa.String(length=16), nullable=False, server_default="WHITE"),
        sa.Column("reliability", sa.String(length=2), nullable=True),
        sa.Column("credibility", sa.String(length=2), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
    )
    op.execute("ALTER TABLE reports ADD COLUMN embedding vector(1536)")
    op.create_index("ix_reports_published", "reports", ["published"], unique=False)
    op.create_index("uq_reports_url_canonical", "reports", ["url_canonical"], unique=True)
    op.execute(
        "CREATE INDEX ix_reports_title_summary_fts ON reports USING gin (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '')))"
    )
    op.execute("CREATE INDEX ix_reports_title_trgm ON reports USING gin (title gin_trgm_ops)")

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("canonical_id", sa.Integer(), sa.ForeignKey("tags.id"), nullable=True),
    )

    op.create_table(
        "report_tags",
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id"), primary_key=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )

    op.create_table(
        "report_techniques",
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), primary_key=True),
        sa.Column("technique_id", sa.Integer(), sa.ForeignKey("techniques.id"), primary_key=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )

    op.create_table(
        "report_codenames",
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), primary_key=True),
        sa.Column("codename_id", sa.Integer(), sa.ForeignKey("codenames.id"), primary_key=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reported", sa.Date(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("est_loss_usd", sa.BigInteger(), nullable=True),
        sa.Column("attribution_confidence", sa.String(length=16), nullable=True),
    )

    op.create_table(
        "incident_sources",
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), primary_key=True),
    )

    op.create_table(
        "incident_motivations",
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), primary_key=True),
        sa.Column("motivation", sa.String(length=64), primary_key=True),
    )

    op.create_table(
        "incident_sectors",
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), primary_key=True),
        sa.Column("sector_code", sa.String(length=32), primary_key=True),
    )

    op.create_table(
        "incident_countries",
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), primary_key=True),
        sa.Column("country_iso2", sa.String(length=2), primary_key=True),
    )

    op.create_table(
        "geopolitical_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
    )
    op.create_index("ix_geopolitical_events_date", "geopolitical_events", ["date"], unique=False)
    op.create_index("ix_geopolitical_events_type", "geopolitical_events", ["type"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("payload_jsonb", sa.JSON(), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("diff_jsonb", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("alerts")
    op.drop_index("ix_geopolitical_events_type", table_name="geopolitical_events")
    op.drop_index("ix_geopolitical_events_date", table_name="geopolitical_events")
    op.drop_table("geopolitical_events")
    op.drop_table("incident_countries")
    op.drop_table("incident_sectors")
    op.drop_table("incident_motivations")
    op.drop_table("incident_sources")
    op.drop_table("incidents")
    op.drop_table("report_codenames")
    op.drop_table("report_techniques")
    op.drop_table("report_tags")
    op.drop_table("tags")
    op.execute("DROP INDEX IF EXISTS ix_reports_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_reports_title_summary_fts")
    op.drop_index("uq_reports_url_canonical", table_name="reports")
    op.drop_index("ix_reports_published", table_name="reports")
    op.drop_table("reports")
    op.drop_table("codenames")
    op.drop_table("vulnerabilities")
    op.drop_table("malware")
    op.drop_table("techniques")
    op.drop_table("sources")
    op.drop_table("groups")
