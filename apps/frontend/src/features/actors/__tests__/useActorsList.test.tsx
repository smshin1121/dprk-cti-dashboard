import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useActorsList } from '../useActorsList'

const BODY = {
  items: [
    {
      id: 3,
      name: 'Lazarus Group',
      mitre_intrusion_set_id: 'G0032',
      aka: ['APT38'],
      description: null,
      codenames: [],
    },
  ],
  limit: 50,
  offset: 0,
  total: 1,
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

describe('useActorsList', () => {
  it('fetches /actors with the given pagination', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorsList({ limit: 20, offset: 0 }), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('limit')).toBe('20')
  })

  // BE audit pin: /actors accepts NO filter params. Changing any
  // FilterBar dimension must not cause a refetch.
  it('FilterBar changes (date/group/TLP) do NOT refetch actors', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorsList({ limit: 50, offset: 0 }), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => useFilterStore.getState().setDateRange('2026-01-01', '2026-04-18'))
    act(() => useFilterStore.getState().toggleGroupId(3))
    act(() => useFilterStore.getState().toggleTlpLevel('AMBER'))

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
