import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useIncidentDetail } from '../useIncidentDetail'

// Lifted verbatim from BE IncidentDetail example[0].
const HAPPY_BODY = {
  id: 18,
  reported: '2024-05-02',
  title: 'Axie Infinity Ronin bridge exploit',
  description: '620M USD bridge compromise attributed to Lazarus',
  est_loss_usd: 620_000_000,
  attribution_confidence: 'HIGH',
  motivations: ['financial'],
  sectors: ['crypto'],
  countries: ['VN', 'SG'],
  linked_reports: [
    {
      id: 42,
      title: 'Lazarus targets SK crypto exchanges',
      url: 'https://mandiant.com/blog/lazarus-2026q1',
      published: '2026-03-15',
      source_name: 'Mandiant',
    },
  ],
}

// BE example[1] — "incident without source reports yet".
const SPARSE_BODY = {
  id: 99,
  reported: null,
  title: 'Incident without source reports yet',
  description: null,
  est_loss_usd: null,
  attribution_confidence: null,
  motivations: [],
  sectors: [],
  countries: [],
  linked_reports: [],
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

describe('useIncidentDetail', () => {
  it('fetches /api/v1/incidents/{id} and returns parsed data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useIncidentDetail(18), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.id).toBe(18)
    expect(result.current.data?.linked_reports).toHaveLength(1)
    expect(result.current.data?.countries).toEqual(['VN', 'SG'])

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/incidents/18')
    expect(url.search).toBe('')
  })

  it('parses the sparse BE example (all-null + empty-collections)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SPARSE_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useIncidentDetail(99), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.linked_reports).toEqual([])
    expect(result.current.data?.reported).toBeNull()
  })

  it('TLP/date/group toggles do NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useIncidentDetail(18), { wrapper: Wrapper })

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
    renderHook(() => useIncidentDetail(0), { wrapper: Wrapper })
    renderHook(() => useIncidentDetail(-1), { wrapper: Wrapper })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})
