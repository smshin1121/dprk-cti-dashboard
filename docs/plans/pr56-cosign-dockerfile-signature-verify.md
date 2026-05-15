# PR #56 Plan — Cosign signature verification for Dockerfile FROM digests (Phase 1, single-surface)

**Phase:** Supply-chain hardening sweep, follow-up to PRs #49 / #51 / #52 / #53 / #54 / #55. The third layer of `pattern_two_layer_defense_for_addressable_refs` — moving from "manifest exists" (existence gate) to "this manifest was signed by the publisher you expect" (signature gate).
**Status:** Draft 2026-05-15. Pre-plan-discovery gate ONLY (no implementation, no commit, no PR yet).
**Predecessors:** PR #54 (Renovate adoption, merged 2026-05-12); PR #55 (silent-pass class fix in resolve jobs, OPEN @ `b5d8561`, CI BLOCKED on GH billing).
**Successors:** Multi-surface cosign rollout (compose / GHA services / GHA uses) — DEFERRED to follow-up plans (PR #57 / #58 / #59).
**Decision driver:** Codex `gpt-5.5` recommended Option B (sigstore/cosign plan-doc) with VERDICT GO; harness architect adjudicated AGREE PARTIAL — scope-lock to a single surface (Dockerfile FROM only) for budget safety; defer the multi-surface matrix to follow-up plans.

---

## 1. Goal

Add a third layer to the supply-chain defense for **Dockerfile FROM image refs**: in addition to the existing format gate (`test_dockerfile_digest_pin.py` — pin must be present) and existence gate (`dockerfile-digest-resolve` CI job — manifest must be reachable in registry), verify that the pinned digest was **signed by the publisher you expect** via [Sigstore cosign](https://docs.sigstore.dev/cosign/). A typo'd or yanked digest is caught by the existence gate; a **legitimate but maliciously-replaced** digest (publisher account compromise, registry MITM, layer substitution) is what the signature gate catches.

**Non-goal (deferred to follow-up plans):**
- Cosign verification for `compose`, `GHA services:`, `GHA uses:` surfaces (multi-surface matrix; PR #57+)
- Sigstore policy-controller / admission webhook integration
- Migrating any image from unsigned to signed (publisher-side; not our action)
- Replacing the existence gate (still required; signature gate is additive)

---

## 2. Locked Decisions (2026-05-15)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | Scope = **exactly Dockerfile FROM image refs only** (NOT compose, NOT GHA services, NOT GHA uses). | Highest blast-radius surface (production runtime images), smallest matrix (3 Dockerfiles in repo today: api, worker, llm-proxy). Multi-surface matrix would make this PR 3x larger and overlap with the deferred PR #57+ scope. |
| **D2** | Trust root = **keyless via Sigstore Fulcio + Rekor** (OIDC-issuer + certificate-identity claims), NOT pre-generated key-pair. | Keyless eliminates key management (rotation, secret distribution, accidental commit). The Fulcio-issued short-lived cert + Rekor transparency log entry IS the trust anchor; we pin the expected OIDC issuer + subject claim per allowlisted upstream image. Trade-off table in §4. |
| **D3** | **Allowlist-based coverage** initially. The PR introduces a `data/cosign/signed-images.yml` registry: image-ref → expected `--certificate-identity` + `--certificate-oidc-issuer` pair. Only allowlisted images are signature-verified; unlisted images are skipped with a warning, NOT failed. | Most upstream Docker Hub community images (redis, nginx, prom/prometheus, grafana, pgvector) do NOT sign with cosign today. Failing on every unsigned image would block CI entirely. The allowlist starts with our 1-2 known-signed images and grows as upstream coverage matures. Documented in §4. |
| **D4** | NEW CI job `dockerfile-cosign-verify` placed as **sibling to `dockerfile-digest-resolve`** (not nested inside it). Runs on the same trigger and same `permissions: contents: read`. | Keeps the three layers (format / existence / signature) cleanly separated for blame-bisect. A signature-gate failure should be diagnosable independently from a manifest-inspect failure. |
| **D5** | Format-gate test for the allowlist file: `services/api/tests/unit/test_cosign_signed_images.py` validates schema (each entry has `image`, `certificate_identity`, `certificate_oidc_issuer` keys; `image` matches `<repo>:<tag>@sha256:<64hex>` shape; no duplicate `image` keys). NO assertion about which images are present — that's policy, not format. | Mirrors the `test_renovate_config.py` / `test_dockerfile_digest_pin.py` static-source format-gate convention per `pattern_layer_boundary_lock_via_static_source`. |
| **D6** | Single-PR shape (no split). All 4 files (allowlist data + CI job + format-gate test + plan + amendment) land together. Plan-doc Codex iteration is hard-capped at **2 rounds** per architect verdict (force-stop on r3 even if findings remain — defer to follow-up iteration when budget refreshes). | Per autonomous-mode architect adjudication: tight token budget headroom requires the iteration cap. |

---

## 3. Scope

### In scope (this PR / Phase 1, ~5 files)

| File | Change | Approx delta |
|---|---|---:|
| `data/cosign/signed-images.yml` | NEW — initial allowlist with 1-3 known-signed upstream images (e.g. distroless, chainguard, or any of our images that publisher signs today; if none, ship an empty allowlist with the schema documented). | ~30 lines |
| `.github/workflows/ci.yml` | NEW `dockerfile-cosign-verify` job (sibling to `dockerfile-digest-resolve`); installs cosign via `sigstore/cosign-installer@<sha>`; iterates allowlist; calls `cosign verify` per image; fail-loud on signature mismatch. | ~80 lines |
| `services/api/tests/unit/test_cosign_signed_images.py` | NEW — schema + uniqueness assertions on `data/cosign/signed-images.yml`. | ~80 lines |
| `docs/plans/pr56-cosign-dockerfile-signature-verify.md` | NEW — this plan + §0.1 amendment slot reserved. | ~240 lines |
| `pattern_two_layer_defense_for_addressable_refs.md` (memory) | UPDATE in follow-up commit — extend to "three-layer defense" with signature gate as layer 3. NOT in this PR (separate post-merge memory commit). | (deferred) |

### Out of scope (DO NOT TOUCH this PR)

- `compose` / `GHA services` / `GHA uses` surfaces — DEFERRED to PR #57 / #58 / #59 (one per surface to keep blast-radius small).
- Existing format gates (`test_*_digest_pin.py`) — untouched.
- Existing existence gates (`*-resolve` jobs) — untouched.
- Renovate config (`renovate.json`) — untouched (Renovate currently does NOT update cosign signatures; manual policy update for now).
- Any pinned digest / SHA value in any Dockerfile.
- Sigstore policy-controller, admission webhooks, k8s integration — deferred indefinitely.

---

## 4. Design

### 4.1 Cosign keyless verification (D2 chosen form)

```bash
cosign verify <image>@<digest> \
  --certificate-identity "<expected-subject>" \
  --certificate-oidc-issuer "<expected-issuer>"
```

`cosign verify` returns 0 on signature match (with claims matching the pins) and non-zero otherwise. The exit code is fully meaningful — no PIPESTATUS / xargs games (per the lessons of `pitfall_xargs_grep_pipestatus_race`).

### 4.2 Trust root trade-off

| Approach | Pro | Con | Plan choice |
|---|---|---|---|
| **Keyless (Fulcio + Rekor)** | No key management. Short-lived certs. Transparency log audits every signature. Most upstream signers (chainguard, GitHub-built images, Distroless) use this today. | Requires OIDC issuer + subject pinning (per-publisher); allowlist needs an entry per upstream signer | ✅ **D2** |
| **Key-pair (`cosign.pub`)** | Simpler verify (`cosign verify --key cosign.pub`). | Key rotation, secret distribution, public-key publishing concern. Most upstream community images don't publish a stable `cosign.pub` we can pin. | Rejected |
| **Hybrid (keyless preferred, fall back to keypair if publisher provides)** | Maximum coverage | Two code paths; complexity disproportionate for Phase 1 | Deferred to follow-up plan if Phase 1 coverage is too narrow |

### 4.3 Allowlist schema

```yaml
# data/cosign/signed-images.yml
# Schema: each entry pins the expected Sigstore identity for one image:tag@digest.
# Phase 1 (PR #56): Dockerfile FROM image refs only.
# Future phases: compose / GHA services / GHA uses (separate allowlist files OR a unified
# schema with a `surface` discriminator — TBD in PR #57 plan).

version: 1
images:
  - image: cgr.dev/chainguard/python:3.12@sha256:<64hex>
    # Identity match mode:
    #   - `literal` (default): exact-string match against `--certificate-identity`
    #   - `regexp`: regex match against `--certificate-identity-regexp`
    # Use `regexp` only when the upstream signer's workflow path varies across
    # branches/tags (e.g., release-N branches); `literal` is preferred for audit clarity.
    identity_match: literal
    certificate_identity: https://github.com/chainguard-images/images/.github/workflows/release.yaml@refs/heads/main
    certificate_oidc_issuer: https://token.actions.githubusercontent.com
    # Annotations to verify (optional; cosign verify --annotations key=value).
    # Most upstream signers don't annotate today; reserve the field for future use
    # when policy needs to discriminate by build-source / commit-sha / etc.
    annotations: {}  # e.g., {sha256: "<commit-sha>", branch: "main"}
    # Transparency-log enforcement mode (default: required).
    #   - `required` (default): cosign verify includes Rekor proof — fail if absent
    #   - `optional`: allow unsigned/missing-tlog (NOT recommended; documented for completeness)
    # Phase 1 hard-rejects `optional` per §4.5 anti-pattern (defeats Rekor anchoring).
    tlog_mode: required
    notes: Phase 1 example; replace with actual chainguard image used in services/<svc>/Dockerfile
```

### 4.4 CI job placement

```yaml
dockerfile-cosign-verify:
  runs-on: ubuntu-latest
  permissions:
    contents: read
  steps:
    - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd  # v5
    - uses: sigstore/cosign-installer@<pinned-sha>  # v4.1.2 (resolved at implementation time; see §0.1 Amendment 4)
    - name: Verify cosign signatures for allowlisted Dockerfile FROM images
      run: |
        set -euo pipefail
        FAIL=0
        SCANNED=0
        # Per-allowlist-entry verify; skip-with-warning for non-allowlisted
        # images so CI doesn't fail on the unsigned-by-publisher long tail.
        # ... (idiom borrowed from pr55-resolve-job-exit-propagation: temp file
        # + `if !` guard around the python YAML walker)
        ...
```

(Full job body deferred to implementation; this plan-doc captures shape + invariants only.)

### 4.5 Anti-patterns explicitly forbidden (carried from PRs #55 lessons)

- **NO** `done < <(cosign verify ...)` process-substitution (per `pitfall_xargs_grep_pipestatus_race` family — masks exit code).
- **NO** bare `extract_exit=$?` capture under `set -euo pipefail` (per PR #55 r1 finding).
- **NO** `grep -q` in lieu of `cosign verify` exit code (semantically wrong).
- **NO** `--insecure-ignore-tlog` / `--allow-insecure-registry` flags (defeats Rekor transparency anchoring).

---

## 5. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|:---:|:---:|---|
| Allowlist coverage too narrow (most upstream community images aren't signed) | High | Low (signature gate is additive; existence gate still catches typo'd digests) | Allowlist starts small; grow as upstream coverage matures. Document the warn-not-fail policy in `data/cosign/signed-images.yml` schema. |
| Sigstore Fulcio / Rekor outage during CI | Medium | Job FAILs on `cosign verify` network error | Acceptable: a fail-loud signature-gate outage beats a silent "we couldn't verify, shipping anyway." Retry-cures; document the rerun playbook. |
| `sigstore/cosign-installer@<sha>` itself becomes a supply-chain risk | Low | Same as any other pinned action SHA | Already covered by existing `gha-action-digest-resolve` job (PR #53/#55) — the cosign-installer action's own ref will be format-gate-pinned + existence-gate-validated. |
| **Sigstore TUF root rotation / trust-root refresh failures** (Codex r1 finding) — Sigstore periodically rotates the TUF root (Fulcio CA cert + Rekor public key); a stale embedded root or a network failure during refresh causes ALL `cosign verify` calls to fail-closed even when signatures are valid | Medium | High (entire signature gate goes red simultaneously) | (1) Pin the cosign CLI version that ships a recent enough embedded root (cosign auto-refreshes at startup from the trust-root mirror). (2) Document the diagnosis path in the implementation: a sudden multi-image verify failure with `tuf: Root metadata` errors = TUF refresh issue, NOT a signature issue. (3) Rerun-cures most network refresh failures; for embedded-root staleness, bump the cosign-installer SHA to a release within 6 months (Sigstore root rotates ~yearly). |
| Allowlist drift (image bumped via Renovate but allowlist not updated → signature mismatch) | Medium | Job FAILs on next CI run after Renovate PR | Acceptable: forces a conscious review of "is this new digest signed by the same publisher?" Document in PR template. |
| Cosign CLI breaking changes between versions | Low | Job FAILs after upgrade | Pin cosign-installer SHA + version; bump deliberately. |
| Plan-doc Codex iteration runs over budget (force-stop on r3) | Per architect | Iteration deferred to follow-up plan | Per architect verdict: 2-round cap; if r3 needed, freeze plan and defer remaining concerns. |

---

## 6. Acceptance criteria

- [ ] `data/cosign/signed-images.yml` exists with valid schema.
- [ ] `.github/workflows/ci.yml` has new `dockerfile-cosign-verify` job sibling to `dockerfile-digest-resolve`.
- [ ] `services/api/tests/unit/test_cosign_signed_images.py` exists with ≥3 schema-validation tests, all PASS locally.
- [ ] No format-gate test, existence-gate job, `renovate.json`, or pinned digest/SHA touched.
- [ ] CI on the PR branch: all jobs SUCCESS (matching pre-PR baseline; new job PASSes on the allowlist's known-signed images).
- [ ] R0 (parallel `code-reviewer` + `security-reviewer`) returns CLEAN PROCEED or one round of convergent fold per `pattern_convergent_harness_findings_strong_signal`.
- [ ] Plan-doc Codex iteration: max 2 rounds (per architect verdict).
- [ ] PR body uses `pattern_pr_body_verification_split` template.

---

## 7. Roll-back

Single revert commit reverses all changes. Reverting drops the signature gate but leaves format + existence gates intact; supply-chain posture returns to pre-PR-#56 state (one layer thinner). No data migration, no schema change, no dependency update.

```bash
git revert <pr56-merge-sha>
```

---

## 8. Out-of-scope follow-ups (recorded for planning continuity)

- **PR #57** — extend cosign verify to `compose-image-digest-resolve` siblings. Same allowlist pattern.
- **PR #58** — extend to `gha-services-image-digest-resolve` siblings.
- **PR #59** — extend to `gha-action-digest-resolve` siblings (uses Sigstore-signed actions; upstream coverage is highest here).
- **Memory update (post-PR-#56-merge)** — `pattern_two_layer_defense_for_addressable_refs` → `pattern_three_layer_defense_for_addressable_refs` (rename + update wording; signature gate is layer 3). Defer to a separate small commit.
- **Optional: Renovate cosign-aware update strategy** — when Renovate bumps an image, also bump the allowlist's expected-cert-identity if the new digest is signed by the same publisher. Requires a Renovate post-update hook script. Defer until allowlist coverage justifies the automation.

---

## §0.1 Implementation amendments (2026-05-15)

Filled during PR #56 implementation per `pattern_plan_vs_impl_section_0_1_amendments`. All amendments were locked BEFORE the first commit by the harness architect adjudicating the Codex GO verdict (see commit body for the full architect transcript). None of these change the locked decisions D1-D6; they refine implementation specifics that the plan-doc legitimately deferred.

### Amendment 1 — Phase 1 ships with `images: []` (empty allowlist)

**Background.** D3's "allowlist starts with 1-3 known-signed upstream images" assumed at least one current FROM ref in the repo would have a publisher cosign signature. Discovery at implementation time (architect grep over `apps/frontend/Dockerfile`, `services/api/Dockerfile`, `services/worker/Dockerfile`, `services/llm-proxy/Dockerfile`) confirmed the four unique FROM refs are `node:22-alpine`, `nginx:1.27-alpine`, and `python:3.12-slim` (x3 services) — all Docker Hub Official Images, none of which publish Sigstore signatures today.

**Amendment.** `data/cosign/signed-images.yml` ships with `images: []`. The file header documents the empty state and the example entry shape (commented out) so a future migration (e.g., `python:3.12-slim` → `cgr.dev/chainguard/python:3.12`) is a pure data-edit with no CI YAML or test changes.

**Why this stays load-bearing.** PR #56 is now framed explicitly as a **forward-compat scaffold**: format gate (test) + existence gate (runner) + signature gate (job + allowlist) form the three-layer defense. The signature gate idle-passes today but activates the moment an entry is added. Without this PR, the first cosign migration would require concurrent CI-YAML + test + allowlist edits in one PR — landing the scaffold separately decouples policy from contract.

### Amendment 2 — Empty-allowlist no-op path is an explicit AC

**Amendment.** The `dockerfile-cosign-verify` job MUST exit 0 with `SCANNED=0 FAIL=0` when the allowlist is empty (after successful parse). This is the dominant Phase 1 code path. AC §6 line "new job PASSes on the allowlist's known-signed images" is reframed: "new job PASSes with `images: []` and emits `INFO: ... Phase 1 scaffold; no FROM ref signed today.`" The job exits non-zero ONLY on (a) parse failure, (b) schema violation, (c) cosign verify rejection of an allowlisted ref.

**Test coverage.** The format-gate test `test_cosign_signed_images.py` vacuously passes the entry-shape assertions when `images: []`. The runner's Python parser asserts `version == 1` and `images is None or list` regardless of allowlist contents, so a malformed YAML still fail-louds (not silent-passes).

### Amendment 3 — Implementation Codex iteration cap raised from 2 to 3 rounds

**Background.** D6 locked the plan-doc Codex iteration at 2 rounds. The architect adjudicating the GO verdict noted that D6's cap was scoped to plan-doc iteration only; the implementation phase is governed by `pattern_codex_iteration` (typical 3-6 rounds for substantive PRs).

**Amendment.** Implementation Codex iteration is capped at **3 rounds** (compromise between budget discipline and substantive coverage). R0 (parallel `code-reviewer` + `security-reviewer` agents per `pattern_harness_reviewer_codex_substitute`) is unchanged and runs FIRST. Codex PR-as-diff rounds follow. Force-stop on r4 even if findings remain — defer to a follow-up plan when budget refreshes. Convergent findings between R0 + Codex r1 fold preemptively in the same commit per `pattern_convergent_harness_findings_strong_signal`.

### Amendment 4 — `sigstore/cosign-installer` pinned to commit `6f9f17788090df1f26f669e9d70d6ae9567deba6` (v4.1.2)

**Background.** Plan §4.4 wrote `sigstore/cosign-installer@<pinned-sha>` as a placeholder. Implementation resolved the latest stable release via `gh api repos/sigstore/cosign-installer/releases/latest` → `v4.1.2` (published 2026-05-07) → commit SHA `6f9f17788090df1f26f669e9d70d6ae9567deba6` (lightweight tag; SHA points directly at the release commit).

**Amendment.** The CI workflow now reads `sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6  # v4.1.2 (2026-05-07)`. This satisfies the `gha-action-digest-resolve` existence-gate job (no unpinned refs) and the PR #53 cross-repo policy. Future Renovate runs will auto-bump this pin when a new cosign-installer release ships.

### Amendment 5 — Explicit `PyYAML` install step in the job

**Background.** Plan §4.4 ("Full job body deferred to implementation") did not specify the runtime dependency for the allowlist parser.

**Amendment.** The job adds `python3 -m pip install --user 'PyYAML==6.0.3'` as the third step (after `actions/checkout` and `sigstore/cosign-installer`). PyYAML is NOT shipped in the system Python on `ubuntu-24.04` runners; an explicit install is required. The pinned version matches the repo's `services/api` venv (`pyyaml 6.0.3`) for cross-environment parity.

**Alternative considered (rejected).** `yq` is pre-installed on `ubuntu-latest` and could parse the YAML without a dependency install. Rejected because (a) yq's expression language is less ergonomic for the multi-key schema validation we want at runtime, (b) the Python parser shares validation logic with the format-gate test (same library, same error message shape), and (c) ~5 seconds of pip-install time is a negligible cost on a job that already runs `actions/checkout` + `sigstore/cosign-installer`.

### Amendment 6 — Schema validation lives in BOTH runner parser AND format-gate test (defense in depth)

**Background.** D5 said "format-gate test validates schema + uniqueness; runner consumes allowlist." Implementation discovered the runner's Python parser already needs to validate every entry it writes to the TSV temp file (or it would crash the verify loop with mis-parsed args).

**Amendment.** The runner Python parser checks: `version == 1`, `images is list-or-null`, each entry has `image`/`certificate_identity`/`certificate_oidc_issuer`, `identity_match in {literal, regexp}`, `tlog_mode == "required"`, and no TAB chars in string fields (rejects mis-split). The format-gate test checks the same plus image-ref regex shape and duplicate-image-ref uniqueness. **Two layers** because: (1) the test catches drift at PR-time (before push); (2) the runner catches drift introduced by post-merge edits or Renovate auto-bumps (before any signature verify call runs). A Renovate-introduced typo'd digest fails the runner schema check IMMEDIATELY rather than during cosign verify (which would emit a less-clear "manifest unknown" error).

---

### What did NOT change

- D1 (scope = Dockerfile FROM only): unchanged.
- D2 (keyless via Fulcio + Rekor): unchanged; empty allowlist defers the trust-root pinning to first-entry-add.
- D3 (allowlist-based coverage): unchanged in shape; only the initial population is empty.
- D4 (CI job sibling to `dockerfile-digest-resolve`): unchanged.
- D5 (format-gate test in `services/api/tests/unit/`): unchanged.
- D6 (single-PR shape): unchanged. The 2-round plan-doc cap was honored; the implementation-iteration cap (Amendment 3) is a separate gate.

---

### §0.2 R0 fold (2026-05-15) — applied in same commit

R0 ran parallel `code-reviewer` + `security-reviewer` agents on the staged diff per `pattern_harness_reviewer_codex_substitute`. Both verdicts: **FOLD-AND-PROCEED**. The following 9 findings were folded into the single commit per `pattern_convergent_harness_findings_strong_signal`:

| Severity | Source | Finding | Fix location | Fix shape |
|---|---|---|---|---|
| HIGH | security-reviewer | `while read < "$inputs"` silently skips the last entry if the TSV temp file lacks a trailing newline | `ci.yml` verify loop | `|| [ -n "$image" ]` guard on the read loop |
| HIGH | security-reviewer | `regexp` identity entries forwarded verbatim to cosign; Go's `regexp.MatchString` is substring-matching, allowing identity spoofing | `ci.yml` Python parser + `test_cosign_signed_images.py` | new check: regexp identities must be anchored with `^...$` |
| MED | code-reviewer | YAML anchor/`<<:` merge keys can override entry fields silently | `test_cosign_signed_images.py` | new regression test pinning safe_load anchor-expansion behavior |
| MED | code-reviewer | `_entries()` helper masked falsy non-list `images:` values via `or []` | `test_cosign_signed_images.py` | explicit `if entries is None: entries = []` (matches runner) |
| MED | code-reviewer | `cosign verify` stderr discarded — TUF refresh vs signature rejection ambiguous in the FAIL log | `ci.yml` verify loop | capture stderr to `cosign_err`, emit as nested `\| ` lines under FAIL |
| MED | security-reviewer | `annotations` field documented in schema but silently ignored at runtime | `ci.yml` parser + `test_cosign_signed_images.py` + allowlist header | refuse-to-scan if `annotations` non-empty; new test asserts `{}` or absent for Phase 1 |
| MED | security-reviewer | `\n` / `\r` in string fields not rejected; only `\t` blocked | `ci.yml` parser + `test_cosign_signed_images.py` | extend `_BAD_CHARS` to `("\t", "\n", "\r")`; rename test from `_no_tab_` to `_no_control_chars_` |
| LOW | code-reviewer | `seen: list` for duplicate check is O(n²) | `test_cosign_signed_images.py` | `seen: set[str] = set()` |
| LOW | code-reviewer | §4.4 plan code-block comment said `# v3` but Amendment 4 locked `v4.1.2` | this file (plan §4.4) | comment updated to `# v4.1.2 (resolved at implementation time; see §0.1 Amendment 4)` |

**LOW finding NOT applied (dismissed after verification):**

- security-reviewer flagged `actions/checkout@93cb6efe...` comment label `# v5` as suspicious (knowledge-cutoff said v4 was current). Verified via `gh api repos/actions/checkout/git/refs/tags/v5 → object.sha` → `93cb6efe18208431cddfb8368fd83d5badbf9bfd`. The SHA IS the actual v5 tag commit (v5 released post-cutoff). No change needed. Cross-cutting note: `pattern_two_layer_defense_for_addressable_refs` test family already covers tag-vs-SHA drift; this PR is downstream of that gate.

**Convergence note (1× confirmed for this PR):** code-reviewer Finding 2 (`_entries()` falsy-scalar mask) and security-reviewer Finding 4 (`\n` mis-split) both concern TSV-parsing edge cases — different facets of "the parser layer must be robust to adversarial allowlist input." Folded together; counts as a single convergent-fact instance per `pattern_convergent_harness_findings_strong_signal` (7× → 8× after PR #56 merge).

### Local verification after R0 fold

- 14 → 17 tests in `test_cosign_signed_images.py` (3 new + 1 renamed + 1 with type-fix; all PASS).
- Sibling supply-chain tests (`test_dockerfile_digest_pin`, `test_compose_image_digest_pin`, `test_gha_services_image_digest_pin`, `test_gha_action_digest_pin`, `test_renovate_config`) — 20/20 PASS (no regression).
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` PASS.
- `python -c "import yaml; yaml.safe_load(open('data/cosign/signed-images.yml'))"` returns `{'version': 1, 'images': []}`.

---

### §0.3 Codex r1 fold (2026-05-15) — applied as r2 commit on top of R0 fold

Codex r1 verdict: **FOLD-AND-PROCEED**. R0 fold audit confirmed all 9 R0 folds are actually present in the code (not just claimed in the plan). Codex raised 2 net-new findings beyond R0; both folded:

| Severity | Source | Finding | Fix location | Fix shape |
|---|---|---|---|---|
| MED | Codex r1 | Allowlist ↔ Dockerfile FROM reconciliation missing. Job verified allowlist rows but never matched them against current Dockerfile FROM refs. Stale entries (image no longer used) silently green; unlisted FROMs (current ref, no allowlist entry) never surfaced. Contradicts plan §5 "Allowlist drift" risk-row intent. | `ci.yml` Python parser | added `Path('.').glob('**/Dockerfile')` walk + FROM regex extract → `allowlist_refs - dockerfile_refs` fails loud (stale); `dockerfile_refs - allowlist_refs` warns (plan D3 long-tail policy) |
| LOW | Codex r1 | Test forbidden-flag denylist under-pinned the threat model. Only `--insecure-ignore-tlog` + `--allow-insecure-registry` were rejected; the upstream cosign verify CLI also exposes `--allow-http-registry`, `--private-infrastructure`, `--insecure-ignore-sct` which weaken HTTPS / tlog / SCT guarantees respectively. | `test_cosign_signed_images.py` parametrize list | extended to 5 flags; cited the sigstore/cosign doc URL inline; module docstring updated to reflect the extended set |

**Cosmetic alongside the LOW fix:** test module docstring referenced `done < <(cosign verify ...)` and bare `=$?` anti-patterns as if explicitly asserted, but the actual asserts only check `done < <(python3 ...)` + presence of `if ! python3`. Docstring narrowed to what the tests actually pin.

**Test count growth this fold:** 17 → 19 (1 new reconciliation test + 3 extra parametrize cases from 2 → 5 forbidden flags).

**Verification source for new flags:** `https://github.com/sigstore/cosign/blob/main/doc/cosign_verify.md` (WebFetch confirmed all 5 flags exist in the official Cosign 2.x CLI documentation).

**Implementation iteration cap status:** Codex r1 was round 1 of 3 (per Amendment 3). r2 is the convergence test — expect CLEAN PROCEED. Force-stop at r3 if findings remain.
