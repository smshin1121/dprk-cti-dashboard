/**
 * Ferrari + Tol-derived chart palette (L3 part 2).
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
 * WCAG non-text contrast (1.4.11)
 * -------------------------------
 * The Ferrari surface tier is canvas-app (#181818) and
 * canvas-elevated (#303030). All chart series colors below MUST
 * pass WCAG 1.4.11's 3:1 contrast floor against canvas-elevated
 * (the harder of the two surfaces) so chart marks stay legible.
 * Translucent fills (e.g. IncidentsStackedArea fillOpacity 0.90)
 * mix with the underlying surface — the per-color contrast values
 * below are computed against the OPAQUE color. Rose (slot 3) is
 * the worst-case slot for alpha blending: at fillOpacity 0.80 it
 * computes to 2.81:1 (FAIL), at the 0.85046 inflection point it
 * just touches 3.0:1, at 0.90 it computes to 3.19:1 (PASS with
 * margin). Consumers using fillOpacity MUST set alpha >= 0.90 to
 * preserve the floor across all 9 slots; lower alphas crash rose
 * and other warm slots below WCAG 3:1.
 *
 * Tol Muted's canonical hex set was the reference (Paul Tol §SRON
 * Qualitative > Muted, https://personal.sron.nl/~pault/), but
 * Tol Muted is calibrated for white backgrounds. Slots 4-8 of the
 * canonical order (purple, olive, green, wine, indigo) all FAIL
 * 3:1 against canvas-elevated. So this palette keeps the four
 * Tol Muted hues that pass dark-canvas contrast, adds Tol grey,
 * and rounds out slots 5-8 with custom muted hues tuned for
 * dark-canvas legibility while staying consistent with the
 * Ferrari editorial-restraint aesthetic.
 *
 * No Rosso Corsa (#da291c) and no Hypersail Yellow (#fff200)
 * appear here — those are reserved per plan §0.1 invariant 3
 * (Rosso Corsa scarce; Hypersail = focus ring only). Warm rose
 * #CC6677 sits at slot 3 — it is NOT Rosso Corsa-adjacent: pinker,
 * lower saturation, distinct hue family.
 *
 * Ferrari semantic chrome
 * -----------------------
 * Grid lines, axis labels, tooltips use Ferrari tokens (mapped to
 * literals here for Recharts string-prop consumption). These
 * literals MUST stay in sync with the corresponding tokens in
 * styles/tokens.css when a color is updated upstream.
 */

/**
 * Ferrari dark-canvas qualitative palette — 9 colors, ordered by
 * use frequency. All slots pass WCAG 1.4.11 3:1 against
 * canvas-elevated (#303030).
 *
 * Index assignment (in-bracket number is contrast vs #303030 via
 * sRGB linearization per WCAG 1.4.11; verified by Codex r4):
 *  0: cyan      #88CCEE [7.5:1] — Tol Muted; primary single-series
 *  1: sand      #DDCC77 [8.2:1] — Tol Muted; warm second series
 *  2: teal      #44AA99 [4.7:1] — Tol Muted; cool third series
 *  3: rose      #CC6677 [3.6:1] — Tol Muted; warm rose (NOT Rosso Corsa)
 *  4: grey      #BBBBBB [6.9:1] — Tol grey; neutral fallback
 *  5: lavender  #BB99FF [5.7:1] — custom; cool purple alternative
 *  6: chartreuse #99CC88 [7.1:1] — custom; lighter green alternative
 *  7: tan       #BBAA99 [5.9:1] — custom; warm beige
 *  8: blue-grey #88AABB [5.4:1] — custom; cool blue-grey
 *
 * Slots 5-8 are custom hues (NOT canonical Tol Muted) tuned for
 * dark-canvas contrast. The canonical Tol Muted slots they replace
 * (purple/olive/green/wine/indigo) all fail 3:1 against
 * canvas-elevated and are intentionally excluded.
 */
export const CHART_SERIES = [
  '#88CCEE', // cyan      (Tol Muted)
  '#DDCC77', // sand      (Tol Muted)
  '#44AA99', // teal      (Tol Muted)
  '#CC6677', // rose      (Tol Muted)
  '#BBBBBB', // grey      (Tol)
  '#BB99FF', // lavender  (custom dark-canvas)
  '#99CC88', // chartreuse (custom dark-canvas)
  '#BBAA99', // tan       (custom dark-canvas)
  '#88AABB', // blue-grey (custom dark-canvas)
] as const

/** Backward-compatibility alias for the old `TOL_MUTED` name. */
export const TOL_MUTED = CHART_SERIES

/**
 * Cyclic series-color picker for Recharts <Area>/<Bar>/<Line> children.
 * Wraps `index % CHART_SERIES.length` so palettes longer than 9
 * series still render — the palette repeats from cyan at index 9.
 */
export function chartSeriesColor(index: number): string {
  return CHART_SERIES[index % CHART_SERIES.length]
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
