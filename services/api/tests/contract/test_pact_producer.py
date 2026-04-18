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
xfails with a clear TODO rather than a bare ImportError — telling the
next-PR author exactly what's missing.
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
    unset AND files exist, the test xfails with an explicit TODO
    so the next-PR author has a single, obvious place to wire up
    the verifier subprocess.
    """
    pacts = _list_pact_files()
    if not pacts:
        pytest.skip(
            "no consumer contract committed yet — skip-with-ok "
            "(FE consumer contract arrives in PR #12, plan §5.3)"
        )

    provider_base_url = os.getenv("PACT_PROVIDER_BASE_URL")
    if not provider_base_url:
        pytest.xfail(
            "consumer contract(s) present but PACT_PROVIDER_BASE_URL "
            "is unset. Wire up a uvicorn subprocess in CI (see "
            "contracts/pacts/README.md) and set PACT_PROVIDER_BASE_URL "
            "to http://127.0.0.1:<port>. This xfail → pass flip is the "
            "single remaining step; no harness edit needed."
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
    failures: list[str] = []
    for pact_file in pacts:
        exit_code, _logs = verifier.verify_pacts(
            str(pact_file),
            verbose=True,
        )
        if exit_code != 0:
            failures.append(f"{pact_file.name} → exit {exit_code}")

    assert not failures, (
        "Pact producer verification failed for:\n  "
        + "\n  ".join(failures)
    )
