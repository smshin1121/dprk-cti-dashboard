/**
 * Plan §B8 (c) — method toggle (Pearson ↔ Spearman) is purely visual.
 *
 * RED state at T7. T9 implements the toggle; until then the page stub
 * throws `NotImplementedError` and every test fails at runtime with
 * a traceable message.
 *
 * Plan §4 T4 + T5 lock — `method` is NOT in the cache key. The same
 * `useCorrelation(...)` cache slot serves both views; the chart picks
 * which method's series to highlight from a single response. Toggling
 * MUST NOT trigger a refetch (`pattern_shared_query_cache_multi_subscriber`).
 *
 * Memory `pitfall_recharts_testid_multielement` — chart per-line
 * testids (`line-pearson` / `line-spearman`); series-shape testids
 * use `getAllByTestId(...).length).toBeGreaterThan(0)`.
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

describe('CorrelationPage method toggle (Plan §B8 c)', () => {
  it('starts on Pearson (default per umbrella §6.3)', async () => {
    mockBothEndpoints()
    const { Wrapper } = makeWrapper()
    render(<CorrelationPage />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('line-pearson')).toHaveAttribute(
        'data-method-active',
        'true',
      )
      expect(screen.getByTestId('line-spearman')).toHaveAttribute(
        'data-method-active',
        'false',
      )
    })
  })

  it('toggle to Spearman switches the active line', async () => {
    mockBothEndpoints()
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper()
    render(<CorrelationPage />, { wrapper: Wrapper })

    await waitFor(() => screen.getByTestId('correlation-method-spearman'))
    await user.click(screen.getByTestId('correlation-method-spearman'))

    expect(screen.getByTestId('line-spearman')).toHaveAttribute(
      'data-method-active',
      'true',
    )
    expect(screen.getByTestId('line-pearson')).toHaveAttribute(
      'data-method-active',
      'false',
    )
  })

  it('toggle does NOT trigger a refetch (visual-only; T4 method-not-in-key)', async () => {
    const fetchSpy = mockBothEndpoints()
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper()
    render(<CorrelationPage />, { wrapper: Wrapper })

    // Wait for both initial fetches (catalog + primary) to settle.
    await waitFor(() => {
      const primaryCalls = fetchSpy.mock.calls.filter(([u]) =>
        String(u).includes('/api/v1/analytics/correlation?'),
      )
      expect(primaryCalls.length).toBe(1)
    })
    const baseline = fetchSpy.mock.calls.length

    // Click the toggle multiple times.
    await user.click(await screen.findByTestId('correlation-method-spearman'))
    await user.click(await screen.findByTestId('correlation-method-pearson'))
    await user.click(await screen.findByTestId('correlation-method-spearman'))

    // No new fetches — single cache slot per (x, y, dates, alpha).
    await new Promise((r) => setTimeout(r, 30))
    expect(fetchSpy.mock.calls.length).toBe(baseline)
  })
})
