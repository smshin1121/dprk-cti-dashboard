"""JSONL sink — writes one JSON object per line to a file.

Semantic contract: every row emitted by :class:`JsonlSink` is the
JSON equivalent of the ``dq_events`` row the :class:`DbSink` would
write for the same :class:`ExpectationResult`. A reviewer must be
able to reconstruct the same logical event from either source.

Mapping (mirrors D5 column order for readability):

    run_id        str (uuid7 string)
    expectation   str
    severity      str
    observed      str (Decimal serialized as string for exactness) | None
    threshold     str (Decimal serialized as string for exactness) | None
    observed_rows int | None   (violating/affected rows)
    detail_jsonb  dict (JSON-serializable)
    observed_at   str (ISO 8601 with explicit offset)

Decimal values are serialized as strings (``"0.1730"``) rather than
float to preserve the exact values the expectations computed. This
matches the guidance in the Python stdlib ``json`` documentation
and avoids silently replacing ``Decimal("0.1")`` with
``0.1000000000000000055...``.

File handling: the sink is configured with a file path. Directories
are created on demand. The file is opened fresh (``"w"``) on each
``write`` call rather than appended, so a second run replaces the
first run's output — matching the bootstrap ETL's dead-letter
contract from PR #6 and making test cleanup trivial. If you need an
appending mirror, instantiate a fresh sink per call with a
different path.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from worker.data_quality.results import ExpectationResult


__all__ = ["JsonlSink"]


def _serialize_decimal(value: Decimal | None) -> str | None:
    """Render a Decimal as its exact string form; None passes through."""
    if value is None:
        return None
    return str(value)


def _json_default(value: Any) -> Any:
    """Fallback for types the stdlib json encoder rejects.

    ``detail`` dicts may carry ``Decimal`` (from expectation
    computations) or dates/datetimes (from column snapshots). Coerce
    each to a stable string so the JSONL output is always valid.
    """
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    raise TypeError(
        f"jsonl sink cannot serialize {type(value).__name__}"
    )


class JsonlSink:
    """Write expectation results to a JSONL file.

    Path directories are created on demand. The file is overwritten
    on each ``write`` call so every run produces a clean artifact.
    """

    name: str = "jsonl"

    def __init__(self, path: Path, run_id: uuid.UUID) -> None:
        self._path = path
        self._run_id = run_id

    async def write(self, results: list[ExpectationResult]) -> None:
        """Write one JSON object per line to the configured path.

        The enclosing directory is created if missing. Empty results
        still produces an empty file so the CI artifact-upload step
        does not fail with "file not found".
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        run_id_str = str(self._run_id)
        with self._path.open("w", encoding="utf-8") as fh:
            for r in results:
                row: dict[str, Any] = {
                    "run_id": run_id_str,
                    "expectation": r.name,
                    "severity": r.severity,
                    "observed": _serialize_decimal(r.observed),
                    "threshold": _serialize_decimal(r.threshold),
                    "observed_rows": r.observed_rows,
                    "detail_jsonb": dict(r.detail),
                    "observed_at": r.observed_at.isoformat(),
                }
                fh.write(
                    json.dumps(
                        row,
                        default=_json_default,
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                )
                fh.write("\n")
