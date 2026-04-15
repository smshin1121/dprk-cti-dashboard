"""SQLAlchemy Table definitions mirroring the Phase 0 schema.

These tables are a **worker-local view** of the real schema defined by
``db/migrations/versions/0001_initial_schema.py``,
``0002_staging_and_indexes.py``,
``0003_audit_entity_nullable.py``, and
``0004_bigint_pk_migration.py``. They intentionally omit PostgreSQL-
specific columns (pgvector embeddings, ARRAY aliases) that sqlite-
memory cannot represent, so unit tests can run the same upsert code
against an in-memory database.

Production deployments never call ``metadata.create_all`` against this
module — the real schema comes from Alembic migrations. This metadata
instance is used only by the worker's unit tests via the
``create_in_memory_engine`` helper in ``worker.bootstrap.upsert``.

When the real migration schema changes, update this file in lock-step
and confirm the unit tests still exercise the upsert paths against a
schema that matches production's column names and constraint shape.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql


# Mirror the naming convention used by db/migrations/_metadata.py so
# constraint names line up between this module and the production
# schema that Alembic produces.
_NAMING_CONVENTION: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

metadata = MetaData(naming_convention=_NAMING_CONVENTION)


# PostgreSQL BigInteger does not autoincrement under sqlite because
# sqlite's autoincrement machinery is tied specifically to
# `INTEGER PRIMARY KEY`. Use a dialect-variant so production still gets
# bigint while unit tests (sqlite-memory) get an autoincrementing
# integer PK that behaves the same way.
_BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


# ---------------------------------------------------------------------------
# groups
# ---------------------------------------------------------------------------

groups_table = sa.Table(
    "groups",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(length=128), nullable=False, unique=True),
    sa.Column("mitre_intrusion_set_id", sa.String(length=64), nullable=True),
    sa.Column("color", sa.String(length=16), nullable=True),
    sa.Column("description", sa.Text(), nullable=True),
)

# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

sources_table = sa.Table(
    "sources",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(length=128), nullable=False, unique=True),
    sa.Column("type", sa.String(length=64), nullable=False, server_default="vendor"),
    sa.Column("country", sa.String(length=2), nullable=True),
    sa.Column("website", sa.String(length=255), nullable=True),
    sa.Column("reliability_default", sa.String(length=2), nullable=True),
)

# ---------------------------------------------------------------------------
# codenames
# ---------------------------------------------------------------------------

codenames_table = sa.Table(
    "codenames",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(length=128), nullable=False, unique=True),
    sa.Column(
        "group_id",
        _BIGINT,
        sa.ForeignKey("groups.id"),
        nullable=True,
    ),
    sa.Column(
        "named_by_source_id",
        _BIGINT,
        sa.ForeignKey("sources.id"),
        nullable=True,
    ),
    sa.Column("first_seen", sa.Date(), nullable=True),
    sa.Column("last_seen", sa.Date(), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("stix_id", sa.String(length=128), nullable=True),
)

# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

reports_table = sa.Table(
    "reports",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("published", sa.Date(), nullable=False),
    sa.Column(
        "source_id",
        _BIGINT,
        sa.ForeignKey("sources.id"),
        nullable=False,
    ),
    sa.Column("title", sa.String(length=512), nullable=False),
    sa.Column("url", sa.String(length=1024), nullable=False),
    sa.Column(
        "url_canonical",
        sa.String(length=1024),
        nullable=False,
        unique=True,
    ),
    sa.Column("sha256_title", sa.String(length=64), nullable=False),
    sa.Column("lang", sa.String(length=8), nullable=True),
    sa.Column("tlp", sa.String(length=16), nullable=False, server_default="WHITE"),
    sa.Column("reliability", sa.String(length=2), nullable=True),
    sa.Column("credibility", sa.String(length=2), nullable=True),
    sa.Column("summary", sa.Text(), nullable=True),
)

# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------

tags_table = sa.Table(
    "tags",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(length=128), nullable=False, unique=True),
    sa.Column("type", sa.String(length=32), nullable=False),
    sa.Column(
        "canonical_id",
        _BIGINT,
        sa.ForeignKey("tags.id"),
        nullable=True,
    ),
)

# ---------------------------------------------------------------------------
# report_tags
# ---------------------------------------------------------------------------

report_tags_table = sa.Table(
    "report_tags",
    metadata,
    sa.Column(
        "report_id",
        _BIGINT,
        sa.ForeignKey("reports.id"),
        primary_key=True,
    ),
    sa.Column(
        "tag_id",
        _BIGINT,
        sa.ForeignKey("tags.id"),
        primary_key=True,
    ),
    sa.Column("confidence", sa.Float(), nullable=True),
)

# ---------------------------------------------------------------------------
# report_codenames
# ---------------------------------------------------------------------------

report_codenames_table = sa.Table(
    "report_codenames",
    metadata,
    sa.Column(
        "report_id",
        _BIGINT,
        sa.ForeignKey("reports.id"),
        primary_key=True,
    ),
    sa.Column(
        "codename_id",
        _BIGINT,
        sa.ForeignKey("codenames.id"),
        primary_key=True,
    ),
    sa.Column("confidence", sa.Float(), nullable=True),
)

# ---------------------------------------------------------------------------
# incidents
# ---------------------------------------------------------------------------

incidents_table = sa.Table(
    "incidents",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("reported", sa.Date(), nullable=True),
    sa.Column("title", sa.String(length=255), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("est_loss_usd", _BIGINT, nullable=True),
    sa.Column("attribution_confidence", sa.String(length=16), nullable=True),
)

# ---------------------------------------------------------------------------
# incident mapping tables
# ---------------------------------------------------------------------------

incident_sources_table = sa.Table(
    "incident_sources",
    metadata,
    sa.Column(
        "incident_id",
        _BIGINT,
        sa.ForeignKey("incidents.id"),
        primary_key=True,
    ),
    sa.Column(
        "report_id",
        _BIGINT,
        sa.ForeignKey("reports.id"),
        primary_key=True,
    ),
)

incident_motivations_table = sa.Table(
    "incident_motivations",
    metadata,
    sa.Column(
        "incident_id",
        _BIGINT,
        sa.ForeignKey("incidents.id"),
        primary_key=True,
    ),
    sa.Column("motivation", sa.String(length=64), primary_key=True),
)

incident_sectors_table = sa.Table(
    "incident_sectors",
    metadata,
    sa.Column(
        "incident_id",
        _BIGINT,
        sa.ForeignKey("incidents.id"),
        primary_key=True,
    ),
    sa.Column("sector_code", sa.String(length=32), primary_key=True),
)

incident_countries_table = sa.Table(
    "incident_countries",
    metadata,
    sa.Column(
        "incident_id",
        _BIGINT,
        sa.ForeignKey("incidents.id"),
        primary_key=True,
    ),
    sa.Column("country_iso2", sa.String(length=2), primary_key=True),
)


# ---------------------------------------------------------------------------
# audit_log (PR #7 Group B)
# ---------------------------------------------------------------------------
#
# The bootstrap ETL writes row-level and run-level provenance records
# to this table. The production schema was established in migrations
# 0001 (initial) / 0003 (entity_id nullable) / 0004 (BIGINT widen);
# this worker-local mirror exists so sqlite-memory unit tests can
# exercise the audit writers in ``worker.bootstrap.audit`` without a
# live Postgres instance. Production ignores this MetaData instance.

audit_log_table = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("actor", sa.String(length=128), nullable=False),
    sa.Column("action", sa.String(length=64), nullable=False),
    sa.Column("entity", sa.String(length=64), nullable=False),
    # 0003_audit_entity_nullable dropped NOT NULL so run-level events
    # (entity="etl_run", entity_id=NULL) are permitted per D4.
    sa.Column("entity_id", sa.String(length=64), nullable=True),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.current_timestamp(),
    ),
    # 0001 used sa.JSON() for diff_jsonb; we match it here so SQLAlchemy
    # serializes dicts uniformly on both dialects. pg stores this as
    # JSON (not JSONB) at rest; the column name is historical.
    sa.Column("diff_jsonb", sa.JSON(), nullable=True),
)


# ---------------------------------------------------------------------------
# dq_events (PR #7 Group C — migration 0005 mirror)
# ---------------------------------------------------------------------------
#
# Mirror of the production table created by
# ``db/migrations/versions/0005_dq_events.py``. Exists so sqlite-memory
# unit tests can exercise the ``worker.data_quality`` sinks and the
# runner without a live Postgres instance. Production runs against the
# Alembic-managed schema; this MetaData is ignored in production.
#
# Dialect variants:
#   - ``run_id`` uses native pg UUID in production and String(36) on
#     sqlite so the sink can keep passing UUID objects uniformly.
#   - ``detail_jsonb`` uses pg JSONB in production and sa.JSON() on
#     sqlite; both accept dict bind parameters via SQLAlchemy's JSON
#     serializer.
#   - ``observed_at`` has a server default matching the migration so
#     a sink that omits the column still gets CURRENT_TIMESTAMP;
#     production sinks always pass an explicit value derived from
#     ``ExpectationResult.observed_at`` so the DB row and the JSONL
#     mirror carry the identical timestamp.

dq_events_table = sa.Table(
    "dq_events",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    # sa.Uuid() is SA 2.0+ dialect-agnostic and resolves to pg native
    # UUID on Postgres and a string/CHAR UUID representation on
    # sqlite. The production schema (migration 0005) declares
    # ``postgresql.UUID(as_uuid=True)`` explicitly; the Core type
    # here only needs to round-trip UUID objects on whatever backend
    # the worker tests use, and sa.Uuid() does that for both.
    sa.Column("run_id", sa.Uuid(), nullable=False),
    sa.Column("expectation", sa.Text(), nullable=False),
    sa.Column("severity", sa.Text(), nullable=False),
    sa.Column("observed", sa.Numeric(), nullable=True),
    sa.Column("threshold", sa.Numeric(), nullable=True),
    sa.Column("observed_rows", sa.BigInteger(), nullable=True),
    sa.Column(
        "detail_jsonb",
        postgresql.JSONB(astext_type=sa.Text()).with_variant(
            sa.JSON(), "sqlite"
        ),
        nullable=False,
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.current_timestamp(),
    ),
    sa.CheckConstraint(
        "severity IN ('warn', 'error', 'pass')",
        name="severity_allowed",
    ),
    sa.Index("ix_dq_events_run_id", "run_id"),
    sa.Index("ix_dq_events_expectation", "expectation"),
    # Migration 0005 declares this index DESC for timestamp-ordered
    # trend queries. sqlite accepts the DESC keyword in CREATE INDEX
    # but the planner treats ASC/DESC on a single column index as a
    # hint at best, so the SQLite test mirror may drop the DESC
    # direction. The index itself must exist either way — the Group C
    # review explicitly called out that the mirror be 1:1 with 0005
    # for index coverage, not for directionality.
    sa.Index("ix_dq_events_observed_at", sa.text("observed_at DESC")),
)


__all__ = [
    "audit_log_table",
    "dq_events_table",
    "codenames_table",
    "groups_table",
    "incident_countries_table",
    "incident_motivations_table",
    "incident_sectors_table",
    "incident_sources_table",
    "incidents_table",
    "metadata",
    "report_codenames_table",
    "report_tags_table",
    "reports_table",
    "sources_table",
    "tags_table",
]
