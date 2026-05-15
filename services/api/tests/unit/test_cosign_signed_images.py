"""Format gate for data/cosign/signed-images.yml (PR #56 — signature gate layer 3).

Mirrors the static-source format-gate pattern from PR #48/#51/#52/#53/#54
(test_dockerfile_digest_pin.py, test_compose_image_digest_pin.py,
test_gha_services_image_digest_pin.py, test_gha_action_digest_pin.py,
test_renovate_config.py) per pattern_layer_boundary_lock_via_static_source.

Asserts about `data/cosign/signed-images.yml`:
- file exists, is valid YAML, has `version: 1`
- `images` is a list (may be EMPTY in Phase 1 — Docker Official Images do
  not publish Sigstore signatures today)
- each entry (when present) carries the required schema keys with valid
  types and value-domains
- `image` ref shape matches `<repo>:<tag>@sha256:<64hex>` (Docker manifest
  digest)
- `image` keys are globally unique (no duplicate entries pointing at the
  same image ref)
- `identity_match` is one of {`literal`, `regexp`}
- `tlog_mode` is exactly `required` (the only allowed value; `optional` is
  rejected per plan §4.5 anti-pattern — defeats Rekor anchoring)

Asserts about `.github/workflows/ci.yml`:
- the new `dockerfile-cosign-verify` job exists, sibling to
  `dockerfile-digest-resolve`
- `sigstore/cosign-installer@<40-hex>` SHA-pinned (matches PR #53 policy
  for all GHA action refs; will be enforced by `gha-action-digest-resolve`
  job once CI runs again)
- no forbidden flags in the job body. Initial set per plan §4.5:
  `--insecure-ignore-tlog`, `--allow-insecure-registry`. Extended after
  Codex r1 (2026-05-15): `--allow-http-registry`,
  `--private-infrastructure`, `--insecure-ignore-sct` (sourced from the
  upstream cosign verify CLI doc — sigstore/cosign repo)
- the Python allowlist parser inside the job is wrapped in an `if !`
  guard (NOT `done < <(python3 ...)` process-substitution) so a parser
  crash exit propagates under `set -euo pipefail` — borrowing the PR #55
  silent-pass class fix; the `cosign verify` calls themselves use `if !`
  + explicit exit-code capture, not bare `=$?`
- the runner reconciles `data/cosign/signed-images.yml` against current
  Dockerfile FROM refs (stale allowlist entries fail-loud; unlisted
  Dockerfile FROMs warn-not-fail per plan D3) — Codex r1 finding
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
ALLOWLIST_PATH = REPO_ROOT / "data" / "cosign" / "signed-images.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Docker manifest image-ref shape: <repo>:<tag>@sha256:<64-hex>.
# Repo may include registry host (e.g. cgr.dev/chainguard/python) and
# repo path separators; tag may include alphanumerics, `.`, `_`, `-`.
_IMAGE_REF_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/\-]*"        # registry host + repo path
    r":[A-Za-z0-9._\-]+"                    # tag
    r"@sha256:[0-9a-f]{64}$"                # digest
)

# Cosign-installer SHA-pin shape: 40-hex commit SHA after `@`.
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
    # `or []` would mask falsy non-list values (`0`, `False`, `""`); use
    # explicit None check so a malformed `images: 0` is caught by the
    # isinstance assert instead of vacuously skipping the per-entry tests.
    # R0 code-reviewer Finding 2.
    entries = cfg.get("images")
    if entries is None:
        entries = []
    assert isinstance(entries, list), (
        f"`images` must be a list (or null/missing => []); got {type(entries).__name__}"
    )
    return entries


def test_cosign_allowlist_exists_and_parses() -> None:
    cfg = _load_allowlist()
    assert "version" in cfg, (
        "allowlist must declare a top-level `version` key"
    )


def test_cosign_allowlist_version_is_1() -> None:
    cfg = _load_allowlist()
    assert cfg.get("version") == 1, (
        f"allowlist version must be 1 (Phase 1 schema); got {cfg.get('version')!r}. "
        "Bumping the version requires a corresponding plan update (PR #57+ may "
        "introduce a `surface:` discriminator)."
    )


def test_cosign_allowlist_images_is_list() -> None:
    cfg = _load_allowlist()
    images = cfg.get("images")
    # null/missing -> [] is acceptable for Phase 1 empty scaffold; an
    # explicit non-list value (e.g., a mapping or scalar) is a schema
    # violation that would crash the runner parser.
    assert images is None or isinstance(images, list), (
        f"`images` must be a list (or null/missing); got {type(images).__name__}"
    )


def test_cosign_allowlist_entries_have_required_keys() -> None:
    """Each entry (when present) must declare the full schema.

    Vacuously PASS on an empty Phase 1 allowlist; activates the moment
    the first entry is added.
    """
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


def test_cosign_allowlist_image_ref_format() -> None:
    """`image` field must be a fully-qualified `<repo>:<tag>@sha256:<64hex>` ref."""
    for idx, entry in enumerate(_entries()):
        image = entry.get("image", "")
        assert _IMAGE_REF_RE.match(image), (
            f"images[{idx}].image {image!r} does not match "
            f"`<repo>:<tag>@sha256:<64-hex>` shape. The signature gate must "
            f"verify against a content-addressed ref, not a mutable tag."
        )


def test_cosign_allowlist_no_duplicate_image_refs() -> None:
    """Two entries pointing at the same image ref is a schema bug.

    A future regexp/literal split should use distinct image refs (e.g.,
    one per upstream signer) — never two entries on the same ref.
    """
    seen: set[str] = set()
    for idx, entry in enumerate(_entries()):
        image = entry.get("image", "")
        assert image not in seen, (
            f"images[{idx}].image {image!r} duplicates an earlier entry. "
            f"Use one entry per image ref."
        )
        seen.add(image)


def test_cosign_allowlist_identity_match_in_allowed_set() -> None:
    """`identity_match` (optional, default `literal`) must be `literal` or `regexp`."""
    for idx, entry in enumerate(_entries()):
        mode = entry.get("identity_match", "literal")
        assert mode in ("literal", "regexp"), (
            f"images[{idx}].identity_match must be 'literal' or 'regexp'; "
            f"got {mode!r}. The job parser rejects any other value."
        )


def test_cosign_allowlist_tlog_mode_required() -> None:
    """`tlog_mode` (optional, default `required`) MUST be `required`.

    `optional` is forbidden per plan §4.5 anti-pattern: it allows the
    cosign verify call to succeed without a Rekor proof, defeating the
    transparency-log anchoring that is the whole point of keyless
    verification. Documented in the allowlist file header.
    """
    for idx, entry in enumerate(_entries()):
        mode = entry.get("tlog_mode", "required")
        assert mode == "required", (
            f"images[{idx}].tlog_mode must be 'required'; got {mode!r}. "
            f"`optional` defeats Rekor anchoring (plan §4.5 anti-pattern)."
        )


def test_cosign_allowlist_no_control_chars_in_string_fields() -> None:
    """Control chars in fields would mis-split the runner's TSV temp file.

    The runner refuses to scan when a field contains a TAB / LF / CR;
    mirror the same defensive guard here so the format gate fails at
    PR-time, not at CI-time on the next push. Extended from TAB-only
    per R0 security-reviewer Finding 4: PyYAML can produce embedded
    newlines from `"foo\nbar"` quoted scalars.
    """
    string_keys = ("image", "certificate_identity", "certificate_oidc_issuer")
    bad_chars = ("\t", "\n", "\r")
    for idx, entry in enumerate(_entries()):
        for key in string_keys:
            value = entry.get(key)
            if isinstance(value, str):
                for bad in bad_chars:
                    assert bad not in value, (
                        f"images[{idx}].{key} contains a literal {bad!r}; "
                        f"the runner refuses to scan rather than mis-split. "
                        f"Use a different value."
                    )


def test_cosign_allowlist_regexp_identity_must_be_anchored() -> None:
    """`identity_match: regexp` entries MUST anchor their pattern with `^...$`.

    Go's `regexp.MatchString` (which cosign uses for the regexp identity
    flag) is substring-matching by default. An unanchored pattern like
    `github.com/legitimate-org` matches `github.com/legitimate-org-evil`,
    allowing an attacker who controls a similar-named org to spoof the
    pinned publisher identity. R0 security-reviewer Finding 2.
    """
    for idx, entry in enumerate(_entries()):
        if entry.get("identity_match") != "regexp":
            continue
        identity = entry.get("certificate_identity", "")
        assert identity.startswith("^") and identity.endswith("$"), (
            f"images[{idx}]: regexp identity {identity!r} must be anchored "
            f"with ^...$ (substring matches allow identity spoofing). "
            f"Wrap with explicit anchors: `^{identity}$` if that's the "
            f"intended exact pattern."
        )


def test_cosign_allowlist_annotations_must_be_empty_in_phase1() -> None:
    """`annotations` field MUST be `{}` (or absent) until --annotations forwarding lands.

    The schema documents `annotations` as a future-policy hook, but the
    runner does not yet forward `--annotations key=value` to `cosign
    verify`. A non-empty annotations value would silently fail to be
    enforced. R0 security-reviewer Finding 3 — refuse-to-scan rather
    than silent skip.
    """
    for idx, entry in enumerate(_entries()):
        annotations = entry.get("annotations")
        # `None` (absent) and `{}` (empty dict) both pass.
        assert annotations in (None, {}), (
            f"images[{idx}].annotations is non-empty ({annotations!r}) but "
            f"the runner does not yet forward --annotations to cosign verify. "
            f"Implement runner support first, OR remove the field for now."
        )


def test_cosign_yaml_safe_load_anchor_alias_behavior_documented() -> None:
    """Regression: PyYAML safe_load expands `<<:` merge keys.

    A YAML allowlist with anchor+merge produces an entry whose final
    field values come from the anchor unless overridden inline. Our
    per-entry required-keys + non-empty-string check catches the case
    where the anchor leaves identity/issuer empty. R0 code-reviewer
    Finding 1: pin the assumption so a future PyYAML semantic change
    (or a switch to a stricter loader) is caught at PR-time.
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
    # PyYAML 6.x expands `<<: *base` so identity/issuer fields exist but
    # are empty. The runner's `if not (image and identity and issuer)`
    # check rejects this; document the expected behavior.
    assert entry.get("certificate_identity") == ""
    assert entry.get("certificate_oidc_issuer") == ""


# --- CI YAML format gate ---------------------------------------------------


def _ci_workflow_body() -> str:
    assert CI_WORKFLOW.exists(), f"missing {CI_WORKFLOW}"
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_has_dockerfile_cosign_verify_job() -> None:
    body = _ci_workflow_body()
    assert re.search(r"^\s*dockerfile-cosign-verify:\s*$", body, flags=re.MULTILINE), (
        "ci.yml must define a top-level `dockerfile-cosign-verify:` job "
        "(sibling to `dockerfile-digest-resolve`) per PR #56 plan §D4."
    )


def test_ci_cosign_installer_sha_pinned() -> None:
    """`sigstore/cosign-installer@<40-hex>` SHA-pinned (PR #53 policy)."""
    body = _ci_workflow_body()
    match = _COSIGN_INSTALLER_PIN_RE.search(body)
    assert match, (
        "ci.yml must pin `sigstore/cosign-installer@<40-hex commit SHA>` "
        "(matches PR #53's policy for all GHA action refs; enforced by "
        "the `gha-action-digest-resolve` existence-gate job)."
    )
    sha = match.group(1)
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), (
        f"cosign-installer pin {sha!r} must be a 40-char lowercase hex SHA"
    )


@pytest.mark.parametrize(
    "forbidden_flag",
    [
        # Plan §4.5 explicit anti-patterns (initial list).
        "--insecure-ignore-tlog",
        "--allow-insecure-registry",
        # Extended after Codex r1 (2026-05-15) flagged the upstream cosign
        # verify CLI surface: any of these flags weakens the signature /
        # tlog / registry guarantees the gate is meant to enforce.
        # Sourced from https://github.com/sigstore/cosign/blob/main/doc/cosign_verify.md.
        "--allow-http-registry",          # allow plain HTTP to registries
        "--private-infrastructure",       # skip tlog verification for private deploys
        "--insecure-ignore-sct",          # skip embedded-SCT (CT log inclusion proof) check
    ],
)
def test_ci_cosign_no_forbidden_flags(forbidden_flag: str) -> None:
    """Plan §4.5 anti-pattern: defeating tlog / sct / registry validation is forbidden."""
    body = _ci_workflow_body()
    assert forbidden_flag not in body, (
        f"ci.yml must NOT pass `{forbidden_flag}` to cosign verify. "
        f"It defeats one of: Rekor transparency log anchoring, "
        f"CT log inclusion proof, or registry TLS validation "
        f"(plan §4.5 anti-pattern; Codex r1 extended set)."
    )


def test_ci_cosign_job_reconciles_allowlist_vs_dockerfile_from() -> None:
    """Per Codex r1 (2026-05-15): runner must reconcile allowlist refs with current Dockerfile FROMs.

    Without reconciliation, a stale allowlist entry (image no longer used)
    silently verifies green, and a Dockerfile FROM that has no allowlist
    entry is never flagged. Both classes break plan §5 "Allowlist drift"
    risk row intent. Stale entries fail-loud (policy contract); unlisted
    FROMs warn (plan D3 long-tail policy).
    """
    body = _ci_workflow_body()
    match = re.search(
        r"^  dockerfile-cosign-verify:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*\n|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "could not isolate dockerfile-cosign-verify job body"
    job_body = match.group(1)

    # Positive 1: reconciliation enumerates current Dockerfile FROM refs.
    assert "Path(\".\").glob(\"**/Dockerfile\")" in job_body or \
           "Path('.').glob('**/Dockerfile')" in job_body, (
        "dockerfile-cosign-verify job must enumerate Dockerfile paths "
        "(via Path.glob '**/Dockerfile') for allowlist↔Dockerfile reconciliation."
    )

    # Positive 2: stale-entry fail-loud branch present (allowlist - dockerfile).
    assert "stale" in job_body and "allowlist_refs - dockerfile_refs" in job_body, (
        "dockerfile-cosign-verify job must fail-loud on stale allowlist "
        "entries (refs in allowlist that no current Dockerfile FROM uses)."
    )

    # Positive 3: unlisted-FROM warn (dockerfile - allowlist).
    assert "WARN:" in job_body and "dockerfile_refs - allowlist_refs" in job_body, (
        "dockerfile-cosign-verify job must WARN (not fail) on Dockerfile "
        "FROM refs that are not in the cosign allowlist (plan D3 long-tail)."
    )


def test_ci_cosign_job_uses_if_bang_guard_not_process_substitution() -> None:
    """Plan §4.5 + PR #55 lesson: avoid `done < <(python3 ...)` silent-pass class.

    The dockerfile-cosign-verify job parses the allowlist via Python; the
    `if ! python3 ... <<'PY' ... PY then ... fi` form is the only set-e-
    safe shape per `pattern_silent_to_loud_failure_conversion`.
    """
    body = _ci_workflow_body()
    # Carve out just the dockerfile-cosign-verify job body so we don't
    # accidentally inspect sibling jobs.
    match = re.search(
        r"^  dockerfile-cosign-verify:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*\n|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "could not isolate dockerfile-cosign-verify job body"
    job_body = match.group(1)

    # Negative: process-substitution against the allowlist parser is forbidden.
    assert "done < <(python3" not in job_body, (
        "dockerfile-cosign-verify job uses `done < <(python3 ...)` "
        "process-substitution — forbidden (PR #55 silent-pass class). "
        "Use `if ! python3 ... <<'PY' ... PY then ... fi` instead."
    )
    # Positive: must contain the `if !` guard around the parser invocation.
    assert re.search(r"if\s+!\s+python3\s", job_body), (
        "dockerfile-cosign-verify job must wrap the Python parser in an "
        "`if !` guard so a parser crash propagates under `set -euo pipefail` "
        "(pattern_silent_to_loud_failure_conversion)."
    )
