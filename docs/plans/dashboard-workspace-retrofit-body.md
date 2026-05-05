# PR 2 — Dashboard workspace retrofit (FE only)

Implements the Dashboard Workspace Pattern locked by [PR #32](https://github.com/smshin1121/DPRK-CTI/pull/32) (DESIGN.md amendment, merged 2026-05-04 as `75936fd`). PR 2 ships the FE relayout + 4-panel migration; **PR 3 follows with the SNA data path** (BE endpoint / zod / Pact / populated `actor-network-graph` rendering).

**Layout-only PR. No BE changes. SNA data wiring deferred to PR 3.**

## Scope

- **3-pane composition** on `/dashboard`: `DashboardLeftRail` (240px) + center column + `DashboardRightRail` (320px). Rails live INSIDE `DashboardPage.tsx` (Shell.tsx is unchanged per L1; static-source guard at `Shell.architectural-guard.test.tsx` enforces this contract).
- **Heading row** with `dashboard-heading-row` testid, `h-md` (`{spacing.md}` = 32px per DESIGN.md `## Dashboard Workspace Pattern > Pane Geometry`), `<h1>` "Threat Overview" + `<PeriodReadout />` right-aligned. PeriodReadout mirrors the FilterBar's date-range state via `useFilterStore.subscribe + flushSync(forceRender)` (zustand v5 + React 18.3 + happy-dom defers commits past synchronous test assertions; see memory note `pattern_zustand_v5_flushsync_live_mirror`).
- **Actor Network slot** (RESERVED / FUTURE) inserted between WorldMap+AttackHeatmap row and LocationsRanked. Card chrome + title + literal `Planned · no data yet` empty state. NO svg / canvas / synthetic nodes-edges / skeleton chart / sparkline (DESIGN.md G5 #2 + actor-network-graph vocabulary entry — production text-only constraint enforced by 7 negative assertions in T6 RED).
- **DashboardLeftRail**: Sections (Overview / Geo / Motivation / Sectors / Trends / Reports — wired to `id="..."` scroll targets on the matching center bands) + Pinned actors (APT37 / Lazarus, static) + Quick filter (3 unchecked checkboxes, static).
- **DashboardRightRail**: alerts-rail-section + recent-activity-list + drilldown-empty-state. All three reserved-slot text-only (no mock rows).
- **AlertsRailSection** — in-place rewrite of the former AlertsDrawer (T0 inventory confirmed 0 non-dashboard production consumers). Floating drawer pattern removed. Static title + Phase 4 pill + single empty-state line; `data-phase-status="static-shell"` preserved.
- **4 ranked panels migrated** to `RankedRowWithShareBar`: LocationsRanked / SectorBreakdown / ContributorsList / GroupsMiniList. Per-panel testid prefix preserved on the `<li>` wrapper; bar-fill testid passed via the new `barFillTestId` prop (backward-compat — T2 isolated component test continues to assert against the default `ranked-row-bar-fill`). ContributorsList + GroupsMiniList gain a share-bar (DESIGN.md mandates it for all 4 panels). GroupsMiniList preserves its `<Link to="/actors/:id">` wrap.
- **DashboardHero deleted** + summarySharedCache subscriber count 7 → 6.
- **9 i18n keys** added to both `en.json` and `ko.json` per L11; init-test extended with presence + cross-locale parity assertions (catches both presence regressions AND copy-paste bugs).
- **Responsive collapse** at `<1024px`: rails stack vertically with horizontal hairline; left-anchor + right-monitoring access preserved (L6 minimum-mechanism contract; comprehensive responsive redesign deferred).

## Out of scope (deferred — explicit, with target)

- SNA data path / endpoint / zod schemas / Pact interactions / populated `actor-network-graph` rendering → **PR 3**.
- `/reports`, `/incidents`, `/actors`, `/correlation` PT-1 retrofit → separate per-route PRs.
- `/analytics/correlation` route mount + page → correlation FE PR.
- Live alerts / recent activity / selection-driven drilldown → Phase 4.
- Comprehensive responsive redesign for mobile / tablet → separate downstream PR (PR 2 ships minimum collapse contract only).
- `apps/frontend/src/lib/pageClass.ts` typed manifest → correlation-fe T0.
- `DashboardLeftRail` labels (Sections / Pinned / Quick filter group titles + 6 anchor labels + 2 pinned actors + 3 quick-filter checkboxes) — intentional T11 deferral; broader nav-label i18n is a follow-up.
- "All time" empty-date-range fallback in `PeriodReadout` + "Recent activity" title in `DashboardRightRail` — not in L11 9-key list; deferred to a follow-up sweep.

## T13 manual smoke result

Performed via Keycloak `analyst@dev.local` against the local dev triad on 2026-05-06. Structural correctness of the 3-pane retrofit confirmed:

- `/dashboard` — 3-pane composition renders; `DashboardHero` absent; `PeriodReadout` mirrors `FilterBar` date-range; `actor-network-graph-slot` renders title + literal `Planned · no data yet` empty state (no svg / canvas / sparkline); `AlertsRailSection` sits inside `DashboardRightRail` (no floating drawer trigger); left-rail Sections / Pinned (APT37 + Lazarus) / Quick filter all present.
- `/reports`, `/incidents`, `/actors` — no rails, no structural break (L1 sanity).
- KO ↔ EN locale toggle — 9 new keys all switch; intentional hardcoded English on left-rail labels and `PeriodReadout` "All time" / `DashboardRightRail` "Recent activity" titles preserved per Out-of-scope deferrals above.

## Known follow-up — compact KPI / density redesign (PR 2.5 candidate)

The KPI strip's 80px hero typography on `/dashboard` is intentional — it follows the Ferrari L3 spec-cell pattern locked by PR #31 (DESIGN.md `## Spec & Race Surfaces`). PR 2 preserves the existing KPI rendering by design; the visual loudness is a property of the locked spec-cell vocabulary, not a PR 2 regression.

A reviewer-flagged direction (sketch v3 + DashLite-style reference) suggests a compact KPI layout — smaller numbers, delta indicators, optional sparklines, denser card grid — would suit dashboard density better than the spec-cell hero. This requires a DESIGN.md amendment (KPI compact variant scoped to dashboard) + `KPICard` restructure + (optionally) a BE delta/series field. **Out of scope for PR 2's "workspace retrofit" contract.**

Tracked as follow-up — PR 2.5: "Dashboard KPI compact + density redesign". Scope: layout density + delta/sparkline affordance only; dark canvas + Ferrari Rosso scarcity + 0px corners preserved (no light theme).

## §0.1 amendments (plan-vs-impl deviations recorded in commit bodies)

- **AC #5 strict-grep clause** — Plan AC #5's literal "grep DashboardHero across `apps/frontend/src/` returns zero matches" is unachievable: T6 RED test itself asserts hero ABSENCE via `queryByTestId('dashboard-hero')` and names the deprecated component in its test description + docstring. Remaining 5 src/ matches are all regression-guard / historical-comment kind (zero production importer / mount / call). Recorded in T10 commit body.
- **`RankedRowWithShareBar` API extension** — Plan §3 listed the migration but didn't anticipate the per-panel testid preservation requirement. Added optional `barFillTestId?: string` prop (backward-compat). Recorded in T9 r1 fold commit body.
- **`dashboard.alerts.phase4Pill` cross-locale invariant** — "Phase 4" is a project version identifier (the empty-state lines also keep "Phase 4" untranslated, e.g. `Phase 4 — 실시간 알림 미연동`); the pill is intentionally identical in both locales. Init-test extended with a `PHASE_INVARIANT_KEYS` allowlist and an explicit equality assertion. Recorded in T11 r1 fold commit body.

## Defaults applied (Open Questions resolved)

Per plan §8 default policy (no input by depending task → default applies):
- **Q1** Actor Network slot rendering → text-only `Planned · no data yet` empty state (no feature-flag infrastructure needed).
- **Q3** Drilldown empty state → inline JSX inside DashboardRightRail.
- **Q4** AlertsDrawer rename → in-place rewrite (T0 confirmed 0 non-dashboard consumers).
- **Q5** Mobile collapse mechanism → `flex-col lg:flex-row` stack-collapse (cheapest, satisfies L6).
- **Q6** i18n init-test → existing init.test.ts extended with the 9-key presence + parity block.

## Test results

| Test file | Tests | Status |
|:---|:---:|:---:|
| `PeriodReadout.test.tsx` (T1) | 7 | ✓ |
| `RankedRowWithShareBar.test.tsx` (T2) | 10 | ✓ |
| `DashboardLeftRail.test.tsx` (T3) | 8 | ✓ |
| `DashboardRightRail.test.tsx` (T4) | 6 | ✓ |
| `Shell.architectural-guard.test.tsx` (T5) | 4 | ✓ |
| `DashboardPage.workspace.test.tsx` (T6) | 7 | ✓ |
| `LocationsRanked.test.tsx` (post-migration) | 7 | ✓ |
| `SectorBreakdown.test.tsx` (post-migration) | 6 | ✓ |
| `ContributorsList.test.tsx` (post-migration) | 7 | ✓ |
| `GroupsMiniList.test.tsx` (post-migration) | 6 | ✓ |
| `summarySharedCache.test.tsx` (7→6) | 1 | ✓ |
| `i18n/init.test.ts` (9-key contract + parity) | 6 | ✓ |
| `DashboardRightRail.test.tsx` drilldown caption (PR #33 r1 F2) | +1 | ✓ |
| `SectorBreakdown.test.tsx` avatar overflow guard (PR #33 r1 F3) | +1 | ✓ |
| **Full FE suite** | **674** | **✓ all GREEN** |

`pnpm --filter @dprk-cti/frontend run build` exits 0.

## Acceptance criteria status

All 15 plan §7 acceptance criteria green (with §0.1 amendment to AC #5 noted above).

## Cross-AI review trail

| Round | Target | Verdict | Folds |
|:---:|:---|:---|:---|
| T7 r1 | components | PROCEED-WITH-AMENDMENT | F1 HIGH (alerts title i18n regression) + F2 MEDIUM (right-rail w-72→w-80) |
| T7 r2 | r1 fold + further check | PROCEED-WITH-AMENDMENT | F1 MEDIUM (period readout SVG → literal `↑`) + F2 LOW (T4 i18n bootstrap) |
| T7 r3 | r2 fold verify | PROCEED | none |
| T9 r1 | DashboardPage relayout | PROCEED-WITH-AMENDMENT | F1 MEDIUM (4-panel migration) + F2 MEDIUM (responsive collapse) + F3 MEDIUM (anchor target ids) |
| T9 r2 | r1 fold verify | PROCEED | none |
| T10 r1 | hero deletion + summarySharedCache 7→6 | PROCEED | LOW: orphaned hero i18n keys (carried to T11) |
| T11 r1 | i18n keys + wire-up | PROCEED-WITH-AMENDMENT | F1 LOW (phase4Pill parity invariant) + F2 LOW (stale left-rail comment) |
| T11 r2 | r1 fold verify | PROCEED | none |
| PR #33 r1 | full PR diff (post-push DRAFT) | PROCEED-WITH-AMENDMENT | F1 MEDIUM (heading row + center pane spacing drift from DESIGN.md `## Dashboard Workspace Pattern > Pane Geometry`: `p-6` → `px-lg py-md`, `h-12` → `h-md`; test tightened) + F2 LOW (drilldown caption title parity per DESIGN.md line 362) + F3 LOW (sector avatar overflow guard via `sectorAvatarText` helper, parity with sibling panels) |

9 Codex rounds total (8 per-step + 1 PR-level). Transcripts under `.codex-review/dashboard-workspace-retrofit-*.transcript.log` (gitignored).

## Plan reference

`docs/plans/dashboard-workspace-retrofit.md` v1.2 (commit `99e535d`). RED batch: `ac3538b`.
