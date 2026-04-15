"""DB sink — writes results into ``dq_events`` via SQLAlchemy Core.

This sink is the authoritative persistence path for the data-quality
trend store. Every :class:`ExpectationResult` is mapped 1:1 onto a
``dq_events`` row following the D5 schema defined in migration
0005. Batched INSERT via ``execute_many`` keeps the round-trip cost
flat regardless of expectation count.

D5 column mapping:

    id            ← auto-assigned (BIGSERIAL)
    run_id        ← supplied at sink construction (shared across batch)
    expectation   ← ExpectationResult.name
    severity      ← ExpectationResult.severity
    observed      ← ExpectationResult.observed (Decimal | None)
    threshold     ← ExpectationResult.threshold (Decimal | None)
    observed_rows ← ExpectationResult.observed_rows (int | None)
    detail_jsonb  ← ExpectationResult.detail (dict)
    observed_at   ← ExpectationResult.observed_at (UTC datetime)

The ``run_id`` is supplied to the sink constructor, not pulled from
the result, because every result in a single run shares the same
run_id and threading it through every result would be noisy.

The sink uses :class:`AsyncSession` (not a bare connection) for
consistency with the rest of the worker: PR #5/#6 upsert, PR #7
audit. The caller owns the transaction boundary — this sink only
issues INSERT statements.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from worker.bootstrap.tables import dq_events_table
from worker.data_quality.results import ExpectationResult


__all__ = ["DbSink"]


class DbSink:
    """Persist expectation results to ``dq_events``.

    Instantiate once per run with the run's ``uuid7`` identifier, then
    pass to :func:`worker.data_quality.runner.run_expectations` as one
    of the sinks. The sink does NOT generate its own ``run_id`` — the
    caller (CLI) creates it once, for the same reason the bootstrap
    audit meta is generated once at CLI entry: a single logical
    invocation must carry a single ``run_id`` across every persisted
    artifact.
    """

    name: str = "db"

    def __init__(self, session: AsyncSession, run_id: uuid.UUID) -> None:
        self._session = session
        self._run_id = run_id

    async def write(self, results: list[ExpectationResult]) -> None:
        """INSERT one ``dq_events`` row per result via ``execute_many``.

        Empty ``results`` is a no-op (no INSERT issued). Runs inside
        the caller's transaction — the sink never opens or commits
        one itself.

        Numeric columns accept ``Decimal`` directly because SQLAlchemy
        NUMERIC coerces both ``int`` and ``Decimal`` without loss.
        ``observed_at`` is passed explicitly so the DB row shares the
        exact timestamp with the JSONL mirror (see D5 rationale: both
        sinks read ``observed_at`` from the same ExpectationResult
        instance).
        """
        if not results:
            return

        rows = [
            {
                "run_id": self._run_id,
                "expectation": r.name,
                "severity": r.severity,
                "observed": r.observed,
                "threshold": r.threshold,
                "observed_rows": r.observed_rows,
                "detail_jsonb": dict(r.detail),
                "observed_at": r.observed_at,
            }
            for r in results
        ]

        await self._session.execute(sa.insert(dq_events_table), rows)
