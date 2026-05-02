"""Pydantic DTOs for the Phase 3 Slice 3 D-1 correlation endpoint.

See docs/plans/phase-3-slice-3-correlation.md §5.2, §6.1, §7.3 for the
locked response shapes. The umbrella spec governs WHY each shape is the
way it is; this module is the typed implementation of those locks.

Module is separate from ``schemas/read.py`` to keep the existing read
DTOs focused on the original PR #11/#13/#23 surface — correlation lives
on its own import path.

Per spec §5.2 lock: every cell carries a homogeneous 6-field per-method
shape with all metric fields nullable + a 4-value ``reason`` enum.
``extra="forbid"`` + ``strict=True`` everywhere keeps the contract from
silently absorbing unknown fields.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Catalog endpoint — GET /api/v1/analytics/correlation/series (spec §7.2)
# ---------------------------------------------------------------------------


class CorrelationSeriesItem(BaseModel):
    """One catalog row — exposes which series are correlatable.

    ``id`` is opaque to the FE per spec R-9 mitigation; the FE reads
    label_ko/label_en for display and never parses the id structure.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    label_ko: str
    label_en: str
    root: Literal["reports.published", "incidents.reported"]
    bucket: Literal["monthly"]


class CorrelationCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    series: list[CorrelationSeriesItem]


# ---------------------------------------------------------------------------
# Per-method block (spec §5.2 — homogeneous 6-field shape)
# ---------------------------------------------------------------------------


CorrelationCellReason = Literal[
    "insufficient_sample_at_lag",
    "degenerate",
    "low_count_suppressed",
]


class CorrelationCellMethodBlock(BaseModel):
    """Locked 6-field per-method shape — every lag, every method, always.

    When ``reason`` is non-null, all of ``r``/``p_raw``/``p_adjusted`` MUST
    be null and ``significant`` MUST be False (spec §5.2 lock). Pact
    pins this contract via the model_validator below.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    r: float | None
    p_raw: float | None
    p_adjusted: float | None
    significant: bool
    effective_n_at_lag: Annotated[int, Field(ge=0)]
    reason: CorrelationCellReason | None

    @model_validator(mode="after")
    def _validate_null_consistency(self) -> CorrelationCellMethodBlock:
        if self.reason is not None:
            if self.r is not None or self.p_raw is not None or self.p_adjusted is not None:
                raise ValueError(
                    "non-null reason requires r/p_raw/p_adjusted to be null"
                )
            if self.significant:
                raise ValueError("non-null reason requires significant=False")
        else:
            if self.r is None or self.p_raw is None or self.p_adjusted is None:
                raise ValueError(
                    "populated cell (reason=null) requires all of "
                    "r/p_raw/p_adjusted to be non-null"
                )
        return self


# ---------------------------------------------------------------------------
# Lag cell + warning + interpretation (spec §6 + §7.3)
# ---------------------------------------------------------------------------


class CorrelationLagCell(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lag: Annotated[int, Field(ge=-24, le=24)]
    pearson: CorrelationCellMethodBlock
    spearman: CorrelationCellMethodBlock


CorrelationWarningCode = Literal[
    "non_stationary_suspected",
    "outlier_influence",
    "sparse_window",
    "cross_rooted_pair",
    "identity_or_containment_suspected",
    "low_count_suppressed_cells",
]


class CorrelationWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: CorrelationWarningCode
    message: str
    severity: Literal["info", "warn"]


class CorrelationInterpretation(BaseModel):
    """Spec §6.1 — correlation ≠ causation as structural API contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    caveat: str
    methodology_url: str
    warnings: list[CorrelationWarning]


# ---------------------------------------------------------------------------
# Top-level response (spec §6.1 + §7.3)
# ---------------------------------------------------------------------------


_EXPECTED_LAG_GRID_LENGTH = 49
_EXPECTED_LAGS = list(range(-24, 25))  # -24, -23, ..., 0, ..., 23, 24


class CorrelationResponse(BaseModel):
    """The locked 200 response shape for GET /api/v1/analytics/correlation.

    Spec §4.4 + §5.3: lag_grid always has exactly 49 cells with sorted
    lags -24..+24. The model validator below pins the invariant so any
    aggregator regression that drops/duplicates/reorders cells is
    caught at validation time, not in production.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    x: str
    y: str
    date_from: date
    date_to: date
    alpha: Annotated[float, Field(gt=0.0, lt=1.0)]
    effective_n: Annotated[int, Field(ge=0)]
    lag_grid: Annotated[
        list[CorrelationLagCell],
        Field(min_length=_EXPECTED_LAG_GRID_LENGTH, max_length=_EXPECTED_LAG_GRID_LENGTH),
    ]
    interpretation: CorrelationInterpretation

    @model_validator(mode="after")
    def _validate_lag_grid_invariant(self) -> CorrelationResponse:
        actual_lags = [cell.lag for cell in self.lag_grid]
        if actual_lags != _EXPECTED_LAGS:
            raise ValueError(
                f"lag_grid must contain exactly the 49 lags -24..+24 in "
                f"ascending order; got {actual_lags!r}"
            )
        return self
