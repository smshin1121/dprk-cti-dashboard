# PR #55 Plan — Process-substitution exit-code propagation across 4 supply-chain resolve jobs

**Phase:** Supply-chain hardening sweep, follow-up to PRs #49 / #51 / #52 / #53 / #54
**Status:** Draft 2026-05-14. Pre-plan-discovery gate (single signal, no implementation yet).
**Predecessors:** PR #54 (Renovate adoption, merged 2026-05-12 at `b44ed73`)
**Successors:** Sigstore/cosign signature verification (separate scoping discussion)
**Decision driver:** Codex `gpt-5.5` recommended Option A (silent-pass class sweep) with VERDICT GO; harness architect adjudicated AGREE PARTIAL (class size = 4, not 5; `renovate-config-resolve` is a different shape and is OUT OF SCOPE).

---

## §0.1 Implementation amendment (2026-05-15)

The 4 guarded jobs use the **two plan-§4-allowed forms split by extractor type** rather than a single uniform form. Both are set-e-safe and equally close the silent-pass class; the split keeps each rewrite as small as possible while staying plan-conformant.

| Job | Extractor type | Plan-§4 form chosen |
|---|---|---|
| `dockerfile-digest-resolve` | `git ls-files \| xargs grep` pipeline | **Form #2**: `set +e ... ${PIPESTATUS[N]} ... set -e` block |
| `compose-image-digest-resolve` | `git ls-files \| xargs grep` pipeline | **Form #2**: `set +e ... ${PIPESTATUS[N]} ... set -e` block |
| `gha-services-image-digest-resolve` | `python3 - <<'PY'` heredoc | **Form #1**: `if !` guard |
| `gha-action-digest-resolve` | `python3 - <<'PY' \| sort -u` pipeline | **Form #1**: `if !` guard around the full pipeline (pipefail catches non-zero in any element) |

Rationale for the split:
- The grep-based extractors return exit code 1 on no-match (benign, caught by SCANNED guard) and exit ≥2 on real error. Form #2 lets us discriminate the two cases via `${PIPESTATUS[N]}` without an inline shell-function wrapper.
- The Python heredoc extractors crash hard on any error (no equivalent benign exit code). Form #1's binary GO/NO-GO suits this perfectly.

The §5 regression test `test_each_guarded_job_has_tempfile_and_set_e_safe_extractor_guard` accepts EITHER form per job via the `_has_if_bang_guard(body) or _has_set_e_block_capture(body)` predicate. The negative assertion `test_no_bare_status_capture_after_extractor` masks `set +e ... set -e` blocks before scanning so Form #2 captures don't trip the guard.

This deviation is **plan-conformant** (both forms are explicitly allowed in plan §4) and is recorded here per `pattern_plan_vs_impl_section_0_1_amendments` for audit traceability.

**R0 convergent fold (2026-05-15):** the parallel `code-reviewer` + `security-reviewer` agents BOTH raised two findings on the dockerfile/compose grep variant (per `pattern_convergent_harness_findings_strong_signal`):

1. **`xargs ... grep` PIPESTATUS race**: `${PIPESTATUS[1]}` reflects `xargs`, not the inner `grep`. GNU `xargs` propagates a child non-zero (e.g., grep's exit 1 for no-match) as exit 123, so the original `[ "$grep_rc" -gt 1 ]` guard would false-FAIL on a legitimately empty Dockerfile tree before the SCANNED guard could emit the correct hint. **Fold:** dropped the `grep_rc` check entirely. The plan's own §4 already says "grep exit 1 (no match) is benign, caught by SCANNED guard"; the implementation now matches that intent. In the **realistic** CI threat model (git-checkout produces readable files for every tracked path) grep can only return 0 (match) or 1 (no match), never 2 (error); the no-match branch leaves `$inputs` empty → SCANNED=0 → fail-loud. A theoretical "partial extractor failure" (some greps return 2 because files become unreadable mid-walk) would leave `SCANNED > 0` and pass green, but is unreachable on a clean GHA `ubuntu-latest` checkout — no file-permission glitches, no mid-run filesystem churn. Recording the gap here so the rationale matches reality (Codex r-final correction, 2026-05-15).
2. **`IFS=':' ... grep -H` path-colon collision**: a tracked file path containing a literal `:` would be mis-split. **Fold:** added an explicit `git ls-files | grep -q ':'` defensive guard before the extractor in both grep-based jobs. Refuses to scan with a clear error rather than silently using the wrong ref.

Both folds land in this same commit; no separate R1 commit per the plan-§5 single-commit shape.

---

## 1. Goal

Close the silent-pass failure mode in the 4 supply-chain existence-gate resolve jobs in `.github/workflows/ci.yml` so that:

1. A crash inside the input-extraction stage (Python YAML walk OR `grep`/`git ls-files`) **always** produces a non-zero job exit, never a green CI tick.
2. A zero-extraction outcome (legit empty walk OR broken extractor) **always** fails loud with an actionable hint, never a green CI tick.

**Non-goal:** changing what is scanned, the registry-roundtrip semantics, the format-gate static-source tests, the Renovate config, or any pinned digest/SHA value. Non-goal: touching `renovate-config-resolve` (different shape, different failure model).

---

## 2. Locked Decisions (2026-05-14)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | Scope = exactly **4** resolve jobs in `.github/workflows/ci.yml`: `dockerfile-digest-resolve`, `compose-image-digest-resolve`, `gha-services-image-digest-resolve`, `gha-action-digest-resolve`. | These 4 share the `done < <(extractor)` process-substitution pattern that masks extractor exit code. `renovate-config-resolve` (line 1168+) is a single `npx renovate-config-validator` call — no extractor stage, no SCANNED counter, no silent-pass mode. Touching it would be cosmetic per `pattern_no_cosmetic_pad_on_green_draft`. |
| **D2** | **Bash idiom = temp-file + `if !` guard around extractor** (Option A, set-e-safe variant). NOT bare `extractor; rc=$?` (Codex r1 caught: `set -euo pipefail` aborts before capture). NOT `$(...)` command substitution (Option D), NOT named pipes (Option C), NOT process-sub `PIPESTATUS` (Option B; process-substitution is not a pipe). | The `if ! extractor > "$inputs"; then exit 1; fi` shape is the only set-e-safe pattern that keeps the failure branch reachable under `errexit`. For the one piped extractor (`gha-action-digest-resolve` uses `python3 ... \| sort -u`), `pipefail` makes `if !` correctly catch a non-zero in any pipeline element. Identical idiom across all 4 jobs; disk-I/O cost is negligible (< 1KB extractor output). |
| **D3** | Add a `SCANNED=0` counter + `[ "$SCANNED" -eq 0 ] && exit 1` guard to **all 4** jobs, including `dockerfile-digest-resolve` and `compose-image-digest-resolve` (currently lack the guard — Tier 2 risk). | The 2 grep-based jobs are silently passing today if `git ls-files` returns 0 results (e.g. all Dockerfiles renamed/moved). gha-services/gha-action already have the guard from PRs #52/#53; this brings the 4 jobs to the same fail-loud floor. |
| **D4** | Regression test = static-source assertion in a new file `services/api/tests/unit/test_ci_resolve_job_exit_propagation.py`, sibling to the existing `test_*_digest_pin.py` and `test_renovate_config.py` format-gate tests. | Mirrors the `pattern_layer_boundary_lock_via_static_source` convention already established for ci.yml gates. Cheap to read; prevents accidental rollback of either the temp-file idiom or the SCANNED guard during future sweeps. |
| **D5** | NO new dependencies, NO new CI jobs, NO modifications to format-gate tests or Renovate config, NO changes to any pinned digest/SHA. | Keeps the rollback unit minimal. Per architect SCOPE LOCK. |
| **D6** | Single-PR shape (no split). All 4 jobs + 1 regression test land together. | Per `pattern_two_layer_defense_for_addressable_refs`: 4 jobs share one bug class; splitting would create N stale-half states across CI runs. |

---

## 3. Scope

### In scope (4 files modified, 1 file added)

| File | Change | Approx delta |
|---|---|---:|
| `.github/workflows/ci.yml` | 4 `run:` blocks rewritten using temp-file + `if !` extractor guard + SCANNED guard idiom (per §4 set-e-safe form, NOT bare `$?` capture); 4 inline rationale comments updated to reference PR #55 | ~120 lines net (+~80, -~40) |
| `services/api/tests/unit/test_ci_resolve_job_exit_propagation.py` | NEW; static-source asserts on each of the 4 `run:` blocks | ~110 lines |

### Out of scope (DO NOT TOUCH)

- `renovate-config-resolve` (line 1168+) — single `npx` call, different shape
- `services/api/tests/unit/test_*_digest_pin.py` — format-gate tests untouched
- `services/api/tests/unit/test_renovate_config.py` — Renovate format gate untouched
- `renovate.json` — config untouched
- Any pinned digest, SHA, or `@<commit>` reference in any workflow / Dockerfile / compose file
- Any other CI job

---

## 4. Design — bash idiom

### Current pattern (silent-pass risk)

```bash
set -euo pipefail
FAIL=0
SCANNED=0   # only in gha-services / gha-action — NOT in dockerfile / compose
while IFS=' ' read -r ...; do
  SCANNED=$((SCANNED + 1))
  ...
done < <(python3 - <<'PY'
... walk that may crash mid-stream ...
PY
)
# Python exit code is masked. SCANNED can be > 0 from rows emitted before crash.
if [ "$SCANNED" -eq 0 ]; then exit 1; fi   # only in gha-services / gha-action
exit "$FAIL"
```

**Failure mode 1 (Tier 1, gha-services/gha-action):** Python emits N rows then crashes on row N+1. The `< <(...)` discards Python's non-zero exit. Loop completes for the N successful rows. SCANNED=N>0 → guard passes. `exit "$FAIL"` returns 0 if all N rows happened to pass `manifest inspect` / `gh api`. **Net result: green tick masking a partial scan.**

**Failure mode 2 (Tier 2, dockerfile/compose):** No SCANNED counter. If `git ls-files` matches zero files (all Dockerfiles renamed/moved/typo'd glob), outer loop runs 0 times. FAIL stays 0. `exit "$FAIL"` returns 0. **Net result: green tick on a zero-scan.**

### New pattern (Option A — temp-file + `if !` guard, set-e-safe)

> **Codex r1 fold (2026-05-14):** the original draft used `python3 ...; rc=$?` to capture the extractor's exit. Under `set -euo pipefail`, the shell aborts on the non-zero exit BEFORE `rc=$?` runs — capture never happens, the fail-loud branch is unreachable, and the silent-pass class is unchanged. The `if ! extractor; then ... fi` shape is the only set-e-safe wrapping that keeps the failure branch reachable.

```bash
set -euo pipefail
FAIL=0
SCANNED=0

# Buffer the input refs into a temp file so we can both check the
# extractor's exit status AND iterate the rows. `set -e` does NOT trip
# when a process inside `< <(...)` exits non-zero — that is the silent-
# pass class this idiom closes (PR #55).
inputs="$(mktemp)"
trap 'rm -f "$inputs"' EXIT

# `if !` keeps the failure branch reachable under `errexit`. A bare
# `python3 ... > "$inputs"; rc=$?` would never reach the rc capture
# because set -e aborts the shell on the non-zero exit first.
if ! python3 - <<'PY' > "$inputs"
... walk code ...
PY
then
  echo "FAIL: input extractor exited non-zero (silent-pass guard, PR #55)"
  exit 1
fi

while IFS=' ' read -r ...; do
  SCANNED=$((SCANNED + 1))
  ...
done < "$inputs"

if [ "$SCANNED" -eq 0 ]; then
  echo "FAIL: extractor returned zero refs — either delete this job or fix the extractor (PR #55)"
  exit 1
fi

exit "$FAIL"
```

**Closes both tiers.** Tier 1: extractor non-zero exit is caught by the `if !` branch (set-e-safe). Tier 2: SCANNED guard is now applied uniformly to all 4 jobs.

### Variants per job

- **dockerfile-digest-resolve / compose-image-digest-resolve:** the extractor is `git ls-files` + per-file `grep`. Plan choice: **single flattened temp file** built by a `git ls-files | xargs grep` (or equivalent) wrapped in the same `if !` guard. The `grep` exit code 1 (no match) inside the pipeline is benign; the guard fires only on exit code ≥ 2 (real error) thanks to `pipefail`. Reduces the change to one extra `mktemp` + one `if !` wrapper per job.
- **gha-services-image-digest-resolve / gha-action-digest-resolve:** Python heredoc redirected to mktemp, wrapped in `if !`. The existing `| sort -u` filter on `gha-action-digest-resolve` is preserved as part of the same pipeline: `if ! { python3 ... | sort -u > "$inputs"; }; then exit 1; fi`. Under `set -o pipefail` (already set by `set -euo pipefail`), a Python crash makes the pipeline's effective exit non-zero, so the `if !` branch fires correctly.

> **Anti-pattern explicitly forbidden (Codex r1 finding):** `python3 - <<'PY' > "$inputs"; extract_exit=$?` — the second statement is unreachable under `errexit`. Either use the `if !` guard above OR an explicit `set +e ... set -e` block around the bare capture. The plan + regression test both pin the `if !` form.

---

## 5. Test plan

### Regression test (NEW)

`services/api/tests/unit/test_ci_resolve_job_exit_propagation.py`

```python
"""Static-source assertions: the 4 supply-chain resolve jobs in
.github/workflows/ci.yml MUST use the temp-file + `if !` extractor guard
+ SCANNED-guard idiom (per plan §4 set-e-safe form) so an extractor
crash or zero-scan produces a non-zero job exit. NOT bare `extract_exit=$?`
or `${PIPESTATUS[0]}` capture — those are unreachable under
`set -euo pipefail` (Codex r1 finding, plan §4 anti-pattern note).

PR #55 fix; sibling to test_*_digest_pin.py format gates.
Excluded: renovate-config-resolve (different shape, no SCANNED counter, npx-only).
"""

JOBS_UNDER_GUARD = (
    "dockerfile-digest-resolve",
    "compose-image-digest-resolve",
    "gha-services-image-digest-resolve",
    "gha-action-digest-resolve",
)
EXCLUDED_JOBS = ("renovate-config-resolve",)  # explicit allowlist of excluded sibling

def test_each_job_uses_tempfile_and_set_e_safe_extractor_guard():
    # parse ci.yml, locate each job's run: body, assert it contains:
    # 1. mktemp invocation
    # 2. trap 'rm -f ...' EXIT
    # 3. `if !` wrapping the extractor (Python heredoc OR git/grep pipeline)
    #    — set-e-safe, NOT bare `extractor; rc=$?` (Codex r1 finding)
    # 4. SCANNED=0 counter incremented inside the consumer loop
    # 5. `[ "$SCANNED" -eq 0 ]` guard with `exit 1` after the loop
    ...

def test_no_naked_process_substitution_extractor_in_guarded_jobs():
    # negative assertion: `done < <(extractor)` patterns are FORBIDDEN
    # in the 4 guarded jobs because that shape silently swallows the
    # extractor's non-zero exit. Consumer loops MUST read from the
    # temp file the `if !` guard wrote.
    # Allowed: `done < "$inputs"` after the temp file is populated.
    # Forbidden: `done < <(python3 ...)` or `done < <(grep ...)`.
    ...

def test_no_bare_status_capture_after_extractor():
    # negative assertion: explicitly forbid the Codex r1 anti-pattern
    # `extractor > "$inputs"` followed by `extract_exit=$?` or
    # `rc=$?` on the next non-comment line. These captures are
    # unreachable under `set -euo pipefail`.
    # Allowed: `if !` guard, or `set +e ... set -e` block around the
    # capture (the test should accept both shapes).
    ...

def test_renovate_config_resolve_is_explicitly_excluded():
    # ensures the test doesn't silently start failing if the npx-shape
    # job is renamed or restructured — forces conscious test update
    ...

def test_no_new_resolve_job_added_without_guard():
    # forward-compat: any future *-digest-resolve or *-resolve job in ci.yml
    # MUST be in either JOBS_UNDER_GUARD or EXCLUDED_JOBS — fails loud on
    # accidental sibling addition without exit-propagation discipline
    ...
```

### Local pre-push smoke (manual)

1. `uv run pytest services/api/tests/unit/test_ci_resolve_job_exit_propagation.py -v` — expect 3 PASS.
2. `act -j gha-action-digest-resolve` if available, OR rely on PR CI run for end-to-end validation.
3. Negative-path manual: temporarily inject `raise RuntimeError("test")` in one of the Python heredocs, push to a throwaway branch, confirm the job FAILS (not silently passes). Revert before merge.

### CI verification (PR run)

- All 4 resolve jobs PASS unchanged on the realistic positive path (no actual crash, no zero-scan).
- New regression test PASSES.
- No other CI job touched, so no regression surface elsewhere.

---

## 6. Risk + mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|:---:|:---:|---|
| **`errexit` aborts before status capture** (Codex r1 finding) — bare `extractor; rc=$?` is unreachable under `set -euo pipefail`, so the fail-loud branch never runs and the silent-pass class is unchanged | High (would have shipped) | Plan reverts to silent-pass; Codex r1 already ran | **RESOLVED** in §4 by `if ! extractor; then exit 1; fi` shape and pinned by 2 dedicated negative assertions in §5 (`test_no_naked_process_substitution_extractor_in_guarded_jobs`, `test_no_bare_status_capture_after_extractor`). |
| `set -euo pipefail` × `mktemp` interaction surprise (e.g. `mktemp` itself fails on a stripped runner) | Low | Job fails loud with mktemp error | Acceptable: a fail-loud regression beats silent-pass. `ubuntu-latest` reliably ships GNU coreutils mktemp. |
| `trap 'rm -f "$inputs"' EXIT` doesn't fire if shell is killed (SIGKILL) | Negligible | Stale `/tmp` file on ephemeral runner | No mitigation needed; runner is destroyed after job. |
| Temp file path collision in parallel matrix (none today, but future) | Negligible | mktemp uses unique suffix; `$RUNNER_TEMP` available as alternative | mktemp default is sufficient. |
| `${PIPESTATUS[0]}` syntax silently fails under non-bash shells | Negligible | GitHub Actions `runs-on: ubuntu-latest` uses `bash` for `run:` blocks by default | Confirmed by GitHub docs; explicit `shell: bash` not required. |
| Reviewer disagrees that Tier 2 (dockerfile/compose) needs SCANNED guard | Low | Extra commit fold | Plan §1 goal #2 makes the zero-extraction failure explicit; if reviewer challenges, the failure mode is demonstrable. |
| Adding 4 nearly-identical idiom blocks invites future drift (one job reverted by accident) | Medium | Future silent-pass regression | The new regression test in §5 pins all 4 jobs by name; drift is caught at static-source time, not at CI-fail time. |
| Plan grows during R0 reviewer rounds (scope creep into renovate-config or format-gate tests) | Medium | Iteration churn | D1 + D5 pre-commit to scope; reviewer rounds reference this plan section explicitly. |

---

## 7. Acceptance criteria

- [ ] All 4 jobs in `.github/workflows/ci.yml` use the temp-file + `if !` extractor guard + SCANNED-guard idiom (per §4). The piped extractor in `gha-action-digest-resolve` uses the same `if !` form wrapping the full `python3 ... | sort -u` pipeline (pipefail catches a non-zero in any element). NO bare `extract_exit=$?` or `${PIPESTATUS[0]}` capture statements anywhere in any of the 4 `run:` blocks.
- [ ] `services/api/tests/unit/test_ci_resolve_job_exit_propagation.py` exists, has 6 tests (per §5: 1 sanity test for ci.yml existence + positive guard assertion + two negative assertions forbidding `done < <(extractor)` and bare `$?` capture + exclusion test + forward-compat sibling test), all PASS locally.
- [ ] `renovate-config-resolve` is unchanged (verified by `git diff main -- .github/workflows/ci.yml` showing no edits in lines 1168+ except possibly an unrelated comment refresh).
- [ ] No format-gate test, no `renovate.json`, no pinned digest/SHA touched.
- [ ] CI on the PR branch: all jobs SUCCESS (matching pre-PR baseline).
- [ ] R0 (parallel `code-reviewer` + `security-reviewer` per `pattern_harness_reviewer_codex_substitute`) returns CLEAN PROCEED or one round of convergent fold per `pattern_convergent_harness_findings_strong_signal`.
- [ ] Pre-merge defensive Codex round returns GO.
- [ ] PR body uses the `pattern_pr_body_verification_split` template (✅ verified-locally / ✅ verified-on-CI / 🟡 pending).

---

## 8. Roll-back

Single revert commit reverses all changes. Reverting does not affect any merged supply-chain pin; the pre-PR-#55 silent-pass risk re-emerges but no production data path is touched.

```bash
git revert <pr55-merge-sha>
```

No data migration, no schema change, no dependency update, no Renovate config change → roll-back is content-only.

---

## 9. Out-of-band notes

- This plan is the **first strategic gate** (`pre-plan-discovery`) of the decision-driven cycle started 2026-05-14. The next signal advances to `local-commit` (apply the 4 ci.yml edits + write the regression test + R0 fold in one commit).
- Codex's original recommendation said class size = 5; architect corrected to 4 (this plan reflects 4). `renovate-config-resolve` exclusion is the single most important scope guard.
- Per `pattern_no_cosmetic_pad_on_green_draft`: do NOT use this PR to bump pattern validation counts, refresh comments unrelated to the fix, or add observability. Those are separate signals.
