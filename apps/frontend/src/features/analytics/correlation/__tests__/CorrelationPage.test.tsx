/**
 * Plan §B8 (a) — 4-state render (loading / error / empty / populated).
 *
 * RED state at T7. T9 implements the page wiring `useCorrelationSeries`
 * + `useCorrelation(...)` and rendering one of four branches based on
 * the React Query state. Until then every test below fails at runtime
 * with the stub's `NotImplementedError` message.
 *
 * Also pins:
 *   - `data-page-class="analyst-workspace"` on the outermost render
 *     (T0 page-class taxonomy; T10 adds `/analytics/correlation` to
 *     the manifest).
 *   - 422 typed-reason copy paths (B10) — populated 422 envelope is
 *     surfaced as the error branch with branch-specific copy.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
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

function makeWrapper(
  initialEntries: string[] = ['/analytics/correlation?x=reports.total&y=incidents.total'],
) {
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
  window.sessionStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

/**
 * Mock both endpoints — catalog hits first, primary fires after the
 * page picks defaults. Use `mockImplementation` (not
 * `mockResolvedValue`) to avoid the
 * `pitfall_response_body_single_consumption` body-locked-after-one-
 * read trap when the page issues multiple fetches across renders.
 */
function mockBothEndpoints(catalog = HAPPY_CATALOG, primary = HAPPY_PRIMARY) {
  return vi.spyOn(global, 'fetch').mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/api/v1/analytics/correlation/series')) {
      return Promise.resolve(
        new Response(JSON.stringify(catalog), { status: 200 }),
      )
    }
    if (url.includes('/api/v1/analytics/correlation')) {
      return Promise.resolve(
        new Response(JSON.stringify(primary), { status: 200 }),
      )
    }
    return Promise.reject(new Error(`Unexpected fetch: ${url}`))
  })
}

describe('CorrelationPage — 4-state render (Plan §B8 a)', () => {
  it('renders loading branch while the primary query is in flight', async () => {
    let resolvePrimary: ((res: Response) => void) | null = null
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/series')) {
        return Promise.resolve(
          new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
        )
      }
      return new Promise<Response>((resolve) => {
        resolvePrimary = resolve
      })
    })
    const { Wrapper } = makeWrapper()
    render(<CorrelationPage />, { wrapper: Wrapper })

    expect(await screen.findByTestId('correlation-loading')).toBeVisible()
    resolvePrimary?.(new Response(JSON.stringify(HAPPY_PRIMARY), { status: 200 }))
  })

  it('renders populated branch when the primary query resolves', async () => {
    mockBothEndpoints()
    const { Wrapper } = makeWrapper()
    render(<CorrelationPage />, { wrapper: Wrapper })

    expect(await screen.findByTestId('correlation-populated')).toBeVisible()
  })

  it('renders error branch with B10 typed-reason copy on 422 insufficient_sample', async () => {
    const envelope = {
      detail: [
        {
          loc: ['body', 'correlation'],
          msg: 'Minimum 30 valid months required after no_data exclusion; got 12',
          type: 'value_error.insufficient_sample',
          ctx: { effective_n: 12, minimum_n: 30 },
        },
      ],
    }
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/series')) {
        return Promise.resolve(
          new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify(envelope), { status: 422 }),
      )
    })
    const { Wrapper } = makeWrapper()
    render(<CorrelationPage />, { wrapper: Wrapper })

    // B10 typed-reason — error branch surfaces the
    // value_error.insufficient_sample copy. T9 wires per-type
    // selection; the testid pins the error-state container plus a
    // type-specific marker.
    const errorEl = await screen.findByTestId('correlation-error')
    expect(errorEl).toBeVisible()
    expect(errorEl.getAttribute('data-error-type')).toBe(
      'value_error.insufficient_sample',
    )
  })

  it('renders empty branch when x/y have not been chosen yet (catalog loaded, primary disabled)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_CATALOG), { status: 200 }),
    )
    // No x/y in URL — page should land on the empty-state branch with
    // catalog populated but primary `enabled: false` (T5 hook contract).
    const { Wrapper } = makeWrapper(['/analytics/correlation'])
    render(<CorrelationPage />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('correlation-empty')).toBeVisible()
    })
  })

  it('outermost section carries data-page-class="analyst-workspace" (T0 manifest)', async () => {
    mockBothEndpoints()
    const { Wrapper } = makeWrapper()
    const { container } = render(<CorrelationPage />, { wrapper: Wrapper })

    await waitFor(() => {
      const root = container.querySelector('[data-page-class="analyst-workspace"]')
      expect(root, 'expected outermost render to carry data-page-class="analyst-workspace" per T0 manifest').not.toBeNull()
    })
  })
})
