# Plan — Dashboard Workspace Retrofit (PR 2 of Option-C 3-PR sequence)

**Phase:** Implementation of the Dashboard Workspace Pattern locked in `DESIGN.md` after PR #32 (merged 2026-05-04 AM as `75936fd`).
**Status:** Draft 2026-05-04. Awaits user PROCEED before D1 implementation work begins.
**PR number:** Not reserved. Confirm via `gh pr list` immediately before opening; current main HEAD is `75936fd`, 0 OPEN PRs at draft time.
**Predecessors:** PR #32 (DESIGN.md amendment; merged 2026-05-04 AM as `75936fd`). All 12 contract locks (G1-G5 edits + 4 component vocabulary entries + 3 Don'ts) are immutable inputs to this PR.
**Successors:** PR 3 — SNA data + wiring. The actor-network-graph slot rendered by this PR as Planned-no-data-yet (or hidden) gets populated in PR 3.
**Source artifacts (immutable for this PR):**
- `DESIGN.md` `## Dashboard Workspace Pattern` section + `## Page Classes` mapping table at HEAD.
- `tmp/sketches/dashboard-workspace-v1.html` v3 (gitignored throwaway, retained as visual reference per session decision (b'). NOT bundled, NOT imported, NOT linked from any production code.

---

## 1. Goal

Land the user-visible workspace retrofit on `/dashboard` per the contract:
- Relayout `DashboardPage.tsx` into the contract's 3-pane composition (left rail + center + right rail) with heading row + period readout + center widget grid + reserved Actor Network slot. **Rails live INSIDE `DashboardPage.tsx`; `Shell.tsx` remains UNCHANGED** (per L1 architectural lock).
- Delete the deprecated `DashboardHero` (component + test).
- Update `summarySharedCache.test.tsx` subscriber count.
- Reposition `AlertsDrawer` to a permanent right-rail static section (no live data wiring).
- Ship two new live components: `PeriodReadout` + `RankedRowWithShareBar`.
- Migrate the 4 ranked panels (`LocationsRanked`, `SectorBreakdown`, `ContributorsList`, `GroupsMiniList`) to `RankedRowWithShareBar`.
- Render the `actor-network-graph` slot per the contract: hidden via feature flag OR title + the text-only empty state `Planned · no data yet`.

**Non-goal (out of scope for this PR):**
- `/reports`, `/incidents`, `/actors`, `/correlation` PT-1 retrofit. Rails MUST NOT propagate to those routes.
- SNA data path / endpoint / zod / Pact / populated graph (PR 3).
- Live alert / recent / drilldown data wiring (Phase 4).
- Comprehensive responsive redesign — this PR ships the minimum collapse-contract guarantee only (left-anchor + right-monitoring access preserved at <breakpoints>); a comprehensive mobile-first redesign is a separate downstream PR.
- BE / API changes. No new endpoints, no schema changes, no Pact interactions added or modified.
- New design tokens. Every value comes from existing tokens.css / DESIGN.md scales.
- `apps/frontend/src/lib/pageClass.ts` typed manifest (correlation-fe T0 owns that). Shell uses route-path matching directly to avoid coupling sequencing.

---

## 2. Locked Decisions

User-locked at PR 2 plan-stage 2026-05-04 (L1-L6) + dependency/pattern locks (L7-L12).

| ID | Decision | Rationale |
|:---:|:---|:---|
| **L1** | Route-scoped retrofit. Rails are rendered **inside `DashboardPage.tsx`** (a 3-pane container). **`Shell.tsx` is UNCHANGED** — it remains a generic frame (top-nav + FilterBar + `<Outlet/>`). Other routes (`/reports`, `/reports/:id`, `/incidents`, `/incidents/:id`, `/actors`, `/actors/:id`, `/login`, `*` NotFound, `/analytics/correlation` when mounted) get the same Shell with their own page component and no rails — no propagation risk because there's nothing in Shell to propagate. **Shell MUST NOT import any `apps/frontend/src/features/dashboard/*` component**, and DashboardPage MUST own the 3-pane composition. | DESIGN.md `## Dashboard Workspace Pattern` is the single documented exception within `analyst-workspace`; PT-1 still owns record-list workspaces. Putting rails inside DashboardPage keeps Shell as a layout primitive rather than a router-aware composition; layer boundaries stay clean. |
| **L2** | `actor-network-graph` slot renders in production as either (a) hidden via feature flag, OR (b) the card chrome (border + title + card-head) + the text-only empty state `Planned · no data yet`. **No mock SVG, no synthetic nodes/edges, no skeleton chart, no sparkline, no visualization-shaped placeholder.** | DESIGN.md Don't bullet (G5 #2) + the actor-network-graph component vocabulary entry both enforce this. Sketch v3 is gitignored / never bundled. |
| **L3** | `DashboardHero.tsx` deletion + `DashboardHero.test.tsx` deletion + `summarySharedCache.test.tsx` subscriber-count update ship in **the same commit** (or at minimum the same PR). Currently the test pins **7 subscribers** (verified at `apps/frontend/src/features/dashboard/__tests__/summarySharedCache.test.tsx:79` — "all seven summary subscribers"); after hero removal it becomes **6**. | Splitting hero removal across PRs leaves `summarySharedCache.test.tsx` pinning a count that's wrong for one merge window; same-PR avoids that gap. |
| **L4** | `AlertsDrawer.tsx` repositions from floating drawer trigger to a permanent right-rail static section. **No live data wiring.** Rendered content: `{typography.caption-uppercase}` title + `Phase 4` placeholder pill + single empty-state line `Phase 4 — no live alerts wired yet`. | DESIGN.md `alerts-rail-section` component vocabulary entry. Live alerts are Phase 4. The drawer-trigger pattern is removed from `/dashboard`; it stays available for any non-dashboard surface that still needs the floating pattern (none currently use it, but the component itself is not deleted). |
| **L5** | `RankedRowWithShareBar` applies to exactly four panels: `LocationsRanked`, `SectorBreakdown`, `ContributorsList`, `GroupsMiniList`. **No other panel migrates to it in this PR.** | DESIGN.md component vocabulary entry pins these four. Other panels (KPIStrip / WorldMap / AttackHeatmap / etc.) use their existing component patterns unchanged. |
| **L6** | Mobile / tablet collapse at the **minimum contract level only**: at `< 1024px`, the rails collapse such that left-rail anchor access and right-rail monitoring access remain reachable (e.g., a top anchor strip + a bottom drawer or simple stack). **Comprehensive responsive redesign is DEFERRED** to a separate downstream PR. | DESIGN.md `### Pane Geometry` deliberately leaves "exact mechanics" to implementation. This PR picks the cheapest mechanism that satisfies the contract; broader responsive work is a separate scope. |
| **L7** | `PeriodReadout` is a **read-only mirror** of the global FilterBar's date-range state. It subscribes to the same `useFilterStore` slot the FilterBar inputs write to, but exposes no setter / no input / no click-to-edit. The "change in filter bar ↑" hint glyph is text-only — clicking it does NOT scroll, focus, or otherwise navigate. | DESIGN.md Don't bullet (G5 #3) + the `period-readout` component vocabulary entry both forbid editability. A click-to-focus interaction would re-introduce the two-surface contract risk. |
| **L8** | Heading row geometry: `{spacing.md}` tall, no card chrome, no hairline divider. Page `<h1>` left-aligned + `period-readout` right-aligned within a flex row. | DESIGN.md `### Heading Row` (post-Codex-r1 fold). |
| **L9** | TDD per memory `pattern_tdd_10step_inventory_shape_before_contract`. Step 0 = inventory (read-only mapping; not RED). RED component tests authored before any GREEN implementation. | Project-standard development discipline. |
| **L10** | Shell stays unchanged (per L1) — no page-class detection mechanism in Shell, no `useLocation()` guard in Shell. **Page-class enforcement is by code-review against L1**, not a runtime check. The correlation-fe T0 manifest at `apps/frontend/src/lib/pageClass.ts` is unrelated to this PR; when it lands, it serves the `data-page-class` runtime attribute work, which is independent of the rail-rendering decision. | Sequencing decoupling: this PR and the correlation-fe PR ship independently. No tactical stop-gap is required because the rails live inside DashboardPage, not Shell. |
| **L11** | i18n keys for new copy live under `dashboard.*` namespace (existing). No new top-level i18n namespace. Korean primary per FR-6. | Existing `apps/frontend/src/i18n/{ko,en}.json` convention (files sit directly under `apps/frontend/src/i18n/`, NOT a `locales/` subdir). New keys: `dashboard.heading.threatOverview`, `dashboard.period.label`, `dashboard.period.hint`, `dashboard.alerts.phase4Pill`, `dashboard.alerts.emptyState`, `dashboard.recent.emptyState`, `dashboard.drilldown.emptyState`, `dashboard.actorNetwork.title`, `dashboard.actorNetwork.plannedEmptyState`. Anything else surfaces as Open Question Q4. |
| **L12** | **No BE / API / Pact changes.** This PR is purely FE. OpenAPI snapshot regeneration must produce zero diff. | Contract scope decision: PR 2 = layout only; PR 3 = BE data path. Mixing creates the same hazard the Option-C sequence was designed to avoid. |
| **L13** | Branch name `feat/dashboard-workspace-retrofit`, base = `main` directly. | Standard convention. PR 2 is sequenced after PR 1 (#32) merged; no stacking. |
| **L14** | Iteration cadence: 3-4 review rounds (memory `feedback_codex_iteration` + `pattern_layered_visual_redesign`). At least one Codex code-review round on the canonical implementation. | Implementation PRs typically need 3-6 Codex rounds; this PR's scope is medium so 3-4 is the working estimate. |

---

## 3. Scope

### In scope (this PR)

**Components — new:**
- `apps/frontend/src/layout/PeriodReadout.tsx` (≈ 30 LoC) + `__tests__/PeriodReadout.test.tsx`.
- `apps/frontend/src/layout/RankedRowWithShareBar.tsx` (≈ 60 LoC) + `__tests__/RankedRowWithShareBar.test.tsx`.
- `apps/frontend/src/features/dashboard/DashboardLeftRail.tsx` (≈ 100 LoC — section anchors + Pinned + Quick filter, all static initially) + `__tests__/DashboardLeftRail.test.tsx`.
- `apps/frontend/src/features/dashboard/DashboardRightRail.tsx` (≈ 80 LoC — alerts-rail-section + recent-activity-list + drilldown-empty-state, all static initially) + `__tests__/DashboardRightRail.test.tsx`.

**Components — modified:**
- `apps/frontend/src/layout/Shell.tsx` — **UNCHANGED** in this PR (per L1). Listed here only to make the no-change explicit; reviewers must confirm Shell stays a generic frame.
- `apps/frontend/src/routes/DashboardPage.tsx` — relayout to 3-pane structure (this is where rails live now), heading row + period readout, center widget grid, reserved Actor Network slot card, DashboardHero usage removed. The page is structurally a 3-column flex/grid container that mounts left rail + center + right rail as direct children.
- `apps/frontend/src/features/dashboard/LocationsRanked.tsx` — migrate row pattern to `RankedRowWithShareBar`.
- `apps/frontend/src/features/dashboard/SectorBreakdown.tsx` — same.
- `apps/frontend/src/features/dashboard/ContributorsList.tsx` — same.
- `apps/frontend/src/features/dashboard/GroupsMiniList.tsx` — same.
- `apps/frontend/src/features/dashboard/AlertsDrawer.tsx` — convert from floating drawer trigger to right-rail static section (or extract a new `AlertsRailSection.tsx` and leave the original drawer file alone if the drawer pattern is reused elsewhere — verified during T0 inventory).

**Components — deleted:**
- `apps/frontend/src/features/dashboard/DashboardHero.tsx`.
- `apps/frontend/src/features/dashboard/__tests__/DashboardHero.test.tsx`.

**Tests — modified:**
- `apps/frontend/src/features/dashboard/__tests__/summarySharedCache.test.tsx` — subscriber-count update (currently **7** with hero per line 79 "all seven summary subscribers"; becomes **6** without).
- Any DashboardPage / Shell tests that pin the old layout markup (verified during T0 inventory).

**i18n:**
- `apps/frontend/src/i18n/ko.json` — add 8-9 keys under `dashboard.*` per L11. (No `locales/` subdir in this repo.)
- `apps/frontend/src/i18n/en.json` — same keys.

**Plan + body docs:**
- `docs/plans/dashboard-workspace-retrofit.md` (this file).
- `docs/plans/dashboard-workspace-retrofit-body.md` (PR body draft, authored at T11).

### Out of scope (deferred — explicit, with target PR)

- `/reports`, `/incidents`, `/actors` PT-1 retrofit → separate per-route PRs.
- `/analytics/correlation` route mount + page → correlation FE PR (`docs/plans/correlation-fe.md` already locked).
- SNA data path / endpoint / zod schemas / Pact interactions / populated `actor-network-graph` rendering → **PR 3**.
- Live alerts data → Phase 4.
- Live recent-activity feed → Phase 4.
- Selection-driven drilldown wiring → Phase 4.
- Comprehensive responsive redesign for mobile / tablet → separate downstream PR (this PR ships the minimum collapse contract only).
- `apps/frontend/src/lib/pageClass.ts` typed manifest → correlation-fe T0.
- Refactoring Shell to consume the manifest once it lands → small follow-up PR after correlation-fe T0.

---

## 4. Task Breakdown

Per memory `pattern_tdd_10step_inventory_shape_before_contract` — Step 0 (T0) = inventory (not RED), Step ≥1 = RED tests before GREEN implementation.

| # | Task | Depends on | Est. | Exit criteria |
|:---:|:---|:---|:---:|:---|
| **T0** | Inventory: read `Shell.tsx` (confirm UNCHANGED is feasible — i.e., the `<Outlet/>` is a flex-grow child that lets DashboardPage own its own viewport-fill — Codex confirmed at v1.1 review), `DashboardPage.tsx`, `AlertsDrawer.tsx`, `summarySharedCache.test.tsx`, `FilterBar.tsx` (confirm store fields `dateFrom` / `dateTo` exposed via `useFilterStore` per Codex F3), 4 ranked panel components, existing dashboard tests pinning layout markup. Re-verify (already established at v1.1/v1.2 plan-review time): subscriber count = 7 (line 79 "all seven"); DashboardHero importers in `apps/frontend/src/**/*.ts(x)` = `DashboardPage.tsx` + `DashboardHero.test.tsx` + `summarySharedCache.test.tsx` (per Codex F6); AlertsDrawer has 0 non-dashboard production consumers (per Codex Q7 confirmation). **Inventory output goes inline into plan v1.3 + PR body** (no separate `_inventory.md` file). | — | 0.1d | Subscriber count re-verified at branch-creation HEAD; hero importer grep re-run; AlertsDrawer audit re-confirmed; FilterBar `dateFrom` / `dateTo` slot access confirmed; Shell unchanged-feasibility re-confirmed; findings folded into plan v1.3 + PR body draft if anything has shifted from v1.2's snapshot. |
| **T1** | RED: `PeriodReadout.test.tsx` — renders `Period` label + date-range value + hint glyph; subscribes to `useFilterStore`; updates when store updates; has NO setter / NO input / NO click handler attached to interactive elements. | T0 | 0.2d | Test file authored; test fails (component doesn't exist yet). |
| **T2** | RED: `RankedRowWithShareBar.test.tsx` — anatomy assertions: **avatar exactly 32×32 with 1px `{colors.hairline}` border, `{colors.canvas}` background, `{colors.body}` initials, `{rounded.none}` corners** (per DESIGN.md `ranked-row-with-share-bar` vocabulary entry); name, sub, bar-track, bar-fill width prop, value tabular-nums, percentage; top-item bar fill = 100%; bar fill color is `{colors.body}` not `{colors.primary}` (regex assert on rendered class / inline style); hairline divider between rows; no row hover background. | T0 | 0.2d | Test file authored; 8 anatomy assertions + 4 behavior assertions; all RED. |
| **T3** | RED: `DashboardLeftRail.test.tsx` — renders Sections group + Pinned actors group + Quick filter group; section anchors use PT-5 1px Rosso left-edge stripe on active row (regex assert); checkbox rows render unchecked by default; no live data fetches. | T0 | 0.2d | Test file authored; test fails. |
| **T4** | RED: `DashboardRightRail.test.tsx` — renders `alerts-rail-section` (title + Phase 4 pill + empty-state line, NO mock rows); `recent-activity-list` (title + empty-state line, NO mock rows); `drilldown-empty-state` (`Phase 4 — drilldown not wired yet` copy); no live data fetches. | T0 | 0.2d | Test file authored; test fails. |
| **T5** | RED: `Shell.test.tsx` static-source assertion (memory `pattern_factory_wiring_guard`) — verify Shell.tsx **does not import** any path under `apps/frontend/src/features/dashboard/`. This is the L1 architectural lock test: catches accidental Shell coupling at lint-test time, not at code-review-only time. | T0 | 0.1d | Test extension authored; assertion is `expect(shellSource).not.toMatch(/from ['"][^'"]*features\/dashboard/)`. Fails before T9 if any import exists; passes after T9 lands clean. |
| **T6** | RED: `DashboardPage.test.tsx` extension — heading row present with `dashboard-heading-row` testid; **heading row asserts `{spacing.md}` height** (regex on inline style or computed style hook per existing dashboard test conventions found at T0); DashboardHero component absent (regex assert no `dashboard-hero` testid); page renders `dashboard-left-rail` + `dashboard-right-rail` testids that DashboardPage owns directly (not Shell — confirms L1); 14-widget grid topology preserved in center (KPIStrip + WorldMap + AttackHeatmap + ActorNetwork slot + LocationsRanked + Donut + YearBar + SectorBreakdown + ContributorsList + TrendChart + GroupsMiniList + MotivationStackedArea + SectorStackedArea + ReportFeed); ActorNetwork slot renders title + `Planned · no data yet` text-only empty state (or hidden if feature flag set to off); **ActorNetwork slot negative assertions: no `<svg>` element, no `<canvas>` element, no element with `data-testid` matching `node` / `edge` / `skeleton` / `sparkline` / `chart-marks` inside the slot** (per DESIGN.md `actor-network-graph` vocabulary entry's text-only constraint). | T0 | 0.25d | Test extension authored; 6 positive assertions + 5 negative assertions; all RED. |
| **T7** | GREEN — implementation order: `PeriodReadout.tsx` → `RankedRowWithShareBar.tsx` → `DashboardLeftRail.tsx` → **AlertsRailSection conversion (decided per T0 inventory: in-place rewrite of `AlertsDrawer.tsx`, OR extract a new `AlertsRailSection.tsx` if T0 found drawer pattern reuse — Codex confirmed at v1.1 review that `AlertsDrawer` has zero non-dashboard production consumers, so in-place rewrite is the default)** → `DashboardRightRail.tsx` (consumes the converted alerts-rail-section). Each step green when its T1-T4 test file passes. | T1, T2, T3, T4 | 0.45d | All 4 component test files green; AlertsDrawer conversion green; build exits 0. |
| **T8** | (skipped — Shell remains unchanged per L1; T5 static-source test already pins this. No GREEN work in Shell.) | — | 0d | n/a — task left in numbering for traceability. |
| **T9** | GREEN — `DashboardPage.tsx` relayout: 3-pane container (left rail + center + right rail as direct children), heading row at the top of the center column, center widget grid, Actor Network slot card. 4 ranked panels migrated to `RankedRowWithShareBar`. **AlertsRailSection wiring** (component already converted in T7 per Codex F7 fold; T9 only mounts it as a child of DashboardRightRail). T6 test passes. **Shell.tsx remains unchanged.** | T6, T7 | 0.4d | DashboardPage test green; T5 Shell static-source test still green (confirms no accidental Shell coupling); build exits 0; visual smoke shows new 3-pane layout with rails inside DashboardPage. |
| **T10** | DELETE `DashboardHero.tsx` + `DashboardHero.test.tsx`. UPDATE `summarySharedCache.test.tsx` subscriber count from **7 → 6** (verified at line 79 "all seven" → "all six" + remove the hero entry from the test's subscriber list). Grep all `DashboardHero` importers and remove imports. | T9 | 0.15d | `pnpm run build` exits 0; `pnpm test` all green; no remaining `DashboardHero` references in repo; summarySharedCache test asserts ONE fetch across 6 subscribers (per memory `pattern_shared_query_cache_multi_subscriber`). |
| **T11** | i18n keys added per L11 in `apps/frontend/src/i18n/{ko,en}.json` (no `locales/` subdir). Korean primary, English secondary. **Extend the existing i18n init-test (or add a new sibling test) with explicit assertions that every new dashboard key — exactly the 9 keys listed in L11 — is present and non-empty in BOTH `ko.json` and `en.json`.** (The current init-test per Codex F5 only checks one shell nav key + command IDs; it does NOT catch missing dashboard keys, so this PR explicitly extends it.) Manual review of changed files for hardcoded English strings (no `eslint-plugin-i18next` is configured in this repo per `apps/frontend/package.json` deps). | T9 | 0.25d | i18n init-test passes; new key-presence test green for all 9 keys × 2 locales; manual review of changed files reports zero hardcoded user-visible strings outside the i18n table; KO ↔ EN locale toggle in T13 swaps every visible new string. |
| **T12** | Plan doc + PR body draft committed. PR body sources from this plan's §1 / §2 / §3 / §7 sections. | T11 | 0.1d | Both files committed. |
| **T13** | Manual smoke per memory `pattern_host_hybrid_dev_triad` — log in as `analyst@dev.local` (per `keycloak_dev_realm` memory), navigate to `/dashboard`, verify: rails present, 3-pane structure, hero absent, period readout reads current FilterBar value, ActorNetwork slot shows Planned text, AlertsDrawer in right-rail position (no floating). Navigate to `/reports`, `/incidents`, `/actors` — verify rails ABSENT (L1 sanity). | T9 | 0.1d | Manual smoke notes captured; no visual regression on non-dashboard routes. |
| **T14** | Open PR (DRAFT) + Codex review iteration. 3-4 rounds expected per memory `feedback_codex_iteration`. CRITICAL/HIGH/MEDIUM folded as fix commits on the branch. | T12, T13 | 0.3d | Codex returns PROCEED-* with no unresolved CRITICAL/HIGH; CI green. |
| **T15** | Final smoke + flip draft → ready + merge via `--merge --delete-branch`. | T14 + reviewer approval | 0.05d | PR merged; remote branch deleted; main fast-forwards. |

**Estimated dev-time:** ≈ **1.7-2.0 dev-days** (medium PR per `pattern_design_contract_iteration_cadence`'s implementation-PR baseline; aligns with PR 2's user-stated 1.5-2.5 dev-day estimate).

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|:---|:---:|:---|
| `DashboardHero` has importers beyond the test file. | Med | T0 grep + T10 import removal. Memory `pattern_factory_wiring_guard` discipline — verify test still pins the absence post-removal. |
| `summarySharedCache.test.tsx` count change (7 → 6) ripples into the test's subscriber list (the 7 components currently mounted in the test must be reduced to 6 by removing the hero entry; the assertion message "all seven summary subscribers" at line 79 must update to "all six"). | Med | T0 confirms the exact subscriber list (already verified at v1.1: line 79 says "all seven"); T10 mechanical update. |
| `AlertsDrawer.tsx` floating-drawer pattern is reused on non-dashboard surfaces. | Low | T0 grep all `AlertsDrawer` imports across repo; if found, extract `AlertsRailSection.tsx` as a new component that consumes the same data-shape but renders in right-rail layout, leaving `AlertsDrawer.tsx` intact. If no other consumer, in-place conversion is safe. |
| Architectural drift: a future contributor adds rail rendering to `Shell.tsx` directly (violating L1) without realizing the layer rule. | Med | T5 static-source test (memory `pattern_factory_wiring_guard`) blocks any `Shell.tsx` import from `apps/frontend/src/features/dashboard/*` at test time. CI fails before merge. |
| `RankedRowWithShareBar` migration changes per-row markup; existing visual snapshot tests on the 4 ranked panels may need approval. | Med | If snapshot tests exist, regenerate during T9 and review the diffs in PR before pushing. Per `feedback_self_review_false_positive_triage`, verify the diff is the intended share-bar addition before approving. |
| (removed at v1.1 — N/A given Shell stays unchanged.) | — | — |
| Mobile collapse minimum mechanism is too cheap and ships a poor mobile experience. | Med | Acceptance criteria pin "left-anchor + right-monitoring access preserved at <breakpoints>" only — anything beyond that is L6 deferred. Codex review may flag if the implementation falls below the contract minimum. |
| `pnpm test` may include Pact verifier that's unaware no Pact change shipped — verifier may complain about stale interactions. | Low | L12 + T6 pin OpenAPI snapshot empty diff; Pact consumer + verifier should pass unchanged. If a Pact replay flake fires (memory `pitfall_pact_v3_ci_cold_start_race`), rerun once before treating as a finding. |
| i18n keys collide with existing `dashboard.*` namespace entries. | Low | T0 inventory reads `apps/frontend/src/i18n/{ko,en}.json` → confirm new key paths don't already exist. |
| `actor-network-graph` slot rendering needs a feature-flag mechanism (L2 (a) hidden) but the project may not have a flag system yet. | Med | If no flag system exists at T0 inventory time, default to L2 (b) — render title + `Planned · no data yet` text-only empty state. The contract permits both states; (b) requires no new infrastructure. |
| FilterBar's date-range store may not export a read-only selector cleanly — `PeriodReadout` may need to subscribe to the entire filter slice. | Low | Store fields are `dateFrom` / `dateTo` (camelCase, verified at `FilterBar.tsx`); URL/query params remain `date_from` / `date_to` (snake_case wire format). Use a selector (`useFilterStore((s) => [s.dateFrom, s.dateTo])`) so PeriodReadout doesn't re-render on unrelated filter slice changes. |
| Heading-row layout interferes with FilterBar (which sits above outlet); double "Period:" labels may confuse users. | Low | Heading-row Period readout is right-aligned and uses the `change in filter bar ↑` hint glyph to disambiguate. Manual smoke (T13) verifies the affordance reads cleanly. |

---

## 6. Rollback Plan

This PR is **purely additive on the FE side and additive-or-deleting on existing FE files**:

- New components added; deleting them via revert is mechanical.
- `DashboardHero.tsx` deletion is reversible via `git revert <merge-commit>` (file restored).
- `summarySharedCache.test.tsx` subscriber count update reverts.
- 4 ranked panels migration reverts to old markup.
- `AlertsDrawer.tsx` reverts to floating drawer (or `AlertsRailSection.tsx` extracted file is removed if T7 chose the extract path).
- `DashboardPage.tsx` reverts to old layout.
- `Shell.tsx` was unchanged (L1) so no Shell-level revert is needed.

Revert leaves no DB migrations, no environment changes, no feature flags. BE unchanged.

If revert lands AFTER PR 3 (SNA data + wiring) merges: PR 3's populated `actor-network-graph` component is rendered under the post-PR-2-revert DashboardPage which no longer has the slot. PR 3 sequencing is therefore strictly downstream of this PR.

---

## 7. Acceptance Criteria

Mergeable only when **all** of the following hold:

1. `pnpm --filter @dprk-cti/frontend run build` exits 0 (per memory `feedback_real_build_check`).
2. `pnpm --filter @dprk-cti/frontend test` reports all new + existing FE tests green; zero xfail / xskip introduced.
3. `summarySharedCache.test.tsx` updated subscriber count green; the test still asserts ONE fetch per shared cache slot (memory `pattern_shared_query_cache_multi_subscriber`).
4. New component test files (`PeriodReadout.test.tsx`, `RankedRowWithShareBar.test.tsx`, `DashboardLeftRail.test.tsx`, `DashboardRightRail.test.tsx`) all green; each has at least 4 assertions covering the L1-L8 contract points relevant to its component.
5. `DashboardHero.tsx` and `DashboardHero.test.tsx` removed. Code-scope check: `grep -rE "DashboardHero" apps/frontend/src/ --include="*.ts" --include="*.tsx"` returns zero matches. (Documentation references in `DESIGN.md` and `docs/plans/*` are PERMITTED — the new Don't bullet at DESIGN.md `### Don't` intentionally names the deprecated component, and plan docs reference it for historical traceability.) `summarySharedCache.test.tsx` asserts ONE fetch across **6** subscribers (down from 7); the line 79 message updates from "all seven" to "all six".
6. `Shell.tsx` is unchanged in this PR's diff. Static-source test (T5) confirms Shell does not import any `apps/frontend/src/features/dashboard/*` path. Rails live entirely inside `DashboardPage.tsx`.
7. Manual smoke (T13) on the dev triad shows `/dashboard` 3-pane layout with rails (rendered by DashboardPage), hero absent, period readout matching FilterBar, ActorNetwork slot showing `Planned · no data yet` text-only or hidden, AlertsDrawer in right-rail position with no floating trigger.
8. Manual smoke navigation to `/reports`, `/incidents`, `/actors` shows NO rails — and no DOM regressions in the topbar / FilterBar (Shell unchanged) (L1 sanity).
9. OpenAPI snapshot diff at PR head is empty (no BE changes — L12 confirmation).
10. i18n init-test green; manual review of changed files reports zero hardcoded user-visible strings outside the i18n table (`eslint-plugin-i18next` is NOT configured in this repo per `apps/frontend/package.json` — manual review is the available enforcement); KO ↔ EN locale toggle swaps every visible new string in T13 smoke.
11. CI green on all jobs that ran for PR #32: `frontend`, `frontend-e2e`, `api-tests`, `worker-tests`, `data-quality-tests`, `db-migrations`, `contract-verify`, `api-integration`, `python-services (api / worker / llm-proxy)`, `llm-proxy-tests`.
12. Plan doc + PR body present at `docs/plans/dashboard-workspace-retrofit.md` and `docs/plans/dashboard-workspace-retrofit-body.md` (or `pr{N}-*` renamed forms post-opening).
13. Final external Codex review reports no unresolved CRITICAL/HIGH findings (per `feedback_codex_iteration` — typically 3-4 rounds).
14. PR body explicitly states: "Layout-only PR. No BE changes. SNA data wiring deferred to PR 3."
15. Sketch (`tmp/sketches/dashboard-workspace-v1.html`) and `.git/info/exclude` `tmp/` line are NOT in the PR diff (decision (b'); local-only). **Mechanical pre-PR check** (run before flipping draft → ready): `git diff --name-only main...HEAD -- tmp/ .gitignore .git/info/exclude` returns empty AND `git ls-files tmp/` returns empty. Both checks must pass; failing either blocks the ready flip until reverted.

---

## 8. Open Questions

- **Q1 — `actor-network-graph` slot rendering: hidden flag vs. text-only empty state?** L2 permits both. Recommendation: text-only empty state (no flag infrastructure needed; matches `alerts-rail-section` and `recent-activity-list` discipline). **Default if no input by T0: text-only `Planned · no data yet` empty state.**
- **Q2 — `RankedRowWithShareBar` shared base with existing `KPICard` etc.?** They share Ferrari card chrome but have different content shapes. Recommendation: don't share; `RankedRowWithShareBar` is a distinct row variant for ranked list-cards, not a KPI card. **Default if no input by T7: independent component.**
- **Q3 — `drilldown-empty-state` as a separate component or inline JSX inside `DashboardRightRail`?** Empty state is 3 lines of JSX with one i18n key. Memory `pattern_factory_wiring_guard` doesn't apply — there's no factory to violate. Recommendation: inline JSX. **Default if no input by T7: inline.**
- **Q4 — `AlertsDrawer.tsx` rename to `AlertsRailSection.tsx` or in-place conversion?** Depends on T0 inventory finding (whether floating drawer pattern is reused elsewhere). **Default: in-place if no other consumer; extract new file `AlertsRailSection.tsx` if drawer pattern is reused.**
- **Q5 — Mobile collapse mechanism (inside DashboardPage): top-anchor strip + bottom-sheet drawer, OR simple stack-collapse below `<lg`?** L6 says minimum compliance. Recommendation: simple stack-collapse below `<lg` inside DashboardPage's CSS — no drawer mechanics, lowest implementation cost; left-rail content stacks above center; right-rail content stacks below ReportFeed. **Default if no input by T9: simple stack-collapse via CSS in DashboardPage.**
- **Q6 — Where do we capture the "i18n init-test passes" check?** Existing FE test suite includes an i18n smoke test (per session memory). Verify name in T0 and add it explicitly to AC #10. **Default: confirmed during T0.**

These are **defaults**, not blockers — if no user input arrives by the depending task's start, the default applies and the open question is folded into the PR body's "Defaults applied" section.

---

## 9. Change Log

- **2026-05-04 — v1.2** — Folded 9 Codex plan-review findings (transcript at `.codex-review/dashboard-workspace-retrofit-plan.transcript.log`, verdict PROCEED-WITH-AMENDMENT, all mechanical):
  - **HIGH F1**: §1 Goal still had "page-class-aware left/right rail slots to Shell.tsx" — replaced with DashboardPage-owns-rails wording per L1.
  - **HIGH F2**: §3 In-scope had stale "currently 6 with hero; becomes 5 without" — corrected to 7 → 6 with line 79 reference.
  - **HIGH F3**: store field names — actual is `dateFrom` / `dateTo` (camelCase) per `FilterBar.tsx`; `date_from` / `date_to` are URL/wire names. Risks row + L7 reword.
  - **HIGH F4**: §3 + Risks still had `apps/frontend/src/i18n/locales/{ko,en}.json` — corrected to `apps/frontend/src/i18n/{ko,en}.json`.
  - **HIGH F6**: AC #5 "grep returns zero matches across the repo" was overbroad — DESIGN.md + plan docs intentionally mention DashboardHero. Scoped to `apps/frontend/src/**/*.ts(x)` code only.
  - **MEDIUM F5**: T11 + AC #10 honest about i18n enforcement — existing init-test only checks one shell nav key, NOT dashboard keys. Plan now explicitly extends the init-test with a 9-keys × 2-locales presence assertion.
  - **MEDIUM F7**: T7 implementation order rewritten to include AlertsRailSection conversion BEFORE DashboardRightRail GREEN (T4 RED test requires alerts-rail-section). Codex confirmed AlertsDrawer has 0 non-dashboard production consumers; default is in-place rewrite. T9 only wires.
  - **MEDIUM F8**: T2 + T6 RED test scope expanded to cover contract-required assertions: heading row `{spacing.md}` height; ranked-row avatar 32×32 + 1px hairline + canvas bg + body initials + rounded.none; ActorNetwork slot negative assertions (no svg/canvas/node/edge/skeleton/sparkline/marks).
  - **LOW F9**: AC #15 strengthened with mechanical pre-PR `git diff --name-only ...` + `git ls-files tmp/` check.
  - Verified clean by Codex: Q1 Shell unchanged-feasibility (Outlet flex-grow OK); Q3 4 ranked panel files all exist; Q7 AlertsDrawer no non-dashboard production consumer.
- **2026-05-04 — v1.1** — Folded 5 user-review findings against v1:
  - F1 (architectural): Shell.tsx stays UNCHANGED (per L1 rewrite). Rails live inside `DashboardPage.tsx`. Page-class detection inside Shell removed (L10 rewritten). T5 repurposed as a static-source assertion that Shell does not import any `features/dashboard/*` path. T8 (Shell GREEN work) skipped. Risk reframed as architectural-drift-by-future-contributor; T5 catches it.
  - F2 (factual): summarySharedCache subscriber count corrected — currently **7** (line 79 "all seven"), becomes **6** after hero removal. L3 + T10 + AC #5 updated.
  - F3 (factual): i18n path corrected — `apps/frontend/src/i18n/{ko,en}.json` (no `locales/` subdir). L11 + T11 updated.
  - F4 (factual): `_inventory.md` claim of gitignored was false. T0 inventory now flows inline into plan v1.2 + PR body, no separate file.
  - F5 (factual): `eslint-plugin-i18next` is NOT in `apps/frontend/package.json` deps. T11 + AC #10 reworded to "manual review of changed files + i18n init-test".
- **2026-05-04 (v1, draft)** — Plan authored after PR #32 merged onto main as `75936fd`. PR-#32 contract (DESIGN.md `## Dashboard Workspace Pattern` + 4 component vocabulary entries + 3 Don'ts) is the immutable source for the implementation locks. Awaits user PROCEED.
