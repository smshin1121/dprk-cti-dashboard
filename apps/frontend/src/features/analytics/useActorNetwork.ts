/**
 * `/api/v1/analytics/actor_network` React Query hook.
 *
 * Plan ``docs/plans/actor-network-data.md`` v1.6 L2 + L5 + T9:
 *   primitive `useFilterStore` selectors for `dateFrom` / `dateTo` /
 *   `groupIds`; per-instance `top_n_actor` / `top_n_tool` /
 *   `top_n_sector` options; `staleTime: 30_000` mirroring sibling
 *   analytics hooks; **isolated cache slot** — does NOT subscribe to
 *   the dashboard-summary shared cache (plan §7 AC #6 + memory
 *   `pattern_shared_cache_test_extension`).
 *
 * Subscription discipline (plan D4 + D9; carries PR #12 Group E
 * pattern):
 *   Primitive selectors for `dateFrom` / `dateTo` / `groupIds` only.
 *   TLP lives in the same store but is UI-only — a TLP toggle MUST
 *   NOT refetch this hook. `AnalyticsFilters` has no tlp field by
 *   construction, so the invariant is pinned at the type layer as
 *   well as at runtime (see `useActorNetwork.test.tsx`).
 *
 * Each per-kind cap (`top_n_actor` / `top_n_tool` / `top_n_sector`)
 * participates in the query key independently, so changing any one
 * opens a new cache scope without colliding with the global filter
 * cache.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import {
  type ActorNetworkOptions,
  type AnalyticsFilters,
  toAnalyticsFilters,
} from '../../lib/analyticsFilters'
import { getActorNetwork } from '../../lib/api/endpoints'
import type { ActorNetworkResponse } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

// Re-export the options type so existing callers/tests that import
// from this module keep compiling without breakage. Canonical home
// is `lib/analyticsFilters.ts`.
export type { ActorNetworkOptions } from '../../lib/analyticsFilters'

export function useActorNetwork(options: ActorNetworkOptions = {}) {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const groupIds = useFilterStore((s) => s.groupIds)

  const filters: AnalyticsFilters = useMemo(
    () => toAnalyticsFilters({ dateFrom, dateTo, groupIds }),
    [dateFrom, dateTo, groupIds],
  )

  return useQuery<ActorNetworkResponse>({
    queryKey: queryKeys.analyticsActorNetwork(filters, options),
    queryFn: ({ signal }) => getActorNetwork(filters, options, signal),
    staleTime: 30_000,
  })
}
