import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { LocationsRanked } from '../LocationsRanked'
import { WorldMap } from '../WorldMap'

const HAPPY_BODY = {
  countries: [
    { iso2: 'KR', count: 18 },
    { iso2: 'US', count: 9 },
    { iso2: 'KP', count: 4 },
    { iso2: 'JP', count: 2 },
  ],
}

const EMPTY_BODY = { countries: [] }

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

describe('LocationsRanked — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<LocationsRanked />, { wrapper: Wrapper })
    expect(
      screen.getByTestId('locations-ranked-loading'),
    ).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<LocationsRanked />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('locations-ranked-error'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('locations-ranked-retry'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('locations-ranked'),
    ).not.toBeInTheDocument()
  })

  it('empty state when countries array is empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<LocationsRanked />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('locations-ranked-empty'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('locations-ranked'),
    ).not.toBeInTheDocument()
  })

  it('populated state preserves BE order (count DESC) and renders one row per country', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<LocationsRanked />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('locations-ranked'),
    ).toBeInTheDocument()
    const items = screen.getByTestId('locations-ranked-items').children
    expect(items).toHaveLength(4)
    expect(items[0]).toHaveAttribute('data-iso2', 'KR')
    expect(items[1]).toHaveAttribute('data-iso2', 'US')
    expect(items[2]).toHaveAttribute('data-iso2', 'KP')
    expect(items[3]).toHaveAttribute('data-iso2', 'JP')
  })
})

describe('LocationsRanked top-N + cache invariants', () => {
  it('caps the rendered list at top 10 even when BE returns more rows', async () => {
    // Generate 18 distinct 2-char ISO codes (Zod schema enforces
    // `iso2: z.string().length(2)`). Use uppercase A* permutations
    // sorted alphabetically — A0..A9, B0..B7 — for stable test data.
    const codes = [
      'A0', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8', 'A9',
      'B0', 'B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7',
    ]
    const longBody = {
      countries: codes.map((iso2, i) => ({ iso2, count: 100 - i })),
    }
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(longBody), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<LocationsRanked />, { wrapper: Wrapper })
    await screen.findByTestId('locations-ranked')
    const items = screen.getByTestId('locations-ranked-items').children
    expect(items).toHaveLength(10)
    // Head 10 = A0..A9 by BE count-DESC order.
    expect(items[0]).toHaveAttribute('data-iso2', 'A0')
    expect(items[9]).toHaveAttribute('data-iso2', 'A9')
    // B0 (row 11) must NOT render.
    expect(
      screen.queryByTestId('locations-ranked-item-B0'),
    ).not.toBeInTheDocument()
  })

  it('bar widths scale to the head row', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<LocationsRanked />, { wrapper: Wrapper })
    await screen.findByTestId('locations-ranked')
    const krBar = screen.getByTestId('locations-ranked-bar-KR')
    const usBar = screen.getByTestId('locations-ranked-bar-US')
    const kpBar = screen.getByTestId('locations-ranked-bar-KP')
    expect(krBar).toHaveStyle({ width: '100%' })
    // 9 / 18 = 50%.
    expect(usBar).toHaveStyle({ width: '50%' })
    // 4 / 18 ≈ 22.2%.
    expect(kpBar.style.width).toMatch(/^22\./)
  })

  it('shares /analytics/geo cache with WorldMap (D9 invariant)', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    render(
      <>
        <WorldMap />
        <LocationsRanked />
      </>,
      { wrapper: Wrapper },
    )
    await waitFor(() =>
      expect(screen.getByTestId('locations-ranked')).toBeInTheDocument(),
    )
    const geoCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/analytics/geo'),
    )
    // Two subscribers, one shared cache key → ONE fetch. Catches a
    // future regression that switches LocationsRanked to a bespoke
    // hook (the lazarus.day parity panel must never duplicate the
    // network round-trip the map already performs).
    expect(geoCalls).toHaveLength(1)
  })
})
