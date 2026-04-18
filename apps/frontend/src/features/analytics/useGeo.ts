/**
 * `/api/v1/analytics/geo` React Query hook.
 *
 * Same subscription discipline as `useAttackMatrix` / `useTrend` —
 * primitive selectors for `dateFrom` / `dateTo` / `groupIds`, no TLP.
 *
 * Note: plan D2 documents `group_id[]` as a BE no-op for this endpoint
 * (the schema has no incident→group path), but we still subscribe to
 * groupIds here for two reasons:
 *   1. Filter contract uniformity — a future BE change wiring the
 *      filter doesn't require a FE change.
 *   2. Cache key stability — the same groupIds state must always
 *      produce the same cache key regardless of the BE's current
 *      semantics; otherwise an FE-side "optimization" (subscribing
 *      only to dateFrom/dateTo for this hook) would desync from the
 *      other two analytics hooks' cache scopes.
 *
 * Empty payload (`{countries: []}`) parses successfully — the viz
 * renders its empty-state card per plan D8.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import {
  type AnalyticsFilters,
  toAnalyticsFilters,
} from '../../lib/analyticsFilters'
import { getGeo } from '../../lib/api/endpoints'
import type { GeoResponse } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

export function useGeo() {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const groupIds = useFilterStore((s) => s.groupIds)

  const filters: AnalyticsFilters = useMemo(
    () => toAnalyticsFilters({ dateFrom, dateTo, groupIds }),
    [dateFrom, dateTo, groupIds],
  )

  return useQuery<GeoResponse>({
    queryKey: queryKeys.analyticsGeo(filters),
    queryFn: ({ signal }) => getGeo(filters, signal),
    staleTime: 30_000,
  })
}
