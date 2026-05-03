"""R-13 prevention test — verbatim lag-direction sentence presence.

Per docs/plans/phase-3-slice-3-correlation.md R-13 mitigation: tests
assert the verbatim sentence appears identically in the aggregator
docstring AND the methodology page. If either drifts, this test fails.
"""

from __future__ import annotations

from pathlib import Path

from api.read.correlation_aggregator import (
    LAG_DIRECTION_SENTENCE,
    compute_correlation,
)


_REPO_ROOT = Path(__file__).resolve().parents[4]
_METHODOLOGY_PAGE = _REPO_ROOT / "docs" / "methodology" / "correlation.md"


def test_lag_sentence_appears_verbatim_in_methodology_page() -> None:
    """R-13 — methodology page H2 must carry the locked sentence verbatim."""
    assert _METHODOLOGY_PAGE.exists(), (
        f"methodology page missing: {_METHODOLOGY_PAGE}"
    )
    content = _METHODOLOGY_PAGE.read_text(encoding="utf-8")
    assert LAG_DIRECTION_SENTENCE in content, (
        f"verbatim lag-direction sentence not found in methodology page; "
        f"R-13 drift detected. Sentence: {LAG_DIRECTION_SENTENCE!r}"
    )


def test_lag_sentence_appears_verbatim_in_aggregator_docstring() -> None:
    """R-13 — compute_correlation docstring must also carry it."""
    assert compute_correlation.__doc__ is not None
    assert LAG_DIRECTION_SENTENCE in compute_correlation.__doc__
