import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { ContributorsList } from '../ContributorsList'

const SUMMARY_BODY = {
  total_reports: 10,
  total_incidents: 5,
  total_actors: 3,
  reports_by_year: [{ year: 2026, count: 10 }],
  incidents_by_motivation: [],
  top_groups: [],
  top_sectors: [],
  top_sources: [
    {
      source_id: 7,
      source_name: 'Mandiant',
      report_count: 23,
      latest_report_date: '2026-04-12',
    },
    {
      source_id: 12,
      source_name: 'Chainalysis',
      report_count: 17,
      latest_report_date: '2026-03-28',
    },
    {
      source_id: 41,
      source_name: 'AnyRun',
      report_count: 4,
      latest_report_date: null,
    },
  ],
}

const EMPTY_SOURCES_BODY = { ...SUMMARY_BODY, top_sources: [] }

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

describe('ContributorsList — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<ContributorsList />, { wrapper: Wrapper })
    expect(
      screen.getByTestId('contributors-list-loading'),
    ).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<ContributorsList />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('contributors-list-error'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('contributors-list-retry'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('contributors-list'),
    ).not.toBeInTheDocument()
  })

  it('empty state when top_sources is empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_SOURCES_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<ContributorsList />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('contributors-list-empty'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('contributors-list'),
    ).not.toBeInTheDocument()
  })

  it('populated state renders one row per source preserving BE order', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<ContributorsList />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('contributors-list'),
    ).toBeInTheDocument()
    const items = screen.getByTestId('contributors-list-items').children
    expect(items).toHaveLength(3)
    // BE arrives sorted report_count DESC — Mandiant(23) /
    // Chainalysis(17) / AnyRun(4).
    expect(items[0]).toHaveAttribute('data-source-name', 'Mandiant')
    expect(items[1]).toHaveAttribute('data-source-name', 'Chainalysis')
    expect(items[2]).toHaveAttribute('data-source-name', 'AnyRun')
  })

  it('renders latest_report_date when present', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<ContributorsList />, { wrapper: Wrapper })
    await screen.findByTestId('contributors-list')
    // Mandiant has latest_report_date='2026-04-12' — expect the date
    // string to appear on the page (specific assertion via the row).
    const mandiantRow = screen.getByTestId('contributors-list-item-7')
    expect(mandiantRow.textContent).toContain('2026-04-12')
    expect(mandiantRow.textContent).toContain('23')
  })

  it('omits latest_report_date subtitle when null', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<ContributorsList />, { wrapper: Wrapper })
    await screen.findByTestId('contributors-list')
    // AnyRun has latest_report_date=null — the row should not show
    // the "Latest" prefix label since it'd be followed by nothing.
    const anyrunRow = screen.getByTestId('contributors-list-item-41')
    expect(anyrunRow.textContent).not.toContain('Latest')
    expect(anyrunRow.textContent).toContain('AnyRun')
    expect(anyrunRow.textContent).toContain('4')
  })
})

describe('ContributorsList shares the dashboard summary cache', () => {
  it('consumes /dashboard/summary, not a bespoke endpoint', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
      )
    const { Wrapper } = makeWrapper()
    render(<ContributorsList />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/dashboard/summary')
  })
})
