"""Single-transaction promote / reject orchestration.

Plan §2.2 A locks the 8-step approve path and the symmetric reject
path. The whole decision runs inside **one transaction opened by the
caller** (the router does ``async with session.begin():`` and calls
these functions inside it). Partial writes must never leak if any
step raises — the caller's ``async with`` rolls back on exception.

Why the caller owns the transaction, not the service: the router is
the natural place for HTTP-response-to-DB-transaction mapping (same
pattern as audit logging around the request), and delegating lets the
service compose cleanly inside tests that already want atomic setup.

Critical invariants (reviewer checklist in order):

1. **Single transaction.** The service performs zero commits and
   zero rollbacks. Every write (sources / reports / tags / staging
   UPDATE / audit_log INSERT) runs inside the caller's transaction.
   A raise from any step propagates to the caller, whose
   ``async with`` triggers rollback. The staging row stays in its
   pre-call status.
2. **Single-winner under concurrent approve.** We start with
   ``SELECT ... FROM staging WHERE id=? FOR UPDATE`` so only one
   transaction can read the pending row. The final staging UPDATE
   adds ``WHERE id=? AND status='pending'`` as a second defense —
   if RETURNING comes back empty, we raise
   ``StagingAlreadyDecidedError`` and the caller rolls back.
3. **Approve emits exactly ONE audit event.** Plan §2.1 D4:
   ``STAGING_APPROVED`` was dropped — approve fires a single
   ``REPORT_PROMOTED`` row whose ``diff_jsonb`` encodes everything
   reviewers need (from_staging_id, attached_existing,
   reviewer_notes, report_snapshot).
4. **Reject writes decision_reason to the staging column, notes to
   audit only.** Plan §2.1 D1 / §2.2 C lock. ``staging.decision_reason``
   (migration 0008) receives the normalized reject reason;
   ``reviewer_notes`` lives only in ``audit_log.diff_jsonb``.
5. **Mid-transaction failure keeps staging pending.** If any write
   after the FOR UPDATE raises, the caller's rollback restores
   staging to its original pending state — promote_report_id stays
   NULL, status stays 'pending', no audit row appears.

SQLite support (unit tests): ``SELECT FOR UPDATE`` is a no-op on
SQLite — SQLAlchemy silently omits the lock clause. That means
Group C/D SQLite tests cannot verify invariant #2 (single-winner
under concurrent writers). The Group H real-PG job is authoritative
for concurrency proofs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..tables import audit_log_table, staging_table
from .errors import (
    PromoteValidationError,
    StagingAlreadyDecidedError,
    StagingInvalidStateError,
    StagingNotFoundError,
)
from .repositories import upsert_report, upsert_source


# ---------------------------------------------------------------------------
# Audit action constants — plan §2.1 D4 locks exactly two values for PR #10
# ---------------------------------------------------------------------------

ACTION_REPORT_PROMOTED = "REPORT_PROMOTED"
ACTION_STAGING_REJECTED = "STAGING_REJECTED"

ENTITY_REPORTS = "reports"
ENTITY_STAGING = "staging"

# Default source name when staging.source_id is NULL — matches the
# bootstrap ETL's anonymous-promotion convention. RSS/TAXII ingest
# currently writes source_id=NULL (PR #8/9 D2 scope), so every promote
# in Phase 2 lands under this synthetic source until a later PR
# teaches the ingest workers to resolve vendor names from feed/
# collection config. Documented in plan §2.3 (staging.source_id
# handling).
UNKNOWN_SOURCE_NAME = "unknown"


# ---------------------------------------------------------------------------
# Outcome dataclasses (frozen — matches DTO immutability rule)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromoteOutcome:
    """Result of a successful approve.

    ``attached_existing`` is True when ``reports.url_canonical``
    already had a row and this promote attached to it rather than
    inserting — the router does not need to distinguish, but the
    audit diff captures it for forensics.
    """

    staging_id: int
    report_id: int
    attached_existing: bool
    reviewer_sub: str


@dataclass(frozen=True)
class RejectOutcome:
    """Result of a successful reject."""

    staging_id: int
    decision_reason: str
    reviewer_sub: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_title(title: str) -> str:
    """Compute staging-side sha256 of a title string.

    Matches the worker's normalization (lowercase + strip) so the
    promote-path hash stays identical to what the ingest workers
    wrote. Not imported from worker to keep services decoupled.
    """
    return hashlib.sha256(title.lower().strip().encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    """JSON serializer hook for date/datetime values in diff_jsonb.

    audit_log.diff_jsonb is a JSON column; native ``date`` and
    ``datetime`` objects need ISO-format string conversion so the
    column accepts them on both PG and SQLite.
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unserializable type in audit diff: {type(value)!r}")


def _serialize_diff(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a diff dict so it round-trips through the JSON type.

    SQLAlchemy's JSON type passes Python dicts straight to the driver;
    any non-primitive value inside (``date``, ``datetime``, ``Decimal``)
    would fail at serialization time. Round-tripping through
    ``json.dumps(default=_json_default) -> json.loads`` forces the
    conversion in one pass and guarantees the column sees only
    JSON-compatible primitives regardless of dialect.
    """
    return json.loads(json.dumps(payload, default=_json_default))


async def _lock_and_load_staging(
    session: AsyncSession, staging_id: int
) -> sa.engine.Row:
    """Acquire FOR UPDATE on the staging row and return its current state.

    Raises ``StagingNotFoundError`` when no such row exists.
    ``StagingAlreadyDecidedError`` for non-pending rows is raised by
    the callers (approve / reject) since the 409 body needs the
    decided_by / decided_at values that live on the staging row.
    """
    stmt = (
        sa.select(
            staging_table.c.id,
            staging_table.c.status,
            staging_table.c.source_id,
            staging_table.c.url,
            staging_table.c.url_canonical,
            staging_table.c.sha256_title,
            staging_table.c.title,
            staging_table.c.lang,
            staging_table.c.published,
            staging_table.c.reviewed_by,
            staging_table.c.reviewed_at,
        )
        .where(staging_table.c.id == staging_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise StagingNotFoundError(staging_id=staging_id)
    return row


async def _fetch_decided_state(
    session: AsyncSession,
    staging_id: int,
    *,
    fallback_status: str,
) -> tuple[str, str, datetime]:
    """Re-read ``(status, reviewed_by, reviewed_at)`` after the
    conditional UPDATE's RETURNING came back empty.

    The FOR UPDATE lock makes the race-lost branch effectively
    unreachable under PG's default isolation, but Codex R1 P2 flagged
    that when it DOES fire (cross-decision race, or non-locking
    dialect like SQLite) the hardcoded ``"promoted"`` / ``"rejected"``
    values could misreport the real decision. A promote caller losing
    to a concurrent reject should see ``current_status="rejected"``
    in the 409 body, not a stale guess derived from the caller's own
    intent. ``decided_by`` / ``decided_at`` are similarly recovered
    from the staging row rather than left as `""` / `now()`.

    Defensive fallback keeps the 409 HTTP contract valid even if the
    re-read returns nothing decidable (row vanished / stays pending
    due to an inconsistency we cannot diagnose here): return the
    caller-provided ``fallback_status`` with an empty actor and a
    fresh ``now()`` timestamp. That matches the pre-fix behavior so
    no existing callers regress.
    """
    result = await session.execute(
        sa.select(
            staging_table.c.status,
            staging_table.c.reviewed_by,
            staging_table.c.reviewed_at,
        ).where(staging_table.c.id == staging_id)
    )
    row = result.one_or_none()
    if row is not None and row.status in {"promoted", "rejected"}:
        return (
            row.status,
            row.reviewed_by or "",
            row.reviewed_at or datetime.now(timezone.utc),
        )
    return fallback_status, "", datetime.now(timezone.utc)


def _raise_if_not_pending(
    row: sa.engine.Row, staging_id: int
) -> None:
    """Enforce the pending-only precondition.

    Two distinct exception classes map cleanly to the narrowly typed
    HTTP surface:

    - ``promoted`` / ``rejected`` → ``StagingAlreadyDecidedError``
      (router → 409 with ``AlreadyDecidedError`` body; the DTO locks
      ``current_status`` to ``Literal["promoted","rejected"]`` per
      plan §2.2 B).
    - ``approved`` / ``error`` (or any other non-pending value) →
      ``StagingInvalidStateError`` (router → 422). These CHECK enum
      values are reserved for future/operational flows that the
      review endpoint deliberately does not handle, so the router
      must avoid the 409 AlreadyDecidedError DTO — serializing
      ``"approved"`` through ``DecidedStatus`` would fail Pydantic
      validation and bury the real issue under a type error.
    """
    if row.status == "pending":
        return
    if row.status in {"promoted", "rejected"}:
        raise StagingAlreadyDecidedError(
            staging_id=staging_id,
            current_status=row.status,
            decided_by=row.reviewed_by or "",
            decided_at=row.reviewed_at or datetime.now(timezone.utc),
        )
    raise StagingInvalidStateError(
        staging_id=staging_id,
        current_status=row.status,
    )


def _build_report_fields(
    row: sa.engine.Row, staging_id: int
) -> dict[str, Any]:
    """Translate a staging row into the minimal reports insert payload.

    Raises ``PromoteValidationError`` when a field that ``reports``
    declares NOT NULL is missing from staging. Listed reasons are
    surfaced in the 422 body by the router.
    """
    if not row.url_canonical:
        raise PromoteValidationError(
            staging_id=staging_id, reason="url_canonical is NULL on staging"
        )
    if not row.title:
        raise PromoteValidationError(
            staging_id=staging_id, reason="title is NULL on staging"
        )
    if not row.url:
        raise PromoteValidationError(
            staging_id=staging_id, reason="url is NULL on staging"
        )
    if row.published is None:
        raise PromoteValidationError(
            staging_id=staging_id,
            reason="published is NULL on staging (reports.published is NOT NULL)",
        )
    # reports.published is DATE; staging.published is tz-aware DateTime.
    # Normalize via ``.date()`` so pg/sqlite both accept the value.
    if isinstance(row.published, datetime):
        published_date = row.published.date()
    elif isinstance(row.published, date):
        published_date = row.published
    else:
        raise PromoteValidationError(
            staging_id=staging_id,
            reason=f"published has unexpected type: {type(row.published).__name__}",
        )

    sha = row.sha256_title or _sha256_title(row.title)

    return {
        "published": published_date,
        "title": row.title,
        "url": row.url,
        "url_canonical": row.url_canonical,
        "sha256_title": sha,
        "lang": row.lang,
    }


async def _emit_audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity: str,
    entity_id: int,
    diff: dict[str, Any],
) -> None:
    """Insert one row into ``audit_log``.

    Deliberately NOT wrapped in try/except: an audit write failure
    must abort the whole transaction. The PR #8/9 "audit swallowing"
    pattern (worker savepoint + except Exception: pass) is wrong for
    the promote path — losing provenance on a real production write
    is a reviewer-visible data corruption risk.
    """
    await session.execute(
        sa.insert(audit_log_table).values(
            actor=actor,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            diff_jsonb=_serialize_diff(diff),
        )
    )


# ---------------------------------------------------------------------------
# Public API — promote (approve) / reject
# ---------------------------------------------------------------------------


async def promote_staging_row(
    session: AsyncSession,
    *,
    staging_id: int,
    reviewer_sub: str,
    reviewer_notes: str | None,
) -> PromoteOutcome:
    """Approve a staging row — materialize it into ``reports`` + link
    tables, mark staging promoted, emit a single ``REPORT_PROMOTED``
    audit event.

    All work happens inside a single explicit transaction. Any raise
    rolls back the whole batch including the staging UPDATE, so a
    mid-transaction failure leaves the row at its original ``pending``
    status with no audit footprint.

    LLM-filled fields (``staging.tags_jsonb`` / ``summary`` /
    ``embedding``) are NULL in Phase 2 ingests (plan §2.3 LLM-filled
    scope). The tags / groups / codenames paths are intentionally
    skeletons — they light up when Phase 4 LLM enrichment populates
    ``tags_jsonb``.

    The caller MUST wrap this call in ``async with session.begin():``
    (or equivalent). This function performs zero commit/rollback —
    raising propagates to the caller's ``async with`` which rolls
    back the whole batch.
    """
    row = await _lock_and_load_staging(session, staging_id)
    _raise_if_not_pending(row, staging_id)

    # Source resolution. staging.source_id is nullable; fall back
    # to the synthetic 'unknown' source so ``reports.source_id``
    # (NOT NULL) always has a target. Future PR populates
    # staging.source_id at ingest time → this branch no-ops.
    if row.source_id is not None:
        source_id = row.source_id
    else:
        source_id = await upsert_source(
            session=session, name=UNKNOWN_SOURCE_NAME
        )

    report_fields = _build_report_fields(row, staging_id)
    report_id, attached_existing = await upsert_report(
        session=session,
        source_id=source_id,
        **report_fields,
    )

    # Phase 4 skeleton: staging.tags_jsonb drives tags /
    # report_tags / groups / codenames / report_codenames upserts.
    # With tags_jsonb NULL in all Phase 2 ingests, there is
    # nothing to attach here. Left as a comment instead of
    # empty-if so reviewers see the deferred scope inline.
    #   if row.tags_jsonb:
    #       for tag in row.tags_jsonb:
    #           ... upsert_tag / link_report_tag ...

    # Conditional UPDATE — second defense against the concurrent
    # approve race (plan §2.2 B). If RETURNING is empty another
    # writer beat us between FOR UPDATE and this line, which in
    # practice PG cannot produce while we hold the row lock, but
    # we ASSERT the invariant anyway to match the locked contract.
    update_stmt = (
        sa.update(staging_table)
        .where(
            (staging_table.c.id == staging_id)
            & (staging_table.c.status == "pending")
        )
        .values(
            status="promoted",
            promoted_report_id=report_id,
            reviewed_by=reviewer_sub,
            reviewed_at=sa.func.current_timestamp(),
        )
        .returning(staging_table.c.id)
    )
    updated = await session.execute(update_stmt)
    if updated.scalar_one_or_none() is None:
        # Raised before audit_log INSERT — the caller's rollback
        # preserves everything including the source/report rows
        # written above (they are inside the same transaction).
        # Re-read the row so the 409 body reports the actual
        # winner's state (Codex R1 P2 — cross-decision race would
        # otherwise surface a misleading current_status).
        status, decided_by, decided_at = await _fetch_decided_state(
            session, staging_id, fallback_status="promoted"
        )
        raise StagingAlreadyDecidedError(
            staging_id=staging_id,
            current_status=status,
            decided_by=decided_by,
            decided_at=decided_at,
        )

    await _emit_audit(
        session,
        actor=reviewer_sub,
        action=ACTION_REPORT_PROMOTED,
        entity=ENTITY_REPORTS,
        entity_id=report_id,
        diff={
            "from_staging_id": staging_id,
            "attached_existing": attached_existing,
            "reviewer_notes": reviewer_notes,
            "report_snapshot": {
                "id": report_id,
                "source_id": source_id,
                **report_fields,
            },
        },
    )

    return PromoteOutcome(
        staging_id=staging_id,
        report_id=report_id,
        attached_existing=attached_existing,
        reviewer_sub=reviewer_sub,
    )


async def reject_staging_row(
    session: AsyncSession,
    *,
    staging_id: int,
    reviewer_sub: str,
    decision_reason: str,
    reviewer_notes: str | None,
) -> RejectOutcome:
    """Reject a staging row — mark ``status='rejected'``, store
    ``decision_reason`` on the staging column, emit one
    ``STAGING_REJECTED`` audit event.

    No production-table writes. Reviewer notes are audit-only per
    plan §2.1 D4 (``staging`` has NO ``notes`` column; migration 0008
    added only ``decision_reason``).

    The caller MUST wrap this call in ``async with session.begin():``
    (or equivalent). This function performs zero commit/rollback.
    """
    row = await _lock_and_load_staging(session, staging_id)
    _raise_if_not_pending(row, staging_id)

    update_stmt = (
        sa.update(staging_table)
        .where(
            (staging_table.c.id == staging_id)
            & (staging_table.c.status == "pending")
        )
        .values(
            status="rejected",
            decision_reason=decision_reason,
            reviewed_by=reviewer_sub,
            reviewed_at=sa.func.current_timestamp(),
        )
        .returning(staging_table.c.id)
    )
    updated = await session.execute(update_stmt)
    if updated.scalar_one_or_none() is None:
        # Same Codex R1 P2 re-read as the approve path — a reject
        # caller losing to a concurrent promote must surface
        # current_status="promoted", not the reject-intent guess.
        status, decided_by, decided_at = await _fetch_decided_state(
            session, staging_id, fallback_status="rejected"
        )
        raise StagingAlreadyDecidedError(
            staging_id=staging_id,
            current_status=status,
            decided_by=decided_by,
            decided_at=decided_at,
        )

    await _emit_audit(
        session,
        actor=reviewer_sub,
        action=ACTION_STAGING_REJECTED,
        entity=ENTITY_STAGING,
        entity_id=staging_id,
        diff={
            "decision_reason": decision_reason,
            "reviewer_notes": reviewer_notes,
        },
    )

    return RejectOutcome(
        staging_id=staging_id,
        decision_reason=decision_reason,
        reviewer_sub=reviewer_sub,
    )


__all__ = [
    "ACTION_REPORT_PROMOTED",
    "ACTION_STAGING_REJECTED",
    "ENTITY_REPORTS",
    "ENTITY_STAGING",
    "PromoteOutcome",
    "RejectOutcome",
    "UNKNOWN_SOURCE_NAME",
    "promote_staging_row",
    "reject_staging_row",
]
