"""Expectation runner — executes every check and fans results to sinks.

The runner's job is narrow and well-defined:

  1. Iterate over the configured :class:`Expectation` list, calling
     each check function with an :class:`AsyncSession`. Successful
     checks return an :class:`ExpectationResult`; failing checks are
     caught and converted to a synthetic ``severity="error"`` result
     so the DQ suite never crashes midway through.
  2. Fan the result list out to every configured :class:`Sink`. If
     a sink raises, capture a :class:`SinkError` and continue with
     the next sink — a broken DB connection must not prevent the
     JSONL mirror from being written.
  3. Return a :class:`RunnerOutcome` so the caller can inspect the
     results, the sink errors, and the worst severity to drive an
     exit-code decision.

This module is intentionally ignorant of where expectations come
from (Group D supplies them), what ``run_id`` they belong to (the
caller generates it), and which sinks persist them (the caller
configures them). That keeps the runner's test surface tight and
its responsibilities obvious.

See docs/plans/pr7-data-quality.md D6 / D9 for the contract.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from worker.data_quality.results import (
    Expectation,
    ExpectationResult,
    RunnerOutcome,
    Sink,
    SinkError,
)


__all__ = ["run_expectations"]


async def run_expectations(
    session: AsyncSession,
    expectations: list[Expectation],
    sinks: list[Sink],
) -> RunnerOutcome:
    """Run every expectation, then fan the results out to every sink.

    Args:
      session: Open :class:`AsyncSession` pointed at the DB the
        expectations should query. The session is used for reads
        only; expectations must not mutate state.
      expectations: Ordered list of :class:`Expectation` bindings.
        Results in the returned :class:`RunnerOutcome` preserve this
        order so stdout summaries are reproducible.
      sinks: Ordered list of :class:`Sink` instances. Each sink sees
        the full results list once. A sink raising does NOT short-
        circuit the remaining sinks — the runner captures the error
        and continues.

    Returns:
      :class:`RunnerOutcome` carrying ``results`` (one per
      expectation, in order) and ``sink_errors`` (one per failed
      sink write, empty when all sinks succeed).

    Error semantics:
      - Expectation check raises → synthesized
        :class:`ExpectationResult` with ``severity="error"`` and
        ``detail`` populated with ``{"internal_error": True,
        "error_type": ..., "error_message": ...}``. The runner uses
        the :class:`Expectation.name` so the error row still has the
        correct stable identifier for trend queries.
      - Sink write raises → :class:`SinkError` appended to
        ``sink_errors``. Runner continues to the next sink. The
        caller decides whether sink failures should produce a
        non-zero CLI exit.
    """
    results: list[ExpectationResult] = []
    for expectation in expectations:
        try:
            result = await expectation.check(session)
        except Exception as exc:
            result = ExpectationResult(
                name=expectation.name,
                severity="error",
                detail={
                    "internal_error": True,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1024],
                },
            )
        results.append(result)

    sink_errors: list[SinkError] = []
    for sink in sinks:
        try:
            await sink.write(results)
        except Exception as exc:
            sink_errors.append(SinkError(
                sink_name=getattr(sink, "name", type(sink).__name__),
                error_type=type(exc).__name__,
                error_message=str(exc)[:1024],
            ))

    return RunnerOutcome(results=results, sink_errors=sink_errors)
