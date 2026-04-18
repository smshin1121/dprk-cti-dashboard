import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { YearBar } from '../YearBar'

const SUMMARY_BODY = {
  total_reports: 3,
  total_incidents: 0,
  total_actors: 0,
  reports_by_year: [
    { year: 2024, count: 3 },
    { year: 2022, count: 1 },
    { year: 2023, count: 2 },
  ],
  incidents_by_motivation: [],
  top_groups: [],
}

const EMPTY_YEAR_BODY = { ...SUMMARY_BODY, reports_by_year: [] }

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

afterEach(() => {
  vi.restoreAllMocks()
})

describe('YearBar', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<YearBar />, { wrapper: Wrapper })
    expect(screen.getByTestId('year-bar-loading')).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<YearBar />, { wrapper: Wrapper })
    expect(await screen.findByTestId('year-bar-error')).toBeInTheDocument()
    expect(screen.getByTestId('year-bar-retry')).toBeInTheDocument()
  })

  it('empty state when reports_by_year is empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_YEAR_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<YearBar />, { wrapper: Wrapper })
    expect(await screen.findByTestId('year-bar-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('year-bar')).not.toBeInTheDocument()
  })

  it('populated state renders bar chart', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<YearBar />, { wrapper: Wrapper })
    expect(await screen.findByTestId('year-bar')).toBeInTheDocument()
  })

  it('uses /api/v1/dashboard/summary (shares cache with KPIStrip/MotivationDonut)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<YearBar />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/dashboard/summary')
  })
})
