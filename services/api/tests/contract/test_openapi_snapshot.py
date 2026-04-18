"""OpenAPI snapshot drift guard (PR #11 Group J).

The committed snapshot ``contracts/openapi/openapi.json`` pins the
API contract surface at a known-good point. This test regenerates
the spec in-process via ``app.openapi()`` and asserts byte-exact
equality against the committed file. Any drift — added endpoint,
removed response, changed DTO, edited example, updated description —
surfaces as a red test with an actionable regen command.

Compare-only, never regenerate
------------------------------
The test never writes to ``contracts/openapi/openapi.json``. Snapshot
updates are an explicit developer step via
``scripts/regenerate_openapi_snapshot.py``. This separation is
deliberate (plan §5.3, Group J review lock):

- "Compare against committed snapshot" = CI responsibility → this test
- "Regenerate snapshot" = developer responsibility → the script

If the test regenerated the snapshot, CI would be self-healing and
a consumer-breaking change could silently land with zero review.

Why the full canonical-bytes check
----------------------------------
``json.dumps(live, sort_keys=True, ...) == snapshot_text`` catches
everything the looser ``live_paths == committed_paths`` check misses:
response shape drift, DTO field order drift inside examples, security
block drift, tag changes, info block (``version``) bumps. The path
comparison runs first anyway, purely for friendlier error messages
in the common "new endpoint landed" case — but the byte check is
the authoritative gate.

Why not use the ``/openapi.json`` HTTP route
--------------------------------------------
``services/api/src/api/main.py`` gates ``openapi_url`` to dev only
(prod returns 404 to avoid unauthenticated spec discovery). The
``app.openapi()`` Python method is env-independent and returns the
full spec regardless — so this test runs cleanly in ``APP_ENV=test``
and the snapshot represents the full contract surface, not a
dev-route-only subset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[4]
_SNAPSHOT_PATH = _REPO_ROOT / "contracts" / "openapi" / "openapi.json"
_REGEN_HINT = (
    "Update procedure:\n"
    "  1. `cd services/api && uv run python "
    "../../scripts/regenerate_openapi_snapshot.py`\n"
    "  2. Review the git diff — confirm the change was intentional\n"
    "  3. Commit the updated contracts/openapi/openapi.json"
)


def _canonical_json(spec: dict[str, Any]) -> str:
    """Match ``scripts/regenerate_openapi_snapshot.py::_canonical_json`` verbatim.

    Identical serializer on both sides is the only way a byte-exact
    comparison is meaningful. A divergence here (e.g. different indent,
    different ensure_ascii) would produce spurious drift on CI and
    force developers to hand-edit the committed file — the exact
    anti-pattern the script exists to prevent.
    """
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_openapi_snapshot_file_exists_and_is_json() -> None:
    """Preflight: the snapshot must exist at a known path and be
    parseable JSON. A missing or malformed snapshot would make every
    subsequent drift assertion fail unclearly — surface that state
    here with a targeted message.
    """
    assert _SNAPSHOT_PATH.is_file(), (
        f"OpenAPI snapshot missing at {_SNAPSHOT_PATH}. "
        "Generate it with `cd services/api && uv run python "
        "../../scripts/regenerate_openapi_snapshot.py` and commit."
    )
    # json.loads will raise a helpful JSONDecodeError on malformed
    # input — preferable to a silent byte-comparison failure deeper
    # in the suite.
    json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_openapi_paths_match_snapshot() -> None:
    """Friendly-diff layer: if paths were added or removed, fail with
    a pinpointed message before the full-bytes check blames the whole
    snapshot.

    This is redundant with ``test_openapi_snapshot_matches_live_exactly``
    for correctness but not for ergonomics: a typical "added a new
    endpoint" PR gets a 3-line error here instead of a 30-KB diff
    from the byte-level check.
    """
    from api.main import app

    live = app.openapi()
    committed = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))

    live_paths = set(live["paths"].keys())
    committed_paths = set(committed["paths"].keys())
    added = sorted(live_paths - committed_paths)
    removed = sorted(committed_paths - live_paths)

    if added or removed:
        pytest.fail(
            "OpenAPI paths drifted vs snapshot:\n"
            f"  added:   {added or '(none)'}\n"
            f"  removed: {removed or '(none)'}\n\n" + _REGEN_HINT,
            pytrace=False,
        )


def test_openapi_snapshot_matches_live_exactly() -> None:
    """Authoritative drift gate — byte-exact canonical JSON comparison.

    Catches every drift category the paths-level test misses:

    - Response body shape / DTO field changes
    - Example drift (a 429 ``message`` string edit, a new field in a
      200 happy-path example)
    - Description / summary edits
    - Security scheme drift
    - ``info.version`` bumps
    - Request schema changes (query params, body models)

    On drift, reports the first divergent path so the dev has a
    specific anchor to investigate. Full diff is not dumped — it can
    reach tens of KB and dominates the test log. The regen command
    is the canonical path forward; a human read of the resulting git
    diff is the intended review surface.
    """
    from api.main import app

    live = app.openapi()
    live_canonical = _canonical_json(live)
    committed_canonical = _SNAPSHOT_PATH.read_text(encoding="utf-8")

    if live_canonical == committed_canonical:
        return

    # Narrow to the first drifted path for the error message. Fall
    # back to non-paths section hint if the divergence is at a
    # meta-level (info / components / security / tags).
    committed = json.loads(committed_canonical)
    drifted_paths: list[str] = []
    for path, live_ops in live["paths"].items():
        if committed["paths"].get(path) != live_ops:
            drifted_paths.append(path)
    if not drifted_paths:
        # Meta-level drift (components, info, security).
        meta_hint = "non-paths section (components / info / security)"
    else:
        meta_hint = "paths " + ", ".join(drifted_paths[:5])
        if len(drifted_paths) > 5:
            meta_hint += f" (+{len(drifted_paths) - 5} more)"

    pytest.fail(
        f"OpenAPI snapshot drifted. First divergent area: {meta_hint}\n\n"
        + _REGEN_HINT,
        pytrace=False,
    )


def test_snapshot_is_canonically_serialized() -> None:
    """The committed file MUST be canonically-serialized (sort_keys,
    2-space indent, trailing newline). Hand-edits usually break this
    and produce a drift false-positive on subsequent CI runs.

    This test re-serializes the parsed snapshot and compares — any
    hand-edit that changed ordering or whitespace fails here before
    the ``matches_live`` test can mislead anyone into thinking the
    live spec changed.
    """
    raw = _SNAPSHOT_PATH.read_text(encoding="utf-8")
    reparsed = json.loads(raw)
    canonical = _canonical_json(reparsed)
    if raw != canonical:
        pytest.fail(
            "contracts/openapi/openapi.json is not canonically serialized. "
            "Do NOT hand-edit the snapshot; regenerate via "
            "`cd services/api && uv run python "
            "../../scripts/regenerate_openapi_snapshot.py` instead.",
            pytrace=False,
        )
