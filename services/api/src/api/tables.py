"""SQLAlchemy Table mirrors for the tables the API service reads/writes.

This mirror is the API-side counterpart to
``services/worker/src/worker/bootstrap/tables.py`` — both trace to the
same Alembic-managed production schema
(``db/migrations/versions/0001`` through ``0008``). They are kept as
separate modules so neither service takes a cross-service import
dependency on the other.

**Production never calls ``metadata.create_all`` against this module.**
The real schema comes from Alembic migrations. This metadata instance
is used only by unit tests that spin up an in-memory SQLite engine to
exercise the ON CONFLICT upsert repositories (``api.promote``)
without a live Postgres instance.

When any migration in ``db/migrations/versions/`` changes, update this
file in lock-step with the worker mirror and the changing migration.
Drift between this mirror and the canonical schema is invisible to
unit tests (they all pass against the mirror) but surfaces
immediately in the Group H real-PG integration job.

Scope limitation: this module carries only the columns the API code
paths touch. Full schema coverage is not a goal — adding unused
columns here creates maintenance burden without benefit.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql


# Mirror the Alembic naming convention so FKs / UQs / CKs from this
# mirror line up with the production schema names. Matches the worker
# mirror and ``db/migrations/_metadata.py`` exactly.
_NAMING_CONVENTION: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

metadata = MetaData(naming_convention=_NAMING_CONVENTION)


# BigInteger autoincrement does not behave on sqlite; dialect-variant
# falls back to Integer there. Matches the worker mirror pattern.
_BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


# ---------------------------------------------------------------------------
# sources (migration 0001 + 0004 BIGINT widen)
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
# groups (migration 0001 + 0004)
# ---------------------------------------------------------------------------

groups_table = sa.Table(
    "groups",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(length=128), nullable=False, unique=True),
    sa.Column("mitre_intrusion_set_id", sa.String(length=64), nullable=True),
    # ``aka`` is migration 0001 line 27 — a PG ARRAY of string aliases
    # (APT38, Hidden Cobra, etc). Added to the mirror for PR #11 Group B
    # (GET /actors returns aka). PG uses ARRAY; sqlite falls back to JSON
    # so the unit-test engine can round-trip the list. Nullable here
    # (production has server_default='{}' — tests set explicit values).
    sa.Column(
        "aka",
        postgresql.ARRAY(sa.String(length=128)).with_variant(sa.JSON(), "sqlite"),
        nullable=True,
    ),
    sa.Column("color", sa.String(length=16), nullable=True),
    sa.Column("description", sa.Text(), nullable=True),
)


# ---------------------------------------------------------------------------
# codenames (migration 0001 + 0004)
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
# reports (migration 0001 + 0004; embedding column omitted — pgvector-only)
# ---------------------------------------------------------------------------
#
# Natural UNIQUE for promote-path ON CONFLICT: url_canonical
# (via 0001 uq_reports_url_canonical index). sha256_title is NOT UNIQUE
# (bootstrap's source-scoped title-hash fallback is ingest-path only,
# not used by the promote path). See plan §2.3 for the authoritative
# table of natural keys.

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
# tags + report_tags + report_codenames (migration 0001 + 0004)
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
# techniques + report_techniques (migration 0001 lines 42-49, 120-125)
# ---------------------------------------------------------------------------
#
# Added for PR #13 Group A (GET /analytics/attack_matrix). ``tactic`` is a
# free-form string on the migration (nullable); the API treats rows with
# null tactic as a distinct "unclassified" bucket rather than dropping
# them. Mirror stays 1:1 with migration 0001.

techniques_table = sa.Table(
    "techniques",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("mitre_id", sa.String(length=32), nullable=False, unique=True),
    sa.Column("name", sa.String(length=255), nullable=False),
    sa.Column("tactic", sa.String(length=128), nullable=True),
    sa.Column("description", sa.Text(), nullable=True),
)

report_techniques_table = sa.Table(
    "report_techniques",
    metadata,
    sa.Column(
        "report_id",
        _BIGINT,
        sa.ForeignKey("reports.id"),
        primary_key=True,
    ),
    sa.Column(
        "technique_id",
        _BIGINT,
        sa.ForeignKey("techniques.id"),
        primary_key=True,
    ),
    sa.Column("confidence", sa.Float(), nullable=True),
)


# ---------------------------------------------------------------------------
# incidents + 3 join tables (migration 0001 lines 134-166)
# ---------------------------------------------------------------------------
#
# Added for PR #11 Group D (GET /incidents). Mirrors migration 0001 1:1.
# reported is nullable in the schema but the list endpoint filters
# ``reported IS NOT NULL`` (cursor needs a date value — see
# api.read.repositories.list_incidents). Detail endpoints (Phase 3)
# can surface null-reported rows separately.

incidents_table = sa.Table(
    "incidents",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("reported", sa.Date(), nullable=True),
    sa.Column("title", sa.String(length=255), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("est_loss_usd", sa.BigInteger(), nullable=True),
    sa.Column("attribution_confidence", sa.String(length=16), nullable=True),
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

# incident_sources is the canonical M:N link between incidents and the
# reports that document them (migration 0001 lines 145-149). Added for
# PR #14 Group A — the report detail endpoint lists "incidents this
# report is a source of" and the incident detail endpoint lists
# "reports that are sources of this incident" via this join. A single
# index on ``report_id`` (migration 0002 line 175 —
# ``ix_incident_sources_report_id``) makes the report→incidents
# direction efficient; the PK (incident_id, report_id) indexes the
# opposite direction for free. No new migration required.
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


# ---------------------------------------------------------------------------
# staging (migration 0002 + 0008 decision_reason)
# ---------------------------------------------------------------------------
#
# Mirror must stay 1:1 with migration 0008. embedding vector(1536) is
# omitted because sqlite cannot represent pgvector. The API promote
# path reads status/reviewed_by/at/decision_reason/promoted_report_id
# and writes via conditional UPDATE (plan §2.2 B — SELECT FOR UPDATE
# + WHERE id=? AND status='pending').

staging_table = sa.Table(
    "staging",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.current_timestamp(),
    ),
    sa.Column(
        "source_id",
        _BIGINT,
        sa.ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("url", sa.Text(), nullable=True),
    sa.Column("url_canonical", sa.Text(), nullable=False, unique=True),
    sa.Column("sha256_title", sa.Text(), nullable=True),
    sa.Column("title", sa.Text(), nullable=True),
    sa.Column("raw_text", sa.Text(), nullable=True),
    sa.Column("lang", sa.Text(), nullable=True),
    sa.Column("published", sa.DateTime(timezone=True), nullable=True),
    sa.Column("summary", sa.Text(), nullable=True),
    sa.Column(
        "tags_jsonb",
        postgresql.JSONB(astext_type=sa.Text()).with_variant(
            sa.JSON(), "sqlite"
        ),
        nullable=True,
    ),
    sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column(
        "status",
        sa.Text(),
        nullable=False,
        server_default="pending",
    ),
    sa.Column("reviewed_by", sa.Text(), nullable=True),
    sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "promoted_report_id",
        _BIGINT,
        sa.ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column("decision_reason", sa.Text(), nullable=True),
    sa.CheckConstraint(
        "status IN ('pending','approved','rejected','promoted','error')",
        name="staging_status",
    ),
)


# ---------------------------------------------------------------------------
# audit_log (migration 0001 + 0003 + 0004)
# ---------------------------------------------------------------------------

audit_log_table = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", _BIGINT, primary_key=True, autoincrement=True),
    sa.Column("actor", sa.String(length=128), nullable=False),
    sa.Column("action", sa.String(length=64), nullable=False),
    sa.Column("entity", sa.String(length=64), nullable=False),
    # 0003 relaxed entity_id to nullable for run-level events.
    sa.Column("entity_id", sa.String(length=64), nullable=True),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.current_timestamp(),
    ),
    sa.Column("diff_jsonb", sa.JSON(), nullable=True),
)


__all__ = [
    "audit_log_table",
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
    "report_techniques_table",
    "reports_table",
    "sources_table",
    "staging_table",
    "tags_table",
    "techniques_table",
]
