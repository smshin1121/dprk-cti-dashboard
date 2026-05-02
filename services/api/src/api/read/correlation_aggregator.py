"""Phase 3 Slice 3 D-1 correlation aggregator.

Implements the locked computation pipeline from
``docs/plans/phase-3-slice-3-correlation.md`` §7.4 (calendar-aware lag
pairing — NOT pre-collapse) plus the safe-primitive contracts in §5.1
and §5.3 (BH-FDR per-(pair, method) over finite p-values).

Public API
----------
- ``compute_correlation_series_catalog(session)`` — returns the catalog
  payload for ``GET /api/v1/analytics/correlation/series`` per spec
  §7.2.
- ``compute_correlation(session, *, x, y, date_from, date_to, alpha)``
  — returns the full 200 response payload per spec §7.3. Raises
  ``InsufficientSampleError`` when effective_n < 30 at lag 0; the
  router translates that to the FastAPI ``detail[]`` 422 envelope.

Statistical primitives
----------------------
- Pearson r + p via ``scipy.stats.pearsonr``.
- Spearman ρ + p via ``scipy.stats.spearmanr``.
- Lag cross-correlation via in-house calendar-aware pairing — NOT
  ``statsmodels.tsa.stattools.ccf`` directly, because ccf collapses
  to valid-only rows before shifting (the exact defect r1 caught).
- ADF stationarity via ``statsmodels.tsa.stattools.adfuller`` for the
  ``non_stationary_suspected`` warning trigger.
- BH-FDR via ``statsmodels.stats.multitest.multipletests`` with
  ``method='fdr_bh'`` over the finite-p subset only.

The verbatim sentence ``Positive lag = X leads Y by k months.`` is
locked at i18n key ``correlation.lag.direction_sentence``. R-13
prevention asserts the sentence appears in the aggregator's compute
docstring (test_correlation_aggregator_math.py).

Positive lag = X leads Y by k months.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import sqlalchemy as sa
import statsmodels.api as sm
from scipy import stats as scipy_stats
from sqlalchemy.ext.asyncio import AsyncSession
from statsmodels.stats.multitest import multipletests

from ..tables import (
    correlation_coverage_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    reports_table,
)
from .repositories import _resolve_dialect


# ---------------------------------------------------------------------------
# Locked constants (spec §4.4 + §5.1 + §5.3 + §13)
# ---------------------------------------------------------------------------

LAG_MAX = 24
LAG_RANGE = list(range(-LAG_MAX, LAG_MAX + 1))  # 49 values: -24..+24
MIN_EFFECTIVE_N = 30
LOW_COUNT_SUPPRESSION_THRESHOLD = 5  # R-16 mitigation

LAG_DIRECTION_SENTENCE = "Positive lag = X leads Y by k months."

# Spec §10.2 future slot — bucket granularity is monthly only in this slice.
BUCKET_GRANULARITY: Literal["monthly"] = "monthly"


# ---------------------------------------------------------------------------
# Series catalog (spec §2.2 — locked first slice)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CatalogSeries:
    id: str
    label_ko: str
    label_en: str
    root: Literal["reports.published", "incidents.reported"]


_BASE_CATALOG: tuple[_CatalogSeries, ...] = (
    _CatalogSeries(
        id="reports.total",
        label_ko="전체 보고서 (월별)",
        label_en="All reports (monthly)",
        root="reports.published",
    ),
    _CatalogSeries(
        id="incidents.total",
        label_ko="전체 사건 (월별)",
        label_en="All incidents (monthly)",
        root="incidents.reported",
    ),
)


# ---------------------------------------------------------------------------
# Errors translated by the router into the spec §7.3 detail[] 422 envelope
# ---------------------------------------------------------------------------


class InsufficientSampleError(Exception):
    """Raised when effective_n < MIN_EFFECTIVE_N at lag 0.

    Caught by the router and translated to:
        422 detail[0].type = "value_error.insufficient_sample"
        ctx = {"effective_n": <N>, "minimum_n": MIN_EFFECTIVE_N}
    """

    def __init__(self, effective_n: int, minimum_n: int) -> None:
        super().__init__(
            f"Minimum {minimum_n} valid months required after no_data "
            f"exclusion; got {effective_n}"
        )
        self.effective_n = effective_n
        self.minimum_n = minimum_n


class SeriesNotFoundError(Exception):
    """Raised when a catalog ID does not resolve to a known query plan."""

    def __init__(self, series_id: str) -> None:
        super().__init__(f"series id {series_id!r} not in catalog")
        self.series_id = series_id


# ---------------------------------------------------------------------------
# Dense calendar grid types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GridCell:
    """One cell on the dense YYYY-MM calendar grid."""

    bucket: str  # 'YYYY-MM'
    count: int
    cell_type: Literal["valid", "zero_count", "no_data"]


# ---------------------------------------------------------------------------
# Public catalog API
# ---------------------------------------------------------------------------


async def compute_correlation_series_catalog(
    session: AsyncSession,
) -> dict[str, list[dict[str, str]]]:
    """Return the catalog payload per spec §7.2.

    The catalog is dynamically extended with per-group and per-(motivation /
    sector / country) entries derived from the existing dimension tables.
    The session argument is required so the dimension lookups stay
    consistent with the rest of the read surface (no separate cache).
    """
    series: list[dict[str, str]] = [
        {
            "id": entry.id,
            "label_ko": entry.label_ko,
            "label_en": entry.label_en,
            "root": entry.root,
            "bucket": BUCKET_GRANULARITY,
        }
        for entry in _BASE_CATALOG
    ]

    # Per-motivation series (incidents-rooted)
    motivation_rows = (
        await session.execute(
            sa.select(incident_motivations_table.c.motivation)
            .distinct()
            .order_by(incident_motivations_table.c.motivation.asc())
        )
    ).all()
    for row in motivation_rows:
        if row.motivation is None:
            continue
        series.append(
            {
                "id": f"incidents.by_motivation.{row.motivation}",
                "label_ko": f"동기={row.motivation} 사건 (월별)",
                "label_en": f"Incidents by motivation={row.motivation} (monthly)",
                "root": "incidents.reported",
                "bucket": BUCKET_GRANULARITY,
            }
        )

    # Per-sector series (incidents-rooted)
    sector_rows = (
        await session.execute(
            sa.select(incident_sectors_table.c.sector_code)
            .distinct()
            .order_by(incident_sectors_table.c.sector_code.asc())
        )
    ).all()
    for row in sector_rows:
        if row.sector_code is None:
            continue
        series.append(
            {
                "id": f"incidents.by_sector.{row.sector_code}",
                "label_ko": f"섹터={row.sector_code} 사건 (월별)",
                "label_en": f"Incidents by sector={row.sector_code} (monthly)",
                "root": "incidents.reported",
                "bucket": BUCKET_GRANULARITY,
            }
        )

    # Per-country series (incidents-rooted) — disclosure-suppression
    # protects sparse-bucket inference per R-16.
    country_rows = (
        await session.execute(
            sa.select(incident_countries_table.c.country_iso2)
            .distinct()
            .order_by(incident_countries_table.c.country_iso2.asc())
        )
    ).all()
    for row in country_rows:
        if row.country_iso2 is None:
            continue
        series.append(
            {
                "id": f"incidents.by_country.{row.country_iso2}",
                "label_ko": f"국가={row.country_iso2} 사건 (월별)",
                "label_en": f"Incidents by country={row.country_iso2} (monthly)",
                "root": "incidents.reported",
                "bucket": BUCKET_GRANULARITY,
            }
        )

    return {"series": series}


# ---------------------------------------------------------------------------
# Series resolution (id → SQL query spec)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SeriesResolver:
    """Internal resolved description of a catalog series."""

    series_id: str
    root: Literal["reports.published", "incidents.reported"]
    # Filters applied to the source row count per bucket. Built as
    # SQLAlchemy expressions at resolve time.
    extra_filter: sa.sql.ColumnElement[bool] | None = None
    # If the series joins through a junction table (motivation / sector /
    # country), this is the table to join against and the column to
    # filter by + value.
    junction_table: sa.Table | None = None
    junction_column: sa.Column[str] | None = None
    junction_value: str | None = None


def _resolve_series(series_id: str) -> _SeriesResolver:
    """Map a catalog series id to a resolved query plan.

    Raises ``SeriesNotFoundError`` for unknown IDs. Catalog drift is
    handled at the router boundary (router validates against the live
    catalog before calling compute_correlation).
    """
    if series_id == "reports.total":
        return _SeriesResolver(series_id=series_id, root="reports.published")

    if series_id == "incidents.total":
        return _SeriesResolver(series_id=series_id, root="incidents.reported")

    if series_id.startswith("incidents.by_motivation."):
        key = series_id[len("incidents.by_motivation."):]
        return _SeriesResolver(
            series_id=series_id,
            root="incidents.reported",
            junction_table=incident_motivations_table,
            junction_column=incident_motivations_table.c.motivation,
            junction_value=key,
        )

    if series_id.startswith("incidents.by_sector."):
        key = series_id[len("incidents.by_sector."):]
        return _SeriesResolver(
            series_id=series_id,
            root="incidents.reported",
            junction_table=incident_sectors_table,
            junction_column=incident_sectors_table.c.sector_code,
            junction_value=key,
        )

    if series_id.startswith("incidents.by_country."):
        key = series_id[len("incidents.by_country."):]
        return _SeriesResolver(
            series_id=series_id,
            root="incidents.reported",
            junction_table=incident_countries_table,
            junction_column=incident_countries_table.c.country_iso2,
            junction_value=key,
        )

    raise SeriesNotFoundError(series_id)


# ---------------------------------------------------------------------------
# Dense calendar grid construction
# ---------------------------------------------------------------------------


def _month_iter(start: date, end: date) -> list[str]:
    """Yield a dense YYYY-MM list from start.month to end.month inclusive."""
    if end < start:
        return []
    out: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year += 1
            month = 1
    return out


def _bucket_expr(
    col: sa.sql.ColumnElement[date], dialect: str
) -> sa.sql.ColumnElement[str]:
    """Portable YYYY-MM expression — same shape as analytics_aggregator."""
    if dialect == "postgresql":
        return sa.func.to_char(col, "YYYY-MM")
    return sa.func.strftime("%Y-%m", col)


async def _query_monthly_counts(
    session: AsyncSession,
    *,
    resolver: _SeriesResolver,
    date_from: date,
    date_to: date,
) -> dict[str, int]:
    """Return ``{bucket: count}`` for the resolved series over the window."""
    dialect = _resolve_dialect(session)

    if resolver.root == "reports.published":
        # Reports-rooted — distinct report count per month
        stmt = (
            sa.select(
                _bucket_expr(reports_table.c.published, dialect).label("bucket"),
                sa.func.count(sa.distinct(reports_table.c.id)).label("count"),
            )
            .select_from(reports_table)
            .where(
                reports_table.c.published >= date_from,
                reports_table.c.published <= date_to,
            )
            .group_by("bucket")
        )
    else:
        # incidents.reported — distinct incident count per month
        select_from: sa.sql.FromClause = incidents_table
        if resolver.junction_table is not None:
            select_from = incidents_table.join(
                resolver.junction_table,
                incidents_table.c.id == resolver.junction_table.c.incident_id,
            )

        stmt = (
            sa.select(
                _bucket_expr(incidents_table.c.reported, dialect).label("bucket"),
                sa.func.count(sa.distinct(incidents_table.c.id)).label("count"),
            )
            .select_from(select_from)
            .where(
                incidents_table.c.reported >= date_from,
                incidents_table.c.reported <= date_to,
            )
            .group_by("bucket")
        )

        if resolver.junction_column is not None and resolver.junction_value is not None:
            stmt = stmt.where(resolver.junction_column == resolver.junction_value)

    rows = (await session.execute(stmt)).all()
    return {row.bucket: int(row.count) for row in rows if row.bucket is not None}


async def _query_no_data_buckets(
    session: AsyncSession, *, root: str
) -> set[str]:
    """Return the set of buckets marked ``no_data`` for this root."""
    stmt = (
        sa.select(correlation_coverage_table.c.bucket)
        .where(
            correlation_coverage_table.c.series_root == root,
            correlation_coverage_table.c.status == "no_data",
        )
    )
    rows = (await session.execute(stmt)).all()
    return {row.bucket for row in rows}


async def _build_dense_calendar_grid(
    session: AsyncSession,
    *,
    resolver: _SeriesResolver,
    date_from: date,
    date_to: date,
) -> list[_GridCell]:
    """Build the dense YYYY-MM grid for one series.

    A bucket is:
        - ``no_data`` if the correlation_coverage table marks it so for
          this series_root, OR
        - ``valid`` if it has count > 0 from the source query, OR
        - ``zero_count`` otherwise (genuine 0 in a normalized period).

    Spec §4.2 lock — zero-fill ONLY for genuinely-zero months. Pre-bootstrap
    / vendor-outage months are no_data per the coverage table.
    """
    counts = await _query_monthly_counts(
        session,
        resolver=resolver,
        date_from=date_from,
        date_to=date_to,
    )
    no_data_set = await _query_no_data_buckets(session, root=resolver.root)

    cells: list[_GridCell] = []
    for bucket in _month_iter(date_from, date_to):
        if bucket in no_data_set:
            cells.append(
                _GridCell(bucket=bucket, count=0, cell_type="no_data")
            )
            continue
        count = counts.get(bucket, 0)
        if count == 0:
            cells.append(
                _GridCell(bucket=bucket, count=0, cell_type="zero_count")
            )
        else:
            cells.append(_GridCell(bucket=bucket, count=count, cell_type="valid"))
    return cells


# ---------------------------------------------------------------------------
# Calendar-aware lag pairing (spec §4.4 + §5.1 — CRITICAL r1 fix)
# ---------------------------------------------------------------------------


def _lag_pair_calendar_aware(
    x_grid: list[_GridCell], y_grid: list[_GridCell], k: int
) -> tuple[list[int], list[int], int]:
    """Return ``(x_arr, y_arr, effective_n_at_lag)`` for calendar-aligned pairs.

    Pair X[t] with Y[t+k] on the dense grid; drop pairs where either side
    is no_data. Per spec §4.4 lock:
        Positive lag = X leads Y by k months.

    For k >= 0: t in [0, N-k); for k < 0: t in [-k, N).
    """
    n = len(x_grid)
    if n != len(y_grid):
        raise ValueError(
            f"x_grid length {n} != y_grid length {len(y_grid)}; "
            "grids must be aligned to the same calendar window"
        )

    if k >= 0:
        t_range = range(0, n - k)
    else:
        t_range = range(-k, n)

    x_pairs: list[int] = []
    y_pairs: list[int] = []
    for t in t_range:
        x_cell = x_grid[t]
        y_cell = y_grid[t + k]
        if x_cell.cell_type == "no_data" or y_cell.cell_type == "no_data":
            continue
        x_pairs.append(x_cell.count)
        y_pairs.append(y_cell.count)
    return (x_pairs, y_pairs, len(x_pairs))


# ---------------------------------------------------------------------------
# Safe statistical primitives (HIGH r1 fix — pre/post finite checks)
# ---------------------------------------------------------------------------


_NullCellTriple = tuple[None, None, str]
_PopulatedCellTriple = tuple[float, float, None]
_SafePrimitiveResult = _NullCellTriple | _PopulatedCellTriple


def _safe_pearsonr(
    x_arr: list[int], y_arr: list[int]
) -> _SafePrimitiveResult:
    """Pearson r + p with full safety checks (HIGH r1 + R-12 mitigation).

    Returns ``(r, p, None)`` on success, or ``(None, None, reason)``
    where reason is one of ``insufficient_sample_at_lag``,
    ``low_count_suppressed``, ``degenerate``.
    """
    n = len(x_arr)
    if n < MIN_EFFECTIVE_N:
        return (None, None, "insufficient_sample_at_lag")
    # R-16 disclosure suppression — applied BEFORE statistic compute.
    if min(x_arr) < LOW_COUNT_SUPPRESSION_THRESHOLD or min(y_arr) < LOW_COUNT_SUPPRESSION_THRESHOLD:
        return (None, None, "low_count_suppressed")
    # Variance pre-check — scipy returns NaN with RuntimeWarning, not raise.
    x_np = np.asarray(x_arr, dtype=float)
    y_np = np.asarray(y_arr, dtype=float)
    if x_np.var(ddof=0) == 0.0 or y_np.var(ddof=0) == 0.0:
        return (None, None, "degenerate")
    result = scipy_stats.pearsonr(x_np, y_np)
    r = float(result.statistic)
    p = float(result.pvalue)
    if not (math.isfinite(r) and math.isfinite(p)):
        return (None, None, "degenerate")
    return (r, p, None)


def _safe_spearmanr(
    x_arr: list[int], y_arr: list[int]
) -> _SafePrimitiveResult:
    """Spearman ρ + p with full safety checks — same contract as Pearson."""
    n = len(x_arr)
    if n < MIN_EFFECTIVE_N:
        return (None, None, "insufficient_sample_at_lag")
    if min(x_arr) < LOW_COUNT_SUPPRESSION_THRESHOLD or min(y_arr) < LOW_COUNT_SUPPRESSION_THRESHOLD:
        return (None, None, "low_count_suppressed")
    x_np = np.asarray(x_arr, dtype=float)
    y_np = np.asarray(y_arr, dtype=float)
    if x_np.var(ddof=0) == 0.0 or y_np.var(ddof=0) == 0.0:
        return (None, None, "degenerate")
    result = scipy_stats.spearmanr(x_np, y_np)
    r = float(result.statistic)
    p = float(result.pvalue)
    if not (math.isfinite(r) and math.isfinite(p)):
        return (None, None, "degenerate")
    return (r, p, None)


# ---------------------------------------------------------------------------
# BH-FDR over finite p-values per (pair, method)
# ---------------------------------------------------------------------------


def _apply_bh_fdr(
    p_values: list[float], alpha: float
) -> tuple[list[float], list[bool]]:
    """Apply BH-FDR over a non-empty list of finite p-values.

    Returns ``(p_adjusted, significant)`` aligned to the input order.
    Spec §5.3 lock — m_method = len(p_values), per-method independent.
    """
    if not p_values:
        return ([], [])
    rejected, p_adj, _, _ = multipletests(p_values, alpha=alpha, method="fdr_bh")
    return ([float(p) for p in p_adj], [bool(r) for r in rejected])


# ---------------------------------------------------------------------------
# Lag scan (orchestrates calendar pairing + safe primitives + BH-FDR)
# ---------------------------------------------------------------------------


@dataclass
class _MethodCellRaw:
    r: float | None
    p_raw: float | None
    p_adjusted: float | None
    significant: bool
    effective_n_at_lag: int
    reason: str | None


@dataclass
class _LagCellRaw:
    lag: int
    pearson: _MethodCellRaw
    spearman: _MethodCellRaw


def _lag_scan(
    x_grid: list[_GridCell], y_grid: list[_GridCell], alpha: float
) -> list[_LagCellRaw]:
    """Run the full lag scan and BH-FDR per spec §7.4.

    Produces one cell per lag in LAG_RANGE. Cells with non-null reason
    are excluded from the BH family entirely.
    """
    cells: list[_LagCellRaw] = []
    pearson_finite_indices: list[int] = []
    pearson_finite_p: list[float] = []
    spearman_finite_indices: list[int] = []
    spearman_finite_p: list[float] = []

    for k in LAG_RANGE:
        x_arr, y_arr, eff_n = _lag_pair_calendar_aware(x_grid, y_grid, k)

        # Pearson
        r_p, p_p, reason_p = _safe_pearsonr(x_arr, y_arr) if eff_n > 0 else (
            None,
            None,
            "insufficient_sample_at_lag",
        )
        pearson = _MethodCellRaw(
            r=r_p,
            p_raw=p_p,
            p_adjusted=None,  # filled by BH below
            significant=False,
            effective_n_at_lag=eff_n,
            reason=reason_p,
        )

        # Spearman — independent of Pearson per spec §5.3
        r_s, p_s, reason_s = _safe_spearmanr(x_arr, y_arr) if eff_n > 0 else (
            None,
            None,
            "insufficient_sample_at_lag",
        )
        spearman = _MethodCellRaw(
            r=r_s,
            p_raw=p_s,
            p_adjusted=None,
            significant=False,
            effective_n_at_lag=eff_n,
            reason=reason_s,
        )

        cell_index = len(cells)
        if reason_p is None and p_p is not None:
            pearson_finite_indices.append(cell_index)
            pearson_finite_p.append(p_p)
        if reason_s is None and p_s is not None:
            spearman_finite_indices.append(cell_index)
            spearman_finite_p.append(p_s)

        cells.append(_LagCellRaw(lag=k, pearson=pearson, spearman=spearman))

    # BH-FDR per (pair, method) — spec §5.3 lock.
    # Pearson family
    if pearson_finite_p:
        pearson_p_adj, pearson_sig = _apply_bh_fdr(pearson_finite_p, alpha)
        for idx, p_adj_value, sig in zip(
            pearson_finite_indices, pearson_p_adj, pearson_sig, strict=True
        ):
            cells[idx].pearson.p_adjusted = p_adj_value
            cells[idx].pearson.significant = sig
    # Spearman family — independent
    if spearman_finite_p:
        spearman_p_adj, spearman_sig = _apply_bh_fdr(spearman_finite_p, alpha)
        for idx, p_adj_value, sig in zip(
            spearman_finite_indices, spearman_p_adj, spearman_sig, strict=True
        ):
            cells[idx].spearman.p_adjusted = p_adj_value
            cells[idx].spearman.significant = sig

    return cells


# ---------------------------------------------------------------------------
# Warning derivation (spec §6.2 + §7.4 AFTER-loop block)
# ---------------------------------------------------------------------------


def _adf_p_value(arr: list[int]) -> float | None:
    """Run ADF stationarity test; return p-value or None if not computable."""
    if len(arr) < MIN_EFFECTIVE_N:
        return None
    arr_np = np.asarray(arr, dtype=float)
    if arr_np.var(ddof=0) == 0.0:
        return None
    try:
        # adfuller returns (adf_stat, pvalue, ...); regression='c' default
        result = sm.tsa.stattools.adfuller(arr_np, autolag="AIC")
        p_val = float(result[1])
        if not math.isfinite(p_val):
            return None
        return p_val
    except (ValueError, RuntimeError):
        return None


def _check_identity_or_containment(
    x_grid: list[_GridCell], y_grid: list[_GridCell]
) -> bool:
    """Return True when one series accounts for >=95% of the other's count.

    Operates on the jointly-valid (non no_data) intersection of the grid.
    """
    x_total = 0
    y_total = 0
    for x_cell, y_cell in zip(x_grid, y_grid, strict=True):
        if x_cell.cell_type == "no_data" or y_cell.cell_type == "no_data":
            continue
        x_total += x_cell.count
        y_total += y_cell.count
    if x_total == 0 or y_total == 0:
        return False
    if x_total >= y_total:
        ratio = y_total / x_total
    else:
        ratio = x_total / y_total
    return ratio >= 0.95


def _compute_warnings(
    *,
    x_grid: list[_GridCell],
    y_grid: list[_GridCell],
    x_root: str,
    y_root: str,
    effective_n: int,
    cells: list[_LagCellRaw],
) -> list[dict[str, str]]:
    """Derive the §6.2 warning list. Spec §7.4 AFTER-loop block."""
    warnings: list[dict[str, str]] = []

    # R-16 — any cell carries low_count_suppressed
    if any(
        cell.pearson.reason == "low_count_suppressed"
        or cell.spearman.reason == "low_count_suppressed"
        for cell in cells
    ):
        warnings.append(
            {
                "code": "low_count_suppressed_cells",
                "message": (
                    "One or more lag cells were suppressed because raw "
                    "monthly counts fell below the disclosure-suppression "
                    "threshold."
                ),
                "severity": "info",
            }
        )

    # outlier_influence — Pearson vs Spearman disagree at lag 0
    cell_at_zero = next((c for c in cells if c.lag == 0), None)
    if cell_at_zero is not None:
        r_p = cell_at_zero.pearson.r
        r_s = cell_at_zero.spearman.r
        if r_p is not None and r_s is not None:
            if abs(r_p - r_s) > 0.2:
                warnings.append(
                    {
                        "code": "outlier_influence",
                        "message": (
                            f"Pearson and Spearman disagree by "
                            f"|Δr|={abs(r_p - r_s):.3f} at lag 0 — possible "
                            "non-linearity or outlier influence."
                        ),
                        "severity": "info",
                    }
                )

    # cross_rooted_pair
    if x_root != y_root:
        warnings.append(
            {
                "code": "cross_rooted_pair",
                "message": (
                    f"X is rooted on {x_root} and Y on {y_root}; lag bias "
                    "may arise from systematic publication delay."
                ),
                "severity": "info",
            }
        )

    # sparse_window — borderline above threshold
    if MIN_EFFECTIVE_N <= effective_n < 36:
        warnings.append(
            {
                "code": "sparse_window",
                "message": (
                    f"effective_n={effective_n} is just above the {MIN_EFFECTIVE_N} "
                    "minimum; results are sensitive to a small number of months."
                ),
                "severity": "info",
            }
        )

    # non_stationary_suspected — ADF on jointly-valid arrays at k=0
    x_arr_zero, y_arr_zero, _ = _lag_pair_calendar_aware(x_grid, y_grid, 0)
    p_adf_x = _adf_p_value(x_arr_zero)
    p_adf_y = _adf_p_value(y_arr_zero)
    if (p_adf_x is not None and p_adf_x > 0.05) or (
        p_adf_y is not None and p_adf_y > 0.05
    ):
        warnings.append(
            {
                "code": "non_stationary_suspected",
                "message": (
                    "One or both series fail an ADF stationarity test at "
                    "α=0.05; spurious correlations possible."
                ),
                "severity": "warn",
            }
        )

    # identity_or_containment_suspected — R-15
    if _check_identity_or_containment(x_grid, y_grid):
        warnings.append(
            {
                "code": "identity_or_containment_suspected",
                "message": (
                    "One series accounts for ≥95% of the other's monthly counts "
                    "over the resolved window — correlation may be tautological."
                ),
                "severity": "warn",
            }
        )

    return warnings


# ---------------------------------------------------------------------------
# Top-level orchestrator (spec §7.4 pipeline)
# ---------------------------------------------------------------------------


_DEFAULT_CAVEAT = (
    "Correlation does not imply causation. This chart shows statistical "
    "co-movement only; non-stationarity, autocorrelation, and unobserved "
    "confounders can produce spurious associations. See the methodology "
    "page for details."
)
_DEFAULT_METHODOLOGY_URL = "/docs/methodology/correlation"


async def compute_correlation(
    session: AsyncSession,
    *,
    x: str,
    y: str,
    date_from: date,
    date_to: date,
    alpha: float,
) -> dict[str, object]:
    """Compute the locked CorrelationResponse payload per spec §7.3.

    Positive lag = X leads Y by k months.

    Raises:
        InsufficientSampleError: when effective_n < 30 at lag 0
        SeriesNotFoundError: when x or y is not in the catalog
    """
    x_resolver = _resolve_series(x)
    y_resolver = _resolve_series(y)

    x_grid = await _build_dense_calendar_grid(
        session, resolver=x_resolver, date_from=date_from, date_to=date_to
    )
    y_grid = await _build_dense_calendar_grid(
        session, resolver=y_resolver, date_from=date_from, date_to=date_to
    )

    # k=0 effective_n (post no_data exclusion)
    effective_n = sum(
        1
        for x_cell, y_cell in zip(x_grid, y_grid, strict=True)
        if x_cell.cell_type != "no_data" and y_cell.cell_type != "no_data"
    )
    if effective_n < MIN_EFFECTIVE_N:
        raise InsufficientSampleError(
            effective_n=effective_n, minimum_n=MIN_EFFECTIVE_N
        )

    cells = _lag_scan(x_grid, y_grid, alpha)
    warnings = _compute_warnings(
        x_grid=x_grid,
        y_grid=y_grid,
        x_root=x_resolver.root,
        y_root=y_resolver.root,
        effective_n=effective_n,
        cells=cells,
    )

    # Round per NFR-4 determinism — 6 decimal places at the boundary.
    def _round(v: float | None) -> float | None:
        if v is None:
            return None
        return round(v, 6)

    lag_grid_payload = [
        {
            "lag": cell.lag,
            "pearson": {
                "r": _round(cell.pearson.r),
                "p_raw": _round(cell.pearson.p_raw),
                "p_adjusted": _round(cell.pearson.p_adjusted),
                "significant": cell.pearson.significant,
                "effective_n_at_lag": cell.pearson.effective_n_at_lag,
                "reason": cell.pearson.reason,
            },
            "spearman": {
                "r": _round(cell.spearman.r),
                "p_raw": _round(cell.spearman.p_raw),
                "p_adjusted": _round(cell.spearman.p_adjusted),
                "significant": cell.spearman.significant,
                "effective_n_at_lag": cell.spearman.effective_n_at_lag,
                "reason": cell.spearman.reason,
            },
        }
        for cell in cells
    ]

    return {
        "x": x,
        "y": y,
        "date_from": date_from,
        "date_to": date_to,
        "alpha": alpha,
        "effective_n": effective_n,
        "lag_grid": lag_grid_payload,
        "interpretation": {
            "caveat": _DEFAULT_CAVEAT,
            "methodology_url": _DEFAULT_METHODOLOGY_URL,
            "warnings": warnings,
        },
    }
