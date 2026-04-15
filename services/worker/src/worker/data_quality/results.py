"""Type definitions for the data-quality gate runtime.

This module defines the common vocabulary every part of the DQ
system speaks in:

  - :data:`Severity` — the closed set of outcome levels. Enforces the
    D9 2-level severity model (``warn`` / ``error``) **plus** the
    ``pass`` outcome row (per D5, which allows pass rows in
    ``dq_events`` for trend baselines without treating pass as a
    severity band).
  - :class:`ExpectationResult` — frozen dataclass returned by every
    expectation function. Every sink (DB, JSONL, stdout) reads from
    the same instance so the DB row and the JSONL mirror are
    guaranteed semantically identical.
  - :class:`Expectation` — binding of a stable expectation name to
    its check function. The runner uses ``name`` for error
    synthesis when the check raises.
  - :class:`Sink` — Protocol every sink implements. Async-only so
    DB sinks and stdout sinks can be fanned out through the same
    code path.
  - :class:`SinkError` — returned (not raised) by the runner when a
    sink's ``write`` raised. The runner continues to the next sink
    on failure so a broken DB connection does not prevent the JSONL
    mirror from being written.
  - :class:`RunnerOutcome` — what :func:`run_expectations` returns.
    Carries the results list, the sink errors list, and a convenience
    ``worst_severity`` accessor for CLI exit-code decisions.

See docs/plans/pr7-data-quality.md D5 / D6 / D9 for the contract
this module commits to.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    Protocol,
    runtime_checkable,
)

from sqlalchemy.ext.asyncio import AsyncSession


__all__ = [
    "Expectation",
    "ExpectationCheck",
    "ExpectationResult",
    "RunnerOutcome",
    "Severity",
    "Sink",
    "SinkError",
]


#: Closed set of expectation outcome levels. ``pass`` represents
#: "expectation ran and found nothing above the warn threshold" and is
#: persisted to ``dq_events`` so the "DQ pass rate" KPI (§15) can be
#: computed from presence rather than inferred from absence. ``warn``
#: and ``error`` are the two severity bands D9 locks — no third band
#: is permitted, and extending this Literal is a load-bearing change
#: that should force a new decision ID.
Severity = Literal["pass", "warn", "error"]

_VALID_SEVERITIES: frozenset[str] = frozenset({"pass", "warn", "error"})


def _utc_now() -> dt.datetime:
    """Return an immediate UTC timestamp for :class:`ExpectationResult`.

    Kept as a module-level helper so tests can patch it when they need
    deterministic ``observed_at`` values without reaching into the
    dataclass internals.
    """
    return dt.datetime.now(dt.timezone.utc)


@dataclasses.dataclass(frozen=True, slots=True)
class ExpectationResult:
    """The outcome of running a single expectation against the DB.

    ``name`` is the stable dotted-identifier for the expectation (e.g.
    ``"reports.tlp.value_domain"``) and is what downstream trend
    queries group by. It MUST match the ``name`` of the
    :class:`Expectation` wrapper — the runner verifies this on the
    error-synthesis path.

    ``observed`` and ``threshold`` are both :class:`decimal.Decimal` so
    ratio-based expectations (dedup rate, null rate) stay exact
    instead of going through float and accumulating drift. ``int`` and
    ``float`` literals coming from the check functions are coerced by
    ``__post_init__`` so callers do not need to remember to wrap
    primitive literals.

    ``observed_rows`` is an optional row count the expectation scanned,
    useful for dashboards that want "out of N rows, M violated".

    ``detail`` is a free-form JSON-serializable dict for expectation-
    specific context (which rows failed, which canonical was missing,
    what the allowed enum set was, etc.). Both the DB sink and the
    JSONL sink pass this dict through unchanged — if it contains
    non-JSON types, the sink will raise and the runner will record a
    :class:`SinkError`.

    ``observed_at`` is generated at construction time (or supplied
    explicitly by tests / replay code) and is used verbatim by every
    sink so a DB row and its JSONL mirror carry the identical
    timestamp. Must be timezone-aware.
    """

    name: str
    severity: Severity
    observed: Decimal | None = None
    threshold: Decimal | None = None
    observed_rows: int | None = None
    detail: dict[str, Any] = dataclasses.field(default_factory=dict)
    observed_at: dt.datetime = dataclasses.field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"invalid severity {self.severity!r}; must be one of "
                f"{sorted(_VALID_SEVERITIES)}"
            )
        if not self.name:
            raise ValueError("ExpectationResult.name must be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError(
                "ExpectationResult.observed_at must be timezone-aware"
            )
        # Coerce numeric primitives to Decimal so ratio math stays
        # exact. Frozen dataclasses forbid direct attribute assignment,
        # so we go through object.__setattr__ once during __post_init__.
        if self.observed is not None and not isinstance(self.observed, Decimal):
            object.__setattr__(self, "observed", Decimal(str(self.observed)))
        if self.threshold is not None and not isinstance(self.threshold, Decimal):
            object.__setattr__(self, "threshold", Decimal(str(self.threshold)))


#: Signature of every expectation check function. Takes an open
#: :class:`AsyncSession` (read-only queries against the populated
#: bootstrap schema) and returns a single :class:`ExpectationResult`.
ExpectationCheck = Callable[[AsyncSession], Awaitable[ExpectationResult]]


@dataclasses.dataclass(frozen=True, slots=True)
class Expectation:
    """Binding of an expectation name to its check function.

    The runner uses ``name`` to synthesize an error result when
    ``check`` raises, so the stable identifier survives even when the
    check function itself fails to build a result. The check
    function's returned result should carry the identical ``name`` —
    Group D includes a lint test that verifies this invariant across
    every shipped expectation.
    """

    name: str
    check: ExpectationCheck

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Expectation.name must be non-empty")


# ---------------------------------------------------------------------------
# Sink Protocol + error record
# ---------------------------------------------------------------------------


@runtime_checkable
class Sink(Protocol):
    """Common interface every sink implements.

    The ``name`` class attribute is used by the runner for error
    reporting when a sink's ``write`` raises. Every concrete sink in
    ``worker.data_quality.sinks`` sets this to a stable short name
    (``"stdout"``, ``"db"``, ``"jsonl"``).

    ``write`` is async because the DB sink needs to issue INSERTs
    through an :class:`AsyncSession`. The stdout and JSONL sinks are
    trivially async (nothing to await inside them) but conform to the
    same shape so the runner's fan-out loop is uniform.
    """

    name: str

    async def write(self, results: list[ExpectationResult]) -> None:
        ...


@dataclasses.dataclass(frozen=True, slots=True)
class SinkError:
    """Captured sink failure.

    The runner creates one of these when a sink's ``write`` raises,
    then keeps going with the remaining sinks so a broken DB
    connection cannot prevent the JSONL mirror from being written.
    The caller of :func:`run_expectations` inspects
    ``RunnerOutcome.sink_errors`` to decide whether to surface a
    non-zero CLI exit code.
    """

    sink_name: str
    error_type: str
    error_message: str


# ---------------------------------------------------------------------------
# RunnerOutcome
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class RunnerOutcome:
    """Return value of :func:`run_expectations`.

    ``results`` contains one :class:`ExpectationResult` per configured
    expectation. If a check function raised, the runner synthesizes
    an error-severity result with the exception detail in ``detail``
    so the failure is visible in all sinks.

    ``sink_errors`` contains one :class:`SinkError` per sink that
    raised while writing the results batch. An empty list means every
    sink succeeded. Sink failures do NOT affect ``results`` — the
    fan-out is best-effort.

    ``worst_severity`` returns the "highest" severity across all
    results, using the ordering ``pass`` < ``warn`` < ``error``. This
    is the value the CLI consults when deciding its exit code under
    ``--fail-on error`` (default) or ``--fail-on warn``.
    """

    results: list[ExpectationResult]
    sink_errors: list[SinkError]

    @property
    def worst_severity(self) -> Severity:
        """Return the most severe result severity (pass if empty)."""
        if any(r.severity == "error" for r in self.results):
            return "error"
        if any(r.severity == "warn" for r in self.results):
            return "warn"
        return "pass"

    @property
    def had_sink_failure(self) -> bool:
        """True if at least one sink raised during fan-out."""
        return bool(self.sink_errors)
