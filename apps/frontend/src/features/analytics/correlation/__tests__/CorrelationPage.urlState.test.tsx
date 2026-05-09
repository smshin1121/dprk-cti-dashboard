/**
 * Plan §B8 (b) — URL state hydration + write-back. Plan §B5 namespace
 * `analytics.correlation.*` (5 keys: `x`, `y`, `date_from`, `date_to`,
 * `method`).
 *
 * RED state at T7. T9/T10 implement the URL ⇄ page-local-state sync
 * (likely via `useFilterUrlSync` extension or per-page successor —
 * §3 In Scope mentions "URL-state additions hooked into
 * `useFilterUrlSync`"). Until then every test fails at runtime with
 * the page stub `NotImplementedError`.
 *
 * Memory anchors:
 *   - `pitfall_browser_router_init_replaceState` — filter spy calls
 *     by URL shape; React Router fires `replaceState(undefined)` on
 *     mount.
 *   - `pattern_shared_query_cache_multi_subscriber` — write-back
 *     should not fire spurious renders that re-execute the queryFn.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../../lib/queryClient'
import { useFilterStore } from '../../../../stores/filters'
import { CorrelationPage } from '../CorrelationPage'

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

const HAPPY_CATALOG = {
  series: [
    {
      id: 'reports.total',
      label_ko: '보고서 총수',
      label_en: 'Total reports',
      root: 'reports.published',
      bucket: 'monthly',
    },
    {
      id: 'incidents.total',
      label_ko: '사건 총수',
      label_en: 'Total incidents',
      root: 'incidents.reported',
      bucket: 'monthly',
    },
    // Third entry — the write-back tests need a non-y option to pick
    // without colliding with x. Without this entry, T9 catalog-driven
    // CorrelationFilters would never render the testid the click test
    // queries (Codex T7 r1 MED finding).
    {
      id: 'incidents.lazarus',
      label_ko: '라자루스 사건',
      label_en: 'Lazarus incidents',
      root: 'incidents.reported',
      bucket: 'monthly',
    },
  ],
}

const HAPPY_PRIMARY = {
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

function mockBothEndpoints() {
  return vi.spyOn(global, 'fetch').mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/series')) {
      return Promise.resolve(
        new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
      )
    }
    return Promise.resolve(
      new Response(JSON.stringify(HAPPY_PRIMARY), { status: 200 }),
    )
  })
}

function makeWrapper(initialEntries: string[]) {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
      </QueryClientProvider>
    )
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

describe('CorrelationPage URL state (Plan §B8 b + B5)', () => {
  it('hydrates x / y / dates / method from the URL on mount', async () => {
    const fetchSpy = mockBothEndpoints()
    const { Wrapper } = makeWrapper([
      '/analytics/correlation?x=reports.total&y=incidents.total&date_from=2024-01-01&date_to=2024-12-31&method=spearman',
    ])
    render(<CorrelationPage />, { wrapper: Wrapper })

    // Wait for the primary fetch to fire — its querystring carries the
    // hydrated x / y / dates pulled from the URL on mount.
    await waitFor(() => {
      const primaryCall = fetchSpy.mock.calls.find(([u]) =>
        String(u).includes('/api/v1/analytics/correlation?'),
      )
      expect(primaryCall, 'no primary fetch fired after URL hydrate').toBeDefined()
      const url = new URL(String(primaryCall![0]))
      expect(url.searchParams.get('x')).toBe('reports.total')
      expect(url.searchParams.get('y')).toBe('incidents.total')
      expect(url.searchParams.get('date_from')).toBe('2024-01-01')
      expect(url.searchParams.get('date_to')).toBe('2024-12-31')
    })

    // Method is purely visual; pinned via the chart's selected-line
    // testid (T9 testids: `line-pearson` / `line-spearman`).
    expect(screen.getByTestId('line-spearman')).toHaveAttribute(
      'data-method-active',
      'true',
    )
  })

  it('writes user y change back to the URL via replaceState (final settled href)', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    mockBothEndpoints()
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper([
      '/analytics/correlation?x=reports.total&y=incidents.total',
    ])
    render(<CorrelationPage />, { wrapper: Wrapper })

    // Wait for the page to render its filter UI before clicking it,
    // then snapshot the spy state so post-click writes can be isolated
    // from any mount/hydrate writes (per `pitfall_browser_router_init_replaceState`).
    const yPicker = await screen.findByTestId('correlation-filter-y')
    const baselineCallCount = replaceSpy.mock.calls.length

    await user.click(yPicker)
    // T9 will surface a dropdown option; the test interacts at the
    // semantic level via testid.
    const newOption = await screen.findByTestId(
      'correlation-filter-y-option-incidents.lazarus',
    )
    await user.click(newOption)

    // Pin THE FINAL post-click write (not just any intermediate
    // match) — guards against an implementation that briefly writes
    // the change then overwrites it later (Codex T7 r3 sibling
    // application of the date-write final-href pattern).
    await waitFor(() => {
      const postClickWrites = replaceSpy.mock.calls
        .slice(baselineCallCount)
        .map(([, , href]) => (typeof href === 'string' ? href : null))
        .filter((h): h is string => h !== null)
      expect(postClickWrites.length).toBeGreaterThan(0)
      const finalWrite = postClickWrites[postClickWrites.length - 1]
      expect(finalWrite).toContain('y=incidents.lazarus')
    })
  })

  // Write-back coverage for the remaining two B5 keys not covered by
  // the y-change test (Codex T7 r1 LOW): `method` (visual toggle) and
  // `date_from` / `date_to`. The five-key contract is `x` / `y` /
  // `date_from` / `date_to` / `method`; `x` is symmetric to `y` and
  // pinned via the same code path so one positive y-change write +
  // method-change write + date-change write is sufficient.
  it('writes user method toggle back to the URL (method=spearman, final settled href)', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    mockBothEndpoints()
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper([
      '/analytics/correlation?x=reports.total&y=incidents.total',
    ])
    render(<CorrelationPage />, { wrapper: Wrapper })

    const toggle = await screen.findByTestId('correlation-method-spearman')
    const baselineCallCount = replaceSpy.mock.calls.length

    await user.click(toggle)

    await waitFor(() => {
      const postClickWrites = replaceSpy.mock.calls
        .slice(baselineCallCount)
        .map(([, , href]) => (typeof href === 'string' ? href : null))
        .filter((h): h is string => h !== null)
      expect(postClickWrites.length).toBeGreaterThan(0)
      const finalWrite = postClickWrites[postClickWrites.length - 1]
      expect(finalWrite).toContain('method=spearman')
    })
  })

  it('writes user date range back to the URL (date_from + date_to in the same final href)', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    mockBothEndpoints()
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper([
      '/analytics/correlation?x=reports.total&y=incidents.total',
    ])
    render(<CorrelationPage />, { wrapper: Wrapper })

    const dateFromInput = await screen.findByTestId('correlation-filter-date-from')
    await user.clear(dateFromInput)
    await user.type(dateFromInput, '2024-01-01')

    const dateToInput = await screen.findByTestId('correlation-filter-date-to')
    await user.clear(dateToInput)
    await user.type(dateToInput, '2024-12-31')

    // Pin THE FINAL settled href carries both — guards against a
    // broken implementation that overwrites one date in a later call
    // (Codex T7 r2 LOW + r3 LOW). `.find(...)` would accept any
    // intermediate intermediate match; checking only `[length - 1]`
    // pins the URL the user actually sees.
    await waitFor(() => {
      const writes = replaceSpy.mock.calls
        .map(([, , href]) => (typeof href === 'string' ? href : null))
        .filter((h): h is string => h !== null)
      expect(writes.length).toBeGreaterThan(0)
      const finalWrite = writes[writes.length - 1]
      expect(finalWrite).toContain('date_from=2024-01-01')
      expect(finalWrite).toContain('date_to=2024-12-31')
    })
  })

  // CONTRACT.md §1 — clearing dates must NOT substitute today() / Date.now() /
  // Math.min(undefined). The URL after a clear reflects the user-input
  // null literally (omitted params).
  it('clearing date range omits date_from / date_to from the URL (no today() substitution)', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    mockBothEndpoints()
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper([
      // Initial entry has dates — clearing them should DROP them
      // from the URL, not auto-substitute.
      '/analytics/correlation?x=reports.total&y=incidents.total&date_from=2024-01-01&date_to=2024-12-31',
    ])
    render(<CorrelationPage />, { wrapper: Wrapper })

    // Wait for both inputs to mount (page hydrate complete) BEFORE
    // snapshotting the spy — any mount/hydrate writes must be excluded
    // from the post-clear delta (Codex T7 r2 MED).
    const dateFromInput = await screen.findByTestId('correlation-filter-date-from')
    const dateToInput = await screen.findByTestId('correlation-filter-date-to')

    // Snapshot baseline AFTER mount + hydrate writes have settled.
    const baselineCallCount = replaceSpy.mock.calls.length

    await user.clear(dateFromInput)
    await user.clear(dateToInput)

    await waitFor(() => {
      // Isolate writes that fire AFTER the user.clear() actions.
      const postClearWrites = replaceSpy.mock.calls
        .slice(baselineCallCount)
        .map(([, , href]) => (typeof href === 'string' ? href : null))
        .filter((h): h is string => h !== null)
      expect(
        postClearWrites.length,
        'expected at least one URL write after clearing dates',
      ).toBeGreaterThan(0)

      // The latest write settles the URL state. It MUST omit:
      //   - the cleared literals (`2024-01-01`, `2024-12-31`)
      //   - the `date_from=` / `date_to=` query keys themselves
      //   - any today() substitution
      const todayIso = new Date().toISOString().slice(0, 10)
      const finalWrite = postClearWrites[postClearWrites.length - 1]
      expect(finalWrite).not.toContain('2024-01-01')
      expect(finalWrite).not.toContain('2024-12-31')
      expect(finalWrite).not.toContain('date_from=')
      expect(finalWrite).not.toContain('date_to=')
      expect(finalWrite).not.toContain(todayIso)
    })
  })
})
