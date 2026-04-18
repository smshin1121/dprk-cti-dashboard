import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useDashboardSummary } from '../useDashboardSummary'

const HAPPY_BODY = {
  total_reports: 3,
  total_incidents: 2,
  total_actors: 1,
  reports_by_year: [{ year: 2024, count: 3 }],
  incidents_by_motivation: [{ motivation: 'financial', count: 2 }],
  top_groups: [{ group_id: 3, name: 'Lazarus Group', report_count: 3 }],
}

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

describe('useDashboardSummary', () => {
  it('fetches /dashboard/summary and returns parsed data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useDashboardSummary(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.total_reports).toBe(3)
    expect(spy).toHaveBeenCalledOnce()
  })

  it('sends date_from / date_to / group_id from the filter store', async () => {
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
    const { result } = renderHook(() => useDashboardSummary(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.get('date_to')).toBe('2026-04-18')
    // Canonicalized ascending (Codex R2 regression is permanent)
    expect(url.searchParams.getAll('group_id')).toEqual(['1', '3'])
  })

  // D5 lock at the hook boundary. Toggling TLP MUST NOT invalidate
  // the dashboard cache OR trigger a refetch — if it ever does, either
  // the transform is leaking TLP (breaks the cache key) or the hook
  // selector is subscribing to tlpLevels (spurious re-run). Both
  // would be latent defects that burn rate-limit budget in prod.
  it('TLP toggle does NOT cause a refetch (cache-key + subscription discipline)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useDashboardSummary(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })
    act(() => {
      useFilterStore.getState().toggleTlpLevel('WHITE')
    })

    // Give React Query a microtask window to fire a spurious refetch
    // if the subscription/key contract were broken.
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('group toggle DOES trigger a refetch (new filter set → new cache key)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useDashboardSummary(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.getState().toggleGroupId(3)
    })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
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
    const { result } = renderHook(() => useDashboardSummary(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    // Swap order — same set — must hit the existing cache entry, not
    // issue a second fetch.
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
})
