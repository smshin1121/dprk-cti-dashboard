"""Regression test: every ``uses:`` action ref in a GHA workflow is pinned to ``@<40-hex commit SHA>``.

Catches the silent-drift class where a contributor adds (or rebases in)
a workflow step that references a third-party action by mutable tag
(``actions/checkout@v5``, ``astral-sh/setup-uv@v5``, etc.) and forgets
to capture the underlying commit SHA. A floating tag can be re-pointed
by the action owner — historically rare for big-name actions but
non-zero, and the tj-actions/changed-files supply-chain compromise of
March 2025 (CVE-2025-30066) demonstrated the concrete attack surface.

This test is the GHA-action companion to:

  - ``test_dockerfile_digest_pin.py`` (PR #48, per-service) — covers
    every ``FROM`` directive in any tracked ``Dockerfile``.
  - ``test_compose_image_digest_pin.py`` (PR #51) — covers every
    ``image:`` value in any ``docker-compose*.yml``.
  - ``test_gha_services_image_digest_pin.py`` (PR #52) — covers every
    ``jobs.<job>.services.<svc>.image`` value in any workflow YAML.

The CI sibling jobs cover the existence-gate half of each surface
(registry roundtrip via ``docker manifest inspect`` for image refs,
GitHub commit roundtrip via ``gh api repos/<owner>/<repo>/commits/<sha>``
for action refs). A new sibling ``gha-action-digest-resolve`` job in
this same PR closes the existence-gate for the GHA action surface.

Together the four test files + four CI jobs cover every supply-chain
entry point a base image OR a workflow step's third-party code takes
into the dev / CI / prod pipeline.

Refresh procedure when bumping an action major:

  1. Find the new tag's commit SHA:
     gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq '.object.sha,.object.type'
     # If type=tag (annotated), dereference once more:
     gh api repos/<owner>/<repo>/git/tags/<tag-sha> --jq '.object.sha'
  2. Replace ``uses: <action>@<old-sha>  # <old-tag>`` with the new
     ``<sha>  # <tag>`` pair across every ``uses:`` site.

Renovate with ``pinDigests: true`` is the recommended automation for
keeping these in sync — it generates the same ``@<sha>  # <tag>``
shape this test enforces. See ``followup_todos.md`` for the renovate
adoption follow-up.

Known limitation (acceptable trade-off):

  - Reusable workflows referenced via ``uses:`` at the JOB level
    (``uses: org/repo/.github/workflows/foo.yml@ref``) ARE checked
    by this test — they should also be pinned to a commit SHA. As of
    PR #53 this repo uses zero job-level ``uses:`` refs.
  - Local action references (``uses: ./.github/actions/foo``) are
    excluded — they live in this repo's tree and are not a third-
    party supply-chain concern.
  - Docker image action references (``uses: docker://<image>``) are
    excluded — they would be covered by an image-digest gate, not an
    action-tag gate.

Per ``pattern_layer_boundary_lock_via_static_source`` (PR #47 / #48 /
#49 / #50 / #51 / #52 lineage): mechanize the maintenance burden of
"remember to pin the SHA after a tag bump" as a CI gate so it cannot
silently drift.

Per ``pattern_service_local_duplication_over_shared``: the test lives
under ``services/api/`` because api is the closest semantic owner of
the GHA workflow surface — every job in this repo today touches an
api-rooted artifact (api code, api migrations, api E2E driver, api
contract verifier). Mirrors the placement decision made for
``test_gha_services_image_digest_pin.py`` (PR #52).

Path resolution: ``parents[4]`` from
``services/api/tests/unit/test_gha_action_digest_pin.py`` is the repo
root.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# Match a 40-character lowercase-hex commit SHA at the end of an
# ``@<sha>`` ref. Rejects ``@v5``, ``@main``, ``@1.2.3``, and any
# non-40-char hex.
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

_WORKFLOWS_DIR = Path(".github") / "workflows"


def _repo_root() -> Path:
    """Locate the repo root from this test file.

    Layout:
    ``<repo>/services/api/tests/unit/test_gha_action_digest_pin.py``
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
    return sorted(
        list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
    )


def _split_uses_ref(uses_value: str) -> tuple[str, str | None] | None:
    """Split a ``uses:`` value into ``(action, ref)`` or return ``None``
    if the value is not a third-party action reference subject to pinning.

    Excluded:
      - ``./<path>`` and ``../<path>`` — local action references in this repo
      - ``docker://<image>`` — image-shaped refs (different gate)
      - Empty / whitespace-only values
    """
    value = (uses_value or "").strip()
    if not value:
        return None
    if value.startswith("./") or value.startswith("../"):
        return None
    if value.startswith("docker://"):
        return None
    if "@" not in value:
        # No ref at all — GHA would reject at runtime; treat as
        # not-our-problem for the digest gate (different failure mode).
        return None
    action, _, ref = value.rpartition("@")
    return action, ref


def _collect_uses_refs(
    workflow_path: Path,
) -> list[tuple[str, str, str, str]]:
    """Return ``[(job_id, step_index_or_name, action, ref), ...]`` for
    every ``jobs.<job>.steps[*].uses`` (step-level) AND
    ``jobs.<job>.uses`` (job-level reusable workflow) value in the
    workflow.

    Local refs (``./...``) and ``docker://`` refs are filtered out.
    """
    raw = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    jobs = raw.get("jobs") or {}
    refs: list[tuple[str, str, str, str]] = []
    for job_id, job_spec in jobs.items():
        if not isinstance(job_spec, dict):
            continue
        # Job-level reusable workflow: ``jobs.<job>.uses``
        job_uses = job_spec.get("uses")
        if isinstance(job_uses, str):
            split = _split_uses_ref(job_uses)
            if split is not None:
                action, ref = split
                refs.append((job_id, "<job-level uses>", action, ref))
        # Step-level: ``jobs.<job>.steps[*].uses``
        steps = job_spec.get("steps") or []
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_uses = step.get("uses")
            if not isinstance(step_uses, str):
                continue
            split = _split_uses_ref(step_uses)
            if split is None:
                continue
            action, ref = split
            label = step.get("name") or f"step[{idx}]"
            refs.append((job_id, str(label), action, ref))
    return refs


def test_workflows_dir_exists() -> None:
    """Sanity check the path resolution math still finds the workflows dir."""
    root = _repo_root()
    path = root / _WORKFLOWS_DIR
    assert path.is_dir(), (
        f"expected workflows directory at {path}; the relative-path "
        f"math in _repo_root() may be wrong if the repo was restructured."
    )


def test_at_least_one_uses_ref_exists() -> None:
    """A repo with zero third-party ``uses:`` keys would silently pass the SHA assertion."""
    total: list[tuple[str, str, str, str, str]] = []
    for workflow_path in _workflow_files():
        for job_id, label, action, ref in _collect_uses_refs(workflow_path):
            total.append((workflow_path.name, job_id, label, action, ref))
    assert total, (
        "no third-party `uses:` references found across any workflow "
        "file. The SHA-pin assertion only protects what it sees — an "
        "empty ref list would silently pass."
    )


def test_every_gha_action_uses_ref_is_sha_pinned() -> None:
    """Every third-party ``uses:`` ref must carry ``@<40-hex commit SHA>``.

    Fails when a contributor adds ``uses: actions/checkout@v5`` (mutable
    tag), ``uses: actions/checkout@main`` (mutable branch), or
    ``uses: actions/checkout@1.2.3`` (semver-shaped, still mutable).

    Acceptable form:

      uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd  # v5
    """
    unpinned: list[tuple[str, str, str, str, str]] = []
    for workflow_path in _workflow_files():
        for job_id, label, action, ref in _collect_uses_refs(workflow_path):
            if _SHA_PATTERN.match(ref):
                continue
            unpinned.append(
                (workflow_path.name, job_id, label, action, ref)
            )

    assert not unpinned, (
        f"GHA `uses:` refs missing @<40-hex commit SHA> pin: "
        f"{unpinned!r}. Resolve via `gh api repos/<owner>/<repo>/git/"
        f"ref/tags/<tag> --jq '.object.sha,.object.type'` (and follow "
        f"the annotated-tag indirection if `type=tag`), then replace "
        f"`uses: <action>@<tag>` with `uses: <action>@<sha>  # <tag>`."
    )
