/**
 * Plan §B8 (f) — shared query-cache invariant: mounting every page
 * subscriber to `useCorrelation(...)` with identical inputs fires
 * exactly ONE primary fetch (`pattern_shared_query_cache_multi_subscriber`).
 *
 * Same shape as `summarySharedCache.test.tsx` (PR #13 / §6.C C9 / C6
 * for dashboard) but scoped to the new correlation cache slot.
 *
 * RED state at T7 — the page tree does not render yet (every leaf is
 * a `NotImplementedError` stub from this commit). T9 implements the
 * page tree; this test asserts that NO leaf re-calls
 * `useCorrelation(...)` outside the cache-shared path. Per
 * `pattern_shared_cache_test_extension`, this test must be UPDATED
 * whenever a new component subscribes to the same cache key — adding
 * a fourth panel to the page tree post-merge would extend this list.
 *
 * Subscribers expected at T9:
 *   - CorrelationPage (orchestrator; one direct `useCorrelation` call
 *     to drive the 4-state branching).
 *   - CorrelationLagChart (consumes the parsed `lag_grid` — may
 *     subscribe directly OR receive via props; either way the cache
 *     key is shared, so React Query dedupes to one fetch).
 *   - CorrelationWarningChips (consumes
 *     `interpretation.warnings[]` — same).
 *
 * The catalog cache (`useCorrelationSeries`) is independent and
 * pinned at the hook layer (T5
 * `useCorrelationSeries.test.tsx::"multiple subscribers share one
 * fetch"`); this file pins the primary slot only.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
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

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter
          initialEntries={[
            '/analytics/correlation?x=reports.total&y=incidents.total',
          ]}
        >
          {children}
        </MemoryRouter>
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

describe('correlation primary cache — one fetch across all page subscribers (Plan §B8 f)', () => {
  it('mounting CorrelationPage fires exactly ONE primary fetch (cache shared across leaves)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input) => {
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
    const { Wrapper } = makeWrapper()
    render(<CorrelationPage />, { wrapper: Wrapper })

    await waitFor(() => {
      const primaryCalls = fetchSpy.mock.calls.filter(([u]) =>
        String(u).includes('/api/v1/analytics/correlation?'),
      )
      expect(
        primaryCalls.length,
        'expected exactly one primary fetch — multiple = a leaf is bypassing the shared cache slot',
      ).toBe(1)
    })

    // Catalog fetch fires too — independent slot, unbounded count
    // not asserted here (catalog dedup is pinned at the hook layer).
    const catalogCalls = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes('/api/v1/analytics/correlation/series'),
    )
    expect(catalogCalls.length).toBeGreaterThan(0)
  })

  it('remounting the same page in the same QueryClient does NOT refetch the primary slot', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input) => {
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
    const { Wrapper } = makeWrapper()
    const { unmount } = render(<CorrelationPage />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(
        fetchSpy.mock.calls.filter(([u]) =>
          String(u).includes('/api/v1/analytics/correlation?'),
        ).length,
      ).toBe(1)
    })
    unmount()

    // Remount with the same wrapper (same QueryClient instance) — the
    // primary cache slot is already populated and within the 5-min
    // staleTime, so no new fetch fires.
    render(<CorrelationPage />, { wrapper: Wrapper })
    await new Promise((r) => setTimeout(r, 30))

    const primaryCalls = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes('/api/v1/analytics/correlation?'),
    )
    expect(primaryCalls.length).toBe(1)
  })
})
