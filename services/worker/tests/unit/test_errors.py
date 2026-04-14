"""Tests for worker.bootstrap.errors — exit-code policy + dead-letter JSONL."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from worker.bootstrap.errors import (
    DEAD_LETTER_WARNING_RATE,
    DeadLetterEntry,
    DeadLetterWriter,
    ExitCode,
    decide_exit_code,
)


# ---------------------------------------------------------------------------
# decide_exit_code — the D5 three-branch policy
# ---------------------------------------------------------------------------


def test_decide_zero_failures_is_clean_exit() -> None:
    decision = decide_exit_code(total=100, failures=0)
    assert decision.code == ExitCode.OK
    assert decision.failures == 0
    assert decision.failure_rate == 0.0
    assert "0 failures" in decision.summary


def test_decide_below_warning_rate_is_warning_exit_zero() -> None:
    """4.76% is below the 5% threshold -> exit 0 with warning
    summary. The warning phrasing must be distinguishable from the
    clean case so operators notice it."""
    decision = decide_exit_code(total=21, failures=1)
    assert decision.code == ExitCode.OK
    assert decision.failures == 1
    assert decision.failure_rate == pytest.approx(1 / 21)
    assert "tolerance" in decision.summary
    assert "1 failures" in decision.summary


def test_decide_exactly_at_warning_rate_is_exit_zero() -> None:
    """5.00% exactly is <= threshold -> exit 0 with warning."""
    decision = decide_exit_code(total=20, failures=1)
    assert decision.code == ExitCode.OK
    assert decision.failure_rate == pytest.approx(0.05)
    assert "tolerance" in decision.summary


def test_decide_above_warning_rate_is_non_zero_exit() -> None:
    """6 of 100 is 6.00% > 5% -> exit 2."""
    decision = decide_exit_code(total=100, failures=6)
    assert decision.code == ExitCode.THRESHOLD_EXCEEDED
    assert decision.failures == 6
    assert decision.failure_rate == pytest.approx(0.06)
    assert "exceeds" in decision.summary


def test_decide_fixture_stress_case() -> None:
    """The real fixture has 32 rows, 6 of which are failure_case.
    6/32 = 18.75%, well above the 5% threshold — this is exactly
    what the fail-loud gate should trip on."""
    decision = decide_exit_code(total=32, failures=6)
    assert decision.code == ExitCode.THRESHOLD_EXCEEDED
    assert decision.failure_rate == pytest.approx(6 / 32)


def test_decide_zero_total_zero_failures_is_clean() -> None:
    decision = decide_exit_code(total=0, failures=0)
    assert decision.code == ExitCode.OK
    assert decision.failure_rate == 0.0


def test_decide_zero_total_with_failures_is_non_zero() -> None:
    """Defensive branch for an impossible-but-well-defined state.
    The CLI should never land here because a row counted as a
    failure is also counted toward total, but the function still
    needs a correct answer."""
    decision = decide_exit_code(total=0, failures=1)
    assert decision.code == ExitCode.THRESHOLD_EXCEEDED
    assert decision.failure_rate == 1.0


def test_decide_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        decide_exit_code(total=-1, failures=0)
    with pytest.raises(ValueError):
        decide_exit_code(total=10, failures=-1)


def test_decide_rejects_failures_greater_than_total() -> None:
    with pytest.raises(ValueError):
        decide_exit_code(total=5, failures=10)


def test_decide_custom_warning_rate_override() -> None:
    # Stricter gate: any failure at all trips non-zero.
    decision = decide_exit_code(total=100, failures=1, warning_rate=0.0)
    assert decision.code == ExitCode.THRESHOLD_EXCEEDED


def test_warning_rate_constant_is_five_percent() -> None:
    """Guard against accidental drift of the plan-locked threshold."""
    assert DEAD_LETTER_WARNING_RATE == 0.05


# ---------------------------------------------------------------------------
# DeadLetterWriter — lazy file creation + JSONL format
# ---------------------------------------------------------------------------


def _entry(
    sheet: str = "Reports",
    row_index: int = 1,
    raw_payload: dict | None = None,
    error_class: str = "RowValidationError",
    message: str = "title must be non-empty",
) -> DeadLetterEntry:
    return DeadLetterEntry(
        sheet=sheet,
        row_index=row_index,
        raw_payload=raw_payload
        or {
            "published": dt.date(2024, 3, 15),
            "title": "",
            "url": "https://example.com/x",
        },
        error_class=error_class,
        message=message,
    )


def test_writer_with_none_path_is_noop(tmp_path: Path) -> None:
    """``path=None`` -> writer is a silent sink. Caller can still
    track the count."""
    with DeadLetterWriter(None) as dl:
        dl.write(_entry())
        dl.write(_entry(row_index=2))
    assert dl.count == 2
    assert list(tmp_path.iterdir()) == []


def test_writer_does_not_create_file_on_zero_writes(tmp_path: Path) -> None:
    """The plan requires that an operator finding the file on disk
    knows unconditionally that something failed. So a zero-failure
    run must not create the file."""
    target = tmp_path / "nested" / "bootstrap_errors.jsonl"
    with DeadLetterWriter(target) as dl:
        pass
    assert not target.exists()
    assert dl.count == 0


def test_writer_creates_file_on_first_write(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "bootstrap_errors.jsonl"
    with DeadLetterWriter(target) as dl:
        dl.write(_entry())
    assert target.exists()
    assert dl.count == 1


def test_writer_appends_one_json_per_line(tmp_path: Path) -> None:
    target = tmp_path / "bootstrap_errors.jsonl"
    with DeadLetterWriter(target) as dl:
        dl.write(_entry(row_index=1, message="first"))
        dl.write(_entry(row_index=2, message="second"))
        dl.write(_entry(row_index=3, message="third"))
    assert dl.count == 3

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [p["row_index"] for p in parsed] == [1, 2, 3]
    assert [p["message"] for p in parsed] == ["first", "second", "third"]


def test_writer_captures_all_required_fields(tmp_path: Path) -> None:
    """Reviewer brief: row index, sheet, raw payload, error class,
    message must all be in every dead-letter entry."""
    target = tmp_path / "bootstrap_errors.jsonl"
    with DeadLetterWriter(target) as dl:
        dl.write(
            DeadLetterEntry(
                sheet="Reports",
                row_index=7,
                raw_payload={"title": "", "url": "https://example.com/x"},
                error_class="RowValidationError",
                message="title must be non-empty",
            )
        )
    parsed = json.loads(target.read_text(encoding="utf-8").strip())
    assert set(parsed.keys()) == {
        "sheet",
        "row_index",
        "raw_payload",
        "error_class",
        "message",
    }
    assert parsed["sheet"] == "Reports"
    assert parsed["row_index"] == 7
    assert parsed["raw_payload"] == {"title": "", "url": "https://example.com/x"}
    assert parsed["error_class"] == "RowValidationError"
    assert parsed["message"] == "title must be non-empty"


def test_writer_serializes_date_in_raw_payload(tmp_path: Path) -> None:
    """openpyxl hands back datetime.date / datetime.datetime for
    date cells. Those must serialize cleanly, not crash the JSON
    encoder or leak a repr artifact."""
    target = tmp_path / "bootstrap_errors.jsonl"
    payload = {
        "published": dt.date(2024, 3, 15),
        "last_seen": dt.datetime(2025, 12, 15, 0, 0),
        "title": "x",
    }
    with DeadLetterWriter(target) as dl:
        dl.write(
            DeadLetterEntry(
                sheet="Reports",
                row_index=1,
                raw_payload=payload,
                error_class="RowValidationError",
                message="irrelevant",
            )
        )
    parsed = json.loads(target.read_text(encoding="utf-8").strip())
    assert parsed["raw_payload"]["published"] == "2024-03-15"
    assert parsed["raw_payload"]["last_seen"].startswith("2025-12-15")


def test_writer_creates_parent_directories(tmp_path: Path) -> None:
    """``artifacts/bootstrap_errors.jsonl`` may point into a
    directory that does not exist yet."""
    target = tmp_path / "a" / "b" / "c" / "errors.jsonl"
    with DeadLetterWriter(target) as dl:
        dl.write(_entry())
    assert target.exists()


def test_writer_close_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "errors.jsonl"
    writer = DeadLetterWriter(target)
    writer.write(_entry())
    writer.close()
    writer.close()  # second close must not raise
    assert target.exists()


def test_writer_enter_clears_stale_file_from_prior_run(tmp_path: Path) -> None:
    """Contract: the dead-letter file exists iff *this* run had
    failures. If a previous run left a file at the same path, a
    subsequent clean run must delete it on entry so the file's
    existence still means "failures happened"."""
    target = tmp_path / "errors.jsonl"
    target.write_text("stale-content-from-previous-run\n", encoding="utf-8")
    assert target.exists()

    with DeadLetterWriter(target) as dl:
        # Clean run — no writes.
        pass

    assert not target.exists()
    assert dl.count == 0


def test_writer_enter_keeps_file_when_run_writes_fresh_failures(tmp_path: Path) -> None:
    """The stale-file cleanup must not eat legitimate failures from
    the current run."""
    target = tmp_path / "errors.jsonl"
    target.write_text("stale\n", encoding="utf-8")

    with DeadLetterWriter(target) as dl:
        dl.write(_entry(message="fresh failure"))

    assert target.exists()
    contents = target.read_text(encoding="utf-8")
    assert "stale" not in contents
    assert "fresh failure" in contents


def test_writer_enter_is_idempotent_for_missing_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "errors.jsonl"
    with DeadLetterWriter(target) as dl:
        pass
    assert not target.exists()


def test_writer_context_manager_closes_on_exception(tmp_path: Path) -> None:
    target = tmp_path / "errors.jsonl"
    with pytest.raises(RuntimeError):
        with DeadLetterWriter(target) as dl:
            dl.write(_entry())
            raise RuntimeError("upstream blew up")
    # File was still written and closed.
    assert target.exists()
    assert target.read_text(encoding="utf-8").strip() != ""
