"""Audit trail writers for the TAXII ingest pipeline (PR #9 Group E).

Thin module per decision F: writes directly to ``audit_log_table`` with
actor ``"taxii_ingest"`` and its own entity/action vocabulary.

Does NOT modify ``worker.bootstrap.audit`` or ``worker.ingest.audit``
(RSS) — only imports shared utilities: ``new_uuid7``,
``_normalize_for_json``, ``audit_log_table``.

Event granularities:

1. **Run-level** — ``taxii_run_started`` / ``taxii_run_completed`` /
   ``taxii_run_failed``. Entity ``"taxii_run"``, ``entity_id=NULL``.

2. **Row-level** — ``staging_insert``. Entity ``"staging"``,
   ``entity_id=str(staging.id)``.

``TaxiiRunMeta`` replaces ``IngestRunMeta`` because TAXII uses
``collections_path`` instead of ``feeds_path``.
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
    "TAXII_INGEST_ACTOR",
    "TAXII_RUN_STARTED",
    "TAXII_RUN_COMPLETED",
    "TAXII_RUN_FAILED",
    "STAGING_INSERT",
    "TaxiiRunMeta",
    "new_taxii_meta",
    "write_taxii_run_audit",
    "write_staging_insert_audit",
]


TAXII_INGEST_ACTOR: str = "taxii_ingest"

TAXII_RUN_STARTED: str = "taxii_run_started"
TAXII_RUN_COMPLETED: str = "taxii_run_completed"
TAXII_RUN_FAILED: str = "taxii_run_failed"
STAGING_INSERT: str = "staging_insert"

_RUN_ENTITY: str = "taxii_run"
_STAGING_ENTITY: str = "staging"

_RunAction = Literal[
    "taxii_run_started", "taxii_run_completed", "taxii_run_failed",
]


@dataclasses.dataclass(frozen=True, slots=True)
class TaxiiRunMeta:
    """Immutable run-identifying metadata for TAXII ingest.

    Unlike ``IngestRunMeta`` (RSS), this uses ``collections_path``
    instead of ``feeds_path``.
    """

    run_id: uuid.UUID
    collections_path: str
    started_at: dt.datetime

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            raise ValueError(
                "TaxiiRunMeta.started_at must be timezone-aware"
            )

    def as_dict(self) -> dict[str, str]:
        return {
            "run_id": str(self.run_id),
            "collections_path": self.collections_path,
            "started_at": self.started_at.isoformat(),
        }


def new_taxii_meta(collections_path: str) -> TaxiiRunMeta:
    """Construct a fresh ``TaxiiRunMeta`` for a new ingest run."""
    return TaxiiRunMeta(
        run_id=new_uuid7(),
        collections_path=collections_path,
        started_at=dt.datetime.now(dt.timezone.utc),
    )


async def write_taxii_run_audit(
    session: AsyncSession,
    *,
    action: _RunAction,
    meta: TaxiiRunMeta,
    detail: dict[str, Any] | None = None,
) -> None:
    """Persist one run-level audit event for the TAXII ingest pipeline.

    Uses ``entity="taxii_run"`` and ``entity_id=NULL``.
    """
    if action not in (TAXII_RUN_STARTED, TAXII_RUN_COMPLETED, TAXII_RUN_FAILED):
        raise ValueError(f"unknown TAXII run action {action!r}")

    payload: dict[str, Any] = {"meta": meta.as_dict()}
    if detail:
        payload["detail"] = detail

    await session.execute(
        sa.insert(audit_log_table).values(
            actor=TAXII_INGEST_ACTOR,
            action=action,
            entity=_RUN_ENTITY,
            entity_id=None,
            diff_jsonb=_normalize_for_json(payload),
        )
    )


async def write_staging_insert_audit(
    session: AsyncSession,
    *,
    meta: TaxiiRunMeta,
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
            actor=TAXII_INGEST_ACTOR,
            action=STAGING_INSERT,
            entity=_STAGING_ENTITY,
            entity_id=str(staging_id),
            diff_jsonb=_normalize_for_json(payload),
        )
    )
