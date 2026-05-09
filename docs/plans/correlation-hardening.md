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
- **PR-B Q1 catalog dropdown grouping** (PR #36 §0.1 amendment 7 deferred): refactor `CorrelationFilters.tsx` to render `[ Reports ]` / `[ Incidents ]` section headers grouping series by their `root` prefix per umbrella §8 Q1 default. **Cosmetic only** — no URL / cache-key / test-contract / BE-surface impact. Tests pin the section header `data-testid` so future regressions are caught.
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
| **C4** | Perf smoke harness lives at `services/api/tests/perf/test_correlation_p95.py` as a pytest **opt-in marker** (`@pytest.mark.perf`) so default `uv run pytest` skips it; CI runs it as a separate workflow job that boots a populated DB fixture. | Greenfield (no existing perf-smoke pattern in this repo per `find services/api -name "*perf*.py"`). Opt-in marker matches the existing `@pytest.mark.contract` pattern in `services/api/tests/contract/`. Avoids slowing every PR's default test run. |
| **C5** | Playwright E2E lives at `apps/frontend/tests/e2e/correlation-uat.spec.ts` as a **single spec file with 5 test cases** mapping 1:1 to UAT 1-5. Reuses the existing Pact provider-state seeding pattern from `login-dashboard-actors.spec.ts:23-78` (POST `/_pact/provider_states` to seed fixtures + mint a session cookie). | UAT 1-5 are sequential user flows; one spec file keeps the journey coherent. UAT 6 (perf p95) is decoupled into the `services/api/tests/perf/` smoke (C4) because it's a load-shape test, not a user-flow test. |
| **C6** | Q1 catalog grouping (PR #36 §0.1 amendment 7 pickup): refactor `CorrelationFilters.tsx:94` `catalog.map(...)` to render under a 2-level grouping structure (`[ Reports ]` header → series whose id starts with `reports.`; `[ Incidents ]` header → series whose id starts with `incidents.`). New testids: `correlation-filter-{x|y}-group-reports` + `correlation-filter-{x|y}-group-incidents`. Existing per-option testids (`correlation-filter-{x|y}-option-{id}`) preserved unchanged. | Umbrella §8 Q1 default ("flat dropdown grouped by root via section headers"). PR #36 deferred this with a §0.1 amendment 7 because it's purely cosmetic. PR-C closes the loop. |
| **C7** | T13 live verifier replay = **procedural step + transcript capture only**. Run `pnpm --filter @dprk-cti/frontend pact:provider` against the host-hybrid stack (BE + DB + Keycloak); expected output: 5/5 new interactions verify + legacy 21 still pass. Transcript saved at `.codex-review/correlation-hardening-t5-pact-verify.transcript.log` (gitignored — shipped only as a §5 risk-row line item documenting the capture). | PR #36 carved this out as user-side gate. PR-C operationalizes the backfill so the umbrella's "Provider verify passes all interactions" AC #6 has a recorded artifact, not a procedural memory of "yes the user ran it once". |
| **C8** | Vitest tests for the C6 catalog grouping change live alongside existing correlation tests (`apps/frontend/src/features/analytics/correlation/__tests__/CorrelationFilters.test.tsx`). Add 2 new test cases: (a) "renders Reports + Incidents section headers", (b) "options nested under correct group by root prefix". No removal of existing tests. | Existing component-test file already pins testids for filter behavior. Additive change matches PR-B's pattern of "tests pin testids only" so the grouping refactor causes zero existing-test churn. |
| **C9** | i18n: 2 new keys for the section headers — `correlation.filters.groupReports` + `correlation.filters.groupIncidents`. Added to both `en.json` and `ko.json`; **NOT** in the parity invariant allowlist (these strings legitimately differ between locales). | Per memory `pattern_cross_locale_parity_with_invariant_allowlist`. Section headers are user-facing labels with locale-distinct content (`Reports` ≠ `보고서`). |
| **C10** | Codex iteration band: 3-6 rounds expected per `feedback_codex_iteration` + umbrella §11 line 785 explicit lock. Track per-task in `.codex-review/correlation-hardening-t{N}-r{M}.transcript.log`. | Umbrella §11 + project memory. PR-B took 32 task rounds + 3 PR-cycle rounds (T15 r1 + T15 r2 + T16 pre-merge); PR-C is smaller surface so should land at the lower edge of the band. |

---

## 3. Scope

### Files added (estimated 6 new files)

- `docs/plans/correlation-hardening.md` (this file; renames to `pr{N}-correlation-hardening.md` at T7 push per `plan_doc_convention`).
- `docs/plans/correlation-hardening-body.md` (PR body draft, authored at T6).
- `apps/frontend/tests/e2e/correlation-uat.spec.ts` (Playwright spec, 5 test cases; T3).
- `services/api/tests/perf/__init__.py` (greenfield perf-test directory marker).
- `services/api/tests/perf/conftest.py` (perf-only fixtures: populated-DB seeder + uvicorn target URL + p95 percentile helper).
- `services/api/tests/perf/test_correlation_p95.py` (50-sequential-request perf smoke, T4).

### Files modified (estimated 4-5 edits)

- `apps/frontend/lighthouse/README.md` — extend `TARGETS` bash array from 5 → 6 entries (T1).
- `apps/frontend/src/features/analytics/correlation/CorrelationFilters.tsx` — Q1 catalog grouping refactor (T2).
- `apps/frontend/src/features/analytics/correlation/__tests__/CorrelationFilters.test.tsx` — 2 new test cases for grouping (T2).
- `apps/frontend/src/i18n/en.json` + `ko.json` — 2 new keys for section headers (T2).
- `apps/frontend/src/i18n/index.ts` — Resources interface adds `correlation.filters.groupReports/groupIncidents` (T2).

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
| **T0** | Workspace inventory (read-only): existing Lighthouse harness target-list mechanism (`apps/frontend/lighthouse/README.md` + `run-audit.mjs:67-78`); existing Playwright spec pattern (`tests/e2e/login-dashboard-actors.spec.ts` Pact-provider-state seeding); existing pytest contract patterns (`services/api/tests/contract/conftest.py`); existing pytest perf patterns (none — greenfield); BE perf surface (`@analytics_correlation.router.get` decorator + `Depends(get_compute_correlation)` factory pattern from PR #36 T13). Per `pattern_tdd_10step_inventory_shape_before_contract`. **No commits**; outputs feed T1-T5 scoping. | T-1 | 0.25d | Inventory documented inline in this plan §3 (already drafted) + per-task scope confirmed. |
| **T1** | Lighthouse 6th target. README.md edit only — extend `TARGETS` bash array with `"correlation:/analytics/correlation?x=reports.total&y=incidents.total"`. Verify `run-audit.mjs` accepts query-string-suffixed `LH_PATH` (it should — see line 68). Pre-flight test: run the new target locally against vite preview + seeded session; confirm `apps/frontend/lighthouse/reports/correlation/SUMMARY.md` is generated with non-trivial scores. | T0 | 0.2d | README updated; one local audit run produces `reports/correlation/` directory with SUMMARY.md + 6 JSONs (3 light + 3 dark). |
| **T2** | Q1 catalog grouping refactor in `CorrelationFilters.tsx` (~30 LoC): replace flat `catalog.map(...)` with 2-tier grouping by `root` prefix. Add 2 new section-header testids. Add 2 new i18n keys + Resources interface entry. Add 2 new vitest test cases. RED first per `tdd-workflow` skill (write tests, watch fail, then implement). | T0 | 0.3d | vitest 858/858 + 2 new = 860/860 GREEN; build GREEN; existing per-option testids still pass; manual smoke shows `[ Reports ]` / `[ Incidents ]` headers in the dropdown. |
| **T3** | Playwright E2E `correlation-uat.spec.ts` covering UAT 1-5 (each as a separate `test()` block). Reuses Pact-provider-state seeding pattern from `login-dashboard-actors.spec.ts:23-78`. Reuse `state: "seeded session as analyst"` for auth + `state: "correlation populated render"` (PR #36 T13 handler) for fixture seed. **No new state handler** — leverage T13's. | T0 | 0.7d | `pnpm --filter @dprk-cti/frontend exec playwright test correlation-uat.spec.ts` → 5/5 PASS locally against host-hybrid stack. |
| **T4** | Perf smoke `test_correlation_p95.py` + greenfield `services/api/tests/perf/conftest.py`. Pytest opt-in marker `@pytest.mark.perf` (added to `pyproject.toml` markers). Test body: seed populated DB via T13's `_ensure_correlation_populated_fixture` (or replicate the seed locally if state-handler invocation is brittle); spawn `httpx.AsyncClient` against running uvicorn; issue 50 sequential `GET /analytics/correlation?x=reports.total&y=incidents.total&date_from=2018-01-01&date_to=2026-04-30`; assert `numpy.percentile(durations, 95) <= 0.500`. | T0, T3 | 0.5d | `uv run pytest -m perf services/api/tests/perf/` → 1 test PASS locally. CI workflow (separate job, manual-trigger or schedule) added. |
| **T5** | T13 live verifier replay backfill. Run `pnpm --filter @dprk-cti/frontend pact:provider` against host-hybrid stack; capture transcript at `.codex-review/correlation-hardening-t5-pact-verify.transcript.log` (gitignored). Confirm 5/5 new D-1 interactions verify + legacy 21 still pass. Add a one-line summary to this plan §6 testing strategy citing the transcript. | T0, T3 | 0.2d | Transcript captured; §6 cites the run; expected log line `Verified pact (5 + 21 interactions, 26 total) ✓`. |
| **T6** | PR body draft at `docs/plans/correlation-hardening-body.md` (will rename to `pr{N}-correlation-hardening-body.md` at T7 push per `plan_doc_convention`). Sections: Scope + Why + Base + Plan ref + What lands (commit table) + Architecture map + Verification ✅/🟡 split per `pattern_pr_body_verification_split` + AC table per §7 + What's NOT in this PR + Reviewer test plan + Decision log + Pre-merge checklist. | T1, T2, T3, T4, T5 | 0.25d | Body file committed; Codex T6 r1 review + fold to CLEAN PROCEED. |
| **T7** | Push DRAFT branch + open PR + PR-as-diff Codex loop (per `pattern_codex_body_review_loop`). Rename plan + body to `pr{N}-*` after `gh pr list` confirms the assigned PR number. | T6 | 0.2d | DRAFT PR open at the assigned number; CI 24/24 SUCCESS at PR head; Codex PR-as-diff r1 + fold loop converges to CLEAN PROCEED. |
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
| **R-C5** | T13 live verifier replay reveals a real verification failure (5/4 instead of 5/5) — meaning PR #36's T13 handlers are subtly wrong. | Low | High | This is exactly why PR-C exists — to catch deferred manual-smoke gaps. If 5/5 doesn't pass, file a follow-up bug + fold the fix into PR-C scope (or hotfix PR before this lands). Per memory `pitfall_pact_v3_ci_cold_start_race`, distinguish between flake (rerun) vs real failure (fix). |
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
| 10 | vitest 860/860 GREEN (was 858/858 + 2 new); contract 26/26 GREEN; build GREEN | 🟡 (T2) |
| 11 | OpenAPI snapshot diff at PR head is empty | 🟡 (verify at T7) |
| 12 | Branch CI green on all 12 checks × 2 events | 🟡 (after push) |
| 13 | Final external Codex review reports no unresolved CRITICAL/HIGH | 🟡 (PR-as-diff at T7-T8) |
| 14 | PR body present at `docs/plans/pr{N}-correlation-hardening-body.md`; plan present at `docs/plans/pr{N}-correlation-hardening.md` | 🟡 (T6, rename at T7) |

---

## 8. Open questions / Defaults

(Per umbrella spec convention: minimal — items needing user/reviewer input but not blocking draft.)

1. **Q-C1 — Perf smoke CI cadence.** Default = `workflow_dispatch` (manual trigger) only. Alternative = `schedule` (e.g. nightly cron). Recommend manual; add schedule in a follow-up if NFR-1 regression detection becomes a concern.
2. **Q-C2 — Lighthouse 6th target seeding mechanism.** Default = query-string `?x=reports.total&y=incidents.total` (C3 lock). Alternative = Pact provider-state seed + cookie. Recommend query-string; simpler and matches the umbrella's "seeded fixture id" pattern for `/reports/999001` etc. — but the cookie path may be required if the page renders empty even with query params (verify at T1 pre-flight).
3. **Q-C3 — Q1 catalog grouping label copy.** Default = `Reports` / `Incidents` (en) + `보고서` / `사건` (ko) — matches existing `shell.nav.reports` + `shell.nav.incidents` copy. Alternative = explicit "Section: Reports" prefix. Recommend default; minimal copy.
4. **Q-C4 — Perf smoke sample-size N.** Default = 50 sequential requests per umbrella §3 NFR-1 + UAT 6. Alternative = larger N for tighter percentile. Recommend default; matches the spec.

---

## 9. §0.1 amendment change log

**(initially empty — populated during T-1 r1 / T0..T8 as folds land.)**

---

**End of plan v1.0. Awaits Codex T-1 r1 plan review.**
