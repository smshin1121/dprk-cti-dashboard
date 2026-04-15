"""Data-quality gate runtime (PR #7 Group C).

Public surface:
  - :class:`ExpectationResult` — frozen dataclass returned by every
    expectation function. Carries the severity outcome, observed
    metric, threshold, the violating/affected row count, and a
    detail payload with the full scan context.
  - :class:`Expectation` — binding of an expectation name to its
    check function. The runner iterates over these and treats the
    name as the stable identifier across DB sink, JSONL sink, and
    error synthesis.
  - :class:`Sink` — Protocol every sink satisfies. Three concrete
    sinks live under ``worker.data_quality.sinks``.
  - :func:`run_expectations` — orchestrator that executes a list of
    expectations against an :class:`AsyncSession`, synthesises
    failure results when a check function raises, and fans the
    results out to every configured sink without letting a sink
    failure abort the whole run.

Expectation function bodies (null-rate, value-domain, year-range,
referential-integrity, dedup-rate) live in
``worker.data_quality.expectations`` — landed in Group D.
"""

from worker.data_quality.results import (
    Expectation,
    ExpectationCheck,
    ExpectationResult,
    RunnerOutcome,
    Severity,
    Sink,
    SinkError,
)
from worker.data_quality.runner import run_expectations


__all__ = [
    "Expectation",
    "ExpectationCheck",
    "ExpectationResult",
    "RunnerOutcome",
    "Severity",
    "Sink",
    "SinkError",
    "run_expectations",
]
