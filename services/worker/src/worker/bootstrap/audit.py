"""Audit trail writers for the Bootstrap ETL (PR #7 Group B).

Two event granularities are persisted to ``audit_log``:

1. **Run-level** events (``etl_run_started`` / ``etl_run_completed`` /
   ``etl_run_failed``) — one per ETL invocation. Use the literal
   ``entity="etl_run"`` with ``entity_id=NULL`` (permitted by migration
   0003). Every run-level row carries the same ``meta`` payload as every
   row-level row, so a single ``run_id`` SELECT yields the complete
   timeline for a given run.

2. **Row-level** events (``etl_insert`` / ``etl_update``) — one per
   upsert against the five entity tables in :data:`ENTITY_TABLES_AUDITED`
   (``groups``, ``sources``, ``codenames``, ``reports``, ``incidents``).
   Mapping tables like ``report_tags`` or ``incident_sources`` are
   **excluded** because they are derivable from the entity audit trail
   and auditing them would ~3x the write volume for no additional
   provenance information.

Every event shares a common :class:`AuditMeta` triple: ``run_id``
(uuid7, generated exactly once per ETL invocation at CLI entry),
``workbook_sha256`` (content hash of the workbook at read time), and
``started_at`` (UTC iso8601). These three fields are the *only* thing
that ties audit rows to a specific ETL run because ``audit_log`` has no
cross-run key of its own.

The module keeps transaction-boundary management out of scope. All
writers assume the caller already has an active transaction and only
issue ``INSERT`` statements. The caller (typically ``run_bootstrap`` in
``cli.py``) is responsible for arranging the savepoint structure that
makes run-level events survive body rollback while row-level events
participate in body rollback — see ``cli.py`` for the concrete layout.

See docs/plans/pr7-data-quality.md D3/D3a/D4 for the full schema
rationale. See ``tests/unit/test_audit.py`` for the behavioural
contract this module commits to.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import audit_log_table


__all__ = [
    "AUDIT_ACTOR",
    "AUDIT_BATCH_SIZE",
    "ENTITY_TABLES_AUDITED",
    "ROW_INSERT",
    "ROW_UPDATE",
    "RUN_COMPLETED",
    "RUN_ENTITY",
    "RUN_FAILED",
    "RUN_STARTED",
    "AuditBuffer",
    "AuditBufferMark",
    "AuditMeta",
    "RowAuditEvent",
    "new_audit_meta",
    "new_uuid7",
    "write_run_audit",
]


# ---------------------------------------------------------------------------
# Public constants (imported by cli.py, upsert.py, and test_audit.py)
# ---------------------------------------------------------------------------

#: Literal written to ``audit_log.actor`` for every ETL audit row.
AUDIT_ACTOR: str = "bootstrap_etl"

#: Literal written to ``audit_log.entity`` for run-level events (D4).
RUN_ENTITY: str = "etl_run"

#: Action verbs for run-level events (D4).
RUN_STARTED: str = "etl_run_started"
RUN_COMPLETED: str = "etl_run_completed"
RUN_FAILED: str = "etl_run_failed"

#: Action verbs for row-level events (D3).
ROW_INSERT: str = "etl_insert"
ROW_UPDATE: str = "etl_update"

#: Entity table names eligible for row-level audit (D3). Mapping tables
#: like ``report_tags`` are deliberately excluded; they are derivable
#: from the entity audit trail.
ENTITY_TABLES_AUDITED: frozenset[str] = frozenset({
    "groups",
    "sources",
    "codenames",
    "reports",
    "incidents",
})

#: Maximum rows per ``execute_many`` chunk when flushing the row audit
#: buffer. Sized for pg16 batch insert throughput; small enough to keep
#: any single batch well under the libpq binary protocol limit.
AUDIT_BATCH_SIZE: int = 500


# ---------------------------------------------------------------------------
# uuid7 inline implementation (RFC 9562)
# ---------------------------------------------------------------------------
#
# Python 3.12 (the worker's target) does not ship uuid.uuid7; it arrives
# in 3.14. We avoid the ``uuid6`` PyPI package because its API surface
# is still 0.x and any version churn would force a new worker-wheel
# release. The inline implementation is verified by
# ``test_new_uuid7_bit_layout`` and ``test_new_uuid7_monotonicity``.


def new_uuid7() -> uuid.UUID:
    """Return a fresh RFC 9562 version-7 UUID.

    Layout (128 bits):

      [48 bits unix_ms_ts] [4 bits ver=7] [12 bits rand_a]
      [2 bits var=10]      [62 bits rand_b]

    The leading 48-bit millisecond timestamp makes successive uuid7
    values lexicographically sortable, which is what we want for the
    ``audit_log`` run-correlation use case — a ``WHERE run_id > ... ORDER
    BY run_id`` query returns runs in chronological order without a
    secondary timestamp join.

    The 76 bits of randomness (``rand_a`` + ``rand_b``) give collision
    probability < 2^-76 within a single millisecond — adequate for
    single-writer bootstrap and all foreseeable multi-writer uses.
    """
    timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48 bits
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF  # 12 bits
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF  # 62 bits

    value = timestamp_ms << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # variant: RFC 9562 fixed bits '10'
    value |= rand_b

    return uuid.UUID(int=value)


# ---------------------------------------------------------------------------
# AuditMeta — the run-identifying triple shared across all events
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AuditMeta:
    """Immutable run-identifying metadata.

    One instance per ETL invocation, generated at CLI entry and threaded
    through ``run_bootstrap`` to every downstream writer. The immutability
    guarantees that every audit row written during a single run shares
    the exact same ``meta`` payload — which is what lets a reviewer run
    a single ``run_id`` query and get a coherent timeline back.

    Fields:
      run_id: uuid7 generated by :func:`new_uuid7`.
      workbook_sha256: SHA-256 content hash of the input workbook.
      started_at: UTC timestamp at CLI entry (before any DB I/O).
    """

    run_id: uuid.UUID
    workbook_sha256: str
    started_at: dt.datetime

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            raise ValueError("AuditMeta.started_at must be timezone-aware")
        if len(self.workbook_sha256) != 64:
            raise ValueError(
                f"workbook_sha256 must be 64 hex chars; got {len(self.workbook_sha256)}"
            )

    def as_dict(self) -> dict[str, str]:
        """Return the serializable form embedded in every ``diff_jsonb.meta``."""
        return {
            "run_id": str(self.run_id),
            "workbook_sha256": self.workbook_sha256,
            "started_at": self.started_at.isoformat(),
        }


def new_audit_meta(workbook_path: Path) -> AuditMeta:
    """Construct a fresh :class:`AuditMeta` for a workbook invocation.

    The ``workbook_path`` is read once to compute its SHA-256. ``run_id``
    is a fresh uuid7 and ``started_at`` is the current UTC timestamp.

    This function is the ONLY place an AuditMeta is created during a
    normal CLI invocation. Tests may construct AuditMeta instances
    directly for deterministic fixtures.
    """
    return AuditMeta(
        run_id=new_uuid7(),
        workbook_sha256=_compute_sha256(workbook_path),
        started_at=dt.datetime.now(dt.timezone.utc),
    )


def _compute_sha256(path: Path) -> str:
    """Stream-hash a file so we don't load the full workbook into RAM."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Row-level events
# ---------------------------------------------------------------------------


_RowAction = Literal["etl_insert", "etl_update"]


@dataclasses.dataclass(frozen=True, slots=True)
class RowAuditEvent:
    """A single buffered row-level audit record.

    ``diff_payload`` is the shape promised by D3a **minus** the ``meta``
    key. :meth:`AuditBuffer.flush` merges ``meta`` in at write time so
    every row in a single run shares the same meta instance without the
    caller having to repeat it on every event.

    For ``etl_insert`` the caller should pass
    ``{"op": "insert", "row": {...full row snapshot...}}``.

    For ``etl_update`` (idempotent re-run with no field changes) the
    caller should pass ``{"op": "update", "changed": {}}``.

    For ``etl_update`` with genuine field changes (a hypothetical future
    path; bootstrap's check-then-insert never produces this case today)
    the caller should pass
    ``{"op": "update", "changed": {<field>: {"before": X, "after": Y}}}``.
    """

    entity: str  # table name; must be in ENTITY_TABLES_AUDITED
    entity_id: int  # BIGINT PK, stringified at write time
    action: _RowAction
    diff_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.entity not in ENTITY_TABLES_AUDITED:
            raise ValueError(
                f"row-level audit is restricted to {sorted(ENTITY_TABLES_AUDITED)}; "
                f"got {self.entity!r}"
            )
        if self.action not in (ROW_INSERT, ROW_UPDATE):
            raise ValueError(f"unknown row action {self.action!r}")


@dataclasses.dataclass(frozen=True, slots=True)
class AuditBufferMark:
    """Opaque cutoff marker returned by :meth:`AuditBuffer.mark`.

    Carries the flush epoch the buffer was at when the mark was created
    so that :meth:`AuditBuffer.rollback_to` can refuse to act on a mark
    that has been invalidated by an intervening ``flush()`` call — at
    that point the events the caller wanted to roll back are already
    committed to the session's transaction and only the surrounding
    savepoint can reverse them.
    """

    epoch: int
    position: int


class AuditBuffer:
    """Buffer row-level events and flush them in :data:`AUDIT_BATCH_SIZE` chunks.

    The buffer is NOT a context manager — the caller is expected to call
    :meth:`flush` explicitly once per sheet, per workbook, or at the end
    of the ETL body (whichever granularity matches their rollback
    requirements). This keeps the buffer's behaviour predictable under
    exception-driven control flow: if ``flush`` is never called, no
    events are written, and the buffer's contents disappear when the
    containing transaction or savepoint is rolled back.

    The buffer is bound to a single ``AuditMeta`` at construction time.
    If the same ``AsyncSession`` is reused for multiple ETL invocations
    (unusual but legal), each invocation must create its own buffer.

    **Per-row savepoint integration.** The expected usage inside the
    bootstrap upsert loop is::

        for workbook_row in rows:
            mark = audit_buffer.mark()
            try:
                async with session.begin_nested():
                    await upsert(..., audit_buffer=audit_buffer)
            except Exception:
                audit_buffer.rollback_to(mark)  # only this row's events
                dead_letter.write(...)
        await audit_buffer.flush()

    :meth:`mark` captures the pending length AND the flush epoch so
    that :meth:`rollback_to` can truncate back to the mark without
    dropping events from previously-successful rows. If the caller
    flushes between ``mark()`` and ``rollback_to()``, the mark is
    marked stale and ``rollback_to`` raises — the "semantics escape
    hatch" is clear: already-flushed events cannot be rolled back by
    the buffer, only by the enclosing savepoint.
    """

    def __init__(self, session: AsyncSession, meta: AuditMeta) -> None:
        self._session = session
        self._meta = meta
        self._pending: list[RowAuditEvent] = []
        self._total_written = 0
        self._flush_epoch = 0

    @property
    def pending(self) -> int:
        """Number of events currently buffered (not yet flushed)."""
        return len(self._pending)

    @property
    def total_written(self) -> int:
        """Cumulative events written across all previous :meth:`flush` calls."""
        return self._total_written

    def append(self, event: RowAuditEvent) -> None:
        """Enqueue a single row-level event.

        This is a plain ``append`` without auto-flush because the
        upsert loop's per-row savepoint pattern means a buffered but
        un-flushed event must still be reversible when the per-row
        savepoint rolls back. Auto-flush would issue INSERTs inside
        arbitrary per-row savepoints, which is wrong — see the
        :meth:`mark` / :meth:`rollback_to` pair for the supported
        per-row cut-point pattern.
        """
        self._pending.append(event)

    def mark(self) -> AuditBufferMark:
        """Return a cut-point marker for the current buffer state.

        The marker is opaque: callers must pass it back to
        :meth:`rollback_to` unchanged. The marker encodes both the
        current pending length and the flush epoch, so any intervening
        :meth:`flush` call invalidates the mark and subsequent
        ``rollback_to`` raises.

        Typical usage pairs one ``mark()`` call with one ``rollback_to``
        call, both inside the same per-row savepoint scope. It is NOT
        an error to obtain a mark and never use it — callers can
        discard a mark if their critical section succeeds.
        """
        return AuditBufferMark(
            epoch=self._flush_epoch,
            position=len(self._pending),
        )

    def rollback_to(self, mark: AuditBufferMark) -> None:
        """Drop events appended since ``mark`` was obtained.

        If zero events have been appended since ``mark``, this is a
        no-op. If the mark is stale — because :meth:`flush` has been
        called between ``mark()`` and now — this raises
        :class:`ValueError` to make the misuse loud. Already-flushed
        events cannot be reversed here; the enclosing savepoint is the
        only mechanism that can undo a committed INSERT.

        The contract is deliberately narrow: ``rollback_to`` truncates
        ``self._pending`` back to ``mark.position`` and nothing else.
        It does not touch ``total_written``, the DB, or the session.
        """
        if mark.epoch != self._flush_epoch:
            raise ValueError(
                "AuditBuffer mark is stale: flush() was called since the "
                "mark was obtained. Already-flushed events can only be "
                "rolled back by the enclosing savepoint."
            )
        if mark.position < 0 or mark.position > len(self._pending):
            raise ValueError(
                f"AuditBuffer mark position {mark.position} out of range "
                f"[0, {len(self._pending)}]; buffer state has diverged "
                f"from the mark in an unexpected way"
            )
        del self._pending[mark.position:]

    async def flush(self) -> int:
        """Persist all buffered events to ``audit_log`` in AUDIT_BATCH_SIZE chunks.

        Returns the number of rows written during this call. Runs inside
        the caller's transaction — no ``session.begin`` or ``commit``.
        Uses the ``audit_log_table`` Core object so dict-to-JSON
        serialization is uniform across pg16 and sqlite-memory (the two
        backends the worker must support today).

        Each successful flush increments the internal flush epoch, so
        any :class:`AuditBufferMark` obtained before this call becomes
        stale and :meth:`rollback_to` will reject it. This is the
        load-bearing guarantee that makes the per-row savepoint
        pattern correct under mixed-granularity flushing (e.g., flush
        at sheet boundary, then keep processing).
        """
        if not self._pending:
            # Empty flush does NOT advance the epoch — there is nothing
            # to invalidate, and keeping the epoch stable lets callers
            # safely probe ``pending == 0`` without losing their marks.
            return 0

        meta_dict = self._meta.as_dict()
        rows: list[dict[str, Any]] = []
        for event in self._pending:
            diff = {**event.diff_payload, "meta": meta_dict}
            rows.append({
                "actor": AUDIT_ACTOR,
                "action": event.action,
                "entity": event.entity,
                "entity_id": str(event.entity_id),
                "diff_jsonb": _normalize_for_json(diff),
            })

        written = 0
        stmt = sa.insert(audit_log_table)
        for start in range(0, len(rows), AUDIT_BATCH_SIZE):
            chunk = rows[start:start + AUDIT_BATCH_SIZE]
            await self._session.execute(stmt, chunk)
            written += len(chunk)

        self._total_written += written
        self._pending.clear()
        self._flush_epoch += 1
        return written


# ---------------------------------------------------------------------------
# Run-level events
# ---------------------------------------------------------------------------


_RunAction = Literal["etl_run_started", "etl_run_completed", "etl_run_failed"]


async def write_run_audit(
    session: AsyncSession,
    *,
    action: _RunAction,
    meta: AuditMeta,
    detail: dict[str, Any] | None = None,
) -> None:
    """Persist one run-level audit event inline (no buffering).

    Run-level events are rare (at most 3 per ETL invocation: started,
    completed OR failed) and their ordering is semantically important
    relative to the surrounding savepoint boundaries, so buffering would
    only obscure the call site.

    Uses ``entity=RUN_ENTITY`` literal and ``entity_id=NULL`` per D4.
    Requires ``meta`` so the run_id is always present in diff_jsonb.
    Optional ``detail`` is merged under the ``detail`` key.
    """
    if action not in (RUN_STARTED, RUN_COMPLETED, RUN_FAILED):
        raise ValueError(f"unknown run action {action!r}")

    payload: dict[str, Any] = {"meta": meta.as_dict()}
    if detail:
        payload["detail"] = detail

    await session.execute(
        sa.insert(audit_log_table).values(
            actor=AUDIT_ACTOR,
            action=action,
            entity=RUN_ENTITY,
            entity_id=None,
            diff_jsonb=_normalize_for_json(payload),
        )
    )


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------


def _normalize_for_json(value: Any) -> Any:
    """Recursively coerce values to JSON-serializable types.

    ``sa.JSON()`` columns call ``json.dumps()`` internally on whatever
    dict / list / scalar we pass, but the stdlib JSON encoder rejects
    bootstrap row-snapshot types: ``datetime.date`` / ``datetime`` from
    DATE / TIMESTAMPTZ columns, ``uuid.UUID`` from UUID columns, bytes
    from BYTEA, Decimal from NUMERIC. Pre-walk the structure and
    rewrite these to stable string forms so SQLAlchemy's JSON serializer
    never sees them.

    The recursive walk is safe for the shapes we actually produce
    (shallow dicts of primitives and nested dicts) and is O(n) in the
    total value count. Cyclic references would loop forever, but
    bootstrap never produces cyclic data.
    """
    if isinstance(value, dict):
        return {k: _normalize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_json(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    # Primitives json.dumps knows about pass through unchanged; anything
    # else (Decimal, custom objects) goes through str() as a last resort
    # rather than raising, so a surprising column type cannot crash the
    # entire audit flush. The normalized form lands in diff_jsonb where
    # a later reviewer can spot the unexpected string and file a bug.
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
