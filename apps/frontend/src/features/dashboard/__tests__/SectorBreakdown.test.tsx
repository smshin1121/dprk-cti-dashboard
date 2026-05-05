import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { SectorBreakdown, sectorAvatarText } from '../SectorBreakdown'

const SUMMARY_BODY = {
  total_reports: 10,
  total_incidents: 5,
  total_actors: 3,
  reports_by_year: [{ year: 2026, count: 10 }],
  incidents_by_motivation: [],
  top_groups: [],
  top_sectors: [
    { sector_code: 'GOV', count: 42 },
    { sector_code: 'FIN', count: 31 },
    { sector_code: 'ENE', count: 12 },
  ],
  top_sources: [],
}

const EMPTY_SECTORS_BODY = { ...SUMMARY_BODY, top_sectors: [] }

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

describe('SectorBreakdown — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<SectorBreakdown />, { wrapper: Wrapper })
    expect(
      screen.getByTestId('sector-breakdown-loading'),
    ).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SectorBreakdown />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('sector-breakdown-error'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('sector-breakdown-retry'),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('sector-breakdown')).not.toBeInTheDocument()
  })

  it('empty state when top_sectors is empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_SECTORS_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SectorBreakdown />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('sector-breakdown-empty'),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('sector-breakdown')).not.toBeInTheDocument()
  })

  it('populated state preserves BE order (count DESC) and renders one row per sector', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SectorBreakdown />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('sector-breakdown'),
    ).toBeInTheDocument()
    const items = screen.getByTestId('sector-breakdown-items').children
    expect(items).toHaveLength(3)
    // Order matches BE: GOV / FIN / ENE.
    expect(items[0]).toHaveAttribute('data-sector-code', 'GOV')
    expect(items[1]).toHaveAttribute('data-sector-code', 'FIN')
    expect(items[2]).toHaveAttribute('data-sector-code', 'ENE')
  })

  it('bar widths scale to the head row (max count → 100%)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SectorBreakdown />, { wrapper: Wrapper })
    await screen.findByTestId('sector-breakdown')
    const govBar = screen.getByTestId('sector-breakdown-bar-GOV')
    const finBar = screen.getByTestId('sector-breakdown-bar-FIN')
    const eneBar = screen.getByTestId('sector-breakdown-bar-ENE')
    // GOV is the head row → 100% width. FIN ratio = 31/42 ≈ 73.8%.
    // ENE ratio = 12/42 ≈ 28.6%. Use string-prefix matching to avoid
    // floating-point fragility on the exact decimal.
    expect(govBar).toHaveStyle({ width: '100%' })
    expect(finBar.style.width).toMatch(/^73\./)
    expect(eneBar.style.width).toMatch(/^28\./)
  })
})

describe('sectorAvatarText — Codex PR #33 r1 F3 overflow guard', () => {
  it('truncates long sector codes to 2 uppercase chars (BE column allows up to 32)', () => {
    // Realistic short codes pass through (lowercased BE → uppercased).
    expect(sectorAvatarText('GOV')).toBe('GO')
    expect(sectorAvatarText('FIN')).toBe('FI')
    // Long BE values (e.g. raw sector names, mistaken full codes) get
    // bounded so the 32×32 avatar box does not overflow.
    expect(sectorAvatarText('finance')).toBe('FI')
    expect(sectorAvatarText('healthcare-pharmaceutical')).toBe('HE')
    // Edge: empty input does not throw.
    expect(sectorAvatarText('')).toBe('')
  })
})

describe('SectorBreakdown shares the dashboard summary cache', () => {
  it('consumes /dashboard/summary, not a bespoke endpoint', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    render(<SectorBreakdown />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/dashboard/summary')
  })
})
