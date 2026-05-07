/**
 * useActorNetwork hook tests (PR 3 T3 RED batch).
 *
 * Mirrors the canonical `useAttackMatrix.test.tsx` pattern, with
 * actor-network-specific pins:
 *
 *   - Three per-instance options: `top_n_actor` / `top_n_tool` /
 *     `top_n_sector` (all bounded BE-side to [1, 200], BE default 25).
 *   - Edge field names: `source_id` / `target_id` (NOT `source` /
 *     `target` — the BE DTO at `services/api/src/api/schemas/read.py`
 *     pins this).
 *   - `cap_breached: bool = false` default applied client-side via
 *     zod schema's `.default(false)` — when omitted by BE, FE still
 *     gets `false`.
 *   - Cache key isolated from `summarySharedCache` (plan §7 AC #6 +
 *     memory `pattern_shared_cache_test_extension`).
 *   - `staleTime: 30_000` mirroring sibling analytics hooks.
 *   - TLP toggle does NOT refetch (D4 lock; carried from PR #12
 *     Group E).
 *   - Stable cache key for groupIds toggled in different orders
 *     (canonicalization at the server-state boundary, plan L5).
 *
 * RED state: the T9 stub at `useActorNetwork.ts` returns
 * `useQuery({ queryKey: ['__t9-stub__'], queryFn: throws })`. Every
 * test below fails at T3 commit time with a clear cause:
 *   - QueryKey assertions fail with "expected <real key> got
 *     ['__t9-stub__']".
 *   - Fetch / URL / staleTime / response-shape assertions fail
 *     because the stubbed queryFn throws.
 * T9 GREEN flips them all to PASS.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { useActorNetwork } from '../useActorNetwork'

const HAPPY_BODY = {
  nodes: [
    { id: 'actor:1', kind: 'actor', label: 'Lazarus Group', degree: 5 },
    { id: 'actor:2', kind: 'actor', label: 'Andariel', degree: 3 },
    { id: 'tool:42', kind: 'tool', label: 'Phishing', degree: 2 },
    { id: 'sector:GOV', kind: 'sector', label: 'GOV', degree: 4 },
  ],
  edges: [
    { source_id: 'actor:1', target_id: 'tool:42', weight: 8 },
    { source_id: 'actor:1', target_id: 'sector:GOV', weight: 3 },
    { source_id: 'actor:1', target_id: 'actor:2', weight: 2 },
  ],
  cap_breached: false,
}

const EMPTY_BODY = { nodes: [], edges: [], cap_breached: false }

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

describe('useActorNetwork', () => {
  it('fetches /analytics/actor_network and returns parsed data', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.nodes).toHaveLength(4)
    expect(result.current.data?.edges).toHaveLength(3)
    expect(result.current.data?.cap_breached).toBe(false)
    expect(spy).toHaveBeenCalledOnce()
  })

  it('parses edges with source_id / target_id (NOT source / target)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const firstEdge = result.current.data?.edges[0]
    // Match the BE DTO at services/api/src/api/schemas/read.py:847.
    expect(firstEdge).toMatchObject({
      source_id: expect.any(String),
      target_id: expect.any(String),
      weight: expect.any(Number),
    })
    // Negative pin — the legacy `source`/`target` shape would slip
    // through if a future schema edit accidentally renamed.
    expect(firstEdge).not.toHaveProperty('source')
    expect(firstEdge).not.toHaveProperty('target')
  })

  it('defaults cap_breached to false when BE omits it (forward-compat)', async () => {
    // Future BE may emit a payload without cap_breached during a
    // backwards-compat window. The zod schema MUST `.default(false)`
    // so FE never sees `undefined` here (pins plan L2 forward-compat).
    const PAYLOAD_NO_CAP_BREACHED = {
      nodes: HAPPY_BODY.nodes,
      edges: HAPPY_BODY.edges,
      // cap_breached intentionally omitted
    }
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(PAYLOAD_NO_CAP_BREACHED), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.cap_breached).toBe(false)
  })

  it('sends date_from / date_to / group_id / top_n_* from store + options', async () => {
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
    const { result } = renderHook(
      () =>
        useActorNetwork({
          top_n_actor: 50,
          top_n_tool: 25,
          top_n_sector: 10,
        }),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/actor_network')
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.get('date_to')).toBe('2026-04-18')
    // groupIds canonicalized ascending — same rule as other analytics
    // hooks; carried from PR #12 Group E.
    expect(url.searchParams.getAll('group_id')).toEqual(['1', '3'])
    expect(url.searchParams.get('top_n_actor')).toBe('50')
    expect(url.searchParams.get('top_n_tool')).toBe('25')
    expect(url.searchParams.get('top_n_sector')).toBe('10')
  })

  it('omits top_n_* when not provided (BE defaults apply)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useActorNetwork(), { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.has('top_n_actor')).toBe(false)
    expect(url.searchParams.has('top_n_tool')).toBe(false)
    expect(url.searchParams.has('top_n_sector')).toBe(false)
  })

  // D4 lock at the hook boundary — TLP toggle MUST NOT refetch.
  // Mirrors the useAttackMatrix invariant (carried from PR #12 Group E).
  it('TLP toggle does NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })

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
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })
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

  // Each top_n_* change is a distinct cache scope (plan L5: query
  // key includes [date_from, date_to, group_id, top_n_actor,
  // top_n_tool, top_n_sector]). Codex r5 M1 fold — cover all three
  // top_n_* options + dateFrom + groupIds positive refetch cases.
  it.each([
    ['top_n_actor', { initial: { top_n_actor: 25 }, next: { top_n_actor: 50 } }],
    ['top_n_tool',  { initial: { top_n_tool: 25 },  next: { top_n_tool: 100 } }],
    ['top_n_sector',{ initial: { top_n_sector: 25 },next: { top_n_sector: 75 } }],
  ])('%s change DOES trigger a refetch (new cache scope)', async (_label, vary) => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(HAPPY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      (props: { opts: import('../useActorNetwork').ActorNetworkOptions }) =>
        useActorNetwork(props.opts),
      { wrapper: Wrapper, initialProps: { opts: vary.initial } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    rerender({ opts: vary.next })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })

  it('dateFrom / dateTo change DOES trigger a refetch (new cache scope)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(HAPPY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.setState({
        dateFrom: '2026-02-01',
        dateTo: '2026-04-18',
        groupIds: [],
        tlpLevels: [],
      })
    })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })

  it('non-equal groupIds change DOES trigger a refetch (new cache scope)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(HAPPY_BODY), { status: 200 })),
    )
    useFilterStore.setState({
      dateFrom: null,
      dateTo: null,
      groupIds: [1, 2],
      tlpLevels: [],
    })
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.setState({
        dateFrom: null,
        dateTo: null,
        groupIds: [1, 2, 3], // genuinely different set, not just reorder
        tlpLevels: [],
      })
    })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })

  // Plan T9 + L5 lock: staleTime mirrors sibling analytics hooks at
  // 30_000 ms. Codex r5 M2 fold — pin the contract directly.
  it('staleTime is 30_000 ms (mirrors sibling analytics hooks)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { client, Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const queries = client.getQueryCache().getAll()
    // The hook is the only subscriber in this test; one query.
    const actorNetworkQuery = queries.find((q) =>
      Array.isArray(q.queryKey)
      && q.queryKey[0] === 'analytics'
      && q.queryKey[1] === 'actor_network',
    )
    expect(
      actorNetworkQuery,
      'no actor_network entry in query cache — query key not formed correctly',
    ).toBeDefined()
    expect(actorNetworkQuery?.options.staleTime).toBe(30_000)
  })

  it('parses empty payload verbatim (viz owns empty-state card)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useActorNetwork(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(EMPTY_BODY)
    expect(result.current.isError).toBe(false)
  })
})
