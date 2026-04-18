import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useReportsList } from '../useReportsList'

const BODY = {
  items: [
    {
      id: 42,
      title: 'Report',
      url: 'https://example.test',
      url_canonical: 'https://example.test',
      published: '2026-03-15',
    },
  ],
  next_cursor: null,
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

afterEach(() => vi.restoreAllMocks())

describe('useReportsList', () => {
  it('fetches /reports with date range from the store', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [],
      tlpLevels: [],
    })
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useReportsList({ limit: 50 }), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.get('date_to')).toBe('2026-04-18')
    expect(url.searchParams.get('limit')).toBe('50')
  })

  it('date range change triggers a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useReportsList(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => useFilterStore.getState().setDateRange('2026-01-01', '2026-04-18'))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })

  // Group + TLP are not part of /reports filter surface. Toggling
  // them must not invalidate the reports cache or fire a refetch.
  it('group + TLP toggle do NOT refetch (BE audit pin)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useReportsList(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => useFilterStore.getState().toggleGroupId(3))
    act(() => useFilterStore.getState().toggleTlpLevel('AMBER'))

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('cursor change triggers a refetch with the new cursor', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      ({ cursor }: { cursor?: string }) => useReportsList({ cursor }),
      { wrapper: Wrapper, initialProps: { cursor: undefined } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    rerender({ cursor: 'next-abc' })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const second = new URL(String(spy.mock.calls[1][0]))
    expect(second.searchParams.get('cursor')).toBe('next-abc')
  })
})
