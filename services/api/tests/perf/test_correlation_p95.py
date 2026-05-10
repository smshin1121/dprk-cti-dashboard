"""NFR-1 perf smoke for `/api/v1/analytics/correlation`.

Plan `correlation-hardening.md` §4 T4 + §2 C4 lock + §3 AC #6 +
umbrella spec §3 NFR-1.

Assertion:
    p95 latency ≤ 500 ms over 50 sequential GETs of the populated
    fixture against a running uvicorn process.

Why "running uvicorn" (not in-process `ASGITransport`):
The `services/api/tests/integration/test_correlation_route.py`
pattern uses `httpx.AsyncClient(transport=ASGITransport(app))` for
contract checks — fast, isolated, no network. NFR-1 is a
production-shape assertion: it must include the uvicorn worker, the
real Postgres + Redis sockets, and the network round-trip. The CI
`correlation-perf-smoke` workflow_dispatch job boots the same
host-hybrid stack the `frontend-e2e` job uses; the test itself
points `httpx.AsyncClient` at `127.0.0.1:8000`.

Opt-in gate:
This test is marked `@pytest.mark.perf` and is deselected unless
`PERF_TEST=1` is set (see `conftest.py`). Default
`uv run pytest services/api/tests/` therefore reports the test as
"deselected", not "failed" — the unit/integration suites stay clean
on every developer's box.

Sample size = 50 (umbrella §3 NFR-1 + Q-C4 default — `services` plan
§8 Q-C4). 95th percentile of N=50 with NumPy's default linear
interpolation: position = 0.95 * (50 - 1) = 46.55, so the reported
value sits between the 47th- and 48th-smallest samples (zero-indexed
46 + 0.55 * (47 - 46)). Matches the plan §C4 explicit claim
"`numpy.percentile(durations, 95) <= 0.500`".

Failure diagnostics:
On budget exceedance the assertion message includes min / median /
max / sample count / sorted top-3 worst latencies so an oncall can
diagnose whether the regression is steady-state slowdown (median
moves) or tail outliers (max moves but median is fine).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator

import httpx
import numpy as np
import pytest


_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_BASE_URL_ENV = "PERF_API_BASE_URL"

_ITERATIONS = 50
_P95_BUDGET_SECONDS = 0.500  # 500 ms per umbrella §3 NFR-1
_SEED_TIMEOUT_SECONDS = 30.0
_REQUEST_TIMEOUT_SECONDS = 10.0  # generous; 95th percentile fits well under

_POPULATED_STATE = (
    "seeded correlation populated fixture "
    "and an authenticated analyst session"
)
_CORRELATION_QUERY = (
    "/api/v1/analytics/correlation"
    "?x=reports.total&y=incidents.total"
    "&date_from=2018-01-01&date_to=2026-04-30"
    "&alpha=0.05"
)


def _api_base_url() -> str:
    return os.environ.get(_BASE_URL_ENV, _DEFAULT_BASE_URL)


@pytest.fixture
async def populated_session_client() -> AsyncIterator[httpx.AsyncClient]:
    """Seed the populated fixture + mint an analyst session cookie.

    Uses the dev-only `/_pact/provider_states` endpoint that
    `frontend-e2e` and the Pact contract verifier already exercise
    — exact provider-state phrase matches
    `services/api/src/api/routers/pact_states.py:2568-2575` per plan
    C5 lock. Unknown states fall through with session-only seeding
    (no fixture data) which would invalidate the assertion silently;
    we treat any non-200 from the seeder as a hard fixture-error
    failure to flag drift early.
    """
    base_url = _api_base_url()
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        seed_resp = await client.post(
            "/_pact/provider_states",
            json={"state": _POPULATED_STATE},
            timeout=_SEED_TIMEOUT_SECONDS,
        )
        assert seed_resp.status_code == 200, (
            "provider-state seed failed: "
            f"{seed_resp.status_code} {seed_resp.text}"
        )
        # Cookie persists in the client's cookie jar; subsequent
        # GETs in this fixture's lifetime authenticate automatically.
        yield client


@pytest.mark.perf
@pytest.mark.asyncio
async def test_correlation_p95_under_500ms(
    populated_session_client: httpx.AsyncClient,
) -> None:
    """50 sequential GETs of the populated correlation endpoint.

    Sequential by design — concurrent load tests answer a different
    question (throughput under contention). NFR-1 is a single-user
    p95 latency budget: the operator pulling the analyst dashboard
    expects sub-500ms per click. Sequential mirrors that user shape.
    """
    durations_seconds: list[float] = []
    for iteration in range(_ITERATIONS):
        start = time.perf_counter()
        resp = await populated_session_client.get(_CORRELATION_QUERY)
        elapsed = time.perf_counter() - start
        # Treat ANY non-200 mid-loop as a hard failure with the
        # iteration index — a 422/500 from a regression deeper in
        # the stack would otherwise inflate latency stats with
        # error-path durations and mask the underlying bug.
        assert resp.status_code == 200, (
            f"iteration {iteration}: GET correlation failed "
            f"{resp.status_code} {resp.text[:200]}"
        )
        durations_seconds.append(elapsed)

    durations_ms = np.array(durations_seconds) * 1000.0
    p95_ms = float(np.percentile(durations_ms, 95))
    p95_seconds = p95_ms / 1000.0

    if p95_seconds > _P95_BUDGET_SECONDS:
        sorted_ms = sorted(durations_ms.tolist())
        diagnostic = (
            f"p95 latency {p95_ms:.1f}ms exceeds NFR-1 budget "
            f"{_P95_BUDGET_SECONDS * 1000:.0f}ms over N={_ITERATIONS} "
            "sequential GETs. "
            f"Distribution: min={sorted_ms[0]:.1f}ms "
            f"median={sorted_ms[len(sorted_ms) // 2]:.1f}ms "
            f"max={sorted_ms[-1]:.1f}ms. "
            f"Slowest 3: {[f'{x:.1f}ms' for x in sorted_ms[-3:]]}."
        )
        pytest.fail(diagnostic)
