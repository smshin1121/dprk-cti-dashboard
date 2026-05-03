## Summary

Docs-only extension of the Ferrari brand contract (`DESIGN.md` v1, locked by PR #29 / `c901ef3` and merged onto `main` via PR #29 = `705e6f9`). Adds **in-product workspace composition rules** for analyst and admin pages plus a **5-class page-class taxonomy** that binds each route to a default density, chrome, and accent budget. No source code, no tokens, no test changes — markdown only.

Plan: `docs/plans/design-v2-layout-patterns.md`
Source proposal (with full review history): `docs/proposals/design-v2-layout-patterns-draft.md` v2.2
Codex pre-review transcript: `.codex-review/design-v2-prereview.transcript.log` (verdict: PROCEED-WITH-AMENDMENT, all findings folded into v2.2 → canonical edit)

## Locked decisions (C1–C6)

| # | Decision | One-line rationale |
|:---:|:---|:---|
| C1 | Cards / CTAs / hero / livery / footer = 0px corners. Inline `chip-inline` + `message-bubble-cell` (analyst-workspace only, NEW) = 4px. Existing v1 ladder unchanged. | Brand-signature 0px stays everywhere users read it as "the brand"; analyst inline elements escape only at 4px. |
| C2 | Page-section padding: editorial 96px / analyst & admin 48px / auth & system share auth column. Card-to-card gap analyst & auth = 24px. One tick down the named ladder, no arbitrary px. | Editorial pacing for hero work; analyst density for information scannability; auth/system focused single-card. |
| C3 | PT-1 three-pane chrome + PT-3 detail-rail cards = analyst & admin only. Editorial / auth / system pages explicitly never inherit them. | Chrome propagation is the most common way design systems break; bind upfront. |
| C4 | Active indicator: PT-5 1px Rosso left-stripe (vertical surfaces) + `top-nav-active-indicator` 2px Rosso bottom-stripe (horizontal top-nav). No full-row Rosso fill, no Rosso text recolor, no segmented/breadcrumb/tab Rosso. | Scarce accent budget; weight-light stripe co-exists with `button-primary` CTAs in same surface. |
| C5 | 5-class taxonomy: `editorial-page` / `auth-page` / `analyst-workspace` / `admin-workspace` / `system-page`. Mutually exclusive. Mapping table covers all currently-mounted routes + NotFound + 3 future-not-routed. | Wildcard NotFound classified; `/login` separated from editorial-hero requirement; `/search` documented as command-palette-only at this commit. |
| C6 | Reference template policy: structure-only, no code/CSS/asset/class-name copy from any third-party admin template. | Keeps the contract clean of third-party brand leakage and gives reviewers an unambiguous "no, you can't lift that CSS" signal. |

## What changed in `DESIGN.md`

Three inserts; total file grows from 260 → 407 lines.

### Insert #1 — Two new H2 sections between `## Components` and `## Do's and Don'ts`

- **`## Layout Patterns`**:
  - **PT-1** Workspace Three-Pane (list rail 280px + canvas + detail rail 360px, pane-internal padding `{spacing.sm}` 24px)
  - **PT-2** List-Rail Item (64px row, 1px Rosso left-stripe + canvas-elevated background on active)
  - **PT-3** Detail-Rail Card Section (`{colors.canvas-elevated}` background, 0px corners, 24px padding, label-value field rows)
  - **PT-4** Density (page-section scale per page-class — 96px editorial / 48px analyst / 48px auth)
  - **PT-5** Active Indicator on vertical surfaces only (1px Rosso left-stripe; explicit "does NOT apply" coverage of segmented controls, horizontal breadcrumbs, future tab strips)
  - **PT-6** Inline-Element Rounding (analyst-workspace exception adds `chip-inline` + `message-bubble-cell` at `{rounded.sm}`; existing v1 radius vocabulary unchanged)
  - **PT-7** Page-Class Taxonomy (5 classes, mutually exclusive, runtime mechanism deferred to next FE PR's T0)
- **`## Page Classes`**: 10-row mapping table covering `/dashboard`, `/`, `/login`, `/reports*`, `/incidents*`, `/actors*`, `*` NotFound, `/analytics/correlation` (next FE PR), `/search` (future-not-routed), `/admin/*` (future).

### Insert #2 — `top-nav-active-indicator` component entry

Appended to the existing `### Top Navigation` block (after `top-nav-on-light`). Documents the 2px Rosso bottom-edge stripe geometry for active horizontal top-nav menu items.

### Insert #3 — 5 new "Don't" bullets in `## Do's and Don'ts`

- Don't paint a full row / link / list item Rosso for active state.
- Don't propagate analyst density onto editorial pages.
- Don't propagate analyst card chrome onto editorial / auth pages.
- Don't soften CTA / hero / card corners because a nearby chip uses 4px.
- Don't copy markup / CSS / class names / assets from any third-party admin template.

## Review history

| Round | When | What | Outcome |
|:---:|:---:|:---|:---|
| Reviewer 1 | 2026-05-03 | v1 → v2 | 5 conflicts fixed (radius reconciliation, padding scope, auth-page split, PT-5 horizontal narrow, spec-only vs runtime) |
| Reviewer 2 | 2026-05-03 | v2 → v2.1 | 3 polish items fixed (DashLite URL out of canonical, `/` redirect treatment, T0 representation alignment) |
| Codex pre-review | 2026-05-04 | v2.1 → v2.2 | PROCEED-WITH-AMENDMENT — HIGH (stale router: `/search` unmounted + `*` unclassified) + 2 MEDIUM (segmented/breadcrumb/tab coverage, 5th class for system-page) folded |
| Reviewer 3 | 2026-05-04 | v2.2 → canonical | 3 minor amendments fixed (3 analyst route pairs not 4; "three interactions" not "two" in correlation-fe.md B7; NotFound row "currently text-only" not "tertiary link only") |

## Verification

- `DESIGN.md` line count: 260 → 407 (+147 lines).
- New H2 anchors: `## Layout Patterns`, `## Page Classes`. New H3 anchors: PT-1 through PT-7.
- New component entry: `top-nav-active-indicator`.
- New tokens introduced: **0**. Every `{token.*}` reference in the inserts already exists in v1.
- DashLite naming inside canonical content: **0** matches (verified via awk extraction of fenced markdown blocks in the proposal + grep of canonical inserts).
- `docs/plans/correlation-fe.md` cross-reference: T0 description, In-scope T0 line, and Acceptance Criteria item 3 all reflect the 5-class taxonomy and 9-entry router-mounted manifest documented here.

## Out of scope (explicit, with target PR)

- Runtime page-class mechanism (`data-page-class` attribute, `apps/frontend/src/lib/pageClass.ts` typed manifest, `pageClass.test.tsx` vitest enforcement) → **next correlation FE PR's T0**.
- First component-level consumption of PT-1..PT-7 (`/analytics/correlation` page) → **next correlation FE PR's T9 / T10**.
- Migration of existing analyst pages (`/reports`, `/incidents`, `/actors`) to PT-1 three-pane chrome → **per-route follow-up PRs**.

## Risk

- **Pure docs PR.** No DB migrations, no env-vars, no feature flags, no source code, no test changes, no CI workflow changes. Revert is `git revert <merge-commit>`.
- The next FE PR (correlation viz) depends on this contract; revert would force re-base or re-issued contract PR.

## Memory references

- `pattern_layered_visual_redesign` — Ferrari L1–L4 cadence proven on PR #29; this contract uses an ~80% reduced cadence (1 round on docs only) per OQ4 lock.
- `feedback_codex_iteration` — Codex findings rarely false positives; 1 round + amendment fold matches the pattern.
- `pattern_plan_vs_impl_section_0_1_amendments` — if next FE PR surfaces underspec in PT-1..PT-7, amendments come back as additional `DESIGN.md` PRs, not silent component-side improvisation.

## Acceptance criteria

Per `docs/plans/design-v2-layout-patterns.md` §7. Briefly:

1. `DESIGN.md` renders cleanly in PR diff; all 3 inserts visible; tables render without overflow.
2. Insert #1, #2, #3 all present at expected locations.
3. No new tokens introduced (every `{token.*}` reference exists in v1).
4. No DashLite naming in canonical content.
5. `correlation-fe.md` cross-reference consistent.
6. CI gates green (docs-only — should be a no-op for code paths).
7. Codex review round 1 produces PROCEED or PROCEED-WITH-AMENDMENT; any HIGH/CRITICAL folded.

## Suggested commits in this PR

1. `feat(design): add Layout Patterns + Page Classes sections to DESIGN.md` — the canonical edit (Insert #1 + #2 + #3 in one commit; the 3 inserts are interlinked).
2. `docs(plans): add design-v2-layout-patterns plan + body` — this file + the plan doc.

(Codex review round 1 fold-fix commits, if any, follow these two.)
