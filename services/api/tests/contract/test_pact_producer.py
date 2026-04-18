"""Pact producer verification harness (PR #11 Group I baseline).

Plan §5.3 / D7: the API is the *producer* in our Pact topology. The
frontend (PR #12) is the *consumer* and will commit pact files into
``contracts/pacts/`` at its own repo boundary. This module enumerates
those files and verifies them against the live API surface.

**Baseline posture.** At PR #11 merge time no consumer contract exists
— the FE doesn't ship until PR #12. The harness therefore skips-with-ok
when the ``contracts/pacts/`` glob is empty. The moment a consumer
file is committed, ``test_pact_producer_verifies_consumer_contracts``
stops skipping and the verifier call runs for real.

This split (detection vs. verification) is deliberate:

1. **Skip path** is tested now (``test_pact_directory_skip_semantics``)
   so a regression that, for example, accidentally deletes the
   `contracts/pacts/` directory or breaks the glob surfaces as a test
   error rather than a silently-passing job.
2. **Verify path** is scaffolded but only fires when pact files exist.
   Plan §5.3 says "fail-fast on contract drift once FE consumer exists"
   — that's a hands-off flip from skip to verify, no harness edit
   required.

The verifier itself is ``pact-python``'s ``Verifier``. It needs the
provider app reachable over HTTP. For baseline we assume it is run
against a live uvicorn process (CI job does this; local devs can
point ``PACT_PROVIDER_BASE_URL`` at their running dev stack). When
``PACT_PROVIDER_BASE_URL`` is unset AND pact files exist, the test
**fails loudly** (``pytest.fail``). The earlier draft used
``pytest.xfail`` here but that counts as green on CI — a consumer
pact file could land without the provider-URL wiring and the
``contract-verify`` job would still pass, defeating the whole
fail-fast posture locked by plan D7 ("consumer 생기면 자동으로
verify path로 전환"). A missing provider URL when a contract exists
is a real wiring regression; it MUST surface red.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# Resolved at import time. Collecting the glob once avoids drift between
# the "skip" and "verify" tests if the directory layout changes.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PACTS_DIR = _REPO_ROOT / "contracts" / "pacts"


def _list_pact_files() -> list[Path]:
    """Return the consumer pact files present under ``contracts/pacts/``.

    ``.gitkeep`` and ``README.md`` are not pact files — filter to
    ``*.json`` only. The glob is flat (not recursive) because the
    layout lock in the README mandates ``<consumer>-<provider>.json``
    directly under ``contracts/pacts/``.
    """
    if not _PACTS_DIR.is_dir():
        return []
    return sorted(_PACTS_DIR.glob("*.json"))


def test_pact_directory_exists_and_is_tracked() -> None:
    """``contracts/pacts/`` must exist at HEAD so the glob has something
    to look at. An accidental ``git rm -r contracts/pacts`` would make
    the skip path silently green; this test prevents that.

    The ``.gitkeep`` (or any tracked file) is sufficient — we're
    asserting the directory, not its contents.
    """
    assert _PACTS_DIR.is_dir(), (
        f"contracts/pacts/ not found at {_PACTS_DIR}. "
        "Baseline requires an empty directory tracked by git "
        "(PR #11 Group I convention)."
    )


def test_pact_directory_skip_semantics() -> None:
    """Pin the baseline posture: when no consumer pact files are
    present, the verifier harness skips. This test is green on the
    skip path (pact file list is empty) and remains green even after
    consumer files land — the skip semantics still hold for any
    future regression where the glob finds zero files.

    The companion test ``test_pact_producer_verifies_consumer_contracts``
    is the one that actually flips when files appear.
    """
    pacts = _list_pact_files()
    if pacts:
        pytest.skip(
            f"consumer contract(s) present — {[p.name for p in pacts]}; "
            "this test only pins the empty-list case"
        )
    # Empty list is the expected baseline.
    assert pacts == []


def test_pact_producer_verifies_consumer_contracts() -> None:
    """Verify every consumer pact under ``contracts/pacts/`` against
    the live API surface.

    **Current baseline (no consumer file):** skips with the
    ``no consumer contract committed yet`` reason. CI reports
    skip-with-ok, the job stays green.

    **Future (PR #12 FE lands):** the test iterates pact files and
    calls ``pact.Verifier(...).verify_pacts(pact_file, ...)``. The
    provider base URL comes from ``PACT_PROVIDER_BASE_URL``, which
    CI sets after booting a uvicorn subprocess; local devs point it
    at their dev-compose stack. When ``PACT_PROVIDER_BASE_URL`` is
    unset AND files exist, the test **fails** (not xfails) — xfail
    counts as green on CI and would silently bypass the verify path
    the moment FE ships a pact file. Loud red is the correct posture:
    contract present without wiring = wiring regression.
    """
    pacts = _list_pact_files()
    if not pacts:
        pytest.skip(
            "no consumer contract committed yet — skip-with-ok "
            "(FE consumer contract arrives in PR #12, plan §5.3)"
        )

    provider_base_url = os.getenv("PACT_PROVIDER_BASE_URL")
    if not provider_base_url:
        pytest.fail(
            "Consumer contract(s) present but PACT_PROVIDER_BASE_URL "
            "is unset — contract-verify cannot run. Boot a uvicorn "
            "subprocess in the `contract-verify` CI job (see "
            "contracts/pacts/README.md) and export "
            "`PACT_PROVIDER_BASE_URL=http://127.0.0.1:<port>` before "
            "this test runs. Plan D7 locks that a committed pact "
            "file must trigger real verification, not a green skip.",
            pytrace=False,
        )

    pact = pytest.importorskip(
        "pact",
        reason=(
            "pact-python is a dev dep — if it failed to install on "
            "this platform, reinstall with `uv sync` and file an "
            "issue. The verifier cannot run without it."
        ),
    )

    verifier = pact.Verifier(
        provider="dprk-cti-api",
        provider_base_url=provider_base_url,
    )
    # PR #12 Group I — state setup endpoint. The dev/test-only router
    # registered in `main.py` under `APP_ENV != "prod"` accepts the
    # verifier's per-interaction POST and returns a Set-Cookie the
    # pact-ruby runtime reuses for the subsequent real request.
    # Without this URL, authenticated interactions (/auth/me 200,
    # /dashboard/summary, /actors) would receive 401 and fail.
    provider_states_setup_url = (
        f"{provider_base_url.rstrip('/')}/_pact/provider_states"
    )
    failures: list[str] = []
    for pact_file in pacts:
        exit_code, _logs = verifier.verify_pacts(
            str(pact_file),
            verbose=True,
            provider_states_setup_url=provider_states_setup_url,
        )
        if exit_code != 0:
            failures.append(f"{pact_file.name} → exit {exit_code}")

    assert not failures, (
        "Pact producer verification failed for:\n  "
        + "\n  ".join(failures)
    )


def test_missing_provider_url_with_pacts_present_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: if a consumer pact file is present and
    ``PACT_PROVIDER_BASE_URL`` is unset, the verifier test must
    **fail** (red CI), never skip or xfail (green CI).

    An earlier draft used ``pytest.xfail`` for this branch. xfail
    counts as a passing outcome on CI, which would let a consumer
    contract file silently land without the provider-URL wiring ever
    being completed — the worst possible failure mode for a contract
    gate. This test stubs ``_list_pact_files`` to simulate "pact file
    exists", unsets the env var, invokes the verifier test directly,
    and asserts that ``_pytest.outcomes.Failed`` is raised.

    If a future refactor downgrades the branch back to ``pytest.xfail``
    or ``pytest.skip``, this test flips to failing — preserving the
    fail-fast posture locked by plan D7.
    """
    from _pytest.outcomes import Failed

    monkeypatch.delenv("PACT_PROVIDER_BASE_URL", raising=False)
    monkeypatch.setattr(
        "tests.contract.test_pact_producer._list_pact_files",
        lambda: [Path("contracts/pacts/frontend-dprk-cti-api.json")],
    )

    with pytest.raises(Failed) as exc_info:
        test_pact_producer_verifies_consumer_contracts()

    # Message content pin — the failure must point the next-PR author
    # at the wiring step, not just say "failed".
    assert "PACT_PROVIDER_BASE_URL" in str(exc_info.value)
