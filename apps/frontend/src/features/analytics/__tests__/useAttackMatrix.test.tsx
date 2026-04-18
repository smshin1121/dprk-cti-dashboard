import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useAttackMatrix } from '../useAttackMatrix'

const HAPPY_BODY = {
  tactics: [
    { id: 'TA0001', name: 'TA0001' },
    { id: 'TA0002', name: 'TA0002' },
  ],
  rows: [
    {
      tactic_id: 'TA0001',
      techniques: [
        { technique_id: 'T1566', count: 3 },
        { technique_id: 'T1190', count: 1 },
      ],
    },
    {
      tactic_id: 'TA0002',
      techniques: [{ technique_id: 'T1059', count: 2 }],
    },
  ],
}

const EMPTY_BODY = { tactics: [], rows: [] }

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

describe('useAttackMatrix', () => {
  it('fetches /analytics/attack_matrix and returns parsed data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useAttackMatrix(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.tactics).toHaveLength(2)
    expect(result.current.data?.rows[0].techniques[0].count).toBe(3)
    expect(spy).toHaveBeenCalledOnce()
  })

  it('sends date_from / date_to / group_id / top_n from store + options', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [3, 1],
      tlpLevels: [],
    })
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useAttackMatrix({ top_n: 50 }), {
      wrapper: Wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/attack_matrix')
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.get('date_to')).toBe('2026-04-18')
    // groupIds canonicalized ascending (shared transform with dashboard)
    expect(url.searchParams.getAll('group_id')).toEqual(['1', '3'])
    expect(url.searchParams.get('top_n')).toBe('50')
  })

  it('omits top_n when not provided (BE default=30 applies)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useAttackMatrix(), { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.has('top_n')).toBe(false)
  })

  // D4 lock at the hook boundary — carries the PR #12 Group E
  // pattern. Toggling TLP must not invalidate the analytics cache
  // OR fire a refetch; the hook subscribes to primitive fields only
  // and `AnalyticsFilters` has no tlp field.
  it('TLP toggle does NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useAttackMatrix(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })
    act(() => {
      useFilterStore.getState().toggleTlpLevel('WHITE')
    })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('produces stable cache key for equivalent group sets toggled in different order', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    useFilterStore.setState({
      dateFrom: null,
      dateTo: null,
      groupIds: [1, 3],
      tlpLevels: [],
    })
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useAttackMatrix(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.setState({
        dateFrom: null,
        dateTo: null,
        groupIds: [3, 1],
        tlpLevels: [],
      })
    })
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('top_n change DOES trigger a refetch (new cache scope)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      (props: { topN: number }) => useAttackMatrix({ top_n: props.topN }),
      { wrapper: Wrapper, initialProps: { topN: 30 } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    rerender({ topN: 100 })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })

  // Empty-payload pass-through — plan D8 empty-state UX depends on
  // the hook returning a well-formed empty shape, not throwing.
  it('parses empty payload verbatim (viz owns empty-state card)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useAttackMatrix(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(EMPTY_BODY)
    expect(result.current.isError).toBe(false)
  })
})
