/**
 * `/api/v1/analytics/trend` React Query hook.
 *
 * Same subscription discipline as `useAttackMatrix` — primitive
 * selectors for `dateFrom` / `dateTo` / `groupIds`, no TLP. The
 * `AnalyticsFilters` type has no tlp field by construction.
 *
 * Response shape forwards the BE wire verbatim; zero-count months
 * are omitted server-side so the viz decides gap-fill semantics.
 * Empty payload (`{buckets: []}`) parses successfully — the viz
 * renders the empty-state card per plan D8.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import {
  type AnalyticsFilters,
  toAnalyticsFilters,
} from '../../lib/analyticsFilters'
import { getTrend } from '../../lib/api/endpoints'
import type { TrendResponse } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

export function useTrend() {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const groupIds = useFilterStore((s) => s.groupIds)

  const filters: AnalyticsFilters = useMemo(
    () => toAnalyticsFilters({ dateFrom, dateTo, groupIds }),
    [dateFrom, dateTo, groupIds],
  )

  return useQuery<TrendResponse>({
    queryKey: queryKeys.analyticsTrend(filters),
    queryFn: ({ signal }) => getTrend(filters, signal),
    staleTime: 30_000,
  })
}
