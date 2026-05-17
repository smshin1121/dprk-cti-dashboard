# PR #61 Plan — Cosign signature verification for GHA `services:` image refs (Phase 3, GHA-services surface)

**Phase:** Supply-chain hardening sweep, follow-up to PR #56 (Dockerfile FROM Phase 1) and PR #57 (compose Phase 2). Third surface of `pattern_signature_gate_scope_lock_per_phase` — extending the keyless Sigstore signature gate from Dockerfile FROM image refs + top-level `docker-compose*.yml image:` refs to `jobs.<job>.services.<svc>.image:` refs in `.github/workflows/*.yml`.
**Status:** Draft 2026-05-17. Plan-doc pre-implementation gate (no commit, no PR yet).
**Predecessors:** PR #56 (cosign Dockerfile FROM Phase 1, merged), PR #57 (cosign compose Phase 2, merged), PR #58 / #59 / #60 (Dockerfile/compose final shapes + cleanup bundle, all merged through `4fdab32`).
**Successors:** PR #62 (GHA `uses: action@sha` Phase 4, fourth + final surface), OPTIONAL post-Phase-4 cross-surface reconcile-all refactor.
**Decision driver:** Session-resume directive 2026-05-17 — autonomous next-phase execution per cycle-15 recommendation. Codex pre-merge GO round to follow at merge gate.

---

## 1. Goal

Apply the same three-layer defense to `gha-services-image-digest-resolve` siblings: in addition to the existing format gate (`test_gha_services_image_digest_pin.py` — pin must be present) and existence gate (`gha-services-image-digest-resolve` CI job — manifest must be reachable in registry), verify that the pinned digest was **signed by the publisher you expect** via Sigstore cosign (Fulcio + Rekor, keyless).

**Surface inventory (`PyYAML safe_load` walking `.github/workflows/*.yml` → `jobs.<job>.services.<svc>.image`):**

| Image (base ref, pre-`@sha256:` strip) | Refs | Workflow / job / svc locations |
|---|---:|---|
| `pgvector/pgvector:pg16` | 6 | `ci.yml`: `frontend-e2e/postgres`, `db-migrations/postgres`, `data-quality-tests/postgres`, `api-integration/postgres`, `contract-verify/postgres`, `correlation-perf-smoke/postgres` |
| `redis:7-alpine` | 3 | `ci.yml`: `frontend-e2e/redis`, `contract-verify/redis`, `correlation-perf-smoke/redis` |
| **TOTAL** | **9** | **2 unique images, 1 workflow file** |

**Phase 3 ships EMPTY allowlist (same shape as PR #56 Phase 1 + PR #57 Phase 2).** Of the 2 unique services-image refs in this repo, neither `pgvector/pgvector` nor `redis` is confirmed cosign-signed by their Docker Hub publishers as of 2026-05-17. A future migration (e.g., switch to a Sigstore-signed Postgres or Redis publisher mirror) becomes a pure allowlist data-edit once the gate is in place.

**Cross-surface duplication note (informational, NOT a scope expansion):** both `pgvector/pgvector:pg16` and `redis:7-alpine` also appear in `docker-compose.yml`. The compose allowlist (`signed-images-compose.yml`) and the new GHA-services allowlist (`signed-images-gha-services.yml`) will hold parallel entries when these publishers eventually sign — per PR #57 D3 rationale, separate per-surface files preserve clean per-surface ownership and stale-check authority. The OPTIONAL cross-surface reconcile-all refactor (deferred to post-Phase-4) is the place to lift this duplication if it ever becomes load-bearing.

**Non-goal (deferred to follow-up plans):**
- Cosign verification for `Dockerfile FROM` (covered by PR #56)
- Cosign verification for `docker-compose*.yml image:` (covered by PR #57)
- Cosign verification for GHA `uses: action@sha` (Phase 4, deferred to PR #62)
- Sigstore policy-controller / admission webhook integration
- Cross-surface reconcile-all job (deferred to post-Phase-4 OPTIONAL refactor; see §4.6)
- `jobs.<job>.container.image:` surface (top-level container image, out of scope per same rationale as `gha-services-image-digest-resolve` job — no `container.image:` refs in this repo today; trivially extends if adopted)

---

## 2. Locked Decisions (2026-05-17)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | Scope = **exactly `.github/workflows/*.yml` `jobs.<job>.services.<svc>.image:` refs** (NOT Dockerfile FROM, NOT compose `image:`, NOT GHA `uses:`, NOT `jobs.<job>.container.image:`). | Smallest matrix that extends Phase 1+2's pattern by one validated surface. 3rd validation of `pattern_signature_gate_scope_lock_per_phase`. Mirrors the `gha-services-image-digest-resolve` job's own scope exactly. |
| **D2** | Trust root = **keyless via Sigstore Fulcio + Rekor** (per-entry OIDC issuer + certificate-identity pinning). Same as PR #56 / #57 D2 — no per-surface trust-root divergence. | Carries forward PR #56/#57 D2 rationale. Key management cost saved; transparency log audits every signature. |
| **D3** | **Separate per-surface allowlist file**: `data/cosign/signed-images-gha-services.yml` (NOT the existing `signed-images.yml` or `signed-images-compose.yml`). Each surface gets its own allowlist file. | Carries forward PR #57 D3 rationale verbatim. Cross-surface duplication on the 2 unique images today is acceptable: each surface's stale-check authority is preserved. Hard objective trigger for promoting the OPTIONAL post-Phase-4 reconcile-all refactor to REQUIRED (per Codex r1 finding): once `>=3` unique **signed** (allowlisted, not just present-in-surface) image refs are duplicated across surfaces, OR two consecutive Renovate/image-refresh cycles require the same signer-identity / digest edit applied to multiple allowlists in lockstep. Until either threshold trips, separate per-surface files remain canonical. |
| **D4** | NEW CI job `gha-services-cosign-verify` placed as **sibling to `gha-services-image-digest-resolve`** (not nested). Runs on same trigger and `permissions: contents: read`. | Mirrors PR #56 D4 + PR #57 D4. Per-layer blame-bisect: a signature failure on GHA services should be diagnosable independently from the manifest-inspect failure or the Dockerfile/compose signature failures. |
| **D5** | Format-gate test: `services/api/tests/unit/test_cosign_gha_services_signed_images.py` validates schema (same anti-pattern coverage as PR #56/#57 plus `_KNOWN_OIDC_ISSUERS` allowlist invariants + cross-phase cosign-installer SHA equality assertion + **cross-phase `_KNOWN_OIDC_ISSUERS` set-parity assertion** — per Codex r1 finding). Per `pattern_service_local_duplication_over_shared`: duplicate the test architecture, do NOT import from Phase 1/2 test modules. The cross-phase issuer-set parity test extracts `_KNOWN_OIDC_ISSUERS` from each cosign-allowlist test module's source via `Path.read_text()` + `ast.parse` (NOT `import`, NOT regex — r2 fold replaced an earlier regex-based extractor to defeat double-quoted-comment-URL false-positives), walks top-level `Assign` nodes, reads string-constant elements directly, and asserts pairwise equality across all 3 modules (extending to 4 in Phase 4). | Mirrors PR #56/#57 D5. Format-gate parity across surfaces is itself a check that no surface relaxes invariants. Cross-phase SHA equality test prevents the class where one surface's cosign-installer pin drifts independently of the others — Renovate would update them in lockstep today, but a manual edit or partial revert could split them. `_KNOWN_OIDC_ISSUERS` allowlist (from PR #60 cycle-14 cleanup) is duplicated as a per-test constant, not imported, per service-local-duplication. The static-source parity test closes the Codex r1 finding that lockstep is otherwise manual-only (drift latent until an issuer-using entry is added — but the parity test fails loud the moment one of the 3 source files mutates the set differently from the others). |
| **D6** | Single-PR shape (no split). 4 files: allowlist data + CI job + format-gate test + this plan. Plan-doc Codex iteration HARD-CAPPED at **2 rounds** per `pattern_signature_gate_scope_lock_per_phase` plan-doc cap. Implementation Codex iteration HARD-CAPPED at **3 rounds** per `pattern_codex_3round_implementation_iteration` (validated 2× on PR #56 + PR #57). | Iteration discipline carries forward. R0 parallel reviewers run first. Convergent findings fold preemptively. |

---

## 3. Scope

### In scope (this PR / Phase 3, ~4 files)

| File | Change | Approx delta |
|---|---|---:|
| `data/cosign/signed-images-gha-services.yml` | NEW — initial allowlist (Phase 3 EMPTY; same schema-only docs as PR #56/#57; cross-link to both in header). | ~80 lines |
| `.github/workflows/ci.yml` | NEW `gha-services-cosign-verify` job sibling to `gha-services-image-digest-resolve`. Reuses PR #56/#57 idioms verbatim (PyYAML install step, `if !` guard, stderr capture, schema validation parity, reconciliation against current GHA services-block `image:` refs). | ~220 lines |
| `services/api/tests/unit/test_cosign_gha_services_signed_images.py` | NEW — ≥20 static-source assertions matching PR #56/#57 coverage + cross-phase cosign-installer SHA equality + per-module `_KNOWN_OIDC_ISSUERS` allowlist tests + cross-phase issuer-set static-source parity (duplicated, not imported, per service-local-duplication pattern). | ~340 lines |
| `docs/plans/pr61-cosign-gha-services-signature-verify.md` | NEW — this plan + §0.1 amendment slot reserved. | ~220 lines |

### Out of scope (DO NOT TOUCH this PR)

- `data/cosign/signed-images.yml` (Dockerfile FROM allowlist; PR #56 owns it)
- `data/cosign/signed-images-compose.yml` (compose allowlist; PR #57 owns it)
- `.github/workflows/ci.yml`'s `dockerfile-cosign-verify` / `compose-cosign-verify` jobs (no changes; new job runs alongside)
- `test_cosign_signed_images.py` / `test_cosign_compose_signed_images.py` (no changes)
- `Dockerfile`, `services/<svc>/Dockerfile` (no FROM digest changes)
- `docker-compose*.yml` (no `image:` changes)
- `gha-services-image-digest-resolve` existing job (no changes; new job runs alongside)
- `test_gha_services_image_digest_pin.py` existing format gate (no changes)
- `renovate.json` (no changes — Renovate auto-bumps cosign-installer uniformly across all surface jobs)
- GHA `uses:` surface (deferred to Phase 4 / PR #62)
- `jobs.<job>.container.image:` surface (no refs in repo today)
- Cross-surface reconcile-all job (deferred to OPTIONAL post-Phase-4 refactor; see §4.6)

---

## 4. Design

### 4.1 Cosign keyless verification (carry-forward from PR #56 / #57 D2)

```bash
cosign verify <image>@<digest> \
  --certificate-identity "<expected-subject>" \
  --certificate-oidc-issuer "<expected-issuer>"
```

Same exit-code semantics as PR #56/#57. No `--insecure-ignore-tlog`, `--allow-insecure-registry`, `--allow-http-registry`, `--private-infrastructure`, `--insecure-ignore-sct` (all 5 anti-pattern flags carried forward from PR #56 R0 + Codex r1 extension + PR #57 carry-forward).

### 4.2 Allowlist schema

Identical to PR #56's `signed-images.yml` and PR #57's `signed-images-compose.yml`:
- `version: 1`
- `images: []` (empty Phase 3; populate as upstream publishers adopt cosign)
- Each entry: `image` (required), `certificate_identity` (required), `certificate_oidc_issuer` (required), `identity_match: literal | regexp` (optional, default `literal`), `tlog_mode: required` (required value), `annotations: {}` (must be empty or absent), `notes` (free-form).

Header cross-references PR #56's `signed-images.yml` AND PR #57's `signed-images-compose.yml` for schema reuse + documents the per-surface separation rationale.

### 4.3 CI job placement

```yaml
gha-services-cosign-verify:
  runs-on: ubuntu-latest
  permissions:
    contents: read
  steps:
    - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd  # v5
    - uses: sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6  # v4.1.2
    - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405  # v6
      with:
        python-version: "3.12"
    - name: Ensure PyYAML available for allowlist + workflow parser
      run: python3 -m pip install --user 'PyYAML==6.0.3'
    - name: Verify cosign signatures for allowlisted GHA services-block image refs
      run: |
        # Parse allowlist via if-bang Python heredoc (PR #56/#57 idiom).
        # Reconcile against current jobs.<job>.services.<svc>.image refs via PyYAML.
        # Per-entry cosign verify with stderr capture.
        # Anti-pattern guards identical to PR #56/#57.
        ...
```

Sibling to `gha-services-image-digest-resolve` (ci.yml line ~1615). Insertion point: immediately after `gha-services-image-digest-resolve`'s final `exit "$FAIL"` line at ~1694 and before the `gha-action-digest-resolve` job header at ~1696.

### 4.4 Reconciliation logic (carries forward PR #56 Codex r1 finding + PR #57 amendments)

The runner Python parser, after schema validation, walks every `.github/workflows/*.yml` / `.yaml` file via `Path('.github/workflows').glob('*.yml')` + `.yaml`, and extracts every `jobs.<job>.services.<svc>.image:` value via PyYAML `safe_load`. This walker is **identical in shape** to the existing `gha-services-image-digest-resolve` extractor — no divergence (unlike the compose surface where structure differs across `image:`-keyed sub-mappings). Mirror PR #56/#57 reconciliation semantics:

- **stale allowlist entries** (refs in `signed-images-gha-services.yml` but NOT in any current workflow services-block `image:` ref) → FAIL loud. The allowlist is the policy contract.
- **unlisted GHA-services refs** (current ref, no allowlist entry) → WARN (plan D3 long-tail policy; mirrors PR #56/#57).

This is **surface-scoped reconciliation, and that scope is sufficient on its own** (carry-forward from PR #57 §4.4 wording).

### 4.5-pre — regexp identity dispatch (explicit carry-forward from PR #56 / #57)

The runner and test BOTH dispatch on `identity_match`:
- `literal` (default) → `cosign verify ... --certificate-identity <exact-string>`
- `regexp` → `cosign verify ... --certificate-identity-regexp <anchored-pattern>` (pattern MUST be anchored with `^...$` per PR #56 R0 security-reviewer Finding 2, enforced by both the runner Python parser and the format-gate test).

No new flag set. Implementation reuses PR #56/#57 idiom verbatim.

### 4.5 Anti-patterns explicitly forbidden (carry-forward from PR #56/#57 §4.5 + R0 + Codex r1)

- NO process-substitution around the cosign verify call (masks exit code)
- NO bare `extract_exit=$?` capture under `set -euo pipefail` (unreachable; PR #55 silent-pass class)
- NO insecure-flag passthrough to cosign verify: `--insecure-ignore-tlog`, `--allow-insecure-registry`, `--allow-http-registry`, `--private-infrastructure`, `--insecure-ignore-sct` (all 5 enforced by format-gate test)
- NO `tlog_mode: optional` allowlist value (rejected by format-gate test and runner parser)
- NO TAB / LF / CR in any allowlist string field (rejected by both layers)
- NO `identity_match: regexp` with an unanchored pattern (must be `^...$`)
- NO non-empty `annotations` field until --annotations passthrough is implemented (refuse-to-scan rather than silent-skip)
- NO `certificate_oidc_issuer` outside the `_KNOWN_OIDC_ISSUERS` allowlist (carry-forward from PR #60 cycle-14 cleanup; reject unknown issuers at the **format-gate test layer** — Codex r1 fold per PR #61, narrowed from earlier "both layers" wording). Defense-in-depth note: the runner forwards `certificate_oidc_issuer` to `cosign verify --certificate-oidc-issuer` directly, so an unknown issuer that somehow bypassed the format-gate would still fail loud on Sigstore's per-entry OIDC issuer check (cosign rejects any cert whose issuer doesn't match `--certificate-oidc-issuer`). Adding a runner-side allowlist check is OPTIONAL future hardening (would close the gap that format-gate is bypassable by a contributor with merge rights — currently format-gate runs as a required check, so the gap is theoretical); track as post-Phase-4 follow-up across all 3 (then 4) runners in lockstep.

### 4.5b — Cross-phase invariant tests (NEW assertion class)

Two cross-surface invariant tests are added in PR #61 to harden the parity that `pattern_service_local_duplication_over_shared` otherwise relies on manual lockstep edits to maintain:

**4.5b.1 — Cross-phase cosign-installer SHA equality.** The `sigstore/cosign-installer@<sha>` pin in the new `gha-services-cosign-verify` job MUST equal the same pin in the existing `dockerfile-cosign-verify` AND `compose-cosign-verify` jobs. The test reads ci.yml as static source and extracts each job's cosign-installer SHA via regex anchored to the job body, then asserts string equality across all three. Catches the class where a manual edit or partial revert splits the cosign-installer version across surfaces — Renovate would update them in lockstep, but a human edit cannot be assumed lockstep-safe. (Phase 4 extends this to four jobs.)

**4.5b.2 — Cross-phase `_KNOWN_OIDC_ISSUERS` set parity (Codex r1 fold + r2 AST refactor).** The `_KNOWN_OIDC_ISSUERS` constant duplicated in `test_cosign_signed_images.py`, `test_cosign_compose_signed_images.py`, and the new `test_cosign_gha_services_signed_images.py` MUST contain the same set of issuer URLs. The test reads each sibling test module's source via `Path.read_text()`, parses it with `ast.parse` (NOT `import`, NOT regex — Codex r2 fold; the AST walk strips comments/docstrings during tree-building, so any future `# See "https://..."` reference inside the frozenset block cannot leak into the extracted set), walks top-level `Assign` nodes for `_KNOWN_OIDC_ISSUERS = frozenset({...})`, reads the string-constant elements of the inner `Set`/`List`/`Tuple` AST node, and asserts pairwise equality across all 3 modules. Fails loud the moment any module mutates the set differently from the others — closes the Codex r1 finding that the lockstep-edit invariant is otherwise latent until an issuer-using allowlist entry lands on a drifted surface.

Per `pattern_service_local_duplication_over_shared`, both invariant tests are service-local to api and do NOT import from PR #56/#57 test modules — the static-source read pattern keeps the invariant duplication-tolerant while still catching drift.

### 4.6 Cross-surface reconciliation (OPTIONAL future refactor — not a coverage prerequisite, BUT with objective promotion trigger)

Carry-forward from PR #57 §4.6 + D3 objective trigger (Codex r1 finding). A cross-surface reconcile-all job comparing the union of all 4 surface refs against the union of all 4 per-surface allowlists is **OPTIONAL today** and does NOT close any coverage gap that the per-surface stale-checks don't already close.

**Promotion trigger (objective; Codex r1 fold)**: the refactor becomes REQUIRED (no longer optional) when EITHER:
- (a) `>=3` unique image refs are duplicated across 2+ surfaces AND all duplicated copies are signed (i.e., live allowlist entries, not empty-allowlist scaffolds — the empty-allowlist state today does NOT count toward this threshold); OR
- (b) Two consecutive Renovate / image-refresh cycles each require the same signer-identity or digest edit applied to multiple allowlists in lockstep (signal: manual lockstep editing has become routine maintenance burden).

Until either threshold trips, separate per-surface files remain canonical. The threshold is intentionally generous: 2 duplicated signed entries (one being today's hypothetical pgvector + redis cross-listing) is still well within "edit-twice tolerable" range; 3+ crosses the threshold where forgetting to update one allowlist becomes a real drift risk.

**Plan**: defer to post-Phase-4 as a refactor whose REQUIRED/OPTIONAL status is governed by the trigger above. No PR #56 / #57 / #61 / #62 implementation change depends on it.

---

## 5. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|:---:|:---:|---|
| Empty Phase 3 allowlist means the gate idle-passes — same "forward-compat scaffold" framing as PR #56/#57 | Certain (Phase 3 ships empty) | None today; load-bearing on next signed-publisher migration | Documented in plan + allowlist header; format-gate test covers schema regardless |
| Sigstore Fulcio / Rekor outage during CI | Medium | Job FAILs on `cosign verify` network error | Same mitigation as PR #56/#57 (fail-loud > silent skip; retry-cures; document the rerun playbook). Carry-forward Codex r1 stderr-capture so TUF refresh errors are distinguishable from signature rejections in logs. |
| Cross-phase cosign-installer SHA drift (manual edit splits surface jobs) | Low (Renovate auto-bumps lockstep) | One surface verifies under a stale installer | NEW cross-phase SHA equality test (§4.5b) — fails loud when any of the 3 (then 4, post-Phase-4) jobs' cosign-installer pins diverge. |
| `_KNOWN_OIDC_ISSUERS` allowlist drift across surfaces (a new issuer added to one test but not others) | Low (the constant holds 5 known Sigstore issuers today; identical across all 3 phase test modules; drift is latent until an issuer-using entry lands on a drifted surface) | Format-gate test of one surface rejects a `certificate_oidc_issuer` value that the other surfaces' tests would accept | Per `pattern_service_local_duplication_over_shared`: duplicate the constant in each test module. **NEW (Codex r1 + r2 folds)**: cross-phase static-source parity assertion in `test_cosign_gha_services_signed_images.py` reads the source of all cosign-allowlist test modules (Path.read_text + AST parse; no import, no regex). r2 fold replaced the regex extractor with `ast.parse` walking top-level `_KNOWN_OIDC_ISSUERS = frozenset({...})` assignments and reading string-constant elements directly — defeats the comment-URL false-positive class that the regex+`startswith("https://")` filter still left open. Fails loud the moment any module mutates the set differently from the others — closes the "latent until used" gap. |
| Cross-surface duplication today (pgvector + redis appear in both compose and GHA services) | Certain (2/2 unique images cross-listed) | Operator must update 2 allowlist entries to migrate one publisher to signed | Documented in §1 + §4.6; per-surface ownership preferred over shared file. The OPTIONAL post-Phase-4 reconcile-all refactor is the place to lift this if it becomes painful. |
| GHA workflow YAML walker false-positive on `image:` keys in step `with:` blocks (e.g. `docker/build-push-action` consumers) | Low (walker is `jobs.<job>.services.<svc>.image:` only, not `jobs.<job>.steps[].with.image:`) | None — structural walker scope is well-defined | Format-gate test pins the walker shape; reconciliation extractor uses the same structural walk as the existing `gha-services-image-digest-resolve` job extractor. |
| `jobs.<job>.container.image:` adoption in a future PR is invisible to the walker (out of scope today, but a real GHA YAML location) | Low (no `container.image:` refs in repo today) | A future `container:` adopter's image would be unverified by the cosign gate (and ALSO by the existing `gha-services-image-digest-resolve` job — both surface jobs have the same gap) | Documented in §3 out-of-scope; if `container:` adoption becomes a pattern, both the existence-gate (PR #52 job) and the signature-gate (this job) need walker extension in lockstep — record as follow-up. |
| Reusable workflow `uses:` external references invisible to walker | Low (no external reusable workflow imports today) | External reusable workflows' service blocks are unscanned | Same gap as existing PR #52 `gha-services-image-digest-resolve` job — accept the same scope. Carry-forward from `test_gha_services_image_digest_pin.py` header comment. |
| Docker Hub / GHCR / quay manifest+signature rate limit (shared GHA runner IP — `pitfall_docker_hub_manifest_rate_limit` carry-forward) | Low for empty-allowlist Phase 3; medium once entries land + concurrent surface jobs all hit same registry | One or more surface jobs FAIL with HTTP 429 / "too many requests" on `cosign verify` or `docker manifest inspect` | Rerun-cures (transient class). When the class becomes a regular failure mode post-allowlist-population: dedupe per-image cosign verify across surfaces (each unique digest verified once per CI run via job dependency or a job-output cache), OR move to authenticated registry pulls. Documented here for diagnostic recognition. |
| Sigstore TUF root rotation / trust-root metadata refresh failure (distinct from Fulcio/Rekor outage) | Low (TUF root rotations are infrequent and pre-announced) | Job FAILs with `error verifying TUF metadata` or `failed to update trust root`; distinct from "cosign verify rejected" | Bump `sigstore/cosign-installer` SHA to the version that ships the new trust root; Renovate auto-bump catches this in the normal cycle. If a rotation lands between Renovate bumps, hold the failing PR + bump installer pin in a single-line fix commit. Carry-forward Codex r1 stderr capture distinguishes TUF errors from signature rejections in logs. |
| Plan-doc Codex iteration runs over budget (force-stop on r3) | Per `pattern_signature_gate_scope_lock_per_phase` plan-doc cap | Iteration deferred | 2-round cap; if r3 needed, freeze plan and defer. |

---

## 6. Acceptance criteria

- [ ] `data/cosign/signed-images-gha-services.yml` exists with valid schema; header cross-links PR #56 + PR #57 allowlists; ships `images: []`.
- [ ] `.github/workflows/ci.yml` has NEW `gha-services-cosign-verify` job sibling to `gha-services-image-digest-resolve`.
- [ ] `services/api/tests/unit/test_cosign_gha_services_signed_images.py` exists with ≥20 tests (parity with PR #56/#57 coverage + cross-phase cosign-installer SHA equality + per-module `_KNOWN_OIDC_ISSUERS` allowlist tests + cross-phase `_KNOWN_OIDC_ISSUERS` static-source set-parity test); all PASS locally.
- [ ] PR #56's `signed-images.yml` / `dockerfile-cosign-verify` / `test_cosign_signed_images.py` UNCHANGED.
- [ ] PR #57's `signed-images-compose.yml` / `compose-cosign-verify` / `test_cosign_compose_signed_images.py` UNCHANGED.
- [ ] CI on the PR branch: all jobs SUCCESS. `gha-services-cosign-verify` reports `SCANNED=0 FAIL=0` on the empty allowlist.
- [ ] R0 (parallel `code-reviewer` + `security-reviewer`) returns CLEAN PROCEED or one round of convergent fold.
- [ ] Plan-doc Codex iteration: max 2 rounds (per pattern).
- [ ] Implementation Codex iteration: max 3 rounds (per `pattern_codex_3round_implementation_iteration`).
- [ ] Pre-merge Codex GO round (per `pattern_pre_merge_codex_round`): single GO/HOLD/BLOCK verdict on blast radius / hotfix path / breaking changes / time bombs.
- [ ] PR body uses `pattern_pr_body_verification_split` template (✅ vs 🟡 pending CI / manual smoke).

---

## 7. Roll-back

Single revert commit reverses all changes. Reverting drops the GHA-services-surface signature gate but leaves PR #56 (Dockerfile FROM) and PR #57 (compose) intact + the format/existence gates intact. Supply-chain posture returns to pre-PR-#61 state.

```bash
git revert <pr61-merge-sha>
```

---

## 8. Out-of-scope follow-ups (recorded for planning continuity)

- **PR #62 — Phase 4** — extend cosign verify to GHA `uses: action@sha` surface. Same shape; new `actions-cosign-verify` job sibling to `gha-action-digest-resolve`; new `signed-images-gha-actions.yml`. Highest publisher-cosign-signed coverage (most GitHub Actions ARE Sigstore-signed today via `https://token.actions.githubusercontent.com` issuer). Cross-phase SHA equality test extends to 4 jobs.
- **OPTIONAL post-Phase-4** — cross-surface reconcile-all job + shared format-gate test helper (consolidation refactor; per-surface stale-checks remain authoritative without it). Conditional on PR #56 + #57 + #61 + #62 all merged.
- **Memory updates (post-PR-#61-merge)** — `pattern_signature_gate_scope_lock_per_phase` 2× → 3× validation. `pattern_codex_3round_implementation_iteration` 2× → 3× (if r2 CLEAN PROCEED holds). `pattern_three_layer_defense_for_addressable_refs` L3 2× → 3× validated (Dockerfile + compose + GHA services).
- **Optional: Renovate cosign-aware update strategy** — when Renovate bumps a GHA services image, also bump the per-surface allowlist's expected-cert-identity if same publisher continues to sign. Defer until allowlist coverage justifies automation.

---

## §0.1 Implementation amendments (2026-05-17)

Filled during PR #61 implementation per `pattern_plan_vs_impl_section_0_1_amendments`.

### Amendment 1 — Phase 3 ships with `images: []` (empty allowlist)

**Carry-forward from PR #56/#57 Amendment 1.** The 2 unique GHA services-image refs in this repo (`pgvector/pgvector:pg16`, `redis:7-alpine`) do not currently carry Sigstore signatures from their Docker Hub publishers. `data/cosign/signed-images-gha-services.yml` ships with `images: []`. The file header documents the empty state, the example entry shape, and cross-references PR #56's `signed-images.yml` + PR #57's `signed-images-compose.yml` for schema reuse.

### Amendment 2 — Empty-allowlist no-op path is an explicit AC

**Carry-forward from PR #57 Amendment 2.** The `gha-services-cosign-verify` job MUST exit 0 with `SCANNED=0 FAIL=0` when the allowlist is empty (after successful parse). This is the dominant Phase 3 code path.

### Amendment 3 — Implementation Codex iteration cap = 3 rounds

**Carry-forward.** R0 (parallel `code-reviewer` + `security-reviewer` agents) runs FIRST per `pattern_harness_reviewer_codex_substitute`. Codex PR-as-diff rounds follow with hard cap at r3. R0 + Codex r1 ran in parallel for PR #61.

### Amendment 4 — `sigstore/cosign-installer` pin = `6f9f17788090df1f26f669e9d70d6ae9567deba6` (v4.1.2)

**Carry-forward from PR #56/#57.** Same SHA across all 3 cosign-verify jobs. Cross-phase SHA equality test (NEW in PR #61) anchors this invariant going forward.

### Amendment 5 — Explicit `PyYAML==6.0.3` install step in the job

**Carry-forward from PR #56/#57.** Same `python3 -m pip install --user 'PyYAML==6.0.3'` step.

### Amendment 6 — Schema validation lives in BOTH runner parser AND format-gate test (defense in depth)

**Carry-forward from PR #56/#57.** Runner Python parser checks: version, list/null images, required keys present, identity_match, anchored regexp, tlog_mode, annotations empty, control chars. Format-gate test (`test_cosign_gha_services_signed_images.py`) checks the same plus image-ref regex shape + duplicate-image-ref uniqueness + `_KNOWN_OIDC_ISSUERS` membership (PR #60 cycle-14 cleanup carry-forward) + cross-phase invariants (NEW in PR #61, see §4.5b).

### Amendment 7 — GHA-services-surface reconciliation walks `jobs.<job>.services.<svc>.image` via PyYAML

**New (GHA-services-surface specific deviation from PR #56/#57).** PR #56's dockerfile reconciliation extracts FROM refs via regex line-walking. PR #57's compose reconciliation walks compose YAML files via `Path.glob("docker-compose*.yml")` + PyYAML structural parse. PR #61's GHA-services reconciliation walks `.github/workflows/*.yml` + `.yaml` via `Path('.github/workflows').glob('*.yml')` + PyYAML structural parse of `jobs.<job>.services.<svc>.image`. This matches the existing `gha-services-image-digest-resolve` job's extractor EXACTLY (no walker divergence for this surface, unlike compose where the sibling job uses grep).

### §0.2 R0 + Codex r1 fold (2026-05-17) — applied in same commit

R0 (parallel `code-reviewer` + `security-reviewer`) + Codex r1 ran in parallel. 3 findings folded into THIS commit before push (1 from Codex, 1 from security-reviewer, 1 plan-only from Codex):

| Severity | Source | Finding | Action |
|---|---|---|---|
| LOW | Codex r1 | `findall(body)` for SHA equality is body-wide; would PASS if one cosign-verify job lost its installer pin while the other two stayed equal | **FOLDED**: `test_ci_gha_services_cosign_installer_sha_equality_across_all_jobs` now isolates each expected cosign-verify job's body via `_EXPECTED_COSIGN_VERIFY_JOBS` tuple + per-job regex; asserts exactly 1 pin per job + cross-job equality |
| LOW | Codex r1 | Plan §4.5 wording claims `_KNOWN_OIDC_ISSUERS` rejection happens at BOTH runner parser AND format-gate; impl only enforces at format-gate (mirrors PR #56/#57 historical truth) | **FOLDED (plan-only)**: §4.5 wording narrowed to "format-gate test layer"; runner-side check tagged as OPTIONAL post-Phase-4 hardening (would close the theoretical bypass where a contributor with merge rights skips format-gate); defense-in-depth rationale documented |
| LOW | security-reviewer | `_STRING_LITERAL_RE.findall(block_body)` extracts ALL double-quoted strings; would false-positive if a future contributor adds a `# See "https://example.com"` comment line INSIDE the `_KNOWN_OIDC_ISSUERS` frozenset block | **FOLDED**: `_extract_known_oidc_issuers_from_source()` now filters to `s.startswith("https://")`. No live false-positive today (no double-quoted comment URLs in any sibling module), but defense-in-depth fix |
| LOW | code-reviewer | `while ... read -r ... || [ -n "$image" ]` carry-forward pattern: theoretically silent on non-EOF `read` errors when `$image` is non-empty | **NOTED** in §0.2 (not folded; this is a 3-phase shared idiom inherited from PR #56/#57. Class-of-issue, not regression. Track for the post-Phase-4 consolidation refactor across all 3 → 4 jobs in lockstep) |

**Convergence note**: 2× partial convergence — Codex finding 2 + security-reviewer finding 1 both touched cross-phase invariant test fragility. Both folded per `pattern_convergent_harness_findings_strong_signal`.

**Class-of-issue sweep**: The runner-side `_KNOWN_OIDC_ISSUERS` gap exists in PR #56/#57 runners too. Per `pattern_signature_gate_scope_lock_per_phase` (3× validated), the fix belongs in a post-Phase-4 consolidation PR touching all 3+1 runners in lockstep, NOT a Phase 3 scope expansion. Recorded in §0.2 follow-ups.

**Implementation iteration cap status**: R0 + Codex r1 = round 1 of 3. R2 will be the convergence test — expect CLEAN PROCEED (all 3 folds verified by re-read).

### Local re-verification after R0 + Codex r1 fold

- 24/24 PR #61 cosign tests still PASS (run after each fold)
- 90/90 sibling supply-chain tests still PASS (no regression)
- YAML parse OK on ci.yml + signed-images-gha-services.yml
- Cross-phase SHA equality test now per-job-anchored (verified by manually inspecting that all 3 cosign jobs' regex matches return exactly 1 pin each)
- Cross-phase issuer-set parity test now URL-filtered (verified extracted sets are unchanged on current sibling modules — all entries are https:// URLs)

### §0.3 Codex r2 fold (2026-05-17) — applied in same commit

Codex r2 returned FOLD_AND_PROCEED with 2 LOW findings on the r1-folded diff:

| Severity | Source | Finding | Action |
|---|---|---|---|
| LOW | Codex r2 | r1's URL-filter fold (`s.startswith("https://")`) was incomplete: still accepts `# See "https://example.com"` double-quoted comment URLs inside the frozenset block (the very class r1 was meant to defeat). The regex+filter approach cannot distinguish a string literal from a string in a comment | **FOLDED**: replaced the regex extractor entirely with `ast.parse(source)` + walk top-level `Assign` nodes for `_KNOWN_OIDC_ISSUERS`; reads string-constant elements directly from `ast.Set`/`List`/`Tuple` elts. AST parsing strips comments and docstrings during tree-building, so comment-URL false-positives are structurally impossible. Removed `_KNOWN_OIDC_ISSUERS_BLOCK_RE` + `_STRING_LITERAL_RE` (no longer needed). Added `import ast`. |
| LOW | Codex r2 | Stale wording in allowlist file comment + plan §5 risk row: claimed "single-issuer per allowlist today; allowlist size = 1" but the actual constant holds 5 issuers (`token.actions.githubusercontent.com`, `oauth2.sigstore.dev/auth`, `accounts.google.com`, `gitlab.com`, `agent.buildkite.com`) | **FOLDED**: allowlist comment + plan §5 risk row rewritten to "5 known Sigstore issuers today; identical across all 3 phase test modules" with cross-references to the canonical declarations |

**Convergence note**: Codex r1's URL-filter recommendation + Codex r2's "filter incomplete" finding form a 2-round refinement of the same invariant — the original regex extractor's defense was insufficient and the eventual fix needed structural AST parsing, not string-prefix filtering. Recorded as a 1× validation that regex-based static-source invariant checks are fragile compared to AST walks; consider AST-first design for any future cross-phase static-source parity assertion (Phase 4 + post-Phase-4 reconcile-all).

**Class-of-issue sweep (Codex r2)**: confirmed no other regex-based static-source extraction exists in this test module. The other static-source assertions (SHA equality, job-body isolation, forbidden flags) read text patterns by position not by literal-string equality, so the comment-confusion class doesn't apply.

**Test count after r2 fold**: 24 tests still (no test additions; the extractor function is internal helper, not a test). All 24 PASS.

**Implementation iteration cap status**: Codex r2 = round 2 of 3. R3 reserved as final convergence test if needed; expect CLEAN PROCEED.

### §0.4 Codex r3 fold (2026-05-17) — final, wording-only

Codex r3 returned FOLD_AND_PROCEED with 2 LOW findings — BOTH wording-only / documentation hygiene (no code defect):

| Severity | Source | Finding | Action |
|---|---|---|---|
| LOW | Codex r3 | Plan §4.5b.2 prose still said the parity test extracts via "multiline regex" after r2 fold replaced the regex with AST | **FOLDED (wording-only)**: §4.5b.2 + D5 rewritten to describe `Path.read_text()` + `ast.parse` flow, walking top-level `Assign` for `_KNOWN_OIDC_ISSUERS = frozenset({...})`, reading string-constant elements |
| LOW | Codex r3 | Test-file prose (module docstring line 46, helper docstring line ~568, assertion error message line ~586) still said "via regex" / "static-source regex" / "regex-based extractor" | **FOLDED (wording-only)**: module docstring + test docstring + assertion message rewritten to AST-based language; the "regex-based extractor" reference at line 497 remains intentionally (it's inside the helper docstring documenting WHY AST defeats every false-positive class a regex extractor WOULD surface — historically correct comparison) |

**Convergence at r3 cap**: Per `pattern_codex_3round_implementation_iteration` (r3 stop), iteration is at cap. r3 findings were wording-only documentation lag — no code defect remained. Plan-doc + test-file prose now match the r2 AST refactor.

**Pattern validation count update (post-PR-#61-merge)**: `pattern_codex_3round_implementation_iteration` previously 2× validated (PR #56 + #57 both CLEAN at r2); PR #61 ran 3 rounds with r3 wording-only fold = 1× r3-cap-stop validation (legitimately at cap, no force-stop blocker).

**Local re-verification after r3 wording fold**:
- 24/24 PR #61 cosign tests still PASS
- 70/70 across all 3 phase modules PASS
- No code changes in r3 fold — only docstring + plan prose

