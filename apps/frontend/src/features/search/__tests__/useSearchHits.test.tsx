import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { SEARCH_DEBOUNCE_MS, useSearchHits } from '../useSearchHits'

// Lifted verbatim from the BE OpenAPI `responses[200].content
// .application/json.examples.happy.value` block for /api/v1/search.
// The schema test already pins parse-equality; reusing the same
// shape here keeps the hook test against a production-shaped body.
const HAPPY_BODY = {
  items: [
    {
      report: {
        id: 999060,
        title: 'Lazarus targets SK crypto exchanges',
        url: 'https://pact.test/search/populated-999060',
        url_canonical: 'https://pact.test/search/populated-999060',
        published: '2026-03-15',
        source_id: 1,
        source_name: 'Vendor',
        lang: 'en',
        tlp: 'WHITE',
      },
      fts_rank: 0.0759,
      vector_rank: null,
    },
  ],
  total_hits: 1,
  latency_ms: 42,
}

const EMPTY_BODY = { items: [], total_hits: 0, latency_ms: 12 }

// Wait a little longer than the debounce window so a pending fetch
// definitely had a chance to fire. Kept as a named constant so a
// future tweak of the debounce window shifts this in lockstep.
const WAIT_PAST_DEBOUNCE_MS = SEARCH_DEBOUNCE_MS + 80

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
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

describe('useSearchHits — plan D8 / D13 / D17', () => {
  // Review criterion #2a — the enable gate is INDEPENDENT of the
  // debounce window. An empty / whitespace-only q must never fire a
  // request, even after the debounce window elapses. The BE rejects
  // blank q with 422 — firing from the FE would be a wasted round
  // trip plus a visible toast-worthy 422.
  it('does NOT fire when q is empty', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useSearchHits(''), { wrapper: Wrapper })

    await sleep(WAIT_PAST_DEBOUNCE_MS)
    expect(spy).not.toHaveBeenCalled()
  })

  it('does NOT fire when q is whitespace-only', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useSearchHits('   '), { wrapper: Wrapper })

    await sleep(WAIT_PAST_DEBOUNCE_MS)
    expect(spy).not.toHaveBeenCalled()
  })

  // Review criterion #2b — debounce collapses rapid keystrokes onto
  // the final value. Three keystrokes within the window must produce
  // exactly ONE fetch on the last value.
  it('collapses rapid keystrokes onto one fetch at the last q', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { rerender } = renderHook(({ q }) => useSearchHits(q), {
      wrapper: Wrapper,
      initialProps: { q: 'l' },
    })

    // Type quickly within the debounce window.
    await sleep(60)
    rerender({ q: 'la' })
    await sleep(60)
    rerender({ q: 'laz' })

    // Still under SEARCH_DEBOUNCE_MS since the last keystroke —
    // fetch must NOT have fired yet.
    expect(spy).not.toHaveBeenCalled()

    // Cross the debounce window; the final value 'laz' fires.
    await sleep(WAIT_PAST_DEBOUNCE_MS)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('q')).toBe('laz')
  })

  // Review criterion #2c — debounce window is exactly 250ms per plan
  // D17. A regression that drops below 200ms turns the search surface
  // into a fetch firehose.
  it('SEARCH_DEBOUNCE_MS is locked at 250', () => {
    expect(SEARCH_DEBOUNCE_MS).toBe(250)
  })

  // Review criterion #2d — debounce and enable are orthogonal. User
  // types " laz " (with surrounding whitespace). After the debounce
  // window, the request fires with the TRIMMED value in the URL AND
  // in the cache key — the intermediate untrimmed form is never
  // what reaches the BE or the cache.
  it('trims q after debouncing (same value hits wire + cache key)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useSearchHits('  lazarus  '), { wrapper: Wrapper })

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1), {
      timeout: WAIT_PAST_DEBOUNCE_MS + 200,
    })
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('q')).toBe('lazarus')
  })

  // Enabling stays off mid-typing when the pre-debounce value is
  // whitespace (typing spaces before any real char). A fetch must
  // NOT fire as the user transitions from blank → whitespace → real
  // chars within the debounce window.
  it('stays disabled for a whitespace-only q across the debounce window', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { rerender } = renderHook(({ q }) => useSearchHits(q), {
      wrapper: Wrapper,
      initialProps: { q: '' },
    })
    rerender({ q: ' ' })
    rerender({ q: '   ' })
    await sleep(WAIT_PAST_DEBOUNCE_MS)
    expect(spy).not.toHaveBeenCalled()
  })

  // D10 empty — pact populated/empty envelopes pass through; the
  // hook doesn't flatten them or inject fallback rows.
  it('passes the D10 empty envelope through verbatim', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { result } = renderHook(() => useSearchHits('nomatchxyz123'), {
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true), {
      timeout: WAIT_PAST_DEBOUNCE_MS + 500,
    })
    expect(result.current.data).toEqual(EMPTY_BODY)
  })

  // D13 subscription lock — no FilterBar state reaches this hook.
  // TLP / groupIds toggles must NOT refetch (would happen if the
  // hook subscribed to `useFilterStore`).
  it('TLP / groupIds toggles do NOT cause a refetch', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(() => useSearchHits('lazarus'), { wrapper: Wrapper })

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1), {
      timeout: WAIT_PAST_DEBOUNCE_MS + 200,
    })

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })
    act(() => {
      useFilterStore.getState().toggleGroupId(3)
    })

    await sleep(WAIT_PAST_DEBOUNCE_MS)
    expect(spy).toHaveBeenCalledTimes(1)
  })

  // Review criterion #3 echo — the wire request carries ONLY q +
  // optional {date_from, date_to, limit}. Nothing else.
  it('sends only q + whitelisted filter keys on the wire', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    renderHook(
      () =>
        useSearchHits('lazarus', {
          date_from: '2026-03-01',
          date_to: '2026-03-31',
          limit: 25,
        }),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1), {
      timeout: WAIT_PAST_DEBOUNCE_MS + 200,
    })
    const url = new URL(String(spy.mock.calls[0][0]))
    const params = Array.from(url.searchParams.keys()).sort()
    expect(params).toEqual(['date_from', 'date_to', 'limit', 'q'])
  })
})
