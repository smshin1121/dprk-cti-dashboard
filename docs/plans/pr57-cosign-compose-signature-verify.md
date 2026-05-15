# PR #57 Plan — Cosign signature verification for docker-compose image refs (Phase 2, compose surface)

**Phase:** Supply-chain hardening sweep, follow-up to PR #56 (Dockerfile FROM cosign Phase 1). Second surface of `pattern_signature_gate_scope_lock_per_phase` — extending the keyless Sigstore signature gate from Dockerfile FROM image refs to top-level `image:` refs in `docker-compose*.yml`.
**Status:** Draft 2026-05-15. Pre-plan-discovery gate ONLY (no implementation, no commit, no PR yet).
**Predecessors:** PR #56 (cosign Dockerfile FROM Phase 1, ready-to-push @ `c45120c`, CI BLOCKED on GH billing; CLEAN PROCEED at Codex r2).
**Successors:** PR #58 (GHA services-image-digest-resolve cosign extension), PR #59 (GHA action-digest-resolve cosign extension).
**Decision driver:** Cycle 10 Codex decision call (VERDICT GO; rationale = best balance of forward motion + budget discipline; extends validated cosign phase pattern without creating another blocked push branch; 2nd validation of `pattern_signature_gate_scope_lock_per_phase`).

---

## 1. Goal

Apply the same three-layer defense to `compose-image-digest-resolve` siblings: in addition to the existing format gate (`test_compose_image_digest_pin.py` — pin must be present) and existence gate (`compose-image-digest-resolve` CI job — manifest must be reachable in registry), verify that the pinned digest was **signed by the publisher you expect** via Sigstore cosign (Fulcio + Rekor, keyless).

**Surface inventory (`git ls-files 'docker-compose*.yml' '**/docker-compose*.yml' '**/docker-compose*.yaml' 'docker-compose*.yaml'`):**

| File | Image refs |
|---|---:|
| `docker-compose.yml` | 7 (pgvector, redis, otel/collector, prom/prometheus, grafana, busybox, keycloak) |
| `docker-compose.smoke.yml` | 0 (overlay; no `image:` keys) |

**Phase 2 ships EMPTY allowlist (same shape as PR #56 Phase 1).** Of the 7 compose `image:` refs, none are confirmed cosign-signed by their respective Docker Hub / quay.io publishers as of 2026-05-15. A future migration (e.g., switch grafana or prometheus to a Sigstore-signed publisher mirror) becomes a pure allowlist data-edit once the gate is in place.

**Non-goal (deferred to follow-up plans):**
- Cosign verification for `Dockerfile FROM` (covered by PR #56; this PR is additive)
- Cosign verification for `GHA services:` / `GHA uses:` surfaces (deferred to PR #58 / #59)
- Sigstore policy-controller / admission webhook integration
- Cross-surface reconcile-all job (deferred to PR #60 OR PR #59 cleanup; see §4.6)

---

## 2. Locked Decisions (2026-05-15)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | Scope = **exactly `docker-compose*.yml` top-level `image:` refs** (NOT Dockerfile FROM, NOT GHA services:, NOT GHA uses:). | Smallest matrix that extends PR #56's pattern by one validated surface. 2nd validation of `pattern_signature_gate_scope_lock_per_phase`. |
| **D2** | Trust root = **keyless via Sigstore Fulcio + Rekor** (per-entry OIDC issuer + certificate-identity pinning). Same as PR #56 D2 — no per-surface trust-root divergence. | Carries forward PR #56 D2 rationale. Key management cost saved; transparency log audits every signature. |
| **D3** | **Separate per-surface allowlist file**: `data/cosign/signed-images-compose.yml` (NOT the existing `data/cosign/signed-images.yml`). Each surface gets its own allowlist file. | Closes the TBD in PR #56 plan §1 ("separate allowlist files OR a unified schema with a `surface` discriminator"). Separate files chosen because: (1) preserves PR #56 backward compatibility (its stale-check `allowlist_refs - dockerfile_refs` would FAIL on compose-only entries in a shared file — see §4.6), (2) clean per-surface ownership (compose has different update cadence than Dockerfile FROM), (3) sparse cross-surface duplication today (only `busybox` overlap risk between compose and Dockerfile FROM, but no Dockerfile uses busybox in this repo). When duplication appears in a future PR, lift to a shared allowlist as a separate refactor. |
| **D4** | NEW CI job `compose-cosign-verify` placed as **sibling to `compose-image-digest-resolve`** (not nested). Runs on same trigger and `permissions: contents: read`. | Mirrors PR #56 D4. Per-layer blame-bisect: a signature failure on compose should be diagnosable independently from the manifest-inspect failure or the Dockerfile signature failure. |
| **D5** | Format-gate test: `services/api/tests/unit/test_cosign_compose_signed_images.py` validates schema (each entry has `image`, `certificate_identity`, `certificate_oidc_issuer`; `image` matches `<repo>:<tag>@sha256:<64hex>`; no duplicate `image` keys; `identity_match in {literal, regexp}`; `tlog_mode == required`; `annotations == {}` or absent; regexp identities anchored `^...$`; no control chars in string fields; static-source assertions on the CI job body). Identical anti-pattern coverage as PR #56's `test_cosign_signed_images.py`. | Mirrors PR #56 D5 + R0 + Codex r1 lessons. Format gate parity across surfaces is itself a check that no surface relaxes invariants. |
| **D6** | Single-PR shape (no split). 4 files: allowlist data + CI job + format-gate test + this plan. Plan-doc Codex iteration HARD-CAPPED at **2 rounds** per `pattern_signature_gate_scope_lock_per_phase` plan-doc cap. Implementation Codex iteration HARD-CAPPED at **3 rounds** per `pattern_codex_3round_implementation_iteration` (validated 1× on PR #56). | Iteration discipline carries forward. R0 parallel reviewers run first. Convergent findings fold preemptively. |

---

## 3. Scope

### In scope (this PR / Phase 2, ~5 files)

| File | Change | Approx delta |
|---|---|---:|
| `data/cosign/signed-images-compose.yml` | NEW — initial allowlist (Phase 2 EMPTY; same schema-only docs as PR #56's `signed-images.yml`; cross-link to it in header). | ~70 lines |
| `.github/workflows/ci.yml` | NEW `compose-cosign-verify` job sibling to `compose-image-digest-resolve`. Reuses PR #56's idioms (PyYAML install step, `if !` guard, stderr capture, schema validation parity, reconciliation against current compose `image:` refs). | ~200 lines |
| `services/api/tests/unit/test_cosign_compose_signed_images.py` | NEW — 17+ static-source assertions matching PR #56's format-gate parity. | ~280 lines |
| `docs/plans/pr57-cosign-compose-signature-verify.md` | NEW — this plan + §0.1 amendment slot reserved. | ~200 lines |

### Out of scope (DO NOT TOUCH this PR)

- `data/cosign/signed-images.yml` (Dockerfile FROM allowlist; PR #56 owns it)
- PR #56's `dockerfile-cosign-verify` CI job (no changes)
- PR #56's `test_cosign_signed_images.py` (no changes)
- `Dockerfile`, `services/<svc>/Dockerfile` (no FROM digest changes)
- `compose-image-digest-resolve` existing job (no changes; new job runs alongside)
- `test_compose_image_digest_pin.py` existing format gate (no changes)
- `renovate.json` (no changes)
- GHA `services:` / `uses:` surfaces (deferred to PR #58 / #59)
- Cross-surface reconcile-all job (deferred; see §4.6)

---

## 4. Design

### 4.1 Cosign keyless verification (carry-forward from PR #56 D2)

```bash
cosign verify <image>@<digest> \
  --certificate-identity "<expected-subject>" \
  --certificate-oidc-issuer "<expected-issuer>"
```

Same exit-code semantics as PR #56. No `--insecure-ignore-tlog`, `--allow-insecure-registry`, `--allow-http-registry`, `--private-infrastructure`, `--insecure-ignore-sct` (all 5 anti-pattern flags carried forward from PR #56 R0 + Codex r1 extension).

### 4.2 Allowlist schema

Identical to PR #56's `data/cosign/signed-images.yml`:
- `version: 1`
- `images: []` (empty Phase 2; populate as upstream publishers adopt cosign)
- Each entry: `image` (required), `certificate_identity` (required), `certificate_oidc_issuer` (required), `identity_match: literal | regexp` (optional, default `literal`), `tlog_mode: required` (required value), `annotations: {}` (must be empty or absent), `notes` (free-form).

Header cross-references PR #56's allowlist for schema reuse + documents the per-surface separation rationale.

### 4.3 CI job placement

```yaml
compose-cosign-verify:
  runs-on: ubuntu-latest
  permissions:
    contents: read
  steps:
    - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd  # v5
    - uses: sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6  # v4.1.2
    - name: Ensure PyYAML available for allowlist parser
      run: python3 -m pip install --user 'PyYAML==6.0.3'
    - name: Verify cosign signatures for allowlisted docker-compose image refs
      run: |
        # Parse allowlist via if-bang Python heredoc (PR #56 idiom).
        # Reconcile against current docker-compose*.yml `image:` refs.
        # Per-entry cosign verify with stderr capture.
        # Anti-pattern guards identical to PR #56 dockerfile-cosign-verify.
        ...
```

Sibling to `compose-image-digest-resolve` (currently at ci.yml line ~908). Insertion point: immediately after that job's `done < <(grep -E '^[[:space:]]+image:' "$compose_file")` final line.

### 4.4 Reconciliation logic (carries forward PR #56 Codex r1 finding)

The runner Python parser, after schema validation, walks every `docker-compose*.yml` / `.yaml` matched by `Path('.').glob('docker-compose*.yml')` and the recursive variants (filesystem glob; see §5 risk row + §0.2 R0 fold note on the divergence from sibling job's `git ls-files` scope), and extracts every top-level `services.<svc>.image:` value via PyYAML `safe_load`. Mirror PR #56 reconciliation semantics:

- **stale allowlist entries** (refs in `signed-images-compose.yml` but NOT in any current compose `image:` ref) → FAIL loud. The allowlist is the policy contract.
- **unlisted compose refs** (current ref, no allowlist entry) → WARN (plan D3 long-tail policy; mirrors PR #56).

This is **surface-scoped reconciliation, and that scope is sufficient on its own**. `compose-cosign-verify` only knows about compose refs vs the compose allowlist; per-surface stale-checks remain the **authoritative** drift gate for each surface (no cross-surface coordination needed). The future reconcile-all job in §4.6 is an OPTIONAL global-inventory refactor, NOT a prerequisite that closes any coverage gap.

### 4.5-pre — regexp identity dispatch (explicit carry-forward from PR #56)

The runner and test BOTH dispatch on `identity_match`:
- `literal` (default) → `cosign verify ... --certificate-identity <exact-string>`
- `regexp` → `cosign verify ... --certificate-identity-regexp <anchored-pattern>` (pattern MUST be anchored with `^...$` per PR #56 R0 security-reviewer Finding 2, enforced by both the runner Python parser and the format-gate test).

No new flag set. Implementation reuses PR #56's idiom verbatim.

### 4.5 Anti-patterns explicitly forbidden (carry-forward from PR #56 §4.5 + R0 + Codex r1; supersedes earlier draft numbering)

- NO process-substitution around the cosign verify call (masks exit code)
- NO bare `extract_exit=$?` capture under `set -euo pipefail` (unreachable; PR #55 silent-pass class)
- NO insecure-flag passthrough to cosign verify: `--insecure-ignore-tlog`, `--allow-insecure-registry`, `--allow-http-registry`, `--private-infrastructure`, `--insecure-ignore-sct` (all 5 enforced by format-gate test)
- NO `tlog_mode: optional` allowlist value (rejected by format-gate test and runner parser)
- NO TAB / LF / CR in any allowlist string field (rejected by both layers)
- NO `identity_match: regexp` with an unanchored pattern (must be `^...$`)
- NO non-empty `annotations` field until --annotations passthrough is implemented (refuse-to-scan rather than silent-skip)

### 4.6 Cross-surface reconciliation (OPTIONAL future refactor — not a coverage prerequisite)

A **cross-surface reconcile-all job** would compare the union of all surface refs (Dockerfile FROM + compose image + GHA services image + GHA uses action) against the union of all per-surface allowlists, and would be a place for a single global-inventory audit. This is OPTIONAL and does NOT close any coverage gap that the per-surface stale-checks don't already close: each surface's own job already FAILs loud on its own stale-allowlist entries, and an entry can only be "stale in surface X" by definition (it's in surface X's allowlist; if surface X doesn't use it, that surface fails). The cross-surface case "image listed in allowlist X but used only by surface Y" is not a real coverage gap — it's just an entry in the wrong file, which the per-surface stale-check in X catches.

When useful: as a consolidation refactor (if all surface allowlists are eventually merged into a unified-schema file with a `surface:` discriminator). Until then, per-surface stale-checks remain the authoritative drift gate.

**Plan**: defer to PR #60 (after PR #58 and PR #59 ship) as a strictly-optional global-inventory + format-gate-test refactor. No PR #56 / #57 / #58 / #59 implementation change depends on it. Plans #58 and #59 will inherit this same wording.

---

## 5. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|:---:|:---:|---|
| Empty Phase 2 allowlist means the gate idle-passes — same "forward-compat scaffold" framing as PR #56 | Certain (Phase 2 ships empty) | None today; load-bearing on next signed-publisher migration | Documented in plan + allowlist header; format-gate test covers schema regardless |
| Sigstore Fulcio / Rekor outage during CI | Medium | Job FAILs on `cosign verify` network error | Same mitigation as PR #56 (fail-loud > silent skip; retry-cures; document the rerun playbook). Carry-forward Codex r1 stderr-capture so TUF refresh errors are distinguishable from signature rejections in logs. |
| Separate allowlist file diverges from `signed-images.yml` schema (drift) | Medium | Format-gate tests miss a difference, runner parsers reject inconsistently | Format-gate test asserts schema parity (same key set, same value-domains, same anti-pattern guards). When PR #58 / #59 land, refactor common assertions into a shared test helper (deferred to PR #60). |
| Cross-surface global-inventory audit absent until optional PR #60 | Certain (Phase 2 has only 2 surfaces) | None — per-surface stale-checks are the authoritative gate; cross-surface reconcile-all is an OPTIONAL consolidation refactor, not a coverage prerequisite (see §4.6 rewording) | Documented in §4.6; PR #58 and PR #59 plans will inherit the same wording |
| Allowlist drift across surfaces (e.g., grafana migrated to a signed publisher in compose only, but the entry is missing from the compose allowlist) | Medium | Job WARNs only (plan D3 long-tail policy) → user adds entry → re-run cures | Acceptable: surfacing the warn forces a conscious review. Same shape as PR #56's policy. |
| Compose YAML walking misses an `image:` ref due to nested mappings or extension fields | Low | Some refs unverified silently | Format-gate test pins the walk against the existing `compose-image-digest-resolve` extractor convention (both walk top-level `services.<svc>.image:` only — explicitly documented). |
| Compose `extends:` pointing OUTSIDE the glob scope (e.g., an absolute path or a file not matching `docker-compose*.yml`) is invisible to the walker — R0 security-reviewer Finding 2 carry-forward | Low (no `extends:` in this repo today) | Some refs in the extended file would be unverified silently | Documented here so a future contributor adding `extends:` knows the gate's walker is structural-not-resolved; if `extends:` adoption becomes a pattern, extend the walker (PR #60 or PR #58 amend) to traverse extends-resolved files within the glob set. |
| Python `Path.glob` walks tracked AND untracked compose files; sibling `compose-image-digest-resolve` uses `git ls-files` (tracked-only). Risk: spurious WARN for refs in untracked compose files | Low (no untracked compose files today) | False-positive WARNs in CI log, no FAIL bypass | Accept the divergence in PR #57 (small noise risk only); align in PR #58 plan by adopting `git ls-files` for the GHA-surface walker too, or refactor in PR #60. R0 code-reviewer Finding 2 carry-forward. |
| Plan-doc Codex iteration runs over budget (force-stop on r3) | Per `pattern_signature_gate_scope_lock_per_phase` plan-doc cap | Iteration deferred | 2-round cap; if r3 needed, freeze plan and defer. |

---

## 6. Acceptance criteria

- [ ] `data/cosign/signed-images-compose.yml` exists with valid schema; header cross-links PR #56's `signed-images.yml`; ships `images: []`.
- [ ] `.github/workflows/ci.yml` has NEW `compose-cosign-verify` job sibling to `compose-image-digest-resolve`.
- [ ] `services/api/tests/unit/test_cosign_compose_signed_images.py` exists with ≥17 tests (parity with PR #56's coverage + cosign-installer SHA pin assertion + reconciliation assertion); all PASS locally.
- [ ] PR #56's `signed-images.yml` / `dockerfile-cosign-verify` job / `test_cosign_signed_images.py` UNCHANGED.
- [ ] CI on the PR branch: all jobs SUCCESS. `compose-cosign-verify` reports `SCANNED=0 FAIL=0` on the empty allowlist.
- [ ] R0 (parallel `code-reviewer` + `security-reviewer`) returns CLEAN PROCEED or one round of convergent fold.
- [ ] Plan-doc Codex iteration: max 2 rounds (per pattern).
- [ ] Implementation Codex iteration: max 3 rounds (per `pattern_codex_3round_implementation_iteration`).
- [ ] PR body uses `pattern_pr_body_verification_split` template.

---

## 7. Roll-back

Single revert commit reverses all changes. Reverting drops the compose-surface signature gate but leaves PR #56 (Dockerfile FROM) intact + the format/existence gates intact. Supply-chain posture returns to pre-PR-#57 state.

```bash
git revert <pr57-merge-sha>
```

---

## 8. Out-of-scope follow-ups (recorded for planning continuity)

- **PR #58** — extend cosign verify to GHA `services:` surface. Same shape; new `services-cosign-verify` job sibling to `gha-services-image-digest-resolve`; new `signed-images-gha-services.yml`.
- **PR #59** — extend cosign verify to GHA `uses:` surface. Same shape; new `actions-cosign-verify` job sibling to `gha-action-digest-resolve`; new `signed-images-gha-actions.yml`. Highest publisher-cosign-signed coverage (most GitHub Actions ARE Sigstore-signed today).
- **PR #60** — OPTIONAL cross-surface reconcile-all job + shared format-gate test helper (consolidation refactor; per-surface stale-checks remain authoritative without it). Conditional on PR #57 + #58 + #59 all merging first.
- **Memory updates (post-PR-#57-merge)** — `pattern_signature_gate_scope_lock_per_phase` 1× → 2× validation. `pattern_codex_3round_implementation_iteration` 1× → 2× (if r2 CLEAN PROCEED holds).
- **Optional: Renovate cosign-aware update strategy** — when Renovate bumps a compose image, also bump the per-surface allowlist's expected-cert-identity if same publisher continues to sign. Defer until allowlist coverage justifies automation.

---

## §0.1 Implementation amendments (2026-05-15)

Filled during PR #57 implementation per `pattern_plan_vs_impl_section_0_1_amendments`. All amendments are carry-forward from PR #56 §0.1 (same surface-agnostic decisions; only the data file path and the reconciliation surface differ). No new architect adjudication required because `pattern_signature_gate_scope_lock_per_phase` is now 2× validated (PR #56 plan-doc + PR #57 plan-doc).

### Amendment 1 — Phase 2 ships with `images: []` (empty allowlist)

**Background.** Same shape as PR #56 Amendment 1. The 7 unique compose `image:` refs in this repo (`pgvector/pgvector:pg16`, `redis:7-alpine`, `otel/opentelemetry-collector-contrib:0.104.0`, `prom/prometheus:v2.54.0`, `grafana/grafana:11.2.0`, `busybox:1.36`, `quay.io/keycloak/keycloak:25.0`) do not currently carry Sigstore signatures from their respective Docker Hub / quay.io publishers.

**Amendment.** `data/cosign/signed-images-compose.yml` ships with `images: []`. The file header documents the empty state, the example entry shape, and cross-references PR #56's `signed-images.yml` for schema reuse.

**Why this stays load-bearing.** PR #57 is framed explicitly as a **forward-compat scaffold** for compose surface. The three-layer defense activates the moment any compose `image:` ref is migrated to a signed publisher (grafana / prometheus / otel are the most plausible near-term candidates) — pure data-edit, no CI YAML / test changes.

### Amendment 2 — Empty-allowlist no-op path is an explicit AC

**Amendment.** The `compose-cosign-verify` job MUST exit 0 with `SCANNED=0 FAIL=0` when the allowlist is empty (after successful parse). This is the dominant Phase 2 code path. Job exits non-zero ONLY on (a) parse failure, (b) schema violation, (c) cosign verify rejection of an allowlisted ref, (d) stale-allowlist reconciliation failure.

**Test coverage.** Format-gate test vacuously passes per-entry assertions when `images: []`. Runner parser asserts `version == 1` and `images is None or list` regardless of contents.

### Amendment 3 — Implementation Codex iteration cap = 3 rounds (per `pattern_codex_3round_implementation_iteration`)

**Carry-forward.** R0 (parallel `code-reviewer` + `security-reviewer` agents) runs FIRST. Codex PR-as-diff rounds follow with hard cap at r3. Convergent findings between R0 + Codex r1 fold preemptively per `pattern_convergent_harness_findings_strong_signal`. CLEAN PROCEED at r2 is the typical exit (1× validated on PR #56).

### Amendment 4 — `sigstore/cosign-installer` pinned to commit `6f9f17788090df1f26f669e9d70d6ae9567deba6` (v4.1.2)

**Carry-forward.** Same SHA as PR #56 (resolved via `gh api repos/sigstore/cosign-installer/releases/latest` → `v4.1.2` published 2026-05-07 → commit `6f9f17788090df1f26f669e9d70d6ae9567deba6`). Future Renovate runs will auto-bump this pin uniformly across all surfaces.

### Amendment 5 — Explicit `PyYAML==6.0.3` install step in the job

**Carry-forward.** Same `python3 -m pip install --user 'PyYAML==6.0.3'` step as PR #56. `ubuntu-24.04` runner lacks system PyYAML; explicit install required. Version pinned for cross-environment parity with `services/api` venv.

### Amendment 6 — Schema validation lives in BOTH runner parser AND format-gate test (defense in depth)

**Carry-forward.** Runner Python parser checks: `version == 1`, `images is list-or-null`, required keys present, `identity_match in {literal, regexp}`, `tlog_mode == "required"`, `annotations empty`, regexp identities anchored `^...$`, no TAB/LF/CR in string fields. Format-gate test (`test_cosign_compose_signed_images.py`) checks the same plus image-ref regex shape + duplicate-image-ref uniqueness. Same defense-in-depth rationale as PR #56.

### Amendment 7 — Compose-surface reconciliation walks `services.<svc>.image:` via PyYAML

**New (compose-surface-specific deviation from PR #56).** PR #56's dockerfile reconciliation extracts FROM refs via regex line-walking. PR #57 extracts compose refs via PyYAML `safe_load` of every `docker-compose*.yml` / `.yaml` file matched by `Path.glob` (the filesystem glob; see §5 risk row + §0.2 R0 fold note on the divergence from the sibling `compose-image-digest-resolve` job's `git ls-files` scope) followed by `services.<svc>.image` key access. This matches the existing `compose-image-digest-resolve` extractor convention (grep-based) on intent (structural walk over compose surface) but uses PyYAML's structural parse instead of regex — avoiding false-positive matches against commented-out / non-services blocks.

The compose-vs-dockerfile difference is intentional: compose has structured YAML semantics (`services.<svc>.image:` is a well-typed location), while Dockerfile FROM is a line-prefix and only line-walking is appropriate.

---

### What did NOT change

- D1 (scope = compose top-level `image:` only): unchanged
- D2 (keyless trust root): unchanged
- D3 (separate per-surface allowlist `signed-images-compose.yml`): unchanged
- D4 (CI job sibling to `compose-image-digest-resolve`): unchanged
- D5 (format-gate test in `services/api/tests/unit/`): unchanged
- D6 (single-PR shape; plan-doc 2-round cap + implementation 3-round cap): unchanged. Plan-doc CLEAN PROCEED at r2.

### Local verification (no push this commit — GH Actions billing block)

- 21/21 new compose-cosign tests PASS
- 20/20 sibling supply-chain tests PASS (`test_dockerfile_digest_pin`, `test_compose_image_digest_pin`, `test_gha_services_image_digest_pin`, `test_gha_action_digest_pin`, `test_renovate_config`) — no regression
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` PASS
- `python -c "import yaml; yaml.safe_load(open('data/cosign/signed-images-compose.yml'))"` returns `{'version': 1, 'images': []}`
- PR #56's files NOT in this branch (this branch was cut from main, before PR #56 merged) — verified via `ls services/api/tests/unit/test_cosign*.py` returning only the compose test file
- Single-PR shape per plan D6

### §0.2 R0 fold (2026-05-15) — applied in same commit

R0 ran parallel `code-reviewer` + `security-reviewer` agents on the staged PR #57 diff per `pattern_harness_reviewer_codex_substitute`. Both verdicts: **FOLD-AND-PROCEED**. The findings are below; 2 folded into THIS commit (1 MED + 1 LOW), 1 MED DISMISSED after empirical verification, 3 LOW/NIT deferred to PR #58/#60.

| Severity | Source | Finding | Action |
|---|---|---|---|
| MED | security-reviewer (Q4) | Runner `annotations = entry.get("annotations") or {}` silently normalizes falsy non-dict values (`False`, `0`, `""`) to `{}`; format-gate test (`in (None, {})`) catches it but defense-in-depth fails | **FOLDED**: runner now uses `annotations = entry.get("annotations")` + `if annotations not in (None, {})` (mirrors test predicate exactly) |
| MED | code-reviewer | stderr capture redirection order `cosign_err=$(... 2>&1 >/dev/null)` claimed to invert stdout/stderr semantics; suggested swap to `>/dev/null 2>&1` | **DISMISSED** after empirical verification: `2>&1 >/dev/null` is the CORRECT order in command substitution (verified via `bash -c 'echo S; echo E >&2' 2>&1 >/dev/null` capture). The reviewer-suggested `>/dev/null 2>&1` would discard BOTH streams (also verified). PR #56 uses the same idiom and ships correctly. |
| LOW | security-reviewer (Q1) | Compose `extends:` pointing outside the glob scope is invisible to the structural walker; not documented in risks | **FOLDED**: §5 risk table row added; if `extends:` adoption becomes a pattern, walker extension lands in PR #60 or amend |
| LOW | code-reviewer | Python `Path.glob` includes untracked compose files; sibling `compose-image-digest-resolve` uses `git ls-files` — scope skew | **NOTED in plan §5**: low-risk today (no untracked compose files); align in PR #58 walker or PR #60 refactor |
| NIT | code-reviewer | `_COSIGN_INSTALLER_PIN_RE.search(body)` matches ANY cosign-installer pin in the workflow (including the sibling job's pin) — would falsely pass if the compose-cosign-verify pin disappeared once PR #56 merges | **DEFERRED to PR #60 shared-test-helper refactor**: known class; same gap exists in PR #56's test. Doesn't block Phase 2 standalone. |
| NIT | security-reviewer (Q4) | `allowlist_refs.discard("")` is dead code (the earlier per-entry completeness check would have already `sys.exit(1)`); no behavior impact | **DEFERRED** as a NIT cosmetic cleanup. |

**Convergence note**: 1× partial convergence — both reviewers flagged runner/test parity issues (code-reviewer focused on stderr capture; security-reviewer focused on annotations normalization). Only the security-reviewer finding survived empirical verification; stderr concern dismissed. Per `pattern_convergent_harness_findings_strong_signal`, when convergence holds it triggers preemptive fold — when one of the two findings is a false positive, document the dismissal rationale (this row) so a future reader doesn't relitigate it.

**Local re-verification after R0 fold** (in addition to the §0.1 pre-R0 PASS):
- 21/21 PR #57 cosign tests still PASS
- 20/20 sibling supply-chain tests still PASS
- YAML parse OK on ci.yml + signed-images-compose.yml
- Annotations strict-check covered by existing `test_cosign_compose_allowlist_annotations_must_be_empty_in_phase2` (which already uses `in (None, {})`) — runner now matches test predicate.

### §0.3 Codex r1 fold (2026-05-15) — applied as r2 amend on top of R0 commit

Codex r1 verdict: **FOLD-AND-PROCEED**. R0 fold audit confirmed all R0 changes + dismissal rationale are present at file:line precision; PR #56 idiom carry-forward audit (5/5 spot-check) confirmed verbatim reuse. 1 net-new LOW finding folded:

| Severity | Source | Finding | Fix location | Fix shape |
|---|---|---|---|---|
| LOW | Codex r1 | Plan-vs-impl wording drift: §0.1 Amendment 7 + §4.4 said the runner walks "every tracked `docker-compose*.yml` / `.yaml` file" but the implementation uses `Path.glob` (filesystem-level, NOT tracked-only). The §5 risk row already documents the glob-vs-`git ls-files` divergence; the §0.1 / §4.4 prose contradicted it | `docs/plans/pr57-cosign-compose-signature-verify.md` §4.4 + §0.1 Amendment 7 | both wordings rewritten to reference `Path.glob` filesystem-level walk with explicit cross-link to §5 risk row + §0.2 R0 fold note |

**Class-of-issue grep**: same wording drift appeared in BOTH §4.4 + §0.1 Amendment 7. Both fixed in this fold. §5 risk-row wording was already correct (no edit).

**Test count growth this fold:** 0 (doc-only fold; no test changes required).

**Implementation iteration cap status:** Codex r1 was round 1 of 3 (per Amendment 3). r2 is the convergence test — expect CLEAN PROCEED (no code changes in this fold, only doc reconciliation).

### §0.4 Codex r2 (2026-05-15) — CLEAN PROCEED

Codex r2 convergence test: **CLEAN PROCEED**. R1 fold (plan §4.4 + §0.1 Amendment 7 wording) confirmed present; both sections now explicitly describe `Path.glob` / filesystem-level compose walking with the recursive variants and the divergence from sibling `compose-image-digest-resolve`'s `git ls-files` tracked-only scope. 0 new findings.

**Exit token**: ready-to-push when GH Actions billing unblocks. `gh pr create --base main --head chore/cosign-compose-signature-verify` once unblocked.

**Implementation iteration cap status**: 2× validated (PR #56 → CLEAN PROCEED at r2 + PR #57 → CLEAN PROCEED at r2). `pattern_codex_3round_implementation_iteration` bumped to 2× validation post-merge.
