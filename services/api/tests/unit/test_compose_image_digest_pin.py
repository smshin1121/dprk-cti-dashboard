"""Regression test: every ``image:`` in ``docker-compose.yml`` is pinned to ``@sha256:<digest>``.

Catches the silent-drift class where a contributor bumps a compose
service image tag (`postgres:16` → `postgres:17`, `redis:7-alpine` →
`redis:8-alpine`, etc.) and forgets to capture a matching digest —
producing "works on my machine" supply-chain drift between local
builds, CI builds, and production rebuilds when the upstream tag
moves.

This test is the compose-level companion to the Dockerfile-level
`test_dockerfile_digest_pin.py` (PR #48) and the CI gate
`dockerfile-digest-resolve` (PR #49). Together they cover all four
ways a base image enters the dev / CI / prod pipeline:

  - `FROM <ref>` in any tracked Dockerfile → PR #48 unit tests +
    PR #49 CI manifest-resolve job
  - `image: <ref>` in `docker-compose.yml` → THIS test (format gate)
    + PR #51 CI manifest-resolve job (existence gate)

The test is intentionally lenient about exact image / tag / platform
syntax — it parses every `image:` mapping value and asserts the
reference contains an ``@sha256:<64-hex>`` segment. ``image: scratch``
is explicitly allowed (scratch is a pseudo-image with no content to
pin), though no service in this repo uses it.

Refresh procedure when bumping tags (mirrored from the PR #48 Dockerfile
header comments):

  docker pull <image>:<new-tag>
  # capture the printed "Digest: sha256:..." line
  # replace the @sha256:... segment + bump the tag in lockstep

Known limitation (acceptable trade-off):

  - The test relies on parsing ``docker-compose.yml`` as YAML and
    walking every service's ``image:`` value. If a future overlay
    file (e.g. ``docker-compose.smoke.yml`` introduces an ``image:``,
    or someone adds a new overlay) is not picked up here, that
    overlay's pins would not be enforced. Today this repo has one
    overlay (``docker-compose.smoke.yml``) which contains no
    ``image:`` keys — verified by the test's scan-all-compose-files
    helper. If a future PR adds compose overlays with ``image:``
    keys, extend this test.

Per ``pattern_layer_boundary_lock_via_static_source`` (PR #47 / #48
/ #49 / #50 lineage): mechanize the maintenance burden of "remember to
pin the digest after a tag bump" as a CI gate so it cannot silently
drift.

Path resolution: ``parents[4]`` from
``services/api/tests/unit/test_compose_image_digest_pin.py`` is the
repo root.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}\b")

# Compose files known today. Add to this tuple if a new overlay with
# ``image:`` keys is introduced. The test's docstring "Known limitation"
# note explains the convention.
_COMPOSE_FILES: tuple[str, ...] = (
    "docker-compose.yml",
    "docker-compose.smoke.yml",
)


def _repo_root() -> Path:
    """Locate the repo root from this test file.

    Layout: ``<repo>/services/api/tests/unit/test_compose_image_digest_pin.py``
    so ``parents[4]`` is ``<repo>``.
    """
    return Path(__file__).resolve().parents[4]


def _collect_image_refs(compose_path: Path) -> list[tuple[str, str]]:
    """Return ``[(service_name, image_ref), ...]`` for every
    ``services.<svc>.image`` value in the compose file.

    Skips services that build from a local Dockerfile (no ``image:``
    key) — those are covered by ``test_dockerfile_digest_pin.py``.
    """
    raw = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    services = raw.get("services") or {}
    refs: list[tuple[str, str]] = []
    for service_name, service_spec in services.items():
        if not isinstance(service_spec, dict):
            continue
        image_ref = service_spec.get("image")
        if isinstance(image_ref, str) and image_ref.strip():
            refs.append((service_name, image_ref.strip()))
    return refs


def test_compose_files_exist() -> None:
    """Sanity check the path resolution math still finds the compose files."""
    root = _repo_root()
    for filename in _COMPOSE_FILES:
        path = root / filename
        assert path.is_file(), (
            f"expected compose file at {path}; the relative-path math "
            f"in _repo_root() may be wrong if the repo was restructured."
        )


def test_at_least_one_image_ref_exists() -> None:
    """A repo with zero ``image:`` keys would silently pass the digest assertion."""
    root = _repo_root()
    total: list[tuple[str, str, str]] = []
    for filename in _COMPOSE_FILES:
        for service_name, image_ref in _collect_image_refs(root / filename):
            total.append((filename, service_name, image_ref))
    assert total, (
        "no `image:` references found across any compose file. The "
        "digest-pin assertion only protects what it sees — an empty "
        "ref list would silently pass."
    )


def test_every_compose_image_is_digest_pinned() -> None:
    """Every ``image:`` target must carry ``@sha256:<64-hex>`` (or be ``scratch``).

    Fails when a contributor bumps a compose image tag but forgets the
    matching digest. Either form is acceptable:

      image: postgres:16@sha256:abc...      # tag + digest (preferred)
      image: scratch                         # special pseudo-image
    """
    root = _repo_root()
    unpinned: list[tuple[str, str, str]] = []
    for filename in _COMPOSE_FILES:
        for service_name, image_ref in _collect_image_refs(root / filename):
            if image_ref.strip().lower() == "scratch":
                continue
            if _DIGEST_PATTERN.search(image_ref):
                continue
            unpinned.append((filename, service_name, image_ref))

    assert not unpinned, (
        f"compose `image:` references missing @sha256:<digest> pin: "
        f"{unpinned!r}. Run `docker pull <image>:<tag>` to capture "
        f"the current digest and append it as `@sha256:<digest>` to "
        f"the `image:` line."
    )
