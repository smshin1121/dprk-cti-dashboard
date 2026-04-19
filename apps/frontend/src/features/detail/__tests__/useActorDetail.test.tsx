import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useActorDetail } from '../useActorDetail'

// Lifted verbatim from BE ActorDetail example[0].
const HAPPY_BODY = {
  id: 3,
  name: 'Lazarus Group',
  mitre_intrusion_set_id: 'G0032',
  aka: ['APT38', 'Hidden Cobra'],
  description: 'DPRK-attributed cyber espionage and financially motivated group',
  codenames: ['Andariel', 'Bluenoroff'],
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

describe('useActorDetail', () => {
  it('fetches /api/v1/actors/{id} and returns parsed data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorDetail(3), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.name).toBe('Lazarus Group')
    expect(result.current.data?.codenames).toEqual(['Andariel', 'Bluenoroff'])

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/actors/3')
    expect(url.search).toBe('')
  })

  // D11 FE-side pin — if the BE accidentally leaks any reports-like
  // key on actor detail, Zod strip-mode drops it at the parse
  // boundary. The hook's exposed data therefore CANNOT carry
  // linked_reports / reports / recent_reports — pages built on this
  // hook structurally cannot render an out-of-scope reports panel.
  it('strips out-of-scope reports-like keys at the parse boundary (D11)', async () => {
    const leaky = {
      ...HAPPY_BODY,
      linked_reports: [
        { id: 42, title: 'leak', url: 'x', published: '2026-01-01', source_name: null },
      ],
      reports: [{ id: 99 }],
      recent_reports: [{ id: 100 }],
    }
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(leaky), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorDetail(3), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const data = result.current.data!
    expect(data).not.toHaveProperty('linked_reports')
    expect(data).not.toHaveProperty('reports')
    expect(data).not.toHaveProperty('recent_reports')
  })

  it('TLP/date/group toggles do NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorDetail(3), { wrapper: Wrapper })

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

  it('does not fetch when id is not a positive integer', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useActorDetail(0), { wrapper: Wrapper })
    renderHook(() => useActorDetail(-1), { wrapper: Wrapper })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})
