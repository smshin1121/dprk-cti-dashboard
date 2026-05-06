import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { KPIStrip } from '../KPIStrip'

const POPULATED_BODY = {
  total_reports: 1204,
  total_incidents: 154,
  total_actors: 12,
  reports_by_year: [
    { year: 2022, count: 201 },
    { year: 2023, count: 287 },
    { year: 2024, count: 318 },
  ],
  incidents_by_motivation: [
    { motivation: 'financial', count: 81 },
    { motivation: 'espionage', count: 52 },
  ],
  top_groups: [
    { group_id: 3, name: 'Lazarus Group', report_count: 412 },
    { group_id: 5, name: 'Kimsuky', report_count: 287 },
  ],
  top_sectors: [],
  top_sources: [],
}

const EMPTY_BODY = {
  total_reports: 0,
  total_incidents: 0,
  total_actors: 0,
  reports_by_year: [],
  incidents_by_motivation: [],
  top_groups: [],
  top_sectors: [],
  top_sources: [],
}

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={createQueryClient()}>
      {children}
    </QueryClientProvider>
  )
}

beforeEach(() => {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('KPIStrip', () => {
  it('renders exactly 6 cards', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })
    await waitFor(() =>
      expect(screen.getAllByTestId('kpi-card')).toHaveLength(6),
    )
  })

  it('shows all cards in loading state while query is pending', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    render(<KPIStrip />, { wrapper: Wrapper })
    const cards = screen.getAllByTestId('kpi-card')
    expect(cards).toHaveLength(6)
    for (const card of cards) {
      expect(card.getAttribute('aria-busy')).toBe('true')
    }
  })

  it('populates 3 scalar totals with locale-formatted values', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('kpi-card-total-reports')).toHaveTextContent('1,204'),
    )
    expect(screen.getByTestId('kpi-card-total-incidents')).toHaveTextContent('154')
    expect(screen.getByTestId('kpi-card-total-actors')).toHaveTextContent('12')
  })

  it('derives top-year, top-motivation, top-group cards from arrays', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })

    // 2024 has the highest count (318) — NOT the array tail; NOT the
    // last entry by order. KPIStrip picks by max(count).
    await waitFor(() =>
      expect(screen.getByTestId('kpi-card-top-year')).toHaveTextContent('2024'),
    )
    expect(screen.getByTestId('kpi-card-top-year')).toHaveTextContent('318')
    expect(screen.getByTestId('kpi-card-top-motivation')).toHaveTextContent('financial')
    expect(screen.getByTestId('kpi-card-top-motivation')).toHaveTextContent('81')
    expect(screen.getByTestId('kpi-card-top-group')).toHaveTextContent('Lazarus Group')
    expect(screen.getByTestId('kpi-card-top-group')).toHaveTextContent('412')
  })

  it('array-derived cards fall back to empty state when BE arrays are empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })

    // Scalars settle to 0 when BE reports totals=0; this is a
    // populated zero, not an empty state. Use it as the load-
    // completed signal before checking the aggregate cards.
    await waitFor(() =>
      expect(screen.getByTestId('kpi-card-total-reports')).toHaveTextContent('0'),
    )
    expect(screen.getByTestId('kpi-card-top-year')).toHaveTextContent('—')
    expect(screen.getByTestId('kpi-card-top-motivation')).toHaveTextContent('—')
    expect(screen.getByTestId('kpi-card-top-group')).toHaveTextContent('—')
  })

  it('renders error state + a single retry affordance on 500', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getAllByTestId('kpi-card-error-message')).toHaveLength(6),
    )
    // One retry button for the whole strip (D11 — inline retry, no
    // global spinner, and no six separate buttons that each fire a
    // refetch on click).
    const retries = screen.getAllByTestId('kpi-card-retry')
    expect(retries).toHaveLength(1)

    spy.mockResolvedValueOnce(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    await userEvent.setup().click(retries[0])
    await waitFor(() =>
      expect(screen.getByTestId('kpi-card-total-reports')).toHaveTextContent('1,204'),
    )
  })

  // PR 2.5 T2 — RED: KPIStrip layout density
  it('uses the compact-density grid layout (grid-cols-3 lg:grid-cols-6 + gap-4), NOT flex-wrap gap-8', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })
    const strip = await waitFor(() => screen.getByTestId('kpi-strip'))
    // PR 2.5 L6: explicit grid layout per DESIGN.md ## Dashboard KPI
    // Compact Variant. Old `flex flex-wrap gap-8 p-6` produced
    // irregular wrapping with 80px values; the compact variant
    // requires deterministic 3 / 6 column grid + tighter gap.
    expect(strip.className).toMatch(/\bgrid\b/)
    expect(strip.className).toMatch(/\bgrid-cols-3\b/)
    expect(strip.className).toMatch(/\b(?:lg:|md:)?grid-cols-6\b/)
    expect(strip.className).toMatch(/\bgap-(?:3|4)\b/)
    // Anti-assertions: previous flex-wrap pattern must be gone.
    expect(strip.className).not.toMatch(/\bflex-wrap\b/)
    expect(strip.className).not.toMatch(/\bgap-8\b/)
  })

  // PR 2.5 T2 — RED: Total Reports card receives client-side delta
  // computed from reports_by_year (YoY) and a sparkline for the
  // count series. Other cards keep delta/sparkline empty (slot only).
  it('passes YoY delta + sparkline data into the Total Reports card from reports_by_year', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })

    // Wait for the populated state — the value text must be present
    // BEFORE querying the delta + sparkline slots (which only render
    // in `populated` state). waitFor on the testid alone returns as
    // soon as the wrapper is in the DOM, which happens during loading.
    await waitFor(() =>
      expect(screen.getByTestId('kpi-card-total-reports')).toHaveTextContent('1,204'),
    )
    const totalReportsCard = screen.getByTestId('kpi-card-total-reports')
    // YoY computed from reports_by_year:
    //   prev = 287 (2023), curr = 318 (2024) → +10.8%
    const delta = totalReportsCard.querySelector('[data-testid="kpi-card-delta"]')
    expect(delta).not.toBeNull()
    expect(delta?.textContent).toMatch(/\+?(10\.8|10\.7|10\.9)%/)

    const sparkline = totalReportsCard.querySelector(
      '[data-testid="kpi-card-sparkline"]',
    )
    expect(sparkline).not.toBeNull()
    expect(sparkline?.querySelector('svg')).not.toBeNull()
    expect(sparkline?.querySelector('path')).not.toBeNull()
  })

  it('omits delta + sparkline slots on cards with no time-series basis (Total Actors / Top Year / Top Motivation / Top Group)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('kpi-card-total-actors')).toHaveTextContent('12'),
    )
    for (const testid of [
      'kpi-card-total-actors',
      'kpi-card-top-year',
      'kpi-card-top-motivation',
      'kpi-card-top-group',
    ]) {
      const card = screen.getByTestId(testid)
      // Delta slot absent — the BE summary doesn't expose a series
      // for these cards, and inventing one is forbidden by the
      // reserved-slot text-only discipline carried over from PR #33.
      expect(
        card.querySelector('[data-testid="kpi-card-delta"]'),
      ).toBeNull()
      expect(
        card.querySelector('[data-testid="kpi-card-sparkline"]'),
      ).toBeNull()
    }
  })

  // PR 2.5 T2 — RED: graceful empty when reports_by_year has < 2 entries.
  it('renders Total Reports card without delta/sparkline when reports_by_year has fewer than 2 entries', async () => {
    const SHALLOW_BODY = {
      ...POPULATED_BODY,
      reports_by_year: [{ year: 2024, count: 318 }],
    }
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SHALLOW_BODY), { status: 200 }),
    )
    render(<KPIStrip />, { wrapper: Wrapper })
    const card = await waitFor(() =>
      screen.getByTestId('kpi-card-total-reports'),
    )
    expect(
      card.querySelector('[data-testid="kpi-card-delta"]'),
    ).toBeNull()
    expect(
      card.querySelector('[data-testid="kpi-card-sparkline"]'),
    ).toBeNull()
  })
})
