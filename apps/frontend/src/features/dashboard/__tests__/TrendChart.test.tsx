import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { TrendChart } from '../TrendChart'

const HAPPY_BODY = {
  buckets: [
    { month: '2026-01', count: 41 },
    { month: '2026-02', count: 38 },
    { month: '2026-03', count: 47 },
  ],
}

const EMPTY_BODY = { buckets: [] }

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

describe('TrendChart — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<TrendChart />, { wrapper: Wrapper })
    expect(screen.getByTestId('trend-chart-loading')).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<TrendChart />, { wrapper: Wrapper })
    expect(await screen.findByTestId('trend-chart-error')).toBeInTheDocument()
    expect(screen.getByTestId('trend-chart-retry')).toBeInTheDocument()
    // Populated/empty states must NOT leak in.
    expect(screen.queryByTestId('trend-chart')).not.toBeInTheDocument()
    expect(screen.queryByTestId('trend-chart-empty')).not.toBeInTheDocument()
  })

  it('empty state when buckets array is empty', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(EMPTY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<TrendChart />, { wrapper: Wrapper })
    expect(await screen.findByTestId('trend-chart-empty')).toBeInTheDocument()
    // The empty card replaces the chart entirely — no degenerate line.
    expect(screen.queryByTestId('trend-chart')).not.toBeInTheDocument()
    expect(screen.queryByTestId('trend-chart-series')).not.toBeInTheDocument()
  })

  it('populated state renders the series', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(HAPPY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<TrendChart />, { wrapper: Wrapper })
    expect(await screen.findByTestId('trend-chart')).toBeInTheDocument()
    // Empty + error cards must NOT co-render with the populated state.
    expect(screen.queryByTestId('trend-chart-empty')).not.toBeInTheDocument()
    expect(screen.queryByTestId('trend-chart-error')).not.toBeInTheDocument()
  })

  it('consumes /analytics/trend endpoint (not /dashboard/summary)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(HAPPY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<TrendChart />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/trend')
  })
})
