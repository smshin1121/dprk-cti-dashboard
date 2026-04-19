import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useReportDetail } from '../useReportDetail'

// Lifted verbatim from BE ReportDetail example[0] in
// services/api/src/api/schemas/read.py (examples section of the
// Pydantic model). When the BE example changes, this test fires
// first — the exact signal plan D7 relies on until OpenAPI→Zod
// codegen lands.
const HAPPY_BODY = {
  id: 42,
  title: 'Lazarus targets South Korean crypto exchanges',
  url: 'https://mandiant.com/blog/lazarus-2026q1',
  url_canonical: 'https://mandiant.com/blog/lazarus-2026q1',
  published: '2026-03-15',
  source_id: 7,
  source_name: 'Mandiant',
  lang: 'en',
  tlp: 'WHITE',
  summary: 'Operation targeting crypto exchanges in Q1 2026.',
  reliability: 'A',
  credibility: '2',
  tags: ['ransomware', 'finance'],
  codenames: ['Andariel'],
  techniques: ['T1566', 'T1190'],
  linked_incidents: [
    { id: 18, title: 'Axie Infinity Ronin bridge exploit', reported: '2024-05-02' },
  ],
}

// BE example[1] — the "single report without incident link" shape
// (all nullable fields null, all collections empty).
const SPARSE_BODY = {
  id: 7,
  title: 'Single report without incident link',
  url: 'https://example.test/r/7',
  url_canonical: 'https://example.test/r/7',
  published: '2026-01-10',
  source_id: null,
  source_name: null,
  lang: 'en',
  tlp: 'WHITE',
  summary: null,
  reliability: null,
  credibility: null,
  tags: [],
  codenames: [],
  techniques: [],
  linked_incidents: [],
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

describe('useReportDetail', () => {
  it('fetches /api/v1/reports/{id} and returns parsed data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useReportDetail(42), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.id).toBe(42)
    expect(result.current.data?.linked_incidents).toHaveLength(1)
    expect(result.current.data?.tags).toEqual(['ransomware', 'finance'])

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/reports/42')
    // No filter querystring — detail endpoint takes only the path-param id.
    expect(url.search).toBe('')
  })

  it('parses the sparse BE example (all-null + empty-collections)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SPARSE_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useReportDetail(7), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.linked_incidents).toEqual([])
    expect(result.current.data?.source_id).toBeNull()
  })

  // D1 + D11 subscription lock — detail hook has NO useFilterStore
  // subscription. A TLP/date/group change must not fire a refetch OR
  // invalidate the cache.
  it('TLP/date/group toggles do NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useReportDetail(42), { wrapper: Wrapper })

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

  it('id change DOES trigger a refetch (new cache scope)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      (props: { id: number }) => useReportDetail(props.id),
      { wrapper: Wrapper, initialProps: { id: 42 } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    rerender({ id: 43 })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    expect(String(spy.mock.calls[1][0])).toContain('/api/v1/reports/43')
  })

  it('does not fetch when id is not a positive integer (enable guard)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useReportDetail(0), { wrapper: Wrapper })
    renderHook(() => useReportDetail(-1), { wrapper: Wrapper })
    renderHook(() => useReportDetail(Number.NaN), { wrapper: Wrapper })

    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})
