import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useSimilarReports } from '../useSimilarReports'

// Lifted from BE SimilarReportsResponse example[0].
const HAPPY_BODY = {
  items: [
    {
      report: {
        id: 99,
        title: 'Related Lazarus campaign',
        url: 'https://mandiant.com/blog/lazarus-2025q4',
        published: '2025-12-01',
        source_name: 'Mandiant',
      },
      score: 0.87,
    },
  ],
}

// BE example[1] — plan D10 empty contract (source has no embedding
// OR kNN returned zero rows after self-exclusion).
const EMPTY_BODY = { items: [] }

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

describe('useSimilarReports', () => {
  it('fetches /api/v1/reports/{id}/similar with default k=10 and parses data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useSimilarReports(42), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.items).toHaveLength(1)
    expect(result.current.data?.items[0].score).toBeCloseTo(0.87)

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/reports/42/similar')
    expect(url.searchParams.get('k')).toBe('10')
  })

  it('sends caller-supplied k on the querystring', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useSimilarReports(42, 25), { wrapper: Wrapper })

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('k')).toBe('25')
  })

  // D10 empty contract — the hook must accept `{items: []}` as a
  // valid 200 response without throwing. No fake fallback injection.
  it('parses the D10 empty contract verbatim (no fake fallback)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useSimilarReports(42), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({ items: [] })
    expect(result.current.isError).toBe(false)
  })

  // D8 cache-scope lock — the hook participates in NO filter state;
  // FilterBar toggles must not refetch.
  it('TLP/date/group toggles do NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useSimilarReports(42), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })
    act(() => {
      useFilterStore.setState({ dateFrom: '2026-01-01', dateTo: '2026-04-01' })
    })
    act(() => {
      useFilterStore.getState().toggleGroupId(3)
    })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  // k-change cache-scope — changing k opens a new React Query slot
  // matching the BE Redis cache key `similar_reports:{id}:{k}`.
  it('k change DOES trigger a refetch (new cache scope)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      (props: { k: number }) => useSimilarReports(42, props.k),
      { wrapper: Wrapper, initialProps: { k: 10 } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    rerender({ k: 20 })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const secondUrl = new URL(String(spy.mock.calls[1][0]))
    expect(secondUrl.searchParams.get('k')).toBe('20')
  })

  it('reportId change DOES trigger a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      (props: { id: number }) => useSimilarReports(props.id),
      { wrapper: Wrapper, initialProps: { id: 42 } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    rerender({ id: 43 })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    expect(String(spy.mock.calls[1][0])).toContain('/api/v1/reports/43/similar')
  })

  it('does not fetch when reportId is not a positive integer', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useSimilarReports(0), { wrapper: Wrapper })
    renderHook(() => useSimilarReports(-1), { wrapper: Wrapper })
    renderHook(() => useSimilarReports(Number.NaN), { wrapper: Wrapper })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})
