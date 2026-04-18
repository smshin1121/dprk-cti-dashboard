/**
 * Plan D9 review invariant (PR #13 Group H → extended in Group I):
 * mounting every dashboard panel that is backed by
 * `useDashboardSummary()` fires ONE /dashboard/summary request, not
 * N. React Query's cache key is shared across subscribers with
 * identical filters, so every subscriber to `useDashboardSummary()`
 * shares one query.
 *
 * Group H pinned: KPIStrip + MotivationDonut + YearBar (3 panels).
 * Group I adds: GroupsMiniList (4th panel on the same hook).
 *
 * If a future edit switches any of these components to a bespoke
 * hook (or forgets to route through `useDashboardSummary`), this
 * test flips red with >1 call count — cheap signal for an expensive
 * regression.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { GroupsMiniList } from '../GroupsMiniList'
import { KPIStrip } from '../KPIStrip'
import { MotivationDonut } from '../MotivationDonut'
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
}

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
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
  it('mounting KPIStrip + MotivationDonut + YearBar + GroupsMiniList fires ONE /dashboard/summary request', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(SUMMARY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()

    render(
      <>
        <KPIStrip />
        <MotivationDonut />
        <YearBar />
        <GroupsMiniList />
      </>,
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const summaryCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/dashboard/summary'),
    )
    // Four subscribers, one shared cache key → ONE fetch. If this
    // climbs to 2+, one of the components bypassed useDashboardSummary.
    expect(summaryCalls).toHaveLength(1)
  })
})
