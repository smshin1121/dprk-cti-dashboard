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

// Minimal bodies for the endpoints the dashboard consumes.
const SUMMARY_BODY = {
  total_reports: 12,
  total_incidents: 5,
  total_actors: 3,
  reports_by_year: [{ year: 2026, count: 12 }],
  incidents_by_motivation: [{ motivation: 'financial', count: 3 }],
  top_groups: [{ group_id: 1, name: 'Lazarus Group', report_count: 5 }],
  top_sectors: [{ sector_code: 'GOV', count: 4 }],
  top_sources: [
    {
      source_id: 7,
      source_name: 'Mandiant',
      report_count: 3,
      latest_report_date: '2026-04-10',
    },
  ],
}

const INCIDENTS_TREND_MOTIVATION_BODY = {
  buckets: [
    {
      month: '2026-02',
      count: 3,
      series: [
        { key: 'Espionage', count: 2 },
        { key: 'Finance', count: 1 },
      ],
    },
  ],
  group_by: 'motivation' as const,
}

const INCIDENTS_TREND_SECTOR_BODY = {
  buckets: [
    {
      month: '2026-02',
      count: 4,
      series: [
        { key: 'GOV', count: 2 },
        { key: 'FIN', count: 2 },
      ],
    },
  ],
  group_by: 'sector' as const,
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
  if (u.pathname === '/api/v1/analytics/incidents_trend') {
    const groupBy = u.searchParams.get('group_by')
    return groupBy === 'sector'
      ? INCIDENTS_TREND_SECTOR_BODY
      : INCIDENTS_TREND_MOTIVATION_BODY
  }
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

    // PR #23 §6.C — five lazarus.day-parity panels added to the
    // grid. Two ranked-slice widgets (C9 SectorBreakdown + C6
    // ContributorsList) sit alongside the existing donut/yearbar; two
    // time-series widgets (C7 MotivationStackedArea + C8
    // SectorStackedArea) sit alongside the existing trend/groups; one
    // geo-accessibility widget (C10 LocationsRanked) sits below the
    // WorldMap row sharing the /analytics/geo cache slot.
    await waitFor(() =>
      expect(screen.getByTestId('locations-ranked')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('sector-breakdown')).toBeInTheDocument()
    expect(screen.getByTestId('contributors-list')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByTestId('motivation-stacked-area'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByTestId('sector-stacked-area')).toBeInTheDocument()

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
    // Wait until the page has finished mounting its queries —
    // ContributorsList is the last summary-subscriber added (PR #23
    // §6.C C6) so its presence is the strongest "all six subscribed"
    // signal.
    await waitFor(() =>
      expect(screen.getByTestId('contributors-list')).toBeInTheDocument(),
    )
    const summaryCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/dashboard/summary'),
    )
    // KPIStrip + MotivationDonut + YearBar + GroupsMiniList +
    // SectorBreakdown + ContributorsList = 6 subscribers, one shared
    // cache key → exactly ONE fetch.
    expect(summaryCalls).toHaveLength(1)
  })

  it('WorldMap + LocationsRanked share ONE /analytics/geo fetch (PR #23 C10)', async () => {
    const spy = mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })
    await waitFor(() =>
      expect(screen.getByTestId('locations-ranked')).toBeInTheDocument(),
    )
    const geoCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/analytics/geo'),
    )
    // WorldMap + LocationsRanked = 2 subscribers, one shared cache
    // key → exactly ONE fetch. If a future regression switches
    // LocationsRanked to a bespoke hook this drops to 2 and fires red.
    expect(geoCalls).toHaveLength(1)
  })

  it('motivation + sector stacked-area widgets occupy distinct cache slots (PR #23 C5)', async () => {
    const spy = mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })
    await waitFor(() =>
      expect(
        screen.getByTestId('sector-stacked-area'),
      ).toBeInTheDocument(),
    )
    const incidentsTrendCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/analytics/incidents_trend'),
    )
    // Two subscribers (motivation + sector) on different axes ⇒
    // two cache keys ⇒ two fetches. If a future regression collapses
    // the keys this drops to 1 and the test fires red.
    expect(incidentsTrendCalls).toHaveLength(2)
    const groupByValues = incidentsTrendCalls
      .map(([url]) => new URL(String(url)).searchParams.get('group_by'))
      .sort()
    expect(groupByValues).toEqual(['motivation', 'sector'])
  })
})
