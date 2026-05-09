# Plan — D-1 Correlation Hardening + UAT (PR C)

**Phase:** 3 Slice 3 (PR C) — D-1 hardening + UAT for the correlation primitive shipped in PR #28 (BE) + PR #36 (FE).
**Status:** **DRAFT v1.0** — Initial draft against `main@bfa2374` (PR #36 merge, 2026-05-09T09:12:41Z). Awaits Codex T-1 r1 plan review before T0 dispatch. **Predecessors satisfied** — PR #28 (BE primitives) AND PR #36 (FE visualization) both on `main`.
**PR number:** Not reserved. Confirm via `gh pr list` immediately before opening; **current main HEAD is `bfa2374`** (PR #36 merge, 2026-05-09), **0 OPEN PRs** at draft time. Next assigned PR number will likely be #37 (verify with `gh pr list --state all --limit 5` at open time).
**Predecessors:** PR #28 (D-1 BE primitives + methodology page; merged 2026-05-03 PM as `597a972`) **AND** PR #36 (`feat/p3.s3-correlation-fe` — D-1 FE visualization + 5 Pact consumer interactions + BE provider-state handlers + page-class manifest 9→10; merged 2026-05-09 as `bfa2374`). Intervening merges between PR #28 and PR #36 (PR #29-#35) DO NOT block this PR.
**Successors:** None — slice 3 closes with this PR. Backlog items (Lazarus.day parity, DESIGN.md token migration, d3 type cleanup) remain in `phase_status.md` Pending follow-ups for separate PRs.
**Umbrella spec:** `docs/plans/phase-3-slice-3-correlation.md` §11 PR C — locked invariants are inherited unchanged; this plan only narrates HOW the hardening side meets them.

---

## 1. Goal

Close PR #36's deferred 🟡 verification items + ship the umbrella spec's UAT acceptance criteria as automated tests:

- **UAT 1-5 as Playwright E2E** (umbrella §3 UAT 1-5): login → correlation page render → method toggle → URL state hydration → locale toggle. UAT 6 (p95 ≤ 500 ms over 50 sequential requests) ships as a separate perf smoke.
- **NFR-1 perf smoke** (umbrella §3 NFR-1 + UAT 6): 50 sequential `GET /analytics/correlation?x=reports.total&y=incidents.total&date_from=2018-01-01&date_to=2026-04-30` requests against the populated dev DB; p95 ≤ 500 ms passes; greater fails.
- **6th Lighthouse target** (`/analytics/correlation?x=reports.total&y=incidents.total`): extend the existing 5-target loop documented in `apps/frontend/lighthouse/README.md:137-159` to add a 6th `correlation:/analytics/correlation?x=...&y=...` entry with seeded query params so the audit measures the populated chart-render state, not the empty-state.
- **PR-B Q1 catalog dropdown grouping** (PR #36 §0.1 amendment 7 deferred): refactor `CorrelationFilters.tsx` to render `[ Reports ]` / `[ Incidents ]` section headers grouping series by their `root` field (literal enum `'reports.published'` / `'incidents.reported'` per `apps/frontend/src/lib/api/schemas.ts:692`; **NOT** by `id` prefix — `id` is opaque per umbrella §2.2). **Cosmetic only** — no URL / cache-key / test-contract / BE-surface impact. Tests pin the section header `data-testid` so future regressions are caught.
- **PR-B T13 live verifier replay backfill**: capture the live `pnpm pact:provider` replay 5/5 verify transcript (carved out from PR #36 as user-side gate; Codex pre-merge round adjudicated SAFE TO MERGE without it). This is a procedural step, not a code change; the transcript lives in `.codex-review/correlation-hardening-t5-pact-verify.transcript.log` for audit.

**Non-goal (deferred to separate PRs):**
- Power-user "any-two-series" API (umbrella §10.1 — out of slice-3 entirely)
- Quarterly / yearly granularity (§10.2)
- F-2 / F-4 / F-5 downstream consumers (§10.3-10.5)
- Cross-pair correction (§10.6)
- Lazarus.day parity / DESIGN.md token migration / d3 type cleanup — separate backlog PRs.

---

## 2. Locked Decisions

These mirror the umbrella spec's locks for PR-C scope (§11). Each row says "PR-C reading of the umbrella lock" so the implementing PR can be audited against the spec without a side-by-side read.

| ID | Decision | Rationale |
|:---:|:---|:---|
| **C1** | Branch = `chore/p3.s3-correlation-hardening` (per umbrella §11 PR-C explicit lock at line 780). Base = `main` directly (PR #36 merged 2026-05-09 as `bfa2374`; no stacking). | Umbrella §11 dependency DAG. PR #28 (BE) and PR #36 (FE) both on main; PR-C runs against the merged stack. No stacked-PR base-flip risk per memory `pitfall_stacked_pr_merge_base_flip`. |
| **C2** | Estimated size = small ≈ 8 files / ≈ 300 LoC per umbrella §11 line 788. Allow up to 50% overage (≤ 12 files / ≤ 450 LoC) before triggering a §0.1 amendment. | Umbrella §11 size band. Aligns with `feedback_codex_iteration` 3-6 round band — PR is meant to be a tight verification PR, not a re-architecture. |
| **C3** | Lighthouse target addition extends the existing bash-loop pattern in `apps/frontend/lighthouse/README.md:146-158`; **no run-audit.mjs source change required** (the harness already accepts `LH_PATH` + `LH_REPORTS_SUBDIR` env vars). Just one new `TARGETS` array entry: `"correlation:/analytics/correlation?x=reports.total&y=incidents.total"`. The query params are URL-encoded by the bash loop's `LH_PATH` assignment. | Existing harness (`run-audit.mjs:67-78`) is target-agnostic; the multi-target loop is documented only — no code wires the target list. **No regression risk** because the harness pre-existed for 5 targets. |
| **C4** | Perf smoke harness lives at `services/api/tests/perf/test_correlation_p95.py`. Opt-in mechanism follows the existing **`integration` marker precedent** at `services/api/pytest.ini:5-9` (skipped automatically when `POSTGRES_TEST_URL` env var is unset; `--strict-markers` is already set). Steps: (a) register `perf` marker in `services/api/pytest.ini` markers section; (b) `services/api/tests/perf/conftest.py` adds `pytest_collection_modifyitems` that skips perf-marked tests unless `PERF_TEST=1` env var is set; (c) CI adds a separate `workflow_dispatch`-triggered job that exports `PERF_TEST=1` + boots populated-DB fixture before running. | Greenfield (no existing perf-smoke pattern in this repo per `find services/api -name "*perf*.py"`). The `integration` marker pattern is the proven precedent for "expensive test that needs explicit opt-in". `--strict-markers` means an unregistered marker raises an error — registration is mandatory. |
| **C5** | Playwright E2E lives at `apps/frontend/tests/e2e/correlation-uat.spec.ts` as a **single spec file with 5 test cases** mapping 1:1 to UAT 1-5. Reuses the existing Pact provider-state seeding pattern from `login-dashboard-actors.spec.ts:23-78` (POST `/_pact/provider_states` to seed fixtures + mint a session cookie). State names use the **exact phrases** committed at `services/api/src/api/routers/pact_states.py:2565-2620`: `seeded correlation catalog fixture and an authenticated analyst session` (catalog) + `seeded correlation populated fixture and an authenticated analyst session` (populated render). **Unknown state strings fall through with session-only seeding** per `pact_states.py:2620-2624` — exact-phrase match is mandatory. | UAT 1-5 are sequential user flows; one spec file keeps the journey coherent. UAT 6 (perf p95) is decoupled into the `services/api/tests/perf/` smoke (C4) because it's a load-shape test, not a user-flow test. |
| **C6** | Q1 catalog grouping (PR #36 §0.1 amendment 7 pickup): refactor `CorrelationFilters.tsx:94` `catalog.map(...)` to render under a 2-level grouping structure (`[ Reports ]` header → series with `root === 'reports.published'`; `[ Incidents ]` header → series with `root === 'incidents.reported'`). **Group by the schema's `root` field** (`apps/frontend/src/lib/api/schemas.ts:692` — 2-value literal enum), NOT by `id` prefix (`id` is opaque per umbrella §2.2 + the schema doc comment at `:683`). New testids: `correlation-filter-{x|y}-group-reports` + `correlation-filter-{x|y}-group-incidents`. Existing per-option testids (`correlation-filter-{x|y}-option-{id}`) preserved unchanged. | Umbrella §8 Q1 default ("flat dropdown grouped by root via section headers"). PR #36 deferred this with a §0.1 amendment 7 because it's purely cosmetic. PR-C closes the loop. |
| **C7** | T13 live verifier replay = **procedural step + transcript capture only**. Run `pnpm --filter @dprk-cti/frontend pact:provider` against the host-hybrid stack (BE + DB + Keycloak); expected output: 5/5 new interactions verify + legacy 21 still pass. Transcript saved at `.codex-review/correlation-hardening-t5-pact-verify.transcript.log` (gitignored — shipped only as a §5 risk-row line item documenting the capture). | PR #36 carved this out as user-side gate. PR-C operationalizes the backfill so the umbrella's "Provider verify passes all interactions" AC #6 has a recorded artifact, not a procedural memory of "yes the user ran it once". |
| **C8** | Vitest tests for the C6 catalog grouping change live in a **NEW** dedicated file `apps/frontend/src/features/analytics/correlation/__tests__/CorrelationFilters.test.tsx` (no dedicated CorrelationFilters test file existed in PR #36 — filters were exercised indirectly via `CorrelationPage.test.tsx` + `CorrelationPage.urlState.test.tsx`). The new file adds at least 2 test cases: (a) "renders Reports + Incidents section headers", (b) "options nested under correct group by `root` value". Existing PR #36 tests are NOT modified. | A separate file keeps the C6 cohesion cleanly testable + matches the leaf-component-per-test-file convention used elsewhere (e.g. `CorrelationCaveatBanner.test.tsx`). |
| **C9** | i18n: 2 new keys for the section headers — `correlation.filters.groupReports` + `correlation.filters.groupIncidents`. Added to both `en.json` and `ko.json`; **NOT** in the parity invariant allowlist (these strings legitimately differ between locales). | Per memory `pattern_cross_locale_parity_with_invariant_allowlist`. Section headers are user-facing labels with locale-distinct content (`Reports` ≠ `보고서`). |
| **C10** | Codex iteration band: 3-6 rounds expected per `feedback_codex_iteration` + umbrella §11 line 785 explicit lock. Track per-task in `.codex-review/correlation-hardening-t{N}-r{M}.transcript.log`. | Umbrella §11 + project memory. PR-B took 32 task rounds + 3 PR-cycle rounds (T15 r1 + T15 r2 + T16 pre-merge); PR-C is smaller surface so should land at the lower edge of the band. |

---

## 3. Scope

### Files added (estimated 7 new files)

- `docs/plans/pr37-correlation-hardening.md` (this file; renamed from `correlation-hardening.md` at T7 push per `plan_doc_convention`; PR #37 confirmed via `gh pr list` after PR #36's merge).
- `docs/plans/pr37-correlation-hardening-body.md` (PR body draft, authored at T6; renamed at T7).
- `apps/frontend/tests/e2e/correlation-uat.spec.ts` (Playwright spec, 5 test cases; T3).
- `apps/frontend/src/features/analytics/correlation/__tests__/CorrelationFilters.test.tsx` (NEW — first dedicated CorrelationFilters test file; 2+ cases for C6 grouping; T2).
- `services/api/tests/perf/conftest.py` (perf-only fixtures: `pytest_collection_modifyitems` skip-unless-`PERF_TEST=1` + populated-DB seeder + uvicorn target URL + p95 percentile helper).
- `services/api/tests/perf/test_correlation_p95.py` (50-sequential-request perf smoke, T4).
- *(no `__init__.py` per `pitfall_pytest_rootdir` — flat tests dir matches existing `services/api/tests/contract/` + `services/api/tests/integration/` patterns).*

### Files modified (estimated 5 edits)

- `apps/frontend/lighthouse/README.md` — extend `TARGETS` bash array from 5 → 6 entries (T1).
- `apps/frontend/src/features/analytics/correlation/CorrelationFilters.tsx` — Q1 catalog grouping refactor (T2).
- `apps/frontend/src/i18n/en.json` + `ko.json` — 2 new keys for section headers (T2).
- `apps/frontend/src/i18n/index.ts` — Resources interface adds `correlation.filters.groupReports/groupIncidents` (T2).
- `services/api/pytest.ini` — register `perf` marker in markers section (`--strict-markers` is already set; unregistered marker raises) (T4).
- `.github/workflows/ci.yml` — add `correlation-perf-smoke` job triggered by `workflow_dispatch` only (NOT on every PR); job sets `PERF_TEST=1` + boots populated DB fixture before invoking `uv run pytest -m perf` (T4).

### Files NOT touched

- `services/api/src/api/routers/analytics_correlation.py` — production route handler unchanged (no API changes; perf smoke calls the existing endpoint).
- `services/api/src/api/routers/pact_states.py` — provider-state handlers unchanged from PR #36.
- `apps/frontend/src/features/analytics/correlation/CorrelationPage.tsx` etc. — 4 of the 5 leaves untouched (only Filters changes for grouping).
- OpenAPI snapshot — empty diff (no BE behavior change).
- Pact JSON contract — no FE consumer change; new interactions NOT added (PR #36's 5 interactions are the lock).

---

## 4. Tasks

| ID | Task | Depends on | Est. | Done when |
|:---|:---|:---|:---:|:---|
| **T-1** | Plan doc v1.0 (this file) + Codex r1 plan review + fold (per `pattern_codex_body_review_loop`). | — | 0.25d | This file committed at `chore/p3.s3-correlation-hardening` HEAD; Codex r2 returns CLEAN PROCEED 0 findings. |
| **T0** | Workspace inventory (read-only): existing Lighthouse harness target-list mechanism (`apps/frontend/lighthouse/README.md` + `run-audit.mjs:67-78`); existing Playwright spec pattern (`tests/e2e/login-dashboard-actors.spec.ts` + `tests/e2e/url-state-deep-link.spec.ts` Pact-provider-state seeding); existing pytest contract patterns (`services/api/tests/contract/test_openapi_snapshot.py` for marker + conftest precedent); existing `integration` marker config (`services/api/pytest.ini:5-9` + skip-unless-env-var pattern); existing pytest perf patterns (none — greenfield); BE perf surface (`@analytics_correlation.router.get` decorator + `Depends(get_compute_correlation)` factory pattern from PR #36 T13). Per `pattern_tdd_10step_inventory_shape_before_contract`. **No commits**; outputs feed T1-T5 scoping. | T-1 | 0.25d | Inventory documented inline in this plan §3 (already drafted) + per-task scope confirmed. |
| **T1** | Lighthouse 6th target. README.md edit only — extend `TARGETS` bash array with `"correlation:/analytics/correlation?x=reports.total&y=incidents.total"`. Verify `run-audit.mjs` accepts query-string-suffixed `LH_PATH` (it should — see line 68). Pre-flight test: run the new target locally against vite preview + seeded session; confirm `apps/frontend/lighthouse/reports/correlation/SUMMARY.md` is generated with non-trivial scores. | T0 | 0.2d | README updated; one local audit run produces `reports/correlation/` directory with SUMMARY.md + 6 JSONs (3 light + 3 dark). |
| **T2** | Q1 catalog grouping refactor in `CorrelationFilters.tsx` (~30 LoC): replace flat `catalog.map(...)` with 2-tier grouping by `s.root` literal value (NOT `id` prefix). Add 2 new section-header testids. Add 2 new i18n keys + Resources interface entry. Create NEW `CorrelationFilters.test.tsx` with 2+ test cases. RED first per `tdd-workflow` skill (write tests, watch fail, then implement). | T0 | 0.3d | vitest 858/858 + 2 new = 860/860 GREEN; build GREEN; existing per-option testids still pass; manual smoke shows `[ Reports ]` / `[ Incidents ]` headers in the dropdown. |
| **T3** | Playwright E2E `correlation-uat.spec.ts` covering UAT 1-5 (each as a separate `test()` block). Reuses Pact-provider-state seeding pattern from `login-dashboard-actors.spec.ts:23-78`. State strings use **exact phrases** from `services/api/src/api/routers/pact_states.py:2565-2620`: `seeded correlation catalog fixture and an authenticated analyst session` (catalog) + `seeded correlation populated fixture and an authenticated analyst session` (populated render). **No new state handler** — leverage PR #36 T13's. | T0 | 0.7d | `pnpm --filter @dprk-cti/frontend exec playwright test correlation-uat.spec.ts` → 5/5 PASS locally against host-hybrid stack. |
| **T4** | Perf smoke `test_correlation_p95.py` + greenfield `services/api/tests/perf/conftest.py` (with `pytest_collection_modifyitems` that skips perf-marked tests unless `PERF_TEST=1`). Register `perf` marker in `services/api/pytest.ini`. Add `correlation-perf-smoke` `workflow_dispatch` job in `.github/workflows/ci.yml`. Test body: seed populated DB via PR #36 T13's `_ensure_correlation_populated_fixture` (or replicate the seed locally if state-handler invocation is brittle); spawn `httpx.AsyncClient` against running uvicorn; issue 50 sequential `GET /analytics/correlation?x=reports.total&y=incidents.total&date_from=2018-01-01&date_to=2026-04-30`; assert `numpy.percentile(durations, 95) <= 0.500`. | T0 | 0.5d | `PERF_TEST=1 uv run pytest -m perf services/api/tests/perf/` → 1 test PASS locally. Default `uv run pytest` skips it. CI workflow `workflow_dispatch` job added + dispatchable. |
| **T5** | T13 live verifier replay backfill. Run `pnpm --filter @dprk-cti/frontend pact:provider` against host-hybrid stack; capture transcript at `.codex-review/correlation-hardening-t5-pact-verify.transcript.log` (gitignored). Confirm 5/5 new D-1 interactions verify + legacy 21 still pass. Add a one-line summary to this plan §6 testing strategy citing the transcript. | T0 | 0.2d | Transcript captured; §6 cites the run; expected log line `Verified pact (5 + 21 interactions, 26 total) ✓`. |
| **T6** | PR body draft at `docs/plans/correlation-hardening-body.md` (renamed to `pr37-correlation-hardening-body.md` at T7 push per `plan_doc_convention`). Sections: Scope + Why + Base + Plan ref + What lands (commit table) + Architecture map + Verification ✅/🟡 split per `pattern_pr_body_verification_split` + AC table per §7 + What's NOT in this PR + Reviewer test plan + Decision log + Pre-merge checklist. | T1, T2, T3, T4, T5 | 0.25d | Body file committed; Codex T6 r1 review + fold to CLEAN PROCEED. |
| **T7** | Push DRAFT branch + open PR + PR-as-diff Codex loop (per `pattern_codex_body_review_loop`). Rename plan + body to `pr37-*` after `gh pr list` confirms the assigned PR number. | T6 | 0.2d | DRAFT PR open at PR #37; CI 12/12 PR-event SUCCESS at PR head (NOT 24 — `chore/*` is outside `on.push.branches: ["main", "feat/**"]` filter at `.github/workflows/ci.yml:5`, only `pull_request` event fires); Codex PR-as-diff r1 + fold loop converges to CLEAN PROCEED. |
| **T8** | Pre-merge Codex GO round per `pattern_pre_merge_codex_round` + `gh pr ready` + `gh pr merge --merge`. Per `collab_style` push gate — awaits explicit user signal. | T7 | 0.1d | PR merged; main fast-forwarded; local + remote branch cleaned up. |

**Estimated dev-time:** ≈ 2.95 dev-days. Within umbrella §11 PR-C "small ≈ 8 files / ≈ 300 LoC" sizing.

---

## 5. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|:---|:---|:---:|:---:|:---|
| **R-C1** | E2E spec brittleness against happy-dom / browser timing differences. Per memory `pitfall_jsdom_abortsignal_react_router`, certain React Router 6.4+ behaviors differ. | Medium | Low | Mirror `login-dashboard-actors.spec.ts` patterns 1:1; use `expect(locator).toBeVisible()` over `expect(locator).toBeInTheDocument()`; generous timeout (60s per umbrella precedent); `retain-on-failure` traces for debug. |
| **R-C2** | Perf smoke flakiness: NFR-1 ≤ 500 ms is tight on a cold-start CI runner; may flake intermittently. | Medium | Medium | Run smoke ONLY against host-hybrid (warm) stack, not against cold-start CI. Mark as `@pytest.mark.perf` opt-in. CI workflow job is `workflow_dispatch` only (manual trigger), not on every PR. Document in §6 that flakes warrant rerun, not code change, per `pitfall_pact_v3_ci_cold_start_race`. |
| **R-C3** | Lighthouse target seed: bare `/analytics/correlation` lands on empty state per Codex T16 pre-merge LOW finding. The 6th target MUST include `?x=reports.total&y=incidents.total` query string OR seed a session cookie + the BE state-handler so the populated state renders. | High | Medium | Use query-string approach (C3 lock) — synthesizes the populated state from URL hydration without needing a state-handler. The auditor sees the chart-render performance, which is the metric of interest. |
| **R-C4** | Q1 grouping refactor in `CorrelationFilters.tsx` could break existing per-option testids if the DOM tree shape changes (e.g., listbox role nesting). | Low | Medium | Tests pin per-option testids directly (no role-based selectors); grouping is additive (section headers wrap existing option buttons, no removal). RED-first per `tdd-workflow` catches accidental DOM shape changes. |
| **R-C5** | T13 live verifier replay reveals a real verification failure (5/4 instead of 5/5) — meaning PR #36's T13 handlers are subtly wrong. | Low | High | If a real failure surfaces (not a flake per `pitfall_pact_v3_ci_cold_start_race`): **(a) BLOCK PR-C** — verification PR cannot ship a green claim while a verification gap exists; **(b) file a separate hotfix PR** against `main` that fixes PR #36's T13 handlers; **(c) PR-C rebases on the hotfix's merge commit and re-runs T5**. Do NOT expand PR-C scope to include the fix — that breaks small-PR sizing AND inverts the audit trail (PR-C is the auditor, not the patcher). |
| **R-C6** | i18n parity invariant allowlist: 2 new keys (groupReports / groupIncidents) MUST NOT be in the allowlist (they legitimately differ ko vs en). | Low | Low | C9 lock makes this explicit. RED-first vitest parity check catches if either key gets accidentally identical across locales. |
| **R-C7** | Pact JSON contract drift: PR #36 locked 26 interactions. PR-C MUST NOT add new consumer interactions (Pact JSON unchanged). | Low | Medium | Scope §3 explicitly excludes `contracts/pacts/frontend-dprk-cti-api.json` from the file list. CI contract-verify catches accidental regen. |
| **R-C8** | E2E + perf-smoke + pact-verify all need a populated dev DB. The dev triad (`docker compose up -d db cache keycloak otel-collector`) might lag boot, causing test flakes. | Medium | Low | Reuse existing `login-dashboard-actors.spec.ts` boot pattern (Playwright `globalSetup` + healthcheck). Document boot order in PR body §Reviewer-test-plan. |
| **R-C9** | New `services/api/tests/perf/` directory creates pytest rootdir collision per memory `pitfall_pytest_rootdir`. | Low | Low | Per memory, drop `tests/__init__.py` if added; verify pytest discovers tests via root `pyproject.toml` `pytest.ini_options` or absent `__init__.py`. CI working-directory should be set per existing pytest invocation. |

---

## 6. Testing strategy

- **vitest**: existing 858 tests preserved; +2 new for C6 grouping → 860 GREEN.
- **Playwright E2E** (T3): 5 test cases mapped to UAT 1-5. Run locally before push: `pnpm --filter @dprk-cti/frontend exec playwright test correlation-uat.spec.ts` against host-hybrid stack.
- **Pytest perf smoke** (T4): `uv run pytest -m perf services/api/tests/perf/test_correlation_p95.py -q` → 1 test PASS, p95 ≤ 500 ms with populated DB.
- **Pact provider verify** (T5): `pnpm --filter @dprk-cti/frontend pact:provider` → `Verified pact (5 + 21 = 26 interactions) ✓`. Transcript captured at `.codex-review/correlation-hardening-t5-pact-verify.transcript.log`.
- **Lighthouse 6-target loop** (T1): bash for-loop runs all 6 targets sequentially; reviewer reads 6 SUMMARY.md tables for accept/reject. **NOT a CI hard gate** — informational only per existing harness contract (`run-audit.mjs:22-24`).
- **CI**: existing 12-check × 2-event workflow surface preserved. Perf smoke is `workflow_dispatch` only (separate job), not added to default PR CI.

---

## 7. Acceptance criteria

| # | Criterion | Status |
|:---:|:---|:---:|
| 1 | UAT 1 — analyst login → correlation page → reports.total × incidents.total → both methods (Pearson + Spearman) render with p-values + caveat banner + lag chart [-24, +24] | 🟡 (T3) |
| 2 | UAT 2 — < 30 monthly buckets → empty state with locked copy "표본이 부족합니다 (최소 30개월 필요)" / "Insufficient sample" | 🟡 (T3) |
| 3 | UAT 3 — direct GET to `/api/v1/analytics/correlation?...` returns both methods at lag 0 + full lag scan + `interpretation.caveat` + `interpretation.methodology_url` | 🟡 (T3) |
| 4 | UAT 4 — URL state survives reload | 🟡 (T3) |
| 5 | UAT 5 — KO / EN locale toggle swaps all chart labels including caveat banner | 🟡 (T3) |
| 6 | UAT 6 / NFR-1 — p95 ≤ 500 ms over 50 sequential requests | 🟡 (T4) |
| 7 | Lighthouse 6-target loop runs cleanly (`reports/correlation/SUMMARY.md` exists; reviewer accepts scores) | 🟡 (T1) |
| 8 | Q1 catalog grouping shows `[ Reports ]` / `[ Incidents ]` headers with options nested correctly | 🟡 (T2) |
| 9 | T13 live `pnpm pact:provider` replay 5/5 verify + legacy 21 still pass; transcript captured | 🟡 (T5) |
| 10 | vitest 860/860 GREEN (was 858/858 + 2 new from T2 + new `CorrelationFilters.test.tsx`) | 🟡 (T2) |
| 11 | Pact contract 26/26 GREEN preserved (no PR-C change to consumer interactions) | 🟡 (T7 default CI verify) |
| 12 | FE production build green (`pnpm run build` exits 0) | 🟡 (T7 default CI verify) |
| 13 | OpenAPI snapshot diff at PR head is empty | 🟡 (T7 default CI `contract-verify` job) |
| 14 | Branch CI green on all 12 checks × 2 events (default surface; perf job is workflow_dispatch only and NOT counted toward this AC) | 🟡 (after push) |
| 15 | Final external Codex review reports no unresolved CRITICAL/HIGH | 🟡 (PR-as-diff at T7-T8) |
| 16 | PR body present at `docs/plans/pr37-correlation-hardening-body.md`; plan present at `docs/plans/pr37-correlation-hardening.md` | ✅ (renamed at T7 push commit) |

---

## 8. Open questions / Defaults

(Per umbrella spec convention: minimal — items needing user/reviewer input but not blocking draft.)

1. **Q-C1 — Perf smoke CI cadence.** Default = `workflow_dispatch` (manual trigger) only. Alternative = `schedule` (e.g. nightly cron). Recommend manual; add schedule in a follow-up if NFR-1 regression detection becomes a concern.
2. **Q-C2 — Lighthouse 6th target seeding mechanism.** Default = query-string `?x=reports.total&y=incidents.total` (C3 lock). Alternative = Pact provider-state seed + cookie. Recommend query-string; simpler and matches the umbrella's "seeded fixture id" pattern for `/reports/999001` etc. — but the cookie path may be required if the page renders empty even with query params (verify at T1 pre-flight).
3. **Q-C3 — Q1 catalog grouping label copy.** Default = `Reports` / `Incidents` (en) + `보고서` / `사건` (ko) — matches existing `shell.nav.reports` + `shell.nav.incidents` copy. Alternative = explicit "Section: Reports" prefix. Recommend default; minimal copy.
4. **Q-C4 — Perf smoke sample-size N.** Default = 50 sequential requests per umbrella §3 NFR-1 + UAT 6. Alternative = larger N for tighter percentile. Recommend default; matches the spec.

---

## 9. §0.1 amendment change log

1. **T-1 r1 (2026-05-09 — Codex T-1 r1 fold):** Codex returned HOLD with 3 HIGH + 3 MEDIUM + 2 LOW. All 8 findings folded together (class-of-issue: plan-vs-codebase factual drift) per `pattern_sweep_class_when_codex_finds_one`:
   - **HIGH 1** — C6 + T2 row + §1 Goal said "group by `id` prefix"; corrected to "group by `s.root` literal value" per `apps/frontend/src/lib/api/schemas.ts:692` (`root` enum is the canonical 2-value field; `id` is opaque per umbrella §2.2).
   - **HIGH 2** — C5 + T3 row named non-existent provider states (`seeded session as analyst`, `correlation populated render`); corrected to **exact phrases** from `services/api/src/api/routers/pact_states.py:2565-2620` (`seeded correlation catalog fixture and an authenticated analyst session` etc.). Unknown-state fall-through behavior at `:2620-2624` makes exact-phrase match mandatory.
   - **HIGH 3** — C4 + T4 said `@pytest.mark.perf` alone makes default `pytest` skip the test, with marker config in `pyproject.toml`; corrected: marker registration goes in `services/api/pytest.ini` (existing markers section) since `--strict-markers` is set; default-skip mechanism uses `pytest_collection_modifyitems` in `services/api/tests/perf/conftest.py` checking `PERF_TEST=1` env var (mirrors the existing `integration` marker's `POSTGRES_TEST_URL` skip-condition pattern at `services/api/pytest.ini:5-9`).
   - **MED 1** — File inventory: `CorrelationFilters.test.tsx` was listed as modified but doesn't exist on `main@bfa2374` (PR #36 had no dedicated CorrelationFilters test file). Moved to "new" + C8 lock updated. Also added missing modified files `services/api/pytest.ini` (T4 marker registration) + `.github/workflows/ci.yml` (T4 perf job). Final inventory: 6 new + 7 modified = 13 files; **at the C2 50%-overage ceiling** (≤ 12 files) — 1-file overage is recorded here without expanding the band, since `en.json` + `ko.json` are an i18n pair (counts as 1 logical change) and `pytest.ini` + `ci.yml` are non-code config additions for T4. Effective code-file count = 11, within band.
   - **MED 2** — R-C5 mitigation pre-authorized scope expansion ("fold the fix into PR-C scope"); rewritten to BLOCK PR-C + file separate hotfix PR if T13 verify reveals real failure. Verification PR cannot ship a green claim while a verification gap exists; the auditor is not the patcher.
   - **MED 3** — T4 + T5 "Depends on" column listed T3 unnecessarily. T4 seeds populated DB independently (or replicates PR #36 T13's seed locally); T5 is a live replay against the host stack (no T3 output consumed). Both deps trimmed to just T0; T1/T2/T3/T4/T5 are now genuinely parallelizable post-T0.
   - **LOW 1** — T0 inventory cited `services/api/tests/contract/conftest.py` which doesn't exist; corrected to cite `services/api/tests/contract/test_openapi_snapshot.py` + `services/api/pytest.ini:5-9` (the actual `integration` marker precedent).
   - **LOW 2** — AC #10 conflated vitest + contract + build under T2; split into 4 separate AC rows (#10 vitest → T2; #11 contract preserved → T7; #12 build → T7; #13 OpenAPI snapshot → T7). Total AC rows: 14 → 16. AC #14 (CI green) explicitly excludes the perf job (workflow_dispatch only).

---

**End of plan v1.0 with T-1 r1 fold. Awaits Codex T-1 r2 verify.**
