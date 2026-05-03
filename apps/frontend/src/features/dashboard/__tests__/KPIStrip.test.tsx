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
})
