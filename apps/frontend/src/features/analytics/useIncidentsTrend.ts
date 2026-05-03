/**
 * `/api/v1/analytics/incidents_trend` React Query hook — PR #23 §6.A C1.
 *
 * Mirror of `useTrend` on the incidents fact table with a required
 * `groupBy` axis. Cache key carries the axis so motivation and sector
 * subscribers occupy separate slots — the two stacked-area widgets
 * (`MotivationStackedArea` C7 + `SectorStackedArea` C8) MUST NOT
 * share a cache entry.
 *
 * Same subscription discipline as `useTrend` — primitive selectors
 * for `dateFrom` / `dateTo` / `groupIds`, no TLP. The
 * `AnalyticsFilters` type has no tlp field by construction.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import {
  type AnalyticsFilters,
  type IncidentsTrendGroupBy,
  toAnalyticsFilters,
} from '../../lib/analyticsFilters'
import { getIncidentsTrend } from '../../lib/api/endpoints'
import type { IncidentsTrendResponse } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

interface UseIncidentsTrendOptions {
  groupBy: IncidentsTrendGroupBy
}

export function useIncidentsTrend({ groupBy }: UseIncidentsTrendOptions) {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const groupIds = useFilterStore((s) => s.groupIds)

  const filters: AnalyticsFilters = useMemo(
    () => toAnalyticsFilters({ dateFrom, dateTo, groupIds }),
    [dateFrom, dateTo, groupIds],
  )

  return useQuery<IncidentsTrendResponse>({
    queryKey: queryKeys.analyticsIncidentsTrend(filters, groupBy),
    queryFn: ({ signal }) => getIncidentsTrend(filters, groupBy, signal),
    staleTime: 30_000,
  })
}
