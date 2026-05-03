# Plan — D-1 Correlation FE Visualization (next correlation FE PR)

**Phase:** 3 Slice 3 (PR B) — D-1 frontend visualization for the correlation primitive shipped in PR #28.
**Status:** Draft 2026-05-03 — awaits user PROCEED before implementation lock. **Sequenced AFTER the design-contract PR** (DESIGN.md v2 Layout Patterns) per the 2026-05-03 reviewer lock — this PR is opened only once the design contract is on `main`.
**PR number:** Not reserved. Confirm via `gh pr list` immediately before opening; current main HEAD is `705e6f9`, only PR #30 (DQ CLI Windows fix) is open at draft time.
**Predecessors:** PR #28 (D-1 BE primitives + methodology page; merged 2026-05-03 PM as `597a972`) **AND** the next design-contract PR (DESIGN.md v2 Layout Patterns + page-class taxonomy + C1–C4 locks).
**Successors:** Next hardening PR (slice 3 PR C — Lighthouse target, E2E spec, perf smoke; per umbrella §11).
**Umbrella spec:** `docs/plans/phase-3-slice-3-correlation.md` §8, §11 — locked invariants are inherited unchanged; this plan only narrates HOW the FE side meets them.

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
| **B1** | Route lives at FE path `/analytics/correlation`; reachable from analytics nav and the command palette (`⌘K → "correlation"` / `"상관분석"`). | Umbrella §8.1. Single new route, additive on top of the existing analytics surface. |
| **B2** | Components split into 5 leaves under `apps/frontend/src/features/analytics/correlation/`: `CorrelationPage` (route container), `CorrelationFilters`, `CorrelationCaveatBanner`, `CorrelationLagChart`, `CorrelationWarningChips`. | Umbrella §8.3. One responsibility per leaf, mirrors the dashboard precedent (`KPICard` / `TrendChart` / `MotivationDonut`). |
| **B3** | Two react-query hooks: `useCorrelationSeries()` (catalog, never stales — `staleTime: Infinity`) and `useCorrelation(x, y, dateFrom, dateTo, alpha)` (primary, 5-min stale time, matches `/dashboard/summary`). | Umbrella §8.7 + NFR-1 cache TTL. Catalog is small and immutable per session; primary is the heavy path that benefits from TTL caching. |
| **B4** | Chart = recharts `LineChart` at fixed 480×240 (no `ResponsiveContainer`). | TrendChart precedent + memory `pitfall_jsdom_abortsignal_react_router` predecessor (responsive containers under happy-dom are flaky). |
| **B5** | URL state = additive — new namespace `analytics.correlation.*` slots new keys (`x`, `y`, `date_from`, `date_to`, `method`) without renaming existing ones. | Umbrella §8.5. Keeps PR #12-#15 URL-state contracts intact. |
| **B6** | i18n keys live under `correlation.*` in both `ko.json` and `en.json`. Korean is the primary copy per FR-6. | Umbrella §6.3 + FR-6. Matches the existing `dashboard.*` / `reports.*` namespacing. |
| **B7** | Pact consumer adds **three interactions**: (1) happy `GET /api/v1/analytics/correlation` over `reports.total × incidents.total` returning a populated 200, (2) `GET /api/v1/analytics/correlation` with a too-narrow window returning 422 `value_error.insufficient_sample`, and (3) `GET /api/v1/analytics/correlation/series` returning a 1-row baseline catalog. | Umbrella §7.6 + NFR-5. Three interactions because catalog is its own endpoint and the FE relies on it for dropdowns. |
| **B8** | Vitest component tests cover: (a) 4-state render (loading / error / empty / populated), (b) URL state hydration + write-back, (c) method-toggle switches the highlight, (d) caveat banner dismiss-once-per-session, (e) warning-chip render for each of the 6 codes, (f) shared query-cache invariant (one fetch per cache-key across mounted consumers — per memory `pattern_shared_cache_test_extension`). | Umbrella §8.4 + project memory `pattern_shared_query_cache_multi_subscriber`. |
| **B9** | TypeScript schemas live in `apps/frontend/src/lib/api/schemas.ts` as zod schemas matching the BE pydantic shape exactly: `correlationSeriesItemSchema`, `correlationCatalogResponseSchema`, `correlationCellMethodBlockSchema`, `correlationLagCellSchema`, `correlationWarningSchema`, `correlationInterpretationSchema`, `correlationResponseSchema`. | Mirrors the existing `attackMatrixResponseSchema` pattern. zod parses every BE response — drift between BE and FE is caught at runtime, not in production. |
| **B10** | Empty-state typed reasons branch on `detail[0].type` from the BE 422 envelope: `value_error.insufficient_sample` → "표본이 부족합니다 (최소 30개월 필요)" / "Insufficient sample (minimum 30 months required)"; `value_error.identical_series` → "서로 다른 시계열을 선택하세요" / "Pick two different series"; plain `value_error` → "데이터를 불러올 수 없습니다" / "Unable to load data". | Umbrella §5.1 + §7.3. Single uniform error parser path. |
| **B11** | Branch name `feat/p3.s3-correlation-fe`, base = `main` directly (PR A merged 2026-05-03 PM, no stacking required). | Umbrella §11 dependency DAG; PR A is already on main per the post-PR-29 verification (`705e6f9`). |

---

## 3. Scope

### In scope (this correlation FE PR)

- **Page-class runtime mechanism (T0)** — fulfils the design-contract PR's PT-7 taxonomy at runtime:
  - `apps/frontend/src/lib/pageClass.ts` (5-element `PageClass` union including `system-page` + typed `PAGE_CLASS_BY_ROUTE` manifest mirroring `apps/frontend/src/routes/router.tsx` at commit `705e6f9`: 9 entries — `/login`, `/dashboard`, three analyst-workspace route pairs (six routes total: `/reports`, `/reports/:id`, `/incidents`, `/incidents/:id`, `/actors`, `/actors/:id`), NotFound `*`)
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
- Nav entry under analytics + command-palette entry.
- i18n keys under `correlation.*` in `ko.json` + `en.json` (matching the umbrella §6.3 copy locks).
- zod schemas + query-key + endpoint helpers in `apps/frontend/src/lib/api/`.
- URL-state additions hooked into `useFilterUrlSync`.
- Pact consumer test additions in `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts` (3 new interactions).
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
| **T0** | Page-class runtime mechanism (fulfils the design-contract PR's PT-7 taxonomy at runtime). Add `apps/frontend/src/lib/pageClass.ts` exporting `type PageClass = 'editorial-page' \| 'auth-page' \| 'analyst-workspace' \| 'admin-workspace' \| 'system-page'` (5 classes; `system-page` covers the inline `NotFound` rendered by the router's wildcard `path: '*'`). Add a typed `PAGE_CLASS_BY_ROUTE` manifest covering every route currently mounted in `apps/frontend/src/routes/router.tsx` (verified at commit `705e6f9`): `/login` (auth-page), `/dashboard` (editorial-page), `/reports`, `/reports/:id`, `/incidents`, `/incidents/:id`, `/actors`, `/actors/:id` (all three route pairs / six routes analyst-workspace), `*` NotFound (system-page). The index `/` redirect is **not** a routed page and is excluded from the manifest. `/search` is **not** mounted in the router today and is excluded — when a routed search page later ships, that PR adds the manifest entry. Add a `data-page-class="..."` attribute on the outermost route container of each manifested page; for `*` NotFound, hang the attribute on the existing `<section>` returned by `router.tsx::NotFound`. Add a vitest test under `apps/frontend/src/routes/__tests__/pageClass.test.tsx` asserting (a) every manifested route's container carries the attribute, (b) the attribute matches `PAGE_CLASS_BY_ROUTE`, (c) the manifest stays synchronized with the route table — adding a new route without manifest entry fails the test, and conversely adding a manifest entry without a real route also fails (so the manifest cannot drift forward of the router). **No visual change** — attribute is invisible at runtime. | design-contract PR merged onto `main` | 0.5d | Test green; manifest contains exactly 9 entries (8 distinct route paths + NotFound `*`); every manifested route container has the attribute; no visual regression in dashboard/login (snapshot tests, if any, stay green). |
| **T1** | Workspace inventory: read `services/api/src/api/schemas/correlation.py`, `services/api/src/api/routers/analytics_correlation.py`, `services/api/tests/integration/test_correlation_route.py` to lock the consumer-side contract from the merged BE source. Not RED — purely mapping. | — | 0.25d | Document at `apps/frontend/src/features/analytics/correlation/CONTRACT.md` (private, gitignored) summarising the 8 nullable / strict / typed fields the FE relies on. |
| **T2** | zod schemas in `apps/frontend/src/lib/api/schemas.ts` for the 7 new response shapes (catalog item / catalog response / cell-method-block / lag-cell / warning / interpretation / primary response). Strict mode (`.strict()`), all unions matched literal-for-literal with the pydantic Literal[] enums. | T1 | 0.5d | New unit test `schemas.test.ts` covers happy parse + 6 negative cases (extra field, wrong literal, null in non-null cell). |
| **T3** | Endpoint helpers in `apps/frontend/src/lib/api/endpoints.ts` (`fetchCorrelationCatalog`, `fetchCorrelation`). Match the existing `fetchAttackMatrix` shape: query-string builder + zod-parsed return. | T2 | 0.25d | Unit tests in `endpoints.test.ts` cover both helpers; abort-signal forwarded; 422 detail surface preserved as throw. |
| **T4** | Query keys in `apps/frontend/src/lib/queryKeys.ts` (`analyticsCorrelationCatalog()`, `analyticsCorrelation(x, y, dateFrom, dateTo, alpha)`). | T3 | 0.1d | Unit tests confirm key stability + key change on filter change. |
| **T5** | Hooks `useCorrelationSeries` + `useCorrelation` per B3. | T4 | 0.5d | Hook tests cover loading/error/empty states + cache reuse across remounts. |
| **T6** | OpenAPI snapshot regen check via existing `pnpm --filter @dprk-cti/frontend openapi:check`. Should be a no-op since BE is unchanged. | T5 | 0.1d | Snapshot diff is empty; CI gate stays green. |
| **T7** | Component tests authored FIRST per TDD: 4-state render + URL state + method toggle + banner dismiss + warning chips + shared-cache invariant. All RED. | T5 | 1.0d | Test file count: ~6 new test files; collectively run < 5 s. All 6 component test groups RED. |
| **T8** | Pact consumer additions (3 interactions): catalog happy, primary happy, primary 422 insufficient_sample. Happy-path lag_grid uses a 49-cell minimum-shape fixture (1 cell per lag, all-`reason: null` populated cells per spec §5.2). | T7 | 0.5d | Local `pnpm --filter @dprk-cti/frontend pact:consumer` produces a regenerated `contracts/pacts/frontend-dprk-cti-api.json`. Expected delta: +3 interactions, +~150 LoC at most. |
| **T9** | Components implementation: `CorrelationPage` (route container, hook orchestration — carries `data-page-class="analyst-workspace"` per T0 manifest), `CorrelationFilters` (X/Y/date/method), `CorrelationCaveatBanner` (sticky + dismiss-once), `CorrelationLagChart` (recharts LineChart 480×240), `CorrelationWarningChips`. Implement until T7 tests GREEN. | T0, T7, T8 | 1.5d | All component tests green; chart renders deterministically under happy-dom. |
| **T10** | Router mount + nav entry + command palette entry. URL-state hookup via existing `useFilterUrlSync`. Append `'/analytics/correlation'` to T0's `PAGE_CLASS_BY_ROUTE` manifest. | T0, T9 | 0.25d | Manual smoke: navigating from `/dashboard` → analytics nav → correlation page renders the populated state with default `reports.total × incidents.total`. T0 vitest test now covers the new route. |
| **T11** | i18n keys (ko + en) covering all visible strings: page title, filter labels, method toggle, caveat banner title/body, methodology link text, warning-chip messages (one per code × language), empty-state copy (3 reasons), loading skeleton SR-only label. | T9 | 0.5d | i18n init-test passes + visible-string scan via `eslint-plugin-i18next` (existing) reports 0 hardcoded strings. |
| **T12** | Plan doc + PR body draft: this file + `docs/plans/correlation-fe-body.md`. | T11 | 0.25d | Both committed. PR body skeleton populated with the umbrella spec lock references. Rename to `pr{N}-*` only after `gh pr list` confirms the assigned number. |
| **T13** | BE-side Pact verifier hook (CI step) wires through unchanged — but verify locally that `pnpm pact:provider` (or equivalent) replays all 3 new interactions against a stub-state-handler-driven backend. Per memory `pattern_pact_dependency_override_via_provider_state`. | T8 | 0.25d | Local replay: 3/3 new interactions verify; legacy interactions still 100% pass. |

**Estimated dev-time:** ≈ 5.9 dev-days (T0 adds 0.5d for the page-class runtime mechanism). Aligns with umbrella §11's "medium ≈ 20 files / ≈ 800 LoC" PR-B sizing — T0 adds ~3 small files (manifest + test + per-route attribute wiring) so total file count holds at ≈ 23 / total LoC stays under 900.

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|:---|:---:|:---|
| Recharts data-testid forwards to multiple sub-elements; series tests use `getByTestId` and break on Pearson + Spearman dual-line render. | Med | Memory `pitfall_recharts_testid_multielement` — use `getAllByTestId('correlation-lag-line').length).toBeGreaterThan(0)` plus per-line distinguisher via `data-testid="line-pearson"` / `"line-spearman"`. |
| Pact V3 mock-server cold-start CI race makes 1-2 of the 3 new interactions flake. | Low | Memory `pitfall_pact_v3_ci_cold_start_race` — rerun first; do NOT modify test/code on a single intermittent miss. |
| Pact `eachLike(...)` rejects the empty `warnings: []` array in the happy-path interaction. | Med | Memory `pitfall_pact_fixture_shape` — supply at least one minimal warning sample in the happy interaction OR use `like([])` rather than `eachLike([])`; we'll go with `like([])` for the empty-warnings happy path and `eachLike(<sample>)` only for the populated-warnings interaction (which we add only if scope allows in T8). |
| OpenAPI snapshot grows past readability threshold when slice 4 lands later. | Low | Memory `openapi_snapshot_size_watch` — current snapshot is 5159 lines (≈ 85 KB at PR #11 + PR #28 era). This PR adds zero BE surface so snapshot is unchanged. Keep the path-split lever in reserve for slice 4. |
| Caveat banner dismiss-once-per-session uses `sessionStorage` and breaks under happy-dom. | Low | Initialise via `useSyncExternalStore` from a tiny zustand store with localStorage persistence keyed by `correlation.banner.dismissed.<session_uuid>`. Memory `pitfall_zustand_useSyncExternalStore_layout_effect` — skip the first emit via `isInitialMountRef`. |
| Method-toggle re-fetches even though both Pearson and Spearman live in the single response. | Low | The toggle is purely visual — it never changes the query key. Test T7 includes an "exactly one fetch" assertion across toggle clicks (per `pattern_shared_query_cache_multi_subscriber`). |
| URL-state hydration on hard reload mounts the page mid-loading and the URL writes back immediately, racing the user. | Med | Memory `pitfall_browser_router_init_replaceState` — filter spy calls by URL shape; in production, debounce write-back behind `useEffect` that depends on the parsed-from-URL state, not on the freshly-edited filter object. |
| Vendor 422 envelope shape drifts (BE could change `detail[].type` codes). | Low | T2 zod schema for the error envelope (separate from the 200 schema) pins the 3 codes. T3's `fetchCorrelation` parses errors through it; drift fails fast in `endpoints.test.ts`. |
| TopoJSON-style static asset proliferation if the chart later wants country-shaped overlays. | Low | Out of scope for D-1; if it ever lands, follow `pattern_topojson_bundled_static`. |

---

## 6. Rollback Plan

This PR is **purely additive on the FE side**:

- New feature dir, new route, new i18n entries, new schemas, new query keys, new Pact interactions.
- Zero changes to the BE: `services/api/` is not touched.
- Zero changes to existing FE routes / dashboard / reports / actors / incidents pages.

Revert path: `git revert <merge-commit>` removes the route, restores the i18n files, and removes the 3 new Pact interactions. The catalog/primary BE endpoints remain on main (shipped in PR #28) and stay independently verifiable via `curl` or the Pact provider job.

No DB migrations. No environment-variable changes. No feature flags.

---

## 7. Acceptance Criteria

This PR is mergeable only when **all** of the following hold:

1. `pnpm --filter @dprk-cti/frontend run build` exits 0 (per memory `feedback_real_build_check`).
2. `pnpm --filter @dprk-cti/frontend test` reports all new and existing FE tests green; zero xfail / xskip introduced.
3. T0's `pageClass.test.tsx` is green: every manifested route container carries the `data-page-class` attribute matching `PAGE_CLASS_BY_ROUTE`; manifest contains exactly 10 entries at PR head time (9 existing per `router.tsx` at `705e6f9` — `/login`, `/dashboard`, three analyst-workspace route pairs / six routes total (`/reports`, `/reports/:id`, `/incidents`, `/incidents/:id`, `/actors`, `/actors/:id`), NotFound `*` — plus the new `/analytics/correlation` route added in T10); test fails fast in both directions (new route without manifest entry, or manifest entry without route).
4. The 6 vitest component-test groups from B8 each have at least one assertion: 4-state, URL-state, method-toggle, banner-dismiss, warning-chips, shared-cache.
5. `pnpm --filter @dprk-cti/frontend pact:consumer` regenerates the consumer pact with **+3** interactions and no schema-drift in existing ones.
6. The provider verify job (`api-tests / pact-verify`) passes all interactions including the 3 new ones (per `pattern_pact_dependency_override_via_provider_state` — a state-handler dep override resolves the catalog + populated lag-grid fixtures).
7. The OpenAPI snapshot diff at PR head is empty (BE unchanged confirmation per T6).
8. Manual smoke through the dev triad (per memory `pattern_host_hybrid_dev_triad`): log in as `analyst@dev.local` → `/dashboard` → analytics nav → `/analytics/correlation` → default-pair render shows populated state, the caveat banner, and at least one significant lag cell.
9. Manual i18n smoke: locale toggle KO ↔ EN — every visible string swaps; the methodology link target is the same URL.
10. Branch CI green on all jobs that ran for PR #28: `frontend-tests`, `frontend-build`, `pact-consumer`, `pact-verify`, plus the legacy `worker-tests` / `api-tests`.
11. Plan doc + PR body present at `docs/plans/correlation-fe.md` and `docs/plans/correlation-fe-body.md` (or their `pr{N}-*` renamed forms post-opening).
12. Final external Codex review reports no unresolved CRITICAL/HIGH findings (per `feedback_codex_iteration` — typically 3-4 rounds; LOWs at the PASS gate are fold-or-skip).

---

## 8. Open Questions

- **Q1 — Dropdown UX for catalog series.** The catalog is small (≈ 20 IDs) but the umbrella spec is silent on whether the X/Y dropdowns should partition by `root` (`reports.published` vs `incidents.reported`). Recommendation: render a single flat list with an `[ Reports ]` / `[ Incidents ]` group-header inside the dropdown — cheap, no new IA. **Default if no input by impl-start: single flat dropdown grouped by root via section headers.**
- **Q2 — Default date window.** Spec §6.1 returns the resolved `date_from`/`date_to` but doesn't lock the FE's *initial* window. Recommendation: empty URL → default = full available data window (FE asks BE for a `meta.default_window` once via the catalog; if catalog doesn't carry it, fall back to `[earliest_published, today]` derived from a one-shot `/dashboard/summary` lookup). **Default if no input: derive from the existing dashboard date-range selector default (whatever the dashboard is already using as 'all time').**
- **Q3 — Banner dismiss persistence scope.** Session-only (sessionStorage) vs forever (localStorage)? Spec says "sticky". Recommendation: session-only — every fresh tab re-shows the caveat because correlation reading drift is the dominant risk. **Default: sessionStorage scoped per-tab.**
- **Q4 — `alpha` exposure.** Umbrella §5.3 says alpha is a query parameter (default 0.05). Recommendation: do **not** surface it in the FE filters in this PR — leave it server-default 0.05. Add it later if user research surfaces a need. **Default: not surfaced; FE always sends without `alpha` and the BE applies its 0.05 default.**

These are **defaults**, not blockers — if the user has no opinion, T2-T13 proceed with the defaults and the open questions get folded into the PR body's "Defaults applied" section. If the user wants to override, T2 picks up the overrides and re-locks B-row decisions.

---

## 9. Change Log

- **2026-05-03 (draft)** — Plan authored after PR #28 merged onto main as `705e6f9`. PR-#28 BE schema + router read in `services/api/src/api/schemas/correlation.py` + `services/api/src/api/routers/analytics_correlation.py` to lock the consumer-side contract. Awaits user PROCEED.
