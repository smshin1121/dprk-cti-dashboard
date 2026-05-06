/**
 * Pure-function helpers for KPIStrip (PR 2.5).
 *
 * Both `computeYoyDelta` and `extractSparklineSeries` consume the
 * same `reports_by_year` shape that `/dashboard/summary` already
 * exposes — no BE schema change is required for this PR. If the
 * series is too shallow (< 2 points) or has a divide-by-zero
 * predecessor, both helpers degrade gracefully to `null`. KPIStrip
 * passes the result into KPICard's optional `delta` and `sparkline`
 * props; null collapses the slot entirely (reserved-slot text-only
 * discipline carried over from PR #33).
 *
 * See `docs/plans/dashboard-kpi-density.md` L4 + L5 for contract
 * boundaries; tests at `__tests__/kpiDeltaUtils.test.ts` (T3 RED).
 */

import type { DashboardYearCount } from '../../lib/api/schemas'

export interface KpiDelta {
  /** Signed percent change. Positive = up, negative = down. */
  readonly value: number
}

/**
 * YoY delta of the latest year vs the immediately preceding year in
 * the input series. Years are picked by VALUE, not array order.
 *
 * Returns null when:
 *   - input has fewer than 2 entries (insufficient resolution)
 *   - the predecessor year has count = 0 (divide-by-zero)
 *
 * Note: "predecessor" = the latest year strictly less than the max
 * year. If years are non-adjacent (e.g. 2020, 2023, 2024), 2023
 * (NOT 2020) is the predecessor when 2024 is the latest.
 */
export function computeYoyDelta(
  byYear: readonly DashboardYearCount[],
): KpiDelta | null {
  if (byYear.length < 2) return null

  // Sort defensively — BE order is not contractually guaranteed.
  const sorted = [...byYear].sort((a, b) => a.year - b.year)
  const latest = sorted[sorted.length - 1]
  const previous = sorted[sorted.length - 2]
  if (previous.count === 0) return null

  const ratio = latest.count / previous.count - 1
  // Round to one decimal place (e.g. +10.8) — matches the test
  // expectation and reads as a stable analyst-glance figure.
  const value = Math.round(ratio * 100 * 10) / 10
  return { value }
}

/**
 * Sparkline data extraction. Returns the count series sorted by year
 * ascending, or null when fewer than 2 entries.
 *
 * Zero counts and duplicate counts are preserved — they are valid
 * data points (e.g. a year with no reports is a real data point,
 * not a missing one). The caller (KPICard sparkline subcomponent) is
 * responsible for normalising the series to the SVG viewport.
 */
export function extractSparklineSeries(
  byYear: readonly DashboardYearCount[],
): readonly number[] | null {
  if (byYear.length < 2) return null
  return [...byYear]
    .sort((a, b) => a.year - b.year)
    .map((entry) => entry.count)
}

/**
 * Map a sparkline series onto an SVG path `d` attribute string.
 * Series is normalized to fill the [0, width] × [0, height] viewport
 * with a small inset on top so a constant series doesn't sit flush
 * against the upper edge.
 *
 * Empty / single-point series return null (caller should hide the
 * sparkline slot in that case — but if the caller passes through,
 * this returns null rather than crashing).
 */
export function buildSparklinePath(
  series: readonly number[],
  width = 60,
  height = 24,
): string | null {
  if (series.length < 2) return null
  const max = Math.max(...series)
  const min = Math.min(...series)
  const span = max - min || 1 // constant series → flat line at midline
  const inset = 2
  const innerHeight = height - inset * 2
  const stepX = width / (series.length - 1)

  const points = series.map((v, i) => {
    const x = i * stepX
    const y = inset + innerHeight - ((v - min) / span) * innerHeight
    return `${x.toFixed(2)},${y.toFixed(2)}`
  })
  return `M${points.join(' L')}`
}
