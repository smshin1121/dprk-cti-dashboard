"""Perf-test opt-in gate.

Plan `correlation-hardening.md` §4 T4 + §2 C4 lock. Mirrors the
`integration` marker precedent at `services/api/pytest.ini:5-9` —
expensive tests must opt in explicitly so the default `uv run pytest`
unit-loop stays self-contained and fast.

Mechanism:
- `--strict-markers` is enabled in `pytest.ini`, so the `perf` marker
  MUST be registered there before any test references it. Registration
  is a separate one-line edit in `pytest.ini`'s `markers` block (T4
  scope item).
- This conftest deselects every collected `perf`-marked test unless
  the `PERF_TEST=1` environment variable is set when pytest is invoked.
  Default invocation therefore produces a "deselected" line in the
  pytest report, NOT a skip — keeps the unit-suite output clean.

Reason for env-var gate (not a `--runperf` CLI flag):
- The `integration` marker already uses an env-var gate
  (`POSTGRES_TEST_URL`); reusing the env-var pattern keeps the project
  consistent.
- CI can flip this without touching pytest argv: the
  `correlation-perf-smoke` workflow_dispatch job exports `PERF_TEST=1`
  and inherits everything else from the existing pytest invocation.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

import pytest


_PERF_OPT_IN_ENV = "PERF_TEST"


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: Iterable[pytest.Item],
) -> None:
    """Deselect perf-marked tests unless `PERF_TEST=1` is set.

    Implementation note: we mutate `items` in-place via
    `config.hook.pytest_deselected` to keep the collection report
    accurate. The `kept` / `deselected` partition mirrors the
    canonical pytest pattern documented at
    https://docs.pytest.org/en/stable/example/simple.html#control-skipping-of-tests-according-to-command-line-option
    adapted to env-var control.
    """
    if os.environ.get(_PERF_OPT_IN_ENV) == "1":
        return

    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if item.get_closest_marker("perf") is not None:
            deselected.append(item)
        else:
            kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        # Mutate the original list in-place so subsequent hooks see
        # the filtered set. `items` is the list the test runner will
        # actually execute.
        items[:] = kept  # type: ignore[index]
