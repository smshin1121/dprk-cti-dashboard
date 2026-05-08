/**
 * useCorrelation hook tests (PR-B T5).
 *
 * Pins (plan §4 T5 row exit "loading/error/empty states + cache
 * reuse across remounts" + plan §B3 staleTime + B5 method-not-in-key
 * + CONTRACT.md §1 null-preservation):
 *
 *   - Happy fetch + parse (4-state populated branch).
 *   - Loading + error states surface correctly.
 *   - 422 typed surface — `error.detail` parses through
 *     `correlationErrorEnvelopeSchema` (T3) for B10 typed-reason copy.
 *   - Enable guard — fires only when both x and y are non-empty.
 *   - x === y still fires (BE 422 surfaces; B10 handles).
 *   - `staleTime: 300_000` (5 min, NFR-1 + §8.7).
 *   - Cache slot per (x, y, dateFrom, dateTo, alpha) — refetch on
 *     each component change.
 *   - Cache reuse across remounts with identical inputs (one fetch
 *     per cache key regardless of mount count —
 *     `pattern_shared_query_cache_multi_subscriber`).
 *   - `null` dates preserved on the wire (no substitution).
 *   - No `useFilterStore` subscription — TLP / date / group toggles
 *     must not affect this hook (defensive belt; the hook reads
 *     positional args, never the global store).
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../../../lib/api'
import { correlationErrorEnvelopeSchema } from '../../../../lib/api/endpoints'
import { createQueryClient } from '../../../../lib/queryClient'
import { useFilterStore } from '../../../../stores/filters'
import { useCorrelation } from '../useCorrelation'

function buildHappyLagGrid(): unknown[] {
  const cells: unknown[] = []
  for (let lag = -24; lag <= 24; lag++) {
    cells.push({
      lag,
      pearson: {
        r: 0.4,
        p_raw: 0.001,
        p_adjusted: 0.005,
        significant: true,
        effective_n_at_lag: 60,
        reason: null,
      },
      spearman: {
        r: 0.38,
        p_raw: 0.002,
        p_adjusted: 0.006,
        significant: true,
        effective_n_at_lag: 60,
        reason: null,
      },
    })
  }
  return cells
}

const HAPPY_BODY = {
  x: 'reports.total',
  y: 'incidents.total',
  date_from: '2020-01-01',
  date_to: '2024-12-31',
  alpha: 0.05,
  effective_n: 60,
  lag_grid: buildHappyLagGrid(),
  interpretation: {
    caveat: 'Correlation does not imply causation.',
    methodology_url: '/docs/methodology/correlation',
    warnings: [],
  },
}

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { client, Wrapper }
}

/** Multi-fetch-safe response factory — `mockResolvedValue` locks the
 *  body after one `.json()` consumption (memory
 *  `pitfall_response_body_single_consumption`); use this when a test
 *  triggers more than one fetch. */
function mockMultiFetch(body: unknown, status = 200) {
  return vi.spyOn(global, 'fetch').mockImplementation(() =>
    Promise.resolve(new Response(JSON.stringify(body), { status })),
  )
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

describe('useCorrelation — happy + loading + empty branches', () => {
  it('fetches /analytics/correlation and returns parsed primary response', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.lag_grid).toHaveLength(49)
    expect(result.current.data?.interpretation.warnings).toEqual([])
    expect(spy).toHaveBeenCalledOnce()
  })

  it('starts in loading state before the fetch resolves', async () => {
    let resolveFetch: ((value: Response) => void) | null = null
    vi.spyOn(global, 'fetch').mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve
        }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    expect(result.current.isLoading).toBe(true)
    expect(result.current.data).toBeUndefined()

    act(() => {
      resolveFetch?.(new Response(JSON.stringify(HAPPY_BODY), { status: 200 }))
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('sends x / y / date_from / date_to / alpha on the wire when all provided', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () =>
        useCorrelation(
          'reports.total',
          'incidents.total',
          '2024-01-01',
          '2024-12-31',
          0.05,
        ),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/correlation')
    expect(url.searchParams.get('x')).toBe('reports.total')
    expect(url.searchParams.get('y')).toBe('incidents.total')
    expect(url.searchParams.get('date_from')).toBe('2024-01-01')
    expect(url.searchParams.get('date_to')).toBe('2024-12-31')
    expect(url.searchParams.get('alpha')).toBe('0.05')
  })

  // CONTRACT.md §1 — null dates omitted from wire (BE resolves default
  // window). Pinned at endpoint layer (T3) but also at hook layer for
  // the integration sanity check.
  it('null dates omit date_from / date_to from the wire (BE resolves default)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.has('date_from')).toBe(false)
    expect(url.searchParams.has('date_to')).toBe(false)
    expect(url.searchParams.get('alpha')).toBe('0.05')
  })
})

describe('useCorrelation — enable guard', () => {
  it('does NOT fire when x is empty (initial mount before catalog hydrates)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    // Give RQ a tick to settle.
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current.isLoading).toBe(false)
    expect(result.current.fetchStatus).toBe('idle')
    expect(spy).not.toHaveBeenCalled()
  })

  it('does NOT fire when y is empty', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', '', null, null, 0.05),
      { wrapper: Wrapper },
    )
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current.fetchStatus).toBe('idle')
    expect(spy).not.toHaveBeenCalled()
  })

  // x === y is intentionally NOT guarded — the BE 422
  // value_error.identical_series surfaces through B10 typed-reason
  // copy. Catching client-side would short-circuit the typed path.
  it('DOES fire when x === y (BE 422 surfaces; B10 typed-reason path)', async () => {
    const envelope = {
      detail: [
        {
          loc: ['query', 'y'],
          msg: 'x and y must be different series IDs',
          type: 'value_error.identical_series',
          ctx: { x: 'reports.total', y: 'reports.total' },
        },
      ],
    }
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(envelope), { status: 422 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'reports.total', null, null, 0.05),
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(spy).toHaveBeenCalledOnce()
    const err = result.current.error as InstanceType<typeof ApiError>
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    // T3-parsed typed detail surface — B10 narrows on
    // detail[0].type to pick the typed-reason copy.
    const parsed = correlationErrorEnvelopeSchema.parse(err.detail)
    expect(parsed.detail[0].type).toBe('value_error.identical_series')
  })
})

describe('useCorrelation — staleTime + cache scoping', () => {
  // Plan §B3 + umbrella NFR-1 + §8.7 — 5 min stale time.
  it('staleTime is 300_000 ms (5 min, umbrella NFR-1)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { client, Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const queries = client.getQueryCache().getAll()
    const primary = queries.find(
      (q) =>
        Array.isArray(q.queryKey)
        && q.queryKey[0] === 'analytics'
        && q.queryKey[1] === 'correlation'
        && q.queryKey.length === 7,
    )
    expect(
      primary,
      'no correlation primary entry in query cache — query key not formed correctly',
    ).toBeDefined()
    expect(primary?.options.staleTime).toBe(300_000)
  })

  // Each component of the BE Redis key opens a fresh cache scope on
  // the FE side. T4 pins this at the key layer; here we pin it at the
  // hook layer via rerender refetch counts.
  it.each([
    [
      'x',
      {
        initial: ['reports.total', 'incidents.total', null, null, 0.05] as const,
        next: ['reports.lazarus', 'incidents.total', null, null, 0.05] as const,
      },
    ],
    [
      'y',
      {
        initial: ['reports.total', 'incidents.total', null, null, 0.05] as const,
        next: ['reports.total', 'incidents.lazarus', null, null, 0.05] as const,
      },
    ],
    [
      'dateFrom',
      {
        initial: ['reports.total', 'incidents.total', null, null, 0.05] as const,
        next: ['reports.total', 'incidents.total', '2024-01-01', null, 0.05] as const,
      },
    ],
    [
      'dateTo',
      {
        initial: ['reports.total', 'incidents.total', null, null, 0.05] as const,
        next: ['reports.total', 'incidents.total', null, '2024-12-31', 0.05] as const,
      },
    ],
    [
      'alpha',
      {
        initial: ['reports.total', 'incidents.total', null, null, 0.05] as const,
        next: ['reports.total', 'incidents.total', null, null, 0.01] as const,
      },
    ],
  ])('%s change DOES trigger a refetch (new cache scope)', async (_label, vary) => {
    const spy = mockMultiFetch(HAPPY_BODY)
    const { Wrapper } = makeWrapper()
    const { result, rerender } = renderHook(
      (props: {
        args: readonly [string, string, string | null, string | null, number]
      }) => useCorrelation(...props.args),
      { wrapper: Wrapper, initialProps: { args: vary.initial } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    rerender({ args: vary.next })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })

  // `pattern_shared_query_cache_multi_subscriber` — N consumers with
  // identical inputs share one fetch.
  it('multiple subscribers with identical inputs share one fetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result: r1 } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(r1.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    const { result: r2 } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(r2.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  // CONTRACT.md §1 + T4 — null literals preserved on the wire too
  // (no `today()` / `Date.now()` substitution at the hook layer).
  it('null dates preserved end-to-end (no substitution at hook layer)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = new URL(String(spy.mock.calls[0][0]))
    // Wire excludes null dates; positive assertion that no
    // `today()`/`Date.now()` substitution happened upstream.
    expect(url.searchParams.has('date_from')).toBe(false)
    expect(url.searchParams.has('date_to')).toBe(false)
    const todayIso = new Date().toISOString().slice(0, 10)
    expect(url.search).not.toContain(todayIso)
  })
})

describe('useCorrelation — filter store isolation (defensive belt)', () => {
  // The hook does not subscribe to `useFilterStore` — TLP toggle
  // cannot reach this cache. Pinned via "exactly one fetch after
  // toggle" assertion (analogous to sibling analytics-hook tests).
  it('TLP toggle does NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
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

  // dateFrom in the global store does NOT correspond to correlation's
  // page-local date filter (B5 URL-state namespace). Toggling the
  // global dateFrom must not invalidate this hook's cache.
  it('global filter store dateFrom toggle does NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(
      () => useCorrelation('reports.total', 'incidents.total', null, null, 0.05),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledTimes(1)

    act(() => {
      useFilterStore.setState({
        dateFrom: '2026-01-01',
        dateTo: '2026-12-31',
        groupIds: [1, 2],
        tlpLevels: ['AMBER'],
      })
    })
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
