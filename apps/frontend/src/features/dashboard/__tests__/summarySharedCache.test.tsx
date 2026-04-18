/**
 * Plan D9 review invariant (PR #13 Group H): mounting KPIStrip +
 * MotivationDonut + YearBar together fires ONE /dashboard/summary
 * request, not three. React Query's cache key is shared across
 * subscribers with identical filters, so three subscribers to
 * `useDashboardSummary()` share one query.
 *
 * If a future edit switches any of these components to a bespoke
 * hook (or forgets to route through `useDashboardSummary`), this
 * test flips red with a 3-call spy — cheap signal for an expensive
 * regression.
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
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
  it('mounting KPIStrip + MotivationDonut + YearBar fires ONE /dashboard/summary request', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()

    render(
      <>
        <KPIStrip />
        <MotivationDonut />
        <YearBar />
      </>,
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const summaryCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/api/v1/dashboard/summary'),
    )
    // Three components, one shared cache key → ONE fetch. If this
    // is 2 or 3, one of the components bypassed useDashboardSummary.
    expect(summaryCalls).toHaveLength(1)
  })
})
