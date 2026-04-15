"""Unit tests for worker.data_quality.sinks (PR #7 Group C).

Covers review points (2) and (3):
  - DbSink writes rows that match the dq_events D5 schema 1:1.
  - JsonlSink writes rows that are semantically equivalent to the
    DbSink rows (same run_id, expectation, severity, observed,
    threshold, observed_rows, detail, observed_at).
  - StdoutSink renders an ASCII-only summary table suitable for
    cp949 consoles.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import dq_events_table
from worker.data_quality.results import ExpectationResult
from worker.data_quality.sinks import DbSink, JsonlSink, StdoutSink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FIXED_TS = dt.datetime(2026, 4, 15, 12, 0, 0, tzinfo=dt.timezone.utc)


def _result(
    name: str,
    severity: str,
    *,
    observed: Decimal | int | None = None,
    threshold: Decimal | int | None = None,
    observed_rows: int | None = None,
    detail: dict | None = None,
) -> ExpectationResult:
    return ExpectationResult(
        name=name,
        severity=severity,
        observed=observed,
        threshold=threshold,
        observed_rows=observed_rows,
        detail=detail or {},
        observed_at=_FIXED_TS,
    )


def _sample_batch() -> list[ExpectationResult]:
    """A representative 11-item batch spanning every severity and shape."""
    return [
        _result("reports.tlp.value_domain", "pass", observed_rows=0),
        _result("sources.country.iso2_conformance", "pass", observed_rows=0),
        _result(
            "incident_countries.country_iso2.iso2_conformance",
            "pass",
            observed_rows=0,
        ),
        _result("tags.type.enum_conformance", "pass", observed_rows=0),
        _result("reports.published.year_range", "pass", observed_rows=0),
        _result("incidents.reported.year_range", "pass", observed_rows=0),
        _result(
            "groups.canonical_name.forward_check",
            "error",
            observed_rows=2,
            detail={"offending_canonicals": ["Unknown1", "Unknown2"]},
        ),
        _result(
            "groups.canonical_name.reverse_check",
            "warn",
            detail={"unused_yaml_canonicals": ["Konni"]},
        ),
        _result(
            "reports.url_canonical.dedup_rate",
            "warn",
            observed=Decimal("0.1730"),
            threshold=Decimal("0.1500"),
        ),
        _result(
            "codenames.group_id.null_rate",
            "warn",
            observed=Decimal("0.6200"),
            threshold=Decimal("0.5000"),
        ),
        _result(
            "codenames.named_by_source_id.null_rate",
            "pass",
            observed=Decimal("0.3100"),
            threshold=Decimal("0.5000"),
        ),
    ]


# ---------------------------------------------------------------------------
# DbSink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDbSink:
    async def test_writes_one_row_per_result(
        self, db_session: AsyncSession
    ) -> None:
        run_id = uuid.uuid4()
        sink = DbSink(db_session, run_id)

        await sink.write(_sample_batch())

        count = (await db_session.execute(
            sa.select(sa.func.count()).select_from(dq_events_table)
        )).scalar_one()
        assert count == 11

    async def test_empty_batch_is_noop(
        self, db_session: AsyncSession
    ) -> None:
        sink = DbSink(db_session, uuid.uuid4())
        await sink.write([])
        count = (await db_session.execute(
            sa.select(sa.func.count()).select_from(dq_events_table)
        )).scalar_one()
        assert count == 0

    async def test_d5_column_mapping_one_to_one(
        self, db_session: AsyncSession
    ) -> None:
        """Pins review point 2: every column in dq_events matches the
        ExpectationResult field it was derived from."""
        run_id = uuid.uuid4()
        sink = DbSink(db_session, run_id)

        batch = [
            _result(
                "reports.url_canonical.dedup_rate",
                "warn",
                observed=Decimal("0.1730"),
                threshold=Decimal("0.1500"),
                observed_rows=320,
                detail={"sample": "payload"},
            ),
        ]
        await sink.write(batch)

        row = (
            await db_session.execute(sa.select(dq_events_table))
        ).mappings().one()

        assert str(row["run_id"]) == str(run_id)
        assert row["expectation"] == "reports.url_canonical.dedup_rate"
        assert row["severity"] == "warn"
        assert Decimal(str(row["observed"])) == Decimal("0.1730")
        assert Decimal(str(row["threshold"])) == Decimal("0.1500")
        assert row["observed_rows"] == 320
        assert row["detail_jsonb"] == {"sample": "payload"}
        # observed_at passed explicitly matches the fixture's _FIXED_TS
        # (up to sqlite datetime round-trip, which drops timezone on
        # the string path but preserves the wall-clock value).
        stored = row["observed_at"]
        assert stored.year == 2026 and stored.month == 4 and stored.day == 15
        assert stored.hour == 12

    async def test_pass_warn_error_all_accepted_by_check_constraint(
        self, db_session: AsyncSession
    ) -> None:
        sink = DbSink(db_session, uuid.uuid4())
        await sink.write([
            _result("a", "pass"),
            _result("b", "warn"),
            _result("c", "error"),
        ])
        rows = (
            await db_session.execute(
                sa.select(dq_events_table.c.severity).order_by(
                    dq_events_table.c.id
                )
            )
        ).scalars().all()
        assert rows == ["pass", "warn", "error"]

    async def test_nullable_observed_and_threshold(
        self, db_session: AsyncSession
    ) -> None:
        sink = DbSink(db_session, uuid.uuid4())
        await sink.write([
            _result("only-rows", "pass", observed_rows=0),
        ])
        row = (
            await db_session.execute(sa.select(dq_events_table))
        ).mappings().one()
        assert row["observed"] is None
        assert row["threshold"] is None
        assert row["observed_rows"] == 0

    async def test_run_id_stable_across_batch(
        self, db_session: AsyncSession
    ) -> None:
        run_id = uuid.uuid4()
        sink = DbSink(db_session, run_id)
        await sink.write(_sample_batch())

        rows = (
            await db_session.execute(sa.select(dq_events_table))
        ).mappings().all()
        ids = {str(r["run_id"]) for r in rows}
        assert ids == {str(run_id)}


# ---------------------------------------------------------------------------
# JsonlSink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJsonlSink:
    async def test_writes_one_line_per_result(self, tmp_path: Path) -> None:
        path = tmp_path / "dq_report.jsonl"
        sink = JsonlSink(path, uuid.uuid4())
        await sink.write(_sample_batch())

        lines = path.read_text("utf-8").splitlines()
        assert len(lines) == 11
        for line in lines:
            assert json.loads(line)  # every line is valid JSON

    async def test_empty_batch_produces_empty_file(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "empty.jsonl"
        sink = JsonlSink(path, uuid.uuid4())
        await sink.write([])
        assert path.exists()
        assert path.read_text("utf-8") == ""

    async def test_creates_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "dq.jsonl"
        sink = JsonlSink(nested, uuid.uuid4())
        await sink.write([_result("x", "pass")])
        assert nested.exists()

    async def test_decimal_observed_serialized_as_string_exact(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "decimal.jsonl"
        sink = JsonlSink(path, uuid.uuid4())
        await sink.write([
            _result(
                "reports.url_canonical.dedup_rate",
                "warn",
                observed=Decimal("0.1730"),
                threshold=Decimal("0.1500"),
            ),
        ])
        row = json.loads(path.read_text("utf-8").strip())
        # String form preserves exact decimal — no float drift.
        assert row["observed"] == "0.1730"
        assert row["threshold"] == "0.1500"

    async def test_row_shape_matches_d5_column_set(
        self, tmp_path: Path
    ) -> None:
        """Pins review point 3: JSONL row carries exactly the same
        fields the DB sink writes, in semantic terms."""
        path = tmp_path / "shape.jsonl"
        run_id = uuid.uuid4()
        sink = JsonlSink(path, run_id)
        await sink.write([
            _result(
                "reports.url_canonical.dedup_rate",
                "warn",
                observed=Decimal("0.1730"),
                threshold=Decimal("0.1500"),
                observed_rows=320,
                detail={"k": "v"},
            ),
        ])
        row = json.loads(path.read_text("utf-8").strip())
        assert set(row.keys()) == {
            "run_id",
            "expectation",
            "severity",
            "observed",
            "threshold",
            "observed_rows",
            "detail_jsonb",
            "observed_at",
        }
        assert row["run_id"] == str(run_id)
        assert row["expectation"] == "reports.url_canonical.dedup_rate"
        assert row["severity"] == "warn"
        assert row["observed_rows"] == 320
        assert row["detail_jsonb"] == {"k": "v"}
        assert row["observed_at"] == _FIXED_TS.isoformat()

    async def test_overwrites_previous_run_output(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "run.jsonl"

        sink1 = JsonlSink(path, uuid.uuid4())
        await sink1.write([_result("first", "pass") for _ in range(3)])
        assert len(path.read_text("utf-8").splitlines()) == 3

        sink2 = JsonlSink(path, uuid.uuid4())
        await sink2.write([_result("second", "pass")])
        lines = path.read_text("utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["expectation"] == "second"

    async def test_detail_with_decimal_value(self, tmp_path: Path) -> None:
        path = tmp_path / "detail.jsonl"
        sink = JsonlSink(path, uuid.uuid4())
        await sink.write([
            _result(
                "x",
                "warn",
                detail={"observed_ratio": Decimal("0.25")},
            ),
        ])
        row = json.loads(path.read_text("utf-8").strip())
        assert row["detail_jsonb"]["observed_ratio"] == "0.25"


# ---------------------------------------------------------------------------
# StdoutSink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStdoutSink:
    async def test_empty_batch_still_prints_header_and_totals(self) -> None:
        stream = io.StringIO()
        sink = StdoutSink(stream)
        await sink.write([])
        output = stream.getvalue()
        assert "Data Quality Gate" in output
        assert "0 expectations" in output
        assert "Totals: 0 pass / 0 warn / 0 error" in output

    async def test_single_pass_result(self) -> None:
        stream = io.StringIO()
        sink = StdoutSink(stream)
        await sink.write([_result("reports.tlp.value_domain", "pass", observed_rows=0)])
        output = stream.getvalue()
        assert "PASS" in output
        assert "reports.tlp.value_domain" in output
        assert "0 rows" in output
        assert "Totals: 1 pass / 0 warn / 0 error" in output

    async def test_warn_renders_observed_and_threshold(self) -> None:
        stream = io.StringIO()
        sink = StdoutSink(stream)
        await sink.write([
            _result(
                "reports.url_canonical.dedup_rate",
                "warn",
                observed=Decimal("0.1730"),
                threshold=Decimal("0.1500"),
            ),
        ])
        output = stream.getvalue()
        assert "WARN" in output
        assert "0.1730" in output
        assert "threshold 0.1500" in output

    async def test_error_row_visible(self) -> None:
        stream = io.StringIO()
        sink = StdoutSink(stream)
        await sink.write([
            _result(
                "groups.canonical_name.forward_check",
                "error",
                observed_rows=2,
            ),
        ])
        output = stream.getvalue()
        assert "ERROR" in output
        assert "2 rows" in output
        assert "Totals: 0 pass / 0 warn / 1 error" in output

    async def test_mixed_batch_totals(self) -> None:
        stream = io.StringIO()
        sink = StdoutSink(stream)
        await sink.write(_sample_batch())
        output = stream.getvalue()
        # 7 pass / 3 warn / 1 error in _sample_batch()
        assert "Totals: 7 pass / 3 warn / 1 error" in output

    async def test_output_is_ascii_only(self) -> None:
        """Pins the cp949 guardrail — no non-ASCII characters
        must appear in stdout output. Same lesson as PR #6's
        ``decide_exit_code`` em-dash incident."""
        stream = io.StringIO()
        sink = StdoutSink(stream)
        await sink.write(_sample_batch())
        output = stream.getvalue()
        # All chars in the Basic Latin range (0x00-0x7F)
        assert all(ord(c) < 0x80 for c in output), (
            f"non-ASCII character detected: {[c for c in output if ord(c) >= 0x80]!r}"
        )

    async def test_ordering_preserved(self) -> None:
        stream = io.StringIO()
        sink = StdoutSink(stream)
        await sink.write([
            _result("first.check", "pass"),
            _result("second.check", "warn"),
            _result("third.check", "error", observed_rows=1),
        ])
        output = stream.getvalue()
        first_pos = output.index("first.check")
        second_pos = output.index("second.check")
        third_pos = output.index("third.check")
        assert first_pos < second_pos < third_pos
