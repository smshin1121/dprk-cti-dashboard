"""Format gate for renovate.json + .github/workflows/renovate.yml.

Mirrors the static-source format-gate pattern from PR #48/#51/#52/#53
(test_dockerfile_digest_pin.py, test_compose_image_digest_pin.py,
test_gha_services_image_digest_pin.py, test_gha_action_digest_pin.py)
per pattern_two_layer_defense_for_addressable_refs.

Asserts:
- renovate.json exists, is valid JSON, has expected keys
- enabledManagers locks scope to github-actions ONLY (defensive against
  scope creep into compose/Dockerfile/pyproject; those surfaces have
  their own existence gates and aren't yet ready for renovate-driven
  updates)
- pinDigests is true (the whole reason for adoption)
- automerge is false initially (manual review required for first cycle)
- dependencyDashboard is enabled (single tracking issue for visibility)
- PR throttling is set (prevents Renovate's first run from opening many
  PRs simultaneously)
- Renovate workflow file exists with action SHAs pinned (matches the
  repo's own supply-chain policy from PR #53)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RENOVATE_JSON = REPO_ROOT / "renovate.json"
RENOVATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "renovate.yml"


def _load_renovate_json() -> dict:
    assert RENOVATE_JSON.exists(), f"missing {RENOVATE_JSON}"
    return json.loads(RENOVATE_JSON.read_text(encoding="utf-8"))


def test_renovate_json_exists_and_parses():
    cfg = _load_renovate_json()
    assert isinstance(cfg, dict), "renovate.json must be a JSON object"


def test_renovate_config_locked_to_github_actions_only():
    cfg = _load_renovate_json()
    managers = cfg.get("enabledManagers")
    assert managers == ["github-actions"], (
        f"enabledManagers must be exactly ['github-actions'] to lock scope; "
        f"got {managers!r}. Expanding to compose/Dockerfile/pyproject "
        f"requires a separate PR with discuss-phase per "
        f"pattern_two_layer_defense_for_addressable_refs."
    )


def test_renovate_config_pin_digests_true():
    cfg = _load_renovate_json()
    assert cfg.get("pinDigests") is True, (
        "pinDigests must be true — the whole reason for adopting Renovate "
        "(matches PR #53's manual @<commit SHA> pinning of all GHA action refs)."
    )


def test_renovate_config_no_automerge_initially():
    cfg = _load_renovate_json()
    # PR #54 R2 LOW-1 closure (2026-05-15): belt-and-suspenders requires
    # `automerge: false` to be EXPLICITLY pinned at BOTH root + every
    # packageRule level — not merely defaulted via .get(..., False). The
    # explicit-presence pin documents intent + survives a future config
    # rewrite that might silently drop the field, relying on the runtime
    # default. Use `in` membership checks (not .get) to assert presence.
    assert "automerge" in cfg, (
        "renovate.json: top-level `automerge` MUST be explicitly set to `false`. "
        "Renovate's runtime default is already false, but explicit-pin documents "
        "intent and prevents silent drift if a future config edit drops the field."
    )
    assert cfg["automerge"] is False, (
        f"automerge must be false initially; got {cfg['automerge']!r}. "
        "Enabling automerge requires a separate PR after cadence is proven stable."
    )
    rules = cfg.get("packageRules", [])
    assert rules, (
        "renovate.json: packageRules MUST exist with the duplicate `automerge: false` "
        "pin (belt-and-suspenders defense per PR #54 R2 LOW-1)."
    )
    for rule in rules:
        assert "automerge" in rule, (
            f"packageRule missing EXPLICIT `automerge` key: {rule!r}. Belt-and-"
            "suspenders requires the duplicate pin at every packageRule level too."
        )
        assert rule["automerge"] is False, (
            f"packageRule has automerge=true: {rule!r}. Forbidden initially."
        )


def test_renovate_config_dependency_dashboard_enabled():
    cfg = _load_renovate_json()
    assert cfg.get("dependencyDashboard") is True, (
        "dependencyDashboard must be true — single tracking issue for visibility."
    )


def test_renovate_config_pr_throttling_set():
    cfg = _load_renovate_json()
    hourly = cfg.get("prHourlyLimit")
    concurrent = cfg.get("prConcurrentLimit")
    assert isinstance(hourly, int) and hourly > 0, (
        f"prHourlyLimit must be a positive int; got {hourly!r}"
    )
    assert isinstance(concurrent, int) and concurrent > 0, (
        f"prConcurrentLimit must be a positive int; got {concurrent!r}"
    )


def test_renovate_workflow_pins_all_actions_to_sha():
    assert RENOVATE_WORKFLOW.exists(), f"missing {RENOVATE_WORKFLOW}"
    body = RENOVATE_WORKFLOW.read_text(encoding="utf-8")

    bare_refs = re.findall(
        r"^\s*-?\s*(?:name:.*\n\s*)?uses:\s*([^\s@]+)@([^\s#]+)",
        body,
        flags=re.MULTILINE,
    )
    assert bare_refs, "renovate.yml has no `uses:` action references"

    sha_re = re.compile(r"^[0-9a-f]{40}$")
    for action, ref in bare_refs:
        assert sha_re.match(ref), (
            f"renovate.yml: action {action} is pinned to {ref!r} which is "
            f"NOT a 40-hex commit SHA. Matches PR #53's policy for all "
            f"GHA action refs (pattern_two_layer_defense_for_addressable_refs)."
        )


def test_renovate_workflow_has_least_privilege_permissions():
    body = RENOVATE_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^permissions:", body, flags=re.MULTILINE), (
        "renovate.yml must declare explicit `permissions:` block "
        "(matches PR #53 R0 sibling-permissions convergent-LOW fold)."
    )
    # Positive: each required permission must be at the exact value Renovate
    # needs (downgrading silently breaks the workflow without failing the
    # mere-presence check above).
    for perm, value in (
        ("contents", "write"),       # required to push the Renovate feature branch
        ("pull-requests", "write"),  # required to open the PR
        ("issues", "write"),         # required for dependencyDashboard issue
    ):
        assert re.search(rf"^\s*{re.escape(perm)}:\s*{value}\b", body, flags=re.MULTILINE), (
            f"renovate.yml: `permissions.{perm}` must be set to `{value}` "
            f"(downgrading silently breaks Renovate)."
        )
    # Negative: scopes Renovate must NOT acquire (defensive against scope
    # creep that would expand the GITHUB_TOKEN blast radius beyond what
    # the digest-pin automation actually needs).
    # `attestations` + `models` added 2026-05-15 per PR #54 R2 security Q8
    # follow-up: both are GHA token scopes that became available with
    # newer GitHub Actions tokens; Renovate's digest-pin automation has
    # no legitimate use for either, so explicitly forbid.
    for forbidden in (
        "security-events",
        "packages",
        "id-token",
        "deployments",
        "actions",
        "attestations",
        "models",
    ):
        assert not re.search(rf"^\s*{re.escape(forbidden)}:", body, flags=re.MULTILINE), (
            f"renovate.yml: `permissions.{forbidden}` is forbidden — Renovate's "
            f"digest-pin automation never needs this scope. If you genuinely "
            f"need it, update this test with a rationale."
        )
