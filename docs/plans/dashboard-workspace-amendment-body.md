# PR — DESIGN.md Amendment · Dashboard Workspace Pattern

**PR 1 of 3-PR Option-C sequence locked 2026-05-04.** Predecessor PR #31 merged on `cf3c2ed`. Successor PR 2 = workspace retrofit implementation; successor PR 3 = SNA data + wiring.

## What

Amend `DESIGN.md` with a dashboard-specific workspace pattern that brings `/dashboard` under the analyst-workspace 3-pane discipline established by PT-1..PT-7 in PR #31, **without touching any token / color / radius / type / motion specification**.

Five edits ship in this PR:

1. **Mapping table (line 334)** — `/dashboard` page-class flips from `editorial-page` to `analyst-workspace`. Notes column rewritten to point at the new section + the new Don't bullet.
2. **Definitions table (lines 320, 322)** — `editorial-page` row's Examples cell loses `dashboard` and gains a "no currently-mapped routes — reserved for future surfaces" note. `analyst-workspace` row's Examples cell gains `dashboard` with a Chrome footnote pointing at the variant.
3. **NEW section `## Dashboard Workspace Pattern`** (between PT-7 and `## Page Classes`) — ~120 LoC. Documents the 3-pane composition specific to `/dashboard` (which differs from PT-1 in left-rail content + right-rail composition), the heading-row + period-readout pattern, and 4 new component vocabulary entries.
4. **4 new component vocabulary entries** (within the new section):
   - `period-readout` — read-only display of the active date range, paired with the page `<h1>` in the heading row. FilterBar at viewport top remains the single editable source.
   - `ranked-row-with-share-bar` — row variant for the four ranked panels (LocationsRanked, SectorBreakdown, ContributorsList, GroupsMiniList). Share-bar fill = `{colors.body}` only; never Rosso, never a chart palette.
   - `alerts-rail-section` — right-rail Phase 4 static shell. Replaces the floating `AlertsDrawer` trigger on `/dashboard`. Title + Phase-4 pill + single empty-state line; no mock rows in production.
   - `actor-network-graph` — full-width center-pane card slot for an SNA co-occurrence visualization. **RESERVED / FUTURE**: contract registers position + title + node-kind vocabulary; data path is undefined here and is the deliverable of PR 3.
5. **3 new Don'ts** (appended to `### Don't`):
   - Don't render an editorial dashboard hero on `/dashboard` (DashboardHero deprecated).
   - Don't render mock SVG / fabricated data in production for reserved/future slots (`actor-network-graph` enforcement).
   - Don't make `period-readout` editable (FilterBar is the single editable source).

## Why

Sketch v3 (gitignored throwaway at `tmp/sketches/dashboard-workspace-v1.html`) settled the layout decision after a directive that the current `/dashboard` editorial composition does not match the user's mental model. The user pointed at DashLite messages.html as a reference for layout grammar (3-pane workspace with section-anchor left rail + monitoring shell right rail). The amendment formalizes the composition as a contract before any code lands.

**Sequenced before implementation** because:

- PR 2 (workspace retrofit) needs a contract entry to point at when removing `DashboardHero` + `summarySharedCache.test.tsx` updates land.
- PR 3 (SNA data) needs the slot reserved + the data-path deferral wording in the contract before BE schema decisions.
- Mixing layout decisions with data-modeling decisions in one PR creates churn under cross-AI review.

## Doc-only diff guarantee

This PR touches `DESIGN.md` + `docs/plans/dashboard-workspace-amendment.md` + this body file. No code, no tests, no migrations, no environment changes, no feature flags.

The throwaway sketch at `tmp/sketches/dashboard-workspace-v1.html` and the corresponding `.gitignore` change for `tmp/` are **NOT included in this PR** (sketch lifecycle = revert at cleanup; not part of any PR).

## Locked decisions in this amendment

- **A1** `/dashboard` → `analyst-workspace` (line 334).
- **A2** New section as top-level H2 between PT-7 and `## Page Classes` (sibling to `## Layout Patterns`).
- **A3-A5** Pane geometry: left rail 240px section anchors / center pane flex (existing 14-widget topology preserved + reserved Actor Network slot inserted) / right rail 320px alerts shell + recent + drilldown.
- **A6-A9** 4 new component vocabulary entries documented in the new section.
- **A10-A11** 3 new Don'ts (hero forbidden / reserved-slot mock-data forbidden / period-readout editability forbidden).
- **A12** `editorial-page` class definition stays in place with explicit "no mapped routes — reserved for future" note.
- **A13** Doc-only diff; sketch + gitignore intentionally excluded.
- **A14** PR #31 cadence reused (≈ 0.5 dev-day, 2 Codex rounds + 2 reviewer rounds).

## What this PR does NOT change

- Any visible UI on `/dashboard` (PR 2's job).
- Any token / color / radius / typography / motion spec.
- Any other route's page-class mapping.
- The PT-1..PT-7 layout patterns (untouched).
- The `## Components` section (4 new entries are colocated in the new `## Dashboard Workspace Pattern` section, not scattered into existing component subsections).
- Any backend / API.

## Defaults applied (Open Questions resolved)

Per plan §8:

- **Q1** Section placement = top-level H2 after PT-7. Applied.
- **Q2** `editorial-page` class = kept with "no mapped routes" note. Applied.
- **Q3** Explicit Don't for `period-readout` editability. Applied.
- **Q4** `alerts-rail-section` = title + Phase-4 pill + empty-state line; no mock rows. Applied.
- **Q5** SNA node-kind vocabulary listed (actor / tool / sector) but flagged PR-3-mutable. Applied.

## Implementation hand-off (PR 2 owns these, NOT this PR)

The following are flagged in the amendment as risks / cross-references but are NOT addressed by this PR:

- `DashboardHero.tsx` + `DashboardHero.test.tsx` removal.
- `summarySharedCache.test.tsx` subscriber-count update (6 → 5 if hero leaves; verify count at PR 2 implementation time).
- `Shell.tsx` left/right rail slot addition + `shell-topnav` / `shell-main` / new rail testid migration.
- `DashboardPage.tsx` 3-pane relayout.
- `AlertsDrawer.tsx` reposition from floating drawer to permanent right-rail section.
- `actor-network-graph` slot rendered as either hidden OR `Planned · no data yet` empty state. **NEVER mock graph in production.**

## Review cadence

Per `pattern_design_contract_iteration_cadence` (PR #31 baseline):

- **Round 1** — Codex pre-review on proposal v1 at `docs/proposals/dashboard-workspace-amendment-draft.md`. CRITICAL/HIGH folded into proposal v1.x.
- **Round 2** — Self-review on canonical post-edit + Codex round 1 on canonical. CRITICAL/HIGH/MEDIUM folded as fix commit on the branch.
- **Final** — Reviewer + Codex agree PROCEED-* with no unresolved CRITICAL/HIGH; flip draft → ready; merge via merge commit (NOT squash) per `collab_style.md`.

Estimated ≈ 0.5 dev-day from D1 to D9.

## Test plan

This PR is doc-only. CI runs:

- Markdown lint (existing).
- Link-check (existing).
- Frontend / backend test suites (no expected diff — they should pass green identical to `cf3c2ed` baseline).

Manual smoke at D8: read `DESIGN.md` head-to-toe in the diff view, verify no broken cross-refs, verify the new section's named patterns (PT-5 stripe / PT-6 inline rounding) still resolve to the existing PT-5 / PT-6 sections in the same doc.

## Rollback

`git revert <merge-commit>` removes the section, restores the mapping cell, removes the vocabulary entries and Don'ts. No tests, no migrations, no env changes, no feature flags.

If revert lands AFTER PR 2 has merged, PR 2's implementation references the now-reverted contract. PR 2 sequencing is therefore strictly downstream of this PR's merge state — confirm via `git log` that PR 2 starts work only after this PR is on `main`.
