/**
 * KPICard compact-variant — RED tests (PR 2.5 T1).
 *
 * Component contract per `docs/plans/dashboard-kpi-density.md` L2 / L3 / L7
 * + DESIGN.md `## Dashboard KPI Compact Variant` (added in T6 GREEN):
 *
 *   - Compact typography target: value rendered with `text-3xl`
 *     (~30px) — NOT `text-[80px]`. Aggregate cards (string values
 *     like "Top Group" → "Kimsuky") render at `text-base` or
 *     `text-lg`, also NOT 80px.
 *   - Optional delta indicator slot. Renders when `delta` prop is
 *     present; absent (no `<span>` with delta testid) when `delta`
 *     is null/undefined. Direction-derived sign + color class.
 *   - Optional sparkline slot. Inline `<svg>` with single `<path>`,
 *     ~60×24 viewport. Renders when `sparkline` array has ≥2 points;
 *     absent otherwise.
 *   - Transparent card chrome for populated/empty/loading states.
 *     Error state keeps small card chrome (status callout).
 *
 * RED phase: KPICard.tsx still uses 80px hero typography + has no
 * delta / sparkline subcomponents. T7 GREEN restructures.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { KPICard } from '../KPICard'

describe('KPICard — compact variant typography (PR 2.5 L2)', () => {
  it('populated scalar value uses text-3xl (~30px), NOT text-[80px]', () => {
    render(
      <KPICard label="Total Reports" value={3458} state="populated" />,
    )
    const value = screen.getByTestId('kpi-card-value')
    expect(value.className).toMatch(/\btext-3xl\b/)
    expect(value.className).not.toMatch(/\btext-\[80px\]\b/)
  })

  it('aggregate categorical string (Top Group / Top Motivation) renders at text-lg, NOT scalar text-3xl', () => {
    // Codex PR #34 r1 F3 fold: tighten the assertion. A regression
    // where "Kimsuky" fell back to text-3xl scalar treatment would
    // have passed under the previous permissive regex.
    render(
      <KPICard
        label="Top Group"
        value="Kimsuky"
        subtext="583 reports"
        state="populated"
      />,
    )
    const value = screen.getByTestId('kpi-card-value')
    expect(value.className).not.toMatch(/\btext-\[80px\]\b/)
    expect(value.className).toMatch(/\btext-lg\b/)
    expect(value.className).not.toMatch(/\btext-3xl\b/)
  })

  it('Top Year (numeric-shaped string "2024") stays at scalar text-3xl, NOT text-lg (PR 2.5 numeric exception)', () => {
    // Top Year arrives as a string from KPIStrip (`String(topYear.year)`)
    // but reads as a numeric callout. isAggregateString returns false
    // for digits-only strings, so the scalar text-3xl applies.
    render(
      <KPICard
        label="Top Year"
        value="2024"
        subtext="318 reports"
        state="populated"
      />,
    )
    const value = screen.getByTestId('kpi-card-value')
    expect(value.className).toMatch(/\btext-3xl\b/)
    expect(value.className).not.toMatch(/\btext-lg\b/)
  })

  it('empty state placeholder dash uses the same compact size as populated value', () => {
    render(<KPICard label="Top Group" state="empty" />)
    const value = screen.getByTestId('kpi-card-value')
    expect(value).toHaveTextContent('—')
    expect(value.className).toMatch(/\btext-3xl\b/)
    expect(value.className).not.toMatch(/\btext-\[80px\]\b/)
  })

  it('loading skeleton width matches the compact value column, not the 80px hero footprint', () => {
    render(<KPICard label="Total Reports" state="loading" />)
    const skeleton = screen.getByTestId('kpi-card-skeleton')
    // Skeleton should NOT pin h-[80px] — that footprint is for the
    // global Spec & Race spec-cell pattern, not the dashboard variant.
    expect(skeleton.querySelector('div')?.className ?? '').not.toMatch(
      /\bh-\[80px\]\b/,
    )
  })
})

describe('KPICard — delta indicator slot (PR 2.5 L4)', () => {
  it('renders delta slot when `delta` prop is provided with value', () => {
    render(
      <KPICard
        label="Total Reports"
        value={3458}
        state="populated"
        delta={{ value: 12.5, label: 'vs last year' }}
      />,
    )
    const delta = screen.getByTestId('kpi-card-delta')
    expect(delta).toBeInTheDocument()
    // Delta value formatted with sign + percent
    expect(delta).toHaveTextContent(/\+?12\.5%/)
  })

  it('omits delta slot entirely when `delta` is null or undefined', () => {
    render(
      <KPICard label="Total Actors" value={106} state="populated" delta={null} />,
    )
    expect(screen.queryByTestId('kpi-card-delta')).toBeNull()
  })

  it('delta direction = down when value is negative, with status-warn class', () => {
    render(
      <KPICard
        label="Total Reports"
        value={3458}
        state="populated"
        delta={{ value: -8.3 }}
      />,
    )
    const delta = screen.getByTestId('kpi-card-delta')
    expect(delta).toHaveTextContent(/-8\.3%/)
    expect(delta.className).toMatch(/status-warn|text-status-warn|text-red|destructive/)
  })

  it('delta direction = up when value is positive, with status-ok class', () => {
    render(
      <KPICard
        label="Total Reports"
        value={3458}
        state="populated"
        delta={{ value: 12.5 }}
      />,
    )
    const delta = screen.getByTestId('kpi-card-delta')
    expect(delta).toHaveTextContent(/\+?12\.5%/)
    expect(delta.className).toMatch(/status-ok|text-status-ok|text-green|signal/)
  })

  it('omits delta slot when delta value is exactly 0 (DESIGN.md zero/null collapses slot)', () => {
    // Codex PR #34 r1 F1 fold: zero delta should be treated like
    // null per DESIGN.md `## Dashboard KPI Compact Variant >
    // kpi-cell-delta` — `zero / null omits the slot entirely`. The
    // previous gate (`delta ? ...`) rendered { value: 0 } as
    // "0.0%" which conflicts with the contract.
    render(
      <KPICard
        label="Total Reports"
        value={3458}
        state="populated"
        delta={{ value: 0 }}
      />,
    )
    expect(screen.queryByTestId('kpi-card-delta')).toBeNull()
  })
})

describe('KPICard — sparkline slot (PR 2.5 L5)', () => {
  it('renders inline <svg> with a <path> when `sparkline` has ≥2 points', () => {
    render(
      <KPICard
        label="Total Reports"
        value={3458}
        state="populated"
        sparkline={[10, 20, 15, 30, 28, 40]}
      />,
    )
    const sparkline = screen.getByTestId('kpi-card-sparkline')
    expect(sparkline).toBeInTheDocument()
    expect(sparkline.querySelector('svg')).not.toBeNull()
    expect(sparkline.querySelector('path')).not.toBeNull()
  })

  it('omits sparkline slot when `sparkline` is null or has fewer than 2 points', () => {
    render(
      <KPICard
        label="Total Actors"
        value={106}
        state="populated"
        sparkline={null}
      />,
    )
    expect(screen.queryByTestId('kpi-card-sparkline')).toBeNull()

    // Insufficient series (single point) also degrades gracefully
    render(
      <KPICard
        label="Total Actors"
        value={106}
        state="populated"
        sparkline={[42]}
      />,
    )
    expect(screen.queryByTestId('kpi-card-sparkline')).toBeNull()
  })
})

describe('KPICard — transparent card chrome (PR 2.5 L7)', () => {
  it('populated state has NO border-card / bg-surface chrome (transparent floating cell)', () => {
    render(<KPICard label="Total Reports" value={3458} state="populated" />)
    const card = screen.getByTestId('kpi-card')
    expect(card.className).not.toMatch(/\bborder-border-card\b/)
    expect(card.className).not.toMatch(/\bbg-surface\b/)
  })

  it('error state KEEPS the small card chrome (border + surface bg) — status callout', () => {
    render(<KPICard label="Total Reports" state="error" />)
    const card = screen.getByTestId('kpi-card')
    expect(card.className).toMatch(/\bborder-border-card\b|\bbg-surface\b/)
  })
})
