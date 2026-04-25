import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import {
  MotivationStackedArea,
  SectorStackedArea,
} from '../IncidentsStackedArea'

const MOTIVATION_HAPPY = {
  buckets: [
    {
      month: '2026-01',
      count: 14,
      series: [
        { key: 'Espionage', count: 9 },
        { key: 'Finance', count: 5 },
      ],
    },
    {
      month: '2026-02',
      count: 16,
      series: [
        { key: 'Espionage', count: 10 },
        { key: 'Finance', count: 4 },
        { key: 'unknown', count: 2 },
      ],
    },
  ],
  group_by: 'motivation' as const,
}

const SECTOR_HAPPY = {
  buckets: [
    {
      month: '2026-03',
      count: 4,
      series: [
        { key: 'GOV', count: 2 },
        { key: 'FIN', count: 1 },
        { key: 'ENE', count: 1 },
      ],
    },
  ],
  group_by: 'sector' as const,
}

const EMPTY_BODY = { buckets: [], group_by: 'motivation' as const }

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

afterEach(() => vi.restoreAllMocks())

describe('MotivationStackedArea — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationStackedArea />, { wrapper: Wrapper })
    expect(
      screen.getByTestId('motivation-stacked-area-loading'),
    ).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationStackedArea />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('motivation-stacked-area-error'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('motivation-stacked-area-retry'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('motivation-stacked-area'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('motivation-stacked-area-empty'),
    ).not.toBeInTheDocument()
  })

  it('empty state when buckets array is empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationStackedArea />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('motivation-stacked-area-empty'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('motivation-stacked-area'),
    ).not.toBeInTheDocument()
  })

  it('populated state renders one series per axis key', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(MOTIVATION_HAPPY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationStackedArea />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('motivation-stacked-area'),
    ).toBeInTheDocument()
    // 3 distinct keys across the two months: Espionage, Finance,
    // unknown. Each gets one <Area /> in JSX but Recharts emits
    // multiple SVG sub-elements per Area sharing the testid (path,
    // dots, etc.) — getAllByTestId asserts ≥1 match per series.
    expect(
      screen.getAllByTestId('motivation-stacked-area-series-Espionage')
        .length,
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByTestId('motivation-stacked-area-series-Finance')
        .length,
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByTestId('motivation-stacked-area-series-unknown')
        .length,
    ).toBeGreaterThan(0)
  })
})

describe('SectorStackedArea — symmetric to motivation widget', () => {
  it('populated state renders sector axis keys', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SECTOR_HAPPY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SectorStackedArea />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('sector-stacked-area'),
    ).toBeInTheDocument()
    expect(
      screen.getAllByTestId('sector-stacked-area-series-GOV').length,
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByTestId('sector-stacked-area-series-FIN').length,
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByTestId('sector-stacked-area-series-ENE').length,
    ).toBeGreaterThan(0)
  })

  it('empty state for sector axis', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ buckets: [], group_by: 'sector' }),
        { status: 200 },
      ),
    )
    const { Wrapper } = makeWrapper()
    render(<SectorStackedArea />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('sector-stacked-area-empty'),
    ).toBeInTheDocument()
  })
})

describe('IncidentsStackedArea wire contract', () => {
  it('motivation widget hits group_by=motivation', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(MOTIVATION_HAPPY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    render(<MotivationStackedArea />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/incidents_trend')
    expect(url.searchParams.get('group_by')).toBe('motivation')
  })

  it('sector widget hits group_by=sector', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(SECTOR_HAPPY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    render(<SectorStackedArea />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('group_by')).toBe('sector')
  })

  it('rendering both widgets produces TWO independent fetches (cache slots distinct)', async () => {
    // Critical companion to the queryKey isolation test — guards
    // against a regression where both widgets accidentally subscribe
    // to the same React Query cache slot via misshapen queryKey.
    let motivationCount = 0
    let sectorCount = 0
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('group_by=sector')) {
        sectorCount += 1
        return Promise.resolve(
          new Response(JSON.stringify(SECTOR_HAPPY), { status: 200 }),
        )
      }
      if (url.includes('group_by=motivation')) {
        motivationCount += 1
        return Promise.resolve(
          new Response(JSON.stringify(MOTIVATION_HAPPY), { status: 200 }),
        )
      }
      throw new Error(`unexpected URL ${url}`)
    })
    const { Wrapper } = makeWrapper()
    render(
      <>
        <MotivationStackedArea />
        <SectorStackedArea />
      </>,
      { wrapper: Wrapper },
    )
    await waitFor(() => {
      expect(motivationCount).toBe(1)
      expect(sectorCount).toBe(1)
    })
  })
})
