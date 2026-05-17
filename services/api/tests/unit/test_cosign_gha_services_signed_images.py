"""Format gate for data/cosign/signed-images-gha-services.yml (PR #61 — signature gate layer 3, GHA-services surface).

Mirrors the static-source format-gate pattern from PR #48/#51/#52/#53/#54/#56/#57
(test_dockerfile_digest_pin.py, test_compose_image_digest_pin.py,
test_gha_services_image_digest_pin.py, test_gha_action_digest_pin.py,
test_renovate_config.py, test_cosign_signed_images.py,
test_cosign_compose_signed_images.py) per
pattern_layer_boundary_lock_via_static_source.

Asserts about `data/cosign/signed-images-gha-services.yml`:
- file exists, is valid YAML, has `version: 1`
- `images` is a list (may be EMPTY in Phase 3 — no GHA services image ref is
  signed by its upstream publisher today)
- each entry (when present) carries the required schema keys with valid
  types and value-domains (parity with PR #56/#57 allowlists)
- `image` ref shape matches `<repo>:<tag>@sha256:<64hex>`
- `image` keys are globally unique
- `identity_match` is one of {`literal`, `regexp`}; regexp identities
  MUST be anchored `^...$` (carry-forward from PR #56 R0 finding)
- `tlog_mode` is exactly `required`
- `annotations` is empty `{}` or absent (carry-forward from PR #56 R0)
- no control chars (TAB / LF / CR) in any string field
- `certificate_oidc_issuer` is in `_KNOWN_OIDC_ISSUERS` (PR #60 cycle-14 cleanup)

Asserts about `.github/workflows/ci.yml`:
- the new `gha-services-cosign-verify` job exists, sibling to
  `gha-services-image-digest-resolve`
- `sigstore/cosign-installer@<40-hex>` SHA-pinned (PR #53 policy)
- cosign-installer SHA equality across all cosign-verify jobs (PR #60 F1
  carry-forward + cross-phase invariant test)
- no forbidden flags in the job body. Same 5-flag denylist as PR #56/#57:
  `--insecure-ignore-tlog`, `--allow-insecure-registry`,
  `--allow-http-registry`, `--private-infrastructure`,
  `--insecure-ignore-sct`
- the Python allowlist parser inside the job is wrapped in an `if !`
  guard (NOT process-substitution) so a parser crash propagates under
  `set -euo pipefail`
- the runner reconciles `data/cosign/signed-images-gha-services.yml`
  against current `.github/workflows/*.yml` `jobs.<job>.services.<svc>.image:`
  refs (stale allowlist entries fail-loud; unlisted GHA-services refs
  warn-not-fail per plan D3) — Codex r1 finding carry-forward from PR #56/#57

NEW in PR #61 (Codex r1 spec-review fold):
- cross-phase `_KNOWN_OIDC_ISSUERS` static-source set-parity test. Reads
  each sibling test module's source via `Path.read_text()` and parses it
  with ``ast.parse`` (NOT ``import``, NOT regex — Codex r2 fold replaced
  an earlier regex extractor to defeat comment-URL false-positives),
  walks top-level ``Assign`` nodes for ``_KNOWN_OIDC_ISSUERS = frozenset({...})``,
  reads the string-constant elements directly, and asserts pairwise
  equality. Closes the drift class where one surface's test mutates the
  issuer allowlist independently of the others.

Per `pattern_service_local_duplication_over_shared`: this test is
service-local to api (same as PR #56/#57) and does NOT import from sibling
test modules — only reads their source statically for the parity check.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
ALLOWLIST_PATH = REPO_ROOT / "data" / "cosign" / "signed-images-gha-services.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Sibling cosign-allowlist test modules for cross-phase parity checks.
# Read-as-source only; not imported. See `_KNOWN_OIDC_ISSUERS` parity test below.
SIBLING_COSIGN_TEST_MODULES = (
    Path(__file__).parent / "test_cosign_signed_images.py",
    Path(__file__).parent / "test_cosign_compose_signed_images.py",
)

# Docker manifest image-ref shape: <repo>:<tag>@sha256:<64-hex>.
# Repo may include registry host with optional `:<port>` (e.g.,
# myregistry.example.com:5000/python:3.12@sha256:...). Private-registry-
# with-port support added per PR #60 LOW finding F2 (cycle 14 security-
# reviewer): a host segment ending in `:<port-digits>/` is part of the
# registry host, NOT a tag delimiter.
_IMAGE_REF_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9.\-]*"          # first host segment
    r"(?::\d{1,5})?"                         # OPTIONAL registry port
    r"(?:/[A-Za-z0-9][A-Za-z0-9._\-]*)*"     # 0+ additional path segments
    r":[A-Za-z0-9._\-]+"                     # tag
    r"@sha256:[0-9a-f]{64}$"                 # digest
)

_COSIGN_INSTALLER_PIN_RE = re.compile(
    r"uses:\s*sigstore/cosign-installer@([0-9a-f]{40})\b"
)

# Known Sigstore OIDC issuers allowlisted for `certificate_oidc_issuer`.
# Phase 3 hardening per PR #60 LOW finding F7 carry-forward. Kept in sync
# with Phase 1's `_KNOWN_OIDC_ISSUERS` in `test_cosign_signed_images.py`
# AND Phase 2's `_KNOWN_OIDC_ISSUERS` in `test_cosign_compose_signed_images.py`
# (per-phase service-local duplication pattern; no cross-import). The
# cross-phase static-source parity test below catches drift.
_KNOWN_OIDC_ISSUERS = frozenset({
    "https://token.actions.githubusercontent.com",
    "https://oauth2.sigstore.dev/auth",
    "https://accounts.google.com",
    "https://gitlab.com",
    "https://agent.buildkite.com",
})


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


def test_cosign_gha_services_allowlist_exists_and_parses() -> None:
    cfg = _load_allowlist()
    assert "version" in cfg, "allowlist must declare a top-level `version` key"


def test_cosign_gha_services_allowlist_version_is_1() -> None:
    cfg = _load_allowlist()
    assert cfg.get("version") == 1, (
        f"allowlist version must be 1 (Phase 3 schema); got {cfg.get('version')!r}. "
        "Bumping the version requires a corresponding plan update."
    )


def test_cosign_gha_services_allowlist_images_is_list() -> None:
    cfg = _load_allowlist()
    images = cfg.get("images")
    assert images is None or isinstance(images, list), (
        f"`images` must be a list (or null/missing); got {type(images).__name__}"
    )


def test_cosign_gha_services_allowlist_entries_have_required_keys() -> None:
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


def test_cosign_gha_services_allowlist_image_ref_format() -> None:
    for idx, entry in enumerate(_entries()):
        image = entry.get("image", "")
        assert _IMAGE_REF_RE.match(image), (
            f"images[{idx}].image {image!r} does not match "
            f"`<repo>:<tag>@sha256:<64-hex>` shape."
        )


def test_cosign_gha_services_allowlist_no_duplicate_image_refs() -> None:
    seen: set[str] = set()
    for idx, entry in enumerate(_entries()):
        image = entry.get("image", "")
        assert image not in seen, (
            f"images[{idx}].image {image!r} duplicates an earlier entry."
        )
        seen.add(image)


def test_cosign_gha_services_allowlist_identity_match_in_allowed_set() -> None:
    for idx, entry in enumerate(_entries()):
        mode = entry.get("identity_match", "literal")
        assert mode in ("literal", "regexp"), (
            f"images[{idx}].identity_match must be 'literal' or 'regexp'; got {mode!r}."
        )


def test_cosign_gha_services_allowlist_tlog_mode_required() -> None:
    """`tlog_mode` MUST be `required`. `optional` is forbidden (defeats Rekor anchoring)."""
    for idx, entry in enumerate(_entries()):
        mode = entry.get("tlog_mode", "required")
        assert mode == "required", (
            f"images[{idx}].tlog_mode must be 'required'; got {mode!r}."
        )


def test_cosign_gha_services_allowlist_no_control_chars_in_string_fields() -> None:
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


def test_cosign_gha_services_allowlist_regexp_identity_must_be_anchored() -> None:
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


def test_cosign_gha_services_allowlist_annotations_must_be_empty_in_phase3() -> None:
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


def test_cosign_gha_services_yaml_safe_load_anchor_alias_behavior_documented() -> None:
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


def test_cosign_gha_services_allowlist_certificate_oidc_issuer_is_known() -> None:
    """`certificate_oidc_issuer` MUST be one of the known Sigstore issuers.

    PR #60 LOW finding F7 (cycle 14 security-reviewer) carry-forward. Mirrors
    the equivalent assertion in `test_cosign_signed_images.py` and
    `test_cosign_compose_signed_images.py` per
    `pattern_service_local_duplication_over_shared`. The `_KNOWN_OIDC_ISSUERS`
    frozenset is duplicated, not imported, so each phase's test remains
    self-contained for blame-bisect. The cross-phase parity test below
    catches drift.

    Vacuously PASS on the empty Phase 3 allowlist.
    """
    for idx, entry in enumerate(_entries()):
        issuer = entry.get("certificate_oidc_issuer", "")
        assert issuer in _KNOWN_OIDC_ISSUERS, (
            f"images[{idx}].certificate_oidc_issuer {issuer!r} is not in "
            f"the known-Sigstore-issuer allowlist. Allowed: "
            f"{sorted(_KNOWN_OIDC_ISSUERS)}. Adding a new issuer requires "
            f"updating `_KNOWN_OIDC_ISSUERS` in ALL THREE "
            f"`test_cosign_signed_images.py`, "
            f"`test_cosign_compose_signed_images.py`, and "
            f"`test_cosign_gha_services_signed_images.py` "
            f"(per-phase service-local duplication; no cross-import). "
            f"The cross-phase parity test will fail loud if the sets diverge."
        )


# --- CI YAML format gate ---------------------------------------------------


def _ci_workflow_body() -> str:
    assert CI_WORKFLOW.exists(), f"missing {CI_WORKFLOW}"
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_has_gha_services_cosign_verify_job() -> None:
    body = _ci_workflow_body()
    assert re.search(r"^\s*gha-services-cosign-verify:\s*$", body, flags=re.MULTILINE), (
        "ci.yml must define a top-level `gha-services-cosign-verify:` job "
        "(sibling to `gha-services-image-digest-resolve`) per PR #61 plan §D4."
    )


def test_ci_gha_services_cosign_installer_sha_pinned() -> None:
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


_EXPECTED_COSIGN_VERIFY_JOBS = (
    "dockerfile-cosign-verify",
    "compose-cosign-verify",
    "gha-services-cosign-verify",
)


def test_ci_gha_services_cosign_installer_sha_equality_across_all_jobs() -> None:
    """All `sigstore/cosign-installer@<sha>` pins in ci.yml MUST be identical.

    PR #60 LOW finding F1 (cycle 14 security-reviewer) carry-forward: per-phase
    pin tests use `re.search()` (first-match), so a future PR diverging the
    Phase 1 / Phase 2 / Phase 3 / Phase 4 pin would pass each test because
    each finds a valid 40-hex SHA somewhere in the body.

    Codex r1 fold (PR #61): the body-wide `findall(body)` check would PASS if
    one cosign-verify job lost its installer step while the other two still
    matched. Now anchors per-job — extracts each expected cosign-verify job's
    body individually, asserts exactly one installer pin per job, then
    asserts pin equality across all jobs.

    Duplicates the equivalent tests in `test_cosign_signed_images.py` and
    `test_cosign_compose_signed_images.py` per
    `pattern_service_local_duplication_over_shared` — each phase test owns
    its own copy; updating either file's assertion must be done in sync.
    """
    body = _ci_workflow_body()
    per_job_shas: dict[str, str] = {}
    for job_name in _EXPECTED_COSIGN_VERIFY_JOBS:
        job_re = re.compile(
            rf"^  {re.escape(job_name)}:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*\n|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = job_re.search(body)
        assert match, (
            f"could not isolate `{job_name}:` job body in ci.yml — has the "
            f"job been renamed or removed? Update `_EXPECTED_COSIGN_VERIFY_JOBS` "
            f"in lockstep across all cosign-verify test modules."
        )
        job_body = match.group(1)
        job_pins = _COSIGN_INSTALLER_PIN_RE.findall(job_body)
        assert len(job_pins) == 1, (
            f"`{job_name}` job body has {len(job_pins)} sigstore/cosign-installer "
            f"pin(s); expected exactly 1. Found: {job_pins}. A missing pin "
            f"means the job no longer verifies via cosign; a duplicate pin "
            f"suggests an accidental copy-paste."
        )
        per_job_shas[job_name] = job_pins[0]

    distinct = set(per_job_shas.values())
    assert len(distinct) == 1, (
        f"sigstore/cosign-installer pin divergence detected across cosign-verify "
        f"jobs: {per_job_shas}. All Phase 1 dockerfile / Phase 2 compose / "
        f"Phase 3 GHA services / future Phase 4 GHA uses jobs MUST share the "
        f"same SHA. Update every pin in lockstep when bumping."
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
def test_ci_gha_services_cosign_no_forbidden_flags(forbidden_flag: str) -> None:
    """Plan §4.5 anti-pattern: defeating tlog / sct / registry validation is forbidden.

    Asserted against the WHOLE ci.yml body (not just this job) because any
    surface adding these flags weakens the supply-chain posture. PR #61
    inherits PR #56/#57's 5-flag denylist verbatim.
    """
    body = _ci_workflow_body()
    assert forbidden_flag not in body, (
        f"ci.yml must NOT pass `{forbidden_flag}` to cosign verify. "
        f"It defeats one of: Rekor transparency log anchoring, CT log "
        f"inclusion proof, or registry TLS validation."
    )


def test_ci_gha_services_cosign_job_reconciles_allowlist_vs_workflow_refs() -> None:
    """The runner reconciles allowlist refs vs current GHA services `image:` refs.

    Stale allowlist entries (image no longer used in any workflow services block)
    MUST fail-loud; unlisted workflow services refs (current ref, no allowlist
    entry) MUST warn (plan D3 long-tail policy). Mirrors PR #56/#57 reconciliation.
    """
    body = _ci_workflow_body()
    match = re.search(
        r"^  gha-services-cosign-verify:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*\n|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "could not isolate gha-services-cosign-verify job body"
    job_body = match.group(1)

    # Positive 1: reconciliation enumerates current GHA workflow files.
    # Mirrors the existing `gha-services-image-digest-resolve` extractor
    # shape: `Path('.github/workflows').glob('*.yml')` + `.yaml`.
    assert (
        "Path(\".github/workflows\").glob(\"*.yml\")" in job_body
        or "Path('.github/workflows').glob('*.yml')" in job_body
        or "Path(\".github/workflows\").glob(\"*.yaml\")" in job_body
        or "Path('.github/workflows').glob('*.yaml')" in job_body
    ), (
        "gha-services-cosign-verify job must enumerate .github/workflows/*.yml "
        "(and .yaml) paths for allowlist↔workflow-services reconciliation. "
        "Walker shape must match the sibling `gha-services-image-digest-resolve` "
        "job's extractor for cross-job consistency."
    )

    # Positive 2: stale-entry fail-loud branch present (allowlist - workflow).
    assert "stale" in job_body and "allowlist_refs - services_refs" in job_body, (
        "gha-services-cosign-verify job must fail-loud on stale allowlist entries "
        "(refs in allowlist that no current GHA services `image:` uses)."
    )

    # Positive 3: unlisted-services WARN (workflow - allowlist).
    assert "WARN:" in job_body and "services_refs - allowlist_refs" in job_body, (
        "gha-services-cosign-verify job must WARN (not fail) on GHA services "
        "`image:` refs that are not in the cosign GHA-services allowlist."
    )


def test_ci_gha_services_cosign_job_uses_if_bang_guard_not_process_substitution() -> None:
    """Plan §4.5: avoid `done < <(python3 ...)` silent-pass class (PR #55 lesson).

    The gha-services-cosign-verify job parses the allowlist via Python; the
    `if ! python3 ... <<'PY' ... PY then ... fi` form is the only set-e-
    safe shape.
    """
    body = _ci_workflow_body()
    match = re.search(
        r"^  gha-services-cosign-verify:\s*\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*\n|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "could not isolate gha-services-cosign-verify job body"
    job_body = match.group(1)

    assert "done < <(python3" not in job_body, (
        "gha-services-cosign-verify job uses process-substitution against the "
        "Python parser — forbidden (PR #55 silent-pass class)."
    )
    assert re.search(r"if\s+!\s+python3\s", job_body), (
        "gha-services-cosign-verify job must wrap the Python parser in an "
        "`if !` guard so a parser crash propagates under `set -euo pipefail`."
    )


# --- NEW PR #61 — cross-phase static-source parity tests --------------------


def _extract_known_oidc_issuers_from_source(source: str) -> set[str]:
    """Static-source extraction of the ``_KNOWN_OIDC_ISSUERS`` frozenset.

    Reads a sibling test module's source text and parses the module AST to
    locate the ``_KNOWN_OIDC_ISSUERS = frozenset({...})`` top-level
    assignment. Does NOT execute or import the module — `ast.parse` only
    builds a syntax tree, and we read string literals from the resulting
    AST nodes directly. This defeats every false-positive class that a
    regex-based extractor would surface:

      - docstring / comment references to ``frozenset({...})`` shapes
      - double-quoted URLs inside ``# comment`` lines INSIDE the frozenset
        block (Codex r2 fold per PR #61 — the previous regex + ``startswith``
        URL-filter approach would still accept ``# See "https://evil.example.com"``
        as an extracted issuer; AST parsing structurally strips comments
        during tree-building so the class is impossible)
      - line breaks, trailing commas, type-annotation suffixes

    Per ``pattern_service_local_duplication_over_shared``, the test is
    service-local and does NOT import sibling modules — only AST-parses
    their source for the parity check.
    """
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id == "_KNOWN_OIDC_ISSUERS"):
            continue
        value = node.value
        # Expecting `frozenset({...})` — a Call to `frozenset` with a single
        # set / list / tuple argument of string constants.
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and len(value.args) == 1
            and isinstance(value.args[0], (ast.Set, ast.List, ast.Tuple))
        ):
            raise AssertionError(
                "_KNOWN_OIDC_ISSUERS must be a `frozenset({...})` assignment "
                "with a single set / list / tuple literal argument; got an "
                "unrecognized AST shape. Static-source parity test depends "
                "on the canonical declaration form."
            )
        elements = value.args[0].elts
        extracted: set[str] = set()
        for elt in elements:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                raise AssertionError(
                    "_KNOWN_OIDC_ISSUERS frozenset contains a non-string "
                    f"element {ast.dump(elt)!r}; all entries MUST be string "
                    "literals (issuer URLs). Refactor in lockstep across "
                    "all cosign-allowlist test modules."
                )
            extracted.add(elt.value)
        return extracted

    raise AssertionError(
        "_KNOWN_OIDC_ISSUERS assignment not found at top-level in sibling "
        "cosign test source — has the constant been renamed, removed, or "
        "moved inside a function? Static-source parity test depends on "
        "top-level assignment."
    )


def test_cross_phase_known_oidc_issuers_set_parity() -> None:
    """Cross-phase invariant: `_KNOWN_OIDC_ISSUERS` is identical across all
    cosign-allowlist test modules.

    NEW in PR #61 (Codex r1 spec-review fold). Per
    `pattern_service_local_duplication_over_shared`, each phase's test module
    declares its own `_KNOWN_OIDC_ISSUERS` constant rather than importing
    from a shared location. The downside is that the lockstep edit invariant
    is otherwise manual-only: a contributor could legitimately update one
    module's set (e.g., add a new approved issuer) and forget the others;
    the drift remains LATENT until an entry using the new issuer lands in
    the drifted-surface's allowlist.

    This test extracts each sibling test module's `_KNOWN_OIDC_ISSUERS`
    declaration via `ast.parse` (NOT `import` — that would mask drift by
    reading only the local file; NOT regex — Codex r2 fold replaced an
    earlier regex+URL-filter approach to defeat comment-URL false-positives),
    walks top-level `Assign` nodes, reads the string-constant elements
    directly, parses each into a Python `set`, and asserts pairwise equality
    across all 3 modules (extending to 4 in Phase 4).

    When adding a new issuer:
      1. Add to `_KNOWN_OIDC_ISSUERS` in all 3 cosign test modules in
         lockstep (single PR, single review).
      2. This test will FAIL until all 3 are updated — that's the design.

    Closes the Codex r1 finding that the issuer-set lockstep invariant
    was otherwise latent until used.
    """
    self_source = Path(__file__).read_text(encoding="utf-8")
    self_set = _extract_known_oidc_issuers_from_source(self_source)
    assert self_set == set(_KNOWN_OIDC_ISSUERS), (
        f"Static-source AST extraction of THIS module's _KNOWN_OIDC_ISSUERS "
        f"({sorted(self_set)}) disagrees with the runtime value "
        f"({sorted(_KNOWN_OIDC_ISSUERS)}). The AST extractor and "
        f"the actual frozenset have diverged — fix the extractor or the "
        f"declaration."
    )

    for sibling_path in SIBLING_COSIGN_TEST_MODULES:
        assert sibling_path.exists(), (
            f"sibling cosign test module missing: {sibling_path}. The "
            f"cross-phase parity test depends on its presence. If the "
            f"module was renamed or deleted, update "
            f"`SIBLING_COSIGN_TEST_MODULES` in lockstep."
        )
        sibling_source = sibling_path.read_text(encoding="utf-8")
        sibling_set = _extract_known_oidc_issuers_from_source(sibling_source)
        assert sibling_set == self_set, (
            f"_KNOWN_OIDC_ISSUERS parity violation between "
            f"{Path(__file__).name} and {sibling_path.name}.\n"
            f"  this module : {sorted(self_set)}\n"
            f"  sibling     : {sorted(sibling_set)}\n"
            f"  this - sibling: {sorted(self_set - sibling_set)}\n"
            f"  sibling - this: {sorted(sibling_set - self_set)}\n"
            f"Adding or removing a Sigstore OIDC issuer must be done in "
            f"lockstep across ALL cosign-allowlist test modules per "
            f"`pattern_service_local_duplication_over_shared`."
        )
