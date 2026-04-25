import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useIncidentsTrend } from '../useIncidentsTrend'

const HAPPY_MOTIVATION_BODY = {
  buckets: [
    {
      month: '2026-01',
      count: 14,
      series: [
        { key: 'Espionage', count: 9 },
        { key: 'Finance', count: 5 },
      ],
    },
    {
      month: '2026-02',
      count: 16,
      series: [
        { key: 'Espionage', count: 10 },
        { key: 'Finance', count: 4 },
        { key: 'unknown', count: 2 },
      ],
    },
  ],
  group_by: 'motivation' as const,
}

const HAPPY_SECTOR_BODY = {
  buckets: [
    {
      month: '2026-03',
      count: 4,
      series: [
        { key: 'ENE', count: 1 },
        { key: 'FIN', count: 1 },
        { key: 'GOV', count: 2 },
      ],
    },
  ],
  group_by: 'sector' as const,
}

const EMPTY_BODY = { buckets: [], group_by: 'motivation' as const }

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

describe('useIncidentsTrend', () => {
  it('fetches /analytics/incidents_trend with group_by=motivation and parses the response', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(HAPPY_MOTIVATION_BODY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useIncidentsTrend({ groupBy: 'motivation' }),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.group_by).toBe('motivation')
    expect(result.current.data?.buckets).toHaveLength(2)
    expect(spy).toHaveBeenCalledOnce()
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/incidents_trend')
    expect(url.searchParams.get('group_by')).toBe('motivation')
  })

  it('fetches with group_by=sector when invoked with that axis', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(HAPPY_SECTOR_BODY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useIncidentsTrend({ groupBy: 'sector' }),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.group_by).toBe('sector')
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('group_by')).toBe('sector')
  })

  it('forwards date + group filters from the store', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(HAPPY_MOTIVATION_BODY), { status: 200 }),
      )
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [3, 1],
      tlpLevels: [],
    })
    const { Wrapper } = makeWrapper()
    renderHook(() => useIncidentsTrend({ groupBy: 'motivation' }), {
      wrapper: Wrapper,
    })

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.get('date_to')).toBe('2026-04-18')
    expect(url.searchParams.getAll('group_id')).toEqual(['1', '3'])
    expect(url.searchParams.get('group_by')).toBe('motivation')
  })

  it('TLP toggle does NOT cause a refetch (D5 isolation invariant)', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(HAPPY_MOTIVATION_BODY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useIncidentsTrend({ groupBy: 'motivation' }),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('motivation and sector subscribers occupy separate cache slots', async () => {
    // Critical — the two stacked-area widgets MUST NOT share a cache
    // entry, otherwise switching between them flashes the wrong axis.
    const motivationSpy = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(HAPPY_MOTIVATION_BODY), { status: 200 }),
      ),
    )
    const sectorSpy = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(HAPPY_SECTOR_BODY), { status: 200 }),
      ),
    )
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('group_by=sector')) return sectorSpy()
      if (url.includes('group_by=motivation')) return motivationSpy()
      throw new Error(`unexpected request URL: ${url}`)
    })

    const { Wrapper } = makeWrapper()
    const { result: motivation } = renderHook(
      () => useIncidentsTrend({ groupBy: 'motivation' }),
      { wrapper: Wrapper },
    )
    const { result: sector } = renderHook(
      () => useIncidentsTrend({ groupBy: 'sector' }),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(motivation.current.isSuccess).toBe(true))
    await waitFor(() => expect(sector.current.isSuccess).toBe(true))
    expect(motivation.current.data?.group_by).toBe('motivation')
    expect(sector.current.data?.group_by).toBe('sector')
    expect(motivationSpy).toHaveBeenCalledTimes(1)
    expect(sectorSpy).toHaveBeenCalledTimes(1)
  })

  it('parses empty payload verbatim', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useIncidentsTrend({ groupBy: 'motivation' }),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(EMPTY_BODY)
  })
})
