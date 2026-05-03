# Plan — DESIGN.md v2 Layout Patterns + Page-Class Taxonomy (next design-contract PR)

**Phase:** Brand-contract extension on top of Ferrari v1 (PR #29 merged 2026-05-03 PM as `705e6f9`).
**Status:** Locked 2026-05-04 after 2 reviewer rounds + 1 Codex pre-review round (v2.2). Awaits branch + PR open.
**PR number:** Not reserved. Confirm via `gh pr list` immediately before opening; current main HEAD is `705e6f9`, only PR #30 (DQ CLI Windows fix) is open at draft time.
**Predecessors:** PR #29 (Ferrari brand contract / DESIGN.md v1; merged 2026-05-03 PM as `705e6f9`).
**Successors:** Next correlation FE PR (`docs/plans/correlation-fe.md`) — consumes PT-1..PT-7 patterns and ships the runtime page-class mechanism as its T0.
**Source proposal:** `docs/proposals/design-v2-layout-patterns-draft.md` v2.2.
**Codex pre-review transcript:** `.codex-review/design-v2-prereview.transcript.log` (verdict PROCEED-WITH-AMENDMENT, all HIGH+MEDIUM findings folded into v2.2).

---

## 1. Goal

Extend the Ferrari v1 brand contract (`DESIGN.md` at commit `705e6f9`) with **in-product workspace composition rules** for analyst and admin pages, plus a 5-class page-class taxonomy that binds each route to a default density / chrome / accent budget. The contract is documentation-only — no runtime mechanism, no component code, no page migration.

The information structure references generic third-party admin-template conventions for layout grammar only; tokens, type, color, corner radius, and motion stay 100% Ferrari per `## Do's and Don'ts`.

**Non-goal (out of scope for this PR):**
- Runtime declaration of page classes (`data-page-class` attribute, typed manifest, vitest enforcement) — moved to next correlation FE PR's T0.
- Component implementation of PT-1..PT-7 — first concrete consumption is the next correlation FE PR.
- Migration of existing analyst pages (`/reports`, `/incidents`, `/actors`) to PT-1 three-pane chrome — separate per-route follow-up PRs.
- New design tokens (spacing / color / typography / radius / shadow). Every value referenced by PT-1..PT-7 already exists in v1.
- Animation / motion specs.

---

## 2. Locked Decisions (2026-05-03 reviewer + 2026-05-04 Codex fold)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **C1** | **Corner radius — mixed.** Cards / CTAs / hero / livery / footer / all major surfaces stay `{rounded.none}` (0px). Inline elements `chip-inline` and `message-bubble-cell` (analyst-workspace only, NEW) bind to `{rounded.sm}` (4px). Existing v1 ladder (`xs` 2 / `sm` 4 / `md` 6 / `lg` 8 / `xl` 12 / `full` 9999) and v1's existing exceptions (`text-input`, `newsletter-input-band`, `badge-pill`) are unchanged. PT-6 introduces no new uses of the `xs`/`md`/`lg`/`xl` rare slots. | Reviewer C1 lock 2026-05-03 — keeps brand-signature 0px sharpness everywhere a user reads it as "the brand", while letting analyst-workspace inline elements sit at `{rounded.sm}` so dense lists / chips don't read as broken. |
| **C2** | **Density — page-class bound.** Editorial pages keep v1 pacing (`{spacing.xxl}` 96px section padding). Analyst-workspace and admin-workspace pages use one tick down (`{spacing.lg}` 48px section padding, `{spacing.sm}` 24px card-to-card gap). Auth pages and system pages share the analyst column for density (single-card focus). | Reviewer C2 lock — analyst pages need information density without feeling cramped; editorial pages need editorial pacing for the photographic hero work. One-tick step uses the existing named ladder; no arbitrary px. |
| **C3** | **Card chrome — analyst/admin only.** PT-3 detail-rail card stack and PT-1 three-pane chrome apply to analyst-workspace and admin-workspace pages only. Editorial pages (dashboard hero / brand / marketing) explicitly never get PT-1 chrome. Auth and system pages explicitly never get PT-3 detail-rail chrome. | Reviewer C3 lock — chrome propagation is the most common way design systems break. Bind chrome to page-class up front so editorial / auth / system pages can never accidentally inherit workspace chrome through a careless component import. |
| **C4** | **Accent — scarce + active indicator.** `{colors.primary}` (Rosso Corsa) stays scarce per v1 (primary CTAs, Cavallino, F1 race-position highlights). PT-5 adds **a 1px left-edge stripe on vertical active states** (list rails, vertical sub-nav). `top-nav-active-indicator` adds **a 2px bottom-edge stripe on horizontal top-nav active items**. No full row fill, no Rosso text recolor, no segmented-control / breadcrumb / tab-strip stripe (those use existing `button-primary` / `button-outline-on-dark` fills or implicit positional active). | Reviewer C4 lock — full-row Rosso for active state is the fastest way to break the "scarce accent" budget. The 1px / 2px stripe geometry gives a visible state signal that stays under the budget; coexists with `button-primary` CTAs in the same surface because weight differential resolves it. |
| **C5** | **Page-class taxonomy — 5 classes, mutually exclusive.** Every route belongs to exactly one of: `editorial-page`, `auth-page`, `analyst-workspace`, `admin-workspace`, `system-page`. Mapping table covers all currently-mounted routes plus `*` NotFound and explicit future-not-routed entries (`/search`, `/admin/*`, `/analytics/correlation`). | Codex Q3 + amendment 2026-05-04 — 4-class set was missing classification for the wildcard NotFound route and conflated `/login` with the editorial hero requirement. 5-class set is exhaustive against the current router and admits clean future growth without re-classification of existing routes. |
| **C6** | **Reference template policy — structure-only, no copy.** Generic third-party admin-template conventions inform PT-1..PT-7 layout grammar (list-rail / center-canvas / detail-rail / panel section / list-row active-indicator). Code, CSS, class names, and assets from any reference template are explicitly forbidden. | Reviewer 2026-05-03 lock + Codex Q1 PASS — keeps the contract extension clean of third-party brand leakage and gives reviewers an unambiguous "no, you can't lift that CSS" signal in code review. |

---

## 3. Scope

### In scope (this PR — docs-only)

- **`DESIGN.md`** — three insertions:
  - **Insert #1:** Two new H2 sections — `## Layout Patterns` (covering PT-1 through PT-7) + `## Page Classes` (covering the route-to-class mapping table) — placed between the existing `## Components` section and `## Do's and Don'ts`.
  - **Insert #2:** New component entry `top-nav-active-indicator` appended to the existing `### Top Navigation` block (after `top-nav-on-light`).
  - **Insert #3:** Five new bullets appended to `## Do's and Don'ts > Don't` covering the C1–C4 + C6 enforcement.
- **`docs/plans/design-v2-layout-patterns.md`** — this plan doc itself.
- **`docs/plans/design-v2-layout-patterns-body.md`** — PR body draft (per project plan-doc convention).
- **No source code changes.** No TypeScript, no React, no test files, no CSS, no Tailwind config — strictly markdown.

### Out of scope (deferred — explicit, with target PR)

- Runtime page-class mechanism (`data-page-class` attribute, `apps/frontend/src/lib/pageClass.ts` manifest, `pageClass.test.tsx` vitest enforcement) → **next correlation FE PR's T0**.
- First component-level consumption of PT-1..PT-7 (`/analytics/correlation` page authored against the contract) → **next correlation FE PR's T9 / T10**.
- Migration of existing analyst pages to PT-1 three-pane → **per-route follow-up PRs** (one per `/reports`, `/incidents`, `/actors`).
- Lighthouse target wiring + 6-target loop expansion → **next slice-3 hardening PR**.

### Out of spec entirely

- New design tokens (no `{layout.rail-list}` / `{layout.rail-detail}` semantic tokens; PT-1 stays on raw 280px / 360px per OQ1 default).
- Animation / motion specs.
- Print / export / PDF stylesheets.
- Storybook / Chromatic / visual-regression tooling.

---

## 4. Task Breakdown

Plan-doc-only PR; no code tasks. The "tasks" below are markdown-edit and review steps.

| # | Task | Depends on | Est. | Exit criteria |
|:---:|:---|:---|:---:|:---|
| **D1** | Apply Insert #1 to `DESIGN.md` (two new H2 sections — `## Layout Patterns` + `## Page Classes`). | — | 0.1d | `## Layout Patterns` and `## Page Classes` H2 anchors exist in `DESIGN.md` between `## Components` and `## Do's and Don'ts`. Total `DESIGN.md` line-count grows by ≈ 130 lines. |
| **D2** | Apply Insert #2 to `DESIGN.md` (`top-nav-active-indicator` component entry inside existing `### Top Navigation`). | D1 | 0.05d | `top-nav-active-indicator` paragraph appears immediately after `top-nav-on-light`. |
| **D3** | Apply Insert #3 to `DESIGN.md` (5 new bullets in `## Do's and Don'ts > Don't`). | D2 | 0.05d | 5 new "Don't" bullets present at end of the Don't list, total Don't list grows from 7 to 12 bullets. |
| **D4** | Commit plan doc + body draft (this file + `docs/plans/design-v2-layout-patterns-body.md`). | D3 | 0.1d | Both files present. PR body summarises the 6 locks (C1–C6) + 3 inserts + cross-references the proposal v2.2 + Codex transcript. |
| **D5** | Branch `feat/design-v2-layout-patterns` from `main`, push, open as **draft PR** (not ready for review). Run CI gate. | D4 | 0.1d | Draft PR open; CI gates green (frontend / backend / lint / link-check if any). No marker should be added to `## Layout Patterns` until merge — the section is the deliverable, not a "draft" marker inside the file. |
| **D6** | Codex code-review round (1 round per `feedback_codex_iteration`, reduced from L1–L4 cycle per OQ4 lock — DESIGN.md insert + cross-ref to `correlation-fe.md` T0). | D5 | 0.5d | Codex transcript stored at `.codex-review/codex-design-v2-r1.transcript.log`. Findings folded into the same branch via additional commits before flipping draft → ready-for-review. |
| **D7** | Flip PR draft → ready for review; mark Codex review-response commits + amendment commits in PR body. | D6 | 0.05d | PR not draft. PR body lists all amendment commits. |
| **D8** | Final manual smoke (no UI to test — verify only that `DESIGN.md` renders cleanly in GitHub PR diff and the new H2 anchors are usable as in-document links). | D7 | 0.05d | GitHub diff renders all 3 inserts with no markdown-table-overflow / no truncated rows. |

**Estimated dev-time:** ≈ 1.0 dev-day. Aligns with reviewer's "축소 운영" guidance — DESIGN.md contract + 1-round Codex, no L1–L4 cycle.

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|:---|:---:|:---|
| GitHub PR diff renders the new tables (PT-4, PT-7, Page Classes) with overflow on narrower display widths, making review hard. | Med | D8 final smoke step explicitly checks the diff render. If overflow, fold longer cell text into nested bullet lists pre-merge. |
| PT-1 / PT-3 specifications are too underspecified for the next correlation FE PR's `CorrelationFilters` / `CorrelationCaveatBanner` / `CorrelationLagChart` components, forcing additional design-contract PRs mid-implementation. | Med | The next correlation FE PR's T0 + T1 + T9 (component implementation) treat any underspec as a flag-and-amend feedback loop. Amendments come back as additional `DESIGN.md` PRs (per `pattern_plan_vs_impl_section_0_1_amendments`), not silent component-side improvisation. |
| Codex pre-review found PASS on Q1–Q5 + folded HIGH/MEDIUM, but the post-canonical-edit verification might surface a regression introduced by the canonical-edit copy. | Low | D6 Codex round operates on the post-edit `DESIGN.md` (not the proposal draft) and re-checks every Q1–Q5 + Q7 invariant against the canonical content. The proposal-vs-canonical text overlap is verbatim, so regressions should be near-zero. |
| Reviewer 2026-05-03 lock said PR is docs-only, but the runtime mechanism in the next FE PR might surface that the manifest needs a key the design contract doesn't expose (e.g. a route-specific override flag). | Low | The taxonomy is intentionally simple: 5 classes, 1 route → 1 class. If the runtime needs override flags, that surfaces as an amendment to `## Page Classes` in a follow-up PR — still under design-contract jurisdiction, not silent runtime drift. |
| The `*` NotFound classification under `system-page` doesn't match the actual NotFound rendering (text-only, no link), making the contract over-specify the runtime. | Low | v2.2 + 2026-05-04 amendment fold this: the system-page row says "currently text-only ... may include at most one tertiary link in future". The contract documents the budget, not a mandatory artifact. |

---

## 6. Rollback Plan

Pure docs-only PR — three markdown inserts in `DESIGN.md` plus two new files in `docs/plans/`. Revert path: `git revert <merge-commit>`.

- No DB migrations.
- No environment-variable changes.
- No feature flags.
- No source code changes.
- No test changes.
- No CI workflow changes.

A successful revert restores `DESIGN.md` to its v1 / Ferrari-only state. The next correlation FE PR (which depends on this contract) would need to re-base or wait for a re-issued design-contract PR.

---

## 7. Acceptance Criteria

This PR is mergeable only when **all** of the following hold:

1. `DESIGN.md` renders cleanly in the GitHub PR diff: all 3 inserts visible, all tables render without overflow, all H2 / H3 anchors valid.
2. Insert #1: `## Layout Patterns` H2 present at expected location (between `## Components` and `## Do's and Don'ts`); contains PT-1 through PT-7 sub-sections; each PT entry is non-empty and references at least one v1 token.
3. Insert #1: `## Page Classes` H2 present immediately after `## Layout Patterns`; mapping table contains 10 rows (`/dashboard`, `/`, `/login`, `/reports*`, `/incidents*`, `/actors*`, `*` NotFound, `/analytics/correlation`, `/search` future, `/admin/*` future).
4. Insert #2: `top-nav-active-indicator` paragraph present at the end of `### Top Navigation`, immediately following `top-nav-on-light`.
5. Insert #3: `## Do's and Don'ts > Don't` list contains the 5 new bullets covering full-row-Rosso ban, density propagation ban, card-chrome propagation ban, corner-softening ban, third-party admin template copy ban.
6. **No new tokens introduced.** Every `{token.*}` reference in the inserts already exists in `DESIGN.md` v1 (verified by lint or manual cross-check).
7. **No DashLite naming in canonical content.** A grep against the new content for "dashlite" / "DashLite" returns zero matches inside the inserted sections (proposal-meta + risk notes outside `DESIGN.md` are unconstrained).
8. **`docs/plans/correlation-fe.md` cross-reference is consistent.** That plan's T0 task description, In-scope T0 list, and Acceptance Criteria item 3 all reference the same 5-class taxonomy and 9-entry router-mounted manifest count as this contract documents.
9. CI gates green (frontend tests / backend tests / lint / link-check / api-tests / pact-verify) — nothing should regress on a docs-only PR.
10. Codex review round 1 produces PROCEED or PROCEED-WITH-AMENDMENT; any HIGH or CRITICAL findings folded back into the branch before merge.
11. Plan doc + PR body present at `docs/plans/design-v2-layout-patterns.md` and `docs/plans/design-v2-layout-patterns-body.md` (or `pr{N}-*` renamed forms post-opening per `gh pr list` confirmation).

---

## 8. Open Questions

(All resolved via 2026-05-03 reviewer + 2026-05-04 Codex amendment; no remaining open questions for this PR.)

| # | Question | Resolution |
|:---:|:---|:---|
| OQ1 | Rail widths — raw px vs `{layout.rail-*}` semantic tokens? | **Raw 280px / 360px** (no new tokens introduced). |
| OQ2 | PT-5 stripe + `button-primary` CTA in same rail? | **Allowed**; weight differential resolves it. |
| OQ3 | `data-page-class` runtime test discipline? | **Moved out of this PR** to next correlation FE PR's T0 (vitest with bi-directional drift detection). |
| OQ4 | Codex review depth? | **1 round on this PR** (down from Ferrari L1–L4 × 3-round = ~11 rounds; ~80% reduction). |

---

## 9. Change Log

- **2026-05-03 (proposal v1)** — Authored after reviewer Option-A lock + C1–C4 decisions. Initial PT-1..PT-7 + 4-class taxonomy.
- **2026-05-03 (proposal v2)** — Reviewer 5-finding fold (radius reconciliation, density scope, auth-page split, PT-5 horizontal narrow, spec-only vs runtime).
- **2026-05-03 (proposal v2.1)** — Reviewer 3-finding fold (DashLite URL out of canonical, `/` `/dashboard` redirect, T0 alignment).
- **2026-05-04 (proposal v2.2)** — Codex pre-review fold: HIGH stale router (`/search` not mounted, NotFound `*` unclassified) + 2 MEDIUM (segmented/breadcrumb/tab coverage, system-page 5th class). 5-class taxonomy locked.
- **2026-05-04 (this plan + canonical edit)** — Plan doc authored. Canonical `DESIGN.md` editing applied via 3 inserts. Awaits branch + draft PR open + Codex round 1 on the canonical content.
