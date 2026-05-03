/**
 * Plan D9 review invariant (PR #13 Group H → extended through PR #23
 * Group C): mounting every dashboard panel backed by
 * `useDashboardSummary()` fires ONE /dashboard/summary request, not
 * N. React Query's cache key is shared across subscribers with
 * identical filters, so every subscriber to `useDashboardSummary()`
 * shares one query.
 *
 * Group H pinned: KPIStrip + MotivationDonut + YearBar (3 panels).
 * Group I adds: GroupsMiniList (4th panel).
 * PR #23 §6.C C9 + C6 add: SectorBreakdown + ContributorsList (5th
 * + 6th panels — both consume the new top_sectors / top_sources
 * fields shipped in §6.A C2).
 * PR #27 Ferrari L4 (commit 8) adds: DashboardHero (7th panel — reads
 * total_incidents for the hero number-display callout).
 *
 * If a future edit switches any of these components to a bespoke
 * hook (or forgets to route through `useDashboardSummary`), this
 * test flips red with >1 call count — cheap signal for an expensive
 * regression.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { ContributorsList } from '../ContributorsList'
import { DashboardHero } from '../DashboardHero'
import { GroupsMiniList } from '../GroupsMiniList'
import { KPIStrip } from '../KPIStrip'
import { MotivationDonut } from '../MotivationDonut'
import { SectorBreakdown } from '../SectorBreakdown'
import { YearBar } from '../YearBar'

const SUMMARY_BODY = {
  total_reports: 10,
  total_incidents: 5,
  total_actors: 3,
  reports_by_year: [{ year: 2026, count: 10 }],
  incidents_by_motivation: [{ motivation: 'financial', count: 3 }],
  top_groups: [
    { group_id: 1, name: 'Lazarus Group', report_count: 3 },
  ],
  top_sectors: [],
  top_sources: [],
}

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    // GroupsMiniList uses <Link> since PR #14 D11 cross-link.
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
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

afterEach(() => {
  vi.restoreAllMocks()
})

describe('dashboard summary shared cache', () => {
  it('mounting all seven summary subscribers fires ONE /dashboard/summary request', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(SUMMARY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()

    render(
      <>
        <DashboardHero />
        <KPIStrip />
        <MotivationDonut />
        <YearBar />
        <GroupsMiniList />
        <SectorBreakdown />
        <ContributorsList />
      </>,
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const summaryCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/dashboard/summary'),
    )
    // Seven subscribers, one shared cache key → ONE fetch. If this
    // climbs to 2+, one of the components bypassed
    // useDashboardSummary.
    expect(summaryCalls).toHaveLength(1)
  })
})
