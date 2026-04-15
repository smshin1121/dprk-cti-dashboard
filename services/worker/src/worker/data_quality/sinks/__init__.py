"""Sink implementations for the data-quality runner.

Three concrete sinks ship in PR #7 Group C:

  - :class:`StdoutSink` — ASCII summary table printed after every
    run. Human-facing, no persistence, cp949-safe output.
  - :class:`DbSink` — inserts rows into the ``dq_events`` table
    (migration 0005). The authoritative trend store.
  - :class:`JsonlSink` — writes one JSON object per line to a file.
    Used as a portable mirror of the DB rows so CI artifacts carry
    the full run outcome even when Postgres is not available.

All three conform to the :class:`worker.data_quality.results.Sink`
Protocol and are fanned out in order by
:func:`worker.data_quality.runner.run_expectations`.
"""

from worker.data_quality.sinks.db import DbSink
from worker.data_quality.sinks.jsonl import JsonlSink
from worker.data_quality.sinks.stdout import StdoutSink


__all__ = ["DbSink", "JsonlSink", "StdoutSink"]
