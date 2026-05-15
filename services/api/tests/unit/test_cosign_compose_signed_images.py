"""Format gate for data/cosign/signed-images-compose.yml (PR #57 — signature gate layer 3, compose surface).

Mirrors the static-source format-gate pattern from PR #48/#51/#52/#53/#54/#56
(test_dockerfile_digest_pin.py, test_compose_image_digest_pin.py,
test_gha_services_image_digest_pin.py, test_gha_action_digest_pin.py,
test_renovate_config.py, test_cosign_signed_images.py) per
pattern_layer_boundary_lock_via_static_source.

Asserts about `data/cosign/signed-images-compose.yml`:
- file exists, is valid YAML, has `version: 1`
- `images` is a list (may be EMPTY in Phase 2 — no compose image ref is
  signed by its upstream publisher today)
- each entry (when present) carries the required schema keys with valid
  types and value-domains (parity with PR #56's allowlist)
- `image` ref shape matches `<repo>:<tag>@sha256:<64hex>`
- `image` keys are globally unique
- `identity_match` is one of {`literal`, `regexp`}; regexp identities
  MUST be anchored `^...$` (carry-forward from PR #56 R0 finding)
- `tlog_mode` is exactly `required`
- `annotations` is empty `{}` or absent (carry-forward from PR #56 R0)
- no control chars (TAB / LF / CR) in any string field

Asserts about `.github/workflows/ci.yml`:
- the new `compose-cosign-verify` job exists, sibling to
  `compose-image-digest-resolve`
- `sigstore/cosign-installer@<40-hex>` SHA-pinned (PR #53 policy)
- no forbidden flags in the job body. Same 5-flag denylist as PR #56:
  `--insecure-ignore-tlog`, `--allow-insecure-registry`,
  `--allow-http-registry`, `--private-infrastructure`,
  `--insecure-ignore-sct`
- the Python allowlist parser inside the job is wrapped in an `if !`
  guard (NOT process-substitution) so a parser crash propagates under
  `set -euo pipefail`
- the runner reconciles `data/cosign/signed-images-compose.yml` against
  current docker-compose*.yml `services.<svc>.image:` refs (stale
  allowlist entries fail-loud; unlisted compose refs warn-not-fail per
  plan D3) — Codex r1 finding carry-forward from PR #56
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
ALLOWLIST_PATH = REPO_ROOT / "data" / "cosign" / "signed-images-compose.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

_IMAGE_REF_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/\-]*"
    r":[A-Za-z0-9._\-]+"
    r"@sha256:[0-9a-f]{64}$"
)

_COSIGN_INSTALLER_PIN_RE = re.compile(
    r"uses:\s*sigstore/cosign-installer@([0-9a-f]{40})\b"
)


def _load_allowlist() -> dict:
    assert ALLOWLIST_PATH.exists(), f"missing {ALLOWLIST_PATH}"
    parsed = yaml.safe_load(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), (
        f"{ALLOWLIST_PATH} must parse to a YAML mapping at the top level"
    )
    return parsed


def _entries() -> list[dict]:
    cfg = _load_allowlist()
    # Explicit None check (NOT `or []`) so a falsy non-list `images:` value
    # is caught by the isinstance assert rather than vacuously skipped.
    # Carry-forward from PR #56 R0 code-reviewer Finding 2.
    entries = cfg.get("images")
    if entries is None:
        entries = []
    assert isinstance(entries, list), (
        f"`images` must be a list (or null/missing => []); got {type(entries).__name__}"
    )
    return entries


def test_cosign_compose_allowlist_exists_and_parses() -> None:
    cfg = _load_allowlist()
    assert "version" in cfg, "allowlist must declare a top-level `version` key"


def test_cosign_compose_allowlist_version_is_1() -> None:
    cfg = _load_allowlist()
    assert cfg.get("version") == 1, (
        f"allowlist version must be 1 (Phase 2 schema); got {cfg.get('version')!r}. "
        "Bumping the version requires a corresponding plan update."
    )


def test_cosign_compose_allowlist_images_is_list() -> None:
    cfg = _load_allowlist()
    images = cfg.get("images")
    assert images is None or isinstance(images, list), (
        f"`images` must be a list (or null/missing); got {type(images).__name__}"
    )


def test_cosign_compose_allowlist_entries_have_required_keys() -> None:
    """Each entry (when present) must declare the full schema. Vacuously PASS on empty."""
    required_keys = {"image", "certificate_identity", "certificate_oidc_issuer"}
    for idx, entry in enumerate(_entries()):
        assert isinstance(entry, dict), (
            f"images[{idx}] must be a mapping; got {type(entry).__name__}"
        )
        missing = required_keys - set(entry.keys())
        assert not missing, (
            f"images[{idx}] missing required keys: {sorted(missing)}; got {entry!r}"
        )
        for key in required_keys:
            value = entry[key]
            assert isinstance(value, str) and value.strip(), (
                f"images[{idx}].{key} must be a non-empty string; got {value!r}"
            )


def test_cosign_compose_allowlist_image_ref_format() -> None:
    for idx, entry in enumerate(_entries()):
        image = entry.get("image", "")
        assert _IMAGE_REF_RE.match(image), (
            f"images[{idx}].image {image!r} does not match "
            f"`<repo>:<tag>@sha256:<64-hex>` shape."
        )


def test_cosign_compose_allowlist_no_duplicate_image_refs() -> None:
    seen: set[str] = set()
    for idx, entry in enumerate(_entries()):
        image = entry.get("image", "")
        assert image not in seen, (
            f"images[{idx}].image {image!r} duplicates an earlier entry."
        )
        seen.add(image)


def test_cosign_compose_allowlist_identity_match_in_allowed_set() -> None:
    for idx, entry in enumerate(_entries()):
        mode = entry.get("identity_match", "literal")
        assert mode in ("literal", "regexp"), (
            f"images[{idx}].identity_match must be 'literal' or 'regexp'; got {mode!r}."
        )


def test_cosign_compose_allowlist_tlog_mode_required() -> None:
    """`tlog_mode` MUST be `required`. `optional` is forbidden (defeats Rekor anchoring)."""
    for idx, entry in enumerate(_entries()):
        mode = entry.get("tlog_mode", "required")
        assert mode == "required", (
            f"images[{idx}].tlog_mode must be 'required'; got {mode!r}."
        )


def test_cosign_compose_allowlist_no_control_chars_in_string_fields() -> None:
    """TAB / LF / CR in string fields would mis-split the runner's TSV temp file."""
    string_keys = ("image", "certificate_identity", "certificate_oidc_issuer")
    bad_chars = ("\t", "\n", "\r")
    for idx, entry in enumerate(_entries()):
        for key in string_keys:
            value = entry.get(key)
            if isinstance(value, str):
                for bad in bad_chars:
                    assert bad not in value, (
                        f"images[{idx}].{key} contains a literal {bad!r}; "
                        f"the runner refuses to scan rather than mis-split."
                    )


def test_cosign_compose_allowlist_regexp_identity_must_be_anchored() -> None:
    """`identity_match: regexp` entries MUST anchor pattern with `^...$`.

    Go's `regexp.MatchString` is substring-matching by default; an unanchored
    pattern allows identity spoofing. Carry-forward from PR #56 R0 finding.
    """
    for idx, entry in enumerate(_entries()):
        if entry.get("identity_match") != "regexp":
            continue
        identity = entry.get("certificate_identity", "")
        assert identity.startswith("^") and identity.endswith("$"), (
            f"images[{idx}]: regexp identity {identity!r} must be anchored with ^...$."
        )


def test_cosign_compose_allowlist_annotations_must_be_empty_in_phase2() -> None:
    """`annotations` MUST be `{}` (or absent) until --annotations forwarding lands.

    Carry-forward from PR #56 R0 security-reviewer Finding 3 — refuse-to-scan
    rather than silent skip.
    """
    for idx, entry in enumerate(_entries()):
        annotations = entry.get("annotations")
        assert annotations in (None, {}), (
            f"images[{idx}].annotations is non-empty ({annotations!r}) but "
            f"the runner does not yet forward --annotations to cosign verify."
        )


def test_cosign_compose_yaml_safe_load_anchor_alias_behavior_documented() -> None:
    """Regression: PyYAML safe_load expands `<<:` merge keys.

    Carry-forward from PR #56 R0 code-reviewer Finding 1. Document the
    assumption so a future PyYAML semantic change is caught at PR-time.
    """
    raw = (
        "version: 1\n"
        "_anchors:\n"
        "  base: &base\n"
        "    certificate_identity: \"\"\n"
        "    certificate_oidc_issuer: \"\"\n"
        "images:\n"
        f"  - image: example.com/repo:tag@sha256:{'0' * 64}\n"
        "    <<: *base\n"
    )
    cfg = yaml.safe_load(raw)
    entries = cfg["images"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.get("certificate_identity") == ""
    assert entry.get("certificate_oidc_issuer") == ""


# --- CI YAML format gate ---------------------------------------------------


def _ci_workflow_body() -> str:
    assert CI_WORKFLOW.exists(), f"missing {CI_WORKFLOW}"
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_has_compose_cosign_verify_job() -> None:
    body = _ci_workflow_body()
    assert re.search(r"^\s*compose-cosign-verify:\s*$", body, flags=re.MULTILINE), (
        "ci.yml must define a top-level `compose-cosign-verify:` job "
        "(sibling to `compose-image-digest-resolve`) per PR #57 plan §D4."
    )


def test_ci_compose_cosign_installer_sha_pinned() -> None:
    """`sigstore/cosign-installer@<40-hex>` SHA-pinned (PR #53 policy)."""
    body = _ci_workflow_body()
    match = _COSIGN_INSTALLER_PIN_RE.search(body)
    assert match, (
        "ci.yml must pin `sigstore/cosign-installer@<40-hex commit SHA>`."
    )
    sha = match.group(1)
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), (
        f"cosign-installer pin {sha!r} must be a 40-char lowercase hex SHA"
    )


@pytest.mark.parametrize(
    "forbidden_flag",
    [
        "--insecure-ignore-tlog",
        "--allow-insecure-registry",
        "--allow-http-registry",
        "--private-infrastructure",
        "--insecure-ignore-sct",
    ],
)
def test_ci_compose_cosign_no_forbidden_flags(forbidden_flag: str) -> None:
    """Plan §4.5 anti-pattern: defeating tlog / sct / registry validation is forbidden.

    Asserted against the WHOLE ci.yml body (not just this job) because any
    surface adding these flags weakens the supply-chain posture. PR #57
    inherits PR #56's 5-flag denylist verbatim.
    """
    body = _ci_workflow_body()
    assert forbidden_flag not in body, (
        f"ci.yml must NOT pass `{forbidden_flag}` to cosign verify. "
        f"It defeats one of: Rekor transparency log anchoring, CT log "
        f"inclusion proof, or registry TLS validation."
    )


def test_ci_compose_cosign_job_reconciles_allowlist_vs_compose_image_refs() -> None:
    """The runner reconciles allowlist refs vs current docker-compose `image:` refs.

    Stale allowlist entries (image no longer used in any compose file) MUST
    fail-loud; unlisted compose refs (current ref, no allowlist entry) MUST
    warn (plan D3 long-tail policy). Mirrors PR #56's dockerfile reconciliation.
    """
    body = _ci_workflow_body()
    match = re.search(
        r"^  compose-cosign-verify:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*\n|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "could not isolate compose-cosign-verify job body"
    job_body = match.group(1)

    # Positive 1: reconciliation enumerates current compose paths.
    assert (
        "Path(\".\").glob(\"docker-compose*.yml\")" in job_body
        or "Path('.').glob('docker-compose*.yml')" in job_body
        or "Path(\".\").glob(\"docker-compose*.yaml\")" in job_body
        or "Path('.').glob('docker-compose*.yaml')" in job_body
    ), (
        "compose-cosign-verify job must enumerate docker-compose*.yml / .yaml "
        "paths for allowlist↔compose reconciliation."
    )

    # Positive 2: stale-entry fail-loud branch present (allowlist - compose).
    assert "stale" in job_body and "allowlist_refs - compose_refs" in job_body, (
        "compose-cosign-verify job must fail-loud on stale allowlist entries "
        "(refs in allowlist that no current compose image: uses)."
    )

    # Positive 3: unlisted-compose WARN (compose - allowlist).
    assert "WARN:" in job_body and "compose_refs - allowlist_refs" in job_body, (
        "compose-cosign-verify job must WARN (not fail) on compose image: refs "
        "that are not in the cosign compose allowlist."
    )


def test_ci_compose_cosign_job_uses_if_bang_guard_not_process_substitution() -> None:
    """Plan §4.5: avoid `done < <(python3 ...)` silent-pass class (PR #55 lesson).

    The compose-cosign-verify job parses the allowlist via Python; the
    `if ! python3 ... <<'PY' ... PY then ... fi` form is the only set-e-
    safe shape.
    """
    body = _ci_workflow_body()
    match = re.search(
        r"^  compose-cosign-verify:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*\n|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "could not isolate compose-cosign-verify job body"
    job_body = match.group(1)

    assert "done < <(python3" not in job_body, (
        "compose-cosign-verify job uses process-substitution against the "
        "Python parser — forbidden (PR #55 silent-pass class)."
    )
    assert re.search(r"if\s+!\s+python3\s", job_body), (
        "compose-cosign-verify job must wrap the Python parser in an "
        "`if !` guard so a parser crash propagates under `set -euo pipefail`."
    )
