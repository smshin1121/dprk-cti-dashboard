"""Regression test: every ``image:`` under a GHA ``services:`` block is pinned to ``@sha256:<digest>``.

Catches the silent-drift class where a contributor bumps a workflow
service image tag (`pgvector/pgvector:pg16` → `pgvector/pgvector:pg17`,
`redis:7-alpine` → `redis:8-alpine`, etc.) and forgets to capture a
matching digest — producing "works on the runner I tried" supply-chain
drift between PR CI builds, post-merge main builds, and on-demand
``workflow_dispatch`` runs once the upstream tag moves.

This test is the GHA-services-block companion to:

  - ``test_dockerfile_digest_pin.py`` (PR #48, per-service) — covers
    every ``FROM`` directive in any tracked ``Dockerfile``.
  - ``test_compose_image_digest_pin.py`` (PR #51) — covers every
    ``image:`` value in any ``docker-compose*.yml``.

The CI sibling jobs (``dockerfile-digest-resolve`` from PR #49 +
``compose-image-digest-resolve`` from PR #51) cover the existence-gate
half of the same surface (registry roundtrip via
``docker manifest inspect``). A new sibling
``gha-services-image-digest-resolve`` job in this same PR closes the
existence-gate for the GHA ``services:`` surface.

Together the three test files + three CI jobs cover every supply-chain
entry point a base image takes into the dev / CI / prod pipeline.

Refresh procedure when bumping tags (mirrored from the PR #48 / #51
header comments):

  docker pull <image>:<new-tag>
  # capture the printed "Digest: sha256:..." line
  # replace the @sha256:... segment + bump the tag in lockstep

Known limitation (acceptable trade-off):

  - The test relies on parsing each workflow file as YAML and walking
    every job's ``services.<svc>.image`` value. Reusable workflows
    invoked via ``uses:`` are NOT followed — if a future workflow
    delegates to a ``.github/workflows/_reusable.yml`` that itself
    contains a ``services:`` block, that block IS scanned (because the
    glob picks up every ``.yml`` in ``.github/workflows/``). What this
    test does NOT scan: external reusable workflows referenced from
    other repos (``uses: org/repo/.github/workflows/foo.yml@ref``) —
    those live outside this repo's source tree and cannot be enforced
    here.

Per ``pattern_layer_boundary_lock_via_static_source`` (PR #47 / #48 /
#49 / #50 / #51 lineage): mechanize the maintenance burden of
"remember to pin the digest after a tag bump" as a CI gate so it
cannot silently drift.

Per ``pattern_service_local_duplication_over_shared``: the test lives
under ``services/api/`` because api is the closest semantic owner of
the GHA ``services:`` surface — every ``services:`` block in this
repo today exists to support an api-rooted job (api-tests not
needing one because it stubs PG; the PG/Redis service blocks all
support api-touching jobs: api-integration, contract-verify,
db-migrations, frontend-e2e, data-quality-tests,
correlation-perf-smoke).

Path resolution: ``parents[4]`` from
``services/api/tests/unit/test_gha_services_image_digest_pin.py`` is
the repo root.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}\b")

_WORKFLOWS_DIR = Path(".github") / "workflows"


def _repo_root() -> Path:
    """Locate the repo root from this test file.

    Layout:
    ``<repo>/services/api/tests/unit/test_gha_services_image_digest_pin.py``
    so ``parents[4]`` is ``<repo>``.
    """
    return Path(__file__).resolve().parents[4]


def _workflow_files() -> list[Path]:
    """Return every tracked workflow file under ``.github/workflows/``.

    Picks up both ``.yml`` and ``.yaml`` extensions so a future overlay
    using either suffix is enforced automatically.
    """
    root = _repo_root()
    workflows_dir = root / _WORKFLOWS_DIR
    if not workflows_dir.is_dir():
        return []
    files = sorted(
        list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
    )
    return files


def _collect_services_image_refs(
    workflow_path: Path,
) -> list[tuple[str, str, str]]:
    """Return ``[(job_id, service_name, image_ref), ...]`` for every
    ``jobs.<job>.services.<svc>.image`` value in the workflow.

    Skips jobs without a ``services:`` block, and services that omit an
    ``image:`` key (Docker Hub auto-uses default; not used in this
    repo today, but tolerant by design — the assertion only flags
    actual ``image:`` strings missing the digest).
    """
    raw = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    jobs = raw.get("jobs") or {}
    refs: list[tuple[str, str, str]] = []
    for job_id, job_spec in jobs.items():
        if not isinstance(job_spec, dict):
            continue
        services = job_spec.get("services") or {}
        if not isinstance(services, dict):
            continue
        for service_name, service_spec in services.items():
            if not isinstance(service_spec, dict):
                continue
            image_ref = service_spec.get("image")
            if isinstance(image_ref, str) and image_ref.strip():
                refs.append((job_id, service_name, image_ref.strip()))
    return refs


def test_workflows_dir_exists() -> None:
    """Sanity check the path resolution math still finds the workflows dir."""
    root = _repo_root()
    path = root / _WORKFLOWS_DIR
    assert path.is_dir(), (
        f"expected workflows directory at {path}; the relative-path "
        f"math in _repo_root() may be wrong if the repo was restructured."
    )


def test_at_least_one_services_image_ref_exists() -> None:
    """A repo with zero ``services.<svc>.image`` keys would silently pass the digest assertion."""
    total: list[tuple[str, str, str, str]] = []
    for workflow_path in _workflow_files():
        for job_id, service_name, image_ref in _collect_services_image_refs(
            workflow_path
        ):
            total.append((workflow_path.name, job_id, service_name, image_ref))
    assert total, (
        "no `services.<svc>.image` references found across any workflow "
        "file. The digest-pin assertion only protects what it sees — an "
        "empty ref list would silently pass."
    )


def test_every_gha_services_image_is_digest_pinned() -> None:
    """Every ``services.<svc>.image`` target must carry ``@sha256:<64-hex>`` (or be ``scratch``).

    Fails when a contributor bumps a service image tag but forgets the
    matching digest. Either form is acceptable:

      image: pgvector/pgvector:pg16@sha256:abc...    # tag + digest (preferred)
      image: scratch                                  # special pseudo-image
    """
    unpinned: list[tuple[str, str, str, str]] = []
    for workflow_path in _workflow_files():
        for job_id, service_name, image_ref in _collect_services_image_refs(
            workflow_path
        ):
            if image_ref.strip().lower() == "scratch":
                continue
            if _DIGEST_PATTERN.search(image_ref):
                continue
            unpinned.append(
                (workflow_path.name, job_id, service_name, image_ref)
            )

    assert not unpinned, (
        f"GHA `services.<svc>.image` references missing @sha256:<digest> "
        f"pin: {unpinned!r}. Run `docker pull <image>:<tag>` to capture "
        f"the current digest and append it as `@sha256:<digest>` to the "
        f"`image:` line."
    )
