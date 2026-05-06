## Overview

Ferrari's marketing site reads as cinematic editorial — closer to a luxury-magazine spread than a typical car-OEM site. The base canvas is **near-black** (`{colors.canvas}` — #181818) holding pure white display type; white-canvas bands appear only inside specific editorial contexts (preowned listings, pricing tables, dealer surfaces). The single brand voltage is **Rosso Corsa** (`{colors.primary}` — #da291c), the iconic Ferrari racing red, used scarcely on primary CTAs, the Cavallino mark, and Formula 1 race-position highlights.

Type runs **FerrariSans** as the single sans family at modest weights — display 500, body 400. CTA labels render in uppercase with generous tracking (1.1-1.4px). The brand never uses bold display copy.

The brand's strongest visual signature is the **full-bleed cinematic hero photograph** — top-of-page imagery shows car photography, model details, or trackside livery without any chrome competing with it. Headlines float over the bottom of the photo or sit in a tight band beneath. Spacing follows the explicit 8px token ladder: `xxxs` 4 / `xxs` 8 / `xs` 16 / `sm` 24 / `md` 32 / `lg` 48 / `xl` 64 / `xxl` 96 / `super` 128.

**Key Characteristics:**
- Single accent: `{colors.primary}` (Rosso Corsa #da291c) for primary CTAs, the Cavallino, F1 race-position highlights. Used scarcely.
- Near-black canvas (#181818) — never pure black. White-canvas bands only inside editorial contexts.
- Single sans family: FerrariSans across every text role.
- Display weight stays at 500 — never bold.
- CTA labels render uppercase with 1.4px tracking.
- Sharp `{rounded.none}` (0px) corners on every CTA, card, and band — luxury-automotive precision.
- Full-bleed cinematic hero photography is the page chrome.
- Explicit 8px spacing token ladder with named scale (xxxs through super).
- Hairlines + photographic depth — no drop shadow tiers.

## Colors

### Brand & Accent
- **Rosso Corsa** (`{colors.primary}` — #da291c): The iconic Ferrari racing red. Primary CTA fill, Cavallino mark, F1 driver-position highlights. Used scarcely.
- **Rosso Corsa Active** (`{colors.primary-active}` — #b01e0a): Press state.
- **Rosso Corsa Hover-darker** (`{colors.primary-hover}` — #9d2211): Documented for completeness; per the no-hover policy this is not used in preview HTML.
- **Hypersail Yellow** (`{colors.accent-yellow-hypersail}` — #fff200) + **Yellow** (`{colors.accent-yellow}` — #f6e500): Sub-brand accents reserved for the Hypersail sailing program and the global focus-ring color. Not part of the main automotive palette.

### Surface
- **Canvas** (`{colors.canvas}` — #181818): Near-black page floor — never pure black, slight warmth.
- **Canvas Elevated** (`{colors.canvas-elevated}` — #303030): Cards and panels on dark canvas.
- **Canvas Light** (`{colors.canvas-light}` — #ffffff): White editorial bands (preowned listings, pricing).
- **Surface Card** (`{colors.surface-card}` — #303030): Same as canvas-elevated — driver cards, livery photo plates.
- **Surface Soft Light** (`{colors.surface-soft-light}` — #f7f7f7): Light editorial alternating band.
- **Surface Strong Light** (`{colors.surface-strong-light}` — #ebebeb): Light-canvas dividers, badges.

### Hairlines
- **Hairline** (`{colors.hairline}` — #303030): 1px divider on dark — same hex as `{colors.canvas-elevated}`.
- **Hairline On Light** (`{colors.hairline-on-light}` — #d2d2d2): 1px divider on light bands.
- **Hairline Soft** (`{colors.hairline-soft}` — #ebebeb): Lighter divider.

### Text
- **Ink** (`{colors.ink}` — #ffffff): Display, body emphasis on dark.
- **Body** (`{colors.body}` — #969696): Default running-text on dark.
- **Body Strong** (`{colors.body-strong}` — #ffffff): Same as ink.
- **Body On Light** (`{colors.body-on-light}` — #181818): Default text on light bands.
- **Muted** (`{colors.muted}` — #666666): Sub-titles, captions on dark.
- **Muted Soft** (`{colors.muted-soft}` — #8f8f8f): Disabled link text.
- **On Primary** (`{colors.on-primary}` — #ffffff): White text on Rosso Corsa.

### Semantic
- **Info** (`{colors.semantic-info}` — #4c98b9): Info badges, callout backgrounds.
- **Success** (`{colors.semantic-success}` — #03904a): Confirmation.
- **Warning** (`{colors.semantic-warning}` — #f13a2c): Validation warnings.

## Typography

### Font Family
**FerrariSans** is the licensed single sans family across every text role. Fallback: `-apple-system, system-ui, sans-serif`. No display/body family split.

### Hierarchy

| Token | Size | Weight | Line Height | Letter Spacing | Use |
|---|---|---|---|---|---|
| `{typography.display-mega}` | 80px | 500 | 1.05 | -1.6px | Homepage hero h1 |
| `{typography.display-xl}` | 56px | 500 | 1.1 | -1.12px | Subsidiary heroes |
| `{typography.display-lg}` | 36px | 500 | 1.2 | -0.36px | Section heads, livery band |
| `{typography.display-md}` | 26px | 500 | 1.5 | 0.195px | Sub-section heads |
| `{typography.title-md}` | 18px | 700 | 1.2 | 0 | Component titles |
| `{typography.title-sm}` | 16px | 500 | 1.4 | 0.08px | List labels |
| `{typography.body-md}` | 14px | 400 | 1.5 | 0 | Default body |
| `{typography.body-sm}` | 13px | 400 | 1.5 | 0 | Footer body |
| `{typography.caption}` | 12px | 400 | 1.4 | 0 | Photo captions |
| `{typography.caption-uppercase}` | 11px | 600 | 1.4 | 1.1px | Section labels, badges |
| `{typography.button}` | 14px | 700 | 1.0 | 1.4px (uppercase) | CTA pill labels |
| `{typography.nav-link}` | 13px | 600 | 1.4 | 0.65px (uppercase) | Top-nav menu items |
| `{typography.number-display}` | 80px | 700 | 1.0 | -1.6px | Race position highlights, spec values |

### Principles
- **Display weight stays at 500.** Editorial confidence, not bombastic. The cinematic photography is doing the visual heavy-lifting — type doesn't need to compete.
- **CTA labels are uppercase with 1.4px tracking.** Luxury-precision feel.
- **Nav labels are uppercase with 0.65px tracking.** Consistent with CTA voice.
- **Negative letter-spacing on display only.** -0.36px to -1.6px on display sizes; body stays at 0.

### Note on Font Substitutes
FerrariSans is licensed. Open-source substitute: **Inter** at weight 500 with letter-spacing -1%, or **Söhne** for closer humanist proportions.

## Layout

### Spacing System
- **Base unit:** 4px.
- **Tokens:** `{spacing.xxxs}` 4px · `{spacing.xxs}` 8px · `{spacing.xs}` 16px · `{spacing.sm}` 24px · `{spacing.md}` 32px · `{spacing.lg}` 48px · `{spacing.xl}` 64px · `{spacing.xxl}` 96px · `{spacing.super}` 128px.
- **Section padding:** `{spacing.xxl}` (96px) for major bands; `{spacing.super}` (128px) reserved for hero band depth.

### Grid & Container
- Max content width: ~1280px on editorial bands. Hero photography goes full-bleed.
- Editorial body: 12-column grid.
- Feature card grids: 2-up at desktop for hero splits, 3-up for benefit grids, 4-up for preowned listing tiles.
- Footer: 5-column at desktop.

### Whitespace Philosophy
Generous editorial pacing. Cinematic hero photography occupies generous viewport real-estate; body sections sit in tighter editorial layouts beneath. The canvas-light editorial bands (preowned, pricing) carry tighter density than the dark cinema bands.

## Elevation & Depth

The system uses **photographic depth + brightness-step** elevation. No drop shadows except a single soft-small `{shadow.small}` documented in extracted tokens.

| Level | Treatment | Use |
|---|---|---|
| Flat (canvas) | `{colors.canvas}` (#181818) | Body bands, footer |
| Card | `{colors.canvas-elevated}` (#303030) | Driver cards, livery plates |
| Light band | `{colors.canvas-light}` (#ffffff) | Preowned listings, pricing |
| Hairline border | 1px `{colors.hairline}` or `{colors.hairline-on-light}` | Card outlines, dividers |
| Soft drop | `0 4px 8px rgba(0,0,0,0.1)` | Hovered cards (single shadow tier) |
| Photographic | Full-bleed cinema imagery | Hero band, livery photographs |

### Decorative Depth
- **Full-bleed cinema photography** is the brand's primary depth treatment.
- **Brand red gradient** (`linear-gradient(180deg, #a00c01, #da291c 64%)`): The Rosso Corsa gradient used inside accent bands and CTA hover states.
- **Dark grey gradient** (`linear-gradient(180deg, #3c3c3c, #030303 64%)`): Atmospheric darken used at section transitions.

## Shapes

### Border Radius Scale

| Token | Value | Use |
|---|---|---|
| `{rounded.none}` | 0px | Every CTA, card, band — dominant radius |
| `{rounded.xs}` | 2px | Tight badges (rare) |
| `{rounded.sm}` | 4px | Form inputs |
| `{rounded.md}` | 6px | Compact cards (rare) |
| `{rounded.lg}` | 8px | Mobile-only collapse cards |
| `{rounded.xl}` | 12px | Modal/dialog corners (rare) |
| `{rounded.full}` | 9999px | Avatar plates, badge pills |

The radius vocabulary is **sharp by default**. Sharp 0px corners are the brand button shape — never rounded pills. Pill geometry is reserved for badge labels only.

## Components

### Top Navigation

**`top-nav-on-dark`** — Default top nav on dark hero pages. Background `{colors.canvas}`, text `{colors.ink}`, height 64px. Layout: Cavallino mark left, primary horizontal menu (Models / F1 / Lifestyle / Owners / Preowned), language picker + utilities right. Menu items render uppercase with 0.65px tracking.

**`top-nav-on-light`** — White-canvas variant for editorial light bands.

**`top-nav-active-indicator`** — Active menu-item indicator on horizontal top navigation. **2px `{colors.primary}` (Rosso Corsa) bottom-edge stripe** under the active menu label, full label width, sitting flush at the nav band's lower hairline. The label text itself stays in the variant's normal nav-link color — `{colors.ink}` on `top-nav-on-dark`, `{colors.body-on-light}` on `top-nav-on-light` — only the stripe carries the active signal. No animation, no hover preview (consistent with `## Iteration Guide` item 5). PT-5's left-edge stripe rule does **not** apply on horizontal nav — geometry rotates by 90° to a bottom-edge stripe to match the nav band's flow.

### Buttons

**`button-primary`** — The signature Rosso Corsa CTA. Background `{colors.primary}`, text `{colors.on-primary}`, type `{typography.button}` (14px / 700 / 1.4px tracking, uppercase), padding 14px × 32px, height 48px, **rounded `{rounded.none}` (0px — sharp corners)**.

**`button-primary-active`** — Press state. Background `{colors.primary-active}`.

**`button-outline-on-dark`** — Transparent with 1px white border. Background transparent, text `{colors.ink}`, 1px white border, same sharp 0px corners.

**`button-outline-on-light`** — Transparent with 1px ink border on light bands.

**`button-tertiary-text`** — Inline text link, uppercase tracking.

### Hero Bands

**`hero-band-cinema`** — Full-bleed cinematic photograph. Background `{colors.canvas}` underneath, but the photo fills the viewport. Display headline floats over the bottom of the photo or sits in a tight band beneath, in `{typography.display-mega}` (80px / 500 / -1.6px). One primary CTA + one outline CTA. Zero padding — the photo fills edge-to-edge.

**`hero-band-light`** — White-canvas variant for editorial bands. Background `{colors.canvas-light}`, text `{colors.body-on-light}`, padding 96px.

### Cards

**`feature-card-photo`** — Image-first card. Background `{colors.canvas}`, text `{colors.ink}`, rounded `{rounded.none}`. Image fills the top edge-to-edge; title + body sit beneath in tight typography.

**`feature-card-light`** — White-canvas variant. Background `{colors.canvas-light}`, text `{colors.body-on-light}`, rounded `{rounded.none}`, padding 32px.

**`driver-card`** — F1 driver portrait card. Background `{colors.canvas-elevated}`, text `{colors.ink}`, rounded `{rounded.none}`, padding 24px. Layout: driver portrait + name + race number + team badge.

### Editorial Surfaces

**`livery-band`** — A full-width Rosso Corsa accent band. Background `{colors.primary}`, text `{colors.ink}`, type `{typography.display-lg}`, 96px padding. Used as a standout livery callout between dark editorial bands.

**`preowned-listing-card`** — Used in the preowned Ferrari listing grid. Background `{colors.canvas-light}`, text `{colors.body-on-light}`, rounded `{rounded.none}`, padding 24px. Layout: car photo top + model name + year/mileage + price.

### Spec & Race Surfaces

**`spec-cell`** — Technical spec callout. Transparent background, value in `{typography.number-display}` (80px / 700 / -1.6px white), label below in `{typography.caption-uppercase}`.

**`race-position-cell`** — F1 driver finishing position. Same number-display geometry but text in `{colors.primary}` Rosso Corsa for the brand's racing identity.

**`race-calendar-row`** — Hairline-divided row in the F1 race calendar. Layout: date column left, race name + circuit middle, results column right.

### Forms & Tags

**`text-input-on-dark`** — Background `{colors.canvas}`, text `{colors.ink}`, rounded `{rounded.sm}` (4px), padding 14px × 16px, height 48px, 1px `{colors.hairline}` border.

**`text-input-on-light`** — White-canvas variant.

**`badge-pill`** — Small uppercase pill. Background `{colors.canvas-elevated}`, text `{colors.ink}`, type `{typography.caption-uppercase}` (11px / 600 / 1.1px tracking, uppercase), rounded `{rounded.full}` (9999px), padding 4px × 12px. The only place pill geometry is used.

### Newsletter / CTA / Footer

**`newsletter-input-band`** — Newsletter signup band. Background `{colors.canvas-elevated}`, padding 32px, rounded `{rounded.sm}`. Holds an inline email input + primary CTA.

**`cta-band-dark`** — Pre-footer band. Background `{colors.canvas}`, centered display headline in `{typography.display-lg}`, single Rosso Corsa CTA. 96px padding.

**`footer-dark`** — Closing dark footer. Background `{colors.canvas}`, text `{colors.body}`. 5-column link list. 64×48px padding.

**`footer-link`** — Background transparent, text `{colors.body}`, type `{typography.body-sm}`.

## Layout Patterns

The patterns below describe **in-product workspace composition** — how the editorial brand surface (covered in `## Layout`, `## Hero Bands`, `## Editorial Surfaces`) reshapes itself for analyst and admin pages without breaking the brand contract.

The information structure references generic third-party admin-template conventions for *layout grammar only* — list-rail / center-canvas / detail-rail composition, panel section pattern, list-row active-indicator. **Tokens, type, color, corner radius, and motion stay 100% Ferrari.** Code, CSS, class names, and assets from any reference template are not adopted.

### PT-1 — Workspace Three-Pane

The reusable analyst-page skeleton.

```
┌────────────────────────────────────────────────────────────────────────┐
│  Top nav (top-nav-on-dark, 64px)                                       │
├──────────────┬───────────────────────────────────────┬─────────────────┤
│  List rail   │  Canvas                                │  Detail rail    │
│  (left)      │  (center, fluid)                       │  (right)        │
│  ~280px      │                                        │  ~360px         │
│              │                                        │                 │
│  list items  │  primary content                       │  detail-card    │
│  + filter    │  (chart / table / form)                │  stack          │
│              │                                        │                 │
└──────────────┴───────────────────────────────────────┴─────────────────┘
```

- **Background:** `{colors.canvas}` (#181818) across all three panes — no white bands.
- **Pane separators:** 1px `{colors.hairline}` (#303030) vertical lines at the rail boundaries.
- **List rail width:** 280px on desktop, collapses below 1024px (rail becomes overlay drawer).
- **Detail rail width:** 360px on desktop, collapses below 1280px (rail becomes hidden behind a `[Details ▸]` toggle in the canvas header).
- **No shadow, no rounded corners, no card chrome** at the pane level — the hairlines do the work.
- **Pane internal padding:** `{spacing.sm}` (24px) — the breathing room between a pane edge and its content. **Distinct from page-section padding** in PT-4 (which governs the gap between major content blocks within a single pane).

### PT-2 — List-Rail Item

The vertical list inside the left rail.

- **Row height:** 64px.
- **Padding:** 12px vertical × 16px horizontal.
- **Layout:** optional 32px avatar/icon + primary label (`{typography.title-sm}`) + optional secondary line (`{typography.caption}` in `{colors.muted}`).
- **Background:** transparent at rest. Hover state is documented as not used (per `## Iteration Guide` item 5: "Hover state never documented"); we keep that contract here too.
- **Active state:** **1px `{colors.primary}` (Rosso Corsa) vertical stripe on the left edge** plus a `{colors.canvas-elevated}` (#303030) row background. The stripe is the brand-scarce accent — see PT-5. The row background gives spatial feedback without painting the row red.
- **Divider:** 1px `{colors.hairline}` (#303030) between adjacent rows. Skip the divider after the active row (the stripe already partitions visually).
- **Corner radius:** 0px on the row itself. Inline child elements (chips, search input above the list) follow PT-6.

### PT-3 — Detail-Rail Card Section

The vertically stacked information cards in the right rail.

- **Card surface:** `{colors.canvas-elevated}` (#303030) on the dark canvas — same elevation token as `driver-card`.
- **Card border:** 1px `{colors.hairline}` (#303030) — visually merges with the canvas-elevated, surfaces only on the section divider.
- **Card padding:** 24px on all sides.
- **Card spacing:** 16px gap between adjacent cards in the stack.
- **Card corner radius:** **0px**.
- **Section header:** `{typography.caption-uppercase}` (11px / 600 / 1.1px tracking) in `{colors.muted}`, separated from the body by 12px.
- **Field rows inside card:** label-value pairs. Label = `{typography.body-sm}` in `{colors.body}`; value = `{typography.body-md}` in `{colors.ink}`. 8px vertical gap between rows.
- **Inline chip elements** (e.g. status pills) follow PT-6.

### PT-4 — Density: Editorial vs Analyst (page-section scale)

**Page-section scale** is bound by page-class (see `## Page Classes`). Page-section scale governs the gap between major content blocks **within a single canvas pane**. It is distinct from PT-1's *pane internal padding* (which governs the breathing room at pane edges).

| Token | Editorial pages | Analyst-workspace pages | Auth pages |
|---|---|---|---|
| Page-section padding (gap between major blocks) | `{spacing.xxl}` (96px) | `{spacing.lg}` (48px) | `{spacing.lg}` (48px) |
| Card-to-card gap (within a stack) | `{spacing.md}` (32px) | `{spacing.sm}` (24px) | `{spacing.sm}` (24px) |
| Pane internal padding | n/a (full-bleed hero) | `{spacing.sm}` (24px) — see PT-1 | `{spacing.sm}` (24px) on the single auth card |
| Hero photograph | full-bleed mandatory | n/a — no hero | n/a — single auth card on canvas |
| Display headline | `{typography.display-mega}` (80px) | `{typography.display-md}` (26px) — page title only | `{typography.display-md}` (26px) — auth card title |
| Body running text | `{typography.body-md}` (14px / 1.5 leading) | `{typography.body-md}` (14px / 1.5 leading) — same body density | same |
| Whitespace philosophy | "generous editorial pacing" | "informational scannability without cramping" | "single-card focus on canvas" |

The analyst-workspace and auth-page rebindings are **one tick down the named ladder** — not arbitrary px. `{spacing.lg}`, `{spacing.sm}`, and `{spacing.md}` already exist in the spacing system; the page classes just rebind which slot is "section" vs "card-gap".

### PT-5 — Active Indicator (vertical surfaces only)

Active states on **vertical** surfaces get **a 1px `{colors.primary}` stripe along the left edge** of the active row or active item, NOT a full row fill or a Rosso text recolor.

- **Where it applies:** PT-2 list-rail rows, vertical sub-nav, file-tree style nav, breadcrumb active segment when rendered vertically.
- **Where it does NOT apply (use the dedicated rule):**
  - **Top navigation** (`top-nav-on-dark` / `top-nav-on-light`) — horizontal surface; uses `top-nav-active-indicator` documented in the `### Top Navigation` component spec.
  - **Primary CTAs** — already Rosso-filled per `button-primary`.
  - **F1 race-position highlights** — already Rosso `race-position-cell`.
  - **The Cavallino mark** — always Rosso, no active-state concept.
- **Where it does NOT apply (other horizontal surfaces — no Rosso stripe):**
  - **Segmented controls** (e.g. inline 2- to 4-option switches such as a method-toggle). Selection signals through the existing `button-primary` fill on the selected segment + `button-outline-on-dark` on the unselected segments. No PT-5 stripe, no `top-nav-active-indicator` stripe — these are toggles, not navigation.
  - **Horizontal breadcrumbs.** The active (rightmost) segment is implicitly active by position; the segments to its left render as inline `button-tertiary-text` links. No Rosso stripe applies.
  - **Future tab strips.** When introduced, document as a new component spec at that time. Until that exists, prefer vertical sub-nav or segmented controls so PT-5 / `top-nav-active-indicator` / segmented-control rules cover the surface unambiguously.
- **Stripe geometry:** 1px wide, full-row height, edge-aligned with the left padding (no inset).
- **Co-existence with primary CTAs in the same rail:** allowed. The stripe is 1px and weight-light; a `button-primary` in the same rail is opaque-filled and dominates visual weight. Both can co-exist without breaking the "scarce accent" budget — the stripe and CTA serve different signals (state vs action).
- **No animation.** Active state shifts on click; no transition is documented.
- **No hover preview.** Per the brand's "hover state never documented" rule, the stripe never previews on hover.

### PT-6 — Inline-Element Rounding (analyst-workspace exception)

The existing radius vocabulary in `## Shapes > Border Radius Scale` is **unchanged** — the named ladder (`xs` 2px, `sm` 4px, `md` 6px, `lg` 8px, `xl` 12px, `full` 9999px) and the documented exceptions for it (`text-input-on-dark`/`text-input-on-light` already use `{rounded.sm}`; `badge-pill` uses `{rounded.full}`; `newsletter-input-band` uses `{rounded.sm}`; `xs`/`md`/`lg`/`xl` reserved for rare cases per the existing scale notes) all stay as documented.

PT-6 adds **two new analyst-workspace inline classes** that bind to `{rounded.sm}` (4px). It does **not** narrow or override existing exceptions; the existing scale stays the source of truth.

| Element | Rounded | Source |
|---|---|---|
| `text-input-on-dark` / `text-input-on-light` | `{rounded.sm}` 4px | `### Forms & Tags` — unchanged |
| `newsletter-input-band` | `{rounded.sm}` 4px | `### Newsletter / CTA / Footer` — unchanged |
| `badge-pill` | `{rounded.full}` 9999px | `### Forms & Tags` — unchanged |
| `chip-inline` (NEW — analyst workspace) | `{rounded.sm}` 4px | PT-6 — analyst-page status / tag / filter chips inside list rails or canvas tables |
| `message-bubble-cell` (NEW — analyst workspace) | `{rounded.sm}` 4px | PT-6 — reserved for conversation/comment-style cells if introduced on analyst pages |
| **CTAs (any variant), hero, livery, footer, all major cards** | `{rounded.none}` 0px | sharp 0px stays the dominant brand shape |
| **Rare-exception slots** (`xs`/`md`/`lg`/`xl`) | per `## Shapes > Border Radius Scale` notes | unchanged — PT-6 introduces no new uses; future cases evaluate against the existing wording ("rare", "compact", "mobile-only", "modal/dialog") |

**PT-6 explicit constraint:** an analyst-workspace page can introduce a `chip-inline` or `message-bubble-cell` at `{rounded.sm}`. It cannot soften any other surface — CTAs/hero/cards stay sharp.

### PT-7 — Page-Class Taxonomy (sets the binding)

Every page in the product belongs to exactly one of **five** classes. The class binds the page to a default density (PT-4), default chrome (PT-1 vs full-bleed vs single-card vs minimal-utility), and default accent budget.

| Class | Examples | Density (per PT-4) | Chrome | Accent | Hero |
|---|---|---|---|---|---|
| **editorial-page** | marketing, brand-spec (no currently-mapped routes — reserved for future surfaces) | Editorial column | full-bleed photographic, no card stack, no PT-1 chrome | scarce — `button-primary` only | required |
| **auth-page** | login, password reset, sign-up | Auth column | single auth card on `{colors.canvas}`, no PT-1 chrome, no hero | scarce — single `button-primary` per card | none |
| **analyst-workspace** | dashboard, correlation, reports, actors, incidents | Analyst-workspace column | PT-1 three-pane + PT-3 detail cards (`/dashboard` uses Dashboard Workspace Pattern variant — see below) | scarce + PT-5 stripe on active rows | none |
| **admin-workspace** | admin actions, settings, user management | Analyst-workspace column (shared with analyst-workspace) | PT-1 three-pane + PT-3 detail cards | scarce + PT-5 stripe + occasional `{colors.semantic-warning}` for destructive actions | none |
| **system-page** | NotFound (404), unrecoverable error fallback, maintenance / banner views | Auth column (shared with auth-page) | inline minimal-utility `<section>` on `{colors.canvas}`, no PT-1 chrome, no hero, no PT-3 detail cards | scarce — text-only or at most one tertiary `button-tertiary-text` "Back to dashboard" link, never more | none |

The taxonomy is **documentation-level** in this section. Runtime declaration (a `data-page-class="..."` attribute on the route container, plus a typed manifest at `apps/frontend/src/lib/pageClass.ts` and a vitest test asserting per-route consistency) lands in the next FE PR after this contract. Until the runtime work lands, the taxonomy is enforced through code review against the mapping in `## Page Classes` below.

## Dashboard Workspace Pattern

`/dashboard` is the single documented exception to the PT-1 three-pane analyst-workspace composition. The page consumes the analyst-workspace **page class** (density, accent budget, no-hero rule) and inherits PT-5 active-row stripes + PT-6 inline-element rounding, but its three-pane structure differs from PT-1 in two material ways:

1. **Left rail content** — section anchors (in-page scroll targets), pinned-actor shortcuts, and quick filters. NOT a record list (PT-1 left rail is a list of selectable records; `/dashboard` has no "selected record" semantics).
2. **Right rail content** — `alerts-rail-section` + `recent-activity-list` + `drilldown-empty-state`. NOT a detail rail (PT-3 detail-rail card section is a deep-read of a selected record; `/dashboard` carries persistent monitoring shell instead).

The center pane preserves the existing 14-widget grid topology (KPIStrip → WorldMap+AttackHeatmap → Actor Network slot (reserved) → LocationsRanked → MotivationDonut+YearBar → SectorBreakdown+ContributorsList → TrendChart+GroupsMiniList → MotivationStackedArea+SectorStackedArea → ReportFeed). Each widget is self-contained and renders its own loading / error / empty / populated states (per plan D11 from PR #13). The `KPIStrip` cell typography + density follow the `## Dashboard KPI Compact Variant` section below — explicitly `/dashboard`-scoped and additive over (NOT replacing) the global `## Spec & Race Surfaces` lock.

### Pane Geometry

- **Left rail**: target width 240px on desktop / wide. Right hairline border `{colors.hairline}` separates it from the center pane.
- **Center pane**: flex. Internal padding `{spacing.md}` × `{spacing.lg}`.
- **Right rail**: target width 320px on desktop / wide. Left hairline border `{colors.hairline}` separates it from the center pane.
- Below the breakpoints in `## Responsive Behavior`, both rails collapse such that left-rail anchor access and right-rail monitoring access are preserved. Exact mechanics (slide-in drawer, top strip, bottom sheet, etc.) land in implementation; this contract reserves the slot and the access guarantee only.

### Heading Row (analyst-workspace pattern, used by `/dashboard` first)

Above the center-pane widget grid, a single heading row carries the page `<h1>` + a `period-readout`. The row sits at the top of the center pane and is `{spacing.md}` tall, no card chrome, no hairline divider.

**`period-readout`** — Read-only display of the active date range from the global FilterBar. Right-aligned in the heading row. Type `{typography.caption-uppercase}` for the "Period" label, body text for the date pair, `{colors.muted}` for the "change in filter bar" hint glyph. **Read-only only — never an input.** The global FilterBar (above the page outlet) remains the single editable source of truth for the date-range URL state. Reusable across analyst-workspace pages where the heading-time-window association is useful.

### Center-Pane Widget Surfaces

`/dashboard` introduces two new component vocabulary entries used in the center pane: `ranked-row-with-share-bar` (reusable across analyst-workspace pages) and `actor-network-graph` (reserved/future slot, dashboard-specific for now).

**`ranked-row-with-share-bar`** — Row variant for ranked list-cards. Anatomy: 32×32 square avatar (`{colors.canvas}` background, `{colors.body}` initials, 1px `{colors.hairline}` border, `{rounded.none}` corners) + name (body) + sub (caption, `{colors.muted-soft}`) + horizontal share-bar (4px height, `{colors.body}` fill at 100% opacity for top item in the panel, scaled to relative share for lower-ranked rows, fill never uses `{colors.primary}` or any chart palette) + value (tabular-nums) + percentage (caption, `{colors.muted-soft}`). Background `{colors.canvas-elevated}`, hairline divider between rows, no row hover background. Used by `LocationsRanked`, `SectorBreakdown`, `ContributorsList`, `GroupsMiniList`. Reusable on any future ranked panel that lives inside an analyst-workspace center pane.

**`actor-network-graph`** — Full-width center-pane card slot for a Social Network Analysis (SNA) co-occurrence visualization of actors / tools / sectors. Card chrome: `{colors.canvas-elevated}` background, 1px `{colors.hairline}` border, `{rounded.none}` corners. Title row consumes the standard card-head pattern. **This slot is RESERVED / FUTURE.** The contract registers position (between WorldMap+AttackHeatmap row and LocationsRanked) + title (`Actor network · co-occurrence`) + node-kind vocabulary (actor / tool / sector with stroke-style differentiation, single muted fill, degree-centrality node sizing). The data path — BE endpoint shape, edge semantics, refresh cadence — is intentionally undefined here. Acceptable production states until the data PR ships: (a) hide the card entirely, or (b) render the card with title + the **text-only** empty state `Planned · no data yet`. The card body must be text-only — **do not** render graph marks, axes, nodes, edges, skeleton charts, sparklines, or any visualization-shaped placeholders that suggest real data. **No mock SVG / fabricated nodes / synthetic edges may render in production.** Sketches and design rehearsals (gitignored) may carry mock shapes; the production tree must not.

### Right-Rail Surfaces

**`alerts-rail-section`** — Right-rail Phase 4 static shell. Replaces the floating `AlertsDrawer` trigger on `/dashboard`. Anatomy: `{typography.caption-uppercase}` section title with a `Phase 4` placeholder pill at end-of-line + a single explicit empty-state line `Phase 4 — no live alerts wired yet` in `{colors.muted-soft}`. **No mock alert rows, no fabricated dot+label+timestamp tuples.** The same reserved-slot rule that governs `actor-network-graph` (production must not render synthetic data) applies here. **Live data wiring is OUT OF SCOPE for both PR 2 (workspace retrofit implementation) and PR 3 (SNA data).** A separate Phase 4 PR ships actual alerts; until then the section renders title + Phase-4 pill + the single empty-state line, nothing else.

The right rail also carries a `recent-activity-list` block — same reserved-slot discipline (title + `Phase 4 — no activity wired yet` empty-state line, no mock rows) — and a `drilldown-empty-state` block (`Phase 4 — drilldown not wired yet`) that anticipates the Phase 4 selection-driven detail interaction. The drilldown copy follows the same Phase-4 honesty discipline as `alerts-rail-section` and `recent-activity-list` — it does NOT prompt the user to perform an action that PR 2 has not wired. Both `recent-activity-list` and `drilldown-empty-state` reuse the caption-uppercase title + empty-state line pattern from `alerts-rail-section`; neither is registered as a separate component vocabulary entry to avoid duplicating the rule.

### Cross-References

- **Page-class binding**: `/dashboard` → `analyst-workspace` per `## Page Classes` mapping. Density (PT-4 analyst column), accent budget (PT-5 stripes only), no-hero rule (analyst-workspace row's hero column = `none` per the definitions table above).
- **PT-1 contrast**: PT-1's record-list left rail and detail-rail right pane do NOT apply here. The Dashboard Workspace Pattern is the dedicated composition for monitoring-and-overview surfaces; PT-1 stays the dedicated composition for record-list workspaces (reports / incidents / actors, plus future correlation once `/analytics/correlation` is mounted).
- **PT-3 contrast**: PT-3 detail-rail card section is unused on `/dashboard`. The right rail uses `alerts-rail-section` + `recent-activity-list` + `drilldown-empty-state` instead.
- **PT-5 active state**: section anchors in the left rail use the PT-5 1px Rosso left-edge stripe on the active row, identical to the analyst-workspace stripe rule.
- **PT-6 inline rounding**: applies on `/dashboard` for any chip-inline / message-bubble-cell that lands here. CTAs / hero / cards stay 0px per the Don't list.

## Dashboard KPI Compact Variant

This section is **additive** over `## Spec & Race Surfaces`. It introduces a `/dashboard`-scoped KPI density pattern that runs in parallel with the locked global `spec-cell` + `race-position-cell` 80px hero patterns from PR #31; those patterns are NOT revised by this section. Race-position-cell (F1 driver finish) and non-dashboard spec-cell consumers continue to use the 80px `{typography.number-display}` token. The dashboard KPI strip uses a denser, scannable variant tuned for the analyst-workspace center-pane density target.

**Why the variant exists.** PR #33 (workspace retrofit) shipped the existing 80px hero KPIs without redesign. Manual smoke against the DashLite analyst-dashboard reference + sketch v3 confirmed the 80px hero reads as editorial/spec callout typography rather than analyst-density information typography. Aggregate cards (Top Group / Top Motivation) renderring short STRINGS at 80px also misuses the spec-cell pattern (which is for NUMBERS). The compact variant fixes both.

**`kpi-strip-compact`** — Dashboard-scoped KPI strip. Anatomy:

- **Layout**: 6-cell grid, `grid grid-cols-3 lg:grid-cols-6 gap-4`. Cells wrap to two rows of 3 below the `lg` breakpoint and align to a single 6-cell row at `lg+`. Replaces the previous `flex flex-wrap gap-8 p-6` layout.
- **Cell chrome**: transparent (no border-card, no bg-surface) for populated / empty / loading states — preserves the spec-cell editorial-floating-cell intent. Error state KEEPS small card chrome (`border border-border-card bg-surface p-4`) to read as a status callout against the dark canvas.
- **Cell label**: `{typography.caption-uppercase}` (10-11px, 600 weight, 1.1px tracking, uppercase, `{colors.muted-soft}`). Same as the 80px spec-cell pattern.
- **Cell value (scalar number)**: `text-3xl` (~30px) at 700 weight (`font-cta`), tight leading (`leading-none` or `leading-tight`). Drops `text-[80px]` and `tracking-number-display` from the spec-cell pattern — the compact variant is NOT a hero callout.
- **Cell value (aggregate string — Top Group, Top Motivation, Top Year)**: `text-base` or `text-lg` body weight on the primary string, optional `text-xs text-ink-subtle` subtext beneath. NEVER 80px. Aggregate strings are categorical labels, not numeric callouts.
- **Empty placeholder**: dash (`—`) at the same `text-3xl` geometry as the populated value (so the cell footprint stays stable when data lands).
- **Loading skeleton**: `text-3xl`-sized pulsing block; NOT the 80px footprint.

**`kpi-cell-delta`** — Optional in-cell delta indicator. Renders as a small caption (`text-xs`, tracking-caption) sized just below the value. Direction-derived color: positive delta uses `{colors.status-ok}` (green), negative uses `{colors.status-warn}` (red), zero / null omits the slot entirely. Sign is explicit (e.g. `+10.8%`, `-8.3%`). The delta is sourced from a real time-series field on the BE summary; if the source series has fewer than 2 points, the slot is omitted (no fake numbers — same reserved-slot text-only discipline that governs `actor-network-graph` and `alerts-rail-section`).

**`kpi-cell-sparkline`** — Optional in-cell sparkline. Inline `<svg viewBox="0 0 60 24">` with a single `<path>` stroked at `{colors.muted-soft}` (1px); no fill, no axes, no labels. Width ~60px, height ~24px. Sits to the right of the value or beneath it depending on cell width. NEVER use Recharts / canvas / animation — the sparkline is structure, not signal. If the data series has fewer than 2 points, the slot is omitted entirely.

**Cross-reference back to `## Spec & Race Surfaces`.** The 80px hero treatment is preserved for non-dashboard spec-cell + race-position-cell consumers. The compact variant is the dashboard exception. If a future surface needs editorial-spec callout typography (e.g. a single-metric standalone hero), it uses the locked 80px pattern; if it needs analyst-density information typography (multiple cells, scannable, possibly with deltas / sparklines), it uses this compact variant. The choice is anchored on which page-class hosts the cell: `analyst-workspace` density → compact variant; `editorial` / standalone → spec-cell.

**Reserved-slot discipline carries over.** Same rule as `actor-network-graph` and `alerts-rail-section`: if a delta or sparkline cannot be honestly computed (BE doesn't expose the series, or the series is too shallow), omit the slot rather than fabricating a number. The `kpi-cell-delta` and `kpi-cell-sparkline` slots are OPTIONAL by design.

## Page Classes

Current product mapping. The mapping table itself ships in this design contract; the actual route-by-route migrations to PT-1 chrome land in separate per-page PRs (correlation FE first, then existing analyst pages reflowed in follow-up PRs). Editorial and auth pages are explicitly **not migrated** — the page-class taxonomy blocks workspace chrome from crossing into marketing / brand-spec pages, and auth pages stay single-card. (`/dashboard` was previously editorial-page; with this amendment it is `analyst-workspace` and explicitly carries the Dashboard Workspace Pattern, see above.)

| Route | Class | Notes |
|---|---|---|
| `/dashboard` | analyst-workspace | Uses Dashboard Workspace Pattern (new section above). 3-pane composition with section-anchor left rail, KPI + chart-grid center, alerts/recent/drilldown right rail. Editorial dashboard hero is forbidden — see `## Do's and Don'ts > Don't`. The PT-1 three-pane variant for record-list workspaces (reports / incidents / actors, plus future correlation once `/analytics/correlation` is mounted) does NOT apply here; `/dashboard` is the documented exception. |
| `/` | (redirect) | `<Navigate to="/dashboard" replace />` — index redirect, not a routed page. The page class is determined by the destination after redirect. |
| `/login` | auth-page | Single-card on canvas, kept minimal-chrome. Hero NOT required (auth-page class). |
| `/reports`, `/reports/:id` | analyst-workspace | Migrate to PT-1 three-pane in subsequent FE PR (out of design-contract scope). |
| `/incidents`, `/incidents/:id` | analyst-workspace | Same. |
| `/actors`, `/actors/:id` | analyst-workspace | Same. |
| `*` (NotFound, gated under `<RouteGate>` `<Shell>`) | system-page | Inline `<section>` rendered by the router's wildcard route. No PT-1 chrome; currently text-only (heading + paragraph) — a tertiary "Back to dashboard" link is permitted by the `system-page` accent budget but is not present yet. |
| `/analytics/correlation` (next FE PR) | analyst-workspace | The first page authored against the PT-1..PT-7 contract. |
| `/search` (future — not currently routed) | analyst-workspace | The `apps/frontend/src/features/search/` feature directory exists for the search experience accessed via the command palette + inline modal; there is no `/search` route mounted. Listed here as the **target class** if a routed search page is later introduced. The runtime page-class manifest must NOT include `/search` until that route ships. |
| `/admin/*` (future) | admin-workspace | When admin surfaces land. |

## Do's and Don'ts

### Do
- Reserve `{colors.primary}` (Rosso Corsa) for primary CTAs, the Cavallino mark, and F1 race-position highlights.
- Set every CTA at `{rounded.none}` (0px sharp corners) — the brand's signature precision.
- Render CTA labels in uppercase with 1.4px tracking via `{typography.button}`.
- Pair every hero with a full-bleed cinematic photograph — the photograph IS the depth.
- Use the explicit 8px spacing ladder (`xxxs` through `super`) rather than ad-hoc px values.
- Keep display weight at 500 — never bold.

### Don't
- Don't introduce a saturated brand color other than Rosso Corsa.
- Don't use rounded or pill CTAs — sharp 0px corners are the brand button.
- Don't bold display copy. The cinematic photography does the visual heavy-lifting.
- Don't use Hypersail yellow outside the Hypersail sailing program context.
- Don't use pure black canvas. The brand canvas is `{colors.canvas}` (#181818) — slightly warm.
- Don't add drop shadow tiers. Photography + brightness-step elevation carry the depth.
- Don't extract a CTA color from a third-party widget (cookie consent, OneTrust). The brand's CTA color is what appears on actual product CTAs, not on injected modals.
- Don't paint a full row, link, or list item in `{colors.primary}` to indicate active state. Active state on lists / vertical nav uses the PT-5 1px Rosso left-edge stripe; horizontal top-nav active state uses the `top-nav-active-indicator` 2px Rosso bottom-edge stripe. Full Rosso fill stays reserved for the `livery-band` editorial accent and the `button-primary` CTA.
- Don't propagate analyst-workspace density (PT-4 analyst column) onto editorial pages. Marketing and brand surfaces stay at editorial pacing.
- Don't propagate analyst-workspace card chrome (PT-3 detail rail) onto editorial pages or auth pages. Hero bands, `feature-card-photo` stack, and the auth single-card stay full-bleed / single-card and chrome-light.
- Don't soften CTA, hero, livery, or main-card corners to 4px because an analyst-workspace chip or input nearby uses 4px. PT-6 is an analyst-workspace inline exception list; CTAs / hero / cards stay 0px in every page class.
- Don't copy markup, CSS, class names, or assets from any third-party admin template into this codebase. Reference templates inform *information structure only* — every line of code is authored fresh against Ferrari tokens.
- Don't render an editorial dashboard hero on `/dashboard`. The page is `analyst-workspace`-class (see `## Dashboard Workspace Pattern`); the heading row carries the page `<h1>` + `period-readout` only. The pre-existing `DashboardHero` component is deprecated; the implementation PR removes the file and its test.
- Don't render mock SVG, fabricated data, or synthetic graph nodes in production for any reserved/future slot (e.g., `actor-network-graph`). Acceptable production states until the data-wiring PR ships: hide the card entirely, OR render the card with its title + a slot-specific text-only empty state — for `actor-network-graph`, that empty state is exactly `Planned · no data yet`; other reserved/future slots must define their own explicit slot-specific empty-state copy. Sketches and design rehearsals (gitignored, never bundled) may carry mock shapes; the production tree must not.
- Don't make `period-readout` editable. The global FilterBar at the viewport top is the single editable source for the date-range URL state. The heading-row readout is read-only display only — duplicating the input would create a two-surface contract for one URL slot.

## Responsive Behavior

### Breakpoints

| Name | Width | Key Changes |
|---|---|---|
| Mobile | < 640px | Hero photograph crops vertically; hero h1 80→32px; feature card grid 1-up; nav hamburger; preowned listing 1-up. |
| Tablet | 640–1024px | Hero h1 56px; feature card grid 2-up; preowned listing 2-up. |
| Desktop | 1024–1280px | Full hero h1 80px; feature card grid 3-up; preowned listing 4-up. |
| Wide | > 1280px | Editorial body content caps at 1280px; hero photography continues full-bleed. |

### Touch Targets
- Primary CTA at 48px height — at WCAG AAA (44 × 44).
- Nav items render uppercase with 0.65px tracking, padded for an effective 48px tap area.

### Collapsing Strategy
- Top nav switches to hamburger below 768px.
- Hero photograph reframes per breakpoint via art direction — desktop carries wide cinematic; mobile crops tighter or shifts to vertical.
- Feature card grid: 4-up → 3-up → 2-up → 1-up.
- F1 driver cards: 2-up at desktop, 1-up at mobile.

## Iteration Guide

1. Focus on a single component at a time.
2. CTAs default to `{rounded.none}` (0px sharp). Cards use `{rounded.none}` too. Pill is reserved for badges.
3. Variants live as separate entries inside `components:`.
4. Use `{token.refs}` everywhere — never inline hex.
5. Hover state never documented.
6. FerrariSans 500 for display, 400/700 for body. Uppercase + tracking on CTAs and nav.
7. Rosso Corsa stays scarce — primary CTAs, Cavallino, race-position highlights only.
8. Use the explicit 8px named spacing ladder.

## Known Gaps

- FerrariSans is a licensed typeface; Inter at weight 500 is the documented substitute.
- Animation timings (hero parallax, livery band entrance, race position counter) out of scope.
- In-product surfaces (preowned configurator, F1 telemetry overlays) only partially captured via marketing surfaces.
- Form validation states beyond focus not visible on captured surfaces.
- Hypersail yellow tokens are extracted but only appear in the Hypersail sailing program context — documented as scoped accents.
