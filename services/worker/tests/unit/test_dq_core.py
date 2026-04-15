"""Unit tests for worker.data_quality results + runner (PR #7 Group C).

Pins the four review points called out by the user for Group C:

  1. :class:`ExpectationResult` expresses exactly ``pass`` / ``warn``
     / ``error`` and rejects anything else at construction time.
  2. :class:`RunnerOutcome.worst_severity` maps the 11-item registry
     onto the D9 2-level model without introducing a third band.
  3. :func:`run_expectations` synthesizes an error result when a
     check function raises, preserving the expectation's stable
     name so downstream trend queries do not lose the row.
  4. :func:`run_expectations` distinguishes expectation failure from
     sink failure: a raising sink does NOT short-circuit the fan-out
     and the error is surfaced via :class:`SinkError`, not by
     re-raising.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from worker.data_quality.results import (
    Expectation,
    ExpectationResult,
    RunnerOutcome,
    Sink,
    SinkError,
)
from worker.data_quality.runner import run_expectations


# ---------------------------------------------------------------------------
# Helpers for constructing test fixtures
# ---------------------------------------------------------------------------


def _result(
    name: str = "test.expectation",
    severity: str = "pass",
    **kwargs,
) -> ExpectationResult:
    return ExpectationResult(name=name, severity=severity, **kwargs)


class _RecordingSink:
    """Sink that remembers every batch it receives."""

    name: str = "recording"

    def __init__(self) -> None:
        self.batches: list[list[ExpectationResult]] = []

    async def write(self, results: list[ExpectationResult]) -> None:
        self.batches.append(list(results))


class _FailingSink:
    """Sink that raises ``RuntimeError`` on every write."""

    name: str = "failing"

    def __init__(self, message: str = "sink down") -> None:
        self._message = message

    async def write(self, results: list[ExpectationResult]) -> None:
        raise RuntimeError(self._message)


# ---------------------------------------------------------------------------
# ExpectationResult validation
# ---------------------------------------------------------------------------


class TestExpectationResultValidation:
    def test_pass_warn_error_accepted(self) -> None:
        for severity in ("pass", "warn", "error"):
            result = _result(severity=severity)
            assert result.severity == severity

    @pytest.mark.parametrize(
        "bad_severity",
        ["info", "critical", "debug", "WARN", "ERROR", "Pass", "", "fatal"],
    )
    def test_rejects_severity_outside_closed_set(
        self, bad_severity: str
    ) -> None:
        with pytest.raises(ValueError, match="invalid severity"):
            _result(severity=bad_severity)

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            _result(name="")

    def test_rejects_naive_observed_at(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            _result(observed_at=dt.datetime(2026, 4, 15, 12, 0, 0))

    def test_default_observed_at_is_utc(self) -> None:
        result = _result()
        assert result.observed_at.tzinfo is not None
        assert result.observed_at.utcoffset() == dt.timedelta(0)

    def test_coerces_int_observed_to_decimal(self) -> None:
        result = _result(observed=42)
        assert isinstance(result.observed, Decimal)
        assert result.observed == Decimal("42")

    def test_coerces_float_observed_to_decimal_via_str(self) -> None:
        result = _result(observed=0.15)
        # Going through str() preserves the literal rather than
        # stringifying a binary-float tail.
        assert isinstance(result.observed, Decimal)
        assert result.observed == Decimal("0.15")

    def test_preserves_decimal_observed_unchanged(self) -> None:
        d = Decimal("0.1730")
        result = _result(observed=d)
        assert result.observed is d  # same instance

    def test_threshold_coercion_matches_observed(self) -> None:
        result = _result(observed=0.17, threshold=0.15)
        assert isinstance(result.threshold, Decimal)
        assert result.threshold == Decimal("0.15")

    def test_detail_defaults_to_empty_dict(self) -> None:
        result = _result()
        assert result.detail == {}

    def test_frozen_immutable(self) -> None:
        import dataclasses

        result = _result()
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.severity = "error"  # type: ignore[misc]


class TestExpectationValidation:
    def test_rejects_empty_name(self) -> None:
        async def _check(session: AsyncSession) -> ExpectationResult:
            return _result()

        with pytest.raises(ValueError, match="non-empty"):
            Expectation(name="", check=_check)

    def test_accepts_valid_binding(self) -> None:
        async def _check(session: AsyncSession) -> ExpectationResult:
            return _result(name="x.y.z")

        exp = Expectation(name="x.y.z", check=_check)
        assert exp.name == "x.y.z"


# ---------------------------------------------------------------------------
# Sink Protocol conformance
# ---------------------------------------------------------------------------


class TestSinkProtocolConformance:
    def test_recording_sink_is_sink(self) -> None:
        # runtime_checkable Protocol → isinstance works at runtime
        sink = _RecordingSink()
        assert isinstance(sink, Sink)
        assert sink.name == "recording"

    def test_failing_sink_is_sink(self) -> None:
        sink = _FailingSink()
        assert isinstance(sink, Sink)


# ---------------------------------------------------------------------------
# RunnerOutcome — worst_severity + had_sink_failure
# ---------------------------------------------------------------------------


class TestRunnerOutcome:
    def test_worst_severity_error_dominates(self) -> None:
        outcome = RunnerOutcome(
            results=[
                _result(severity="pass"),
                _result(severity="warn"),
                _result(severity="error"),
            ],
            sink_errors=[],
        )
        assert outcome.worst_severity == "error"

    def test_worst_severity_warn_when_no_error(self) -> None:
        outcome = RunnerOutcome(
            results=[
                _result(severity="pass"),
                _result(severity="warn"),
                _result(severity="pass"),
            ],
            sink_errors=[],
        )
        assert outcome.worst_severity == "warn"

    def test_worst_severity_pass_when_all_pass(self) -> None:
        outcome = RunnerOutcome(
            results=[
                _result(severity="pass"),
                _result(severity="pass"),
            ],
            sink_errors=[],
        )
        assert outcome.worst_severity == "pass"

    def test_worst_severity_pass_on_empty_results(self) -> None:
        outcome = RunnerOutcome(results=[], sink_errors=[])
        assert outcome.worst_severity == "pass"

    def test_had_sink_failure_reflects_sink_errors(self) -> None:
        outcome_ok = RunnerOutcome(results=[_result()], sink_errors=[])
        outcome_err = RunnerOutcome(
            results=[_result()],
            sink_errors=[SinkError(
                sink_name="db", error_type="OperationalError", error_message="boom",
            )],
        )
        assert outcome_ok.had_sink_failure is False
        assert outcome_err.had_sink_failure is True


# ---------------------------------------------------------------------------
# run_expectations — orchestration contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunExpectations:
    async def test_happy_path_runs_every_expectation_in_order(
        self, db_session: AsyncSession
    ) -> None:
        order: list[str] = []

        async def _check_a(session: AsyncSession) -> ExpectationResult:
            order.append("a")
            return _result(name="a.check", severity="pass")

        async def _check_b(session: AsyncSession) -> ExpectationResult:
            order.append("b")
            return _result(name="b.check", severity="warn", observed=0.17, threshold=0.15)

        async def _check_c(session: AsyncSession) -> ExpectationResult:
            order.append("c")
            return _result(name="c.check", severity="pass", observed_rows=0)

        expectations = [
            Expectation(name="a.check", check=_check_a),
            Expectation(name="b.check", check=_check_b),
            Expectation(name="c.check", check=_check_c),
        ]
        sink = _RecordingSink()

        outcome = await run_expectations(db_session, expectations, [sink])

        assert order == ["a", "b", "c"]
        assert [r.name for r in outcome.results] == ["a.check", "b.check", "c.check"]
        assert outcome.sink_errors == []
        assert outcome.worst_severity == "warn"

        # Sink saw the full batch once, in the same order.
        assert len(sink.batches) == 1
        assert [r.name for r in sink.batches[0]] == ["a.check", "b.check", "c.check"]

    async def test_expectation_raise_synthesizes_error_result(
        self, db_session: AsyncSession
    ) -> None:
        async def _good(session: AsyncSession) -> ExpectationResult:
            return _result(name="good", severity="pass")

        async def _bad(session: AsyncSession) -> ExpectationResult:
            raise RuntimeError("db table missing")

        expectations = [
            Expectation(name="good", check=_good),
            Expectation(name="bad", check=_bad),
        ]

        outcome = await run_expectations(db_session, expectations, [])

        assert len(outcome.results) == 2
        assert outcome.results[0].name == "good"
        assert outcome.results[0].severity == "pass"

        # Synthesized error result preserves the stable expectation
        # name (from the Expectation wrapper, not from the raising
        # function) so trend queries still have the right identifier.
        bad = outcome.results[1]
        assert bad.name == "bad"
        assert bad.severity == "error"
        assert bad.detail["internal_error"] is True
        assert bad.detail["error_type"] == "RuntimeError"
        assert bad.detail["error_message"] == "db table missing"

    async def test_expectation_failure_does_not_stop_the_loop(
        self, db_session: AsyncSession
    ) -> None:
        ran: list[str] = []

        async def _bad(session: AsyncSession) -> ExpectationResult:
            ran.append("bad")
            raise ValueError("whatever")

        async def _after(session: AsyncSession) -> ExpectationResult:
            ran.append("after")
            return _result(name="after", severity="pass")

        outcome = await run_expectations(
            db_session,
            [
                Expectation(name="bad", check=_bad),
                Expectation(name="after", check=_after),
            ],
            [],
        )

        assert ran == ["bad", "after"]
        assert outcome.results[0].severity == "error"
        assert outcome.results[1].severity == "pass"

    async def test_sink_failure_is_captured_as_sink_error(
        self, db_session: AsyncSession
    ) -> None:
        async def _good(session: AsyncSession) -> ExpectationResult:
            return _result(name="good", severity="pass")

        recording = _RecordingSink()
        failing = _FailingSink(message="db connection lost")

        # Put the failing sink in the middle so we can verify both
        # (a) the sink before it ran, and (b) the sink after it also
        # ran — failure does NOT short-circuit fan-out.
        second_recording = _RecordingSink()
        second_recording.name = "recording2"

        outcome = await run_expectations(
            db_session,
            [Expectation(name="good", check=_good)],
            [recording, failing, second_recording],
        )

        # Both recording sinks received the batch.
        assert len(recording.batches) == 1
        assert len(second_recording.batches) == 1

        # And the failing sink's error was captured.
        assert len(outcome.sink_errors) == 1
        err = outcome.sink_errors[0]
        assert err.sink_name == "failing"
        assert err.error_type == "RuntimeError"
        assert err.error_message == "db connection lost"

        # The results list itself was not affected by the sink
        # failure — it still contains the check result.
        assert outcome.results[0].name == "good"
        assert outcome.results[0].severity == "pass"
        assert outcome.had_sink_failure is True
        assert outcome.worst_severity == "pass"

    async def test_expectation_failure_and_sink_failure_are_independent(
        self, db_session: AsyncSession
    ) -> None:
        """A check that raises becomes an error-severity result. A
        sink that raises becomes a SinkError. The two error types
        coexist without conflating."""

        async def _bad_check(session: AsyncSession) -> ExpectationResult:
            raise RuntimeError("check failed")

        outcome = await run_expectations(
            db_session,
            [Expectation(name="broken", check=_bad_check)],
            [_FailingSink()],
        )

        assert len(outcome.results) == 1
        assert outcome.results[0].severity == "error"
        assert outcome.results[0].detail["internal_error"] is True

        assert len(outcome.sink_errors) == 1
        assert outcome.sink_errors[0].sink_name == "failing"

    async def test_empty_expectations_still_fans_out_to_sinks(
        self, db_session: AsyncSession
    ) -> None:
        sink = _RecordingSink()
        outcome = await run_expectations(db_session, [], [sink])
        assert outcome.results == []
        assert len(sink.batches) == 1
        assert sink.batches[0] == []
        assert outcome.worst_severity == "pass"

    async def test_no_sinks_still_returns_results(
        self, db_session: AsyncSession
    ) -> None:
        async def _check(session: AsyncSession) -> ExpectationResult:
            return _result(name="only", severity="warn")

        outcome = await run_expectations(
            db_session,
            [Expectation(name="only", check=_check)],
            [],
        )
        assert len(outcome.results) == 1
        assert outcome.results[0].severity == "warn"
        assert outcome.sink_errors == []
        assert outcome.worst_severity == "warn"
