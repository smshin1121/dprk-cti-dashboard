"""ON CONFLICT upsert helpers for the promote path.

Plan §2.3 locks the natural-key strategy per table. PostgreSQL is the
canonical target; each function uses ``INSERT ... ON CONFLICT
DO NOTHING RETURNING id`` against the natural-key UNIQUE constraint
and falls back to a ``SELECT ... WHERE <natural_key>=...`` when
RETURNING comes back empty (conflict means the row pre-existed).

SQLite support exists solely so unit tests can run the same flow in
memory — SQLAlchemy's ``sqlite.insert().on_conflict_do_nothing(...)``
honors the same ``index_elements`` argument and the same RETURNING
semantics (SQLite 3.35+), so the polyfill is one line of dialect
dispatch. The real-PG integration test job (Group H) is the
authoritative semantic check; do not treat passing SQLite tests as
evidence that ON CONFLICT behaves identically at scale.

Design rules enforced across helpers:

- **Natural keys only**. No SELECT-by-id lookups here — the caller
  already has the id when that's relevant. These helpers exist to
  resolve ids from natural keys idempotently under concurrent writes.
- **No surprise updates**. Every helper uses ``DO NOTHING`` — callers
  that need "update on conflict" semantics (none in PR #10) must add
  explicit helpers. Silently updating on conflict would make the
  promote path overwrite analyst-curated fields, which plan §2.3
  explicitly rejects (reports "첨부" semantics).
- **Session is caller-owned**. None of these helpers commit; the
  single-transaction promote service (Group D) owns begin/commit
  and the SELECT FOR UPDATE lock on staging.
"""

from __future__ import annotations

from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import (
    codenames_table,
    groups_table,
    report_codenames_table,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
)


# ---------------------------------------------------------------------------
# Dialect dispatch
# ---------------------------------------------------------------------------


def _insert_factory(session: AsyncSession) -> Callable[..., Any]:
    """Return the dialect-appropriate ``insert(...)`` factory.

    Both PG and SQLite dialects expose
    ``.on_conflict_do_nothing(index_elements=[...])`` with identical
    semantics on the happy path. The RETURNING clause also works on
    both (SQLite 3.35+; SQLAlchemy 2.0 pgvector-free paths).

    Raises on any other dialect — if we ever add MySQL or a test
    dialect, the caller must explicitly add it here so the
    ON CONFLICT semantics are a conscious choice, not an accident.
    """
    dialect_name = session.bind.dialect.name  # type: ignore[union-attr]
    if dialect_name == "postgresql":
        return postgresql.insert
    if dialect_name == "sqlite":
        return sqlite.insert
    raise RuntimeError(
        f"promote repositories do not support dialect {dialect_name!r}; "
        "add an explicit ON CONFLICT path before using this dialect"
    )


async def _upsert_by_unique_name(
    session: AsyncSession,
    table: sa.Table,
    *,
    values: dict[str, Any],
    unique_column: str = "name",
) -> int:
    """Common 'upsert by single-column UNIQUE' pattern.

    Returns the row id whether the INSERT succeeded or the ON CONFLICT
    fired. The fallback SELECT covers the conflict case — empty
    RETURNING means the row already existed under a different INSERT
    (concurrent writer) and we read its id to continue the
    transaction.
    """
    insert = _insert_factory(session)
    stmt = (
        insert(table)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[unique_column])
        .returning(table.c.id)
    )
    result = await session.execute(stmt)
    row_id = result.scalar_one_or_none()
    if row_id is not None:
        return row_id

    # Conflict: the row already exists. Read its id by the natural key.
    column = table.c[unique_column]
    key_value = values[unique_column]
    existing = await session.execute(
        sa.select(table.c.id).where(column == key_value)
    )
    # scalar_one() — if SELECT misses here, the earlier conflict was
    # lying (or the row was deleted between INSERT and SELECT, which
    # in practice cannot happen while the transaction is open).
    return existing.scalar_one()


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


async def upsert_source(
    session: AsyncSession,
    *,
    name: str,
    type_: str = "vendor",
) -> int:
    """Resolve a source row by ``name``, inserting if missing.

    Plan §2.3: ``ON CONFLICT (name) DO NOTHING RETURNING id``, fallback
    ``SELECT id FROM sources WHERE name=?``.
    """
    if not name:
        raise ValueError("source name is required")
    return await _upsert_by_unique_name(
        session,
        sources_table,
        values={"name": name, "type": type_},
    )


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


async def upsert_report(
    session: AsyncSession,
    *,
    published: Any,
    source_id: int,
    title: str,
    url: str,
    url_canonical: str,
    sha256_title: str,
    lang: str | None = None,
) -> tuple[int, bool]:
    """Resolve a report row by ``url_canonical``, inserting if missing.

    Returns ``(report_id, attached_existing)``. ``attached_existing``
    is True when the UNIQUE conflict fired and the caller got an
    existing row's id — the promote service records this in the
    audit diff so reviewers can see when a staging approval attached
    to a pre-existing report rather than creating a new one.

    Plan §2.3: ``ON CONFLICT (url_canonical) DO NOTHING RETURNING id``,
    fallback ``SELECT id FROM reports WHERE url_canonical=?``.

    LLM-filled columns (summary, embedding) and promote-path metadata
    (tlp defaults to 'WHITE' via migration server default) are
    deliberately not set here — the canonical schema fills them or
    leaves them NULL per §2.3 LLM-filled scope. Callers passing those
    fields go through a future helper, not this one.
    """
    if not url_canonical:
        raise ValueError("url_canonical is required")
    if not sha256_title:
        raise ValueError("sha256_title is required")

    insert = _insert_factory(session)
    values: dict[str, Any] = {
        "published": published,
        "source_id": source_id,
        "title": title,
        "url": url,
        "url_canonical": url_canonical,
        "sha256_title": sha256_title,
        "lang": lang,
    }
    stmt = (
        insert(reports_table)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["url_canonical"])
        .returning(reports_table.c.id)
    )
    result = await session.execute(stmt)
    row_id = result.scalar_one_or_none()
    if row_id is not None:
        return row_id, False

    existing = await session.execute(
        sa.select(reports_table.c.id).where(
            reports_table.c.url_canonical == url_canonical
        )
    )
    return existing.scalar_one(), True


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------


async def upsert_tag(
    session: AsyncSession,
    *,
    name: str,
    type_: str,
) -> int:
    """Resolve a tag row by ``name``, inserting if missing.

    Plan §2.3: ``ON CONFLICT (name) DO NOTHING RETURNING id`` + SELECT
    fallback. ``type_`` is insert-only — if the existing row carries a
    different type, the upsert does NOT overwrite it (DO NOTHING).
    """
    if not name:
        raise ValueError("tag name is required")
    if not type_:
        raise ValueError("tag type is required")
    return await _upsert_by_unique_name(
        session,
        tags_table,
        values={"name": name, "type": type_},
    )


# ---------------------------------------------------------------------------
# groups + codenames (LLM-filled actor pipeline — Phase 4 trigger)
# ---------------------------------------------------------------------------


async def upsert_group(session: AsyncSession, *, name: str) -> int:
    """Resolve a group row by ``name``, inserting if missing.

    Plan §2.3 skeleton: the PR #10 promote path reaches this only via
    actor-type tags, and RSS/TAXII staging carries none until Phase 4
    LLM enrichment populates ``tags_jsonb``. The helper is
    implemented now so the later switch-on is one call-site change.
    """
    if not name:
        raise ValueError("group name is required")
    return await _upsert_by_unique_name(
        session,
        groups_table,
        values={"name": name},
    )


async def upsert_codename(
    session: AsyncSession,
    *,
    name: str,
    group_id: int | None = None,
) -> int:
    """Resolve a codename row by ``name``, inserting if missing.

    Plan §2.3 skeleton: same deferral rationale as ``upsert_group``.
    ``group_id`` is only applied on INSERT — an existing codename
    with a different group stays unchanged (DO NOTHING). The
    bootstrap ETL's group_id backfill logic (worker upsert.py) is
    deliberately not replicated here; the promote path is a
    single-authoring event, not a multi-pass reconciliation.
    """
    if not name:
        raise ValueError("codename name is required")
    return await _upsert_by_unique_name(
        session,
        codenames_table,
        values={"name": name, "group_id": group_id},
    )


# ---------------------------------------------------------------------------
# link tables (composite PK ON CONFLICT DO NOTHING)
# ---------------------------------------------------------------------------


async def link_report_tag(
    session: AsyncSession,
    *,
    report_id: int,
    tag_id: int,
    confidence: float | None = None,
) -> None:
    """Attach a tag to a report. Idempotent on composite PK.

    Plan §2.3: ``ON CONFLICT (report_id, tag_id) DO NOTHING``. No
    RETURNING — a caller that needs to know whether the link was
    freshly attached can observe it via the audit diff, not a return
    value. Existing ``confidence`` on a pre-linked row is NOT
    overwritten.
    """
    insert = _insert_factory(session)
    stmt = (
        insert(report_tags_table)
        .values(report_id=report_id, tag_id=tag_id, confidence=confidence)
        .on_conflict_do_nothing(index_elements=["report_id", "tag_id"])
    )
    await session.execute(stmt)


async def link_report_codename(
    session: AsyncSession,
    *,
    report_id: int,
    codename_id: int,
    confidence: float | None = None,
) -> None:
    """Attach a codename to a report. Idempotent on composite PK.

    Plan §2.3: ``ON CONFLICT (report_id, codename_id) DO NOTHING``.
    Same non-update semantics as ``link_report_tag``.
    """
    insert = _insert_factory(session)
    stmt = (
        insert(report_codenames_table)
        .values(
            report_id=report_id,
            codename_id=codename_id,
            confidence=confidence,
        )
        .on_conflict_do_nothing(index_elements=["report_id", "codename_id"])
    )
    await session.execute(stmt)


__all__ = [
    "link_report_codename",
    "link_report_tag",
    "upsert_codename",
    "upsert_group",
    "upsert_report",
    "upsert_source",
    "upsert_tag",
]
