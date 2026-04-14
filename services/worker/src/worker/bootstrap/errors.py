"""Dead-letter writer and exit-code policy for the Bootstrap ETL CLI.

Two independent concerns, co-located because they are both triggered
by the same event (a row failed to ingest):

1. **DeadLetterWriter** — lazily opens a JSONL file at the configured
   path and appends one line per failed row. The file is deliberately
   **not created** when there are zero failures, so an operator
   seeing the file on disk knows unconditionally that something went
   wrong.

2. **decide_exit_code** — pure function that turns a ``(total,
   failures)`` counter pair into the exit-code tuple mandated by D5
   in ``docs/plans/pr5-bootstrap-etl.md``:

     - failures == 0                  -> (0, "clean")
     - 0 < failures, rate <= 5%       -> (0, "warning")
     - rate > 5%                      -> (2, "exceeded")

   The summary string is suitable to print to stdout; the exit code
   is returned to ``sys.exit``.

Both types are pure Python with no SQLAlchemy or openpyxl imports so
they can be unit-tested without the full bootstrap context.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Any


__all__ = [
    "DEAD_LETTER_WARNING_RATE",
    "DeadLetterEntry",
    "DeadLetterWriter",
    "ExitCode",
    "ExitDecision",
    "decide_exit_code",
]


# D5 5% threshold from the plan. Kept as a module constant so tests
# and the CLI --help string agree on the exact number.
DEAD_LETTER_WARNING_RATE: float = 0.05


# Exit codes. 0 and 2 are the only values the CLI emits; 1 is
# reserved for argparse / unexpected CLI-layer failures.
class ExitCode:
    OK = 0
    THRESHOLD_EXCEEDED = 2


@dataclass(frozen=True)
class DeadLetterEntry:
    """One row that failed to ingest.

    Fields match what the reviewer requested in the PR #6 brief:
    enough context to reproduce the failure from the committed
    fixture or an external workbook.
    """

    sheet: str
    row_index: int
    raw_payload: dict[str, Any]
    error_class: str
    message: str


def _json_default(obj: object) -> object:
    """Serializer fallback for JSON-unfriendly types in ``raw_payload``.

    openpyxl hands back ``datetime.datetime`` / ``datetime.date`` for
    date cells, and pydantic's validation errors may carry arbitrary
    objects in their ``.errors()`` payload. Turning them into strings
    keeps the JSONL valid without leaking repr artifacts.
    """
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    return str(obj)


class DeadLetterWriter:
    """Append-only JSONL writer that defers file creation until the
    first entry is written.

    ``path=None`` turns the writer into a silent no-op so callers
    that never configured a dead-letter path can still invoke
    :meth:`write` unconditionally.

    Use as a context manager to guarantee the file handle is closed
    even if the pipeline raises::

        with DeadLetterWriter(Path("artifacts/bootstrap_errors.jsonl")) as dl:
            for row in loader.iter_all():
                try:
                    ...
                except Exception as exc:
                    dl.write(DeadLetterEntry(...))
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._handle = None  # lazy — see write()
        self._written = 0

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def count(self) -> int:
        return self._written

    @property
    def file_created(self) -> bool:
        """True once the first entry has been written and the file
        exists on disk. ``False`` for a zero-failure run."""
        return self._handle is not None or (
            self._path is not None and self._path.exists() and self._written > 0
        )

    def write(self, entry: DeadLetterEntry) -> None:
        """Serialize and append a single failure."""
        if self._path is None:
            self._written += 1
            return
        if self._handle is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("w", encoding="utf-8")
        line = json.dumps(asdict(entry), default=_json_default, ensure_ascii=False)
        self._handle.write(line + "\n")
        self._written += 1

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "DeadLetterWriter":
        # Clear any stale artifact from a previous run at the same
        # path. Without this, a clean run that follows a failing run
        # would leave the old JSONL in place and operators would
        # falsely conclude that the current run had failures. The
        # contract is "file exists iff *this* run had failures".
        if self._path is not None and self._path.exists():
            self._path.unlink()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


@dataclass(frozen=True)
class ExitDecision:
    """Result of :func:`decide_exit_code`."""

    code: int
    total: int
    failures: int
    failure_rate: float
    summary: str


def decide_exit_code(
    total: int,
    failures: int,
    *,
    warning_rate: float = DEAD_LETTER_WARNING_RATE,
) -> ExitDecision:
    """Apply the D5 three-branch exit-code policy.

    Branches:
      1. ``failures == 0`` — exit 0, "clean" summary.
      2. ``0 < failures / total <= warning_rate`` — exit 0, "warning"
         summary that the operator should still notice.
      3. ``failures / total > warning_rate`` — exit 2, "exceeded"
         summary that trips CI.

    Edge cases:
      - ``total == 0`` with ``failures == 0``: exit 0, "clean".
      - ``total == 0`` with ``failures > 0``: treat rate as 100% →
        exit 2. In practice this should never happen because a row
        that failed was still counted toward ``total`` in the CLI
        accumulator, but we still want a well-defined result.
    """
    if failures < 0 or total < 0:
        raise ValueError("total and failures must be non-negative")
    if total > 0 and failures > total:
        raise ValueError(
            f"failures ({failures}) cannot exceed total rows ({total})"
        )

    if failures == 0:
        return ExitDecision(
            code=ExitCode.OK,
            total=total,
            failures=0,
            failure_rate=0.0,
            summary=f"{total} rows processed, 0 failures",
        )

    if total == 0:
        # Well-defined answer for a hypothetically-reachable state.
        return ExitDecision(
            code=ExitCode.THRESHOLD_EXCEEDED,
            total=0,
            failures=failures,
            failure_rate=1.0,
            summary=f"0 rows processed, {failures} failures — no rows counted",
        )

    rate = failures / total
    if rate <= warning_rate:
        return ExitDecision(
            code=ExitCode.OK,
            total=total,
            failures=failures,
            failure_rate=rate,
            summary=(
                f"{total} rows processed, {failures} failures "
                f"({rate:.2%}) — within {warning_rate:.0%} tolerance"
            ),
        )

    return ExitDecision(
        code=ExitCode.THRESHOLD_EXCEEDED,
        total=total,
        failures=failures,
        failure_rate=rate,
        summary=(
            f"{total} rows processed, {failures} failures "
            f"({rate:.2%}) — exceeds {warning_rate:.0%} threshold"
        ),
    )
