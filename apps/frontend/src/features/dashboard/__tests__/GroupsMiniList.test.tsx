import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { GroupsMiniList } from '../GroupsMiniList'

const SUMMARY_BODY = {
  total_reports: 10,
  total_incidents: 5,
  total_actors: 3,
  reports_by_year: [],
  incidents_by_motivation: [],
  top_groups: [
    { group_id: 1, name: 'Lazarus Group', report_count: 12 },
    { group_id: 2, name: 'Kimsuky', report_count: 7 },
    { group_id: 3, name: 'Andariel', report_count: 3 },
  ],
}

const EMPTY_GROUPS_BODY = { ...SUMMARY_BODY, top_groups: [] }

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { client, Wrapper }
}

beforeEach(() => {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
})

afterEach(() => vi.restoreAllMocks())

describe('GroupsMiniList — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<GroupsMiniList />, { wrapper: Wrapper })
    expect(screen.getByTestId('groups-mini-list-loading')).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<GroupsMiniList />, { wrapper: Wrapper })
    expect(await screen.findByTestId('groups-mini-list-error')).toBeInTheDocument()
    expect(screen.getByTestId('groups-mini-list-retry')).toBeInTheDocument()
  })

  it('empty state when top_groups is empty', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(EMPTY_GROUPS_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<GroupsMiniList />, { wrapper: Wrapper })
    expect(await screen.findByTestId('groups-mini-list-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('groups-mini-list')).not.toBeInTheDocument()
  })

  it('populated state renders groups in BE-returned order (no client re-sort)', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(SUMMARY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<GroupsMiniList />, { wrapper: Wrapper })
    expect(await screen.findByTestId('groups-mini-list')).toBeInTheDocument()
    const items = screen.getAllByTestId(/^groups-mini-list-item-/)
    expect(items).toHaveLength(3)
    // Order preservation: BE ships desc by report_count — we must
    // not re-sort client-side.
    expect(items[0]).toHaveAttribute('data-group-id', '1')
    expect(items[1]).toHaveAttribute('data-group-id', '2')
    expect(items[2]).toHaveAttribute('data-group-id', '3')
    expect(items[0]).toHaveAttribute('data-report-count', '12')
  })

  it('consumes /api/v1/dashboard/summary (shared cache with KPIStrip/Donut/YearBar)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(SUMMARY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<GroupsMiniList />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/dashboard/summary')
  })
})
