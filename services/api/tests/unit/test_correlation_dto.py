"""Pydantic strict-required-field tests for correlation DTOs (PR #28).

Per docs/plans/phase-3-slice-3-correlation.md §11 PR A test list (MEDIUM
r1 fix + r2 family-size lock):

    CorrelationResponse.model_validate rejects payloads missing
    lag_grid, missing alpha, missing interpretation.caveat, missing
    interpretation.methodology_url, missing effective_n_at_lag;
    populated cells with reason=null must have all of r/p_raw/p_adjusted
    non-null AND finite; null-shape cells with non-null reason must have
    all metric fields null; reason enum is one of {null,
    "insufficient_sample_at_lag", "degenerate", "low_count_suppressed"}.
    No defaults on required fields.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from api.schemas.correlation import (
    CorrelationCellMethodBlock,
    CorrelationLagCell,
    CorrelationResponse,
)


# ---------------------------------------------------------------------------
# CorrelationCellMethodBlock — null-shape consistency
# ---------------------------------------------------------------------------


def _populated_block() -> dict[str, object]:
    return {
        "r": 0.5,
        "p_raw": 0.01,
        "p_adjusted": 0.02,
        "significant": True,
        "effective_n_at_lag": 36,
        "reason": None,
    }


def _null_block(reason: str = "insufficient_sample_at_lag") -> dict[str, object]:
    return {
        "r": None,
        "p_raw": None,
        "p_adjusted": None,
        "significant": False,
        "effective_n_at_lag": 28,
        "reason": reason,
    }


def test_populated_cell_block_validates() -> None:
    CorrelationCellMethodBlock.model_validate(_populated_block())


@pytest.mark.parametrize(
    "reason",
    ["insufficient_sample_at_lag", "degenerate", "low_count_suppressed"],
)
def test_null_cell_block_validates_for_each_locked_reason(reason: str) -> None:
    CorrelationCellMethodBlock.model_validate(_null_block(reason=reason))


def test_unknown_reason_value_rejected() -> None:
    payload = _null_block()
    payload["reason"] = "made_up_reason"
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_populated_cell_with_null_r_rejected() -> None:
    payload = _populated_block()
    payload["r"] = None
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_populated_cell_with_null_p_raw_rejected() -> None:
    payload = _populated_block()
    payload["p_raw"] = None
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_populated_cell_with_null_p_adjusted_rejected() -> None:
    payload = _populated_block()
    payload["p_adjusted"] = None
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_null_cell_with_non_null_r_rejected() -> None:
    payload = _null_block()
    payload["r"] = 0.5
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_null_cell_with_significant_true_rejected() -> None:
    payload = _null_block()
    payload["significant"] = True
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_missing_effective_n_at_lag_rejected() -> None:
    payload = _populated_block()
    del payload["effective_n_at_lag"]
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_negative_effective_n_at_lag_rejected() -> None:
    payload = _populated_block()
    payload["effective_n_at_lag"] = -1
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


def test_extra_field_rejected() -> None:
    payload = _populated_block()
    payload["unexpected"] = "leak"
    with pytest.raises(ValidationError):
        CorrelationCellMethodBlock.model_validate(payload)


# ---------------------------------------------------------------------------
# CorrelationLagCell — lag range
# ---------------------------------------------------------------------------


def test_lag_out_of_range_rejected() -> None:
    payload = {
        "lag": 25,
        "pearson": _populated_block(),
        "spearman": _populated_block(),
    }
    with pytest.raises(ValidationError):
        CorrelationLagCell.model_validate(payload)


def test_lag_in_range_validates() -> None:
    for lag in (-24, 0, 24):
        CorrelationLagCell.model_validate(
            {
                "lag": lag,
                "pearson": _populated_block(),
                "spearman": _populated_block(),
            }
        )


# ---------------------------------------------------------------------------
# CorrelationResponse — top-level required fields
# ---------------------------------------------------------------------------


def _full_response() -> dict[str, object]:
    cell = {
        "lag": 0,
        "pearson": _populated_block(),
        "spearman": _populated_block(),
    }
    return {
        "x": "reports.total",
        "y": "incidents.total",
        "date_from": dt.date(2022, 1, 1),
        "date_to": dt.date(2024, 12, 31),
        "alpha": 0.05,
        "effective_n": 36,
        "lag_grid": [cell],
        "interpretation": {
            "caveat": "Correlation does not imply causation.",
            "methodology_url": "/docs/methodology/correlation",
            "warnings": [],
        },
    }


def test_full_response_validates() -> None:
    CorrelationResponse.model_validate(_full_response())


def test_missing_alpha_rejected() -> None:
    payload = _full_response()
    del payload["alpha"]
    with pytest.raises(ValidationError):
        CorrelationResponse.model_validate(payload)


def test_missing_lag_grid_rejected() -> None:
    payload = _full_response()
    del payload["lag_grid"]
    with pytest.raises(ValidationError):
        CorrelationResponse.model_validate(payload)


def test_missing_interpretation_caveat_rejected() -> None:
    payload = _full_response()
    del payload["interpretation"]["caveat"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        CorrelationResponse.model_validate(payload)


def test_missing_interpretation_methodology_url_rejected() -> None:
    payload = _full_response()
    del payload["interpretation"]["methodology_url"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        CorrelationResponse.model_validate(payload)


def test_alpha_out_of_range_rejected() -> None:
    payload = _full_response()
    payload["alpha"] = 1.5
    with pytest.raises(ValidationError):
        CorrelationResponse.model_validate(payload)
    payload["alpha"] = 0.0
    with pytest.raises(ValidationError):
        CorrelationResponse.model_validate(payload)


def test_extra_top_level_field_rejected() -> None:
    payload = _full_response()
    payload["unexpected"] = "leak"
    with pytest.raises(ValidationError):
        CorrelationResponse.model_validate(payload)
