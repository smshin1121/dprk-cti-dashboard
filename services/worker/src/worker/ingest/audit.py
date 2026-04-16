"""Audit trail writers for the RSS ingest pipeline (PR #8 Group E).

Thin module per D8: writes directly to ``audit_log_table`` with
actor ``"rss_ingest"`` and its own entity/action vocabulary.

Does NOT modify ``worker.bootstrap.audit`` — only imports shared
utilities: ``new_uuid7``, ``_normalize_for_json``, ``audit_log_table``.

Event granularities:

1. **Run-level** — ``rss_run_started`` / ``rss_run_completed`` /
   ``rss_run_failed``. Entity ``"rss_run"``, ``entity_id=NULL``.

2. **Row-level** — ``staging_insert``. Entity ``"staging"``,
   ``entity_id=str(staging.id)``.

``IngestRunMeta`` replaces ``AuditMeta`` because RSS has no workbook
(no ``workbook_sha256`` field). The ``feeds_path`` field replaces it
as the run-identifying file reference.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.audit import _normalize_for_json, new_uuid7
from worker.bootstrap.tables import audit_log_table


__all__ = [
    "INGEST_ACTOR",
    "RSS_RUN_STARTED",
    "RSS_RUN_COMPLETED",
    "RSS_RUN_FAILED",
    "STAGING_INSERT",
    "IngestRunMeta",
    "new_ingest_meta",
    "write_ingest_run_audit",
    "write_staging_insert_audit",
]


INGEST_ACTOR: str = "rss_ingest"

RSS_RUN_STARTED: str = "rss_run_started"
RSS_RUN_COMPLETED: str = "rss_run_completed"
RSS_RUN_FAILED: str = "rss_run_failed"
STAGING_INSERT: str = "staging_insert"

_RUN_ENTITY: str = "rss_run"
_STAGING_ENTITY: str = "staging"

_RunAction = Literal["rss_run_started", "rss_run_completed", "rss_run_failed"]


@dataclasses.dataclass(frozen=True, slots=True)
class IngestRunMeta:
    """Immutable run-identifying metadata for RSS ingest.

    Unlike ``AuditMeta``, this has no ``workbook_sha256`` because
    RSS ingest has no workbook. ``feeds_path`` identifies the feed
    catalog file used for this run.
    """

    run_id: uuid.UUID
    feeds_path: str
    started_at: dt.datetime

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            raise ValueError("IngestRunMeta.started_at must be timezone-aware")

    def as_dict(self) -> dict[str, str]:
        return {
            "run_id": str(self.run_id),
            "feeds_path": self.feeds_path,
            "started_at": self.started_at.isoformat(),
        }


def new_ingest_meta(feeds_path: str) -> IngestRunMeta:
    """Construct a fresh ``IngestRunMeta`` for a new ingest run."""
    return IngestRunMeta(
        run_id=new_uuid7(),
        feeds_path=feeds_path,
        started_at=dt.datetime.now(dt.timezone.utc),
    )


async def write_ingest_run_audit(
    session: AsyncSession,
    *,
    action: _RunAction,
    meta: IngestRunMeta,
    detail: dict[str, Any] | None = None,
) -> None:
    """Persist one run-level audit event for the RSS ingest pipeline.

    Uses ``entity="rss_run"`` and ``entity_id=NULL`` — same pattern
    as bootstrap's ``entity="etl_run"`` but with a different actor
    and entity literal.
    """
    if action not in (RSS_RUN_STARTED, RSS_RUN_COMPLETED, RSS_RUN_FAILED):
        raise ValueError(f"unknown ingest run action {action!r}")

    payload: dict[str, Any] = {"meta": meta.as_dict()}
    if detail:
        payload["detail"] = detail

    await session.execute(
        sa.insert(audit_log_table).values(
            actor=INGEST_ACTOR,
            action=action,
            entity=_RUN_ENTITY,
            entity_id=None,
            diff_jsonb=_normalize_for_json(payload),
        )
    )


async def write_staging_insert_audit(
    session: AsyncSession,
    *,
    meta: IngestRunMeta,
    staging_id: int,
    url_canonical: str,
) -> None:
    """Persist one row-level audit event for a staging insert.

    Uses ``entity="staging"`` and ``entity_id=str(staging_id)``.
    """
    payload: dict[str, Any] = {
        "op": "insert",
        "url_canonical": url_canonical,
        "meta": meta.as_dict(),
    }

    await session.execute(
        sa.insert(audit_log_table).values(
            actor=INGEST_ACTOR,
            action=STAGING_INSERT,
            entity=_STAGING_ENTITY,
            entity_id=str(staging_id),
            diff_jsonb=_normalize_for_json(payload),
        )
    )
