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

  it('writes user filter changes back to the URL via replaceState', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    mockBothEndpoints()
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper([
      '/analytics/correlation?x=reports.total&y=incidents.total',
    ])
    render(<CorrelationPage />, { wrapper: Wrapper })

    // Wait for the page to render its filter UI before clicking it.
    const yPicker = await screen.findByTestId('correlation-filter-y')
    await user.click(yPicker)
    // T9 will surface a dropdown option; the test interacts at the
    // semantic level via testid.
    const newOption = await screen.findByTestId(
      'correlation-filter-y-option-incidents.lazarus',
    )
    await user.click(newOption)

    // Filter `pitfall_browser_router_init_replaceState` — the test
    // ignores the initial Router replaceState call and pins only the
    // user-change-driven write.
    await waitFor(() => {
      const userWrite = replaceSpy.mock.calls.find(([, , href]) =>
        typeof href === 'string' && href.includes('y=incidents.lazarus'),
      )
      expect(userWrite, 'expected URL write-back to include y=incidents.lazarus').toBeDefined()
    })
  })

  it('preserves null dates as omitted URL params (no today() substitution)', async () => {
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    mockBothEndpoints()
    const { Wrapper } = makeWrapper([
      '/analytics/correlation?x=reports.total&y=incidents.total',
    ])
    render(<CorrelationPage />, { wrapper: Wrapper })

    // After hydrate completes, the URL reflects the user-input null
    // for date_from / date_to (no auto-fill).
    await waitFor(() => {
      const writes = replaceSpy.mock.calls
        .map(([, , href]) => (typeof href === 'string' ? href : null))
        .filter((h): h is string => h !== null)
      const todayIso = new Date().toISOString().slice(0, 10)
      for (const w of writes) {
        expect(w).not.toContain(todayIso)
      }
    })
  })
})
