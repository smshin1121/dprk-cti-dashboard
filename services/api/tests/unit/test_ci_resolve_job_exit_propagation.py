"""Static-source assertions: the 4 supply-chain resolve jobs in
.github/workflows/ci.yml MUST use the temp-file + `if !` extractor guard
+ SCANNED-guard idiom (per plan §4 set-e-safe form) so an extractor
crash or zero-scan produces a non-zero job exit. NOT bare `extract_exit=$?`
or `${PIPESTATUS[0]}` capture — those are unreachable under
`set -euo pipefail` (Codex r1 finding, plan §4 anti-pattern note).

PR #55 fix; sibling to test_*_digest_pin.py format gates per
pattern_two_layer_defense_for_addressable_refs and to test_renovate_config.py.

Excluded: renovate-config-resolve (different shape, no SCANNED counter,
single `npx renovate-config-validator` call — no extractor stage to guard).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
CI_YML: Final[Path] = REPO_ROOT / ".github" / "workflows" / "ci.yml"

JOBS_UNDER_GUARD: Final[tuple[str, ...]] = (
    "dockerfile-digest-resolve",
    "compose-image-digest-resolve",
    "gha-services-image-digest-resolve",
    "gha-action-digest-resolve",
)
# Subset of JOBS_UNDER_GUARD whose extractor is `git ls-files | xargs
# grep -H`. The grep `-H` output is `path:line`, parsed downstream by
# `IFS=':' read -r`. A tracked file path containing a literal `:` would
# mis-split. The R0 convergent fold added a defensive `git ls-files |
# grep -q ':'` refuse-to-scan guard for each of these jobs (plan §0.1
# fold #2). The path-colon guard ONLY applies to grep-based extractors;
# the Python-heredoc extractors parse YAML directly so they have no
# colon-collision surface.
GREP_BASED_JOBS: Final[tuple[str, ...]] = (
    "dockerfile-digest-resolve",
    "compose-image-digest-resolve",
)
EXCLUDED_JOBS: Final[tuple[str, ...]] = (
    # Different shape: single `npx renovate-config-validator` call,
    # no extractor + consumer-loop split, no SCANNED counter applicable.
    # Renaming or restructuring this job MUST update this allowlist
    # consciously (caught by test_renovate_config_resolve_is_explicitly_excluded).
    "renovate-config-resolve",
)


def _ci_yml_text() -> str:
    assert CI_YML.exists(), f"missing {CI_YML}"
    return CI_YML.read_text(encoding="utf-8")


_JOB_HEADER_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


def _extract_job_body(yml: str, job_name: str) -> str:
    """Return the YAML body of the named job (the lines between the
    job header and the next job header at the same indent level).

    Uses plain regex over indentation rather than a YAML parser so the
    test mirrors the way a human reviewer reads a long workflow file
    and stays robust against pyyaml drift.
    """
    headers = list(_JOB_HEADER_RE.finditer(yml))
    for idx, m in enumerate(headers):
        if m.group(1) != job_name:
            continue
        start = m.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(yml)
        return yml[start:end]
    raise AssertionError(f"job {job_name!r} not found in ci.yml")


def _has_set_e_block_capture(body: str) -> bool:
    """Return True if the body has at least one `set +e ... set -e`
    block that captures `${PIPESTATUS[...]}` (the second plan-§4
    allowed form for set-e-safe extractor exit capture).
    """
    block_re = re.compile(
        r"set \+e\b.*?\$\{PIPESTATUS\[\d+\][^}]*\}.*?set -e\b",
        re.DOTALL,
    )
    return bool(block_re.search(body))


def _has_if_bang_guard(body: str) -> bool:
    """Return True if the body uses `if ! <extractor>` redirected to
    `"$inputs"` (the first plan-§4 allowed form)."""
    return bool(re.search(r'if !\s.*?>\s*"\$inputs"', body, re.DOTALL))


def test_ci_yml_exists() -> None:
    assert CI_YML.is_file(), f"missing {CI_YML}"


def test_each_guarded_job_has_tempfile_and_set_e_safe_extractor_guard() -> None:
    """Plan §4 + §7 acceptance criterion #1: every guarded job has the
    full set-e-safe idiom — mktemp + trap + extractor guard (either
    `if !` or `set +e ... set -e` block) + SCANNED counter + zero-scan
    fail-loud guard.
    """
    yml = _ci_yml_text()
    for job in JOBS_UNDER_GUARD:
        body = _extract_job_body(yml, job)

        # 1. mktemp invocation buffering extractor output
        assert 'inputs="$(mktemp)"' in body, (
            f"{job}: missing `inputs=\"$(mktemp)\"` — extractor output "
            "must be buffered to a temp file (plan §4)."
        )
        # 2. trap to clean up the temp file on exit
        assert "trap 'rm -f \"$inputs\"' EXIT" in body, (
            f"{job}: missing `trap 'rm -f \"$inputs\"' EXIT` — temp-file "
            "cleanup must be registered (plan §4)."
        )
        # 3. one of the two plan-§4 allowed extractor-guard forms
        assert _has_if_bang_guard(body) or _has_set_e_block_capture(body), (
            f"{job}: extractor lacks set-e-safe guard. Plan §4 allows "
            "either `if ! <extractor> > \"$inputs\"; then exit 1; fi` "
            "OR `set +e ... ${PIPESTATUS[N]} ... set -e` capture block. "
            "Bare `<extractor> > \"$inputs\"; rc=$?` is unreachable "
            "under `set -euo pipefail` (Codex r1 finding)."
        )
        # 4. SCANNED counter present
        assert "SCANNED=0" in body, (
            f"{job}: missing `SCANNED=0` initializer (plan §3 D3)."
        )
        assert "SCANNED=$((SCANNED + 1))" in body, (
            f"{job}: missing `SCANNED=$((SCANNED + 1))` increment inside "
            "consumer loop (plan §3 D3)."
        )
        # 5. zero-scan fail-loud guard
        assert '[ "$SCANNED" -eq 0 ]' in body, (
            f"{job}: missing `[ \"$SCANNED\" -eq 0 ]` zero-scan guard "
            "(plan §3 D3 — Tier 2 silent-pass class fix)."
        )
        # 6. consumer loop reads from the temp file (not from a process-sub)
        assert 'done < "$inputs"' in body, (
            f"{job}: consumer loop must read from `\"$inputs\"`, not from "
            "process-substitution (plan §4)."
        )


def _strip_shell_comments(body: str) -> str:
    """Remove `^\\s*#...$` lines so rationale comments referencing
    `done < <(...)` don't trip the negative assertions below.
    Inline `#` comments after code are kept (rare in this file and
    not load-bearing for the patterns we forbid).
    """
    return re.sub(r"^\s*#[^\n]*\n", "", body, flags=re.MULTILINE)


def test_no_naked_process_substitution_extractor_in_guarded_jobs() -> None:
    """Plan §5 negative assertion #1: `done < <(extractor)` patterns
    are FORBIDDEN in the 4 guarded jobs because that shape silently
    swallows the extractor's non-zero exit. Consumer loops MUST read
    from the temp file the `if !` (or `set +e ... set -e`) guard wrote.
    """
    yml = _ci_yml_text()
    for job in JOBS_UNDER_GUARD:
        body = _strip_shell_comments(_extract_job_body(yml, job))
        # `done < <(...)` is the silent-pass-prone shape we are eliminating.
        assert "done < <(" not in body, (
            f"{job}: contains `done < <(` process-substitution which masks "
            "the extractor's exit code. Plan §5 forbids this shape in "
            "guarded jobs. Read from `\"$inputs\"` after an `if !` or "
            "`set +e ... set -e` extractor guard wrote to it."
        )


def test_no_bare_status_capture_after_extractor() -> None:
    """Plan §5 negative assertion #2: explicitly forbid the Codex r1
    anti-pattern `extractor > "$inputs"` immediately followed by
    `extract_exit=$?` or `rc=$?` on the next non-comment line. These
    captures are unreachable under `set -euo pipefail`.

    Allowed: `if !` guard, OR `set +e ... set -e` block around the
    capture (the test accepts both shapes by skipping captures that
    sit inside a `set +e ... set -e` block).
    """
    yml = _ci_yml_text()
    for job in JOBS_UNDER_GUARD:
        body = _extract_job_body(yml, job)

        # Mask out `set +e ... set -e` blocks before scanning so the
        # plan-allowed PIPESTATUS capture form does not trip the guard.
        masked = re.sub(
            r"set \+e\b.*?set -e\b",
            "<<SET_E_BLOCK>>",
            body,
            flags=re.DOTALL,
        )

        # Look for the silent-fail anti-pattern: a line ending with
        # `> "$inputs"` (extractor redirect) followed within a few lines
        # by a bare `name=$?` or `name="${PIPESTATUS[0]}"` capture
        # OUTSIDE any set+e/set-e block.
        anti_pattern = re.compile(
            r'>\s*"\$inputs"\s*\n'              # redirect to temp file
            r'(?:\s*#[^\n]*\n)*'                 # optional comment lines
            r'\s*\w+=\$\?',                      # bare $? capture
            re.MULTILINE,
        )
        assert not anti_pattern.search(masked), (
            f"{job}: extractor output is captured by a bare `name=$?` "
            "outside any `set +e ... set -e` block. This statement is "
            "unreachable under `set -euo pipefail` (Codex r1 finding). "
            "Wrap the extractor in `if ! <extractor>; then ... fi` or "
            "an explicit `set +e ... ${PIPESTATUS[N]} ... set -e` block."
        )


def test_renovate_config_resolve_is_explicitly_excluded() -> None:
    """Forces conscious test update if renovate-config-resolve is ever
    renamed or restructured into the silent-pass-prone shape.
    """
    yml = _ci_yml_text()
    assert "renovate-config-resolve" in EXCLUDED_JOBS, (
        "renovate-config-resolve must remain in EXCLUDED_JOBS — it has "
        "a single npx call shape with no extractor + consumer-loop split."
    )
    body = _extract_job_body(yml, "renovate-config-resolve")
    # If someone added an extractor + SCANNED to this job, the test
    # author should reconsider whether it now belongs in JOBS_UNDER_GUARD.
    assert "SCANNED=0" not in body and "SCANNED=$" not in body, (
        "renovate-config-resolve gained a SCANNED counter — it now has "
        "the same shape as the guarded jobs and should move to "
        "JOBS_UNDER_GUARD (and out of EXCLUDED_JOBS)."
    )


def test_grep_based_jobs_have_path_colon_refuse_to_scan_guard() -> None:
    """Plan §0.1 fold #2 (R0 convergent finding): the 2 grep-based
    extractors emit `path:line` records that downstream `IFS=':' read -r`
    parses by splitting on the first colon. A tracked file path that
    itself contains `:` would silently mis-split into the wrong (path,
    line) tuple. The R0 fold added a defensive `git ls-files ... |
    grep -q ':'` refuse-to-scan guard ahead of the extractor. This test
    pins that guard's presence so a future cleanup pass does not delete
    it (Codex r-final 2026-05-15 regression-test gap).

    Python-heredoc-based jobs (`gha-services-image-digest-resolve`,
    `gha-action-digest-resolve`) parse YAML directly, so they have no
    colon-collision surface and are exempt.
    """
    yml = _ci_yml_text()
    for job in GREP_BASED_JOBS:
        body = _extract_job_body(yml, job)
        assert "git ls-files" in body and "grep -q ':'" in body, (
            f"{job}: missing the path-colon refuse-to-scan guard "
            "(`git ls-files ... | grep -q ':'`). Plan §0.1 R0 fold "
            "added this defense; without it, a path with `:` would "
            "silently mis-split downstream `IFS=':' read -r`."
        )
        # Pin the FAIL message string so the guard remains diagnostic
        # rather than a silent `exit 1`.
        assert "path contains ':'" in body, (
            f"{job}: path-colon guard exists but lacks the "
            "diagnostic `path contains ':'` FAIL message. Without "
            "the message the guard refuses to scan but doesn't tell "
            "the operator what to rename."
        )


def test_no_new_resolve_job_added_without_guard() -> None:
    """Forward-compat: any future `*-resolve` job in ci.yml MUST be in
    either JOBS_UNDER_GUARD or EXCLUDED_JOBS. Catches accidental
    sibling addition without exit-propagation discipline.
    """
    yml = _ci_yml_text()
    resolve_jobs = {
        m.group(1)
        for m in _JOB_HEADER_RE.finditer(yml)
        if m.group(1).endswith("-resolve")
    }
    known = set(JOBS_UNDER_GUARD) | set(EXCLUDED_JOBS)
    unaccounted = resolve_jobs - known
    assert not unaccounted, (
        f"new `*-resolve` job(s) added without exit-propagation discipline: "
        f"{sorted(unaccounted)}. Add each to JOBS_UNDER_GUARD (and apply "
        "plan §4 idiom) or to EXCLUDED_JOBS (with rationale comment)."
    )
