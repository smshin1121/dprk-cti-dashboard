/**
 * kpiDeltaUtils — RED tests (PR 2.5 T3).
 *
 * Pure-function utility tests for the client-side delta + sparkline
 * computation helpers consumed by KPIStrip. Mirrors PR #33's pattern
 * of extracting computation from the rendering component so it can
 * be exercised in isolation without rendering overhead.
 *
 * Contract per `docs/plans/dashboard-kpi-density.md` L4:
 *   - `computeYoyDelta(byYear)` returns null when fewer than 2 years.
 *   - When 2+ years: delta = (latest.count - previous.count) / previous.count
 *     × 100, with prev = the year before latest, NOT the array tail.
 *     Returns { value: number } where value is signed (positive =
 *     up, negative = down).
 *   - `extractSparklineSeries(byYear)` returns the count array sorted
 *     by year ascending; returns null when fewer than 2 entries.
 *
 * RED phase: kpiDeltaUtils.ts does not exist yet. T9 GREEN.
 */

import { describe, expect, it } from 'vitest'

import {
  buildSparklinePath,
  computeYoyDelta,
  extractSparklineSeries,
} from '../kpiDeltaUtils'

describe('computeYoyDelta — YoY delta percent (PR 2.5 L4)', () => {
  it('returns null when input array is empty', () => {
    expect(computeYoyDelta([])).toBeNull()
  })

  it('returns null when input array has only 1 entry (insufficient resolution)', () => {
    expect(computeYoyDelta([{ year: 2024, count: 318 }])).toBeNull()
  })

  it('returns positive delta when latest > previous', () => {
    const result = computeYoyDelta([
      { year: 2023, count: 287 },
      { year: 2024, count: 318 },
    ])
    expect(result).not.toBeNull()
    // 318 / 287 - 1 = 0.108
    expect(result!.value).toBeCloseTo(10.8, 1)
  })

  it('returns negative delta when latest < previous', () => {
    const result = computeYoyDelta([
      { year: 2023, count: 287 },
      { year: 2024, count: 200 },
    ])
    expect(result).not.toBeNull()
    expect(result!.value).toBeLessThan(0)
    // 200 / 287 - 1 ≈ -0.303
    expect(result!.value).toBeCloseTo(-30.3, 1)
  })

  it('selects the latest year by year value, NOT array tail order', () => {
    // Unsorted input — latest year is 2024 (count 318) regardless of
    // array ordering. Previous year is 2023 (count 287).
    const result = computeYoyDelta([
      { year: 2024, count: 318 },
      { year: 2022, count: 201 },
      { year: 2023, count: 287 },
    ])
    expect(result).not.toBeNull()
    expect(result!.value).toBeCloseTo(10.8, 1)
  })

  it('returns null when previous year has count = 0 (avoids divide-by-zero)', () => {
    expect(
      computeYoyDelta([
        { year: 2023, count: 0 },
        { year: 2024, count: 318 },
      ]),
    ).toBeNull()
  })

  it('handles non-adjacent years by picking the IMMEDIATELY preceding year, not just any earlier year', () => {
    // Latest = 2024. Previous-by-year-value should be 2023 (NOT 2020).
    const result = computeYoyDelta([
      { year: 2020, count: 100 },
      { year: 2023, count: 287 },
      { year: 2024, count: 318 },
    ])
    expect(result).not.toBeNull()
    // Uses 2023 (287), not 2020 (100).
    expect(result!.value).toBeCloseTo(10.8, 1)
  })
})

describe('extractSparklineSeries — sparkline data extraction (PR 2.5 L5)', () => {
  it('returns null for empty input', () => {
    expect(extractSparklineSeries([])).toBeNull()
  })

  it('returns null for single-entry input (sparkline needs ≥2 points)', () => {
    expect(
      extractSparklineSeries([{ year: 2024, count: 318 }]),
    ).toBeNull()
  })

  it('returns count array sorted by year ascending', () => {
    const result = extractSparklineSeries([
      { year: 2024, count: 318 },
      { year: 2022, count: 201 },
      { year: 2023, count: 287 },
    ])
    expect(result).toEqual([201, 287, 318])
  })

  it('preserves duplicate counts and zero counts in the series', () => {
    const result = extractSparklineSeries([
      { year: 2021, count: 0 },
      { year: 2022, count: 100 },
      { year: 2023, count: 100 },
    ])
    expect(result).toEqual([0, 100, 100])
  })
})

describe('buildSparklinePath — SVG path string (PR 2.5 r1 F4)', () => {
  it('returns null for empty / single-point series (caller should hide slot)', () => {
    expect(buildSparklinePath([])).toBeNull()
    expect(buildSparklinePath([42])).toBeNull()
  })

  it('returns a path string starting with M for ≥2 points', () => {
    const path = buildSparklinePath([1, 5, 3, 8])
    expect(path).not.toBeNull()
    expect(path!.startsWith('M')).toBe(true)
    // Each point separated by space + L: M..., L..., L..., L...
    expect(path!.match(/L/g)).toHaveLength(3)
  })

  it('constant series renders flat at the midline (NOT collapsed to bottom inset)', () => {
    // Codex PR #34 r1 F4 fold: previous max-min || 1 fallback
    // pushed every point to the bottom edge (y=22 for 60×24);
    // the contract reads as "flat line at midline" so the
    // special-case midline render is the correct behavior.
    const path = buildSparklinePath([5, 5, 5], 60, 24)
    expect(path).not.toBeNull()
    // Midline = inset + innerHeight / 2 = 2 + (24 - 4)/2 = 12.0
    // Every point should sit at y = 12.0.
    const yCoords = path!.match(/\d+\.\d+,(\d+\.\d+)/g)?.map((s) => s.split(',')[1])
    expect(yCoords).toEqual(['12.00', '12.00', '12.00'])
    // Anti-assertion: NOT at the bottom inset (y = 22.00 for 60×24).
    expect(path).not.toContain('22.00')
  })

  it('non-constant series spans the inset-padded inner viewport', () => {
    const path = buildSparklinePath([0, 10], 60, 24)
    expect(path).not.toBeNull()
    // First point (min=0) sits at the bottom inset boundary
    // (y = inset + innerHeight = 2 + 20 = 22.00).
    // Last point (max=10) sits at the top inset (y = 2.00).
    expect(path).toContain('22.00')
    expect(path).toContain('2.00')
  })
})
