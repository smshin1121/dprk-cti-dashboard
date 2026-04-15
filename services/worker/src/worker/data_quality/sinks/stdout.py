"""Stdout summary sink — ASCII table printed after every DQ run.

Output format (example):

    Data Quality Gate - 11 expectations
    ------------------------------------------------------------
      PASS   reports.tlp.value_domain                         0
      PASS   sources.country.iso2_conformance                 0
      WARN   reports.url_canonical.dedup_rate                 0.1730 (threshold 0.1500)
      ERROR  groups.canonical_name.forward_check              2 rows
    ------------------------------------------------------------
    Totals: 9 pass / 1 warn / 1 error

Design notes:

  - **ASCII only.** cp949 Windows consoles must handle the output
    without ``PYTHONIOENCODING=utf-8`` — the same lesson PR #6 learned
    from em-dash characters in ``decide_exit_code`` summaries.
  - **No dynamic colour.** The stdout sink is purely for operator
    glance value; colour would force ANSI escapes that break when
    captured by CI.
  - **Width-aware.** Severity column is fixed at 7 characters; name
    column is sized to the longest expectation name plus padding.
  - **Observed formatting.** Decimal ``observed`` values format to
    4 decimal places (with threshold if present). When ``observed``
    is None, the violating/affected ``observed_rows`` count is
    rendered as ``"N rows"`` — the "rows" label is shorthand for
    "violating rows" in the error/warn case and "0 rows" in the
    pass case. None values render as an empty string.
"""

from __future__ import annotations

import io
import sys
from decimal import Decimal
from typing import TextIO

from worker.data_quality.results import ExpectationResult


__all__ = ["StdoutSink"]


_SEVERITY_LABEL: dict[str, str] = {
    "pass": "PASS ",
    "warn": "WARN ",
    "error": "ERROR",
}


def _format_observed(result: ExpectationResult) -> str:
    """Render the observed value column for one result row.

    Prefers the most specific representation available:
      - numeric ``observed`` (ratio check) → 4 decimal places, with
        threshold suffix if present
      - integer ``observed_rows`` (count check; value is the
        violating/affected row count per D13) → ``"<N> rows"``
      - neither → empty string
    """
    if result.observed is not None:
        if result.threshold is not None:
            return f"{result.observed:.4f} (threshold {result.threshold:.4f})"
        return f"{result.observed:.4f}"
    if result.observed_rows is not None:
        return f"{result.observed_rows} rows"
    return ""


class StdoutSink:
    """Write an ASCII summary table to a text stream.

    Defaults to :data:`sys.stdout` but accepts any ``TextIO`` so
    tests can capture the output into an :class:`io.StringIO`.
    """

    name: str = "stdout"

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout

    async def write(self, results: list[ExpectationResult]) -> None:
        """Render the summary table and write it to the stream.

        Async to conform to the :class:`Sink` Protocol; does no actual
        I/O awaiting internally.
        """
        total = len(results)
        counts = {"pass": 0, "warn": 0, "error": 0}
        for r in results:
            counts[r.severity] += 1

        lines: list[str] = []
        lines.append(f"Data Quality Gate - {total} expectations")
        lines.append("-" * 60)

        # Fixed severity column width (7), expectation name padded to
        # the longest name in this batch, and the observed column
        # wraps naturally on the right.
        name_width = max(
            (len(r.name) for r in results),
            default=len("<none>"),
        )
        for r in results:
            label = _SEVERITY_LABEL[r.severity]
            observed = _format_observed(r)
            lines.append(
                f"  {label}  {r.name.ljust(name_width)}   {observed}".rstrip()
            )

        lines.append("-" * 60)
        lines.append(
            f"Totals: {counts['pass']} pass / {counts['warn']} warn / "
            f"{counts['error']} error"
        )
        lines.append("")

        self._stream.write("\n".join(lines))
