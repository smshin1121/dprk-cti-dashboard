import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useActorReports } from '../useActorReports'

// Lifted from the BE pact populated fixture (Group C).
const HAPPY_BODY = {
  items: [
    {
      id: 999050,
      title: 'Pact fixture — actor reports #1 (newest)',
      url: 'https://pact.test/actor-reports/999050',
      url_canonical: 'https://pact.test/actor-reports/999050',
      published: '2026-03-15',
      source_id: 1,
      source_name: 'Vendor A',
      lang: 'en',
      tlp: 'WHITE',
    },
  ],
  next_cursor: null,
}

const EMPTY_BODY = { items: [], next_cursor: null }

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

describe('useActorReports', () => {
  it('fetches /api/v1/actors/{id}/reports and returns parsed data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorReports(999003), {
      wrapper: Wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.items).toHaveLength(1)
    expect(result.current.data?.items[0].id).toBe(999050)
    expect(result.current.data?.next_cursor).toBeNull()

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/actors/999003/reports')
  })

  // D15 empty — panel-friendly shape passes through unchanged.
  it('passes D15 empty contract through to the consumer', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorReports(999004), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(EMPTY_BODY)
  })

  // D13 subscription lock — no FilterBar state. TLP / groupIds /
  // dateFrom toggles must NOT refetch. The hook only re-keys on its
  // arguments (actorId, filters, pagination).
  it('TLP / groupIds toggles do NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorReports(999003), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })
    act(() => {
      useFilterStore.getState().toggleGroupId(3)
    })
    act(() => {
      useFilterStore.setState({ dateFrom: '2026-01-01' })
    })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  // Enable guard — invalid actor id never fires the request, so a
  // route that reaches this hook with malformed path params does
  // not emit a 404-prone GET on mount.
  it('does not fetch when actorId is not a positive integer', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useActorReports(0), { wrapper: Wrapper })
    renderHook(() => useActorReports(-1), { wrapper: Wrapper })
    renderHook(() => useActorReports(Number.NaN), { wrapper: Wrapper })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })

  // Different arguments → different cache entries (and hence
  // different fetches). Proves the queryKey actually carries the
  // args it should.
  it('different filters produce distinct fetches for the same actorId', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(
      () => useActorReports(999003, { date_from: '2026-01-01' }),
      { wrapper: Wrapper },
    )
    renderHook(
      () => useActorReports(999003, { date_from: '2026-02-01' }),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const urls = spy.mock.calls.map((c) => new URL(String(c[0])))
    expect(urls[0].searchParams.get('date_from')).toBe('2026-01-01')
    expect(urls[1].searchParams.get('date_from')).toBe('2026-02-01')
  })
})
