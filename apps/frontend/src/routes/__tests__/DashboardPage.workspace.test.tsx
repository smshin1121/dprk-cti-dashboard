/**
 * DashboardPage workspace retrofit — RED tests (PR 2 T6).
 *
 * Per `docs/plans/dashboard-workspace-retrofit.md` L1 / L8 / T6 +
 * Codex F8 expansion + DESIGN.md `## Dashboard Workspace Pattern`:
 *
 *   - Heading row at top of center column with dashboard-heading-row
 *     testid + {spacing.md} height.
 *   - Period readout right-aligned in heading row.
 *   - DashboardHero ABSENT (deprecated by PR #32 contract).
 *   - dashboard-left-rail + dashboard-right-rail testids owned BY
 *     DashboardPage (not Shell — confirms L1 architectural lock).
 *   - 14-widget center grid topology preserved.
 *   - actor-network-graph slot = title + Planned · no data yet
 *     text-only empty state. NEGATIVE: no <svg>, no <canvas>, no
 *     node/edge/skeleton/sparkline/marks.
 *
 * RED phase: DashboardPage.tsx still has the old hero+stack layout.
 * T9 GREEN.
 *
 * NOTE on test isolation: this file is a sibling to the existing
 * DashboardPage.test.tsx so the original area [B]-[F] wiring test
 * stays untouched. The new workspace assertions live here.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useFilterStore } from '../../stores/filters'
import { DashboardPage } from '../DashboardPage'

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

function mockAllEndpoints(): void {
  vi.spyOn(global, 'fetch').mockImplementation(async () =>
    new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
  )
}

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }): JSX.Element {
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

describe('DashboardPage workspace retrofit (PR 2)', () => {
  it('renders the heading row with testid and period readout', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    const headingRow = await waitFor(() =>
      screen.getByTestId('dashboard-heading-row'),
    )
    expect(headingRow).toBeInTheDocument()
    // Heading row contains the page <h1> + the period readout.
    expect(within(headingRow).getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(within(headingRow).getByTestId('period-readout')).toBeInTheDocument()
  })

  it('heading row asserts {spacing.md} height contract via Tailwind utility (h-md or h-12 per spacing scale)', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    const headingRow = await waitFor(() =>
      screen.getByTestId('dashboard-heading-row'),
    )
    // {spacing.md} = 16-24px in the project's scale; the heading row
    // composes spacing.md as its row-gap or min-height target.
    // Acceptable utility patterns: h-md / py-md / min-h-md / h-12
    // (3rem ≈ 48px is the dashboard heading-row target).
    expect(headingRow.className).toMatch(
      /\bh-(md|12|14)\b|\bmin-h-(md|12|14)\b|\bpy-md\b/,
    )
  })

  it('DashboardHero is ABSENT — deprecated by PR #32 contract', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('kpi-strip')).toBeInTheDocument(),
    )
    // The original Ferrari L4 hero callout must not render.
    expect(screen.queryByTestId('dashboard-hero')).toBeNull()
  })

  it('renders left-rail + right-rail owned BY DashboardPage (not Shell)', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('dashboard-left-rail')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('dashboard-right-rail')).toBeInTheDocument()
  })

  it('preserves the 14-widget center grid topology', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    // 13 existing widgets (hero gone) + 1 new actor-network-graph
    // slot = 14 entries. The plan keeps the existing 12-13 testids
    // intact. The actor-network slot adds one new testid.
    const expected = [
      'kpi-strip',
      'world-map',
      'attack-heatmap',
      'actor-network-graph-slot', // NEW (reserved/future)
      'locations-ranked',
      'motivation-donut',
      'year-bar',
      'sector-breakdown',
      'contributors-list',
      'trend-chart',
      'groups-mini-list',
      'motivation-stacked-area',
      'sector-stacked-area',
      'report-feed',
    ]
    for (const testid of expected) {
      // Use waitFor because chart panels render async after fetch.
      // eslint-disable-next-line no-await-in-loop
      await waitFor(() =>
        expect(screen.getByTestId(testid)).toBeInTheDocument(),
      )
    }
  })

  it('actor-network-graph slot renders title + "Planned · no data yet" text-only empty state', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    const slot = await waitFor(() =>
      screen.getByTestId('actor-network-graph-slot'),
    )
    expect(within(slot).getByTestId('actor-network-graph-title')).toBeInTheDocument()
    expect(within(slot).getByTestId('actor-network-graph-empty-state')).toHaveTextContent(
      /planned.*no data yet/i,
    )
  })

  it('actor-network-graph slot has NO svg / canvas / node / edge / skeleton / sparkline / marks elements', async () => {
    mockAllEndpoints()
    const { Wrapper } = makeWrapper()
    render(<DashboardPage />, { wrapper: Wrapper })

    const slot = await waitFor(() =>
      screen.getByTestId('actor-network-graph-slot'),
    )
    // DESIGN.md G5 #2 + actor-network-graph vocabulary entry —
    // text-only constraint. Production tree must NOT render
    // visualization-shaped placeholders.
    expect(slot.querySelectorAll('svg')).toHaveLength(0)
    expect(slot.querySelectorAll('canvas')).toHaveLength(0)
    const negativeIds = ['node', 'edge', 'skeleton', 'sparkline', 'chart-marks']
    for (const id of negativeIds) {
      expect(within(slot).queryAllByTestId(new RegExp(id))).toHaveLength(0)
    }
  })
})
