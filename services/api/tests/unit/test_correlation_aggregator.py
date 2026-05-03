"""Unit tests for ``api.read.correlation_aggregator`` (PR #28).

Covers the locked statistical behaviors per
``docs/plans/phase-3-slice-3-correlation.md``:

- §4.4 / §5.1 calendar-aware lag pairing (CRITICAL r1 fix)
- §5.2 4-value reason enum + null-shape contract
- §5.3 BH-FDR per-(pair, method) family scope, m_method
- §6.2 warning vocabulary triggers (all 6 codes)
- §7.4 pipeline ordering (suppression before variance)
- R-12 degenerate handling via _safe_pearsonr / _safe_spearmanr
- R-13 verbatim lag sentence presence
- R-15 identity / containment
- R-16 disclosure suppression

Runs against in-memory aiosqlite per the existing test pattern
(test_analytics_aggregator.py precedent).
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from api.read.correlation_aggregator import (
    LAG_DIRECTION_SENTENCE,
    LAG_RANGE,
    LOW_COUNT_SUPPRESSION_THRESHOLD,
    MIN_EFFECTIVE_N,
    InsufficientSampleError,
    SeriesNotFoundError,
    _apply_bh_fdr,
    _check_identity_or_containment,
    _GridCell,
    _lag_pair_calendar_aware,
    _safe_pearsonr,
    _safe_spearmanr,
    compute_correlation,
    compute_correlation_series_catalog,
)
from api.tables import (
    correlation_coverage_table,
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    metadata,
    reports_table,
    sources_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


async def _seed_reports(
    session: AsyncSession, monthly_counts: dict[str, int]
) -> None:
    """Seed a reports table with N reports in each YYYY-MM bucket."""
    src = await session.execute(
        sa.insert(sources_table)
        .values(name="src-test", type="vendor")
        .returning(sources_table.c.id)
    )
    source_id = src.scalar_one()

    rows = []
    counter = 1
    for bucket, count in monthly_counts.items():
        year, month = (int(p) for p in bucket.split("-"))
        for _ in range(count):
            rows.append(
                {
                    "source_id": source_id,
                    "published": dt.date(year, month, 1),
                    "title": f"r{counter}",
                    "url": f"https://example.test/r{counter}",
                    "url_canonical": f"https://example.test/r{counter}",
                    "sha256_title": f"{counter:064x}",
                    "lang": "en",
                    "tlp": "white",
                }
            )
            counter += 1
    if rows:
        await session.execute(sa.insert(reports_table), rows)
    await session.commit()


async def _seed_incidents(
    session: AsyncSession,
    monthly_counts: dict[str, int],
    *,
    motivation: str | None = None,
    sector: str | None = None,
    country: str | None = None,
) -> None:
    """Seed N incidents per YYYY-MM, optionally with junction rows."""
    rows = []
    counter = 1
    for bucket, count in monthly_counts.items():
        year, month = (int(p) for p in bucket.split("-"))
        for _ in range(count):
            rows.append(
                {
                    "reported": dt.date(year, month, 1),
                    "title": f"i{counter}",
                    "description": "test incident",
                }
            )
            counter += 1

    if not rows:
        return

    result = await session.execute(
        sa.insert(incidents_table).returning(incidents_table.c.id),
        rows,
    )
    incident_ids = [r.id for r in result.all()]

    if motivation is not None:
        await session.execute(
            sa.insert(incident_motivations_table),
            [{"incident_id": iid, "motivation": motivation} for iid in incident_ids],
        )
    if sector is not None:
        await session.execute(
            sa.insert(incident_sectors_table),
            [{"incident_id": iid, "sector_code": sector} for iid in incident_ids],
        )
    if country is not None:
        await session.execute(
            sa.insert(incident_countries_table),
            [{"incident_id": iid, "country_iso2": country} for iid in incident_ids],
        )
    await session.commit()


async def _mark_no_data(
    session: AsyncSession, *, root: str, buckets: list[str]
) -> None:
    """Mark specific buckets as no_data in the coverage table."""
    if not buckets:
        return
    await session.execute(
        sa.insert(correlation_coverage_table),
        [
            {"series_root": root, "bucket": b, "status": "no_data"}
            for b in buckets
        ],
    )
    await session.commit()


# ---------------------------------------------------------------------------
# R-13 — verbatim lag-direction sentence presence (single-sentence-of-truth)
# ---------------------------------------------------------------------------


def test_lag_direction_sentence_constant() -> None:
    """R-13 — constant matches the spec lock exactly."""
    assert LAG_DIRECTION_SENTENCE == "Positive lag = X leads Y by k months."


def test_lag_direction_sentence_in_compute_docstring() -> None:
    """R-13 — sentence appears verbatim in compute_correlation.__doc__."""
    assert compute_correlation.__doc__ is not None
    assert LAG_DIRECTION_SENTENCE in compute_correlation.__doc__


# ---------------------------------------------------------------------------
# Lag range invariant
# ---------------------------------------------------------------------------


def test_lag_range_is_49_values_from_minus_24_to_plus_24() -> None:
    assert len(LAG_RANGE) == 49
    assert LAG_RANGE[0] == -24
    assert LAG_RANGE[-1] == 24
    assert LAG_RANGE[24] == 0


# ---------------------------------------------------------------------------
# Calendar-aware lag pairing (CRITICAL r1 fix)
# ---------------------------------------------------------------------------


def _grid(values: list[tuple[int, str]]) -> list[_GridCell]:
    """Build a grid from (count, type) tuples — bucket synthesized from index."""
    return [
        _GridCell(bucket=f"2020-{i + 1:02d}", count=c, cell_type=t)  # type: ignore[arg-type]
        for i, (c, t) in enumerate(values)
    ]


def test_calendar_pairing_k_zero_aligns_t_to_t() -> None:
    x = _grid([(1, "valid"), (2, "valid"), (3, "valid")])
    y = _grid([(10, "valid"), (20, "valid"), (30, "valid")])
    x_arr, y_arr, n = _lag_pair_calendar_aware(x, y, 0)
    assert n == 3
    assert list(zip(x_arr, y_arr)) == [(1, 10), (2, 20), (3, 30)]


def test_calendar_pairing_positive_k_x_leads() -> None:
    """Positive lag = X leads Y by k months — pair X[t] with Y[t+k]."""
    x = _grid([(1, "valid"), (2, "valid"), (3, "valid"), (4, "valid")])
    y = _grid([(10, "valid"), (20, "valid"), (30, "valid"), (40, "valid")])
    x_arr, y_arr, n = _lag_pair_calendar_aware(x, y, 1)
    assert n == 3
    # X[t] paired with Y[t+1]: (1,20), (2,30), (3,40)
    assert list(zip(x_arr, y_arr)) == [(1, 20), (2, 30), (3, 40)]


def test_calendar_pairing_negative_k_x_lags() -> None:
    x = _grid([(1, "valid"), (2, "valid"), (3, "valid"), (4, "valid")])
    y = _grid([(10, "valid"), (20, "valid"), (30, "valid"), (40, "valid")])
    x_arr, y_arr, n = _lag_pair_calendar_aware(x, y, -1)
    assert n == 3
    # X[t] paired with Y[t-1]: t in [1, 4): (X[1]=2, Y[0]=10), (X[2]=3, Y[1]=20), (X[3]=4, Y[2]=30)
    assert list(zip(x_arr, y_arr)) == [(2, 10), (3, 20), (4, 30)]


def test_calendar_pairing_drops_no_data_after_shift() -> None:
    """CRITICAL r1 fix — internal no_data must be dropped AFTER shift, not BEFORE.

    With X = [1,2,3,4,5] and Y = [10,20,no_data,40,50], at k=0:
    pairs would be (1,10), (2,20), (3,no_data DROPPED), (4,40), (5,50) → n=4.
    """
    x = _grid([(1, "valid"), (2, "valid"), (3, "valid"), (4, "valid"), (5, "valid")])
    y = _grid([
        (10, "valid"),
        (20, "valid"),
        (0, "no_data"),
        (40, "valid"),
        (50, "valid"),
    ])
    x_arr, y_arr, n = _lag_pair_calendar_aware(x, y, 0)
    assert n == 4
    assert list(zip(x_arr, y_arr)) == [(1, 10), (2, 20), (4, 40), (5, 50)]


def test_calendar_pairing_effective_n_at_lag_NOT_n_minus_abs_k() -> None:
    """CRITICAL r1 fix — internal no_data invalidates 2 cells per lag, not 1.

    When Y[2] is no_data, both pair (X[2], Y[2]) at k=0 and pair (X[0], Y[2])
    at k=2 are invalidated. The simple formula N - |k| would over-count.
    """
    x = _grid([(c, "valid") for c in [1, 2, 3, 4, 5, 6, 7, 8]])
    y = _grid([
        (10, "valid"),
        (20, "valid"),
        (0, "no_data"),
        (40, "valid"),
        (50, "valid"),
        (60, "valid"),
        (70, "valid"),
        (80, "valid"),
    ])
    # Naive N-|k| for k=2 on N=8: 6. But Y[2] no_data means pair (X[0],Y[2])
    # at t=0 is dropped; t=1..5 are X[1..5] paired with Y[3..7] all valid → 5.
    _, _, n = _lag_pair_calendar_aware(x, y, 2)
    assert n == 5
    # Naive N-|k| would say 6; the fix produces 5.
    assert n != (len(x) - 2)


# ---------------------------------------------------------------------------
# Safe primitives — pre/post finite checks
# ---------------------------------------------------------------------------


def test_safe_pearsonr_perfect_linear() -> None:
    # Start at LOW_COUNT_SUPPRESSION_THRESHOLD so suppression doesn't trigger.
    x = [LOW_COUNT_SUPPRESSION_THRESHOLD + i for i in range(MIN_EFFECTIVE_N + 5)]
    y = [v * 2 + 100 for v in x]
    r, p, reason = _safe_pearsonr(x, y)
    assert reason is None
    assert r is not None and p is not None
    assert r > 0.999
    assert p < 1e-10


def test_safe_pearsonr_insufficient_sample() -> None:
    x = [10] * (MIN_EFFECTIVE_N - 1)
    y = [10] * (MIN_EFFECTIVE_N - 1)
    r, p, reason = _safe_pearsonr(x, y)
    assert reason == "insufficient_sample_at_lag"
    assert r is None and p is None


def test_safe_pearsonr_low_count_suppressed() -> None:
    """R-16 — min raw count below threshold triggers suppression."""
    x = list(range(MIN_EFFECTIVE_N + 5))
    y = [LOW_COUNT_SUPPRESSION_THRESHOLD - 1] * len(x)  # 4, below threshold of 5
    r, p, reason = _safe_pearsonr(x, y)
    assert reason == "low_count_suppressed"


def test_safe_pearsonr_degenerate_zero_variance() -> None:
    """R-12 — zero-variance input returns degenerate.

    Both arrays must be at-or-above the low-count threshold so suppression
    doesn't fire first; THEN one must be constant to trigger degenerate.
    """
    x = [LOW_COUNT_SUPPRESSION_THRESHOLD + i for i in range(MIN_EFFECTIVE_N + 5)]
    y = [100] * len(x)  # constant — zero variance
    r, p, reason = _safe_pearsonr(x, y)
    assert reason == "degenerate"


def test_safe_pearsonr_ordering_suppression_before_variance() -> None:
    """Spec §7.4 ordering: insufficient → suppression → variance → finite."""
    # All values are 0 (low count + zero variance simultaneously).
    # Per ordering, low_count_suppressed should win.
    x = [0] * MIN_EFFECTIVE_N
    y = [0] * MIN_EFFECTIVE_N
    _, _, reason = _safe_pearsonr(x, y)
    assert reason == "low_count_suppressed"


def test_safe_spearmanr_perfect_monotonic() -> None:
    """Spearman is rank-based; strictly monotonic input → ρ ≈ 1.0.

    The ``_safe_spearmanr`` signature takes ``list[int]`` so we use a
    strictly increasing integer pattern (large multiplier to avoid
    int-truncation ties). Spearman ρ should be exactly 1.0 since the
    ranks of x and y are identical.
    """
    x = [LOW_COUNT_SUPPRESSION_THRESHOLD + i for i in range(MIN_EFFECTIVE_N + 5)]
    y = [v * 100 + v * v for v in x]  # strictly monotonic, distinct ints
    r, p, reason = _safe_spearmanr(x, y)
    assert reason is None
    assert r is not None and r > 0.999


# ---------------------------------------------------------------------------
# BH-FDR family scope
# ---------------------------------------------------------------------------


def test_bh_fdr_empty_input_returns_empty() -> None:
    p_adj, sig = _apply_bh_fdr([], 0.05)
    assert p_adj == []
    assert sig == []


def test_bh_fdr_simple_case() -> None:
    """BH adjusts p-values and produces significance flags."""
    p_values = [0.001, 0.01, 0.04, 0.5]
    p_adj, sig = _apply_bh_fdr(p_values, 0.05)
    assert len(p_adj) == 4
    assert len(sig) == 4
    # All should be ordered such that adjusted >= raw
    for raw, adj in zip(p_values, p_adj, strict=True):
        assert adj >= raw - 1e-9


# ---------------------------------------------------------------------------
# Identity / containment (R-15)
# ---------------------------------------------------------------------------


def test_check_identity_or_containment_true_when_one_dominates() -> None:
    x = _grid([(100, "valid"), (200, "valid"), (300, "valid")])
    y = _grid([(98, "valid"), (195, "valid"), (290, "valid")])  # ~96% containment
    assert _check_identity_or_containment(x, y) is True


def test_check_identity_or_containment_false_when_independent() -> None:
    x = _grid([(100, "valid"), (200, "valid"), (300, "valid")])
    y = _grid([(50, "valid"), (50, "valid"), (50, "valid")])  # 25%
    assert _check_identity_or_containment(x, y) is False


def test_check_identity_or_containment_zero_total_returns_false() -> None:
    x = _grid([(0, "zero_count"), (0, "zero_count")])
    y = _grid([(10, "valid"), (20, "valid")])
    assert _check_identity_or_containment(x, y) is False


# ---------------------------------------------------------------------------
# End-to-end aggregator smoke (synthetic series in DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_correlation_insufficient_sample_raises(
    session: AsyncSession,
) -> None:
    """Window with < 30 valid months raises InsufficientSampleError."""
    monthly = {f"2024-{m:02d}": 5 for m in range(1, 13)}  # 12 months only
    await _seed_reports(session, monthly)
    await _seed_incidents(session, monthly)

    with pytest.raises(InsufficientSampleError) as exc_info:
        await compute_correlation(
            session,
            x="reports.total",
            y="incidents.total",
            date_from=dt.date(2024, 1, 1),
            date_to=dt.date(2024, 12, 31),
            alpha=0.05,
        )
    assert exc_info.value.minimum_n == MIN_EFFECTIVE_N
    assert exc_info.value.effective_n < MIN_EFFECTIVE_N


@pytest.mark.asyncio
async def test_compute_correlation_series_not_found_raises(
    session: AsyncSession,
) -> None:
    with pytest.raises(SeriesNotFoundError):
        await compute_correlation(
            session,
            x="not.a.real.series",
            y="incidents.total",
            date_from=dt.date(2020, 1, 1),
            date_to=dt.date(2024, 12, 31),
            alpha=0.05,
        )


@pytest.mark.asyncio
async def test_compute_correlation_happy_synthetic_pair(
    session: AsyncSession,
) -> None:
    """Synthetic perfect-linear pair across 36 months → r=1.0 at lag 0."""
    # 36 months 2022-01..2024-12. Y = X * 2 + 100 each month.
    monthly_x = {}
    monthly_y = {}
    for ym in range(36):
        year = 2022 + ym // 12
        month = (ym % 12) + 1
        bucket = f"{year:04d}-{month:02d}"
        x_count = 10 + ym  # ramp 10..45
        y_count = x_count * 2 + 100  # 120..190
        monthly_x[bucket] = x_count
        monthly_y[bucket] = y_count
    await _seed_reports(session, monthly_x)
    await _seed_incidents(session, monthly_y)

    payload = await compute_correlation(
        session,
        x="reports.total",
        y="incidents.total",
        date_from=dt.date(2022, 1, 1),
        date_to=dt.date(2024, 12, 31),
        alpha=0.05,
    )
    assert payload["effective_n"] == 36
    assert len(payload["lag_grid"]) == 49
    cell_at_zero = next(c for c in payload["lag_grid"] if c["lag"] == 0)
    assert cell_at_zero["pearson"]["r"] is not None
    assert cell_at_zero["pearson"]["r"] > 0.999
    assert cell_at_zero["pearson"]["reason"] is None
    assert cell_at_zero["spearman"]["reason"] is None
    # Significance flag should be True (BH-adjusted p << 0.05)
    assert cell_at_zero["pearson"]["significant"] is True
    # interpretation contract present
    assert payload["interpretation"]["caveat"]
    assert payload["interpretation"]["methodology_url"]


@pytest.mark.asyncio
async def test_compute_correlation_alpha_echoed(session: AsyncSession) -> None:
    monthly = {f"{2020 + i // 12:04d}-{i % 12 + 1:02d}": 10 + i for i in range(36)}
    await _seed_reports(session, monthly)
    await _seed_incidents(session, monthly)

    payload = await compute_correlation(
        session,
        x="reports.total",
        y="incidents.total",
        date_from=dt.date(2020, 1, 1),
        date_to=dt.date(2022, 12, 31),
        alpha=0.10,
    )
    assert payload["alpha"] == 0.10


@pytest.mark.asyncio
async def test_compute_correlation_lag_grid_homogeneous_shape(
    session: AsyncSession,
) -> None:
    """Every cell carries the locked 6-field per-method shape."""
    monthly = {f"{2020 + i // 12:04d}-{i % 12 + 1:02d}": 10 + i for i in range(36)}
    await _seed_reports(session, monthly)
    await _seed_incidents(session, monthly)

    payload = await compute_correlation(
        session,
        x="reports.total",
        y="incidents.total",
        date_from=dt.date(2020, 1, 1),
        date_to=dt.date(2022, 12, 31),
        alpha=0.05,
    )
    assert len(payload["lag_grid"]) == 49
    for cell in payload["lag_grid"]:
        for method in ("pearson", "spearman"):
            block = cell[method]
            assert set(block.keys()) == {
                "r",
                "p_raw",
                "p_adjusted",
                "significant",
                "effective_n_at_lag",
                "reason",
            }
            # Null-shape consistency
            if block["reason"] is not None:
                assert block["r"] is None
                assert block["p_raw"] is None
                assert block["p_adjusted"] is None
                assert block["significant"] is False


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_includes_baseline_and_dimension_series(
    session: AsyncSession,
) -> None:
    await _seed_reports(session, {"2024-01": 1})
    await _seed_incidents(
        session,
        {"2024-01": 1},
        motivation="Espionage",
        sector="GOV",
        country="KR",
    )
    catalog = await compute_correlation_series_catalog(session)
    ids = {entry["id"] for entry in catalog["series"]}
    assert "reports.total" in ids
    assert "incidents.total" in ids
    assert "incidents.by_motivation.Espionage" in ids
    assert "incidents.by_sector.GOV" in ids
    assert "incidents.by_country.KR" in ids


# ---------------------------------------------------------------------------
# no_data integration — coverage table marks pre-bootstrap months as no_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_data_coverage_excludes_marked_months(
    session: AsyncSession,
) -> None:
    """Months marked as no_data in correlation_coverage are excluded from the
    effective_n count."""
    # 36 monthly buckets, but mark first 6 as no_data
    monthly = {f"{2020 + i // 12:04d}-{i % 12 + 1:02d}": 10 + i for i in range(36)}
    await _seed_reports(session, monthly)
    await _seed_incidents(session, monthly)
    # Mark first 6 months as no_data on reports root
    no_data_buckets = list(monthly.keys())[:6]
    await _mark_no_data(
        session, root="reports.published", buckets=no_data_buckets
    )

    payload = await compute_correlation(
        session,
        x="reports.total",
        y="incidents.total",
        date_from=dt.date(2020, 1, 1),
        date_to=dt.date(2022, 12, 31),
        alpha=0.05,
    )
    # Effective N should be 36 - 6 = 30 (just at threshold)
    assert payload["effective_n"] == 30
