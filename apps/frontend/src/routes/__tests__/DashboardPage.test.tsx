/**
 * DashboardPage wiring test (PR #13 Group I). This test is the
 * scope-lock for the dashboard layout: every area the plan
 * promises ([B] through [F]) is mounted here. If a future edit
 * drops or accidentally renames a panel, this test flips red.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useFilterStore } from '../../stores/filters'
import { DashboardPage } from '../DashboardPage'

// Minimal bodies for the three endpoints the dashboard consumes.
const SUMMARY_BODY = {
  total_reports: 12,
  total_incidents: 5,
  total_actors: 3,
  reports_by_year: [{ year: 2026, count: 12 }],
  incidents_by_motivation: [{ motivation: 'financial', count: 3 }],
  top_groups: [{ group_id: 1, name: 'Lazarus Group', report_count: 5 }],
  top_sectors: [],
  top_sources: [],
}

const TREND_BODY = {
  buckets: [
    { month: '2026-01', count: 4 },
    { month: '2026-02', count: 3 },
  ],
}

const GEO_BODY = {
  countries: [
    { iso2: 'KR', count: 3 },
    { iso2: 'KP', count: 1 },
  ],
}

const ATTACK_MATRIX_BODY = {
  tactics: [{ id: 'TA0001', name: 'Initial Access' }],
  rows: [
    {
      tactic_id: 'TA0001',
      techniques: [{ technique_id: 'T1566', count: 2 }],
    },
  ],
}

const REPORTS_BODY = {
  items: [
    {
      id: 1,
      title: 'Feed report',
      url: 'https://example.test/1',
      url_canonical: 'https://example.test/1',
      published: '2026-04-15',
      source_name: 'Example',
    },
  ],
  next_cursor: null,
}

function routeFor(url: string): unknown {
  const u = new URL(url, 'http://localhost')
  if (u.pathname === '/api/v1/dashboard/summary') return SUMMARY_BODY
  if (u.pathname === '/api/v1/analytics/trend') return TREND_BODY
  if (u.pathname === '/api/v1/analytics/geo') return GEO_BODY
  if (u.pathname === '/api/v1/analytics/attack_matrix') return ATTACK_MATRIX_BODY
  if (u.pathname === '/api/v1/reports') return REPORTS_BODY
  return null
}

function mockAllEndpoints() {
  return vi.spyOn(global, 'fetch').mockImplementation(async (input) => {
    const body = routeFor(String(input))
    if (body == null) return new Response('unhandled', { status: 500 })
    return new Response(JSON.stringify(body), { status: 200 })
  })
}

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/dashboard']}>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
  return { Wrapper, client }
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

describe('DashboardPage — §4.2 area [B]-[F] wiring (PR #13 Group I)', () => {
  it('mounts every dashboard panel the plan promises', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    // [B] KPIStrip
    expect(screen.getByTestId('kpi-strip')).toBeInTheDocument()

    // [C] WorldMap — awaits data before switching from loading
    await waitFor(() =>
      expect(screen.getByTestId('world-map')).toBeInTheDocument(),
    )

    // [D] AttackHeatmap + MotivationDonut + YearBar
    await waitFor(() =>
      expect(screen.getByTestId('attack-heatmap')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('motivation-donut')).toBeInTheDocument()
    expect(screen.getByTestId('year-bar')).toBeInTheDocument()

    // [E] TrendChart + GroupsMiniList + ReportFeed. SimilarReports
    // moved to ReportDetailPage in PR #14 Group F — no longer mounts
    // here.
    await waitFor(() =>
      expect(screen.getByTestId('trend-chart')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('groups-mini-list')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('report-feed')).toBeInTheDocument(),
    )
    // PR #14 Group F regression guard — the PR #13 stub must not
    // reappear on the dashboard. If a future edit re-mounts it,
    // this assertion fires red.
    expect(
      screen.queryByTestId('similar-reports-stub'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('similar-reports'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('similar-reports-empty'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('similar-reports-loading'),
    ).not.toBeInTheDocument()

    // [F] AlertsDrawer trigger
    expect(screen.getByTestId('alerts-drawer-trigger')).toBeInTheDocument()
  })

  it('summary-backed panels share ONE /dashboard/summary fetch (D9 invariant)', async () => {
    const spy = mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })
    // Wait until the page has finished mounting its queries.
    await waitFor(() =>
      expect(screen.getByTestId('groups-mini-list')).toBeInTheDocument(),
    )
    const summaryCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/dashboard/summary'),
    )
    // KPIStrip + MotivationDonut + YearBar + GroupsMiniList = 4
    // subscribers, one shared cache key → exactly ONE fetch.
    expect(summaryCalls).toHaveLength(1)
  })
})
