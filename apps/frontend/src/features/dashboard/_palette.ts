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
 * Tol Muted qualitative palette — 9 colors, ordered for series indexing.
 *
 * Index assignment (canonical):
 *  0: indigo  #332288
 *  1: cyan    #88CCEE
 *  2: teal    #44AA99
 *  3: green   #117733
 *  4: olive   #999933
 *  5: sand    #DDCC77
 *  6: rose    #CC6677
 *  7: wine    #882255
 *  8: purple  #AA4499
 */
export const TOL_MUTED = [
  '#332288', // indigo
  '#88CCEE', // cyan
  '#44AA99', // teal
  '#117733', // green
  '#999933', // olive
  '#DDCC77', // sand
  '#CC6677', // rose
  '#882255', // wine
  '#AA4499', // purple
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
