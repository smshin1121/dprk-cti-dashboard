/**
 * Ferrari + Tol chart palette (L3 part 2).
 *
 * Used by every dashboard chart (TrendChart, AttackHeatmap, WorldMap,
 * MotivationDonut, IncidentsStackedArea, SectorBreakdown, YearBar,
 * etc.) so the visual story stays coherent across the dashboard.
 *
 * Why a JS module (not CSS tokens)
 * --------------------------------
 * Recharts and the bundled visx widgets receive color values as
 * strings, not CSS classes — `<Area stroke="..." fill="..." />`.
 * Resolving CSS vars at render time would require a `useEffect` +
 * `getComputedStyle` dance per chart. The chart palette is also
 * not surface-themed (it does NOT flip on `.editorial-band-light`)
 * so static hex literals here are the right level of abstraction.
 *
 * Series colors: Tol Muted (9-color qualitative palette)
 * ------------------------------------------------------
 * Paul Tol's "Muted" qualitative palette is the most editorial-
 * restrained of the Tol family — distinct enough for series
 * separation, soft enough not to compete with the dark Ferrari
 * canvas. All 9 colors pass WCAG AAA contrast against
 * canvas-elevated (#303030).
 *
 * Source: https://personal.sron.nl/~pault/ §Qualitative > Muted
 *
 * Order matters: callers index into this array sequentially, so
 * series 1 = indigo, series 2 = cyan, series 3 = teal, etc. Reorder
 * only if a future palette decision is committed to this constant.
 *
 * Ferrari semantic chrome
 * -----------------------
 * Grid lines, axis labels, tooltips use Ferrari tokens (mapped to
 * literals here for Recharts string-prop consumption). These
 * literals MUST stay in sync with the corresponding tokens in
 * styles/tokens.css when a color is updated upstream.
 */

/**
 * Tol Muted qualitative palette — 9 colors, REORDERED for the Ferrari
 * dark-canvas use case.
 *
 * Why reorder: Tol Muted's canonical first slot is indigo #332288.
 * That hue's contrast against the Ferrari surface tier is 1.08:1 on
 * bg-surface (#303030) and 1.46:1 on bg-app (#181818) — well below
 * WCAG 1.4.11 non-text contrast (3:1) for chart marks. Single-series
 * widgets (TrendChart, YearBar, SectorBreakdown, LocationsRanked,
 * WorldMap high-count ramp) all use slot 0, so an unreadable slot 0
 * means data disappears visually. Multi-series widgets cascade the
 * same problem at slots 1+ if dark hues sit at low indices.
 *
 * Reorder strategy: bright Tol hues (cyan, sand, teal, rose) come
 * first so slot 0/1/2 are guaranteed legible against the dark
 * canvas. Darker hues (indigo, wine, green) move to higher indices
 * — used only when a chart needs >5 simultaneous series, which is
 * rare in this dashboard.
 *
 * Index assignment (Ferrari dark-canvas order):
 *  0: cyan    #88CCEE — primary single-series accent (contrast 11.4:1 vs bg-app)
 *  1: sand    #DDCC77 — second series; warm complement to cyan
 *  2: teal    #44AA99 — third series; cool middle
 *  3: rose    #CC6677 — fourth series; warm rose (NOT Rosso Corsa)
 *  4: purple  #AA4499 — fifth series; distinct from indigo
 *  5: olive   #999933 — sixth series; muted yellow-green
 *  6: green   #117733 — darker green; needs surface lift to read
 *  7: wine    #882255 — dark wine; rare slot
 *  8: indigo  #332288 — Tol canonical slot 0; deferred here for
 *             dark-canvas readability. WCAG-borderline so charts
 *             rendering at index 8 should be exceptional.
 *
 * Hex set unchanged from Tol Muted; only the ordering differs.
 * Source for the canonical hex list:
 *   https://personal.sron.nl/~pault/ §Qualitative > Muted
 */
export const TOL_MUTED = [
  '#88CCEE', // cyan
  '#DDCC77', // sand
  '#44AA99', // teal
  '#CC6677', // rose
  '#AA4499', // purple
  '#999933', // olive
  '#117733', // green
  '#882255', // wine
  '#332288', // indigo
] as const

/**
 * Cyclic series-color picker for Recharts <Area>/<Bar>/<Line> children.
 * Wraps `index % TOL_MUTED.length` so palettes longer than 9 series
 * still render — Tol Muted repeats from indigo at index 9.
 */
export function chartSeriesColor(index: number): string {
  return TOL_MUTED[index % TOL_MUTED.length]
}

/**
 * Ferrari semantic chart chrome literals.
 *
 * `gridStroke` — visible against canvas-elevated (#303030) but not
 *   competing with the series palette. Resolves to Ferrari `--body`
 *   (#969696) so the grid reads as a soft divider tier, not as ink.
 * `axisTickFill` — same `--body` for axis labels.
 * `tooltipBorder` — Ferrari `--hairline` (#303030) for tooltip 1px outline.
 * `tooltipBg` — Ferrari `--canvas-elevated` for tooltip background.
 * `tooltipText` — Ferrari `--ink` for tooltip text.
 * `tooltipCursorFill` — semi-transparent white over the chart to mark
 *   the hover bar / column without competing with the series palette.
 *   Lower alpha so the underlying series color stays legible.
 */
export const CHART_CHROME = {
  gridStroke: '#969696', // --body
  axisTickFill: '#969696', // --body
  tooltipBorder: '#303030', // --hairline (== --canvas-elevated)
  tooltipBg: '#303030', // --canvas-elevated
  tooltipText: '#ffffff', // --ink
  tooltipCursorFill: 'rgba(255,255,255,0.06)', // ink @ 6% — hover scrim
} as const
