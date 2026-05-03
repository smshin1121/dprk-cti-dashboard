"""Importable seed-helper for migration 0009_correlation_coverage.

Lives outside the alembic revision graph (file name does NOT match
``NNNN_*.py`` convention) so it is not picked up as a migration but
remains importable for unit tests AND from the actual revision file.

The function is dialect-portable: PG returns ``date`` from
``MIN(<date_column>)`` while sqlite returns an ISO-8601 string when
the query is issued via raw ``sa.text``. ``_coerce_to_year_month``
normalizes both.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa


_BASELINE_FLOOR_MONTH = "1900-01"
_FALLBACK_EARLIEST_MONTH = "2009-01"


def _coerce_to_year_month(value: object) -> tuple[int, int] | None:
    """Convert ``MIN(<date>)`` result to ``(year, month)`` across dialects."""
    if value is None:
        return None
    if isinstance(value, (dt.datetime, dt.date)):
        return (value.year, value.month)
    if isinstance(value, str):
        try:
            parsed = dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
        return (parsed.year, parsed.month)
    return None


def seed_correlation_no_data(
    bind: sa.engine.Connection,
    *,
    series_root: str,
    source_table: str,
    source_column: str,
) -> None:
    """Insert ``no_data`` coverage rows for months strictly before the
    source table's earliest date. Empty source tables fall back to the
    hardcoded fallback earliest month.
    """
    earliest_row = bind.execute(
        sa.text(
            f"SELECT MIN({source_column}) AS earliest FROM {source_table}"  # noqa: S608
        )
    ).fetchone()
    earliest_value = earliest_row.earliest if earliest_row else None

    coerced = _coerce_to_year_month(earliest_value)
    if coerced is None:
        earliest_year, earliest_month = (
            int(part) for part in _FALLBACK_EARLIEST_MONTH.split("-")
        )
    else:
        earliest_year, earliest_month = coerced

    floor_year, floor_month = (
        int(part) for part in _BASELINE_FLOOR_MONTH.split("-")
    )

    rows: list[dict[str, str]] = []
    year, month = floor_year, floor_month
    while (year, month) < (earliest_year, earliest_month):
        rows.append(
            {
                "series_root": series_root,
                "bucket": f"{year:04d}-{month:02d}",
                "status": "no_data",
            }
        )
        month += 1
        if month > 12:
            year += 1
            month = 1

    if not rows:
        return

    bind.execute(
        sa.text(
            "INSERT INTO correlation_coverage (series_root, bucket, status) "
            "VALUES (:series_root, :bucket, :status)"
        ),
        rows,
    )
