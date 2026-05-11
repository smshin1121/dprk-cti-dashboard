"""Regression test: ``services/api/Dockerfile`` pins every base image to ``@sha256:<digest>``.

Catches the silent-drift class where the deployment Dockerfile is updated
to a new base tag (`python:3.13-slim`, `python:3.12-bookworm`, etc.) and
the contributor forgets to capture a matching digest — producing
"works on my machine" supply-chain drift between local builds, CI builds,
and production rebuilds when the upstream tag moves.

The test is intentionally lenient about EXACT image / tag / platform
syntax — it parses every line that starts with ``FROM`` and asserts the
target reference contains an ``@sha256:`` segment with 64 lowercase hex
characters. ``FROM scratch`` is explicitly allowed (scratch is a
pseudo-image with no content to pin).

Refresh procedure when bumping tags (mirrored from the Dockerfile header
comment so contributors only need to read one place):

  docker pull <image>:<new-tag>
  # capture the printed "Digest: sha256:..." line
  # replace the @sha256:... segment + bump the tag in lockstep

Known limitation (acceptable trade-off, per
`pattern_service_local_duplication_over_shared`): the digest regex
accepts any 64-hex value, so a contributor could in theory paste a
syntactically-valid but content-wrong digest. Catching that would
require pulling the image at test time — a network round-trip we
deliberately keep out of the unit-test layer. CI's container build job
is the second-line catch (build fails on digest mismatch).

Per `pattern_layer_boundary_lock_via_static_source` (PR #47 model):
mechanizes the "pin to @sha256:<digest> before production" TODO that
sat above each FROM since PR #1 (Phase 0).
"""
from __future__ import annotations

import re
from pathlib import Path

_FROM_PATTERN = re.compile(r"^\s*FROM\s+(.+?)\s*(?:AS\s+\w+\s*)?$", re.IGNORECASE | re.MULTILINE)
_DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}\b")


def _service_dockerfile() -> Path:
    """Locate ``services/api/Dockerfile`` from this test file.

    Layout: ``<repo>/services/api/tests/unit/test_dockerfile_digest_pin.py``
    so ``parents[2]`` is ``services/api/``.
    """
    return Path(__file__).resolve().parents[2] / "Dockerfile"


def _from_targets(dockerfile_text: str) -> list[str]:
    """Return the target reference for every ``FROM`` directive.

    Strips the optional ``AS <stage>`` suffix and the optional
    ``--platform=...`` flag so the assertion focuses on the image ref.
    """
    targets: list[str] = []
    for match in _FROM_PATTERN.finditer(dockerfile_text):
        raw = match.group(1).strip()
        # Drop trailing "AS <stage>" if the regex's optional group missed it
        # (it should not, but a belt-and-braces split keeps the test robust
        # against unusual whitespace).
        raw = re.sub(r"\s+AS\s+\w+\s*$", "", raw, flags=re.IGNORECASE)
        # Drop leading "--platform=..." flag(s).
        raw = re.sub(r"^(?:--\S+\s+)+", "", raw)
        targets.append(raw)
    return targets


def test_dockerfile_exists() -> None:
    """Sanity check the relative-path math still finds the Dockerfile."""
    dockerfile = _service_dockerfile()
    assert dockerfile.is_file(), (
        f"expected Dockerfile at {dockerfile}; the relative-path math in "
        f"_service_dockerfile() may be wrong if the service was restructured."
    )


def test_dockerfile_has_at_least_one_from() -> None:
    """A Dockerfile with zero FROMs would silently pass the digest assertion."""
    text = _service_dockerfile().read_text(encoding="utf-8")
    targets = _from_targets(text)
    assert targets, (
        f"no FROM directives found in {_service_dockerfile()}. "
        f"The digest-pin assertion only protects what it sees — an empty "
        f"target list would silently pass."
    )


def test_every_from_is_digest_pinned() -> None:
    """Every FROM target must carry ``@sha256:<64-hex>`` or be ``scratch``.

    Fails when a contributor bumps a base image tag but forgets the
    matching digest. Either form is acceptable:

      FROM python:3.12-slim@sha256:abc...      # tag + digest (preferred)
      FROM scratch                              # special pseudo-image
    """
    text = _service_dockerfile().read_text(encoding="utf-8")
    targets = _from_targets(text)

    unpinned: list[str] = []
    for target in targets:
        if target.strip().lower() == "scratch":
            continue
        if _DIGEST_PATTERN.search(target):
            continue
        unpinned.append(target)

    assert not unpinned, (
        f"services/api/Dockerfile has FROM directives without an "
        f"@sha256:<digest> pin: {unpinned!r}. "
        f"Run `docker pull <image>:<tag>` to capture the current digest "
        f"and append it as `@sha256:<digest>` to the FROM line."
    )
