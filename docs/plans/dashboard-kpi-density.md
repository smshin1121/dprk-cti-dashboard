# PR 2.5 — Dashboard KPI compact + density redesign

**Status:** v1.0 plan (locked-at-draft).
**Base:** `main` @ `d0d0a89` (PR #33 merge).
**Branch:** `feat/dashboard-kpi-density`.
**Successor:** PR 3 — SNA data + actor-network wiring (independent).
**Spec-mode:** FE-only redesign + `DESIGN.md` amendment. NO BE changes in this PR.

## Goal

Replace the current 80px hero KPI typography on `/dashboard` with a compact, denser layout inspired by DashLite-style KPI cards while preserving Ferrari brand discipline (dark canvas, Rosso scarcity, 0px corners). The `## Spec & Race Surfaces` lock from PR #31 stays intact for race-position-cell + non-dashboard spec-cell consumers; this PR introduces a NEW `## Dashboard KPI Compact Variant` section in `DESIGN.md` that is explicitly `/dashboard`-scoped.

## Non-goals (explicit deferrals)

- BE delta / time-series fields → DEFERRED. If client-side computation from existing `reports_by_year` is insufficient resolution, the delta indicator and sparkline ship in disabled / empty-state form. Live data wiring is a follow-up PR.
- Light theme → NOT in scope. Dark canvas + Ferrari Rosso scarcity + 0px corners preserved.
- Other dashboard panels (WorldMap, ATT&CK, ranked panels, trends) — NOT in scope. Density redesign is KPI-strip only.
- `## Spec & Race Surfaces` global lock revision — NOT TOUCHED. New pattern is additive.
- KPIStrip page reuse — confirmed by grep: KPIStrip is consumed by `apps/frontend/src/routes/DashboardPage.tsx:101` only. No other route imports it. Safe to redesign without backward-compat shims.

## Locks (architectural decisions — pre-applied per `gsd-plan-phase` discipline)

| Lock | Decision | Why |
|:---:|:---|:---|
| **L1** | Combined PR (DESIGN.md amendment + impl) — NOT split. | Amendment is small (~30 LoC DESIGN.md addition), `/dashboard`-scoped, no global pattern conflict. Splitting doubles review surface for marginal safety. PR #32 + #33 split was justified by GLOBAL pattern lock; PR 2.5 amendment is local. |
| **L2** | Compact typography target = `text-3xl` (1.875rem ≈ 30px). | DashLite reference uses ~28-32px; sketch v3 used 26px; 30px is a standard Tailwind size that matches DashLite density without surrounding-text conflicts. Drops the 80px hero entirely. |
| **L3** | Aggregate cards (`Top Motivation`, `Top Group`) treatment → compact text rows (name + count + secondary), NOT 80px display. | The Ferrari spec-cell hero pattern is for NUMBERS; rendering short STRINGS (`DataBreach`, `Kimsuky`) at 80px is typography misuse even within the locked pattern. Compact treatment fixes the misuse. |
| **L4** | Delta + sparkline → CLIENT-SIDE computation from `reports_by_year` time series, with graceful empty state when insufficient data. | BE delta/series fields don't exist; computing client-side from existing data avoids cascading BE PR. If precision is too low (e.g. only year-resolution), degrade gracefully — the slot exists and is rendered empty rather than absent. |
| **L5** | Sparkline implementation → tiny inline SVG path (~60px × 24px), no Recharts dependency for KPI cells. | Recharts adds runtime cost and ResizeObserver complexity for a 60px sparkline. Inline `<path d="..." />` from a 12-point series is sufficient. |
| **L6** | KPI strip horizontal layout → `grid grid-cols-3 lg:grid-cols-6 gap-4` (responsive: 3-cell rows on tablet, single 6-cell row on desktop ≥1024px). | Current `flex flex-wrap gap-8 p-6` produces irregular wrapping with 80px values; explicit grid with smaller gap matches DashLite density. |
| **L7** | Card chrome → transparent (no border, no bg) for populated/empty/loading states; small card chrome for error state ONLY. | Preserves the spec-cell editorial-floating-cell behavior already in KPICard. Errors keep small card to read as a status callout. |
| **L8** | Backward-compat → none. KPIStrip and KPICard are restructured in-place; isolated tests get updated. No optional prop or variant flag (memory `pattern_backward_compat_optional_prop_for_consumer_migration` does NOT apply — KPIStrip has 1 consumer, both are owned by this PR). |
| **L9** | i18n → no new keys in this PR. Compact variant uses the same `dashboard.*` keys + the existing literal labels (`Total Reports`, etc.). Scope is layout/typography only. |
| **L10** | Tests → mirror PR #33 RED-first batch pattern. T1-T5 RED → T6 amendment + GREEN → T7 manual smoke → T8 PR open + Codex iteration. |
| **L11** | DESIGN.md amendment scope → add `## Dashboard KPI Compact Variant` section + cross-reference from `## Dashboard Workspace Pattern > Center-Pane Widget Surfaces > kpi-strip`. Existing `## Spec & Race Surfaces` section is NOT touched. |

## §0.1 amendments to PR #33 carryforward (none required)

PR #33's body draft already pre-records this redesign as "Known follow-up — PR 2.5 candidate". This plan IS the follow-up; no §0.1 amendment to PR #33 is needed.

## Tasks

| ID | Task | Deliverable | Depends |
|:---:|:---|:---|:---:|
| **T0** | Inventory: confirm KPIStrip / KPICard consumers + BE schema. | `KPIStrip` consumed by `DashboardPage.tsx:101` only (verified). `KPICard` consumed by `KPIStrip.tsx` only (verified). BE `/dashboard/summary` has NO delta/series fields (verified — schemas in `services/api/src/api/schemas/` do not include delta or by_day). | — |
| **T1** | RED — `KPICard.compact.test.tsx`: assert compact typography (`text-3xl` not `text-[80px]`), delta indicator slot, sparkline slot with empty fallback, transparent card chrome. | new test file with ~10 assertions. | T0 |
| **T2** | RED — extend `KPIStrip.test.tsx`: assert `grid grid-cols-3 lg:grid-cols-6 gap-4` layout pattern, drop the `flex-wrap gap-8` pattern. | extension to existing test (~5 assertions). | T0 |
| **T3** | RED — `KPIStripDelta.test.tsx`: assert client-side delta computation from `reports_by_year` series with graceful empty state when series < 2 entries. | new test file with ~6 assertions. | T0 |
| **T4** | RED — extend `KPICard.test.tsx`: assert aggregate card compact treatment (string values rendered with `text-base` / `text-lg`, NOT `text-[80px]`). | extension to existing tests (~3 assertions). | T0 |
| **T5** | RED — `DashboardKpiAmendment.spec.test.tsx` (or static-source check): grep `DESIGN.md` for the new `## Dashboard KPI Compact Variant` section + verify cross-reference from existing Workspace Pattern section. | new static-source test (~3 assertions). | T0 |
| **T6** | GREEN — DESIGN.md amendment: add `## Dashboard KPI Compact Variant` section with anatomy + token recipe + cross-reference. | DESIGN.md change ~30 LoC. | T1-T5 |
| **T7** | GREEN — `KPICard.tsx` restructure: replace `text-[80px]` with `text-3xl`; add delta indicator + sparkline subcomponents; preserve 4 render states. | KPICard.tsx ~90 LoC restructured. | T6 |
| **T8** | GREEN — `KPIStrip.tsx` restructure: switch from `flex flex-wrap gap-8 p-6` to `grid grid-cols-3 lg:grid-cols-6 gap-4`; compute delta + sparkline data per cell; pass into KPICard. | KPIStrip.tsx ~30 LoC restructured. | T7 |
| **T9** | GREEN — extend `useDashboardSummary` consumers if needed for delta/series computation helpers. | small helper file `apps/frontend/src/features/dashboard/kpiDeltaUtils.ts` if extracted. | T8 |
| **T10** | Run full FE suite + build. | 81 files / 674+ tests GREEN; build exits 0. | T7-T9 |
| **T11** | Manual smoke (user-only): visual confirm on `/dashboard` against DashLite reference + sketch v3. | smoke result in PR body. | T10 |
| **T12** | Push branch + open PR DRAFT. | `gh pr create --draft --body-file docs/plans/dashboard-kpi-density-body.md`. | T11 |
| **T13** | Codex iteration on PR diff. Aim for 3-4 rounds (per `feedback_codex_iteration`); apply `pattern_sweep_class_when_codex_finds_one` to compress rounds. | clean PROCEED. | T12 |
| **T14** | Final mechanical guard + ready-flip + merge. | `gh pr ready` then `gh pr merge --merge --delete-branch` (memory `collab_style`: merge commit, NOT squash). | T13 |

## Risks

| Risk | Severity | Mitigation |
|:---:|:---|:---|
| DESIGN.md amendment conflicts with locked `## Spec & Race Surfaces` (PR #31). | LOW | Amendment is ADDITIVE (new section, not editing existing). `## Spec & Race Surfaces` keeps 80px lock for race-position-cell + non-dashboard spec-cell. Cross-reference makes scope explicit. |
| Client-side delta computation from year-resolution series is too coarse to be meaningful. | MEDIUM | Graceful degradation: if computed delta has insufficient resolution, render empty delta slot. Don't fake numbers. Sparkline same. |
| Sparkline SVG `<path>` rendering under happy-dom for tests. | LOW | Inline `<path>` is just a string DOM node; no canvas, no ResizeObserver. Tests assert presence + structure, not visual rendering. |
| 30px `text-3xl` looks awkward against neighboring `text-xl` heading. | LOW | DashLite reference uses ~30px without conflict. Test asserts the class; visual confirm during T11 manual smoke. |
| Dropping 80px hero on `/dashboard` reads as "PR 2 was wrong" to a reviewer who hasn't followed the trail. | LOW | PR body explicitly says "PR 2 preserved the locked spec-cell pattern; PR 2.5 introduces a /dashboard-scoped compact variant per DESIGN.md amendment". Body cites PR #33 known-follow-up note. |

## Open questions (none — all pre-resolved into Locks)

L1-L11 above absorb every decision. If any lock is wrong, capture the deviation as a §0.1 amendment in the relevant commit body (memory `pattern_plan_vs_impl_section_0_1_amendments`).

## Plan reference

This document is the single source of truth for PR 2.5 implementation. Body draft will live at `docs/plans/dashboard-kpi-density-body.md` (created at T12).

## Memory references

- `pattern_3pr_split_architecture_data` — PR 2.5 is INSERT, not REPLACEMENT, of the 3-PR sequence (PR1 contract / PR2 layout / **PR 2.5 polish** / PR3 data).
- `feedback_close_visible_gaps_before_pr` — closes the visible-gap follow-up flagged during PR #33 manual smoke.
- `feedback_existing_surface_widgets_before_new_endpoints` — polish existing surface before opening new BE.
- `feedback_codex_iteration` — 3-6 rounds typical for substantive PRs; aim to compress with `pattern_sweep_class_when_codex_finds_one`.
- `pattern_tdd_10step_inventory_shape_before_contract` — T0 inventory is NOT RED; T1-T5 are RED before any GREEN.
- `pattern_factory_wiring_guard` (not applicable here — no factories).
- `collab_style` — merge commit (NOT squash), 사용자 승인 후 merge.
