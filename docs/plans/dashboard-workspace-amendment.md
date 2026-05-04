# Plan — DESIGN.md Amendment · Dashboard Workspace Pattern

**Phase:** Brand-contract minor revision on top of v2 (PR #31 merged 2026-05-04 AM as `cf3c2ed`).
**Status:** Draft 2026-05-04. Awaits user PROCEED on this plan before writing the canonical DESIGN.md edit.
**PR number:** Not reserved. Confirm via `gh pr list` immediately before opening; current main HEAD is `cf3c2ed`, 0 OPEN PRs at draft time.
**Predecessors:** PR #31 (DESIGN.md v2 Layout Patterns + Page-Class Taxonomy; merged 2026-05-04 AM as `cf3c2ed`).
**Successors (per Option-C 3-PR sequence locked 2026-05-04):**
- **PR 2 — Dashboard workspace retrofit (implementation).** Branch `feat/dashboard-workspace-retrofit`. Adds left/right rail slots to `Shell.tsx` for analyst-workspace pages, relays `DashboardPage.tsx` into the 3-pane structure, removes `DashboardHero` + its test, updates `summarySharedCache.test.tsx`, ships Period readout, ships `ranked-row-with-share-bar` component on the four ranked panels, repositions `AlertsDrawer` as a right-rail static section, renders `actor-network-graph` slot as **"Planned · no data yet"** placeholder OR hides it — never mock.
- **PR 3 — SNA data + wiring.** Branch `feat/actor-network-data`. Picks data path (new endpoint vs. summary field augmentation; deferred decision), ships zod schemas + Pact interactions + populated graph component.

**Source artifact:** `tmp/sketches/dashboard-workspace-v1.html` v3 (gitignored throwaway sketch). Reviewed 2026-05-04 with 3 findings folded (title/v3 sync, SNA reserved-slot wording, gitignore lifecycle decision = revert at sketch cleanup, not in any PR).

---

## 1. Goal

Amend `DESIGN.md` (commit `cf3c2ed`) with a **dashboard-specific workspace pattern** that brings `/dashboard` under the analyst-workspace 3-pane discipline established by PT-1..PT-7, **without changing any token / color / radius / type / motion specification**. The contract is documentation-only — no runtime mechanism, no component code, no page migration.

Specifically:
- Reclassify `/dashboard` from `editorial-page` to `analyst-workspace`.
- Document the 3-pane composition that the dashboard uses (this differs from PT-1's three-pane analyst pattern because `/dashboard` has no record-list anchor — left rail is section anchors, center is widget grid, right rail is alerts shell + recent + drilldown).
- Register four new component vocabulary entries used by the dashboard workspace pattern.
- Deprecate the editorial dashboard hero (`DashboardHero`).
- Reserve a future SNA (Social Network Analysis) widget slot in the contract — slot title + position only, **no data path defined here**; data path picked in PR 3.

**Non-goal (out of scope for this PR):**
- Implementation work — left/right rail slots in `Shell.tsx`, dashboard relayout, hero removal, share-bar component, AlertsDrawer reposition, SNA placeholder rendering. All move to **PR 2**.
- Any backend / API change. The amendment is FE contract only; no schema / endpoint additions.
- SNA data model — endpoint shape, edge semantics, refresh cadence. Deferred to **PR 3**. The slot exists in the contract only.
- New design tokens. Every value referenced in this amendment already exists in v1/v2.
- `/reports`, `/incidents`, `/actors` retrofit. The PT-1 three-pane analyst-workspace pattern from PR #31 still maps to those routes; their retrofit remains a separate downstream PR (per DESIGN.md line 337-339 deferral note).
- Removing the `editorial-page` class. The class definition stays (forward-compat for marketing / brand-spec surfaces); it just loses `/dashboard` as its current representative.

---

## 2. Locked Decisions

These mirror the sketch v3 review and the user's Option-C sequencing decision (2026-05-04). Each row is the form the canonical DESIGN.md edit will take.

| ID | Decision | Rationale |
|:---:|:---|:---|
| **A1** | `/dashboard` page-class: `editorial-page` → `analyst-workspace`. Mapping table at DESIGN.md line 334 updated. | Layout sketch v3 settled the 3-pane composition with section-anchor left rail + alerts/recent/drilldown right rail. Editorial-page class definition (no PT-1 chrome, hero required) directly contradicts the new composition. |
| **A2** | New section heading `## Dashboard Workspace Pattern` inserted after PT-7 (or as a `### PT-1.1 Dashboard variant` under PT-1, depending on canonical-edit reviewer preference). | Dashboard workspace differs from PT-1 in left-rail content (anchors, not record list) and right-rail composition (alerts shell + recent + drilldown, not detail rail). It needs an explicit pattern entry, not a PT-1 footnote. |
| **A3** | Left-rail composition: section anchors (Overview / Geo / Motivation / Sectors / Trends / Reports — anchor-link scroll within the page) + Pinned actors + Quick filter. Width 240px. PT-5 1px Rosso left-edge stripe on active row. | Sketch v3 established. Dashboard has no "select a row → load detail" semantics, so left rail is navigational, not record-list. Anchors stay in-page; do NOT navigate. |
| **A4** | Center pane composition preserves all 14 existing widgets in current grid (KPIStrip → WorldMap+AttackHeatmap (2:1) → **Actor Network slot (NEW, reserved)** → LocationsRanked (full) → MotivationDonut+YearBar (1:1) → SectorBreakdown+ContributorsList (1:1) → TrendChart+GroupsMiniList (1:1) → MotivationStackedArea+SectorStackedArea (1:1) → ReportFeed (full)). Width = flex between rails. | Existing widget topology unchanged minimizes implementation PR scope and prevents test churn beyond the hero removal. |
| **A5** | Right-rail composition: `alerts-rail-section` (Phase 4 static shell, repositioned from current floating drawer) + `recent-activity-list` + `drilldown-empty-state`. Width 320px. | Sketch v3 established. Repositioning `AlertsDrawer` from floating drawer to right-rail permanent section means the FE visual surface gains permanent visibility for the alerts shell, but live data wiring stays Phase 4 (out of scope for both PR 2 and PR 3). |
| **A6** | New component vocabulary entry: `period-readout`. Position: heading-row right side (paired with page `<h1>`). Behavior: read-only mirror of the global FilterBar's date-range state — display only, never an input. Value comes from the same `useFilterStore` + `useFilterUrlSync` slots that drive FilterBar; the FilterBar at the top of the viewport remains the single editable source of truth. | Period (date range) is global filter state shared across `/dashboard`, `/reports`, `/incidents`, `/actors`. Duplicating the input in the dashboard heading would create a two-surface contract for one URL slot. The readout makes the time-window association strong without the duplication risk. |
| **A7** | New component vocabulary entry: `ranked-row-with-share-bar`. Applies to the four ranked list-card panels (`LocationsRanked`, `SectorBreakdown`, `ContributorsList`, `GroupsMiniList`). Row anatomy: avatar + name+sub + horizontal share-bar + value+%. Bar width = relative share within the panel (top item = 100%). Bar fill = `body` token (#969696); no Rosso, no chart-color palette. | Sketch v3 established. The four panels currently render bare names with absolute counts — a parity gap relative to typical analytics dashboards. Single muted bar color preserves Ferrari accent scarcity. |
| **A8** | New component vocabulary entry: `alerts-rail-section`. Static shell, no live data wiring in this amendment, in PR 2, or in PR 3. Currently flagged as Phase 4. The `AlertsDrawer` floating-trigger pattern is replaced by a permanent right-rail section in the dashboard workspace. | Repositioning the alerts surface is part of the workspace retrofit. Live data wiring waits for Phase 4. The contract states the position; the implementation PR ships the empty shell. |
| **A9** | New component vocabulary entry: `actor-network-graph`. Position: full-width center-pane card between WorldMap+AttackHeatmap row and LocationsRanked. **RESERVED / FUTURE SLOT.** Contract registers card position, title (`Actor network · co-occurrence`), node-shape vocabulary (actor / tool / sector node-kinds with stroke-style differentiation), and degree-centrality node sizing. **Data path (BE endpoint shape, edge semantics, refresh cadence) is intentionally undefined here** and is the deliverable of PR 3. | Per Option-C sequencing locked 2026-05-04: layout decisions stay separate from data-model decisions. PR 1 reserves the slot; PR 2 ships an explicit "Planned · no data yet" placeholder OR hides the card; PR 3 picks the data path and populates it. |
| **A10** | Don'ts addition: "Don't reintroduce an editorial dashboard hero on `/dashboard`. The `DashboardHero` component is deprecated; the implementation PR (PR 2) removes the file and its test." | Hero conflicts with analyst-workspace density (PT-4 implication) and with the workspace heading-row composition (heading + period-readout). |
| **A11** | Don'ts addition: "Don't render mock SVG / fabricated data in production for reserved/future slots like `actor-network-graph`. Acceptable production states until the data PR ships are: (a) hide the card entirely, or (b) render a card carrying its title + an explicit `Planned · no data yet` empty state placeholder." | Sketch v3 finding #1 (2026-05-04 review): a mock graph in production code reads as live to users and creates a credibility hazard. The sketch's mock SVG is gitignored / throwaway only. |
| **A12** | `editorial-page` class definition stays in place at DESIGN.md line 320 (and the page-class taxonomy section at line 318), but the mapping table loses `/dashboard` as its representative route. The class is preserved for forward-compat (marketing / brand-spec surfaces); the table currently has zero mapped routes for editorial-page after this amendment. A short note clarifies "currently no mapped routes — reserved for future surfaces." | Removing the class entirely would create churn if a marketing page lands later. Preservation cost = a 1-line note. |
| **A13** | Branch name `feat/dashboard-workspace-amendment`, base = `main` directly. Doc-only PR — no `tmp/` / `.gitignore` changes carried in this PR (sketch lifecycle = (i) revert at sketch cleanup; not in any PR). | Doc-only discipline matches PR #31 cadence (4-round Codex/reviewer). Mixing the gitignore line into this PR would muddy the doc-only diff. |
| **A14** | Iteration cadence: PR #31 pattern (`pattern_design_contract_iteration_cadence`) — 2 Codex rounds (pre-review on proposal v1, round 1 on canonical post-edit) + 2 reviewer rounds. Roughly half a dev-day. | Smaller scope than PR #31 (single page-class change + 4 vocabulary entries) — same cadence applies. |

---

## 3. Scope

### In scope (this amendment PR)

- **`DESIGN.md` edits**, additive on top of `cf3c2ed`:
  - **Mapping table (line 334)** — change `/dashboard` row's class column from `editorial-page` to `analyst-workspace`; update RHS commentary to reference the new Dashboard Workspace Pattern section.
  - **Page-class definitions table (line 318-325)** — `analyst-workspace` row example list gains `dashboard`; `editorial-page` row gains a "currently no mapped routes" note.
  - **NEW section** `## Dashboard Workspace Pattern` (or `### PT-1.1 Dashboard variant` — final placement during canonical edit). ~30-50 lines covering: 3-pane composition, left-rail anchor list, center widget topology + Actor Network reserved slot, right-rail composition, heading-row + period-readout pattern.
  - **NEW component vocabulary entries** for `period-readout`, `ranked-row-with-share-bar`, `alerts-rail-section`, `actor-network-graph` (4 entries, ~40-60 lines combined).
  - **`## Do's and Don'ts > Don't` extensions** — A10 + A11 (2 new bullets, ~6-10 lines).
- **Plan doc** — this file, committed under `docs/plans/dashboard-workspace-amendment.md`. Renames to `pr{N}-dashboard-workspace-amendment.md` only after `gh pr list` confirms the assigned number.
- **PR-body draft** — staged at `docs/plans/dashboard-workspace-amendment-body.md` (per memory `plan_doc_convention`); same rename rule.

### Out of scope (deferred — explicit, with target PR)

- All implementation — left/right rail slots in Shell, DashboardPage relayout, DashboardHero removal, share-bar component, AlertsDrawer reposition, SNA placeholder rendering → **PR 2**.
- SNA data path / endpoint / Pact / wiring → **PR 3**.
- `/reports`, `/incidents`, `/actors` PT-1 retrofit → separate per-route follow-ups (DESIGN.md line 337-339 deferral note unchanged by this amendment).
- New design tokens / motion / animation specs.
- Sketch lifecycle — `tmp/` / `.gitignore` revert is local-only project hygiene; not carried in any PR.

---

## 4. Task Breakdown

| # | Task | Depends on | Est. | Exit criteria |
|:---:|:---|:---|:---:|:---|
| **D1** | Author proposal draft at `docs/proposals/dashboard-workspace-amendment-draft.md` (gitignored, internal review material). Mirrors the canonical DESIGN.md edit at the markdown level so reviewer + Codex pre-review can read it without committing to `DESIGN.md` directly. | — | 0.25d | Draft contains: section text for Dashboard Workspace Pattern + 4 vocabulary entries + 2 Don'ts + mapping/definition table diff. |
| **D2** | Reviewer round 1 on D1 proposal — internal contradiction sweep (does the new pattern conflict with PT-1..PT-7? does the Period readout duplicate FilterBar input? does the SNA slot rule collide with PT-1's three-pane?). | D1 | 0.1d | Findings folded into proposal draft v1.1. |
| **D3** | Codex pre-review on the proposal — `node codex.js exec ...` with prompt at `.codex-review/dashboard-workspace-amendment-prereview-prompt.md`. Look for cross-file router/contract drift (does DESIGN.md still match `apps/frontend/src/routes/router.tsx`? does the SNA reserved-slot wording leave loopholes for production mock?). | D2 | 0.2d | Verdict: PROCEED-* on the proposal; CRITICAL/HIGH findings folded; MEDIUMs folded or escalated to amendment risks. |
| **D4** | Apply canonical edit to `DESIGN.md`. Single commit `feat(design): dashboard workspace pattern + reclassification` with the 5 change groups (mapping, definitions, new section, vocabulary, Don'ts). | D3 | 0.1d | `DESIGN.md` diff matches proposal vN.x; line counts: ≤ ~120 LoC added, mapping table 1 row changed in place, definitions table 1 row appended note. |
| **D5** | Reviewer round 2 on canonical DESIGN.md — final contradiction sweep + line-by-line line-number sanity (after the edit, do internal cross-references like "PT-5 1px Rosso stripe" still target the right line / section)? | D4 | 0.1d | Findings folded as small fix commit on the branch. |
| **D6** | Codex round 1 on canonical DESIGN.md. Same Codex CLI invocation, prompt at `.codex-review/dashboard-workspace-amendment-r1-prompt.md`. | D5 | 0.2d | Verdict: PROCEED-* on canonical; CRITICAL/HIGH/MEDIUM findings folded as fix commit on the branch (per `feedback_codex_iteration`). |
| **D7** | Open PR via `gh pr create --draft --base main --head feat/dashboard-workspace-amendment`. Body sourced from `docs/plans/dashboard-workspace-amendment-body.md`. | D6 | 0.05d | PR opened DRAFT, MERGEABLE / CLEAN, CI green on docs lint. |
| **D8** | Final manual smoke — read DESIGN.md head-to-toe in the diff view, verify no broken cross-refs / no stale "current" claims / no PT-1 vs Dashboard Workspace ambiguity. | D7 | 0.05d | No findings; flip draft → ready (`gh pr ready`). |
| **D9** | Merge via `--merge --delete-branch` per `collab_style.md`. | D8 + reviewer approval | 0.05d | PR merged into `main` as a merge commit; remote branch auto-pruned; origin returns to `main`-only state. |

**Estimated dev-time:** ≈ **0.5 dev-day** (consistent with PR #31 cadence per `pattern_design_contract_iteration_cadence`).

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|:---|:---:|:---|
| `/dashboard` page-class change leaves `editorial-page` with zero mapped routes; reviewers may interpret this as the class being dead. | Med | A12 keeps the class definition with an explicit "currently no mapped routes — reserved for future surfaces" note. |
| The new Dashboard Workspace Pattern reads as a third three-pane variant alongside PT-1; reviewers may demand reconciliation into PT-1. | Med | The pattern explicitly cross-references PT-1 and lists the differences (left rail = anchors not record list; right rail = alerts shell not detail rail). Final canonical placement (top-level section vs. PT-1 sub-pattern) decided in D4 based on D2/D3 reviewer feedback. |
| `period-readout` reads as duplicating FilterBar input; readers may try to make it editable. | Med | A6 wording is explicit: "read-only mirror." Don'ts entry can reinforce: "Don't make `period-readout` editable. The global FilterBar at viewport top is the single editable source for date-range state." (Add as A11.5 if D2/D3 reviewers push on this.) |
| `actor-network-graph` reserved-slot wording is interpreted permissively; PR 2 implementation team renders a mock graph anyway. | High | A11 Don'ts entry forbids mock SVG / fabricated data in production for reserved/future slots, and explicitly enumerates the two acceptable states (hide OR `Planned · no data yet` placeholder). PR 2's plan doc inherits this constraint as a hard AC item. |
| `DashboardHero` deprecation in this contract triggers test-removal work in PR 2 that grows that PR's scope. | Low | `DashboardHero.test.tsx` removal + `summarySharedCache.test.tsx` subscriber-count update are pre-known and fit the PR 2 scope. The amendment risk list flags them; PR 2 plan budgets the work. |
| Shell.tsx left/right rail addition is global structural change; testid-keyed tests across other pages may regress. | Med | This is a PR 2 risk, not amendment risk. The amendment notes it; PR 2 plan budgets testid migration work. |
| Reviewer rounds catch a stale router phrasing (Codex caught `/search` not mounted on PR #31's v2.1 → HIGH finding). | Med | D2 reviewer round 1 grep `apps/frontend/src/routes/router.tsx` for the routes named in this amendment; D3 Codex pre-review same; cross-file consistency at proposal stage. |
| Cadence overruns (PR #31 was 4 rounds; this amendment may also need 3-4). | Low | Plan budgets D1-D9 = ~0.5 dev-day. If a round 2 surfaces new findings, fold and continue; per `feedback_codex_iteration`, Codex findings are rarely false positives. |
| Post-merge, the sketch (`tmp/sketches/dashboard-workspace-v1.html`) and the corresponding `.gitignore` line linger. | Low | Sketch lifecycle decision (i) — once amendment merges, run `rm -rf tmp/` + `git checkout -- .gitignore` locally. Not part of any PR. |

---

## 6. Rollback Plan

This PR is **purely additive on the documentation side**:

- 1 mapping table cell change (`/dashboard` row, class column).
- 1 mapping table cell augmentation (RHS commentary).
- 1 definitions table augmentation (`editorial-page` row gains a note).
- 1 new section (~30-50 LoC).
- 4 new component vocabulary entries (~40-60 LoC).
- 2 new Don'ts bullets.

Revert path: `git revert <merge-commit>` removes the section, restores the mapping cell, removes the vocabulary entries and Don'ts. No tests, no migrations, no environment-variable changes, no feature flags.

If revert lands AFTER PR 2 merges, PR 2's implementation references the now-reverted contract — but PR 2 is on its own branch sequenced after this PR; if this revert is anticipated, sequence accordingly.

---

## 7. Acceptance Criteria

This PR is mergeable only when **all** of the following hold:

1. `DESIGN.md` diff covers all 5 change groups: mapping update, definitions augmentation, new pattern section, 4 component vocabulary entries, 2 Don'ts additions.
2. Mapping table at line 334 contains exactly one row change: `/dashboard` class column flips from `editorial-page` to `analyst-workspace`. RHS commentary updated.
3. Definitions table at line 318-325 has `editorial-page` augmented with the "currently no mapped routes" note; `analyst-workspace` row example list gains `dashboard`.
4. New section explicitly says `actor-network-graph` is RESERVED / FUTURE; data path is undefined here. The two acceptable production states (hide OR `Planned · no data yet` placeholder) are enumerated.
5. New section explicitly says `period-readout` is read-only; FilterBar is the single editable source for date-range state.
6. The 4 new component vocabulary entries each carry: name, position, anatomy, token bindings, accent budget (none beyond v1/v2), Don'ts cross-reference where applicable.
7. The 2 Don'ts additions: editorial dashboard hero forbidden; reserved-slot mock data forbidden.
8. Plan doc + PR body draft present at `docs/plans/dashboard-workspace-amendment.md` and `docs/plans/dashboard-workspace-amendment-body.md` (or their `pr{N}-*` renamed forms post-opening).
9. Codex pre-review and round 1 each return PROCEED-* with all CRITICAL/HIGH findings folded; MEDIUMs typically folded.
10. `gh pr view --json mergeable,mergeStateStatus` returns `MERGEABLE` / `CLEAN` (or `BEHIND` resolved by rebase).
11. CI green on whatever doc lints run for `.md` changes (markdown-lint, link check, etc.).
12. PR diff is doc-only — no code files touched, no `tmp/` leakage, no `.gitignore` change, no test file change.

---

## 8. Open Questions

- **Q1 — Section placement.** New `## Dashboard Workspace Pattern` as a top-level H2 after PT-7, OR as a `### PT-1.1 Dashboard variant` sub-pattern under PT-1? Recommendation: top-level H2 — the dashboard workspace is materially different from PT-1 (anchor left rail vs. record-list left rail; alerts/recent/drilldown right rail vs. detail rail) and demoting it to a PT-1 variant under-states the difference. **Default if no input by D4: top-level H2 after PT-7.**
- **Q2 — Editorial-page class survival.** Keep the class defined (current proposal A12) with the "no mapped routes" note, OR remove the class entirely from DESIGN.md? Recommendation: keep — forward-compat for marketing / brand-spec surfaces is a real possibility per the v1 examples list. **Default if no input by D4: keep with note.**
- **Q3 — `period-readout` editability hardening.** Add an explicit Don'ts bullet ("Don't make `period-readout` editable. FilterBar is the single editable source.") OR rely on A6 wording alone? Recommendation: add the Don'ts bullet — three- to six-month-out implementation team may not read A6 with the same care; an explicit Don't kills the ambiguity. **Default if no input by D4: add the Don't.**
- **Q4 — `alerts-rail-section` Phase 4 coupling.** The amendment registers the position only; live data wiring stays Phase 4. Should the contract specify a no-data presentation (skeleton vs. empty-state)? Recommendation: empty-state with title visible, body says "Phase 4 — placeholder". Same pattern as `actor-network-graph`'s "Planned · no data yet". **Default if no input by D4: empty-state with title + Phase-4 placeholder body.**
- **Q5 — SNA node-kind vocabulary depth.** Sketch v3 used 3 kinds (actor / tool / sector). Should the contract lock this taxonomy here, or leave it open for PR 3 to decide based on real data? Recommendation: leave open — the data-model decision in PR 3 may surface kinds the sketch didn't anticipate (campaign / IOC family / target type). **Default if no input by D4: contract lists "actor / tool / sector" as the sketch baseline but flags the list as PR-3-mutable.**

These are **defaults**, not blockers — if the user has no opinion, D4 proceeds with the defaults and the open questions get folded into the PR body's "Defaults applied" section.

---

## 9. Change Log

- **2026-05-04 (draft)** — Plan authored after sketch v3 review (3 findings folded: title v3 sync, SNA reserved-slot wording, gitignore lifecycle decision = revert at cleanup). Option-C 3-PR sequence locked; this is PR 1 of 3. Awaits user PROCEED.
