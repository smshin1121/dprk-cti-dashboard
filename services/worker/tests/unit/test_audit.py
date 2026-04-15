"""Unit tests for ``worker.bootstrap.audit`` (PR #7 Group B step 1).

These tests pin the audit module's behavioural contract that the rest
of Group B wires into the upsert loop and the CLI transaction
structure. Every test here should be readable in isolation — the
row-level / run-level audit shapes defined by D3 / D3a / D4 should be
visible in the assertions without cross-referencing the production
writer code.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.audit import (
    AUDIT_ACTOR,
    AUDIT_BATCH_SIZE,
    ENTITY_TABLES_AUDITED,
    ROW_INSERT,
    ROW_UPDATE,
    RUN_COMPLETED,
    RUN_ENTITY,
    RUN_FAILED,
    RUN_STARTED,
    AuditBuffer,
    AuditBufferMark,
    AuditMeta,
    RowAuditEvent,
    new_audit_meta,
    new_uuid7,
    write_run_audit,
)
from worker.bootstrap.audit import _normalize_for_json
from worker.bootstrap.tables import audit_log_table


# ---------------------------------------------------------------------------
# new_uuid7 bit layout + monotonicity
# ---------------------------------------------------------------------------


class TestNewUuid7:
    def test_version_is_7(self) -> None:
        u = new_uuid7()
        assert u.version == 7, f"expected version 7, got {u.version}"

    def test_variant_is_rfc_4122(self) -> None:
        # uuid.UUID.variant returns the RFC 4122 string for variant bits
        # 10xx_xxxx — which is what RFC 9562 v7 uses too.
        u = new_uuid7()
        assert u.variant == uuid.RFC_4122

    def test_timestamp_prefix_matches_now(self) -> None:
        # The leading 48 bits are the unix millisecond timestamp. A
        # fresh uuid7 should have a timestamp within the last few
        # seconds of "now".
        import time

        now_ms = int(time.time() * 1000)
        u = new_uuid7()
        # Top 48 bits: shift right by 80.
        ts_from_uuid = u.int >> 80
        # Allow a 5-second window to avoid flakiness under cold starts.
        assert abs(ts_from_uuid - now_ms) < 5000, (
            f"uuid7 timestamp {ts_from_uuid} far from now_ms {now_ms}"
        )

    def test_monotonic_within_same_millisecond(self) -> None:
        # Successive uuid7 values generated in the same ms may or may
        # not be strictly increasing (we use random rand_a+rand_b, not
        # a counter) but they MUST all have the same leading timestamp
        # prefix. This guards against a bit-layout bug that would
        # scramble the timestamp into rand_b.
        uuids = [new_uuid7() for _ in range(20)]
        prefixes = {u.int >> 80 for u in uuids}
        # Allow at most 2 distinct prefixes (in case the loop crosses a
        # ms boundary).
        assert len(prefixes) <= 2, f"ts prefixes spread too wide: {prefixes}"

    def test_distinct_values(self) -> None:
        uuids = {new_uuid7() for _ in range(100)}
        assert len(uuids) == 100, "uuid7 collided within 100 draws"


# ---------------------------------------------------------------------------
# AuditMeta dataclass validation
# ---------------------------------------------------------------------------


class TestAuditMeta:
    def _valid_kwargs(self) -> dict[str, object]:
        return dict(
            run_id=new_uuid7(),
            workbook_sha256="a" * 64,
            started_at=dt.datetime(2026, 4, 15, 12, 0, 0, tzinfo=dt.timezone.utc),
        )

    def test_construct_happy_path(self) -> None:
        meta = AuditMeta(**self._valid_kwargs())
        assert meta.run_id.version == 7
        assert meta.workbook_sha256 == "a" * 64
        assert meta.started_at.tzinfo is dt.timezone.utc

    def test_frozen_immutable(self) -> None:
        meta = AuditMeta(**self._valid_kwargs())
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.workbook_sha256 = "b" * 64  # type: ignore[misc]

    def test_rejects_naive_datetime(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["started_at"] = dt.datetime(2026, 4, 15, 12, 0, 0)  # no tz
        with pytest.raises(ValueError, match="timezone-aware"):
            AuditMeta(**kwargs)

    def test_rejects_bad_sha256_length(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["workbook_sha256"] = "abc"  # 3 chars, not 64
        with pytest.raises(ValueError, match="64 hex chars"):
            AuditMeta(**kwargs)

    def test_as_dict_shape(self) -> None:
        meta = AuditMeta(**self._valid_kwargs())
        payload = meta.as_dict()
        assert set(payload) == {"run_id", "workbook_sha256", "started_at"}
        assert payload["run_id"] == str(meta.run_id)
        assert payload["workbook_sha256"] == "a" * 64
        # ISO 8601 with explicit offset
        assert payload["started_at"] == "2026-04-15T12:00:00+00:00"


# ---------------------------------------------------------------------------
# new_audit_meta — file reading + sha256
# ---------------------------------------------------------------------------


class TestNewAuditMeta:
    def test_computes_sha256_of_file(self, tmp_path: Path) -> None:
        workbook = tmp_path / "wb.xlsx"
        payload = b"hello world" * 1000
        workbook.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()

        meta = new_audit_meta(workbook)
        assert meta.workbook_sha256 == expected
        assert len(meta.workbook_sha256) == 64

    def test_generates_fresh_run_id_each_call(self, tmp_path: Path) -> None:
        workbook = tmp_path / "wb.xlsx"
        workbook.write_bytes(b"content")

        ids = {new_audit_meta(workbook).run_id for _ in range(5)}
        assert len(ids) == 5

    def test_started_at_is_utc(self, tmp_path: Path) -> None:
        workbook = tmp_path / "wb.xlsx"
        workbook.write_bytes(b"content")

        meta = new_audit_meta(workbook)
        assert meta.started_at.tzinfo is not None
        assert meta.started_at.utcoffset() == dt.timedelta(0)

    def test_hashes_large_file_in_chunks(self, tmp_path: Path) -> None:
        # Construct a workbook >= 2 MiB so the chunked read is exercised.
        workbook = tmp_path / "big.xlsx"
        payload = b"x" * (2 * 1024 * 1024 + 7)
        workbook.write_bytes(payload)

        meta = new_audit_meta(workbook)
        assert meta.workbook_sha256 == hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# RowAuditEvent validation
# ---------------------------------------------------------------------------


class TestRowAuditEvent:
    def test_accepts_all_five_audited_entity_tables(self) -> None:
        for entity in ENTITY_TABLES_AUDITED:
            event = RowAuditEvent(
                entity=entity,
                entity_id=1,
                action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {}},
            )
            assert event.entity == entity

    def test_rejects_mapping_table(self) -> None:
        with pytest.raises(ValueError, match="row-level audit is restricted"):
            RowAuditEvent(
                entity="report_tags",
                entity_id=1,
                action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {}},
            )

    def test_rejects_unknown_action(self) -> None:
        with pytest.raises(ValueError, match="unknown row action"):
            RowAuditEvent(
                entity="groups",
                entity_id=1,
                action="etl_delete",  # type: ignore[arg-type]
                diff_payload={"op": "delete"},
            )

    def test_entity_tables_audited_is_exactly_five(self) -> None:
        # Guard against a future edit that accidentally widens or
        # shrinks the audited set without also updating D3.
        assert ENTITY_TABLES_AUDITED == frozenset({
            "groups", "sources", "codenames", "reports", "incidents",
        })


# ---------------------------------------------------------------------------
# _normalize_for_json
# ---------------------------------------------------------------------------


class TestNormalizeForJson:
    def test_passes_through_primitives(self) -> None:
        assert _normalize_for_json("a") == "a"
        assert _normalize_for_json(1) == 1
        assert _normalize_for_json(1.5) == 1.5
        assert _normalize_for_json(True) is True
        assert _normalize_for_json(None) is None

    def test_date_to_iso(self) -> None:
        assert _normalize_for_json(dt.date(2026, 4, 15)) == "2026-04-15"

    def test_datetime_to_iso_with_offset(self) -> None:
        ts = dt.datetime(2026, 4, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
        assert _normalize_for_json(ts) == "2026-04-15T12:00:00+00:00"

    def test_uuid_to_string(self) -> None:
        u = new_uuid7()
        assert _normalize_for_json(u) == str(u)

    def test_bytes_to_hex(self) -> None:
        assert _normalize_for_json(b"\x00\xff") == "00ff"

    def test_recursive_dict(self) -> None:
        d = {
            "run_id": new_uuid7(),
            "published": dt.date(2026, 4, 15),
            "nested": {"ts": dt.datetime(2026, 4, 15, 12, tzinfo=dt.timezone.utc)},
        }
        normalized = _normalize_for_json(d)
        assert isinstance(normalized["run_id"], str)
        assert normalized["published"] == "2026-04-15"
        assert normalized["nested"]["ts"] == "2026-04-15T12:00:00+00:00"

    def test_list_and_tuple(self) -> None:
        src = [dt.date(2026, 1, 1), (dt.date(2026, 12, 31), "x")]
        normalized = _normalize_for_json(src)
        assert normalized == ["2026-01-01", ["2026-12-31", "x"]]


# ---------------------------------------------------------------------------
# AuditBuffer — batching and flush semantics
# ---------------------------------------------------------------------------


def _sample_meta() -> AuditMeta:
    return AuditMeta(
        run_id=new_uuid7(),
        workbook_sha256="f" * 64,
        started_at=dt.datetime(2026, 4, 15, 0, 0, 0, tzinfo=dt.timezone.utc),
    )


@pytest.mark.asyncio
class TestAuditBuffer:
    async def test_empty_flush_writes_nothing(self, db_session: AsyncSession) -> None:
        buf = AuditBuffer(db_session, _sample_meta())
        written = await buf.flush()
        assert written == 0
        count = await db_session.execute(
            sa.select(sa.func.count()).select_from(audit_log_table)
        )
        assert count.scalar_one() == 0

    async def test_single_append_then_flush(self, db_session: AsyncSession) -> None:
        meta = _sample_meta()
        buf = AuditBuffer(db_session, meta)
        buf.append(RowAuditEvent(
            entity="groups",
            entity_id=42,
            action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {"id": 42, "name": "Lazarus"}},
        ))
        assert buf.pending == 1
        written = await buf.flush()
        assert written == 1
        assert buf.pending == 0
        assert buf.total_written == 1

        stored = await db_session.execute(sa.select(audit_log_table))
        rows = list(stored.mappings())
        assert len(rows) == 1
        row = rows[0]
        assert row["actor"] == AUDIT_ACTOR
        assert row["action"] == ROW_INSERT
        assert row["entity"] == "groups"
        assert row["entity_id"] == "42"
        diff = row["diff_jsonb"]
        # sa.JSON() deserializes on read; diff is already a dict
        assert diff["op"] == "insert"
        assert diff["row"] == {"id": 42, "name": "Lazarus"}
        assert diff["meta"]["run_id"] == str(meta.run_id)
        assert diff["meta"]["workbook_sha256"] == "f" * 64
        assert diff["meta"]["started_at"] == "2026-04-15T00:00:00+00:00"

    async def test_chunking_splits_over_batch_size(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        buf = AuditBuffer(db_session, meta)
        # 1205 events → 3 chunks (500, 500, 205)
        total = AUDIT_BATCH_SIZE * 2 + 205
        for i in range(total):
            buf.append(RowAuditEvent(
                entity="reports",
                entity_id=i,
                action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {"id": i}},
            ))
        assert buf.pending == total

        written = await buf.flush()
        assert written == total
        assert buf.pending == 0
        assert buf.total_written == total

        count_row = await db_session.execute(
            sa.select(sa.func.count()).select_from(audit_log_table)
        )
        assert count_row.scalar_one() == total

    async def test_update_empty_changed_shape(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        buf = AuditBuffer(db_session, meta)
        buf.append(RowAuditEvent(
            entity="codenames",
            entity_id=7,
            action=ROW_UPDATE,
            diff_payload={"op": "update", "changed": {}},
        ))
        await buf.flush()

        row = (
            await db_session.execute(sa.select(audit_log_table))
        ).mappings().one()
        assert row["action"] == ROW_UPDATE
        assert row["diff_jsonb"]["op"] == "update"
        assert row["diff_jsonb"]["changed"] == {}
        # meta merged in even for empty-changed updates
        assert row["diff_jsonb"]["meta"]["run_id"] == str(meta.run_id)

    async def test_flush_twice_is_idempotent(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        buf = AuditBuffer(db_session, meta)
        buf.append(RowAuditEvent(
            entity="sources", entity_id=1, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {}},
        ))
        first = await buf.flush()
        second = await buf.flush()
        assert first == 1
        assert second == 0
        assert buf.total_written == 1
        count = await db_session.execute(
            sa.select(sa.func.count()).select_from(audit_log_table)
        )
        assert count.scalar_one() == 1


# ---------------------------------------------------------------------------
# AuditBuffer.mark / rollback_to — per-row cut-point semantics
# ---------------------------------------------------------------------------
#
# These tests pin the contract the user flagged in review: a per-row
# savepoint rollback must NOT drop audit events from previously
# successful rows. The mark/rollback_to pair implements a cut-point so
# the caller can truncate the buffer back to a specific position
# without touching earlier events.


@pytest.mark.asyncio
class TestAuditBufferMarkRollback:
    async def test_rollback_to_drops_only_events_after_mark(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        buf = AuditBuffer(db_session, meta)

        # Row 1: 2 events buffered, succeeds (no rollback).
        buf.append(RowAuditEvent(
            entity="groups", entity_id=1, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {"id": 1}},
        ))
        buf.append(RowAuditEvent(
            entity="sources", entity_id=10, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {"id": 10}},
        ))
        assert buf.pending == 2

        # Row 2 starts: mark the cut-point.
        mark = buf.mark()
        assert isinstance(mark, AuditBufferMark)
        assert mark.position == 2

        # Row 2 appends before failing.
        buf.append(RowAuditEvent(
            entity="groups", entity_id=2, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {"id": 2}},
        ))
        buf.append(RowAuditEvent(
            entity="reports", entity_id=100, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {"id": 100}},
        ))
        assert buf.pending == 4

        # Row 2 fails → roll back to the mark. Row 1's 2 events must
        # survive; Row 2's 2 events must be gone.
        buf.rollback_to(mark)
        assert buf.pending == 2

        # Flush and verify only Row 1's 2 events hit audit_log.
        written = await buf.flush()
        assert written == 2
        rows = (
            await db_session.execute(
                sa.select(audit_log_table).order_by(audit_log_table.c.entity_id)
            )
        ).mappings().all()
        assert len(rows) == 2
        entity_ids = {r["entity_id"] for r in rows}
        assert entity_ids == {"1", "10"}

    async def test_rollback_to_at_same_position_is_noop(
        self, db_session: AsyncSession
    ) -> None:
        buf = AuditBuffer(db_session, _sample_meta())
        buf.append(RowAuditEvent(
            entity="groups", entity_id=1, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {}},
        ))
        mark = buf.mark()  # position=1
        # No appends happen in the critical section.
        buf.rollback_to(mark)
        assert buf.pending == 1

    async def test_rollback_to_mark_at_position_zero_clears_buffer(
        self, db_session: AsyncSession
    ) -> None:
        buf = AuditBuffer(db_session, _sample_meta())
        mark = buf.mark()  # position=0 (buffer empty)
        buf.append(RowAuditEvent(
            entity="groups", entity_id=1, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {}},
        ))
        buf.append(RowAuditEvent(
            entity="groups", entity_id=2, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {}},
        ))
        assert buf.pending == 2
        buf.rollback_to(mark)
        assert buf.pending == 0

    async def test_mark_becomes_stale_after_flush(
        self, db_session: AsyncSession
    ) -> None:
        buf = AuditBuffer(db_session, _sample_meta())
        buf.append(RowAuditEvent(
            entity="groups", entity_id=1, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {}},
        ))
        mark = buf.mark()
        await buf.flush()  # epoch advances

        # Even if pending is 0 right now, the mark was made at epoch 0
        # and flush advanced to epoch 1. Any rollback attempt with the
        # old mark must refuse.
        with pytest.raises(ValueError, match="stale"):
            buf.rollback_to(mark)

    async def test_empty_flush_does_not_advance_epoch(
        self, db_session: AsyncSession
    ) -> None:
        buf = AuditBuffer(db_session, _sample_meta())
        mark = buf.mark()
        # Empty flush: nothing to persist, epoch must not advance.
        written = await buf.flush()
        assert written == 0
        # Buffer is still at epoch 0 → mark is still valid.
        buf.append(RowAuditEvent(
            entity="groups", entity_id=1, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {}},
        ))
        buf.rollback_to(mark)  # must not raise
        assert buf.pending == 0

    async def test_rollback_to_out_of_range_position_raises(
        self, db_session: AsyncSession
    ) -> None:
        buf = AuditBuffer(db_session, _sample_meta())
        # Fabricate a mark with a position past the pending length.
        bad_mark = AuditBufferMark(epoch=0, position=99)
        with pytest.raises(ValueError, match="out of range"):
            buf.rollback_to(bad_mark)

    async def test_realistic_per_row_savepoint_pattern(
        self, db_session: AsyncSession
    ) -> None:
        """Integration-style scenario for the per-row cut pattern.

        Simulates 3 workbook rows:
          - Row 1: upserts a group + a source (2 events) → SUCCESS
          - Row 2: upserts a group + a report + an incident (3 events)
                   → FAILS after all 3 events buffered
          - Row 3: upserts a codename (1 event) → SUCCESS

        Expected final state after flush: exactly 3 events in audit_log
        (Row 1's group + source, Row 3's codename). Row 2's partial
        buffering must be rolled back cleanly.
        """
        buf = AuditBuffer(db_session, _sample_meta())

        # Row 1
        mark1 = buf.mark()
        try:
            buf.append(RowAuditEvent(
                entity="groups", entity_id=1, action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {"id": 1, "name": "Lazarus"}},
            ))
            buf.append(RowAuditEvent(
                entity="sources", entity_id=10, action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {"id": 10, "name": "Mandiant"}},
            ))
        except Exception:  # pragma: no cover — defensive
            buf.rollback_to(mark1)

        # Row 2 — buffered then failed
        mark2 = buf.mark()
        assert mark2.position == 2
        try:
            buf.append(RowAuditEvent(
                entity="groups", entity_id=2, action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {"id": 2, "name": "Kimsuky"}},
            ))
            buf.append(RowAuditEvent(
                entity="reports", entity_id=100, action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {"id": 100, "title": "t"}},
            ))
            buf.append(RowAuditEvent(
                entity="incidents", entity_id=50, action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {"id": 50, "title": "i"}},
            ))
            raise RuntimeError("simulated row-2 upsert failure")
        except RuntimeError:
            buf.rollback_to(mark2)

        # Row 3
        mark3 = buf.mark()
        assert mark3.position == 2  # back to Row 1's end
        try:
            buf.append(RowAuditEvent(
                entity="codenames", entity_id=500, action=ROW_INSERT,
                diff_payload={"op": "insert", "row": {"id": 500, "name": "APT38"}},
            ))
        except Exception:  # pragma: no cover
            buf.rollback_to(mark3)

        assert buf.pending == 3  # 2 from Row 1 + 1 from Row 3

        written = await buf.flush()
        assert written == 3

        rows = (
            await db_session.execute(
                sa.select(audit_log_table).order_by(audit_log_table.c.id)
            )
        ).mappings().all()
        assert len(rows) == 3

        surviving = [(r["entity"], r["entity_id"]) for r in rows]
        assert surviving == [
            ("groups", "1"),
            ("sources", "10"),
            ("codenames", "500"),
        ]

        # The failed Row 2 events (groups/2, reports/100, incidents/50)
        # must NOT appear anywhere in audit_log.
        failed_entity_ids = {"2", "100", "50"}
        stored_entity_ids = {r["entity_id"] for r in rows}
        assert not (stored_entity_ids & failed_entity_ids)


# ---------------------------------------------------------------------------
# write_run_audit — D4 run-level shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWriteRunAudit:
    async def test_run_started_shape(self, db_session: AsyncSession) -> None:
        meta = _sample_meta()
        await write_run_audit(db_session, action=RUN_STARTED, meta=meta)

        row = (
            await db_session.execute(sa.select(audit_log_table))
        ).mappings().one()
        assert row["actor"] == AUDIT_ACTOR
        assert row["action"] == RUN_STARTED
        assert row["entity"] == RUN_ENTITY  # "etl_run"
        assert row["entity_id"] is None  # D4 nullable
        assert row["diff_jsonb"]["meta"]["run_id"] == str(meta.run_id)
        assert "detail" not in row["diff_jsonb"]

    async def test_run_completed_with_detail(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        await write_run_audit(
            db_session,
            action=RUN_COMPLETED,
            meta=meta,
            detail={"rows_attempted": 32, "rows_failed": 0, "dry_run": False},
        )
        row = (
            await db_session.execute(sa.select(audit_log_table))
        ).mappings().one()
        assert row["action"] == RUN_COMPLETED
        assert row["diff_jsonb"]["detail"] == {
            "rows_attempted": 32,
            "rows_failed": 0,
            "dry_run": False,
        }

    async def test_run_failed_carries_error_detail(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        await write_run_audit(
            db_session,
            action=RUN_FAILED,
            meta=meta,
            detail={"error_type": "ValueError", "error_message": "bad row"},
        )
        row = (
            await db_session.execute(sa.select(audit_log_table))
        ).mappings().one()
        assert row["action"] == RUN_FAILED
        assert row["diff_jsonb"]["detail"]["error_type"] == "ValueError"

    async def test_rejects_unknown_action(self, db_session: AsyncSession) -> None:
        meta = _sample_meta()
        with pytest.raises(ValueError, match="unknown run action"):
            await write_run_audit(
                db_session,
                action="etl_partial",  # type: ignore[arg-type]
                meta=meta,
            )

    async def test_multiple_run_events_share_same_run_id(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        await write_run_audit(db_session, action=RUN_STARTED, meta=meta)
        await write_run_audit(
            db_session,
            action=RUN_COMPLETED,
            meta=meta,
            detail={"rows_attempted": 1},
        )

        rows = (
            await db_session.execute(sa.select(audit_log_table).order_by(audit_log_table.c.id))
        ).mappings().all()
        assert len(rows) == 2
        run_ids = {r["diff_jsonb"]["meta"]["run_id"] for r in rows}
        assert run_ids == {str(meta.run_id)}


# ---------------------------------------------------------------------------
# Cross-link: AuditBuffer row events share run_id with write_run_audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunIdLinkageConsistency:
    """Both row-level and run-level writes on the same meta must
    carry the identical run_id string. This is the invariant the user's
    Group B review explicitly called out: a single run_id query must
    return a coherent timeline across both event shapes."""

    async def test_row_and_run_audit_share_run_id(
        self, db_session: AsyncSession
    ) -> None:
        meta = _sample_meta()
        await write_run_audit(db_session, action=RUN_STARTED, meta=meta)

        buf = AuditBuffer(db_session, meta)
        buf.append(RowAuditEvent(
            entity="groups", entity_id=1, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {"id": 1, "name": "Lazarus"}},
        ))
        buf.append(RowAuditEvent(
            entity="reports", entity_id=100, action=ROW_INSERT,
            diff_payload={"op": "insert", "row": {"id": 100, "title": "t"}},
        ))
        await buf.flush()

        await write_run_audit(
            db_session, action=RUN_COMPLETED, meta=meta,
            detail={"rows_attempted": 2},
        )

        rows = (
            await db_session.execute(
                sa.select(audit_log_table).order_by(audit_log_table.c.id)
            )
        ).mappings().all()
        assert len(rows) == 4  # started + 2 row inserts + completed

        # All four rows carry the same run_id, workbook_sha256, started_at
        run_ids = {r["diff_jsonb"]["meta"]["run_id"] for r in rows}
        wb_hashes = {r["diff_jsonb"]["meta"]["workbook_sha256"] for r in rows}
        started_ats = {r["diff_jsonb"]["meta"]["started_at"] for r in rows}
        assert run_ids == {str(meta.run_id)}
        assert wb_hashes == {"f" * 64}
        assert started_ats == {"2026-04-15T00:00:00+00:00"}

        # And the action progression is the expected timeline:
        assert [r["action"] for r in rows] == [
            RUN_STARTED, ROW_INSERT, ROW_INSERT, RUN_COMPLETED,
        ]
