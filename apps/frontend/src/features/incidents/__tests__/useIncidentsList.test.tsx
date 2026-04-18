import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useIncidentsList } from '../useIncidentsList'

const BODY = {
  items: [
    {
      id: 18,
      title: 'Ronin bridge',
      motivations: ['financial'],
      sectors: ['crypto'],
      countries: ['VN'],
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

describe('useIncidentsList', () => {
  it('fetches /incidents with date range from the store', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: null,
      groupIds: [],
      tlpLevels: [],
    })
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useIncidentsList(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.has('date_to')).toBe(false)
  })

  it('group + TLP toggle do NOT refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useIncidentsList(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => useFilterStore.getState().toggleGroupId(3))
    act(() => useFilterStore.getState().toggleTlpLevel('GREEN'))

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
