"""bigint pk migration

Revision ID: 0004_bigint_pk_migration
Revises: 0003_audit_entity_nullable
Create Date: 2026-04-14

Preflight migration for PR #4 (Bootstrap ETL). Widens every Integer
primary key declared in 0001_initial_schema, and every referencing
foreign key column, to BigInteger. See docs/plans/pr4-bootstrap-etl.md
task T1 for rationale and rollback expectations.

Tables whose PKs are widened:
    groups, sources, techniques, malware, vulnerabilities, codenames,
    reports, tags, incidents, geopolitical_events, alerts, audit_log

FK columns widened to keep types in sync with their referenced PKs:
    codenames.group_id, codenames.named_by_source_id,
    reports.source_id,
    tags.canonical_id (self-ref),
    report_tags.{report_id, tag_id},
    report_techniques.{report_id, technique_id},
    report_codenames.{report_id, codename_id},
    incident_sources.{incident_id, report_id},
    incident_motivations.incident_id,
    incident_sectors.incident_id,
    incident_countries.incident_id,
    staging.source_id, staging.promoted_report_id

Intentionally unchanged:
    staging.id           -- already BigInteger IDENTITY (0002)
    incidents.est_loss_usd  -- already BigInteger (USD cents domain value)
    audit_log.entity_id  -- String; not a numeric PK/FK
    incident_{motivations,sectors,countries} text PK parts
        (motivation, sector_code, country_iso2)

Strategy: drop referencing FKs, widen columns, recreate FKs. Since the
database is empty when this runs, the rewrite is effectively free. The
downgrade path is the exact reverse and is exercised by the CI
db-migrations reversibility step.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_bigint_pk_migration"
down_revision = "0003_audit_entity_nullable"
branch_labels = None
depends_on = None


# Every FK touched by this migration.
# Format: (constraint_name, table, referred_table, local_cols, remote_cols, ondelete)
# Names match the project's alembic naming convention defined in
# db/migrations/_metadata.py: fk_<table>_<column_0>_<referred_table>.
_FKS: list[tuple[str, str, str, list[str], list[str], str | None]] = [
    ("fk_codenames_group_id_groups", "codenames", "groups", ["group_id"], ["id"], None),
    ("fk_codenames_named_by_source_id_sources", "codenames", "sources", ["named_by_source_id"], ["id"], None),
    ("fk_reports_source_id_sources", "reports", "sources", ["source_id"], ["id"], None),
    ("fk_tags_canonical_id_tags", "tags", "tags", ["canonical_id"], ["id"], None),
    ("fk_report_tags_report_id_reports", "report_tags", "reports", ["report_id"], ["id"], None),
    ("fk_report_tags_tag_id_tags", "report_tags", "tags", ["tag_id"], ["id"], None),
    ("fk_report_techniques_report_id_reports", "report_techniques", "reports", ["report_id"], ["id"], None),
    ("fk_report_techniques_technique_id_techniques", "report_techniques", "techniques", ["technique_id"], ["id"], None),
    ("fk_report_codenames_report_id_reports", "report_codenames", "reports", ["report_id"], ["id"], None),
    ("fk_report_codenames_codename_id_codenames", "report_codenames", "codenames", ["codename_id"], ["id"], None),
    ("fk_incident_sources_incident_id_incidents", "incident_sources", "incidents", ["incident_id"], ["id"], None),
    ("fk_incident_sources_report_id_reports", "incident_sources", "reports", ["report_id"], ["id"], None),
    ("fk_incident_motivations_incident_id_incidents", "incident_motivations", "incidents", ["incident_id"], ["id"], None),
    ("fk_incident_sectors_incident_id_incidents", "incident_sectors", "incidents", ["incident_id"], ["id"], None),
    ("fk_incident_countries_incident_id_incidents", "incident_countries", "incidents", ["incident_id"], ["id"], None),
    ("fk_staging_source_id_sources", "staging", "sources", ["source_id"], ["id"], "SET NULL"),
    ("fk_staging_promoted_report_id_reports", "staging", "reports", ["promoted_report_id"], ["id"], "SET NULL"),
]


# Every Integer column widened by this migration.
# Format: (table, column, nullable)
# PKs first, then FK columns. Order matters only for readability — Postgres
# does all the ALTERs in a single transaction, and with empty tables the
# rewrite is a no-op on data.
_COLUMNS_TO_WIDEN: list[tuple[str, str, bool]] = [
    # Primary keys
    ("groups", "id", False),
    ("sources", "id", False),
    ("techniques", "id", False),
    ("malware", "id", False),
    ("vulnerabilities", "id", False),
    ("codenames", "id", False),
    ("reports", "id", False),
    ("tags", "id", False),
    ("incidents", "id", False),
    ("geopolitical_events", "id", False),
    ("alerts", "id", False),
    ("audit_log", "id", False),
    # Foreign key columns
    ("codenames", "group_id", True),
    ("codenames", "named_by_source_id", True),
    ("reports", "source_id", False),
    ("tags", "canonical_id", True),
    ("report_tags", "report_id", False),
    ("report_tags", "tag_id", False),
    ("report_techniques", "report_id", False),
    ("report_techniques", "technique_id", False),
    ("report_codenames", "report_id", False),
    ("report_codenames", "codename_id", False),
    ("incident_sources", "incident_id", False),
    ("incident_sources", "report_id", False),
    ("incident_motivations", "incident_id", False),
    ("incident_sectors", "incident_id", False),
    ("incident_countries", "incident_id", False),
    ("staging", "source_id", True),
    ("staging", "promoted_report_id", True),
]


def upgrade() -> None:
    # 1. Drop every FK that references a PK we are about to widen.
    for name, table, *_rest in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")

    # 2. Widen PK and FK columns from Integer to BigInteger.
    for table, column, nullable in _COLUMNS_TO_WIDEN:
        op.alter_column(
            table,
            column,
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=nullable,
        )

    # 3. Recreate FKs with their original names and ondelete behavior.
    for name, table, referred_table, local_cols, remote_cols, ondelete in _FKS:
        op.create_foreign_key(
            name,
            table,
            referred_table,
            local_cols,
            remote_cols,
            ondelete=ondelete,
        )


def downgrade() -> None:
    # 1. Drop the (bigint) FKs.
    for name, table, *_rest in reversed(_FKS):
        op.drop_constraint(name, table, type_="foreignkey")

    # 2. Narrow columns back to Integer (reverse order of widen for symmetry).
    for table, column, nullable in reversed(_COLUMNS_TO_WIDEN):
        op.alter_column(
            table,
            column,
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=nullable,
        )

    # 3. Recreate FKs at the original (integer) types.
    for name, table, referred_table, local_cols, remote_cols, ondelete in _FKS:
        op.create_foreign_key(
            name,
            table,
            referred_table,
            local_cols,
            remote_cols,
            ondelete=ondelete,
        )
