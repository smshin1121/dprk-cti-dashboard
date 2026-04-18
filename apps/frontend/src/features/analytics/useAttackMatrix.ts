/**
 * `/api/v1/analytics/attack_matrix` React Query hook.
 *
 * Subscription discipline (plan D4 + D9; carries PR #12 Group E
 * pattern):
 *   Primitive selectors for `dateFrom` / `dateTo` / `groupIds` only.
 *   TLP lives in the same store but is UI-only — a TLP toggle MUST
 *   NOT refetch this hook. `AnalyticsFilters` has no tlp field by
 *   construction, so the invariant is pinned at the type layer as
 *   well as at runtime (see `useAttackMatrix.test.tsx`).
 *
 * `top_n` is a hook argument (caller-configurable per viz instance,
 * not global filter state). It participates in the query key so
 * changing it refetches without colliding with the global filter
 * cache.
 *
 * Refetch policy mirrors `useDashboardSummary` (staleTime 30s). Errors
 * surface immediately for D11 inline-error rendering; a failing matrix
 * fetch does not take down sibling viz panels.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import {
  type AnalyticsFilters,
  type AttackMatrixOptions,
  toAnalyticsFilters,
} from '../../lib/analyticsFilters'
import { getAttackMatrix } from '../../lib/api/endpoints'
import type { AttackMatrixResponse } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

export function useAttackMatrix(options: AttackMatrixOptions = {}) {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const groupIds = useFilterStore((s) => s.groupIds)

  const filters: AnalyticsFilters = useMemo(
    () => toAnalyticsFilters({ dateFrom, dateTo, groupIds }),
    [dateFrom, dateTo, groupIds],
  )

  return useQuery<AttackMatrixResponse>({
    queryKey: queryKeys.analyticsAttackMatrix(filters, options),
    queryFn: ({ signal }) => getAttackMatrix(filters, options, signal),
    staleTime: 30_000,
  })
}
