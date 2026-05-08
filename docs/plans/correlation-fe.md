# Plan — D-1 Correlation FE Visualization (next correlation FE PR)

**Phase:** 3 Slice 3 (PR B) — D-1 frontend visualization for the correlation primitive shipped in PR #28.
**Status:** **READY v1.0** — Refreshed 2026-05-08 (Codex post-PR-#35 next-step decision review folded + r1 plan-review on refresh folded). Awaits user PROCEED before T0 dispatch. **Predecessors satisfied** — design-contract PR (PR #31) AND BE primitives PR (PR #28) both on `main`.
**PR number:** Not reserved. Confirm via `gh pr list` immediately before opening; **current main HEAD is `5b42c6e`** (PR #35 merge, 2026-05-08), **0 OPEN PRs** at refresh time. Next assigned PR number will likely be #36 (verify with `gh pr list --state all --limit 5` at open time).
**Predecessors:** PR #28 (D-1 BE primitives + methodology page; merged 2026-05-03 PM as `597a972`) **AND** PR #31 (`feat/design-v2-layout-patterns` — DESIGN.md v2 Layout Patterns + page-class taxonomy + C1–C4 locks; merged 2026-05-04 as `cf3c2ed`). Intervening merges that DO NOT block this PR but inform the refresh: PR #32 (workspace amendment, `75936fd`), PR #33 (workspace retrofit, `d0d0a89`), PR #34 (KPI density, `7818cc0`), PR #35 (actor-network data, `5b42c6e`).
**Successors:** Next hardening PR (slice 3 PR C — Lighthouse target, E2E spec, perf smoke; per umbrella §11).
**Umbrella spec:** `docs/plans/phase-3-slice-3-correlation.md` §8, §11 — locked invariants are inherited unchanged; this plan only narrates HOW the FE side meets them. **Note on TTL rationale:** umbrella NFR-1 line 114 + §8.7 line 667 lock 5-min cache TTL with the prose "matches /dashboard/summary"; the actual `useDashboardSummary.ts:63` uses `staleTime: 30_000` (30 s, not 5 min). **This plan honors the umbrella's 5-min lock** but decouples its rationale from the /dashboard/summary code reference (see B3).

---

## 1. Goal

Land the user-visible side of the D-1 correlation primitive: an `/analytics/correlation` route that lets an `analyst`-role user pick two series from the catalog, render the lag-scan chart with both Pearson and Spearman significance flags, see the typed warning chips, and read the "correlation ≠ causation" caveat banner — all while consuming PR #28's locked DTO with no new BE changes.

**Non-goal (deferred to the next slice-3 hardening PR — umbrella §11 PR C):**
- Lighthouse target wiring + 6-target loop expansion
- E2E (Playwright) coverage of UAT criteria 1-5
- Performance smoke against populated DB asserting NFR-1 (p95 ≤ 500 ms)
- Full Codex iteration cycle (3-6 rounds — hardening PR absorbs)

**Non-goal (out-of-spec for slice 3 entirely):**
- Power-user "any-two-series" API (umbrella §10.1)
- Quarterly / yearly granularity (§10.2)
- F-2 / F-4 / F-5 downstream consumers (§10.3-10.5)
- Cross-pair correction (§10.6)

---

## 2. Locked Decisions

These mirror the umbrella spec's locks; this PR introduces no new policy. Each row says "PR-B reading of the umbrella lock" so the implementing PR can be audited against the spec without a side-by-side read.

| ID | Decision | Rationale |
|:---:|:---|:---|
| **B1** | Route lives at FE path `/analytics/correlation`; reachable from a **new top-nav entry** (`Analytics` or direct `Correlation` — final label finalized in T10 against the current `Shell.tsx:28-32` `NAV_ITEMS` array which today only carries `dashboard / reports / incidents / actors`) and the command palette (`⌘K → "correlation"` / `"상관분석"` — new entry appended to `apps/frontend/src/lib/commands.ts:43` `COMMAND_IDS as const` tuple, plus a corresponding key in `CommandPaletteButton.tsx:68` `NAV_PATHS` map so the palette navigates correctly). | Umbrella §8.1. Single new route. There is **no `/analytics/*` parent nav surface on `main@5b42c6e`** (earlier draft phrasing implied one) — this PR creates the first analytics-namespaced FE route. The nav addition is a one-line entry in `NAV_ITEMS` (and one new i18n key `shell.nav.analytics`) — additive, no rename. |
| **B2** | Components split into 5 leaves under `apps/frontend/src/features/analytics/correlation/`: `CorrelationPage` (route container), `CorrelationFilters`, `CorrelationCaveatBanner`, `CorrelationLagChart`, `CorrelationWarningChips`. | Umbrella §8.3. One responsibility per leaf, mirrors the dashboard precedent (`KPICard` / `TrendChart` / `MotivationDonut`). |
| **B3** | Two react-query hooks: `useCorrelationSeries()` (catalog, never stales — `staleTime: Infinity`) and `useCorrelation(x, y, dateFrom, dateTo, alpha)` (primary, **5-min stale time** per umbrella NFR-1 + §8.7 lock). | Umbrella §8.7 + NFR-1 cache TTL. Catalog is small and immutable per session; primary is the heavy path that benefits from TTL caching. **Decoupled from /dashboard/summary code reference** (header note above): `useDashboardSummary.ts` uses 30 s; the umbrella's "matches /dashboard/summary" prose is stale code-wise but the 5-min lock is the actual rationale (correlation is a heavier statistical primitive than KPI summary, computed against larger windows; 30 s would burn cycles without UX gain). |
| **B4** | Chart = recharts `LineChart` at fixed 480×240 (no `ResponsiveContainer`). | TrendChart precedent + memory `pitfall_jsdom_abortsignal_react_router` predecessor (responsive containers under happy-dom are flaky). |
| **B5** | URL state = additive — new namespace `analytics.correlation.*` slots new keys (`x`, `y`, `date_from`, `date_to`, `method`) without renaming existing ones. | Umbrella §8.5. Keeps PR #12-#15 URL-state contracts intact. |
| **B6** | i18n keys live under `correlation.*` in both `ko.json` and `en.json`. Korean is the primary copy per FR-6. | Umbrella §6.3 + FR-6. Matches the existing `dashboard.*` / `reports.*` namespacing. |
| **B7** | Pact consumer adds **five interactions** per umbrella §7.6 explicit lock (`docs/plans/phase-3-slice-3-correlation.md:580-586`): (1) `correlation_series happy` — catalog list with ≥ 1 series; (2) `correlation happy populated` — populated 49-cell `lag_grid`, both Pearson + Spearman methods, all `reason: null`, with one warning; (3) `correlation happy with insufficient_sample_at_lag cells` — populated grid where extreme-lag cells carry `reason: "insufficient_sample_at_lag"` (R-12 + §5.1); (4) `correlation happy with degenerate + low_count_suppressed cells` — pins both `reason: "degenerate"` (zero-variance synthetic) and `reason: "low_count_suppressed"` (R-16 mitigation), demonstrating the full 4-value `reason` enum in one interaction; (5) `correlation insufficient_sample 422` — `detail[]` envelope with `type: "value_error.insufficient_sample"` and `ctx.effective_n`. | Umbrella §7.6 + NFR-5. **Refresh 2026-05-08 aligns this plan to the umbrella's five-interaction lock** (the earlier draft under-specified the Pact surface; the extra happy variants pin all 4 `reason` enum values per umbrella §5.2's homogeneous 6-field cell shape, which the umbrella spec contract demands). See change log. |
| **B8** | Vitest component tests cover: (a) 4-state render (loading / error / empty / populated), (b) URL state hydration + write-back, (c) method-toggle switches the highlight, (d) caveat banner dismiss-once-per-session, (e) warning-chip render for each of the 6 codes, (f) shared query-cache invariant (one fetch per cache-key across mounted consumers — per memory `pattern_shared_cache_test_extension`). | Umbrella §8.4 + project memory `pattern_shared_query_cache_multi_subscriber`. |
| **B9** | TypeScript schemas live in `apps/frontend/src/lib/api/schemas.ts` as zod schemas matching the BE pydantic shape exactly: `correlationSeriesItemSchema`, `correlationCatalogResponseSchema`, `correlationCellMethodBlockSchema`, `correlationLagCellSchema`, `correlationWarningSchema`, `correlationInterpretationSchema`, `correlationResponseSchema`. | Mirrors the existing `attackMatrixResponseSchema` pattern. zod parses every BE response — drift between BE and FE is caught at runtime, not in production. |
| **B10** | Empty-state typed reasons branch on `detail[0].type` from the BE 422 envelope: `value_error.insufficient_sample` → "표본이 부족합니다 (최소 30개월 필요)" / "Insufficient sample (minimum 30 months required)"; `value_error.identical_series` → "서로 다른 시계열을 선택하세요" / "Pick two different series"; plain `value_error` → "데이터를 불러올 수 없습니다" / "Unable to load data". | Umbrella §5.1 + §7.3. Single uniform error parser path. |
| **B11** | Branch name `feat/p3.s3-correlation-fe`, base = `main` directly (PR A merged 2026-05-03 PM as `597a972`, no stacking required). | Umbrella §11 dependency DAG; PR A is on main, PR #31 (design contract) is on main as of `cf3c2ed`, current `main@5b42c6e` (PR #35 merge). No stacked-PR base-flip risk per memory `pitfall_stacked_pr_merge_base_flip`. |

---

## 3. Scope

### In scope (this correlation FE PR)

- **Page-class runtime mechanism (T0)** — fulfils the design-contract PR's PT-7 taxonomy at runtime:
  - `apps/frontend/src/lib/pageClass.ts` (5-element `PageClass` union including `system-page` + typed `PAGE_CLASS_BY_ROUTE` manifest mirroring `apps/frontend/src/routes/router.tsx@5b42c6e` (verified 2026-05-08): 9 manifest entries pre-this-PR — `/login` (auth-page), `/dashboard` (**analyst-workspace** per DESIGN.md page-class table line 403), three analyst-workspace record-list route pairs / 6 routes total (`/reports`, `/reports/:id`, `/incidents`, `/incidents/:id`, `/actors`, `/actors/:id`), NotFound `*` (system-page); **+1 entry added by this PR** = `/analytics/correlation` (analyst-workspace per DESIGN.md page-class table line 410). Final manifest count after this PR merges = **10 entries**)
  - `data-page-class="..."` attribute on each manifested route container, including the `<section>` rendered by `router.tsx::NotFound`
  - `apps/frontend/src/routes/__tests__/pageClass.test.tsx` (bi-directional manifest ↔ DOM ↔ DESIGN.md table consistency — fails on either drift direction)
- New feature dir `apps/frontend/src/features/analytics/correlation/`:
  - `CorrelationPage.tsx`
  - `CorrelationFilters.tsx`
  - `CorrelationCaveatBanner.tsx`
  - `CorrelationLagChart.tsx`
  - `CorrelationWarningChips.tsx`
  - `useCorrelationSeries.ts`
  - `useCorrelation.ts`
  - `__tests__/` for the component + hook tests above
- New route handler in `apps/frontend/src/routes/router.tsx` mounting `/analytics/correlation`.
- New top-nav entry in `Shell.tsx:28-32` `NAV_ITEMS` + command-palette entry in `commands.ts:43` `COMMAND_IDS` and `CommandPaletteButton.tsx:68` `NAV_PATHS`.
- i18n keys under `correlation.*` in `ko.json` + `en.json` (matching the umbrella §6.3 copy locks).
- zod schemas + query-key + endpoint helpers in `apps/frontend/src/lib/api/`.
- URL-state additions hooked into `useFilterUrlSync`.
- Pact consumer test additions in `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts` (5 new interactions per B7).
- OpenAPI snapshot regeneration (will pick up nothing new since BE is unchanged — PR is FE-only — but the regen step proves the snapshot didn't drift).
- Plan doc itself committed under `docs/plans/correlation-fe.md` (this file). When the PR is actually opened, rename to `docs/plans/pr{N}-correlation-fe.md` only after `gh pr list` confirms the assigned number.
- PR-body draft staged at `docs/plans/correlation-fe-body.md` (per memory `plan_doc_convention`); same rename-after-opening rule applies.

### Out of scope (deferred — explicit, with target PR)

- Lighthouse target + 6-target loop → next hardening PR
- Playwright E2E for UAT 1-5 → next hardening PR
- Performance smoke against populated DB → next hardening PR
- Codex full 3-6-round iteration → next hardening PR
- Catalog dropdown filtering by series root (reports vs incidents) — flagged as **Open Question Q1** below; default = no filter, single flat dropdown
- Methodology page render styling — page exists at `docs/methodology/correlation.md` from PR #28; FE links to it, doesn't restyle it

### Out of spec entirely (umbrella §10)

- Power-user any-two-series API
- Quarterly/yearly granularity
- F-2 / F-4 / F-5 downstream slots

---

## 4. Task Breakdown

Per memory `pattern_tdd_10step_inventory_shape_before_contract` — Step 1 is inventory (not RED), Step 6 is OpenAPI snapshot regen (proves BE drift didn't sneak in), Step 8 is Pact (consumer-driven, after schemas are pinned).

| # | Task | Depends on | Est. | Exit criteria |
|:---:|:---|:---|:---:|:---|
| **T0** | Page-class runtime mechanism (fulfils the design-contract PR's PT-7 taxonomy at runtime). Add `apps/frontend/src/lib/pageClass.ts` exporting `type PageClass = 'editorial-page' \| 'auth-page' \| 'analyst-workspace' \| 'admin-workspace' \| 'system-page'` (5 classes; `system-page` covers the inline `NotFound` rendered by the router's wildcard `path: '*'`). Add a typed `PAGE_CLASS_BY_ROUTE` manifest covering every route currently mounted in `apps/frontend/src/routes/router.tsx` (verified against `main@5b42c6e` 2026-05-08): `/login` (auth-page), `/dashboard` (analyst-workspace per DESIGN.md page-class table line 403), `/reports`, `/reports/:id`, `/incidents`, `/incidents/:id`, `/actors`, `/actors/:id` (all three route pairs / six routes analyst-workspace), `*` NotFound (system-page). The index `/` redirect is **not** a routed page and is excluded from the manifest. `/search` is **not** mounted in the router today and is excluded — when a routed search page later ships, that PR adds the manifest entry. **This PR also adds `/analytics/correlation` (analyst-workspace) to the manifest** — bringing the post-merge total to 10 entries. Add a `data-page-class="..."` attribute on the outermost route container of each manifested page; for `*` NotFound, hang the attribute on the existing `<section>` returned by `router.tsx::NotFound`. Add a vitest test under `apps/frontend/src/routes/__tests__/pageClass.test.tsx` asserting (a) every manifested route's container carries the attribute, (b) the attribute matches `PAGE_CLASS_BY_ROUTE`, (c) the manifest stays synchronized with the route table — adding a new route without manifest entry fails the test, and conversely adding a manifest entry without a real route also fails (so the manifest cannot drift forward of the router). **No visual change** — attribute is invisible at runtime. | design-contract PR (PR #31) merged onto `main` ✓ | 0.5d | Test green; manifest contains exactly **10 entries** post-merge (9 distinct route paths + NotFound `*`); every manifested route container has the attribute; no visual regression in dashboard/login (snapshot tests, if any, stay green). |
| **T1** | Workspace inventory: read `services/api/src/api/schemas/correlation.py`, `services/api/src/api/routers/analytics_correlation.py`, `services/api/tests/integration/test_correlation_route.py` to lock the consumer-side contract from the merged BE source. Not RED — purely mapping. | — | 0.25d | Document at `apps/frontend/src/features/analytics/correlation/CONTRACT.md` (private, gitignored) summarising the 8 nullable / strict / typed fields the FE relies on. |
| **T2** | zod schemas in `apps/frontend/src/lib/api/schemas.ts` for the 7 new response shapes (catalog item / catalog response / cell-method-block / lag-cell / warning / interpretation / primary response). Strict mode (`.strict()`), all unions matched literal-for-literal with the pydantic Literal[] enums. | T1 | 0.5d | New unit test `schemas.test.ts` covers happy parse + 6 negative cases (extra field, wrong literal, null in non-null cell). |
| **T3** | Endpoint helpers in `apps/frontend/src/lib/api/endpoints.ts` (`fetchCorrelationCatalog`, `fetchCorrelation`). Match the existing `fetchAttackMatrix` shape: query-string builder + zod-parsed return. | T2 | 0.25d | Unit tests in `endpoints.test.ts` cover both helpers; abort-signal forwarded; 422 detail surface preserved as throw. |
| **T4** | Query keys in `apps/frontend/src/lib/queryKeys.ts` (`analyticsCorrelationCatalog()`, `analyticsCorrelation(x, y, dateFrom, dateTo, alpha)`). | T3 | 0.1d | Unit tests confirm key stability + key change on filter change. |
| **T5** | Hooks `useCorrelationSeries` + `useCorrelation` per B3. | T4 | 0.5d | Hook tests cover loading/error/empty states + cache reuse across remounts. |
| **T6** | OpenAPI snapshot regen check via the canonical BE-side flow per `contracts/openapi/README.md`: `cd services/api && uv run python ../../scripts/regenerate_openapi_snapshot.py` (developer-run regen) + `cd services/api && uv run pytest tests/contract/test_openapi_snapshot.py -q` (CI drift guard, compare-only). Should be a no-op since BE is unchanged. | T5 | 0.1d | Snapshot diff is empty; CI gate stays green. |
| **T7** | Component tests authored FIRST per TDD: 4-state render + URL state + method toggle + banner dismiss + warning chips + shared-cache invariant. All RED. | T5 | 1.0d | Test file count: ~6 new test files; collectively run < 5 s. All 6 component test groups RED. |
| **T8** | Pact consumer additions (**5 interactions** per B7 + umbrella §7.6): (1) catalog happy ≥ 1 series; (2) primary happy populated 49-cell `lag_grid` (all `reason: null` + 1 warning); (3) primary happy with `insufficient_sample_at_lag` extreme-lag cells; (4) primary happy with `degenerate` + `low_count_suppressed` cells (pins all 4 `reason` enum values across this and (3)); (5) primary 422 `insufficient_sample` with `detail[].type` + `ctx.effective_n`. Use `pact-ruby` matcher cascade per memory `pitfall_pact_ruby_root_like_required` — root `like(...)` wrap + leaf `eachLike` for `lag_grid` + `string()` / `integer()` / `boolean()` per umbrella §5.2 homogeneous 6-field cell shape. | T7 | 0.7d | Local `pnpm --filter @dprk-cti/frontend pact:consumer` produces a regenerated `contracts/pacts/frontend-dprk-cti-api.json`. Expected delta: **+5 interactions**, +~250 LoC at most (umbrella §7.6 expects ~7 KB OpenAPI snapshot growth, but BE is unchanged so OpenAPI delta is 0; the 7 KB growth lands in PR A-equivalent — already on main). |
| **T9** | Components implementation: `CorrelationPage` (route container, hook orchestration — carries `data-page-class="analyst-workspace"` per T0 manifest), `CorrelationFilters` (X/Y/date/method), `CorrelationCaveatBanner` (sticky + dismiss-once), `CorrelationLagChart` (recharts LineChart 480×240), `CorrelationWarningChips`. Implement until T7 tests GREEN. | T0, T7, T8 | 1.5d | All component tests green; chart renders deterministically under happy-dom. |
| **T10** | Router mount + new top-nav entry + command palette entry. URL-state hookup via existing `useFilterUrlSync`. Append `'/analytics/correlation'` to T0's `PAGE_CLASS_BY_ROUTE` manifest. | T0, T9 | 0.25d | Manual smoke: navigating from `/dashboard` → new top-nav entry → correlation page renders the populated state with default `reports.total × incidents.total`. T0 vitest test now covers the new route. |
| **T11** | i18n keys (ko + en) covering all visible strings: page title, filter labels, method toggle, caveat banner title/body, methodology link text, warning-chip messages (one per code × language), empty-state copy (3 reasons), loading skeleton SR-only label. | T9 | 0.5d | i18n init-test passes + visible-string scan via `eslint-plugin-i18next` (existing) reports 0 hardcoded strings. |
| **T12** | Plan doc + PR body draft: this file + `docs/plans/correlation-fe-body.md`. | T11 | 0.25d | Both committed. PR body skeleton populated with the umbrella spec lock references. Rename to `pr{N}-*` only after `gh pr list` confirms the assigned number. |
| **T13** | BE-side Pact verifier hook (CI step) wires through unchanged — but verify locally that `pnpm pact:provider` (or equivalent) replays all 5 new interactions against a stub-state-handler-driven backend. Per memory `pattern_pact_dependency_override_via_provider_state`. | T8 | 0.25d | Local replay: 5/5 new interactions verify; legacy interactions still 100% pass. |

**Estimated dev-time:** ≈ 5.9 dev-days (T0 adds 0.5d for the page-class runtime mechanism). Aligns with umbrella §11's "medium ≈ 20 files / ≈ 800 LoC" PR-B sizing — T0 adds ~3 small files (manifest + test + per-route attribute wiring) so total file count holds at ≈ 23 / total LoC stays under 900.

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|:---|:---:|:---|
| Recharts data-testid forwards to multiple sub-elements; series tests use `getByTestId` and break on Pearson + Spearman dual-line render. | Med | Memory `pitfall_recharts_testid_multielement` — use `getAllByTestId('correlation-lag-line').length).toBeGreaterThan(0)` plus per-line distinguisher via `data-testid="line-pearson"` / `"line-spearman"`. |
| Pact V3 mock-server cold-start CI race makes 1-2 of the 5 new interactions flake. | Low | Memory `pitfall_pact_v3_ci_cold_start_race` — rerun first; do NOT modify test/code on a single intermittent miss. Validated end-to-end on PR #35 (cold-start race resolved by `gh run rerun --failed`, no test/code change). |
| Pact `eachLike(...)` rejects the empty `warnings: []` array in the happy-path interaction. | Med | Memory `pitfall_pact_fixture_shape` — supply at least one minimal warning sample in the happy interaction OR use `like([])` rather than `eachLike([])`. Plan: `like([])` for any empty-`warnings` interaction; `eachLike(<sample>)` for the B7 (2) `correlation happy populated` interaction which carries one warning per the locked fixture shape. |
| OpenAPI snapshot grows past readability threshold when slice 4 lands later. | Low | Memory `openapi_snapshot_size_watch` — current snapshot is 5159 lines (≈ 85 KB at PR #11 + PR #28 era). This PR adds zero BE surface so snapshot is unchanged. Keep the path-split lever in reserve for slice 4. |
| Caveat banner dismiss-once-per-session needs storage that survives remounts inside the same tab without leaking across tabs. | Low | Q3 default = sessionStorage (per-tab). Initialise via `useSyncExternalStore` from a tiny zustand store with sessionStorage persistence keyed by `correlation.banner.dismissed` (no session_uuid needed — sessionStorage is naturally per-tab). Verified under happy-dom 20.9.0 in T7 RED tests. Memory `pitfall_zustand_useSyncExternalStore_layout_effect` — skip the first emit via `isInitialMountRef`. |
| Method-toggle re-fetches even though both Pearson and Spearman live in the single response. | Low | The toggle is purely visual — it never changes the query key. Test T7 includes an "exactly one fetch" assertion across toggle clicks (per `pattern_shared_query_cache_multi_subscriber`). |
| URL-state hydration on hard reload mounts the page mid-loading and the URL writes back immediately, racing the user. | Med | Memory `pitfall_browser_router_init_replaceState` — filter spy calls by URL shape; in production, debounce write-back behind `useEffect` that depends on the parsed-from-URL state, not on the freshly-edited filter object. |
| Vendor 422 envelope shape drifts (BE could change `detail[].type` codes). | Low | T3's `fetchCorrelation` authors the zod error-envelope schema (separate from the 200 schema) and parses errors through it before throwing — drift fails fast in `endpoints.test.ts`. T2 covers only the 7 success-response DTOs per its own row's enumeration; the error-envelope sits with its consumer in T3 (per §0.1 amendment 2026-05-08, Codex T2 r2 fold). |
| TopoJSON-style static asset proliferation if the chart later wants country-shaped overlays. | Low | Out of scope for D-1; if it ever lands, follow `pattern_topojson_bundled_static`. |

---

## 6. Rollback Plan

This PR is **purely additive on the FE side**:

- New feature dir, new route, new i18n entries, new schemas, new query keys, new Pact interactions.
- Zero changes to the BE: `services/api/` is not touched.
- No visible behavior changes to existing FE routes / dashboard / reports / actors / incidents pages — existing route containers receive only a new `data-page-class="..."` attribute (T0 page-class runtime mechanism), invisible at runtime.

Revert path: `git revert <merge-commit>` removes the route, restores the i18n files, and removes the 5 new Pact interactions. The catalog/primary BE endpoints remain on main (shipped in PR #28) and stay independently verifiable via `curl` or the Pact provider job.

No DB migrations. No environment-variable changes. No feature flags.

---

## 7. Acceptance Criteria

This PR is mergeable only when **all** of the following hold:

1. `pnpm --filter @dprk-cti/frontend run build` exits 0 (per memory `feedback_real_build_check`).
2. `pnpm --filter @dprk-cti/frontend test` reports all new and existing FE tests green; zero xfail / xskip introduced.
3. T0's `pageClass.test.tsx` is green: every manifested route container carries the `data-page-class` attribute matching `PAGE_CLASS_BY_ROUTE`; manifest contains exactly 10 entries at PR head time (9 existing per `router.tsx@5b42c6e` — `/login` (auth-page), `/dashboard` (analyst-workspace per DESIGN.md page-class table), three analyst-workspace record-list route pairs / six routes total (`/reports`, `/reports/:id`, `/incidents`, `/incidents/:id`, `/actors`, `/actors/:id`), NotFound `*` (system-page) — plus the new `/analytics/correlation` (analyst-workspace) route added in T10); test fails fast in both directions (new route without manifest entry, or manifest entry without route).
4. The 6 vitest component-test groups from B8 each have at least one assertion: 4-state, URL-state, method-toggle, banner-dismiss, warning-chips, shared-cache.
5. `pnpm --filter @dprk-cti/frontend pact:consumer` regenerates the consumer pact with **+5** interactions per B7 + umbrella §7.6, and no schema-drift in existing ones.
6. The provider verify job (`api-tests / pact-verify`) passes all interactions including the 5 new ones (per `pattern_pact_dependency_override_via_provider_state` — a state-handler dep override resolves the catalog + populated lag-grid + reason-enum-discriminating fixtures).
7. The OpenAPI snapshot diff at PR head is empty (BE unchanged confirmation per T6).
8. Manual smoke through the dev triad (per memory `pattern_host_hybrid_dev_triad`): log in as `analyst@dev.local` → `/dashboard` → click new top-nav `Analytics` (or `Correlation` direct) entry → `/analytics/correlation` → default-pair render shows populated state, the caveat banner, and at least one significant lag cell. Also exercise via `⌘K → "correlation" / "상관분석"` to verify the command-palette path lands on the same route.
9. Manual i18n smoke: locale toggle KO ↔ EN — every visible string swaps; the methodology link target is the same URL.
10. Branch CI green on all jobs validated on PR #35 (`5b42c6e`): the 12 distinct checks `frontend`, `frontend-e2e`, `python-services` (api / worker / llm-proxy), `api-tests`, `worker-tests`, `llm-proxy-tests`, `db-migrations`, `data-quality-tests`, `contract-verify`, `api-integration` — each runs twice (push + pull_request event surfaces) → 24 SUCCESS / 0 FAILURE for the merge gate.
11. Plan doc + PR body present at `docs/plans/correlation-fe.md` and `docs/plans/correlation-fe-body.md` (or their `pr{N}-*` renamed forms post-opening).
12. Final external Codex review reports no unresolved CRITICAL/HIGH findings (per `feedback_codex_iteration` — 3-6 rounds typical; LOWs at the PASS gate are fold-or-skip).

---

## 8. Open Questions

- **Q1 — Dropdown UX for catalog series.** The catalog is small (≈ 20 IDs) but the umbrella spec is silent on whether the X/Y dropdowns should partition by `root` (`reports.published` vs `incidents.reported`). Recommendation: render a single flat list with an `[ Reports ]` / `[ Incidents ]` group-header inside the dropdown — cheap, no new IA. **Default if no input by impl-start: single flat dropdown grouped by root via section headers.**
- **Q2 — Default date window.** Spec §6.1 returns the resolved `date_from`/`date_to` but doesn't lock the FE's *initial* window. Recommendation: empty URL → default = full available data window (FE asks BE for a `meta.default_window` once via the catalog; if catalog doesn't carry it, fall back to `[earliest_published, today]` derived from a one-shot `/dashboard/summary` lookup). **Default if no input: derive from the existing dashboard date-range selector default (whatever the dashboard is already using as 'all time').**
- **Q3 — Banner dismiss persistence scope.** Session-only (sessionStorage) vs forever (localStorage)? Spec says "sticky". Recommendation: session-only — every fresh tab re-shows the caveat because correlation reading drift is the dominant risk. **Default: sessionStorage scoped per-tab.**
- **Q4 — `alpha` exposure.** Umbrella §5.3 says alpha is a query parameter (default 0.05). Recommendation: do **not** surface it in the FE filters in this PR — leave it server-default 0.05. Add it later if user research surfaces a need. **Default: not surfaced; FE always sends without `alpha` and the BE applies its 0.05 default.**

These are **defaults**, not blockers — if the user has no opinion, T2-T13 proceed with the defaults and the open questions get folded into the PR body's "Defaults applied" section. If the user wants to override, T2 picks up the overrides and re-locks B-row decisions.

---

## 9. Change Log

- **2026-05-03 (draft)** — Plan authored after PR #28 merged onto main as `597a972`; main HEAD at draft time was `705e6f9` (PR #29 visual-redesign-seed). PR-#28 BE schema + router read in `services/api/src/api/schemas/correlation.py` + `services/api/src/api/routers/analytics_correlation.py` to lock the consumer-side contract. Awaited user PROCEED.
- **2026-05-08 (refresh — Codex post-PR-#35 next-step decision review folded)** — Six freshness deltas resolved without re-spec'ing any locked invariant from the umbrella spec. Refresh trigger: PR #29..#35 merged in the 5-day gap; current main HEAD `5b42c6e`. Folded:
  - **Header & B11** — main HEAD updated `705e6f9` → `5b42c6e`; PR #30 (was open at draft) → MERGED; predecessors satisfied (PR #28 + PR #31 both on main); zero open PRs at refresh time.
  - **B1 (nav surface)** — clarified that no `/analytics/*` parent surface exists on `main@5b42c6e`; this PR creates the first analytics-namespaced FE route. Top-nav addition is one new entry in `Shell.tsx:28-32` `NAV_ITEMS` + one new `shell.nav.analytics` i18n key. Command-palette entry added by appending one ID to `commands.ts:43` `COMMAND_IDS as const` tuple plus a corresponding key in `CommandPaletteButton.tsx:68` `NAV_PATHS` map.
  - **B3 (cache TTL)** — decoupled rationale from the stale "matches /dashboard/summary" prose; umbrella's 5-min lock honored, but `useDashboardSummary.ts:63` actually uses `staleTime: 30_000`. Plan now cites umbrella NFR-1 + §8.7 directly with weight rationale (correlation is a heavier statistical primitive than KPI summary).
  - **B7 / T8 / T13 / §7 items 5+6+8+10 / §5 risks (Pact scope)** — aligned `+3` → **`+5`** interactions per umbrella §7.6 lock at `phase-3-slice-3-correlation.md:580-586`. The extra 2 happy variants pin all 4 `reason` enum values across (3) `insufficient_sample_at_lag` and (4) `degenerate` + `low_count_suppressed`, demonstrating umbrella §5.2's homogeneous 6-field cell shape with the full `reason` discrimination.
  - **T0 page-class manifest** — `/dashboard` corrected from `editorial-page` (pre-PR-#31 draft text) to **`analyst-workspace`** per DESIGN.md page-class table line 403 + the explicit `## Page Classes` paragraph "/dashboard was previously editorial-page; with this amendment it is analyst-workspace". Manifest count post-merge clarified as **10 entries** (9 existing + this PR's `/analytics/correlation`). All references at lines 100 / 155 updated.
  - **CI gate (§7 item 10)** — updated from PR #28's CI surface to PR #35's validated 12-check × 2-event = 24-success surface (the v2 CI workflow that landed via PR #16 infra-node20-gha-bump and was validated end-to-end on PR #35).
  No B-row policy invariant was changed; only freshness updates.

- **2026-05-08 (post-refresh r1 plan-review folds — 5 LOW)** — Codex r1 against the refreshed plan returned FOLD with 5 surgical items (status line wording + symbol citation + 3 stale residuals). All folded:
  - Status line at line 4 promoted to `READY v1.0`.
  - B1 command-palette citation `commands.ts:43-50 commandsRegistry` → `commands.ts:43 COMMAND_IDS as const` + `CommandPaletteButton.tsx:68 NAV_PATHS` (the actual export and the navigation map; `commandsRegistry` does not exist).
  - §6 rollback Pact count `3 new Pact interactions` → `5 new Pact interactions` (was missed in the prior refresh's sweep).
  - §6 "Zero changes to existing FE routes" softened to "no visible behavior changes — existing route containers receive only a new `data-page-class` attribute" (resolves T0 contradiction).
  - §3 + T10 nav wording "Nav entry under analytics" / "analytics nav" → "new top-nav entry" (consistent with B1 prose; no `/analytics/*` parent surface exists pre-this-PR).
  Per `pattern_sweep_class_when_codex_finds_one`, ran a final pre-commit grep for `analytics nav|3 new Pact|3 interactions|commandsRegistry|editorial-page` to confirm zero leftover residuals outside the change-log.

- **2026-05-08 (post-r1-fold status)** — **READY v1.0** for T0 dispatch (page-class runtime mechanism). Awaits user PROCEED to create branch `feat/p3.s3-correlation-fe` (no remote push until T15-equivalent gate per `collab_style`).

- **2026-05-08 (post-refresh r2 plan-review folds — 5 LOW)** — Codex r2 against the post-r1-fold plan returned FOLD with 5 LOW items. All folded:
  - **Nav residual at line 36** — B1 still had the literal `"analytics nav"` phrase in its rationale prose, contradicting the line-197 self-claim that residuals are confined to the change-log. Reworded to `no /analytics/* parent nav surface on main@5b42c6e (earlier draft phrasing implied one)` — preserves the explanation without the literal phrase.
  - **B1 nav-label finalization owner** — said "finalized in T0" (page-class runtime) but T10 owns router/nav mount per task-table. Folded to "finalized in T10".
  - **DESIGN.md page-class table line citation** — said line 405 but actual `/dashboard` row is at DESIGN.md line 403. Folded `replace_all` across plan body and change-log entries.
  - **§7 PASS gate Codex iteration count** — said `typically 3-4 rounds`; memory `feedback_codex_iteration` is `3-6 rounds typical`. Folded.
  - **§5 risk row optional-Pact wording** — said "populated-warnings interaction (which we add only if scope allows in T8)" but B7/T8 lock the warning-bearing interaction (B7 (2) is `correlation happy populated` with one warning). Removed the conditional clause; aligned with locked B7/T8.
  Per `pattern_sweep_class_when_codex_finds_one`, ran a final pre-commit grep for `analytics nav|3 new Pact|3 interactions|commandsRegistry|page-class table line 405|3-4 rounds|only if scope allows` to confirm zero leftover residuals.

- **2026-05-08 (post-r2-fold status)** — **READY v1.0** for T0 dispatch. Plan refresh + r1 fold + r2 fold all in working tree (not yet committed). Awaits Codex r3 CLEAN PROCEED before branch creation + T0 commit.

- **2026-05-08 (post-refresh r3 plan-review folds — 2 LOW)** — Codex r3 returned FOLD with 2 LOW live-prose residuals. Both folded:
  - **B7 rationale at `:42`** — removed historical "Earlier draft 2026-05-03 of this plan listed 3 interactions" phrasing; reworded to "Refresh 2026-05-08 aligns this plan to the umbrella's five-interaction lock (the earlier draft under-specified the Pact surface...)". Historical detail moved to change-log.
  - **§3 + T0 rationale at `:55` and `:100`** — removed historical "was editorial-page in pre-PR-#31 draft" / "corrected from pre-PR-#31 draft's editorial-page" phrasing; the page-class taxonomy literal `PageClass = 'editorial-page' | 'auth-page' | ...` stays (it's a TypeScript type literal, not a stale historical reference). The DESIGN.md line 403 citation stays.
  Final pre-commit grep `analytics nav|3 new Pact|3 interactions|commandsRegistry|page-class table line 405|3-4 rounds|only if scope allows|finalized in T0|was editorial-page` returns 0 hits in live prose; remaining hits exist only in the change-log historical entries (intentional).

- **2026-05-08 (post-r3-fold status)** — **READY v1.0** for T0 dispatch. Awaits Codex r4 CLEAN PROCEED.

- **2026-05-08 (§0.1 amendment — T2 r2 Codex fold)** — §5 risk row #7 (vendor 422 envelope drift) had said "T2 zod schema for the error envelope" — internally inconsistent with §4 T2 row's enumeration of "7 response shapes" (catalog item / catalog response / cell-method-block / lag-cell / warning / interpretation / primary response — none of which is the error envelope). §4 T3 row exit was already "422 detail surface preserved as throw", which is where the parsing happens. Reworded §5 row to attribute the error-envelope schema to T3, consistent with §4 T2/T3 enumeration. No invariant changed; T2 ships exactly the 7 success DTOs; T3 ships the 422 envelope schema + `fetchCorrelation` parsing. Per `pattern_plan_vs_impl_section_0_1_amendments` — this is a plan-vs-impl wording fix surfaced by Codex T2 r2; CONTRACT.md §3 + §3 sketch header updated to match (local-only doc).

- **2026-05-08 (§0.1 amendment — T3 helper-name alignment with sibling pattern)** — Plan §4 T3 prose used `fetchCorrelationCatalog` / `fetchCorrelation` for the helper names AND referenced "the existing fetchAttackMatrix shape", but the actual sibling helper is named `getAttackMatrix` — and so are all 16 other helpers in `endpoints.ts` (15× `get*` + `listActors` / `listReports` / `listIncidents` + `logout`; zero `fetch*`). Naming the new helpers `fetchCorrelation*` would create a 1-of-17 outlier, contradicting the plan's own "match the existing fetchAttackMatrix shape" instruction (which clearly meant "match the sibling pattern"). T3 ships them as `getCorrelationCatalog` / `getCorrelation` to match the sibling convention; the hook layer (T5) keeps the umbrella-locked names `useCorrelationSeries` / `useCorrelation` (decoupled from endpoint-helper naming, matching `useDashboardSummary` / `useAttackMatrix` etc.). No invariant changed; behavior is identical; CONTRACT.md §3 reference to `fetchCorrelation()` is a local-only doc and can stay or be updated later — does not affect any tracked artefact. Per `pattern_plan_vs_impl_section_0_1_amendments`.

- **2026-05-08 (§0.1 amendment — T6 OpenAPI regen command alignment)** — Plan §4 T6 prose said "via existing `pnpm --filter @dprk-cti/frontend openapi:check`", but no such FE script exists. The canonical flow lives BE-side per `contracts/openapi/README.md`: developer-run `cd services/api && uv run python ../../scripts/regenerate_openapi_snapshot.py` regenerates `contracts/openapi/openapi.json` from `app.openapi()`; CI runs the drift guard `cd services/api && uv run pytest tests/contract/test_openapi_snapshot.py -q` (compare-only — never writes back). T6 row updated to cite the canonical flow. Same shape of plan-vs-impl wording issue as T3's `fetchAttackMatrix` (which doesn't exist either; T3's amendment resolved that). Verified `5b42c6e` no-op end-to-end at T6 dispatch time: regen wrote 190,076 bytes / 35 paths byte-identical to committed snapshot; `git diff --stat contracts/openapi/openapi.json` empty; drift guard `4 passed in 2.64s`. Per `pattern_plan_vs_impl_section_0_1_amendments`.

- **2026-05-08 (§0.1 amendment — T7 caveat-banner storage alignment with Q3)** — §5 risk row at line 127 said "uses `sessionStorage` and breaks under happy-dom" with a mitigation pointing to `localStorage` + `<session_uuid>` suffix. This contradicted §8 Q3 default ("sessionStorage scoped per-tab"). Verified end-to-end under happy-dom 20.9.0 in T7 RED tests — sessionStorage works fine; the prior risk-row phrasing was speculative. §5 row reworded: storage keyed `correlation.banner.dismissed` (no `<session_uuid>` suffix needed — sessionStorage is naturally per-tab) using sessionStorage per Q3. T9 implementation will follow this aligned spec. Per `pattern_plan_section_precedence_4_normative_5_descriptive` — Q3 lock (user-decision in §8) is normative; §5 risk-mitigation prose was descriptive and is now corrected. Per `pattern_plan_vs_impl_section_0_1_amendments`.
