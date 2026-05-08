/**
 * useCorrelationSeries hook tests (PR-B T5).
 *
 * Pins:
 *   - Catalog fetch path + parse.
 *   - Empty series list parses correctly (BE returns zero rows when
 *     DB is empty).
 *   - `staleTime: Infinity` (umbrella §8.7, plan §B3).
 *   - Single shared cache slot — N consumers share 1 fetch
 *     (`pattern_shared_query_cache_multi_subscriber`).
 *   - No `useFilterStore` subscription — TLP / date / group toggles
 *     do not affect this cache.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../../lib/queryClient'
import { useFilterStore } from '../../../../stores/filters'
import { useCorrelationSeries } from '../useCorrelationSeries'

const HAPPY_CATALOG = {
  series: [
    {
      id: 'reports.total',
      label_ko: '보고서 총수',
      label_en: 'Total reports',
      root: 'reports.published',
      bucket: 'monthly',
    },
    {
      id: 'incidents.total',
      label_ko: '사건 총수',
      label_en: 'Total incidents',
      root: 'incidents.reported',
      bucket: 'monthly',
    },
  ],
}

const EMPTY_CATALOG = { series: [] }

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

describe('useCorrelationSeries', () => {
  it('GETs /analytics/correlation/series and returns parsed catalog', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.series).toHaveLength(2)
    expect(result.current.data?.series[0].id).toBe('reports.total')

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/correlation/series')
    expect(url.search).toBe('')
  })

  it('parses empty series list (DB empty case)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_CATALOG), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.series).toEqual([])
  })

  // Plan §B3 + umbrella §8.7 — catalog never stales within a session;
  // single fetch on first subscriber serves all consumers.
  it('staleTime is Infinity (catalog never re-fetches)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
    )
    const { client, Wrapper } = makeWrapper()
    const { result } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const queries = client.getQueryCache().getAll()
    const catalogQuery = queries.find(
      (q) =>
        Array.isArray(q.queryKey)
        && q.queryKey[0] === 'analytics'
        && q.queryKey[1] === 'correlation'
        && q.queryKey[2] === 'series',
    )
    expect(
      catalogQuery,
      'no correlation catalog entry in query cache — query key not formed correctly',
    ).toBeDefined()
    expect(catalogQuery?.options.staleTime).toBe(Infinity)
  })

  // `pattern_shared_query_cache_multi_subscriber` — three consumers
  // (X dropdown + Y dropdown + chart caption) share one cache slot.
  // Pinned at the hook level by mounting the hook twice in the same
  // QueryClient and asserting exactly one fetch.
  it('multiple subscribers share one fetch (cache slot reuse)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()

    // Subscriber 1 — fires the fetch.
    const { result: r1 } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(r1.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    // Subscribers 2 + 3 — read from cache; no new fetch.
    const { result: r2 } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })
    const { result: r3 } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(r2.current.isSuccess).toBe(true))
    await waitFor(() => expect(r3.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  // No `useFilterStore` subscription — TLP / date / group toggles must
  // not affect this hook. Defensive belt against a future edit wiring
  // the global store.
  it('TLP toggle does NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('surfaces 5xx as isError (no silent retry)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'internal' }), { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useCorrelationSeries(), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
