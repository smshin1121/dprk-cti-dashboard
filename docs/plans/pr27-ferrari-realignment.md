# PR #27 — Ferrari design realignment

**Status:** 🔒 **Locked 2026-05-03** — user sign-off received on all 4 §10 decisions. Implementation gated on ultrareview Monitor finding fix (per workflow 2-b).
**Parent doc:** `DESIGN.md` (Ferrari/Rosso Corsa Google-Stitch spec, 260 lines, 9 sections — see project memory `design_md_reference`).
**PR:** #27 (currently OPEN, MERGEABLE/CLEAN, Monitor preset adopted in 8 commits at `107d868`). This plan extends PR #27 with a Ferrari realignment that replaces Monitor.
**Workflow precedence:** Per user 2-b decision, ultrareview Monitor findings (in flight) get fixed first; THEN this Ferrari realignment. Monitor fixes preserve audit trail for reviewers; Ferrari realignment is the final state.
**Branch:** `feat/pr27-visual-redesign-seed` (current cwd worktree).
**Stack relationship:** Stacked on PR #23 (`feat/p3.5-lazarus-parity`); base flips to `main` after PR #23 merges (existing watcher unchanged by this plan).

---

## 0. Lock summary (DRAFT — to be locked at sign-off)

Five invariants for the Ferrari realignment:

1. **Single dark canvas as standard.** Theme model collapses from `light/dark/system` (3-mode) to **Ferrari dark canvas (#181818) as the page floor**, with **per-section light editorial bands** for surfaces that explicitly opt in (e.g. report list tables, pricing-style detail panes). `ThemeToggle.tsx` is removed; `useThemeStore` is removed; FOUC inline script becomes obsolete.
2. **Sharp 0px corners are the brand button.** `--radius` becomes `0`; tailwind `borderRadius.lg/md/sm` collapse to `0`. Pill geometry (`rounded-full`) is reserved for badges only — no exceptions.
3. **Single accent: Rosso Corsa #da291c, used scarcely.** Replaces Monitor cyan. Used only on primary CTAs, the brand mark (if any), and incident/report priority highlights (CTI-domain mapping of "F1 race-position highlights").
4. **Inter weight 500 with -1% letter-spacing on display, 400 body, 700 buttons + uppercase + 1.4px tracking.** FerrariSans is licensed; Inter Variable (already in fontFamily.sans) is the documented substitute. Display weight NEVER bold.
5. **Explicit named 8px spacing ladder.** `xxxs 4 / xxs 8 / xs 16 / sm 24 / md 32 / lg 48 / xl 64 / xxl 96 / super 128` — extend tailwind `theme.spacing` (or alias) so utilities like `p-md` render 32px. Ad-hoc px values are linted out.

---

## 1. Goal

Replace the Monitor visual language adopted in PR #27 commits 1-8 with the Ferrari/Rosso Corsa visual language defined in `DESIGN.md`. Result: the dashboard's tokens, typography, spacing, corners, and elevation all match the Ferrari brand spec; CTI-domain components (KPI cards, charts, dashboard widgets, list tables) inherit the Ferrari shape vocabulary while preserving their data semantics.

**Non-goals (this plan):**
- BE / API / contract changes — pure FE.
- Replacing data semantics (KPI math, chart type, etc.) — only chrome.
- Mobile-first redesign — Ferrari responsive lock is honored, but breakpoints stay at the existing Tailwind defaults.
- Switching framework (Tailwind / shadcn / Vite / Inter) — all preserved.

---

## 2. Theme model change (3-mode → single dark + per-section light)

Current `tokens.css` carries three branches (`:root`, `[data-theme="dark"]`, `[data-theme="system"]` + `@media prefers-color-scheme`). Ferrari standard collapses this to **one canvas** plus **per-section light editorial bands**.

**Removed:**
- `apps/frontend/src/components/ThemeToggle.tsx` + its tests
- `apps/frontend/src/layout/__tests__/Shell.theme.test.tsx`
- `useThemeStore` (zustand store for theme selection)
- FOUC inline `<script>` in `index.html` (no longer needed; one canvas)
- `tailwind.config.ts` `darkMode: [...]` selector (replaced with default `'media'` or removed entirely)

**Added:**
- A single CSS class `editorial-band-light` (or similar token) that overrides surface tokens within an opt-in DOM subtree to the Ferrari light palette (`canvas-light #ffffff`, `body-on-light #181818`, `hairline-on-light #d2d2d2`). Used on report list tables, detail pane backgrounds where explicit white-canvas read-through is desired.
- Layout-level `<body class="bg-canvas text-ink">` — Ferrari canvas as floor.

**Migration risk:** Existing user theme preferences in localStorage become orphaned data. No-op cleanup is acceptable (key just stops being read).

---

## 3. L1 — tokens.css full Ferrari replacement

Single-source replacement of `apps/frontend/src/styles/tokens.css`. Drop the HSL triple convention; introduce Ferrari named-hex tokens at `:root` only (no theme branches).

### 3.1 Token mapping (Monitor → Ferrari)

| Token role | Monitor (current HSL) | Ferrari (target) |
|:---|:---|:---|
| Canvas (page floor) | `220 8% 96%` (light) / `220 6% 7%` (dark) | `#181818` (single) |
| Canvas elevated (card) | `0 0% 100%` (light) / `220 6% 9%` (dark) | `#303030` |
| Canvas light (editorial band only) | n/a | `#ffffff` |
| Surface soft light | n/a | `#f7f7f7` |
| Hairline (dark) | `220 10% 88%` / `220 6% 16%` | `#303030` |
| Hairline on light | n/a | `#d2d2d2` |
| Hairline soft | n/a | `#ebebeb` |
| Ink (display, on dark) | `220 10% 12%` / `0 0% 96%` | `#ffffff` |
| Body | `220 8% 40%` / `220 4% 65%` | `#969696` |
| Muted | `220 6% 55%` / `220 4% 45%` | `#666666` |
| Body on light | n/a | `#181818` |
| Primary | cyan `190 75% 45%` | `#da291c` Rosso Corsa |
| Primary active | cyan-darker | `#b01e0a` |
| On primary | white | `#ffffff` |
| Status info | `190 75% 45%` | `#4c98b9` |
| Status success | `145 60% 40%` | `#03904a` |
| Status warning | `30 90% 50%` | `#f13a2c` |
| **Removed (Monitor 6-color SOC palette)** | crit / warn / elev / ok / info / special | — Reduced to 3 semantic only |
| Focus ring | `30 90% 50%` (Hypersail-yellow tone) | `#fff200` Hypersail Yellow (focus-only) |
| Radius | `0.5rem` | `0` (default); `9999px` (badge pill only); `0.25rem` (form inputs only per DESIGN §Forms) |

### 3.2 Spacing ladder (new)

Add to tailwind `theme.spacing` extension (alias, not replacement, to keep existing `p-4` etc. working until L2 sweep is done):

```ts
spacing: {
  xxxs: '4px',  xxs: '8px',  xs: '16px',  sm: '24px',
  md: '32px',   lg: '48px',  xl: '64px',  xxl: '96px',
  super: '128px',
}
```

### 3.3 Typography

Tailwind `fontFamily.sans` already starts with Inter Variable — no change. Add `fontWeight` aliases for Ferrari display semantics:

```ts
fontWeight: {
  display: '500',     // Ferrari display NEVER bold
  body: '400',
  cta: '700',         // CTAs only
}
```

Add `letterSpacing` Ferrari ladder:

```ts
letterSpacing: {
  display: '-0.0125em',  // -1% on display sizes
  cta: '0.0875em',       // 1.4px / 16px button base
  nav: '0.0406em',       // 0.65px / 16px nav
}
```

---

## 4. L2 — 1st-class component layer (direct translation)

These map 1:1 onto Ferrari component definitions in DESIGN.md §Components.

| File | DESIGN.md ref | Ferrari change |
|:---|:---|:---|
| `components/Button` (where defined / inline) | §Buttons | Sharp 0px corners; uppercase; 1.4px tracking; Rosso Corsa primary fill; press state #b01e0a; outline variant 1px white border |
| `components/Card` (KPICard, etc.) | §Cards `feature-card-photo`, `driver-card` | 0px corners; canvas-elevated #303030 bg; ink text; 1px hairline border |
| Form inputs (LoginPage, FilterBar) | §Forms `text-input-on-dark` | 4px corners (per DESIGN.md §Forms exception); canvas bg; ink text; hairline border |
| `components/UserMenu` (badges) | §Forms `badge-pill` | rounded-full pills with caption-uppercase typo |
| `layout/Shell` top nav | §Top Navigation `top-nav-on-dark` | Canvas bg; ink text; uppercase 0.65px tracking |
| `components/CommandPaletteButton` | §Buttons + §Cards | Same Ferrari button vocabulary; sharp corners |
| `components/LocaleToggle` | §Buttons (text-tertiary) | Inline text link; uppercase tracking |
| `components/ReportsViewModeToggle` | §Buttons (group / segmented) | Sharp 0px corners; uppercase labels |
| `components/ReportsYearJumpSelect` | §Forms `text-input` | Form input variant |

---

## 5. L3 — Mapped components (CTI ↔ Ferrari translation)

Ferrari domain components that need CTI-domain renaming. Structure imported, content semantics preserved.

| Ferrari component (DESIGN.md) | CTI mapping | Reuse degree |
|:---|:---|:---|
| `driver-card` (F1 driver portrait) | `actor-card` (in `ActorsPage`, `GroupsMiniList`) | Photo plate → actor avatar; name/race-number → actor name/codename count; team badge → motivation tag |
| `preowned-listing-card` (used cars) | `report-list-card` (in `ListTable`, `ReportFeed`, `ReportTimeline`) | Car photo → report headline; model → publisher; year/mileage → date/source confidence |
| `race-position-cell` (F1 #1 in Rosso Corsa) | `incident-priority-cell` (in `IncidentsPage`, `AlertsDrawer`) | Number-display Rosso Corsa for HIGH-priority incident counters; canvas fade for routine |
| `livery-band` (Rosso Corsa accent band) | `priority-incident-band` (in `DashboardPage` top section, conditional) | Rosso Corsa full-width band ONLY when at least one critical incident is unresolved |
| `spec-cell` (technical specs in cinema number-display) | `kpi-cell` (in `KPIStrip`, `KPICard`) | Number-display 80px for primary KPI value; caption-uppercase for label |
| `race-calendar-row` (F1 race calendar) | `incident-row` / `report-row` (in `ListTable`) | Hairline-divided rows; date column left, title middle, status right |
| `cta-band-dark` (pre-footer CTA) | n/a (no marketing CTA in dashboard) | — Not used |
| `newsletter-input-band` | n/a | — Not used |
| `footer-dark` | `app-footer` (currently minimal/none) | Optional — defer if not present |

---

## 6. L4 — Hero reinterpretation for CTI dashboard

DESIGN.md `hero-band-cinema` is a marketing pattern (full-bleed cinematic photograph + display headline). CTI dashboard has no marketing surface; the equivalent surface is the **dashboard landing view** (`DashboardPage`).

### 6.1 CTI hero definition (proposed)

The CTI "hero" surface, per Ferrari aesthetic principles:

- **Full-bleed canvas** — `#181818` (no boxed/contained header on the dashboard landing).
- **Display-mega number callout** — primary KPI rendered in `typography.number-display` (80px / 700 / -1.6px) at the top, with caption-uppercase label below. Either:
  - **Option H1**: Total active incidents count (RED Rosso Corsa if > threshold).
  - **Option H2**: Recent activity timeline strip (last 30d) full-bleed at the top, with a number-display callout overlaid bottom-left.
- **Sub-headline** in `typography.display-md` (26px / 500) summarizing context (e.g. "DPRK CTI — current threat surface").
- **One primary CTA** (Rosso Corsa) — "Acknowledge alerts" / "Review unread reports" / similar, depending on user role.
- **One outline CTA** — "Browse incidents" / "Browse reports".
- **Below the hero**: existing KPI strip + dashboard widgets in standard editorial layout.

### 6.2 Choice point

H1 (number-only) vs H2 (timeline + number overlay) is a UX decision worth surfacing. H1 is faster to ship and matches Ferrari's editorial restraint; H2 is more dashboard-native but risks competing visually with the existing TrendChart widget.

**Recommendation: H1** for v1 — single number-display KPI at the top with sub-headline + 2 CTAs. H2 deferred to a future iteration if H1 reads as too sparse.

---

## 7. Implementation sequence (execution gate)

Atomic commits, in order:

| # | Commit subject | Files | Risk |
|:---:|:---|:---|:---|
| 1 | `chore(fe): collapse 3-mode theme to single dark canvas` | tokens.css; remove ThemeToggle.tsx + 2 tests; remove useThemeStore; remove FOUC script; tailwind.config.ts darkMode | High — test removals |
| 2 | `feat(fe): adopt Ferrari token palette (L1)` | tokens.css full rewrite; tailwind.config.ts colors/radius/spacing/font extensions | High — visual cascade |
| 3 | `feat(fe): apply Ferrari button + form vocabulary (L2 part 1)` | All button/input/CTA usages — sharp corners, uppercase, tracking | Medium |
| 4 | `feat(fe): apply Ferrari card + nav vocabulary (L2 part 2)` | All card/nav usages | Medium |
| 5 | `feat(fe): retrofit dashboard widgets to Ferrari spec (L3 part 1)` | KPICard, KPIStrip, ListTable, ReportFeed | Medium |
| 6 | `feat(fe): retrofit chart + heatmap surfaces (L3 part 2)` | TrendChart, AttackHeatmap, WorldMap, MotivationDonut, IncidentsStackedArea, SectorBreakdown, LocationsRanked, ContributorsList, GroupsMiniList | Medium |
| 7 | `feat(fe): apply Rosso Corsa priority highlights (L3 part 3)` | AlertsDrawer, IncidentsPage status cells, priority-incident-band | Low |
| 8 | `feat(fe): introduce CTI hero per Ferrari Option H1 (L4)` | DashboardPage hero band; sub-headline; 2 CTAs | Medium |
| 9 | `test(fe): visual regression baseline + remove obsolete theme tests` | Jest snapshots / Playwright screenshots; remove Shell.theme.test.tsx | Medium |

**After commit 9:** Codex r1-r4 on the Ferrari delta (full diff vs Monitor end-state). Then PR body update + body Codex r1-r4. Then user push gate (force-push since previous commits remain).

---

## 8. Out of scope

- **PR B (Phase 3 Slice 3 FE)** — independent, lands on its own branch from main after PR A merges.
- **PR C (hardening + cache + UAT)** — independent.
- **Mobile-first redesign** — out of scope; existing breakpoints honored.
- **Animation timings** (DESIGN.md §Known Gaps) — out of scope.
- **Hypersail yellow tokens beyond focus ring** — Hypersail program-specific in DESIGN.md; CTI uses yellow only as focus ring per WCAG.
- **F1-specific surfaces** (`race-calendar-row` direct port, `driver-card` literal F1 mapping) — only the structural patterns are reused, not the F1 content semantics.

---

## 9. Test impact

- **Removed**: `ThemeToggle.test.tsx`, `Shell.theme.test.tsx` (theme toggle obsolete).
- **Modified**: many existing snapshot tests will re-baseline (intentional cascade).
- **Added**:
  - `tokens.css` regression test — assert hex values match DESIGN.md (R-13-style prevention against drift).
  - Visual snapshot test for L4 hero on `DashboardPage`.
  - Sharp-corners regression — assert `--radius: 0` resolves; no `rounded-md/lg/sm` cascade.

---

## 10. Sign-off decisions (LOCKED 2026-05-03)

1. **L4 hero option** → **H1** (single number-display KPI). Primary KPI rendered in `typography.number-display` (80px / 700 / -1.6px) at top, caption-uppercase label below, sub-headline in `display-md`, one Rosso Corsa primary CTA + one outline CTA. Below: existing KPI strip + dashboard widgets in standard editorial layout. H2 deferred to a later iteration if H1 reads sparse.
2. **`editorial-band-light` opt-in surfaces** →
   - Report list table rows (currently in `ListTable`, `ReportFeed`, `ReportTimeline`)
   - Detail pane backgrounds (currently in `ReportDetailPage`, `IncidentDetailPage`, `ActorDetailPage`)
   - Other surfaces (dashboard widgets, charts, KPI strip, top nav, footer) stay on the dark canvas.
3. **Status palette** → **Option B** (6-token CTI-semantic preservation, recolored within Ferrari palette). The 6-token mapping draft (final values fixed at L1):
   | Monitor token | Ferrari recolor (proposed) |
   |:---|:---|
   | `crit` | `#da291c` Rosso Corsa (saturated) |
   | `warn` | `#f13a2c` Ferrari semantic-warning |
   | `elev` | TBD at L1 — collapse to `warn` (recommended) OR introduce a Ferrari-warm escalation tone (DESIGN.md does not provide one; Hypersail yellow is reserved). Decision: **collapse `elev` to `warn`** unless L1 review surfaces a UX gap. |
   | `ok` | `#03904a` Ferrari semantic-success |
   | `info` | `#4c98b9` Ferrari semantic-info |
   | `special` | `#8f8f8f` Ferrari muted-soft (downgrade `special` to neutral; classification badges retain Rosso Corsa accent only when escalation-relevant) |

   Rationale: Ferrari strict 3-color palette would force creative reinterpretation of CTI criticality semantics (incident-CRIT vs incident-WARN vs HIGH-eleverated alert) into Rosso Corsa intensity gradients, which is not a documented Ferrari pattern. CTI-domain semantic richness is preserved by recoloring the existing 6-token taxonomy within the Ferrari palette. Ferrari principle "single accent used scarcely" is honored because Rosso Corsa is reserved for `crit` only, not all 6 statuses.
4. **Rollback policy** → **atomic per-commit revert**. Each of the 9 commits in §7 is independently revertible (`git revert <sha>`). Branch-level reset is reserved for emergency only and would require user explicit authorization. Plan doc itself is preserved in any rollback path.

---

## 11. Refs

- DESIGN.md (Ferrari brand spec)
- `apps/frontend/src/styles/tokens.css` (Monitor preset, current state)
- `apps/frontend/tailwind.config.ts` (current tailwind config)
- Project memory `design_md_reference` (Ferrari is one of 69 brand DESIGN.md presets; Google Stitch format)
- Project memory `pattern_codex_body_review_loop` (4-round body Codex after L1-L4 ships)
