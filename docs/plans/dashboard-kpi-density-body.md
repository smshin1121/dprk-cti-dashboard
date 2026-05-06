# PR 2.5 — Dashboard KPI compact + density redesign

Implements `docs/plans/dashboard-kpi-density.md` v1.0 (commit `0397458`). Closes the visible-gap follow-up flagged during PR #33 manual smoke + documented as "Known follow-up — PR 2.5 candidate" in [PR #33 body](https://github.com/smshin1121/dprk-cti-dashboard/pull/33).

**FE-only PR. No BE changes.** All delta + sparkline computation happens client-side from existing `useDashboardSummary().reports_by_year`. PR #31 `## Spec & Race Surfaces` 80px hero lock is **NOT** revised — non-dashboard spec-cell + race-position-cell consumers continue to use that token.

## Scope

- **DESIGN.md amendment** (additive, +25 LoC): adds `## Dashboard KPI Compact Variant` section after `## Dashboard Workspace Pattern`. Cross-references back to `## Spec & Race Surfaces` to make the additive scope explicit, and forward from the Workspace Pattern section so a reader scanning the dashboard contract is pointed at the compact variant.
- **`KPICard.tsx` restructure**:
  - Compact typography: `text-3xl` (~30px) for scalar values, `text-lg` for aggregate strings (`Top Motivation` / `Top Group` primary label). Drops `text-[80px]`. Top Year stays `text-3xl` (numeric-shaped per `isAggregateString` digit check).
  - Optional `delta` prop with direction-derived color (`status-ok` / `status-warn`).
  - Optional `sparkline` prop rendering inline 60×24 SVG path. Single 1px stroke at `text-ink-subtle`, no fill, no axes, no Recharts dependency.
  - Reserved-slot discipline: when `delta` is null OR `sparkline` has < 2 points, the slot is **omitted entirely** (no fake numbers, no empty visualization).
- **`KPIStrip.tsx` restructure**:
  - Layout: `grid grid-cols-3 gap-4 lg:grid-cols-6` (was `flex flex-wrap gap-8 p-6`). Single 6-cell row at desktop, 3-cell rows on tablet.
  - Total Reports card receives `computeYoyDelta(reports_by_year)` + `extractSparklineSeries(reports_by_year)`. Other 5 cards pass `delta` / `sparkline` undefined → slots collapse.
  - When `reports_by_year` has < 2 entries, even the Total Reports card omits delta + sparkline (graceful empty).
- **`kpiDeltaUtils.ts` (NEW)**: pure-function helpers `computeYoyDelta`, `extractSparklineSeries`, `buildSparklinePath`. Picks latest year by VALUE (not array tail), handles divide-by-zero predecessor, sorts series ascending.

## Out of scope (deferred — explicit, with target)

- BE delta / time-series fields → DEFERRED. Current `/dashboard/summary` exposes no `delta` / `by_day` / `series` fields; PR 2.5 ships compact variant on `reports_by_year` YoY only. Future BE PR may add per-card series fields and unlock delta/sparkline on the other 5 cards.
- Light theme → NOT in scope. Dark canvas + Ferrari Rosso scarcity + 0px corners preserved.
- Other dashboard panels (WorldMap, ATT&CK, ranked panels, trends) — NOT in scope. Density redesign is KPI-strip only.
- `## Spec & Race Surfaces` global lock revision → NOT TOUCHED. Compact variant is additive.
- Backward-compat shim — KPIStrip / KPICard are `/dashboard`-only (verified by grep at T0 inventory); no other consumers to migrate.

## Plan locks (L1-L11)

All 11 architectural decisions pre-applied at plan v1.0 lock per `gsd-plan-phase` discipline; no open questions. See `docs/plans/dashboard-kpi-density.md` for the full table.

## §0.1 amendments

None expected at this commit. Any plan-vs-impl deviation surfaced during Codex review will be recorded as a §0.1 amendment in the relevant fold commit body per `pattern_plan_vs_impl_section_0_1_amendments`.

## Test results

| Test file | Tests | Status |
|:---|:---:|:---:|
| `KPICard.compact.test.tsx` (T1, NEW) | 12 | ✓ |
| `KPIStrip.test.tsx` (T2, +4 tests) | 10 | ✓ |
| `kpiDeltaUtils.test.ts` (T3, NEW) | 11 | ✓ |
| `KPICard.test.tsx` (T4, 1 update) | 8 | ✓ |
| `dashboardKpiAmendment.spec.test.ts` (T5, NEW) | 5 | ✓ |
| **Full FE suite** | **706** | **✓ all GREEN** |

Was 674 (PR #33 baseline) → +32 tests / +3 test files. `pnpm --filter @dprk-cti/frontend run build` exits 0.

## Acceptance criteria

All 14 plan tasks (T0 inventory + T1-T5 RED + T6-T9 GREEN + T10 verification) green. T11 manual smoke pending (user action). T12-T14 = this PR open + Codex iteration + ready+merge.

## Plan reference

`docs/plans/dashboard-kpi-density.md` v1.0 (commit `0397458`). RED batch: subsequent commits 0397458 → ... follow standard PR #33 atomic-per-step convention.
